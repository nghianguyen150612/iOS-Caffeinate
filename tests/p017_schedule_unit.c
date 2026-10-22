#define _GNU_SOURCE
#include "schedule.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static unsigned checks;

#define CHECK(condition, label) do { \
    checks++; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, label); \
        return -1; \
    } \
} while (0)

typedef struct {
    const char *name;
    int standard_offset;
    int daylight_offset;
    time_t daylight_start;
    time_t daylight_end;
    int has_dst;
} fixture_timezone_t;

typedef struct {
    fixture_timezone_t eastern;
    fixture_timezone_t western;
    fixture_timezone_t dateline;
} fixture_set_t;

static time_t instant(const char *text) {
    return parse_iso8601(text);
}

static int fixture_localtime(void *context, time_t epoch, struct tm *local) {
    fixture_timezone_t *zone = context;
    int offset = zone->standard_offset;
    if (zone->has_dst && epoch >= zone->daylight_start && epoch < zone->daylight_end)
        offset = zone->daylight_offset;
    int64_t local_epoch = (int64_t)epoch + offset;
    time_t value = (time_t)local_epoch;
    if ((int64_t)value != local_epoch) return -1;
    return gmtime_r(&value, local) ? 0 : -1;
}

static int fixture_provider(void *context, const char *tz,
                            schedule_timezone_resolver_t *resolver,
                            schedule_resolution_t *status) {
    fixture_set_t *set = context;
    fixture_timezone_t *zone = NULL;
    if (strcmp(tz, "Fixture/Eastern") == 0) zone = &set->eastern;
    else if (strcmp(tz, "Fixture/Western") == 0) zone = &set->western;
    else if (strcmp(tz, "Fixture/Dateline") == 0) zone = &set->dateline;
    if (!zone) {
        if (status) *status = SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED;
        return -1;
    }
    memset(resolver, 0, sizeof(*resolver));
    resolver->localtime = fixture_localtime;
    resolver->context = zone;
    snprintf(resolver->effective_timezone, sizeof(resolver->effective_timezone), "%s", zone->name);
    if (status) *status = SCHEDULE_RESOLUTION_OK;
    return 0;
}

static schedule_t recurring(const char *id, sched_type_t type, int hour, int minute,
                            uint8_t days_mask, uint32_t duration, const char *tz) {
    schedule_t value;
    memset(&value, 0, sizeof(value));
    snprintf(value.id, sizeof(value.id), "%s", id);
    value.type = type;
    value.hour = hour;
    value.minute = minute;
    value.days_mask = days_mask;
    value.duration = duration;
    snprintf(value.tz, sizeof(value.tz), "%s", tz);
    value.enabled = true;
    return value;
}

static int test_calendar_recurrence(void) {
    schedule_timezone_resolver_t utc = {0};
    utc.localtime = fixture_localtime;
    fixture_timezone_t utc_zone = {.name = "UTC", .standard_offset = 0};
    utc.context = &utc_zone;
    snprintf(utc.effective_timezone, sizeof(utc.effective_timezone), "UTC");

    schedule_t once;
    memset(&once, 0, sizeof(once));
    snprintf(once.id, sizeof(once.id), "once");
    once.type = SCHED_TYPE_ONETIME;
    once.target_time = instant("2026-10-22T12:00:00Z");
    once.duration = 300;
    once.enabled = true;
    schedule_analysis_t analysis;
    CHECK(schedule_analyze_with_resolver(&once, instant("2026-10-22T11:00:00Z"),
                                         NULL, &analysis) == 0, "one-time analysis");
    CHECK(analysis.outcome == SCHEDULE_OUTCOME_UPCOMING && analysis.has_next,
          "one-time upcoming state");
    CHECK(analysis.next.start == once.target_time, "one-time exact UTC start");
    CHECK(schedule_analyze_with_resolver(&once, once.target_time + 300, NULL, &analysis) == 0 &&
          analysis.outcome == SCHEDULE_OUTCOME_EXPIRED, "expired one-time is not replayed");

    schedule_t daily = recurring("daily", SCHED_TYPE_DAILY, 0, 30, 0, 300, "UTC");
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-12-31T23:00:00Z"),
                                         &utc, &analysis) == 0, "daily calendar analysis");
    CHECK(analysis.has_next && analysis.next.start == instant("2027-01-01T00:30:00Z"),
          "daily recurrence crosses year boundary");
    daily.hour = 9;
    daily.minute = 0;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-04-30T23:00:00Z"),
                                         &utc, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-05-01T09:00:00Z"),
          "daily recurrence crosses month boundary");
    daily.hour = 0;
    daily.minute = 30;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2024-02-28T13:00:00Z"),
                                         &utc, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2024-02-29T00:30:00Z"), "leap-day recurrence");

    schedule_t weekly = recurring("weekly", SCHED_TYPE_WEEKLY, 8, 0, (uint8_t)(1U << 1),
                                   300, "UTC");
    CHECK(schedule_analyze_with_resolver(&weekly, instant("2026-10-18T23:00:00Z"),
                                         &utc, &analysis) == 0 && analysis.has_next,
          "weekly mask analysis");
    CHECK(analysis.next.start == instant("2026-10-19T08:00:00Z"),
          "weekly Monday mask");

    schedule_t midnight = recurring("midnight", SCHED_TYPE_DAILY, 23, 58, 0, 300, "UTC");
    CHECK(schedule_analyze_with_resolver(&midnight, instant("2026-05-01T23:59:00Z"),
                                         &utc, &analysis) == 0 &&
          analysis.outcome == SCHEDULE_OUTCOME_ACTIVE_WINDOW &&
          analysis.occurrence.end == instant("2026-05-02T00:03:00Z"),
          "duration crosses midnight in UTC");

    schedule_t overflow = once;
    overflow.target_time = (time_t)INT64_MAX;
    CHECK(schedule_analyze_with_resolver(&overflow, 0, NULL, &analysis) != 0,
          "timestamp plus duration overflow rejected");
    return 0;
}

static int test_dst_and_timezones(void) {
    fixture_timezone_t eastern = {
        .name = "Fixture/Eastern", .standard_offset = -5 * 3600,
        .daylight_offset = -4 * 3600,
        .daylight_start = 0, .daylight_end = 0, .has_dst = 1,
    };
    eastern.daylight_start = instant("2026-03-08T07:00:00Z");
    eastern.daylight_end = instant("2026-11-01T06:00:00Z");
    fixture_timezone_t western = {.name = "Fixture/Western", .standard_offset = -8 * 3600};
    fixture_timezone_t dateline = {.name = "Fixture/Dateline", .standard_offset = 14 * 3600};
    fixture_set_t set = {.eastern = eastern, .western = western, .dateline = dateline};
    schedule_timezone_resolver_t resolver;
    schedule_resolution_t status;
    CHECK(fixture_provider(&set, "Fixture/Eastern", &resolver, &status) == 0,
          "fixture timezone provider");

    schedule_t daily = recurring("spring-gap", SCHED_TYPE_DAILY, 2, 30, 0, 300,
                                 "Fixture/Eastern");
    schedule_analysis_t analysis;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-03-08T12:00:00Z"),
                                         &resolver, &analysis) == 0,
          "spring DST gap analysis");
    CHECK(analysis.saw_nonexistent_local_time, "spring gap recorded");
    CHECK(analysis.has_next && analysis.next.start == instant("2026-03-09T06:30:00Z"),
          "nonexistent 02:30 is skipped, not shifted");

    daily.hour = 1;
    daily.minute = 30;
    snprintf(daily.id, sizeof(daily.id), "fall-ambiguous");
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-11-01T00:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next,
          "fall DST overlap analysis");
    CHECK(analysis.next.start == instant("2026-11-01T05:30:00Z"),
          "ambiguous time selects first UTC instant");
    CHECK(analysis.next.resolution == SCHEDULE_RESOLUTION_AMBIGUOUS_FIRST &&
          analysis.next.matching_instants == 2, "ambiguity explicitly reported");
    char first_identity[256], second_identity[256];
    CHECK(schedule_occurrence_identity(&analysis.next, first_identity, sizeof(first_identity)) > 0,
          "occurrence identity formatting");
    schedule_analysis_t repeat;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-11-01T00:00:00Z"),
                                         &resolver, &repeat) == 0 &&
          schedule_occurrence_identity(&repeat.next, second_identity,
                                       sizeof(second_identity)) > 0 &&
          strcmp(first_identity, second_identity) == 0,
          "repeated evaluation keeps one logical occurrence identity");
    CHECK(strstr(first_identity, "fall-ambiguous@") == first_identity &&
          strstr(first_identity, "Fixture/Eastern") != NULL &&
          strstr(first_identity, "DST_AMBIGUOUS_FIRST_OCCURRENCE") != NULL,
          "identity binds ID revision intended date timezone and resolution");

    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-11-01T06:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-11-02T06:30:00Z"),
          "fall-back second fold never creates a second logical occurrence");

    schedule_t local = recurring("zone-offset", SCHED_TYPE_DAILY, 9, 0, 0, 300,
                                 "Fixture/Eastern");
    CHECK(fixture_provider(&set, "Fixture/Western", &resolver, &status) == 0,
          "second fixture timezone provider");
    local.tz[0] = '\0';
    snprintf(local.tz, sizeof(local.tz), "Fixture/Western");
    CHECK(schedule_analyze_with_resolver(&local, instant("2026-07-01T00:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-07-01T17:00:00Z"),
          "second timezone has independent offset");
    CHECK(fixture_provider(&set, "Fixture/Dateline", &resolver, &status) == 0 &&
          schedule_analyze_with_resolver(&local, instant("2026-07-01T00:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-07-01T19:00:00Z"),
          "date-line offset is handled without fixed-day UTC offsets");

    schedule_t system_local = recurring("system-zone", SCHED_TYPE_DAILY, 9, 0, 0, 300, "");
    CHECK(fixture_provider(&set, "Fixture/Eastern", &resolver, &status) == 0 &&
          schedule_analyze_with_resolver(&system_local, instant("2026-07-01T00:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-07-01T13:00:00Z"),
          "system-local schedule resolves against first timezone context");
    char eastern_identity[256], western_identity[256];
    CHECK(schedule_occurrence_identity(&analysis.next, eastern_identity,
                                       sizeof(eastern_identity)) > 0,
          "system timezone identity captures first effective zone");
    CHECK(fixture_provider(&set, "Fixture/Western", &resolver, &status) == 0 &&
          schedule_analyze_with_resolver(&system_local, instant("2026-07-01T00:00:00Z"),
                                         &resolver, &analysis) == 0 && analysis.has_next &&
          analysis.next.start == instant("2026-07-01T17:00:00Z"),
          "system-local schedule follows a changed timezone context");
    CHECK(schedule_occurrence_identity(&analysis.next, western_identity,
                                       sizeof(western_identity)) > 0 &&
          strcmp(eastern_identity, western_identity) != 0 &&
          strstr(western_identity, "Fixture/Western") != NULL,
          "timezone change creates a distinct effective occurrence identity");

    CHECK(schedule_timezone_default("America/New_York", &resolver, &status) != 0 &&
          status == SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED,
          "unverified IANA backend fails closed");
    return 0;
}

static int test_replay_and_conflicts(void) {
    fixture_timezone_t eastern = {
        .name = "Fixture/Eastern", .standard_offset = -5 * 3600,
        .daylight_offset = -4 * 3600,
        .daylight_start = 0, .daylight_end = 0, .has_dst = 1,
    };
    eastern.daylight_start = instant("2026-03-08T07:00:00Z");
    eastern.daylight_end = instant("2026-11-01T06:00:00Z");
    fixture_timezone_t western = {.name = "Fixture/Western", .standard_offset = -8 * 3600};
    fixture_timezone_t dateline = {.name = "Fixture/Dateline", .standard_offset = 14 * 3600};
    fixture_set_t fixtures = {.eastern = eastern, .western = western, .dateline = dateline};

    schedule_t daily = recurring("rollback", SCHED_TYPE_DAILY, 10, 0, 0, 300, "UTC");
    daily.last_fired_time = instant("2026-05-02T10:05:00Z");
    schedule_timezone_resolver_t utc = {0};
    fixture_timezone_t utc_zone = {.name = "UTC", .standard_offset = 0};
    utc.localtime = fixture_localtime;
    utc.context = &utc_zone;
    snprintf(utc.effective_timezone, sizeof(utc.effective_timezone), "UTC");
    schedule_analysis_t analysis;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-05-02T09:00:00Z"),
                                         &utc, &analysis) == 0 &&
          analysis.outcome == SCHEDULE_OUTCOME_ALREADY_FIRED && analysis.has_next &&
          analysis.next.start == instant("2026-05-03T10:00:00Z"),
          "clock rollback does not replay a fired daily occurrence");

    daily.last_fired_time = 0;
    CHECK(schedule_analyze_with_resolver(&daily, instant("2026-05-02T10:10:00Z"),
                                         &utc, &analysis) == 0 &&
          analysis.outcome == SCHEDULE_OUTCOME_MISSED && analysis.has_next &&
          analysis.next.start == instant("2026-05-03T10:00:00Z"),
          "forward reference jump reports missed window without catch-up");

    schedule_store_t store;
    schedule_store_init(&store, "/tmp/p017-unused-schedule-state.json");
    store.count = 3;
    store.items[0] = recurring("cross-midnight", SCHED_TYPE_DAILY, 23, 58, 0, 300, "UTC");
    store.items[1] = recurring("after-midnight", SCHED_TYPE_DAILY, 0, 0, 0, 300, "UTC");
    memset(&store.items[2], 0, sizeof(store.items[2]));
    snprintf(store.items[2].id, sizeof(store.items[2].id), "one-time");
    store.items[2].type = SCHED_TYPE_ONETIME;
    store.items[2].target_time = instant("2026-05-02T00:01:00Z");
    store.items[2].duration = 300;
    store.items[2].enabled = true;
    schedule_conflict_t conflicts[SCHEDULE_CONFLICT_MAX];
    size_t count = 0;
    int incomplete = 0;
    CHECK(schedule_store_find_conflicts(&store, instant("2026-05-01T00:00:00Z"), 3,
                                        conflicts, SCHEDULE_CONFLICT_MAX, &count,
                                        &incomplete) == 0 && count >= 2 && !incomplete,
          "daily midnight and one-time windows conflict");

    schedule_store_t zone_store;
    schedule_store_init(&zone_store, "/tmp/p017-unused-schedule-state.json");
    zone_store.count = 2;
    zone_store.items[0] = recurring("east", SCHED_TYPE_DAILY, 10, 0, 0, 600,
                                    "Fixture/Eastern");
    zone_store.items[1] = recurring("west", SCHED_TYPE_DAILY, 7, 0, 0, 600,
                                    "Fixture/Western");
    CHECK(schedule_store_find_conflicts_with_provider(
              &zone_store, instant("2026-10-31T00:00:00Z"), 370,
              fixture_provider, &fixtures, conflicts, SCHEDULE_CONFLICT_MAX,
              &count, &incomplete) == 0 && count > 0 && !incomplete,
          "overlap analysis compares UTC windows across timezones and DST");

    schedule_store_t dst_store;
    schedule_store_init(&dst_store, "/tmp/p017-unused-schedule-state.json");
    dst_store.count = 2;
    dst_store.items[0] = recurring("spring-before", SCHED_TYPE_DAILY, 1, 58, 0, 300,
                                   "Fixture/Eastern");
    dst_store.items[1] = recurring("spring-after", SCHED_TYPE_DAILY, 3, 0, 0, 300,
                                   "Fixture/Eastern");
    CHECK(schedule_store_find_conflicts_with_provider(
              &dst_store, instant("2026-03-07T00:00:00Z"), 2,
              fixture_provider, &fixtures, conflicts, SCHEDULE_CONFLICT_MAX,
              &count, &incomplete) == 0 && count == 1 && !incomplete &&
          conflicts[0].first_start == instant("2026-03-08T06:58:00Z") &&
          conflicts[0].second_start == instant("2026-03-08T07:00:00Z"),
          "UTC overlap at a DST forward transition is detected");

    zone_store.items[1] = zone_store.items[0];
    snprintf(zone_store.items[1].id, sizeof(zone_store.items[1].id), "east-copy");
    CHECK(schedule_store_find_conflicts_with_provider(
              &zone_store, instant("2026-10-31T00:00:00Z"), 14,
              fixture_provider, &fixtures, conflicts, SCHEDULE_CONFLICT_MAX,
              &count, &incomplete) == 0 && count > 0 && conflicts[0].duplicate_definition,
          "duplicate definitions are reported explicitly");

    zone_store.items[1].tz[0] = '\0';
    snprintf(zone_store.items[1].tz, sizeof(zone_store.items[1].tz), "Invalid/Zone");
    CHECK(schedule_store_find_conflicts(&zone_store, instant("2026-10-31T00:00:00Z"), 14,
                                        conflicts, SCHEDULE_CONFLICT_MAX,
                                        &count, &incomplete) == 0 && incomplete,
          "unverified timezone makes conflict analysis incomplete");
    return 0;
}

static int read_state(const char *path, char *buffer, size_t cap) {
    FILE *file = fopen(path, "rb");
    if (!file) return -1;
    size_t length = fread(buffer, 1, cap - 1, file);
    int failed = ferror(file);
    if (fclose(file) != 0) failed = 1;
    if (failed || length >= cap - 1) return -1;
    buffer[length] = '\0';
    return (int)length;
}

static int test_storage_transactions(void) {
    char directory_template[] = "/tmp/ioscaf-p017-store-XXXXXX";
    char *directory = mkdtemp(directory_template);
    CHECK(directory != NULL, "create private storage fixture");
    char path[256];
    snprintf(path, sizeof(path), "%s/schedules.json", directory);
    schedule_store_t store;
    schedule_store_init(&store, path);
    schedule_t item = recurring("storage-item", SCHED_TYPE_DAILY, 12, 0, 0, 300, "UTC");
    char error[256] = {0};
    CHECK(schedule_store_add(&store, &item, error, sizeof(error)) == 0,
          "new schedule writes through atomic storage path");
    CHECK(store.count == 1 && store.items[0].duration == 300,
          "schedule add updates in-memory state after persistence");

    schedule_store_t loaded;
    schedule_store_init(&loaded, path);
    CHECK(schedule_store_load(&loaded, error, sizeof(error)) == 0 && loaded.count == 1,
          "schedule file reads back after atomic commit");
    char before[8192], after[8192];
    int before_len = read_state(path, before, sizeof(before));
    CHECK(before_len > 0, "read persisted schedule bytes");
    uint64_t generation = schedule_store_generation(&loaded);
    int changed = 0;
    CHECK(schedule_store_set_enabled(&loaded, "storage-item", false, generation + 1,
                                     &changed, error, sizeof(error)) != 0 && changed == 0,
          "stale edit generation is rejected");
    int after_len = read_state(path, after, sizeof(after));
    CHECK(after_len == before_len && memcmp(before, after, (size_t)before_len) == 0,
          "stale edit leaves storage byte-for-byte unchanged");

    CHECK(schedule_store_set_enabled(&loaded, "storage-item", false, generation,
                                     &changed, error, sizeof(error)) == 0 && changed == 1,
          "current generation disables through transaction");
    uint64_t disabled_generation = schedule_store_generation(&loaded);
    CHECK(disabled_generation != generation && !loaded.items[0].enabled,
          "successful edit advances generation");
    before_len = read_state(path, before, sizeof(before));
    CHECK(schedule_store_set_enabled(&loaded, "storage-item", false, disabled_generation,
                                     &changed, error, sizeof(error)) == 0 && changed == 0,
          "unchanged edit reports no change");
    after_len = read_state(path, after, sizeof(after));
    CHECK(after_len == before_len && memcmp(before, after, (size_t)before_len) == 0,
          "unchanged edit does not rewrite storage");

    CHECK(setenv("IOSCAFFEINATE_MOCK_FAIL_SCHEDULE_SAVE", "1", 1) == 0,
          "enable schedule write fault injection");
    CHECK(schedule_store_set_enabled(&loaded, "storage-item", true, disabled_generation,
                                     &changed, error, sizeof(error)) != 0 && changed == 0,
          "failed write does not report a changed schedule");
    CHECK(unsetenv("IOSCAFFEINATE_MOCK_FAIL_SCHEDULE_SAVE") == 0,
          "clear schedule write fault injection");
    after_len = read_state(path, after, sizeof(after));
    CHECK(after_len == before_len && memcmp(before, after, (size_t)before_len) == 0 &&
          !loaded.items[0].enabled,
          "failed serialization preserves old bytes and in-memory value");

    time_t fired_start = instant("2026-10-21T12:00:00Z");
    CHECK(schedule_mark_fired(&loaded, 0, fired_start, error, sizeof(error)) == 0,
          "occurrence bookkeeping persists an end boundary");
    time_t fired_end = fired_start + 300;
    CHECK(loaded.items[0].last_fired_time == fired_end,
          "last_fired_time retains P004 end-boundary meaning");
    before_len = read_state(path, before, sizeof(before));
    CHECK(schedule_mark_fired(&loaded, 0, fired_start, error, sizeof(error)) == 0 &&
          schedule_mark_fired(&loaded, 0, fired_start - 86400, error, sizeof(error)) == 0,
          "duplicate and older marks are idempotent");
    after_len = read_state(path, after, sizeof(after));
    CHECK(loaded.items[0].last_fired_time == fired_end && after_len == before_len &&
          memcmp(before, after, (size_t)before_len) == 0,
          "clock rollback cannot regress persisted occurrence history");

    unlink(path);
    CHECK(rmdir(directory) == 0, "remove storage fixture directory");
    return 0;
}

int main(void) {
    if (test_calendar_recurrence() != 0 || test_dst_and_timezones() != 0 ||
        test_replay_and_conflicts() != 0 || test_storage_transactions() != 0) return 1;
    printf("P017 scheduling checks: %u passed\n", checks);
    return 0;
}
