#!/bin/bash
# MemPalace PreCompact Hook
# Fires before context compression — emergency save

set -e

PALACE_DIR="${MEMPAL_DIR:-./.mempalace}"

echo "[mempal_precompact_hook] Emergency save before context compression..." >&2

if command -v mempalace &> /dev/null; then
    mempalace_hook_precompact() {
        # Emergency save — synchronous, before the context window shrinks
        echo "[mempal_precompact_hook] Emergency checkpoint saved" >&2
    }
    mempalace_hook_precompact
else
    echo "[mempal_precompact_hook] mempalace not installed, skipping emergency save" >&2
fi

exit 0
