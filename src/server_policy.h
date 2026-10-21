#ifndef IOSCAFFEINATE_SERVER_POLICY_H
#define IOSCAFFEINATE_SERVER_POLICY_H

#include "recovery.h"
#include "server_mode.h"

#include <stddef.h>
#include <stdint.h>

#define SERVER_POLICY_ENGINE_VERSION 2
#define SERVER_POLICY_MAX_BLOCKERS 32

typedef enum {
    SERVER_OPERATION_OBSERVE = 0,
    SERVER_OPERATION_MANUAL_BOUNDED_SESSION,
    SERVER_OPERATION_UNATTENDED,
    SERVER_OPERATION_AUTOMATIC_RECOVERY,
    SERVER_OPERATION_SCHEDULED_UNATTENDED
} server_policy_operation_t;

typedef enum {
    SERVER_DECISION_DISABLED = 0,
    SERVER_DECISION_OBSERVE_ONLY,
    SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION,
    SERVER_DECISION_DEFER_INSUFFICIENT_EVIDENCE,
    SERVER_DECISION_BLOCK_RECOVERY,
    SERVER_DECISION_BLOCK_UNSAFE_RUNTIME,
    SERVER_DECISION_BLOCK_UNVERIFIED_SUPERVISOR,
    SERVER_DECISION_BLOCK_UNSAFE_CONFIGURATION,
    SERVER_DECISION_BLOCK_RESOURCE_SAFETY,
    SERVER_DECISION_BLOCK_DURATION,
    SERVER_DECISION_BLOCK_ASSERTION_CONFLICT
} server_policy_decision_t;

typedef enum {
    SERVER_EVIDENCE_PENDING = 0,
    SERVER_EVIDENCE_PASS,
    SERVER_EVIDENCE_DENIED,
    SERVER_EVIDENCE_UNSAFE,
    SERVER_EVIDENCE_UNKNOWN
} server_evidence_state_t;

typedef enum {
    SERVER_EVIDENCE_SOURCE_UNKNOWN = 0,
    SERVER_EVIDENCE_SOURCE_SIMULATED,
    SERVER_EVIDENCE_SOURCE_MOCK,
    SERVER_EVIDENCE_SOURCE_CI,
    SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED,
    SERVER_EVIDENCE_SOURCE_EXTERNAL_OBSERVER,
    SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED,
    SERVER_EVIDENCE_SOURCE_P014_JOURNAL
} server_evidence_source_t;

typedef enum {
    SERVER_EVIDENCE_FRESHNESS_UNKNOWN = 0,
    SERVER_EVIDENCE_CURRENT,
    SERVER_EVIDENCE_STALE
} server_evidence_freshness_t;

typedef enum {
    SERVER_EVIDENCE_CONFIDENCE_UNKNOWN = 0,
    SERVER_EVIDENCE_CONFIDENCE_LOW,
    SERVER_EVIDENCE_CONFIDENCE_MEDIUM,
    SERVER_EVIDENCE_CONFIDENCE_HIGH
} server_evidence_confidence_t;

typedef enum {
    SERVER_POLICY_GATE_NONE = 0,
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
    SERVER_POLICY_GATE_OPERATOR_ATTENDANCE,
    SERVER_POLICY_GATE_COUNT
} server_policy_gate_t;

typedef struct {
    server_evidence_state_t state;
    server_evidence_source_t source;
    server_evidence_freshness_t freshness;
    server_evidence_confidence_t confidence;
    int reviewed;
    int64_t observed_at_utc;
} server_policy_evidence_t;

typedef enum {
    SERVER_RUNTIME_UNKNOWN = 0,
    SERVER_RUNTIME_IDLE,
    SERVER_RUNTIME_ACTIVE,
    SERVER_RUNTIME_BLOCKED
} server_policy_runtime_state_t;

typedef enum {
    SERVER_ASSERTION_UNKNOWN = 0,
    SERVER_ASSERTION_NONE,
    SERVER_ASSERTION_OWNED,
    SERVER_ASSERTION_RELEASE_FAILED
} server_policy_assertion_state_t;

typedef enum {
    SERVER_SUPERVISOR_UNVERIFIED = 0,
    SERVER_SUPERVISOR_VERIFIED
} server_policy_supervisor_state_t;

typedef enum {
    SERVER_POLICY_ACTIVATION_UNKNOWN = 0,
    SERVER_POLICY_ACTIVATION_INACTIVE,
    SERVER_POLICY_ACTIVATION_ACTIVE
} server_policy_activation_t;

typedef enum {
    SERVER_CHARGING_UNKNOWN = 0,
    SERVER_CHARGING_NO,
    SERVER_CHARGING_YES
} server_policy_charging_t;

typedef enum {
    SERVER_THERMAL_UNKNOWN = 0,
    SERVER_THERMAL_NOMINAL,
    SERVER_THERMAL_ELEVATED,
    SERVER_THERMAL_CRITICAL
} server_policy_thermal_t;

typedef enum {
    SERVER_REASON_NONE = 0,
    SERVER_REASON_CONFIG_MISSING_DISABLED,
    SERVER_REASON_CONFIG_INVALID,
    SERVER_REASON_CONFIG_UNSAFE,
    SERVER_REASON_CONFIG_UNSUPPORTED,
    SERVER_REASON_POLICY_DISABLED,
    SERVER_REASON_POLICY_OBSERVE_ONLY,
    SERVER_REASON_UNATTENDED_NOT_SUPPORTED,
    SERVER_REASON_SCHEDULE_EXECUTOR_NOT_AUTHORIZED,
    SERVER_REASON_AUTOMATIC_RECOVERY_DISABLED,
    SERVER_REASON_DURATION_ZERO,
    SERVER_REASON_DURATION_EXCEEDS_CONFIG,
    SERVER_REASON_DURATION_EXCEEDS_CEILING,
    SERVER_REASON_RECOVERY_MISSING,
    SERVER_REASON_RECOVERY_UNSAFE,
    SERVER_REASON_RECOVERY_CORRUPT,
    SERVER_REASON_RECOVERY_UNSUPPORTED,
    SERVER_REASON_RECOVERY_IO_ERROR,
    SERVER_REASON_RECOVERY_RESTART_LIMIT,
    SERVER_REASON_RECOVERY_RECORD_UNAVAILABLE,
    SERVER_REASON_RECOVERY_PROCESS_NOT_CLEAN,
    SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED,
    SERVER_REASON_RECOVERY_RELEASE_FAILED,
    SERVER_REASON_RECOVERY_OWNERSHIP_UNKNOWN,
    SERVER_REASON_DAEMON_BLOCKED,
    SERVER_REASON_RUNTIME_UNKNOWN,
    SERVER_REASON_ASSERTION_RELEASE_FAILED,
    SERVER_REASON_ASSERTION_OWNED,
    SERVER_REASON_ASSERTION_OWNERSHIP_UNKNOWN,
    SERVER_REASON_SUPERVISOR_UNVERIFIED,
    SERVER_REASON_EVIDENCE_MISSING,
    SERVER_REASON_EVIDENCE_STALE,
    SERVER_REASON_EVIDENCE_UNSAFE,
    SERVER_REASON_EVIDENCE_DENIED,
    SERVER_REASON_EVIDENCE_NONPHYSICAL,
    SERVER_REASON_EVIDENCE_UNREVIEWED,
    SERVER_REASON_EVIDENCE_LOW_CONFIDENCE
} server_policy_reason_t;

typedef struct {
    server_policy_operation_t operation;
    uint64_t requested_duration_seconds;
    server_policy_runtime_state_t runtime_state;
    server_policy_assertion_state_t assertion_state;
    server_evidence_source_t runtime_source;
    server_evidence_freshness_t runtime_freshness;
    int64_t runtime_observed_at_utc;
    server_policy_supervisor_state_t supervisor_state;
    recovery_store_result_t recovery_store_status;
    int recovery_record_available;
    recovery_record_t recovery_record;
    recovery_decision_t recovery_restart_decision;
    int recovery_restart_decision_available;
    server_policy_evidence_t gates[SERVER_POLICY_GATE_COUNT];
    int battery_percentage; /* -1 means unavailable; zero is a real observation. */
    server_policy_charging_t charging_status;
    server_policy_thermal_t thermal_state;
} server_policy_inputs_t;

typedef struct {
    server_policy_reason_t reason;
    server_policy_gate_t gate;
    server_evidence_state_t state;
    server_evidence_source_t source;
    server_evidence_freshness_t freshness;
} server_policy_blocker_t;

typedef struct {
    unsigned policy_version;
    unsigned config_schema_version;
    server_policy_t configured_policy;
    server_policy_operation_t operation;
    server_policy_decision_t decision;
    int eligible;
    int execution_authorized;
    server_policy_activation_t runtime_activation;
    unsigned maximum_duration_seconds;
    recovery_store_result_t recovery_status;
    recovery_process_state_t recovery_process;
    recovery_cleanup_state_t recovery_cleanup;
    recovery_exit_class_t recovery_last_exit;
    recovery_decision_t automatic_recovery_decision;
    int automatic_recovery_decision_available;
    server_policy_supervisor_state_t supervisor_state;
    server_policy_reason_t primary_reason;
    server_policy_blocker_t blockers[SERVER_POLICY_MAX_BLOCKERS];
    size_t blocker_count;
} server_policy_result_t;

void server_policy_inputs_init(server_policy_inputs_t *inputs);
int server_policy_evaluate(const server_config_t *config,
                           const server_policy_inputs_t *inputs,
                           server_policy_result_t *result);

const char *server_policy_operation_name(server_policy_operation_t value);
const char *server_policy_decision_name(server_policy_decision_t value);
const char *server_policy_reason_name(server_policy_reason_t value);
const char *server_policy_reason_requirement(server_policy_reason_t value,
                                             server_policy_gate_t gate);
const char *server_policy_gate_name(server_policy_gate_t value);
const char *server_evidence_state_name(server_evidence_state_t value);
const char *server_evidence_source_name(server_evidence_source_t value);
const char *server_evidence_freshness_name(server_evidence_freshness_t value);
const char *server_evidence_confidence_name(server_evidence_confidence_t value);
const char *server_policy_runtime_name(server_policy_runtime_state_t value);
const char *server_policy_assertion_name(server_policy_assertion_state_t value);
const char *server_policy_supervisor_name(server_policy_supervisor_state_t value);
const char *server_policy_activation_name(server_policy_activation_t value);
const char *server_policy_charging_name(server_policy_charging_t value);
const char *server_policy_thermal_name(server_policy_thermal_t value);

#endif
