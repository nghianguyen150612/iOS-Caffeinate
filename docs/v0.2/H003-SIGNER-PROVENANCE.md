# H003 Signer Provenance

## Verified executable identity

| Field | Observed and checked value |
|---|---|
| Upstream repository | `https://github.com/ProcursusTeam/ldid.git` |
| Source commit | `aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef` |
| Source tree | `e473e8213e9821e986ac488ced802f5ee2b4bbea` |
| Version banner | `Link Identity Editor 2.1.5-procursus7` |
| Executable SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Expected P010 SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Executable format | ELF64 PIE, little-endian, x86_64 |
| Independent build 1 SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Independent build 2 SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Reproducibility | `EXACT_MATCH` |

Both builds used separate fresh source checkouts and temporary build directories. The executable was hashed and matched against the pin before H003 executed it to inspect its version banner. The H002 legacy validator now applies the same hash-before-execution rule when validating the pinned signer.

## New build environment

H003's observed environment is Ubuntu 24.04 on `linux/amd64`, using image `ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac` and the signed apt snapshot `https://snapshot.ubuntu.com/ubuntu/20261022T000000Z`.

The locked toolchain is GCC/G++ 13.3.0, GNU binutils 2.42, GNU Make 4.3, libplist 2.3.0, and OpenSSL 3.0.13. Exact Debian package versions, including Git, Python, pkg-config, and CA certificates, are recorded in `scripts/h003-build-inputs.lock` and in the generated JSON receipt.

The H001 historical image digest and package snapshot receipt were not recoverable. This H003 environment is a new verified observation; its identity is not represented as the former H001 environment. Matching the exact P010 executable hash is required independently of the build environment record.

The full non-sensitive receipt is [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json), under `signer_provenance`. CI retains the generated signer provenance JSON as a run artifact. The signer executable itself is not committed, uploaded, or published.
