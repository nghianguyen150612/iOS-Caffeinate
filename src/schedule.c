#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L
#include "schedule.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#endif

#define MAX_FILE_SIZE 65536

time_t parse_iso8601(const char *str) {
    if (!str) return (time_t)-1;
    int year, month, day, hour, min, sec;
    char tz_sign = '\0';
    int tz_hour = 0, tz_min = 0;

    if (strlen(str) < 19) return (time_t)-1;
    if (str[4] != '-' || str[7] != '-' || (str[10] != 'T' && str[10] != 't' && str[10] != ' ') ||
        str[13] != ':' || str[16] != ':') {
        return (time_t)-1;
    }

    if (sscanf(str, "%4d-%2d-%2dT%2d:%2d:%2d", &year, &month, &day, &hour, &min, &sec) != 6) {
        if (sscanf(str, "%4d-%2d-%2d %2d:%2d:%2d", &year, &month, &day, &hour, &min, &sec) != 6) {
            return (time_t)-1;
        }
    }

    if (year < 1970 || month < 1 || month > 12 || day < 1 || day > 31 ||
        hour < 0 || hour > 23 || min < 0 || min > 59 || sec < 0 || sec > 59) {
        return (time_t)-1;
    }

    const char *p = str + 19;
    if (*p == 'Z' || *p == 'z') {
        tz_sign = 'Z';
        p++;
    } else if (*p == '+' || *p == '-') {
        tz_sign = *p;
        int parsed_len = 0;
        if (sscanf(p + 1, "%2d:%2d%n", &tz_hour, &tz_min, &parsed_len) == 2 && parsed_len == 5) {
            p += 6;
        } else if (sscanf(p + 1, "%2d%2d%n", &tz_hour, &tz_min, &parsed_len) == 2 && parsed_len == 4) {
            p += 5;
        } else if (sscanf(p + 1, "%2d%n", &tz_hour, &parsed_len) == 1 && parsed_len == 2) {
            tz_min = 0;
            p += 3;
        } else {
            return (time_t)-1;
        }
        if (tz_hour < 0 || tz_hour > 23 || tz_min < 0 || tz_min > 59) return (time_t)-1;
    } else {
        return (time_t)-1;
    }

    while (*p) {
        if (!isspace((unsigned char)*p)) return (time_t)-1;
        p++;
    }

    struct tm tm_utc;
    memset(&tm_utc, 0, sizeof(tm_utc));
    tm_utc.tm_year = year - 1900;
    tm_utc.tm_mon = month - 1;
    tm_utc.tm_mday = day;
    tm_utc.tm_hour = hour;
    tm_utc.tm_min = min;
    tm_utc.tm_sec = sec;

    time_t t = timegm(&tm_utc);
    if (t == (time_t)-1) return (time_t)-1;
    struct tm normalized;
    if (!gmtime_r(&t, &normalized) || normalized.tm_year != year - 1900 ||
        normalized.tm_mon != month - 1 || normalized.tm_mday != day ||
        normalized.tm_hour != hour || normalized.tm_min != min || normalized.tm_sec != sec) {
        return (time_t)-1;
    }

    if (tz_sign == '+' || tz_sign == '-') {
        int offset_sec = tz_hour * 3600 + tz_min * 60;
        if (tz_sign == '+') t -= offset_sec;
        else t += offset_sec;
    }

    return t;
}

int format_iso8601_utc(time_t t, char *buf, size_t cap) {
    struct tm tm_buf;
    if (!gmtime_r(&t, &tm_buf)) return -1;
    return snprintf(buf, cap, "%04d-%02d-%02dT%02d:%02d:%02dZ",
                    tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
                    tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec);
}

int parse_weekly_days(const char *str, uint8_t *mask_out) {
    if (!str || !mask_out) return -1;
    uint8_t mask = 0;
    char tmp[128];
    snprintf(tmp, sizeof(tmp), "%s", str);
    char *token = strtok(tmp, ",");
    while (token) {
        while (isspace((unsigned char)*token)) token++;
        char *end = token + strlen(token) - 1;
        while (end > token && isspace((unsigned char)*end)) { *end = '\0'; end--; }

        if (strcasecmp(token, "sun") == 0 || strcasecmp(token, "0") == 0 || strcasecmp(token, "7") == 0) mask |= (1 << 0);
        else if (strcasecmp(token, "mon") == 0 || strcasecmp(token, "1") == 0) mask |= (1 << 1);
        else if (strcasecmp(token, "tue") == 0 || strcasecmp(token, "2") == 0) mask |= (1 << 2);
        else if (strcasecmp(token, "wed") == 0 || strcasecmp(token, "3") == 0) mask |= (1 << 3);
        else if (strcasecmp(token, "thu") == 0 || strcasecmp(token, "4") == 0) mask |= (1 << 4);
        else if (strcasecmp(token, "fri") == 0 || strcasecmp(token, "5") == 0) mask |= (1 << 5);
        else if (strcasecmp(token, "sat") == 0 || strcasecmp(token, "6") == 0) mask |= (1 << 6);
        else return -1;

        token = strtok(NULL, ",");
    }
    if (mask == 0) return -1;
    *mask_out = mask;
    return 0;
}

void schedule_store_init(schedule_store_t *store, const char *file_path) {
    if (!store) return;
    memset(store, 0, sizeof(*store));
    if (file_path) snprintf(store->state_file_path, sizeof(store->state_file_path), "%s", file_path);
    else snprintf(store->state_file_path, sizeof(store->state_file_path), "/var/lib/ioscaffeinate/schedules.json");
    store->next_id_counter = 1;
}

static void json_skip_whitespace(const char **cursor) {
    while (isspace((unsigned char)**cursor)) (*cursor)++;
}

static int json_expect_char(const char **cursor, char expected) {
    json_skip_whitespace(cursor);
    if (**cursor != expected) return -1;
    (*cursor)++;
    return 0;
}

static int json_expect_key(const char **cursor, const char *expected) {
    json_skip_whitespace(cursor);
    if (**cursor != '"') return -1;
    (*cursor)++;
    size_t length = strlen(expected);
    if (strncmp(*cursor, expected, length) != 0 || (*cursor)[length] != '"') return -1;
    *cursor += length + 1;
    if (json_expect_char(cursor, ':') != 0) return -1;
    return 0;
}

static int json_parse_string(const char **cursor, char *out, size_t cap) {
    if (cap == 0 || json_expect_char(cursor, '"') != 0) return -1;
    size_t length = 0;
    while (**cursor && **cursor != '"') {
        unsigned char c = (unsigned char)*(*cursor)++;
        if (c < 0x20 || c > 0x7e || c == '\\' || length + 1 >= cap) return -1;
        out[length++] = (char)c;
    }
    if (json_expect_char(cursor, '"') != 0) return -1;
    out[length] = '\0';
    return 0;
}

static int json_parse_int64(const char **cursor, int64_t *value) {
    json_skip_whitespace(cursor);
    if (!(**cursor == '-' || (**cursor >= '0' && **cursor <= '9')) ||
        (**cursor == '-' && ((*cursor)[1] < '0' || (*cursor)[1] > '9'))) return -1;
    const char *start = *cursor;
    errno = 0;
    char *end = NULL;
    long long parsed = strtoll(*cursor, &end, 10);
    if (errno || end == *cursor) return -1;
    const char *digits = *start == '-' ? start + 1 : start;
    if (*digits == '0' && end > digits + 1) return -1;
    *value = (int64_t)parsed;
    *cursor = end;
    return 0;
}

static int json_parse_uint32(const char **cursor, uint32_t *value) {
    json_skip_whitespace(cursor);
    if (**cursor < '0' || **cursor > '9') return -1;
    const char *start = *cursor;
    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(*cursor, &end, 10);
    if (errno || end == *cursor || parsed > UINT32_MAX) return -1;
    if (*start == '0' && end > start + 1) return -1;
    *value = (uint32_t)parsed;
    *cursor = end;
    return 0;
}

static int json_parse_int(const char **cursor, int *value) {
    int64_t parsed = 0;
    if (json_parse_int64(cursor, &parsed) != 0 || parsed < INT_MIN || parsed > INT_MAX) return -1;
    *value = (int)parsed;
    return 0;
}

static int json_parse_time(const char **cursor, time_t *value) {
    int64_t parsed = 0;
    if (json_parse_int64(cursor, &parsed) != 0) return -1;
    *value = (time_t)parsed;
    return (int64_t)*value == parsed ? 0 : -1;
}

static int json_parse_bool(const char **cursor, bool *value) {
    json_skip_whitespace(cursor);
    if (strncmp(*cursor, "true", 4) == 0) {
        *value = true;
        *cursor += 4;
        return 0;
    }
    if (strncmp(*cursor, "false", 5) == 0) {
        *value = false;
        *cursor += 5;
        return 0;
    }
    return -1;
}

static int valid_schedule_text(const schedule_t *item) {
    if (!item->id[0]) return 0;
    for (const unsigned char *p = (const unsigned char *)item->id; *p; ++p) {
        if (!( (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
               (*p >= '0' && *p <= '9') || *p == '_' || *p == '-')) return 0;
    }
    size_t tz_len = strlen(item->tz);
    if (tz_len > 0 && (item->tz[0] == '/' || item->tz[tz_len - 1] == '/')) return 0;
    for (const unsigned char *p = (const unsigned char *)item->tz; *p; ++p) {
        if (!( (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
               (*p >= '0' && *p <= '9') || *p == '_' || *p == '+' ||
               *p == '-' || *p == '.' || *p == '/')) return 0;
    }
    if (strstr(item->tz, "..") != NULL) return 0;
    const char *component = item->tz;
    while (*component) {
        const char *slash = strchr(component, '/');
        size_t length = slash ? (size_t)(slash - component) : strlen(component);
        if (length == 0 || (length == 1 && component[0] == '.')) return 0;
        component = slash ? slash + 1 : component + length;
    }
    return true;
}

static int valid_schedule(const schedule_t *item) {
    if (!valid_schedule_text(item) || item->duration < 1 || item->duration > 86400 ||
        item->last_fired_time < 0) return 0;
    if (item->type == SCHED_TYPE_ONETIME)
        return item->target_time >= 0 && item->target_time <= (time_t)(INT64_MAX - item->duration) &&
               item->hour == 0 && item->minute == 0 && item->days_mask == 0;
    if (item->type == SCHED_TYPE_DAILY)
        return item->target_time == 0 && item->hour >= 0 && item->hour <= 23 &&
               item->minute >= 0 && item->minute <= 59 && item->days_mask == 0;
    if (item->type == SCHED_TYPE_WEEKLY)
        return item->target_time == 0 && item->hour >= 0 && item->hour <= 23 &&
               item->minute >= 0 && item->minute <= 59 && item->days_mask > 0 &&
               item->days_mask <= 127;
    return 0;
}

static int trusted_state_directory(const struct stat *st, int final_parent) {
    if (!S_ISDIR(st->st_mode) || (st->st_uid != geteuid() && st->st_uid != 0)) return 0;
    mode_t writable = st->st_mode & (S_IWGRP | S_IWOTH);
    if (!writable) return 1;
    if (final_parent) return 0;
    return st->st_uid == 0 && (st->st_mode & S_ISVTX) != 0;
}

/* Pin every parent component by descriptor so custom state paths cannot
 * redirect a privileged daemon through a symlink or replaced directory. */
static int open_state_parent(const char *path, char *basename, size_t basename_cap) {
    if (!path || path[0] != '/' || strlen(path) >= 256 || basename_cap == 0) return -1;
    char copy[256];
    snprintf(copy, sizeof(copy), "%s", path);
    size_t length = strlen(copy);
    if (length < 2 || copy[length - 1] == '/') return -1;

    int dir_fd = open("/", O_RDONLY | O_DIRECTORY);
    if (dir_fd < 0) return -1;
    char *component = copy + 1;
    for (;;) {
        char *slash = strchr(component, '/');
        if (!slash) {
            if (!*component || strcmp(component, ".") == 0 || strcmp(component, "..") == 0 ||
                snprintf(basename, basename_cap, "%s", component) >= (int)basename_cap) {
                close(dir_fd);
                return -1;
            }
            struct stat st;
            if (fstat(dir_fd, &st) != 0 || !trusted_state_directory(&st, 1)) {
                close(dir_fd);
                return -1;
            }
            return dir_fd;
        }
        *slash = '\0';
        if (!*component || strcmp(component, ".") == 0 || strcmp(component, "..") == 0) {
            close(dir_fd);
            return -1;
        }
        int next_fd = openat(dir_fd, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        if (next_fd < 0) {
            close(dir_fd);
            return -1;
        }
        struct stat st;
        if (fstat(next_fd, &st) != 0 || !trusted_state_directory(&st, 0)) {
            close(next_fd);
            close(dir_fd);
            return -1;
        }
        close(dir_fd);
        dir_fd = next_fd;
        component = slash + 1;
    }
}

int schedule_store_load(schedule_store_t *store, char *err_buf, size_t err_cap) {
    if (!store || !store->state_file_path[0] || store->state_file_path[0] != '/') {
        if (err_buf) snprintf(err_buf, err_cap, "schedule state path must be absolute and non-empty");
        return -1;
    }

    char basename[256];
    int dir_fd = open_state_parent(store->state_file_path, basename, sizeof(basename));
    if (dir_fd < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule state parent is unsafe or inaccessible");
        return -1;
    }

    struct stat st;
    if (fstatat(dir_fd, basename, &st, AT_SYMLINK_NOFOLLOW) != 0) {
        int saved = errno;
        close(dir_fd);
        if (saved == ENOENT) return 0;
        if (err_buf) snprintf(err_buf, err_cap, "inspect schedule file failed: %s", strerror(saved));
        return -1;
    }

    if (!S_ISREG(st.st_mode) || st.st_nlink != 1 || (st.st_mode & 0777) != 0600) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "schedule file is not a regular file");
        return -1;
    }

    if (st.st_uid != geteuid()) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "schedule file ownership mismatch");
        return -1;
    }

    if (st.st_size < 0 || st.st_size > MAX_FILE_SIZE) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "schedule file exceeds maximum size");
        return -1;
    }

    int fd = openat(dir_fd, basename, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "open schedule file failed: %s", strerror(errno));
        return -1;
    }

    struct stat opened;
    if (fstat(fd, &opened) != 0 || !S_ISREG(opened.st_mode) || opened.st_nlink != 1 ||
        opened.st_uid != geteuid() || (opened.st_mode & 0777) != 0600 ||
        opened.st_dev != st.st_dev || opened.st_ino != st.st_ino ||
        opened.st_size != st.st_size || opened.st_size < 0 || opened.st_size > MAX_FILE_SIZE) {
        close(fd);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "schedule file changed or became unsafe while opening");
        return -1;
    }

    size_t file_size = (size_t)st.st_size;
    char *buf = malloc(file_size + 1);
    if (!buf) {
        close(fd);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "out of memory");
        return -1;
    }

    size_t used = 0;
    while (used < file_size) {
        ssize_t n = read(fd, buf + used, file_size - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
    }
    struct stat after_read;
    int stable = used == file_size && fstat(fd, &after_read) == 0 &&
                 S_ISREG(after_read.st_mode) && after_read.st_nlink == 1 &&
                 after_read.st_uid == geteuid() && (after_read.st_mode & 0777) == 0600 &&
                 after_read.st_dev == opened.st_dev &&
                 after_read.st_ino == opened.st_ino && after_read.st_size == (off_t)used;
    close(fd);
    close(dir_fd);
    if (!stable || memchr(buf, '\0', used) != NULL) {
        free(buf);
        if (err_buf) snprintf(err_buf, err_cap, "schedule file changed or could not be read completely");
        return -1;
    }
    buf[used] = '\0';

    schedule_store_t temp;
    memcpy(&temp, store, sizeof(temp));
    temp.count = 0;

    int version = 0;
    uint32_t counter = 0;
    const char *p = buf;
    if (json_expect_char(&p, '{') != 0 || json_expect_key(&p, "version") != 0 ||
        json_parse_int(&p, &version) != 0 || version != 1 || json_expect_char(&p, ',') != 0 ||
        json_expect_key(&p, "next_id_counter") != 0 || json_parse_uint32(&p, &counter) != 0 ||
        counter == 0 || json_expect_char(&p, ',') != 0 ||
        json_expect_key(&p, "schedules") != 0 || json_expect_char(&p, '[') != 0) goto invalid_state;
    temp.next_id_counter = counter;

    for (;;) {
        json_skip_whitespace(&p);
        if (*p == ']') { p++; break; }
        if (json_expect_char(&p, '{') != 0) goto invalid_state;

        if (temp.count >= MAX_SCHEDULES) goto invalid_capacity;

        schedule_t *item = &temp.items[temp.count];
        memset(item, 0, sizeof(*item));
        int type_val = 0;
        int mask = 0;
        if (json_expect_key(&p, "id") != 0 || json_parse_string(&p, item->id, sizeof(item->id)) != 0 ||
            json_expect_char(&p, ',') != 0 || json_expect_key(&p, "type") != 0 ||
            json_parse_int(&p, &type_val) != 0 || type_val < 1 || type_val > 3 ||
            json_expect_char(&p, ',') != 0 || json_expect_key(&p, "target_time") != 0 ||
            json_parse_time(&p, &item->target_time) != 0 || json_expect_char(&p, ',') != 0 ||
            json_expect_key(&p, "hour") != 0 || json_parse_int(&p, &item->hour) != 0 ||
            json_expect_char(&p, ',') != 0 || json_expect_key(&p, "minute") != 0 ||
            json_parse_int(&p, &item->minute) != 0 || json_expect_char(&p, ',') != 0 ||
            json_expect_key(&p, "days_mask") != 0 || json_parse_int(&p, &mask) != 0 ||
            mask < 0 || mask > 127 || json_expect_char(&p, ',') != 0 ||
            json_expect_key(&p, "duration") != 0 || json_parse_uint32(&p, &item->duration) != 0 ||
            json_expect_char(&p, ',') != 0 || json_expect_key(&p, "tz") != 0 ||
            json_parse_string(&p, item->tz, sizeof(item->tz)) != 0 ||
            json_expect_char(&p, ',') != 0 || json_expect_key(&p, "enabled") != 0 ||
            json_parse_bool(&p, &item->enabled) != 0 || json_expect_char(&p, ',') != 0 ||
            json_expect_key(&p, "last_fired_time") != 0 ||
            json_parse_time(&p, &item->last_fired_time) != 0 || json_expect_char(&p, '}') != 0) {
            goto invalid_state;
        }
        item->type = (sched_type_t)type_val;
        item->days_mask = (uint8_t)mask;
        if (!valid_schedule(item)) goto invalid_state;

        bool duplicate = false;
        for (size_t i = 0; i < temp.count; ++i) {
            if (strcmp(temp.items[i].id, item->id) == 0) { duplicate = true; break; }
        }
        if (duplicate) {
            if (err_buf) snprintf(err_buf, err_cap, "duplicate schedule ID in state file: %s", item->id);
            free(buf);
            return -1;
        }

        temp.count++;
        json_skip_whitespace(&p);
        if (*p == ',') {
            p++;
            json_skip_whitespace(&p);
            if (*p == ']') goto invalid_state;
            continue;
        }
        if (*p == ']') { p++; break; }
        goto invalid_state;
    }

    if (json_expect_char(&p, '}') != 0) goto invalid_state;
    json_skip_whitespace(&p);
    if (*p != '\0') goto invalid_state;

    free(buf);
    memcpy(store, &temp, sizeof(*store));
    return 0;

invalid_capacity:
    free(buf);
    if (err_buf) snprintf(err_buf, err_cap, "schedule state exceeds maximum schedule capacity");
    return -1;
invalid_state:
    free(buf);
    if (err_buf) snprintf(err_buf, err_cap, "malformed or unsafe schedule-state document");
    return -1;
}

int schedule_store_save(const schedule_store_t *store, char *err_buf, size_t err_cap) {
    if (!store || !store->state_file_path[0] || store->state_file_path[0] != '/') {
        if (err_buf) snprintf(err_buf, err_cap, "schedule state path must be absolute and non-empty");
        return -1;
    }

#ifdef IOSCAFFEINATE_TEST_MOCK
    if (getenv("IOSCAFFEINATE_MOCK_FAIL_SCHEDULE_SAVE")) {
        if (err_buf) snprintf(err_buf, err_cap, "mock schedule-state write failure");
        errno = EIO;
        return -1;
    }
#endif

    if (store->count > MAX_SCHEDULES) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule count exceeds maximum capacity");
        return -1;
    }
    for (size_t i = 0; i < store->count; ++i) {
        if (!valid_schedule(&store->items[i])) {
            if (err_buf) snprintf(err_buf, err_cap, "refusing to persist invalid schedule fields");
            return -1;
        }
    }

    char basename[256];
    int dir_fd = open_state_parent(store->state_file_path, basename, sizeof(basename));
    if (dir_fd < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule state parent is unsafe or inaccessible");
        return -1;
    }
    if (strlen(basename) > 200) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "schedule state filename exceeds the safe bound");
        return -1;
    }

    struct stat existing;
    if (fstatat(dir_fd, basename, &existing, AT_SYMLINK_NOFOLLOW) == 0) {
        if (!S_ISREG(existing.st_mode) || existing.st_uid != geteuid() ||
            existing.st_nlink != 1 || (existing.st_mode & 0777) != 0600) {
            close(dir_fd);
            if (err_buf) snprintf(err_buf, err_cap, "refusing to replace an unsafe schedule-state file");
            return -1;
        }
    } else if (errno != ENOENT) {
        int saved = errno;
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "inspect schedule-state destination failed: %s", strerror(saved));
        return -1;
    }

    char tmp_name[256];
    if (snprintf(tmp_name, sizeof(tmp_name), "%s.tmp.%ld", basename, (long)getpid()) >= (int)sizeof(tmp_name)) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "temporary schedule-state filename exceeds the safe bound");
        return -1;
    }

    int fd = openat(dir_fd, tmp_name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) {
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "failed to create temp schedule file: %s", strerror(errno));
        return -1;
    }

    FILE *f = fdopen(fd, "w");
    if (!f) {
        close(fd);
        unlinkat(dir_fd, tmp_name, 0);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "fdopen temp schedule file failed");
        return -1;
    }

    fprintf(f, "{\n  \"version\": 1,\n  \"next_id_counter\": %u,\n  \"schedules\": [\n", store->next_id_counter);
    for (size_t i = 0; i < store->count; ++i) {
        const schedule_t *s = &store->items[i];
        fprintf(f, "    {\n"
                   "      \"id\": \"%s\",\n"
                   "      \"type\": %d,\n"
                   "      \"target_time\": %lld,\n"
                   "      \"hour\": %d,\n"
                   "      \"minute\": %d,\n"
                   "      \"days_mask\": %d,\n"
                   "      \"duration\": %u,\n"
                   "      \"tz\": \"%s\",\n"
                   "      \"enabled\": %s,\n"
                   "      \"last_fired_time\": %lld\n"
                   "    }%s\n",
                s->id, (int)s->type, (long long)s->target_time,
                s->hour, s->minute, (int)s->days_mask, s->duration,
                s->tz, s->enabled ? "true" : "false", (long long)s->last_fired_time,
                (i + 1 < store->count) ? "," : "");
    }
    fprintf(f, "  ]\n}\n");

    if (fflush(f) != 0 || fsync(fileno(f)) != 0) {
        fclose(f);
        unlinkat(dir_fd, tmp_name, 0);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "flush/sync temp schedule file failed");
        return -1;
    }

    if (fclose(f) != 0) {
        unlinkat(dir_fd, tmp_name, 0);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "close temp schedule file failed");
        return -1;
    }

    if (renameat(dir_fd, tmp_name, dir_fd, basename) != 0) {
        int saved = errno;
        unlinkat(dir_fd, tmp_name, 0);
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap, "rename temp schedule file failed: %s", strerror(saved));
        return -1;
    }

    if (fsync(dir_fd) != 0 && errno != EINVAL && errno != ENOTSUP) {
        int saved = errno;
        close(dir_fd);
        if (err_buf) snprintf(err_buf, err_cap,
                              "schedule rename succeeded but directory durability is unconfirmed: %s",
                              strerror(saved));
        return -1;
    }

    close(dir_fd);
    return 0;
}

static int schedule_stores_equal(const schedule_store_t *left, const schedule_store_t *right) {
    if (!left || !right || left->count != right->count ||
        left->next_id_counter != right->next_id_counter) return 0;
    for (size_t i = 0; i < left->count; ++i) {
        const schedule_t *a = &left->items[i], *b = &right->items[i];
        if (strcmp(a->id, b->id) != 0 || a->type != b->type ||
            a->target_time != b->target_time || a->hour != b->hour ||
            a->minute != b->minute || a->days_mask != b->days_mask ||
            a->duration != b->duration || strcmp(a->tz, b->tz) != 0 ||
            a->enabled != b->enabled || a->last_fired_time != b->last_fired_time) return 0;
    }
    return 1;
}

static int schedule_store_persist_transaction(const schedule_store_t *old_store,
                                               const schedule_store_t *new_store,
                                               char *err_buf, size_t err_cap) {
    char save_error[256] = {0};
    int saved = schedule_store_save(new_store, save_error, sizeof(save_error));
    schedule_store_t readback;
    schedule_store_init(&readback, new_store->state_file_path);
    char read_error[256] = {0};
    int loaded = schedule_store_load(&readback, read_error, sizeof(read_error));
    if (saved == 0 && loaded == 0 && schedule_stores_equal(&readback, new_store)) return 0;

    if (loaded == 0 && schedule_stores_equal(&readback, new_store) &&
        !schedule_stores_equal(&readback, old_store)) {
        char rollback_error[256] = {0};
        if (schedule_store_save(old_store, rollback_error, sizeof(rollback_error)) != 0) {
            if (err_buf) snprintf(err_buf, err_cap,
                                  "schedule commit verification failed and prior data rollback failed: %s",
                                  rollback_error);
            return -1;
        }
    }
    if (err_buf) {
        if (saved != 0)
            snprintf(err_buf, err_cap, "schedule persistence failed: %s", save_error);
        else if (loaded != 0)
            snprintf(err_buf, err_cap, "schedule read-back verification failed: %s", read_error);
        else snprintf(err_buf, err_cap, "schedule read-back differs from the requested transaction");
    }
    return -1;
}

int schedule_store_add(schedule_store_t *store, schedule_t *sched, char *err_buf, size_t err_cap) {
    if (!store || !sched) return -1;
    if (store->count >= MAX_SCHEDULES) {
        if (err_buf) snprintf(err_buf, err_cap, "maximum schedule limit (%d) reached", MAX_SCHEDULES);
        return -1;
    }

    schedule_store_t temp;
    memcpy(&temp, store, sizeof(temp));

    if (!sched->id[0]) {
        if (temp.next_id_counter == 0 || temp.next_id_counter == UINT32_MAX) {
            if (err_buf) snprintf(err_buf, err_cap, "schedule ID counter is exhausted");
            return -1;
        }
        snprintf(sched->id, sizeof(sched->id), "sched-%u", temp.next_id_counter++);
    } else {
        for (size_t i = 0; i < temp.count; ++i) {
            if (strcmp(temp.items[i].id, sched->id) == 0) {
                if (err_buf) snprintf(err_buf, err_cap, "schedule ID '%s' already exists", sched->id);
                return -1;
            }
        }
    }

    sched->enabled = true;
    if (!valid_schedule(sched)) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule fields contain invalid or unsafe values");
        return -1;
    }

    if (sched->duration > SCHEDULE_MAX_SESSION_SECONDS) {
        if (err_buf) snprintf(err_buf, err_cap,
                              "new schedule duration exceeds the %u-second policy ceiling",
                              SCHEDULE_MAX_SESSION_SECONDS);
        return -1;
    }
    if (sched->type != SCHED_TYPE_ONETIME) {
        schedule_timezone_resolver_t resolver;
        schedule_resolution_t status = SCHEDULE_RESOLUTION_INVALID;
        int timezone_ok = schedule_timezone_default(sched->tz, &resolver, &status);
        schedule_timezone_resolver_clear(&resolver);
        if (timezone_ok != 0) {
            if (err_buf) snprintf(err_buf, err_cap, "timezone resolution is unavailable: %s",
                                  schedule_resolution_name(status));
            return -1;
        }
    }

    temp.items[temp.count++] = *sched;

    if (schedule_store_persist_transaction(store, &temp, err_buf, err_cap) != 0) {
        return -1;
    }

    memcpy(store, &temp, sizeof(*store));
    return 0;
}

int schedule_store_remove(schedule_store_t *store, const char *id, char *err_buf, size_t err_cap) {
    if (!store || !id) return -1;
    int index = -1;
    for (size_t i = 0; i < store->count; ++i) {
        if (strcmp(store->items[i].id, id) == 0) { index = (int)i; break; }
    }
    if (index < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule ID '%s' not found", id);
        return -1;
    }

    schedule_store_t temp;
    memcpy(&temp, store, sizeof(temp));

    for (size_t i = (size_t)index; i + 1 < temp.count; ++i) {
        temp.items[i] = temp.items[i + 1];
    }
    temp.count--;

    if (schedule_store_persist_transaction(store, &temp, err_buf, err_cap) != 0) {
        return -1;
    }

    memcpy(store, &temp, sizeof(*store));
    return 0;
}

int schedule_store_set_enabled(schedule_store_t *store, const char *id, bool enabled,
                               uint64_t expected_generation, int *changed,
                               char *err_buf, size_t err_cap) {
    if (changed) *changed = 0;
    if (!store || !id) {
        if (err_buf) snprintf(err_buf, err_cap, "invalid schedule enable request");
        return -1;
    }
    if (schedule_store_generation(store) != expected_generation) {
        if (err_buf) snprintf(err_buf, err_cap, "stale schedule generation; reload before editing");
        return -1;
    }
    int index = -1;
    for (size_t i = 0; i < store->count; ++i) {
        if (strcmp(store->items[i].id, id) == 0) { index = (int)i; break; }
    }
    if (index < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule ID '%s' not found", id);
        return -1;
    }
    if (store->items[index].enabled == enabled) return 0;
    schedule_store_t temp;
    memcpy(&temp, store, sizeof(temp));
    temp.items[index].enabled = enabled;
    if (schedule_store_persist_transaction(store, &temp, err_buf, err_cap) != 0) return -1;
    memcpy(store, &temp, sizeof(*store));
    if (changed) *changed = 1;
    return 0;
}

static int days_from_civil(int year, int month, int day, int64_t *days_out) {
    if (!days_out || year < 1970 || year > 9999 || month < 1 || month > 12 ||
        day < 1 || day > 31) return -1;
    int adjusted_year = year - (month <= 2);
    int era = adjusted_year / 400;
    unsigned year_of_era = (unsigned)(adjusted_year - era * 400);
    unsigned shifted_month = (unsigned)(month + (month > 2 ? -3 : 9));
    unsigned day_of_year = (153 * shifted_month + 2) / 5 + (unsigned)day - 1;
    unsigned day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    int64_t result = (int64_t)era * 146097 + (int64_t)day_of_era - 719468;
    int64_t check_year = year;
    int leap = (check_year % 4 == 0 && check_year % 100 != 0) || check_year % 400 == 0;
    static const int month_days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int max_day = month_days[month - 1] + (month == 2 && leap ? 1 : 0);
    if (day > max_day) return -1;
    *days_out = result;
    return 0;
}

static void civil_from_days(int64_t days, int *year_out, int *month_out, int *day_out) {
    days += 719468;
    int64_t era = (days >= 0 ? days : days - 146096) / 146097;
    unsigned day_of_era = (unsigned)(days - era * 146097);
    unsigned year_of_era = (day_of_era - day_of_era / 1460 + day_of_era / 36524 -
                            day_of_era / 146096) / 365;
    int year = (int)year_of_era + (int)(era * 400);
    unsigned day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    unsigned shifted_month = (5 * day_of_year + 2) / 153;
    unsigned day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
    int month = (int)shifted_month + (shifted_month < 10 ? 3 : -9);
    year += month <= 2;
    *year_out = year;
    *month_out = month;
    *day_out = (int)day;
}

static int civil_wall_seconds(int year, int month, int day, int hour, int minute,
                              int second, int64_t *seconds_out) {
    int64_t days = 0;
    if (!seconds_out || days_from_civil(year, month, day, &days) != 0 ||
        hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59)
        return -1;
    if (days > (INT64_MAX - 86399) / 86400 || days < INT64_MIN / 86400) return -1;
    *seconds_out = days * 86400 + hour * 3600 + minute * 60 + second;
    return 0;
}

static int time_to_i64(time_t value, int64_t *out) {
    if (!out) return -1;
    int64_t converted = (int64_t)value;
    if ((time_t)converted != value) return -1;
    *out = converted;
    return 0;
}

static int i64_to_time(int64_t value, time_t *out) {
    if (!out) return -1;
    time_t converted = (time_t)value;
    if ((int64_t)converted != value) return -1;
    *out = converted;
    return 0;
}

static int time_add_seconds(time_t start, uint32_t seconds, time_t *end) {
    int64_t value = 0;
    if (time_to_i64(start, &value) != 0 || value < 0 ||
        value > INT64_MAX - (int64_t)seconds) return -1;
    return i64_to_time(value + seconds, end);
}

static uint64_t schedule_revision(const schedule_t *schedule);

static int weekday_for_days(int64_t days) {
    int weekday = (int)((days + 4) % 7);
    return weekday < 0 ? weekday + 7 : weekday;
}

static int utc_localtime(void *context, time_t instant, struct tm *local) {
    (void)context;
    return gmtime_r(&instant, local) ? 0 : -1;
}

static int system_localtime(void *context, time_t instant, struct tm *local) {
    (void)context;
    return localtime_r(&instant, local) ? 0 : -1;
}

#ifdef __APPLE__
typedef struct {
    CFTimeZoneRef timezone;
    CFCalendarRef calendar;
} cf_timezone_context_t;

static int corefoundation_localtime(void *context, time_t instant, struct tm *local) {
    cf_timezone_context_t *timezone = context;
    int64_t epoch = 0;
    if (!timezone || !timezone->calendar || !local || time_to_i64(instant, &epoch) != 0)
        return -1;
    CFAbsoluteTime absolute = (CFAbsoluteTime)epoch - kCFAbsoluteTimeIntervalSince1970;
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
    if (!CFCalendarDecomposeAbsoluteTime(timezone->calendar, absolute, "yMdHms",
                                         &year, &month, &day, &hour, &minute, &second) ||
        year < 1970 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31 ||
        hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59)
        return -1;
    memset(local, 0, sizeof(*local));
    local->tm_year = year - 1900;
    local->tm_mon = month - 1;
    local->tm_mday = day;
    local->tm_hour = hour;
    local->tm_min = minute;
    local->tm_sec = second;
    local->tm_isdst = CFTimeZoneIsDaylightSavingTime(
        timezone->timezone, absolute) ? 1 : 0;
    return 0;
}

static void corefoundation_timezone_destroy(void *context) {
    cf_timezone_context_t *timezone = context;
    if (!timezone) return;
    if (timezone->calendar) CFRelease(timezone->calendar);
    if (timezone->timezone) CFRelease(timezone->timezone);
    free(timezone);
}

static int corefoundation_timezone_create(const char *name, int system_timezone,
                                          schedule_timezone_resolver_t *resolver) {
    CFTimeZoneRef timezone = NULL;
    CFCalendarRef calendar = NULL;
    CFStringRef cf_name = NULL;
    if (system_timezone) timezone = CFTimeZoneCopySystem();
    else {
        cf_name = CFStringCreateWithCString(kCFAllocatorDefault, name, kCFStringEncodingUTF8);
        if (!cf_name) return -2;
        timezone = CFTimeZoneCreateWithName(kCFAllocatorDefault, cf_name, false);
        if (!timezone) {
            CFArrayRef known_names = CFTimeZoneCopyKnownNames();
            int known = known_names && CFArrayContainsValue(
                known_names, CFRangeMake(0, CFArrayGetCount(known_names)), cf_name);
            if (known_names) CFRelease(known_names);
            CFRelease(cf_name);
            return known ? -1 : -2;
        }
    }
    if (cf_name) CFRelease(cf_name);
    if (!timezone) return -1;
    calendar = CFCalendarCreateWithIdentifier(kCFAllocatorDefault, kCFGregorianCalendar);
    if (!calendar) {
        CFRelease(timezone);
        return -1;
    }
    CFCalendarSetTimeZone(calendar, timezone);
    CFStringRef effective_name = CFTimeZoneGetName(timezone);
    char effective[TZ_LEN] = {0};
    if (!effective_name || !CFStringGetCString(effective_name, effective,
                                               sizeof(effective), kCFStringEncodingUTF8) ||
        !effective[0]) {
        CFRelease(calendar);
        CFRelease(timezone);
        return -1;
    }
    cf_timezone_context_t *context = calloc(1, sizeof(*context));
    if (!context) {
        CFRelease(calendar);
        CFRelease(timezone);
        return -1;
    }
    context->timezone = timezone;
    context->calendar = calendar;
    resolver->localtime = corefoundation_localtime;
    resolver->context = context;
    resolver->destroy_context = corefoundation_timezone_destroy;
    snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "%s", effective);
    return 0;
}
#endif

void schedule_timezone_resolver_clear(schedule_timezone_resolver_t *resolver) {
    if (!resolver) return;
    if (resolver->destroy_context) resolver->destroy_context(resolver->context);
    memset(resolver, 0, sizeof(*resolver));
}

int schedule_timezone_default(const char *tz, schedule_timezone_resolver_t *resolver,
                              schedule_resolution_t *status) {
    if (status) *status = SCHEDULE_RESOLUTION_INVALID;
    if (!resolver) return -1;
    memset(resolver, 0, sizeof(*resolver));
    if (!tz || strlen(tz) >= TZ_LEN) return -1;
    if (!tz[0]) {
        /* Resolve the OS timezone as an immutable per-evaluation object. */
#ifdef __APPLE__
        int system_status = corefoundation_timezone_create(NULL, 1, resolver);
        if (system_status == 0) {
            if (status) *status = SCHEDULE_RESOLUTION_OK;
            return 0;
        }
        resolver->unavailable_reason = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
        snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone),
                 "SYSTEM_LOCAL_UNVERIFIED");
        if (status) *status = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
        return -1;
#else
        /* On non-Darwin hosts the process environment can override localtime.
         * Tests use injected deterministic timezone fixtures instead. */
        const char *override = getenv("TZ");
        if (override) {
            if (status) *status = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
            resolver->unavailable_reason = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
            snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone),
                     "SYSTEM_LOCAL_UNVERIFIED");
            return -1;
        }
        resolver->localtime = system_localtime;
        snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "SYSTEM_LOCAL");
        if (status) *status = SCHEDULE_RESOLUTION_OK;
        return 0;
#endif
    }
    if (strcmp(tz, "UTC") == 0 || strcmp(tz, "Etc/UTC") == 0 ||
        strcmp(tz, "GMT") == 0 || strcmp(tz, "Etc/GMT") == 0) {
        resolver->localtime = utc_localtime;
        snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "UTC");
        if (status) *status = SCHEDULE_RESOLUTION_OK;
        return 0;
    }
    schedule_t timezone_check = {0};
    snprintf(timezone_check.id, sizeof(timezone_check.id), "timezone-check");
    snprintf(timezone_check.tz, sizeof(timezone_check.tz), "%s", tz);
    if (!valid_schedule_text(&timezone_check)) return -1;
#ifdef __APPLE__
    int timezone_status = corefoundation_timezone_create(tz, 0, resolver);
    if (timezone_status == 0) {
        if (status) *status = SCHEDULE_RESOLUTION_OK;
        return 0;
    }
    resolver->unavailable_reason = timezone_status == -2
        ? SCHEDULE_RESOLUTION_INVALID : SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
    snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "%s", tz);
    if (status) *status = resolver->unavailable_reason;
    return -1;
#else
    /* Linux hosts are not a compatibility oracle for iOS. Keep arbitrary
     * IANA definitions gated unless a platform-specific resolver is compiled. */
    resolver->unavailable_reason = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
    snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "%s", tz);
    if (status) *status = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
    return -1;
#endif
}

static int local_tm_to_wall(const struct tm *local, int64_t *wall_out) {
    if (!local || !wall_out) return -1;
    return civil_wall_seconds(local->tm_year + 1900, local->tm_mon + 1, local->tm_mday,
                              local->tm_hour, local->tm_min, local->tm_sec, wall_out);
}

static int local_matches(const schedule_timezone_resolver_t *resolver, time_t instant,
                         int year, int month, int day, int hour, int minute) {
    struct tm local;
    if (!resolver->localtime || resolver->localtime(resolver->context, instant, &local) != 0)
        return 0;
    return local.tm_year + 1900 == year && local.tm_mon + 1 == month &&
           local.tm_mday == day && local.tm_hour == hour && local.tm_min == minute &&
           local.tm_sec == 0;
}

static int resolve_local_date(const schedule_timezone_resolver_t *resolver,
                              int year, int month, int day, int hour, int minute,
                              uint32_t duration, schedule_occurrence_t *occurrence) {
    int64_t wall = 0;
    if (!resolver || !resolver->localtime || !occurrence ||
        civil_wall_seconds(year, month, day, hour, minute, 0, &wall) != 0) return -1;

    int64_t offsets[16];
    size_t offset_count = 0;
    const int64_t radius = 3 * 86400;
    const int64_t step = 1800;
    for (int64_t delta = -radius; delta <= radius; delta += step) {
        if ((delta < 0 && wall < INT64_MIN - delta) ||
            (delta > 0 && wall > INT64_MAX - delta)) continue;
        time_t sample = 0;
        if (i64_to_time(wall + delta, &sample) != 0) continue;
        struct tm local;
        if (resolver->localtime(resolver->context, sample, &local) != 0) continue;
        int64_t local_wall = 0;
        if (local_tm_to_wall(&local, &local_wall) != 0) continue;
        int64_t instant = 0;
        if (time_to_i64(sample, &instant) != 0) continue;
        int64_t offset = local_wall - instant;
        int known = 0;
        for (size_t i = 0; i < offset_count; ++i) if (offsets[i] == offset) known = 1;
        if (!known) {
            if (offset_count == sizeof(offsets) / sizeof(offsets[0])) return -1;
            offsets[offset_count++] = offset;
        }
    }
    if (offset_count == 0) return -1;

    time_t matches[8];
    size_t match_count = 0;
    for (size_t i = 0; i < offset_count; ++i) {
        if ((offsets[i] < 0 && wall > INT64_MAX + offsets[i]) ||
            (offsets[i] > 0 && wall < INT64_MIN + offsets[i])) continue;
        time_t candidate = 0;
        if (i64_to_time(wall - offsets[i], &candidate) != 0 ||
            !local_matches(resolver, candidate, year, month, day, hour, minute)) continue;
        int duplicate = 0;
        for (size_t j = 0; j < match_count; ++j) if (matches[j] == candidate) duplicate = 1;
        if (!duplicate) {
            if (match_count == sizeof(matches) / sizeof(matches[0])) return -1;
            matches[match_count++] = candidate;
        }
    }

    memset(occurrence, 0, sizeof(*occurrence));
    occurrence->year = year;
    occurrence->month = month;
    occurrence->day = day;
    occurrence->hour = hour;
    occurrence->minute = minute;
    snprintf(occurrence->effective_timezone, sizeof(occurrence->effective_timezone), "%s",
             resolver->effective_timezone);
    occurrence->matching_instants = (unsigned)match_count;
    if (match_count == 0) {
        occurrence->resolution = SCHEDULE_RESOLUTION_DST_NONEXISTENT_LOCAL_TIME;
        return 1;
    }
    for (size_t i = 0; i < match_count; ++i) {
        for (size_t j = i + 1; j < match_count; ++j) {
            if (matches[j] < matches[i]) {
                time_t swap = matches[i]; matches[i] = matches[j]; matches[j] = swap;
            }
        }
    }
    occurrence->start = matches[0];
    if (time_add_seconds(occurrence->start, duration, &occurrence->end) != 0) {
        occurrence->resolution = SCHEDULE_RESOLUTION_INVALID;
        return -1;
    }
    occurrence->resolution = match_count > 1 ? SCHEDULE_RESOLUTION_AMBIGUOUS_FIRST
                                             : SCHEDULE_RESOLUTION_OK;
    return 0;
}

const char *schedule_resolution_name(schedule_resolution_t value) {
    switch (value) {
        case SCHEDULE_RESOLUTION_OK: return "RESOLVED";
        case SCHEDULE_RESOLUTION_AMBIGUOUS_FIRST: return "DST_AMBIGUOUS_FIRST_OCCURRENCE";
        case SCHEDULE_RESOLUTION_DST_NONEXISTENT_LOCAL_TIME: return "DST_NONEXISTENT_LOCAL_TIME";
        case SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED: return "TIMEZONE_UNVERIFIED";
        case SCHEDULE_RESOLUTION_INVALID: return "INVALID";
    }
    return "INVALID";
}

const char *schedule_outcome_name(schedule_outcome_t value) {
    switch (value) {
        case SCHEDULE_OUTCOME_UPCOMING: return "UPCOMING";
        case SCHEDULE_OUTCOME_ACTIVE_WINDOW: return "ACTIVE_WINDOW";
        case SCHEDULE_OUTCOME_EXPIRED: return "EXPIRED";
        case SCHEDULE_OUTCOME_MISSED: return "MISSED";
        case SCHEDULE_OUTCOME_ALREADY_FIRED: return "ALREADY_FIRED";
        case SCHEDULE_OUTCOME_CONFLICT: return "CONFLICT";
        case SCHEDULE_OUTCOME_BLOCKED_RECOVERY: return "BLOCKED_RECOVERY";
        case SCHEDULE_OUTCOME_BLOCKED_POLICY: return "BLOCKED_POLICY";
        case SCHEDULE_OUTCOME_RESOURCE_UNAVAILABLE: return "RESOURCE_UNAVAILABLE";
        case SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED: return "TIMEZONE_UNVERIFIED";
        case SCHEDULE_OUTCOME_INCOMPLETE: return "INCOMPLETE";
    }
    return "INCOMPLETE";
}

int schedule_analyze_with_resolver(const schedule_t *schedule, time_t reference,
                                   const schedule_timezone_resolver_t *resolver,
                                   schedule_analysis_t *analysis) {
    if (!schedule || !analysis || reference < 0 || !valid_schedule(schedule)) return -1;
    memset(analysis, 0, sizeof(*analysis));
    analysis->outcome = SCHEDULE_OUTCOME_INCOMPLETE;

    if (schedule->type == SCHED_TYPE_ONETIME) {
        schedule_occurrence_t occurrence;
        memset(&occurrence, 0, sizeof(occurrence));
        occurrence.start = schedule->target_time;
        struct tm utc;
        if (!gmtime_r(&occurrence.start, &utc)) return -1;
        snprintf(occurrence.schedule_id, sizeof(occurrence.schedule_id), "%s", schedule->id);
        occurrence.schedule_revision = schedule_revision(schedule);
        occurrence.year = utc.tm_year + 1900;
        occurrence.month = utc.tm_mon + 1;
        occurrence.day = utc.tm_mday;
        occurrence.hour = utc.tm_hour;
        occurrence.minute = utc.tm_min;
        snprintf(occurrence.effective_timezone, sizeof(occurrence.effective_timezone), "UTC");
        if (time_add_seconds(occurrence.start, schedule->duration, &occurrence.end) != 0) return -1;
        occurrence.resolution = SCHEDULE_RESOLUTION_OK;
        analysis->occurrence = occurrence;
        analysis->has_occurrence = 1;
        if (reference >= occurrence.start && reference < occurrence.end) {
            analysis->outcome = schedule->last_fired_time >= occurrence.end
                ? SCHEDULE_OUTCOME_ALREADY_FIRED : SCHEDULE_OUTCOME_ACTIVE_WINDOW;
        } else if (reference < occurrence.start) {
            analysis->outcome = schedule->last_fired_time >= occurrence.end
                ? SCHEDULE_OUTCOME_ALREADY_FIRED : SCHEDULE_OUTCOME_UPCOMING;
            if (schedule->last_fired_time < occurrence.start) {
                analysis->next = occurrence;
                analysis->has_next = 1;
            }
        } else {
            analysis->outcome = schedule->last_fired_time >= occurrence.end
                ? SCHEDULE_OUTCOME_ALREADY_FIRED : SCHEDULE_OUTCOME_EXPIRED;
        }
        return 0;
    }

    if (!resolver || !resolver->localtime) {
        analysis->outcome = resolver && resolver->unavailable_reason == SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED
            ? SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED : SCHEDULE_OUTCOME_INCOMPLETE;
        return -1;
    }
    struct tm local_now;
    if (resolver->localtime(resolver->context, reference, &local_now) != 0) {
        analysis->outcome = SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED;
        return -1;
    }
    int64_t today = 0;
    if (days_from_civil(local_now.tm_year + 1900, local_now.tm_mon + 1, local_now.tm_mday,
                        &today) != 0) return -1;

    schedule_occurrence_t best_recent;
    schedule_occurrence_t best_future;
    schedule_occurrence_t best_active;
    schedule_occurrence_t best_already;
    int have_recent = 0, have_future = 0, have_active = 0, have_already = 0;
    for (int day_offset = -2; day_offset <= 14; ++day_offset) {
        int year = 0, month = 0, day = 0;
        civil_from_days(today + day_offset, &year, &month, &day);
        int64_t civil_day = today + day_offset;
        if (schedule->type == SCHED_TYPE_WEEKLY &&
            !(schedule->days_mask & (1U << weekday_for_days(civil_day)))) continue;

        schedule_occurrence_t occurrence;
        int resolved = resolve_local_date(resolver, year, month, day, schedule->hour,
                                          schedule->minute, schedule->duration, &occurrence);
        if (resolved < 0) {
            analysis->outcome = SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED;
            return -1;
        }
        if (resolved > 0) {
            analysis->saw_nonexistent_local_time = 1;
            continue;
        }
        snprintf(occurrence.schedule_id, sizeof(occurrence.schedule_id), "%s", schedule->id);
        occurrence.schedule_revision = schedule_revision(schedule);
        if (occurrence.start <= reference && occurrence.end > reference) {
            if (!have_active || occurrence.start < best_active.start) {
                best_active = occurrence;
                have_active = 1;
            }
        }
        if (occurrence.start <= reference && (!have_recent || occurrence.start > best_recent.start)) {
            best_recent = occurrence;
            have_recent = 1;
        }
        if (occurrence.start > reference && schedule->last_fired_time < occurrence.start &&
            (!have_future || occurrence.start < best_future.start)) {
            best_future = occurrence;
            have_future = 1;
        }
        if (occurrence.start >= reference && schedule->last_fired_time >= occurrence.end &&
            (!have_already || occurrence.start < best_already.start)) {
            best_already = occurrence;
            have_already = 1;
        }
    }

    if (have_future) {
        analysis->next = best_future;
        analysis->has_next = 1;
    }
    if (have_active) {
        analysis->occurrence = best_active;
        analysis->has_occurrence = 1;
        analysis->outcome = schedule->last_fired_time >= best_active.end
            ? SCHEDULE_OUTCOME_ALREADY_FIRED : SCHEDULE_OUTCOME_ACTIVE_WINDOW;
    } else if (have_already) {
        analysis->occurrence = best_already;
        analysis->has_occurrence = 1;
        analysis->outcome = SCHEDULE_OUTCOME_ALREADY_FIRED;
    } else if (have_recent) {
        analysis->occurrence = best_recent;
        analysis->has_occurrence = 1;
        if (schedule->last_fired_time >= best_recent.end)
            analysis->outcome = SCHEDULE_OUTCOME_ALREADY_FIRED;
        else
            analysis->outcome = SCHEDULE_OUTCOME_MISSED;
    } else if (have_future) {
        analysis->occurrence = best_future;
        analysis->has_occurrence = 1;
        analysis->outcome = SCHEDULE_OUTCOME_UPCOMING;
    } else if (analysis->saw_nonexistent_local_time) {
        analysis->outcome = SCHEDULE_OUTCOME_MISSED;
    }
    return 0;
}

int schedule_analyze(const schedule_t *schedule, time_t reference,
                     schedule_analysis_t *analysis) {
    if (!schedule || !analysis) return -1;
    schedule_timezone_resolver_t resolver;
    schedule_resolution_t status = SCHEDULE_RESOLUTION_INVALID;
    if (schedule->type == SCHED_TYPE_ONETIME) {
        return schedule_analyze_with_resolver(schedule, reference, NULL, analysis);
    }
    if (schedule_timezone_default(schedule->tz, &resolver, &status) != 0) {
        memset(analysis, 0, sizeof(*analysis));
        analysis->outcome = status == SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED
            ? SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED : SCHEDULE_OUTCOME_INCOMPLETE;
        schedule_timezone_resolver_clear(&resolver);
        return -1;
    }
    int result = schedule_analyze_with_resolver(schedule, reference, &resolver, analysis);
    schedule_timezone_resolver_clear(&resolver);
    return result;
}

void schedule_store_evaluate(schedule_store_t *store,
                             time_t now_wall,
                             int *active_index,
                             uint32_t *active_remaining,
                             int *next_index,
                             time_t *next_start) {
    if (active_index) *active_index = -1;
    if (active_remaining) *active_remaining = 0;
    if (next_index) *next_index = -1;
    if (next_start) *next_start = 0;
    if (!store) return;

    int found_active = -1;
    uint32_t remaining = 0;
    int found_next = -1;
    time_t earliest_next = 0;
    for (size_t i = 0; i < store->count; ++i) {
        schedule_t *schedule = &store->items[i];
        if (!schedule->enabled) continue;
        schedule_analysis_t analysis;
        if (schedule_analyze(schedule, now_wall, &analysis) != 0) continue;
        if (analysis.outcome == SCHEDULE_OUTCOME_ACTIVE_WINDOW && analysis.has_occurrence) {
            if (found_active >= 0) {
                found_active = -2; /* Ambiguous owner: never choose by storage order. */
                remaining = 0;
            } else if (found_active != -2) {
                found_active = (int)i;
                int64_t end = 0, now = 0;
                if (time_to_i64(analysis.occurrence.end, &end) == 0 &&
                    time_to_i64(now_wall, &now) == 0 && end > now)
                    remaining = (uint32_t)(end - now);
            }
        }
        if (analysis.has_next && (!earliest_next || analysis.next.start < earliest_next)) {
            earliest_next = analysis.next.start;
            found_next = (int)i;
        }
    }
    if (active_index) *active_index = found_active >= 0 ? found_active : -1;
    if (active_remaining) *active_remaining = found_active >= 0 ? remaining : 0;
    if (next_index) *next_index = found_next;
    if (next_start) *next_start = earliest_next;
}

typedef struct {
    time_t start;
    time_t end;
} schedule_window_t;

typedef struct {
    schedule_window_t *items;
    size_t count;
    int incomplete;
} schedule_window_set_t;

#define SCHEDULE_MAX_HORIZON_DAYS 370
#define SCHEDULE_MAX_WINDOWS 400

static int compare_windows(const void *left, const void *right) {
    const schedule_window_t *a = left;
    const schedule_window_t *b = right;
    if (a->start < b->start) return -1;
    if (a->start > b->start) return 1;
    if (a->end < b->end) return -1;
    if (a->end > b->end) return 1;
    return 0;
}

static int default_timezone_provider(void *context, const char *tz,
                                     schedule_timezone_resolver_t *resolver,
                                     schedule_resolution_t *status) {
    (void)context;
    return schedule_timezone_default(tz, resolver, status);
}

static int enumerate_windows(const schedule_t *schedule, time_t range_start,
                             time_t range_end, unsigned horizon_days,
                             schedule_timezone_provider_fn provider, void *provider_context,
                             schedule_window_set_t *set) {
    if (!schedule || !set || !schedule->enabled || !valid_schedule(schedule)) return 0;
    if (schedule->type == SCHED_TYPE_ONETIME) {
        time_t end = 0;
        if (time_add_seconds(schedule->target_time, schedule->duration, &end) != 0) {
            set->incomplete = 1;
            return -1;
        }
        if (schedule->target_time < range_end && end > range_start) {
            if (set->count == SCHEDULE_MAX_WINDOWS) return -1;
            set->items[set->count++] = (schedule_window_t){schedule->target_time, end};
        }
        return 0;
    }

    schedule_timezone_resolver_t resolver;
    schedule_resolution_t timezone_status = SCHEDULE_RESOLUTION_INVALID;
    memset(&resolver, 0, sizeof(resolver));
    if (!provider || provider(provider_context, schedule->tz, &resolver, &timezone_status) != 0 ||
        !resolver.localtime) {
        schedule_timezone_resolver_clear(&resolver);
        set->incomplete = 1;
        return -1;
    }
    struct tm local_start;
    if (resolver.localtime(resolver.context, range_start, &local_start) != 0) {
        schedule_timezone_resolver_clear(&resolver);
        set->incomplete = 1;
        return -1;
    }
    int64_t start_day = 0;
    if (days_from_civil(local_start.tm_year + 1900, local_start.tm_mon + 1,
                        local_start.tm_mday, &start_day) != 0) {
        schedule_timezone_resolver_clear(&resolver);
        set->incomplete = 1;
        return -1;
    }
    for (int offset = -2; offset <= (int)horizon_days + 4; ++offset) {
        int year = 0, month = 0, day = 0;
        int64_t civil_day = start_day + offset;
        civil_from_days(civil_day, &year, &month, &day);
        if (schedule->type == SCHED_TYPE_WEEKLY &&
            !(schedule->days_mask & (1U << weekday_for_days(civil_day)))) continue;
        schedule_occurrence_t occurrence;
        int resolved = resolve_local_date(&resolver, year, month, day, schedule->hour,
                                          schedule->minute, schedule->duration, &occurrence);
        if (resolved < 0) {
            schedule_timezone_resolver_clear(&resolver);
            set->incomplete = 1;
            return -1;
        }
        if (resolved > 0) continue; /* A DST gap is a skipped logical occurrence. */
        if (occurrence.start < range_end && occurrence.end > range_start) {
            if (set->count == SCHEDULE_MAX_WINDOWS) {
                schedule_timezone_resolver_clear(&resolver);
                set->incomplete = 1;
                return -1;
            }
            set->items[set->count++] = (schedule_window_t){occurrence.start, occurrence.end};
        }
    }
    qsort(set->items, set->count, sizeof(set->items[0]), compare_windows);
    schedule_timezone_resolver_clear(&resolver);
    return 0;
}

static int same_definition(const schedule_t *left, const schedule_t *right) {
    return left->type == right->type && left->target_time == right->target_time &&
           left->hour == right->hour && left->minute == right->minute &&
           left->days_mask == right->days_mask && left->duration == right->duration &&
           strcmp(left->tz, right->tz) == 0;
}

static void record_conflict(schedule_conflict_t *conflicts, size_t cap, size_t *count,
                            size_t first, size_t second, int duplicate,
                            schedule_window_t a, schedule_window_t b) {
    if (*count < cap && conflicts) {
        conflicts[*count].duplicate_definition = duplicate;
        conflicts[*count].first_index = first;
        conflicts[*count].second_index = second;
        conflicts[*count].first_start = a.start;
        conflicts[*count].first_end = a.end;
        conflicts[*count].second_start = b.start;
        conflicts[*count].second_end = b.end;
    }
    (*count)++;
}

int schedule_store_find_conflicts_with_provider(
    const schedule_store_t *store, time_t reference, unsigned horizon_days,
    schedule_timezone_provider_fn provider, void *provider_context,
    schedule_conflict_t *conflicts, size_t conflict_cap, size_t *conflict_count,
    int *analysis_incomplete) {
    if (conflict_count) *conflict_count = 0;
    if (analysis_incomplete) *analysis_incomplete = 0;
    if (!store || reference < 0 || store->count > MAX_SCHEDULES ||
        horizon_days == 0 || horizon_days > SCHEDULE_MAX_HORIZON_DAYS ||
        (!conflicts && conflict_cap != 0)) return -1;
    int64_t reference_i64 = 0;
    if (time_to_i64(reference, &reference_i64) != 0 ||
        reference_i64 > INT64_MAX - (int64_t)horizon_days * 86400) return -1;
    int64_t begin_i64 = reference_i64 > 86400 ? reference_i64 - 86400 : 0;
    time_t range_start = 0, range_end = 0;
    if (i64_to_time(begin_i64, &range_start) != 0 ||
        i64_to_time(reference_i64 + (int64_t)horizon_days * 86400, &range_end) != 0) return -1;

    schedule_window_set_t *sets = calloc(store->count ? store->count : 1, sizeof(*sets));
    if (!sets) return -1;
    for (size_t i = 0; i < store->count; ++i) {
        sets[i].items = calloc(SCHEDULE_MAX_WINDOWS, sizeof(*sets[i].items));
        if (!sets[i].items) {
            for (size_t j = 0; j < i; ++j) free(sets[j].items);
            free(sets);
            return -1;
        }
        if (enumerate_windows(&store->items[i], range_start, range_end, horizon_days,
                              provider, provider_context, &sets[i]) != 0) {
            sets[i].incomplete = 1;
        }
        if (sets[i].incomplete && analysis_incomplete) *analysis_incomplete = 1;
    }

    size_t found = 0;
    schedule_window_t no_window = {0, 0};
    for (size_t i = 0; i < store->count; ++i) {
        if (!store->items[i].enabled) continue;
        for (size_t j = i; j < store->count; ++j) {
            if (!store->items[j].enabled) continue;
            if (i < j && same_definition(&store->items[i], &store->items[j])) {
                schedule_window_t a = sets[i].count ? sets[i].items[0] : no_window;
                schedule_window_t b = sets[j].count ? sets[j].items[0] : no_window;
                record_conflict(conflicts, conflict_cap, &found, i, j, 1, a, b);
                continue;
            }
            int overlap_found = 0;
            if (i == j) {
                for (size_t a = 0; a < sets[i].count && !overlap_found; ++a) {
                    for (size_t b = a + 1; b < sets[i].count; ++b) {
                        if (sets[i].items[b].start >= sets[i].items[a].end) break;
                        if (sets[i].items[a].start < sets[i].items[b].end &&
                            sets[i].items[b].start < sets[i].items[a].end) {
                            record_conflict(conflicts, conflict_cap, &found, i, i, 0,
                                            sets[i].items[a], sets[i].items[b]);
                            overlap_found = 1;
                            break;
                        }
                    }
                }
            } else {
                size_t a = 0, b = 0;
                while (a < sets[i].count && b < sets[j].count) {
                    schedule_window_t first = sets[i].items[a];
                    schedule_window_t second = sets[j].items[b];
                    if (first.start < second.end && second.start < first.end) {
                        record_conflict(conflicts, conflict_cap, &found, i, j, 0, first, second);
                        overlap_found = 1;
                        break;
                    }
                    if (first.end <= second.start) a++;
                    else b++;
                }
            }
            (void)overlap_found;
        }
    }
    for (size_t i = 0; i < store->count; ++i) free(sets[i].items);
    free(sets);
    if (conflict_count) *conflict_count = found;
    if (found > conflict_cap && conflicts) return -1;
    return 0;
}

int schedule_store_find_conflicts(const schedule_store_t *store, time_t reference,
                                  unsigned horizon_days, schedule_conflict_t *conflicts,
                                  size_t conflict_cap, size_t *conflict_count,
                                  int *analysis_incomplete) {
    return schedule_store_find_conflicts_with_provider(store, reference, horizon_days,
                                                       default_timezone_provider, NULL,
                                                       conflicts, conflict_cap,
                                                       conflict_count, analysis_incomplete);
}

static uint64_t generation_hash_byte(uint64_t hash, unsigned char value) {
    return (hash ^ value) * UINT64_C(1099511628211);
}

static uint64_t generation_hash_u64(uint64_t hash, uint64_t value) {
    for (unsigned shift = 0; shift < 64; shift += 8)
        hash = generation_hash_byte(hash, (unsigned char)(value >> shift));
    return hash;
}

static uint64_t generation_hash_text(uint64_t hash, const char *value) {
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p)
        hash = generation_hash_byte(hash, *p);
    return generation_hash_byte(hash, 0);
}

uint64_t schedule_store_generation(const schedule_store_t *store) {
    if (!store) return 0;
    uint64_t hash = UINT64_C(1469598103934665603);
    hash = generation_hash_u64(hash, store->count);
    hash = generation_hash_u64(hash, store->next_id_counter);
    for (size_t i = 0; i < store->count && i < MAX_SCHEDULES; ++i) {
        const schedule_t *item = &store->items[i];
        hash = generation_hash_text(hash, item->id);
        hash = generation_hash_u64(hash, (uint64_t)item->type);
        hash = generation_hash_u64(hash, (uint64_t)item->target_time);
        hash = generation_hash_u64(hash, (uint64_t)item->hour);
        hash = generation_hash_u64(hash, (uint64_t)item->minute);
        hash = generation_hash_u64(hash, item->days_mask);
        hash = generation_hash_u64(hash, item->duration);
        hash = generation_hash_text(hash, item->tz);
        hash = generation_hash_u64(hash, item->enabled ? 1 : 0);
        hash = generation_hash_u64(hash, (uint64_t)item->last_fired_time);
    }
    return hash;
}

static uint64_t schedule_revision(const schedule_t *schedule) {
    if (!schedule) return 0;
    uint64_t hash = UINT64_C(1469598103934665603);
    hash = generation_hash_text(hash, schedule->id);
    hash = generation_hash_u64(hash, (uint64_t)schedule->type);
    hash = generation_hash_u64(hash, (uint64_t)schedule->target_time);
    hash = generation_hash_u64(hash, (uint64_t)schedule->hour);
    hash = generation_hash_u64(hash, (uint64_t)schedule->minute);
    hash = generation_hash_u64(hash, schedule->days_mask);
    hash = generation_hash_u64(hash, schedule->duration);
    hash = generation_hash_text(hash, schedule->tz);
    hash = generation_hash_u64(hash, schedule->enabled ? 1 : 0);
    return hash;
}

int schedule_occurrence_identity(const schedule_occurrence_t *occurrence,
                                 char *out, size_t cap) {
    if (!occurrence || !out || cap == 0 || !occurrence->schedule_id[0] ||
        !occurrence->effective_timezone[0]) return -1;
    char start[32] = {0}, end[32] = {0};
    if (format_iso8601_utc(occurrence->start, start, sizeof(start)) < 0 ||
        format_iso8601_utc(occurrence->end, end, sizeof(end)) < 0) return -1;
    int n = snprintf(out, cap,
                     "%s@%016llx:%04d-%02d-%02dT%02d:%02d[%s]:%s:%s..%s",
                     occurrence->schedule_id,
                     (unsigned long long)occurrence->schedule_revision,
                     occurrence->year, occurrence->month, occurrence->day,
                     occurrence->hour, occurrence->minute,
                     occurrence->effective_timezone,
                     schedule_resolution_name(occurrence->resolution), start, end);
    return n < 0 || (size_t)n >= cap ? -1 : n;
}

int schedule_mark_fired(schedule_store_t *store, int index, time_t occurrence_start,
                        char *err_buf, size_t err_cap) {
    if (!store || index < 0 || (size_t)index >= store->count) {
        if (err_buf) snprintf(err_buf, err_cap, "invalid schedule index");
        return -1;
    }

    time_t previous = store->items[index].last_fired_time;
    time_t occurrence_end = 0;
    if (time_add_seconds(occurrence_start, store->items[index].duration,
                         &occurrence_end) != 0) {
        if (err_buf) snprintf(err_buf, err_cap, "occurrence end overflows the supported time range");
        return -1;
    }
    if (occurrence_end <= previous) return 0;
    store->items[index].last_fired_time = occurrence_end;
    if (schedule_store_save(store, err_buf, err_cap) != 0) {
        store->items[index].last_fired_time = previous;
        return -1;
    }
    return 0;
}
