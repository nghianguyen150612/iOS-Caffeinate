#define _POSIX_C_SOURCE 200809L
#include "../src/recovery.h"
#include "../src/server_mode.h"
#include "../src/server_policy.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static unsigned checks;
static char test_dir[256];
static char config_path[320];

static void check(int condition, const char *name) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", name);
        exit(1);
    }
    checks++;
}

static int write_file(const char *path, const char *data, size_t length, mode_t mode) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, mode);
    if (fd < 0) return -1;
    if (fchmod(fd, mode) != 0) { close(fd); return -1; }
    size_t offset = 0;
    while (offset < length) {
        ssize_t written = write(fd, data + offset, length - offset);
        if (written <= 0) { close(fd); return -1; }
        offset += (size_t)written;
    }
    return close(fd);
}

static server_config_t load_text(const char *text, server_config_status_t expected_status,
                                 unsigned expected_version, server_policy_t expected_policy,
                                 const char *label) {
    server_config_t config;
    unlink(config_path);
    check(write_file(config_path, text, strlen(text), 0600) == 0, "write bounded test config");
    check(server_mode_config_load(config_path, &config) == 0, "config loader returns diagnostics");
    check(config.status == expected_status, label);
    if (expected_status == SERVER_CONFIG_VALID) {
        check(config.schema_version == expected_version, "schema version retained");
        check(config.policy == expected_policy, "policy meaning retained");
    }
    return config;
}

static server_config_t bounded_config(void) {
    server_config_t config;
    memset(&config, 0, sizeof(config));
    config.status = SERVER_CONFIG_VALID;
    config.schema_version = 2;
    config.policy = SERVER_POLICY_BOUNDED_SESSION;
    config.max_duration_seconds = 300;
    config.require_operator_confirmation = 1;
    return config;
}

static void set_gate(server_policy_inputs_t *inputs, server_policy_gate_t gate,
                     server_evidence_state_t state, server_evidence_source_t source,
                     server_evidence_freshness_t freshness, int reviewed) {
    inputs->gates[gate].state = state;
    inputs->gates[gate].source = source;
    inputs->gates[gate].freshness = freshness;
    inputs->gates[gate].confidence = reviewed
        ? SERVER_EVIDENCE_CONFIDENCE_HIGH : SERVER_EVIDENCE_CONFIDENCE_UNKNOWN;
    inputs->gates[gate].reviewed = reviewed;
    inputs->gates[gate].observed_at_utc = 1800000000;
}

static server_policy_inputs_t eligible_inputs(void) {
    server_policy_inputs_t inputs;
    server_policy_inputs_init(&inputs);
    inputs.operation = SERVER_OPERATION_MANUAL_BOUNDED_SESSION;
    inputs.requested_duration_seconds = 300;
    inputs.runtime_state = SERVER_RUNTIME_IDLE;
    inputs.assertion_state = SERVER_ASSERTION_NONE;
    inputs.runtime_source = SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED;
    inputs.runtime_freshness = SERVER_EVIDENCE_CURRENT;
    inputs.runtime_observed_at_utc = 1800000000;
    inputs.recovery_store_status = RECOVERY_STORE_OK;
    inputs.recovery_record_available = 1;
    recovery_record_init(&inputs.recovery_record);
    inputs.recovery_record.generation = 1;
    inputs.recovery_record.process_state = RECOVERY_PROCESS_CLEAN;
    inputs.recovery_record.cleanup_state = RECOVERY_CLEANUP_CONFIRMED;
    inputs.recovery_record.last_exit_class = RECOVERY_EXIT_GRACEFUL_CONFIRMED;
    inputs.battery_percentage = 55;
    inputs.charging_status = SERVER_CHARGING_NO;
    inputs.thermal_state = SERVER_THERMAL_NOMINAL;
    for (int gate = SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE;
         gate < SERVER_POLICY_GATE_COUNT; ++gate) {
        set_gate(&inputs, (server_policy_gate_t)gate, SERVER_EVIDENCE_PASS,
                 SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED, SERVER_EVIDENCE_CURRENT, 1);
    }
    return inputs;
}

static void test_configuration_schema(void) {
    load_text("{\"version\":1,\"policy\":\"disabled\"}", SERVER_CONFIG_VALID,
              1, SERVER_POLICY_DISABLED, "v1 disabled remains valid");
    server_config_t v1 = load_text("{\"version\":1,\"policy\":\"observe_only\"}",
                                   SERVER_CONFIG_VALID, 1, SERVER_POLICY_OBSERVE_ONLY,
                                   "v1 observe-only remains valid");
    check(v1.max_duration_seconds == 300 && v1.require_operator_confirmation &&
          !v1.allow_automatic_start && !v1.allow_restart_resume,
          "v1 defaults are conservative without changing v1 policy");

    load_text("{\"version\":2,\"policy\":\"disabled\",\"session\":{\"max_duration_seconds\":300,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_VALID, 2, SERVER_POLICY_DISABLED, "v2 disabled valid");
    load_text("{\"version\":2,\"policy\":\"observe_only\",\"session\":{\"max_duration_seconds\":300,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_VALID, 2, SERVER_POLICY_OBSERVE_ONLY, "v2 observe-only valid");
    server_config_t v2 = load_text("{\"policy\":\"bounded_session\",\"version\":2,\"session\":{\"max_duration_seconds\":300,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
                                   SERVER_CONFIG_VALID, 2, SERVER_POLICY_BOUNDED_SESSION,
                                   "v2 bounded-session valid with reordered top-level fields");
    check(v2.max_duration_seconds == 300 && v2.require_operator_confirmation &&
          !v2.allow_automatic_start && !v2.allow_restart_resume,
          "v2 session limits retained");

    load_text("{\"version\":3,\"policy\":\"disabled\"}",
              SERVER_CONFIG_UNSUPPORTED, 0, SERVER_POLICY_DISABLED,
              "future schema fails closed as unsupported");
    load_text("{\"version\":1,\"version\":1,\"policy\":\"disabled\"}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "duplicate field rejected");
    load_text("{\"version\":1,\"policy\":\"disabled\",\"extra\":true}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "unknown field rejected");
    load_text("{\"version\":1,\"policy\":\"bounded_session\"}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED,
              "v1 never migrates to bounded-session");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":301,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "duration ceiling enforced");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":0,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "zero configured duration rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":18446744073709551616,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "integer overflow rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":-1,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "negative duration rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":1.5,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "fractional duration rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\"}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "missing session object rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":1,\"require_operator_confirmation\":1,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "non-boolean value rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":false,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "operator confirmation cannot be disabled");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":true,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "automatic start cannot be enabled");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":true}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "restart resume cannot be enabled");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "duplicate nested key rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false,\"secret\":\"redact-me\"}}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "unknown secret field rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}} trailing",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "trailing data rejected");
    load_text("{\"version\":2,\"policy\":\"bounded_session\",\"session\":{\"max_duration_seconds\":3,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}",
              SERVER_CONFIG_INVALID, 0, SERVER_POLICY_DISABLED, "truncated JSON rejected");
}

static void test_filesystem_safety(void) {
    server_config_t config;
    char link_path[320], hardlink_path[320];
    snprintf(link_path, sizeof(link_path), "%s/link.json", test_dir);
    snprintf(hardlink_path, sizeof(hardlink_path), "%s/hardlink.json", test_dir);

    unlink(config_path);
    check(symlink("missing-target", config_path) == 0, "create config symlink fixture");
    check(server_mode_config_load(config_path, &config) == 0 && config.status == SERVER_CONFIG_UNSAFE,
          "symlink configuration rejected");
    unlink(config_path);

    check(write_file(config_path, "{\"version\":1,\"policy\":\"disabled\"}",
                     strlen("{\"version\":1,\"policy\":\"disabled\"}"), 0600) == 0,
          "write hardlink fixture");
    unlink(hardlink_path);
    check(link(config_path, hardlink_path) == 0, "create hardlink fixture");
    check(server_mode_config_load(config_path, &config) == 0 && config.status == SERVER_CONFIG_UNSAFE,
          "hardlink configuration rejected");
    unlink(hardlink_path);

    check(chmod(config_path, 0644) == 0, "change config mode fixture");
    check(server_mode_config_load(config_path, &config) == 0 && config.status == SERVER_CONFIG_UNSAFE,
          "non-0600 mode rejected");
    unlink(config_path);

    check(server_mode_config_load("/etc/hosts", &config) == 0 &&
          config.status == SERVER_CONFIG_UNSAFE,
          "wrong-owner or non-private system config rejected");

    char oversized[SERVER_MODE_CONFIG_MAX + 2];
    memset(oversized, ' ', sizeof(oversized));
    check(write_file(config_path, oversized, sizeof(oversized), 0600) == 0,
          "write oversized fixture");
    check(server_mode_config_load(config_path, &config) == 0 &&
          config.status == SERVER_CONFIG_UNSAFE,
          "oversized file rejected before parse");

#ifdef IOSCAFFEINATE_SERVER_MODE_TESTING
    static const char valid[] = "{\"version\":1,\"policy\":\"disabled\"}";
    check(write_file(config_path, valid, sizeof(valid) - 1, 0600) == 0,
          "write concurrent-change fixture");
    server_mode_test_append_after_read(config_path);
    check(server_mode_config_load(config_path, &config) == 0 &&
          config.status == SERVER_CONFIG_INVALID,
          "configuration size race rejected after stable read check");
#endif
}

static void test_policy_decisions(void) {
    server_config_t config = bounded_config();
    server_policy_inputs_t inputs = eligible_inputs();
    server_policy_result_t first, second;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION &&
          first.eligible && !first.execution_authorized &&
          first.runtime_activation == SERVER_POLICY_ACTIVATION_INACTIVE,
          "reviewed manual bounded-session inputs become eligible without execution authorization");
    check(first.supervisor_state == SERVER_SUPERVISOR_UNVERIFIED,
          "P014 supervisor status remains separate from manual session eligibility");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].state = SERVER_EVIDENCE_PENDING;
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].freshness =
        SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "missing Tailscale evidence cannot be replaced by LAN reachability");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].state = SERVER_EVIDENCE_PENDING;
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].freshness =
        SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "missing LAN evidence cannot be replaced by Tailscale reachability");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].state = SERVER_EVIDENCE_PENDING;
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
    inputs.gates[SERVER_POLICY_GATE_LAN_REACHABILITY].freshness =
        SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].state = SERVER_EVIDENCE_PENDING;
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
    inputs.gates[SERVER_POLICY_GATE_TAILSCALE_REACHABILITY].freshness =
        SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "both missing network routes defer bounded-session eligibility");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE].source = SERVER_EVIDENCE_SOURCE_CI;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "CI evidence cannot satisfy P011 hardware acceptance");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P012_IDLE_POWER_REVIEW].freshness = SERVER_EVIDENCE_STALE;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "stale power research evidence defers eligibility");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_OPERATOR_ATTENDANCE].source = SERVER_EVIDENCE_SOURCE_SIMULATED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "simulated attendance cannot satisfy physical attendance gate");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE].confidence =
        SERVER_EVIDENCE_CONFIDENCE_MEDIUM;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "medium-confidence gate evidence defers eligibility");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE].source =
        SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED;
    inputs.gates[SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE].reviewed = 0;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "unreviewed operator report cannot satisfy a hardware gate");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE].source =
        SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION,
          "separately reviewed P009 operator evidence retains its source classification");

    inputs = eligible_inputs();
    inputs.gates[SERVER_POLICY_GATE_P013_LIFECYCLE_COMPATIBILITY].state = SERVER_EVIDENCE_UNSAFE;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RESOURCE_SAFETY,
          "unsafe P013 lifecycle evidence blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_store_status = RECOVERY_STORE_MISSING;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "missing P014 journal blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_store_status = RECOVERY_STORE_CORRUPT;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "corrupt P014 journal blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_store_status = RECOVERY_STORE_UNSAFE;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "unsafe P014 journal blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "P014 cleanup uncertainty blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_record.last_exit_class = RECOVERY_EXIT_RELEASE_FAILURE;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "P014 release failure blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_record.last_exit_class = RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "unknown prior assertion ownership blocks policy");

    inputs = eligible_inputs();
    inputs.recovery_record.last_exit_class = RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP;
    inputs.gates[SERVER_POLICY_GATE_PHYSICAL_RECOVERY].state = SERVER_EVIDENCE_PENDING;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "operator-reviewed P014 reset does not satisfy physical recovery evidence");

    inputs = eligible_inputs();
    inputs.recovery_record.process_state = RECOVERY_PROCESS_RUNNING;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "running P014 record blocks policy");

    inputs = eligible_inputs();
    inputs.runtime_state = SERVER_RUNTIME_BLOCKED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_UNSAFE_RUNTIME,
          "BLOCKED daemon state blocks policy");

    inputs = eligible_inputs();
    inputs.assertion_state = SERVER_ASSERTION_RELEASE_FAILED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "runtime RELEASE_FAILED blocks policy");

    inputs = eligible_inputs();
    inputs.runtime_state = SERVER_RUNTIME_ACTIVE;
    inputs.assertion_state = SERVER_ASSERTION_OWNED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_ASSERTION_CONFLICT &&
          first.runtime_activation == SERVER_POLICY_ACTIVATION_ACTIVE,
          "active assertion conflicts and is reported as observed active");

    inputs = eligible_inputs();
    inputs.assertion_state = SERVER_ASSERTION_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY,
          "unknown assertion ownership blocks policy");

    inputs = eligible_inputs();
    inputs.battery_percentage = -1;
    inputs.charging_status = SERVER_CHARGING_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "unknown battery and charging observations defer eligibility");

    inputs = eligible_inputs();
    inputs.battery_percentage = 0;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RESOURCE_SAFETY,
          "observed empty battery blocks policy");

    inputs = eligible_inputs();
    inputs.thermal_state = SERVER_THERMAL_UNKNOWN;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
          "unknown thermal status defers eligibility");

    inputs = eligible_inputs();
    inputs.thermal_state = SERVER_THERMAL_CRITICAL;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RESOURCE_SAFETY,
          "critical thermal observation blocks eligibility");

    inputs = eligible_inputs();
    inputs.runtime_source = SERVER_EVIDENCE_SOURCE_MOCK;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE &&
          first.runtime_activation == SERVER_POLICY_ACTIVATION_UNKNOWN,
          "mock runtime status cannot establish physical runtime readiness or activation");

    inputs = eligible_inputs();
    inputs.operation = SERVER_OPERATION_UNATTENDED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION &&
          !first.execution_authorized,
          "unattended operation is explicitly denied");

    inputs = eligible_inputs();
    inputs.operation = SERVER_OPERATION_SCHEDULED_UNATTENDED;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION &&
          first.primary_reason == SERVER_REASON_SCHEDULE_EXECUTOR_NOT_AUTHORIZED &&
          !first.eligible && !first.execution_authorized,
          "manual bounded-session readiness never authorizes scheduled execution");

    inputs = eligible_inputs();
    inputs.operation = SERVER_OPERATION_AUTOMATIC_RECOVERY;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_UNVERIFIED_SUPERVISOR,
          "automatic recovery remains blocked with unverified supervisor");

    inputs = eligible_inputs();
    inputs.operation = SERVER_OPERATION_AUTOMATIC_RECOVERY;
    inputs.recovery_restart_decision_available = 1;
    inputs.recovery_restart_decision = RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_RECOVERY &&
          first.primary_reason == SERVER_REASON_RECOVERY_RESTART_LIMIT,
          "P014 exhausted restart budget blocks automatic recovery eligibility");

    inputs = eligible_inputs();
    inputs.requested_duration_seconds = 0;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_DURATION,
          "zero requested duration rejected");

    inputs = eligible_inputs();
    inputs.requested_duration_seconds = 301;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_DURATION,
          "duration beyond configured and policy ceiling rejected");

    inputs = eligible_inputs();
    inputs.requested_duration_seconds = UINT64_MAX;
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_BLOCK_DURATION,
          "integer-overflow-sized duration rejected without arithmetic wraparound");

    inputs = eligible_inputs();
    check(server_policy_evaluate(&config, &inputs, &first) == 0 &&
          server_policy_evaluate(&config, &inputs, &second) == 0 &&
          memcmp(&first, &second, sizeof(first)) == 0,
          "reason ordering and result are deterministic");

    server_config_t missing = config;
    missing.status = SERVER_CONFIG_MISSING;
    server_policy_inputs_init(&inputs);
    inputs.operation = SERVER_OPERATION_MANUAL_BOUNDED_SESSION;
    check(server_policy_evaluate(&missing, &inputs, &first) == 0 &&
          first.decision == SERVER_DECISION_DISABLED && !first.eligible,
          "missing config resolves conservatively to disabled");
}

int main(void) {
    char template[] = "/tmp/ioscaffeinate-p015-XXXXXX";
    char *directory = mkdtemp(template);
    check(directory != NULL, "create private policy test directory");
    snprintf(test_dir, sizeof(test_dir), "%s", directory);
    snprintf(config_path, sizeof(config_path), "%s/server-mode.json", test_dir);

    test_configuration_schema();
    test_filesystem_safety();
    test_policy_decisions();

    unlink(config_path);
    rmdir(test_dir);
    printf("P015 policy/schema/filesystem checks: %u passed\n", checks);
    return 0;
}
