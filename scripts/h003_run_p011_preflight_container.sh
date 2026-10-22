#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/.." && pwd -P)
source "$script_dir/h003-build-inputs.lock"

usage() {
  echo 'Usage: h003_run_p011_preflight_container.sh --package FILE --asset-dir DIR --ldid FILE --json-out FILE' >&2
}

package=
asset_dir=
ldid=
json_out=
while (($#)); do
  case "$1" in
    --package) (($# >= 2)) || { usage; exit 2; }; package=$2; shift 2 ;;
    --asset-dir) (($# >= 2)) || { usage; exit 2; }; asset_dir=$2; shift 2 ;;
    --ldid) (($# >= 2)) || { usage; exit 2; }; ldid=$2; shift 2 ;;
    --json-out) (($# >= 2)) || { usage; exit 2; }; json_out=$2; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

for path in "$package" "$asset_dir" "$ldid" "$json_out"; do
  [[ "$path" == /* ]] || { echo 'H003 P011 paths must be absolute.' >&2; exit 2; }
  [[ "$path" != *','* ]] || { echo 'H003 P011 paths must not contain commas.' >&2; exit 2; }
done
[[ -d "$asset_dir" && ! -L "$asset_dir" ]] || { echo 'Release asset directory is missing or unsafe.' >&2; exit 2; }
[[ -f "$package" && ! -L "$package" && "$(dirname -- "$package")" -ef "$asset_dir" ]] || { echo 'Package must be a regular release asset in the pinned asset directory.' >&2; exit 2; }
[[ -f "$ldid" && ! -L "$ldid" && -x "$ldid" ]] || { echo 'Verified signer executable is missing or unsafe.' >&2; exit 2; }
report_dir=$(dirname -- "$json_out")
report_name=$(basename -- "$json_out")
[[ -d "$report_dir" && ! -L "$report_dir" && ! -e "$json_out" && ! -L "$json_out" ]] || { echo 'JSON report destination must be a new file in a real directory.' >&2; exit 2; }
[[ "$report_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.json$ ]] || { echo 'JSON report filename is unsafe.' >&2; exit 2; }
[[ ! -e "$report_dir/P011-host-preflight.txt" && ! -L "$report_dir/P011-host-preflight.txt" ]] || { echo 'P011 text report destination must be a new file.' >&2; exit 2; }

[[ "$(uname -m)" == x86_64 ]] || { echo 'WRONG_HOST_ARCHITECTURE: pinned H003 signer is an x86_64 Linux executable.' >&2; exit 20; }
docker=$(command -v docker || true)
[[ -n "$docker" ]] || { echo 'Pinned Docker P011 runtime is unavailable.' >&2; exit 2; }
"$docker" pull "$H003_CONTAINER_IMAGE" >/dev/null 2>&1 || { echo 'Pinned Ubuntu P011 runtime image is unavailable.' >&2; exit 2; }
inspect=$("$docker" image inspect --format '{{json .RepoDigests}}' "$H003_CONTAINER_IMAGE" 2>/dev/null) || { echo 'Pinned Ubuntu P011 runtime identity could not be inspected.' >&2; exit 2; }
python3 - "$inspect" "$H003_CONTAINER_IMAGE" <<'PY'
import json
import sys

try:
    digests = json.loads(sys.argv[1])
except json.JSONDecodeError:
    raise SystemExit("Pinned Ubuntu P011 runtime digest response is malformed") from None
if sys.argv[2] not in digests:
    raise SystemExit("Pinned Ubuntu P011 runtime digest does not match the H003 lock")
PY

temporary=$(mktemp -d "${TMPDIR:-/tmp}/ioscaffeinate-h003-p011.XXXXXX")
chmod 0700 "$temporary"
trap 'rm -rf -- "$temporary"' EXIT HUP INT TERM
ca_bundle="$temporary/ca-bundle.pem"
if [[ -n "${SSL_CERT_FILE:-}" && -r "$SSL_CERT_FILE" ]]; then
  cat "$SSL_CERT_FILE" > "$ca_bundle"
else
  cat /etc/ssl/certs/ca-certificates.crt > "$ca_bundle"
fi
if [[ -n "${CODEX_PROXY_CERT:-}" && -r "$CODEX_PROXY_CERT" ]]; then
  cat "$CODEX_PROXY_CERT" >> "$ca_bundle"
fi
chmod 0644 "$ca_bundle"

for path in "$repo_root" "$asset_dir" "$ldid" "$report_dir" "$ca_bundle"; do
  [[ "$path" != *','* ]] || { echo 'H003 P011 mount paths must not contain commas.' >&2; exit 2; }
done
docker_args=(
  run --rm "--platform=$H003_PLATFORM" --user=0:0
  --env H003_IN_PINNED_CONTAINER=1
  --env "H003_CONTAINER_IMAGE=$H003_CONTAINER_IMAGE"
  --env "H003_PLATFORM=$H003_PLATFORM"
  --env "H003_HOST_UID=$(id -u)"
  --env "H003_HOST_GID=$(id -g)"
  --env "H003_PACKAGE_NAME=$(basename -- "$package")"
  --env "H003_REPORT_NAME=$report_name"
  --env SSL_CERT_FILE=/run/h003-ca.pem
  --mount "type=bind,src=$repo_root,dst=/workspace,readonly"
  --mount "type=bind,src=$asset_dir,dst=/release,readonly"
  --mount "type=bind,src=$ldid,dst=/signer/ldid,readonly"
  --mount "type=bind,src=$report_dir,dst=/reports"
  --mount "type=bind,src=$ca_bundle,dst=/run/h003-ca.pem,readonly"
)
for variable in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
  if [[ -n "${!variable:-}" ]]; then
    docker_args+=(--env "$variable=${!variable}")
  fi
done
"$docker" "${docker_args[@]}" "$H003_CONTAINER_IMAGE" bash /workspace/scripts/h003_p011_preflight_container.sh
