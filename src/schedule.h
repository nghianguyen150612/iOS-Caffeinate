#ifndef IOSCAFFEINATE_SCHEDULE_H
#define IOSCAFFEINATE_SCHEDULE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#define MAX_SCHEDULES 64
#define SCHED_ID_LEN 32
#define TZ_LEN 64
#define SCHEDULE_MAX_SESSION_SECONDS 300
#define SCHEDULE_CONFLICT_MAX 2048

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

typedef enum {
    SCHEDULE_RESOLUTION_OK = 0,
    SCHEDULE_RESOLUTION_AMBIGUOUS_FIRST,
    SCHEDULE_RESOLUTION_DST_NONEXISTENT_LOCAL_TIME,
    SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED,
    SCHEDULE_RESOLUTION_INVALID
} schedule_resolution_t;

typedef enum {
    SCHEDULE_OUTCOME_UPCOMING = 0,
    SCHEDULE_OUTCOME_ACTIVE_WINDOW,
    SCHEDULE_OUTCOME_EXPIRED,
    SCHEDULE_OUTCOME_MISSED,
    SCHEDULE_OUTCOME_ALREADY_FIRED,
    SCHEDULE_OUTCOME_CONFLICT,
    SCHEDULE_OUTCOME_BLOCKED_RECOVERY,
    SCHEDULE_OUTCOME_BLOCKED_POLICY,
    SCHEDULE_OUTCOME_RESOURCE_UNAVAILABLE,
    SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED,
    SCHEDULE_OUTCOME_INCOMPLETE
} schedule_outcome_t;

typedef int (*schedule_localtime_fn)(void *context, time_t instant, struct tm *local);
typedef void (*schedule_timezone_destroy_fn)(void *context);

/* Injectable calendar conversion boundary. Production code uses UTC or the
 * system timezone; tests supply deterministic transition fixtures. */
typedef struct {
    schedule_localtime_fn localtime;
    void *context;
    schedule_timezone_destroy_fn destroy_context;
    char effective_timezone[TZ_LEN];
    schedule_resolution_t unavailable_reason;
} schedule_timezone_resolver_t;

typedef struct {
    char schedule_id[SCHED_ID_LEN];
    uint64_t schedule_revision;
    int year;
    int month;
    int day;
    int hour;
    int minute;
    char effective_timezone[TZ_LEN];
    time_t start;
    time_t end;
    schedule_resolution_t resolution;
    unsigned matching_instants;
} schedule_occurrence_t;

typedef struct {
    schedule_outcome_t outcome;
    schedule_occurrence_t occurrence;
    schedule_occurrence_t next;
    int has_occurrence;
    int has_next;
    int saw_nonexistent_local_time;
} schedule_analysis_t;

typedef struct {
    int duplicate_definition;
    size_t first_index;
    size_t second_index;
    time_t first_start;
    time_t first_end;
    time_t second_start;
    time_t second_end;
} schedule_conflict_t;

typedef int (*schedule_timezone_provider_fn)(void *context, const char *tz,
                                             schedule_timezone_resolver_t *resolver,
                                             schedule_resolution_t *status);

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
int schedule_store_set_enabled(schedule_store_t *store, const char *id, bool enabled,
                               uint64_t expected_generation, int *changed,
                               char *err_buf, size_t err_cap);

/* Calculate next occurrence and currently active occurrence across all schedules. */
void schedule_store_evaluate(schedule_store_t *store,
                             time_t now_wall,
                             int *active_index,
                             uint32_t *active_remaining,
                             int *next_index,
                             time_t *next_start);

/* Calendar-safe, side-effect-free occurrence analysis. */
int schedule_timezone_default(const char *tz, schedule_timezone_resolver_t *resolver,
                              schedule_resolution_t *status);
void schedule_timezone_resolver_clear(schedule_timezone_resolver_t *resolver);
int schedule_analyze_with_resolver(const schedule_t *schedule, time_t reference,
                                   const schedule_timezone_resolver_t *resolver,
                                   schedule_analysis_t *analysis);
int schedule_analyze(const schedule_t *schedule, time_t reference,
                     schedule_analysis_t *analysis);
int schedule_occurrence_identity(const schedule_occurrence_t *occurrence,
                                 char *out, size_t cap);
const char *schedule_resolution_name(schedule_resolution_t value);
const char *schedule_outcome_name(schedule_outcome_t value);
uint64_t schedule_store_generation(const schedule_store_t *store);
int schedule_store_find_conflicts(const schedule_store_t *store, time_t reference,
                                  unsigned horizon_days, schedule_conflict_t *conflicts,
                                  size_t conflict_cap, size_t *conflict_count,
                                  int *analysis_incomplete);
int schedule_store_find_conflicts_with_provider(
    const schedule_store_t *store, time_t reference, unsigned horizon_days,
    schedule_timezone_provider_fn provider, void *provider_context,
    schedule_conflict_t *conflicts, size_t conflict_cap, size_t *conflict_count,
    int *analysis_incomplete);

/* Mark schedule occurrence as fired */
int schedule_mark_fired(schedule_store_t *store, int index, time_t occurrence_start,
                        char *err_buf, size_t err_cap);

/* Helper to parse weekday string e.g. "mon,wed,fri" to bitmask */
int parse_weekly_days(const char *str, uint8_t *mask_out);

#endif
