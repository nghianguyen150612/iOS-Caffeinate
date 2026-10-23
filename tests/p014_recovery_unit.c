#define _POSIX_C_SOURCE 200809L
#define IOSCAFFEINATE_RECOVERY_TESTING 1
#include "../src/recovery.h"
#include "../src/service.h"

#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static unsigned checks;

static recovery_clock_t test_clock(uint64_t monotonic_ns, int64_t wall, const char *clock_id) {
    recovery_clock_t value = {
        .monotonic_ns = monotonic_ns,
        .wall_utc_seconds = wall,
        .clock_id = clock_id,
        .monotonic_valid = 1,
        .wall_clock_valid = 1,
    };
    return value;
}

static recovery_record_t clean_record(void) {
    recovery_record_t record;
    recovery_record_init(&record);
    record.generation = 1;
    record.process_state = RECOVERY_PROCESS_CLEAN;
    record.cleanup_state = RECOVERY_CLEANUP_CONFIRMED;
    record.last_exit_class = RECOVERY_EXIT_GRACEFUL_CONFIRMED;
    assert(recovery_record_validate(&record));
    return record;
}

static recovery_observations_t safe_unexpected_exit(void) {
    recovery_observations_t facts;
    memset(&facts, 0, sizeof(facts));
    facts.exit_class = RECOVERY_EXIT_UNEXPECTED_EXIT;
    facts.exit_observed = 1;
    facts.prior_assertion_ownership_known = 1;
    facts.cleanup_status_known = 1;
    facts.cleanup_confirmed = 1;
    facts.supervisor_status_known = 1;
    facts.supervisor_compatible = 1;
    facts.socket_status_known = 1;
    facts.socket_safe = 1;
    facts.lock_status_known = 1;
    facts.lock_safe = 1;
    facts.service_ready = 1;
    return facts;
}

static int mock_supervisor_observer(void *context, recovery_observations_t *observations) {
    if (!context || !observations) return -1;
    *observations = *(const recovery_observations_t *)context;
    return 0;
}

static int failed_supervisor_observer(void *context, recovery_observations_t *observations) {
    (void)context;
    (void)observations;
    return -1;
}

static void add_failure(recovery_record_t *record, recovery_exit_class_t cls, int signal,
                        uint64_t event_id, const recovery_clock_t *clock) {
    assert(recovery_note_failure(record, cls, signal, event_id, clock) == 0);
    assert(recovery_confirm_cleanup(record, 1, 1, 1) == 0);
}

static void test_exit_classification_contract(void) {
    recovery_exit_class_t parsed = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
    assert(recovery_exit_class_parse("SIGNAL_TERMINATION", &parsed) == 0);
    assert(parsed == RECOVERY_EXIT_SIGNAL_TERMINATION);
    assert(recovery_exit_class_parse("SIGKILL_GRACEFUL", &parsed) != 0);
    assert(strcmp(recovery_exit_class_name(RECOVERY_EXIT_UNKNOWN_UNOBSERVED), "UNKNOWN_UNOBSERVED") == 0);
    assert(strcmp(recovery_exit_class_name((recovery_exit_class_t)99), "INVALID") == 0);
    checks++;
}

static void test_stop_expiry_and_unknown_are_distinct(void) {
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(1000000000), 1800000000, "boot-a");
    recovery_result_t result;
    recovery_observations_t facts = safe_unexpected_exit();
    facts.exit_class = RECOVERY_EXIT_GRACEFUL_CONFIRMED;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_NO_ACTION);
    facts.exit_class = RECOVERY_EXIT_EXPLICIT_STOP;
    facts.explicit_stop = 1;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.state == RECOVERY_STATE_EXIT_CONFIRMED);
    facts.explicit_stop = 0;
    facts.exit_class = RECOVERY_EXIT_TIMED_EXPIRY_ONLY;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_NO_ACTION);
    facts.exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED);
    facts.exit_observed = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_NO_ACTION);
    checks++;
}

static void test_injected_supervisor_observer_is_policy_only(void) {
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(10000000000), 1800000000, "boot-a");
    recovery_observations_t facts = safe_unexpected_exit();
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock);
    clock.monotonic_ns += UINT64_C(5000000000);
    recovery_supervisor_adapter_t adapter = {
        .observe = mock_supervisor_observer,
        .context = &facts,
    };
    recovery_result_t result;
    assert(recovery_evaluate_supervisor(&adapter, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START);
    assert(result.restart_eligibility == 1 && result.automatic_runtime_enabled == 0);

    adapter.observe = failed_supervisor_observer;
    assert(recovery_evaluate_supervisor(&adapter, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    assert(result.automatic_runtime_enabled == 0);
    checks++;
}

static void test_cleanup_supervisor_socket_and_lock_blocks(void) {
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(1000000000), 1800000000, "boot-a");
    recovery_result_t result;
    recovery_observations_t facts = safe_unexpected_exit();
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock);

    facts.cleanup_confirmed = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    facts.cleanup_confirmed = 1;
    facts.release_failed = 1;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    facts.release_failed = 0;
    facts.prior_assertion_owned = 1;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    facts.prior_assertion_owned = 0;
    facts.supervisor_status_known = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED);
    facts.supervisor_status_known = 1;
    facts.socket_safe = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE);
    facts.socket_safe = 1;
    facts.lock_safe = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE);
    checks++;
}

static void test_backoff_attempt_accounting_and_duplicate_events(void) {
    const uint64_t second = UINT64_C(1000000000);
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(100000000000), 1800000000, "boot-a");
    recovery_result_t result;
    recovery_observations_t facts = safe_unexpected_exit();
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock);
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_WAIT_BACKOFF && result.wait_seconds == 5);
    clock.monotonic_ns += 5 * second;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START);
    assert(result.restart_eligibility && !result.automatic_runtime_enabled);
    assert(recovery_consume_attempt(&record, 2, &clock) == 0);
    assert(record.attempt_count == 1 && record.last_event_id == 2);
    assert(recovery_consume_attempt(&record, 2, &clock) == 1);
    assert(record.attempt_count == 1);
    clock.monotonic_ns += second;
    clock.wall_utc_seconds -= 10000; /* Wall-clock rollback cannot shorten monotonic delay. */
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 3, &clock);
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_WAIT_BACKOFF && result.wait_seconds == 15);
    clock.monotonic_ns += 15 * second;
    clock.wall_utc_seconds += 40000; /* A wall-clock jump also does not alter the delay. */
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START);
    assert(recovery_consume_attempt(&record, 4, &clock) == 0);
    clock.monotonic_ns += second;
    add_failure(&record, RECOVERY_EXIT_REPEATED_FAILURE, 0, 5, &clock);
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_WAIT_BACKOFF && result.wait_seconds == 60);
    clock.monotonic_ns += 60 * second;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START);
    assert(recovery_consume_attempt(&record, 6, &clock) == 0);
    clock.monotonic_ns += second;
    add_failure(&record, RECOVERY_EXIT_REPEATED_FAILURE, 0, 7, &clock);
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT);
    assert(result.state == RECOVERY_STATE_RESTART_LIMIT_REACHED);
    assert(recovery_note_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock) == 1);
    checks++;
}

static void test_rolling_window_and_timebase_ambiguity(void) {
    const uint64_t second = UINT64_C(1000000000);
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(50000000000), 1800000000, "boot-a");
    recovery_result_t result;
    recovery_observations_t facts = safe_unexpected_exit();
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock);
    clock.monotonic_ns += 5 * second;
    assert(recovery_consume_attempt(&record, 2, &clock) == 0);
    clock.monotonic_ns += 700 * second;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_ELIGIBLE_FOR_ATTENDED_START);
    assert(result.attempts_remaining == RECOVERY_MAX_ATTEMPTS);

    recovery_clock_t rebooted = test_clock(UINT64_C(1000000000), 1800000100, "boot-b");
    assert(recovery_decide(&facts, &record, &rebooted, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_INCONSISTENT_STATE);
    rebooted = test_clock(UINT64_C(900000000), 1800000200, "boot-a");
    assert(recovery_decide(&facts, &record, &rebooted, &result) == 0);
    assert(result.state == RECOVERY_STATE_RECOVERY_UNVERIFIED);
    checks++;
}

static void test_signal_and_release_failure_classification(void) {
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(90000000000), 1800000000, "boot-a");
    recovery_result_t result;
    recovery_observations_t facts = safe_unexpected_exit();
    facts.exit_class = RECOVERY_EXIT_SIGNAL_TERMINATION;
    facts.exit_signal = 9; /* SIGKILL is an observed abrupt signal, never a graceful release. */
    add_failure(&record, RECOVERY_EXIT_SIGNAL_TERMINATION, 9, 1, &clock);
    facts.exit_signal = 15;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED);
    facts.exit_signal = 9;
    facts.cleanup_confirmed = 0;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    facts.exit_class = RECOVERY_EXIT_RELEASE_FAILURE;
    facts.release_failed = 1;
    assert(recovery_decide(&facts, &record, &clock, &result) == 0);
    assert(result.decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED);
    checks++;
}

static void test_healthy_and_reviewed_reset_rules(void) {
    const uint64_t second = UINT64_C(1000000000);
    recovery_record_t record = clean_record();
    recovery_clock_t clock = test_clock(UINT64_C(1000000000), 1800000000, "boot-a");
    add_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock);
    /* An explicit confirmation is required before a healthy interval can reset attempts. */
    record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    assert(recovery_note_healthy(&record, &clock) == -1);
    assert(recovery_confirm_cleanup(&record, 1, 1, 1) == 0);
    assert(recovery_note_healthy(&record, &clock) == 0);
    clock.monotonic_ns += (RECOVERY_HEALTHY_RESET_SECONDS - 1) * second;
    assert(recovery_note_healthy(&record, &clock) == 0);
    assert(record.last_failure_event_id == 1);
    clock.monotonic_ns += second;
    assert(recovery_note_healthy(&record, &clock) == 1);
    assert(record.last_failure_event_id == 0);

    record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    record.process_state = RECOVERY_PROCESS_CLEAN;
    assert(recovery_reset_reviewed(&record, 0, 1) != 0);
    assert(recovery_reset_reviewed(&record, 1, 0) != 0);
    assert(recovery_reset_reviewed(&record, 1, 1) == 0);
    assert(record.cleanup_state == RECOVERY_CLEANUP_CONFIRMED);
    assert(record.last_exit_class == RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP);
    checks++;
}

static void write_raw(const char *path, const char *contents, mode_t mode) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, mode);
    assert(fd >= 0);
    size_t length = strlen(contents), used = 0;
    while (used < length) {
        ssize_t n = write(fd, contents + used, length - used);
        assert(n > 0);
        used += (size_t)n;
    }
    assert(close(fd) == 0);
    assert(chmod(path, mode) == 0);
}

static void make_paths(char *directory, size_t dir_cap, char *record, size_t record_cap) {
    snprintf(directory, dir_cap, "/tmp/ioscaf-p014-XXXXXX");
    assert(mkdtemp(directory) != NULL);
    assert(snprintf(record, record_cap, "%s/recovery-state.json", directory) < (int)record_cap);
}

static void test_store_round_trip_and_startup_gate(void) {
    char directory[128], path[256], detail[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    recovery_record_t record;
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_MISSING);
    int blocked = 0;
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 1);
    assert(record.process_state == RECOVERY_PROCESS_RUNNING);
    assert(record.cleanup_state == RECOVERY_CLEANUP_UNVERIFIED);
    assert(recovery_store_finish_run(path, geteuid(), &record, 1,
                                     RECOVERY_EXIT_GRACEFUL_CONFIRMED, 0,
                                     detail, sizeof(detail)) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.process_state == RECOVERY_PROCESS_CLEAN);
    assert(record.cleanup_state == RECOVERY_CLEANUP_UNVERIFIED);
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 1);

    assert(recovery_reset_reviewed(&record, 1, 1) == 0);
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 0);
    assert(record.process_state == RECOVERY_PROCESS_RUNNING);
    assert(recovery_store_finish_run(path, geteuid(), &record, 1,
                                     RECOVERY_EXIT_SIGNAL_TERMINATION, 15,
                                     detail, sizeof(detail)) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.last_exit_class == RECOVERY_EXIT_SIGNAL_TERMINATION && record.last_exit_signal == 15);
    assert(record.cleanup_state == RECOVERY_CLEANUP_CONFIRMED);
    recovery_clock_t clock = test_clock(UINT64_C(9000000000), 1800000000, "boot-a");
    assert(recovery_note_failure(&record, RECOVERY_EXIT_UNEXPECTED_EXIT, 0, 1, &clock) == 0);
    assert(recovery_confirm_cleanup(&record, 1, 1, 1) == 0);
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    assert(recovery_store_consume_attempt(path, geteuid(), &record, 2, &clock,
                                          detail, sizeof(detail)) == 0);
    assert(record.attempt_count == 1);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.attempt_count == 1 && record.attempts[0].event_id == 2);
    assert(recovery_store_consume_attempt(path, geteuid(), &record, 2, &clock,
                                          detail, sizeof(detail)) == 1);
    assert(record.attempt_count == 1);
    recovery_test_fail_save_before_rename(1);
    assert(recovery_store_consume_attempt(path, geteuid(), &record, 3, &clock,
                                          detail, sizeof(detail)) != 0);
    recovery_test_fail_save_before_rename(0);
    assert(record.attempt_count == 1);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.attempt_count == 1 && record.attempts[0].event_id == 2);
    char temp[320];
    assert(snprintf(temp, sizeof(temp), "%s/.recovery-state.json.tmp.%ld",
                    directory, (long)getpid()) < (int)sizeof(temp));
    assert(unlink(temp) == 0); /* The injected pre-rename interruption mimics an abandoned temp. */
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_store_parser_corruption_and_versions(void) {
    char directory[128], path[256], detail[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    const char *malformed = "{\"schema_version\":1";
    write_raw(path, malformed, 0600);
    recovery_record_t record;
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_CORRUPT);

    const char *unknown =
        "{\"schema_version\":2,\"policy_version\":1,\"generation\":0,\"process_state\":\"CLEAN\","
        "\"cleanup_state\":\"CONFIRMED\",\"last_exit_class\":\"GRACEFUL_CONFIRMED\","
        "\"last_exit_signal\":0,\"attempts\":[],\"last_event_id\":0,"
        "\"last_failure_event_id\":0,\"last_failure_monotonic_ns\":0,"
        "\"last_failure_wall_utc_seconds\":0,\"last_failure_clock_id\":\"\","
        "\"healthy_since_monotonic_ns\":0,\"healthy_clock_id\":\"\"}";
    write_raw(path, unknown, 0600);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSUPPORTED);

    const char *duplicate =
        "{\"schema_version\":1,\"schema_version\":1,\"policy_version\":1,\"generation\":0,"
        "\"process_state\":\"CLEAN\",\"cleanup_state\":\"CONFIRMED\","
        "\"last_exit_class\":\"GRACEFUL_CONFIRMED\",\"last_exit_signal\":0,\"attempts\":[],"
        "\"last_event_id\":0,\"last_failure_event_id\":0,\"last_failure_monotonic_ns\":0,"
        "\"last_failure_wall_utc_seconds\":0,\"last_failure_clock_id\":\"\","
        "\"healthy_since_monotonic_ns\":0,\"healthy_clock_id\":\"\"}";
    write_raw(path, duplicate, 0600);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_CORRUPT);

    char oversized[RECOVERY_MAX_RECORD_BYTES + 2];
    memset(oversized, 'x', sizeof(oversized) - 1);
    oversized[sizeof(oversized) - 1] = '\0';
    write_raw(path, oversized, 0600);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_CORRUPT);
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_release_failure_remains_visible_after_shutdown(void) {
    char directory[128], path[256], detail[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    recovery_record_t record = clean_record();
    record.process_state = RECOVERY_PROCESS_RUNNING;
    record.last_exit_class = RECOVERY_EXIT_RELEASE_FAILURE;
    record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    assert(recovery_store_finish_run(path, geteuid(), &record, 1,
                                     RECOVERY_EXIT_EXPLICIT_STOP, 0,
                                     detail, sizeof(detail)) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE);
    assert(record.cleanup_state == RECOVERY_CLEANUP_UNVERIFIED);
    /* Later cleanup evidence does not erase the failure without reviewed reset. */
    record.cleanup_state = RECOVERY_CLEANUP_CONFIRMED;
    record.process_state = RECOVERY_PROCESS_CLEAN;
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    int blocked = 0;
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked,
                                    detail, sizeof(detail)) == 0);
    assert(blocked == 1);
    assert(recovery_reset_reviewed(&record, 1, 1) == 0);
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked,
                                    detail, sizeof(detail)) == 0);
    assert(blocked == 0);
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_service_lock_is_held_and_exclusive(void) {
    char directory[] = "/tmp/ioscaf-p014-lock-XXXXXX";
    assert(mkdtemp(directory) != NULL);
    char path[256];
    assert(snprintf(path, sizeof(path), "%s/daemon.sock.lock", directory) < (int)sizeof(path));
    int first = service_test_recovery_lock_acquire(path);
    assert(first >= 0);
    struct stat st;
    assert(lstat(path, &st) == 0 && S_ISREG(st.st_mode) &&
           (st.st_mode & 07777) == 0600 && st.st_nlink == 1);
    assert(service_test_recovery_lock_acquire(path) < 0);
    assert(close(first) == 0);
    int second = service_test_recovery_lock_acquire(path);
    assert(second >= 0);
    assert(close(second) == 0);
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_store_symlink_hardlink_mode_and_owner_safety(void) {
    char directory[128], path[256], detail[256], other[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    recovery_record_t record = clean_record();
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    uid_t wrong_owner = geteuid() == 0 ? (uid_t)1 : (uid_t)(geteuid() + 1);
    assert(recovery_store_load(path, wrong_owner, &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSAFE);

    assert(snprintf(other, sizeof(other), "%s/other", directory) < (int)sizeof(other));
    assert(link(path, other) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSAFE);
    assert(unlink(other) == 0);

    assert(chmod(path, 0644) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSAFE);
    assert(chmod(path, 0600) == 0);

    assert(unlink(path) == 0);
    assert(symlink("/etc/passwd", path) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSAFE);
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) != 0);
    assert(unlink(path) == 0);

    if (geteuid() == 0) {
        assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
        assert(chown(path, 1, (gid_t)-1) == 0);
        assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_UNSAFE);
    }
    unlink(path);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_atomic_interruption_preserves_old_record(void) {
    char directory[128], path[256], detail[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    recovery_record_t original = clean_record();
    assert(recovery_store_save_atomic(path, geteuid(), &original, detail, sizeof(detail)) == 0);
    recovery_record_t replacement = original;
    replacement.generation++;
    recovery_test_fail_save_before_rename(1);
    assert(recovery_store_save_atomic(path, geteuid(), &replacement, detail, sizeof(detail)) != 0);
    recovery_test_fail_save_before_rename(0);
    recovery_record_t loaded;
    assert(recovery_store_load(path, geteuid(), &loaded, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(loaded.generation == original.generation);
    char temp[320];
    snprintf(temp, sizeof(temp), "%s/.recovery-state.json.tmp.%ld", directory, (long)getpid());
    assert(unlink(temp) == 0);
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

static void test_attended_service_reset_requires_all_reviews(void) {
    char directory[128], path[256], detail[256];
    make_paths(directory, sizeof(directory), path, sizeof(path));
    recovery_record_t record;
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_MISSING);
    assert(service_test_recovery_reset(path, 0, 1, 1) != 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_MISSING);
    assert(service_test_recovery_reset(path, 1, 0, 1) != 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_MISSING);
    assert(service_test_recovery_reset(path, 1, 1, 0) != 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_MISSING);
    assert(service_test_recovery_reset(path, 1, 1, 1) == 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_OK);
    assert(record.last_exit_class == RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP);
    assert(record.cleanup_state == RECOVERY_CLEANUP_CONFIRMED);
    assert(record.process_state == RECOVERY_PROCESS_CLEAN);

    /* The reviewed first-install record authorizes startup only after all gates pass. */
    int blocked = 1;
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 0);
    assert(record.process_state == RECOVERY_PROCESS_RUNNING);
    assert(recovery_store_finish_run(path, geteuid(), &record, 1,
                                     RECOVERY_EXIT_GRACEFUL_CONFIRMED, 0,
                                     detail, sizeof(detail)) == 0);
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 0);

    /* A crash after a reviewed startup restores the fail-closed first-run gate. */
    assert(recovery_store_save_atomic(path, geteuid(), &record, detail, sizeof(detail)) == 0);
    assert(recovery_store_begin_run(path, geteuid(), &record, &blocked, detail, sizeof(detail)) == 0);
    assert(blocked == 1);
    assert(record.cleanup_state == RECOVERY_CLEANUP_UNVERIFIED);
    assert(record.last_exit_class == RECOVERY_EXIT_UNKNOWN_UNOBSERVED);

    write_raw(path, "{broken\n", 0600);
    assert(service_test_recovery_reset(path, 1, 1, 1) != 0);
    assert(recovery_store_load(path, geteuid(), &record, detail, sizeof(detail)) == RECOVERY_STORE_CORRUPT);
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
    checks++;
}

int main(void) {
    test_exit_classification_contract();
    test_stop_expiry_and_unknown_are_distinct();
    test_injected_supervisor_observer_is_policy_only();
    test_cleanup_supervisor_socket_and_lock_blocks();
    test_backoff_attempt_accounting_and_duplicate_events();
    test_rolling_window_and_timebase_ambiguity();
    test_signal_and_release_failure_classification();
    test_healthy_and_reviewed_reset_rules();
    test_store_round_trip_and_startup_gate();
    test_store_parser_corruption_and_versions();
    test_release_failure_remains_visible_after_shutdown();
    test_service_lock_is_held_and_exclusive();
    test_store_symlink_hardlink_mode_and_owner_safety();
    test_atomic_interruption_preserves_old_record();
    test_attended_service_reset_requires_all_reviews();
    printf("P014 recovery policy and persistence checks: %u passed\n", checks);
    return 0;
}
