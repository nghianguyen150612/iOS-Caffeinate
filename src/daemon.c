/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L
#include "power.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define MAX_DURATION_SECONDS 86400
static volatile sig_atomic_t keep_running = 1;
static bool holding, release_pending, clock_failed;
static uint32_t held_id;
static double deadline, retry_at;
static const char *socket_path = DEFAULT_SOCKET;

/* CLOCK_MONOTONIC is available since iOS 10; wall clock changes must not
 * extend or prematurely end a bounded hardware test. */
static double now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        clock_failed = true;
        keep_running = 0;
        return 0;
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}
static void on_signal(int sig) { (void)sig; keep_running = 0; }

static int clear_hold(char *error, size_t cap) {
    if (!holding) return 0;
    if (power_release(held_id, error, cap) != 0) {
        fprintf(stderr, "ERROR releasing assertion %u: %s; %s\n", held_id, error, power_diagnostics());
        release_pending = true;
        retry_at = now() + 1;
        return -1;
    }
    fprintf(stderr, "Released assertion %u; %s\n", held_id, power_diagnostics());
    holding = release_pending = false;
    held_id = 0;
    deadline = 0;
    return 0;
}
static void expire_if_due(void) {
    double t = now();
    if (holding && ((release_pending && t >= retry_at) || (!release_pending && t >= deadline))) {
        char error[256];
        (void)clear_hold(error, sizeof(error));
    }
}

/* A stable sidecar lock serializes stale detection, bind and listen. Never
 * unlink it: another process may already have the same inode open. */
static int lock_socket_path(const char *path) {
    char lock_path[sizeof(((struct sockaddr_un *)0)->sun_path) + 6];
    snprintf(lock_path, sizeof(lock_path), "%s.lock", path);
    int fd = open(lock_path, O_CREAT | O_RDWR | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (fd < 0) { perror("open socket lock"); return -1; }
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        st.st_nlink != 1 || (st.st_mode & 0777) != 0600 || flock(fd, LOCK_EX | LOCK_NB) != 0) {
        fprintf(stderr, "Socket lock unsafe or daemon already running: %s\n", lock_path);
        close(fd);
        return -1;
    }
    return fd;
}
static int prepare_socket(const char *path) {
    struct stat st;
    if (lstat(path, &st) == 0) {
        if (!S_ISSOCK(st.st_mode) || st.st_uid != geteuid()) {
            fprintf(stderr, "Refusing to delete non-owned or non-socket path: %s\n", path);
            return -1;
        }
        int test_fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (test_fd < 0) return -1;
        if (fcntl(test_fd, F_SETFL, O_NONBLOCK) != 0) { close(test_fd); return -1; }
        struct sockaddr_un addr = {0};
        addr.sun_family = AF_UNIX;
        snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
        int connected = connect(test_fd, (struct sockaddr *)&addr, sizeof(addr));
        int saved_errno = errno;
        close(test_fd);
        if (connected == 0 || saved_errno != ECONNREFUSED) {
            fprintf(stderr, "Socket appears active or unsafe to replace: %s\n", path);
            return -1;
        }
        if (unlink(path) != 0) { perror("unlink stale socket"); return -1; }
    } else if (errno != ENOENT) { perror("lstat socket"); return -1; }
    return 0;
}
static int remove_owned_socket(const struct stat *bound) {
    struct stat st;
    if (lstat(socket_path, &st) == 0 && S_ISSOCK(st.st_mode) &&
        st.st_dev == bound->st_dev && st.st_ino == bound->st_ino) {
        if (unlink(socket_path) != 0) { perror("unlink socket"); return -1; }
    }
    return 0;
}
static int respond(int fd, const char *message) {
    size_t len = strlen(message);
    while (len && keep_running) {
        ssize_t n = send(fd, message, len, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        message += n;
        len -= (size_t)n;
    }
    return len ? -1 : 0;
}
static void reply_error(int fd, const char *operation, const char *error) {
    char out[1024];
    snprintf(out, sizeof(out), "ERR %s: %s backend=%s type=PreventUserIdleSystemSleep %s\n",
             operation, error, power_backend_name(), power_diagnostics());
    respond(fd, out);
}

/* Newline-terminated ASCII, one frame per connection, 127 bytes maximum.
 * Bound the whole read, not each fragment, to prevent a slow client from
 * delaying expiry or graceful shutdown. Reject NUL, CR and queued extra data. */
static int read_command(int fd, char *command, size_t cap) {
    size_t used = 0;
    double until = now() + 1;
    while (keep_running && now() < until) {
        expire_if_due();
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int rc = poll(&pfd, 1, 50);
        if (rc < 0 && errno == EINTR) continue;
        if (rc < 0) return -1;
        if (rc == 0) continue;
        ssize_t n = recv(fd, command + used, cap - 1 - used, MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) break;
        size_t total = used + (size_t)n;
        for (size_t i = used; i < total; ++i) {
            unsigned char c = (unsigned char)command[i];
            if (c == '\n') {
                if (i + 1 != total) goto malformed;
                command[i] = '\0';
                return 0;
            }
            if (c < 32 || c > 126) goto malformed;
        }
        used = total;
        if (used == cap - 1) goto malformed;
    }
malformed:
    respond(fd, "ERR malformed or incomplete command\n");
    return -1;
}
static void handle_client(int fd) {
    struct timeval tv = {.tv_sec = 1, .tv_usec = 0};
    if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)) != 0) return;
    char command[128];
    if (read_command(fd, command, sizeof(command)) != 0 || !keep_running) return;
    expire_if_due();
    if (strcmp(command, "STATUS") == 0) {
        char out[1024];
        double left = holding ? deadline - now() : 0;
        unsigned remaining = left > 0 ? (unsigned)left + 1 : 0;
        snprintf(out, sizeof(out), "OK active=%s remaining_seconds=%u assertion_id=%u release_pending=%s backend=%s type=PreventUserIdleSystemSleep %s\n",
                 holding ? "yes" : "no", remaining, held_id, release_pending ? "yes" : "no",
                 power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "PROBE") == 0) {
        if (holding) { respond(fd, "ERR already active; stop before probing\n"); return; }
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            reply_error(fd, "acquire", error); held_id = 0; return;
        }
        /* Track even the probe until release succeeds, so failure can be
         * reported and retried by expiry, STOP and shutdown. */
        holding = true;
        deadline = now();
        uint32_t probe_id = held_id;
        if (clear_hold(error, sizeof(error)) != 0) {
            reply_error(fd, "release", error); return;
        }
        char out[1024];
        snprintf(out, sizeof(out), "OK probe=acquire_release assertion_id=%u backend=%s type=PreventUserIdleSystemSleep %s\n",
                 probe_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strncmp(command, "START ", 6) == 0) {
        const char *value = command + 6;
        if (*value < '0' || *value > '9') { respond(fd, "ERR invalid duration\n"); return; }
        errno = 0;
        char *end = NULL;
        unsigned long long duration = strtoull(value, &end, 10);
        if (errno || *end || duration == 0 || duration > MAX_DURATION_SECONDS) {
            respond(fd, "ERR duration must be 1..86400 seconds\n"); return;
        }
        if (holding) { respond(fd, "ERR already active; stop before restarting\n"); return; }
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            reply_error(fd, "acquire", error); held_id = 0; return;
        }
        holding = true;
        deadline = now() + (double)duration;
        fprintf(stderr, "Acquired assertion %u for %llu seconds; %s\n", held_id, duration, power_diagnostics());
        char out[1024];
        snprintf(out, sizeof(out), "OK active=yes duration_seconds=%llu assertion_id=%u backend=%s %s\n",
                 duration, held_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "STOP") == 0) {
        char error[256] = {0};
        if (!holding) respond(fd, "OK already_stopped=yes\n");
        else if (clear_hold(error, sizeof(error)) != 0) reply_error(fd, "release", error);
        else respond(fd, "OK active=no release_rc=0x00000000\n");
    } else respond(fd, "ERR unknown command\n");
}
static void usage(const char *exe) {
    fprintf(stderr, "Usage: %s [--socket /absolute/path.sock] [--foreground]\n", exe);
}
int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--foreground") == 0) continue;
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) socket_path = argv[++i];
        else { usage(argv[0]); return 2; }
    }
    if (*socket_path != '/' || strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Socket path must be absolute and fit sockaddr_un\n"); return 2;
    }
    if (strcmp(socket_path, DEFAULT_SOCKET) == 0 && geteuid() != 0) {
        fprintf(stderr, "Default socket requires root; use a private --socket directory for tests\n"); return 1;
    }
    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGTERM, &sa, NULL) != 0 || sigaction(SIGINT, &sa, NULL) != 0 ||
        signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("signal setup"); return 1; }
    umask(0077);
    int lock_fd = lock_socket_path(socket_path);
    if (lock_fd < 0) return 1;
    if (prepare_socket(socket_path) != 0) { close(lock_fd); return 1; }
    int listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (listen_fd < 0) { perror("socket"); close(lock_fd); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", socket_path);
    if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("bind"); close(listen_fd); close(lock_fd); return 1;
    }
    struct stat bound;
    if (lstat(socket_path, &bound) != 0) {
        perror("lstat bound socket"); close(listen_fd); close(lock_fd); return 1;
    }
    int result = 0;
    if (chmod(socket_path, 0600) != 0 || listen(listen_fd, 8) != 0) {
        perror("chmod/listen"); result = 1; goto cleanup;
    }
    fprintf(stderr, "ios-caffeinated starting: socket=%s backend=%s\n", socket_path, power_backend_name());
    while (keep_running) {
        expire_if_due();
        struct pollfd pfd = {.fd = listen_fd, .events = POLLIN};
        int ret = poll(&pfd, 1, 100);
        if (ret < 0) {
            if (errno == EINTR) continue;
            perror("poll"); result = 1; break;
        }
        if (ret > 0 && (pfd.revents & POLLIN)) {
            int client = accept(listen_fd, NULL, NULL);
            if (client >= 0) { handle_client(client); close(client); }
            else if (errno != EINTR) { perror("accept"); result = 1; break; }
        }
    }
cleanup:;
    char error[256] = {0};
    if (clear_hold(error, sizeof(error)) != 0) {
        fprintf(stderr, "UNRESOLVED assertion release at exit; device verification required\n");
        result = 1;
    }
    close(listen_fd);
    if (remove_owned_socket(&bound) != 0 || clock_failed) result = 1;
    close(lock_fd);
    power_cleanup();
    return result;
}
