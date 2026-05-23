# Design: Real-Time Log Mirroring for Dev Environment

**Date:** 2026-05-22  
**Branch:** feat/realtime-log-mirroring  
**Status:** Approved

---

## Problem

When `Run All Dev (CRM & Backend)` is executed:

- **Redis:** Output captured as a single block after the command ends — not streaming.
- **Backend:** Logs written via Python's `RotatingFileHandler` inside `main.py`. Only content that flows through Python's `logging` module reaches the file; raw uvicorn stdout/stderr is not mirrored. File-logging logic lives in application code, coupling infrastructure concerns to the app.
- **Frontend:** No file logging at all — `frontend.log` is never written.

## Goals

1. **Clean slate:** Each run truncates/overwrites the log file from scratch.
2. **Tee (mirror):** Everything that appears in the VS Code terminal panel is simultaneously written to the log file.
3. **Real-time (unbuffered):** No buffering delay. `PYTHONUNBUFFERED=1` for Python; `Tee-Object` writes each pipeline object as it arrives.
4. **Auto-create:** `logs/` directory is created if absent. No manual setup required.

## Scope

DEV environment only. These scripts are invoked exclusively by VS Code tasks. Production (Docker Swarm) is unaffected.

---

## Architecture

### File Structure

```
maquina-de-vendas/
├── scripts/
│   ├── start-redis.ps1        ← NEW
│   ├── start-backend.ps1      ← NEW
│   └── start-frontend.ps1     ← NEW
├── logs/
│   ├── .gitkeep
│   ├── redis.log
│   ├── backend.log
│   └── frontend.log
├── .vscode/
│   └── tasks.json             ← MODIFIED: thin launchers calling scripts
└── backend/app/main.py        ← MODIFIED: remove _setup_file_logging()
```

`clean-logs.ps1` at root is preserved for manual use.

---

## Script Behavior

### `scripts/start-redis.ps1`

1. Auto-create `logs/` directory.
2. `cd backend/` — required for docker compose context.
3. `docker compose up -d redis` — start Redis container detached.
4. `docker logs -f redis 2>&1 | Tee-Object -FilePath ../logs/redis.log` — stream container logs in real-time to terminal and file simultaneously. Task becomes `isBackground: true`.

**Why `docker logs -f`:** Redis runs detached so there is no foreground process stdout. Following the container log is the only way to get real-time Redis output.

### `scripts/start-backend.ps1`

1. Kill any process on port 8001 (port reuse guard).
2. Auto-create `logs/` directory.
3. Set `$env:PYTHONUNBUFFERED = "1"` — disables Python's stdout buffer.
4. `cd backend/`.
5. `& .venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 2>&1 | Tee-Object -FilePath ../logs/backend.log` — all uvicorn stdout+stderr mirrored in real-time.

### `scripts/start-frontend.ps1`

1. Kill any process on port 3000 (port reuse guard).
2. Auto-create `logs/` directory.
3. `cd frontend/`.
4. `npm run dev -- --hostname 127.0.0.1 --port 3000 2>&1 | Tee-Object -FilePath ../logs/frontend.log` — all Next.js output mirrored in real-time.

---

## tasks.json Changes

Each task becomes a thin launcher:

```json
{
  "label": "Start Redis",
  "type": "shell",
  "command": "powershell",
  "args": ["-NoProfile", "-NonInteractive", "-File", "${workspaceFolder}/scripts/start-redis.ps1"],
  "isBackground": true,
  "presentation": { "echo": true, "reveal": "always", "focus": false, "panel": "shared" },
  "problemMatcher": []
}
```

- `Start Redis` changes from `isBackground: false` to `isBackground: true` (now streams continuously).
- `env.LOG_FILE` removed from `Start Backend Dev` — no longer needed.
- `env.PYTHONUNBUFFERED` removed from task — set inside the script.

---

## backend/app/main.py Changes

**Remove entirely:**
- `import logging.handlers`
- `_LOG_FMT` formatter variable
- `_setup_file_logging()` function definition
- `_setup_file_logging()` call inside `lifespan()`

**Keep:**
- `import logging` + `logging.basicConfig(...)` — terminal output still works.

**Why:** File logging is now handled at the process level by `Tee-Object`. The application should not need to know where its logs go.

---

## Error Handling

- Port-kill errors are silenced with `-ErrorAction SilentlyContinue` (same as current behavior).
- If Redis container is not yet running when `docker logs -f` is called, docker will wait until it starts — acceptable for dev.
- `2>&1` merges stderr into the pipeline. In PowerShell 5.1 stderr lines from native executables appear as `ErrorRecord` objects but their string representation is written correctly by `Tee-Object -FilePath`.

---

## Out of Scope

- Log rotation (removed with `_setup_file_logging()`). Dev logs are small and short-lived.
- Log aggregation or structured logging.
- Production environment changes.
- Evolution API (excluded per project rules).
