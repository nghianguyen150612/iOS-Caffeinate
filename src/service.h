#ifndef IOSCAFFEINATE_SERVICE_H
#define IOSCAFFEINATE_SERVICE_H

#include <stddef.h>
#include <stdio.h>
#include <sys/types.h>

#define IOSCAFFEINATE_SERVICE_LABEL "com.ioscaffeinate.daemon"
#define IOSCAFFEINATE_SERVICE_EXECUTABLE "/usr/local/bin/ios-caffeinated"
#define IOSCAFFEINATE_SERVICE_STAGED_PLIST \
    "/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist"
#define IOSCAFFEINATE_SERVICE_LIVE_PLIST \
    "/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist"
#define IOSCAFFEINATE_SERVICE_SOCKET "/var/run/ioscaffeinated.sock"

/* Exit values shared by the CLI and its operator documentation. */
enum {
    SERVICE_EXIT_OK = 0,
    SERVICE_EXIT_ERROR = 1,
    SERVICE_EXIT_USAGE = 2,
    SERVICE_EXIT_UNSUPPORTED = 3,
    SERVICE_EXIT_PRIVILEGE = 4,
    SERVICE_EXIT_INVALID_STATE = 5,
    SERVICE_EXIT_UNSAFE = 6
};

int service_command(int argc, char **argv, FILE *out, FILE *err);
int service_write_managed_plist(FILE *out);
int service_validate_managed_plist(const char *path, uid_t expected_owner,
                                   int *enabled, char *detail, size_t detail_cap);
int service_install_managed_plist(const char *path, uid_t expected_owner,
                                  char *detail, size_t detail_cap);

typedef struct {
    int privileged;
    /* package_valid/staged_valid: 0 missing, 1 exact valid, 2 inconsistent */
    int package_valid;
    int staged_valid;
    /* managed: 0 absent, 1 exact enabled, 2 exact disabled, 3 unsafe/unknown */
    int managed;
    /* registered: 0 absent, 1 present, 2 unknown */
    int registered;
    /* runtime: 0 stopped/absent, 1 running, 2 unknown */
    int runtime;
    /* socket: 0 absent, 1 present, 2 stale, 3 unsafe, 4 unknown */
    int socket;
    /* daemon_state: 0 IDLE, 1 ACTIVE, 2 other/unknown */
    int daemon_state;
    /* assertion: 0 NONE, 1 OWNED, 2 RELEASE_FAILED, 3 unknown */
    int assertion;
    /* release_pending: 0 no, 1 yes, 2 unknown */
    int release_pending;
    int invariant_ok;
    int enable_verified;
    int start_verified;
    int disable_verified;
    int shutdown_protocol_supported;
    int enable_combines_start;
    int combined_behavior_consent;
} service_policy_facts_t;

int service_policy_preflight(const char *action, const service_policy_facts_t *facts);

#ifdef IOSCAFFEINATE_SERVICE_TESTING
typedef int (*service_test_runner_fn)(void *context, const char *subcommand,
                                      char *output, size_t output_cap,
                                      int *exit_status);
void service_test_set_runner(service_test_runner_fn runner, void *context);
int service_test_preflight(const char *action, const service_policy_facts_t *facts);
#endif

#endif
