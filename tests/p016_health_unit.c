#define _POSIX_C_SOURCE 200809L

#include "health.h"
#include "health_mock.h"
#include "health_policy.h"

#include <stdio.h>
#include <string.h>

static unsigned checks;
static unsigned failures;

static void check(int condition, const char *name) {
    checks++;
    if (!condition) {
        failures++;
        fprintf(stderr, "FAIL: %s\n", name);
    }
}

static void origin_set(health_platform_origin_t *origin, health_status_t status,
                       const char *name) {
    origin->status = status;
    origin->source_detected = status == HEALTH_STATUS_AVAILABLE;
    origin->source_class = HEALTH_SOURCE_MOCK;
    origin->source_name = name;
}

static void mock_init(health_mock_t *mock) {
    memset(mock, 0, sizeof(*mock));
    origin_set(&mock->platform.battery_percentage_origin, HEALTH_STATUS_AVAILABLE,
               "mock.battery.percent");
    origin_set(&mock->platform.charging_origin, HEALTH_STATUS_AVAILABLE,
               "mock.battery.state");
    origin_set(&mock->platform.thermal_origin, HEALTH_STATUS_AVAILABLE,
               "mock.thermal.category");
    origin_set(&mock->platform.device_uptime_origin, HEALTH_STATUS_AVAILABLE,
               "mock.device.uptime");
    mock->platform.battery_percentage = 0;
    mock->platform.charging_state = HEALTH_CHARGING_YES;
    mock->platform.thermal_raw_state = HEALTH_THERMAL_RAW_NOMINAL;
    mock->platform.device_uptime_seconds = 120;
    mock->clock.utc_seconds = 1000;
    mock->clock.monotonic_ns = 100000000000ULL;
    mock->clock.clock_uncertainty_ms = 0;
    snprintf(mock->clock.timebase_id, sizeof(mock->clock.timebase_id), "boot-a");
}

static int collect(health_mock_t *mock, health_snapshot_t *snapshot) {
    health_provider_t provider;
    health_mock_provider_init(&provider, mock);
    return health_collect_with_provider(&provider, snapshot);
}

static health_observation_t valid_observation(const char *source) {
    health_observation_t observation;
    memset(&observation, 0, sizeof(observation));
    observation.status = HEALTH_STATUS_AVAILABLE;
    observation.source_class = HEALTH_SOURCE_DEVICE_REPORTED;
    snprintf(observation.source_name, sizeof(observation.source_name), "%s", source);
    observation.source_detected = 1;
    observation.measurement_acquired = 1;
    observation.value_valid = 1;
    observation.observed_at_utc = 1000;
    observation.observed_monotonic_ns = 100000000000ULL;
    observation.clock_uncertainty_ms = 0;
    snprintf(observation.timebase_id, sizeof(observation.timebase_id), "boot-a");
    observation.freshness = HEALTH_FRESHNESS_CURRENT;
    observation.age_available = 1;
    observation.confidence = HEALTH_CONFIDENCE_MEDIUM;
    return observation;
}

static void test_battery_and_charging(void) {
    health_mock_t mock;
    health_snapshot_t snapshot;
    mock_init(&mock);
    check(collect(&mock, &snapshot) == 0, "mock provider collects a complete snapshot");
    check(health_snapshot_validate(&snapshot), "zero percent is a valid snapshot");
    check(snapshot.battery_percentage == 0, "zero battery percent is preserved");
    check(snapshot.battery_percentage_observation.value_valid, "zero battery value is marked valid");
    check(snapshot.charging_state == HEALTH_CHARGING_YES, "charging state is preserved");
    check(snapshot.device_uptime_seconds == 120, "device uptime fixture is preserved");

    mock.platform.battery_percentage = 100;
    mock.platform.charging_state = HEALTH_CHARGING_NO;
    check(collect(&mock, &snapshot) == 0 && snapshot.battery_percentage == 100,
          "one hundred percent is valid");
    check(snapshot.charging_state == HEALTH_CHARGING_NO,
          "discharging state is preserved");

    mock.platform.battery_percentage_origin.status = HEALTH_STATUS_UNAVAILABLE;
    mock.platform.battery_percentage_origin.source_detected = 0;
    mock.platform.battery_percentage = 77;
    check(collect(&mock, &snapshot) == 0, "unavailable battery source collects");
    check(snapshot.battery_percentage == -1, "unavailable percentage uses sentinel");
    check(!snapshot.battery_percentage_observation.value_valid,
          "unavailable percentage does not become a measurement");

    mock.platform.battery_percentage_origin.status = HEALTH_STATUS_AVAILABLE;
    mock.platform.battery_percentage_origin.source_detected = 1;
    mock.platform.battery_percentage = 101;
    check(collect(&mock, &snapshot) == 0, "invalid percentage is reportable");
    check(snapshot.battery_percentage_observation.status == HEALTH_STATUS_INVALID,
          "percentage above one hundred is rejected");
    check(snapshot.battery_percentage == -1, "invalid percentage is never clamped");

    mock.platform.battery_percentage = -1;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.battery_percentage_observation.status == HEALTH_STATUS_INVALID,
          "negative percentage is rejected");

    mock.platform.battery_percentage = 55;
    mock.platform.charging_state = HEALTH_CHARGING_UNKNOWN;
    check(collect(&mock, &snapshot) == 0, "unknown charging source is reportable");
    check(snapshot.charging_state == HEALTH_CHARGING_UNKNOWN &&
          !snapshot.charging_observation.value_valid,
          "unknown charging is not guessed from percentage");
    check(snapshot.charging_observation.measurement_acquired,
          "unknown charging response records acquisition separately");

    mock.platform.charging_state = HEALTH_CHARGING_FULL;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.charging_state == HEALTH_CHARGING_FULL,
          "full is kept distinct from charging");
    mock.platform.charging_state = (health_charging_state_t)99;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.charging_observation.status == HEALTH_STATUS_INVALID,
          "out-of-range charging enum is rejected");
}

static void test_thermal_and_partial_failures(void) {
    static const struct {
        health_thermal_raw_state_t raw;
        health_thermal_state_t normalized;
    } mappings[] = {
        {HEALTH_THERMAL_RAW_NOMINAL, HEALTH_THERMAL_NOMINAL},
        {HEALTH_THERMAL_RAW_FAIR, HEALTH_THERMAL_ELEVATED},
        {HEALTH_THERMAL_RAW_SERIOUS, HEALTH_THERMAL_ELEVATED},
        {HEALTH_THERMAL_RAW_CRITICAL, HEALTH_THERMAL_CRITICAL}
    };
    health_mock_t mock;
    health_snapshot_t snapshot;
    mock_init(&mock);
    for (size_t i = 0; i < sizeof(mappings) / sizeof(mappings[0]); ++i) {
        mock.platform.thermal_raw_state = mappings[i].raw;
        check(collect(&mock, &snapshot) == 0, "thermal category collects");
        check(snapshot.thermal_state == mappings[i].normalized,
              "thermal platform state maps conservatively");
        check(snapshot.thermal_raw_state == mappings[i].raw,
              "raw thermal distinction is preserved");
    }
    mock.platform.thermal_raw_state = HEALTH_THERMAL_RAW_UNKNOWN;
    check(collect(&mock, &snapshot) == 0, "unknown thermal category collects");
    check(snapshot.thermal_state == HEALTH_THERMAL_UNKNOWN &&
          snapshot.thermal_observation.status == HEALTH_STATUS_UNAVAILABLE,
          "unknown thermal category never maps to nominal");
    mock.platform.thermal_raw_state = HEALTH_THERMAL_RAW_UNRECOGNIZED;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.thermal_observation.status == HEALTH_STATUS_UNSUPPORTED,
          "new thermal API category is reported unsupported");
    mock.platform.thermal_raw_state = (health_thermal_raw_state_t)99;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.thermal_observation.status == HEALTH_STATUS_INVALID,
          "malformed thermal category is rejected");

    mock_init(&mock);
    mock.platform.thermal_origin.status = HEALTH_STATUS_UNSUPPORTED;
    mock.platform.thermal_origin.source_detected = 0;
    mock.platform.thermal_origin.source_name = "THERMAL_SYMBOL_MISSING";
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.thermal_observation.status == HEALTH_STATUS_UNSUPPORTED &&
          snapshot.thermal_state == HEALTH_THERMAL_UNKNOWN,
          "missing platform symbol remains unsupported and unknown");

    mock_init(&mock);
    mock.platform.battery_percentage_origin.status = HEALTH_STATUS_ERROR;
    mock.platform.battery_percentage_origin.source_name = "BATTERY_PERMISSION_ERROR";
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.battery_percentage_observation.status == HEALTH_STATUS_ERROR,
          "permission failure remains an explicit source error");

    mock_init(&mock);
    mock.clock_result = -1;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.battery_percentage_observation.value_valid &&
          snapshot.battery_percentage_observation.freshness == HEALTH_FRESHNESS_UNKNOWN,
          "clock failure preserves value but leaves freshness unknown");

    mock_init(&mock);
    mock.platform.charging_origin.status = HEALTH_STATUS_UNAVAILABLE;
    mock.platform.thermal_origin.status = HEALTH_STATUS_UNSUPPORTED;
    check(collect(&mock, &snapshot) == 0, "partial observation succeeds");
    check(snapshot.battery_percentage_observation.value_valid,
          "partial observation retains successful battery reading");
    check(snapshot.charging_state == HEALTH_CHARGING_UNKNOWN,
          "partial observation leaves charging unknown");
    check(snapshot.thermal_state == HEALTH_THERMAL_UNKNOWN,
          "partial observation leaves thermal unknown");

    mock.platform_result = -1;
    check(collect(&mock, &snapshot) == 0, "provider failure returns diagnostic snapshot");
    check(snapshot.battery_percentage_observation.status == HEALTH_STATUS_ERROR,
          "provider failure is an error, not nominal data");
    check(snapshot.thermal_state == HEALTH_THERMAL_UNKNOWN,
          "provider failure has no fabricated thermal value");

    mock_init(&mock);
    char long_source[HEALTH_SOURCE_NAME_CAP + 1];
    memset(long_source, 'x', sizeof(long_source));
    long_source[sizeof(long_source) - 1] = '\0';
    mock.platform.thermal_origin.source_name = long_source;
    check(collect(&mock, &snapshot) == 0 &&
          snapshot.thermal_observation.status == HEALTH_STATUS_INVALID,
          "malformed adapter source name is rejected");
}

static void test_freshness_and_sources(void) {
    health_observation_t observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 1001, 101000000000ULL,
                                   "boot-a", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_CURRENT &&
          observation.age_seconds == 1,
          "monotonic age classifies a current observation");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 1600, 700000000000ULL,
                                   "boot-a", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_STALE,
          "expired monotonic observation is stale");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 999, 101000000000ULL,
                                   "boot-a", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_UNKNOWN,
          "future wall clock timestamp cannot prove freshness");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 1001, 99000000000ULL,
                                   "boot-a", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_UNKNOWN,
          "monotonic clock rollback is unknown");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 1001, 101000000000ULL,
                                   "boot-b", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_UNKNOWN,
          "boot identity change invalidates monotonic comparison");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 900, 101000000000ULL,
                                   "boot-a", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_UNKNOWN,
          "wall clock rollback cannot make a reading current");
    observation = valid_observation("api-a");
    check(health_recheck_freshness(&observation, 1100, 101000000000ULL,
                                   "boot-a", 0, HEALTH_MAX_FRESHNESS_SECONDS + 1U) == -1,
          "freshness threshold is bounded");

    health_observation_t left = valid_observation("api-a");
    health_observation_t right = valid_observation("api-b");
    check(health_compare_battery_sources(&left, 50, &right, 50) ==
          HEALTH_SOURCE_COMPARISON_AGREE, "independent matching sources agree");
    check(health_compare_battery_sources(&left, 50, &right, 54) ==
          HEALTH_SOURCE_COMPARISON_DISAGREE, "conflicting sources remain detectable");
    snprintf(right.source_name, sizeof(right.source_name), "api-a");
    check(health_compare_battery_sources(&left, 50, &right, 90) ==
          HEALTH_SOURCE_COMPARISON_UNKNOWN, "same source is not counted as independent");
    check(health_compare_battery_sources(&left, -1, &right, 90) ==
          HEALTH_SOURCE_COMPARISON_UNKNOWN, "invalid comparison values are rejected");

    health_snapshot_t disagreement;
    health_snapshot_init(&disagreement);
    right = valid_observation("api-b");
    check(health_record_battery_comparison(&disagreement, &left, 50, &right, 54) ==
          HEALTH_SOURCE_COMPARISON_DISAGREE && disagreement.battery_sources_disagree,
          "battery disagreement is retained in snapshot diagnostics");
    check(health_record_thermal_comparison(&disagreement, &left,
          HEALTH_THERMAL_RAW_FAIR, &right, HEALTH_THERMAL_RAW_CRITICAL) ==
          HEALTH_SOURCE_COMPARISON_DISAGREE && disagreement.thermal_sources_disagree,
          "thermal category disagreement is retained in snapshot diagnostics");
    check(health_record_thermal_comparison(&disagreement, &left,
          HEALTH_THERMAL_RAW_FAIR, &right, HEALTH_THERMAL_RAW_SERIOUS) ==
          HEALTH_SOURCE_COMPARISON_DISAGREE,
          "different raw thermal categories remain distinguishable");

    observation = valid_observation("api-a");
    observation.observed_monotonic_ns = 0;
    observation.timebase_id[0] = '\0';
    check(health_recheck_freshness(&observation, 1005, 0, "", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_CURRENT,
          "bounded wall clock fallback works without monotonic metadata");
    check(health_recheck_freshness(&observation, 2000, 0, "", 0, 300) == 0 &&
          observation.freshness == HEALTH_FRESHNESS_STALE,
          "wall clock fallback expires old observations");

    observation = valid_observation("bad\nsource");
    check(!health_observation_validate(&observation),
          "source metadata rejects line injection");
}

static void test_policy_adapter_and_defaults(void) {
    health_mock_t mock;
    health_snapshot_t snapshot;
    health_provider_t provider;
    server_policy_inputs_t inputs;
    mock_init(&mock);
    mock.platform.battery_percentage = 0;
    mock.platform.charging_state = HEALTH_CHARGING_FULL;
    mock.platform.thermal_raw_state = HEALTH_THERMAL_RAW_NOMINAL;
    health_mock_provider_init(&provider, &mock);
    check(health_collect_with_provider(&provider, &snapshot) == 0,
          "policy adapter fixture collects");
    server_policy_inputs_init(&inputs);
    health_apply_to_server_policy(&snapshot, &inputs);
    check(inputs.battery_percentage == 0, "zero value reaches P015 as raw diagnostic data");
    check(inputs.charging_status == SERVER_CHARGING_UNKNOWN,
          "full state is not misrepresented as active charging");
    check(inputs.thermal_state == SERVER_THERMAL_NOMINAL,
          "nominal raw state reaches P015 diagnostics");
    check(inputs.gates[SERVER_POLICY_GATE_BATTERY_SAFETY].state == SERVER_EVIDENCE_PENDING,
          "battery telemetry cannot pass the P015 gate");
    check(inputs.gates[SERVER_POLICY_GATE_THERMAL_SAFETY].state == SERVER_EVIDENCE_PENDING,
          "thermal telemetry cannot pass the P015 gate");
    check(!inputs.gates[SERVER_POLICY_GATE_THERMAL_SAFETY].reviewed,
          "mock telemetry is never marked reviewed");

    snapshot.thermal_state = HEALTH_THERMAL_CRITICAL;
    snapshot.thermal_raw_state = HEALTH_THERMAL_RAW_CRITICAL;
    snapshot.thermal_observation.source_class = HEALTH_SOURCE_DEVICE_REPORTED;
    snapshot.thermal_observation.physical_source_verified = 1;
    snapshot.thermal_observation.freshness = HEALTH_FRESHNESS_CURRENT;
    snapshot.thermal_observation.value_valid = 1;
    snapshot.thermal_observation.status = HEALTH_STATUS_AVAILABLE;
    server_policy_inputs_init(&inputs);
    health_apply_to_server_policy(&snapshot, &inputs);
    check(inputs.gates[SERVER_POLICY_GATE_THERMAL_SAFETY].state == SERVER_EVIDENCE_UNSAFE,
          "trusted current critical thermal state adds a blocker");
    check(!inputs.gates[SERVER_POLICY_GATE_THERMAL_SAFETY].reviewed,
          "critical blocker does not become P009 accepted evidence");
    check(inputs.gates[SERVER_POLICY_GATE_BATTERY_SAFETY].state == SERVER_EVIDENCE_PENDING,
          "critical thermal evidence does not change battery gate");

    mock_init(&mock);
    health_default_provider(&provider);
    check(health_collect_with_provider(&provider, &snapshot) == 0,
          "default target provider has a safe fallback");
    check(snapshot.battery_percentage == -1 &&
          snapshot.battery_percentage_observation.source_class == HEALTH_SOURCE_MOCK,
          "Linux default fixture stays explicitly mock and unavailable");
    check(snapshot.thermal_state == HEALTH_THERMAL_UNKNOWN,
          "unsupported host thermal source stays unknown");
    check(strcmp(health_platform_backend_name(), "MOCK_NO_SENSOR_DATA") == 0,
          "mock backend identifies itself as non-device data");
}

int main(void) {
    test_battery_and_charging();
    test_thermal_and_partial_failures();
    test_freshness_and_sources();
    test_policy_adapter_and_defaults();
    if (failures) {
        fprintf(stderr, "P016 health/native checks: %u failed out of %u\n", failures, checks);
        return 1;
    }
    printf("P016 health/native checks: %u passed\n", checks);
    return 0;
}
