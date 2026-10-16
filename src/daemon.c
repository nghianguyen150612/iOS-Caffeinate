#define _POSIX_C_SOURCE 200809L
#include "power.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define MAX_DURATION_SECONDS (24 * 60 * 60) /* P001: no permanent holds */
static volatile sig_atomic_t keep_running = 1;
static bool holding = false;
static uint32_t held_id = 0;
static time_t deadline = 0;
static int listen_fd = -1;
static const char *socket_path = DEFAULT_SOCKET;

static void on_signal(int sig) {
    (void)sig;
    keep_running = 0;
}

static void clear_hold(void) {
    if (!holding) return;
    char error[256] = {0};
    if (power_release(held_id, error, sizeof(error)) != 0) {
        fprintf(stderr, "ERROR releasing assertion %u: %s\n", held_id, error);
    } else {
        fprintf(stderr, "Released assertion %u\n", held_id);
    }
    holding = false;
    held_id = 0;
    deadline = 0;
}

static void expire_if_due(void) {
    if (holding && deadline && time(NULL) >= deadline) clear_hold();
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
        struct sockaddr_un check_addr = {0};
        check_addr.sun_family = AF_UNIX;
        snprintf(check_addr.sun_path, sizeof(check_addr.sun_path), "%s", path);
        int connected = connect(test_fd, (struct sockaddr *)&check_addr, sizeof(check_addr));
        int conn_errno = errno;
        close(test_fd);
        if (connected == 0 || conn_errno != ECONNREFUSED) {
            fprintf(stderr, "Socket appears active or unsafe to replace: %s\n", path);
            return -1;
        }
        if (unlink(path) != 0) { perror("unlink stale socket"); return -1; }
    } else if (errno != ENOENT) {
        perror("lstat socket");
        return -1;
    }
    return 0;
}

static int respond(int fd, const char *message) {
    size_t len = strlen(message);
    while (len) {
        ssize_t n = send(fd, message, len, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        message += n;
        len -= (size_t)n;
    }
    return 0;
}

static void handle_client(int fd) {
    struct timeval tv = {.tv_sec = 2, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    char command[128] = {0};
    ssize_t n = recv(fd, command, sizeof(command) - 1, 0);
    if (n <= 0) return;
    command[n] = '\0';
    char *eol = strpbrk(command, "\r\n");
    if (eol) *eol = '\0';
    expire_if_due();

    if (strcmp(command, "STATUS") == 0) {
        char out[256];
        long long remaining = holding ? (long long)(deadline - time(NULL)) : 0;
        if (remaining < 0) remaining = 0;
        snprintf(out, sizeof(out), "OK active=%s remaining_seconds=%lld backend=%s\n",
                 holding ? "yes" : "no", remaining, power_backend_name());
        respond(fd, out);
    } else if (strcmp(command, "PROBE") == 0) {
        char error[256] = {0};
        uint32_t probe_id = 0;
        if (power_acquire(&probe_id, error, sizeof(error)) != 0) {
            char out[320];
            snprintf(out, sizeof(out), "ERR acquire: %s\n", error);
            respond(fd, out);
            return;
        }
        if (power_release(probe_id, error, sizeof(error)) != 0) {
            char out[320];
            snprintf(out, sizeof(out), "ERR release: %s\n", error);
            respond(fd, out);
            return;
        }
        char out[160];
        snprintf(out, sizeof(out), "OK probe=acquire_release backend=%s\n", power_backend_name());
        respond(fd, out);
    } else if (strncmp(command, "START ", 6) == 0) {
        const char *value = command + 6;
        if (*value < '0' || *value > '9') {
            respond(fd, "ERR invalid duration\n");
            return;
        }
        errno = 0;
        char *end = NULL;
        unsigned long long duration = strtoull(value, &end, 10);
        if (errno != 0 || !end || *end != '\0' || duration == 0 ||
            duration > MAX_DURATION_SECONDS) {
            respond(fd, "ERR duration must be 1..86400 seconds\n");
            return;
        }
        if (holding) {
            respond(fd, "ERR already active; stop before restarting\n");
            return;
        }
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            char out[320];
            snprintf(out, sizeof(out), "ERR acquire: %s\n", error);
            respond(fd, out);
            return;
        }
        holding = true;
        deadline = time(NULL) + (time_t)duration;
        fprintf(stderr, "Acquired assertion %u for %llu seconds\n", held_id, duration);
        char out[160];
        snprintf(out, sizeof(out), "OK active=yes duration_seconds=%llu backend=%s\n",
                 duration, power_backend_name());
        respond(fd, out);
    } else if (strcmp(command, "STOP") == 0) {
        if (!holding) {
            respond(fd, "OK already_stopped=yes\n");
        } else {
            clear_hold();
            respond(fd, "OK active=no\n");
        }
    } else {
        respond(fd, "ERR unknown command\n");
    }
}

static void usage(const char *exe) {
    fprintf(stderr, "Usage: %s [--socket /absolute/path.sock] [--foreground]\n", exe);
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--foreground") == 0) continue;
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        } else {
            usage(argv[0]);
            return 2;
        }
    }
    if (*socket_path != '/' || strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Socket path must be absolute and fit sockaddr_un\n");
        return 2;
    }
    umask(0077);
    if (prepare_socket(socket_path) != 0) return 1;
    listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (listen_fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", socket_path);
    if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("bind");
        close(listen_fd);
        return 1;
    }
    if (chmod(socket_path, S_IRUSR | S_IWUSR) != 0 || listen(listen_fd, 8) != 0) {
        perror("chmod/listen");
        close(listen_fd);
        unlink(socket_path);
        return 1;
    }
    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);
    fprintf(stderr, "ioscaffeinated starting: socket=%s backend=%s\n", socket_path, power_backend_name());
    while (keep_running) {
        expire_if_due();
        struct pollfd pfd = {.fd = listen_fd, .events = POLLIN};
        int ms = 250;
        if (holding) {
            time_t remaining = deadline - time(NULL);
            if (remaining < 1) { expire_if_due(); continue; }
            if (remaining == 1) ms = 200;
        }
        int ret = poll(&pfd, 1, ms);
        if (ret < 0) {
            if (errno == EINTR) continue;
            perror("poll");
            break;
        }
        if (ret > 0 && (pfd.revents & POLLIN)) {
            int client = accept(listen_fd, NULL, NULL);
            if (client >= 0) { handle_client(client); close(client); }
            else if (errno != EINTR) perror("accept");
        }
    }
    clear_hold();
    close(listen_fd);
    unlink(socket_path);
    power_cleanup();
    return 0;
}
