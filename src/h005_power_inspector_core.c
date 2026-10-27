#include "h005_power_inspector.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

struct h005_json_writer {
    char *buffer;
    size_t capacity;
    size_t used;
    bool failed;
};

static void h005_json_append(struct h005_json_writer *writer, const char *format, ...)
{
    int result;
    va_list arguments;

    if (writer->failed || writer->used >= writer->capacity) {
        writer->failed = true;
        return;
    }

    va_start(arguments, format);
    result = vsnprintf(writer->buffer + writer->used,
                       writer->capacity - writer->used, format, arguments);
    va_end(arguments);

    if (result < 0 || (size_t)result >= writer->capacity - writer->used) {
        writer->failed = true;
        return;
    }
    writer->used += (size_t)result;
}

static void h005_json_string(struct h005_json_writer *writer, const char *value)
{
    const unsigned char *cursor = (const unsigned char *)value;

    h005_json_append(writer, "\"");
    while (*cursor != 0 && !writer->failed) {
        switch (*cursor) {
        case '"':
            h005_json_append(writer, "\\\"");
            break;
        case '\\':
            h005_json_append(writer, "\\\\");
            break;
        case '\b':
            h005_json_append(writer, "\\b");
            break;
        case '\f':
            h005_json_append(writer, "\\f");
            break;
        case '\n':
            h005_json_append(writer, "\\n");
            break;
        case '\r':
            h005_json_append(writer, "\\r");
            break;
        case '\t':
            h005_json_append(writer, "\\t");
            break;
        default:
            if (*cursor < 0x20) {
                h005_json_append(writer, "\\u%04x", (unsigned int)*cursor);
            } else {
                h005_json_append(writer, "%c", (int)*cursor);
            }
            break;
        }
        cursor++;
    }
    h005_json_append(writer, "\"");
}

static void h005_json_optional_text(struct h005_json_writer *writer, bool known,
                                   const char *value)
{
    if (known) {
        h005_json_string(writer, value);
    } else {
        h005_json_append(writer, "null");
    }
}

static const char *h005_current_status(bool known, bool recognized, int32_t level)
{
    if (!known || !recognized) {
        return "UNKNOWN";
    }
    return level == 0 ? "OFF" : "ON";
}

enum h005_assertion_role {
    H005_ROLE_SLEEP_PREVENTION = 0,
    H005_ROLE_DISPLAY_ONLY,
    H005_ROLE_NETWORK_ACTIVITY,
    H005_ROLE_OTHER_KNOWN,
    H005_ROLE_UNKNOWN
};

static enum h005_assertion_role h005_assertion_role(const char *type, bool known)
{
    if (!known) {
        return H005_ROLE_UNKNOWN;
    }
    if (strcmp(type, "PreventUserIdleSystemSleep") == 0 ||
        strcmp(type, "PreventSystemSleep") == 0 ||
        strcmp(type, "NoIdleSleepAssertion") == 0) {
        return H005_ROLE_SLEEP_PREVENTION;
    }
    if (strcmp(type, "PreventUserIdleDisplaySleep") == 0 ||
        strcmp(type, "NoDisplaySleepAssertion") == 0) {
        return H005_ROLE_DISPLAY_ONLY;
    }
    if (strcmp(type, "NetworkAccess") == 0) {
        return H005_ROLE_NETWORK_ACTIVITY;
    }
    if (strcmp(type, "PreventDiskIdle") == 0 ||
        strcmp(type, "BackgroundTask") == 0) {
        return H005_ROLE_OTHER_KNOWN;
    }
    return H005_ROLE_UNKNOWN;
}

static const char *h005_assertion_role_name(enum h005_assertion_role role)
{
    switch (role) {
    case H005_ROLE_SLEEP_PREVENTION:
        return "SLEEP_PREVENTION";
    case H005_ROLE_DISPLAY_ONLY:
        return "DISPLAY_ONLY";
    case H005_ROLE_NETWORK_ACTIVITY:
        return "NETWORK_ACTIVITY";
    case H005_ROLE_OTHER_KNOWN:
        return "OTHER_KNOWN";
    case H005_ROLE_UNKNOWN:
    default:
        return "UNKNOWN";
    }
}

const char *h005_sleep_prevention_assessment_name(
    enum h005_sleep_prevention_assessment assessment)
{
    switch (assessment) {
    case H005_SLEEP_NO_ACTIVE_PREVENTION_OBSERVED:
        return "NO_ACTIVE_SLEEP_PREVENTION_OBSERVED_COMPLETE";
    case H005_SLEEP_ACTIVE_OWNER_IDENTIFIED:
        return "ACTIVE_SLEEP_PREVENTION_OWNER_IDENTIFIED";
    case H005_SLEEP_ACTIVE_OWNER_UNKNOWN:
        return "ACTIVE_SLEEP_PREVENTION_OWNER_UNKNOWN";
    case H005_SLEEP_UNESTABLISHED:
    default:
        return "UNESTABLISHED";
    }
}

static bool h005_level_is_on(bool known, bool recognized, int32_t level)
{
    return known && recognized && level != 0;
}

static bool h005_source_is_complete(const struct h005_source *source);

static void h005_assess_sleep_prevention(struct h005_snapshot *snapshot)
{
    bool uncertain = false;
    bool active_owner_identified = false;
    bool active_owner_unknown = false;
    bool driver_cpu_owner_found = false;
    uint64_t detail_union = 0;
    size_t index;

    if (!h005_source_is_complete(&snapshot->process_api) ||
        !h005_source_is_complete(&snapshot->aggregate_api) ||
        !h005_source_is_complete(&snapshot->driver_registry) ||
        !snapshot->driver_summary_known) {
        uncertain = true;
    }

    for (index = 0; index < snapshot->process_assertion_count; index++) {
        const struct h005_process_assertion *assertion = &snapshot->process_assertions[index];
        enum h005_assertion_role role = h005_assertion_role(assertion->type,
                                                             assertion->type_known);
        bool active = h005_level_is_on(assertion->level_known,
                                       assertion->level_recognized,
                                       assertion->level);
        if (!assertion->pid_known || !assertion->type_known || !assertion->level_known ||
            !assertion->level_recognized) {
            uncertain = true;
        }
        if (active && role == H005_ROLE_SLEEP_PREVENTION) {
            if (assertion->pid_known) {
                active_owner_identified = true;
            } else {
                active_owner_unknown = true;
            }
        } else if (active && (role == H005_ROLE_UNKNOWN ||
                             role == H005_ROLE_DISPLAY_ONLY)) {
            uncertain = true;
        }
    }

    for (index = 0; index < snapshot->aggregate_type_count; index++) {
        const struct h005_aggregate_status *status = &snapshot->aggregate_status[index];
        enum h005_assertion_role role = h005_assertion_role(status->type,
                                                            status->type_known);
        bool active = h005_level_is_on(status->level_known,
                                       status->level_recognized,
                                       status->level);
        size_t process_index;
        bool owner_found = false;

        if (!status->type_known || !status->level_known || !status->level_recognized) {
            uncertain = true;
        }
        if (active && role == H005_ROLE_SLEEP_PREVENTION) {
            for (process_index = 0;
                 process_index < snapshot->process_assertion_count;
                 process_index++) {
                const struct h005_process_assertion *process =
                    &snapshot->process_assertions[process_index];
                if (process->pid_known && process->type_known &&
                    strcmp(process->type, status->type) == 0 &&
                    h005_level_is_on(process->level_known,
                                     process->level_recognized,
                                     process->level)) {
                    owner_found = true;
                    break;
                }
            }
            if (owner_found) {
                active_owner_identified = true;
            } else {
                active_owner_unknown = true;
            }
        } else if (active && (role == H005_ROLE_UNKNOWN ||
                             role == H005_ROLE_DISPLAY_ONLY)) {
            uncertain = true;
        }
    }

    for (index = 0; index < snapshot->driver_assertion_count; index++) {
        const struct h005_driver_assertion *assertion =
            &snapshot->driver_assertions[index];
        const uint64_t known_driver_bits = UINT64_C(0x000003fd);

        if (!assertion->mask_known || !assertion->owner_known || assertion->owner_redacted ||
            !assertion->level_known || !assertion->level_recognized) {
            uncertain = true;
            continue;
        }
        detail_union |= assertion->type_mask;
        if ((assertion->type_mask & ~known_driver_bits) != 0) {
            uncertain = true;
        }
        if ((assertion->type_mask & UINT64_C(0x01)) != 0) {
            if (assertion->level != 0) {
                driver_cpu_owner_found = true;
                active_owner_identified = true;
            } else {
                uncertain = true;
            }
        }
    }

    if (snapshot->driver_summary_known && detail_union != snapshot->driver_summary_mask) {
        uncertain = true;
    }
    if (snapshot->driver_summary_known &&
        (snapshot->driver_summary_mask & ~UINT64_C(0x000003fd)) != 0) {
        uncertain = true;
    }
    if (snapshot->driver_summary_known &&
        (snapshot->driver_summary_mask & UINT64_C(0x01)) != 0 &&
        !driver_cpu_owner_found) {
        active_owner_unknown = true;
    }

    if (active_owner_unknown) {
        snapshot->sleep_prevention_assessment = H005_SLEEP_ACTIVE_OWNER_UNKNOWN;
    } else if (active_owner_identified) {
        snapshot->sleep_prevention_assessment = H005_SLEEP_ACTIVE_OWNER_IDENTIFIED;
    } else if (uncertain) {
        snapshot->sleep_prevention_assessment = H005_SLEEP_UNESTABLISHED;
    } else {
        snapshot->sleep_prevention_assessment =
            H005_SLEEP_NO_ACTIVE_PREVENTION_OBSERVED;
    }
}

static const char *h005_driver_bit_name(unsigned int bit)
{
    switch (bit) {
    case 0:
        return "CPU_DARK_WAKE";
    case 2:
        return "USB_EXTERNAL_DEVICE";
    case 3:
        return "BLUETOOTH_HID_PAIRED";
    case 4:
        return "EXTERNAL_MEDIA_MOUNTED";
    case 5:
        return "RESERVED_THUNDERBOLT";
    case 6:
        return "PREVENT_DISPLAY_SLEEP";
    case 7:
        return "RESERVED_STORAGE";
    case 8:
        return "MAGIC_PACKET_WAKE_ENABLED";
    case 9:
        return "NETWORK_KEEPALIVE_ACTIVE";
    default:
        return "UNKNOWN";
    }
}

static void h005_json_driver_categories(struct h005_json_writer *writer,
                                        bool mask_known, uint64_t mask)
{
    unsigned int bit;
    bool first = true;

    h005_json_append(writer, "[");
    if (mask_known) {
        for (bit = 0; bit < 64; bit++) {
            if ((mask & (UINT64_C(1) << bit)) != 0) {
                if (!first) {
                    h005_json_append(writer, ",");
                }
                h005_json_string(writer, h005_driver_bit_name(bit));
                first = false;
            }
        }
    }
    h005_json_append(writer, "]");
}

static void h005_json_source(struct h005_json_writer *writer,
                             const struct h005_source *source,
                             bool include_symbol_availability,
                             size_t record_count)
{
    h005_json_append(writer, "{\"state\":");
    h005_json_string(writer, h005_source_state_name(source->state));
    h005_json_append(writer, ",\"reason\":");
    h005_json_string(writer, h005_source_reason_name(source->reason));
    if (include_symbol_availability) {
        h005_json_append(writer, ",\"symbol_available\":%s",
                         source->symbol_available ? "true" : "false");
    }
    h005_json_append(writer, ",\"return_code\":");
    if (source->has_return_code) {
        h005_json_append(writer, "%d", source->return_code);
    } else {
        h005_json_append(writer, "null");
    }
    h005_json_append(writer, ",\"records\":%zu,\"truncated\":%s}",
                     record_count, source->truncated ? "true" : "false");
}

void h005_snapshot_reset(struct h005_snapshot *snapshot)
{
    if (snapshot != NULL) {
        memset(snapshot, 0, sizeof(*snapshot));
        snapshot->process_api.state = H005_SOURCE_NOT_RUN;
        snapshot->aggregate_api.state = H005_SOURCE_NOT_RUN;
        snapshot->driver_registry.state = H005_SOURCE_NOT_RUN;
        snapshot->classification = H005_UNKNOWN;
    }
}

static void h005_set_limit(struct h005_source *source)
{
    source->state = H005_SOURCE_UNKNOWN;
    source->reason = H005_REASON_LIMIT_EXCEEDED;
    source->truncated = true;
}

bool h005_add_process_assertion(struct h005_snapshot *snapshot,
                                const struct h005_process_assertion *assertion)
{
    if (snapshot == NULL || assertion == NULL) {
        return false;
    }
    if (snapshot->process_assertion_count >= H005_MAX_PROCESS_ASSERTIONS) {
        h005_set_limit(&snapshot->process_api);
        return false;
    }
    snapshot->process_assertions[snapshot->process_assertion_count++] = *assertion;
    return true;
}

bool h005_add_aggregate_status(struct h005_snapshot *snapshot,
                               const struct h005_aggregate_status *status)
{
    if (snapshot == NULL || status == NULL) {
        return false;
    }
    if (snapshot->aggregate_type_count >= H005_MAX_AGGREGATE_TYPES) {
        h005_set_limit(&snapshot->aggregate_api);
        return false;
    }
    snapshot->aggregate_status[snapshot->aggregate_type_count++] = *status;
    return true;
}

bool h005_add_driver_assertion(struct h005_snapshot *snapshot,
                               const struct h005_driver_assertion *assertion)
{
    if (snapshot == NULL || assertion == NULL) {
        return false;
    }
    if (snapshot->driver_assertion_count >= H005_MAX_DRIVER_ASSERTIONS) {
        h005_set_limit(&snapshot->driver_registry);
        return false;
    }
    snapshot->driver_assertions[snapshot->driver_assertion_count++] = *assertion;
    return true;
}

const char *h005_classification_name(enum h005_classification classification)
{
    switch (classification) {
    case H005_NO_ASSERTIONS_OBSERVED:
        return "NO_ASSERTIONS_OBSERVED";
    case H005_ASSERTIONS_PRESENT:
        return "ASSERTIONS_PRESENT";
    case H005_UNAVAILABLE:
        return "UNAVAILABLE";
    case H005_UNKNOWN:
    default:
        return "UNKNOWN";
    }
}

const char *h005_source_state_name(enum h005_source_state state)
{
    switch (state) {
    case H005_SOURCE_COMPLETE:
        return "COMPLETE";
    case H005_SOURCE_UNAVAILABLE:
        return "UNAVAILABLE";
    case H005_SOURCE_UNKNOWN:
        return "UNKNOWN";
    case H005_SOURCE_NOT_RUN:
    default:
        return "NOT_RUN";
    }
}

const char *h005_source_reason_name(enum h005_source_reason reason)
{
    switch (reason) {
    case H005_REASON_SYMBOL_MISSING:
        return "SYMBOL_MISSING";
    case H005_REASON_PRIVILEGE_DENIED:
        return "PRIVILEGE_DENIED";
    case H005_REASON_API_ERROR:
        return "API_ERROR";
    case H005_REASON_MALFORMED_RESULT:
        return "MALFORMED_RESULT";
    case H005_REASON_SERVICE_UNAVAILABLE:
        return "SERVICE_UNAVAILABLE";
    case H005_REASON_PROPERTY_UNAVAILABLE:
        return "PROPERTY_UNAVAILABLE";
    case H005_REASON_LIMIT_EXCEEDED:
        return "LIMIT_EXCEEDED";
    case H005_REASON_NONE:
    default:
        return "NONE";
    }
}

static bool h005_source_is_complete(const struct h005_source *source)
{
    return source->state == H005_SOURCE_COMPLETE && !source->truncated;
}

static bool h005_has_observed_assertion(const struct h005_snapshot *snapshot)
{
    size_t index;

    if (snapshot->process_entries_seen > 0 || snapshot->process_assertion_count > 0 ||
        snapshot->driver_assertion_count > 0 ||
        (snapshot->driver_summary_known && snapshot->driver_summary_mask != 0)) {
        return true;
    }
    for (index = 0; index < snapshot->aggregate_type_count; index++) {
        const struct h005_aggregate_status *status = &snapshot->aggregate_status[index];
        if (status->level_known && status->level != 0) {
            return true;
        }
    }
    return false;
}

void h005_snapshot_classify(struct h005_snapshot *snapshot)
{
    bool complete;
    bool has_unknown;
    bool has_unavailable;

    if (snapshot == NULL) {
        return;
    }

    complete = h005_source_is_complete(&snapshot->process_api) &&
               h005_source_is_complete(&snapshot->aggregate_api) &&
               h005_source_is_complete(&snapshot->driver_registry);
    snapshot->enumeration_complete = complete;

    if (h005_has_observed_assertion(snapshot)) {
        snapshot->classification = H005_ASSERTIONS_PRESENT;
        h005_assess_sleep_prevention(snapshot);
        return;
    }
    if (complete) {
        snapshot->classification = H005_NO_ASSERTIONS_OBSERVED;
        h005_assess_sleep_prevention(snapshot);
        return;
    }

    has_unknown = snapshot->process_api.state == H005_SOURCE_UNKNOWN ||
                  snapshot->aggregate_api.state == H005_SOURCE_UNKNOWN ||
                  snapshot->driver_registry.state == H005_SOURCE_UNKNOWN ||
                  snapshot->process_api.state == H005_SOURCE_NOT_RUN ||
                  snapshot->aggregate_api.state == H005_SOURCE_NOT_RUN ||
                  snapshot->driver_registry.state == H005_SOURCE_NOT_RUN;
    has_unavailable = snapshot->process_api.state == H005_SOURCE_UNAVAILABLE ||
                      snapshot->aggregate_api.state == H005_SOURCE_UNAVAILABLE ||
                      snapshot->driver_registry.state == H005_SOURCE_UNAVAILABLE;

    if (has_unknown || !has_unavailable) {
        snapshot->classification = H005_UNKNOWN;
    } else {
        snapshot->classification = H005_UNAVAILABLE;
    }
    h005_assess_sleep_prevention(snapshot);
}

void h005_collect(const struct h005_provider *provider, struct h005_snapshot *snapshot)
{
    h005_snapshot_reset(snapshot);
    if (provider == NULL || snapshot == NULL) {
        return;
    }

    if (provider->query_process_assertions != NULL) {
        provider->query_process_assertions(snapshot);
    }
    if (provider->query_aggregate_status != NULL) {
        provider->query_aggregate_status(snapshot);
    }
    if (provider->query_driver_assertions != NULL) {
        provider->query_driver_assertions(snapshot);
    }
    h005_snapshot_classify(snapshot);
}

int h005_exit_code(enum h005_classification classification)
{
    switch (classification) {
    case H005_NO_ASSERTIONS_OBSERVED:
        return 0;
    case H005_ASSERTIONS_PRESENT:
        return 10;
    case H005_UNAVAILABLE:
        return 20;
    case H005_UNKNOWN:
    default:
        return 21;
    }
}

bool h005_write_json(const struct h005_snapshot *snapshot, char *buffer, size_t capacity,
                     size_t *written)
{
    struct h005_json_writer writer;
    size_t index;

    if (snapshot == NULL || buffer == NULL || capacity == 0) {
        return false;
    }
    writer.buffer = buffer;
    writer.capacity = capacity;
    writer.used = 0;
    writer.failed = false;

    h005_json_append(&writer, "{\"schema\":\"ioscaffeinate.h005.power-inspector.v2\","
                     "\"read_only\":true,\"assertion_mutation_attempted\":false,"
                     "\"execution_timeout_seconds\":%d,\"classification\":",
                     H005_EXECUTION_TIMEOUT_SECONDS);
    h005_json_string(&writer, h005_classification_name(snapshot->classification));
    h005_json_append(&writer, ",\"project_assertion_attribution\":"
                     "\"NOT_PERFORMED_NO_PROCESS_NAMES_QUERIED\","
                     "\"sleep_prevention_ownership\":");
    h005_json_string(&writer,
                     h005_sleep_prevention_assessment_name(
                         snapshot->sleep_prevention_assessment));
    h005_json_append(&writer, ",\"enumeration_complete\":%s,\"process_api\":",
                     snapshot->enumeration_complete ? "true" : "false");
    h005_json_source(&writer, &snapshot->process_api, true,
                     snapshot->process_assertion_count);
    h005_json_append(&writer, ",\"process_owners_seen\":%zu,\"process_assertions\":[",
                     snapshot->process_entries_seen);
    for (index = 0; index < snapshot->process_assertion_count; index++) {
        const struct h005_process_assertion *assertion = &snapshot->process_assertions[index];
        if (index != 0) {
            h005_json_append(&writer, ",");
        }
        h005_json_append(&writer, "{\"assertion_domain\":\"USERSPACE_PROCESS\","
                         "\"pid\":");
        if (assertion->pid_known) {
            h005_json_append(&writer, "%d", assertion->pid);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"assertion_type\":");
        h005_json_optional_text(&writer, assertion->type_known, assertion->type);
        h005_json_append(&writer, ",\"assertion_role\":");
        h005_json_string(&writer, h005_assertion_role_name(
            h005_assertion_role(assertion->type, assertion->type_known)));
        h005_json_append(&writer, ",\"owner_state\":\"%s\"",
                         assertion->pid_known ? "PID_ONLY" : "UNKNOWN");
        h005_json_append(&writer, ",\"type_redacted\":%s,\"level\":",
                         assertion->type_redacted ? "true" : "false");
        if (assertion->level_known) {
            h005_json_append(&writer, "%d", assertion->level);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"current_status\":");
        h005_json_string(&writer, h005_current_status(assertion->level_known,
                                                       assertion->level_recognized,
                                                       assertion->level));
        h005_json_append(&writer, "}");
    }

    h005_json_append(&writer, "],\"aggregate_api\":");
    h005_json_source(&writer, &snapshot->aggregate_api, true,
                     snapshot->aggregate_type_count);
    h005_json_append(&writer, ",\"aggregate_status\":[");
    for (index = 0; index < snapshot->aggregate_type_count; index++) {
        const struct h005_aggregate_status *status = &snapshot->aggregate_status[index];
        if (index != 0) {
            h005_json_append(&writer, ",");
        }
        h005_json_append(&writer, "{\"assertion_domain\":\"AGGREGATE_STATUS\","
                         "\"assertion_type\":");
        h005_json_optional_text(&writer, status->type_known, status->type);
        h005_json_append(&writer, ",\"assertion_role\":");
        h005_json_string(&writer, h005_assertion_role_name(
            h005_assertion_role(status->type, status->type_known)));
        h005_json_append(&writer, ",\"type_redacted\":%s,\"level\":",
                         status->type_redacted ? "true" : "false");
        if (status->level_known) {
            h005_json_append(&writer, "%d", status->level);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"current_status\":");
        h005_json_string(&writer, h005_current_status(status->level_known,
                                                       status->level_recognized,
                                                       status->level));
        h005_json_append(&writer, "}");
    }

    h005_json_append(&writer, "],\"driver_registry\":");
    h005_json_source(&writer, &snapshot->driver_registry, false,
                     snapshot->driver_assertion_count);
    h005_json_append(&writer, ",\"driver_summary_mask\":");
    if (snapshot->driver_summary_known) {
        h005_json_append(&writer, "\"0x%llx\"",
                         (unsigned long long)snapshot->driver_summary_mask);
    } else {
        h005_json_append(&writer, "null");
    }
    h005_json_append(&writer, ",\"driver_assertions\":[");
    for (index = 0; index < snapshot->driver_assertion_count; index++) {
        const struct h005_driver_assertion *assertion = &snapshot->driver_assertions[index];
        if (index != 0) {
            h005_json_append(&writer, ",");
        }
        h005_json_append(&writer, "{\"assertion_domain\":\"IOKIT_DRIVER\",\"id\":");
        if (assertion->id_known) {
            h005_json_append(&writer, "%llu", (unsigned long long)assertion->id);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"type_mask\":");
        if (assertion->mask_known) {
            h005_json_append(&writer, "\"0x%llx\"",
                             (unsigned long long)assertion->type_mask);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"driver_assertion_categories\":");
        h005_json_driver_categories(&writer, assertion->mask_known,
                                    assertion->type_mask);
        h005_json_append(&writer, ",\"owner\":");
        h005_json_optional_text(&writer, assertion->owner_known, assertion->owner);
        h005_json_append(&writer, ",\"owner_redacted\":%s,\"owner_state\":\"%s\",\"level\":",
                         assertion->owner_redacted ? "true" : "false",
                         assertion->owner_known && !assertion->owner_redacted ?
                         "KNOWN_DRIVER_SERVICE_LABEL" : "UNKNOWN");
        if (assertion->level_known) {
            h005_json_append(&writer, "%d", assertion->level);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"current_status\":");
        h005_json_string(&writer, h005_current_status(assertion->level_known,
                                                       assertion->level_recognized,
                                                       assertion->level));
        h005_json_append(&writer, "}");
    }

    h005_json_append(&writer, "],\"privacy\":{\"process_names_emitted\":false,"
                     "\"assertion_names_emitted\":false,\"details_emitted\":false,"
                     "\"registry_snapshot_emitted\":false}}\n");

    if (writer.failed) {
        return false;
    }
    if (written != NULL) {
        *written = writer.used;
    }
    return true;
}
