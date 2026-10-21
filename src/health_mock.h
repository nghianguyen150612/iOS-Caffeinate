#ifndef IOSCAFFEINATE_HEALTH_MOCK_H
#define IOSCAFFEINATE_HEALTH_MOCK_H

#include "health.h"

typedef struct {
    health_platform_sample_t platform;
    health_clock_sample_t clock;
    int platform_result;
    int clock_result;
} health_mock_t;

void health_mock_provider_init(health_provider_t *provider, health_mock_t *mock);

#endif
