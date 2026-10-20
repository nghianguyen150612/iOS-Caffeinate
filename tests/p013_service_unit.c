#define _POSIX_C_SOURCE 200809L
#include "../src/service.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

typedef struct {
    const char *help;
    const char *list;
    int help_exit;
    int list_exit;
    unsigned calls;
    char commands[16][32];
} fake_launchctl_t;

static int fake_launchctl(void *context, const char *subcommand,
                          char *output, size_t output_cap, int *exit_status) {
    fake_launchctl_t *fake = context;
    assert(fake->calls < 16);
    snprintf(fake->commands[fake->calls], sizeof(fake->commands[0]), "%s", subcommand);
    fake->calls++;
    const char *result = "";
    if (strcmp(subcommand, "package") == 0) {
        result = "dpkg-query: no packages found matching com.ioscaffeinate.cli\n";
        *exit_status = 1;
    } else if (strcmp(subcommand, "help") == 0) {
        result = fake->help;
        *exit_status = fake->help_exit;
    } else if (strcmp(subcommand, "list") == 0) {
        result = fake->list;
        *exit_status = fake->list_exit;
    } else {
        /* A mocked lifecycle must never issue a host mutation command. */
        *exit_status = 99;
        return -1;
    }
    if (strlen(result) + 1 > output_cap) return -1;
    snprintf(output, output_cap, "%s", result);
    return 0;
}

static char *run_cli(const char *action, int *exit_code) {
    FILE *out = tmpfile();
    FILE *err = tmpfile();
    assert(out && err);
    char *args[] = {(char *)action};
    *exit_code = service_command(1, args, out, err);
    fflush(out); fflush(err);
    assert(fseek(out, 0, SEEK_END) == 0);
    long length = ftell(out);
    assert(length >= 0);
    rewind(out);
    char *text = calloc((size_t)length + 1, 1);
    assert(text != NULL);
    assert(fread(text, 1, (size_t)length, out) == (size_t)length);
    fclose(out); fclose(err);
    return text;
}

static void write_file(const char *path, const char *contents, mode_t mode) {
    FILE *file = fopen(path, "wb");
    assert(file != NULL);
    size_t length = strlen(contents);
    assert(fwrite(contents, 1, length, file) == length);
    assert(fclose(file) == 0);
    assert(chmod(path, mode) == 0);
}

static unsigned checks;

static void test_plist_generation_and_atomic_install(void) {
    char template_dir[] = "/tmp/ioscaf-p013-XXXXXX";
    char *dir = mkdtemp(template_dir);
    assert(dir != NULL);
    char path[512];
    snprintf(path, sizeof(path), "%s/com.ioscaffeinate.daemon.plist", dir);

    FILE *generated = tmpfile();
    assert(generated != NULL);
    assert(service_write_managed_plist(generated) == 0);
    assert(fflush(generated) == 0);
    assert(fseek(generated, 0, SEEK_END) == 0);
    long generated_len = ftell(generated);
    assert(generated_len > 0 && generated_len < 4096);
    rewind(generated);
    char generated_data[4096] = {0};
    assert(fread(generated_data, 1, (size_t)generated_len, generated) == (size_t)generated_len);
    fclose(generated);
    assert(strstr(generated_data, "<key>Disabled</key><false/>") != NULL);
    assert(strstr(generated_data, "<key>RunAtLoad</key><false/>") != NULL);
    assert(strstr(generated_data, "<key>KeepAlive</key><false/>") != NULL);
    assert(strstr(generated_data, "/usr/local/bin/ios-caffeinated") != NULL);
    assert(strstr(generated_data, "KeepAlive</key><true/>") == NULL);
    checks++;

    char detail[192] = {0};
    assert(service_install_managed_plist(path, geteuid(), detail, sizeof(detail)) == 0);
    int enabled = 0;
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) == 0);
    assert(enabled == 1);
    struct stat st;
    assert(lstat(path, &st) == 0 && S_ISREG(st.st_mode));
    assert(st.st_uid == geteuid() && st.st_nlink == 1 && (st.st_mode & 07777) == 0644);
    checks++;

    assert(service_install_managed_plist(path, geteuid(), detail, sizeof(detail)) != 0);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) == 0);
    checks++;

    char hardlink[512];
    snprintf(hardlink, sizeof(hardlink), "%s/hardlink.plist", dir);
    assert(link(path, hardlink) == 0);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(unlink(hardlink) == 0);
    checks++;

    assert(chmod(path, 0600) == 0);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(chmod(path, 0644) == 0);
    checks++;

    assert(service_validate_managed_plist(path, (uid_t)(geteuid() + 1), &enabled,
                                          detail, sizeof(detail)) != 0);
    checks++;

    assert(unlink(path) == 0);
    assert(symlink("/etc/passwd", path) == 0);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(unlink(path) == 0);
    checks++;

    write_file(path, "<plist><dict><key>KeepAlive</key><true/></dict></plist>\n", 0644);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(unlink(path) == 0);
    checks++;

    char collision[4096];
    snprintf(collision, sizeof(collision), "%s", generated_data);
    char *label = strstr(collision, "com.ioscaffeinate.daemon");
    assert(label != NULL);
    const char replacement[] = "com.unrelated.daemon";
    size_t old_label_len = strlen("com.ioscaffeinate.daemon");
    size_t new_label_len = sizeof(replacement) - 1;
    memmove(label + new_label_len, label + old_label_len,
            strlen(label + old_label_len) + 1);
    memcpy(label, replacement, new_label_len);
    write_file(path, collision, 0644);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(unlink(path) == 0);
    checks++;

    char link_dir[512];
    snprintf(link_dir, sizeof(link_dir), "%s/linkdir", dir);
    assert(mkdir(link_dir, 0700) == 0);
    char alias_dir[512];
    snprintf(alias_dir, sizeof(alias_dir), "%s/alias", dir);
    assert(symlink(link_dir, alias_dir) == 0);
    char alias_path[1024];
    snprintf(alias_path, sizeof(alias_path), "%s/plist", alias_dir);
    assert(service_install_managed_plist(alias_path, geteuid(), detail, sizeof(detail)) != 0);
    assert(service_validate_managed_plist(alias_path, geteuid(), &enabled, detail, sizeof(detail)) != 0);
    assert(service_install_managed_plist(path, geteuid(), detail, sizeof(detail)) == 0);
    assert(service_validate_managed_plist(path, geteuid(), &enabled, detail, sizeof(detail)) == 0);
    checks++;

    assert(unlink(path) == 0);
    assert(unlink(alias_dir) == 0);
    assert(rmdir(link_dir) == 0);
    assert(rmdir(dir) == 0);
}

static void test_read_only_diagnostics_and_launchctl_injection(void) {
    fake_launchctl_t fake = {
        .help = "Usage: launchctl [help | list | load | unload | start | stop | enable | disable]\n",
        .list = "PID\tStatus\tLabel\n-\t0\tcom.ioscaffeinate.daemon\n",
        .help_exit = 0,
        .list_exit = 0
    };
    service_test_set_runner(fake_launchctl, &fake);
    const char *actions[] = {"status", "doctor", "plan"};
    for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i) {
        int code = -1;
        char *output = run_cli(actions[i], &code);
        assert(code == SERVICE_EXIT_OK);
        if (strcmp(actions[i], "plan") == 0) {
            assert(strstr(output, "launchctl_mutation=UNVERIFIED") != NULL);
        } else {
            assert(strstr(output, "launchd.help=AVAILABLE") != NULL);
            assert(strstr(output, "launchd.registration=REGISTERED") != NULL);
            assert(strstr(output, "launchd.command.start=DETECTED_UNVERIFIED") != NULL);
        }
        assert(strstr(output, "changed=no") != NULL);
        assert(strstr(output, "assertion_is_implied_by_registration=no") != NULL ||
               strcmp(actions[i], "plan") == 0);
        free(output);
    }
    assert(fake.calls == 9);
    for (unsigned i = 0; i < fake.calls; ++i)
        assert(strcmp(fake.commands[i], "package") == 0 || strcmp(fake.commands[i], "help") == 0 ||
               strcmp(fake.commands[i], "list") == 0);
    checks++;

    fake = (fake_launchctl_t){
        .help = "Usage: launchctl help|list\n",
        .list = "PID Status Label\n",
        .help_exit = 0,
        .list_exit = 0
    };
    service_test_set_runner(fake_launchctl, &fake);
    int code = -1;
    char *output = run_cli("status", &code);
    assert(code == SERVICE_EXIT_OK);
    assert(strstr(output, "launchd.command.bootstrap=UNSUPPORTED") != NULL);
    assert(strstr(output, "launchd.registration=NOT_REGISTERED") != NULL);
    free(output);
    checks++;

    fake = (fake_launchctl_t){
        .help = "permission denied\n",
        .list = "permission denied\n",
        .help_exit = 1,
        .list_exit = 1
    };
    service_test_set_runner(fake_launchctl, &fake);
    output = run_cli("doctor", &code);
    assert(code == SERVICE_EXIT_OK);
    assert(strstr(output, "launchd.help=UNVERIFIED") != NULL);
    assert(strstr(output, "launchd.registration=UNVERIFIED") != NULL);
    free(output);
    checks++;

    service_test_set_runner(NULL, NULL);
}

static void test_mutations_fail_closed(void) {
    fake_launchctl_t fake = {
        .help = "Usage: launchctl [help | list | start | stop | enable | disable]\n",
        .list = "PID Status Label\n",
        .help_exit = 0,
        .list_exit = 0
    };
    service_test_set_runner(fake_launchctl, &fake);
    const char *actions[] = {"enable", "disable", "start", "restart"};
    for (size_t i = 0; i < sizeof(actions) / sizeof(actions[0]); ++i) {
        int code = -1;
        char *output = run_cli(actions[i], &code);
        assert(code == SERVICE_EXIT_UNSUPPORTED || code == SERVICE_EXIT_PRIVILEGE ||
               code == SERVICE_EXIT_INVALID_STATE || code == SERVICE_EXIT_UNSAFE);
        assert(fake.calls <= 12);
        free(output);
    }
    for (unsigned i = 0; i < fake.calls; ++i)
        assert(strcmp(fake.commands[i], "package") == 0 || strcmp(fake.commands[i], "help") == 0 ||
               strcmp(fake.commands[i], "list") == 0);
    checks++;
    service_test_set_runner(NULL, NULL);
}

static void test_lifecycle_preflight_matrix(void) {
    service_policy_facts_t facts = {
        .privileged = 1,
        .package_valid = 1,
        .staged_valid = 1,
        .managed = 1,
        .registered = 1,
        .runtime = 0,
        .socket = 0,
        .daemon_state = 0,
        .assertion = 0,
        .release_pending = 0,
        .invariant_ok = 1,
        .shutdown_protocol_supported = 1
    };
    assert(service_test_preflight("enable", &facts) == SERVICE_EXIT_INVALID_STATE);
    facts.enable_combines_start = 1;
    facts.combined_behavior_consent = 0;
    facts.managed = 0;
    facts.registered = 0;
    assert(service_test_preflight("enable", &facts) == SERVICE_EXIT_UNSUPPORTED);
    facts.combined_behavior_consent = 1;
    facts.enable_verified = 1;
    assert(service_test_preflight("enable", &facts) == SERVICE_EXIT_OK);

    facts = (service_policy_facts_t){
        .privileged = 1, .package_valid = 1, .staged_valid = 1,
        .managed = 1, .registered = 1, .runtime = 0, .socket = 0,
        .daemon_state = 0, .assertion = 0, .release_pending = 0,
        .invariant_ok = 1
    };
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_UNSUPPORTED);
    facts.start_verified = 1;
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_OK);
    facts.runtime = 1;
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_INVALID_STATE);
    facts.runtime = 0; facts.socket = 2;
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_UNSAFE);
    facts.socket = 0; facts.registered = 2;
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_UNSAFE);

    facts = (service_policy_facts_t){
        .privileged = 1, .package_valid = 1, .staged_valid = 1,
        .managed = 1, .registered = 1, .runtime = 1, .socket = 1,
        .daemon_state = 1, .assertion = 1, .release_pending = 0,
        .invariant_ok = 1, .shutdown_protocol_supported = 1
    };
    assert(service_test_preflight("stop", &facts) == SERVICE_EXIT_OK);
    assert(service_test_preflight("restart", &facts) == SERVICE_EXIT_UNSUPPORTED);
    facts.start_verified = 1;
    assert(service_test_preflight("restart", &facts) == SERVICE_EXIT_OK);
    facts.daemon_state = 2; facts.assertion = 2; facts.release_pending = 1;
    assert(service_test_preflight("stop", &facts) == SERVICE_EXIT_UNSAFE);
    assert(service_test_preflight("restart", &facts) == SERVICE_EXIT_UNSAFE);
    facts.daemon_state = 0; facts.assertion = 3; facts.release_pending = 2;
    assert(service_test_preflight("stop", &facts) == SERVICE_EXIT_UNSAFE);

    facts = (service_policy_facts_t){
        .privileged = 1, .package_valid = 1, .staged_valid = 1,
        .managed = 1, .registered = 1, .runtime = 0, .socket = 0,
        .daemon_state = 0, .assertion = 0, .release_pending = 0,
        .invariant_ok = 1
    };
    assert(service_test_preflight("disable", &facts) == SERVICE_EXIT_UNSUPPORTED);
    facts.disable_verified = 1;
    assert(service_test_preflight("disable", &facts) == SERVICE_EXIT_OK);
    facts.runtime = 1;
    assert(service_test_preflight("disable", &facts) == SERVICE_EXIT_INVALID_STATE);
    facts.privileged = 0;
    assert(service_test_preflight("enable", &facts) == SERVICE_EXIT_PRIVILEGE);
    facts.privileged = 1; facts.package_valid = 0;
    assert(service_test_preflight("enable", &facts) == SERVICE_EXIT_INVALID_STATE);
    facts.package_valid = 1; facts.socket = 3;
    assert(service_test_preflight("start", &facts) == SERVICE_EXIT_UNSAFE);
    checks++;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "--emit-managed") == 0) {
        FILE *file = fopen(argv[2], "wb");
        if (!file || service_write_managed_plist(file) != 0 || fclose(file) != 0 ||
            chmod(argv[2], 0644) != 0) return 1;
        return 0;
    }
    test_plist_generation_and_atomic_install();
    test_read_only_diagnostics_and_launchctl_injection();
    test_mutations_fail_closed();
    test_lifecycle_preflight_matrix();
    printf("P013 native service checks: %u passed\n", checks);
    return 0;
}
