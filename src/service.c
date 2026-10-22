/*
 * P013 service inspection and guarded lifecycle support.
 * No launchctl mutation syntax is assumed. On the iOS 12 target, mutations
 * remain blocked until a supervised device investigation establishes the
 * relevant semantics.
 */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L

#include "service.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_DIRECTORY
#define O_DIRECTORY 0
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif
#ifndef S_ISVTX
#define S_ISVTX 01000
#endif

#define SERVICE_MAX_PATH PATH_MAX
#define SERVICE_MAX_PLIST 4096
#define SERVICE_CAPTURE_SIZE 16384
#define SERVICE_STOP_TIMEOUT_SECONDS 5

static char *const service_child_environment[] = {
    "PATH=/usr/bin:/bin",
    "LANG=C",
    "LC_ALL=C",
    NULL
};

static const char managed_enabled_plist[] =
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
    "<plist version=\"1.0\">\n"
    "<dict>\n"
    "  <key>Label</key><string>com.ioscaffeinate.daemon</string>\n"
    "  <key>Disabled</key><false/>\n"
    "  <key>ProgramArguments</key>\n"
    "  <array>\n"
    "    <string>/usr/local/bin/ios-caffeinated</string>\n"
    "    <string>--foreground</string>\n"
    "  </array>\n"
    "  <key>RunAtLoad</key><false/>\n"
    "  <key>KeepAlive</key><false/>\n"
    "  <key>StandardOutPath</key><string>/var/log/ioscaffeinate/daemon.log</string>\n"
    "  <key>StandardErrorPath</key><string>/var/log/ioscaffeinate/daemon.err</string>\n"
    "</dict>\n"
    "</plist>\n";

static const char managed_disabled_plist[] =
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
    "<plist version=\"1.0\">\n"
    "<dict>\n"
    "  <key>Label</key><string>com.ioscaffeinate.daemon</string>\n"
    "  <key>Disabled</key><true/>\n"
    "  <key>ProgramArguments</key>\n"
    "  <array>\n"
    "    <string>/usr/local/bin/ios-caffeinated</string>\n"
    "    <string>--foreground</string>\n"
    "  </array>\n"
    "  <key>RunAtLoad</key><false/>\n"
    "  <key>KeepAlive</key><false/>\n"
    "  <key>StandardOutPath</key><string>/var/log/ioscaffeinate/daemon.log</string>\n"
    "  <key>StandardErrorPath</key><string>/var/log/ioscaffeinate/daemon.err</string>\n"
    "</dict>\n"
    "</plist>\n";

static const char packaged_template[] =
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
    "<plist version=\"1.0\">\n"
    "<dict>\n"
    "  <key>Label</key><string>com.ioscaffeinate.daemon</string>\n"
    "  <!-- Do NOT activate before physical runtime validation. -->\n"
    "  <key>Disabled</key><true/>\n"
    "  <key>ProgramArguments</key>\n"
    "  <array>\n"
    "    <string>/usr/local/bin/ios-caffeinated</string>\n"
    "    <string>--foreground</string>\n"
    "  </array>\n"
    "  <key>RunAtLoad</key><false/>\n"
    "  <key>KeepAlive</key><true/>\n"
    "  <key>StandardOutPath</key><string>/var/log/ioscaffeinate/daemon.log</string>\n"
    "  <key>StandardErrorPath</key><string>/var/log/ioscaffeinate/daemon.err</string>\n"
    "</dict>\n"
    "</plist>\n";

static const char *inspect_regular_path(const char *path, uid_t owner, mode_t mode,
                                        int require_exec, const char *expected_content,
                                        char *detail, size_t detail_cap);
static const char *package_database_state(void);
static int launchctl_path_status(void);
static int secure_launchctl_present(void);
static int run_launchctl(const char *subcommand, char *output, size_t output_cap,
                         int *exit_status, int *truncated);
static int list_has_label(const char *output, const char *label, char *pid_out, size_t pid_cap);

typedef struct {
    int launchctl_present;
    int help_exit;
    int list_exit;
    int help_truncated;
    int list_truncated;
    char help[SERVICE_CAPTURE_SIZE];
    char list[SERVICE_CAPTURE_SIZE];
    const char *help_state;
    const char *launchctl_path;
    const char *registration;
    const char *registration_pid;
    const char *runtime;
    const char *ipc;
    const char *assertion;
    const char *daemon_state;
    const char *state_invariant;
    const char *release_pending;
    const char *managed_plist;
    const char *enablement;
    const char *package;
    const char *package_database;
    const char *staged;
    const char *socket_state;
    const char *state;
    const char *last_shutdown;
    int live_plist_exists;
    int live_plist_enabled;
    char daemon_reply[4096];
    char blocker[256];
} service_snapshot_t;

#ifdef IOSCAFFEINATE_SERVICE_TESTING
static service_test_runner_fn test_runner;
static void *test_runner_context;

void service_test_set_runner(service_test_runner_fn runner, void *context) {
    test_runner = runner;
    test_runner_context = context;
}
#endif

static void detail_set(char *detail, size_t cap, const char *message) {
    if (detail && cap) snprintf(detail, cap, "%s", message ? message : "unknown error");
}

static int directory_is_safe(const struct stat *st, uid_t owner, int final_parent) {
    if (!S_ISDIR(st->st_mode)) return 0;
    if (st->st_uid == owner && (st->st_mode & (S_IWGRP | S_IWOTH)) == 0) return 1;
    if (!final_parent && st->st_uid == 0 && (st->st_mode & S_ISVTX) != 0) return 1;
    return 0;
}

/* Walk absolute directory components from / without following links. */
static int open_parent(const char *path, uid_t owner, int *parent_fd,
                       char *basename, size_t basename_cap,
                       char *detail, size_t detail_cap) {
    if (!path || path[0] != '/' || strlen(path) >= SERVICE_MAX_PATH) {
        detail_set(detail, detail_cap, "path must be an absolute bounded path");
        return -1;
    }
    char copy[SERVICE_MAX_PATH];
    snprintf(copy, sizeof(copy), "%s", path);
    size_t length = strlen(copy);
    if (length < 2 || copy[length - 1] == '/') {
        detail_set(detail, detail_cap, "path must name a file");
        return -1;
    }
    int dirfd = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dirfd < 0) {
        detail_set(detail, detail_cap, "cannot open filesystem root safely");
        return -1;
    }
    char *cursor = copy + 1;
    for (;;) {
        char *slash = strchr(cursor, '/');
        if (!slash) {
            if (*cursor == '\0' || strcmp(cursor, ".") == 0 || strcmp(cursor, "..") == 0 ||
                strlen(cursor) >= basename_cap) {
                close(dirfd);
                detail_set(detail, detail_cap, "file name is invalid or too long");
                return -1;
            }
            memcpy(basename, cursor, strlen(cursor) + 1);
            struct stat st;
            if (fstat(dirfd, &st) != 0 || !directory_is_safe(&st, owner, 1)) {
                close(dirfd);
                detail_set(detail, detail_cap, "parent directory ownership or mode is unsafe");
                return -1;
            }
            *parent_fd = dirfd;
            return 0;
        }
        *slash = '\0';
        if (*cursor == '\0' || strcmp(cursor, ".") == 0 || strcmp(cursor, "..") == 0) {
            close(dirfd);
            detail_set(detail, detail_cap, "path contains an unsafe component");
            return -1;
        }
        int nextfd = openat(dirfd, cursor, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        int saved = errno;
        if (nextfd < 0) {
            close(dirfd);
            detail_set(detail, detail_cap, saved == ENOENT ? "parent directory is absent" :
                       "parent directory is not a real directory");
            return -1;
        }
        struct stat st;
        int final_parent = slash[1] == '\0';
        if (fstat(nextfd, &st) != 0 || !directory_is_safe(&st, owner, final_parent)) {
            close(nextfd);
            close(dirfd);
            detail_set(detail, detail_cap, "parent directory ownership or mode is unsafe");
            return -1;
        }
        close(dirfd);
        dirfd = nextfd;
        cursor = slash + 1;
    }
}

static int read_exact_regular_at(int parent_fd, const char *name, uid_t owner,
                                 char *data, size_t cap, size_t *length,
                                 mode_t expected_mode, char *detail, size_t detail_cap) {
    int fd = openat(parent_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    int saved = errno;
    if (fd < 0) {
        detail_set(detail, detail_cap, saved == ENOENT ? "file is absent" : "file cannot be opened safely");
        return saved == ENOENT ? 1 : -1;
    }
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_uid != owner ||
        st.st_nlink != 1 || (st.st_mode & 07777) != expected_mode ||
        st.st_size < 0 || (uintmax_t)st.st_size >= cap) {
        close(fd);
        detail_set(detail, detail_cap, "file type, owner, mode, links, or size is unexpected");
        return -1;
    }
    size_t used = 0;
    while (used + 1 < cap) {
        ssize_t n = read(fd, data + used, cap - used - 1);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) {
            close(fd);
            detail_set(detail, detail_cap, "file read failed");
            return -1;
        }
        if (n == 0) break;
        used += (size_t)n;
    }
    char extra;
    ssize_t extra_n;
    do { extra_n = read(fd, &extra, 1); } while (extra_n < 0 && errno == EINTR);
    close(fd);
    if (extra_n != 0) {
        detail_set(detail, detail_cap, "file changed or exceeds the size limit");
        return -1;
    }
    data[used] = '\0';
    *length = used;
    return 0;
}

static int file_content_at_path(const char *path, uid_t owner, mode_t expected_mode,
                                const char *expected_a, const char *expected_b,
                                int *which, char *detail, size_t detail_cap) {
    int dirfd = -1;
    char name[NAME_MAX + 1];
    if (open_parent(path, owner, &dirfd, name, sizeof(name), detail, detail_cap) != 0) return -1;
    char content[SERVICE_MAX_PLIST + 1];
    size_t length = 0;
    int rc = read_exact_regular_at(dirfd, name, owner, content, sizeof(content), &length,
                                   expected_mode, detail, detail_cap);
    close(dirfd);
    if (rc != 0) return rc;
    size_t a_len = strlen(expected_a);
    size_t b_len = expected_b ? strlen(expected_b) : 0;
    if (length == a_len && memcmp(content, expected_a, length) == 0) {
        if (which) *which = 1;
        detail_set(detail, detail_cap, "managed file is valid");
        return 0;
    }
    if (expected_b && length == b_len && memcmp(content, expected_b, length) == 0) {
        if (which) *which = 0;
        detail_set(detail, detail_cap, "managed file is valid");
        return 0;
    }
    detail_set(detail, detail_cap, "managed file content or provenance does not match");
    return -1;
}

int service_validate_managed_plist(const char *path, uid_t expected_owner,
                                   int *enabled, char *detail, size_t detail_cap) {
    int which = 0;
    int rc = file_content_at_path(path, expected_owner, 0644, managed_enabled_plist,
                                  managed_disabled_plist, &which, detail, detail_cap);
    if (rc == 0 && enabled) *enabled = which;
    return rc;
}

int service_write_managed_plist(FILE *out) {
    if (!out) return -1;
    if (fwrite(managed_enabled_plist, 1, sizeof(managed_enabled_plist) - 1, out) !=
        sizeof(managed_enabled_plist) - 1) return -1;
    return ferror(out) ? -1 : 0;
}

static int write_all(int fd, const char *data, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t n = write(fd, data + offset, length - offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        offset += (size_t)n;
    }
    return 0;
}

int service_install_managed_plist(const char *path, uid_t expected_owner,
                                  char *detail, size_t detail_cap) {
    if (!path) {
        detail_set(detail, detail_cap, "managed plist path is required");
        return -1;
    }
#ifdef IOSCAFFEINATE_SERVICE_TESTING
    if (geteuid() != expected_owner) {
        detail_set(detail, detail_cap, "effective UID does not match the expected owner");
        return -1;
    }
#else
    if (expected_owner != 0 || geteuid() != 0) {
        detail_set(detail, detail_cap, "managed launchd plist installation requires root ownership");
        return -1;
    }
#ifndef IOSCAFFEINATE_P013_LAUNCHD_MUTATION_VERIFIED
    detail_set(detail, detail_cap, "iOS 12 launchd file-placement semantics are unverified");
    return -1;
#endif
    if (strcmp(path, IOSCAFFEINATE_SERVICE_LIVE_PLIST) != 0) {
        detail_set(detail, detail_cap, "managed plist path is outside the approved LaunchDaemons location");
        return -1;
    }
    if (strcmp(package_database_state(), "INSTALLED") != 0) {
        detail_set(detail, detail_cap, "exact rootful package identity is not confirmed");
        return -1;
    }
    char validation_detail[192] = {0};
    if (strcmp(inspect_regular_path(IOSCAFFEINATE_SERVICE_EXECUTABLE, 0, 0755, 1, NULL,
                                    validation_detail, sizeof(validation_detail)), "VALID") != 0 ||
        strcmp(inspect_regular_path(IOSCAFFEINATE_SERVICE_STAGED_PLIST, 0, 0644, 0,
                                    packaged_template, validation_detail, sizeof(validation_detail)), "VALID") != 0) {
        detail_set(detail, detail_cap, "canonical daemon or immutable staged template is not validated");
        return -1;
    }
    if (!secure_launchctl_present()) {
        detail_set(detail, detail_cap, "launchctl executable identity is unavailable or unsafe");
        return -1;
    }
    char listing[SERVICE_CAPTURE_SIZE] = {0};
    int list_exit = 1, list_truncated = 0;
    if (run_launchctl("list", listing, sizeof(listing), &list_exit, &list_truncated) != 0 ||
        list_exit != 0 || list_truncated) {
        detail_set(detail, detail_cap, "launchd registration state is not observable");
        return -1;
    }
    char existing_pid[64] = {0};
    if (list_has_label(listing, IOSCAFFEINATE_SERVICE_LABEL, existing_pid, sizeof(existing_pid))) {
        detail_set(detail, detail_cap, "launchd label already exists; refusing registration collision");
        return -1;
    }
    struct stat socket_st;
    if (lstat(IOSCAFFEINATE_SERVICE_SOCKET, &socket_st) == 0 || errno != ENOENT) {
        detail_set(detail, detail_cap, "daemon socket is present or uncertain; refusing managed plist installation");
        return -1;
    }
#endif
    int dirfd = -1;
    char name[NAME_MAX + 1];
    if (open_parent(path, expected_owner, &dirfd, name, sizeof(name), detail, detail_cap) != 0)
        return -1;
    char temp[NAME_MAX + 1];
    int fd = -1;
    for (unsigned attempt = 0; attempt < 16; ++attempt) {
        int n = snprintf(temp, sizeof(temp), ".ioscaffeinate.%ld.%u.tmp", (long)getpid(), attempt);
        if (n < 0 || (size_t)n >= sizeof(temp)) break;
        fd = openat(dirfd, temp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd >= 0 || errno != EEXIST) break;
    }
    if (fd < 0) {
        close(dirfd);
        detail_set(detail, detail_cap, "cannot create a private temporary file");
        return -1;
    }
    int failed = 0;
    if (write_all(fd, managed_enabled_plist, sizeof(managed_enabled_plist) - 1) != 0 ||
        fsync(fd) != 0 ||
        (expected_owner == 0 && fchown(fd, 0, 0) != 0) ||
        fchmod(fd, 0644) != 0 || fsync(fd) != 0) failed = 1;
    if (close(fd) != 0) failed = 1;
    if (!failed && linkat(dirfd, temp, dirfd, name, 0) != 0) failed = 1;
    int saved = errno;
    (void)unlinkat(dirfd, temp, 0);
    if (!failed && fsync(dirfd) != 0) failed = 1;
    close(dirfd);
    if (failed) {
        errno = saved;
        detail_set(detail, detail_cap, saved == EEXIST ? "refusing to replace an existing live plist" :
                   "atomic managed plist installation failed");
        return -1;
    }
    detail_set(detail, detail_cap, "managed plist installed atomically");
    return 0;
}

static int run_launchctl(const char *subcommand, char *output, size_t output_cap,
                         int *exit_status, int *truncated) {
#ifdef IOSCAFFEINATE_SERVICE_TESTING
    if (test_runner) {
        int rc = test_runner(test_runner_context, subcommand, output, output_cap, exit_status);
        if (truncated) *truncated = 0;
        return rc;
    }
#endif
    if (output_cap == 0) return -1;
    output[0] = '\0';
    if (truncated) *truncated = 0;
    char *const launchctl_argv[] = {"/bin/launchctl", (char *)subcommand, NULL};
    int pipefd[2];
    if (pipe(pipefd) != 0) return -1;
    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions) != 0) {
        close(pipefd[0]); close(pipefd[1]); return -1;
    }
    int rc = posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDOUT_FILENO);
    if (rc == 0) rc = posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDERR_FILENO);
    if (rc == 0) rc = posix_spawn_file_actions_addclose(&actions, pipefd[0]);
    if (rc == 0) rc = posix_spawn_file_actions_addclose(&actions, pipefd[1]);
    pid_t child = -1;
    if (rc == 0) rc = posix_spawn(&child, "/bin/launchctl", &actions, NULL,
                                   launchctl_argv, service_child_environment);
    posix_spawn_file_actions_destroy(&actions);
    close(pipefd[1]);
    if (rc != 0) { close(pipefd[0]); return -1; }
    size_t used = 0;
    char buffer[1024];
    for (;;) {
        ssize_t n = read(pipefd[0], buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        size_t copy = (size_t)n;
        if (copy > output_cap - 1 - used) {
            copy = output_cap - 1 - used;
            if (truncated) *truncated = 1;
        }
        if (copy) {
            memcpy(output + used, buffer, copy);
            used += copy;
            output[used] = '\0';
        }
        if (used + 1 == output_cap && truncated) *truncated = 1;
    }
    close(pipefd[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return -1;
    }
    if (WIFEXITED(status)) *exit_status = WEXITSTATUS(status);
    else *exit_status = 128;
    return 0;
}

/* 0=absent, 1=validated executable, 2=present or inaccessible but unsafe. */
static int launchctl_path_status(void) {
    int rootfd = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (rootfd < 0) return errno == ENOENT ? 0 : 2;
    int bindir = openat(rootfd, "bin", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    int saved = errno;
    close(rootfd);
    if (bindir < 0) return saved == ENOENT ? 0 : 2;
    struct stat dir_st, file_st;
    int safe_dir = fstat(bindir, &dir_st) == 0 && S_ISDIR(dir_st.st_mode) &&
                   dir_st.st_uid == 0 && (dir_st.st_mode & (S_IWGRP | S_IWOTH)) == 0;
    int fd = safe_dir ? openat(bindir, "launchctl", O_RDONLY | O_NOFOLLOW | O_CLOEXEC) : -1;
    saved = errno;
    close(bindir);
    if (fd < 0) return safe_dir && saved == ENOENT ? 0 : 2;
    int safe_file = fstat(fd, &file_st) == 0 && S_ISREG(file_st.st_mode) &&
                    file_st.st_uid == 0 && (file_st.st_mode & (S_IWGRP | S_IWOTH)) == 0 &&
                    (file_st.st_mode & 0111) != 0 && file_st.st_nlink == 1;
    close(fd);
    return safe_file ? 1 : 2;
}

static int secure_launchctl_present(void) {
    return launchctl_path_status() == 1;
}

static int help_mentions(const char *output, const char *name) {
    size_t len = strlen(name);
    const char *cursor = output;
    while ((cursor = strstr(cursor, name)) != NULL) {
        unsigned char before = cursor == output ? ' ' : (unsigned char)cursor[-1];
        unsigned char after = (unsigned char)cursor[len];
        if ((before == ' ' || before == '\t' || before == '\n' || before == '[' || before == '|') &&
            (after == '\0' || after == ' ' || after == '\t' || after == '\n' || after == ']' || after == '|'))
            return 1;
        cursor += len;
    }
    return 0;
}

static int list_has_label(const char *output, const char *label, char *pid_out, size_t pid_cap) {
    const char *line = output;
    while (*line) {
        const char *end = strchr(line, '\n');
        if (!end) end = line + strlen(line);
        char copy[512];
        size_t len = (size_t)(end - line);
        if (len < sizeof(copy)) {
            memcpy(copy, line, len); copy[len] = '\0';
            char *tokens[16]; size_t count = 0;
            char *save = NULL;
            for (char *token = strtok_r(copy, " \t\r", &save); token && count < 16;
                 token = strtok_r(NULL, " \t\r", &save)) tokens[count++] = token;
            if (count >= 2 && strcmp(tokens[count - 1], label) == 0) {
                snprintf(pid_out, pid_cap, "%s", tokens[0]);
                return 1;
            }
        }
        line = *end ? end + 1 : end;
    }
    return 0;
}

static int pid_is_stopped(const char *pid) {
    return pid && (strcmp(pid, "-") == 0 || strcmp(pid, "0") == 0);
}

static int pid_is_positive(const char *pid) {
    if (!pid || !*pid) return 0;
    unsigned long value = 0;
    for (const unsigned char *p = (const unsigned char *)pid; *p; ++p) {
        if (*p < '0' || *p > '9') return 0;
        unsigned long digit = (unsigned long)(*p - '0');
        if (value > (2147483647UL - digit) / 10UL) return 0;
        value = value * 10UL + digit;
    }
    return value > 0;
}

static const char *inspect_regular_path(const char *path, uid_t owner, mode_t mode,
                                        int require_exec, const char *expected_content,
                                        char *detail, size_t detail_cap) {
    int dirfd = -1;
    char name[NAME_MAX + 1];
    if (open_parent(path, owner, &dirfd, name, sizeof(name), detail, detail_cap) != 0) {
        if (errno == ENOENT || strstr(detail, "absent")) return "ABSENT";
        return "UNSAFE";
    }
    int fd = openat(dirfd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    int saved = errno;
    if (fd < 0) {
        close(dirfd);
        if (saved == ENOENT) return "ABSENT";
        detail_set(detail, detail_cap, "file cannot be opened safely");
        return "UNSAFE";
    }
    struct stat st;
    int ok = fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_uid == owner &&
             st.st_nlink == 1 && (st.st_mode & 07777) == mode &&
             (!require_exec || (st.st_mode & 0111) != 0);
    if (ok && expected_content) {
        char content[SERVICE_MAX_PLIST + 1]; size_t length = 0;
        if (st.st_size < 0 || (uintmax_t)st.st_size >= sizeof(content)) ok = 0;
        else {
            size_t used = 0;
            while (used + 1 < sizeof(content)) {
                ssize_t n = read(fd, content + used, sizeof(content) - used - 1);
                if (n < 0 && errno == EINTR) continue;
                if (n <= 0) break;
                used += (size_t)n;
            }
            content[used] = '\0'; length = used;
            if (length != strlen(expected_content) || memcmp(content, expected_content, length) != 0) ok = 0;
        }
    }
    close(fd); close(dirfd);
    if (!ok) {
        detail_set(detail, detail_cap, "file type, identity, mode, links, or content is unexpected");
        return "UNSAFE";
    }
    detail_set(detail, detail_cap, "file identity and permissions are valid");
    return "VALID";
}

static int run_package_query(char *output, size_t output_cap, int *exit_status) {
#ifdef IOSCAFFEINATE_SERVICE_TESTING
    if (test_runner) {
        int rc = test_runner(test_runner_context, "package", output, output_cap, exit_status);
        return rc;
    }
#endif
    char detail[160] = {0};
    if (strcmp(inspect_regular_path("/usr/bin/dpkg-query", 0, 0755, 1, NULL,
                                    detail, sizeof(detail)), "VALID") != 0) return -1;
    char *const args[] = {"/usr/bin/dpkg-query", "-W",
                          "-f=${Status}|${Package}|${Architecture}\\n",
                          "com.ioscaffeinate.cli", NULL};
    int pipefd[2];
    if (pipe(pipefd) != 0) return -1;
    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions) != 0) {
        close(pipefd[0]); close(pipefd[1]); return -1;
    }
    int rc = posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDOUT_FILENO);
    if (rc == 0) rc = posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDERR_FILENO);
    if (rc == 0) rc = posix_spawn_file_actions_addclose(&actions, pipefd[0]);
    if (rc == 0) rc = posix_spawn_file_actions_addclose(&actions, pipefd[1]);
    pid_t child = -1;
    if (rc == 0) rc = posix_spawn(&child, "/usr/bin/dpkg-query", &actions, NULL,
                                   args, service_child_environment);
    posix_spawn_file_actions_destroy(&actions);
    close(pipefd[1]);
    if (rc != 0) { close(pipefd[0]); return -1; }
    size_t used = 0;
    char buffer[512];
    int too_large = 0;
    for (;;) {
        ssize_t n = read(pipefd[0], buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        size_t copy = (size_t)n;
        if (copy > output_cap - 1 - used) { copy = output_cap - 1 - used; too_large = 1; }
        if (copy) { memcpy(output + used, buffer, copy); used += copy; output[used] = '\0'; }
    }
    close(pipefd[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return -1;
    if (too_large || !WIFEXITED(status)) return -1;
    *exit_status = WEXITSTATUS(status);
    return 0;
}

static const char *package_database_state(void) {
    char output[2048] = {0};
    int status = 1;
    if (run_package_query(output, sizeof(output), &status) != 0) return "UNVERIFIED";
    if (status == 0 && strcmp(output, "install ok installed|com.ioscaffeinate.cli|iphoneos-arm\n") == 0)
        return "INSTALLED";
    if (status != 0 && strstr(output, "no packages found matching com.ioscaffeinate.cli") != NULL)
        return "NOT_INSTALLED";
    if (status == 0 && strstr(output, "|com.ioscaffeinate.cli|") != NULL &&
        strstr(output, "|iphoneos-arm\n") != NULL && strstr(output, "install ok installed|") != output)
        return "NOT_INSTALLED";
    return "INCONSISTENT";
}

static int daemon_query(char *reply, size_t reply_cap, const char **ipc_state,
                        const char **socket_state) {
    struct stat st;
    if (lstat(IOSCAFFEINATE_SERVICE_SOCKET, &st) != 0) {
        int saved = errno;
        *ipc_state = saved == ENOENT ? "UNAVAILABLE" : "ERROR";
        *socket_state = saved == ENOENT ? "ABSENT" : "ERROR";
        return saved == ENOENT ? 1 : -1;
    }
    if (!S_ISSOCK(st.st_mode) || (st.st_mode & 0777) != 0600 || st.st_uid != 0) {
        *ipc_state = "UNSAFE";
        *socket_state = "UNSAFE";
        return -1;
    }
    *socket_state = "PRESENT";
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { *ipc_state = "ERROR"; return -1; }
    struct timeval timeout = {.tv_sec = 2, .tv_usec = 0};
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s", IOSCAFFEINATE_SERVICE_SOCKET);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        int saved = errno; close(fd);
        *ipc_state = (saved == ENOENT || saved == ECONNREFUSED) ? "UNAVAILABLE" : "ERROR";
        *socket_state = (saved == ENOENT || saved == ECONNREFUSED) ? "STALE" : "ERROR";
        return (saved == ENOENT || saved == ECONNREFUSED) ? 1 : -1;
    }
    const char request[] = "SERVER STATUS\n";
    size_t offset = 0;
    while (offset < sizeof(request) - 1) {
        ssize_t n = write(fd, request + offset, sizeof(request) - 1 - offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { close(fd); *ipc_state = "ERROR"; return -1; }
        offset += (size_t)n;
    }
    size_t used = 0;
    while (used + 1 < reply_cap) {
        ssize_t n = recv(fd, reply + used, reply_cap - used - 1, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
        reply[used] = '\0';
        char *newline = memchr(reply, '\n', used);
        if (newline) {
            if (newline != reply + used - 1) { close(fd); *ipc_state = "ERROR"; return -1; }
            *newline = '\0'; close(fd);
            if (strncmp(reply, "OK SERVER protocol=1 ", 21) == 0) {
                *ipc_state = "RESPONSIVE";
                return 0;
            }
            *ipc_state = "INCOMPATIBLE";
            return -1;
        }
    }
    close(fd); *ipc_state = "ERROR"; return -1;
}

static const char *field_value(const char *reply, const char *key, const char *fallback) {
    static char fields[8][64];
    static unsigned slot;
    char *result = fields[slot++ % 8];
    char pattern[48];
    if (snprintf(pattern, sizeof(pattern), "%s=", key) >= (int)sizeof(pattern)) return fallback;
    const char *p = strstr(reply, pattern);
    if (!p || (p != reply && p[-1] != ' ')) return fallback;
    p += strlen(pattern);
    size_t n = 0;
    while (p[n] && p[n] != ' ' && n + 1 < sizeof(fields[0])) n++;
    if (n == 0 || (p[n] && p[n] != ' ')) return fallback;
    memcpy(result, p, n); result[n] = '\0';
    return result;
}

static void inspect_service(service_snapshot_t *s) {
    memset(s, 0, sizeof(*s));
    char detail[192] = {0};
    const char *exe = inspect_regular_path(IOSCAFFEINATE_SERVICE_EXECUTABLE, 0, 0755, 1,
                                           NULL, detail, sizeof(detail));
    const char *staged = inspect_regular_path(IOSCAFFEINATE_SERVICE_STAGED_PLIST, 0, 0644, 0,
                                              packaged_template, detail, sizeof(detail));
    s->package_database = package_database_state();
    if (strcmp(s->package_database, "INSTALLED") == 0 && strcmp(exe, "VALID") == 0 && strcmp(staged, "VALID") == 0)
        s->package = "INSTALLED";
    else if (strcmp(s->package_database, "NOT_INSTALLED") == 0 && strcmp(exe, "ABSENT") == 0 && strcmp(staged, "ABSENT") == 0)
        s->package = "NOT_INSTALLED";
    else if (strcmp(s->package_database, "UNVERIFIED") == 0 && strcmp(exe, "UNSAFE") != 0 && strcmp(staged, "UNSAFE") != 0)
        s->package = "UNVERIFIED";
    else s->package = "INCONSISTENT";
    s->staged = strcmp(staged, "VALID") == 0 ? "PRESENT_VALID" : strcmp(staged, "ABSENT") == 0 ? "ABSENT" : "INCONSISTENT";

    struct stat live_st;
    if (lstat(IOSCAFFEINATE_SERVICE_LIVE_PLIST, &live_st) == 0) {
        s->live_plist_exists = 1;
        int enabled = 0;
        if (service_validate_managed_plist(IOSCAFFEINATE_SERVICE_LIVE_PLIST, 0,
                                           &enabled, detail, sizeof(detail)) == 0) {
            s->managed_plist = enabled ? "VALID_ENABLED" : "VALID_DISABLED";
            s->live_plist_enabled = enabled;
            s->enablement = enabled ? "ENABLED" : "DISABLED";
        } else {
            s->managed_plist = "INCONSISTENT";
            s->enablement = "UNKNOWN";
        }
    } else if (errno == ENOENT) {
        s->managed_plist = "ABSENT";
        s->enablement = "NOT_CONFIGURED";
    } else {
        s->managed_plist = "UNVERIFIED";
        s->enablement = "UNKNOWN";
    }

#ifdef IOSCAFFEINATE_SERVICE_TESTING
    int launchctl_status = test_runner ? 1 : launchctl_path_status();
#else
    int launchctl_status = launchctl_path_status();
#endif
    s->launchctl_present = launchctl_status == 1;
    s->launchctl_path = launchctl_status == 1 ? "SAFE" :
                        launchctl_status == 0 ? "ABSENT" : "UNSAFE_OR_UNKNOWN";
    s->help_state = launchctl_status == 0 ? "UNSUPPORTED" : "UNVERIFIED";
    s->registration = "UNVERIFIED";
    s->registration_pid = "UNKNOWN";
    if (s->launchctl_present) {
        if (run_launchctl("help", s->help, sizeof(s->help), &s->help_exit, &s->help_truncated) == 0 &&
            s->help_exit == 0 && !s->help_truncated) s->help_state = "AVAILABLE";
        if (run_launchctl("list", s->list, sizeof(s->list), &s->list_exit, &s->list_truncated) == 0 &&
            s->list_exit == 0 && !s->list_truncated) {
            char pid[64] = {0};
            if (list_has_label(s->list, IOSCAFFEINATE_SERVICE_LABEL, pid, sizeof(pid))) {
                s->registration = "REGISTERED";
                static char pid_cache[64];
                snprintf(pid_cache, sizeof(pid_cache), "%s", pid);
                s->registration_pid = pid_cache;
            } else s->registration = "NOT_REGISTERED";
        }
    }

    s->ipc = "UNAVAILABLE";
    s->socket_state = "UNKNOWN";
    (void)daemon_query(s->daemon_reply, sizeof(s->daemon_reply), &s->ipc, &s->socket_state);
    s->runtime = strcmp(s->ipc, "RESPONSIVE") == 0 ? "RUNNING_CONFIRMED" :
                 strcmp(s->registration, "REGISTERED") == 0 && pid_is_stopped(s->registration_pid) ? "STOPPED_CONFIRMED" :
                 strcmp(s->registration, "REGISTERED") == 0 && pid_is_positive(s->registration_pid) ? "RUNNING_UNVERIFIED" :
                 strcmp(s->registration, "REGISTERED") == 0 ? "UNVERIFIED" : "NOT_OBSERVED";
    if (strcmp(s->ipc, "RESPONSIVE") == 0) {
        const char *owned = field_value(s->daemon_reply, "assertion_owned", "UNKNOWN");
        s->assertion = strcmp(owned, "1") == 0 ? "OWNED" :
                       strcmp(owned, "0") == 0 ? "NONE" : "UNKNOWN";
    } else {
        s->assertion = "UNKNOWN";
    }
    s->daemon_state = strcmp(s->ipc, "RESPONSIVE") == 0 ? field_value(s->daemon_reply, "state", "UNKNOWN") : "UNKNOWN";
    s->state_invariant = strcmp(s->ipc, "RESPONSIVE") == 0 ? field_value(s->daemon_reply, "state_invariant", "UNKNOWN") : "UNKNOWN";
    s->release_pending = strcmp(s->ipc, "RESPONSIVE") == 0 ? field_value(s->daemon_reply, "release_pending", "UNKNOWN") : "UNKNOWN";
    s->last_shutdown = "UNAVAILABLE";

    if (strcmp(s->package, "INCONSISTENT") == 0 || strcmp(s->staged, "INCONSISTENT") == 0 ||
        strcmp(s->managed_plist, "INCONSISTENT") == 0 || strcmp(s->ipc, "UNSAFE") == 0 ||
        strcmp(s->state_invariant, "ERROR") == 0) {
        s->state = "INCONSISTENT";
        snprintf(s->blocker, sizeof(s->blocker), "path identity, ownership, configuration, IPC, or daemon invariant is inconsistent");
    } else if ((s->live_plist_exists && strcmp(s->package, "INSTALLED") != 0) ||
               (strcmp(s->registration, "REGISTERED") == 0 &&
                strcmp(s->managed_plist, "ABSENT") == 0) ||
               (strcmp(s->registration, "REGISTERED") == 0 &&
                strcmp(s->managed_plist, "VALID_DISABLED") == 0)) {
        s->state = "INCONSISTENT";
        snprintf(s->blocker, sizeof(s->blocker), "managed executable, plist enablement, and registered job disagree");
    } else if (strcmp(s->ipc, "RESPONSIVE") == 0 &&
               (strcmp(s->daemon_state, "RELEASE_FAILED") == 0 ||
                strcmp(s->daemon_state, "BLOCKED") == 0)) {
        s->state = "FAILED";
        snprintf(s->blocker, sizeof(s->blocker), "daemon reports unresolved assertion release or blocked state");
    } else if (strcmp(s->ipc, "RESPONSIVE") == 0 &&
               (strcmp(s->daemon_state, "IDLE") == 0 || strcmp(s->daemon_state, "ACTIVE") == 0)) {
        s->state = "RUNNING";
        snprintf(s->blocker, sizeof(s->blocker), "launchd ownership and iOS lifecycle compatibility are unverified");
    } else if (strcmp(s->ipc, "RESPONSIVE") == 0) {
        s->state = "UNVERIFIED";
        snprintf(s->blocker, sizeof(s->blocker), "daemon reports a transitional or unknown runtime state");
    } else if (strcmp(s->registration, "REGISTERED") == 0) {
        if (pid_is_stopped(s->registration_pid)) {
            s->state = "REGISTERED_STOPPED";
            snprintf(s->blocker, sizeof(s->blocker), "job is registered but stopped; start semantics remain unverified");
        } else {
            s->state = "UNVERIFIED";
            snprintf(s->blocker, sizeof(s->blocker), "launchd reports a process or unknown PID while daemon IPC is unavailable");
        }
    } else if (strcmp(s->managed_plist, "VALID_DISABLED") == 0 &&
               strcmp(s->registration, "NOT_REGISTERED") == 0) {
        s->state = "DISABLED";
        snprintf(s->blocker, sizeof(s->blocker), "launchd compatibility and boot persistence are unverified");
    } else if (strcmp(s->managed_plist, "VALID_ENABLED") == 0) {
        s->state = "UNVERIFIED";
        snprintf(s->blocker, sizeof(s->blocker), "configured enabled but launchd registration is not confirmed");
    } else if (strcmp(s->registration, "UNVERIFIED") == 0 ||
               strcmp(s->managed_plist, "UNVERIFIED") == 0) {
        s->state = "UNVERIFIED";
        snprintf(s->blocker, sizeof(s->blocker), "launchd registration or live-plist state could not be observed");
    } else if (strcmp(s->package, "NOT_INSTALLED") == 0 && strcmp(s->staged, "ABSENT") == 0 &&
               strcmp(s->registration, "NOT_REGISTERED") == 0) {
        s->state = "NOT_INSTALLED";
        snprintf(s->blocker, sizeof(s->blocker), "package and staged template are absent");
    } else if (strcmp(s->package, "INSTALLED") == 0 && strcmp(s->staged, "PRESENT_VALID") == 0 &&
               strcmp(s->registration, "NOT_REGISTERED") == 0) {
        s->state = "STAGED_ONLY";
        snprintf(s->blocker, sizeof(s->blocker), "service has not been explicitly configured");
    } else {
        s->state = "INCONSISTENT";
        snprintf(s->blocker, sizeof(s->blocker), "package files are incomplete or unavailable");
    }
}

static int policy_assertion_is_safe(const service_policy_facts_t *facts) {
    if (!facts->invariant_ok || facts->release_pending != 0) return 0;
    if (facts->daemon_state == 0) return facts->assertion == 0;
    if (facts->daemon_state == 1) return facts->assertion == 1;
    return 0;
}

int service_policy_preflight(const char *action, const service_policy_facts_t *facts) {
    if (!action || !facts) return SERVICE_EXIT_USAGE;
    if (!facts->privileged) return SERVICE_EXIT_PRIVILEGE;
    if (facts->managed == 3 || facts->socket == 3 ||
        facts->package_valid > 1 || facts->staged_valid > 1) return SERVICE_EXIT_UNSAFE;
    if (facts->package_valid == 0 || facts->staged_valid == 0) return SERVICE_EXIT_INVALID_STATE;

    if (strcmp(action, "enable") == 0) {
        if (facts->managed == 1 || facts->registered == 1) return SERVICE_EXIT_INVALID_STATE;
        if (facts->registered == 2) return SERVICE_EXIT_UNSAFE;
        if (facts->enable_combines_start && !facts->combined_behavior_consent)
            return SERVICE_EXIT_UNSUPPORTED;
        return facts->enable_verified ? SERVICE_EXIT_OK : SERVICE_EXIT_UNSUPPORTED;
    }
    if (strcmp(action, "start") == 0) {
        if (facts->runtime == 1) return SERVICE_EXIT_INVALID_STATE;
        if (facts->runtime == 2 || facts->registered == 2) return SERVICE_EXIT_UNSAFE;
        if (facts->socket != 0) return SERVICE_EXIT_UNSAFE;
        if (facts->managed != 1 || facts->registered != 1) return SERVICE_EXIT_INVALID_STATE;
        return facts->start_verified ? SERVICE_EXIT_OK : SERVICE_EXIT_UNSUPPORTED;
    }
    if (strcmp(action, "stop") == 0) {
        if (facts->registered == 2 || facts->runtime == 2) return SERVICE_EXIT_UNSAFE;
        if (facts->managed != 1 || facts->registered != 1 || facts->runtime != 1)
            return SERVICE_EXIT_INVALID_STATE;
        if (!policy_assertion_is_safe(facts)) return SERVICE_EXIT_UNSAFE;
        return facts->shutdown_protocol_supported ? SERVICE_EXIT_OK : SERVICE_EXIT_UNSUPPORTED;
    }
    if (strcmp(action, "disable") == 0) {
        if (facts->runtime == 1) return SERVICE_EXIT_INVALID_STATE;
        if (facts->runtime == 2 || facts->registered == 2) return SERVICE_EXIT_UNSAFE;
        if (facts->managed != 1 || facts->registered != 1) return SERVICE_EXIT_INVALID_STATE;
        return facts->disable_verified ? SERVICE_EXIT_OK : SERVICE_EXIT_UNSUPPORTED;
    }
    if (strcmp(action, "restart") == 0) {
        if (facts->runtime != 1) return facts->runtime == 2 ? SERVICE_EXIT_UNSAFE : SERVICE_EXIT_INVALID_STATE;
        if (facts->managed != 1 || facts->registered != 1) return SERVICE_EXIT_INVALID_STATE;
        if (!policy_assertion_is_safe(facts)) return SERVICE_EXIT_UNSAFE;
        /* Start compatibility is checked before stop so restart cannot leave
         * a healthy service down when the subsequent start is not verified. */
        if (!facts->start_verified || !facts->shutdown_protocol_supported)
            return SERVICE_EXIT_UNSUPPORTED;
        return SERVICE_EXIT_OK;
    }
    return SERVICE_EXIT_USAGE;
}

static service_policy_facts_t policy_facts_from_snapshot(const char *action,
                                                         const service_snapshot_t *s) {
    service_policy_facts_t facts;
    memset(&facts, 0, sizeof(facts));
    facts.privileged = geteuid() == 0;
    facts.package_valid = strcmp(s->package, "INSTALLED") == 0 ? 1 :
                          strcmp(s->package, "NOT_INSTALLED") == 0 ? 0 : 2;
    facts.staged_valid = strcmp(s->staged, "PRESENT_VALID") == 0 ? 1 :
                         strcmp(s->staged, "ABSENT") == 0 ? 0 : 2;
    facts.managed = strcmp(s->managed_plist, "ABSENT") == 0 ? 0 :
                    strcmp(s->managed_plist, "VALID_ENABLED") == 0 ? 1 :
                    strcmp(s->managed_plist, "VALID_DISABLED") == 0 ? 2 : 3;
    facts.registered = strcmp(s->registration, "NOT_REGISTERED") == 0 ? 0 :
                       strcmp(s->registration, "REGISTERED") == 0 ? 1 : 2;
    facts.runtime = (strcmp(s->runtime, "RUNNING_CONFIRMED") == 0 ||
                     strcmp(s->runtime, "RUNNING_UNVERIFIED") == 0) ? 1 :
                    (strcmp(s->runtime, "STOPPED_CONFIRMED") == 0 ||
                     strcmp(s->runtime, "NOT_OBSERVED") == 0) ? 0 : 2;
    facts.socket = strcmp(s->socket_state, "ABSENT") == 0 ? 0 :
                   strcmp(s->socket_state, "PRESENT") == 0 ? 1 :
                   strcmp(s->socket_state, "STALE") == 0 ? 2 :
                   strcmp(s->socket_state, "UNSAFE") == 0 ? 3 : 4;
    facts.daemon_state = strcmp(s->daemon_state, "IDLE") == 0 ? 0 :
                         strcmp(s->daemon_state, "ACTIVE") == 0 ? 1 : 2;
    facts.assertion = strcmp(s->assertion, "NONE") == 0 ? 0 :
                      strcmp(s->assertion, "OWNED") == 0 ? 1 :
                      strcmp(s->daemon_state, "RELEASE_FAILED") == 0 ? 2 : 3;
    facts.release_pending = strcmp(s->release_pending, "no") == 0 ? 0 :
                            strcmp(s->release_pending, "yes") == 0 ? 1 : 2;
    facts.invariant_ok = strcmp(s->state_invariant, "OK") == 0;
    facts.enable_verified = 0;
    facts.start_verified = 0;
    facts.disable_verified = 0;
    facts.shutdown_protocol_supported = strcmp(action, "stop") == 0 && strcmp(s->ipc, "RESPONSIVE") == 0;
    facts.enable_combines_start = 0;
    facts.combined_behavior_consent = 0;
    return facts;
}

#ifdef IOSCAFFEINATE_SERVICE_TESTING
int service_test_preflight(const char *action, const service_policy_facts_t *facts) {
    return service_policy_preflight(action, facts);
}
#endif

static void report_snapshot(FILE *out, const service_snapshot_t *s) {
    fprintf(out,
            "state=%s\n"
            "package.installation=%s\n"
            "package.database_identity=%s\n"
            "package.identity=com.ioscaffeinate.cli\n"
            "package.architecture=iphoneos-arm\n"
            "package.staged_template=%s\n"
            "managed_plist=%s\n"
            "configured_enablement=%s\n"
            "launchd.registration=%s\n"
            "launchd.registration_pid=%s\n"
            "launchd.executable=%s\n"
            "launchd.help=%s\n"
            "launchd.mutating_compatibility=UNVERIFIED\n"
            "runtime.process=%s\n"
            "ipc.availability=%s\n"
            "socket.state=%s\n"
            "daemon.state=%s\n"
            "assertion.state=%s\n"
            "assertion.release_pending=%s\n"
            "assertion.state_invariant=%s\n"
            "assertion_is_implied_by_registration=no\n"
            "last_shutdown_result=%s\n"
            "boot_persistence=UNVERIFIED\n"
            "device_awake=UNVERIFIED\n"
            "ssh_reachability=UNVERIFIED\n"
            "readiness=BLOCKED\n"
            "recovery_blocker=%s\n"
            "changed=no\n",
            s->state, s->package, s->package_database, s->staged, s->managed_plist, s->enablement, s->registration,
            s->registration_pid, s->launchctl_path, s->help_state, s->runtime, s->ipc, s->socket_state,
            s->daemon_state, s->assertion, s->release_pending, s->state_invariant, s->last_shutdown, s->blocker);
    static const char *const commands[] = {
        "load", "unload", "start", "stop", "enable", "disable", "bootstrap", "bootout"
    };
    for (size_t i = 0; i < sizeof(commands) / sizeof(commands[0]); ++i) {
        const char *capability = "UNVERIFIED";
        if (strcmp(s->help_state, "UNSUPPORTED") == 0) capability = "UNSUPPORTED";
        else if (strcmp(s->help_state, "AVAILABLE") == 0)
            capability = help_mentions(s->help, commands[i]) ? "DETECTED_UNVERIFIED" : "UNSUPPORTED";
        fprintf(out, "launchd.command.%s=%s\n", commands[i], capability);
    }
}

static int send_shutdown_request(char *reply, size_t reply_cap) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct timeval timeout = {.tv_sec = 2, .tv_usec = 0};
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address)); address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s", IOSCAFFEINATE_SERVICE_SOCKET);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) { close(fd); return -1; }
    const char request[] = "SHUTDOWN\n";
    if (write_all(fd, request, sizeof(request) - 1) != 0) { close(fd); return -1; }
    size_t used = 0;
    while (used + 1 < reply_cap) {
        ssize_t n = recv(fd, reply + used, reply_cap - used - 1, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n; reply[used] = '\0';
        char *newline = memchr(reply, '\n', used);
        if (newline) { *newline = '\0'; close(fd); return 0; }
    }
    close(fd); return -1;
}

static int wait_for_clean_shutdown(void) {
    struct timespec delay = {.tv_sec = 0, .tv_nsec = 100000000};
    for (unsigned i = 0; i < SERVICE_STOP_TIMEOUT_SECONDS * 10; ++i) {
        struct stat st;
        int socket_removed = lstat(IOSCAFFEINATE_SERVICE_SOCKET, &st) != 0 && errno == ENOENT;
        if (socket_removed && secure_launchctl_present()) {
            char output[SERVICE_CAPTURE_SIZE] = {0};
            int exit_status = 1, truncated = 0;
            if (run_launchctl("list", output, sizeof(output), &exit_status, &truncated) == 0 &&
                exit_status == 0 && !truncated) {
                char pid[64] = {0};
                if (list_has_label(output, IOSCAFFEINATE_SERVICE_LABEL, pid, sizeof(pid)) &&
                    pid_is_stopped(pid)) return 0;
            }
        }
        (void)nanosleep(&delay, NULL);
    }
    return -1;
}

static int service_stop(FILE *out, FILE *err) {
    if (geteuid() != 0) {
        fprintf(err, "service stop: root privilege is required; changed=no\n");
        return SERVICE_EXIT_PRIVILEGE;
    }
    service_snapshot_t s; inspect_service(&s);
    service_policy_facts_t facts = policy_facts_from_snapshot("stop", &s);
    if (!pid_is_positive(s.registration_pid)) facts.runtime = 0;
    int gate = service_policy_preflight("stop", &facts);
    if (gate != SERVICE_EXIT_OK) {
        fprintf(err, "service stop: safe preconditions are not established; state=%s registration=%s pid=%s ipc=%s assertion=%s changed=no\n",
                s.state, s.registration, s.registration_pid, s.ipc, s.assertion);
        return gate;
    }
    char reply[1024] = {0};
    if (send_shutdown_request(reply, sizeof(reply)) != 0) {
        fprintf(err, "service stop: graceful shutdown request did not return a result; cleanup is unresolved; changed=unknown\n");
        return SERVICE_EXIT_UNSAFE;
    }
    static const char expected[] = "OK shutdown=accepted assertion_released=yes";
    if (strncmp(reply, expected, sizeof(expected) - 1) != 0) {
        if (strncmp(reply, "ERR unknown command", 19) == 0) {
            fprintf(err, "service stop: daemon does not support acknowledged graceful shutdown; changed=no\n");
            return SERVICE_EXIT_UNSUPPORTED;
        }
        fprintf(err, "service stop: daemon refused or did not confirm assertion release; response=%s changed=unknown\n", reply);
        return SERVICE_EXIT_UNSAFE;
    }
    if (wait_for_clean_shutdown() != 0) {
        fprintf(err, "service stop: shutdown timed out; process or socket cleanup remains unresolved; changed=unknown\n");
        return SERVICE_EXIT_UNSAFE;
    }
    fprintf(out, "operation=stop\nchanged=yes\nshutdown=GRACEFUL\nassertion_release=CONFIRMED\nruntime_process=STOPPED\nlaunchd_registration=REGISTERED_STOPPED\n");
    return ferror(out) ? SERVICE_EXIT_ERROR : SERVICE_EXIT_OK;
}

int service_command(int argc, char **argv, FILE *out, FILE *err) {
    if (argc != 1 || !argv || !out || !err) {
        fprintf(err ? err : stderr, "usage: ic service status|doctor|plan|enable|disable|start|stop|restart\n");
        return SERVICE_EXIT_USAGE;
    }
    const char *action = argv[0];
    if (strcmp(action, "status") == 0 || strcmp(action, "doctor") == 0 || strcmp(action, "plan") == 0) {
        service_snapshot_t s; inspect_service(&s);
        if (strcmp(action, "status") == 0) {
            report_snapshot(out, &s);
            return ferror(out) ? SERVICE_EXIT_ERROR : SERVICE_EXIT_OK;
        }
        if (strcmp(action, "doctor") == 0) {
            fprintf(out, "iOS-Caffeinate service doctor\n");
            report_snapshot(out, &s);
            fprintf(out,
                    "check.package_identity=%s\n"
                    "check.staged_template=%s\n"
                    "check.managed_plist=%s\n"
                    "check.launchctl_help=%s\n"
                    "check.launchd_registration=%s\n"
                    "check.daemon_ipc=%s\n"
                    "check.daemon_state=%s\n"
                    "check.assertion_state=%s\n"
                    "check.assertion_release_pending=%s\n"
                    "check.boot_persistence=UNVERIFIED\n"
                    "check.hardware_acceptance=PENDING\n"
                    "readiness=BLOCKED\n"
                    "unattended_authorized=no\n",
                    s.package, s.staged, s.managed_plist, s.help_state, s.registration,
                    s.ipc, s.daemon_state, s.assertion, s.release_pending);
            return ferror(out) ? SERVICE_EXIT_ERROR : SERVICE_EXIT_OK;
        }
        fprintf(out,
                "iOS-Caffeinate service plan\n"
                "current_state=%s\n"
                "package.installation=%s\n"
                "package.database_identity=%s\n"
                "package.staged_template=%s\n"
                "managed_plist=%s\n"
                "configured_enablement=%s\n"
                "launchd.help=%s\n"
                "launchd.registration=%s\n"
                "runtime.process=%s\n"
                "ipc.availability=%s\n"
                "daemon.state=%s\n"
                "assertion.state=%s\n"
                "assertion.release_pending=%s\n"
                "automatic_activation=no\n"
                "automatic_assertion=no\n"
                "managed_profile=Disabled-false RunAtLoad-false KeepAlive-false\n"
                "managed_executable=%s\n"
                "managed_label=%s\n"
                "launchctl_mutation=UNVERIFIED\n"
                "enable_semantics=UNVERIFIED\n"
                "start_semantics=UNVERIFIED\n"
                "boot_persistence=UNVERIFIED\n"
                "crash_restart_policy=DISABLED_KEEPALIVE_FALSE\n"
                "changed=no\n",
                s.state, s.package, s.package_database, s.staged, s.managed_plist, s.enablement, s.help_state,
                s.registration, s.runtime, s.ipc, s.daemon_state, s.assertion, s.release_pending,
                IOSCAFFEINATE_SERVICE_EXECUTABLE, IOSCAFFEINATE_SERVICE_LABEL);
        return ferror(out) ? SERVICE_EXIT_ERROR : SERVICE_EXIT_OK;
    }
    if (strcmp(action, "stop") == 0) return service_stop(out, err);
    if (strcmp(action, "enable") != 0 && strcmp(action, "disable") != 0 &&
        strcmp(action, "start") != 0 && strcmp(action, "restart") != 0) {
        fprintf(err, "service: unknown action '%s'; changed=no\n", action);
        return SERVICE_EXIT_USAGE;
    }
    if (geteuid() != 0) {
        fprintf(err, "service %s: root privilege is required; changed=no\n", action);
        return SERVICE_EXIT_PRIVILEGE;
    }
    service_snapshot_t s; inspect_service(&s);
    service_policy_facts_t facts = policy_facts_from_snapshot(action, &s);
    int gate = service_policy_preflight(action, &facts);
    if (gate == SERVICE_EXIT_PRIVILEGE) {
        fprintf(err, "service %s: root privilege is required; changed=no\n", action);
        return gate;
    }
    if (gate == SERVICE_EXIT_INVALID_STATE) {
        fprintf(err, "service %s: package or lifecycle state is not valid for this operation; package=%s managed_plist=%s registration=%s runtime=%s changed=no\n",
                action, s.package, s.managed_plist, s.registration, s.runtime);
        return gate;
    }
    if (gate == SERVICE_EXIT_UNSAFE) {
        fprintf(err, "service %s: state, socket, assertion ownership, or cleanup is unsafe/unknown; state=%s socket=%s assertion=%s changed=no\n",
                action, s.state, s.socket_state, s.assertion);
        return gate;
    }
    if (gate == SERVICE_EXIT_UNSUPPORTED) {
        fprintf(err,
                "service %s: iOS 12 launchctl semantics or a required verified operation adapter are UNVERIFIED; no service, package, file, assertion, or launchd state was changed; changed=no\n",
                action);
        return gate;
    }
    fprintf(err,
            "service %s: no lifecycle operation is enabled in this build; changed=no\n",
            action);
    return SERVICE_EXIT_UNSUPPORTED;
}
