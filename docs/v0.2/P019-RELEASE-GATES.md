# P019 and P020 Release Gates

## P019 hardware acceptance

The P019 result can be `ACCEPTED_FOR_TESTED_SCOPE` only when all registered evidence is complete and reviewed:

- P011 stable package acceptance and exact P010 signer provenance.
- Exact signed development candidate identity and installed-path hashes for P018/P019 behavior.
- Attended clean foreground lifecycle, known assertion ownership, and P014 journal/recovery evidence.
- All 24 valid P012 trials in registered order, with separate LAN/Tailscale denominators and no unresolved comparison confounders.
- All 12 manual bounded cycles across 3 dates with 12 confirmed acquisitions, 12 confirmed releases, no release failure, no unexpected daemon exit/restart, safe cleanup, and resource review.
- Valid original P009 v1 packages, source provenance, human review, and an independently reviewed P018 derivative/privacy result.
- No unresolved safety incident. Every accepted behavior, route, build, and tested condition is named.

No single missing gate is waived because other trials passed. If only part of the scope is complete, retain that information as pending or inconclusive; do not call overall P019 hardware accepted.

## Explicitly outside P019 scope

P019 does not establish 24/7 uptime, automatic restart, reboot persistence, crash recovery, launchd activation, unattended schedule execution, causal sleep prevention, calibrated battery health, or a safe unattended thermal envelope. P013 launchd compatibility remains unverified and P014 has no production automatic restart executor.

## P020 readiness

Cloud evidence can assess schema validity, deterministic offline analysis, protocol compliance, build/package CI, P009/P012/P018 compatibility, safety static checks, and exact-source workflow execution. Release assessment remains blocked on physical P011 acceptance, target candidate identity, P012 controlled observations, P014 cleanup/recovery, resource availability, P018 privacy review, P019 independent review, and every other release-critical gate. P019 CI success cannot set P020 hardware gates to PASS.
