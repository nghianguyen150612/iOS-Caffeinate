# P016 — P015 Policy Integration

P015 remains the policy authority. `src/health_policy.c` is a one-way adapter from a validated P016 snapshot to P015's existing diagnostic fields. The policy evaluator never reads sensors directly.

The adapter may show a valid measurement and its source, age, freshness, and confidence. It does not create `SERVER_EVIDENCE_PASS`, mark an observation reviewed, claim physical-source verification, or set P009 acceptance. Missing battery or thermal data remains missing. A stale reading may remain visible as raw diagnostic data with `STALE` metadata, but it is never current safety evidence.

P015 has no `FULL` charging state; P016 preserves `FULL` in its own model and maps it to P015's `UNKNOWN` charging value. A source-reported thermal `CRITICAL` value can only add `UNSAFE` when the sample is current and physical device provenance has been verified. It cannot pass the thermal gate. Unknown thermal data does not become nominal.

P014 cleanup, release-failure and recovery blockers are unchanged. Policy eligibility is not execution authorization. `execution_authorized` remains `no`; P016 does not enable an executor, automatic recovery, unattended operation, launchd, or an assertion.
