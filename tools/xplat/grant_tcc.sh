#!/usr/bin/env bash
# Grants macOS privacy permissions (TCC) to one program on a CI runner, where
# nobody can press Allow: a row written straight into the system TCC.db with
# sudo sqlite3, read back, then tccd restarted. This is xa11y's
# scripts/grant_macos_tcc.sh (MIT, see NOTICE) with a list of services.
# It only works where SIP leaves the system TCC.db writable (GitHub's hosted
# macOS runners); on a person's Mac the grant is theirs to give in System Settings.
#
#   tools/xplat/grant_tcc.sh <program> [service ...]
#
# <program> is the real binary on disk (TCC matches the resolved path, not a
# symlink). Services default to Accessibility, PostEvent and ScreenCapture.

set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "grant_tcc.sh: not macOS, nothing to do." >&2
    exit 0
fi

CLIENT="${1:?usage: $0 <program> [service ...]}"
shift
SERVICES=("$@")
[ "${#SERVICES[@]}" -gt 0 ] || SERVICES=(Accessibility PostEvent ScreenCapture)

TCC_DB="/Library/Application Support/com.apple.TCC/TCC.db"
BUSY_MS="${TCC_BUSY_TIMEOUT_MS:-10000}"
ATTEMPTS="${TCC_WRITE_ATTEMPTS:-5}"
CLIENT_SQL="$(printf '%s' "$CLIENT" | sed "s/'/''/g")"

# tccd holds TCC.db and writes on its own schedule: wait on its lock, retry a few times, fail loudly.
OUT=""
tcc() {
    local what="$1" sql="$2" attempt=1
    until OUT="$(sudo sqlite3 -cmd ".timeout ${BUSY_MS}" "$TCC_DB" "$sql" 2>&1)"; do
        echo "grant_tcc.sh: ${what} attempt ${attempt}/${ATTEMPTS} failed: ${OUT}" >&2
        if [ "$attempt" -ge "$ATTEMPTS" ]; then
            echo "::error::grant_tcc.sh: ${what} for ${CLIENT} failed: ${OUT}" >&2
            exit 1
        fi
        sleep $((attempt * 2))
        attempt=$((attempt + 1))
    done
}

for name in "${SERVICES[@]}"; do
    service="kTCCService${name}"
    # Named columns keep the insert working as the table gains columns; auth_value 2 is allowed, client_type 1
    # an absolute path.
    tcc "write of ${service}" "INSERT OR REPLACE INTO access(service,client,client_type,auth_value,auth_reason,\
auth_version,csreq,policy_id,indirect_object_identifier_type,indirect_object_identifier,\
indirect_object_code_identity,flags,last_modified) VALUES('${service}','${CLIENT_SQL}',1,2,4,1,NULL,NULL,0,\
'UNUSED',NULL,0,$(date +%s));"
    tcc "read-back of ${service}" "SELECT auth_value FROM access WHERE service='${service}' AND \
client='${CLIENT_SQL}' AND client_type=1 AND indirect_object_identifier='UNUSED';"
    if [ "$OUT" != "2" ]; then
        echo "::error::grant_tcc.sh: no allowed ${service} row for ${CLIENT} after the write (read back '${OUT}')" >&2
        exit 1
    fi
    echo "grant_tcc.sh: ${service} granted to ${CLIENT}"
done

# launchctl stop makes launchd start tccd again, which then reads the new rows.
sudo launchctl stop com.apple.tccd 2>/dev/null || true
sleep 2
