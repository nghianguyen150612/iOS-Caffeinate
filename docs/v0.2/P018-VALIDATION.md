# P018 Validation

P018 validation is pinned to the exact checked-out source SHA and never connects to the iPad. CI builds the explicit Linux mock backend, runs CLI/error/exit regressions, existing P009–P017 tests, package manager/preflight tests, offline export validation/security tests, portable shell syntax checks, package-script invariants, and existing cross-build/package/signing gates.

The P018 workflow uploads the exact source SHA, test reports, and a deterministic export-validator fixture. Fixture records are labelled `MOCK`/`SIMULATED`; the manifest says `hardware_evidence_accepted=NOT_ESTABLISHED`. No CI fixture is device evidence.

Native checks:

- C11 compilation uses `-Wall -Wextra -Werror` and the explicit mock gate only on Linux.
- Python tooling uses the standard library and runs offline.
- Shell examples are parsed with POSIX `/bin/sh` and interactive zsh syntax modes; package scripts are syntax-checked and scanned for mutation commands.
- Package tests inspect/build temporary `.deb` fixtures but never install, remove, or roll back a package.
- Exact-source Actions checkout uses the PR head SHA; reports print and archive that SHA.

Cloud validation cannot establish iOS installation/signature acceptance, launchd mutation compatibility, P014 runtime cleanup, assertion behavior, battery/thermal sources, SSH/Tailscale reachability, scheduled wake, or endurance. Those gates remain for attended device review and P019.
