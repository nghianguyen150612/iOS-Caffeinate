#if defined(__APPLE__)
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L

#include "health.h"

#include <errno.h>
#include <limits.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>

#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
#include <mach/mach_time.h>
#include <sys/sysctl.h>
#endif

static void copy_name(char *target, size_t target_cap, const char *source) {
    if (target_cap == 0) return;
    target[0] = '\0';
    if (!source) return;
    size_t length = strnlen(source, target_cap);
    if (length < target_cap) memcpy(target, source, length + 1);
}

static int safe_identifier(const char *value, size_t cap, int allow_empty) {
    if (!value) return 0;
    size_t length = strnlen(value, cap);
    if (length >= cap || (!allow_empty && length == 0)) return 0;
    for (size_t i = 0; i < length; ++i) {
        unsigned char c = (unsigned char)value[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-' ||
              c == '.' || c == ':')) return 0;
    }
    return 1;
}

static void observation_init(health_observation_t *observation) {
    memset(observation, 0, sizeof(*observation));
    observation->status = HEALTH_STATUS_UNAVAILABLE;
    observation->source_class = HEALTH_SOURCE_UNKNOWN;
    observation->freshness = HEALTH_FRESHNESS_UNKNOWN;
    observation->confidence = HEALTH_CONFIDENCE_UNKNOWN;
    copy_name(observation->source_name, sizeof(observation->source_name), "UNKNOWN");
}

void health_snapshot_init(health_snapshot_t *snapshot) {
    if (!snapshot) return;
    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->schema_version = HEALTH_SCHEMA_VERSION;
    snapshot->battery_percentage = -1;
    snapshot->charging_state = HEALTH_CHARGING_UNKNOWN;
    snapshot->thermal_state = HEALTH_THERMAL_UNKNOWN;
    snapshot->thermal_raw_state = HEALTH_THERMAL_RAW_UNKNOWN;
    observation_init(&snapshot->battery_percentage_observation);
    observation_init(&snapshot->charging_observation);
    observation_init(&snapshot->thermal_observation);
    observation_init(&snapshot->device_uptime_observation);
}

const char *health_status_name(health_status_t value) {
    switch (value) {
        case HEALTH_STATUS_AVAILABLE: return "AVAILABLE";
        case HEALTH_STATUS_UNAVAILABLE: return "UNAVAILABLE";
        case HEALTH_STATUS_INVALID: return "INVALID";
        case HEALTH_STATUS_ERROR: return "ERROR";
        case HEALTH_STATUS_UNSUPPORTED: return "UNSUPPORTED";
    }
    return "INVALID";
}

const char *health_source_class_name(health_source_class_t value) {
    switch (value) {
        case HEALTH_SOURCE_UNKNOWN: return "UNKNOWN";
        case HEALTH_SOURCE_DEVICE_REPORTED: return "DEVICE_REPORTED";
        case HEALTH_SOURCE_EXTERNAL_OBSERVER: return "EXTERNAL_OBSERVER";
        case HEALTH_SOURCE_OPERATOR_RECORDED: return "OPERATOR_RECORDED";
        case HEALTH_SOURCE_MOCK: return "MOCK";
        case HEALTH_SOURCE_SIMULATED: return "SIMULATED";
        case HEALTH_SOURCE_CI: return "CI";
    }
    return "UNKNOWN";
}

const char *health_freshness_name(health_freshness_t value) {
    switch (value) {
        case HEALTH_FRESHNESS_UNKNOWN: return "UNKNOWN";
        case HEALTH_FRESHNESS_CURRENT: return "CURRENT";
        case HEALTH_FRESHNESS_STALE: return "STALE";
    }
    return "UNKNOWN";
}

const char *health_confidence_name(health_confidence_t value) {
    switch (value) {
        case HEALTH_CONFIDENCE_UNKNOWN: return "UNKNOWN";
        case HEALTH_CONFIDENCE_LOW: return "LOW";
        case HEALTH_CONFIDENCE_MEDIUM: return "MEDIUM";
        case HEALTH_CONFIDENCE_HIGH: return "HIGH";
    }
    return "UNKNOWN";
}

const char *health_charging_name(health_charging_state_t value) {
    switch (value) {
        case HEALTH_CHARGING_UNKNOWN: return "UNKNOWN";
        case HEALTH_CHARGING_YES: return "CHARGING";
        case HEALTH_CHARGING_NO: return "DISCHARGING";
        case HEALTH_CHARGING_FULL: return "FULL";
    }
    return "UNKNOWN";
}

const char *health_thermal_name(health_thermal_state_t value) {
    switch (value) {
        case HEALTH_THERMAL_UNKNOWN: return "UNKNOWN";
        case HEALTH_THERMAL_NOMINAL: return "NOMINAL";
        case HEALTH_THERMAL_ELEVATED: return "ELEVATED";
        case HEALTH_THERMAL_CRITICAL: return "CRITICAL";
    }
    return "UNKNOWN";
}

const char *health_thermal_raw_name(health_thermal_raw_state_t value) {
    switch (value) {
        case HEALTH_THERMAL_RAW_UNKNOWN: return "UNKNOWN";
        case HEALTH_THERMAL_RAW_NOMINAL: return "NOMINAL";
        case HEALTH_THERMAL_RAW_FAIR: return "FAIR";
        case HEALTH_THERMAL_RAW_SERIOUS: return "SERIOUS";
        case HEALTH_THERMAL_RAW_CRITICAL: return "CRITICAL";
        case HEALTH_THERMAL_RAW_UNRECOGNIZED: return "UNRECOGNIZED";
    }
    return "UNRECOGNIZED";
}

const char *health_resource_state_name(health_resource_state_t value) {
    switch (value) {
        case HEALTH_RESOURCE_AVAILABLE: return "AVAILABLE";
        case HEALTH_RESOURCE_UNAVAILABLE: return "UNAVAILABLE";
        case HEALTH_RESOURCE_STALE: return "STALE";
        case HEALTH_RESOURCE_INVALID: return "INVALID";
        case HEALTH_RESOURCE_UNVERIFIED: return "UNVERIFIED";
        case HEALTH_RESOURCE_WARNING: return "WARNING";
        case HEALTH_RESOURCE_CRITICAL: return "CRITICAL";
    }
    return "INVALID";
}

static int valid_enum_observation(const health_observation_t *observation) {
    if (!observation) return 0;
    if (observation->status < HEALTH_STATUS_AVAILABLE ||
        observation->status > HEALTH_STATUS_UNSUPPORTED ||
        observation->source_class < HEALTH_SOURCE_UNKNOWN ||
        observation->source_class > HEALTH_SOURCE_CI ||
        observation->freshness < HEALTH_FRESHNESS_UNKNOWN ||
        observation->freshness > HEALTH_FRESHNESS_STALE ||
        observation->confidence < HEALTH_CONFIDENCE_UNKNOWN ||
        observation->confidence > HEALTH_CONFIDENCE_HIGH) return 0;
    return 1;
}

int health_observation_validate(const health_observation_t *observation) {
    if (!valid_enum_observation(observation) ||
        memchr(observation->source_name, '\0', sizeof(observation->source_name)) == NULL ||
        memchr(observation->timebase_id, '\0', sizeof(observation->timebase_id)) == NULL ||
        !safe_identifier(observation->source_name, sizeof(observation->source_name), 0) ||
        !safe_identifier(observation->timebase_id, sizeof(observation->timebase_id), 1) ||
        (observation->source_detected != 0 && observation->source_detected != 1) ||
        (observation->measurement_acquired != 0 && observation->measurement_acquired != 1) ||
        (observation->value_valid != 0 && observation->value_valid != 1) ||
        (observation->physical_source_verified != 0 && observation->physical_source_verified != 1) ||
        (observation->safety_interpretation_reviewed != 0 && observation->safety_interpretation_reviewed != 1) ||
        (observation->p009_evidence_accepted != 0 && observation->p009_evidence_accepted != 1) ||
        (observation->age_available != 0 && observation->age_available != 1) ||
        observation->observed_at_utc < 0 ||
        observation->clock_uncertainty_ms > 86400000ULL) return 0;
    if (observation->value_valid &&
        (observation->status != HEALTH_STATUS_AVAILABLE ||
         !observation->measurement_acquired ||
         !observation->source_detected ||
         observation->source_class == HEALTH_SOURCE_UNKNOWN ||
         observation->source_name[0] == '\0')) return 0;
    if (observation->status == HEALTH_STATUS_AVAILABLE && !observation->value_valid) return 0;
    if (observation->freshness != HEALTH_FRESHNESS_UNKNOWN &&
        (!observation->value_valid || !observation->age_available)) return 0;
    if (observation->freshness == HEALTH_FRESHNESS_CURRENT &&
        observation->observed_at_utc <= 0) return 0;
    if (observation->physical_source_verified &&
        (observation->source_class != HEALTH_SOURCE_DEVICE_REPORTED &&
         observation->source_class != HEALTH_SOURCE_EXTERNAL_OBSERVER)) return 0;
    if (observation->p009_evidence_accepted &&
        (!observation->safety_interpretation_reviewed ||
         !observation->physical_source_verified)) return 0;
    if (observation->safety_interpretation_reviewed &&
        !observation->physical_source_verified) return 0;
    return 1;
}

int health_snapshot_validate(const health_snapshot_t *snapshot) {
    if (!snapshot || snapshot->schema_version != HEALTH_SCHEMA_VERSION ||
        snapshot->battery_percentage < -1 || snapshot->battery_percentage > 100 ||
        snapshot->charging_state < HEALTH_CHARGING_UNKNOWN ||
        snapshot->charging_state > HEALTH_CHARGING_FULL ||
        snapshot->thermal_state < HEALTH_THERMAL_UNKNOWN ||
        snapshot->thermal_state > HEALTH_THERMAL_CRITICAL ||
        snapshot->thermal_raw_state < HEALTH_THERMAL_RAW_UNKNOWN ||
        snapshot->thermal_raw_state > HEALTH_THERMAL_RAW_UNRECOGNIZED ||
        !health_observation_validate(&snapshot->battery_percentage_observation) ||
        !health_observation_validate(&snapshot->charging_observation) ||
        !health_observation_validate(&snapshot->thermal_observation) ||
        !health_observation_validate(&snapshot->device_uptime_observation)) return 0;
    if ((snapshot->battery_percentage >= 0) !=
        snapshot->battery_percentage_observation.value_valid ||
        ((snapshot->battery_percentage_observation.status == HEALTH_STATUS_AVAILABLE) !=
         snapshot->battery_percentage_observation.value_valid)) return 0;
    if ((snapshot->charging_state != HEALTH_CHARGING_UNKNOWN) !=
        snapshot->charging_observation.value_valid ||
        ((snapshot->charging_observation.status == HEALTH_STATUS_AVAILABLE) !=
         snapshot->charging_observation.value_valid)) return 0;
    if ((snapshot->thermal_state != HEALTH_THERMAL_UNKNOWN) !=
        snapshot->thermal_observation.value_valid ||
        ((snapshot->thermal_observation.status == HEALTH_STATUS_AVAILABLE) !=
         snapshot->thermal_observation.value_valid)) return 0;
    if ((snapshot->device_uptime_observation.status == HEALTH_STATUS_AVAILABLE) !=
        snapshot->device_uptime_observation.value_valid) return 0;
    if ((snapshot->battery_sources_disagree != 0 && snapshot->battery_sources_disagree != 1) ||
        (snapshot->thermal_sources_disagree != 0 && snapshot->thermal_sources_disagree != 1)) return 0;
    return 1;
}

static void observe_origin(health_observation_t *observation,
                           const health_platform_origin_t *origin,
                           const health_clock_sample_t *clock_sample,
                           int clock_valid) {
    observation_init(observation);
    if (!origin) return;
    observation->status = origin->status;
    observation->source_class = origin->source_class;
    observation->source_detected = origin->source_detected == 1;
    copy_name(observation->source_name, sizeof(observation->source_name),
              origin->source_name ? origin->source_name : "UNKNOWN");
    observation->measurement_acquired = origin->status == HEALTH_STATUS_AVAILABLE;
    observation->value_valid = origin->status == HEALTH_STATUS_AVAILABLE;
    observation->confidence = origin->status == HEALTH_STATUS_AVAILABLE
        ? HEALTH_CONFIDENCE_MEDIUM : HEALTH_CONFIDENCE_UNKNOWN;
    if (clock_valid) {
        observation->observed_at_utc = clock_sample->utc_seconds;
        observation->observed_monotonic_ns = clock_sample->monotonic_ns;
        observation->clock_uncertainty_ms = clock_sample->clock_uncertainty_ms;
        copy_name(observation->timebase_id, sizeof(observation->timebase_id),
                  clock_sample->timebase_id);
        if (clock_sample->utc_seconds > 0 && observation->measurement_acquired) {
            observation->freshness = HEALTH_FRESHNESS_CURRENT;
            observation->age_seconds = 0;
            observation->age_available = 1;
        }
    }
    if (origin->source_detected != 0 && origin->source_detected != 1) {
        observation->status = HEALTH_STATUS_INVALID;
        observation->source_detected = 0;
        observation->value_valid = 0;
        observation->measurement_acquired = 0;
    }
    if (origin->status < HEALTH_STATUS_AVAILABLE ||
        origin->status > HEALTH_STATUS_UNSUPPORTED ||
        origin->source_class < HEALTH_SOURCE_UNKNOWN ||
        origin->source_class > HEALTH_SOURCE_CI ||
        !safe_identifier(origin->source_name, HEALTH_SOURCE_NAME_CAP, 0)) {
        observation->status = HEALTH_STATUS_INVALID;
        observation->source_class = HEALTH_SOURCE_UNKNOWN;
        observation->source_detected = 0;
        observation->value_valid = 0;
        observation->measurement_acquired = 0;
        copy_name(observation->source_name, sizeof(observation->source_name), "INVALID_SOURCE");
    }
    if (observation->status != HEALTH_STATUS_AVAILABLE) {
        observation->value_valid = 0;
        observation->freshness = HEALTH_FRESHNESS_UNKNOWN;
        observation->age_seconds = 0;
        observation->age_available = 0;
    }
}

static void mark_invalid(health_observation_t *observation) {
    observation->status = HEALTH_STATUS_INVALID;
    observation->value_valid = 0;
    observation->freshness = HEALTH_FRESHNESS_UNKNOWN;
    observation->age_seconds = 0;
    observation->age_available = 0;
}

static void clear_value_age(health_observation_t *observation) {
    observation->value_valid = 0;
    observation->freshness = HEALTH_FRESHNESS_UNKNOWN;
    observation->age_seconds = 0;
    observation->age_available = 0;
}

static health_thermal_state_t normalize_thermal(health_thermal_raw_state_t value) {
    switch (value) {
        case HEALTH_THERMAL_RAW_NOMINAL: return HEALTH_THERMAL_NOMINAL;
        case HEALTH_THERMAL_RAW_FAIR:
        case HEALTH_THERMAL_RAW_SERIOUS: return HEALTH_THERMAL_ELEVATED;
        case HEALTH_THERMAL_RAW_CRITICAL: return HEALTH_THERMAL_CRITICAL;
        case HEALTH_THERMAL_RAW_UNKNOWN:
        case HEALTH_THERMAL_RAW_UNRECOGNIZED: return HEALTH_THERMAL_UNKNOWN;
    }
    return HEALTH_THERMAL_UNKNOWN;
}

int health_collect_with_provider(const health_provider_t *provider,
                                 health_snapshot_t *snapshot) {
    health_platform_sample_t raw;
    health_clock_sample_t clock_sample;
    int have_clock = 0;
    int read_result;
    if (!provider || !provider->read_platform || !snapshot) return -1;
    health_snapshot_init(snapshot);
    memset(&raw, 0, sizeof(raw));
    raw.battery_percentage_origin.status = HEALTH_STATUS_ERROR;
    raw.charging_origin.status = HEALTH_STATUS_ERROR;
    raw.thermal_origin.status = HEALTH_STATUS_ERROR;
    raw.device_uptime_origin.status = HEALTH_STATUS_ERROR;
    raw.battery_percentage_origin.source_name = "UNKNOWN";
    raw.charging_origin.source_name = "UNKNOWN";
    raw.thermal_origin.source_name = "UNKNOWN";
    raw.device_uptime_origin.source_name = "UNKNOWN";
    memset(&clock_sample, 0, sizeof(clock_sample));
    if (provider->read_clock && provider->read_clock(provider->clock_context, &clock_sample) == 0 &&
        clock_sample.utc_seconds >= 0 &&
        memchr(clock_sample.timebase_id, '\0', sizeof(clock_sample.timebase_id)) != NULL) {
        have_clock = 1;
    }
    read_result = provider->read_platform(provider->platform_context, &raw);
    observe_origin(&snapshot->battery_percentage_observation,
                   &raw.battery_percentage_origin, &clock_sample, have_clock);
    observe_origin(&snapshot->charging_observation,
                   &raw.charging_origin, &clock_sample, have_clock);
    observe_origin(&snapshot->thermal_observation,
                   &raw.thermal_origin, &clock_sample, have_clock);
    observe_origin(&snapshot->device_uptime_observation,
                   &raw.device_uptime_origin, &clock_sample, have_clock);

    if (read_result != 0) {
        health_observation_t *observations[] = {
            &snapshot->battery_percentage_observation,
            &snapshot->charging_observation,
            &snapshot->thermal_observation,
            &snapshot->device_uptime_observation
        };
        for (size_t i = 0; i < sizeof(observations) / sizeof(observations[0]); ++i) {
            observations[i]->status = HEALTH_STATUS_ERROR;
            observations[i]->source_class = HEALTH_SOURCE_UNKNOWN;
            observations[i]->source_detected = 0;
            observations[i]->measurement_acquired = 0;
            observations[i]->value_valid = 0;
            observations[i]->freshness = HEALTH_FRESHNESS_UNKNOWN;
            observations[i]->age_seconds = 0;
            observations[i]->age_available = 0;
            observations[i]->confidence = HEALTH_CONFIDENCE_UNKNOWN;
            copy_name(observations[i]->source_name, sizeof(observations[i]->source_name),
                      "PLATFORM_READ_ERROR");
        }
        return 0;
    }

    if (snapshot->battery_percentage_observation.status == HEALTH_STATUS_AVAILABLE) {
        if (raw.battery_percentage < 0 || raw.battery_percentage > 100) {
            mark_invalid(&snapshot->battery_percentage_observation);
        } else {
            snapshot->battery_percentage = raw.battery_percentage;
        }
    }
    if (snapshot->charging_observation.status == HEALTH_STATUS_AVAILABLE) {
        if (raw.charging_state < HEALTH_CHARGING_UNKNOWN ||
            raw.charging_state > HEALTH_CHARGING_FULL) {
            mark_invalid(&snapshot->charging_observation);
        } else if (raw.charging_state == HEALTH_CHARGING_UNKNOWN) {
            snapshot->charging_observation.status = HEALTH_STATUS_UNAVAILABLE;
            clear_value_age(&snapshot->charging_observation);
        } else {
            snapshot->charging_state = raw.charging_state;
        }
    }
    if (snapshot->thermal_observation.status == HEALTH_STATUS_AVAILABLE) {
        if (raw.thermal_raw_state < HEALTH_THERMAL_RAW_UNKNOWN ||
            raw.thermal_raw_state > HEALTH_THERMAL_RAW_UNRECOGNIZED) {
            snapshot->thermal_raw_state = HEALTH_THERMAL_RAW_UNRECOGNIZED;
            snapshot->thermal_observation.status = HEALTH_STATUS_INVALID;
            clear_value_age(&snapshot->thermal_observation);
        } else if (raw.thermal_raw_state == HEALTH_THERMAL_RAW_UNRECOGNIZED) {
            snapshot->thermal_raw_state = HEALTH_THERMAL_RAW_UNRECOGNIZED;
            snapshot->thermal_state = HEALTH_THERMAL_UNKNOWN;
            snapshot->thermal_observation.status = HEALTH_STATUS_UNSUPPORTED;
            clear_value_age(&snapshot->thermal_observation);
        } else if (raw.thermal_raw_state == HEALTH_THERMAL_RAW_UNKNOWN) {
            snapshot->thermal_raw_state = HEALTH_THERMAL_RAW_UNKNOWN;
            snapshot->thermal_state = HEALTH_THERMAL_UNKNOWN;
            snapshot->thermal_observation.status = HEALTH_STATUS_UNAVAILABLE;
            clear_value_age(&snapshot->thermal_observation);
        } else {
            snapshot->thermal_raw_state = raw.thermal_raw_state;
            snapshot->thermal_state = normalize_thermal(raw.thermal_raw_state);
            if (snapshot->thermal_state == HEALTH_THERMAL_UNKNOWN) {
                snapshot->thermal_observation.status = HEALTH_STATUS_UNSUPPORTED;
                clear_value_age(&snapshot->thermal_observation);
            }
        }
    }
    if (snapshot->device_uptime_observation.status == HEALTH_STATUS_AVAILABLE) {
        snapshot->device_uptime_seconds = raw.device_uptime_seconds;
    }
    if (!health_snapshot_validate(snapshot)) return -1;
    return 0;
}

int health_collect(health_snapshot_t *snapshot) {
    health_provider_t provider;
    health_default_provider(&provider);
    return health_collect_with_provider(&provider, snapshot);
}

int health_clock_read(void *context, health_clock_sample_t *sample) {
    struct timeval wall;
    (void)context;
    if (!sample) return -1;
    memset(sample, 0, sizeof(*sample));
    if (gettimeofday(&wall, NULL) != 0 || wall.tv_sec < 0 || wall.tv_usec < 0 ||
        wall.tv_usec >= 1000000) return -1;
    sample->utc_seconds = (int64_t)wall.tv_sec;
#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    mach_timebase_info_data_t timebase;
    if (mach_timebase_info(&timebase) != KERN_SUCCESS || timebase.denom == 0) return -1;
    long double nanoseconds = ((long double)mach_continuous_time() *
                               (long double)timebase.numer) /
                              (long double)timebase.denom;
    if (nanoseconds < 0 || nanoseconds > (long double)UINT64_MAX) return -1;
    sample->monotonic_ns = (uint64_t)nanoseconds;
    int mib[2] = {CTL_KERN, KERN_BOOTTIME};
    struct timeval boot_time;
    size_t boot_time_size = sizeof(boot_time);
    if (sysctl(mib, 2, &boot_time, &boot_time_size, NULL, 0) == 0 &&
        boot_time_size == sizeof(boot_time) && boot_time.tv_sec >= 0) {
        snprintf(sample->timebase_id, sizeof(sample->timebase_id),
                 "mach-continuous:%lld", (long long)boot_time.tv_sec);
    } else {
        sample->timebase_id[0] = '\0';
    }
#else
    struct timespec monotonic;
    if (clock_gettime(CLOCK_MONOTONIC, &monotonic) != 0 ||
        monotonic.tv_sec < 0 || monotonic.tv_nsec < 0 || monotonic.tv_nsec >= 1000000000L ||
        (uint64_t)monotonic.tv_sec > (UINT64_MAX - (uint64_t)monotonic.tv_nsec) / 1000000000ULL)
        return -1;
    sample->monotonic_ns = (uint64_t)monotonic.tv_sec * 1000000000ULL +
                           (uint64_t)monotonic.tv_nsec;
    sample->timebase_id[0] = '\0';
#endif
    sample->clock_uncertainty_ms = 1000;
    return 0;
}

static uint64_t uncertainty_seconds(uint64_t uncertainty_ms) {
    return uncertainty_ms / 1000ULL + (uncertainty_ms % 1000ULL != 0);
}

int health_recheck_freshness(health_observation_t *observation,
                             int64_t now_utc_seconds,
                             uint64_t now_monotonic_ns,
                             const char *timebase_id,
                             uint64_t now_uncertainty_ms,
                             unsigned max_age_seconds) {
    int same_timebase = 0;
    uint64_t uncertainty_ms;
    uint64_t age = 0;
    if (!health_observation_validate(observation) || now_utc_seconds <= 0 ||
        max_age_seconds == 0 || max_age_seconds > HEALTH_MAX_FRESHNESS_SECONDS ||
        now_uncertainty_ms > 86400000ULL) return -1;
    observation->freshness = HEALTH_FRESHNESS_UNKNOWN;
    observation->age_available = 0;
    if (!observation->value_valid || observation->observed_at_utc <= 0) return 0;
    uncertainty_ms = observation->clock_uncertainty_ms > now_uncertainty_ms
        ? observation->clock_uncertainty_ms : now_uncertainty_ms;
    if (now_utc_seconds < observation->observed_at_utc &&
        (uint64_t)(observation->observed_at_utc - now_utc_seconds) >
            uncertainty_seconds(uncertainty_ms)) return 0;

    if (timebase_id && timebase_id[0] != '\0' && observation->timebase_id[0] != '\0') {
        same_timebase = strcmp(timebase_id, observation->timebase_id) == 0;
        if (!same_timebase) return 0;
    }
    if (same_timebase && now_monotonic_ns != 0 && observation->observed_monotonic_ns != 0) {
        if (now_monotonic_ns < observation->observed_monotonic_ns) return 0;
        age = (now_monotonic_ns - observation->observed_monotonic_ns) / 1000000000ULL;
        observation->age_seconds = age;
        observation->age_available = 1;
        uint64_t upper_age = age + uncertainty_seconds(uncertainty_ms);
        uint64_t lower_age = age > uncertainty_seconds(uncertainty_ms)
            ? age - uncertainty_seconds(uncertainty_ms) : 0;
        if (lower_age > max_age_seconds) observation->freshness = HEALTH_FRESHNESS_STALE;
        else if (upper_age <= max_age_seconds) observation->freshness = HEALTH_FRESHNESS_CURRENT;
        return 0;
    }

    if (now_utc_seconds < observation->observed_at_utc) return 0;
    age = (uint64_t)(now_utc_seconds - observation->observed_at_utc);
    observation->age_seconds = age;
    observation->age_available = 1;
    uint64_t uncertainty = uncertainty_seconds(uncertainty_ms);
    uint64_t upper_age = age + uncertainty;
    uint64_t lower_age = age > uncertainty ? age - uncertainty : 0;
    if (lower_age > max_age_seconds) observation->freshness = HEALTH_FRESHNESS_STALE;
    else if (upper_age <= max_age_seconds) observation->freshness = HEALTH_FRESHNESS_CURRENT;
    return 0;
}

health_source_comparison_t health_compare_battery_sources(
    const health_observation_t *left, int left_percentage,
    const health_observation_t *right, int right_percentage) {
    if (!health_observation_validate(left) || !health_observation_validate(right) ||
        left_percentage < 0 || left_percentage > 100 ||
        right_percentage < 0 || right_percentage > 100 ||
        !left->value_valid || !right->value_valid ||
        left->freshness != HEALTH_FRESHNESS_CURRENT ||
        right->freshness != HEALTH_FRESHNESS_CURRENT ||
        left->source_class == HEALTH_SOURCE_UNKNOWN ||
        right->source_class == HEALTH_SOURCE_UNKNOWN ||
        strcmp(left->source_name, right->source_name) == 0) return HEALTH_SOURCE_COMPARISON_UNKNOWN;
    int difference = left_percentage > right_percentage
        ? left_percentage - right_percentage : right_percentage - left_percentage;
    return difference <= 1 ? HEALTH_SOURCE_COMPARISON_AGREE
                           : HEALTH_SOURCE_COMPARISON_DISAGREE;
}

health_source_comparison_t health_record_battery_comparison(
    health_snapshot_t *snapshot,
    const health_observation_t *left, int left_percentage,
    const health_observation_t *right, int right_percentage) {
    if (!snapshot) return HEALTH_SOURCE_COMPARISON_UNKNOWN;
    health_source_comparison_t result = health_compare_battery_sources(
        left, left_percentage, right, right_percentage);
    if (result == HEALTH_SOURCE_COMPARISON_DISAGREE)
        snapshot->battery_sources_disagree = 1;
    return result;
}

health_source_comparison_t health_record_thermal_comparison(
    health_snapshot_t *snapshot,
    const health_observation_t *left, health_thermal_raw_state_t left_state,
    const health_observation_t *right, health_thermal_raw_state_t right_state) {
    if (!snapshot || !health_observation_validate(left) ||
        !health_observation_validate(right) || !left->value_valid || !right->value_valid ||
        left->freshness != HEALTH_FRESHNESS_CURRENT ||
        right->freshness != HEALTH_FRESHNESS_CURRENT ||
        left->source_class == HEALTH_SOURCE_UNKNOWN ||
        right->source_class == HEALTH_SOURCE_UNKNOWN ||
        strcmp(left->source_name, right->source_name) == 0 ||
        left_state <= HEALTH_THERMAL_RAW_UNKNOWN ||
        left_state >= HEALTH_THERMAL_RAW_UNRECOGNIZED ||
        right_state <= HEALTH_THERMAL_RAW_UNKNOWN ||
        right_state >= HEALTH_THERMAL_RAW_UNRECOGNIZED)
        return HEALTH_SOURCE_COMPARISON_UNKNOWN;
    health_source_comparison_t result = left_state == right_state
        ? HEALTH_SOURCE_COMPARISON_AGREE : HEALTH_SOURCE_COMPARISON_DISAGREE;
    if (result == HEALTH_SOURCE_COMPARISON_DISAGREE)
        snapshot->thermal_sources_disagree = 1;
    return result;
}

static health_resource_state_t classify_metadata(const health_observation_t *observation) {
    if (!observation) return HEALTH_RESOURCE_INVALID;
    if (observation->status == HEALTH_STATUS_UNAVAILABLE ||
        observation->status == HEALTH_STATUS_UNSUPPORTED) return HEALTH_RESOURCE_UNAVAILABLE;
    if (observation->status == HEALTH_STATUS_INVALID ||
        observation->status == HEALTH_STATUS_ERROR) return HEALTH_RESOURCE_INVALID;
    if (observation->freshness == HEALTH_FRESHNESS_STALE) return HEALTH_RESOURCE_STALE;
    if (observation->freshness != HEALTH_FRESHNESS_CURRENT ||
        !observation->physical_source_verified || !observation->value_valid)
        return HEALTH_RESOURCE_UNVERIFIED;
    return HEALTH_RESOURCE_AVAILABLE;
}

health_resource_state_t health_classify_battery(const health_snapshot_t *snapshot) {
    if (!health_snapshot_validate(snapshot)) return HEALTH_RESOURCE_INVALID;
    if (snapshot->battery_sources_disagree) return HEALTH_RESOURCE_WARNING;
    return classify_metadata(&snapshot->battery_percentage_observation);
}

health_resource_state_t health_classify_thermal(const health_snapshot_t *snapshot) {
    if (!health_snapshot_validate(snapshot)) return HEALTH_RESOURCE_INVALID;
    if (snapshot->thermal_sources_disagree) return HEALTH_RESOURCE_WARNING;
    health_resource_state_t metadata = classify_metadata(&snapshot->thermal_observation);
    if (metadata != HEALTH_RESOURCE_AVAILABLE) return metadata;
    if (snapshot->thermal_state == HEALTH_THERMAL_CRITICAL) return HEALTH_RESOURCE_CRITICAL;
    if (snapshot->thermal_state == HEALTH_THERMAL_ELEVATED) return HEALTH_RESOURCE_WARNING;
    if (snapshot->thermal_state == HEALTH_THERMAL_NOMINAL) return HEALTH_RESOURCE_AVAILABLE;
    return HEALTH_RESOURCE_UNVERIFIED;
}
