#include "server_policy.h"

#include <string.h>

static const server_policy_gate_t required_gates[] = {
    SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE,
    SERVER_POLICY_GATE_INSTALLED_CLI,
    SERVER_POLICY_GATE_INSTALLED_DAEMON,
    SERVER_POLICY_GATE_P012_IDLE_POWER_REVIEW,
    SERVER_POLICY_GATE_ASSERTION_ACQUIRE,
    SERVER_POLICY_GATE_ASSERTION_RELEASE,
    SERVER_POLICY_GATE_P013_LIFECYCLE_COMPATIBILITY,
    SERVER_POLICY_GATE_PHYSICAL_RECOVERY,
    SERVER_POLICY_GATE_BATTERY_SAFETY,
    SERVER_POLICY_GATE_THERMAL_SAFETY,
    SERVER_POLICY_GATE_LAN_REACHABILITY,
    SERVER_POLICY_GATE_TAILSCALE_REACHABILITY,
    SERVER_POLICY_GATE_OPERATOR_ATTENDANCE
};

static void add_blocker(server_policy_result_t *result, server_policy_reason_t reason,
                        server_policy_gate_t gate, server_evidence_state_t state,
                        server_evidence_source_t source,
                        server_evidence_freshness_t freshness) {
    if (result->blocker_count >= SERVER_POLICY_MAX_BLOCKERS) return;
    server_policy_blocker_t *blocker = &result->blockers[result->blocker_count++];
    blocker->reason = reason;
    blocker->gate = gate;
    blocker->state = state;
    blocker->source = source;
    blocker->freshness = freshness;
    if (result->primary_reason == SERVER_REASON_NONE) result->primary_reason = reason;
}

static int physical_source(server_evidence_source_t source) {
    return source == SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED ||
           source == SERVER_EVIDENCE_SOURCE_EXTERNAL_OBSERVER;
}

static int acceptable_evidence_source(server_evidence_source_t source, int reviewed) {
    return physical_source(source) ||
           (source == SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED && reviewed);
}

void server_policy_inputs_init(server_policy_inputs_t *inputs) {
    if (!inputs) return;
    memset(inputs, 0, sizeof(*inputs));
    inputs->operation = SERVER_OPERATION_OBSERVE;
    inputs->runtime_state = SERVER_RUNTIME_UNKNOWN;
    inputs->assertion_state = SERVER_ASSERTION_UNKNOWN;
    inputs->runtime_source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
    inputs->runtime_freshness = SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    inputs->supervisor_state = SERVER_SUPERVISOR_UNVERIFIED;
    inputs->recovery_store_status = RECOVERY_STORE_MISSING;
    inputs->recovery_record.process_state = RECOVERY_PROCESS_UNKNOWN;
    inputs->recovery_record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
    inputs->recovery_record.last_exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
    inputs->battery_percentage = -1;
    inputs->charging_status = SERVER_CHARGING_UNKNOWN;
    inputs->thermal_state = SERVER_THERMAL_UNKNOWN;
    for (size_t i = 0; i < SERVER_POLICY_GATE_COUNT; ++i) {
        inputs->gates[i].state = SERVER_EVIDENCE_PENDING;
        inputs->gates[i].source = SERVER_EVIDENCE_SOURCE_UNKNOWN;
        inputs->gates[i].freshness = SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    }
}

static void evaluate_gate(const server_policy_inputs_t *inputs,
                          server_policy_gate_t gate,
                          server_policy_result_t *result,
                          int *resource_blocker,
                          int *deferred) {
    const server_policy_evidence_t *evidence = &inputs->gates[gate];
    server_policy_reason_t reason = SERVER_REASON_NONE;
    if (evidence->state == SERVER_EVIDENCE_DENIED) {
        reason = SERVER_REASON_EVIDENCE_DENIED;
        *resource_blocker = 1;
    } else if (evidence->state == SERVER_EVIDENCE_UNSAFE) {
        reason = SERVER_REASON_EVIDENCE_UNSAFE;
        *resource_blocker = 1;
    } else if (evidence->freshness == SERVER_EVIDENCE_STALE) {
        reason = SERVER_REASON_EVIDENCE_STALE;
        *deferred = 1;
    } else if (evidence->state != SERVER_EVIDENCE_PASS) {
        reason = SERVER_REASON_EVIDENCE_MISSING;
        *deferred = 1;
    } else if (!acceptable_evidence_source(evidence->source, evidence->reviewed)) {
        reason = SERVER_REASON_EVIDENCE_NONPHYSICAL;
        *deferred = 1;
    } else if (!evidence->reviewed) {
        reason = SERVER_REASON_EVIDENCE_UNREVIEWED;
        *deferred = 1;
    } else if (evidence->confidence != SERVER_EVIDENCE_CONFIDENCE_HIGH) {
        reason = SERVER_REASON_EVIDENCE_LOW_CONFIDENCE;
        *deferred = 1;
    } else if (evidence->freshness != SERVER_EVIDENCE_CURRENT ||
               evidence->observed_at_utc <= 0) {
        reason = SERVER_REASON_EVIDENCE_STALE;
        *deferred = 1;
    }
    if (reason != SERVER_REASON_NONE) {
        add_blocker(result, reason, gate, evidence->state, evidence->source,
                    evidence->freshness);
    }
}

static int recovery_blockers(const server_policy_inputs_t *inputs,
                             server_policy_result_t *result) {
    int blocked = 0;
    server_policy_reason_t reason = SERVER_REASON_NONE;
    switch (inputs->recovery_store_status) {
        case RECOVERY_STORE_OK: break;
        case RECOVERY_STORE_MISSING: reason = SERVER_REASON_RECOVERY_MISSING; break;
        case RECOVERY_STORE_UNSAFE: reason = SERVER_REASON_RECOVERY_UNSAFE; break;
        case RECOVERY_STORE_CORRUPT: reason = SERVER_REASON_RECOVERY_CORRUPT; break;
        case RECOVERY_STORE_UNSUPPORTED: reason = SERVER_REASON_RECOVERY_UNSUPPORTED; break;
        case RECOVERY_STORE_IO_ERROR: reason = SERVER_REASON_RECOVERY_IO_ERROR; break;
    }
    if (reason != SERVER_REASON_NONE) {
        add_blocker(result, reason, SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNSAFE,
                    SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        return 1;
    }
    if (!inputs->recovery_record_available) {
        add_blocker(result, SERVER_REASON_RECOVERY_RECORD_UNAVAILABLE,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNKNOWN,
                    SERVER_EVIDENCE_SOURCE_UNKNOWN, SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        return 1;
    }
    const recovery_record_t *record = &inputs->recovery_record;
    if (!recovery_record_validate(record)) {
        add_blocker(result, SERVER_REASON_RECOVERY_CORRUPT, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_UNSAFE, SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        return 1;
    }
    if (record->process_state != RECOVERY_PROCESS_CLEAN) {
        add_blocker(result, SERVER_REASON_RECOVERY_PROCESS_NOT_CLEAN,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNSAFE,
                    SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        blocked = 1;
    }
    if (record->cleanup_state != RECOVERY_CLEANUP_CONFIRMED) {
        add_blocker(result, SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED,
                    SERVER_POLICY_GATE_PHYSICAL_RECOVERY, SERVER_EVIDENCE_UNKNOWN,
                    SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        blocked = 1;
    }
    if (record->last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE) {
        add_blocker(result, SERVER_REASON_RECOVERY_RELEASE_FAILED,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                    SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        blocked = 1;
    } else if (record->last_exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN ||
               record->last_exit_class == RECOVERY_EXIT_UNKNOWN_UNOBSERVED) {
        add_blocker(result, SERVER_REASON_RECOVERY_OWNERSHIP_UNKNOWN,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNKNOWN,
                    SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                    SERVER_EVIDENCE_CURRENT);
        blocked = 1;
    }
    if (inputs->recovery_restart_decision_available &&
        inputs->operation == SERVER_OPERATION_AUTOMATIC_RECOVERY) {
        if (inputs->recovery_restart_decision == RECOVERY_DECISION_BLOCK_CLEANUP_UNVERIFIED) {
            add_blocker(result, SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED,
                        SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNSAFE,
                        SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                        SERVER_EVIDENCE_CURRENT);
            blocked = 1;
        } else if (inputs->recovery_restart_decision == RECOVERY_DECISION_BLOCK_ATTEMPT_LIMIT) {
            add_blocker(result, SERVER_REASON_RECOVERY_RESTART_LIMIT,
                        SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                        SERVER_EVIDENCE_SOURCE_P014_JOURNAL,
                        SERVER_EVIDENCE_CURRENT);
            blocked = 1;
        } else if (inputs->recovery_restart_decision == RECOVERY_DECISION_BLOCK_SUPERVISOR_UNVERIFIED) {
            add_blocker(result, SERVER_REASON_SUPERVISOR_UNVERIFIED,
                        SERVER_POLICY_GATE_P013_LIFECYCLE_COMPATIBILITY,
                        SERVER_EVIDENCE_UNKNOWN, SERVER_EVIDENCE_SOURCE_UNKNOWN,
                        SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
            blocked = 1;
        }
    }
    return blocked;
}

int server_policy_evaluate(const server_config_t *config,
                           const server_policy_inputs_t *inputs,
                           server_policy_result_t *result) {
    if (!config || !inputs || !result) return -1;
    memset(result, 0, sizeof(*result));
    result->policy_version = SERVER_POLICY_ENGINE_VERSION;
    result->config_schema_version = config->schema_version;
    result->configured_policy = config->policy;
    result->operation = inputs->operation;
    result->recovery_status = inputs->recovery_store_status;
    result->recovery_process = inputs->recovery_record.process_state;
    result->recovery_cleanup = inputs->recovery_record.cleanup_state;
    result->recovery_last_exit = inputs->recovery_record.last_exit_class;
    result->automatic_recovery_decision = inputs->recovery_restart_decision;
    result->automatic_recovery_decision_available = inputs->recovery_restart_decision_available;
    result->supervisor_state = inputs->supervisor_state;
    if (physical_source(inputs->runtime_source) &&
        inputs->runtime_freshness == SERVER_EVIDENCE_CURRENT &&
        inputs->runtime_observed_at_utc > 0) {
        result->runtime_activation =
            inputs->runtime_state == SERVER_RUNTIME_ACTIVE ||
            inputs->assertion_state == SERVER_ASSERTION_OWNED
                ? SERVER_POLICY_ACTIVATION_ACTIVE
                : inputs->runtime_state == SERVER_RUNTIME_IDLE &&
                  inputs->assertion_state == SERVER_ASSERTION_NONE
                      ? SERVER_POLICY_ACTIVATION_INACTIVE
                      : SERVER_POLICY_ACTIVATION_UNKNOWN;
    } else {
        result->runtime_activation = SERVER_POLICY_ACTIVATION_UNKNOWN;
    }
    if (config->status == SERVER_CONFIG_VALID &&
        config->max_duration_seconds > 0 &&
        config->max_duration_seconds <= SERVER_MODE_MAX_SESSION_SECONDS)
        result->maximum_duration_seconds = config->max_duration_seconds;

    if (config->status == SERVER_CONFIG_MISSING) {
        result->decision = SERVER_DECISION_DISABLED;
        add_blocker(result, SERVER_REASON_CONFIG_MISSING_DISABLED,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_PENDING,
                    SERVER_EVIDENCE_SOURCE_UNKNOWN, SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        return 0;
    }
    if (config->status != SERVER_CONFIG_VALID) {
        server_policy_reason_t reason = config->status == SERVER_CONFIG_UNSAFE
            ? SERVER_REASON_CONFIG_UNSAFE
            : config->status == SERVER_CONFIG_UNSUPPORTED
                ? SERVER_REASON_CONFIG_UNSUPPORTED : SERVER_REASON_CONFIG_INVALID;
        add_blocker(result, reason, SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNSAFE,
                    SERVER_EVIDENCE_SOURCE_UNKNOWN, SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        result->decision = SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }
    if ((config->schema_version != 1 && config->schema_version != SERVER_MODE_CONFIG_VERSION) ||
        (config->schema_version == 1 && config->policy == SERVER_POLICY_BOUNDED_SESSION)) {
        add_blocker(result, SERVER_REASON_CONFIG_INVALID, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_UNSAFE, SERVER_EVIDENCE_SOURCE_UNKNOWN,
                    SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        result->decision = SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }
    if (config->policy == SERVER_POLICY_DISABLED) {
        result->decision = SERVER_DECISION_DISABLED;
        add_blocker(result, SERVER_REASON_POLICY_DISABLED, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_DENIED, SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED,
                    SERVER_EVIDENCE_CURRENT);
        return 0;
    }
    if (config->policy == SERVER_POLICY_OBSERVE_ONLY) {
        result->decision = SERVER_DECISION_OBSERVE_ONLY;
        add_blocker(result, SERVER_REASON_POLICY_OBSERVE_ONLY, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_PASS, SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED,
                    SERVER_EVIDENCE_CURRENT);
        return 0;
    }
    if (config->policy != SERVER_POLICY_BOUNDED_SESSION ||
        config->schema_version != SERVER_MODE_CONFIG_VERSION ||
        config->max_duration_seconds == 0 ||
        config->max_duration_seconds > SERVER_MODE_MAX_SESSION_SECONDS ||
        !config->require_operator_confirmation || config->allow_automatic_start ||
        config->allow_restart_resume) {
        add_blocker(result, SERVER_REASON_CONFIG_INVALID, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_UNSAFE, SERVER_EVIDENCE_SOURCE_UNKNOWN,
                    SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        result->decision = SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }
    if (inputs->operation == SERVER_OPERATION_OBSERVE) {
        result->decision = SERVER_DECISION_OBSERVE_ONLY;
        add_blocker(result, SERVER_REASON_POLICY_OBSERVE_ONLY, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_PASS, SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED,
                    SERVER_EVIDENCE_CURRENT);
        return 0;
    }
    if (inputs->operation == SERVER_OPERATION_UNATTENDED) {
        add_blocker(result, SERVER_REASON_UNATTENDED_NOT_SUPPORTED,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                    SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED, SERVER_EVIDENCE_CURRENT);
        result->decision = SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }
    if (inputs->operation == SERVER_OPERATION_AUTOMATIC_RECOVERY) {
        int recovery_blocker = recovery_blockers(inputs, result);
        server_policy_reason_t reason = inputs->supervisor_state == SERVER_SUPERVISOR_UNVERIFIED
            ? SERVER_REASON_SUPERVISOR_UNVERIFIED : SERVER_REASON_AUTOMATIC_RECOVERY_DISABLED;
        add_blocker(result, reason, SERVER_POLICY_GATE_P013_LIFECYCLE_COMPATIBILITY,
                    SERVER_EVIDENCE_UNKNOWN, SERVER_EVIDENCE_SOURCE_UNKNOWN,
                    SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        result->decision = recovery_blocker ? SERVER_DECISION_BLOCK_RECOVERY
            : inputs->supervisor_state == SERVER_SUPERVISOR_UNVERIFIED
                ? SERVER_DECISION_BLOCK_UNVERIFIED_SUPERVISOR
                : SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }
    if (inputs->operation != SERVER_OPERATION_MANUAL_BOUNDED_SESSION) {
        add_blocker(result, SERVER_REASON_CONFIG_INVALID, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_UNSAFE, SERVER_EVIDENCE_SOURCE_UNKNOWN,
                    SERVER_EVIDENCE_FRESHNESS_UNKNOWN);
        result->decision = SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION;
        return 0;
    }

    int duration_blocker = 0;
    if (inputs->requested_duration_seconds == 0) {
        add_blocker(result, SERVER_REASON_DURATION_ZERO, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_DENIED, SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED,
                    SERVER_EVIDENCE_CURRENT);
        duration_blocker = 1;
    } else {
        if (inputs->requested_duration_seconds > SERVER_MODE_MAX_SESSION_SECONDS) {
            add_blocker(result, SERVER_REASON_DURATION_EXCEEDS_CEILING,
                        SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                        SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED, SERVER_EVIDENCE_CURRENT);
            duration_blocker = 1;
        }
        if (inputs->requested_duration_seconds > config->max_duration_seconds) {
            add_blocker(result, SERVER_REASON_DURATION_EXCEEDS_CONFIG,
                        SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                        SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED, SERVER_EVIDENCE_CURRENT);
            duration_blocker = 1;
        }
    }

    int recovery_blocker = recovery_blockers(inputs, result);
    int runtime_blocker = 0;
    int assertion_conflict = 0;
    int resource_blocker = 0;
    int deferred = 0;

    if (inputs->runtime_state == SERVER_RUNTIME_BLOCKED) {
        add_blocker(result, SERVER_REASON_DAEMON_BLOCKED, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_DENIED, inputs->runtime_source,
                    inputs->runtime_freshness);
        runtime_blocker = 1;
    } else if (inputs->runtime_state == SERVER_RUNTIME_ACTIVE) {
        add_blocker(result, SERVER_REASON_ASSERTION_OWNED, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_DENIED, inputs->runtime_source,
                    inputs->runtime_freshness);
        assertion_conflict = 1;
    } else if (inputs->runtime_state == SERVER_RUNTIME_UNKNOWN ||
               inputs->runtime_freshness != SERVER_EVIDENCE_CURRENT ||
               !physical_source(inputs->runtime_source) ||
               inputs->runtime_observed_at_utc <= 0) {
        add_blocker(result, SERVER_REASON_RUNTIME_UNKNOWN, SERVER_POLICY_GATE_NONE,
                    SERVER_EVIDENCE_UNKNOWN, inputs->runtime_source,
                    inputs->runtime_freshness);
        deferred = 1;
    }

    if (inputs->assertion_state == SERVER_ASSERTION_RELEASE_FAILED) {
        add_blocker(result, SERVER_REASON_ASSERTION_RELEASE_FAILED,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                    inputs->runtime_source, inputs->runtime_freshness);
        recovery_blocker = 1;
    } else if (inputs->assertion_state == SERVER_ASSERTION_OWNED) {
        if (inputs->runtime_state != SERVER_RUNTIME_ACTIVE) {
            add_blocker(result, SERVER_REASON_ASSERTION_OWNED,
                        SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_DENIED,
                        inputs->runtime_source, inputs->runtime_freshness);
        }
        assertion_conflict = 1;
    } else if (inputs->assertion_state == SERVER_ASSERTION_UNKNOWN) {
        add_blocker(result, SERVER_REASON_ASSERTION_OWNERSHIP_UNKNOWN,
                    SERVER_POLICY_GATE_NONE, SERVER_EVIDENCE_UNKNOWN,
                    inputs->runtime_source, inputs->runtime_freshness);
        recovery_blocker = 1;
    }

    if (inputs->runtime_state == SERVER_RUNTIME_IDLE &&
        inputs->assertion_state == SERVER_ASSERTION_NONE &&
        physical_source(inputs->runtime_source) &&
        inputs->runtime_freshness == SERVER_EVIDENCE_CURRENT &&
        inputs->runtime_observed_at_utc > 0) {
        /* Current runtime observations are useful for conflict checks; they
         * do not count as reviewed hardware acceptance evidence. */
    }

    for (size_t i = 0; i < sizeof(required_gates) / sizeof(required_gates[0]); ++i) {
        server_policy_gate_t gate = required_gates[i];
        evaluate_gate(inputs, gate, result, &resource_blocker, &deferred);
    }

    const server_policy_evidence_t *battery =
        &inputs->gates[SERVER_POLICY_GATE_BATTERY_SAFETY];
    if (battery->state == SERVER_EVIDENCE_PASS &&
        (inputs->battery_percentage < 0 || inputs->battery_percentage > 100 ||
         inputs->charging_status == SERVER_CHARGING_UNKNOWN)) {
        add_blocker(result, SERVER_REASON_EVIDENCE_MISSING,
                    SERVER_POLICY_GATE_BATTERY_SAFETY, SERVER_EVIDENCE_UNKNOWN,
                    battery->source, battery->freshness);
        deferred = 1;
    } else if (battery->state == SERVER_EVIDENCE_PASS && inputs->battery_percentage == 0) {
        add_blocker(result, SERVER_REASON_EVIDENCE_DENIED,
                    SERVER_POLICY_GATE_BATTERY_SAFETY, SERVER_EVIDENCE_DENIED,
                    battery->source, battery->freshness);
        resource_blocker = 1;
    }

    const server_policy_evidence_t *thermal =
        &inputs->gates[SERVER_POLICY_GATE_THERMAL_SAFETY];
    if (thermal->state == SERVER_EVIDENCE_PASS &&
        inputs->thermal_state == SERVER_THERMAL_UNKNOWN) {
        add_blocker(result, SERVER_REASON_EVIDENCE_MISSING,
                    SERVER_POLICY_GATE_THERMAL_SAFETY, SERVER_EVIDENCE_UNKNOWN,
                    thermal->source, thermal->freshness);
        deferred = 1;
    } else if (thermal->state == SERVER_EVIDENCE_PASS &&
               inputs->thermal_state != SERVER_THERMAL_NOMINAL) {
        add_blocker(result, SERVER_REASON_EVIDENCE_DENIED,
                    SERVER_POLICY_GATE_THERMAL_SAFETY, SERVER_EVIDENCE_DENIED,
                    thermal->source, thermal->freshness);
        resource_blocker = 1;
    }

    if (recovery_blocker) result->decision = SERVER_DECISION_BLOCK_RECOVERY;
    else if (runtime_blocker) result->decision = SERVER_DECISION_BLOCK_UNSAFE_RUNTIME;
    else if (assertion_conflict) result->decision = SERVER_DECISION_BLOCK_ASSERTION_CONFLICT;
    else if (resource_blocker) result->decision = SERVER_DECISION_BLOCK_RESOURCE_SAFETY;
    else if (duration_blocker) result->decision = SERVER_DECISION_BLOCK_DURATION;
    else if (deferred) result->decision = SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE;
    else {
        result->decision = SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION;
        result->eligible = 1;
    }
    /* This policy module never authorizes or performs an operation. */
    result->execution_authorized = 0;
    return 0;
}

const char *server_policy_operation_name(server_policy_operation_t value) {
    switch (value) {
        case SERVER_OPERATION_OBSERVE: return "OBSERVE";
        case SERVER_OPERATION_MANUAL_BOUNDED_SESSION: return "MANUAL_BOUNDED_SESSION";
        case SERVER_OPERATION_UNATTENDED: return "UNATTENDED";
        case SERVER_OPERATION_AUTOMATIC_RECOVERY: return "AUTOMATIC_RECOVERY";
    }
    return "UNKNOWN";
}

const char *server_policy_decision_name(server_policy_decision_t value) {
    switch (value) {
        case SERVER_DECISION_DISABLED: return "DISABLED";
        case SERVER_DECISION_OBSERVE_ONLY: return "OBSERVE_ONLY";
        case SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION: return "ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION";
        case SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE: return "DEFER_INSUFFICIENT_EVIDENCE";
        case SERVER_DECISION_BLOCK_RECOVERY: return "BLOCK_RECOVERY";
        case SERVER_DECISION_BLOCK_UNSAFE_RUNTIME: return "BLOCK_UNSAFE_RUNTIME";
        case SERVER_DECISION_BLOCK_UNVERIFIED_SUPERVISOR: return "BLOCK_UNVERIFIED_SUPERVISOR";
        case SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION: return "BLOCK_UNSAFE_CONFIGURATION";
        case SERVER_DECISION_BLOCK_RESOURCE_SAFETY: return "BLOCK_RESOURCE_SAFETY";
        case SERVER_DECISION_BLOCK_DURATION: return "BLOCK_DURATION";
        case SERVER_DECISION_BLOCK_ASSERTION_CONFLICT: return "BLOCK_ASSERTION_CONFLICT";
    }
    return "BLOCK_UNSAFE_CONFIGURATION";
}

const char *server_policy_gate_name(server_policy_gate_t value) {
    switch (value) {
        case SERVER_POLICY_GATE_NONE: return "none";
        case SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE: return "p011_package_acceptance";
        case SERVER_POLICY_GATE_INSTALLED_CLI: return "installed_cli_execution";
        case SERVER_POLICY_GATE_INSTALLED_DAEMON: return "installed_daemon_execution";
        case SERVER_POLICY_GATE_P012_IDLE_POWER_REVIEW: return "p012_idle_power_review";
        case SERVER_POLICY_GATE_ASSERTION_ACQUIRE: return "assertion_acquire";
        case SERVER_POLICY_GATE_ASSERTION_RELEASE: return "assertion_release";
        case SERVER_POLICY_GATE_P013_LIFECYCLE_COMPATIBILITY: return "p013_lifecycle_compatibility";
        case SERVER_POLICY_GATE_PHYSICAL_RECOVERY: return "physical_recovery";
        case SERVER_POLICY_GATE_BATTERY_SAFETY: return "battery_safety";
        case SERVER_POLICY_GATE_THERMAL_SAFETY: return "thermal_safety";
        case SERVER_POLICY_GATE_LAN_REACHABILITY: return "lan_reachability";
        case SERVER_POLICY_GATE_TAILSCALE_REACHABILITY: return "tailscale_reachability";
        case SERVER_POLICY_GATE_OPERATOR_ATTENDANCE: return "operator_attendance";
        case SERVER_POLICY_GATE_COUNT: break;
    }
    return "unknown";
}

const char *server_policy_reason_name(server_policy_reason_t value) {
    switch (value) {
        case SERVER_REASON_NONE: return "NONE";
        case SERVER_REASON_CONFIG_MISSING_DISABLED: return "CONFIG_MISSING_DISABLED";
        case SERVER_REASON_CONFIG_INVALID: return "CONFIG_INVALID";
        case SERVER_REASON_CONFIG_UNSAFE: return "CONFIG_UNSAFE";
        case SERVER_REASON_CONFIG_UNSUPPORTED: return "CONFIG_UNSUPPORTED";
        case SERVER_REASON_POLICY_DISABLED: return "POLICY_DISABLED";
        case SERVER_REASON_POLICY_OBSERVE_ONLY: return "POLICY_OBSERVE_ONLY";
        case SERVER_REASON_UNATTENDED_NOT_SUPPORTED: return "UNATTENDED_NOT_SUPPORTED";
        case SERVER_REASON_AUTOMATIC_RECOVERY_DISABLED: return "AUTOMATIC_RECOVERY_DISABLED";
        case SERVER_REASON_DURATION_ZERO: return "DURATION_ZERO";
        case SERVER_REASON_DURATION_EXCEEDS_CONFIG: return "DURATION_EXCEEDS_CONFIG";
        case SERVER_REASON_DURATION_EXCEEDS_CEILING: return "DURATION_EXCEEDS_CEILING";
        case SERVER_REASON_RECOVERY_MISSING: return "RECOVERY_MISSING";
        case SERVER_REASON_RECOVERY_UNSAFE: return "RECOVERY_UNSAFE";
        case SERVER_REASON_RECOVERY_CORRUPT: return "RECOVERY_CORRUPT";
        case SERVER_REASON_RECOVERY_UNSUPPORTED: return "RECOVERY_UNSUPPORTED";
        case SERVER_REASON_RECOVERY_IO_ERROR: return "RECOVERY_IO_ERROR";
        case SERVER_REASON_RECOVERY_RESTART_LIMIT: return "RECOVERY_RESTART_LIMIT";
        case SERVER_REASON_RECOVERY_RECORD_UNAVAILABLE: return "RECOVERY_RECORD_UNAVAILABLE";
        case SERVER_REASON_RECOVERY_PROCESS_NOT_CLEAN: return "RECOVERY_PROCESS_NOT_CLEAN";
        case SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED: return "RECOVERY_CLEANUP_UNVERIFIED";
        case SERVER_REASON_RECOVERY_RELEASE_FAILED: return "RECOVERY_RELEASE_FAILED";
        case SERVER_REASON_RECOVERY_OWNERSHIP_UNKNOWN: return "RECOVERY_OWNERSHIP_UNKNOWN";
        case SERVER_REASON_DAEMON_BLOCKED: return "DAEMON_BLOCKED";
        case SERVER_REASON_RUNTIME_UNKNOWN: return "RUNTIME_UNKNOWN";
        case SERVER_REASON_ASSERTION_RELEASE_FAILED: return "ASSERTION_RELEASE_FAILED";
        case SERVER_REASON_ASSERTION_OWNED: return "ASSERTION_OWNED";
        case SERVER_REASON_ASSERTION_OWNERSHIP_UNKNOWN: return "ASSERTION_OWNERSHIP_UNKNOWN";
        case SERVER_REASON_SUPERVISOR_UNVERIFIED: return "SUPERVISOR_UNVERIFIED";
        case SERVER_REASON_EVIDENCE_MISSING: return "EVIDENCE_MISSING";
        case SERVER_REASON_EVIDENCE_STALE: return "EVIDENCE_STALE";
        case SERVER_REASON_EVIDENCE_UNSAFE: return "EVIDENCE_UNSAFE";
        case SERVER_REASON_EVIDENCE_DENIED: return "EVIDENCE_DENIED";
        case SERVER_REASON_EVIDENCE_NONPHYSICAL: return "EVIDENCE_NONPHYSICAL";
        case SERVER_REASON_EVIDENCE_UNREVIEWED: return "EVIDENCE_UNREVIEWED";
        case SERVER_REASON_EVIDENCE_LOW_CONFIDENCE: return "EVIDENCE_LOW_CONFIDENCE";
    }
    return "UNKNOWN_REASON";
}

const char *server_policy_reason_requirement(server_policy_reason_t value,
                                             server_policy_gate_t gate) {
    switch (value) {
        case SERVER_REASON_CONFIG_MISSING_DISABLED: return "store an explicitly reviewed version 2 policy to request a bounded session";
        case SERVER_REASON_CONFIG_INVALID: return "replace the invalid configuration through an operator-reviewed configuration process";
        case SERVER_REASON_CONFIG_UNSAFE: return "inspect the path and file safety conditions without automatic repair";
        case SERVER_REASON_CONFIG_UNSUPPORTED: return "use a supported schema version after reviewing its policy meaning";
        case SERVER_REASON_POLICY_DISABLED: return "an explicit operator action is required to request another policy";
        case SERVER_REASON_POLICY_OBSERVE_ONLY: return "an explicit bounded-session request and separate authorization are required";
        case SERVER_REASON_UNATTENDED_NOT_SUPPORTED: return "P015 does not support unattended or automatic start";
        case SERVER_REASON_AUTOMATIC_RECOVERY_DISABLED: return "automatic recovery execution is not implemented or authorized";
        case SERVER_REASON_DURATION_ZERO: return "request a positive duration from 1 second through the configured maximum";
        case SERVER_REASON_DURATION_EXCEEDS_CONFIG: return "request no more than the configured session maximum";
        case SERVER_REASON_DURATION_EXCEEDS_CEILING: return "request no more than the 300 second P015 ceiling";
        case SERVER_REASON_RECOVERY_MISSING: return "complete P014 recovery review and retain a trusted recovery journal";
        case SERVER_REASON_RECOVERY_UNSAFE: return "resolve the unsafe P014 journal state without rewriting it automatically";
        case SERVER_REASON_RECOVERY_CORRUPT: return "review and resolve the corrupt P014 journal using its documented recovery procedure";
        case SERVER_REASON_RECOVERY_UNSUPPORTED: return "review the P014 journal schema before any session request";
        case SERVER_REASON_RECOVERY_IO_ERROR: return "restore safe read access to the existing P014 journal";
        case SERVER_REASON_RECOVERY_RESTART_LIMIT: return "wait for P014's rolling restart budget to recover; no automatic restart is performed";
        case SERVER_REASON_RECOVERY_RECORD_UNAVAILABLE: return "load a validated P014 recovery record";
        case SERVER_REASON_RECOVERY_PROCESS_NOT_CLEAN: return "establish a clean prior daemon exit through P014";
        case SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED: return "verify assertion cleanup under P014 and collect separate physical recovery evidence";
        case SERVER_REASON_RECOVERY_RELEASE_FAILED: return "resolve the P014 release failure and verify cleanup before any session";
        case SERVER_REASON_RECOVERY_OWNERSHIP_UNKNOWN: return "establish prior assertion ownership and cleanup through P014 review";
        case SERVER_REASON_DAEMON_BLOCKED: return "resolve the daemon BLOCKED state through the P014 recovery process";
        case SERVER_REASON_RUNTIME_UNKNOWN: return "obtain a current read-only daemon and assertion observation";
        case SERVER_REASON_ASSERTION_RELEASE_FAILED: return "resolve the release failure and verify cleanup before any new assertion";
        case SERVER_REASON_ASSERTION_OWNED: return "release or otherwise resolve the independently owned active assertion";
        case SERVER_REASON_ASSERTION_OWNERSHIP_UNKNOWN: return "establish current assertion ownership before any new session";
        case SERVER_REASON_SUPERVISOR_UNVERIFIED: return "verify the P014/P013 supervisor and lifecycle behavior; P015 does not start it";
        case SERVER_REASON_EVIDENCE_MISSING: return "collect and review current physical evidence for the named gate";
        case SERVER_REASON_EVIDENCE_STALE: return "collect a current observation for the named gate";
        case SERVER_REASON_EVIDENCE_UNSAFE: return "resolve the reported unsafe condition and repeat the reviewed observation";
        case SERVER_REASON_EVIDENCE_DENIED: return "review the explicit denial and do not override it with configuration";
        case SERVER_REASON_EVIDENCE_NONPHYSICAL: return "provide current P009-reviewed DEVICE_REPORTED or EXTERNAL_OBSERVER evidence, or a separately reviewed OPERATOR_RECORDED observation";
        case SERVER_REASON_EVIDENCE_UNREVIEWED: return "review evidence provenance and gate meaning before relying on it";
        case SERVER_REASON_EVIDENCE_LOW_CONFIDENCE: return "improve observation confidence and review provenance before relying on it";
        case SERVER_REASON_NONE: break;
    }
    (void)gate;
    return "inspect the named gate and provide the required reviewed evidence";
}

const char *server_evidence_state_name(server_evidence_state_t value) {
    switch (value) {
        case SERVER_EVIDENCE_PENDING: return "PENDING";
        case SERVER_EVIDENCE_PASS: return "PASS";
        case SERVER_EVIDENCE_DENIED: return "DENIED";
        case SERVER_EVIDENCE_UNSAFE: return "UNSAFE";
        case SERVER_EVIDENCE_UNKNOWN: return "UNKNOWN";
    }
    return "UNKNOWN";
}

const char *server_evidence_source_name(server_evidence_source_t value) {
    switch (value) {
        case SERVER_EVIDENCE_SOURCE_UNKNOWN: return "UNKNOWN";
        case SERVER_EVIDENCE_SOURCE_SIMULATED: return "SIMULATED";
        case SERVER_EVIDENCE_SOURCE_MOCK: return "MOCK";
        case SERVER_EVIDENCE_SOURCE_CI: return "CI";
        case SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED: return "DEVICE_REPORTED";
        case SERVER_EVIDENCE_SOURCE_EXTERNAL_OBSERVER: return "EXTERNAL_OBSERVER";
        case SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED: return "OPERATOR_RECORDED";
        case SERVER_EVIDENCE_SOURCE_P014_JOURNAL: return "P014_JOURNAL";
    }
    return "UNKNOWN";
}

const char *server_evidence_freshness_name(server_evidence_freshness_t value) {
    switch (value) {
        case SERVER_EVIDENCE_FRESHNESS_UNKNOWN: return "UNKNOWN";
        case SERVER_EVIDENCE_CURRENT: return "CURRENT";
        case SERVER_EVIDENCE_STALE: return "STALE";
    }
    return "UNKNOWN";
}

const char *server_evidence_confidence_name(server_evidence_confidence_t value) {
    switch (value) {
        case SERVER_EVIDENCE_CONFIDENCE_UNKNOWN: return "UNKNOWN";
        case SERVER_EVIDENCE_CONFIDENCE_LOW: return "LOW";
        case SERVER_EVIDENCE_CONFIDENCE_MEDIUM: return "MEDIUM";
        case SERVER_EVIDENCE_CONFIDENCE_HIGH: return "HIGH";
    }
    return "UNKNOWN";
}

const char *server_policy_runtime_name(server_policy_runtime_state_t value) {
    switch (value) {
        case SERVER_RUNTIME_UNKNOWN: return "UNKNOWN";
        case SERVER_RUNTIME_IDLE: return "IDLE";
        case SERVER_RUNTIME_ACTIVE: return "ACTIVE";
        case SERVER_RUNTIME_BLOCKED: return "BLOCKED";
    }
    return "UNKNOWN";
}

const char *server_policy_assertion_name(server_policy_assertion_state_t value) {
    switch (value) {
        case SERVER_ASSERTION_UNKNOWN: return "UNKNOWN";
        case SERVER_ASSERTION_NONE: return "NONE";
        case SERVER_ASSERTION_OWNED: return "OWNED";
        case SERVER_ASSERTION_RELEASE_FAILED: return "RELEASE_FAILED";
    }
    return "UNKNOWN";
}

const char *server_policy_supervisor_name(server_policy_supervisor_state_t value) {
    return value == SERVER_SUPERVISOR_VERIFIED ? "VERIFIED" : "UNVERIFIED";
}

const char *server_policy_activation_name(server_policy_activation_t value) {
    switch (value) {
        case SERVER_POLICY_ACTIVATION_UNKNOWN: return "UNKNOWN";
        case SERVER_POLICY_ACTIVATION_INACTIVE: return "NO";
        case SERVER_POLICY_ACTIVATION_ACTIVE: return "YES";
    }
    return "UNKNOWN";
}

const char *server_policy_charging_name(server_policy_charging_t value) {
    switch (value) {
        case SERVER_CHARGING_UNKNOWN: return "UNAVAILABLE";
        case SERVER_CHARGING_NO: return "NO";
        case SERVER_CHARGING_YES: return "YES";
    }
    return "UNAVAILABLE";
}

const char *server_policy_thermal_name(server_policy_thermal_t value) {
    switch (value) {
        case SERVER_THERMAL_UNKNOWN: return "UNAVAILABLE";
        case SERVER_THERMAL_NOMINAL: return "NOMINAL";
        case SERVER_THERMAL_ELEVATED: return "ELEVATED";
        case SERVER_THERMAL_CRITICAL: return "CRITICAL";
    }
    return "UNAVAILABLE";
}
