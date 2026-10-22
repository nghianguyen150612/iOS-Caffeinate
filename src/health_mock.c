#include "health_mock.h"

#include <string.h>

static int mock_read(void *context, health_platform_sample_t *sample) {
    health_mock_t *mock = context;
    if (!mock || !sample) return -1;
    *sample = mock->platform;
    return mock->platform_result;
}

static int mock_read_clock(void *context, health_clock_sample_t *sample) {
    health_mock_t *mock = context;
    if (!mock || !sample) return -1;
    *sample = mock->clock;
    return mock->clock_result;
}

void health_mock_provider_init(health_provider_t *provider, health_mock_t *mock) {
    if (!provider) return;
    memset(provider, 0, sizeof(*provider));
    provider->read_platform = mock_read;
    provider->platform_context = mock;
    provider->read_clock = mock_read_clock;
    provider->clock_context = mock;
}
