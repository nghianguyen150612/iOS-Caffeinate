#include "../src/h005_power_inspector.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void complete_source(struct h005_source *source)
{
    source->state = H005_SOURCE_COMPLETE;
    source->reason = H005_REASON_NONE;
    source->has_return_code = true;
    source->return_code = 0;
}

static void mock_empty_process(struct h005_snapshot *snapshot)
{
    snapshot->process_api.symbol_available = true;
    complete_source(&snapshot->process_api);
}

static void mock_empty_aggregate(struct h005_snapshot *snapshot)
{
    snapshot->aggregate_api.symbol_available = true;
    complete_source(&snapshot->aggregate_api);
}

static void mock_empty_driver(struct h005_snapshot *snapshot)
{
    snapshot->driver_summary_known = true;
    snapshot->driver_summary_mask = 0;
    complete_source(&snapshot->driver_registry);
}

static void mock_process_symbol_missing(struct h005_snapshot *snapshot)
{
    snapshot->process_api.state = H005_SOURCE_UNAVAILABLE;
    snapshot->process_api.reason = H005_REASON_SYMBOL_MISSING;
    snapshot->process_api.symbol_available = false;
}

static void mock_process_privilege_denied(struct h005_snapshot *snapshot)
{
    snapshot->process_api.state = H005_SOURCE_UNAVAILABLE;
    snapshot->process_api.reason = H005_REASON_PRIVILEGE_DENIED;
    snapshot->process_api.symbol_available = true;
    snapshot->process_api.has_return_code = true;
    snapshot->process_api.return_code = -100;
}

static void mock_process_api_error(struct h005_snapshot *snapshot)
{
    snapshot->process_api.state = H005_SOURCE_UNKNOWN;
    snapshot->process_api.reason = H005_REASON_API_ERROR;
    snapshot->process_api.symbol_available = true;
    snapshot->process_api.has_return_code = true;
    snapshot->process_api.return_code = -1;
}

static void mock_aggregate_api_error(struct h005_snapshot *snapshot)
{
    snapshot->aggregate_api.state = H005_SOURCE_UNKNOWN;
    snapshot->aggregate_api.reason = H005_REASON_API_ERROR;
    snapshot->aggregate_api.symbol_available = true;
    snapshot->aggregate_api.has_return_code = true;
    snapshot->aggregate_api.return_code = -1;
}

static void mock_process_malformed(struct h005_snapshot *snapshot)
{
    struct h005_process_assertion record;
    memset(&record, 0, sizeof(record));
    snapshot->process_entries_seen = 1;
    snapshot->process_api.state = H005_SOURCE_UNKNOWN;
    snapshot->process_api.reason = H005_REASON_MALFORMED_RESULT;
    snapshot->process_api.symbol_available = true;
    (void)h005_add_process_assertion(snapshot, &record);
}

static void mock_user_assertion(struct h005_snapshot *snapshot)
{
    struct h005_process_assertion record;
    mock_empty_process(snapshot);
    snapshot->process_entries_seen = 1;
    memset(&record, 0, sizeof(record));
    record.pid_known = true;
    record.pid = 42;
    record.type_known = true;
    (void)snprintf(record.type, sizeof(record.type), "PreventSystemSleep");
    record.level_known = true;
    record.level_recognized = true;
    record.level = 255;
    (void)h005_add_process_assertion(snapshot, &record);
}

static void mock_driver_assertion(struct h005_snapshot *snapshot)
{
    struct h005_driver_assertion record;
    mock_empty_driver(snapshot);
    snapshot->driver_summary_mask = 0x100;
    memset(&record, 0, sizeof(record));
    record.id_known = true;
    record.id = 500;
    record.mask_known = true;
    record.type_mask = 0x100;
    record.owner_known = true;
    (void)snprintf(record.owner, sizeof(record.owner), "en0");
    record.level_known = true;
    record.level_recognized = true;
    record.level = 255;
    (void)h005_add_driver_assertion(snapshot, &record);
}

static void mock_aggregate_nonstandard_level(struct h005_snapshot *snapshot)
{
    struct h005_aggregate_status record;
    mock_empty_aggregate(snapshot);
    memset(&record, 0, sizeof(record));
    record.type_known = true;
    (void)snprintf(record.type, sizeof(record.type), "PreventUserIdleSystemSleep");
    record.level_known = true;
    record.level_recognized = false;
    record.level = 1;
    snapshot->aggregate_api.state = H005_SOURCE_UNKNOWN;
    snapshot->aggregate_api.reason = H005_REASON_MALFORMED_RESULT;
    (void)h005_add_aggregate_status(snapshot, &record);
}

static void expect_classification(const struct h005_provider *provider,
                                  enum h005_classification expected,
                                  bool expected_complete)
{
    struct h005_snapshot snapshot;
    h005_collect(provider, &snapshot);
    if (snapshot.classification != expected ||
        snapshot.enumeration_complete != expected_complete) {
        fprintf(stderr, "mock case mismatch: class %s complete=%d; expected %s complete=%d\n",
                h005_classification_name(snapshot.classification),
                snapshot.enumeration_complete ? 1 : 0,
                h005_classification_name(expected), expected_complete ? 1 : 0);
    }
    assert(snapshot.classification == expected);
    assert(snapshot.enumeration_complete == expected_complete);
}

static void test_complete_empty_is_the_only_clear_result(void)
{
    const struct h005_provider provider = {
        mock_empty_process, mock_empty_aggregate, mock_empty_driver
    };
    expect_classification(&provider, H005_NO_ASSERTIONS_OBSERVED, true);
}

static void test_missing_symbol_is_unavailable(void)
{
    const struct h005_provider provider = {
        mock_process_symbol_missing, mock_empty_aggregate, mock_empty_driver
    };
    expect_classification(&provider, H005_UNAVAILABLE, false);
}

static void test_privilege_denial_is_unavailable(void)
{
    const struct h005_provider provider = {
        mock_process_privilege_denied, mock_empty_aggregate, mock_empty_driver
    };
    expect_classification(&provider, H005_UNAVAILABLE, false);
}

static void test_query_error_and_malformed_result_are_unknown(void)
{
    const struct h005_provider api_error = {
        mock_process_api_error, mock_empty_aggregate, mock_empty_driver
    };
    const struct h005_provider malformed = {
        mock_process_malformed, mock_empty_aggregate, mock_empty_driver
    };
    expect_classification(&api_error, H005_UNKNOWN, false);
    expect_classification(&malformed, H005_ASSERTIONS_PRESENT, false);
}

static void test_any_user_or_driver_record_is_positive_evidence(void)
{
    const struct h005_provider user_assertion = {
        mock_user_assertion, mock_empty_aggregate, mock_empty_driver
    };
    const struct h005_provider driver_assertion = {
        mock_empty_process, mock_empty_aggregate, mock_driver_assertion
    };
    expect_classification(&user_assertion, H005_ASSERTIONS_PRESENT, true);
    expect_classification(&driver_assertion, H005_ASSERTIONS_PRESENT, true);
}

static void test_nonzero_aggregate_is_positive_even_when_level_is_ambiguous(void)
{
    const struct h005_provider provider = {
        mock_empty_process, mock_aggregate_nonstandard_level, mock_empty_driver
    };
    expect_classification(&provider, H005_ASSERTIONS_PRESENT, false);
}

static void test_mixed_unavailable_and_unknown_is_unknown(void)
{
    const struct h005_provider provider = {
        mock_process_symbol_missing, mock_aggregate_api_error, mock_empty_driver
    };
    expect_classification(&provider, H005_UNKNOWN, false);
}

static void test_output_is_bounded_and_json_escaped(void)
{
    const struct h005_provider provider = {
        mock_user_assertion, mock_empty_aggregate, mock_empty_driver
    };
    struct h005_snapshot snapshot;
    char output[H005_JSON_CAPACITY];
    size_t written = 0;
    char tiny[8];

    h005_collect(&provider, &snapshot);
    assert(h005_write_json(&snapshot, output, sizeof(output), &written));
    assert(written > 0 && written < sizeof(output));
    assert(strstr(output, "\"pid\":42") != NULL);
    assert(strstr(output, "\"assertion_type\":\"PreventSystemSleep\"") != NULL);
    assert(strstr(output, "\"process_names_emitted\":false") != NULL);
    assert(!h005_write_json(&snapshot, tiny, sizeof(tiny), NULL));

    snapshot.driver_assertion_count = 1;
    snapshot.driver_assertions[0].owner_known = true;
    (void)snprintf(snapshot.driver_assertions[0].owner,
                   sizeof(snapshot.driver_assertions[0].owner), "en0\"\\line\n");
    assert(h005_write_json(&snapshot, output, sizeof(output), &written));
    assert(strstr(output, "en0\\\"\\\\line\\n") != NULL);
}

static void test_exit_codes_do_not_turn_presence_into_clearance(void)
{
    assert(h005_exit_code(H005_NO_ASSERTIONS_OBSERVED) == 0);
    assert(h005_exit_code(H005_ASSERTIONS_PRESENT) == 10);
    assert(h005_exit_code(H005_UNAVAILABLE) == 20);
    assert(h005_exit_code(H005_UNKNOWN) == 21);
}

int main(void)
{
    test_complete_empty_is_the_only_clear_result();
    test_missing_symbol_is_unavailable();
    test_privilege_denial_is_unavailable();
    test_query_error_and_malformed_result_are_unknown();
    test_any_user_or_driver_record_is_positive_evidence();
    test_nonzero_aggregate_is_positive_even_when_level_is_ambiguous();
    test_mixed_unavailable_and_unknown_is_unknown();
    test_output_is_bounded_and_json_escaped();
    test_exit_codes_do_not_turn_presence_into_clearance();
    puts("H005_POWER_INSPECTOR_MOCK_TESTS_PASS");
    return 0;
}
