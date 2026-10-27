#ifndef IOSCAFFEINATE_H005_POWER_INSPECTOR_H
#define IOSCAFFEINATE_H005_POWER_INSPECTOR_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define H005_MAX_PROCESS_OWNERS 32
#define H005_MAX_PROCESS_ASSERTIONS 64
#define H005_MAX_AGGREGATE_TYPES 32
#define H005_MAX_DRIVER_ASSERTIONS 32
#define H005_TEXT_CAPACITY 64
#define H005_JSON_CAPACITY 16384

enum h005_source_state {
    H005_SOURCE_NOT_RUN = 0,
    H005_SOURCE_COMPLETE,
    H005_SOURCE_UNAVAILABLE,
    H005_SOURCE_UNKNOWN
};

enum h005_source_reason {
    H005_REASON_NONE = 0,
    H005_REASON_SYMBOL_MISSING,
    H005_REASON_PRIVILEGE_DENIED,
    H005_REASON_API_ERROR,
    H005_REASON_MALFORMED_RESULT,
    H005_REASON_SERVICE_UNAVAILABLE,
    H005_REASON_PROPERTY_UNAVAILABLE,
    H005_REASON_LIMIT_EXCEEDED
};

enum h005_classification {
    H005_NO_ASSERTIONS_OBSERVED = 0,
    H005_ASSERTIONS_PRESENT,
    H005_UNAVAILABLE,
    H005_UNKNOWN
};

struct h005_source {
    enum h005_source_state state;
    enum h005_source_reason reason;
    bool symbol_available;
    bool has_return_code;
    int32_t return_code;
    bool truncated;
};

struct h005_process_assertion {
    bool pid_known;
    int32_t pid;
    bool type_known;
    bool type_redacted;
    char type[H005_TEXT_CAPACITY];
    bool level_known;
    bool level_recognized;
    int32_t level;
};

struct h005_aggregate_status {
    bool type_known;
    bool type_redacted;
    char type[H005_TEXT_CAPACITY];
    bool level_known;
    bool level_recognized;
    int32_t level;
};

struct h005_driver_assertion {
    bool id_known;
    uint64_t id;
    bool mask_known;
    uint64_t type_mask;
    bool owner_known;
    bool owner_redacted;
    char owner[H005_TEXT_CAPACITY];
    bool level_known;
    bool level_recognized;
    int32_t level;
};

struct h005_snapshot {
    struct h005_source process_api;
    struct h005_source aggregate_api;
    struct h005_source driver_registry;

    size_t process_entries_seen;
    size_t process_assertion_count;
    struct h005_process_assertion process_assertions[H005_MAX_PROCESS_ASSERTIONS];

    size_t aggregate_type_count;
    struct h005_aggregate_status aggregate_status[H005_MAX_AGGREGATE_TYPES];

    bool driver_summary_known;
    uint64_t driver_summary_mask;
    size_t driver_assertion_count;
    struct h005_driver_assertion driver_assertions[H005_MAX_DRIVER_ASSERTIONS];

    bool enumeration_complete;
    enum h005_classification classification;
};

struct h005_provider {
    void (*query_process_assertions)(struct h005_snapshot *snapshot);
    void (*query_aggregate_status)(struct h005_snapshot *snapshot);
    void (*query_driver_assertions)(struct h005_snapshot *snapshot);
};

void h005_snapshot_reset(struct h005_snapshot *snapshot);
void h005_snapshot_classify(struct h005_snapshot *snapshot);
void h005_collect(const struct h005_provider *provider, struct h005_snapshot *snapshot);

bool h005_add_process_assertion(struct h005_snapshot *snapshot,
                                const struct h005_process_assertion *assertion);
bool h005_add_aggregate_status(struct h005_snapshot *snapshot,
                               const struct h005_aggregate_status *status);
bool h005_add_driver_assertion(struct h005_snapshot *snapshot,
                               const struct h005_driver_assertion *assertion);

const char *h005_classification_name(enum h005_classification classification);
const char *h005_source_state_name(enum h005_source_state state);
const char *h005_source_reason_name(enum h005_source_reason reason);
int h005_exit_code(enum h005_classification classification);

/* Writes one bounded JSON object. Returns false if it cannot fit in capacity. */
bool h005_write_json(const struct h005_snapshot *snapshot, char *buffer, size_t capacity,
                     size_t *written);

#endif
