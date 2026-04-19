#!/usr/bin/env bash
#
# SessionStart hook: install the claude-vision Python package into a stable
# location under $HOME/.local/state/claude-vision/, and generate a wrapper
# script there with the lib path hard-coded.
#
# Why $HOME-based instead of ${CLAUDE_PLUGIN_DATA}:
# subagents (and the main agent's Bash tool) do not reliably inherit
# CLAUDE_PLUGIN_* env vars — only hooks do. Using a fixed $HOME-based
# path means the subagent can invoke the wrapper unambiguously without
# depending on env vars at all.
#
# Idempotent: a marker file tied to the pyproject.toml hash means we
# reinstall only when deps actually change.

set -eu

: "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"

STATE="${HOME}/.local/state/claude-vision"
LIB="${STATE}/lib"
BINDIR="${STATE}/bin"

if ! command -v python3 >/dev/null 2>&1; then
    echo "claude-vision: python3 is required (>= 3.10)" >&2
    exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "claude-vision: pip is required (try: python3 -m ensurepip --upgrade)" >&2
    exit 1
fi

# tkinter ships with Python's stdlib but Debian/Ubuntu split it out as
# python3-tk. When it's missing we pull pygame-ce as the fallback picker —
# only ~25MB, only where actually needed.
#
# The `ml` extra is always included in the "full" variant: it pulls torch +
# transformers + accelerate (~500MB), enabling local SmolVLM captioning.
# The model itself (~250MB) is downloaded on first captioner init, cached
# in ${STATE}/models/.
EXTRAS="wayland,webcam,ml"
if ! python3 -c "import tkinter" 2>/dev/null; then
    EXTRAS="${EXTRAS},picker"
fi

# Include the extras set in the install hash so that gaining or losing tkinter
# on the user's system triggers a fresh reinstall with the right extras.
HASH="$(
    { cat "${CLAUDE_PLUGIN_ROOT}/pyproject.toml"; printf 'extras=%s\n' "${EXTRAS}"; } \
    | sha256sum | cut -c1-12
)"
MARKER="${STATE}/.installed-${HASH}"

[ -f "${MARKER}" ] && exit 0

mkdir -p "${STATE}" "${BINDIR}"
rm -rf "${LIB}"
mkdir -p "${LIB}"

python3 -m pip install \
    --quiet \
    --target="${LIB}" \
    --break-system-packages \
    --upgrade \
    "${CLAUDE_PLUGIN_ROOT}[${EXTRAS}]" >&2

# Self-contained wrapper. Hard-codes ${LIB} so it works regardless of
# env vars — critical for subagents that don't inherit CLAUDE_PLUGIN_*.
cat > "${BINDIR}/claude-vision" <<EOF
#!/usr/bin/env bash
set -eu
export PYTHONPATH="${LIB}\${PYTHONPATH:+:\${PYTHONPATH}}"
exec python3 -m claude_vision "\$@"
EOF
chmod +x "${BINDIR}/claude-vision"

# Drop stale markers from previous versions before placing the new one.
find "${STATE}" -maxdepth 1 -name '.installed-*' -delete 2>/dev/null || true
touch "${MARKER}"

echo "claude-vision: installed to ${STATE}" >&2
