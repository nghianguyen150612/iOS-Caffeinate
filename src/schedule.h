#ifndef IOSCAFFEINATE_SCHEDULE_H
#define IOSCAFFEINATE_SCHEDULE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#define MAX_SCHEDULES 64
#define SCHED_ID_LEN 32
#define TZ_LEN 64

typedef enum {
    SCHED_TYPE_ONETIME = 1,
    SCHED_TYPE_DAILY = 2,
    SCHED_TYPE_WEEKLY = 3
} sched_type_t;

typedef struct {
    char id[SCHED_ID_LEN];
    sched_type_t type;
    time_t target_time;     /* For ONETIME: UTC timestamp */
    int hour;               /* For DAILY/WEEKLY: 0..23 */
    int minute;             /* For DAILY/WEEKLY: 0..59 */
    uint8_t days_mask;      /* For WEEKLY: bitmask (1<<0=Sun, 1<<1=Mon..1<<6=Sat) */
    uint32_t duration;      /* Duration in seconds (1..86400) */
    char tz[TZ_LEN];        /* IANA timezone or empty for system local */
    bool enabled;
    time_t last_fired_time; /* Timestamp of the last fired occurrence */
} schedule_t;

typedef struct {
    schedule_t items[MAX_SCHEDULES];
    size_t count;
    uint32_t next_id_counter;
    char state_file_path[256];
} schedule_store_t;

/* Parse ISO-8601 string (e.g. 2026-10-18T23:00:00+07:00 or 2026-10-18T23:00:00Z)
 * Returns UTC timestamp, or (time_t)-1 on parse error. */
time_t parse_iso8601(const char *str);

/* Format time_t as ISO-8601 UTC string: YYYY-MM-DDTHH:MM:SSZ */
int format_iso8601_utc(time_t t, char *buf, size_t cap);

/* Initialize schedule store with state file path */
void schedule_store_init(schedule_store_t *store, const char *file_path);

/* Load schedules from persistent storage */
int schedule_store_load(schedule_store_t *store, char *err_buf, size_t err_cap);

/* Save schedules atomically to persistent storage */
int schedule_store_save(const schedule_store_t *store, char *err_buf, size_t err_cap);

/* Add a schedule item; auto-generates ID if not provided */
int schedule_store_add(schedule_store_t *store, schedule_t *sched, char *err_buf, size_t err_cap);

/* Remove schedule by ID */
int schedule_store_remove(schedule_store_t *store, const char *id, char *err_buf, size_t err_cap);

/* Calculate next occurrence and currently active occurrence across all schedules. */
void schedule_store_evaluate(schedule_store_t *store,
                             time_t now_wall,
                             int *active_index,
                             uint32_t *active_remaining,
                             int *next_index,
                             time_t *next_start);

/* Mark schedule occurrence as fired */
int schedule_mark_fired(schedule_store_t *store, int index, time_t occurrence_start,
                        char *err_buf, size_t err_cap);

/* Helper to parse weekday string e.g. "mon,wed,fri" to bitmask */
int parse_weekly_days(const char *str, uint8_t *mask_out);

#endif
