#!/bin/bash
set -euxo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "ERROR: ARM Steam bootstrap must be generated on aarch64" >&2
    exit 1
fi

STEAM_BOOTSTRAP_HOME="${STEAM_BOOTSTRAP_HOME:-/var/lib/armada/steam-bootstrap-home}"
STEAM="${STEAM_BOOTSTRAP_HOME}/.local/share/Steam"
DOT_STEAM="${STEAM_BOOTSTRAP_HOME}/.steam"
STEAM_ARM_RUNTIME_BASE="https://repo.steampowered.com/steamrt3c/images"
STEAM_ARM_RUNTIME_CHANNEL="${STEAM_ARM_RUNTIME_CHANNEL:-latest-public-beta}"
STEAM_ARM_RUNTIME_SNAPSHOT="${STEAM_ARM_RUNTIME_SNAPSHOT:-$(curl -fsSL "${STEAM_ARM_RUNTIME_BASE}/${STEAM_ARM_RUNTIME_CHANNEL}.txt" | tr -d '[:space:]')}"
[[ -n "${STEAM_ARM_RUNTIME_SNAPSHOT}" ]] || { echo "ERROR: could not resolve ${STEAM_ARM_RUNTIME_CHANNEL} to a steamrt3c snapshot" >&2; exit 1; }
STEAM_ARM_RUNTIME_URL="${STEAM_ARM_RUNTIME_BASE}/${STEAM_ARM_RUNTIME_SNAPSHOT}/steam-runtime-steamrt-arm64.tar.xz"
STEAM_ARM_CHANNEL="steamdeck_publicbeta"
STEAM_ARM_CDN="https://client-update.steamstatic.com"
STEAM_ARM_MANIFEST_NAME="steam_client_${STEAM_ARM_CHANNEL}_linuxarm64"
STEAM_ARM_MANIFEST_URL="${STEAM_ARM_CDN}/${STEAM_ARM_MANIFEST_NAME}"
STEAM_BOOTSTRAP_TIMEOUT="${STEAM_BOOTSTRAP_TIMEOUT:-900}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rm -rf "${STEAM_BOOTSTRAP_HOME}"
mkdir -p "${STEAM}/package" "${DOT_STEAM}"

echo "${STEAM_ARM_CHANNEL}" > "${STEAM}/package/beta"
ln -sfn ../.local/share/Steam "${DOT_STEAM}/steam"
ln -sfn ../.local/share/Steam "${DOT_STEAM}/root"
ln -sfn ../.local/share/Steam/linux32 "${DOT_STEAM}/sdk32"
ln -sfn ../.local/share/Steam/linux64 "${DOT_STEAM}/sdk64"
ln -sfn ../.local/share/Steam/linuxarm64 "${DOT_STEAM}/sdkarm64"
ln -sfn ../.local/share/Steam/ubuntu12_32 "${DOT_STEAM}/bin32"
ln -sfn ../.local/share/Steam/ubuntu12_64 "${DOT_STEAM}/bin64"

steam_manifest="${STEAM}/package/${STEAM_ARM_MANIFEST_NAME}.manifest"
curl -fsSL -o "${steam_manifest}" "${STEAM_ARM_MANIFEST_URL}"

steam_seed_package=$(
    python3 - "${steam_manifest}" <<'PY'
import pathlib
import re
import sys

manifest = pathlib.Path(sys.argv[1]).read_text(errors="ignore")
match = re.search(r'bins_linuxarm64_linuxarm64\.zip\.(?!vz\.)[^"\s]+', manifest)
if not match:
    raise SystemExit("failed to find ARM64 Steam seed package")
print(match.group(0))
PY
)

curl -fsSL -o "${STEAM}/package/${steam_seed_package}" \
    "${STEAM_ARM_CDN}/${steam_seed_package}"
unzip -q -o "${STEAM}/package/${steam_seed_package}" -d "${STEAM}"

python3 - "${STEAM}/package/${steam_seed_package}" "${STEAM}" <<'PY'
import os
import pathlib
import stat
import subprocess
import sys
import zipfile

archive = pathlib.Path(sys.argv[1])
steam = pathlib.Path(sys.argv[2])

with zipfile.ZipFile(archive) as zf:
    names = [info.filename for info in zf.infolist() if not info.is_dir()]

for name in names:
    path = (steam / name).resolve()
    if not path.is_relative_to(steam.resolve()) or not path.is_file():
        continue
    result = subprocess.run(
        ["file", "-b", str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
    )
    if "interpreter /lib/ld-linux" not in result.stdout and not result.stdout.startswith(
        ("POSIX shell script", "Python script")
    ):
        continue
    mode = path.stat().st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
PY

curl -fsSL -o /tmp/steam-runtime-steamrt-arm64.tar.xz "${STEAM_ARM_RUNTIME_URL}"
tar -xJf /tmp/steam-runtime-steamrt-arm64.tar.xz -C "${STEAM}"
rm -f /tmp/steam-runtime-steamrt-arm64.tar.xz

steam_arm_ibus=$(
    find "${STEAM}/steam-runtime-steamrt-arm64" \
        -path '*/files/lib/aarch64-linux-gnu/libibus-1.0.so.5.*' \
        -type f |
        sort |
        tail -n1
)
if [[ -z "${steam_arm_ibus}" ]]; then
    echo "ERROR: failed to find ARM64 Steam runtime libibus shim" >&2
    exit 1
fi
mkdir -p "${STEAM}/lib/aarch64-linux-gnu"
ln -sfn \
    "../../${steam_arm_ibus#"${STEAM}/"}" \
    "${STEAM}/lib/aarch64-linux-gnu/libibus-1.0.so.5"

if [[ ! -f "${STEAM}/steamrtarm64/steam" ]]; then
    echo "ERROR: ARM64 Steam seed did not install steamrtarm64/steam" >&2
    exit 1
fi

Xvfb :99 -screen 0 1280x800x24 >/tmp/armada-steam-bootstrap-xvfb.log 2>&1 &
xvfb_pid=$!
trap 'kill "${xvfb_pid}" 2>/dev/null || true' EXIT
sleep 1

export HOME="${STEAM_BOOTSTRAP_HOME}"
export DISPLAY=:99
export LD_LIBRARY_PATH="${STEAM}/steamrtarm64:${STEAM}/lib/aarch64-linux-gnu"

installed_manifest="${STEAM}/package/${STEAM_ARM_MANIFEST_NAME}.installed"

verify_installed_manifest() {
    python3 "${script_dir}/verify-steam-bootstrap.py" \
        "${installed_manifest}" "${STEAM}"
}

steam_processes() {
    local pid state
    # The full bootstrap path avoids matching unrelated Steam-named processes.
    while read -r pid; do
        state=$(ps -o stat= -p "${pid}" 2>/dev/null) || continue
        state=${state//[[:space:]]/}
        [[ "${state}" == Z* ]] || echo "${pid}"
    done < <(pgrep -f "${STEAM_BOOTSTRAP_HOME}" || true)
}

show_steam_processes() {
    local pid_list
    printf -v pid_list '%s,' "$@"
    ps -o pid=,ppid=,stat=,args= -p "${pid_list%,}" >&2 || true
}

quiesce_steam_processes() {
    local -a steam_pids
    mapfile -t steam_pids < <(steam_processes)
    if ((${#steam_pids[@]} == 0)); then
        echo "No Steam bootstrap helpers remained after updater exit"
        return
    fi

    echo "Stopping Steam bootstrap helpers after updater exit:" >&2
    show_steam_processes "${steam_pids[@]}"
    kill "${steam_pids[@]}" 2>/dev/null || true
    for _ in {1..50}; do
        mapfile -t steam_pids < <(steam_processes)
        ((${#steam_pids[@]} == 0)) && return 0
        sleep 0.1
    done

    echo "Steam bootstrap helpers survived SIGTERM; sending SIGKILL:" >&2
    show_steam_processes "${steam_pids[@]}"
    kill -KILL "${steam_pids[@]}" 2>/dev/null || true
    for _ in {1..20}; do
        mapfile -t steam_pids < <(steam_processes)
        ((${#steam_pids[@]} == 0)) && return 0
        sleep 0.1
    done

    echo "ERROR: Steam bootstrap helpers survived SIGKILL" >&2
    show_steam_processes "${steam_pids[@]}"
    return 1
}

steam_verified=false
bootstrap_deadline=$((SECONDS + STEAM_BOOTSTRAP_TIMEOUT))
for attempt in {1..3}; do
    remaining_timeout=$((bootstrap_deadline - SECONDS))
    if ((remaining_timeout <= 0)); then
        break
    fi
    set +e
    timeout "${remaining_timeout}" \
        "${STEAM}/steamrtarm64/steam" \
        -steamdeck \
        -exitsteam \
        >/tmp/armada-steam-bootstrap.stdout \
        2>/tmp/armada-steam-bootstrap.stderr
    steam_rc=$?
    set -e
    quiesce_steam_processes

    if [[ "${steam_rc}" == "124" ]]; then
        echo "ERROR: Steam bootstrap exhausted its ${STEAM_BOOTSTRAP_TIMEOUT}-second timeout" >&2
        break
    fi

    if [[ -x "${STEAM}/steamrtarm64/steam" \
        && -f "${STEAM}/steamrtarm64/steamui.so" \
        && -f "${installed_manifest}" ]] \
        && verify_installed_manifest; then
        steam_verified=true
        break
    fi
    echo "Steam bootstrap attempt ${attempt} was incomplete (rc ${steam_rc})" >&2
done

if [[ "${steam_verified}" != "true" ]]; then
    echo "ERROR: Steam bootstrap did not produce a complete ARM64 Steam tree" >&2
    echo "--- last bootstrap stdout (tail) ---" >&2
    tail -n 30 /tmp/armada-steam-bootstrap.stdout >&2 || true
    echo "--- last bootstrap stderr (tail) ---" >&2
    tail -n 30 /tmp/armada-steam-bootstrap.stderr >&2 || true
    exit 1
fi

rm -rf \
    "${STEAM}/logs" \
    "${STEAM}/appcache/httpcache" \
    "${STEAM}/appcache/cefdata" \
    "${STEAM}/config/htmlcache"
find "${STEAM_BOOTSTRAP_HOME}" \
    \( -name '*.log' -o -name '*.pid' -o -name '*.token' -o -name '*.crash' \) \
    -delete
find "${STEAM_BOOTSTRAP_HOME}" \( -type s -o -type p \) -delete
rm -f \
    "${STEAM}/package/steam_client_metrics.bin" \
    "${STEAM}/registry.vdf" \
    "${STEAM}/ssfn"* \
    "${DOT_STEAM}/registry.vdf" \
    "${DOT_STEAM}/steam.pid" \
    "${DOT_STEAM}/steam.token"

# Steam opens Decky's localhost CEF debugger only when this marker exists.
touch "${STEAM}/.cef-enable-remote-debugging"
if ! verify_installed_manifest; then
    echo "ERROR: Steam bootstrap cleanup removed manifest content" >&2
    exit 1
fi

package_count=$(find "${STEAM}/package" -maxdepth 1 -type f | wc -l)
zipvz_count=$(find "${STEAM}/package" -maxdepth 1 -type f -name '*.zip.vz.*' | wc -l)
echo "Generated ARM64 Steam bootstrap: ${package_count} package files, ${zipvz_count} compressed payloads, updater rc ${steam_rc}, manifest verified"
