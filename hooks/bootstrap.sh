#!/usr/bin/env bash
#
# SessionStart hook: install the claude-vision Python package into the
# plugin's data directory. Uses `pip install --target` so no venv is needed
# and nothing outside ${CLAUDE_PLUGIN_DATA} is touched.
#
# Idempotent: a marker file tied to the pyproject.toml hash means reinstall
# only happens when deps actually change (plugin update).

set -eu

: "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"
: "${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA not set}"

LIB="${CLAUDE_PLUGIN_DATA}/lib"
HASH="$(sha256sum "${CLAUDE_PLUGIN_ROOT}/pyproject.toml" | cut -c1-12)"
MARKER="${LIB}/.installed-${HASH}"

[ -f "${MARKER}" ] && exit 0

if ! command -v python3 >/dev/null 2>&1; then
    echo "claude-vision: python3 is required (>= 3.10)" >&2
    exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "claude-vision: pip is required (try: python3 -m ensurepip --upgrade)" >&2
    exit 1
fi

# Clean any previous installation so stale files don't leak between versions.
rm -rf "${LIB}"
mkdir -p "${LIB}"

# --break-system-packages is a no-op on non-PEP-668 envs; needed on Ubuntu 24.04+.
# --target keeps the install fully inside the plugin's data dir.
python3 -m pip install \
    --quiet \
    --target="${LIB}" \
    --break-system-packages \
    --upgrade \
    "${CLAUDE_PLUGIN_ROOT}[wayland,webcam]" >&2

touch "${MARKER}"
echo "claude-vision: installed to ${LIB}" >&2
