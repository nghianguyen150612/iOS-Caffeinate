#!/bin/sh
# Read-only P011 inspection for the iPad mini 2 A1489 / rootful Procursus target.
# This script never installs/removes packages, stops processes, changes launchd,
# edits SSH/Tailscale, opens an IPC session, or acquires an IOKit assertion.

set -u

PACKAGE='com.ioscaffeinate.cli'
EXPECTED_VERSION='0.1.0-1'
EXPECTED_ARCH='iphoneos-arm'
EXPECTED_DEVICE='iPad4,4'
EXPECTED_IOS='12.5.7'
EXPECTED_PACKAGE_SHA256='439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c'
PACKAGE_FILE='ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb'
CLI='/usr/local/bin/ios-caffeinate'
DAEMON='/usr/local/bin/ios-caffeinated'
ALIAS='/usr/local/bin/ic'
MANAGER='/usr/local/libexec/ioscaffeinate-manager'
SOCKET='/var/run/ioscaffeinated.sock'
STAGED_PLIST='/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist'
LIVE_PLIST='/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist'
FAILURES=0
PACKAGE_PATH=${1:-}

info() {
    printf '%s\n' "$*"
}

fail() {
    info "FAIL: $*"
    FAILURES=$((FAILURES + 1))
}

usage() {
    info "Usage: /bin/sh $0 [path/to/$PACKAGE_FILE]"
    info 'Read-only inspection; the optional package is checked against the pinned stable release hash.'
}

if [ "${1:-}" = '--help' ] || [ "${1:-}" = '-h' ]; then
    usage
    exit 0
fi
if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi

hash_file() {
    hash_path=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$hash_path" 2>/dev/null | awk 'NR == 1 {print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$hash_path" 2>/dev/null | awk 'NR == 1 {print $1}'
    elif command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$hash_path" 2>/dev/null | awk '{print $NF}'
    else
        return 1
    fi
}

check_package_path() {
    path=$1
    if [ -L "$path" ] || [ ! -f "$path" ] || [ ! -r "$path" ]; then
        fail 'package must be a readable regular file, not a symlink'
        return
    fi
    actual_hash=$(hash_file "$path" 2>/dev/null || true)
    if [ -z "$actual_hash" ]; then
        fail 'no working SHA-256 implementation could read the package'
    elif [ "$actual_hash" != "$EXPECTED_PACKAGE_SHA256" ]; then
        fail "package SHA-256 mismatch: $actual_hash"
    else
        info "package_sha256=$actual_hash"
    fi
    if command -v dpkg-deb >/dev/null 2>&1; then
        package_name=$(dpkg-deb --field "$path" Package 2>/dev/null || true)
        package_version=$(dpkg-deb --field "$path" Version 2>/dev/null || true)
        package_arch=$(dpkg-deb --field "$path" Architecture 2>/dev/null || true)
        info "artifact_identity=${package_name:-UNKNOWN} version=${package_version:-UNKNOWN} architecture=${package_arch:-UNKNOWN}"
        [ "$package_name" = "$PACKAGE" ] || fail "package artifact identity is ${package_name:-unknown}"
        [ "$package_version" = "$EXPECTED_VERSION" ] || fail "package artifact version is ${package_version:-unknown}"
        [ "$package_arch" = "$EXPECTED_ARCH" ] || fail "package artifact architecture is ${package_arch:-unknown}"
    else
        fail 'dpkg-deb is unavailable for package metadata inspection'
    fi
}

check_package_owned_path() {
    path=$1
    if [ -e "$path" ] || [ -L "$path" ]; then
        if [ "$PACKAGE_STATE" != 'installed' ]; then
            fail "existing path collides with an uninstalled package: $path"
            return
        fi
        owner_line=$(dpkg-query -S "$path" 2>/dev/null | awk 'NR == 1 {print $1}' || true)
        owner=${owner_line%%:*}
        if [ "$owner" != "$PACKAGE" ]; then
            fail "existing package path is not owned by $PACKAGE: $path"
        else
            info "package_path[$path]=PRESENT_AND_OWNED"
        fi
    elif [ "$PACKAGE_STATE" = 'installed' ]; then
        fail "installed package file is missing: $path"
    else
        info "package_path[$path]=ABSENT"
    fi
}

check_real_directory() {
    path=$1
    if [ -L "$path" ]; then
        fail "directory path is a symlink: $path"
    elif [ -e "$path" ] && [ ! -d "$path" ]; then
        fail "directory path is not a directory: $path"
    elif [ -d "$path" ]; then
        info "directory_path[$path]=REAL_DIRECTORY"
    else
        info "directory_path[$path]=ABSENT"
    fi
}

info 'P011 read-only device preflight; physical recovery and install authorization remain operator gates.'

if command -v sw_vers >/dev/null 2>&1; then
    ios_version=$(sw_vers -productVersion 2>/dev/null || true)
    info "ios_version=${ios_version:-UNKNOWN}"
    [ "$ios_version" = "$EXPECTED_IOS" ] || fail "expected iOS $EXPECTED_IOS"
else
    fail 'sw_vers is unavailable; iOS version could not be verified'
fi

if command -v sysctl >/dev/null 2>&1; then
    device_model=$(sysctl -n hw.machine 2>/dev/null || true)
    info "device_model=${device_model:-UNKNOWN}"
    [ "$device_model" = "$EXPECTED_DEVICE" ] || fail "expected device model identifier $EXPECTED_DEVICE"
else
    fail 'sysctl is unavailable; device model could not be verified'
fi

if command -v id >/dev/null 2>&1; then
    uid=$(id -u 2>/dev/null || true)
    info "effective_uid=${uid:-UNKNOWN}"
    [ "$uid" = '0' ] || fail 'read-only preflight must run from the rootful target shell'
else
    fail 'id is unavailable; root privileges could not be checked'
fi

if [ -e /var/jb ] || [ -L /var/jb ]; then
    fail '/var/jb is present; rootful installation assumptions need operator review'
else
    info 'bootstrap_layout=ROOTFUL_PREFIX_ASSUMPTION_MATCHES'
fi

if command -v dpkg >/dev/null 2>&1; then
    dpkg_arch=$(dpkg --print-architecture 2>/dev/null || true)
    info "dpkg_architecture=${dpkg_arch:-UNKNOWN}"
    [ "$dpkg_arch" = "$EXPECTED_ARCH" ] || fail "dpkg architecture must be $EXPECTED_ARCH"
    info 'package_manager=dpkg_AVAILABLE'
else
    fail 'dpkg is unavailable'
fi
if command -v apt-get >/dev/null 2>&1; then
    info 'bootstrap_package_manager=apt-get_AVAILABLE'
else
    info 'bootstrap_package_manager=apt-get_NOT_PRESENT'
fi

PACKAGE_STATE='not-installed'
if command -v dpkg-query >/dev/null 2>&1; then
    package_record=$(dpkg-query -W -f='${Status}|${Version}|${Architecture}' "$PACKAGE" 2>/dev/null || true)
    if [ -n "$package_record" ]; then
        package_status=${package_record%%|*}
        package_tail=${package_record#*|}
        installed_version=${package_tail%%|*}
        installed_arch=${package_tail#*|}
        info "installed_package=$PACKAGE status=$package_status version=$installed_version architecture=$installed_arch"
        if [ "$package_status" = 'install ok installed' ]; then
            PACKAGE_STATE='installed'
            [ "$installed_arch" = "$EXPECTED_ARCH" ] || fail "installed package architecture is $installed_arch"
            case "$installed_version" in
                '0.1.0-1'|'0.1.0~rc1-1') ;;
                *) fail "installed package version requires explicit review: $installed_version" ;;
            esac
        else
            fail "package database has a partial or inconsistent state: $package_status"
        fi
    else
        info "installed_package=$PACKAGE state=NOT_INSTALLED"
    fi
else
    fail 'dpkg-query is unavailable'
fi

for directory_path in \
    /usr/local \
    /usr/local/bin \
    /usr/local/libexec \
    /usr/share \
    /usr/share/doc \
    /usr/share/ioscaffeinate \
    /usr/share/ioscaffeinate/launchd \
    /usr/share/doc/ioscaffeinate \
    /var/lib/ioscaffeinate \
    /var/log/ioscaffeinate
do
    check_real_directory "$directory_path"
done

if [ -n "$PACKAGE_PATH" ]; then
    check_package_path "$PACKAGE_PATH"
else
    info 'package_artifact=NOT_SUPPLIED_HASH_CHECK_NOT_RUN'
    if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1 && ! command -v openssl >/dev/null 2>&1; then
        fail 'no SHA-256 implementation is available for package verification'
    else
        info 'package_hash_verifier=AVAILABLE'
    fi
fi

if command -v dpkg-query >/dev/null 2>&1; then
    check_package_owned_path "$CLI"
    check_package_owned_path "$DAEMON"
    check_package_owned_path "$ALIAS"
    check_package_owned_path "$MANAGER"
    check_package_owned_path "$STAGED_PLIST"
else
    fail 'cannot inspect package-file collisions without dpkg-query'
fi

if [ -L "$ALIAS" ]; then
    alias_target=$(readlink "$ALIAS" 2>/dev/null || true)
    case "$alias_target" in
        ios-caffeinate|/usr/local/bin/ios-caffeinate) info "cli_alias=EXPECTED_TARGET ($alias_target)" ;;
        *) fail "ic points to an unexpected target: ${alias_target:-UNKNOWN}" ;;
    esac
elif [ -e "$ALIAS" ]; then
    fail '/usr/local/bin/ic exists but is not a symlink'
else
    info 'cli_alias=ABSENT'
fi

if [ -e "$STAGED_PLIST" ] && [ -r "$STAGED_PLIST" ]; then
    if grep -q '<key>Disabled</key><true/>' "$STAGED_PLIST" && grep -q '<key>RunAtLoad</key><false/>' "$STAGED_PLIST"; then
        info 'staged_launchd_template=DISABLED_AND_NOT_RUN_AT_LOAD'
    else
        fail 'staged launchd template is malformed or does not remain disabled'
    fi
else
    info 'staged_launchd_template=ABSENT'
fi

if [ -e "$LIVE_PLIST" ] || [ -L "$LIVE_PLIST" ]; then
    fail "active LaunchDaemons plist exists and requires P013/operator review: $LIVE_PLIST"
else
    info 'active_launchd_plist=ABSENT'
fi
if command -v launchctl >/dev/null 2>&1; then
    if launchd_list=$(launchctl list 2>/dev/null); then
        if printf '%s\n' "$launchd_list" | awk '$NF == "com.ioscaffeinate.daemon" {found=1} END {exit !found}'; then
            fail 'iOS-Caffeinate launchd label is loaded'
        else
            info 'launchd_label=NOT_LISTED'
        fi
    else
        fail 'launchctl list could not confirm launchd state'
    fi
else
    fail 'launchctl is unavailable; launchd state could not be confirmed'
fi

if command -v ps >/dev/null 2>&1; then
    daemon_processes=$(ps -ax 2>/dev/null | awk '$0 ~ /ios-caffeinated/ && $0 !~ /awk/ {print}' || true)
    if [ -n "$daemon_processes" ]; then
        fail 'ios-caffeinated process is present; do not continue installation preflight'
    else
        info 'daemon_process=ABSENT'
    fi
else
    fail 'ps is unavailable; daemon process state could not be confirmed'
fi

if [ -S "$SOCKET" ]; then
    fail "default daemon socket is present; do not remove it or continue: $SOCKET"
elif [ -e "$SOCKET" ] || [ -L "$SOCKET" ]; then
    fail "default daemon endpoint exists but is not a socket: $SOCKET"
else
    info 'default_daemon_socket=ABSENT'
fi

for state_path in \
    /var/lib/ioscaffeinate/schedules.json \
    /var/lib/ioscaffeinate/server-mode.json \
    /var/lib/ioscaffeinate \
    /var/log/ioscaffeinate
do
    if [ -e "$state_path" ] || [ -L "$state_path" ]; then
        ls -ld "$state_path" 2>/dev/null || fail "could not inspect existing state path: $state_path"
    else
        info "persistent_path[$state_path]=ABSENT"
    fi
done

if command -v df >/dev/null 2>&1; then
    free_kb=$(df -Pk / 2>/dev/null | awk 'NR == 2 {print $4}')
    case "$free_kb" in
        ''|*[!0-9]*) fail 'available storage could not be read' ;;
        *)
            info "root_filesystem_available_kb=$free_kb"
            [ "$free_kb" -ge 10240 ] || fail 'less than 10 MiB is available on the root filesystem'
            ;;
    esac
else
    fail 'df is unavailable; storage could not be checked'
fi

if [ -x "$MANAGER" ]; then
    if "$MANAGER" verify; then
        info 'installed_manager_verify=PASS_READ_ONLY'
    else
        fail 'installed package manager verify reported an inconsistency'
    fi
else
    info 'installed_manager=NOT_PRESENT'
    if [ "$PACKAGE_STATE" = 'installed' ]; then
        fail 'package is installed but its manager is missing or not executable'
    fi
fi

info 'physical_recovery=OPERATOR_CONFIRMATION_REQUIRED_INDEPENDENT_OF_SSH'
info 'installation_authorization=NOT_GRANTED_BY_PREFLIGHT'
if [ "$FAILURES" -gt 0 ]; then
    info "P011_DEVICE_PREFLIGHT=BLOCKED failure_count=$FAILURES"
    exit 1
fi
info 'P011_DEVICE_PREFLIGHT=READ_ONLY_CHECKS_PASS_OPERATOR_REVIEW_STILL_REQUIRED'
exit 0
