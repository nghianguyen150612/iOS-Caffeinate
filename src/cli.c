/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L
#include "schedule.h"
#include "service.h"
#include "server_mode.h"
#include "wake_capability.h"
#include <errno.h>
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
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define DEFAULT_SCHEDULE_STATE "/var/lib/ioscaffeinate/schedules.json"

typedef enum {
    SERVER_DAEMON_UNAVAILABLE = 0,
    SERVER_DAEMON_COMPATIBLE,
    SERVER_DAEMON_INCOMPATIBLE,
    SERVER_DAEMON_ERROR
} server_daemon_result_t;

static void usage(void) {
    puts("ios-caffeinate — jailbreak iOS server power-management CLI\n"
         "\n"
         "Usage:\n"
         "  ios-caffeinate [--socket /absolute/path.sock] probe\n"
         "  ios-caffeinate [--socket /absolute/path.sock] status\n"
         "  ios-caffeinate [--socket /absolute/path.sock] start --for 5m\n"
         "  ios-caffeinate [--socket /absolute/path.sock] start --until 2026-10-18T23:00:00+07:00\n"
         "  ios-caffeinate [--socket /absolute/path.sock] stop\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --at <ISO-8601> --for <duration>\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --daily <HH:MM> --for <duration> [--tz <TZ>]\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule add --weekly <days> --at <HH:MM> --for <duration> [--tz <TZ>]\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule list\n"
         "  ios-caffeinate [--socket /absolute/path.sock] schedule remove <schedule-id>\n"
         "  ios-caffeinate wake status\n"
         "  ios-caffeinate server status|doctor|plan\n"
         "  ios-caffeinate service status|doctor|plan|recovery status|recovery plan|recovery reset --reviewed-cleanup --reviewed-supervisor-state|enable|disable|start|stop|restart\n"
         "  ios-caffeinate server trial start --for 1s..5m\n"
         "  ios-caffeinate server trial stop\n"
         "  ios-caffeinate [--server-config /absolute/path] [--schedule-state /absolute/path] server status|doctor|plan\n"
         "\n"
         "Duration: seconds (s), minutes (m), or hours (h), maximum 24h.\n"
         "Alias: ic (filesystem symlink to ios-caffeinate).\n"
         "Only root can access the default daemon socket.\n");
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
    static char values[16][64];
    static size_t next_value;
    char *value = values[next_value++ % 16];
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

static int load_server_config(const char *path, server_config_t *config) {
    if (server_mode_config_load(path, config) != 0) {
        fprintf(stderr, "server configuration diagnostics failed\n");
        return -1;
    }
    return 0;
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
    const char *state = config.status == SERVER_CONFIG_INVALID || config.status == SERVER_CONFIG_UNSAFE
                            ? "BLOCKED"
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
            config.status == SERVER_CONFIG_INVALID || config.status == SERVER_CONFIG_UNSAFE
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

int main(int argc, char **argv) {
    const char *path = DEFAULT_SOCKET;
    const char *server_config_path = SERVER_MODE_CONFIG_DEFAULT;
    const char *schedule_path = DEFAULT_SCHEDULE_STATE;
    int i = 1;
    while (i < argc && argv[i][0] == '-' && argv[i][1] == '-' &&
           strcmp(argv[i], "--help") != 0) {
        if (i + 1 >= argc) { usage(); return 2; }
        if (strcmp(argv[i], "--socket") == 0) path = argv[i + 1];
        else if (strcmp(argv[i], "--server-config") == 0) server_config_path = argv[i + 1];
        else if (strcmp(argv[i], "--schedule-state") == 0) schedule_path = argv[i + 1];
        else { usage(); return 2; }
        i += 2;
    }
    if (i == argc || strcmp(argv[i], "help") == 0 || strcmp(argv[i], "--help") == 0) {
        usage(); return i + 1 == argc ? 0 : 2;
    }

    if (strcmp(argv[i], "service") == 0) {
        return service_command(argc - i - 1, argv + i + 1, stdout, stderr);
    }

    char command[512] = {0};

    if (strcmp(argv[i], "server") == 0) {
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
        if (strcmp(argv[i], "list") == 0 && i + 1 == argc) {
            strcpy(command, "SCHEDULE LIST\n");
        } else if (strcmp(argv[i], "remove") == 0 && i + 2 == argc) {
            snprintf(command, sizeof(command), "SCHEDULE REMOVE %s\n", argv[i + 1]);
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
            if (parse_duration(for_str, &duration) != 0) {
                fprintf(stderr, "Invalid --for duration. Use 1s..24h.\n");
                return 2;
            }

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
                snprintf(command, sizeof(command), "SCHEDULE ADD WEEKLY %u %02d:%02d %u %s\n",
                         (unsigned)mask, hour, min, duration, tz_str ? tz_str : "");
            } else if (daily_str) {
                int hour = 0, min = 0;
                if (parse_hhmm(daily_str, &hour, &min) != 0) {
                    fprintf(stderr, "Daily schedule requires --daily HH:MM.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD DAILY %02d:%02d %u %s\n",
                         hour, min, duration, tz_str ? tz_str : "");
            } else if (at_str) {
                time_t target_utc = parse_iso8601(at_str);
                if (target_utc == (time_t)-1) {
                    fprintf(stderr, "Invalid ISO-8601 timestamp for schedule --at. Explicit timezone offset required.\n");
                    return 2;
                }
                snprintf(command, sizeof(command), "SCHEDULE ADD ONETIME %lld %u\n",
                         (long long)target_utc, duration);
            } else { usage(); return 2; }
        } else { usage(); return 2; }
    } else { usage(); return 2; }

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
