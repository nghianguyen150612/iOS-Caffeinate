/* Darwin hides a few POSIX declarations in strict language mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L

#include "server_mode.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef S_ISVTX
#define S_ISVTX 01000
#endif

static const char *const readiness_gates[] = {
    "device_runtime_verified",
    "assertion_acquire_verified",
    "assertion_release_verified",
    "bounded_hold_verified",
    "screen_locked_lan_verified",
    "screen_locked_tailscale_verified",
    "shutdown_cleanup_verified",
    "battery_observation_available",
    "thermal_observation_available",
    "physical_recovery_confirmed"
};

size_t server_mode_gate_count(void) {
    return sizeof(readiness_gates) / sizeof(readiness_gates[0]);
}

const char *server_mode_gate_name(size_t index) {
    return index < server_mode_gate_count() ? readiness_gates[index] : "unknown";
}

const char *server_config_status_name(server_config_status_t status) {
    switch (status) {
        case SERVER_CONFIG_MISSING: return "MISSING";
        case SERVER_CONFIG_VALID: return "VALID";
        case SERVER_CONFIG_INVALID: return "INVALID";
        case SERVER_CONFIG_UNSAFE: return "UNSAFE";
    }
    return "INVALID";
}

const char *server_policy_name(server_policy_t policy) {
    switch (policy) {
        case SERVER_POLICY_DISABLED: return "DISABLED";
        case SERVER_POLICY_OBSERVE_ONLY: return "OBSERVE_ONLY";
    }
    return "DISABLED";
}

const char *server_mode_backend_name(void) {
#if defined(IOSCAFFEINATE_TEST_MOCK)
    return "MOCK_NO_POWER_EFFECT";
#elif defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    return "IOKit_RUNTIME_UNVERIFIED";
#elif defined(__APPLE__)
    return "IOKit_RUNTIME_UNVERIFIED";
#else
    return "NONE";
#endif
}

static int trusted_directory(const struct stat *st) {
    if (!S_ISDIR(st->st_mode)) return 0;
    if (st->st_uid != geteuid() && st->st_uid != 0) return 0;
    mode_t writable = st->st_mode & (S_IWGRP | S_IWOTH);
    if (writable == 0) return 1;
    /* Shared root-owned sticky directories such as /tmp are safe ancestors;
     * the configuration file itself has stricter owner and mode checks. */
    return st->st_uid == 0 && (st->st_mode & S_ISVTX) != 0;
}

static int open_config_file(const char *path, int *fd_out, server_config_status_t *status,
                            char *detail, size_t detail_cap) {
    if (!path || path[0] != '/' || strlen(path) >= PATH_MAX) {
        *status = SERVER_CONFIG_UNSAFE;
        snprintf(detail, detail_cap, "path must be absolute and bounded");
        return -1;
    }

    char copy[PATH_MAX];
    snprintf(copy, sizeof(copy), "%s", path);
    size_t length = strlen(copy);
    if (length < 2 || copy[length - 1] == '/') {
        *status = SERVER_CONFIG_UNSAFE;
        snprintf(detail, detail_cap, "path must name a file");
        return -1;
    }

    int dirfd = open("/", O_RDONLY | O_DIRECTORY);
    if (dirfd < 0) {
        *status = SERVER_CONFIG_UNSAFE;
        snprintf(detail, detail_cap, "cannot open filesystem root");
        return -1;
    }

    char *cursor = copy + 1;
    for (;;) {
        char *slash = strchr(cursor, '/');
        if (slash) *slash = '\0';
        if (*cursor == '\0' || strcmp(cursor, ".") == 0 || strcmp(cursor, "..") == 0) {
            close(dirfd);
            *status = SERVER_CONFIG_UNSAFE;
            snprintf(detail, detail_cap, "path contains an unsafe component");
            return -1;
        }

        if (!slash) {
            int fd = openat(dirfd, cursor, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
            int saved = errno;
            close(dirfd);
            if (fd < 0) {
                if (saved == ENOENT) {
                    *status = SERVER_CONFIG_MISSING;
                    snprintf(detail, detail_cap, "configuration file is absent");
                } else {
                    *status = SERVER_CONFIG_UNSAFE;
                    snprintf(detail, detail_cap, "cannot safely open configuration file");
                }
                return -1;
            }
            *fd_out = fd;
            return 0;
        }

        int nextfd = openat(dirfd, cursor, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        int saved = errno;
        if (nextfd < 0) {
            close(dirfd);
            if (saved == ENOENT) {
                *status = SERVER_CONFIG_MISSING;
                snprintf(detail, detail_cap, "configuration parent is absent");
            } else {
                *status = SERVER_CONFIG_UNSAFE;
                snprintf(detail, detail_cap, "configuration parent is not a safe directory");
            }
            return -1;
        }
        struct stat st;
        if (fstat(nextfd, &st) != 0 || !trusted_directory(&st)) {
            close(nextfd);
            close(dirfd);
            *status = SERVER_CONFIG_UNSAFE;
            snprintf(detail, detail_cap, "configuration parent is untrusted");
            return -1;
        }
        close(dirfd);
        dirfd = nextfd;
        cursor = slash + 1;
    }
}

typedef struct {
    const char *cursor;
    const char *end;
} parser_t;

static void skip_whitespace(parser_t *parser) {
    while (parser->cursor < parser->end &&
           (*parser->cursor == ' ' || *parser->cursor == '\t' ||
            *parser->cursor == '\r' || *parser->cursor == '\n')) {
        parser->cursor++;
    }
}

static int expect(parser_t *parser, char token) {
    skip_whitespace(parser);
    if (parser->cursor >= parser->end || *parser->cursor != token) return -1;
    parser->cursor++;
    return 0;
}

static int parse_string(parser_t *parser, char *out, size_t cap) {
    if (expect(parser, '"') != 0 || cap == 0) return -1;
    size_t used = 0;
    while (parser->cursor < parser->end && *parser->cursor != '"') {
        unsigned char c = (unsigned char)*parser->cursor++;
        /* Keys and enum values are fixed ASCII tokens; escapes/control bytes
         * have no meaning in this intentionally small schema. */
        if (c < 0x20 || c > 0x7e || c == '\\' || used + 1 >= cap) return -1;
        out[used++] = (char)c;
    }
    if (parser->cursor >= parser->end || *parser->cursor != '"') return -1;
    parser->cursor++;
    out[used] = '\0';
    return 0;
}

static int parse_version(parser_t *parser) {
    skip_whitespace(parser);
    if (parser->cursor >= parser->end || *parser->cursor != '1') return -1;
    parser->cursor++;
    if (parser->cursor < parser->end && *parser->cursor >= '0' && *parser->cursor <= '9') return -1;
    return 0;
}

static int parse_config_json(const char *data, size_t length, server_policy_t *policy) {
    parser_t parser = {.cursor = data, .end = data + length};
    bool have_version = false;
    bool have_policy = false;
    if (expect(&parser, '{') != 0) return -1;
    for (;;) {
        char key[32], value[32];
        skip_whitespace(&parser);
        if (parser.cursor >= parser.end || *parser.cursor == '}') return -1;
        if (parse_string(&parser, key, sizeof(key)) != 0 || expect(&parser, ':') != 0) return -1;
        if (strcmp(key, "version") == 0) {
            if (have_version || parse_version(&parser) != 0) return -1;
            have_version = true;
        } else if (strcmp(key, "policy") == 0) {
            if (have_policy || parse_string(&parser, value, sizeof(value)) != 0) return -1;
            if (strcmp(value, "disabled") == 0) *policy = SERVER_POLICY_DISABLED;
            else if (strcmp(value, "observe_only") == 0) *policy = SERVER_POLICY_OBSERVE_ONLY;
            else return -1;
            have_policy = true;
        } else {
            return -1;
        }
        skip_whitespace(&parser);
        if (parser.cursor < parser.end && *parser.cursor == '}') {
            parser.cursor++;
            break;
        }
        if (expect(&parser, ',') != 0) return -1;
        skip_whitespace(&parser);
        if (parser.cursor < parser.end && *parser.cursor == '}') return -1;
    }
    skip_whitespace(&parser);
    return have_version && have_policy && parser.cursor == parser.end ? 0 : -1;
}

int server_mode_config_load(const char *path, server_config_t *config) {
    if (!config) return -1;
    memset(config, 0, sizeof(*config));
    config->status = SERVER_CONFIG_MISSING;
    config->policy = SERVER_POLICY_DISABLED;
    snprintf(config->detail, sizeof(config->detail), "configuration file is absent");

    int fd = -1;
    if (open_config_file(path ? path : SERVER_MODE_CONFIG_DEFAULT, &fd, &config->status,
                         config->detail, sizeof(config->detail)) != 0) {
        return 0;
    }

    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        st.st_nlink != 1 || (st.st_mode & 07777) != 0600 || st.st_size < 1 ||
        st.st_size > SERVER_MODE_CONFIG_MAX) {
        close(fd);
        config->status = SERVER_CONFIG_UNSAFE;
        snprintf(config->detail, sizeof(config->detail),
                 "file must be owned by the effective user, regular, single-link, 0600, and <=%d bytes",
                 SERVER_MODE_CONFIG_MAX);
        return 0;
    }

    char data[SERVER_MODE_CONFIG_MAX + 1];
    size_t used = 0;
    int read_error = 0;
    while (used < sizeof(data)) {
        ssize_t n = read(fd, data + used, sizeof(data) - used);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { read_error = 1; break; }
        if (n == 0) break;
        used += (size_t)n;
    }
    struct stat after_read;
    int stable = !read_error && fstat(fd, &after_read) == 0 &&
                 S_ISREG(after_read.st_mode) && after_read.st_uid == geteuid() &&
                 after_read.st_nlink == 1 && (after_read.st_mode & 07777) == 0600 &&
                 after_read.st_dev == st.st_dev && after_read.st_ino == st.st_ino &&
                 after_read.st_size == (off_t)used;
    close(fd);
    if (used > SERVER_MODE_CONFIG_MAX || !stable || memchr(data, '\0', used) != NULL) {
        config->policy = SERVER_POLICY_DISABLED;
        config->status = SERVER_CONFIG_INVALID;
        snprintf(config->detail, sizeof(config->detail), "configuration size changed or exceeded the bound");
        return 0;
    }
    data[used] = '\0';
    if (parse_config_json(data, used, &config->policy) != 0) {
        config->policy = SERVER_POLICY_DISABLED;
        config->status = SERVER_CONFIG_INVALID;
        snprintf(config->detail, sizeof(config->detail), "strict version 1 schema parse failed");
        return 0;
    }

    config->status = SERVER_CONFIG_VALID;
    snprintf(config->detail, sizeof(config->detail), "schema version 1 accepted");
    return 0;
}
