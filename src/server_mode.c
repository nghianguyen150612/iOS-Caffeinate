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
        case SERVER_CONFIG_UNSUPPORTED: return "UNSUPPORTED";
    }
    return "INVALID";
}

const char *server_policy_name(server_policy_t policy) {
    switch (policy) {
        case SERVER_POLICY_DISABLED: return "DISABLED";
        case SERVER_POLICY_OBSERVE_ONLY: return "OBSERVE_ONLY";
        case SERVER_POLICY_BOUNDED_SESSION: return "BOUNDED_SESSION";
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

#ifdef IOSCAFFEINATE_SERVER_MODE_TESTING
static char test_append_path[PATH_MAX];

void server_mode_test_append_after_read(const char *path) {
    if (!path || strlen(path) >= sizeof(test_append_path)) {
        test_append_path[0] = '\0';
        return;
    }
    snprintf(test_append_path, sizeof(test_append_path), "%s", path);
}

static void test_append_config_race(const char *path) {
    if (!test_append_path[0] || strcmp(path, test_append_path) != 0) return;
    test_append_path[0] = '\0';
    int fd = open(path, O_WRONLY | O_APPEND | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return;
    const char byte = ' ';
    (void)write(fd, &byte, 1);
    close(fd);
}
#endif

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

static int parse_uint(parser_t *parser, uint64_t *value) {
    skip_whitespace(parser);
    if (!value || parser->cursor >= parser->end ||
        *parser->cursor < '0' || *parser->cursor > '9') return -1;
    const char *start = parser->cursor;
    uint64_t parsed = 0;
    while (parser->cursor < parser->end &&
           *parser->cursor >= '0' && *parser->cursor <= '9') {
        uint64_t digit = (uint64_t)(*parser->cursor - '0');
        if (parsed > (UINT64_MAX - digit) / 10) return -1;
        parsed = parsed * 10 + digit;
        parser->cursor++;
    }
    if (parser->cursor - start > 1 && *start == '0') return -1;
    *value = parsed;
    return 0;
}

static int parse_bool(parser_t *parser, int *value) {
    skip_whitespace(parser);
    if (parser->end - parser->cursor >= 4 &&
        memcmp(parser->cursor, "true", 4) == 0) {
        parser->cursor += 4;
        *value = 1;
        return 0;
    }
    if (parser->end - parser->cursor >= 5 &&
        memcmp(parser->cursor, "false", 5) == 0) {
        parser->cursor += 5;
        *value = 0;
        return 0;
    }
    return -1;
}

static int parse_schema_version(parser_t *parser, unsigned *version) {
    uint64_t parsed = 0;
    if (parse_uint(parser, &parsed) != 0 || parsed > UINT_MAX) return -1;
    *version = (unsigned)parsed;
    return parsed == 1 || parsed == SERVER_MODE_CONFIG_VERSION ? 0 : 1;
}

static int parse_session(parser_t *parser, server_config_t *config) {
    bool have_duration = false;
    bool have_confirmation = false;
    bool have_automatic = false;
    bool have_resume = false;
    if (expect(parser, '{') != 0) return -1;
    for (;;) {
        char key[40];
        skip_whitespace(parser);
        if (parser->cursor >= parser->end || *parser->cursor == '}') return -1;
        if (parse_string(parser, key, sizeof(key)) != 0 || expect(parser, ':') != 0) return -1;
        if (strcmp(key, "max_duration_seconds") == 0) {
            uint64_t value = 0;
            if (have_duration || parse_uint(parser, &value) != 0 ||
                value == 0 || value > SERVER_MODE_MAX_SESSION_SECONDS) return -1;
            config->max_duration_seconds = (unsigned)value;
            have_duration = true;
        } else if (strcmp(key, "require_operator_confirmation") == 0) {
            if (have_confirmation || parse_bool(parser, &config->require_operator_confirmation) != 0)
                return -1;
            have_confirmation = true;
        } else if (strcmp(key, "allow_automatic_start") == 0) {
            if (have_automatic || parse_bool(parser, &config->allow_automatic_start) != 0)
                return -1;
            have_automatic = true;
        } else if (strcmp(key, "allow_restart_resume") == 0) {
            if (have_resume || parse_bool(parser, &config->allow_restart_resume) != 0)
                return -1;
            have_resume = true;
        } else {
            return -1;
        }
        skip_whitespace(parser);
        if (parser->cursor < parser->end && *parser->cursor == '}') {
            parser->cursor++;
            break;
        }
        if (expect(parser, ',') != 0) return -1;
        skip_whitespace(parser);
        if (parser->cursor < parser->end && *parser->cursor == '}') return -1;
    }
    if (!have_duration || !have_confirmation || !have_automatic || !have_resume ||
        !config->require_operator_confirmation || config->allow_automatic_start ||
        config->allow_restart_resume) return -1;
    return 0;
}

/* 0 accepted, 1 unsupported schema version, -1 invalid/ambiguous JSON. */
static int parse_config_json(const char *data, size_t length, server_config_t *config) {
    parser_t parser = {.cursor = data, .end = data + length};
    bool have_version = false;
    bool have_policy = false;
    bool have_session = false;
    int version_status = 0;
    if (expect(&parser, '{') != 0) return -1;
    for (;;) {
        char key[32], value[32];
        skip_whitespace(&parser);
        if (parser.cursor >= parser.end || *parser.cursor == '}') return -1;
        if (parse_string(&parser, key, sizeof(key)) != 0 || expect(&parser, ':') != 0) return -1;
        if (strcmp(key, "version") == 0) {
            if (have_version) return -1;
            version_status = parse_schema_version(&parser, &config->schema_version);
            if (version_status < 0) return -1;
            have_version = true;
        } else if (strcmp(key, "policy") == 0) {
            if (have_policy || parse_string(&parser, value, sizeof(value)) != 0) return -1;
            if (strcmp(value, "disabled") == 0) config->policy = SERVER_POLICY_DISABLED;
            else if (strcmp(value, "observe_only") == 0) config->policy = SERVER_POLICY_OBSERVE_ONLY;
            else if (strcmp(value, "bounded_session") == 0)
                config->policy = SERVER_POLICY_BOUNDED_SESSION;
            else return -1;
            have_policy = true;
        } else if (strcmp(key, "session") == 0) {
            if (have_session || parse_session(&parser, config) != 0) return -1;
            have_session = true;
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
    if (version_status > 0) return 1;
    if (!have_version || !have_policy || parser.cursor != parser.end) return -1;
    if (config->schema_version == 1) {
        if (have_session || config->policy == SERVER_POLICY_BOUNDED_SESSION) return -1;
        config->max_duration_seconds = SERVER_MODE_MAX_SESSION_SECONDS;
        config->require_operator_confirmation = 1;
        config->allow_automatic_start = 0;
        config->allow_restart_resume = 0;
    } else {
        if (!have_session) return -1;
    }
    return 0;
}

int server_mode_config_load(const char *path, server_config_t *config) {
    if (!config) return -1;
    memset(config, 0, sizeof(*config));
    config->status = SERVER_CONFIG_MISSING;
    config->policy = SERVER_POLICY_DISABLED;
    config->schema_version = 0;
    config->max_duration_seconds = SERVER_MODE_MAX_SESSION_SECONDS;
    config->require_operator_confirmation = 1;
    config->allow_automatic_start = 0;
    config->allow_restart_resume = 0;
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
#ifdef IOSCAFFEINATE_SERVER_MODE_TESTING
    test_append_config_race(path ? path : SERVER_MODE_CONFIG_DEFAULT);
#endif
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
    int parse_status = parse_config_json(data, used, config);
    if (parse_status != 0) {
        config->policy = SERVER_POLICY_DISABLED;
        config->status = parse_status > 0 ? SERVER_CONFIG_UNSUPPORTED : SERVER_CONFIG_INVALID;
        snprintf(config->detail, sizeof(config->detail), parse_status > 0 ?
                 "configuration schema version is unsupported" :
                 "strict version 1 or version 2 schema parse failed");
        return 0;
    }

    config->status = SERVER_CONFIG_VALID;
    snprintf(config->detail, sizeof(config->detail), "schema version %u accepted",
             config->schema_version);
    return 0;
}
