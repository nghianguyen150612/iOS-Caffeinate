#!/usr/bin/env bash
set -euo pipefail
umask 077

requested_image=${H003_CONTAINER_IMAGE:-}
requested_platform=${H003_PLATFORM:-}
source /workspace/scripts/h003-build-inputs.lock
[[ "${H003_IN_PINNED_CONTAINER:-}" == 1 ]] || { echo 'H003 container invocation guard missing.' >&2; exit 2; }
[[ "$requested_image" == "$H003_CONTAINER_IMAGE" && "$requested_platform" == "$H003_PLATFORM" ]] || { echo 'Pinned P011 runtime image identity mismatch.' >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'WRONG_HOST_ARCHITECTURE: P011 signer runtime requires x86_64 Linux.' >&2; exit 20; }

ca_file=/run/h003-ca.pem
[[ -r "$ca_file" ]] || ca_file=/etc/ssl/certs/ca-certificates.crt
[[ -r "$ca_file" ]] || { echo 'H003 pinned P011 runtime CA bundle is unavailable.' >&2; exit 2; }
temporary=$(mktemp -d /tmp/ioscaffeinate-h003-p011.XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT HUP INT TERM
suites=${H003_APT_SUITES//,/ }
cat > "$temporary/ubuntu.sources" <<EOF
Types: deb
URIs: $H003_APT_SNAPSHOT/
Suites: $suites
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
install -m 0644 "$temporary/ubuntu.sources" /etc/apt/sources.list.d/h003-p011.sources
apt-get -o "Acquire::https::CaInfo=$ca_file" -o APT::Update::Error-Mode=any update

packages=(
  "python3=$H003_PYTHON3_PACKAGE_VERSION"
  "ca-certificates=$H003_CA_CERTIFICATES_PACKAGE_VERSION"
  "libplist-2.0-4=$H003_LIBPLIST_RUNTIME_PACKAGE_VERSION"
  "libplist-dev=$H003_LIBPLIST_PACKAGE_VERSION"
  "libssl-dev=$H003_OPENSSL_PACKAGE_VERSION"
)
for spec in "${packages[@]}"; do
  package=${spec%%=*}
  policy=$(apt-cache policy "$package")
  grep -Fq "$H003_APT_SNAPSHOT" <<<"$policy" || { echo "P011 runtime origin mismatch: $package" >&2; exit 21; }
done
DEBIAN_FRONTEND=noninteractive apt-get -o "Acquire::https::CaInfo=$ca_file" install -y --no-install-recommends "${packages[@]}"
for spec in "${packages[@]}"; do
  package=${spec%%=*}
  expected=${spec#*=}
  actual=$(dpkg-query -W -f='${Version}' "$package")
  [[ "$actual" == "$expected" ]] || { echo "P011 runtime version mismatch: $package" >&2; exit 1; }
done

report_path="/reports/$H003_REPORT_NAME"
python3 /workspace/scripts/p011_release_preflight.py \
  --package "/release/$H003_PACKAGE_NAME" \
  --asset-dir /release \
  --ldid /signer/ldid \
  --json-out "$report_path" | tee /reports/P011-host-preflight.txt
python3 - "$report_path" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
package = report["verified_package"]
expected = {
    "historical_archive": "VERIFIED",
    "legacy_checksum_manifest": "VERIFIED",
    "checksum_coverage": "HISTORICALLY_PARTIAL",
    "package_structure": "VERIFIED",
    "signer_provenance": "VERIFIED",
    "embedded_entitlements": "EXACT_MATCH",
    "signature_integrity": "PENDING",
    "device_acceptance": "PENDING",
    "package_sha256": "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c",
    "package_size_bytes": 95572,
}
if report["status"] != "P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING":
    raise SystemExit("authentic P011 preflight did not pass with device acceptance pending")
for key, value in expected.items():
    if package.get(key) != value:
        raise SystemExit(f"P011 result mismatch: {key}")
if report["hardware"]["device_acceptance"] != "PENDING":
    raise SystemExit("host preflight changed device acceptance")
if report["hardware"]["release_authorization"] != "BLOCKED":
    raise SystemExit("host preflight changed the release decision")
if any(value != "PENDING" for value in report["hardware"]["gate_states"].values()):
    raise SystemExit("host preflight satisfied a hardware gate")
PY
chown "${H003_HOST_UID:-0}:${H003_HOST_GID:-0}" "$report_path" /reports/P011-host-preflight.txt
