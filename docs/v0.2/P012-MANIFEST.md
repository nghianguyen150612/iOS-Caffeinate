# P012 — Cloud engineering manifest

This manifest records the P012 integration identity and scope. The manifest is not a signature, run log, source attestation, P009 hardware session, or empirical provenance proof. CI artifacts record run-specific test counts and the exact checked-out source SHA.

| Field | Value |
|---|---|
| Repository | `nghianguyen150612/iOS-Caffeinate` |
| Milestone | P012 — Controlled Idle & Power Behavior Research |
| Branch | `ios/p012-controlled-idle-power-research` |
| Effective integration base branch | `ios/p011-signed-package-acceptance` |
| Effective base SHA | `1fed3d15f44099d4f862ac1ff422da287b78b0b3` |
| P012 merge-base | `1fed3d15f44099d4f862ac1ff422da287b78b0b3` |
| P011 PR | [#10](https://github.com/nghianguyen150612/iOS-Caffeinate/pull/10), open at preflight |
| P011 exact-head CI | [run 39359731276](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39359731276), success on `1fed3d15f44099d4f862ac1ff422da287b78b0b3` |
| P012 protocol | `experiments/p012/protocol-v1.json` |
| Protocol status | `PREREGISTERED_PROPOSAL`; no P012 hardware data collected |
| Hardware experiment status | `PENDING`; P011 physical package acceptance and separate authorization required |
| Release status | No v0.2.0 release created or authorized |

P011 remains open and is not merged automatically. The P012 branch is stacked on its exact head. If P011 merges, the P012 branch/PR must be rebased or retargeted onto integrated `main` while preserving logical P012 commits.

## P011 package limitation

P011's cloud CI run is successful, but physical stable-package acceptance is still pending. The P011 record reports that embedded-entitlement reinspection was blocked because the exact pinned `ldid` binary hash (`15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`) was unavailable in the validation environment; an upstream same-version binary with a different hash was correctly rejected. P012 does not substitute a signer or bypass that provenance check.

## Provenance limits

Generated P012 manifests and CI reports prove only file consistency and the exact source checked by that workflow. Synthetic fixtures are `SIMULATED`. Operator confirmations remain operator-reported. A P012 analysis report cannot replace P009 human review or establish that an assertion prevented OS suspend.
