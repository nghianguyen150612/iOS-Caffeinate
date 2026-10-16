#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"

static void usage(void) {
    puts("ioscaffeinate — jailbreak iOS server power-management CLI (experimental)\n"
         "\n"
         "Usage:\n"
         "  ioscaffeinate [--socket /absolute/path.sock] probe\n"
         "  ioscaffeinate [--socket /absolute/path.sock] status\n"
         "  ioscaffeinate [--socket /absolute/path.sock] start --for 5m\n"
         "  ioscaffeinate [--socket /absolute/path.sock] stop\n"
         "\n"
         "Duration: seconds (s), minutes (m), or hours (h), maximum 24h.\n"
         "RTC wake and indefinite mode are not available in P001.\n"
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

int main(int argc, char **argv) {
    const char *path = DEFAULT_SOCKET;
    int i = 1;
    if (i < argc && strcmp(argv[i], "--socket") == 0) {
        if (i + 1 >= argc) { usage(); return 2; }
        path = argv[i + 1];
        i += 2;
    }
    if (i == argc || strcmp(argv[i], "help") == 0 || strcmp(argv[i], "--help") == 0) {
        usage(); return i == argc ? 2 : 0;
    }
    char command[128] = {0};
    if (strcmp(argv[i], "probe") == 0 && i + 1 == argc) strcpy(command, "PROBE\n");
    else if (strcmp(argv[i], "status") == 0 && i + 1 == argc) strcpy(command, "STATUS\n");
    else if (strcmp(argv[i], "stop") == 0 && i + 1 == argc) strcpy(command, "STOP\n");
    else if (strcmp(argv[i], "start") == 0 && i + 3 == argc &&
             strcmp(argv[i + 1], "--for") == 0) {
        unsigned duration = 0;
        if (parse_duration(argv[i + 2], &duration) != 0) {
            fprintf(stderr, "Invalid duration. Use 1s..24h.\n");
            return 2;
        }
        snprintf(command, sizeof(command), "START %u\n", duration);
    } else { usage(); return 2; }

    if (*path != '/' || strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Invalid socket path\n");
        return 2;
    }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("connect daemon (is ioscaffeinated running?)");
        close(fd);
        return 1;
    }
    struct timeval timeout = {.tv_sec = 4, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    size_t to_send = strlen(command);
    const char *out = command;
    while (to_send) {
        ssize_t n = write(fd, out, to_send);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { perror("write"); close(fd); return 1; }
        to_send -= (size_t)n;
        out += n;
    }
    char response[512] = {0};
    ssize_t n = read(fd, response, sizeof(response) - 1);
    if (n <= 0) { fprintf(stderr, "Daemon did not reply\n"); close(fd); return 1; }
    response[n] = 0;
    close(fd);
    fputs(response, strncmp(response, "ERR ", 4) == 0 ? stderr : stdout);
    return strncmp(response, "OK ", 3) == 0 ? 0 : 1;
}
