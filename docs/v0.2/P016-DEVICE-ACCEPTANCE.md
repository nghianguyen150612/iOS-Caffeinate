# P016 — Supervised Device Acceptance

**Status: PENDING.** Cloud work did not connect to the iPad. The iOS ARM64 build and API calls remain runtime-unverified until a physically attended investigation records their actual behavior.

## Preconditions

- P011 package acceptance and signing prerequisites are satisfied.
- Use a reviewed build for the exact source SHA and a known rollback package.
- Operator is physically present with an independent recovery route.
- Confirm current daemon, assertion, and P014 cleanup state before sampling.
- Do not proceed with unresolved release or recovery state.

## Read-only sequence

1. Record model, iOS, bootstrap, package/build identity, and current daemon/assertion state.
2. Run `ic health sources` and record that unsupported APIs stay unavailable.
3. Run `ic health status`, `ic health battery`, `ic health thermal`, and `ic health doctor`. For a separately preregistered P012 measurement outside its quiet interval, `health status` may include `--trial-id <id> --condition-id <A|B|C|D> --outside-quiet-interval`; this only labels output and does not update the trial record.
4. Compare a battery value with the visible system status only if a future verified read-only source provides one. Current expected battery and charging results are `UNAVAILABLE`.
5. Record thermal availability. Current expected thermal result is `UNKNOWN` / `UNAVAILABLE`.
6. Run `ic server policy explain` and verify resource gates remain pending and execution authorization remains `no`.
7. Confirm health reads did not acquire/release an assertion, restart the daemon, activate launchd, or create background work.
8. Associate observations with P009 event proposals and independent clock metadata without changing the P009 v1 schema.

Do not change charging state, stress the device, deliberately overheat it, or run sampling during P012 quiet intervals. Thermal-critical handling remains mock-tested; longer supervised characterization belongs to P019. Mark every API that has only compiled as `RUNTIME_UNVERIFIED`.
