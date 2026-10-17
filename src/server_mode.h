#ifndef IOSCAFFEINATE_SERVER_MODE_H
#define IOSCAFFEINATE_SERVER_MODE_H

#include <stddef.h>

#define SERVER_MODE_CONFIG_DEFAULT "/var/lib/ioscaffeinate/server-mode.json"
#define SERVER_MODE_CONFIG_MAX 512

typedef enum {
    SERVER_CONFIG_MISSING = 0,
    SERVER_CONFIG_VALID,
    SERVER_CONFIG_INVALID,
    SERVER_CONFIG_UNSAFE
} server_config_status_t;

typedef enum {
    SERVER_POLICY_DISABLED = 0,
    SERVER_POLICY_OBSERVE_ONLY
} server_policy_t;

typedef struct {
    server_config_status_t status;
    server_policy_t policy;
    char detail[160];
} server_config_t;

/* This loader only reads. Missing, invalid, or unsafe input always maps to
 * DISABLED. The caller may supply a diagnostic path for offline inspection. */
int server_mode_config_load(const char *path, server_config_t *config);
const char *server_config_status_name(server_config_status_t status);
const char *server_policy_name(server_policy_t policy);
const char *server_mode_backend_name(void);

size_t server_mode_gate_count(void);
const char *server_mode_gate_name(size_t index);

#endif
