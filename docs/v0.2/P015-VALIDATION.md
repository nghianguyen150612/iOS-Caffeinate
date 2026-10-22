# P015 — Cloud Validation

Run from the P015 branch:

```sh
./scripts/build-linux-test.sh
cc -std=c11 -Wall -Wextra -Werror -O2 \
  tests/p015_policy_unit.c src/server_mode.c src/server_policy.c src/recovery.c \
  -o build/p015/policy-unit
build/p015/policy-unit
python3 -m unittest discover -s tests -p 'test_p015_policy_cli.py' -v
python3 tests/integration.py
```

The P015 C harness covers v1/v2 modes, unsupported schemas, duplicate and unknown fields, malformed and truncated input, trailing bytes, exact boolean types, integer overflow, duration bounds, file-size bounds, symlink/hardlink/mode/ownership and concurrent-change checks, policy eligibility and denials, P014 cleanup and ownership blocks, P013 evidence requirements, simulated-only and low-confidence evidence, stale observations, resource unknowns, unattended requests, active assertion conflicts, deterministic reason order, and no execution authorization. CLI tests verify read-only show/validate/explain behavior, dry-run migration, unsupported-version rejection, and that no apply command exists.

The CI job reruns P009–P014 and rootful package regressions, verifies P013 lifecycle gates remain fail-closed, checks the exact source SHA, and uploads `P015-VALIDATION.json` plus deterministic logs. The report labels all policy fixtures `SIMULATED_AND_MOCK_ONLY`. Existing P008 attestation skip guards remain unchanged.

There is no configuration writer in P015, so atomic replacement, concurrent writer detection, migration interruption, and writer rollback are not claimed or tested. Mocks cannot establish iOS power behavior. CI does not install the package, register launchd, contact SSH/Tailscale, acquire an IOKit assertion, or validate physical cleanup.

The generated validation report records the exact checked-out source SHA, P014 base SHA, merge-base, branch, test results, and inactive runtime controls. Cloud completion is reported as `P015_CLOUD_COMPLETE_DEVICE_POLICY_PENDING` while hardware gates remain open.
