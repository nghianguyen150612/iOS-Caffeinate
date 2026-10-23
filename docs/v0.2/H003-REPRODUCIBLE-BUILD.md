# H003 Reproducible Signer Build

## Host requirements

- Linux x86_64 host with Docker Engine and Python 3.
- Network access to Docker Hub, the signed Ubuntu snapshot, and the public Procursus Git repository.
- A usable host CA bundle. If a host HTTPS inspection certificate is configured through `CODEX_PROXY_CERT`, the builder adds it only to a private temporary CA bundle.

The builder rejects other host architectures. It verifies the locked image digest before running the container, bind-mounts the checkout read-only, uses a private temporary build directory, and requires an empty private output directory. It never copies the executable into a system path.

## Rebuild command

```sh
mkdir -m 700 /tmp/ioscaffeinate-h003-signer
scripts/h003_build_signer.sh --output-dir /tmp/ioscaffeinate-h003-signer
```

The command fetches the locked source commit twice into clean directories, verifies commit and tree identities for each checkout, and runs:

```sh
make -C /path/to/ldid VERSION=2.1.5-procursus7
```

The two build outputs must match each other and the exact SHA-256 recorded in the lock. A mismatch aborts before executing the candidate binary. A successful run emits `ldid`, the exact pinned `libplist-2.0.so.4` runtime, `build-env.txt`, and `signer-provenance.json` in the private output directory. The JSON receipt binds the runtime library hash and package version to the signed Ubuntu snapshot. Downstream host use must set `LD_LIBRARY_PATH` to this output directory; do not substitute a host-installed libplist. Keep only the reviewed JSON receipt where durable evidence is needed; do not publish the executable or runtime as a public release asset.

## P011 command

After the signer output and eight official release assets have been verified, run the same H002 P011 CLI in the pinned runtime container:

```sh
scripts/h003_run_p011_preflight_container.sh \
  --package /absolute/path/to/release/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
  --asset-dir /absolute/path/to/release \
  --ldid /absolute/path/to/h003-signer/ldid \
  --json-out /absolute/path/to/new/P011-host-preflight.json
```

The wrapper validates absolute, non-symlink inputs, verifies the container digest, mounts package inputs read-only, and exposes only the report directory as writable. It pins and verifies Python, CA certificates, libplist, and OpenSSL package versions and their signed snapshot origin. Existing `HTTP_PROXY`/`HTTPS_PROXY` settings are passed through without being written to the receipt; the matching CA bundle is mounted for apt and Python HTTPS validation.

The P011 command checks the package against the pinned release identity and sidecars and validates its historical seven-record checksum contract plus the full derived member inventory. Historical coverage remains `HISTORICALLY_PARTIAL`. A successful host result cannot change `signature_integrity=PENDING`, `device_acceptance=PENDING`, or `release_authorization=BLOCKED`.
