#!/usr/bin/env bash
set -euo pipefail
umask 077

requested_image="${H003_CONTAINER_IMAGE:-}"
source /workspace/scripts/h003-build-inputs.lock

if [[ "${H003_IN_PINNED_CONTAINER:-}" != "1" ]]; then
  echo 'H003_IN_PINNED_CONTAINER must be set by scripts/h003_signer.py.' >&2
  exit 2
fi
if [[ -n "$requested_image" && "$requested_image" != "$H003_CONTAINER_IMAGE" ]]; then
  echo 'Pinned builder image identity mismatch.' >&2
  exit 2
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo 'WRONG_HOST_ARCHITECTURE: pinned H003 signer is an x86_64 Linux executable.' >&2
  exit 20
fi

source_file=/run/h003.sources
if [[ ! -r "$source_file" ]]; then
  source_file=/tmp/h003.sources
  suites=${H003_APT_SUITES//,/ }
  cat > "$source_file" <<EOF
Types: deb
URIs: $H003_APT_SNAPSHOT/
Suites: $suites
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
fi
ca_file=/run/h003-ca.pem
if [[ ! -r "$ca_file" ]]; then
  ca_file=/etc/ssl/certs/ca-certificates.crt
fi
if [[ ! -r "$source_file" || ! -r "$ca_file" ]]; then
  echo 'H003 pinned apt source or CA bundle is unavailable.' >&2
  exit 2
fi

rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
install -m 0644 "$source_file" /etc/apt/sources.list.d/h003.sources
apt-get -o "Acquire::https::CaInfo=$ca_file" \
  -o APT::Update::Error-Mode=any \
  update

packages=(
  "gcc-13=$H003_GCC13_PACKAGE_VERSION"
  "g++-13=$H003_GPP13_PACKAGE_VERSION"
  "binutils=$H003_BINUTILS_PACKAGE_VERSION"
  "make=$H003_MAKE_PACKAGE_VERSION"
  "libplist-dev=$H003_LIBPLIST_PACKAGE_VERSION"
  "libssl-dev=$H003_OPENSSL_PACKAGE_VERSION"
  "pkg-config=$H003_PKG_CONFIG_PACKAGE_VERSION"
  "git=$H003_GIT_PACKAGE_VERSION"
  "python3=$H003_PYTHON3_PACKAGE_VERSION"
  "ca-certificates=$H003_CA_CERTIFICATES_PACKAGE_VERSION"
)

for spec in "${packages[@]}"; do
  package=${spec%%=*}
  policy=$(apt-cache policy "$package")
  if ! grep -Fq "$H003_APT_SNAPSHOT" <<<"$policy"; then
    echo "Dependency origin mismatch: $package is not sourced from the pinned Ubuntu snapshot." >&2
    exit 21
  fi
done

DEBIAN_FRONTEND=noninteractive apt-get \
  -o "Acquire::https::CaInfo=$ca_file" \
  install -y --no-install-recommends "${packages[@]}"

export GIT_SSL_CAINFO="$ca_file"
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_TERMINAL_PROMPT=0
export H003_CONTAINER_IMAGE
export H003_PLATFORM="$H003_PLATFORM"
export H003_OUTPUT_DIR="${H003_OUTPUT_DIR:-/output}"
exec python3 /workspace/scripts/h003_signer.py build-in-container --output-dir "$H003_OUTPUT_DIR"
