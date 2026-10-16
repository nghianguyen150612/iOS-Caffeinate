#ifndef IOSCAFFEINATE_POWER_H
#define IOSCAFFEINATE_POWER_H
#include <stddef.h>
#include <stdint.h>

/* Linux builds require explicit IOSCAFFEINATE_TEST_MOCK.
 * iOS backend availability and effectiveness are unverified. */
int power_init(char *error, size_t error_size);
int power_acquire(uint32_t *assertion_id, char *error, size_t error_size);
int power_release(uint32_t assertion_id, char *error, size_t error_size);
const char *power_backend_name(void);
const char *power_diagnostics(void);
void power_cleanup(void);
#endif
