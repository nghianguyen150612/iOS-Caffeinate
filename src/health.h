#ifndef IOSCAFFEINATE_HEALTH_H
#define IOSCAFFEINATE_HEALTH_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define HEALTH_SCHEMA_VERSION 1U
#define HEALTH_SOURCE_NAME_CAP 80
#define HEALTH_TIMEBASE_ID_CAP 64
#define HEALTH_DEFAULT_FRESHNESS_SECONDS 300U
#define HEALTH_MAX_FRESHNESS_SECONDS 3600U

typedef enum {
    HEALTH_STATUS_AVAILABLE = 0,
    HEALTH_STATUS_UNAVAILABLE,
    HEALTH_STATUS_INVALID,
    HEALTH_STATUS_ERROR,
    HEALTH_STATUS_UNSUPPORTED
} health_status_t;

typedef enum {
    HEALTH_SOURCE_UNKNOWN = 0,
    HEALTH_SOURCE_DEVICE_REPORTED,
    HEALTH_SOURCE_EXTERNAL_OBSERVER,
    HEALTH_SOURCE_OPERATOR_RECORDED,
    HEALTH_SOURCE_MOCK,
    HEALTH_SOURCE_SIMULATED,
    HEALTH_SOURCE_CI
} health_source_class_t;

typedef enum {
    HEALTH_FRESHNESS_UNKNOWN = 0,
    HEALTH_FRESHNESS_CURRENT,
    HEALTH_FRESHNESS_STALE
} health_freshness_t;

typedef enum {
    HEALTH_CONFIDENCE_UNKNOWN = 0,
    HEALTH_CONFIDENCE_LOW,
    HEALTH_CONFIDENCE_MEDIUM,
    HEALTH_CONFIDENCE_HIGH
} health_confidence_t;

typedef enum {
    HEALTH_CHARGING_UNKNOWN = 0,
    HEALTH_CHARGING_YES,
    HEALTH_CHARGING_NO,
    HEALTH_CHARGING_FULL
} health_charging_state_t;

typedef enum {
    HEALTH_THERMAL_UNKNOWN = 0,
    HEALTH_THERMAL_NOMINAL,
    HEALTH_THERMAL_ELEVATED,
    HEALTH_THERMAL_CRITICAL
} health_thermal_state_t;

/* NSProcessInfo's FAIR and SERIOUS states remain distinct in raw_state even
 * though both normalize to the conservative ELEVATED category. */
typedef enum {
    HEALTH_THERMAL_RAW_UNKNOWN = 0,
    HEALTH_THERMAL_RAW_NOMINAL,
    HEALTH_THERMAL_RAW_FAIR,
    HEALTH_THERMAL_RAW_SERIOUS,
    HEALTH_THERMAL_RAW_CRITICAL,
    HEALTH_THERMAL_RAW_UNRECOGNIZED
} health_thermal_raw_state_t;

typedef enum {
    HEALTH_RESOURCE_AVAILABLE = 0,
    HEALTH_RESOURCE_UNAVAILABLE,
    HEALTH_RESOURCE_STALE,
    HEALTH_RESOURCE_INVALID,
    HEALTH_RESOURCE_UNVERIFIED,
    HEALTH_RESOURCE_WARNING,
    HEALTH_RESOURCE_CRITICAL
} health_resource_state_t;

typedef enum {
    HEALTH_SOURCE_COMPARISON_UNKNOWN = 0,
    HEALTH_SOURCE_COMPARISON_AGREE,
    HEALTH_SOURCE_COMPARISON_DISAGREE
} health_source_comparison_t;

typedef struct {
    health_status_t status;
    health_source_class_t source_class;
    char source_name[HEALTH_SOURCE_NAME_CAP];
    int source_detected;
    int measurement_acquired;
    int value_valid;
    int physical_source_verified;
    int safety_interpretation_reviewed;
    int p009_evidence_accepted;
    int64_t observed_at_utc;
    uint64_t observed_monotonic_ns;
    uint64_t clock_uncertainty_ms;
    char timebase_id[HEALTH_TIMEBASE_ID_CAP];
    health_freshness_t freshness;
    uint64_t age_seconds;
    int age_available;
    health_confidence_t confidence;
} health_observation_t;

typedef struct {
    unsigned schema_version;
    int battery_percentage; /* -1 means unavailable; 0 is an observed value. */
    health_observation_t battery_percentage_observation;
    health_charging_state_t charging_state;
    health_observation_t charging_observation;
    health_thermal_state_t thermal_state;
    health_thermal_raw_state_t thermal_raw_state;
    health_observation_t thermal_observation;
    uint64_t device_uptime_seconds;
    health_observation_t device_uptime_observation;
    int battery_sources_disagree;
    int thermal_sources_disagree;
} health_snapshot_t;

typedef struct {
    int64_t utc_seconds;
    uint64_t monotonic_ns;
    uint64_t clock_uncertainty_ms;
    char timebase_id[HEALTH_TIMEBASE_ID_CAP];
} health_clock_sample_t;

typedef struct {
    health_status_t status;
    int source_detected;
    health_source_class_t source_class;
    const char *source_name;
} health_platform_origin_t;

typedef struct {
    health_platform_origin_t battery_percentage_origin;
    health_platform_origin_t charging_origin;
    health_platform_origin_t thermal_origin;
    health_platform_origin_t device_uptime_origin;
    int battery_percentage;
    health_charging_state_t charging_state;
    health_thermal_raw_state_t thermal_raw_state;
    uint64_t device_uptime_seconds;
} health_platform_sample_t;

typedef int (*health_platform_reader_fn)(void *context,
                                         health_platform_sample_t *sample);
typedef int (*health_clock_reader_fn)(void *context,
                                      health_clock_sample_t *sample);

typedef struct {
    health_platform_reader_fn read_platform;
    void *platform_context;
    health_clock_reader_fn read_clock;
    void *clock_context;
} health_provider_t;

void health_snapshot_init(health_snapshot_t *snapshot);
void health_default_provider(health_provider_t *provider);
int health_collect_with_provider(const health_provider_t *provider,
                                 health_snapshot_t *snapshot);
int health_collect(health_snapshot_t *snapshot);
int health_clock_read(void *context, health_clock_sample_t *sample);
int health_observation_validate(const health_observation_t *observation);
int health_snapshot_validate(const health_snapshot_t *snapshot);
int health_recheck_freshness(health_observation_t *observation,
                             int64_t now_utc_seconds,
                             uint64_t now_monotonic_ns,
                             const char *timebase_id,
                             uint64_t now_uncertainty_ms,
                             unsigned max_age_seconds);
health_source_comparison_t health_compare_battery_sources(
    const health_observation_t *left, int left_percentage,
    const health_observation_t *right, int right_percentage);
health_source_comparison_t health_record_battery_comparison(
    health_snapshot_t *snapshot,
    const health_observation_t *left, int left_percentage,
    const health_observation_t *right, int right_percentage);
health_source_comparison_t health_record_thermal_comparison(
    health_snapshot_t *snapshot,
    const health_observation_t *left, health_thermal_raw_state_t left_state,
    const health_observation_t *right, health_thermal_raw_state_t right_state);
health_resource_state_t health_classify_battery(
    const health_snapshot_t *snapshot);
health_resource_state_t health_classify_thermal(
    const health_snapshot_t *snapshot);

const char *health_status_name(health_status_t value);
const char *health_source_class_name(health_source_class_t value);
const char *health_freshness_name(health_freshness_t value);
const char *health_confidence_name(health_confidence_t value);
const char *health_charging_name(health_charging_state_t value);
const char *health_thermal_name(health_thermal_state_t value);
const char *health_thermal_raw_name(health_thermal_raw_state_t value);
const char *health_resource_state_name(health_resource_state_t value);
const char *health_platform_backend_name(void);
void health_sources_write(FILE *out);

#endif
