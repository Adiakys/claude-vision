#!/usr/bin/env bash
#
# Keep plugins/base and plugins/full in sync.
#
# plugins/base/ is the source of truth. plugins/full/ is a copy with
# small, deterministic diffs layered on top (different plugin.json name,
# different bootstrap EXTRAS, optional ml/ module that lives only in full).
#
# Usage:
#   ./scripts/sync.sh             # regenerate plugins/full/ from plugins/base/
#   ./scripts/sync.sh --verify    # exit non-zero if out of sync (for CI)
#
# Dev workflow: edit plugins/base/ → run ./scripts/sync.sh → commit both.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${REPO_ROOT}/plugins/base"
FULL="${REPO_ROOT}/plugins/full"

VERIFY=false
if [ "${1:-}" = "--verify" ]; then
    VERIFY=true
fi

if [ ! -d "${BASE}" ]; then
    echo "sync: expected ${BASE} to exist" >&2
    exit 2
fi

# Files and directories that live ONLY in plugins/full/ (full-specific)
# — sync MUST preserve these. Everything else is mirrored from base.
FULL_ONLY=(
    ".claude-plugin/plugin.json"        # different name / description
    "hooks/bootstrap.sh"                 # different EXTRAS string (includes ml)
    "pyproject.toml"                     # different name + ml extra
    "src/claude_vision/ml"               # ML module lives only in full
    "tests/test_captioner.py"            # test of the ml-specific module
    "agents/frame-analyst.md"            # extended playbook with captioning guidance
)

_is_full_only() {
    local rel="$1"
    for entry in "${FULL_ONLY[@]}"; do
        # exact match or prefix match (for directories)
        [ "$rel" = "$entry" ] && return 0
        [[ "$rel" == ${entry}/* ]] && return 0
    done
    return 1
}

STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

# 1. Populate staging with EVERYTHING from base
#    Skip generated caches so sync stays deterministic across test runs.
rsync -a \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='.egg-info' \
    "${BASE}/" "${STAGING}/"

# 2. Overlay the full-only files from the EXISTING full/, so they survive
if [ -d "${FULL}" ]; then
    for entry in "${FULL_ONLY[@]}"; do
        src="${FULL}/${entry}"
        dest="${STAGING}/${entry}"
        if [ -e "${src}" ]; then
            mkdir -p "$(dirname "${dest}")"
            rm -rf "${dest}"
            cp -r "${src}" "${dest}"
        fi
    done
fi

# 3. Compare staging with current full (ignoring transient cache files)
if [ "${VERIFY}" = true ]; then
    DIFF_OUT="$(diff -qr \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='*.pyc' \
        "${STAGING}" "${FULL}" 2>&1 || true)"
    if [ -n "${DIFF_OUT}" ]; then
        echo "sync: plugins/full/ is out of sync with plugins/base/" >&2
        echo "      run ./scripts/sync.sh to regenerate" >&2
        echo "${DIFF_OUT}" | head -20 >&2
        exit 1
    fi
    echo "sync: plugins/full/ is in sync with plugins/base/"
    exit 0
fi

# 4. Overwrite full/ atomically with staging
rm -rf "${FULL}"
mv "${STAGING}" "${FULL}"
trap - EXIT

echo "sync: plugins/full/ regenerated from plugins/base/"
echo "      preserved full-only: ${FULL_ONLY[*]}"
