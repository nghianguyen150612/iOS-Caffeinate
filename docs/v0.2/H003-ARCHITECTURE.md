# H003 Architecture — signer provisioning and P011 host validation

H003 removes the ephemeral-workspace dependency from the host verification path. It reproduces the pinned Procursus `ldid` executable in an isolated, digest-pinned Ubuntu container, checks the result before executing it, retrieves the official v0.1.0 release assets, and invokes the existing H002 P011 contract against the published package.

## Data flow

1. `scripts/h003_signer.py` reads `scripts/h003-build-inputs.lock`, verifies the Docker image digest, mounts the source checkout read-only, and asks the container build script to install exact dependency versions from the signed Ubuntu snapshot.
2. The build script fetches the exact Procursus commit into two independent clean directories, checks both commit and tree identities, and builds each with the pinned compiler and libraries.
3. H003 compares both executable hashes with each other and with the pinned P010 SHA-256. It validates the ELF architecture and type, then reads the version banner only after the executable hash matches.
4. `scripts/h003_fetch_release_assets.py` uses the existing P011 HTTPS/API and pinned asset validation to retrieve the exact eight public release assets into a private empty directory.
5. `scripts/h003_run_p011_preflight_container.sh` starts the pinned Ubuntu runtime, installs the exact signer runtime libraries and Python from the signed snapshot, and invokes the unchanged H002 P011 release-preflight command. The package and assets are mounted read-only; only the report directory is writable.
6. The report asserts host-only results while keeping cryptographic signature integrity and every hardware gate pending. CI uploads the report and provenance receipts, never the signer binary or package.

## Trust boundaries

The historical H001 image digest and signed package snapshot could not be recovered from repository history or available H001 receipts. H003 therefore records a newly observed, reproducible environment rather than claiming to reconstruct H001's environment. The exact upstream commit, source tree, toolchain versions, signed apt origin, image digest, executable architecture, expected version, and final executable SHA-256 are checked independently.

The published v0.1.0 package remains byte-for-byte unchanged. H003 verifies its release identity, package archive hash, sidecars, historical checksum contract, derived inventory, package structure, profile, Mach-O metadata, maintainer scripts, and both embedded entitlement sets. The original historical checksum manifest remains partial; H003 does not imply that the release contains a full payload manifest.

Entitlement extraction establishes what the embedded entitlement blobs contain. It does not establish cryptographic signature trust, runtime behavior, installation acceptance, or hardware reliability. The P011 result is `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`; the release decision remains `BLOCKED`.

## Safety boundaries

The build output is held in a private temporary directory and is never installed system-wide or published as a release artifact. The P011 package and sidecars are mounted read-only. H003 has no device connection or package-install step. It does not start the daemon, acquire an assertion, change launchd state, authorize release, or create a v0.2 tag.
