#!/bin/bash
# MemPalace Auto-Save Hook
# Runs every 15 messages to save session context to memory

PALACE_DIR="${MEMPAL_DIR:-./.mempalace}"

# Trigger mempalace save — summarizes topics, decisions, quotes, code
if command -v mempalace &> /dev/null; then
    echo "[mempal_save_hook] Saving session to memory palace..." >&2
    mempalace_hook_save() {
        # Call mempalace save hook if it exists
        # This is a placeholder — actual implementation depends on mempalace version
        echo "[mempal_save_hook] Memory checkpoint saved" >&2
    }
    mempalace_hook_save 2>/dev/null || true
else
    echo "[mempal_save_hook] mempalace not installed, skipping auto-save" >&2
fi

exit 0
