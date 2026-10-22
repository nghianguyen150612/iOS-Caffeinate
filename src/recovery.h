#ifndef IOSCAFFEINATE_RECOVERY_H
#define IOSCAFFEINATE_RECOVERY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define RECOVERY_SCHEMA_VERSION 1
#define RECOVERY_POLICY_VERSION 1
#define RECOVERY_MAX_ATTEMPTS 3
#define RECOVERY_WINDOW_SECONDS 600
#define RECOVERY_HEALTHY_RESET_SECONDS 1800
#define RECOVERY_MAX_RECORD_BYTES 4096
#define RECOVERY_CLOCK_ID_CAP 64
#define RECOVERY_DEFAULT_PATH "/var/lib/ioscaffeinate/recovery-state.json"

typedef enum {
    RECOVERY_EXIT_UNKNOWN_UNOBSERVED = 0,
    RECOVERY_EXIT_GRACEFUL_CONFIRMED,
    RECOVERY_EXIT_EXPLICIT_STOP,
    RECOVERY_EXIT_TIMED_EXPIRY_ONLY,
    RECOVERY_EXIT_UNEXPECTED_EXIT,
    RECOVERY_EXIT_SIGNAL_TERMINATION,
    RECOVERY_EXIT_STARTUP_FAILURE,
    RECOVERY_EXIT_RELEASE_FAILURE,
    RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN,
    RECOVERY_EXIT_SUPERVISOR_STATUS_UNKNOWN,
    RECOVERY_EXIT_REPEATED_FAILURE,
    RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP
} recovery_exit_class_t;

typedef enum {
    RECOVERY_PROCESS_UNKNOWN = 0,
    RECOVERY_PROCESS_RUNNING,
    RECOVERY_PROCESS_CLEAN
} recovery_process_state_t;

typedef enum {
    RECOVERY_CLEANUP_UNVERIFIED = 0,
    RECOVERY_CLEANUP_CONFIRMED
} recovery_cleanup_state_t;

typedef enum {
    RECOVERY_STATE_HEALTHY = 0,
    RECOVERY_STATE_STOP_REQUESTED,
    RECOVERY_STATE_EXIT_CONFIRMED,
    RECOVERY_STATE_CRASH_SUSPECTED,
    RECOVERY_STATE_CLEANUP_UNVERIFIED,
    RECOVERY_STATE_COOLDOWN,
    RECOVERY_STATE_RESTART_ELIGIBLE,
    RECOVERY_STATE_RESTART_BLOCKED,
    RECOVERY_STATE_RESTART_LIMIT_REACHED,
    RECOVERY_STATE_RECOVERY_UNVERIFIED
} recovery_state_t;

typedef enum {
    RECOVERY_DECISION_NO_ACTION = 0,
    RECOVERY_DECISION_WAIT_BACKOFF,
    RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START,
    RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED,
    RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT,
    RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE,
    RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED
} recovery_decision_t;

typedef enum {
    RECOVERY_STORE_OK = 0,
    RECOVERY_STORE_MISSING,
    RECOVERY_STORE_UNSAFE,
    RECOVERY_STORE_CORRUPT,
    RECOVERY_STORE_UNSUPPORTED,
    RECOVERY_STORE_IO_ERROR
} recovery_store_result_t;

typedef struct {
    uint64_t event_id;
    uint64_t monotonic_ns;
    int64_t wall_utc_seconds;
    char clock_id[RECOVERY_CLOCK_ID_CAP];
} recovery_attempt_t;

/* This record contains accounting metadata only. It never stores IOKit IDs. */
typedef struct {
    uint32_t schema_version;
    uint32_t policy_version;
    uint64_t generation;
    recovery_process_state_t process_state;
    recovery_cleanup_state_t cleanup_state;
    recovery_exit_class_t last_exit_class;
    int last_exit_signal;
    uint32_t attempt_count;
    recovery_attempt_t attempts[RECOVERY_MAX_ATTEMPTS];
    uint64_t last_event_id;
    uint64_t last_failure_event_id;
    uint64_t last_failure_monotonic_ns;
    int64_t last_failure_wall_utc_seconds;
    char last_failure_clock_id[RECOVERY_CLOCK_ID_CAP];
    uint64_t healthy_since_monotonic_ns;
    char healthy_clock_id[RECOVERY_CLOCK_ID_CAP];
} recovery_record_t;

typedef struct {
    uint64_t monotonic_ns;
    int64_t wall_utc_seconds;
    const char *clock_id;
    int monotonic_valid;
    int wall_clock_valid;
} recovery_clock_t;

typedef struct {
    recovery_exit_class_t exit_class;
    int exit_signal;
    int exit_observed;
    int explicit_stop;
    int release_failed;
    int prior_assertion_ownership_known;
    int prior_assertion_owned;
    int cleanup_status_known;
    int cleanup_confirmed;
    int supervisor_status_known;
    int supervisor_compatible;
    int socket_status_known;
    int socket_safe;
    int lock_status_known;
    int lock_safe;
    int service_ready;
} recovery_observations_t;

typedef struct {
    recovery_state_t state;
    recovery_decision_t decision;
    uint32_t attempts_remaining;
    uint32_t wait_seconds;
    int restart_eligibility;
    int automatic_runtime_enabled;
    const char *reason;
} recovery_result_t;

/* Injectable observer boundary for a future verified supervisor; no action callback exists. */
typedef int (*recovery_supervisor_observer_fn)(void *context,
                                              recovery_observations_t *observations);
typedef struct {
    recovery_supervisor_observer_fn observe;
    void *context;
} recovery_supervisor_adapter_t;

const char *recovery_exit_class_name(recovery_exit_class_t value);
int recovery_exit_class_parse(const char *text, recovery_exit_class_t *value_out);
const char *recovery_state_name(recovery_state_t value);
const char *recovery_decision_name(recovery_decision_t value);
const char *recovery_process_state_name(recovery_process_state_t value);
const char *recovery_cleanup_state_name(recovery_cleanup_state_t value);

void recovery_record_init(recovery_record_t *record);
int recovery_record_validate(const recovery_record_t *record);
int recovery_note_failure(recovery_record_t *record, recovery_exit_class_t exit_class,
                          int exit_signal, uint64_t event_id,
                          const recovery_clock_t *clock);
int recovery_consume_attempt(recovery_record_t *record, uint64_t event_id,
                             const recovery_clock_t *clock);
int recovery_note_healthy(recovery_record_t *record, const recovery_clock_t *clock);
int recovery_confirm_cleanup(recovery_record_t *record, int external_cleanup_evidence_verified,
                            int supervisor_exit_confirmed, int socket_and_lock_safe);
int recovery_reset_reviewed(recovery_record_t *record, int cleanup_reviewed,
                            int supervisor_state_reviewed);
int recovery_decide(const recovery_observations_t *observations,
                    const recovery_record_t *record, const recovery_clock_t *clock,
                    recovery_result_t *result);
int recovery_evaluate_supervisor(const recovery_supervisor_adapter_t *adapter,
                                 const recovery_record_t *record,
                                 const recovery_clock_t *clock,
                                 recovery_result_t *result);

recovery_store_result_t recovery_store_load(const char *path, uid_t expected_owner,
                                            recovery_record_t *record,
                                            char *detail, size_t detail_cap);
int recovery_store_save_atomic(const char *path, uid_t expected_owner,
                               const recovery_record_t *record,
                               char *detail, size_t detail_cap);
/* Caller serializes writers; success means the attempt is durable before work starts. */
int recovery_store_consume_attempt(const char *path, uid_t expected_owner,
                                  recovery_record_t *record, uint64_t event_id,
                                  const recovery_clock_t *clock,
                                  char *detail, size_t detail_cap);
/* Called only while the daemon socket lock is held: the daemon is the sole writer. */
int recovery_store_begin_run(const char *path, uid_t expected_owner,
                             recovery_record_t *record, int *assertions_blocked,
                             char *detail, size_t detail_cap);
int recovery_store_finish_run(const char *path, uid_t expected_owner,
                              recovery_record_t *record, int current_cleanup_confirmed,
                              recovery_exit_class_t exit_class, int exit_signal,
                              char *detail, size_t detail_cap);

#ifdef IOSCAFFEINATE_RECOVERY_TESTING
void recovery_test_fail_save_before_rename(int enabled);
#endif

#endif
