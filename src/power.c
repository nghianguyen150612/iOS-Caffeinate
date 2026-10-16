#include "power.h"
#include <stdio.h>

#ifdef IOSCAFFEINATE_TEST_MOCK
/* Test-only backend. It does not inhibit system sleep. */
static uint32_t next_id = 1;
int power_init(char *error, size_t cap) {
    (void)error; (void)cap;
    return 0;
}
int power_acquire(uint32_t *id, char *error, size_t cap) {
    (void)error; (void)cap;
    *id = next_id++;
    return 0;
}
int power_release(uint32_t id, char *error, size_t cap) {
    (void)id; (void)error; (void)cap;
    return 0;
}
const char *power_backend_name(void) { return "MOCK_NO_POWER_EFFECT"; }
void power_cleanup(void) {}
#elif defined(__APPLE__)
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>

/* Resolve dynamically because these macOS IOPM symbols may not exist
 * or be functional on iOS 12. This backend requires device validation. */
typedef int32_t (*create_fn)(CFStringRef, uint32_t, CFStringRef, uint32_t *);
typedef int32_t (*release_fn)(uint32_t);
static void *iokit;
static create_fn create_assertion;
static release_fn release_assertion;

int power_init(char *error, size_t cap) {
    if (create_assertion && release_assertion) return 0;
    iokit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!iokit) {
        snprintf(error, cap, "IOKit dlopen failed: %s", dlerror());
        return -1;
    }
    void *create_symbol = dlsym(iokit, "IOPMAssertionCreateWithName");
    void *release_symbol = dlsym(iokit, "IOPMAssertionRelease");
    if (!create_symbol || !release_symbol) {
        snprintf(error, cap, "IOPM assertion symbols missing on this iOS build");
        dlclose(iokit);
        iokit = NULL;
        return -1;
    }
    create_assertion = (create_fn)create_symbol;
    release_assertion = (release_fn)release_symbol;
    return 0;
}

int power_acquire(uint32_t *id, char *error, size_t cap) {
    if (!create_assertion && power_init(error, cap) != 0) return -1;
    /* Request idle system sleep inhibition, not display-on. */
    int32_t rc = create_assertion(CFSTR("PreventUserIdleSystemSleep"), 255,
                                  CFSTR("ioscaffeinated timed keep-awake"), id);
    if (rc != 0) {
        snprintf(error, cap, "IOPMAssertionCreateWithName returned 0x%08x", (unsigned)rc);
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
    if (rc != 0) {
        snprintf(error, cap, "IOPMAssertionRelease returned 0x%08x", (unsigned)rc);
        return -1;
    }
    return 0;
}
const char *power_backend_name(void) { return "IOKit_UNVERIFIED_iOS12"; }
void power_cleanup(void) {
    create_assertion = NULL;
    release_assertion = NULL;
    if (iokit) dlclose(iokit);
    iokit = NULL;
}
#else
#error "No real backend for this OS. Use -DIOSCAFFEINATE_TEST_MOCK for tests only."
#endif
