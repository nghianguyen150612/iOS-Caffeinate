/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L
#include "schedule.h"
#include "health.h"
#include "health_policy.h"
#include "service.h"
#include "server_mode.h"
#include "server_policy.h"
#include "wake_capability.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <sys/utsname.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define DEFAULT_SCHEDULE_STATE "/var/lib/ioscaffeinate/schedules.json"
#ifndef IOSCAFFEINATE_MANAGER_PATH
#define IOSCAFFEINATE_MANAGER_PATH "/usr/local/libexec/ioscaffeinate-manager"
#endif
#ifndef IOSCAFFEINATE_EVIDENCE_TOOL_PATH
#define IOSCAFFEINATE_EVIDENCE_TOOL_PATH "/usr/share/doc/ioscaffeinate/tools/p018_evidence.py"
#endif
#ifndef IOSCAFFEINATE_PYTHON_PATH
#define IOSCAFFEINATE_PYTHON_PATH "/usr/bin/python3"
#endif
#ifndef IOSCAFFEINATE_PACKAGE_VERSION
#define IOSCAFFEINATE_PACKAGE_VERSION "UNAVAILABLE"
#endif
#ifndef IOSCAFFEINATE_BUILD_SHA
#define IOSCAFFEINATE_BUILD_SHA "UNAVAILABLE"
#endif
#ifndef IOSCAFFEINATE_BUILD_KIND
#define IOSCAFFEINATE_BUILD_KIND "UNIDENTIFIED"
#endif
#ifndef IOSCAFFEINATE_RELEASE_CHANNEL
#define IOSCAFFEINATE_RELEASE_CHANNEL "UNKNOWN"
#endif

static int server_policy_explain(FILE *out, const char *socket_path,
                                 const char *config_path, int include_plan);
static int server_doctor(FILE *out, const char *socket_path,
                         const char *config_path, const char *schedule_path);
static int health_command(FILE *out, const char *command, const char *socket_path,
                          const char *trial_id, const char *condition_id,
                          int outside_quiet_interval);
static int schedule_diagnostics_command(int argc, char **argv,
                                        const char *socket_path,
                                        const char *schedule_path,
                                        const char *server_config_path,
                                        const char *recovery_path);

typedef enum {
    SERVER_DAEMON_UNAVAILABLE = 0,
    SERVER_DAEMON_COMPATIBLE,
    SERVER_DAEMON_INCOMPATIBLE,
    SERVER_DAEMON_ERROR
} server_daemon_result_t;

static void usage(void) {
    puts("iOS-Caffeinate — bounded power operations and read-only diagnostics\n"
         "\n"
         "Usage: ic [global options] <command> [arguments]\n"
         "\n"
         "Read-only diagnostics:\n"
         "  ic status | doctor [--json] | --version\n"
         "  ic wake status\n"
         "  ic schedule list|next|validate|doctor|conflicts|explain ...\n"
         "  ic server status|doctor|plan|policy ...\n"
         "  ic service status|doctor|plan|recovery status|recovery plan\n"
         "  ic health status|battery|thermal|doctor|sources\n"
         "  ic package status|verify|upgrade-check|rollback-check|uninstall-check ...\n"
         "  ic evidence status|inventory|validate|export ...\n"
         "\n"
         "Configuration changes:\n"
         "  ic schedule add|enable|disable|remove ...  (requires explicit arguments)\n"
         "  ic service enable|disable|start|stop|restart and recovery reset ...\n"
         "\n"
         "Bounded power and assertion operations:\n"
         "  ic probe  (brief assertion acquire/release check)\n"
         "  ic start --for <duration> | --until <ISO-8601>  (maximum 24 hours)\n"
         "  ic server trial start --for <duration>  (maximum 300 seconds)\n"
         "  ic stop\n"
         "\n"
         "Unavailable or unverified: unattended Server Mode execution, scheduled assertion\n"
         "execution, scheduled wake, automatic restart, and launchd activation semantics.\n"
         "Battery and thermal sources may be unavailable on this iOS build.\n"
         "\n"
         "Device acceptance is separate from package or diagnostic readiness. Run `ic help`\n"
         "for topics. Global options: --socket, --server-config, --schedule-state,\n"
         "--recovery-state. Alias: ic -> ios-caffeinate.");
}

static void report_cli_error(const char *code, const char *operation,
                             const char *reason, const char *changed,
                             const char *next_step) {
    fprintf(stderr,
            "error.code=%s\nerror.operation=%s\nerror.reason=%s\n"
            "changed=%s\ncleanup=not_applicable\nnext_safe_step=%s\n",
            code, operation, reason, changed, next_step);
}

static int help_topic(const char *topic) {
    if (!topic || !*topic || strcmp(topic, "help") == 0) {
        usage();
    } else if (strcmp(topic, "schedule") == 0) {
        puts("ic schedule — diagnostics are read-only and do not start the daemon.\n"
             "  list [--at ISO-8601] | next [--at ISO-8601] | validate\n"
             "  doctor [--at ISO-8601] | conflicts [--at ISO-8601]\n"
             "  explain <id> [--at ISO-8601]\n"
             "  add --at ISO-8601|--daily HH:MM|--weekly days --at HH:MM --for duration [--tz TZ]\n"
             "  enable|disable|remove <id> [--if-generation hex] [--dry-run]\n"
             "New definitions are capped at 300 seconds. Existing longer records are preserved.\n"
             "Execution remains unauthorized; scheduled wake is unverified.");
    } else if (strcmp(topic, "service") == 0) {
        puts("ic service — status, doctor, plan, and recovery status/plan are read-only.\n"
             "enable/disable/start/restart remain fail-closed while iOS 12 launchd mutation\n"
             "semantics are unverified. stop requires acknowledged cleanup. recovery reset\n"
             "records an operator review; it does not perform physical cleanup. See P013/P014.");
    } else if (strcmp(topic, "server") == 0) {
        puts("ic server — status/doctor/plan and policy show/validate/explain/plan are diagnostic.\n"
             "trial start/stop are explicit bounded assertion operations (maximum 300 seconds).\n"
             "Policy eligibility is not execution authorization. No unattended executor exists.");
    } else if (strcmp(topic, "package") == 0) {
        puts("ic package — status, verify, upgrade-check, rollback-check, and uninstall-check\n"
             "are read-only. Preflight never invokes dpkg installation/removal or maintainer\n"
             "scripts. READY_FOR_OPERATOR_REVIEW is not an installation authorization.");
    } else if (strcmp(topic, "evidence") == 0) {
        puts("ic evidence — status/inventory/validate are read-only.\n"
             "export --dry-run writes nothing; export --output <absolute-new-directory> is\n"
             "explicit and creates a privacy-filtered bundle. A valid export is not accepted\n"
             "hardware evidence. Additional files require --include-operator-file and are\n"
             "validated as UNKNOWN/UNREVIEWED. Review P009 provenance and privacy before sharing.");
    } else if (strcmp(topic, "health") == 0) {
        puts("ic health status/doctor/sources are on-demand diagnostics. Battery and thermal\n"
             "values may be UNAVAILABLE; no value is fabricated and no background polling occurs.");
    } else if (strcmp(topic, "power") == 0) {
        puts("Manual start holds accept 1 second through 24 hours. Server trials and new schedule\n"
             "definitions have a maximum of 300 seconds. Explicit start/trial commands can acquire\n"
             "an assertion; status, doctor, plans, and previews do not.");
    } else {
        fprintf(stderr, "error.code=INVALID_ARGUMENT\nerror.operation=help\n"
                        "error.reason=UNKNOWN_HELP_TOPIC\nchanged=no\ncleanup=not_applicable\n"
                        "next_safe_step=run_ic_help\n");
        return 2;
    }
    return 0;
}

static void version_report(void) {
    struct utsname platform;
    const char *system = uname(&platform) == 0 ? platform.sysname : "UNAVAILABLE";
    printf("version.schema_version=1\n"
           "cli.name=ios-caffeinate\n"
           "package.identifier=com.ioscaffeinate.cli\n"
           "package.version=%s\n"
           "source.commit=%s\n"
           "build.kind=%s\n"
           "release.channel=%s\n"
           "platform=%s\n"
           "schema.p009=1\n"
           "schema.p011=1\n"
           "schema.p012=1\n"
           "schema.p014=1\n"
           "schema.p015=2\n"
           "schema.p016=1\n"
           "schema.p017=1\n"
           "schema.p018=1\n",
           IOSCAFFEINATE_PACKAGE_VERSION, IOSCAFFEINATE_BUILD_SHA,
           IOSCAFFEINATE_BUILD_KIND, IOSCAFFEINATE_RELEASE_CHANNEL,
           system);
}

#define DIAGNOSTIC_CAPTURE_MAX (32U * 1024U)

typedef enum {
    DIAG_SERVICE,
    DIAG_SERVER,
    DIAG_POLICY,
    DIAG_HEALTH,
    DIAG_SCHEDULE
} diagnostic_kind_t;

typedef struct {
    const char *socket_path;
    const char *server_config_path;
    const char *schedule_path;
    const char *recovery_path;
} diagnostic_context_t;

static int diagnostic_child(diagnostic_kind_t kind,
                            const diagnostic_context_t *context) {
    if (kind == DIAG_SERVICE) {
        char *args[] = {(char *)"status", NULL};
        return service_command(1, args, stdout, stderr);
    }
    if (kind == DIAG_SERVER)
        return server_doctor(stdout, context->socket_path,
                             context->server_config_path, context->schedule_path);
    if (kind == DIAG_POLICY)
        return server_policy_explain(stdout, context->socket_path,
                                     context->server_config_path, 0);
    if (kind == DIAG_HEALTH)
        return health_command(stdout, "status", context->socket_path,
                              NULL, NULL, 0);
    char *args[] = {(char *)"doctor", NULL};
    return schedule_diagnostics_command(1, args, context->socket_path,
                                       context->schedule_path,
                                       context->server_config_path,
                                       context->recovery_path);
}

static int capture_child_output(pid_t child, int read_fd, char *output,
                                size_t output_cap, unsigned timeout_ms,
                                int *exit_code, int *timed_out) {
    if (!output || output_cap < 2) return -1;
    output[0] = '\0';
    size_t used = 0;
    int eof = 0;
    int status = 0;
    int child_done = 0;
    *timed_out = 0;
    struct timespec started = {0}, current = {0};
    if (clock_gettime(CLOCK_MONOTONIC, &started) != 0) {
        close(read_fd);
        (void)kill(child, SIGTERM);
        (void)waitpid(child, NULL, 0);
        return -1;
    }
    int flags = fcntl(read_fd, F_GETFL, 0);
    if (flags >= 0) (void)fcntl(read_fd, F_SETFL, flags | O_NONBLOCK);
    while (!eof || !child_done) {
        if (clock_gettime(CLOCK_MONOTONIC, &current) != 0) break;
        long long elapsed_ms = (long long)(current.tv_sec - started.tv_sec) * 1000LL +
            (long long)(current.tv_nsec - started.tv_nsec) / 1000000LL;
        if ((unsigned long long)elapsed_ms >= timeout_ms) {
            *timed_out = 1;
            (void)kill(child, SIGTERM);
            break;
        }
        struct pollfd pfd = {.fd = read_fd, .events = POLLIN | POLLHUP};
        int wait_ms = (int)(timeout_ms - (unsigned)elapsed_ms);
        if (wait_ms > 100) wait_ms = 100;
        int ready = poll(&pfd, 1, wait_ms);
        if (ready < 0 && errno != EINTR) break;
        if (ready > 0 && !eof) {
            for (;;) {
                char chunk[2048];
                ssize_t n = read(read_fd, chunk, sizeof(chunk));
                if (n < 0 && errno == EINTR) continue;
                if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
                if (n <= 0) { eof = 1; break; }
                size_t count = (size_t)n;
                if (used + count >= output_cap) {
                    size_t copy = output_cap - used - 1;
                    if (copy) memcpy(output + used, chunk, copy);
                    used += copy;
                } else {
                    memcpy(output + used, chunk, count);
                    used += count;
                }
                output[used] = '\0';
            }
        }
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) child_done = 1;
        else if (result < 0 && errno != EINTR) { child_done = 1; status = 0; }
    }
    if (!child_done) {
        if (!*timed_out) (void)kill(child, SIGTERM);
        for (unsigned i = 0; i < 20; ++i) {
            pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child) { child_done = 1; break; }
            struct timespec pause = {.tv_sec = 0, .tv_nsec = 50000000};
            (void)nanosleep(&pause, NULL);
        }
        if (!child_done) (void)waitpid(child, &status, 0);
    }
    close(read_fd);
    *exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 1;
    return 0;
}

static int capture_diagnostic(diagnostic_kind_t kind,
                              const diagnostic_context_t *context,
                              char *output, size_t output_cap,
                              unsigned timeout_ms, int *exit_code,
                              int *timed_out) {
    int descriptors[2];
    if (pipe(descriptors) != 0) return -1;
    pid_t child = fork();
    if (child < 0) {
        close(descriptors[0]); close(descriptors[1]);
        return -1;
    }
    if (child == 0) {
        close(descriptors[0]);
        if (dup2(descriptors[1], STDOUT_FILENO) < 0 ||
            dup2(descriptors[1], STDERR_FILENO) < 0) _exit(125);
        close(descriptors[1]);
        int result = diagnostic_child(kind, context);
        fflush(stdout); fflush(stderr);
        _exit(result < 0 ? 1 : result);
    }
    close(descriptors[1]);
    return capture_child_output(child, descriptors[0], output, output_cap,
                                timeout_ms, exit_code, timed_out);
}

static int capture_program(const char *program, char *const argv[],
                           char *output, size_t output_cap,
                           unsigned timeout_ms, int *exit_code,
                           int *timed_out) {
    int descriptors[2];
    if (pipe(descriptors) != 0) return -1;
    pid_t child = fork();
    if (child < 0) {
        close(descriptors[0]); close(descriptors[1]);
        return -1;
    }
    if (child == 0) {
        static const char missing[] = "error.code=NOT_INSTALLED\nerror.operation=diagnostic_helper\nerror.reason=REQUIRED_TOOL_UNAVAILABLE\nchanged=no\ncleanup=not_applicable\nnext_safe_step=install_the_declared_procursus_tool\n";
        close(descriptors[0]);
        if (dup2(descriptors[1], STDOUT_FILENO) < 0) _exit(125);
        close(descriptors[1]);
        execv(program, argv);
        size_t missing_length = sizeof(missing) - 1;
        const char *missing_cursor = missing;
        while (missing_length > 0) {
            ssize_t written = write(STDOUT_FILENO, missing_cursor, missing_length);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) break;
            missing_cursor += (size_t)written;
            missing_length -= (size_t)written;
        }
        _exit(127);
    }
    close(descriptors[1]);
    int result = capture_child_output(child, descriptors[0], output,
                                      output_cap, timeout_ms, exit_code,
                                      timed_out);
    return result;
}

static int output_value(const char *output, const char *key,
                        char *value, size_t value_cap) {
    if (!output || !key || !value || value_cap == 0) return -1;
    size_t key_length = strlen(key);
    int found = 0;
    const char *cursor = output;
    while (*cursor) {
        const char *end = strchr(cursor, '\n');
        if (!end) end = cursor + strlen(cursor);
        if ((size_t)(end - cursor) > key_length &&
            memcmp(cursor, key, key_length) == 0 && cursor[key_length] == '=') {
            size_t length = (size_t)(end - cursor) - key_length - 1;
            if (found || length >= value_cap) return -1;
            memcpy(value, cursor + key_length + 1, length);
            value[length] = '\0';
            found = 1;
        }
        cursor = *end ? end + 1 : end;
    }
    return found ? 0 : -1;
}

static void json_string(FILE *out, const char *value) {
    fputc('"', out);
    for (const unsigned char *p = (const unsigned char *)(value ? value : ""); *p; ++p) {
        if (*p == '"' || *p == '\\') { fputc('\\', out); fputc(*p, out); }
        else if (*p < 0x20) fprintf(out, "\\u%04x", (unsigned)*p);
        else fputc(*p, out);
    }
    fputc('"', out);
}

static const char *doctor_status_for(const char *value) {
    if (!value) return "UNKNOWN";
    if (strcmp(value, "INVALID") == 0 || strcmp(value, "ERROR") == 0 ||
        strcmp(value, "INCONSISTENT") == 0 || strcmp(value, "FAILED") == 0 ||
        strcmp(value, "UNSAFE") == 0 || strcmp(value, "CLEANUP_UNVERIFIED") == 0 ||
        strcmp(value, "RECOVERY_UNVERIFIED") == 0 || strcmp(value, "RESTART_BLOCKED") == 0 ||
        strcmp(value, "RELEASE_FAILED") == 0 || strcmp(value, "BLOCKED") == 0)
        return "UNSAFE";
    if (strcmp(value, "UNAVAILABLE") == 0 || strcmp(value, "UNKNOWN") == 0 ||
        strcmp(value, "UNKNOWN_RUNTIME_UNAVAILABLE") == 0 || strcmp(value, "NOT_INSTALLED") == 0 ||
        strcmp(value, "MISSING") == 0)
        return "UNAVAILABLE";
    if (strstr(value, "UNVERIFIED") || strstr(value, "PENDING") ||
        strstr(value, "NOT_AUTHORIZED") || strstr(value, "BLOCKED"))
        return "PENDING_VERIFICATION";
    if (strcmp(value, "AVAILABLE") == 0 || strcmp(value, "RESPONSIVE") == 0 ||
        strcmp(value, "VALID") == 0 || strcmp(value, "HEALTHY") == 0 ||
        strcmp(value, "NONE") == 0 || strcmp(value, "NOT_REGISTERED") == 0 ||
        strcmp(value, "PRESENT") == 0 || strcmp(value, "INSTALLED") == 0 ||
        strcmp(value, "VERIFIED") == 0 || strcmp(value, "PASS_READ_ONLY") == 0 ||
        strcmp(value, "NO") == 0 || strcmp(value, "no") == 0)
        return "HEALTHY";
    return "UNKNOWN";
}

typedef struct {
    const char *component;
    const char *status;
    const char *reason;
    const char *next;
} doctor_check_t;

static void doctor_add(doctor_check_t *checks, size_t *count,
                       const char *component, const char *status,
                       const char *reason, const char *next) {
    if (*count >= 16) return;
    checks[*count].component = component;
    checks[*count].status = status;
    checks[*count].reason = reason;
    checks[*count].next = next;
    (*count)++;
}

static void doctor_render(FILE *out, int as_json, const doctor_check_t *checks,
                          size_t count) {
    if (as_json) {
        fputs("{\"schema_version\":1,\"command\":\"doctor\",\"read_only\":true,\"changed\":\"no\",\"checks\":[", out);
        for (size_t i = 0; i < count; ++i) {
            if (i) fputc(',', out);
            fputs("{\"component\":", out); json_string(out, checks[i].component);
            fputs(",\"status\":", out); json_string(out, checks[i].status);
            fputs(",\"reason\":", out); json_string(out, checks[i].reason);
            fputs(",\"next_safe_step\":", out); json_string(out, checks[i].next);
            fputc('}', out);
        }
        fputs("]}\n", out);
        return;
    }
    fputs("doctor.schema_version=1\ndoctor.read_only=yes\n", out);
    for (size_t i = 0; i < count; ++i) {
        fprintf(out, "check.%s.status=%s\ncheck.%s.reason=%s\n"
                     "check.%s.next_safe_step=%s\n",
                checks[i].component, checks[i].status,
                checks[i].component, checks[i].reason,
                checks[i].component, checks[i].next);
    }
    fputs("doctor.changed=no\nhardware_acceptance=PENDING\n"
          "unattended_operation_authorized=no\n", out);
}

static int doctor_command(int argc, char **argv, const diagnostic_context_t *context) {
    int as_json = 0;
    if (argc > 1 || (argc == 1 && strcmp(argv[0], "--json") != 0)) {
        fprintf(stderr, "error.code=INVALID_ARGUMENT\nerror.operation=doctor\n"
                        "error.reason=EXPECTED_OPTIONAL_JSON_FORMAT\nchanged=no\ncleanup=not_applicable\n"
                        "next_safe_step=run_ic_help\n");
        return 2;
    }
    if (argc == 1) as_json = 1;
    doctor_check_t checks[16];
    size_t count = 0;
    struct utsname platform;
    const char *platform_status = uname(&platform) == 0 && strcmp(platform.sysname, "Darwin") == 0
        ? "PENDING_VERIFICATION" : "UNKNOWN";
    doctor_add(checks, &count, "platform", platform_status,
               "target identity is not independently verified by this query",
               "review_the_target_platform_and_hardware_runbook");

    char service[DIAGNOSTIC_CAPTURE_MAX] = {0};
    char server[DIAGNOSTIC_CAPTURE_MAX] = {0};
    char policy[DIAGNOSTIC_CAPTURE_MAX] = {0};
    char health[DIAGNOSTIC_CAPTURE_MAX] = {0};
    char schedule[DIAGNOSTIC_CAPTURE_MAX] = {0};
    int code = 1, timeout = 0;
    if (capture_diagnostic(DIAG_SERVICE, context, service, sizeof(service),
                          2500, &code, &timeout) != 0 || timeout) service[0] = '\0';
    char value[256];
    if (output_value(service, "package.installation", value, sizeof(value)) == 0) {
        const char *state = strcmp(value, "INSTALLED") == 0 ? "PRESENT" :
            strcmp(value, "MISSING") == 0 ? "NOT_INSTALLED" : value;
        doctor_add(checks, &count, "installed_package", doctor_status_for(state),
                   "installed package identity is reported independently of runtime state",
                   "run_ic_package_status");
    } else {
        doctor_add(checks, &count, "installed_package", "UNKNOWN",
                   "package metadata could not be read from the service snapshot",
                   "run_ic_package_status");
    }
    struct stat st;
    const char *binary_state = stat("/usr/local/bin/ios-caffeinate", &st) == 0 && S_ISREG(st.st_mode)
        ? "PRESENT" : "NOT_INSTALLED";
    struct stat daemon_st, alias_st;
    int daemon_present = stat("/usr/local/bin/ios-caffeinated", &daemon_st) == 0 && S_ISREG(daemon_st.st_mode);
    int alias_present = lstat("/usr/local/bin/ic", &alias_st) == 0 && S_ISLNK(alias_st.st_mode);
    doctor_add(checks, &count, "installed_binaries", doctor_status_for(
                   strcmp(binary_state, "PRESENT") == 0 && daemon_present && alias_present ? "PRESENT" : "NOT_INSTALLED"),
               "CLI, daemon, and alias paths are checked without executing or changing them",
               "run_ic_package_verify");
    const char *ipc = output_value(service, "ipc.availability", value, sizeof(value)) == 0
        ? doctor_status_for(value) : "UNKNOWN";
    doctor_add(checks, &count, "daemon_ipc", ipc,
               "daemon IPC is queried read-only; absence does not start the daemon",
               "inspect_ic_service_status_without_starting_the_daemon");
    const char *assertion = output_value(service, "assertion.state", value, sizeof(value)) == 0
        ? doctor_status_for(value) : "UNKNOWN";
    doctor_add(checks, &count, "assertion_ownership", assertion,
               "ownership is reported only when the daemon supplies an observation",
               "inspect_ic_service_recovery_status_and_physical_cleanup");
    const char *recovery = output_value(service, "recovery.state", value, sizeof(value)) == 0
        ? doctor_status_for(value) : "UNKNOWN";
    doctor_add(checks, &count, "p014_recovery", recovery,
               "recovery state is not reset or repaired by doctor",
               "inspect_ic_service_recovery_status_and_complete_attended_cleanup_review");
    doctor_add(checks, &count, "p013_launchd", service[0] ? "PENDING_VERIFICATION" : "UNKNOWN",
               "registration observation does not verify iOS 12 mutation semantics",
               "review_P013_launchd_compatibility_without_running_mutation_commands");

    if (capture_diagnostic(DIAG_SERVER, context, server, sizeof(server),
                          2500, &code, &timeout) != 0 || timeout) server[0] = '\0';
    if (capture_diagnostic(DIAG_POLICY, context, policy, sizeof(policy),
                          2500, &code, &timeout) != 0 || timeout) policy[0] = '\0';
    if (output_value(policy, "decision", value, sizeof(value)) == 0) {
        const char *state = strcmp(value, "OBSERVE_ONLY") == 0 || strcmp(value, "DISABLED") == 0
            ? "HEALTHY" : "PENDING_VERIFICATION";
        doctor_add(checks, &count, "p015_server_policy", state,
                   "policy decision is diagnostic and grants no execution authorization",
                   "run_ic_server_policy_explain_and_follow_its_next_safe_step");
    } else {
        doctor_add(checks, &count, "p015_server_policy", "UNKNOWN",
                   "policy inputs could not be fully observed",
                   "run_ic_server_policy_explain");
    }
    if (capture_diagnostic(DIAG_HEALTH, context, health, sizeof(health),
                          2500, &code, &timeout) != 0 || timeout) health[0] = '\0';
    doctor_add(checks, &count, "p016_telemetry",
               strstr(health, "battery.percentage=UNAVAILABLE") ||
               strstr(health, "thermal.state=UNKNOWN") ? "UNAVAILABLE" :
               health[0] ? "UNKNOWN" : "UNAVAILABLE",
               "battery or thermal sources may be unavailable on this platform",
               "run_ic_health_sources_and_report_unavailable_values_as_unknown");
    if (capture_diagnostic(DIAG_SCHEDULE, context, schedule, sizeof(schedule),
                          2500, &code, &timeout) != 0 || timeout) schedule[0] = '\0';
    const char *storage = output_value(schedule, "schedule.storage", value, sizeof(value)) == 0
        ? doctor_status_for(value) : "UNKNOWN";
    doctor_add(checks, &count, "p017_scheduling", storage,
               "schedule execution is not authorized and previews do not imply wake",
               "run_ic_schedule_doctor_and_use_preview_commands_only");
    doctor_add(checks, &count, "schedule_executor", schedule[0] ? "UNSUPPORTED" : "UNKNOWN",
               "P017 intentionally has no unattended schedule executor",
               "do_not_enable_unattended_schedule_execution");

    int manager_code = 127;
    int manager_timeout = 0;
    char *const manager_args[] = {(char *)IOSCAFFEINATE_MANAGER_PATH, (char *)"status", NULL};
    if (capture_program(IOSCAFFEINATE_MANAGER_PATH, manager_args, server,
                        sizeof(server), 3000, &manager_code, &manager_timeout) != 0 || manager_timeout)
        server[0] = '\0';
    const char *manager_state = manager_timeout ? "UNKNOWN" : manager_code == 0 ? "HEALTHY" :
        manager_code == 127 ? "UNAVAILABLE" : "FAILED";
    doctor_add(checks, &count, "p011_package_integrity", manager_state,
               manager_code == 0 ? "read-only package manager checks completed" :
                   "package manager checks are incomplete or unavailable",
               "run_ic_package_status_and_ic_package_verify");
    const char *signature_status = "UNKNOWN";
    if (manager_timeout) signature_status = "UNKNOWN";
    else if (output_value(server, "signing_state", value, sizeof(value)) == 0) {
        if (strstr(value, "SIGNATURE_PRESENT")) signature_status = "PENDING_VERIFICATION";
        else if (strstr(value, "UNSIGNED")) signature_status = "UNVERIFIED";
    } else if (manager_code == 127) signature_status = "UNAVAILABLE";
    doctor_add(checks, &count, "signature_metadata", signature_status,
               "signature metadata does not establish exact signer provenance or iOS acceptance",
               "run_ic_package_verify_and_review_the_P010_signer_manifest");
    int evidence_code = 127, evidence_timeout = 0;
    char *const evidence_args[] = {(char *)IOSCAFFEINATE_PYTHON_PATH,
        (char *)IOSCAFFEINATE_EVIDENCE_TOOL_PATH, (char *)"status", (char *)"--json", NULL};
    if (capture_program(IOSCAFFEINATE_PYTHON_PATH, evidence_args, health,
                        sizeof(health), 3000, &evidence_code, &evidence_timeout) != 0 || evidence_timeout)
        health[0] = '\0';
    doctor_add(checks, &count, "p009_evidence", evidence_code == 0 ? "PENDING_VERIFICATION" :
                   evidence_code == 127 ? "UNAVAILABLE" : "UNKNOWN",
               "parsing or export consistency does not establish physical provenance or acceptance",
               "run_ic_evidence_inventory_and_follow_P009_review_requirements");
    doctor_add(checks, &count, "hardware_acceptance", "PENDING_VERIFICATION",
               "cloud diagnostics cannot establish physical iPad acceptance",
               "complete_the_attended_device_runbook_after_P011_and_P013_P014_gates");
    doctor_render(stdout, as_json, checks, count);
    return ferror(stdout) ? 1 : 0;
}

static int package_status_json(const char *command) {
    char output[DIAGNOSTIC_CAPTURE_MAX] = {0};
    int code = 127, timeout = 0;
    char *const args[] = {(char *)IOSCAFFEINATE_MANAGER_PATH, (char *)command, NULL};
    if (capture_program(IOSCAFFEINATE_MANAGER_PATH, args, output, sizeof(output),
                        5000, &code, &timeout) != 0) code = 127;
    if (timeout) {
        output[0] = '\0';
        code = 1;
    }
    char package_metadata[256], architecture[64], signing_state[64];
    int have_metadata = output_value(output, "package_metadata", package_metadata,
                                     sizeof(package_metadata)) == 0;
    int have_arch = output_value(output, "dpkg_architecture", architecture,
                                 sizeof(architecture)) == 0;
    int have_signing = output_value(output, "signing_state", signing_state,
                                   sizeof(signing_state)) == 0;
    fputs("{\"schema_version\":1,\"command\":", stdout);
    json_string(stdout, strcmp(command, "verify") == 0 ? "package.verify" : "package.status");
    fputs(",\"package_identifier\":\"com.ioscaffeinate.cli\",\"status\":", stdout);
    json_string(stdout, timeout ? "UNKNOWN" : code == 0 ? "VERIFIED" :
                code == 127 ? "UNAVAILABLE" : "INCOMPLETE");
    printf(",\"manager_exit_code\":%d,\"timed_out\":%s,\"error_code\":",
           code, timeout ? "true" : "false");
    if (timeout) json_string(stdout, "IO_ERROR");
    else if (code == 127) json_string(stdout, "NOT_INSTALLED");
    else if (code != 0) json_string(stdout, "INTEGRITY_FAILED");
    else fputs("null", stdout);
    fputs(",\"error_reason\":", stdout);
    if (timeout) json_string(stdout, "BOUNDED_QUERY_TIMEOUT");
    else if (code == 127) json_string(stdout, "MANAGER_NOT_INSTALLED");
    else if (code != 0) json_string(stdout, "PACKAGE_MANAGER_CHECK_FAILED");
    else fputs("null", stdout);
    fputs(",\"next_safe_step\":", stdout);
    if (timeout) json_string(stdout, "retry_the_read_only_query_after_inspection");
    else if (code == 127) json_string(stdout, "verify_the_package_installation");
    else if (code != 0) json_string(stdout, "inspect_package_manager_output_and_verify_integrity");
    else fputs("null", stdout);
    fputs(",\"manager_output\":", stdout);
    json_string(stdout, output);
    fputs(",\"package_metadata\":", stdout);
    if (have_metadata) json_string(stdout, package_metadata); else fputs("null", stdout);
    fputs(",\"architecture\":", stdout);
    if (have_arch) json_string(stdout, architecture); else fputs("null", stdout);
    fputs(",\"signing_state\":", stdout);
    if (have_signing) json_string(stdout, signing_state); else fputs("null", stdout);
    fputs(",\"hardware_acceptance\":\"NOT_ESTABLISHED\",\"changed\":\"no\",\"cleanup\":\"not_applicable\"}\n", stdout);
    return ferror(stdout) ? 1 : code;
}

static int package_command(int argc, char **argv) {
    if (argc < 1) {
        report_cli_error("INVALID_ARGUMENT", "package", "MISSING_SUBCOMMAND", "no",
                         "run_ic_help_package");
        return 2;
    }
    const char *subcommand = argv[0];
    if (argc == 2 && strcmp(argv[1], "--json") == 0 &&
        (strcmp(subcommand, "status") == 0 || strcmp(subcommand, "verify") == 0))
        return package_status_json(subcommand);
    const char *manager_command = NULL;
    if (strcmp(subcommand, "status") == 0 || strcmp(subcommand, "verify") == 0 ||
        strcmp(subcommand, "doctor") == 0) manager_command = subcommand;
    else if (strcmp(subcommand, "upgrade-check") == 0) manager_command = "upgrade-check";
    else if (strcmp(subcommand, "rollback-check") == 0) manager_command = "rollback-check";
    else if (strcmp(subcommand, "uninstall-check") == 0) manager_command = "uninstall-check";
    else {
        report_cli_error("INVALID_ARGUMENT", "package", "UNKNOWN_SUBCOMMAND", "no",
                         "run_ic_help_package");
        return 2;
    }
    if ((strcmp(manager_command, "upgrade-check") == 0 ||
         strcmp(manager_command, "rollback-check") == 0) && argc < 2) {
        report_cli_error("INVALID_ARGUMENT", "package_preflight", "MISSING_ARTIFACT_PATH", "no",
                         "provide_an_absolute_package_artifact_path");
        return 2;
    }
    if (strcmp(manager_command, "upgrade-check") == 0 && argc != 2 && argc != 4) {
        report_cli_error("INVALID_ARGUMENT", "package_upgrade_check", "UNEXPECTED_ARGUMENTS", "no",
                         "run_ic_help_package");
        return 2;
    }
    if (strcmp(manager_command, "upgrade-check") == 0 && argc == 4 &&
        strcmp(argv[2], "--rollback-artifact") != 0) {
        report_cli_error("INVALID_ARGUMENT", "package_upgrade_check", "UNKNOWN_OPTION", "no",
                         "run_ic_help_package");
        return 2;
    }
    if (strcmp(manager_command, "rollback-check") == 0 && argc != 2) {
        report_cli_error("INVALID_ARGUMENT", "package_rollback_check", "UNEXPECTED_ARGUMENTS", "no",
                         "run_ic_help_package");
        return 2;
    }
    if ((strcmp(manager_command, "status") == 0 || strcmp(manager_command, "verify") == 0 ||
         strcmp(manager_command, "doctor") == 0 || strcmp(manager_command, "uninstall-check") == 0) && argc != 1)
    {
        report_cli_error("INVALID_ARGUMENT", "package", "UNEXPECTED_ARGUMENTS", "no",
                         "run_ic_help_package");
        return 2;
    }
    if ((strcmp(manager_command, "upgrade-check") == 0 || strcmp(manager_command, "rollback-check") == 0) &&
        (argv[1][0] != '/' || strstr(argv[1], "\n") || strstr(argv[1], "\r") ||
         (argc == 4 && (argv[3][0] != '/' || strstr(argv[3], "\n") || strstr(argv[3], "\r"))))) {
        fprintf(stderr, "error.code=INVALID_ARGUMENT\nerror.operation=package_preflight\n"
                        "error.reason=PACKAGE_PATH_MUST_BE_ABSOLUTE\nchanged=no\ncleanup=not_applicable\n"
                        "next_safe_step=use_an_absolute_artifact_path\n");
        return 2;
    }
    char *manager_argv[7] = {(char *)IOSCAFFEINATE_MANAGER_PATH,
                             (char *)manager_command, NULL, NULL, NULL, NULL, NULL};
    if (argc >= 2) manager_argv[2] = argv[1];
    if (argc == 4) {
        manager_argv[3] = argv[2];
        manager_argv[4] = argv[3];
    }
    char output[DIAGNOSTIC_CAPTURE_MAX] = {0};
    int code = 127, timed_out = 0;
    if (capture_program(IOSCAFFEINATE_MANAGER_PATH, manager_argv, output,
                        sizeof(output), 12000, &code, &timed_out) != 0) code = 127;
    if (timed_out) {
        report_cli_error("IO_ERROR", "package_manager", "BOUNDED_READ_ONLY_QUERY_TIMEOUT",
                         "no", "retry_the_read_only_query_after_inspection");
        return 1;
    }
    if (output[0]) fputs(output, stdout);
    if (code == 127 && !strstr(output, "error.code=NOT_INSTALLED"))
        fprintf(stderr, "error.code=NOT_INSTALLED\nerror.operation=package_manager\n"
                        "error.reason=MANAGER_NOT_INSTALLED\nchanged=no\ncleanup=not_applicable\n"
                        "next_safe_step=verify_the_package_installation\n");
    return code;
}

static int evidence_command(int argc, char **argv) {
    if (argc < 1) {
        report_cli_error("INVALID_ARGUMENT", "evidence", "MISSING_SUBCOMMAND", "no",
                         "run_ic_help_evidence");
        return 2;
    }
    const char *subcommand = argv[0];
    if (strcmp(subcommand, "status") != 0 && strcmp(subcommand, "inventory") != 0 &&
        strcmp(subcommand, "validate") != 0 && strcmp(subcommand, "export") != 0) {
        report_cli_error("INVALID_ARGUMENT", "evidence", "UNKNOWN_SUBCOMMAND", "no",
                         "run_ic_help_evidence");
        return 2;
    }
    char *tool_argv[12];
    size_t used = 0;
    tool_argv[used++] = (char *)IOSCAFFEINATE_PYTHON_PATH;
    tool_argv[used++] = (char *)IOSCAFFEINATE_EVIDENCE_TOOL_PATH;
    tool_argv[used++] = (char *)subcommand;
    for (int i = 1; i < argc; ++i) {
        if (used + 1 >= sizeof(tool_argv) / sizeof(tool_argv[0])) return 2;
        tool_argv[used++] = argv[i];
    }
    tool_argv[used] = NULL;
    char output[DIAGNOSTIC_CAPTURE_MAX] = {0};
    int code = 127, timeout = 0;
    unsigned timeout_ms = strcmp(subcommand, "export") == 0 ? 30000 : 8000;
    if (capture_program(IOSCAFFEINATE_PYTHON_PATH, tool_argv, output,
                        sizeof(output), timeout_ms, &code, &timeout) != 0) code = 127;
    if (timeout) {
        if (strcmp(subcommand, "export") == 0) {
            fprintf(stderr, "error.code=IO_ERROR\nerror.operation=evidence_export\n"
                            "error.reason=BOUNDED_EXPORT_TIMEOUT\nchanged=unknown\n"
                            "cleanup=unknown\n"
                            "next_safe_step=inspect_the_destination_for_partial_export_files\n");
        } else {
            report_cli_error("IO_ERROR", "evidence_diagnostic", "BOUNDED_QUERY_TIMEOUT",
                             "no", "retry_the_read_only_query_after_inspection");
        }
        return 1;
    }
    if (output[0]) fputs(output, stdout);
    if (code == 127 && !strstr(output, "error.code=NOT_INSTALLED"))
        fprintf(stderr, "error.code=UNSUPPORTED\nerror.operation=evidence\n"
                        "error.reason=PYTHON3_OR_EVIDENCE_TOOL_UNAVAILABLE\nchanged=no\ncleanup=not_applicable\n"
                        "next_safe_step=install_the_declared_Procursus_Python3_runtime\n");
    return code;
}

static int parse_duration(const char *str, unsigned *result) {
    if (!str || str[0] < '0' || str[0] > '9') return -1;
    errno = 0;
    char *end = NULL;
    unsigned long long n = strtoull(str, &end, 10);
    if (errno || end == str) return -1;
    unsigned long long multiplier = 1;
    if (strcmp(end, "s") == 0 || *end == '\0') multiplier = 1;
    else if (strcmp(end, "m") == 0) multiplier = 60;
    else if (strcmp(end, "h") == 0) multiplier = 3600;
    else return -1;
    if (n == 0 || n > 86400ULL / multiplier) return -1;
    *result = (unsigned)(n * multiplier);
    return 0;
}

static int parse_hhmm(const char *str, int *hour, int *min) {
    if (!str) return -1;
    int h, m;
    if (sscanf(str, "%2d:%2d", &h, &m) != 2) return -1;
    if (h < 0 || h > 23 || m < 0 || m > 59) return -1;
    if (strlen(str) != 5 || str[2] != ':') return -1;
    *hour = h;
    *min = m;
    return 0;
}

static server_daemon_result_t server_query_daemon(const char *path, char *reply,
                                                  size_t reply_cap, char *error,
                                                  size_t error_cap) {
    if (reply_cap == 0 || *path != '/' ||
        strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        snprintf(error, error_cap, "invalid socket path");
        return SERVER_DAEMON_ERROR;
    }
    (void)signal(SIGPIPE, SIG_IGN);
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        snprintf(error, error_cap, "socket creation failed");
        return SERVER_DAEMON_ERROR;
    }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        int saved = errno;
        close(fd);
        if (saved == ENOENT || saved == ECONNREFUSED) {
            snprintf(error, error_cap, "daemon socket unavailable");
            return SERVER_DAEMON_UNAVAILABLE;
        }
        snprintf(error, error_cap, "daemon connection failed");
        return SERVER_DAEMON_ERROR;
    }
    struct timeval timeout = {.tv_sec = 2, .tv_usec = 0};
    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0 ||
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
        close(fd);
        snprintf(error, error_cap, "cannot set diagnostic socket timeout");
        return SERVER_DAEMON_ERROR;
    }
    const char request[] = "SERVER STATUS\n";
    size_t remaining = sizeof(request) - 1;
    const char *cursor = request;
    while (remaining > 0) {
        ssize_t n = write(fd, cursor, remaining);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            close(fd);
            snprintf(error, error_cap, "diagnostic request failed");
            return SERVER_DAEMON_ERROR;
        }
        remaining -= (size_t)n;
        cursor += n;
    }

    size_t used = 0;
    while (used + 1 < reply_cap) {
        ssize_t n = recv(fd, reply + used, reply_cap - used - 1, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        size_t end = used + (size_t)n;
        for (size_t i = used; i < end; ++i) {
            unsigned char c = (unsigned char)reply[i];
            if (c == '\n') {
                if (i + 1 != end) {
                    close(fd);
                    snprintf(error, error_cap, "diagnostic reply has trailing data");
                    return SERVER_DAEMON_ERROR;
                }
                reply[i] = '\0';
                close(fd);
                if (strncmp(reply, "OK SERVER protocol=1 ", 21) == 0)
                    return SERVER_DAEMON_COMPATIBLE;
                if (strncmp(reply, "ERR unknown command", 19) == 0)
                    return SERVER_DAEMON_INCOMPATIBLE;
                snprintf(error, error_cap, "daemon returned an invalid diagnostic reply");
                return SERVER_DAEMON_ERROR;
            }
            if (c < 32 || c > 126) {
                close(fd);
                snprintf(error, error_cap, "diagnostic reply contains invalid bytes");
                return SERVER_DAEMON_ERROR;
            }
        }
        used = end;
    }
    close(fd);
    snprintf(error, error_cap, "daemon diagnostic reply was incomplete or oversized");
    return SERVER_DAEMON_ERROR;
}

static const char *server_query_name(server_daemon_result_t result) {
    switch (result) {
        case SERVER_DAEMON_UNAVAILABLE: return "UNAVAILABLE";
        case SERVER_DAEMON_COMPATIBLE: return "COMPATIBLE";
        case SERVER_DAEMON_INCOMPATIBLE: return "INCOMPATIBLE";
        case SERVER_DAEMON_ERROR: return "ERROR";
    }
    return "ERROR";
}

static const char *server_field(const char *reply, const char *key, const char *fallback) {
    static char values[32][64];
    static size_t next_value;
    char *value = values[next_value++ % (sizeof(values) / sizeof(values[0]))];
    char pattern[48];
    if (snprintf(pattern, sizeof(pattern), "%s=", key) >= (int)sizeof(pattern)) return fallback;
    const char *found = strstr(reply, pattern);
    if (!found || (found != reply && found[-1] != ' ')) return fallback;
    found += strlen(pattern);
    size_t n = 0;
    while (found[n] && found[n] != ' ' && n + 1 < sizeof(values[0])) n++;
    if (n == 0 || (found[n] != '\0' && found[n] != ' ')) return fallback;
    memcpy(value, found, n);
    value[n] = '\0';
    return value;
}

static const char *server_path_state(const char *path, int socket_expected) {
    static char states[4][32];
    static size_t next_state;
    char *state = states[next_state++ % 4];
    struct stat st;
    if (lstat(path, &st) != 0) {
        snprintf(state, sizeof(states[0]), "%s", errno == ENOENT ? "MISSING" : "ERROR");
    } else if (socket_expected) {
        snprintf(state, sizeof(states[0]), "%s",
                 S_ISSOCK(st.st_mode) && (st.st_mode & 0777) == 0600 && st.st_uid == geteuid()
                     ? "AVAILABLE" : "UNSAFE");
    } else {
        snprintf(state, sizeof(states[0]), "%s", S_ISREG(st.st_mode) ? "AVAILABLE" : "UNSAFE");
    }
    return state;
}

static int health_refresh_observation(health_observation_t *observation,
                                     const health_clock_sample_t *now) {
    if (!observation || !now || !observation->value_valid) return 0;
    return health_recheck_freshness(observation, now->utc_seconds, now->monotonic_ns,
                                    now->timebase_id, now->clock_uncertainty_ms,
                                    HEALTH_DEFAULT_FRESHNESS_SECONDS);
}

static void health_refresh_snapshot(health_snapshot_t *snapshot) {
    health_clock_sample_t now;
    if (!snapshot || health_clock_read(NULL, &now) != 0) return;
    (void)health_refresh_observation(&snapshot->battery_percentage_observation, &now);
    (void)health_refresh_observation(&snapshot->charging_observation, &now);
    (void)health_refresh_observation(&snapshot->thermal_observation, &now);
    (void)health_refresh_observation(&snapshot->device_uptime_observation, &now);
}

static const char *health_yes_no(int value) {
    return value ? "yes" : "no";
}

static void health_print_observation(FILE *out, const char *prefix,
                                     const health_observation_t *observation) {
    fprintf(out,
            "%s.status=%s\n"
            "%s.source=%s\n"
            "%s.source_class=%s\n"
            "%s.source_detected=%s\n"
            "%s.measurement_acquired=%s\n"
            "%s.value_valid=%s\n"
            "%s.observed_at_utc=%lld\n"
            "%s.freshness=%s\n"
            "%s.age_seconds=",
            prefix, health_status_name(observation->status),
            prefix, observation->source_name,
            prefix, health_source_class_name(observation->source_class),
            prefix, health_yes_no(observation->source_detected),
            prefix, health_yes_no(observation->measurement_acquired),
            prefix, health_yes_no(observation->value_valid),
            prefix, (long long)observation->observed_at_utc,
            prefix, health_freshness_name(observation->freshness), prefix);
    if (observation->age_available) fprintf(out, "%llu\n", (unsigned long long)observation->age_seconds);
    else fprintf(out, "UNAVAILABLE\n");
    fprintf(out,
            "%s.clock_uncertainty_ms=%llu\n"
            "%s.timebase=boot_scoped_monotonic\n"
            "%s.timebase_id=%s\n"
            "%s.confidence=%s\n"
            "%s.physical_source_verified=%s\n"
            "%s.safety_interpretation_reviewed=%s\n"
            "%s.p009_evidence_accepted=%s\n",
            prefix, (unsigned long long)observation->clock_uncertainty_ms,
            prefix, prefix, observation->timebase_id[0] ? observation->timebase_id : "UNKNOWN",
            prefix, health_confidence_name(observation->confidence),
            prefix, health_yes_no(observation->physical_source_verified),
            prefix, health_yes_no(observation->safety_interpretation_reviewed),
            prefix, health_yes_no(observation->p009_evidence_accepted));
}

static int health_decimal_field(const char *reply, const char *key,
                                unsigned long long maximum,
                                char *out, size_t out_cap) {
    const char *value = server_field(reply, key, NULL);
    if (!value || value[0] < '0' || value[0] > '9' || out_cap == 0) return 0;
    unsigned long long parsed = 0;
    for (size_t i = 0; value[i]; ++i) {
        if (value[i] < '0' || value[i] > '9') return 0;
        unsigned digit = (unsigned)(value[i] - '0');
        if ((unsigned long long)digit > maximum ||
            parsed > (maximum - digit) / 10ULL) return 0;
        parsed = parsed * 10ULL + digit;
    }
    if (parsed > maximum || snprintf(out, out_cap, "%llu", parsed) >= (int)out_cap) return 0;
    return 1;
}

static int health_daemon_status(FILE *out, const char *socket_path) {
    char reply[4096] = {0}, error[128] = {0};
    char uptime[32], remaining[32], acquire[32], release[32], errors[32], schedules[32];
    server_daemon_result_t result = server_query_daemon(socket_path, reply, sizeof(reply),
                                                        error, sizeof(error));
    if (result != SERVER_DAEMON_COMPATIBLE) {
        fprintf(out,
                "daemon.status=%s\n"
                "daemon.source=existing_SERVER_STATUS_IPC\n"
                "daemon.detail=%s\n"
                "daemon.state=UNAVAILABLE\n"
                "daemon.uptime_seconds=UNAVAILABLE\n"
                "daemon.assertion_owned=UNKNOWN\n"
                "daemon.remaining_hold_seconds=UNAVAILABLE\n"
                "daemon.last_acquisition_epoch=UNAVAILABLE\n"
                "daemon.last_release_epoch=UNAVAILABLE\n"
                "daemon.last_release_error=UNAVAILABLE\n"
                "daemon.recent_errors=UNAVAILABLE\n"
                "daemon.schedule_status=UNAVAILABLE\n"
                "daemon.recovery_status=UNAVAILABLE\n"
                "daemon.recovery_restart_eligibility=UNAVAILABLE\n"
                "daemon.supervisor=UNAVAILABLE\n"
                "daemon.read_only_query=yes\n",
                result == SERVER_DAEMON_UNAVAILABLE ? "UNAVAILABLE" : "ERROR",
                error[0] ? error : server_query_name(result));
        return result == SERVER_DAEMON_ERROR ? -1 : 0;
    }

    int owned = strcmp(server_field(reply, "assertion_owned", "unknown"), "1") == 0;
    const char *owned_value = strcmp(server_field(reply, "assertion_owned", "unknown"), "0") == 0
        ? "no" : owned ? "yes" : "UNKNOWN";
    const char *last_release_error = server_field(reply, "last_release_error", "UNKNOWN");
    fprintf(out,
            "daemon.status=AVAILABLE\n"
            "daemon.source=existing_SERVER_STATUS_IPC\n"
            "daemon.state=%s\n"
            "daemon.uptime_seconds=%s\n"
            "daemon.assertion_owned=%s\n"
            "daemon.remaining_hold_seconds=%s\n"
            "daemon.last_acquisition_epoch=%s\n"
            "daemon.last_release_epoch=%s\n"
            "daemon.last_release_error=%s\n"
            "daemon.recent_errors=%s\n"
            "daemon.schedule_count=%s\n"
            "daemon.schedule_active=%s\n"
            "daemon.recovery_status=%s\n"
            "daemon.recovery_cleanup=%s\n"
            "daemon.recovery_restart_eligibility=%s\n"
            "daemon.supervisor=%s\n"
            "daemon.state_invariant=%s\n"
            "daemon.read_only_query=yes\n",
            server_field(reply, "state", "UNKNOWN"),
            health_decimal_field(reply, "uptime_seconds", 315360000ULL, uptime, sizeof(uptime))
                ? uptime : "INVALID",
            owned_value,
            health_decimal_field(reply, "remaining_seconds", 86400ULL, remaining, sizeof(remaining))
                ? remaining : "INVALID",
            health_decimal_field(reply, "last_acquire_epoch", 4102444800ULL, acquire, sizeof(acquire))
                ? acquire : "UNAVAILABLE",
            health_decimal_field(reply, "last_release_epoch", 4102444800ULL, release, sizeof(release))
                ? release : "UNAVAILABLE",
            strcmp(last_release_error, "none") == 0 ? "none" : last_release_error,
            health_decimal_field(reply, "recent_errors", 100000000ULL, errors, sizeof(errors))
                ? errors : "INVALID",
            health_decimal_field(reply, "schedule_count", 100000ULL, schedules, sizeof(schedules))
                ? schedules : "INVALID",
            server_field(reply, "schedule_active", "UNKNOWN"),
            server_field(reply, "recovery_state", "UNKNOWN"),
            server_field(reply, "recovery_cleanup", "UNKNOWN"),
            server_field(reply, "recovery_restart_eligibility", "UNKNOWN"),
            server_field(reply, "recovery_supervisor", "UNKNOWN"),
            server_field(reply, "state_invariant", "UNKNOWN"));
    return ferror(out) ? -1 : 0;
}

static void health_print_battery(FILE *out, const health_snapshot_t *snapshot) {
    if (snapshot->battery_percentage_observation.value_valid)
        fprintf(out, "battery.percentage=%d\n", snapshot->battery_percentage);
    else
        fprintf(out, "battery.percentage=UNAVAILABLE\n");
    fprintf(out, "battery.charging=%s\n", health_charging_name(snapshot->charging_state));
    health_print_observation(out, "battery.percentage_observation",
                             &snapshot->battery_percentage_observation);
    health_print_observation(out, "battery.charging_observation",
                             &snapshot->charging_observation);
    fprintf(out, "battery.resource_data_status=%s\n",
            health_resource_state_name(health_classify_battery(snapshot)));
    fprintf(out, "battery.source_disagreement=%s\n",
            health_yes_no(snapshot->battery_sources_disagree));
    fprintf(out, "battery.health_metric=UNAVAILABLE\n");
}

static void health_print_thermal(FILE *out, const health_snapshot_t *snapshot) {
    fprintf(out, "thermal.state=%s\n", health_thermal_name(snapshot->thermal_state));
    fprintf(out, "thermal.raw_platform_state=%s\n",
            health_thermal_raw_name(snapshot->thermal_raw_state));
    health_print_observation(out, "thermal.observation", &snapshot->thermal_observation);
    fprintf(out, "thermal.resource_data_status=%s\n",
            health_resource_state_name(health_classify_thermal(snapshot)));
    fprintf(out, "thermal.source_disagreement=%s\n",
            health_yes_no(snapshot->thermal_sources_disagree));
    fprintf(out, "thermal.temperature_celsius=UNAVAILABLE\n");
}

static const char *health_observation_reason(const health_observation_t *observation,
                                            health_resource_state_t resource_state) {
    if (!observation) return "observation metadata missing";
    if (observation->status == HEALTH_STATUS_UNSUPPORTED)
        return "platform interface is unsupported or has ambiguous semantics";
    if (observation->status == HEALTH_STATUS_UNAVAILABLE)
        return observation->measurement_acquired
            ? "source responded without a usable value" : "no supported read-only value is available";
    if (observation->status == HEALTH_STATUS_INVALID)
        return "source value failed strict validation";
    if (observation->status == HEALTH_STATUS_ERROR)
        return "platform read failed";
    if (observation->freshness == HEALTH_FRESHNESS_STALE)
        return "observation exceeds the freshness limit";
    if (observation->freshness != HEALTH_FRESHNESS_CURRENT)
        return "clock or timebase cannot prove freshness";
    if (!observation->physical_source_verified)
        return "measurement source has not been verified on the reference device";
    if (resource_state == HEALTH_RESOURCE_CRITICAL)
        return "verified critical thermal observation blocks resource safety";
    if (resource_state == HEALTH_RESOURCE_WARNING)
        return "sources disagree or the resource category is elevated";
    return "current diagnostic measurement; safety review remains separate";
}

static int health_command(FILE *out, const char *command, const char *socket_path,
                          const char *trial_id, const char *condition_id,
                          int outside_quiet_interval) {
    health_snapshot_t snapshot;
    if (strcmp(command, "sources") == 0) {
        health_sources_write(out);
        return ferror(out) ? 1 : 0;
    }
    if (strcmp(command, "status") != 0 && strcmp(command, "battery") != 0 &&
        strcmp(command, "thermal") != 0 && strcmp(command, "doctor") != 0) return 2;
    if (health_collect(&snapshot) != 0) {
        fprintf(stderr, "health observation failed\n");
        return 1;
    }
    health_refresh_snapshot(&snapshot);
    if (!health_snapshot_validate(&snapshot)) {
        fprintf(stderr, "health observation validation failed\n");
        return 1;
    }
    if (strcmp(command, "battery") == 0) {
        health_print_battery(out, &snapshot);
        if (snapshot.battery_percentage_observation.status == HEALTH_STATUS_ERROR ||
            snapshot.charging_observation.status == HEALTH_STATUS_ERROR) return 1;
        return snapshot.battery_percentage_observation.value_valid ||
               snapshot.charging_observation.value_valid ? 0 : 3;
    }
    if (strcmp(command, "thermal") == 0) {
        health_print_thermal(out, &snapshot);
        if (snapshot.thermal_observation.status == HEALTH_STATUS_ERROR) return 1;
        return snapshot.thermal_observation.value_valid ? 0 : 3;
    }

    if (strcmp(command, "status") == 0) {
        fprintf(out, "health.schema_version=%u\n", snapshot.schema_version);
        fprintf(out, "health.platform=%s\n", health_platform_backend_name());
        if (snapshot.device_uptime_observation.value_valid)
            fprintf(out, "device.uptime_seconds=%llu\n",
                    (unsigned long long)snapshot.device_uptime_seconds);
        else
            fprintf(out, "device.uptime_seconds=UNAVAILABLE\n");
        health_print_observation(out, "device.uptime_observation",
                                 &snapshot.device_uptime_observation);
        health_print_battery(out, &snapshot);
        health_print_thermal(out, &snapshot);
        if (trial_id && condition_id && outside_quiet_interval) {
            fprintf(out,
                    "trial.association=EXPLICIT\n"
                    "trial.trial_id=%s\n"
                    "trial.condition_id=%s\n"
                    "trial.sampling_window=OPERATOR_ASSERTED_OUTSIDE_QUIET_INTERVAL\n"
                    "trial.record_written=no\n"
                    "trial.independent_host_observation=UNAVAILABLE\n",
                    trial_id, condition_id);
        }
        if (health_daemon_status(out, socket_path) != 0)
            fprintf(out, "daemon.query_result=ERROR\n");
        fprintf(out,
                "health.polling=ON_DEMAND\n"
                "health.record_persisted=no\n"
                "health.hardware_acceptance=NOT_ESTABLISHED\n");
        return ferror(out) ? 1 : 0;
    }

    fprintf(out, "doctor.platform=%s\n", health_platform_backend_name());
    health_print_battery(out, &snapshot);
    health_print_thermal(out, &snapshot);
    fprintf(out,
            "doctor.battery_interpretation=%s\n"
            "doctor.thermal_interpretation=%s\n"
            "doctor.battery_reason=%s\n"
            "doctor.thermal_reason=%s\n"
            "doctor.uptime_status=%s\n"
            "doctor.uptime_runtime_verification=RUNTIME_UNVERIFIED\n"
            "doctor.read_only=yes\n"
            "doctor.background_polling=no\n"
            "doctor.launchd_activation=no\n"
            "doctor.assertion_acquisition=no\n"
            "doctor.unattended_server_mode=no\n",
            health_status_name(snapshot.battery_percentage_observation.status),
            health_status_name(snapshot.thermal_observation.status),
            health_observation_reason(&snapshot.battery_percentage_observation,
                                      health_classify_battery(&snapshot)),
            health_observation_reason(&snapshot.thermal_observation,
                                      health_classify_thermal(&snapshot)),
            health_status_name(snapshot.device_uptime_observation.status));
    return ferror(out) ? 1 : 0;
}

static int health_trial_id_valid(const char *value) {
    if (!value) return 0;
    size_t length = strlen(value);
    if (length == 0 || length > 64 ||
        !((value[0] >= 'a' && value[0] <= 'z') ||
          (value[0] >= 'A' && value[0] <= 'Z') ||
          (value[0] >= '0' && value[0] <= '9'))) return 0;
    for (size_t i = 1; i < length; ++i) {
        char c = value[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return 0;
    }
    return 1;
}

static int load_server_config(const char *path, server_config_t *config) {
    if (server_mode_config_load(path, config) != 0) {
        fprintf(stderr, "server configuration diagnostics failed\n");
        return -1;
    }
    return 0;
}

static void policy_runtime_observe(const char *socket_path,
                                   server_policy_inputs_t *inputs) {
    char reply[4096] = {0}, error[128] = {0};
    server_daemon_result_t daemon = server_query_daemon(socket_path, reply, sizeof(reply),
                                                        error, sizeof(error));
    if (daemon != SERVER_DAEMON_COMPATIBLE) return;
    const char *state = server_field(reply, "state", "UNKNOWN");
    const char *owned = server_field(reply, "assertion_owned", "unknown");
    const char *release_error = server_field(reply, "last_release_error", "unknown");
    const char *release_pending = server_field(reply, "release_pending", "unknown");
    const char *backend = server_field(reply, "backend", server_mode_backend_name());
    if (strcmp(state, "BLOCKED") == 0) inputs->runtime_state = SERVER_RUNTIME_BLOCKED;
    else if (strcmp(state, "ACTIVE") == 0 || strcmp(owned, "1") == 0)
        inputs->runtime_state = SERVER_RUNTIME_ACTIVE;
    else if (strcmp(state, "IDLE") == 0) inputs->runtime_state = SERVER_RUNTIME_IDLE;
    else inputs->runtime_state = SERVER_RUNTIME_UNKNOWN;

    if (strcmp(release_pending, "yes") == 0 ||
        (strcmp(release_error, "none") != 0 && strcmp(release_error, "unknown") != 0))
        inputs->assertion_state = SERVER_ASSERTION_RELEASE_FAILED;
    else if (strcmp(owned, "1") == 0) inputs->assertion_state = SERVER_ASSERTION_OWNED;
    else if (strcmp(owned, "0") == 0) inputs->assertion_state = SERVER_ASSERTION_NONE;
    else inputs->assertion_state = SERVER_ASSERTION_UNKNOWN;

    inputs->runtime_source = strstr(backend, "MOCK") != NULL
        ? SERVER_EVIDENCE_SOURCE_MOCK : SERVER_EVIDENCE_SOURCE_DEVICE_REPORTED;
    inputs->runtime_freshness = SERVER_EVIDENCE_CURRENT;
    time_t now = time(NULL);
    inputs->runtime_observed_at_utc = now > 0 ? (int64_t)now : 0;
}

static void policy_recovery_observe(server_policy_inputs_t *inputs,
                                   char *detail, size_t detail_cap) {
    if (detail && detail_cap) detail[0] = '\0';
    inputs->recovery_store_status = recovery_store_load(RECOVERY_DEFAULT_PATH, geteuid(),
                                                        &inputs->recovery_record,
                                                        detail, detail_cap);
    inputs->recovery_record_available = inputs->recovery_store_status == RECOVERY_STORE_OK;
}

static const char *recovery_store_status_name(recovery_store_result_t value) {
    switch (value) {
        case RECOVERY_STORE_OK: return "OK";
        case RECOVERY_STORE_MISSING: return "MISSING";
        case RECOVERY_STORE_UNSAFE: return "UNSAFE";
        case RECOVERY_STORE_CORRUPT: return "CORRUPT";
        case RECOVERY_STORE_UNSUPPORTED: return "UNSUPPORTED";
        case RECOVERY_STORE_IO_ERROR: return "IO_ERROR";
    }
    return "UNKNOWN";
}

static const char *server_config_stored_name(server_config_status_t value) {
    switch (value) {
        case SERVER_CONFIG_MISSING: return "no";
        case SERVER_CONFIG_VALID:
        case SERVER_CONFIG_INVALID:
        case SERVER_CONFIG_UNSUPPORTED: return "yes";
        case SERVER_CONFIG_UNSAFE: return "unknown";
    }
    return "unknown";
}

static int server_policy_show(FILE *out, const char *config_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    char maximum[16];
    if (config.status == SERVER_CONFIG_VALID)
        snprintf(maximum, sizeof(maximum), "%u", config.max_duration_seconds);
    else
        snprintf(maximum, sizeof(maximum), "UNAVAILABLE");
    fprintf(out,
            "policy.version=%u\n"
            "policy.schema_version=%u\n"
            "policy.mode=%s\n"
            "policy.config_status=%s\n"
            "policy.config_stored=%s\n"
            "policy.config_valid=%s\n"
            "policy.config_source=%s\n"
            "policy.max_duration_seconds=%s\n"
            "policy.require_operator_confirmation=%s\n"
            "policy.allow_automatic_start=%s\n"
            "policy.allow_restart_resume=%s\n"
            "policy.detail=%s\n"
            "policy.apply_supported=no\n",
            SERVER_POLICY_ENGINE_VERSION, config.schema_version,
            server_policy_name(config.policy), server_config_status_name(config.status),
            server_config_stored_name(config.status),
            config.status == SERVER_CONFIG_VALID ? "yes" : "no", config_path,
            maximum,
            config.require_operator_confirmation ? "yes" : "no",
            config.allow_automatic_start ? "yes" : "no",
            config.allow_restart_resume ? "yes" : "no", config.detail);
    return ferror(out) ? -1 : 0;
}

static int server_policy_validate(FILE *out, const char *config_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    fprintf(out,
            "policy.config_status=%s\n"
            "policy.config_valid=%s\n"
            "policy.schema_version=%u\n"
            "policy.mode=%s\n"
            "policy.detail=%s\n",
            server_config_status_name(config.status),
            config.status == SERVER_CONFIG_VALID ? "yes" : "no",
            config.schema_version, server_policy_name(config.policy), config.detail);
    return config.status == SERVER_CONFIG_VALID && !ferror(out) ? 0 : 1;
}

static const char *policy_next_step(const server_policy_result_t *result) {
    if (result->decision == SERVER_DECISION_ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION)
        return "obtain separate operator authorization for a single bounded manual trial";
    if (result->decision == SERVER_DECISION_OBSERVE_ONLY)
        return "continue read-only diagnostics; this policy permits no assertion action";
    if (result->decision == SERVER_DECISION_DISABLED &&
        result->primary_reason == SERVER_REASON_POLICY_DISABLED)
        return "no action is required while the configured policy remains disabled";
    switch (result->primary_reason) {
        case SERVER_REASON_CONFIG_MISSING_DISABLED:
            return "review the version 2 schema and use an explicit operator-controlled configuration process";
        case SERVER_REASON_RECOVERY_MISSING:
        case SERVER_REASON_RECOVERY_UNSAFE:
        case SERVER_REASON_RECOVERY_CORRUPT:
        case SERVER_REASON_RECOVERY_UNSUPPORTED:
        case SERVER_REASON_RECOVERY_IO_ERROR:
        case SERVER_REASON_RECOVERY_PROCESS_NOT_CLEAN:
        case SERVER_REASON_RECOVERY_CLEANUP_UNVERIFIED:
        case SERVER_REASON_RECOVERY_RELEASE_FAILED:
        case SERVER_REASON_RECOVERY_RESTART_LIMIT:
        case SERVER_REASON_RECOVERY_RECORD_UNAVAILABLE:
        case SERVER_REASON_RECOVERY_OWNERSHIP_UNKNOWN:
        case SERVER_REASON_ASSERTION_RELEASE_FAILED:
        case SERVER_REASON_ASSERTION_OWNERSHIP_UNKNOWN:
            return "resolve the P014 recovery blocker and review recovery status";
        case SERVER_REASON_DAEMON_BLOCKED:
            return "resolve the daemon BLOCKED state through the P014 procedure";
        case SERVER_REASON_RUNTIME_UNKNOWN:
            return "obtain a current read-only daemon and assertion observation";
        case SERVER_REASON_ASSERTION_OWNED:
            return "resolve the current assertion before requesting a bounded session";
        case SERVER_REASON_SUPERVISOR_UNVERIFIED:
            return "complete P013/P014 lifecycle review; automatic recovery remains disabled";
        case SERVER_REASON_CONFIG_INVALID:
        case SERVER_REASON_CONFIG_UNSAFE:
        case SERVER_REASON_CONFIG_UNSUPPORTED:
            return "review the configuration schema and file safety without automatic repair";
        case SERVER_REASON_DURATION_ZERO:
        case SERVER_REASON_DURATION_EXCEEDS_CONFIG:
        case SERVER_REASON_DURATION_EXCEEDS_CEILING:
            return "select a positive duration within the configured and 300 second limits";
        case SERVER_REASON_UNATTENDED_NOT_SUPPORTED:
        case SERVER_REASON_SCHEDULE_EXECUTOR_NOT_AUTHORIZED:
        case SERVER_REASON_AUTOMATIC_RECOVERY_DISABLED:
            return "keep unattended start and automatic recovery disabled in P015";
        case SERVER_REASON_EVIDENCE_DENIED:
        case SERVER_REASON_EVIDENCE_UNSAFE:
            return "review the explicit hardware or resource safety result before any later request";
        default:
            return "complete P011 acceptance, P012 safety review, P013 compatibility, and physical recovery evidence";
    }
}

static int server_policy_explain(FILE *out, const char *socket_path,
                                 const char *config_path, int include_plan) {
    server_config_t config;
    server_policy_inputs_t inputs;
    server_policy_result_t result;
    health_snapshot_t telemetry;
    char battery_percentage[16];
    char recovery_detail[192] = {0};
    const server_policy_evidence_t *battery_evidence;
    const server_policy_evidence_t *thermal_evidence;
    if (load_server_config(config_path, &config) != 0) return -1;
    server_policy_inputs_init(&inputs);
    if (health_collect(&telemetry) == 0) {
        health_refresh_snapshot(&telemetry);
        health_apply_to_server_policy(&telemetry, &inputs);
    } else {
        health_snapshot_init(&telemetry);
    }
    inputs.operation = SERVER_OPERATION_MANUAL_BOUNDED_SESSION;
    inputs.requested_duration_seconds = config.max_duration_seconds;
    policy_recovery_observe(&inputs, recovery_detail, sizeof(recovery_detail));
    policy_runtime_observe(socket_path, &inputs);
    if (server_policy_evaluate(&config, &inputs, &result) != 0) return -1;
    battery_evidence = &inputs.gates[SERVER_POLICY_GATE_BATTERY_SAFETY];
    thermal_evidence = &inputs.gates[SERVER_POLICY_GATE_THERMAL_SAFETY];
    if (inputs.battery_percentage < 0)
        snprintf(battery_percentage, sizeof(battery_percentage), "UNAVAILABLE");
    else
        snprintf(battery_percentage, sizeof(battery_percentage), "%d", inputs.battery_percentage);

    fprintf(out,
            "policy.version=%u\n"
            "policy.mode=%s\n"
            "policy.config_stored=%s\n"
            "policy.config_status=%s\n"
            "policy.config_valid=%s\n"
            "policy.config_source=%s\n"
            "policy.requested=%s\n"
            "requested_operation=%s\n"
            "requested_duration_seconds=%llu\n"
            "policy.max_duration_seconds=%u\n"
            "decision=%s\n"
            "eligible=%s\n"
            "execution_authorized=%s\n"
            "operator_authorization=NOT_GRANTED\n"
            "operator_authorization_required=yes\n"
            "runtime_activated=%s\n"
            "runtime.observation=%s\n"
            "runtime.source=%s\n"
            "runtime.freshness=%s\n"
            "runtime.observed_at_utc=%lld\n"
            "recovery.journal=%s\n"
            "recovery.process=%s\n"
            "recovery.cleanup=%s\n"
            "recovery.last_exit=%s\n"
            "recovery.load_detail=%s\n"
            "recovery.restart_decision=%s\n"
            "recovery.restart_eligibility=no\n"
            "recovery.supervisor=%s\n"
            "recovery.automatic_runtime_enabled=no\n"
            "launchd.compatibility=UNVERIFIED\n"
            "battery.percentage=%s\n"
            "battery.charging=%s\n"
            "battery.source=%s\n"
            "battery.confidence=%s\n"
            "battery.observed_at_utc=%lld\n"
            "battery.freshness=%s\n"
            "thermal.status=%s\n"
            "thermal.source=%s\n"
            "thermal.confidence=%s\n"
            "thermal.observed_at_utc=%lld\n"
            "thermal.freshness=%s\n"
            "telemetry.battery.status=%s\n"
            "telemetry.battery.source=%s\n"
            "telemetry.battery.source_class=%s\n"
            "telemetry.battery.source_detected=%s\n"
            "telemetry.battery.measurement_acquired=%s\n"
            "telemetry.battery.valid=%s\n"
            "telemetry.battery.current=%s\n"
            "telemetry.battery.freshness=%s\n"
            "telemetry.battery.physical_source_verified=%s\n"
            "telemetry.battery.safety_reviewed=%s\n"
            "telemetry.battery.p009_accepted=%s\n"
            "telemetry.thermal.status=%s\n"
            "telemetry.thermal.source=%s\n"
            "telemetry.thermal.source_class=%s\n"
            "telemetry.thermal.source_detected=%s\n"
            "telemetry.thermal.measurement_acquired=%s\n"
            "telemetry.thermal.valid=%s\n"
            "telemetry.thermal.current=%s\n"
            "telemetry.thermal.state=%s\n"
            "telemetry.thermal.raw_state=%s\n"
            "telemetry.thermal.freshness=%s\n"
            "telemetry.thermal.physical_source_verified=%s\n"
            "telemetry.thermal.safety_reviewed=%s\n"
            "telemetry.thermal.p009_accepted=%s\n"
            "reason.primary=%s\n"
            "reason.count=%zu\n",
            result.policy_version, server_policy_name(config.policy),
            server_config_stored_name(config.status),
            server_config_status_name(config.status),
            config.status == SERVER_CONFIG_VALID ? "yes" : "no",
            config_path,
            config.status == SERVER_CONFIG_VALID && config.policy == SERVER_POLICY_BOUNDED_SESSION ? "yes" : "no",
            server_policy_operation_name(inputs.operation),
            (unsigned long long)inputs.requested_duration_seconds,
            result.maximum_duration_seconds, server_policy_decision_name(result.decision),
            result.eligible ? "yes" : "no", result.execution_authorized ? "yes" : "no",
            server_policy_activation_name(result.runtime_activation),
            server_policy_runtime_name(inputs.runtime_state),
            server_evidence_source_name(inputs.runtime_source),
            server_evidence_freshness_name(inputs.runtime_freshness),
            (long long)inputs.runtime_observed_at_utc,
            recovery_store_status_name(inputs.recovery_store_status),
            recovery_process_state_name(result.recovery_process),
            recovery_cleanup_state_name(result.recovery_cleanup),
            recovery_exit_class_name(result.recovery_last_exit),
            recovery_detail[0] ? recovery_detail : "not_available",
            inputs.recovery_restart_decision_available
                ? recovery_decision_name(result.automatic_recovery_decision) : "UNAVAILABLE",
            server_policy_supervisor_name(inputs.supervisor_state),
            battery_percentage,
            server_policy_charging_name(inputs.charging_status),
            server_evidence_source_name(battery_evidence->source),
            server_evidence_confidence_name(battery_evidence->confidence),
            (long long)battery_evidence->observed_at_utc,
            server_evidence_freshness_name(battery_evidence->freshness),
            server_policy_thermal_name(inputs.thermal_state),
            server_evidence_source_name(thermal_evidence->source),
            server_evidence_confidence_name(thermal_evidence->confidence),
            (long long)thermal_evidence->observed_at_utc,
            server_evidence_freshness_name(thermal_evidence->freshness),
            health_status_name(telemetry.battery_percentage_observation.status),
            telemetry.battery_percentage_observation.source_name,
            health_source_class_name(telemetry.battery_percentage_observation.source_class),
            health_yes_no(telemetry.battery_percentage_observation.source_detected),
            health_yes_no(telemetry.battery_percentage_observation.measurement_acquired),
            health_yes_no(telemetry.battery_percentage_observation.value_valid),
            health_yes_no(telemetry.battery_percentage_observation.value_valid &&
                          telemetry.battery_percentage_observation.freshness == HEALTH_FRESHNESS_CURRENT),
            health_freshness_name(telemetry.battery_percentage_observation.freshness),
            health_yes_no(telemetry.battery_percentage_observation.physical_source_verified),
            health_yes_no(telemetry.battery_percentage_observation.safety_interpretation_reviewed),
            health_yes_no(telemetry.battery_percentage_observation.p009_evidence_accepted),
            health_status_name(telemetry.thermal_observation.status),
            telemetry.thermal_observation.source_name,
            health_source_class_name(telemetry.thermal_observation.source_class),
            health_yes_no(telemetry.thermal_observation.source_detected),
            health_yes_no(telemetry.thermal_observation.measurement_acquired),
            health_yes_no(telemetry.thermal_observation.value_valid),
            health_yes_no(telemetry.thermal_observation.value_valid &&
                          telemetry.thermal_observation.freshness == HEALTH_FRESHNESS_CURRENT),
            health_thermal_name(telemetry.thermal_state),
            health_thermal_raw_name(telemetry.thermal_raw_state),
            health_freshness_name(telemetry.thermal_observation.freshness),
            health_yes_no(telemetry.thermal_observation.physical_source_verified),
            health_yes_no(telemetry.thermal_observation.safety_interpretation_reviewed),
            health_yes_no(telemetry.thermal_observation.p009_evidence_accepted),
            server_policy_reason_name(result.primary_reason), result.blocker_count);

    for (size_t i = SERVER_POLICY_GATE_P011_PACKAGE_ACCEPTANCE;
         i < SERVER_POLICY_GATE_COUNT; ++i) {
        server_policy_evidence_t *gate = &inputs.gates[i];
        fprintf(out, "evidence.%s.state=%s\n"
                     "evidence.%s.source=%s\n"
                     "evidence.%s.freshness=%s\n"
                     "evidence.%s.confidence=%s\n"
                     "evidence.%s.reviewed=%s\n"
                     "evidence.%s.observed_at_utc=%lld\n",
                server_policy_gate_name((server_policy_gate_t)i), server_evidence_state_name(gate->state),
                server_policy_gate_name((server_policy_gate_t)i), server_evidence_source_name(gate->source),
                server_policy_gate_name((server_policy_gate_t)i), server_evidence_freshness_name(gate->freshness),
                server_policy_gate_name((server_policy_gate_t)i), server_evidence_confidence_name(gate->confidence),
                server_policy_gate_name((server_policy_gate_t)i), gate->reviewed ? "yes" : "no",
                server_policy_gate_name((server_policy_gate_t)i), (long long)gate->observed_at_utc);
    }
    for (size_t i = 0; i < result.blocker_count; ++i) {
        const server_policy_blocker_t *blocker = &result.blockers[i];
        fprintf(out,
                "reason.%zu.code=%s\n"
                "reason.%zu.gate=%s\n"
                "reason.%zu.state=%s\n"
                "reason.%zu.source=%s\n"
                "reason.%zu.freshness=%s\n"
                "reason.%zu.required=%s\n",
                i + 1, server_policy_reason_name(blocker->reason),
                i + 1, server_policy_gate_name(blocker->gate),
                i + 1, server_evidence_state_name(blocker->state),
                i + 1, server_evidence_source_name(blocker->source),
                i + 1, server_evidence_freshness_name(blocker->freshness),
                i + 1, server_policy_reason_requirement(blocker->reason, blocker->gate));
    }
    fprintf(out,
            "session.executor=NOT_IMPLEMENTED\n"
            "automatic_start=no\n"
            "restart_resume=no\n"
            "runtime_action_performed=no\n"
            "next_safe_step=%s\n",
            policy_next_step(&result));
    if (include_plan) {
        fprintf(out, "plan.migration_writer=NOT_IMPLEMENTED\n"
                     "plan.configuration_write=no\n"
                     "plan.assertion_action=no\n"
                     "plan.launchd_action=no\n");
    }
    return ferror(out) ? -1 : 0;
}

static int server_policy_migrate_preview(FILE *out, const char *config_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    fprintf(out, "migration.mode=DRY_RUN\n"
                 "migration.write_performed=no\n"
                 "migration.writer_supported=no\n"
                 "migration.source_status=%s\n",
            server_config_status_name(config.status));
    if (config.status == SERVER_CONFIG_VALID && config.schema_version == 1) {
        fprintf(out,
                "migration.proposed_config={\"version\":2,\"policy\":\"%s\",\"session\":{\"max_duration_seconds\":300,\"require_operator_confirmation\":true,\"allow_automatic_start\":false,\"allow_restart_resume\":false}}\n"
                "migration.original_preserved=yes\n"
                "migration.session_activation=no\n",
                config.policy == SERVER_POLICY_OBSERVE_ONLY ? "observe_only" : "disabled");
    } else if (config.status == SERVER_CONFIG_VALID && config.schema_version == 2) {
        fprintf(out, "migration.result=already_version_2\n");
    } else if (config.status == SERVER_CONFIG_MISSING) {
        fprintf(out, "migration.result=no_source_configuration\n"
                     "migration.proposed_policy=disabled\n");
    } else {
        fprintf(out, "migration.result=blocked_source_not_valid\n"
                     "migration.proposed_config=none\n");
    }
    return ferror(out) ? -1 : 0;
}

static int server_policy_command(int argc, char **argv, const char *socket_path,
                                 const char *config_path) {
    if (argc == 1 && strcmp(argv[0], "show") == 0)
        return server_policy_show(stdout, config_path) == 0 ? 0 : 1;
    if (argc == 1 && strcmp(argv[0], "validate") == 0)
        return server_policy_validate(stdout, config_path);
    if (argc == 1 && strcmp(argv[0], "explain") == 0)
        return server_policy_explain(stdout, socket_path, config_path, 0) == 0 ? 0 : 1;
    if (argc == 1 && strcmp(argv[0], "plan") == 0)
        return server_policy_explain(stdout, socket_path, config_path, 1) == 0 ? 0 : 1;
    if (argc == 2 && strcmp(argv[0], "migrate") == 0 &&
        strcmp(argv[1], "--dry-run") == 0)
        return server_policy_migrate_preview(stdout, config_path) == 0 ? 0 : 1;
    usage();
    return 2;
}

static int server_status(FILE *out, const char *socket_path, const char *config_path,
                         const char *schedule_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    char reply[4096] = {0}, query_error[128] = {0};
    server_daemon_result_t daemon = server_query_daemon(socket_path, reply, sizeof(reply),
                                                        query_error, sizeof(query_error));
    int configured = config.status == SERVER_CONFIG_VALID &&
                     config.policy == SERVER_POLICY_OBSERVE_ONLY;
    int compatible = daemon == SERVER_DAEMON_COMPATIBLE;
    const char *state = config.status == SERVER_CONFIG_INVALID ||
                        config.status == SERVER_CONFIG_UNSAFE ||
                        config.status == SERVER_CONFIG_UNSUPPORTED
                            ? "BLOCKED"
                            : config.policy == SERVER_POLICY_BOUNDED_SESSION
                                ? "POLICY_STORED_INACTIVE"
                                : configured ? "OBSERVE_ONLY" : "DISABLED";

    fprintf(out,
            "configured_policy=%s\n"
            "server_mode_enabled=%s\n"
            "operating_state=%s\n"
            "configuration_status=%s\n"
            "configuration_source=%s\n"
            "configuration_detail=%s\n"
            "backend_identity=%s\n"
            "backend_verification=UNVERIFIED\n"
            "source_capability=IMPLEMENTED\n"
            "build_capability=%s\n"
            "device_runtime_capability=UNVERIFIED\n"
            "power_management_capability=UNVERIFIED\n"
            "network_reliability=UNVERIFIED\n"
            "os_power_state=UNVERIFIED\n"
            "prior_process_cleanup=UNVERIFIED\n"
            "daemon_availability=%s\n"
            "daemon_protocol_compatibility=%s\n",
            server_policy_name(config.policy), configured ? "yes" : "no", state,
            server_config_status_name(config.status), config_path ? config_path : SERVER_MODE_CONFIG_DEFAULT,
            config.detail, compatible ? server_field(reply, "backend", server_mode_backend_name())
                                      : server_mode_backend_name(),
            strcmp(server_mode_backend_name(), "MOCK_NO_POWER_EFFECT") == 0 ? "MOCK_ONLY" : "IOS_TARGET_UNVERIFIED",
            daemon == SERVER_DAEMON_COMPATIBLE || daemon == SERVER_DAEMON_INCOMPATIBLE
                ? "AVAILABLE" : daemon == SERVER_DAEMON_UNAVAILABLE ? "UNAVAILABLE" : "ERROR",
            server_query_name(daemon));

    if (compatible) {
        fprintf(out,
                "assertion_ownership=%s\n"
                "assertion_lifecycle=%s\n"
                "assertion_source=%s\n"
                "trial_state=%s\n"
                "state_invariant=%s\n"
                "daemon_uptime_seconds=%s\n"
                "last_acquisition_epoch=%s\n"
                "last_release_epoch=%s\n"
                "last_release_error=%s\n"
                "schedule_activity=%s\n"
                "daemon_recent_errors=%s\n"
                "daemon_report=%s\n",
                strcmp(server_field(reply, "assertion_owned", "0"), "1") == 0 ? "OWNED" : "NONE",
                server_field(reply, "state", "UNKNOWN"),
                server_field(reply, "source", "UNKNOWN"),
                server_field(reply, "trial_state", "UNKNOWN"),
                server_field(reply, "state_invariant", "UNKNOWN"),
                server_field(reply, "uptime_seconds", "UNKNOWN"),
                server_field(reply, "last_acquire_epoch", "UNAVAILABLE"),
                server_field(reply, "last_release_epoch", "UNAVAILABLE"),
                server_field(reply, "last_release_error", "none"),
                server_field(reply, "schedule_active", "UNKNOWN"),
                server_field(reply, "recent_errors", "UNKNOWN"), reply);
        const char *last_acquire = server_field(reply, "last_acquire_epoch", "UNAVAILABLE");
        const char *last_release = server_field(reply, "last_release_epoch", "UNAVAILABLE");
        const char *release_error = server_field(reply, "last_release_error", "unknown");
        fprintf(out,
                "health.daemon_uptime=AVAILABLE\n"
                "health.assertion_lifecycle=AVAILABLE\n"
                "health.last_assertion_acquisition=%s\n"
                "health.last_assertion_release=%s\n"
                "health.last_release_error=%s\n"
                "health.schedule_activity=AVAILABLE\n"
                "health.recent_daemon_errors=AVAILABLE\n",
                strcmp(last_acquire, "UNAVAILABLE") == 0 ? "UNAVAILABLE" : "AVAILABLE",
                strcmp(last_release, "UNAVAILABLE") == 0 ? "UNAVAILABLE" : "AVAILABLE",
                strcmp(release_error, "none") == 0 ? "AVAILABLE" : "ERROR");
    } else {
        fprintf(out,
                "assertion_ownership=UNKNOWN\n"
                "assertion_lifecycle=UNAVAILABLE\n"
                "daemon_uptime_seconds=UNAVAILABLE\n"
                "last_acquisition_epoch=UNAVAILABLE\n"
                "last_release_epoch=UNAVAILABLE\n"
                "last_release_error=UNAVAILABLE\n"
                "schedule_activity=UNAVAILABLE\n"
                "daemon_recent_errors=UNAVAILABLE\n"
                "assertion_source=UNAVAILABLE\n"
                "trial_state=UNKNOWN\n"
                "state_invariant=UNAVAILABLE\n"
                "health.daemon_uptime=UNAVAILABLE\n"
                "health.assertion_lifecycle=UNAVAILABLE\n"
                "health.last_assertion_acquisition=UNAVAILABLE\n"
                "health.last_assertion_release=UNAVAILABLE\n"
                "health.last_release_error=UNAVAILABLE\n"
                "health.schedule_activity=UNAVAILABLE\n"
                "health.recent_daemon_errors=UNAVAILABLE\n"
                "daemon_error=%s\n", query_error[0] ? query_error : server_query_name(daemon));
    }
    fprintf(out,
            "socket_status=%s\n"
            "schedule_state_status=%s\n"
            "scheduled_wake_support=UNVERIFIED\n"
            "hardware_validation_complete=no\n"
            "unattended_mode_authorized=no\n"
            "operational_readiness=BLOCKED\n"
            "known_blocking_conditions=hardware_gates_pending,backend_unverified,network_measurements_unavailable,telemetry_unavailable,%s\n"
            "health.battery_level=UNAVAILABLE\n"
            "battery_level=UNAVAILABLE\n"
            "charging_status=UNAVAILABLE\n"
            "health.thermal_state=UNAVAILABLE\n"
            "thermal_state=UNAVAILABLE\n"
            "health.lan_connectivity=UNAVAILABLE\n"
            "lan_reachability=UNAVAILABLE\n"
            "health.tailscale_connectivity=UNAVAILABLE\n"
            "tailscale_reachability=UNAVAILABLE\n",
            server_path_state(socket_path, 1), server_path_state(schedule_path, 0),
            config.status == SERVER_CONFIG_INVALID || config.status == SERVER_CONFIG_UNSAFE ||
            config.status == SERVER_CONFIG_UNSUPPORTED
                ? "server_mode_config_invalid"
                : compatible && strcmp(server_field(reply, "state_invariant", "OK"), "ERROR") == 0
                    ? "daemon_state_invariant_failure"
                    : compatible && strcmp(server_field(reply, "release_pending", "no"), "yes") == 0
                        ? "assertion_release_unresolved" : "none");
    return ferror(out) ? -1 : 0;
}

static int server_doctor(FILE *out, const char *socket_path, const char *config_path,
                         const char *schedule_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    char reply[4096] = {0}, query_error[128] = {0};
    server_daemon_result_t daemon = server_query_daemon(socket_path, reply, sizeof(reply),
                                                        query_error, sizeof(query_error));
    const char *socket = server_path_state(socket_path, 1);
    const char *schedule = server_path_state(schedule_path, 0);
    fprintf(out,
            "iOS-Caffeinate server doctor\n"
            "check.cli_daemon_protocol=%s\n"
            "check.expected_socket=%s\n"
            "check.daemon_availability=%s\n"
            "check.assertion_backend=%s\n"
            "check.backend_diagnostics=%s\n"
            "check.daemon_state=%s\n"
            "check.os_power_state=UNVERIFIED\n"
            "check.prior_process_cleanup=UNVERIFIED\n"
            "check.schedule_state=%s\n"
            "check.power_management_limitations=UNVERIFIED\n"
            "check.scheduled_wake=UNVERIFIED\n"
            "check.missing_hardware_validation=PENDING\n"
            "check.automatic_startup=UNKNOWN\n"
            "check.launchd_template=DISABLED\n"
            "check.network_measurements=UNAVAILABLE\n"
            "check.battery_telemetry=UNAVAILABLE\n"
            "check.thermal_telemetry=UNAVAILABLE\n"
            "configuration=%s (%s)\n"
            "readiness=BLOCKED\n",
            server_query_name(daemon), socket,
            daemon == SERVER_DAEMON_COMPATIBLE || daemon == SERVER_DAEMON_INCOMPATIBLE
                ? "AVAILABLE" : "UNAVAILABLE",
            server_mode_backend_name(), daemon == SERVER_DAEMON_COMPATIBLE ? "AVAILABLE" : "UNAVAILABLE",
            daemon == SERVER_DAEMON_COMPATIBLE ? server_field(reply, "state", "UNKNOWN") : "UNAVAILABLE",
            strcmp(schedule, "AVAILABLE") == 0 ? "AVAILABLE" : "UNAVAILABLE",
            server_policy_name(config.policy), server_config_status_name(config.status));
    if (daemon == SERVER_DAEMON_COMPATIBLE)
        fprintf(out, "daemon_assertion_report=%s\n", reply);
    else
        fprintf(out, "daemon_detail=%s\n", query_error[0] ? query_error : server_query_name(daemon));
    fprintf(out, "unattended_authorized=no\n");
    return ferror(out) ? -1 : 0;
}

static int server_plan(FILE *out, const char *config_path) {
    server_config_t config;
    if (load_server_config(config_path, &config) != 0) return -1;
    fprintf(out,
            "iOS-Caffeinate unattended server readiness plan\n"
            "configured_policy=%s\n"
            "configuration_status=%s\n"
            "unattended_authorized=no\n"
            "automatic_apply=no\n",
            server_policy_name(config.policy), server_config_status_name(config.status));
    for (size_t i = 0; i < server_mode_gate_count(); ++i) {
        const char *gate = server_mode_gate_name(i);
        const char *consequence = "unattended operation remains blocked";
        if (strcmp(gate, "device_runtime_verified") == 0) consequence = "target execution remains unknown";
        else if (strcmp(gate, "assertion_acquire_verified") == 0) consequence = "assertion creation is unproven";
        else if (strcmp(gate, "assertion_release_verified") == 0) consequence = "cleanup cannot be trusted";
        else if (strcmp(gate, "bounded_hold_verified") == 0) consequence = "trial timing and expiry are unproven";
        else if (strcmp(gate, "screen_locked_lan_verified") == 0) consequence = "LAN SSH availability is unknown";
        else if (strcmp(gate, "screen_locked_tailscale_verified") == 0) consequence = "Tailscale SSH availability is unknown";
        else if (strcmp(gate, "shutdown_cleanup_verified") == 0) consequence = "shutdown release behavior is unknown";
        else if (strcmp(gate, "battery_observation_available") == 0) consequence = "battery impact cannot be assessed";
        else if (strcmp(gate, "thermal_observation_available") == 0) consequence = "thermal impact cannot be assessed";
        else if (strcmp(gate, "physical_recovery_confirmed") == 0) consequence = "recovery from a failed trial is unconfirmed";
        fprintf(out, "gate.%s=PENDING consequence=%s\n", gate, consequence);
    }
    fprintf(out, "next_safe_step=complete the separate P006-HW procedure with physical recovery available\n");
    return ferror(out) ? -1 : 0;
}

static int schedule_readonly_status(const char *socket_path, char *response, size_t cap) {
    if (!socket_path || socket_path[0] != '/' || !response || cap < 2 ||
        strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) return -1;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct timeval timeout = {.tv_sec = 0, .tv_usec = 750000};
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s", socket_path);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        close(fd);
        return -1;
    }
    const char request[] = "SERVER STATUS\n";
    size_t sent = 0;
    while (sent < sizeof(request) - 1) {
        ssize_t n = write(fd, request + sent, sizeof(request) - 1 - sent);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { close(fd); return -1; }
        sent += (size_t)n;
    }
    size_t used = 0;
    while (used + 1 < cap) {
        ssize_t n = recv(fd, response + used, cap - used - 1, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
        if (memchr(response, '\n', used)) break;
    }
    close(fd);
    response[used] = '\0';
    return used > 0 && strncmp(response, "OK SERVER ", 10) == 0 ? 0 : -1;
}

static int schedule_status_value(const char *response, const char *key,
                                 char *out, size_t cap) {
    if (!response || !key || !out || cap == 0) return -1;
    size_t key_len = strlen(key);
    const char *p = response;
    while ((p = strstr(p, key)) != NULL) {
        if ((p == response || p[-1] == ' ') && p[key_len] == '=') {
            p += key_len + 1;
            size_t n = strcspn(p, " \r\n");
            if (n == 0 || n >= cap) return -1;
            memcpy(out, p, n);
            out[n] = '\0';
            return 0;
        }
        p += key_len;
    }
    return -1;
}

static const char *schedule_cli_type(sched_type_t type) {
    switch (type) {
        case SCHED_TYPE_ONETIME: return "onetime";
        case SCHED_TYPE_DAILY: return "daily";
        case SCHED_TYPE_WEEKLY: return "weekly";
    }
    return "invalid";
}

static const char *schedule_recovery_store_name(recovery_store_result_t value) {
    switch (value) {
        case RECOVERY_STORE_OK: return "OK";
        case RECOVERY_STORE_MISSING: return "MISSING";
        case RECOVERY_STORE_UNSAFE: return "UNSAFE";
        case RECOVERY_STORE_CORRUPT: return "CORRUPT";
        case RECOVERY_STORE_UNSUPPORTED: return "UNSUPPORTED";
        case RECOVERY_STORE_IO_ERROR: return "IO_ERROR";
    }
    return "UNKNOWN";
}

static void schedule_cli_print_utc(FILE *out, const char *key, time_t instant) {
    char value[32] = {0};
    if (format_iso8601_utc(instant, value, sizeof(value)) >= 0)
        fprintf(out, "%s=%s\n", key, value);
    else fprintf(out, "%s=UNAVAILABLE\n", key);
}

static int schedule_cli_print_definition(FILE *out, const schedule_t *schedule,
                                         time_t reference) {
    schedule_analysis_t analysis;
    int analyzed = schedule_analyze(schedule, reference, &analysis);
    fprintf(out, "schedule.id=%s\n", schedule->id);
    fprintf(out, "schedule.type=%s\n", schedule_cli_type(schedule->type));
    fprintf(out, "schedule.enabled=%s\n", schedule->enabled ? "yes" : "no");
    fprintf(out, "schedule.duration_seconds=%u\n", schedule->duration);
    fprintf(out, "schedule.timezone=%s\n", schedule->tz[0] ? schedule->tz : "SYSTEM_LOCAL");
    if (schedule->type == SCHED_TYPE_ONETIME)
        schedule_cli_print_utc(out, "schedule.target_utc", schedule->target_time);
    else {
        fprintf(out, "schedule.local_time=%02d:%02d\n", schedule->hour, schedule->minute);
        if (schedule->type == SCHED_TYPE_WEEKLY)
            fprintf(out, "schedule.weekday_mask=0x%02x\n", (unsigned)schedule->days_mask);
    }
    fprintf(out, "schedule.last_fired_time=%lld\n", (long long)schedule->last_fired_time);
    fprintf(out, "schedule.outcome=%s\n", schedule->enabled
            ? schedule_outcome_name(analysis.outcome) : "DISABLED");
    if (analyzed != 0) {
        schedule_resolution_t resolution = analysis.outcome == SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED
            ? SCHEDULE_RESOLUTION_TIMEZONE_UNVERIFIED : SCHEDULE_RESOLUTION_INVALID;
        fprintf(out, "schedule.resolution=%s\n", schedule_resolution_name(resolution));
    } else if (analysis.has_occurrence) {
        fprintf(out, "schedule.resolution=%s\n",
                schedule_resolution_name(analysis.occurrence.resolution));
        char identity[320] = {0};
        if (schedule_occurrence_identity(&analysis.occurrence, identity, sizeof(identity)) > 0)
            fprintf(out, "schedule.occurrence_id=%s\n", identity);
    } else fprintf(out, "schedule.resolution=UNRESOLVED\n");
    if (analysis.saw_nonexistent_local_time)
        fprintf(out, "schedule.dst_gap_policy=SKIP_OCCURRENCE\n");
    if (analysis.has_next) schedule_cli_print_utc(out, "schedule.next_utc", analysis.next.start);
    else fprintf(out, "schedule.next_utc=UNAVAILABLE\n");
    if (schedule->duration > SCHEDULE_MAX_SESSION_SECONDS)
        fprintf(out, "schedule.policy_blocker=LEGACY_DURATION_EXCEEDS_POLICY\n");
    fprintf(out, "schedule.execution=BLOCKED_POLICY\n");
    fprintf(out, "schedule.execution_reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED\n");
    return ferror(out) ? -1 : 0;
}

static int schedule_cli_conflicts(FILE *out, const schedule_store_t *store,
                                  time_t reference, const char *socket_path,
                                  int check_manual_hold, const char *only_id) {
    schedule_conflict_t conflicts[SCHEDULE_CONFLICT_MAX];
    size_t count = 0;
    int incomplete = 0;
    if (schedule_store_find_conflicts(store, reference, 370, conflicts,
                                      SCHEDULE_CONFLICT_MAX, &count, &incomplete) != 0) {
        fprintf(out, "schedule.conflicts=INCOMPLETE\n");
        return -1;
    }
    fprintf(out, "schedule.horizon_days=370\n");
    if (incomplete) fprintf(out, "schedule.conflicts=INCOMPLETE\n");
    size_t emitted = 0;
    for (size_t i = 0; i < count && i < SCHEDULE_CONFLICT_MAX; ++i) {
        const schedule_conflict_t *conflict = &conflicts[i];
        const char *first_id = store->items[conflict->first_index].id;
        const char *second_id = store->items[conflict->second_index].id;
        if (only_id && strcmp(first_id, only_id) != 0 && strcmp(second_id, only_id) != 0)
            continue;
        emitted++;
        fprintf(out, "schedule.conflict=yes\n");
        fprintf(out, "conflict.type=%s\n", conflict->duplicate_definition
                ? "DUPLICATE_DEFINITION" : "OVERLAPPING_WINDOWS");
        fprintf(out, "conflict.first=%s\n", first_id);
        fprintf(out, "conflict.second=%s\n", second_id);
        if (conflict->first_end > conflict->first_start) {
            schedule_cli_print_utc(out, "conflict.first_start_utc", conflict->first_start);
            schedule_cli_print_utc(out, "conflict.first_end_utc", conflict->first_end);
            schedule_cli_print_utc(out, "conflict.second_start_utc", conflict->second_start);
            schedule_cli_print_utc(out, "conflict.second_end_utc", conflict->second_end);
        }
        fprintf(out, "conflict.resolution=OPERATOR_REVIEW_REQUIRED\n");
    }
    if (emitted == 0 && !incomplete) fprintf(out, "schedule.conflict=no\n");
    if (!check_manual_hold) return ferror(out) ? -1 : 0;

    char status[4096] = {0}, active[16] = {0}, remaining_text[32] = {0};
    if (schedule_readonly_status(socket_path, status, sizeof(status)) != 0) {
        fprintf(out, "manual_assertion=UNAVAILABLE\n");
        return ferror(out) ? -1 : 0;
    }
    if (schedule_status_value(status, "active", active, sizeof(active)) != 0 ||
        strcmp(active, "yes") != 0) {
        fprintf(out, "manual_assertion=NONE\n");
        return ferror(out) ? -1 : 0;
    }
    if (schedule_status_value(status, "remaining_seconds", remaining_text,
                              sizeof(remaining_text)) != 0) {
        fprintf(out, "manual_assertion=OWNED\nmanual_schedule_conflict=INCOMPLETE\n");
        return ferror(out) ? -1 : 0;
    }
    char *endptr = NULL;
    errno = 0;
    unsigned long remaining = strtoul(remaining_text, &endptr, 10);
    int64_t reference_i64 = (int64_t)reference;
    time_t manual_end = 0;
    int have_end = !errno && endptr != remaining_text && !*endptr &&
        (time_t)reference_i64 == reference && remaining <= 86400 &&
        reference_i64 <= INT64_MAX - (int64_t)remaining &&
        (manual_end = (time_t)(reference_i64 + (int64_t)remaining),
         (int64_t)manual_end == reference_i64 + (int64_t)remaining);
    fprintf(out, "manual_assertion=OWNED\n");
    for (size_t i = 0; have_end && i < store->count; ++i) {
        if (!store->items[i].enabled) continue;
        schedule_analysis_t analysis;
        if (schedule_analyze(&store->items[i], reference, &analysis) != 0) continue;
        schedule_occurrence_t window;
        int overlaps = 0;
        if (analysis.outcome == SCHEDULE_OUTCOME_ACTIVE_WINDOW && analysis.has_occurrence) {
            window = analysis.occurrence;
            overlaps = window.end > reference && window.start < manual_end;
        } else if (analysis.has_next) {
            window = analysis.next;
            overlaps = window.start < manual_end;
        }
        if (overlaps) {
            fprintf(out, "manual_schedule_conflict=yes\n");
            fprintf(out, "conflict.first=%s\n", store->items[i].id);
            fprintf(out, "conflict.second=manual-hold\n");
            schedule_cli_print_utc(out, "conflict.first_start_utc", window.start);
            schedule_cli_print_utc(out, "conflict.first_end_utc", window.end);
            schedule_cli_print_utc(out, "conflict.second_start_utc", reference);
            schedule_cli_print_utc(out, "conflict.second_end_utc", manual_end);
            fprintf(out, "conflict.resolution=OPERATOR_REVIEW_REQUIRED\n");
        }
    }
    return ferror(out) ? -1 : 0;
}

static int schedule_diagnostics_command(int argc, char **argv, const char *socket_path,
                                        const char *schedule_path,
                                        const char *server_config_path,
                                        const char *recovery_path) {
    if (argc < 1) return -2;
    const char *command = argv[0];
    int known = strcmp(command, "list") == 0 || strcmp(command, "next") == 0 ||
        strcmp(command, "doctor") == 0 || strcmp(command, "conflicts") == 0 ||
        strcmp(command, "validate") == 0 || strcmp(command, "explain") == 0;
    if (!known) return -2;
    const char *id = NULL;
    int option = 1;
    if (strcmp(command, "explain") == 0) {
        if (option >= argc || argv[option][0] == '-') return 2;
        id = argv[option++];
    }
    time_t reference = time(NULL);
    int supplied_at = 0;
    while (option < argc) {
        if (strcmp(argv[option], "--at") == 0 && option + 1 < argc && !supplied_at) {
            reference = parse_iso8601(argv[option + 1]);
            if (reference == (time_t)-1) {
                fprintf(stderr, "Invalid --at timestamp. Use ISO-8601 with an explicit timezone.\n");
                return 2;
            }
            supplied_at = 1;
            option += 2;
        } else return 2;
    }
    if (strcmp(command, "validate") == 0 && supplied_at) return 2;

    schedule_store_t store;
    schedule_store_init(&store, schedule_path);
    char error[256] = {0};
    if (schedule_store_load(&store, error, sizeof(error)) != 0) {
        fprintf(stderr, "schedule.storage=INVALID detail=%s\n", error);
        return 1;
    }
    fprintf(stdout, "schedule.definitions_source=STORAGE\n");
    fprintf(stdout, "schedule.storage=VALID\n");
    fprintf(stdout, "schedule.generation=%016llx\n",
            (unsigned long long)schedule_store_generation(&store));
    fprintf(stdout, "schedule.count=%zu\n", store.count);
    fprintf(stdout, "schedules=%zu\n", store.count);

    if (strcmp(command, "validate") == 0) {
        size_t legacy = 0, timezone_unverified = 0;
        for (size_t i = 0; i < store.count; ++i) {
            if (store.items[i].duration > SCHEDULE_MAX_SESSION_SECONDS) legacy++;
            if (store.items[i].enabled && store.items[i].type != SCHED_TYPE_ONETIME) {
                schedule_analysis_t analysis;
                if (schedule_analyze(&store.items[i], time(NULL), &analysis) != 0 &&
                    analysis.outcome == SCHEDULE_OUTCOME_TIMEZONE_UNVERIFIED)
                    timezone_unverified++;
            }
        }
        fprintf(stdout, "schedule.validation=PASS\nlegacy_duration_exceeds_policy=%zu\n",
                legacy);
        fprintf(stdout, "timezone_resolution_unverified=%zu\n", timezone_unverified);
        fprintf(stdout, "schedule.execution=BLOCKED_POLICY reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED\n");
        return 0;
    }
    if (strcmp(command, "doctor") == 0) {
        char status[4096] = {0}, recovery[32] = {0}, active[16] = {0};
        int status_ok = !supplied_at &&
            schedule_readonly_status(socket_path, status, sizeof(status)) == 0;
        recovery_record_t recovery_record;
        char recovery_detail[192] = {0};
        recovery_store_result_t recovery_result = recovery_store_load(
            recovery_path, geteuid(), &recovery_record,
            recovery_detail, sizeof(recovery_detail));
        fprintf(stdout, "schedule.timebase=UTC_EPOCH_REFERENCE\n");
        fprintf(stdout, "schedule.runtime=%s\n", status_ok ? "AVAILABLE_READ_ONLY" : "UNAVAILABLE");
        if (status_ok && schedule_status_value(status, "recovery_schedule_gate", recovery,
                                               sizeof(recovery)) == 0)
            fprintf(stdout, "schedule.recovery=%s\n", recovery);
        else fprintf(stdout, "schedule.recovery=UNKNOWN_RUNTIME_UNAVAILABLE\n");
        fprintf(stdout, "schedule.recovery_journal=%s\n",
                schedule_recovery_store_name(recovery_result));
        if (recovery_result == RECOVERY_STORE_OK) {
            fprintf(stdout, "schedule.recovery_process=%s\n",
                    recovery_process_state_name(recovery_record.process_state));
            fprintf(stdout, "schedule.recovery_cleanup=%s\n",
                    recovery_cleanup_state_name(recovery_record.cleanup_state));
        } else if (recovery_detail[0]) {
            fprintf(stdout, "schedule.recovery_detail=%s\n", recovery_detail);
        }
        if (status_ok && schedule_status_value(status, "active", active, sizeof(active)) == 0)
            fprintf(stdout, "schedule.assertion_owner=%s\n",
                    strcmp(active, "yes") == 0 ? "OWNED" : "NONE");
        else fprintf(stdout, "schedule.assertion_owner=UNKNOWN\n");
        server_config_t config;
        server_policy_inputs_t inputs;
        server_policy_result_t result;
        (void)server_mode_config_load(server_config_path, &config);
        server_policy_inputs_init(&inputs);
        inputs.operation = SERVER_OPERATION_SCHEDULED_UNATTENDED;
        inputs.requested_duration_seconds = 1;
        if (server_policy_evaluate(&config, &inputs, &result) == 0) {
            fprintf(stdout, "schedule.policy=%s\n", server_policy_decision_name(result.decision));
            fprintf(stdout, "schedule.policy_reason=%s\n",
                    server_policy_reason_name(result.primary_reason));
        } else fprintf(stdout, "schedule.policy=BLOCKED_POLICY\nschedule.policy_reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED\n");
        fprintf(stdout, "schedule.telemetry=UNKNOWN_NOT_SAMPLED\n");
        fprintf(stdout, "schedule.executor=NOT_AUTHORIZED\n");
        fprintf(stdout, "schedule.wake_capability=UNVERIFIED\n");
        (void)schedule_cli_conflicts(stdout, &store, reference, socket_path,
                                     !supplied_at, NULL);
        return 0;
    }
    if (strcmp(command, "list") == 0 || strcmp(command, "next") == 0) {
        fprintf(stdout, "schedule.runtime_state=NOT_INFERRED_FROM_STORAGE\n");
        fprintf(stdout, "scheduled_wake=UNVERIFIED execution=NOT_GUARANTEED\n");
        for (size_t i = 0; i < store.count; ++i) {
            if (i) fprintf(stdout, "schedule.record_separator=---\n");
            (void)schedule_cli_print_definition(stdout, &store.items[i], reference);
        }
        return ferror(stdout) ? 1 : 0;
    }
    if (strcmp(command, "conflicts") == 0) {
        fprintf(stdout, "schedule.horizon_days=370\n");
        (void)schedule_cli_conflicts(stdout, &store, reference, socket_path,
                                     !supplied_at, NULL);
        return ferror(stdout) ? 1 : 0;
    }
    if (strcmp(command, "explain") == 0) {
        size_t index = store.count;
        for (size_t i = 0; i < store.count; ++i)
            if (strcmp(store.items[i].id, id) == 0) { index = i; break; }
        if (index == store.count) {
            fprintf(stderr, "schedule ID '%s' not found\n", id);
            return 1;
        }
        schedule_cli_print_utc(stdout, "schedule.reference_utc", reference);
        (void)schedule_cli_print_definition(stdout, &store.items[index], reference);
        fprintf(stdout, "schedule.conflicts_scope=%s\n", id);
        (void)schedule_cli_conflicts(stdout, &store, reference, socket_path,
                                     !supplied_at, id);
        return ferror(stdout) ? 1 : 0;
    }
    return 2;
}

static int schedule_cli_load_store(const char *path, schedule_store_t *store) {
    char error[256] = {0};
    schedule_store_init(store, path);
    if (schedule_store_load(store, error, sizeof(error)) != 0) {
        fprintf(stderr, "schedule storage cannot be safely read: %s\n", error);
        return -1;
    }
    return 0;
}

static int schedule_cli_parse_generation(const char *text, uint64_t *generation) {
    if (!text || !generation || strlen(text) != 16) return -1;
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 16);
    if (errno || end == text || *end) return -1;
    *generation = (uint64_t)value;
    return 0;
}

static int schedule_cli_preview_mutation(FILE *out, const schedule_store_t *store,
                                         size_t index, const char *operation) {
    schedule_store_t preview = *store;
    int changed = 0;
    if (strcmp(operation, "remove") == 0) {
        for (size_t i = index; i + 1 < preview.count; ++i)
            preview.items[i] = preview.items[i + 1];
        if (preview.count > 0) preview.count--;
        changed = 1;
    } else {
        bool enabled = strcmp(operation, "enable") == 0;
        changed = preview.items[index].enabled != enabled;
        preview.items[index].enabled = enabled;
    }
    schedule_conflict_t conflicts[SCHEDULE_CONFLICT_MAX];
    size_t before_count = 0, after_count = 0;
    int before_incomplete = 0, after_incomplete = 0;
    time_t now = time(NULL);
    int before_ok = schedule_store_find_conflicts(store, now, 370, conflicts,
                        SCHEDULE_CONFLICT_MAX, &before_count, &before_incomplete) == 0;
    int after_ok = schedule_store_find_conflicts(&preview, now, 370, conflicts,
                        SCHEDULE_CONFLICT_MAX, &after_count, &after_incomplete) == 0;
    fprintf(out, "schedule.preview=DRY_RUN\n");
    fprintf(out, "schedule.operation=%s\n", operation);
    fprintf(out, "schedule.changed=%s\n", changed ? "yes" : "no");
    fprintf(out, "schedule.generation=%016llx\n",
            (unsigned long long)schedule_store_generation(store));
    fprintf(out, "conflicts.before=%s%zu\n", before_ok ? "" : "INCOMPLETE:", before_count);
    fprintf(out, "conflicts.after=%s%zu\n", after_ok ? "" : "INCOMPLETE:", after_count);
    if (after_ok) {
        for (size_t i = 0; i < after_count && i < SCHEDULE_CONFLICT_MAX; ++i) {
            const schedule_conflict_t *conflict = &conflicts[i];
            fprintf(out, "conflict.after.type=%s\n", conflict->duplicate_definition
                    ? "DUPLICATE_DEFINITION" : "OVERLAPPING_WINDOWS");
            fprintf(out, "conflict.after.first=%s\n",
                    preview.items[conflict->first_index].id);
            fprintf(out, "conflict.after.second=%s\n",
                    preview.items[conflict->second_index].id);
            if (conflict->first_end > conflict->first_start) {
                schedule_cli_print_utc(out, "conflict.after.first_start_utc",
                                       conflict->first_start);
                schedule_cli_print_utc(out, "conflict.after.first_end_utc",
                                       conflict->first_end);
                schedule_cli_print_utc(out, "conflict.after.second_start_utc",
                                       conflict->second_start);
                schedule_cli_print_utc(out, "conflict.after.second_end_utc",
                                       conflict->second_end);
            }
            fprintf(out, "conflict.after.resolution=OPERATOR_REVIEW_REQUIRED\n");
        }
    }
    fprintf(out, "schedule.execution=BLOCKED_POLICY reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED\n");
    if (before_incomplete || after_incomplete)
        fprintf(out, "schedule.preview_resolution=INCOMPLETE_TIMEZONE_OR_HORIZON\n");
    fprintf(out, "schedule.write_performed=no\n");
    return ferror(out) ? -1 : 0;
}

int main(int argc, char **argv) {
    const char *path = DEFAULT_SOCKET;
    const char *server_config_path = SERVER_MODE_CONFIG_DEFAULT;
    const char *schedule_path = DEFAULT_SCHEDULE_STATE;
    const char *recovery_path = RECOVERY_DEFAULT_PATH;
    int i = 1;
    while (i < argc && argv[i][0] == '-' && argv[i][1] == '-' &&
           strcmp(argv[i], "--help") != 0 && strcmp(argv[i], "--version") != 0) {
        if (i + 1 >= argc) { usage(); return 2; }
        if (strcmp(argv[i], "--socket") == 0) path = argv[i + 1];
        else if (strcmp(argv[i], "--server-config") == 0) server_config_path = argv[i + 1];
        else if (strcmp(argv[i], "--schedule-state") == 0) schedule_path = argv[i + 1];
        else if (strcmp(argv[i], "--recovery-state") == 0) recovery_path = argv[i + 1];
        else {
            fprintf(stderr, "error.code=INVALID_ARGUMENT\nerror.operation=global_options\n"
                            "error.reason=UNKNOWN_OR_MISSING_OPTION_VALUE\nchanged=no\ncleanup=not_applicable\n"
                            "next_safe_step=run_ic_help\n");
            return 2;
        }
        i += 2;
    }
    if (i == argc) {
        usage();
        return 2;
    }
    if (strcmp(argv[i], "--help") == 0) {
        if (i + 1 != argc) {
            report_cli_error("INVALID_ARGUMENT", "help", "UNEXPECTED_ARGUMENTS", "no",
                             "run_ic_help");
            return 2;
        }
        usage();
        return 0;
    }
    if (strcmp(argv[i], "--version") == 0 || strcmp(argv[i], "version") == 0) {
        if (i + 1 != argc) return 2;
        version_report();
        return ferror(stdout) ? 1 : 0;
    }
    if (strcmp(argv[i], "help") == 0) {
        if (i + 2 < argc) {
            fprintf(stderr, "error.code=INVALID_ARGUMENT\nerror.operation=help\n"
                            "error.reason=TOO_MANY_HELP_ARGUMENTS\nchanged=no\ncleanup=not_applicable\n"
                            "next_safe_step=run_ic_help\n");
            return 2;
        }
        return help_topic(i + 1 < argc ? argv[i + 1] : NULL);
    }

    diagnostic_context_t diagnostic_context = {
        .socket_path = path,
        .server_config_path = server_config_path,
        .schedule_path = schedule_path,
        .recovery_path = recovery_path,
    };

    if (strcmp(argv[i], "doctor") == 0)
        return doctor_command(argc - i - 1, argv + i + 1, &diagnostic_context);
    if (strcmp(argv[i], "package") == 0)
        return package_command(argc - i - 1, argv + i + 1);
    if (strcmp(argv[i], "evidence") == 0)
        return evidence_command(argc - i - 1, argv + i + 1);

    if (strcmp(argv[i], "schedule") == 0) {
        int diagnostic = schedule_diagnostics_command(argc - i - 1, argv + i + 1,
                                                     path, schedule_path,
                                                     server_config_path, recovery_path);
        if (diagnostic != -2) {
            if (diagnostic == 2) usage();
            return diagnostic;
        }
    }

    if (strcmp(argv[i], "service") == 0) {
        return service_command(argc - i - 1, argv + i + 1, stdout, stderr);
    }

    if (strcmp(argv[i], "health") == 0) {
        if (i + 1 >= argc) { usage(); return 2; }
        const char *trial_id = NULL;
        const char *condition_id = NULL;
        int outside_quiet_interval = 0;
        int invalid_option = 0;
        int option = i + 2;
        while (option < argc) {
            if (strcmp(argv[option], "--trial-id") == 0 && option + 1 < argc && !trial_id) {
                trial_id = argv[option + 1];
                option += 2;
            } else if (strcmp(argv[option], "--condition-id") == 0 &&
                       option + 1 < argc && !condition_id) {
                condition_id = argv[option + 1];
                option += 2;
            } else if (strcmp(argv[option], "--outside-quiet-interval") == 0 &&
                       !outside_quiet_interval) {
                outside_quiet_interval = 1;
                option++;
            } else {
                invalid_option = 1;
                break;
            }
        }
        int valid_condition = condition_id &&
            (strcmp(condition_id, "A") == 0 || strcmp(condition_id, "B") == 0 ||
             strcmp(condition_id, "C") == 0 || strcmp(condition_id, "D") == 0);
        if (invalid_option ||
            ((trial_id || condition_id || outside_quiet_interval) &&
             (strcmp(argv[i + 1], "status") != 0 || !trial_id || !valid_condition ||
              !outside_quiet_interval || !health_trial_id_valid(trial_id)))) {
            fprintf(stderr, "P012 association requires health status, a valid --trial-id, --condition-id A|B|C|D, and --outside-quiet-interval.\n");
            return 2;
        }
        int rc = health_command(stdout, argv[i + 1], path, trial_id, condition_id,
                                outside_quiet_interval);
        if (rc == 2) usage();
        return rc;
    }

    char command[512] = {0};

    if (strcmp(argv[i], "server") == 0) {
        if (i + 2 < argc && strcmp(argv[i + 1], "policy") == 0) {
            return server_policy_command(argc - i - 2, argv + i + 2,
                                         path, server_config_path);
        }
        if (i + 2 == argc && strcmp(argv[i + 1], "status") == 0) {
            return server_status(stdout, path, server_config_path, schedule_path) == 0 ? 0 : 1;
        }
        if (i + 2 == argc && strcmp(argv[i + 1], "doctor") == 0) {
            return server_doctor(stdout, path, server_config_path, schedule_path) == 0 ? 0 : 1;
        }
        if (i + 2 == argc && strcmp(argv[i + 1], "plan") == 0) {
            return server_plan(stdout, server_config_path) == 0 ? 0 : 1;
        }
        if (i + 3 == argc && strcmp(argv[i + 1], "trial") == 0 &&
            strcmp(argv[i + 2], "stop") == 0) {
            strcpy(command, "TRIAL STOP\n");
        } else if (i + 5 == argc && strcmp(argv[i + 1], "trial") == 0 &&
                   strcmp(argv[i + 2], "start") == 0 && strcmp(argv[i + 3], "--for") == 0) {
            unsigned duration = 0;
            if (parse_duration(argv[i + 4], &duration) != 0 || duration > 300) {
                fprintf(stderr, "Server trials must be bounded to 1 second through 5 minutes.\n");
                return 2;
            }
            snprintf(command, sizeof(command), "TRIAL START %u\n", duration);
        } else {
            usage();
            return 2;
        }
    } else if (strcmp(argv[i], "wake") == 0) {
        if (i + 2 != argc || strcmp(argv[i + 1], "status") != 0) {
            usage();
            return 2;
        }
        if (wake_capability_write(stdout) != 0) {
            perror("write wake capability status");
            return 1;
        }
        return 0;
    }

    if (command[0] != '\0') {
        /* Explicit bounded server trial request already parsed above. */
    } else if (strcmp(argv[i], "probe") == 0 && i + 1 == argc) {
        strcpy(command, "PROBE\n");
    } else if (strcmp(argv[i], "status") == 0 && i + 1 == argc) {
        strcpy(command, "STATUS\n");
    } else if (strcmp(argv[i], "stop") == 0 && i + 1 == argc) {
        strcpy(command, "STOP\n");
    } else if (strcmp(argv[i], "start") == 0) {
        if (i + 3 == argc && strcmp(argv[i + 1], "--for") == 0) {
            unsigned duration = 0;
            if (parse_duration(argv[i + 2], &duration) != 0) {
                fprintf(stderr, "Invalid duration. Use 1s..24h.\n");
                return 2;
            }
            snprintf(command, sizeof(command), "START %u\n", duration);
        } else if (i + 3 == argc && strcmp(argv[i + 1], "--until") == 0) {
            time_t deadline_utc = parse_iso8601(argv[i + 2]);
            if (deadline_utc == (time_t)-1) {
                fprintf(stderr, "Invalid ISO-8601 timestamp for --until. Explicit timezone offset required.\n");
                return 2;
            }
            time_t now_utc = time(NULL);
            if (deadline_utc <= now_utc) {
                fprintf(stderr, "Deadline is in the past.\n");
                return 2;
            }
            double diff = difftime(deadline_utc, now_utc);
            if (diff < 1.0 || diff > 86400.0) {
                fprintf(stderr, "Duration until deadline must be between 1s and 24h.\n");
                return 2;
            }
            snprintf(command, sizeof(command), "START %u\n", (unsigned)diff);
        } else { usage(); return 2; }
    } else if (strcmp(argv[i], "schedule") == 0) {
        i++;
        if (i >= argc) { usage(); return 2; }
        if (strcmp(argv[i], "remove") == 0 || strcmp(argv[i], "enable") == 0 ||
            strcmp(argv[i], "disable") == 0) {
            const char *operation = argv[i++];
            if (i >= argc || argv[i][0] == '-') { usage(); return 2; }
            const char *id = argv[i++];
            const char *generation_arg = NULL;
            int dry_run = 0;
            while (i < argc) {
                if (strcmp(argv[i], "--dry-run") == 0 && !dry_run) {
                    dry_run = 1;
                    i++;
                } else if (strcmp(argv[i], "--if-generation") == 0 &&
                           i + 1 < argc && !generation_arg) {
                    generation_arg = argv[i + 1];
                    i += 2;
                } else { usage(); return 2; }
            }
            schedule_store_t current;
            if (schedule_cli_load_store(schedule_path, &current) != 0) return 1;
            size_t index = current.count;
            for (size_t j = 0; j < current.count; ++j)
                if (strcmp(current.items[j].id, id) == 0) { index = j; break; }
            if (index == current.count) {
                fprintf(stderr, "schedule ID '%s' not found\n", id);
                return 1;
            }
            uint64_t generation = schedule_store_generation(&current);
            if (generation_arg && schedule_cli_parse_generation(generation_arg, &generation) != 0) {
                fprintf(stderr, "Invalid --if-generation value; expected 16 hexadecimal digits.\n");
                return 2;
            }
            if (generation != schedule_store_generation(&current)) {
                fprintf(stderr, "Stale schedule generation; reload before editing.\n");
                return 1;
            }
            if (dry_run) return schedule_cli_preview_mutation(stdout, &current, index, operation) == 0 ? 0 : 1;
            if (strcmp(operation, "remove") == 0)
                snprintf(command, sizeof(command), "SCHEDULE REMOVE %s %016llx\n", id,
                         (unsigned long long)generation);
            else
                snprintf(command, sizeof(command), "SCHEDULE SET_ENABLED %s %d %016llx\n",
                         id, strcmp(operation, "enable") == 0 ? 1 : 0,
                         (unsigned long long)generation);
        } else if (strcmp(argv[i], "add") == 0) {
            i++;
            const char *at_str = NULL;
            const char *daily_str = NULL;
            const char *weekly_str = NULL;
            const char *for_str = NULL;
            const char *tz_str = NULL;

            while (i < argc) {
                if (strcmp(argv[i], "--at") == 0 && i + 1 < argc) { at_str = argv[++i]; }
                else if (strcmp(argv[i], "--daily") == 0 && i + 1 < argc) { daily_str = argv[++i]; }
                else if (strcmp(argv[i], "--weekly") == 0 && i + 1 < argc) { weekly_str = argv[++i]; }
                else if (strcmp(argv[i], "--for") == 0 && i + 1 < argc) { for_str = argv[++i]; }
                else if (strcmp(argv[i], "--tz") == 0 && i + 1 < argc) { tz_str = argv[++i]; }
                else { usage(); return 2; }
                i++;
            }

            if (!for_str) {
                fprintf(stderr, "Missing --for duration parameter.\n");
                return 2;
            }
            unsigned duration = 0;
            if (parse_duration(for_str, &duration) != 0 ||
                duration > SCHEDULE_MAX_SESSION_SECONDS) {
                fprintf(stderr, "New schedule durations must be 1 second through 300 seconds.\n");
                return 2;
            }
            schedule_store_t current;
            if (schedule_cli_load_store(schedule_path, &current) != 0) return 1;
            uint64_t generation = schedule_store_generation(&current);

            if (weekly_str) {
                uint8_t mask = 0;
                if (parse_weekly_days(weekly_str, &mask) != 0) {
                    fprintf(stderr, "Invalid --weekly days. Use mon,wed,fri etc.\n");
                    return 2;
                }
                int hour = 0, min = 0;
                if (!at_str || parse_hhmm(at_str, &hour, &min) != 0) {
                    fprintf(stderr, "Weekly schedule requires --at HH:MM.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD WEEKLY %u %02d:%02d %u %s %016llx\n",
                         (unsigned)mask, hour, min, duration, tz_str ? tz_str : "-",
                         (unsigned long long)generation);
            } else if (daily_str) {
                int hour = 0, min = 0;
                if (parse_hhmm(daily_str, &hour, &min) != 0) {
                    fprintf(stderr, "Daily schedule requires --daily HH:MM.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD DAILY %02d:%02d %u %s %016llx\n",
                         hour, min, duration, tz_str ? tz_str : "-",
                         (unsigned long long)generation);
            } else if (at_str) {
                time_t target_utc = parse_iso8601(at_str);
                if (target_utc == (time_t)-1) {
                    fprintf(stderr, "Invalid ISO-8601 timestamp for schedule --at. Explicit timezone offset required.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD ONETIME %lld %u %016llx\n",
                         (long long)target_utc, duration, (unsigned long long)generation);
            } else { usage(); return 2; }
        } else { usage(); return 2; }
    } else {
        report_cli_error("INVALID_ARGUMENT", "command", "UNKNOWN_SUBCOMMAND", "no",
                         "run_ic_help");
        usage();
        return 2;
    }

    if (*path != '/' || strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Invalid socket path\n");
        return 2;
    }
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("signal setup"); return 1; }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("connect daemon (is ios-caffeinated running?)");
        close(fd);
        return 1;
    }
    struct timeval timeout = {.tv_sec = 4, .tv_usec = 0};
    if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
        perror("socket timeout"); close(fd); return 1; }
    size_t to_send = strlen(command);
    const char *out = command;
    while (to_send) {
        ssize_t n = write(fd, out, to_send);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { perror("write"); close(fd); return 1; }
        to_send -= (size_t)n;
        out += n;
    }
    char response[16384] = {0};
    size_t used = 0;
    struct timespec started, current;
    if (clock_gettime(CLOCK_MONOTONIC, &started) != 0) {
        perror("clock_gettime"); close(fd); return 1; }
    for (;;) {
        if (clock_gettime(CLOCK_MONOTONIC, &current) != 0) break;
        double elapsed = (double)(current.tv_sec - started.tv_sec) +
                         (double)(current.tv_nsec - started.tv_nsec) / 1000000000.0;
        if (elapsed >= 4) break;
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int ready = poll(&pfd, 1, 100);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0) break;
        if (ready == 0) continue;
        ssize_t n = recv(fd, response + used, sizeof(response) - 1 - used, MSG_DONTWAIT);
        if (n <= 0) {
            if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            break;
        }
        size_t end = used + (size_t)n;
        bool is_sched_list = (strncmp(response, "OK schedules=", 13) == 0);
        for (size_t j = used; j < end; ++j) {
            if (response[j] == '\n') {
                if (!is_sched_list && j + 1 != end) goto incomplete;
            } else if ((unsigned char)response[j] < 32 || (unsigned char)response[j] > 126) {
                goto incomplete;
            }
        }
        used = end;
        if (!is_sched_list && used > 0 && response[used - 1] == '\n') {
            response[used] = 0;
            close(fd);
            fputs(response, strncmp(response, "OK ", 3) == 0 ? stdout : stderr);
            return strncmp(response, "OK ", 3) == 0 ? 0 : 1;
        }
        if (used == sizeof(response) - 1) break;
    }
incomplete:
    if (used > 0 && response[used - 1] == '\n') {
        response[used] = 0;
        close(fd);
        fputs(response, strncmp(response, "OK ", 3) == 0 ? stdout : stderr);
        return strncmp(response, "OK ", 3) == 0 ? 0 : 1;
    }
    fprintf(stderr, "Daemon did not send a complete valid reply\n");
    close(fd);
    return 1;
}
