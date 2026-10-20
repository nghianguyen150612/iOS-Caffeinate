#define IOSCAFFEINATE_TEST_MOCK 1
#define main daemon_program_main
#include "../src/daemon.c"
#undef main

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static void check_status_is_observational(const char *request, const char *expected_field) {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(write(pair[1], request, strlen(request)) == (ssize_t)strlen(request));
    handle_client(pair[0]);

    char reply[4096] = {0};
    size_t used = 0;
    while (used + 1 < sizeof(reply)) {
        ssize_t n = read(pair[1], reply + used, sizeof(reply) - used - 1);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
        reply[used] = '\0';
        if (memchr(reply, '\n', used)) break;
    }

    assert(strstr(reply, expected_field) != NULL);
    assert(held_id == 71);
    assert(daemon_state == DAEMON_STATE_ACTIVE);
    close(pair[0]);
    close(pair[1]);
}

int main(void) {
    /* A private socket path allows the test to use the current host UID. */
    socket_path = "/tmp/ioscaffeinate-p013-readonly-test.sock";
    keep_running = 1;
    daemon_state = DAEMON_STATE_ACTIVE;
    held_id = 71;
    deadline = now() - 1.0;
    daemon_started_at = now();
    memset(&sched_store, 0, sizeof(sched_store));

    check_status_is_observational("SERVER STATUS\n", "assertion_owned=1");
    check_status_is_observational("STATUS\n", "active=yes");
    puts("P013 daemon read-only status check: 2 passed");
    return 0;
}
