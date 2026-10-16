#include "power.h"
#include <stdio.h>

static char diagnostics[512] = "load=not_attempted create_symbol=not_checked release_symbol=not_checked create_rc=not_called release_rc=not_called";
const char *power_diagnostics(void) { return diagnostics; }

#ifdef IOSCAFFEINATE_TEST_MOCK
#include <stdlib.h>
/* Test-only backend. It does not inhibit system sleep. Fault injection is
 * compiled out of the Apple backend, including all environment overrides. */
static uint32_t next_id = 1;
int power_init(char *error, size_t cap) {
    (void)error; (void)cap;
    snprintf(diagnostics, sizeof(diagnostics), "load=mock create_symbol=mock release_symbol=mock");
    return 0;
}
int power_acquire(uint32_t *id, char *error, size_t cap) {
    if (getenv("IOSCAFFEINATE_MOCK_FAIL_ACQUIRE")) {
        snprintf(diagnostics, sizeof(diagnostics), "load=mock create_symbol=mock release_symbol=mock create_rc=0xe00002c7 last_assertion_id=0 release_rc=not_called");
        snprintf(error, cap, "mock create_rc=0xe00002c7");
        return -1;
    }
    *id = next_id++;
    snprintf(diagnostics, sizeof(diagnostics), "load=mock create_symbol=mock release_symbol=mock create_rc=0x00000000 last_assertion_id=%u release_rc=not_called", *id);
    return 0;
}
int power_release(uint32_t id, char *error, size_t cap) {
    if (getenv("IOSCAFFEINATE_MOCK_FAIL_RELEASE")) {
        snprintf(diagnostics, sizeof(diagnostics), "load=mock create_symbol=mock release_symbol=mock create_rc=0x00000000 last_assertion_id=%u release_rc=0xe00002bc", id);
        snprintf(error, cap, "mock release_rc=0xe00002bc");
        return -1;
    }
    snprintf(diagnostics, sizeof(diagnostics), "load=mock create_symbol=mock release_symbol=mock create_rc=0x00000000 last_assertion_id=%u release_rc=0x00000000", id);
    return 0;
}
const char *power_backend_name(void) { return "MOCK_NO_POWER_EFFECT"; }
void power_cleanup(void) {}
#elif defined(__APPLE__)
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>

/* Symbols are resolved at runtime: SDK/link success does not establish iOS
 * implementation support. No static IOKit or private-framework dependency. */
typedef int32_t (*create_fn)(CFStringRef, uint32_t, CFStringRef, uint32_t *);
typedef int32_t (*release_fn)(uint32_t);
static void *iokit;
static create_fn create_assertion;
static release_fn release_assertion;
static const char *create_result = "not_called";
static const char *release_result = "not_called";
static char create_code[16], release_code[16];
static uint32_t last_id;

static void update_diagnostics(const char *load) {
    snprintf(diagnostics, sizeof(diagnostics),
             "load=%s create_symbol=%s release_symbol=%s create_rc=%s last_assertion_id=%u release_rc=%s",
             load, create_assertion ? "resolved" : "missing",
             release_assertion ? "resolved" : "missing", create_result, last_id, release_result);
}
int power_init(char *error, size_t cap) {
    if (create_assertion && release_assertion) return 0;
    if (!iokit) iokit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!iokit) {
        snprintf(error, cap, "IOKit dlopen failed: %s", dlerror());
        update_diagnostics("failed");
        return -1;
    }
    create_assertion = (create_fn)dlsym(iokit, "IOPMAssertionCreateWithName");
    release_assertion = (release_fn)dlsym(iokit, "IOPMAssertionRelease");
    update_diagnostics("ok");
    if (!create_assertion || !release_assertion) {
        snprintf(error, cap, "IOPM assertion symbols missing on this iOS build");
        return -1;
    }
    return 0;
}
int power_acquire(uint32_t *id, char *error, size_t cap) {
    if (power_init(error, cap) != 0) return -1;
    *id = 0;
    release_result = "not_called";
    int32_t rc = create_assertion(CFSTR("PreventUserIdleSystemSleep"), 255,
                                  CFSTR("ios-caffeinated timed keep-awake"), id);
    snprintf(create_code, sizeof(create_code), "0x%08x", (unsigned)rc);
    create_result = create_code;
    last_id = *id;
    update_diagnostics("ok");
    if (rc != 0 || *id == 0) {
        snprintf(error, cap, "IOPMAssertionCreateWithName returned %s assertion_id=%u", create_code, *id);
        return -1;
    }
    return 0;
}
int power_release(uint32_t id, char *error, size_t cap) {
    if (!release_assertion) {
        snprintf(error, cap, "release symbol not resolved");
        return -1;
    }
    int32_t rc = release_assertion(id);
    snprintf(release_code, sizeof(release_code), "0x%08x", (unsigned)rc);
    release_result = release_code;
    update_diagnostics("ok");
    if (rc != 0) {
        snprintf(error, cap, "IOPMAssertionRelease returned %s assertion_id=%u", release_code, id);
        return -1;
    }
    return 0;
}
const char *power_backend_name(void) { return "IOKit_RUNTIME_UNVERIFIED"; }
void power_cleanup(void) {
    create_assertion = NULL;
    release_assertion = NULL;
    if (iokit) dlclose(iokit);
    iokit = NULL;
}
#else
#error "No real backend for this OS. Use -DIOSCAFFEINATE_TEST_MOCK for tests only."
#endif
