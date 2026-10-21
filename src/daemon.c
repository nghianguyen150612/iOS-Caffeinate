/* Darwin hides BSD socket/locking declarations in strict POSIX mode. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L
#include "power.h"
#include "recovery.h"
#include "schedule.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_SOCKET "/var/run/ioscaffeinated.sock"
#define MAX_DURATION_SECONDS 86400
#define MAX_SERVER_TRIAL_SECONDS 300
#define MAX_RELEASE_ATTEMPTS 3

typedef enum {
    DAEMON_STATE_IDLE = 0,
    DAEMON_STATE_ACQUIRING,
    DAEMON_STATE_ACTIVE,
    DAEMON_STATE_RELEASING,
    DAEMON_STATE_RELEASE_FAILED,
    DAEMON_STATE_SHUTTING_DOWN,
    DAEMON_STATE_BLOCKED
} daemon_state_t;

static volatile sig_atomic_t keep_running = 1;
static daemon_state_t daemon_state = DAEMON_STATE_IDLE;
static bool clock_failed;
static uint32_t held_id;
static double deadline, retry_at;
static double daemon_started_at;
static time_t last_acquire_epoch;
static time_t last_release_epoch;
static char last_release_error[128] = "none";
static unsigned recent_errors;
static unsigned release_attempts;
static bool hold_is_trial;
static bool trial_stop_seen;
static bool trial_expired;
static const char *trial_state = "INACTIVE";
static bool state_invariant_reported;
static bool state_invariant_failed;
static const char *socket_path = DEFAULT_SOCKET;
static const char *schedule_file_path = NULL;
static const char *recovery_file_path = RECOVERY_DEFAULT_PATH;
static recovery_record_t recovery_record;
static bool recovery_assertions_blocked = true;
static bool recovery_journal_started;
static volatile sig_atomic_t termination_signal;
static recovery_exit_class_t process_exit_class = RECOVERY_EXIT_UNKNOWN_UNOBSERVED;
static int process_exit_signal;

static schedule_store_t sched_store;
static int current_active_sched_idx = -1;

static const char *daemon_state_name(daemon_state_t s) {
    switch (s) {
        case DAEMON_STATE_IDLE: return "IDLE";
        case DAEMON_STATE_ACQUIRING: return "ACQUIRING";
        case DAEMON_STATE_ACTIVE: return "ACTIVE";
        case DAEMON_STATE_RELEASING: return "RELEASING";
        case DAEMON_STATE_RELEASE_FAILED: return "RELEASE_FAILED";
        case DAEMON_STATE_SHUTTING_DOWN: return "SHUTTING_DOWN";
        case DAEMON_STATE_BLOCKED: return "BLOCKED";
    }
    return "UNKNOWN";
}

static void log_msg(const char *level, const char *fmt, ...) {
    time_t raw = time(NULL);
    struct tm tm_buf;
    struct tm *tm_info = localtime_r(&raw, &tm_buf);
    char time_str[32] = {0};
    if (tm_info) {
        strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", tm_info);
    } else {
        snprintf(time_str, sizeof(time_str), "0000-00-00 00:00:00");
    }
    fprintf(stderr, "[%s] [%s] ", time_str, level);
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
}

static double now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        clock_failed = true;
        keep_running = 0;
        return 0;
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static void on_signal(int sig) {
    termination_signal = sig;
    keep_running = 0;
}

static bool is_holding(void) {
    return held_id != 0;
}

static bool is_release_pending(void) {
    return daemon_state == DAEMON_STATE_RELEASING ||
           daemon_state == DAEMON_STATE_RELEASE_FAILED ||
           daemon_state == DAEMON_STATE_BLOCKED;
}

static void copy_error_token(char *out, size_t cap, const char *error) {
    size_t used = 0;
    if (cap == 0) return;
    while (error && *error && used + 1 < cap) {
        unsigned char c = (unsigned char)*error++;
        out[used++] = ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                       (c >= '0' && c <= '9') || c == '.' || c == '-') ? (char)c : '_';
    }
    out[used] = '\0';
    if (used == 0) snprintf(out, cap, "unknown");
}

static bool can_acquire(void) {
    return !recovery_assertions_blocked && held_id == 0 &&
           daemon_state == DAEMON_STATE_IDLE && !is_release_pending();
}

static const char *schedule_mutation_blocker(void) {
    if (recovery_assertions_blocked) return "recovery state is not verified";
    if (state_invariant_failed || held_id != 0 || daemon_state != DAEMON_STATE_IDLE ||
        is_release_pending()) return "daemon and assertion state must be idle";
    return NULL;
}

static const char *recovery_runtime_state(void) {
    if (!recovery_assertions_blocked) return "HEALTHY";
    if (recovery_record.last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
        recovery_record.last_exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN)
        return "CLEANUP_UNVERIFIED";
    return "RECOVERY_UNVERIFIED";
}

static const char *recovery_runtime_cleanup(void) {
    if (recovery_record.cleanup_state != RECOVERY_CLEANUP_CONFIRMED) return "UNVERIFIED";
    if (recovery_record.last_exit_class == RECOVERY_EXIT_RELEASE_FAILURE ||
        recovery_record.last_exit_class == RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN)
        return "REVIEW_REQUIRED";
    return recovery_record.last_exit_class == RECOVERY_EXIT_OPERATOR_REVIEWED_CLEANUP ?
           "OPERATOR_REVIEWED" : "CONFIRMED";
}

static const char *recovery_runtime_eligibility(void) {
    return recovery_record.cleanup_state == RECOVERY_CLEANUP_CONFIRMED &&
           recovery_record.last_exit_class != RECOVERY_EXIT_RELEASE_FAILURE &&
           recovery_record.last_exit_class != RECOVERY_EXIT_ASSERTION_OWNERSHIP_UNKNOWN ?
           "BLOCKED_SUPERVISOR_UNVERIFIED" : "BLOCK_CLEANUP_UNVERIFIED";
}

static void validate_runtime_state(void) {
    bool valid = true;
    if (daemon_state == DAEMON_STATE_IDLE && held_id != 0) valid = false;
    if ((daemon_state == DAEMON_STATE_ACTIVE || daemon_state == DAEMON_STATE_RELEASING ||
         daemon_state == DAEMON_STATE_RELEASE_FAILED) && held_id == 0) valid = false;
    if (daemon_state == DAEMON_STATE_ACQUIRING && held_id != 0) valid = false;
    if (valid) return;
    if (!state_invariant_reported) {
        state_invariant_reported = true;
        state_invariant_failed = true;
        recent_errors++;
        log_msg("ERROR", "Assertion ownership/state invariant failed; blocking new acquisitions");
    }
    copy_error_token(last_release_error, sizeof(last_release_error), "state invariant failure");
    if (held_id != 0) {
        daemon_state = DAEMON_STATE_RELEASE_FAILED;
        retry_at = 0;
    } else {
        daemon_state = DAEMON_STATE_BLOCKED;
    }
}

static int clear_hold(char *error, size_t cap) {
    if (held_id == 0) return 0;
    bool releasing_trial = hold_is_trial;
    daemon_state = DAEMON_STATE_RELEASING;
    release_attempts++;
    if (power_release(held_id, error, cap) != 0) {
        daemon_state = DAEMON_STATE_RELEASE_FAILED;
        recent_errors++;
        copy_error_token(last_release_error, sizeof(last_release_error), error);
        if (releasing_trial) trial_state = "RELEASE_FAILED";
        retry_at = release_attempts < MAX_RELEASE_ATTEMPTS ? now() + 1.0 : 0;
        if (recovery_journal_started) {
            recovery_record.last_exit_class = RECOVERY_EXIT_RELEASE_FAILURE;
            recovery_record.last_exit_signal = 0;
            recovery_record.cleanup_state = RECOVERY_CLEANUP_UNVERIFIED;
            recovery_assertions_blocked = true;
            char journal_error[256] = {0};
            if (recovery_store_save_atomic(recovery_file_path, geteuid(), &recovery_record,
                                           journal_error, sizeof(journal_error)) != 0)
                log_msg("ERROR", "Could not persist release-failure recovery state: %s", journal_error);
        }
        log_msg("ERROR", "Releasing assertion %u failed: %s; %s", held_id, error, power_diagnostics());
        return -1;
    }
    log_msg("INFO", "Released assertion %u; %s", held_id, power_diagnostics());
    last_release_epoch = time(NULL);
    if (releasing_trial) {
        if (trial_expired) trial_state = "EXPIRED";
        else if (trial_stop_seen) trial_state = "STOPPED";
        else trial_state = "RELEASED";
    }
    daemon_state = DAEMON_STATE_IDLE;
    held_id = 0;
    deadline = 0;
    retry_at = 0;
    hold_is_trial = false;
    current_active_sched_idx = -1;
    return 0;
}

static void expire_if_due(void) {
    double t = now();
    if (held_id != 0) {
        if (daemon_state == DAEMON_STATE_ACTIVE && t >= deadline) {
            char error[256];
            log_msg("INFO", "Assertion %u deadline reached; expiring hold", held_id);
            if (hold_is_trial) trial_expired = true;
            (void)clear_hold(error, sizeof(error));
        } else if (daemon_state == DAEMON_STATE_RELEASE_FAILED && retry_at > 0 && t >= retry_at) {
            char error[256];
            log_msg("WARN", "Retrying release for assertion %u", held_id);
            (void)clear_hold(error, sizeof(error));
        }
    }
}

static int check_peer_euid(int fd, uid_t *peer_euid) {
#if defined(__APPLE__)
    gid_t egid;
    if (getpeereid(fd, peer_euid, &egid) == 0) return 0;
    return -1;
#elif defined(__linux__)
    struct ucred cred;
    socklen_t len = sizeof(cred);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cred, &len) == 0) {
        *peer_euid = cred.uid;
        return 0;
    }
    return -1;
#else
    (void)fd; (void)peer_euid;
    return -1;
#endif
}

static int lock_socket_path(const char *path) {
    char lock_path[sizeof(((struct sockaddr_un *)0)->sun_path) + 6];
    snprintf(lock_path, sizeof(lock_path), "%s.lock", path);
    int fd = open(lock_path, O_CREAT | O_RDWR | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (fd < 0) { perror("open socket lock"); return -1; }
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        st.st_nlink != 1 || (st.st_mode & 0777) != 0600 || flock(fd, LOCK_EX | LOCK_NB) != 0) {
        log_msg("ERROR", "Socket lock unsafe or daemon already running: %s", lock_path);
        close(fd);
        return -1;
    }
    return fd;
}

static int prepare_socket(const char *path) {
    struct stat st;
    if (lstat(path, &st) == 0) {
        if (!S_ISSOCK(st.st_mode) || st.st_uid != geteuid()) {
            log_msg("ERROR", "Refusing to delete non-owned or non-socket path: %s", path);
            return -1;
        }
        int test_fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (test_fd < 0) return -1;
        if (fcntl(test_fd, F_SETFL, O_NONBLOCK) != 0) { close(test_fd); return -1; }
        struct sockaddr_un addr = {0};
        addr.sun_family = AF_UNIX;
        snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);
        int connected = connect(test_fd, (struct sockaddr *)&addr, sizeof(addr));
        int saved_errno = errno;
        close(test_fd);
        if (connected == 0 || saved_errno != ECONNREFUSED) {
            log_msg("ERROR", "Socket appears active or unsafe to replace: %s", path);
            return -1;
        }
        if (unlink(path) != 0) { perror("unlink stale socket"); return -1; }
    } else if (errno != ENOENT) { perror("lstat socket"); return -1; }
    return 0;
}

static int remove_owned_socket(const struct stat *bound) {
    struct stat st;
    if (lstat(socket_path, &st) == 0 && S_ISSOCK(st.st_mode) &&
        st.st_dev == bound->st_dev && st.st_ino == bound->st_ino) {
        if (unlink(socket_path) != 0) { perror("unlink socket"); return -1; }
    }
    return 0;
}

static int respond(int fd, const char *message) {
    size_t len = strlen(message);
    while (len && keep_running) {
        ssize_t n = send(fd, message, len, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        message += n;
        len -= (size_t)n;
    }
    return len ? -1 : 0;
}

static void reply_error(int fd, const char *operation, const char *error) {
    char out[1024];
    snprintf(out, sizeof(out), "ERR %s: %s backend=%s type=PreventUserIdleSystemSleep %s\n",
             operation, error, power_backend_name(), power_diagnostics());
    respond(fd, out);
}

static bool is_read_only_status_prefix(const char *command, size_t length) {
    static const char *const commands[] = {"STATUS\n", "SERVER STATUS\n"};
    if (length == 0) return false;
    for (size_t i = 0; i < sizeof(commands) / sizeof(commands[0]); ++i) {
        size_t command_length = strlen(commands[i]);
        if (length <= command_length && memcmp(command, commands[i], length) == 0) return true;
    }
    return false;
}

static int read_command(int fd, char *command, size_t cap) {
    size_t used = 0;
    double until = now() + 1.0;
    while (keep_running && now() < until) {
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int rc = poll(&pfd, 1, 50);
        if (rc < 0 && errno == EINTR) continue;
        if (rc < 0) return -1;
        if (rc == 0) {
            if (!is_read_only_status_prefix(command, used)) expire_if_due();
            continue;
        }
        ssize_t n = recv(fd, command + used, cap - 1 - used, MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) break;
        size_t total = used + (size_t)n;
        for (size_t i = used; i < total; ++i) {
            unsigned char c = (unsigned char)command[i];
            if (c == '\n') {
                if (i + 1 != total) goto malformed;
                command[i] = '\0';
                return 0;
            }
            if (c < 32 || c > 126) goto malformed;
        }
        used = total;
        if (used == cap - 1) goto malformed;
        if (!is_read_only_status_prefix(command, used)) expire_if_due();
    }
malformed:
    respond(fd, "ERR malformed or incomplete command\n");
    return -1;
}

static void handle_client(int fd) {
    struct timeval tv = {.tv_sec = 1, .tv_usec = 0};
    if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)) != 0) return;

    uid_t peer_uid = (uid_t)-1;
    if (check_peer_euid(fd, &peer_uid) != 0) {
        log_msg("WARN", "Rejecting client connection: unable to verify peer credentials");
        respond(fd, "ERR permission denied: unable to verify peer credentials\n");
        return;
    }

    uid_t required_uid = (strcmp(socket_path, DEFAULT_SOCKET) == 0) ? 0 : geteuid();
    if (peer_uid != required_uid) {
        log_msg("WARN", "Rejecting client connection: peer UID %u != required UID %u",
                (unsigned)peer_uid, (unsigned)required_uid);
        respond(fd, "ERR permission denied: unauthorized client UID\n");
        return;
    }

    char command[512];
    if (read_command(fd, command, sizeof(command)) != 0 || !keep_running) return;
    /* A status query is observational.  The event loop owns deadline expiry;
     * servicing a read-only client request must not itself release a hold. */
    if (strcmp(command, "STATUS") != 0 && strcmp(command, "SERVER STATUS") != 0)
        expire_if_due();

    if (strcmp(command, "STATUS") == 0) {
        char out[1024];
        double left = (daemon_state == DAEMON_STATE_ACTIVE) ? (deadline - now()) : 0;
        unsigned remaining = left > 0 ? (unsigned)left + 1 : 0;
        snprintf(out, sizeof(out), "OK active=%s state=%s remaining_seconds=%u assertion_id=%u release_pending=%s schedule_count=%zu recovery_state=%s recovery_last_exit=%s recovery_attempt_budget=%u/%u recovery_cooldown=INACTIVE recovery_cleanup=%s recovery_restart_eligibility=%s recovery_supervisor=UNVERIFIED recovery_runtime_activated=no recovery_schedule_gate=%s backend=%s type=PreventUserIdleSystemSleep %s\n",
                 is_holding() ? "yes" : "no", daemon_state_name(daemon_state),
                 remaining, held_id, is_release_pending() ? "yes" : "no",
                 sched_store.count,
                 recovery_runtime_state(),
                 recovery_exit_class_name(recovery_record.last_exit_class),
                 RECOVERY_MAX_ATTEMPTS - recovery_record.attempt_count, RECOVERY_MAX_ATTEMPTS,
                 recovery_runtime_cleanup(), recovery_runtime_eligibility(),
                 recovery_assertions_blocked ? "BLOCKED" : "OPEN",
                 power_backend_name(), power_diagnostics());
        respond(fd, out);
#ifdef IOSCAFFEINATE_TEST_MOCK
    } else if (strcmp(command, "TEST INVALID STATE") == 0) {
        /* Fault injection is present only in explicitly gated Linux mocks. */
        daemon_state = DAEMON_STATE_ACTIVE;
        held_id = 0;
        respond(fd, "OK fault_injected=yes\n");
#endif
    } else if (strcmp(command, "SERVER STATUS") == 0) {
        char out[2048];
        char acquire_epoch[32], release_epoch[32];
        double elapsed = daemon_started_at > 0 ? now() - daemon_started_at : 0;
        double left = (daemon_state == DAEMON_STATE_ACTIVE) ? deadline - now() : 0;
        unsigned remaining = left > 0 ? (unsigned)left + 1 : 0;
        const char *source = !is_holding() ? "none" : hold_is_trial ? "server_trial" :
                             current_active_sched_idx >= 0 ? "scheduled_awake" : "bounded_hold";
        const char *schedule_active = current_active_sched_idx >= 0 ? "yes" : "no";
        if (last_acquire_epoch > 0)
            snprintf(acquire_epoch, sizeof(acquire_epoch), "%lld", (long long)last_acquire_epoch);
        else snprintf(acquire_epoch, sizeof(acquire_epoch), "UNAVAILABLE");
        if (last_release_epoch > 0)
            snprintf(release_epoch, sizeof(release_epoch), "%lld", (long long)last_release_epoch);
        else snprintf(release_epoch, sizeof(release_epoch), "UNAVAILABLE");
        snprintf(out, sizeof(out),
                 "OK SERVER protocol=1 uptime_seconds=%u state=%s state_invariant=%s active=%s assertion_owned=%s assertion_id=%u source=%s trial=%s trial_state=%s trial_stop_seen=%s remaining_seconds=%u release_pending=%s release_attempts=%u last_acquire_epoch=%s last_release_epoch=%s last_release_error=%s schedule_count=%zu schedule_active=%s recovery_state=%s recovery_last_exit=%s recovery_attempt_budget=%u/%u recovery_cooldown=INACTIVE recovery_cleanup=%s recovery_restart_eligibility=%s recovery_supervisor=UNVERIFIED recovery_runtime_activated=no recovery_schedule_gate=%s recent_errors=%u backend=%s backend_verification=UNVERIFIED backend_diagnostics=%s\n",
                 elapsed > 0 ? (unsigned)elapsed : 0, daemon_state_name(daemon_state),
                 state_invariant_failed ? "ERROR" : "OK",
                 is_holding() ? "yes" : "no", is_holding() ? "1" : "0", held_id,
                 source, hold_is_trial && is_holding() ? "yes" : "no",
                 trial_state, trial_stop_seen ? "yes" : "no", remaining,
                 is_release_pending() ? "yes" : "no", release_attempts,
                 acquire_epoch, release_epoch, last_release_error,
                 sched_store.count, schedule_active,
                 recovery_runtime_state(),
                 recovery_exit_class_name(recovery_record.last_exit_class),
                 RECOVERY_MAX_ATTEMPTS - recovery_record.attempt_count, RECOVERY_MAX_ATTEMPTS,
                 recovery_runtime_cleanup(), recovery_runtime_eligibility(),
                 recovery_assertions_blocked ? "BLOCKED" : "OPEN", recent_errors,
                 power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "PROBE") == 0) {
        if (recovery_assertions_blocked) {
            respond(fd, "ERR recovery blocked: prior assertion cleanup is unverified\n");
            return;
        }
        if (!can_acquire()) {
            respond(fd, "ERR already active; stop before probing\n");
            return;
        }
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            recent_errors++;
            reply_error(fd, "acquire", error);
            held_id = 0;
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now();
        last_acquire_epoch = time(NULL);
        release_attempts = 0;
        hold_is_trial = false;
        uint32_t probe_id = held_id;
        if (clear_hold(error, sizeof(error)) != 0) {
            reply_error(fd, "release", error);
            return;
        }
        char out[1024];
        snprintf(out, sizeof(out), "OK probe=acquire_release assertion_id=%u backend=%s type=PreventUserIdleSystemSleep %s\n",
                 probe_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strncmp(command, "TRIAL START ", 12) == 0) {
        const char *value = command + 12;
        if (*value < '0' || *value > '9') { respond(fd, "ERR invalid trial duration\n"); return; }
        errno = 0;
        char *end = NULL;
        unsigned long long duration = strtoull(value, &end, 10);
        if (errno || *end || duration == 0 || duration > MAX_SERVER_TRIAL_SECONDS) {
            respond(fd, "ERR server trial duration must be 1..300 seconds\n"); return;
        }
        if (!can_acquire()) {
            respond(fd, recovery_assertions_blocked ?
                    "ERR recovery blocked: prior assertion cleanup is unverified\n" :
                    "ERR assertion owner is busy; stop the current hold before a trial\n");
            return;
        }
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            recent_errors++;
            held_id = 0;
            reply_error(fd, "trial acquire", error);
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now() + (double)duration;
        current_active_sched_idx = -1;
        last_acquire_epoch = time(NULL);
        release_attempts = 0;
        hold_is_trial = true;
        trial_stop_seen = false;
        trial_expired = false;
        trial_state = "ACTIVE";
        log_msg("INFO", "Acquired explicit server trial assertion %u for %llu seconds; %s",
                held_id, duration, power_diagnostics());
        char out[1024];
        snprintf(out, sizeof(out), "OK trial=active duration_seconds=%llu assertion_id=%u backend=%s %s\n",
                 duration, held_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "TRIAL STOP") == 0) {
        if (!hold_is_trial || !is_holding()) {
            respond(fd, "OK trial=inactive already_stopped=yes\n");
            return;
        }
        char error[256] = {0};
        trial_stop_seen = true;
        trial_expired = false;
        trial_state = "STOPPED";
        if (clear_hold(error, sizeof(error)) != 0) reply_error(fd, "trial release", error);
        else respond(fd, "OK trial=stopped active=no release_rc=0x00000000\n");
    } else if (strncmp(command, "START ", 6) == 0) {
        const char *value = command + 6;
        if (*value < '0' || *value > '9') { respond(fd, "ERR invalid duration\n"); return; }
        errno = 0;
        char *end = NULL;
        unsigned long long duration = strtoull(value, &end, 10);
        if (errno || *end || duration == 0 || duration > MAX_DURATION_SECONDS) {
            respond(fd, "ERR duration must be 1..86400 seconds\n"); return;
        }
        if (recovery_assertions_blocked) {
            respond(fd, "ERR recovery blocked: prior assertion cleanup is unverified\n");
            return;
        }
        if (!can_acquire()) {
            respond(fd, "ERR already active; stop before restarting\n");
            return;
        }
        daemon_state = DAEMON_STATE_ACQUIRING;
        char error[256] = {0};
        if (power_acquire(&held_id, error, sizeof(error)) != 0) {
            daemon_state = DAEMON_STATE_IDLE;
            recent_errors++;
            reply_error(fd, "acquire", error);
            held_id = 0;
            return;
        }
        daemon_state = DAEMON_STATE_ACTIVE;
        deadline = now() + (double)duration;
        current_active_sched_idx = -1;
        last_acquire_epoch = time(NULL);
        release_attempts = 0;
        hold_is_trial = false;
        log_msg("INFO", "Acquired assertion %u for %llu seconds; %s", held_id, duration, power_diagnostics());
        char out[1024];
        snprintf(out, sizeof(out), "OK active=yes duration_seconds=%llu assertion_id=%u backend=%s %s\n",
                 duration, held_id, power_backend_name(), power_diagnostics());
        respond(fd, out);
    } else if (strcmp(command, "STOP") == 0) {
        char error[256] = {0};
        if (!is_holding()) respond(fd, "OK already_stopped=yes\n");
        else {
            if (hold_is_trial) {
                trial_stop_seen = true;
                trial_expired = false;
                trial_state = "STOPPED";
            }
            if (clear_hold(error, sizeof(error)) != 0) reply_error(fd, "release", error);
            else respond(fd, "OK active=no release_rc=0x00000000\n");
        }
    } else if (strcmp(command, "SHUTDOWN") == 0) {
        if (daemon_state == DAEMON_STATE_RELEASE_FAILED || daemon_state == DAEMON_STATE_BLOCKED ||
            daemon_state == DAEMON_STATE_RELEASING || daemon_state == DAEMON_STATE_ACQUIRING) {
            respond(fd, "ERR shutdown blocked: assertion or daemon state is unresolved\n");
            return;
        }
        char error[256] = {0};
        if (clear_hold(error, sizeof(error)) != 0) {
            reply_error(fd, "shutdown assertion release", error);
            return;
        }
        respond(fd, "OK shutdown=accepted assertion_released=yes\n");
        process_exit_class = RECOVERY_EXIT_EXPLICIT_STOP;
        keep_running = false;
    } else if (strcmp(command, "SCHEDULE LIST") == 0) {
        char out[16384] = "OK schedules=";
        char item_str[256];
        snprintf(out + strlen(out), sizeof(out) - strlen(out), "%zu\n", sched_store.count);
        for (size_t i = 0; i < sched_store.count; ++i) {
            const schedule_t *s = &sched_store.items[i];
            if (s->type == SCHED_TYPE_ONETIME) {
                char iso_time[32] = {0};
                format_iso8601_utc(s->target_time, iso_time, sizeof(iso_time));
                snprintf(item_str, sizeof(item_str), "  id=%s type=onetime target=%s duration=%us\n",
                         s->id, iso_time, s->duration);
            } else if (s->type == SCHED_TYPE_DAILY) {
                snprintf(item_str, sizeof(item_str), "  id=%s type=daily time=%02d:%02d duration=%us tz=%s\n",
                         s->id, s->hour, s->minute, s->duration, s->tz[0] ? s->tz : "system");
            } else if (s->type == SCHED_TYPE_WEEKLY) {
                snprintf(item_str, sizeof(item_str), "  id=%s type=weekly days_mask=0x%02x time=%02d:%02d duration=%us tz=%s\n",
                         s->id, (unsigned)s->days_mask, s->hour, s->minute, s->duration, s->tz[0] ? s->tz : "system");
            }
            strncat(out, item_str, sizeof(out) - strlen(out) - 1);
        }
        respond(fd, out);
    } else if (strncmp(command, "SCHEDULE REMOVE ", 16) == 0) {
        char id[SCHED_ID_LEN] = {0}, generation_text[17] = {0}, extra = '\0';
        if (sscanf(command + 16, "%31s %16s %c", id, generation_text, &extra) != 2 ||
            strlen(generation_text) != 16) {
            respond(fd, "ERR schedule remove requires an ID and generation precondition\n");
            return;
        }
        errno = 0;
        char *generation_end = NULL;
        unsigned long long expected = strtoull(generation_text, &generation_end, 16);
        if (errno || generation_end == generation_text || *generation_end ||
            schedule_store_generation(&sched_store) != (uint64_t)expected) {
            respond(fd, "ERR stale schedule generation; reload before editing\n");
            return;
        }
        const char *mutation_blocker = schedule_mutation_blocker();
        if (mutation_blocker) {
            char out[192];
            snprintf(out, sizeof(out), "ERR schedule mutation blocked: %s\n", mutation_blocker);
            respond(fd, out);
            return;
        }
        char err_buf[256] = {0};
        if (schedule_store_remove(&sched_store, id, err_buf, sizeof(err_buf)) != 0) {
            reply_error(fd, "schedule remove", err_buf);
        } else {
            respond(fd, "OK schedule_removed=yes changed=yes\n");
        }
    } else if (strncmp(command, "SCHEDULE SET_ENABLED ", 21) == 0) {
        char id[SCHED_ID_LEN] = {0}, enabled_text[8] = {0};
        char generation_text[17] = {0}, extra = '\0';
        if (sscanf(command + 21, "%31s %7s %16s %c", id, enabled_text,
                   generation_text, &extra) != 3 || strlen(generation_text) != 16 ||
            (strcmp(enabled_text, "0") != 0 && strcmp(enabled_text, "1") != 0)) {
            respond(fd, "ERR invalid schedule enable arguments\n");
            return;
        }
        errno = 0;
        char *generation_end = NULL;
        unsigned long long expected = strtoull(generation_text, &generation_end, 16);
        if (errno || generation_end == generation_text || *generation_end) {
            respond(fd, "ERR invalid schedule generation precondition\n");
            return;
        }
        const char *mutation_blocker = schedule_mutation_blocker();
        if (mutation_blocker) {
            char out[192];
            snprintf(out, sizeof(out), "ERR schedule mutation blocked: %s\n", mutation_blocker);
            respond(fd, out);
            return;
        }
        char err_buf[256] = {0};
        int changed = 0;
        if (schedule_store_set_enabled(&sched_store, id, strcmp(enabled_text, "1") == 0,
                                       (uint64_t)expected, &changed,
                                       err_buf, sizeof(err_buf)) != 0) {
            reply_error(fd, "schedule enable", err_buf);
        } else {
            char out[256];
            snprintf(out, sizeof(out), "OK schedule_enabled=%s changed=%s generation=%016llx\n",
                     strcmp(enabled_text, "1") == 0 ? "yes" : "no",
                     changed ? "yes" : "no",
                     (unsigned long long)schedule_store_generation(&sched_store));
            respond(fd, out);
        }
    } else if (strncmp(command, "SCHEDULE ADD ", 13) == 0) {
        const char *sub = command + 13;
        char err_buf[256] = {0};
        schedule_t item;
        memset(&item, 0, sizeof(item));

        if (strncmp(sub, "ONETIME ", 8) == 0) {
            long long target_time = 0;
            unsigned duration = 0;
            char generation_text[17] = {0}, extra = '\0';
            if (sscanf(sub + 8, "%lld %u %16s %c", &target_time, &duration,
                       generation_text, &extra) != 3 || duration < 1 ||
                duration > SCHEDULE_MAX_SESSION_SECONDS || strlen(generation_text) != 16 ||
                (long long)(time_t)target_time != target_time) {
                respond(fd, "ERR invalid ONETIME schedule arguments\n");
                return;
            }
            errno = 0;
            char *generation_end = NULL;
            unsigned long long expected = strtoull(generation_text, &generation_end, 16);
            if (errno || generation_end == generation_text || *generation_end ||
                schedule_store_generation(&sched_store) != (uint64_t)expected) {
                respond(fd, "ERR stale schedule generation; reload before editing\n");
                return;
            }
            item.type = SCHED_TYPE_ONETIME;
            item.target_time = (time_t)target_time;
            item.duration = duration;
        } else if (strncmp(sub, "DAILY ", 6) == 0) {
            int h = 0, m = 0;
            unsigned duration = 0;
            char tz[TZ_LEN] = {0}, generation_text[17] = {0}, extra = '\0';
            int ret = sscanf(sub + 6, "%02d:%02d %u %63s %16s %c",
                             &h, &m, &duration, tz, generation_text, &extra);
            if (ret != 5 || duration < 1 || duration > SCHEDULE_MAX_SESSION_SECONDS ||
                h < 0 || h > 23 || m < 0 || m > 59 || strlen(generation_text) != 16) {
                respond(fd, "ERR invalid DAILY schedule arguments\n");
                return;
            }
            errno = 0;
            char *generation_end = NULL;
            unsigned long long expected = strtoull(generation_text, &generation_end, 16);
            if (errno || generation_end == generation_text || *generation_end ||
                schedule_store_generation(&sched_store) != (uint64_t)expected) {
                respond(fd, "ERR stale schedule generation; reload before editing\n");
                return;
            }
            item.type = SCHED_TYPE_DAILY;
            item.hour = h;
            item.minute = m;
            item.duration = duration;
            if (strcmp(tz, "-") != 0) snprintf(item.tz, sizeof(item.tz), "%s", tz);
        } else if (strncmp(sub, "WEEKLY ", 7) == 0) {
            unsigned mask = 0, duration = 0;
            int h = 0, m = 0;
            char tz[TZ_LEN] = {0}, generation_text[17] = {0}, extra = '\0';
            int ret = sscanf(sub + 7, "%u %02d:%02d %u %63s %16s %c",
                             &mask, &h, &m, &duration, tz, generation_text, &extra);
            if (ret != 6 || duration < 1 || duration > SCHEDULE_MAX_SESSION_SECONDS ||
                h < 0 || h > 23 || m < 0 || m > 59 || mask == 0 || mask > 127 ||
                strlen(generation_text) != 16) {
                respond(fd, "ERR invalid WEEKLY schedule arguments\n");
                return;
            }
            errno = 0;
            char *generation_end = NULL;
            unsigned long long expected = strtoull(generation_text, &generation_end, 16);
            if (errno || generation_end == generation_text || *generation_end ||
                schedule_store_generation(&sched_store) != (uint64_t)expected) {
                respond(fd, "ERR stale schedule generation; reload before editing\n");
                return;
            }
            item.type = SCHED_TYPE_WEEKLY;
            item.days_mask = (uint8_t)mask;
            item.hour = h;
            item.minute = m;
            item.duration = duration;
            if (strcmp(tz, "-") != 0) snprintf(item.tz, sizeof(item.tz), "%s", tz);
        } else {
            respond(fd, "ERR unknown schedule add type\n");
            return;
        }

        const char *mutation_blocker = schedule_mutation_blocker();
        if (mutation_blocker) {
            char out[192];
            snprintf(out, sizeof(out), "ERR schedule mutation blocked: %s\n", mutation_blocker);
            respond(fd, out);
            return;
        }

        if (schedule_store_add(&sched_store, &item, err_buf, sizeof(err_buf)) != 0) {
            reply_error(fd, "schedule add", err_buf);
        } else {
            char out[256];
            snprintf(out, sizeof(out), "OK schedule_added=yes id=%s\n", item.id);
            respond(fd, out);
        }
    } else respond(fd, "ERR unknown command\n");
}

static void usage(const char *exe) {
    fprintf(stderr, "Usage: %s [--socket /absolute/path.sock] [--schedules /path/to/schedules.json] [--recovery-state /path/to/recovery-state.json] [--foreground]\n", exe);
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--foreground") == 0) continue;
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) socket_path = argv[++i];
        else if (strcmp(argv[i], "--schedules") == 0 && i + 1 < argc) schedule_file_path = argv[++i];
        else if (strcmp(argv[i], "--recovery-state") == 0 && i + 1 < argc) recovery_file_path = argv[++i];
        else { usage(argv[0]); return 2; }
    }
    if (*socket_path != '/' || strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Socket path must be absolute and fit sockaddr_un\n"); return 2;
    }
    if (schedule_file_path &&
        (*schedule_file_path != '/' || strlen(schedule_file_path) >= sizeof(sched_store.state_file_path))) {
        fprintf(stderr, "Schedule state path must be absolute and fit the supported path bound\n"); return 2;
    }
    if (!recovery_file_path || recovery_file_path[0] != '/' || strlen(recovery_file_path) >= 512) {
        fprintf(stderr, "Recovery state path must be absolute and fit the supported path bound\n"); return 2;
    }
    if (strcmp(socket_path, DEFAULT_SOCKET) == 0 && geteuid() != 0) {
        fprintf(stderr, "Default socket requires root; use a private --socket directory for tests\n"); return 1;
    }

    schedule_store_init(&sched_store, schedule_file_path);
    char sched_err[256] = {0};
    if (schedule_store_load(&sched_store, sched_err, sizeof(sched_err)) != 0) {
        fprintf(stderr, "Failed to load schedules: %s\n", sched_err);
        return 1;
    }

    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGTERM, &sa, NULL) != 0 || sigaction(SIGINT, &sa, NULL) != 0 ||
        signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("signal setup"); return 1; }
    daemon_started_at = now();
    umask(0077);
    int lock_fd = lock_socket_path(socket_path);
    if (lock_fd < 0) return 1;
    if (prepare_socket(socket_path) != 0) { close(lock_fd); return 1; }
    int listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (listen_fd < 0) { perror("socket"); close(lock_fd); return 1; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", socket_path);
    if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("bind"); close(listen_fd); close(lock_fd); return 1;
    }
    struct stat bound;
    if (lstat(socket_path, &bound) != 0) {
        perror("lstat bound socket"); close(listen_fd); close(lock_fd); return 1;
    }
    int result = 0;
    if (chmod(socket_path, 0600) != 0 || listen(listen_fd, 8) != 0) {
        perror("chmod/listen"); result = 1; goto cleanup;
    }
    char recovery_error[256] = {0};
    int assertions_blocked = 1;
    recovery_record_init(&recovery_record);
    if (recovery_store_begin_run(recovery_file_path, geteuid(), &recovery_record,
                                 &assertions_blocked, recovery_error,
                                 sizeof(recovery_error)) == 0) {
        recovery_journal_started = true;
        recovery_assertions_blocked = assertions_blocked != 0;
    } else {
        recovery_assertions_blocked = true;
        log_msg("ERROR", "Recovery journal unavailable; new assertions are blocked: %s", recovery_error);
    }
    log_msg("INFO", "ios-caffeinated starting: socket=%s backend=%s schedules=%zu executor=NOT_AUTHORIZED",
            socket_path, power_backend_name(), sched_store.count);
    if (sched_store.count > 0)
        log_msg("WARN", "Persistent schedule definitions are retained for diagnostics; automatic assertion execution is not authorized by P015");
    if (recovery_assertions_blocked)
        log_msg("WARN", "Recovery state is unverified; schedule, probe, trial, and manual assertion acquisition are blocked");
    else
        log_msg("INFO", "Recovery journal confirms prior cleanup; current daemon generation is recorded");

    while (keep_running) {
        validate_runtime_state();
        expire_if_due();

        /* A stored future occurrence is not a wake source. Do not poll or
         * acquire power assertions on behalf of schedule definitions. */
        int timeout_ms = -1;
        double t_now = now();
        if (daemon_state == DAEMON_STATE_ACTIVE && deadline > t_now) {
            double left = deadline - t_now;
            int ms = (int)(left * 1000.0);
            if (ms < 0) ms = 0;
            timeout_ms = ms;
        } else if (daemon_state == DAEMON_STATE_RELEASE_FAILED && retry_at > t_now) {
            double left = retry_at - t_now;
            int ms = (int)(left * 1000.0);
            if (ms < 0) ms = 0;
            timeout_ms = ms;
        }

        struct pollfd pfd = {.fd = listen_fd, .events = POLLIN};
        int ret = poll(&pfd, 1, timeout_ms);
        if (ret < 0) {
            if (errno == EINTR) continue;
            perror("poll"); result = 1; break;
        }
        if (ret > 0 && (pfd.revents & POLLIN)) {
            int client = accept(listen_fd, NULL, NULL);
            if (client >= 0) { handle_client(client); close(client); }
            else if (errno != EINTR) { perror("accept"); result = 1; break; }
        }
    }
cleanup:;
    log_msg("INFO", "ios-caffeinated shutting down");
    char error[256] = {0};
    int current_cleanup_confirmed = clear_hold(error, sizeof(error)) == 0;
    if (!current_cleanup_confirmed) {
        log_msg("ERROR", "UNRESOLVED assertion release at exit; device verification required");
        result = 1;
        process_exit_class = RECOVERY_EXIT_RELEASE_FAILURE;
    }
    if (process_exit_class == RECOVERY_EXIT_UNKNOWN_UNOBSERVED) {
        if (termination_signal) {
            process_exit_class = RECOVERY_EXIT_SIGNAL_TERMINATION;
            process_exit_signal = (int)termination_signal;
        } else process_exit_class = result == 0 ? RECOVERY_EXIT_GRACEFUL_CONFIRMED :
                                                  RECOVERY_EXIT_UNEXPECTED_EXIT;
    }
    daemon_state = DAEMON_STATE_SHUTTING_DOWN;
    close(listen_fd);
    if (remove_owned_socket(&bound) != 0 || clock_failed) result = 1;
    if (recovery_journal_started &&
        recovery_store_finish_run(recovery_file_path, geteuid(), &recovery_record,
                                  current_cleanup_confirmed, process_exit_class,
                                  process_exit_signal, recovery_error,
                                  sizeof(recovery_error)) != 0) {
        log_msg("ERROR", "Could not persist final recovery classification; next start will remain blocked: %s",
                recovery_error);
        result = 1;
    }
    close(lock_fd);
    power_cleanup();
    return result;
}
