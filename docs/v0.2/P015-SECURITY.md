# P015 — Security and Failure Boundaries

The v1/v2 configuration loader is read-only. It reuses P006 safe traversal, ownership, mode `0600`, single-link, regular-file, bounded-size, and stable-read checks. Parsing rejects duplicate and unknown fields, trailing data, overflow, non-exact types, and unsupported versions. Invalid or unsafe content maps to a disabled policy and cannot enable a session.

The evaluator is pure C11. It has no filesystem writes, launchctl calls, process spawning, network sockets, IOKit calls, assertion calls, or daemon control. The CLI policy commands read the config, read the P014 journal, and may query the existing daemon status socket. The socket query is read-only. Policy commands never expose arbitrary configuration contents or secrets.

No config writer ships. `apply` is not a supported command, so atomic-write interruption, overwrite races, backup restoration, and writer fault injection are not claimed as implemented. These are explicit prerequisites for a future writer. The dry-run migration preserves the source file byte-for-byte.

P009 source classifications remain unchanged. Policy fixtures and CI inputs are `SIMULATED`, `MOCK`, or `CI`; those sources cannot pass hardware gates. Current, reviewed physical observations from `DEVICE_REPORTED` or `EXTERNAL_OBSERVER` can satisfy the evaluator. An `OPERATOR_RECORDED` observation remains labeled as such and requires separate P009 review before it can satisfy a gate. P015 does not import arbitrary JSON as hardware certification.

The policy result never grants execution authorization. It never activates a launchd service, obtains an assertion, wakes the device, changes networking, or creates a schedule. Existing P013 lifecycle and P014 recovery protections remain active.
