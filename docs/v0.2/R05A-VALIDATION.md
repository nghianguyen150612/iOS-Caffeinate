# R05A Validation Record

**Source under review:** R05 baseline `b2fdea8764ba08a8f60fe4d5acae2705dce7bd37`; corrected implementation is stacked in [PR #23](https://github.com/nghianguyen150612/iOS-Caffeinate/pull/23).

## Completed local checks

- The authentic failed R05 receipt, package hash, source commit, binary hashes, H003 signer identity, and profile identity were checked against the downloaded evidence.
- Independent parsing of both failed Mach-O signatures verified all 53/35 code-slot hashes, special slots 2/5/7, CodeDirectory v2.4 metadata, entitlement identities, and the signature's `__LINKEDIT` placement. Both CodeDirectories had flags `0`.
- The pinned H003 signer was run on copies of both exact unsigned inputs using `-Cadhoc -S` and the unchanged approved profile. Both outputs had flags `0x2`; independent hashes and exact entitlements passed.
- Regression tests cover the required ad hoc flag, valid code and special-slot hashes, Apple’s empty ad hoc wrapper, missing CodeDirectory, malformed SuperBlob offsets, changed executable bytes, changed special-slot hashes, altered entitlement content, truncation, wrong architecture, receipt run binding, and source/package digest mismatch.
- Full local suite: 363 tests passed, 3 skipped. `scripts/build-linux-test.sh`, shell/document checks, workflow YAML parsing, Python compilation, and `git diff --check` passed.

## GitHub-hosted validation

| Check | Run / result |
|---|---|
| Authentic macOS comparison workflow | [Run 40064018459](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/40064018459), source `8f61de738d2fe9f402d3ea247071d6aa41bae82c`: pass; flags-zero R05 and v0.1 controls fail Apple verification, flags-two Apple ad hoc copies pass |
| Exact-head PR CI | The result on PR #23 is authoritative for its exact commit SHA; the candidate workflow waits for that result |
| Corrected signed-candidate workflow | Run-bound Apple and independent verification receipts determine candidate status for each exact source commit |
| Final candidate inventory and fresh-extraction validation | Generated and uploaded by the finalizer only after both executable checks and receipt bindings pass |

## Qualification boundary

No device transfer or operation was performed. Physical H004, P011, P012, P013, P014, P016, and P019 evidence remains pending. A completed macOS host check will not establish iOS runtime behavior or target-device acceptance.
