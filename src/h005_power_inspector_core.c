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
        return;
    }
    if (complete) {
        snapshot->classification = H005_NO_ASSERTIONS_OBSERVED;
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

    h005_json_append(&writer, "{\"schema\":\"ioscaffeinate.h005.power-inspector.v1\","
                     "\"read_only\":true,\"assertion_mutation_attempted\":false,"
                     "\"classification\":");
    h005_json_string(&writer, h005_classification_name(snapshot->classification));
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
        h005_json_append(&writer, "{\"pid\":");
        if (assertion->pid_known) {
            h005_json_append(&writer, "%d", assertion->pid);
        } else {
            h005_json_append(&writer, "null");
        }
        h005_json_append(&writer, ",\"assertion_type\":");
        h005_json_optional_text(&writer, assertion->type_known, assertion->type);
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
        h005_json_append(&writer, "{\"assertion_type\":");
        h005_json_optional_text(&writer, status->type_known, status->type);
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
        h005_json_append(&writer, "{\"id\":");
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
        h005_json_append(&writer, ",\"owner\":");
        h005_json_optional_text(&writer, assertion->owner_known, assertion->owner);
        h005_json_append(&writer, ",\"owner_redacted\":%s,\"level\":",
                         assertion->owner_redacted ? "true" : "false");
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
