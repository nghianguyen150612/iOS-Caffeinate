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

#define MAX_FILE_SIZE 65536

static void set_tz_env(const char *tz) {
    if (tz && *tz) {
        setenv("TZ", tz, 1);
    } else {
        unsetenv("TZ");
    }
    tzset();
}

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

    close(dir_fd);
    return 0;
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

    if (sched->tz[0]) {
        const char *old_tz = getenv("TZ");
        char old_tz_buf[128] = {0};
        if (old_tz) snprintf(old_tz_buf, sizeof(old_tz_buf), "%s", old_tz);

        set_tz_env(sched->tz);
        if (old_tz) set_tz_env(old_tz_buf);
        else set_tz_env(NULL);
    }

    temp.items[temp.count++] = *sched;

    if (schedule_store_save(&temp, err_buf, err_cap) != 0) {
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

    if (schedule_store_save(&temp, err_buf, err_cap) != 0) {
        return -1;
    }

    memcpy(store, &temp, sizeof(*store));
    return 0;
}

static void get_next_recurring_occurrence(const schedule_t *sched, time_t now_wall, time_t *next_start_out, time_t *current_window_start_out) {
    *next_start_out = 0;
    if (current_window_start_out) *current_window_start_out = 0;

    const char *old_tz = getenv("TZ");
    char old_tz_buf[128] = {0};
    if (old_tz) snprintf(old_tz_buf, sizeof(old_tz_buf), "%s", old_tz);
    set_tz_env(sched->tz);

    struct tm tm_now;
    localtime_r(&now_wall, &tm_now);

    time_t best_next = 0;
    time_t best_curr_start = 0;

    for (int day_offset = -1; day_offset <= 14; ++day_offset) {
        time_t check_day_t = now_wall + day_offset * 86400;
        struct tm tm_day;
        localtime_r(&check_day_t, &tm_day);

        tm_day.tm_hour = sched->hour;
        tm_day.tm_min = sched->minute;
        tm_day.tm_sec = 0;
        tm_day.tm_isdst = -1;

        time_t occ_start = mktime(&tm_day);
        if (occ_start == (time_t)-1) continue;

        if (sched->type == SCHED_TYPE_WEEKLY) {
            struct tm tm_occ;
            localtime_r(&occ_start, &tm_occ);
            if (!(sched->days_mask & (1 << tm_occ.tm_wday))) continue;
        }

        time_t occ_end = occ_start + sched->duration;

        if (now_wall >= occ_start && now_wall < occ_end) {
            if (sched->last_fired_time < occ_end) {
                best_curr_start = occ_start;
            }
        }

        if (occ_start > now_wall && (sched->last_fired_time < occ_start)) {
            if (best_next == 0 || occ_start < best_next) {
                best_next = occ_start;
            }
        }
    }

    if (old_tz) set_tz_env(old_tz_buf);
    else set_tz_env(NULL);

    *next_start_out = best_next;
    if (current_window_start_out) *current_window_start_out = best_curr_start;
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

    time_t earliest_next = 0;
    int best_next_idx = -1;

    int best_act_idx = -1;
    uint32_t best_act_rem = 0;

    for (size_t i = 0; i < store->count; ++i) {
        schedule_t *s = &store->items[i];
        if (!s->enabled) continue;

        if (s->type == SCHED_TYPE_ONETIME) {
            time_t occ_start = s->target_time;
            time_t occ_end = occ_start + s->duration;

            if (now_wall >= occ_start && now_wall < occ_end) {
                if (s->last_fired_time < occ_end) {
                    best_act_idx = (int)i;
                    best_act_rem = (uint32_t)(occ_end - now_wall);
                }
            } else if (occ_start > now_wall && s->last_fired_time < occ_start) {
                if (earliest_next == 0 || occ_start < earliest_next) {
                    earliest_next = occ_start;
                    best_next_idx = (int)i;
                }
            }
        } else if (s->type == SCHED_TYPE_DAILY || s->type == SCHED_TYPE_WEEKLY) {
            time_t occ_next = 0, occ_curr_start = 0;
            get_next_recurring_occurrence(s, now_wall, &occ_next, &occ_curr_start);

            if (occ_curr_start > 0) {
                best_act_idx = (int)i;
                best_act_rem = (uint32_t)((occ_curr_start + s->duration) - now_wall);
            }

            if (occ_next > 0) {
                if (earliest_next == 0 || occ_next < earliest_next) {
                    earliest_next = occ_next;
                    best_next_idx = (int)i;
                }
            }
        }
    }

    if (active_index) *active_index = best_act_idx;
    if (active_remaining) *active_remaining = best_act_rem;
    if (next_index) *next_index = best_next_idx;
    if (next_start) *next_start = earliest_next;
}

int schedule_mark_fired(schedule_store_t *store, int index, time_t occurrence_start,
                        char *err_buf, size_t err_cap) {
    if (!store || index < 0 || (size_t)index >= store->count) {
        if (err_buf) snprintf(err_buf, err_cap, "invalid schedule index");
        return -1;
    }

    time_t previous = store->items[index].last_fired_time;
    store->items[index].last_fired_time = occurrence_start + store->items[index].duration;
    if (schedule_store_save(store, err_buf, err_cap) != 0) {
        store->items[index].last_fired_time = previous;
        return -1;
    }
    return 0;
}
