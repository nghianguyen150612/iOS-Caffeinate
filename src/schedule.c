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
        hour < 0 || hour > 23 || min < 0 || min > 59 || sec < 0 || sec > 60) {
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

static const char *json_find_key(const char *json, const char *key) {
    char pattern[128];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return NULL;
    p += strlen(pattern);
    while (*p && (isspace((unsigned char)*p) || *p == ':')) p++;
    return p;
}

static int json_get_string(const char *json, const char *key, char *out, size_t cap) {
    const char *p = json_find_key(json, key);
    if (!p || *p != '"') return -1;
    p++;
    size_t len = 0;
    while (*p && *p != '"' && len + 1 < cap) {
        out[len++] = *p++;
    }
    out[len] = '\0';
    return (*p == '"') ? 0 : -1;
}

static int json_get_int(const char *json, const char *key, int *val) {
    const char *p = json_find_key(json, key);
    if (!p) return -1;
    char *end = NULL;
    long l = strtol(p, &end, 10);
    if (end == p) return -1;
    *val = (int)l;
    return 0;
}

static int json_get_uint32(const char *json, const char *key, uint32_t *val) {
    const char *p = json_find_key(json, key);
    if (!p) return -1;
    char *end = NULL;
    unsigned long l = strtoul(p, &end, 10);
    if (end == p) return -1;
    *val = (uint32_t)l;
    return 0;
}

static int json_get_time(const char *json, const char *key, time_t *val) {
    const char *p = json_find_key(json, key);
    if (!p) return -1;
    char *end = NULL;
    long long l = strtoll(p, &end, 10);
    if (end == p) return -1;
    *val = (time_t)l;
    return 0;
}

static int json_get_bool(const char *json, const char *key, bool *val) {
    const char *p = json_find_key(json, key);
    if (!p) return -1;
    if (strncmp(p, "true", 4) == 0) { *val = true; return 0; }
    if (strncmp(p, "false", 5) == 0) { *val = false; return 0; }
    return -1;
}

int schedule_store_load(schedule_store_t *store, char *err_buf, size_t err_cap) {
    if (!store || !store->state_file_path[0]) return 0;

    struct stat st;
    if (lstat(store->state_file_path, &st) != 0) {
        if (errno == ENOENT) return 0;
        if (err_buf) snprintf(err_buf, err_cap, "lstat schedule file failed: %s", strerror(errno));
        return -1;
    }

    if (S_ISLNK(st.st_mode)) {
        if (err_buf) snprintf(err_buf, err_cap, "refusing symlink schedule file: %s", store->state_file_path);
        return -1;
    }

    if (!S_ISREG(st.st_mode)) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule file is not a regular file");
        return -1;
    }

    if (st.st_uid != geteuid()) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule file ownership mismatch");
        return -1;
    }

    if (st.st_size > MAX_FILE_SIZE) {
        if (err_buf) snprintf(err_buf, err_cap, "schedule file exceeds maximum size");
        return -1;
    }

    int fd = open(store->state_file_path, O_RDONLY | O_NOFOLLOW);
    if (fd < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "open schedule file failed: %s", strerror(errno));
        return -1;
    }

    char *buf = malloc((size_t)st.st_size + 1);
    if (!buf) {
        close(fd);
        if (err_buf) snprintf(err_buf, err_cap, "out of memory");
        return -1;
    }

    ssize_t n = read(fd, buf, (size_t)st.st_size);
    close(fd);
    if (n != st.st_size) {
        free(buf);
        if (err_buf) snprintf(err_buf, err_cap, "read schedule file failed");
        return -1;
    }
    buf[n] = '\0';

    schedule_store_t temp;
    memcpy(&temp, store, sizeof(temp));
    temp.count = 0;

    int version = 0;
    if (json_get_int(buf, "version", &version) != 0 || version != 1) {
        free(buf);
        if (err_buf) snprintf(err_buf, err_cap, "invalid or unsupported schema version");
        return -1;
    }

    uint32_t counter = 1;
    if (json_get_uint32(buf, "next_id_counter", &counter) == 0) {
        temp.next_id_counter = counter;
    }

    const char *p = strstr(buf, "\"schedules\"");
    if (!p) { free(buf); return 0; }
    p = strchr(p, '[');
    if (!p) { free(buf); return 0; }

    while (*p && *p != ']') {
        const char *obj_start = strchr(p, '{');
        if (!obj_start) break;
        const char *obj_end = strchr(obj_start, '}');
        if (!obj_end) break;

        size_t obj_len = (size_t)(obj_end - obj_start + 1);
        char obj_buf[1024];
        if (obj_len >= sizeof(obj_buf)) { p = obj_end + 1; continue; }
        memcpy(obj_buf, obj_start, obj_len);
        obj_buf[obj_len] = '\0';

        if (temp.count >= MAX_SCHEDULES) {
            free(buf);
            if (err_buf) snprintf(err_buf, err_cap, "schedule state exceeds maximum schedule capacity");
            return -1;
        }

        schedule_t *item = &temp.items[temp.count];
        memset(item, 0, sizeof(*item));

        if (json_get_string(obj_buf, "id", item->id, sizeof(item->id)) != 0) {
            p = obj_end + 1; continue;
        }

        bool duplicate = false;
        for (size_t i = 0; i < temp.count; ++i) {
            if (strcmp(temp.items[i].id, item->id) == 0) { duplicate = true; break; }
        }
        if (duplicate) {
            free(buf);
            if (err_buf) snprintf(err_buf, err_cap, "duplicate schedule ID in state file: %s", item->id);
            return -1;
        }

        int type_val = 0;
        if (json_get_int(obj_buf, "type", &type_val) != 0 || type_val < 1 || type_val > 3) {
            p = obj_end + 1; continue;
        }
        item->type = (sched_type_t)type_val;

        json_get_time(obj_buf, "target_time", &item->target_time);
        json_get_int(obj_buf, "hour", &item->hour);
        json_get_int(obj_buf, "minute", &item->minute);
        int mask = 0;
        if (json_get_int(obj_buf, "days_mask", &mask) == 0) item->days_mask = (uint8_t)mask;
        json_get_uint32(obj_buf, "duration", &item->duration);
        json_get_string(obj_buf, "tz", item->tz, sizeof(item->tz));
        json_get_bool(obj_buf, "enabled", &item->enabled);
        json_get_time(obj_buf, "last_fired_time", &item->last_fired_time);

        if (item->duration < 1 || item->duration > 86400) {
            p = obj_end + 1; continue;
        }

        temp.count++;
        p = obj_end + 1;
    }

    free(buf);
    memcpy(store, &temp, sizeof(*store));
    return 0;
}

int schedule_store_save(const schedule_store_t *store, char *err_buf, size_t err_cap) {
    if (!store || !store->state_file_path[0]) return 0;

    char dir_path[256];
    snprintf(dir_path, sizeof(dir_path), "%s", store->state_file_path);
    char *last_slash = strrchr(dir_path, '/');
    if (last_slash && last_slash != dir_path) {
        *last_slash = '\0';
        struct stat st_dir;
        if (lstat(dir_path, &st_dir) == 0) {
            if (S_ISLNK(st_dir.st_mode)) {
                if (err_buf) snprintf(err_buf, err_cap, "refusing symlink directory: %s", dir_path);
                return -1;
            }
            if (st_dir.st_uid != geteuid()) {
                if (err_buf) snprintf(err_buf, err_cap, "directory ownership mismatch: %s", dir_path);
                return -1;
            }
        }
    }

    char tmp_path[320];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp.%d", store->state_file_path, getpid());

    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600);
    if (fd < 0) {
        if (err_buf) snprintf(err_buf, err_cap, "failed to create temp schedule file: %s", strerror(errno));
        return -1;
    }

    FILE *f = fdopen(fd, "w");
    if (!f) {
        close(fd);
        unlink(tmp_path);
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
        unlink(tmp_path);
        if (err_buf) snprintf(err_buf, err_cap, "flush/sync temp schedule file failed");
        return -1;
    }

    fclose(f);

    if (rename(tmp_path, store->state_file_path) != 0) {
        unlink(tmp_path);
        if (err_buf) snprintf(err_buf, err_cap, "rename temp schedule file failed: %s", strerror(errno));
        return -1;
    }

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
        snprintf(sched->id, sizeof(sched->id), "sched-%u", temp.next_id_counter++);
    } else {
        for (size_t i = 0; i < temp.count; ++i) {
            if (strcmp(temp.items[i].id, sched->id) == 0) {
                if (err_buf) snprintf(err_buf, err_cap, "schedule ID '%s' already exists", sched->id);
                return -1;
            }
        }
    }

    if (sched->duration < 1 || sched->duration > 86400) {
        if (err_buf) snprintf(err_buf, err_cap, "duration must be between 1 and 86400 seconds");
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

    sched->enabled = true;
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

void schedule_mark_fired(schedule_store_t *store, int index, time_t occurrence_start) {
    if (!store || index < 0 || (size_t)index >= store->count) return;
    store->items[index].last_fired_time = occurrence_start + store->items[index].duration;
    char err[256];
    schedule_store_save(store, err, sizeof(err));
}
