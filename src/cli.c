/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L
#include "schedule.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"

static void usage(void) {
    puts("ios-caffeinate — jailbreak iOS server power-management CLI\n"
         "\n"
         "Usage:\n"
         "  ios-caffeinate [--socket /absolute/path.sock] probe\n"
         "  ios-caffeinate [--socket /absolute/path.sock] status\n"
         "  ios-caffeinate [--socket /absolute/path.sock] start --for 5m\n"
         "  ios-caffeinate [--socket /absolute/path.sock] start --until 2026-10-18T23:00:00+07:00\n"
         "  ios-caffeinate [--socket /absolute/path.sock] stop\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --at <ISO-8601> --for <duration>\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --daily <HH:MM> --for <duration> [--tz <TZ>]\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --weekly <days> --at <HH:MM> --for <duration> [--tz <TZ>]\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule list\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule remove <schedule-id>\n"
         "\n"
         "Duration: seconds (s), minutes (m), or hours (h), maximum 24h.\n"
         "Alias: ic (filesystem symlink to ios-caffeinate).\n"
         "Only root can access the default daemon socket.\n");
}

static int parse_duration(const char *str, unsigned *result) {
    if (!str || str[0] < '0' || str[0] > '9') return -1;
    errno = 0;
    char *end = NULL;
    unsigned long long n = strtoull(str, &end, 10);
    if (errno || end == str) return -1;
    unsigned long long multiplier = 1;
    if (strcmp(end, "s") == 0 || *end == '\0') multiplier = 1;
    else if (strcmp(end, "m") == 0) multiplier = 60;
    else if (strcmp(end, "h") == 0) multiplier = 3600;
    else return -1;
    if (n == 0 || n > 86400ULL / multiplier) return -1;
    *result = (unsigned)(n * multiplier);
    return 0;
}

static int parse_hhmm(const char *str, int *hour, int *min) {
    if (!str) return -1;
    int h, m;
    if (sscanf(str, "%2d:%2d", &h, &m) != 2) return -1;
    if (h < 0 || h > 23 || m < 0 || m > 59) return -1;
    if (strlen(str) != 5 || str[2] != ':') return -1;
    *hour = h;
    *min = m;
    return 0;
}

int main(int argc, char **argv) {
    const char *path = DEFAULT_SOCKET;
    int i = 1;
    if (i < argc && strcmp(argv[i], "--socket") == 0) {
        if (i + 1 >= argc) { usage(); return 2; }
        path = argv[i + 1];
        i += 2;
    }
    if (i == argc || strcmp(argv[i], "help") == 0 || strcmp(argv[i], "--help") == 0) {
        usage(); return i + 1 == argc ? 0 : 2;
    }

    char command[512] = {0};

    if (strcmp(argv[i], "probe") == 0 && i + 1 == argc) {
        strcpy(command, "PROBE\n");
    } else if (strcmp(argv[i], "status") == 0 && i + 1 == argc) {
        strcpy(command, "STATUS\n");
    } else if (strcmp(argv[i], "stop") == 0 && i + 1 == argc) {
        strcpy(command, "STOP\n");
    } else if (strcmp(argv[i], "start") == 0) {
        if (i + 3 == argc && strcmp(argv[i + 1], "--for") == 0) {
            unsigned duration = 0;
            if (parse_duration(argv[i + 2], &duration) != 0) {
                fprintf(stderr, "Invalid duration. Use 1s..24h.\n");
                return 2;
            }
            snprintf(command, sizeof(command), "START %u\n", duration);
        } else if (i + 3 == argc && strcmp(argv[i + 1], "--until") == 0) {
            time_t deadline_utc = parse_iso8601(argv[i + 2]);
            if (deadline_utc == (time_t)-1) {
                fprintf(stderr, "Invalid ISO-8601 timestamp for --until. Explicit timezone offset required.\n");
                return 2;
            }
            time_t now_utc = time(NULL);
            if (deadline_utc <= now_utc) {
                fprintf(stderr, "Deadline is in the past.\n");
                return 2;
            }
            double diff = difftime(deadline_utc, now_utc);
            if (diff < 1.0 || diff > 86400.0) {
                fprintf(stderr, "Duration until deadline must be between 1s and 24h.\n");
                return 2;
            }
            snprintf(command, sizeof(command), "START %u\n", (unsigned)diff);
        } else { usage(); return 2; }
    } else if (strcmp(argv[i], "schedule") == 0) {
        i++;
        if (i >= argc) { usage(); return 2; }
        if (strcmp(argv[i], "list") == 0 && i + 1 == argc) {
            strcpy(command, "SCHEDULE LIST\n");
        } else if (strcmp(argv[i], "remove") == 0 && i + 2 == argc) {
            snprintf(command, sizeof(command), "SCHEDULE REMOVE %s\n", argv[i + 1]);
        } else if (strcmp(argv[i], "add") == 0) {
            i++;
            const char *at_str = NULL;
            const char *daily_str = NULL;
            const char *weekly_str = NULL;
            const char *for_str = NULL;
            const char *tz_str = NULL;

            while (i < argc) {
                if (strcmp(argv[i], "--at") == 0 && i + 1 < argc) { at_str = argv[++i]; }
                else if (strcmp(argv[i], "--daily") == 0 && i + 1 < argc) { daily_str = argv[++i]; }
                else if (strcmp(argv[i], "--weekly") == 0 && i + 1 < argc) { weekly_str = argv[++i]; }
                else if (strcmp(argv[i], "--for") == 0 && i + 1 < argc) { for_str = argv[++i]; }
                else if (strcmp(argv[i], "--tz") == 0 && i + 1 < argc) { tz_str = argv[++i]; }
                else { usage(); return 2; }
                i++;
            }

            if (!for_str) {
                fprintf(stderr, "Missing --for duration parameter.\n");
                return 2;
            }
            unsigned duration = 0;
            if (parse_duration(for_str, &duration) != 0) {
                fprintf(stderr, "Invalid --for duration. Use 1s..24h.\n");
                return 2;
            }

            if (weekly_str) {
                uint8_t mask = 0;
                if (parse_weekly_days(weekly_str, &mask) != 0) {
                    fprintf(stderr, "Invalid --weekly days. Use mon,wed,fri etc.\n");
                    return 2;
                }
                int hour = 0, min = 0;
                if (!at_str || parse_hhmm(at_str, &hour, &min) != 0) {
                    fprintf(stderr, "Weekly schedule requires --at HH:MM.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD WEEKLY %u %02d:%02d %u %s\n",
                         (unsigned)mask, hour, min, duration, tz_str ? tz_str : "");
            } else if (daily_str) {
                int hour = 0, min = 0;
                if (parse_hhmm(daily_str, &hour, &min) != 0) {
                    fprintf(stderr, "Daily schedule requires --daily HH:MM.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD DAILY %02d:%02d %u %s\n",
                         hour, min, duration, tz_str ? tz_str : "");
            } else if (at_str) {
                time_t target_utc = parse_iso8601(at_str);
                if (target_utc == (time_t)-1) {
                    fprintf(stderr, "Invalid ISO-8601 timestamp for schedule --at. Explicit timezone offset required.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD ONETIME %lld %u\n",
                         (long long)target_utc, duration);
            } else { usage(); return 2; }
        } else { usage(); return 2; }
    } else { usage(); return 2; }

    if (*path != '/' || strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Invalid socket path\n");
        return 2;
    }
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("signal setup"); return 1; }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("connect daemon (is ios-caffeinated running?)");
        close(fd);
        return 1;
    }
    struct timeval timeout = {.tv_sec = 4, .tv_usec = 0};
    if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
        perror("socket timeout"); close(fd); return 1; }
    size_t to_send = strlen(command);
    const char *out = command;
    while (to_send) {
        ssize_t n = write(fd, out, to_send);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { perror("write"); close(fd); return 1; }
        to_send -= (size_t)n;
        out += n;
    }
    char response[16384] = {0};
    size_t used = 0;
    struct timespec started, current;
    if (clock_gettime(CLOCK_MONOTONIC, &started) != 0) {
        perror("clock_gettime"); close(fd); return 1; }
    for (;;) {
        if (clock_gettime(CLOCK_MONOTONIC, &current) != 0) break;
        double elapsed = (double)(current.tv_sec - started.tv_sec) +
                         (double)(current.tv_nsec - started.tv_nsec) / 1000000000.0;
        if (elapsed >= 4) break;
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int ready = poll(&pfd, 1, 100);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0) break;
        if (ready == 0) continue;
        ssize_t n = recv(fd, response + used, sizeof(response) - 1 - used, MSG_DONTWAIT);
        if (n <= 0) {
            if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            break;
        }
        size_t end = used + (size_t)n;
        bool is_sched_list = (strncmp(response, "OK schedules=", 13) == 0);
        for (size_t j = used; j < end; ++j) {
            if (response[j] == '\n') {
                if (!is_sched_list && j + 1 != end) goto incomplete;
            } else if ((unsigned char)response[j] < 32 || (unsigned char)response[j] > 126) {
                goto incomplete;
            }
        }
        used = end;
        if (!is_sched_list && used > 0 && response[used - 1] == '\n') {
            response[used] = 0;
            close(fd);
            fputs(response, strncmp(response, "OK ", 3) == 0 ? stdout : stderr);
            return strncmp(response, "OK ", 3) == 0 ? 0 : 1;
        }
        if (used == sizeof(response) - 1) break;
    }
incomplete:
    if (used > 0 && response[used - 1] == '\n') {
        response[used] = 0;
        close(fd);
        fputs(response, strncmp(response, "OK ", 3) == 0 ? stdout : stderr);
        return strncmp(response, "OK ", 3) == 0 ? 0 : 1;
    }
    fprintf(stderr, "Daemon did not send a complete valid reply\n");
    close(fd);
    return 1;
}
