#include "wake_capability.h"

#include <stddef.h>

void wake_capability_get(wake_capability_report_t *report) {
    if (!report) return;

#if defined(IOSCAFFEINATE_TEST_MOCK)
    report->platform = "linux";
    report->backend = "MOCK_NO_POWER_EFFECT";
#elif defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__)
    report->platform = "ios";
    report->backend = "IOKit_RUNTIME_UNVERIFIED";
#elif defined(__APPLE__)
    report->platform = "darwin";
    report->backend = "IOKit_RUNTIME_UNVERIFIED";
#else
    report->platform = "unknown";
    report->backend = "NONE";
#endif

    report->platform_identity = "compile_time_target";
    report->timed_awake = "implemented";
    report->timed_awake_backend = "unverified";
    report->scheduled_awake = "definitions_only";
    report->scheduled_awake_backend = "not_authorized";
    report->scheduled_wake = "unverified";
    report->scheduled_wake_validated = "no";
    report->hardware_validation = "pending";
    report->runtime_wake_probe = "unavailable";
    report->read_only_evidence = "none";
    report->wake_guarantee = "no";
    report->limitations =
        "schedule_executor_not_authorized,assertion_is_not_wake_alarm,missed_windows_not_replayed";
}

int wake_capability_write(FILE *stream) {
    if (!stream) return -1;

    wake_capability_report_t report;
    wake_capability_get(&report);
    if (fprintf(stream,
                "platform=%s\n"
                "backend=%s\n"
                "platform_identity=%s\n"
                "timed_awake=%s\n"
                "timed_awake_backend=%s\n"
                "scheduled_awake=%s\n"
                "scheduled_awake_backend=%s\n"
                "scheduled_wake=%s\n"
                "scheduled_wake_validated=%s\n"
                "hardware_validation=%s\n"
                "runtime_wake_probe=%s\n"
                "read_only_evidence=%s\n"
                "wake_guarantee=%s\n"
                "limitations=%s\n",
                report.platform, report.backend, report.platform_identity,
                report.timed_awake, report.timed_awake_backend,
                report.scheduled_awake, report.scheduled_awake_backend,
                report.scheduled_wake, report.scheduled_wake_validated,
                report.hardware_validation, report.runtime_wake_probe,
                report.read_only_evidence, report.wake_guarantee,
                report.limitations) < 0) {
        return -1;
    }
    return ferror(stream) ? -1 : 0;
}
