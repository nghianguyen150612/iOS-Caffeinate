# P015 — Supervised Device Acceptance

Cloud engineering does not access the iPad and does not establish physical acceptance. Prepare direct recovery independent of SSH/Tailscale and operator presence before any device inspection.

Prerequisites are P011 installed-package and signing/provenance acceptance, P012 safety and idle-comparison review, P014 recovery-state review, a known daemon/assertion state, battery and thermal observations, and a safe recovery route. P013 launchd mutation remains unverified and disabled.

Initial P015 checks are read-only:

1. Run `ic server policy show`, `validate`, `explain`, and `plan` against the existing configuration.
2. Confirm valid v1 `disabled` and `observe_only` files retain their behavior.
3. Run `ic server policy migrate --dry-run` and compare the persistent v1 file before and after.
4. Validate an explicit v2 config without applying it.
5. Confirm missing or unknown hardware evidence defers or blocks eligibility.
6. Confirm an unsafe, missing, or unresolved P014 journal blocks the policy.
7. Confirm the CLI reports no policy execution, no launchd activation, and no hidden assertion creation.
8. Confirm P004 schedules, P014 recovery state, and package files are unchanged.

Do not run persistent or unattended Server Mode in P015. A later physical trial requires a separate approval and a single manually authorized bounded duration no greater than 300 seconds. A policy eligibility result alone does not authorize that trial.
