#include "h005_power_inspector.h"

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOReturn.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/*
 * These private-on-iOS APIs use the IOPMLib.h ABI documented by Apple for
 * macOS: IOReturn function(CFDictionaryRef *result). They are resolved at
 * runtime because iOS runtime availability and privilege are not guaranteed.
 */
typedef IOReturn (*h005_copy_assertions_fn)(CFDictionaryRef *result);

static bool h005_number_i64(CFTypeRef value, int64_t *number)
{
    return value != NULL && CFGetTypeID(value) == CFNumberGetTypeID() &&
           CFNumberGetValue((CFNumberRef)value, kCFNumberSInt64Type, number);
}

static bool h005_level(CFTypeRef value, bool *known, bool *recognized, int32_t *level)
{
    int64_t numeric = 0;

    *known = h005_number_i64(value, &numeric) && numeric >= INT32_MIN && numeric <= INT32_MAX;
    if (!*known) {
        *recognized = false;
        return false;
    }
    *level = (int32_t)numeric;
    *recognized = *level == 0 || *level == 255;
    return *recognized;
}

static void h005_sanitize_cfstring(CFTypeRef value, char *output, size_t capacity,
                                  bool *known, bool *redacted)
{
    char temporary[H005_TEXT_CAPACITY * 4];
    CFIndex length;
    size_t index;

    *known = false;
    *redacted = false;
    output[0] = '\0';
    if (value == NULL || CFGetTypeID(value) != CFStringGetTypeID() || capacity == 0) {
        return;
    }
    length = CFStringGetLength((CFStringRef)value);
    if (length < 0 || (size_t)length >= sizeof(temporary) ||
        !CFStringGetCString((CFStringRef)value, temporary, sizeof(temporary),
                            kCFStringEncodingUTF8)) {
        (void)snprintf(output, capacity, "REDACTED");
        *known = true;
        *redacted = true;
        return;
    }

    for (index = 0; temporary[index] != '\0'; index++) {
        unsigned char character = (unsigned char)temporary[index];
        bool safe = (character >= 'a' && character <= 'z') ||
                    (character >= 'A' && character <= 'Z') ||
                    (character >= '0' && character <= '9') ||
                    character == '.' || character == '_' || character == '-';
        if (!safe || index + 1 >= capacity) {
            (void)snprintf(output, capacity, "REDACTED");
            *known = true;
            *redacted = true;
            return;
        }
        output[index] = (char)character;
    }
    output[index] = '\0';
    *known = true;
}

static h005_copy_assertions_fn h005_resolve_copy_function(const char *name)
{
    void *symbol = dlsym(RTLD_DEFAULT, name);
    h005_copy_assertions_fn function = NULL;

    _Static_assert(sizeof(symbol) == sizeof(function),
                   "Darwin ARM64 object and function pointers must have equal size");
    if (symbol != NULL) {
        memcpy(&function, &symbol, sizeof(function));
    }
    return function;
}

static void h005_source_failure(struct h005_source *source, IOReturn result)
{
    source->has_return_code = true;
    source->return_code = (int32_t)result;
    if (result == kIOReturnNotPrivileged) {
        source->state = H005_SOURCE_UNAVAILABLE;
        source->reason = H005_REASON_PRIVILEGE_DENIED;
    } else {
        source->state = H005_SOURCE_UNKNOWN;
        source->reason = H005_REASON_API_ERROR;
    }
}

static void h005_source_malformed(struct h005_source *source)
{
    source->state = H005_SOURCE_UNKNOWN;
    source->reason = H005_REASON_MALFORMED_RESULT;
}

static void h005_query_process_assertions(struct h005_snapshot *snapshot)
{
    h005_copy_assertions_fn copy_assertions =
        h005_resolve_copy_function("IOPMCopyAssertionsByProcess");
    CFDictionaryRef result = NULL;
    const void *keys[H005_MAX_PROCESS_OWNERS];
    const void *values[H005_MAX_PROCESS_OWNERS];
    CFIndex count;
    CFIndex process_index;

    if (copy_assertions == NULL) {
        snapshot->process_api.state = H005_SOURCE_UNAVAILABLE;
        snapshot->process_api.reason = H005_REASON_SYMBOL_MISSING;
        snapshot->process_api.symbol_available = false;
        return;
    }
    snapshot->process_api.symbol_available = true;

    {
        IOReturn result_code = copy_assertions(&result);
        if (result_code != kIOReturnSuccess) {
            h005_source_failure(&snapshot->process_api, result_code);
            if (result != NULL) {
                CFRelease(result);
            }
            return;
        }
        snapshot->process_api.has_return_code = true;
        snapshot->process_api.return_code = (int32_t)result_code;
    }
    if (result == NULL || CFGetTypeID(result) != CFDictionaryGetTypeID()) {
        h005_source_malformed(&snapshot->process_api);
        if (result != NULL) {
            CFRelease(result);
        }
        return;
    }

    count = CFDictionaryGetCount(result);
    if (count < 0) {
        h005_source_malformed(&snapshot->process_api);
        CFRelease(result);
        return;
    }
    snapshot->process_entries_seen = (size_t)count;
    if (count > H005_MAX_PROCESS_OWNERS) {
        snapshot->process_api.state = H005_SOURCE_UNKNOWN;
        snapshot->process_api.reason = H005_REASON_LIMIT_EXCEEDED;
        snapshot->process_api.truncated = true;
        CFRelease(result);
        return;
    }
    CFDictionaryGetKeysAndValues(result, keys, values);
    for (process_index = 0; process_index < count; process_index++) {
        const void *process_key = keys[process_index];
        CFTypeRef assertion_list = (CFTypeRef)values[process_index];
        int64_t pid_value = 0;
        bool pid_known = h005_number_i64((CFTypeRef)process_key, &pid_value) &&
                         pid_value >= 0 && pid_value <= INT32_MAX;
        CFIndex assertion_count;
        CFIndex assertion_index;

        if (assertion_list == NULL || CFGetTypeID(assertion_list) != CFArrayGetTypeID()) {
            h005_source_malformed(&snapshot->process_api);
            continue;
        }
        if (!pid_known) {
            h005_source_malformed(&snapshot->process_api);
        }
        assertion_count = CFArrayGetCount((CFArrayRef)assertion_list);
        if (assertion_count < 0) {
            h005_source_malformed(&snapshot->process_api);
            continue;
        }
        if ((size_t)assertion_count > H005_MAX_PROCESS_ASSERTIONS -
                                          snapshot->process_assertion_count) {
            snapshot->process_api.state = H005_SOURCE_UNKNOWN;
            snapshot->process_api.reason = H005_REASON_LIMIT_EXCEEDED;
            snapshot->process_api.truncated = true;
            assertion_count = (CFIndex)(H005_MAX_PROCESS_ASSERTIONS -
                                        snapshot->process_assertion_count);
        }
        for (assertion_index = 0; assertion_index < assertion_count; assertion_index++) {
            CFTypeRef item = (CFTypeRef)CFArrayGetValueAtIndex((CFArrayRef)assertion_list,
                                                               assertion_index);
            struct h005_process_assertion assertion;
            CFTypeRef type_value;
            CFTypeRef level_value;

            memset(&assertion, 0, sizeof(assertion));
            assertion.pid_known = pid_known;
            assertion.pid = pid_known ? (int32_t)pid_value : -1;
            if (item == NULL || CFGetTypeID(item) != CFDictionaryGetTypeID()) {
                h005_source_malformed(&snapshot->process_api);
                (void)h005_add_process_assertion(snapshot, &assertion);
                continue;
            }
            type_value = CFDictionaryGetValue((CFDictionaryRef)item, CFSTR("AssertType"));
            level_value = CFDictionaryGetValue((CFDictionaryRef)item, CFSTR("AssertLevel"));
            h005_sanitize_cfstring(type_value, assertion.type, sizeof(assertion.type),
                                   &assertion.type_known, &assertion.type_redacted);
            if (!assertion.type_known) {
                h005_source_malformed(&snapshot->process_api);
            }
            if (!h005_level(level_value, &assertion.level_known,
                            &assertion.level_recognized, &assertion.level)) {
                h005_source_malformed(&snapshot->process_api);
            }
            (void)h005_add_process_assertion(snapshot, &assertion);
        }
    }
    snapshot->process_api.state = snapshot->process_api.state == H005_SOURCE_NOT_RUN ?
                                  H005_SOURCE_COMPLETE : snapshot->process_api.state;
    CFRelease(result);
}

static void h005_query_aggregate_status(struct h005_snapshot *snapshot)
{
    h005_copy_assertions_fn copy_status =
        h005_resolve_copy_function("IOPMCopyAssertionsStatus");
    CFDictionaryRef result = NULL;
    const void *keys[H005_MAX_AGGREGATE_TYPES];
    const void *values[H005_MAX_AGGREGATE_TYPES];
    CFIndex count;
    CFIndex index;

    if (copy_status == NULL) {
        snapshot->aggregate_api.state = H005_SOURCE_UNAVAILABLE;
        snapshot->aggregate_api.reason = H005_REASON_SYMBOL_MISSING;
        snapshot->aggregate_api.symbol_available = false;
        return;
    }
    snapshot->aggregate_api.symbol_available = true;

    {
        IOReturn result_code = copy_status(&result);
        if (result_code != kIOReturnSuccess) {
            h005_source_failure(&snapshot->aggregate_api, result_code);
            if (result != NULL) {
                CFRelease(result);
            }
            return;
        }
        snapshot->aggregate_api.has_return_code = true;
        snapshot->aggregate_api.return_code = (int32_t)result_code;
    }
    if (result == NULL || CFGetTypeID(result) != CFDictionaryGetTypeID()) {
        h005_source_malformed(&snapshot->aggregate_api);
        if (result != NULL) {
            CFRelease(result);
        }
        return;
    }

    count = CFDictionaryGetCount(result);
    if (count < 0) {
        h005_source_malformed(&snapshot->aggregate_api);
        CFRelease(result);
        return;
    }
    if (count > H005_MAX_AGGREGATE_TYPES) {
        snapshot->aggregate_api.state = H005_SOURCE_UNKNOWN;
        snapshot->aggregate_api.reason = H005_REASON_LIMIT_EXCEEDED;
        snapshot->aggregate_api.truncated = true;
        CFRelease(result);
        return;
    }
    CFDictionaryGetKeysAndValues(result, keys, values);
    for (index = 0; index < count; index++) {
        struct h005_aggregate_status status;

        memset(&status, 0, sizeof(status));
        h005_sanitize_cfstring((CFTypeRef)keys[index], status.type,
                               sizeof(status.type), &status.type_known,
                               &status.type_redacted);
        if (!status.type_known) {
            h005_source_malformed(&snapshot->aggregate_api);
        }
        if (!h005_level((CFTypeRef)values[index], &status.level_known,
                        &status.level_recognized, &status.level)) {
            h005_source_malformed(&snapshot->aggregate_api);
        }
        (void)h005_add_aggregate_status(snapshot, &status);
    }
    snapshot->aggregate_api.state = snapshot->aggregate_api.state == H005_SOURCE_NOT_RUN ?
                                    H005_SOURCE_COMPLETE : snapshot->aggregate_api.state;
    CFRelease(result);
}

static void h005_query_driver_assertions(struct h005_snapshot *snapshot)
{
    CFMutableDictionaryRef matching = IOServiceMatching("IOPMrootDomain");
    io_service_t service;
    CFMutableDictionaryRef properties = NULL;
    kern_return_t result_code;
    CFTypeRef summary_value;
    CFTypeRef details_value;
    int64_t summary_mask = 0;
    CFIndex index;

    if (matching == NULL) {
        snapshot->driver_registry.state = H005_SOURCE_UNAVAILABLE;
        snapshot->driver_registry.reason = H005_REASON_SERVICE_UNAVAILABLE;
        return;
    }
    /* The SDK marks kIOMasterPortDefault unavailable on iOS; zero is the
     * documented default-port value accepted by IOServiceGetMatchingService. */
    service = IOServiceGetMatchingService(MACH_PORT_NULL, matching);
    if (service == IO_OBJECT_NULL) {
        snapshot->driver_registry.state = H005_SOURCE_UNAVAILABLE;
        snapshot->driver_registry.reason = H005_REASON_SERVICE_UNAVAILABLE;
        return;
    }

    result_code = IORegistryEntryCreateCFProperties(service, &properties,
                                                    kCFAllocatorDefault, 0);
    (void)IOObjectRelease(service);
    snapshot->driver_registry.has_return_code = true;
    snapshot->driver_registry.return_code = (int32_t)result_code;
    if (result_code != KERN_SUCCESS) {
        h005_source_failure(&snapshot->driver_registry, (IOReturn)result_code);
        if (properties != NULL) {
            CFRelease(properties);
        }
        return;
    }
    if (properties == NULL || CFGetTypeID(properties) != CFDictionaryGetTypeID()) {
        snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
        snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
        if (properties != NULL) {
            CFRelease(properties);
        }
        return;
    }

    summary_value = CFDictionaryGetValue(properties, CFSTR("DriverPMAssertions"));
    if (!h005_number_i64(summary_value, &summary_mask) || summary_mask < 0) {
        snapshot->driver_registry.state = summary_value == NULL ? H005_SOURCE_UNAVAILABLE :
                                                                   H005_SOURCE_UNKNOWN;
        snapshot->driver_registry.reason = summary_value == NULL ?
                                           H005_REASON_PROPERTY_UNAVAILABLE :
                                           H005_REASON_MALFORMED_RESULT;
        CFRelease(properties);
        return;
    }
    snapshot->driver_summary_known = true;
    snapshot->driver_summary_mask = (uint64_t)summary_mask;

    details_value = CFDictionaryGetValue(properties,
                                         CFSTR("DriverPMAssertionsDetailed"));
    if (details_value == NULL) {
        if (summary_mask == 0) {
            snapshot->driver_registry.state = H005_SOURCE_COMPLETE;
            snapshot->driver_registry.reason = H005_REASON_NONE;
        } else {
            snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
            snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
        }
        CFRelease(properties);
        return;
    }
    if (CFGetTypeID(details_value) != CFArrayGetTypeID()) {
        snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
        snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
        CFRelease(properties);
        return;
    }

    {
        CFIndex count = CFArrayGetCount((CFArrayRef)details_value);
        if (count < 0) {
            snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
            snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
            CFRelease(properties);
            return;
        }
        if (count > H005_MAX_DRIVER_ASSERTIONS) {
            snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
            snapshot->driver_registry.reason = H005_REASON_LIMIT_EXCEEDED;
            snapshot->driver_registry.truncated = true;
            count = H005_MAX_DRIVER_ASSERTIONS;
        }
        for (index = 0; index < count; index++) {
            CFTypeRef item = (CFTypeRef)CFArrayGetValueAtIndex((CFArrayRef)details_value,
                                                               index);
            struct h005_driver_assertion assertion;
            CFTypeRef id_value;
            CFTypeRef type_mask_value;
            CFTypeRef owner_value;
            CFTypeRef level_value;
            int64_t numeric = 0;

            memset(&assertion, 0, sizeof(assertion));
            if (item == NULL || CFGetTypeID(item) != CFDictionaryGetTypeID()) {
                snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
                (void)h005_add_driver_assertion(snapshot, &assertion);
                continue;
            }
            id_value = CFDictionaryGetValue((CFDictionaryRef)item, CFSTR("ID"));
            if (h005_number_i64(id_value, &numeric) && numeric >= 0) {
                assertion.id_known = true;
                assertion.id = (uint64_t)numeric;
            } else {
                snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
            }

            type_mask_value = CFDictionaryGetValue((CFDictionaryRef)item,
                                                   CFSTR("Assertions"));
            if (h005_number_i64(type_mask_value, &numeric) && numeric >= 0) {
                assertion.mask_known = true;
                assertion.type_mask = (uint64_t)numeric;
            } else {
                snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
            }

            owner_value = CFDictionaryGetValue((CFDictionaryRef)item, CFSTR("Owner"));
            if (owner_value != NULL) {
                h005_sanitize_cfstring(owner_value, assertion.owner,
                                       sizeof(assertion.owner), &assertion.owner_known,
                                       &assertion.owner_redacted);
                if (!assertion.owner_known) {
                    snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                    snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
                }
            } else {
                snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
            }

            level_value = CFDictionaryGetValue((CFDictionaryRef)item, CFSTR("Level"));
            if (!h005_level(level_value, &assertion.level_known,
                            &assertion.level_recognized, &assertion.level)) {
                snapshot->driver_registry.state = H005_SOURCE_UNKNOWN;
                snapshot->driver_registry.reason = H005_REASON_MALFORMED_RESULT;
            }
            (void)h005_add_driver_assertion(snapshot, &assertion);
        }
    }

    if (snapshot->driver_registry.state == H005_SOURCE_NOT_RUN) {
        snapshot->driver_registry.state = H005_SOURCE_COMPLETE;
        snapshot->driver_registry.reason = H005_REASON_NONE;
    }
    CFRelease(properties);
}

int main(int argc, char **argv)
{
    const struct h005_provider provider = {
        h005_query_process_assertions,
        h005_query_aggregate_status,
        h005_query_driver_assertions
    };
    struct h005_snapshot snapshot;
    char output[H005_JSON_CAPACITY];
    size_t output_size = 0;

    (void)argv;
    if (argc != 1) {
        fputs("usage: ios-power-preflight-inspector\n", stderr);
        return 64;
    }

    (void)alarm(H005_EXECUTION_TIMEOUT_SECONDS);
    h005_collect(&provider, &snapshot);
    (void)alarm(0);
    if (!h005_write_json(&snapshot, output, sizeof(output), &output_size)) {
        fputs("{\"schema\":\"ioscaffeinate.h005.power-inspector.v2\","
              "\"read_only\":true,\"assertion_mutation_attempted\":false,"
              "\"execution_timeout_seconds\":15,"
              "\"classification\":\"UNKNOWN\","
              "\"project_assertion_attribution\":\"NOT_PERFORMED_NO_PROCESS_NAMES_QUERIED\","
              "\"sleep_prevention_ownership\":\"UNESTABLISHED\","
              "\"enumeration_complete\":false,"
              "\"error\":\"OUTPUT_LIMIT\"}\n", stdout);
        return 21;
    }
    if (fwrite(output, 1, output_size, stdout) != output_size) {
        return 21;
    }
    return h005_exit_code(snapshot.classification);
}
