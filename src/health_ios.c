/* Read-only, on-demand platform observation. Sensor APIs are isolated here. */
#define _DARWIN_C_SOURCE 1

#include "health.h"

#include <string.h>

#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
#include <mach/mach_time.h>
#endif

static void set_origin(health_platform_origin_t *origin, health_status_t status,
                       int detected, health_source_class_t source_class,
                       const char *source_name) {
    origin->status = status;
    origin->source_detected = detected;
    origin->source_class = source_class;
    origin->source_name = source_name;
}

static int platform_read(void *context, health_platform_sample_t *sample) {
    if (!sample) return -1;
    (void)context;
    memset(sample, 0, sizeof(*sample));
    sample->battery_percentage = -1;
    sample->charging_state = HEALTH_CHARGING_UNKNOWN;
    sample->thermal_raw_state = HEALTH_THERMAL_RAW_UNKNOWN;

#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    /* UIDevice battery monitoring is deliberately not enabled here. Enabling
     * it mutates process monitoring state, so battery and charging stay unknown. */
    set_origin(&sample->battery_percentage_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UIDevice.batteryLevel.not-enabled");
    set_origin(&sample->charging_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UIDevice.batteryState.not-enabled");
    /* Apple's iOS SDK documents that NSProcessInfo.thermalState returns
     * NOMINAL when thermal state is unknown or unsupported. That fallback
     * cannot satisfy our rule against converting missing data to NOMINAL. */
    set_origin(&sample->thermal_origin, HEALTH_STATUS_UNAVAILABLE, 0,
               HEALTH_SOURCE_UNKNOWN, "NSProcessInfo.thermalState.rejected-fallback");

    mach_timebase_info_data_t timebase;
    if (mach_timebase_info(&timebase) == KERN_SUCCESS && timebase.denom != 0) {
        long double seconds = ((long double)mach_continuous_time() *
                               (long double)timebase.numer) /
                              ((long double)timebase.denom * 1000000000.0L);
        if (seconds >= 0 && seconds <= (long double)UINT64_MAX) {
            sample->device_uptime_seconds = (uint64_t)seconds;
            set_origin(&sample->device_uptime_origin, HEALTH_STATUS_AVAILABLE, 1,
                       HEALTH_SOURCE_DEVICE_REPORTED, "mach_continuous_time");
        } else {
            set_origin(&sample->device_uptime_origin, HEALTH_STATUS_ERROR, 1,
                       HEALTH_SOURCE_DEVICE_REPORTED, "mach_continuous_time");
        }
    } else {
        set_origin(&sample->device_uptime_origin, HEALTH_STATUS_UNAVAILABLE, 1,
                   HEALTH_SOURCE_DEVICE_REPORTED, "mach_continuous_time");
    }
#elif defined(IOSCAFFEINATE_TEST_MOCK)
    set_origin(&sample->battery_percentage_origin, HEALTH_STATUS_UNAVAILABLE, 0,
               HEALTH_SOURCE_MOCK, "MOCK_NO_BATTERY_SENSOR");
    set_origin(&sample->charging_origin, HEALTH_STATUS_UNAVAILABLE, 0,
               HEALTH_SOURCE_MOCK, "MOCK_NO_CHARGING_SENSOR");
    set_origin(&sample->thermal_origin, HEALTH_STATUS_UNAVAILABLE, 0,
               HEALTH_SOURCE_MOCK, "MOCK_NO_THERMAL_SENSOR");
    set_origin(&sample->device_uptime_origin, HEALTH_STATUS_UNAVAILABLE, 0,
               HEALTH_SOURCE_MOCK, "MOCK_NO_DEVICE_UPTIME");
#else
    set_origin(&sample->battery_percentage_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UNSUPPORTED_PLATFORM");
    set_origin(&sample->charging_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UNSUPPORTED_PLATFORM");
    set_origin(&sample->thermal_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UNSUPPORTED_PLATFORM");
    set_origin(&sample->device_uptime_origin, HEALTH_STATUS_UNSUPPORTED, 0,
               HEALTH_SOURCE_UNKNOWN, "UNSUPPORTED_PLATFORM");
#endif
    return 0;
}

void health_default_provider(health_provider_t *provider) {
    if (!provider) return;
    provider->read_platform = platform_read;
    provider->platform_context = NULL;
    provider->read_clock = health_clock_read;
    provider->clock_context = NULL;
}

const char *health_platform_backend_name(void) {
#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    return "IOS12_READ_ONLY_PARTIAL_RUNTIME_UNVERIFIED";
#elif defined(IOSCAFFEINATE_TEST_MOCK)
    return "MOCK_NO_SENSOR_DATA";
#else
    return "UNSUPPORTED_PLATFORM";
#endif
}

void health_sources_write(FILE *out) {
    if (!out) return;
#if defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    fprintf(out,
            "platform=%s\n"
            "battery.api=UIDevice.batteryLevel\n"
            "battery.framework=UIKit.framework\n"
            "battery.ios_minimum=3.0\n"
            "battery.status=UNAVAILABLE\n"
            "battery.reason=reading requires per-process battery monitoring; enabling it is outside the read-only contract\n"
            "battery.runtime_verification=RUNTIME_UNVERIFIED\n"
            "charging.api=UIDevice.batteryState\n"
            "charging.framework=UIKit.framework\n"
            "charging.status=UNAVAILABLE\n"
            "charging.runtime_verification=RUNTIME_UNVERIFIED\n"
            "thermal.api=NSProcessInfo.thermalState\n"
            "thermal.framework=Foundation.framework\n"
            "thermal.ios_minimum=11.0\n"
            "thermal.status=UNAVAILABLE\n"
            "thermal.reason=the SDK defines NOMINAL as the fallback for unknown or unsupported thermal state\n"
            "thermal.runtime_verification=RUNTIME_UNVERIFIED\n"
            "uptime.api=mach_continuous_time\n"
            "uptime.ios_minimum=10.0\n"
            "uptime.status=RUNTIME_UNVERIFIED\n"
            "uptime.includes_sleep=yes\n"
            "power_source_api=UNAVAILABLE_ON_TARGET_BUILD\n"
            "iokit_sensor_enumeration=DISABLED\n",
            health_platform_backend_name());
#elif defined(IOSCAFFEINATE_TEST_MOCK)
    fprintf(out,
            "platform=%s\n"
            "battery.api=MOCK_NO_BATTERY_SENSOR\n"
            "battery.status=UNAVAILABLE\n"
            "charging.api=MOCK_NO_CHARGING_SENSOR\n"
            "charging.status=UNAVAILABLE\n"
            "thermal.api=MOCK_NO_THERMAL_SENSOR\n"
            "thermal.status=UNAVAILABLE\n"
            "uptime.api=MOCK_NO_DEVICE_UPTIME\n"
            "uptime.status=UNAVAILABLE\n"
            "physical_device_observation=no\n",
            health_platform_backend_name());
#else
    fprintf(out,
            "platform=%s\n"
            "battery.api=UNSUPPORTED\n"
            "battery.status=UNAVAILABLE\n"
            "charging.api=UNSUPPORTED\n"
            "charging.status=UNAVAILABLE\n"
            "thermal.api=UNSUPPORTED\n"
            "thermal.status=UNAVAILABLE\n"
            "uptime.api=UNSUPPORTED\n"
            "uptime.status=UNAVAILABLE\n",
            health_platform_backend_name());
#endif
}
