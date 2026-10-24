# R05A Mach-O Signature Audit

## Authentic R05 failure input

The failure receipt is bound to source `b2fdea8764ba08a8f60fe4d5acae2705dce7bd37` and package SHA-256 `18631b8aff5c25607a88ba4fc28c945d1b8a552903950ec73dbae386d695807e`. Both Apple verification commands failed with exit 1 and `code object is not signed at all`; finalization was skipped.

| Binary | Failed H003 `ldid` SHA-256 | CodeDirectory | CodeDirectory flags | Page hashes | Special slots |
|---|---|---|---:|---|---|
| `ios-caffeinate` | `9bc552fa23917adb337a8602879c098d3c53f081863bf6e72bb6d96001c55b54` | v2.4, SHA-256/32, codeLimit 213216, 4096-byte pages, 53 slots | `0x0` | All verified | requirements (2), XML entitlements (5), DER entitlements (7) verified |
| `ios-caffeinated` | `00dc373b305de6e8293271289c593cd498c67ff49f9eff48a1b91e9200e4b06b` | v2.4, SHA-256/32, codeLimit 142656, 4096-byte pages, 35 slots | `0x0` | All verified | requirements (2), XML entitlements (5), DER entitlements (7) verified |

Both inputs are thin little-endian ARM64 `MH_EXECUTE` Mach-O files targeting iOS 12.0. Each has one final `LC_CODE_SIGNATURE` within `__LINKEDIT`. The SuperBlobs contain exactly slots 0, 2, 5, and 7. The daemon signature area contains 15 zero padding bytes after the SuperBlob; the CLI has none. No CMS blob is present. Both XML entitlement dictionaries contain exactly `com.apple.private.security.no-container=true`; DER encodings and CodeDirectory special-slot hashes agree.

This establishes internal integrity for the observed CodeDirectory format. It does not establish an Apple host pass, certificate trust, AMFI acceptance, or device execution. The R05 defect included a missing `CS_ADHOC` CodeDirectory flag (`0x0002`).

## First correction and second Apple rejection

The pinned H003 `ldid` binary, SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`, was run by the exact-source workflow with `-Cadhoc -S` and the existing approved profile. Candidate run [40064205079](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/40064205079) produced flags `0x2`, but Apple returned exit 3 for both executables: `valid on disk` followed by `does not satisfy its designated Requirement`. Finalization was skipped. The authentic receipt (artifact ID `12549330339`) is SHA-256 `f17459b43c55af8fe0475930121c5de5cdc2e5eee71fc04b7eb13e2e9e8cb4a0`; its package SHA-256 is `f920e8455773d0a5994856b88ac1f65c69f094c89fbcad2fcb08941738a90d7a`. This package is failed-gate evidence only.

Independent parsing of the failed corrected-flag binaries reported:

| Binary | Diagnostic copy SHA-256 | Flags | Independent code hashes | Entitlements | Device acceptance |
|---|---|---:|---|---|---|
| `ios-caffeinate` | `cd110e0e1414f76cf2fa826d64bc77c39917e6908a1971d3797a983a13d64791` | `0x2` | 53/53 code slots; special slots 2/5/7 verified | Exact match | Pending |
| `ios-caffeinated` | `bfe0eab6048ff7529eb1d53f28fba1f13c62cbb0dbf6f1dbbc0b8177449357eb` | `0x2` | Verified | Exact match | Pending |

Both failed candidate binaries use CodeDirectory v2.4, SHA-256/32, 4096-byte pages, exact entitlement blobs, and the expected ARM64 iOS 12.0 Mach-O context. Their Requirements SuperBlobs each have one index (type 3), length 132. The corresponding requirement hashes are `988826a4d1629fbe2c8ba5b499b532a9e9d00c7b292c52ac0dc3e9a4bc96057a` and `831a2c150da128499b8bcf1373b992908fb057d44e825303cbd82818c81eaa4b`. The pinned `ldid` source shows this default requirement tests an Apple anchor and certificate fields; the candidate's ad hoc signature has no certificate.

## Empty-requirements correction, local structural check

The supported `ldid -Q` input is now an explicit 12-byte empty Requirements SuperBlob, SHA-256 `987920904eab650e75788c054aa0b0524e6a80bfc71aa32df8d237a61743f986`. The exact pinned H003 executable was run against copies of the exact-source unsigned binaries with `-Cadhoc -Q<blob> -S<approved-profile>`:

| Binary | Local corrected-copy SHA-256 | Flags | Requirements | Independent hashes | Entitlements |
|---|---|---:|---|---|---|
| `ios-caffeinate` | `09ad90576ff2ba8d40d498b80008ad5bf8206488406cec7d64899127965009f1` | `0x2` | Count 0 | All code slots and special slots 2/5/7 verified | Exact match |
| `ios-caffeinated` | `a4f8b2bc24199363db5813c79752b74cb631a9dd1842bdf64e45d48823f1cc25` | `0x2` | Count 0 | All code slots and special slots 2/5/7 verified | Exact match |

These local copies are structural evidence only. The corrected exact-source workflow must still independently verify the built package with Apple `codesign`, bind its receipt to both binary hashes and package digest, and complete finalization before an RC can be called finalized.

## Authentic macOS comparison

The diagnostic-only comparison [run 40064018459](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/40064018459) used the exact unsigned and failed R05 inputs, the byte-pinned v0.1.0 package, and separate Apple-native ad hoc copies. The machine receipt is artifact `iOS-Caffeinate-R05A-DIAGNOSTIC-ONLY-NO-RC-APPROVAL` (artifact ID `12548299016`); its SHA-256 is `31327d9b999dcdfe7d038bb720fdb3b7e63d5a5c9adc4aebc7cde12226f817a3`.

| Case | Apple strict verification | Independent result | Finding |
|---|---:|---|---|
| Exact-source unsigned | Exit 1 for both | No signature or entitlements | Expected unsigned control |
| Failed R05 H003 `ldid` package | Exit 1 for both | CodeDirectory, all page hashes, and exact entitlements verified; flags `0x0` | Apple reports “code object is not signed at all” |
| Apple-native diagnostic ad hoc copies | Exit 0 for both | CodeDirectory and exact entitlements verified; flags `0x2` | Both report “valid on disk”; diagnostic only |
| Stable v0.1.0 historical package | Exit 1 for both | CodeDirectory and exact entitlements verified; flags `0x0` | Same missing ad hoc flag as R05 |

The host reported macOS `26.6.2` and Xcode `26.6` (`17F113`). Apple `codesign --version` returned 2 because that command does not recognize `--version`; `otool -V` returned 1 because it requires an operation. Those version probes are recorded as environment evidence. The actual `codesign` verification and `otool -l` inspection commands completed and are the relevant tool checks.

The independent parser accepts Apple's empty ad hoc signature wrapper and canonical DER Boolean encoding only in the isolated diagnostic-control path. Production package validation requires the pinned ldid SuperBlob layout, exact entitlements, the ad hoc flag, and the approved empty requirements profile.

## Parser bounds and rejection coverage

`scripts/macho_code_signature.py` bounds Mach-O headers, load commands, segment ranges, `__LINKEDIT`, the signature area, SuperBlob indexes, subblob lengths, Requirements indexes, CodeDirectory hashes, and padding. It rejects unsupported architectures, malformed or missing CodeDirectories, overlaps/gaps, altered executable bytes, invalid special-slot hashes, changed or extra entitlements, truncated signatures, unexpected slots, and unmarked signatures at the RC acceptance layer. It reports independent CodeDirectory verification separately from Apple `codesign` and device acceptance.
