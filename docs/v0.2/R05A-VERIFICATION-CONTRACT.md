# R05A Signature Verification Contract

The candidate workflow retains separate results and only finalizes after all required host checks pass:

| Result | Required evidence | Meaning |
|---|---|---|
| `APPLE_CODESIGN_VERIFIED` | `/usr/bin/codesign --verify --strict --verbose=4` exits 0 for both exact package binaries | Apple host verifier accepted these files in this macOS environment |
| `INDEPENDENT_CODEDIRECTORY_VERIFIED` | Bounded parser validates architecture, load commands, signature layout, CodeDirectory fields, every executable-page hash, and requirements/entitlement special-slot hashes | Independently computed integrity checks passed |
| `ENTITLEMENTS_EXACT_MATCH` | XML and DER entitlement blobs are linked by verified special-slot hashes and contain only the approved `no-container=true` entitlement | The embedded entitlement set matches the approved profile |
| `DEVICE_SIGNATURE_ACCEPTANCE_PENDING` | Always pending in cloud-only workflows | No claim about iOS installation, AMFI behavior, runtime, or device trust |

The production signing identity remains ProcursusTeam `ldid` 2.1.5-procursus7 at SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`. The profile remains `amethyst-ios12-rootful`, SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`, with exactly `com.apple.private.security.no-container=true`.

The signed-input manifest and receipt bind source commit, package filename and digest, both binary digests, signer, profile, and exact workflow run ID and attempt. The finalizer accepts only a `VERIFIED` schema-v2 macOS receipt from that same workflow run and attempt, with exit 0 for both Apple commands and all independent signature checks. It validates the package with the pinned signer again, confirms binaries did not change during metadata-only repackaging, and verifies the final package from a fresh extraction. Any missing, failed, mismatched, or copied receipt blocks finalization.

The `codesign --version` probe is stored as environment output because Apple tool releases may reject that query. It does not determine the result: the two exact package binaries must pass `codesign --verify --strict --verbose=4` and the independent CodeDirectory/entitlement audit.

`INDEPENDENT_CODEDIRECTORY_VERIFIED` never substitutes for `APPLE_CODESIGN_VERIFIED`. The diagnostic Apple-native ad hoc output is isolated under a diagnostic-only directory and cannot be submitted to the finalizer. A successful host result leaves device acceptance pending and does not authorize transfer, installation, runtime mutation, tag creation, stable publication, or physical qualification.
