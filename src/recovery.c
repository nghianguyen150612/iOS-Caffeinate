/* P014 recovery policy and durable, fail-closed daemon-run journal. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L

#include "recovery.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_DIRECTORY
#define O_DIRECTORY 0
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif

#define RECOVERY_PATH_CAP 512
#define RECOVERY_FILE_MODE 0600
#define RECOVERY_WINDOW_NS ((uint64_t)RECOVERY_WINDOW_SECONDS * UINT64_C(1000000000))

static const uint32_t restart_backoff_seconds[RECOVERY_MAX_ATTEMPTS] = {5, 15, 60};

#ifdef IOSCAFFEINATE_RECOVERY_TESTING
static int fail_save_before_rename;
void recovery_test_fail_save_before_rename(int enabled) {
    fail_save_before_rename = enabled != 0;
}
#endif

static void set_detail(char *detail, size_t cap, const char *message) {
    if (detail && cap) snprintf(detail, cap, "%s", message ? message : "unknown recovery error");
}

const char *recovery_exit_class_name(recovery_exit_class_t value) {
    switch (value) {
        case RECOVERY_EXIT_UNKNOWN_UNOBSERVED: return "UNKNOWN_UNOBSERVED";
        case RECOVERY_EXIT_GRACEFUL_CONFIRMED: return "GRACEFUL_CONFIRMED";
        case RECOVERY_EXIT_EXPLICIT_STOP: return "EXPLICIT_STOP";
        case RECOVERY_EXIT_TIMED_EXPIRY_ONLY: return "TIMED_EXPIRY_ONLY";
        case RECOVERY_EXIT_UNEXPECTED_EXIT: return "UNEXPECTED_EXIT";
        case RECOVERY_EXIT_SIGNAL_TERMINATION: return "SIGNAL_TERMINATION";
        case RECOVERY_EXIT_STARTUP_FAILURE: return "STARTUP_FAILURE";
        case RECOVERY_EXIT_RELEASE_FAILURE: return "RELEASE_FAILURE";
        case RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN: return "ASSERTION_OWNERSHIP_UNKNOWN";
        case RECOVERY_EXIT_SUPERVISOR_STATUS_UNKNOWN: return "SUPERVISOR_STATUS_UNKNOWN";
        case RECOVERY_EXIT_REPEATED_FAILURE: return "REPEATED_FAILURE";
        case RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP: return "OPERATOR_REVIEWED_CLEANUP";
    }
    return "INVALID";
}

int recovery_exit_class_parse(const char *text, recovery_exit_class_t *value_out) {
    if (!text || !value_out) return -1;
    for (int value = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
         value <= RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP; ++value) {
        if (strcmp(text, recovery_exit_class_name((recovery_exit_class_t)value)) == 0) {
            *value_out = (recovery_exit_class_t)value;
            return 0;
        }
    }
    return -1;
}

const char *recovery_state_name(recovery_state_t value) {
    switch (value) {
        case RECOVERY_STATE_HEALTHY: return "HEALTHY";
        case RECOVERY_STATE_STOP_REQUESTED: return "STOP_REQUESTED";
        case RECOVERY_STATE_EXIT_CONFIRMED: return "EXIT_CONFIRMED";
        case RECOVERY_STATE_CRASH_SUSPECTED: return "CRASH_SUSPECTED";
        case RECOVERY_STATE_CLEANUP_UNVERIFIED: return "CLEANUP_UNVERIFIED";
        case RECOVERY_STATE_COOLDOWN: return "COOLDOWN";
        case RECOVERY_STATE_RESTART_ELIGIBLE: return "RESTART_ELIGIBLE";
        case RECOVERY_STATE_RESTART_BLOCKED: return "RESTART_BLOCKED";
        case RECOVERY_STATE_RESTART_LIMIT_REACHED: return "RESTART_LIMIT_REACHED";
        case RECOVERY_STATE_RECOVERY_UNVERIFIED: return "RECOVERY_UNVERIFIED";
    }
    return "RECOVERY_UNVERIFIED";
}

const char *recovery_decision_name(recovery_decision_t value) {
    switch (value) {
        case RECOVERY_DECISION_NO_ACTION: return "NO_ACTION";
        case RECOVERY_DECISION_WAIT_BACKOFF: return "WAIT_BACKOFF";
        case RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START: return "ELIGIBLE_FOR_ATTENDED_START";
        case RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED: return "BLOCK_CLEANUP_UNVERIFIED";
        case RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT: return "BLOCK_ATTEMPT_LIMIT";
        case RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE: return "BLOCK_INCONSISTENT_STATE";
        case RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED: return "BLOCK_SUPERVISOR_UNVERIFIED";
    }
    return "BLOCK_INCONSISTENT_STATE";
}

const char *recovery_process_state_name(recovery_process_state_t value) {
    switch (value) {
        case RECOVERY_PROCESS_UNKNOWN: return "UNKNOWN";
        case RECOVERY_PROCESS_RUNNING: return "RUNNING";
        case RECOVERY_PROCESS_CLEAN: return "CLEAN";
    }
    return "UNKNOWN";
}

const char *recovery_cleanup_state_name(recovery_cleanup_state_t value) {
    switch (value) {
        case RECOVERY_CLEANUP_UNVERIFIED: return "UNVERIFIED";
        case RECOVERY_CLEANUP_CONFIRMED: return "CONFIRMED";
    }
    return "UNVERIFIED";
}

void recovery_record_init(recovery_record_t *record) {
    if (!record) return;
    memset(record, 0, sizeof(*record));
    record->schema_version = RECOVERY_SCHEMA_VERSION;
    record->policy_version = RECOVERY_POLICY_VERSION;
    record->process_state = RECOVERY_PROCESS_UNKNOWN;
    record->cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    record->last_exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
}

static int valid_clock_id(const char *clock_id, int allow_empty) {
    if (!clock_id) return 0;
    size_t length = strlen(clock_id);
    if (length >= RECOVERY_CLOCK_ID_CAP || (!allow_empty && length == 0)) return 0;
    for (const unsigned char *p = (const unsigned char *)clock_id; *p; ++p) {
        if (!( (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
               (*p >= '0' && *p <= '9') || *p == '_' || *p == '-' || *p == '.')) return 0;
    }
    return 1;
}

int recovery_record_validate(const recovery_record_t *record) {
    if (!record || record->schema_version != RECOVERY_SCHEMA_VERSION ||
        record->policy_version != RECOVERY_POLICY_VERSION ||
        record->process_state < RECOVERY_PROCESS_UNKNOWN ||
        record->process_state > RECOVERY_PROCESS_CLEAN ||
        record->cleanup_state < RECOVERY_CLEANUP_UNVERIFIED ||
        record->cleanup_state > RECOVERY_CLEANUP_CONFIRMED ||
        record->last_exit_class < RECOVERY_EXIT_UNKNOWN_UNOBSERVED ||
        record->last_exit_class > RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP ||
        record->last_exit_signal < 0 || record->last_exit_signal > 255 ||
        record->attempt_count > RECOVERY_MAX_ATTEMPTS ||
        record->last_failure_wall_utc_seconds < 0 ||
        !valid_clock_id(record->last_failure_clock_id, record->last_failure_event_id == 0) ||
        !valid_clock_id(record->healthy_clock_id, record->healthy_since_monotonic_ns == 0)) return 0;
    if ((record->last_failure_event_id == 0) != (record->last_failure_monotonic_ns == 0) ||
        (record->last_failure_event_id == 0) != (record->last_failure_wall_utc_seconds == 0) ||
        (record->last_failure_event_id == 0) != (record->last_failure_clock_id[0] == '\0')) return 0;
    if ((record->healthy_since_monotonic_ns == 0) != (record->healthy_clock_id[0] == '\0')) return 0;
    if (record->last_exit_class == RECOVERY_EXIT_SIGNAL_TERMINATION) {
        if (record->last_exit_signal == 0) return 0;
    } else if (record->last_exit_signal != 0) return 0;
    for (uint32_t i = 0; i < record->attempt_count; ++i) {
        const recovery_attempt_t *attempt = &record->attempts[i];
        if (attempt->event_id == 0 || attempt->event_id > record->last_event_id ||
            attempt->monotonic_ns == 0 || attempt->wall_utc_seconds < 0 ||
            !valid_clock_id(attempt->clock_id, 0)) return 0;
        for (uint32_t j = 0; j < i; ++j) {
            if (record->attempts[j].event_id == attempt->event_id) return 0;
        }
    }
    if (record->last_failure_event_id > record->last_event_id) return 0;
    return 1;
}

static int clock_valid(const recovery_clock_t *clock) {
    return clock && clock->monotonic_valid && clock->wall_clock_valid &&
           clock->monotonic_ns != 0 && clock->wall_utc_seconds >= 0 &&
           valid_clock_id(clock->clock_id, 0);
}

int recovery_note_failure(recovery_record_t *record, recovery_exit_class_t exit_class,
                          int exit_signal, uint64_t event_id,
                          const recovery_clock_t *clock) {
    if (!recovery_record_validate(record) || !clock_valid(clock) || event_id == 0 ||
        exit_class < RECOVERY_EXIT_UNKNOWN_UNOBSERVED ||
        exit_class > RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP || exit_signal < 0 || exit_signal > 255 ||
        (exit_class == RECOVERY_EXIT_SIGNAL_TERMINATION && exit_signal == 0) ||
        (exit_class != RECOVERY_EXIT_SIGNAL_TERMINATION && exit_signal != 0)) return -1;
    if (event_id <= record->last_event_id) return 1;
    if (exit_class == RECOVERY_EXIT_GRACEFUL_CONFIRMED ||
        exit_class == RECOVERY_EXIT_EXPLICIT_STOP ||
        exit_class == RECOVERY_EXIT_TIMED_EXPIRY_ONLY ||
        exit_class == RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP) return -1;
    record->last_event_id = event_id;
    record->last_failure_event_id = event_id;
    record->last_failure_monotonic_ns = clock->monotonic_ns;
    record->last_failure_wall_utc_seconds = clock->wall_utc_seconds;
    snprintf(record->last_failure_clock_id, sizeof(record->last_failure_clock_id), "%s", clock->clock_id);
    record->last_exit_class = exit_class;
    record->last_exit_signal = exit_signal;
    record->process_state = RECOVERY_PROCESS_CLEAN;
    record->cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    record->healthy_since_monotonic_ns = 0;
    record->healthy_clock_id[0] = '\0';
    return 0;
}

static int prune_attempts(recovery_record_t *record, const recovery_clock_t *clock,
                          uint32_t *recent_count) {
    recovery_attempt_t kept[RECOVERY_MAX_ATTEMPTS];
    uint32_t count = 0;
    for (uint32_t i = 0; i < record->attempt_count; ++i) {
        const recovery_attempt_t *attempt = &record->attempts[i];
        if (strcmp(attempt->clock_id, clock->clock_id) != 0 ||
            clock->monotonic_ns < attempt->monotonic_ns) return -1;
        uint64_t age = clock->monotonic_ns - attempt->monotonic_ns;
        if (age <= RECOVERY_WINDOW_NS) kept[count++] = *attempt;
    }
    memset(record->attempts, 0, sizeof(record->attempts));
    if (count) memcpy(record->attempts, kept, count * sizeof(kept[0]));
    record->attempt_count = count;
    *recent_count = count;
    return 0;
}

int recovery_consume_attempt(recovery_record_t *record, uint64_t event_id,
                             const recovery_clock_t *clock) {
    if (!recovery_record_validate(record) || !clock_valid(clock) || event_id == 0 ||
        record->last_failure_event_id == 0) return -1;
    if (event_id <= record->last_event_id) return 1;
    uint32_t recent = 0;
    if (prune_attempts(record, clock, &recent) != 0) return -2;
    if (recent >= RECOVERY_MAX_ATTEMPTS) return -3;
    recovery_attempt_t *attempt = &record->attempts[record->attempt_count++];
    memset(attempt, 0, sizeof(*attempt));
    attempt->event_id = event_id;
    attempt->monotonic_ns = clock->monotonic_ns;
    attempt->wall_utc_seconds = clock->wall_utc_seconds;
    snprintf(attempt->clock_id, sizeof(attempt->clock_id), "%s", clock->clock_id);
    record->last_event_id = event_id;
    return 0;
}

int recovery_note_healthy(recovery_record_t *record, const recovery_clock_t *clock) {
    if (!recovery_record_validate(record) || !clock_valid(clock) ||
        record->cleanup_state != RECOVERY_CLEANUP_CONFIRMED) return -1;
    if (record->healthy_since_monotonic_ns == 0) {
        record->healthy_since_monotonic_ns = clock->monotonic_ns;
        snprintf(record->healthy_clock_id, sizeof(record->healthy_clock_id), "%s", clock->clock_id);
        return 0;
    }
    if (strcmp(record->healthy_clock_id, clock->clock_id) != 0 ||
        clock->monotonic_ns < record->healthy_since_monotonic_ns) {
        record->healthy_since_monotonic_ns = 0;
        record->healthy_clock_id[0] = '\0';
        return -1;
    }
    uint64_t healthy_ns = clock->monotonic_ns - record->healthy_since_monotonic_ns;
    if (healthy_ns < (uint64_t)RECOVERY_HEALTHY_RESET_SECONDS * UINT64_C(1000000000)) return 0;
    memset(record->attempts, 0, sizeof(record->attempts));
    record->attempt_count = 0;
    record->last_failure_event_id = 0;
    record->last_failure_monotonic_ns = 0;
    record->last_failure_wall_utc_seconds = 0;
    record->last_failure_clock_id[0] = '\0';
    record->healthy_since_monotonic_ns = 0;
    record->healthy_clock_id[0] = '\0';
    return 1;
}

int recovery_confirm_cleanup(recovery_record_t *record, int external_cleanup_evidence_verified,
                            int supervisor_exit_confirmed, int socket_and_lock_safe) {
    if (!recovery_record_validate(record) || record->process_state != RECOVERY_PROCESS_CLEAN ||
        !external_cleanup_evidence_verified || !supervisor_exit_confirmed || !socket_and_lock_safe) return -1;
    record->cleanup_state = RECOVERY_CLEANUP_CONFIRMED;
    return 0;
}

int recovery_reset_reviewed(recovery_record_t *record, int cleanup_reviewed,
                            int supervisor_state_reviewed) {
    if (!recovery_record_validate(record) || !cleanup_reviewed || !supervisor_state_reviewed) return -1;
    if (record->generation == UINT64_MAX) return -1;
    record->generation++;
    record->process_state = RECOVERY_PROCESS_CLEAN;
    record->cleanup_state = RECOVERY_CLEANUP_CONFIRMED;
    record->last_exit_class = RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP;
    record->last_exit_signal = 0;
    record->attempt_count = 0;
    memset(record->attempts, 0, sizeof(record->attempts));
    record->last_event_id = 0;
    record->last_failure_event_id = 0;
    record->last_failure_monotonic_ns = 0;
    record->last_failure_wall_utc_seconds = 0;
    record->last_failure_clock_id[0] = '\0';
    record->healthy_since_monotonic_ns = 0;
    record->healthy_clock_id[0] = '\0';
    return 0;
}

static recovery_result_t result_value(recovery_state_t state, recovery_decision_t decision,
                                      uint32_t attempts, uint32_t wait, int eligible,
                                      const char *reason) {
    recovery_result_t result;
    result.state = state;
    result.decision = decision;
    result.attempts_remaining = attempts;
    result.wait_seconds = wait;
    result.restart_eligibility = eligible;
    result.automatic_runtime_enabled = 0;
    result.reason = reason;
    return result;
}

int recovery_decide(const recovery_observations_t *observations,
                    const recovery_record_t *record, const recovery_clock_t *clock,
                    recovery_result_t *result) {
    if (!result) return -1;
    *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                           RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                           0, 0, 0, "invalid recovery input or record");
    if (!observations || !recovery_record_validate(record)) return -1;
    if (observations->explicit_stop ||
        observations->exit_class == RECOVERY_EXIT_EXPLICIT_STOP ||
        observations->exit_class == RECOVERY_EXIT_GRACEFUL_CONFIRMED ||
        observations->exit_class == RECOVERY_EXIT_TIMED_EXPIRY_ONLY) {
        *result = result_value(RECOVERY_STATE_EXIT_CONFIRMED, RECOVERY_DECISION_NO_ACTION,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "explicit stop or normal expiry does not request a restart");
        return 0;
    }
    if (!observations->exit_observed) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED, RECOVERY_DECISION_NO_ACTION,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "no supervisor-observed process exit; no cause or cleanup outcome is inferred");
        return 0;
    }
    if (observations->exit_class == RECOVERY_EXIT_UNKNOWN_UNOBSERVED ||
        observations->exit_class < RECOVERY_EXIT_UNKNOWN_UNOBSERVED ||
        observations->exit_class > RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "exit cause was not observed or is outside the versioned contract");
        return 0;
    }
    if (observations->release_failed || !observations->cleanup_status_known ||
        !observations->cleanup_confirmed || !observations->prior_assertion_ownership_known ||
        observations->prior_assertion_owned ||
        record->cleanup_state != RECOVERY_CLEANUP_CONFIRMED ||
        observations->exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
        observations->exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN) {
        *result = result_value(RECOVERY_STATE_CLEANUP_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "prior assertion cleanup is unresolved; time does not clear this blocker");
        return 0;
    }
    if (!observations->supervisor_status_known || !observations->supervisor_compatible ||
        observations->exit_class == RECOVERY_EXIT_SUPERVISOR_STATUS_UNKNOWN) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "supervisor exit and lifecycle compatibility are unverified");
        return 0;
    }
    if (observations->exit_class == RECOVERY_EXIT_SIGNAL_TERMINATION &&
        (observations->exit_signal <= 0 || observations->exit_signal > 255 ||
         observations->exit_signal != record->last_exit_signal)) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "signal-specific exit evidence is missing or inconsistent");
        return 0;
    }
    if (!observations->socket_status_known || !observations->socket_safe ||
        !observations->lock_status_known || !observations->lock_safe ||
        !observations->service_ready) {
        *result = result_value(RECOVERY_STATE_RESTART_BLOCKED,
                               RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "socket, lock, or service readiness is ambiguous");
        return 0;
    }
    if (!clock_valid(clock) || record->last_failure_event_id == 0) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                               RECOVERY_MAX_ATTEMPTS - record->attempt_count, 0, 0,
                               "monotonic timebase identity or failure timestamp is unavailable");
        return 0;
    }
    if (strcmp(record->last_failure_clock_id, clock->clock_id) != 0 ||
        clock->monotonic_ns < record->last_failure_monotonic_ns) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                               0, 0, 0,
                               "clock identity changed or monotonic time moved backward");
        return 0;
    }
    uint32_t recent_attempts = 0;
    recovery_record_t copy = *record;
    if (prune_attempts(&copy, clock, &recent_attempts) != 0) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                               0, 0, 0,
                               "persisted attempt timestamps cannot be reconciled with this clock");
        return 0;
    }
    uint32_t remaining = RECOVERY_MAX_ATTEMPTS - recent_attempts;
    if (recent_attempts >= RECOVERY_MAX_ATTEMPTS) {
        *result = result_value(RECOVERY_STATE_RESTART_LIMIT_REACHED,
                               RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT, 0, 0, 0,
                               "three restart attempts remain inside the rolling ten-minute window");
        return 0;
    }
    uint32_t delay = restart_backoff_seconds[recent_attempts];
    uint64_t delay_ns = (uint64_t)delay * UINT64_C(1000000000);
    if (UINT64_MAX - record->last_failure_monotonic_ns < delay_ns) {
        *result = result_value(RECOVERY_STATE_RECOVERY_UNVERIFIED,
                               RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
                               remaining, 0, 0, "backoff deadline overflows the monotonic clock");
        return 0;
    }
    uint64_t deadline = record->last_failure_monotonic_ns + delay_ns;
    if (clock->monotonic_ns < deadline) {
        uint64_t ns_left = deadline - clock->monotonic_ns;
        uint32_t seconds_left = (uint32_t)((ns_left + UINT64_C(999999999)) / UINT64_C(1000000000));
        *result = result_value(RECOVERY_STATE_COOLDOWN, RECOVERY_DECISION_WAIT_BACKOFF,
                               remaining, seconds_left, 0,
                               "bounded monotonic backoff has not elapsed");
        return 0;
    }
    *result = result_value(RECOVERY_STATE_RESTART_ELIGIBLE,
                           RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START,
                           remaining, 0, 1,
                           "policy is eligible for an attended start; no restart action is executed");
    return 0;
}

int recovery_evaluate_supervisor(const recovery_supervisor_adapter_t *adapter,
                                 const recovery_record_t *record,
                                 const recovery_clock_t *clock,
                                 recovery_result_t *result) {
    recovery_observations_t observations;
    memset(&observations, 0, sizeof(observations));
    if (!adapter || !adapter->observe || adapter->observe(adapter->context, &observations) != 0) {
        observations.exit_class = RECOVERY_EXIT_SUPERVISOR_STATUS_UNKNOWN;
        observations.exit_observed = 1;
        observations.supervisor_status_known = 0;
        observations.supervisor_compatible = 0;
    }
    return recovery_decide(&observations, record, clock, result);
}

static int trusted_directory(const struct stat *st, uid_t expected_owner, int final_parent) {
    if (!S_ISDIR(st->st_mode)) return 0;
    if ((st->st_uid == expected_owner || st->st_uid == 0) &&
        (st->st_mode & (S_IWGRP | S_IWOTH)) == 0) return 1;
    if (!final_parent && st->st_uid == 0 && (st->st_mode & S_ISVTX) != 0) return 1;
    return 0;
}

static int open_parent(const char *path, uid_t expected_owner, int *parent_fd,
                       char *basename, size_t basename_cap) {
    if (!path || path[0] != '/' || strlen(path) >= RECOVERY_PATH_CAP || !parent_fd ||
        !basename || basename_cap == 0) return -1;
    char copy[RECOVERY_PATH_CAP];
    snprintf(copy, sizeof(copy), "%s", path);
    size_t length = strlen(copy);
    if (length < 2 || copy[length - 1] == '/') return -1;
    int dirfd = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dirfd < 0) return -1;
    char *component = copy + 1;
    for (;;) {
        char *slash = strchr(component, '/');
        if (!slash) {
            if (!*component || strcmp(component, ".") == 0 || strcmp(component, "..") == 0 ||
                snprintf(basename, basename_cap, "%s", component) >= (int)basename_cap) {
                close(dirfd);
                return -1;
            }
            struct stat parent_stat;
            if (fstat(dirfd, &parent_stat) != 0 || !trusted_directory(&parent_stat, expected_owner, 1)) {
                close(dirfd);
                return -1;
            }
            *parent_fd = dirfd;
            return 0;
        }
        *slash = '\0';
        if (!*component || strcmp(component, ".") == 0 || strcmp(component, "..") == 0) {
            close(dirfd);
            return -1;
        }
        int next = openat(dirfd, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0) {
            close(dirfd);
            return -1;
        }
        struct stat next_stat;
        if (fstat(next, &next_stat) != 0 || !trusted_directory(&next_stat, expected_owner, 0)) {
            close(next);
            close(dirfd);
            return -1;
        }
        close(dirfd);
        dirfd = next;
        component = slash + 1;
    }
}

static void skip_ws(const char **p) {
    while (**p == ' ' || **p == '\n' || **p == '\r' || **p == '\t') (*p)++;
}

static int expect_char(const char **p, char expected) {
    skip_ws(p);
    if (**p != expected) return -1;
    (*p)++;
    return 0;
}

static int expect_key(const char **p, const char *expected) {
    skip_ws(p);
    if (**p != '"') return -1;
    (*p)++;
    size_t length = strlen(expected);
    if (strncmp(*p, expected, length) != 0 || (*p)[length] != '"') return -1;
    *p += length + 1;
    return expect_char(p, ':');
}

static int parse_u64(const char **p, uint64_t *value) {
    skip_ws(p);
    if (**p < '0' || **p > '9') return -1;
    const char *start = *p;
    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(*p, &end, 10);
    if (errno || end == *p || (*start == '0' && end > start + 1)) return -1;
    *value = (uint64_t)parsed;
    *p = end;
    return 0;
}

static int parse_i64(const char **p, int64_t *value) {
    skip_ws(p);
    if (!(**p == '-' || (**p >= '0' && **p <= '9')) ||
        (**p == '-' && ((*p)[1] < '0' || (*p)[1] > '9'))) return -1;
    const char *start = *p;
    errno = 0;
    char *end = NULL;
    long long parsed = strtoll(*p, &end, 10);
    if (errno || end == *p) return -1;
    const char *digits = *start == '-' ? start + 1 : start;
    if (*digits == '0' && end > digits + 1) return -1;
    *value = (int64_t)parsed;
    *p = end;
    return 0;
}

static int parse_string(const char **p, char *out, size_t cap) {
    if (!out || cap == 0 || expect_char(p, '"') != 0) return -1;
    size_t used = 0;
    while (**p && **p != '"') {
        unsigned char ch = (unsigned char)*(*p)++;
        if (ch < 0x20 || ch > 0x7e || ch == '\\' || used + 1 >= cap) return -1;
        out[used++] = (char)ch;
    }
    if (expect_char(p, '"') != 0) return -1;
    out[used] = '\0';
    return 0;
}

static int parse_process_state(const char *text, recovery_process_state_t *value) {
    if (strcmp(text, "UNKNOWN") == 0) *value = RECOVERY_PROCESS_UNKNOWN;
    else if (strcmp(text, "RUNNING") == 0) *value = RECOVERY_PROCESS_RUNNING;
    else if (strcmp(text, "CLEAN") == 0) *value = RECOVERY_PROCESS_CLEAN;
    else return -1;
    return 0;
}

static int parse_cleanup_state(const char *text, recovery_cleanup_state_t *value) {
    if (strcmp(text, "UNVERIFIED") == 0) *value = RECOVERY_CLEANUP_UNVERIFIED;
    else if (strcmp(text, "CONFIRMED") == 0) *value = RECOVERY_CLEANUP_CONFIRMED;
    else return -1;
    return 0;
}

static int read_record_json(const char *buffer, recovery_record_t *record,
                            recovery_store_result_t *failure) {
    const char *p = buffer;
    uint64_t number = 0;
    int64_t signed_number = 0;
    char token[RECOVERY_CLOCK_ID_CAP];
    recovery_record_t parsed;
    recovery_record_init(&parsed);
    if (expect_char(&p, '{') != 0 || expect_key(&p, "schema_version") != 0 ||
        parse_u64(&p, &number) != 0) goto corrupt;
    if (number != RECOVERY_SCHEMA_VERSION) {
        *failure = RECOVERY_STORE_UNSUPPORTED;
        return -1;
    }
    parsed.schema_version = (uint32_t)number;
    if (expect_char(&p, ',') != 0 || expect_key(&p, "policy_version") != 0 ||
        parse_u64(&p, &number) != 0) goto corrupt;
    if (number != RECOVERY_POLICY_VERSION) {
        *failure = RECOVERY_STORE_UNSUPPORTED;
        return -1;
    }
    parsed.policy_version = (uint32_t)number;
    if (expect_char(&p, ',') != 0 || expect_key(&p, "generation") != 0 ||
        parse_u64(&p, &parsed.generation) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "process_state") != 0 || parse_string(&p, token, sizeof(token)) != 0 ||
        parse_process_state(token, &parsed.process_state) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "cleanup_state") != 0 || parse_string(&p, token, sizeof(token)) != 0 ||
        parse_cleanup_state(token, &parsed.cleanup_state) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_exit_class") != 0 || parse_string(&p, token, sizeof(token)) != 0 ||
        recovery_exit_class_parse(token, &parsed.last_exit_class) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_exit_signal") != 0 || parse_i64(&p, &signed_number) != 0 ||
        signed_number < 0 || signed_number > 255 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "attempts") != 0 ||
        expect_char(&p, '[') != 0) goto corrupt;
    parsed.last_exit_signal = (int)signed_number;
    for (;;) {
        skip_ws(&p);
        if (*p == ']') { p++; break; }
        if (parsed.attempt_count >= RECOVERY_MAX_ATTEMPTS) goto corrupt;
        recovery_attempt_t *attempt = &parsed.attempts[parsed.attempt_count];
        if (expect_char(&p, '{') != 0 || expect_key(&p, "event_id") != 0 ||
            parse_u64(&p, &attempt->event_id) != 0 || expect_char(&p, ',') != 0 ||
            expect_key(&p, "monotonic_ns") != 0 || parse_u64(&p, &attempt->monotonic_ns) != 0 ||
            expect_char(&p, ',') != 0 || expect_key(&p, "wall_utc_seconds") != 0 ||
            parse_i64(&p, &attempt->wall_utc_seconds) != 0 || expect_char(&p, ',') != 0 ||
            expect_key(&p, "clock_id") != 0 || parse_string(&p, attempt->clock_id, sizeof(attempt->clock_id)) != 0 ||
            expect_char(&p, '}') != 0) goto corrupt;
        parsed.attempt_count++;
        skip_ws(&p);
        if (*p == ',') { p++; continue; }
        if (*p == ']') { p++; break; }
        goto corrupt;
    }
    if (expect_char(&p, ',') != 0 || expect_key(&p, "last_event_id") != 0 ||
        parse_u64(&p, &parsed.last_event_id) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_failure_event_id") != 0 ||
        parse_u64(&p, &parsed.last_failure_event_id) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_failure_monotonic_ns") != 0 ||
        parse_u64(&p, &parsed.last_failure_monotonic_ns) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_failure_wall_utc_seconds") != 0 ||
        parse_i64(&p, &parsed.last_failure_wall_utc_seconds) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "last_failure_clock_id") != 0 ||
        parse_string(&p, parsed.last_failure_clock_id, sizeof(parsed.last_failure_clock_id)) != 0 ||
        expect_char(&p, ',') != 0 || expect_key(&p, "healthy_since_monotonic_ns") != 0 ||
        parse_u64(&p, &parsed.healthy_since_monotonic_ns) != 0 || expect_char(&p, ',') != 0 ||
        expect_key(&p, "healthy_clock_id") != 0 ||
        parse_string(&p, parsed.healthy_clock_id, sizeof(parsed.healthy_clock_id)) != 0 ||
        expect_char(&p, '}') != 0) goto corrupt;
    skip_ws(&p);
    if (*p != '\0' || !recovery_record_validate(&parsed)) goto corrupt;
    *record = parsed;
    return 0;
corrupt:
    *failure = RECOVERY_STORE_CORRUPT;
    return -1;
}

static int validate_existing_target(int parent_fd, const char *basename, uid_t owner,
                                    int *exists, char *detail, size_t detail_cap) {
    struct stat st;
    if (fstatat(parent_fd, basename, &st, AT_SYMLINK_NOFOLLOW) != 0) {
        if (errno == ENOENT) { *exists = 0; return 0; }
        set_detail(detail, detail_cap, "cannot inspect recovery record path");
        return -1;
    }
    *exists = 1;
    if (!S_ISREG(st.st_mode) || st.st_nlink != 1 || st.st_uid != owner ||
        (st.st_mode & 07777) != RECOVERY_FILE_MODE || st.st_size < 0 ||
        st.st_size > RECOVERY_MAX_RECORD_BYTES) {
        set_detail(detail, detail_cap, "recovery record target is not a private owned regular file");
        return -1;
    }
    return 0;
}

recovery_store_result_t recovery_store_load(const char *path, uid_t expected_owner,
                                            recovery_record_t *record,
                                            char *detail, size_t detail_cap) {
    if (!record || !path || path[0] != '/') {
        set_detail(detail, detail_cap, "recovery record path must be absolute");
        return RECOVERY_STORE_UNSAFE;
    }
    char basename[256];
    int dir_fd = -1;
    if (open_parent(path, expected_owner, &dir_fd, basename, sizeof(basename)) != 0) {
        set_detail(detail, detail_cap, "recovery record parent is unsafe or inaccessible");
        return RECOVERY_STORE_UNSAFE;
    }
    struct stat st;
    if (fstatat(dir_fd, basename, &st, AT_SYMLINK_NOFOLLOW) != 0) {
        int saved = errno;
        close(dir_fd);
        if (saved == ENOENT) {
            set_detail(detail, detail_cap, "recovery record is missing; cleanup is unverified");
            return RECOVERY_STORE_MISSING;
        }
        set_detail(detail, detail_cap, "cannot inspect recovery record");
        return RECOVERY_STORE_IO_ERROR;
    }
    if (!S_ISREG(st.st_mode) || st.st_nlink != 1 || st.st_uid != expected_owner ||
        (st.st_mode & 07777) != RECOVERY_FILE_MODE) {
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery record ownership, mode, type, or link count is unsafe");
        return RECOVERY_STORE_UNSAFE;
    }
    if (st.st_size < 1 || st.st_size > RECOVERY_MAX_RECORD_BYTES) {
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery record size is outside the supported bound");
        return RECOVERY_STORE_CORRUPT;
    }
    int fd = openat(dir_fd, basename, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        close(dir_fd);
        set_detail(detail, detail_cap, "cannot open recovery record without following links");
        return RECOVERY_STORE_UNSAFE;
    }
    struct stat opened;
    if (fstat(fd, &opened) != 0 || !S_ISREG(opened.st_mode) || opened.st_nlink != 1 ||
        opened.st_uid != expected_owner || (opened.st_mode & 07777) != RECOVERY_FILE_MODE ||
        opened.st_dev != st.st_dev || opened.st_ino != st.st_ino || opened.st_size != st.st_size) {
        close(fd);
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery record changed or became unsafe while opening");
        return RECOVERY_STORE_UNSAFE;
    }
    char buffer[RECOVERY_MAX_RECORD_BYTES + 1];
    size_t used = 0;
    while (used < (size_t)opened.st_size) {
        ssize_t n = read(fd, buffer + used, (size_t)opened.st_size - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
    }
    struct stat after;
    int stable = used == (size_t)opened.st_size && fstat(fd, &after) == 0 &&
                 after.st_dev == opened.st_dev && after.st_ino == opened.st_ino &&
                 after.st_nlink == 1 && after.st_uid == expected_owner &&
                 (after.st_mode & 07777) == RECOVERY_FILE_MODE && after.st_size == (off_t)used;
    close(fd);
    close(dir_fd);
    if (!stable || memchr(buffer, '\0', used) != NULL) {
        set_detail(detail, detail_cap, "recovery record changed or could not be read completely");
        return RECOVERY_STORE_UNSAFE;
    }
    buffer[used] = '\0';
    recovery_store_result_t failure = RECOVERY_STORE_CORRUPT;
    if (read_record_json(buffer, record, &failure) != 0) {
        set_detail(detail, detail_cap, failure == RECOVERY_STORE_UNSUPPORTED ?
                   "recovery record schema or policy version is unsupported" :
                   "recovery record JSON is malformed or internally inconsistent");
        return failure;
    }
    set_detail(detail, detail_cap, "recovery record loaded");
    return RECOVERY_STORE_OK;
}

static int serialize_record(const recovery_record_t *record, char *buffer, size_t cap) {
    if (!recovery_record_validate(record) || !buffer || cap == 0) return -1;
    int n = snprintf(buffer, cap,
        "{\n"
        "  \"schema_version\": %u,\n"
        "  \"policy_version\": %u,\n"
        "  \"generation\": %" PRIu64 ",\n"
        "  \"process_state\": \"%s\",\n"
        "  \"cleanup_state\": \"%s\",\n"
        "  \"last_exit_class\": \"%s\",\n"
        "  \"last_exit_signal\": %d,\n"
        "  \"attempts\": [",
        record->schema_version, record->policy_version, record->generation,
        recovery_process_state_name(record->process_state),
        recovery_cleanup_state_name(record->cleanup_state),
        recovery_exit_class_name(record->last_exit_class), record->last_exit_signal);
    if (n < 0 || (size_t)n >= cap) return -1;
    size_t used = (size_t)n;
    for (uint32_t i = 0; i < record->attempt_count; ++i) {
        const recovery_attempt_t *attempt = &record->attempts[i];
        n = snprintf(buffer + used, cap - used,
                     "%s{\"event_id\": %" PRIu64 ", \"monotonic_ns\": %" PRIu64
                     ", \"wall_utc_seconds\": %" PRId64 ", \"clock_id\": \"%s\"}",
                     i ? ", " : "", attempt->event_id, attempt->monotonic_ns,
                     attempt->wall_utc_seconds, attempt->clock_id);
        if (n < 0 || (size_t)n >= cap - used) return -1;
        used += (size_t)n;
    }
    n = snprintf(buffer + used, cap - used,
        "],\n"
        "  \"last_event_id\": %" PRIu64 ",\n"
        "  \"last_failure_event_id\": %" PRIu64 ",\n"
        "  \"last_failure_monotonic_ns\": %" PRIu64 ",\n"
        "  \"last_failure_wall_utc_seconds\": %" PRId64 ",\n"
        "  \"last_failure_clock_id\": \"%s\",\n"
        "  \"healthy_since_monotonic_ns\": %" PRIu64 ",\n"
        "  \"healthy_clock_id\": \"%s\"\n"
        "}\n",
        record->last_event_id, record->last_failure_event_id,
        record->last_failure_monotonic_ns, record->last_failure_wall_utc_seconds,
        record->last_failure_clock_id, record->healthy_since_monotonic_ns,
        record->healthy_clock_id);
    if (n < 0 || (size_t)n >= cap - used) return -1;
    return (int)(used + (size_t)n);
}

static int write_all(int fd, const char *buffer, size_t length) {
    size_t used = 0;
    while (used < length) {
        ssize_t n = write(fd, buffer + used, length - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        used += (size_t)n;
    }
    return 0;
}

int recovery_store_save_atomic(const char *path, uid_t expected_owner,
                               const recovery_record_t *record,
                               char *detail, size_t detail_cap) {
    if (!recovery_record_validate(record)) {
        set_detail(detail, detail_cap, "refusing to save invalid recovery metadata");
        return -1;
    }
    char basename[256];
    int dir_fd = -1;
    if (open_parent(path, expected_owner, &dir_fd, basename, sizeof(basename)) != 0) {
        set_detail(detail, detail_cap, "recovery record parent is unsafe or inaccessible");
        return -1;
    }
    int exists = 0;
    if (validate_existing_target(dir_fd, basename, expected_owner, &exists, detail, detail_cap) != 0) {
        close(dir_fd);
        return -1;
    }
    char temp_name[300];
    if (snprintf(temp_name, sizeof(temp_name), ".%s.tmp.%ld", basename, (long)getpid()) >=
        (int)sizeof(temp_name)) {
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery temporary filename exceeds the supported bound");
        return -1;
    }
    int fd = openat(dir_fd, temp_name,
                    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
                    RECOVERY_FILE_MODE);
    if (fd < 0) {
        close(dir_fd);
        set_detail(detail, detail_cap, "cannot create exclusive recovery temporary file");
        return -1;
    }
    char buffer[RECOVERY_MAX_RECORD_BYTES + 1];
    int length = serialize_record(record, buffer, sizeof(buffer));
    int write_ok = length > 0 && (size_t)length <= RECOVERY_MAX_RECORD_BYTES &&
                   fchmod(fd, RECOVERY_FILE_MODE) == 0 && write_all(fd, buffer, (size_t)length) == 0 &&
                   fsync(fd) == 0;
    if (!write_ok) {
        close(fd);
        unlinkat(dir_fd, temp_name, 0);
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery temporary file could not be written and synced");
        return -1;
    }
    if (close(fd) != 0) {
        unlinkat(dir_fd, temp_name, 0);
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery temporary file close failed");
        return -1;
    }
#ifdef IOSCAFFEINATE_RECOVERY_TESTING
    if (fail_save_before_rename) {
        close(dir_fd);
        set_detail(detail, detail_cap, "injected interruption before atomic recovery replacement");
        return -1;
    }
#endif
    if (renameat(dir_fd, temp_name, dir_fd, basename) != 0) {
        int saved = errno;
        unlinkat(dir_fd, temp_name, 0);
        close(dir_fd);
        set_detail(detail, detail_cap, saved == ENOENT ? "recovery record replacement failed" : strerror(saved));
        return -1;
    }
    if (fsync(dir_fd) != 0) {
        close(dir_fd);
        set_detail(detail, detail_cap, "recovery record directory sync failed after replacement");
        return -1;
    }
    close(dir_fd);
    (void)exists;
    set_detail(detail, detail_cap, "recovery record atomically replaced and synced");
    return 0;
}

int recovery_store_consume_attempt(const char *path, uid_t expected_owner,
                                  recovery_record_t *record, uint64_t event_id,
                                  const recovery_clock_t *clock,
                                  char *detail, size_t detail_cap) {
    if (!record || !recovery_record_validate(record)) {
        set_detail(detail, detail_cap, "refusing to consume an attempt from invalid recovery metadata");
        return -1;
    }
    recovery_record_t next = *record;
    int consumed = recovery_consume_attempt(&next, event_id, clock);
    if (consumed != 0) {
        set_detail(detail, detail_cap, consumed == 1 ?
                   "duplicate recovery event was already accounted for" :
                   consumed == -2 ? "attempt history cannot be reconciled with the current clock" :
                   consumed == -3 ? "restart attempt limit is already reached" :
                   "recovery attempt could not be accounted for");
        return consumed;
    }
    if (recovery_store_save_atomic(path, expected_owner, &next, detail, detail_cap) != 0) return -1;
    *record = next;
    set_detail(detail, detail_cap, "restart attempt consumed and durably synced before operation");
    return 0;
}

int recovery_store_begin_run(const char *path, uid_t expected_owner,
                             recovery_record_t *record, int *assertions_blocked,
                             char *detail, size_t detail_cap) {
    if (!record || !assertions_blocked) return -1;
    recovery_record_t loaded;
    recovery_store_result_t loaded_state = recovery_store_load(path, expected_owner, &loaded,
                                                                detail, detail_cap);
    int blocked = 1;
    if (loaded_state == RECOVERY_STORE_OK) {
        blocked = loaded.process_state != RECOVERY_PROCESS_CLEAN ||
                  loaded.cleanup_state != RECOVERY_CLEANUP_CONFIRMED ||
                  loaded.last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
                  loaded.last_exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN;
        if (loaded.process_state == RECOVERY_PROCESS_RUNNING) {
            loaded.last_exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
            loaded.last_exit_signal = 0;
            loaded.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
        }
        if (loaded.generation == UINT64_MAX) {
            *assertions_blocked = 1;
            set_detail(detail, detail_cap, "recovery generation counter is exhausted");
            return -1;
        }
        loaded.generation++;
        loaded.process_state = RECOVERY_PROCESS_RUNNING;
        if (recovery_store_save_atomic(path, expected_owner, &loaded, detail, detail_cap) != 0) {
            *assertions_blocked = 1;
            *record = loaded;
            return -1;
        }
        *record = loaded;
        *assertions_blocked = blocked;
        if (blocked) set_detail(detail, detail_cap, "prior cleanup is unverified; new assertions are blocked");
        else set_detail(detail, detail_cap, "journal was clean; daemon run marker is durable");
        return 0;
    }
    if (loaded_state == RECOVERY_STORE_MISSING) {
        recovery_record_init(&loaded);
        loaded.generation = 1;
        loaded.process_state = RECOVERY_PROCESS_RUNNING;
        loaded.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
        loaded.last_exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
        if (recovery_store_save_atomic(path, expected_owner, &loaded, detail, detail_cap) == 0) {
            *record = loaded;
            *assertions_blocked = 1;
            set_detail(detail, detail_cap, "initial journal cannot prove prior assertion cleanup; new assertions are blocked");
            return 0;
        }
    }
    recovery_record_init(record);
    record->process_state = RECOVERY_PROCESS_RUNNING;
    record->cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    *assertions_blocked = 1;
    if (loaded_state == RECOVERY_STORE_UNSUPPORTED)
        set_detail(detail, detail_cap, "unsupported journal is preserved; new assertions are blocked");
    else if (loaded_state == RECOVERY_STORE_CORRUPT)
        set_detail(detail, detail_cap, "corrupt journal is preserved; new assertions are blocked");
    else if (loaded_state == RECOVERY_STORE_UNSAFE)
        set_detail(detail, detail_cap, "unsafe journal is preserved; new assertions are blocked");
    return -1;
}

int recovery_store_finish_run(const char *path, uid_t expected_owner,
                              recovery_record_t *record, int current_cleanup_confirmed,
                              recovery_exit_class_t exit_class, int exit_signal,
                              char *detail, size_t detail_cap) {
    if (!record || !recovery_record_validate(record) || exit_class < RECOVERY_EXIT_UNKNOWN_UNOBSERVED ||
        exit_class > RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP) return -1;
    int cleanup_ok = record->cleanup_state == RECOVERY_CLEANUP_CONFIRMED &&
                     current_cleanup_confirmed;
    if (exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
        exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN) cleanup_ok = 0;
    if (!cleanup_ok &&
        (record->last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
         record->last_exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN)) {
        exit_class = record->last_exit_class;
        exit_signal = 0;
    }
    record->process_state = RECOVERY_PROCESS_CLEAN;
    record->cleanup_state = cleanup_ok ? RECOVERY_CLEANUP_CONFIRMED : RECOVERY_CLEANUP_UNVERIFIED;
    record->last_exit_class = exit_class;
    record->last_exit_signal = exit_class == RECOVERY_EXIT_SIGNAL_TERMINATION ? exit_signal : 0;
    if (!recovery_record_validate(record)) {
        set_detail(detail, detail_cap, "exit classification or signal is inconsistent");
        return -1;
    }
    return recovery_store_save_atomic(path, expected_owner, record, detail, detail_cap);
}
