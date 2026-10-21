#include "health_policy.h"

static server_evidence_source_t policy_source(health_source_class_t source) {
    switch (source) {
        case HEALTH_SOURCE_DEVICE_REPORTED: return SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED;
        case HEALTH_SOURCE_EXTERNAL_OBSERVER: return SERVER_EVIDENCE_SOURCE_EXTERNAL_OBSERVER;
        case HEALTH_SOURCE_OPERATOR_RECORDED: return SERVER_EVIDENCE_SOURCE_OPERATOR_RECORDED;
        case HEALTH_SOURCE_MOCK: return SERVER_EVIDENCE_SOURCE_MOCK;
        case HEALTH_SOURCE_SIMULATED: return SERVER_EVIDENCE_SOURCE_SIMULATED;
        case HEALTH_SOURCE_CI: return SERVER_EVIDENCE_SOURCE_CI;
        case HEALTH_SOURCE_UNKNOWN: return SERVER_EVIDENCE_SOURCE_UNKNOWN;
    }
    return SERVER_EVIDENCE_SOURCE_UNKNOWN;
}

static server_evidence_freshness_t policy_freshness(health_freshness_t value) {
    switch (value) {
        case HEALTH_FRESHNESS_CURRENT: return SERVER_EVIDENCE_CURRENT;
        case HEALTH_FRESHNESS_STALE: return SERVER_EVIDENCE_STALE;
        case HEALTH_FRESHNESS_UNKNOWN: return SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
    }
    return SERVER_EVIDENCE_FRESHNESS_UNKNOWN;
}

static server_evidence_confidence_t policy_confidence(health_confidence_t value) {
    switch (value) {
        case HEALTH_CONFIDENCE_LOW: return SERVER_EVIDENCE_CONFIDENCE_LOW;
        case HEALTH_CONFIDENCE_MEDIUM: return SERVER_EVIDENCE_CONFIDENCE_MEDIUM;
        case HEALTH_CONFIDENCE_HIGH: return SERVER_EVIDENCE_CONFIDENCE_HIGH;
        case HEALTH_CONFIDENCE_UNKNOWN: return SERVER_EVIDENCE_CONFIDENCE_UNKNOWN;
    }
    return SERVER_EVIDENCE_CONFIDENCE_UNKNOWN;
}

static void expose_metadata(const health_observation_t *observation,
                            server_policy_evidence_t *evidence) {
    if (!observation || !evidence || evidence->state == SERVER_EVIDENCE_PASS ||
        evidence->state == SERVER_EVIDENCE_DENIED ||
        evidence->state == SERVER_EVIDENCE_UNSAFE) return;
    evidence->source = policy_source(observation->source_class);
    evidence->freshness = policy_freshness(observation->freshness);
    evidence->confidence = policy_confidence(observation->confidence);
    evidence->reviewed = observation->physical_source_verified &&
                         observation->safety_interpretation_reviewed &&
                         observation->p009_evidence_accepted;
    evidence->observed_at_utc = observation->observed_at_utc;
}

void health_apply_to_server_policy(const health_snapshot_t *snapshot,
                                   server_policy_inputs_t *inputs) {
    if (!snapshot || !inputs || !health_snapshot_validate(snapshot)) return;

    const health_observation_t *battery = &snapshot->battery_percentage_observation;
    server_policy_evidence_t *battery_gate =
        &inputs->gates[SERVER_POLICY_GATE_BATTERY_SAFETY];
    expose_metadata(battery, battery_gate);
    if (battery->value_valid && snapshot->battery_percentage >= 0 &&
        snapshot->battery_percentage <= 100) {
        inputs->battery_percentage = snapshot->battery_percentage;
    }
    const health_observation_t *charging = &snapshot->charging_observation;
    if (charging->value_valid) {
        if (snapshot->charging_state == HEALTH_CHARGING_YES)
            inputs->charging_status = SERVER_CHARGING_YES;
        else if (snapshot->charging_state == HEALTH_CHARGING_NO)
            inputs->charging_status = SERVER_CHARGING_NO;
        /* P015 has no FULL value. Preserve FULL in telemetry and map it to
         * UNKNOWN instead of treating a full battery as actively charging. */
    }

    const health_observation_t *thermal = &snapshot->thermal_observation;
    server_policy_evidence_t *thermal_gate =
        &inputs->gates[SERVER_POLICY_GATE_THERMAL_SAFETY];
    expose_metadata(thermal, thermal_gate);
    if (thermal->value_valid) {
        switch (snapshot->thermal_state) {
            case HEALTH_THERMAL_NOMINAL: inputs->thermal_state = SERVER_THERMAL_NOMINAL; break;
            case HEALTH_THERMAL_ELEVATED: inputs->thermal_state = SERVER_THERMAL_ELEVATED; break;
            case HEALTH_THERMAL_CRITICAL: inputs->thermal_state = SERVER_THERMAL_CRITICAL; break;
            case HEALTH_THERMAL_UNKNOWN: inputs->thermal_state = SERVER_THERMAL_UNKNOWN; break;
        }
        /* A verified current CRITICAL reading can only add a blocker. It does
         * not turn an unreviewed or mock reading into accepted evidence. */
        if (snapshot->thermal_state == HEALTH_THERMAL_CRITICAL &&
            thermal->source_class == HEALTH_SOURCE_DEVICE_REPORTED &&
            thermal->physical_source_verified &&
            thermal->freshness == HEALTH_FRESHNESS_CURRENT &&
            thermal_gate->state != SERVER_EVIDENCE_DENIED &&
            thermal_gate->state != SERVER_EVIDENCE_UNSAFE) {
            thermal_gate->state = SERVER_EVIDENCE_UNSAFE;
        }
    }
}
