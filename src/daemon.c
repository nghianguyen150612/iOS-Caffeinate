/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L
#include "power.h"
#include "schedule.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define MAX_DURATION_SECONDS 86400

typedef enum {
    DAEMON_STATE_IDLE = 0,
    DAEMON_STATE_ACQUIRING,
    DAEMON_STATE_ACTIVE,
    DAEMON_STATE_RELEASING,
    DAEMON_STATE_RELEASE_FAILED,
    DAEMON_STATE_SHUTTING_DOWN
} daemon_state_t;

static volatile sig_atomic_t keep_running = 1;
static daemon_state_t daemon_state = DAEMON_STATE_IDLE;
static bool clock_failed;
static uint32_t held_id;
static double deadline, retry_at;
static const char *socket_path = DEFAULT_SOCKET;
static const char *schedule_file_path = NULL;

static schedule_store_t sched_store;
static int current_active_sched_idx = -1;

static const char *daemon_state_name(daemon_state_t s) {
    switch (s) {
        case DAEMON_STATE_IDLE: return "IDLE";
        case DAEMON_STATE_ACQUIRING: return "ACQUIRING";
        case DAEMON_STATE_ACTIVE: return "ACTIVE";
        case DAEMON_STATE_RELEASING: return "RELEASING";
        case DAEMON_STATE_RELEASE_FAILED: return "RELEASE_FAILED";
        case DAEMON_STATE_SHUTTING_DOWN: return "SHUTTING_DOWN";
    }
    return "UNKNOWN";
}

static void log_msg(const char *level, const char *fmt, ...) {
    time_t raw = time(NULL);
    struct tm tm_buf;
    struct tm *tm_info = localtime_r(&raw, &tm_buf);
    char time_str[32] = {0};
    if (tm_info) {
        strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", tm_info);
    } else {
        snprintf(time_str, sizeof(time_str), "0000-00-00 00:00:00");
    }
    fprintf(stderr, "[%s] [%s] ", time_str, level);
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
}

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

static void on_signal(int sig) {
    (void)sig;
    keep_running = 0;
}

static bool is_holding(void) {
    return held_id != 0;
}

static bool is_release_pending(void) {
    return daemon_state == DAEMON_STATE_RELEASING ||
           daemon_state == DAEMON_STATE_RELEASE_FAILED;
}

static int clear_hold(char *error, size_t cap) {
    if (held_id == 0) return 0;
    daemon_state = DAEMON_STATE_RELEASING;
    if (power_release(held_id, error, cap) != 0) {
        daemon_state = DAEMON_STATE_RELEASE_FAILED;
        retry_at = now() + 1.0;
        log_msg("ERROR", "Releasing assertion %u failed: %s; %s", held_id, error, power_diagnostics());
        return -1;
    }
    log_msg("INFO", "Released assertion %u; %s", held_id, power_diagnostics());
    daemon_state = DAEMON_STATE_IDLE;
    held_id = 0;
    deadline = 0;
    retry_at = 0;
    current_active_sched_idx = -1;
    return 0;
}

static void expire_if_due(void) {
    double t = now();
    if (held_id != 0) {
        if (daemon_state == DAEMON_STATE_ACTIVE && t >= deadline) {
            char error[256];
            log_msg("INFO", "Assertion %u deadline reached; expiring hold", held_id);
            (void)clear_hold(error, sizeof(error));
        } else if (daemon_state == DAEMON_STATE_RELEASE_FAILED && t >= retry_at) {
            char error[256];
            log_msg("WARN", "Retrying release for assertion %u", held_id);
            (void)clear_hold(error, sizeof(error));
        }
    }
}

static void check_and_trigger_schedules(void) {
    if (is_holding() || is_release_pending()) return;

    time_t now_wall = time(NULL);
    int active_idx = -1;
    uint32_t active_remaining = 0;
    int next_idx = -1;
    time_t next_start = 0;

    schedule_store_evaluate(&sched_store, now_wall, &active_idx, &active_remaining, &next_idx, &next_start);

    if (active_idx >= 0 && active_remaining > 0) {
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            log_msg("ERROR", "Failed to acquire scheduled hold for schedule %s: %s",
                    sched_store.items[active_idx].id, error);
            held_id = 0;
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now() + (double)active_remaining;
        current_active_sched_idx = active_idx;
        schedule_mark_fired(&sched_store, active_idx, now_wall - (sched_store.items[active_idx].duration - active_remaining));
        log_msg("INFO", "Triggered schedule %s: acquired assertion %u for remaining %u seconds",
                sched_store.items[active_idx].id, held_id, active_remaining);
    }
}

static int check_peer_euid(int fd, uid_t *peer_euid) {
#if defined(__APPLE__)
    gid_t egid;
    if (getpeereid(fd, peer_euid, &egid) == 0) return 0;
    return -1;
#elif defined(__linux__)
    struct ucred cred;
    socklen_t len = sizeof(cred);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cred, &len) == 0) {
        *peer_euid = cred.uid;
        return 0;
    }
    return -1;
#else
    (void)fd; (void)peer_euid;
    return -1;
#endif
}

static int lock_socket_path(const char *path) {
    char lock_path[sizeof(((struct sockaddr_un *)0)->sun_path) + 6];
    snprintf(lock_path, sizeof(lock_path), "%s.lock", path);
    int fd = open(lock_path, O_CREAT | O_RDWR | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (fd < 0) { perror("open socket lock"); return -1; }
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        st.st_nlink != 1 || (st.st_mode & 0777) != 0600 || flock(fd, LOCK_EX | LOCK_NB) != 0) {
        log_msg("ERROR", "Socket lock unsafe or daemon already running: %s", lock_path);
        close(fd);
        return -1;
    }
    return fd;
}

static int prepare_socket(const char *path) {
    struct stat st;
    if (lstat(path, &st) == 0) {
        if (!S_ISSOCK(st.st_mode) || st.st_uid != geteuid()) {
            log_msg("ERROR", "Refusing to delete non-owned or non-socket path: %s", path);
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
            log_msg("ERROR", "Socket appears active or unsafe to replace: %s", path);
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

static int read_command(int fd, char *command, size_t cap) {
    size_t used = 0;
    double until = now() + 1.0;
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

    uid_t peer_uid = (uid_t)-1;
    if (check_peer_euid(fd, &peer_uid) != 0) {
        log_msg("WARN", "Rejecting client connection: unable to verify peer credentials");
        respond(fd, "ERR permission denied: unable to verify peer credentials\n");
        return;
    }

    uid_t required_uid = (strcmp(socket_path, DEFAULT_SOCKET) == 0) ? 0 : geteuid();
    if (peer_uid != required_uid) {
        log_msg("WARN", "Rejecting client connection: peer UID %u != required UID %u",
                (unsigned)peer_uid, (unsigned)required_uid);
        respond(fd, "ERR permission denied: unauthorized client UID\n");
        return;
    }

    char command[512];
    if (read_command(fd, command, sizeof(command)) != 0 || !keep_running) return;
    expire_if_due();

    if (strcmp(command, "STATUS") == 0) {
        char out[1024];
        double left = (daemon_state == DAEMON_STATE_ACTIVE) ? (deadline - now()) : 0;
        unsigned remaining = left > 0 ? (unsigned)left + 1 : 0;
        snprintf(out, sizeof(out), "OK active=%s state=%s remaining_seconds=%u assertion_id=%u release_pending=%s schedule_count=%zu backend=%s type=PreventUserIdleSystemSleep %s\n",
                 is_holding() ? "yes" : "no", daemon_state_name(daemon_state),
                 remaining, held_id, is_release_pending() ? "yes" : "no",
                 sched_store.count,
                 power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "PROBE") == 0) {
        if (is_holding()) {
            respond(fd, "ERR already active; stop before probing\n");
            return;
        }
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            reply_error(fd, "acquire", error);
            held_id = 0;
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now();
        uint32_t probe_id = held_id;
        if (clear_hold(error, sizeof(error)) != 0) {
            reply_error(fd, "release", error);
            return;
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
        if (is_holding()) {
            respond(fd, "ERR already active; stop before restarting\n");
            return;
        }
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            reply_error(fd, "acquire", error);
            held_id = 0;
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now() + (double)duration;
        current_active_sched_idx = -1;
        log_msg("INFO", "Acquired assertion %u for %llu seconds; %s", held_id, duration, power_diagnostics());
        char out[1024];
        snprintf(out, sizeof(out), "OK active=yes duration_seconds=%llu assertion_id=%u backend=%s %s\n",
                 duration, held_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "STOP") == 0) {
        char error[256] = {0};
        if (!is_holding()) respond(fd, "OK already_stopped=yes\n");
        else if (clear_hold(error, sizeof(error)) != 0) reply_error(fd, "release", error);
        else respond(fd, "OK active=no release_rc=0x00000000\n");
    } else if (strcmp(command, "SCHEDULE LIST") == 0) {
        char out[2048] = "OK schedules=";
        char item_str[256];
        snprintf(out + strlen(out), sizeof(out) - strlen(out), "%zu\n", sched_store.count);
        for (size_t i = 0; i < sched_store.count; ++i) {
            const schedule_t *s = &sched_store.items[i];
            if (s->type == SCHED_TYPE_ONETIME) {
                char iso_time[32] = {0};
                format_iso8601_utc(s->target_time, iso_time, sizeof(iso_time));
                snprintf(item_str, sizeof(item_str), "  id=%s type=onetime target=%s duration=%us\n",
                         s->id, iso_time, s->duration);
            } else if (s->type == SCHED_TYPE_DAILY) {
                snprintf(item_str, sizeof(item_str), "  id=%s type=daily time=%02d:%02d duration=%us tz=%s\n",
                         s->id, s->hour, s->minute, s->duration, s->tz[0] ? s->tz : "system");
            } else if (s->type == SCHED_TYPE_WEEKLY) {
                snprintf(item_str, sizeof(item_str), "  id=%s type=weekly days_mask=0x%02x time=%02d:%02d duration=%us tz=%s\n",
                         s->id, (unsigned)s->days_mask, s->hour, s->minute, s->duration, s->tz[0] ? s->tz : "system");
            }
            strncat(out, item_str, sizeof(out) - strlen(out) - 1);
        }
        respond(fd, out);
    } else if (strncmp(command, "SCHEDULE REMOVE ", 16) == 0) {
        const char *id = command + 16;
        char err_buf[256] = {0};
        if (schedule_store_remove(&sched_store, id, err_buf, sizeof(err_buf)) != 0) {
            reply_error(fd, "schedule remove", err_buf);
        } else {
            respond(fd, "OK schedule_removed=yes\n");
        }
    } else if (strncmp(command, "SCHEDULE ADD ", 13) == 0) {
        const char *sub = command + 13;
        char err_buf[256] = {0};
        schedule_t item;
        memset(&item, 0, sizeof(item));

        if (strncmp(sub, "ONETIME ", 8) == 0) {
            long long target_time = 0;
            unsigned duration = 0;
            if (sscanf(sub + 8, "%lld %u", &target_time, &duration) != 2 || duration < 1 || duration > 86400) {
                respond(fd, "ERR invalid ONETIME schedule arguments\n");
                return;
            }
            item.type = SCHED_TYPE_ONETIME;
            item.target_time = (time_t)target_time;
            item.duration = duration;
        } else if (strncmp(sub, "DAILY ", 6) == 0) {
            int h = 0, m = 0;
            unsigned duration = 0;
            char tz[TZ_LEN] = {0};
            int ret = sscanf(sub + 6, "%02d:%02d %u %63s", &h, &m, &duration, tz);
            if (ret < 3 || duration < 1 || duration > 86400 || h < 0 || h > 23 || m < 0 || m > 59) {
                respond(fd, "ERR invalid DAILY schedule arguments\n");
                return;
            }
            item.type = SCHED_TYPE_DAILY;
            item.hour = h;
            item.minute = m;
            item.duration = duration;
            snprintf(item.tz, sizeof(item.tz), "%s", tz);
        } else if (strncmp(sub, "WEEKLY ", 7) == 0) {
            unsigned mask = 0, duration = 0;
            int h = 0, m = 0;
            char tz[TZ_LEN] = {0};
            int ret = sscanf(sub + 7, "%u %02d:%02d %u %63s", &mask, &h, &m, &duration, tz);
            if (ret < 4 || duration < 1 || duration > 86400 || h < 0 || h > 23 || m < 0 || m > 59 || mask == 0 || mask > 127) {
                respond(fd, "ERR invalid WEEKLY schedule arguments\n");
                return;
            }
            item.type = SCHED_TYPE_WEEKLY;
            item.days_mask = (uint8_t)mask;
            item.hour = h;
            item.minute = m;
            item.duration = duration;
            snprintf(item.tz, sizeof(item.tz), "%s", tz);
        } else {
            respond(fd, "ERR unknown schedule add type\n");
            return;
        }

        if (schedule_store_add(&sched_store, &item, err_buf, sizeof(err_buf)) != 0) {
            reply_error(fd, "schedule add", err_buf);
        } else {
            char out[256];
            snprintf(out, sizeof(out), "OK schedule_added=yes id=%s\n", item.id);
            respond(fd, out);
        }
    } else respond(fd, "ERR unknown command\n");
}

static void usage(const char *exe) {
    fprintf(stderr, "Usage: %s [--socket /absolute/path.sock] [--schedules /path/to/schedules.json] [--foreground]\n", exe);
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--foreground") == 0) continue;
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) socket_path = argv[++i];
        else if (strcmp(argv[i], "--schedules") == 0 && i + 1 < argc) schedule_file_path = argv[++i];
        else { usage(argv[0]); return 2; }
    }
    if (*socket_path != '/' || strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Socket path must be absolute and fit sockaddr_un\n"); return 2;
    }
    if (strcmp(socket_path, DEFAULT_SOCKET) == 0 && geteuid() != 0) {
        fprintf(stderr, "Default socket requires root; use a private --socket directory for tests\n"); return 1;
    }

    schedule_store_init(&sched_store, schedule_file_path);
    char sched_err[256] = {0};
    if (schedule_store_load(&sched_store, sched_err, sizeof(sched_err)) != 0) {
        fprintf(stderr, "Failed to load schedules: %s\n", sched_err);
        return 1;
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
    log_msg("INFO", "ios-caffeinated starting: socket=%s backend=%s schedules=%zu",
            socket_path, power_backend_name(), sched_store.count);

    check_and_trigger_schedules();

    while (keep_running) {
        expire_if_due();
        check_and_trigger_schedules();

        int timeout_ms = 1000;
        double t_now = now();
        if (daemon_state == DAEMON_STATE_ACTIVE && deadline > t_now) {
            double left = deadline - t_now;
            int ms = (int)(left * 1000.0);
            if (ms < 0) ms = 0;
            if (ms < timeout_ms) timeout_ms = ms;
        } else if (daemon_state == DAEMON_STATE_RELEASE_FAILED && retry_at > t_now) {
            double left = retry_at - t_now;
            int ms = (int)(left * 1000.0);
            if (ms < 0) ms = 0;
            if (ms < timeout_ms) timeout_ms = ms;
        }

        if (!is_holding() && !is_release_pending()) {
            time_t now_w = time(NULL);
            int act_i = -1, nxt_i = -1;
            uint32_t act_rem = 0;
            time_t nxt_start = 0;
            schedule_store_evaluate(&sched_store, now_w, &act_i, &act_rem, &nxt_i, &nxt_start);

            if (act_i >= 0 && act_rem > 0) {
                timeout_ms = 0;
            } else if (nxt_i >= 0 && nxt_start > now_w) {
                long long diff_sec = (long long)(nxt_start - now_w);
                if (diff_sec > 0 && diff_sec < 86400) {
                    int ms = (int)(diff_sec * 1000);
                    if (ms < timeout_ms) timeout_ms = ms;
                }
            }
        }

        struct pollfd pfd = {.fd = listen_fd, .events = POLLIN};
        int ret = poll(&pfd, 1, timeout_ms);
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
    log_msg("INFO", "ios-caffeinated shutting down");
    char error[256] = {0};
    if (clear_hold(error, sizeof(error)) != 0) {
        log_msg("ERROR", "UNRESOLVED assertion release at exit; device verification required");
        result = 1;
    }
    daemon_state = DAEMON_STATE_SHUTTING_DOWN;
    close(listen_fd);
    if (remove_owned_socket(&bound) != 0 || clock_failed) result = 1;
    close(lock_fd);
    power_cleanup();
    return result;
}
