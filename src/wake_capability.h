#ifndef IOSCAFFEINATE_WAKE_CAPABILITY_H
#define IOSCAFFEINATE_WAKE_CAPABILITY_H

#include <stdio.h>

/* A deterministic, side-effect-free summary of the compiled capability
 * boundary. This does not probe IOKit, acquire assertions, or inspect state. */
typedef struct {
    const char *platform;
    const char *backend;
    const char *platform_identity;
    const char *timed_awake;
    const char *timed_awake_backend;
    const char *scheduled_awake;
    const char *scheduled_awake_backend;
    const char *scheduled_wake;
    const char *scheduled_wake_validated;
    const char *hardware_validation;
    const char *runtime_wake_probe;
    const char *read_only_evidence;
    const char *wake_guarantee;
    const char *limitations;
} wake_capability_report_t;

void wake_capability_get(wake_capability_report_t *report);
int wake_capability_write(FILE *stream);

#endif
