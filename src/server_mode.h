#ifndef IOSCAFFEINATE_SERVER_MODE_H
#define IOSCAFFEINATE_SERVER_MODE_H

#include <stddef.h>

#define SERVER_MODE_CONFIG_DEFAULT "/var/lib/ioscaffeinate/server-mode.json"
#define SERVER_MODE_CONFIG_MAX 512
#define SERVER_MODE_CONFIG_VERSION 2
#define SERVER_MODE_MAX_SESSION_SECONDS 300

typedef enum {
    SERVER_CONFIG_MISSING = 0,
    SERVER_CONFIG_VALID,
    SERVER_CONFIG_INVALID,
    SERVER_CONFIG_UNSAFE,
    SERVER_CONFIG_UNSUPPORTED
} server_config_status_t;

typedef enum {
    SERVER_POLICY_DISABLED = 0,
    SERVER_POLICY_OBSERVE_ONLY,
    SERVER_POLICY_BOUNDED_SESSION
} server_policy_t;

typedef struct {
    server_config_status_t status;
    unsigned schema_version;
    server_policy_t policy;
    unsigned max_duration_seconds;
    int require_operator_confirmation;
    int allow_automatic_start;
    int allow_restart_resume;
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

#ifdef IOSCAFFEINATE_SERVER_MODE_TESTING
void server_mode_test_append_after_read(const char *path);
#endif

#endif
