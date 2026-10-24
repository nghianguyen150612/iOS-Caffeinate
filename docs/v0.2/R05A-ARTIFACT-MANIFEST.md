# R05A Artifact and Provenance Manifest

## Preserved R05 input evidence

| Artifact | Identity |
|---|---|
| Failed candidate source | `b2fdea8764ba08a8f60fe4d5acae2705dce7bd37` |
| Failed workflow | [Run 39978072203](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39978072203) |
| Authentic failed receipt artifact | `iOS-Caffeinate-P020-v0.2.0-rc1-macOS-signature-integrity`; receipt SHA-256 `83b32e137ad903065a4d77c1968a7b9c7a0517f66506131e49bcdd3d2908ed0c` |
| Failed signed-input package | SHA-256 `18631b8aff5c25607a88ba4fc28c945d1b8a552903950ec73dbae386d695807e`; diagnostic input only |
| Unsigned exact-source control | [Run 39978081363](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39978081363), artifact `iOS-Caffeinate-P020-v0.2.0-rc1-UNSIGNED-DEVICE-UNVERIFIED` |
| Historical stable package | v0.1.0 package SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` |

## Preserved signing identity

- Signer: ProcursusTeam `ldid` 2.1.5-procursus7, SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`.
- Profile: `amethyst-ios12-rootful`, SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`.
- Entitlements: exactly `com.apple.private.security.no-container=true`.
- Corrected signing mode: pinned `ldid -Cadhoc -S<approved-profile>`.

## R05A outputs

The GitHub-hosted diagnostic-only receipt, exact-head CI run, corrected candidate run, signed-input and finalized package digests, finalization receipt digest, and complete `SHA256SUMS` will be added here after exact-source workflows finish. The Apple-native ad hoc comparison remains diagnostic-only. No final candidate digest is claimed by this document yet.
