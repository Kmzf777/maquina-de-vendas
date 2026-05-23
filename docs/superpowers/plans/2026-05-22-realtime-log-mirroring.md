# Real-Time Log Mirroring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror stdout+stderr of Redis, Backend, and Frontend dev processes to `logs/*.log` in real-time using PowerShell `Tee-Object`, replacing the current broken/absent log file approach.

**Architecture:** Three `.ps1` scripts in `scripts/` handle process startup and tee piping. VS Code `tasks.json` becomes thin launchers that call these scripts. The `_setup_file_logging()` function in `backend/app/main.py` is removed — file logging is now a process-level concern, not an application concern.

**Tech Stack:** PowerShell 5.1 (Windows), `Tee-Object`, `docker logs -f`, uvicorn, Next.js `npm run dev`

**Branch:** `feat/realtime-log-mirroring`

---

### Task 1: Create `scripts/start-redis.ps1`

**Files:**
- Create: `scripts/start-redis.ps1`

- [ ] **Step 1: Create the scripts directory and start-redis.ps1**

Create `scripts/start-redis.ps1` with the following content:

```powershell
$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\backend"
docker compose up -d redis
docker logs -f redis 2>&1 | Tee-Object -FilePath "$logsDir\redis.log"
```

- [ ] **Step 2: Verify the script syntax is valid**

Run:
```powershell
powershell -NoProfile -NonInteractive -Command "& { [System.Management.Automation.Language.Parser]::ParseFile('scripts/start-redis.ps1', [ref]$null, [ref]$null) | Out-Null; 'syntax ok' }"
```
Expected output: `syntax ok`

- [ ] **Step 3: Commit**

```powershell
git add scripts/start-redis.ps1
git commit -m "feat(dev): add start-redis.ps1 with real-time tee to redis.log"
```

---

### Task 2: Create `scripts/start-backend.ps1`

**Files:**
- Create: `scripts/start-backend.ps1`

- [ ] **Step 1: Create start-backend.ps1**

Create `scripts/start-backend.ps1` with the following content:

```powershell
$port = 8001
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

$env:PYTHONUNBUFFERED = "1"
Set-Location "$PSScriptRoot\..\backend"
& "$PSScriptRoot\..\.venv\Scripts\python" -m uvicorn app.main:app --host 0.0.0.0 --port 8001 2>&1 |
    Tee-Object -FilePath "$logsDir\backend.log"
```

- [ ] **Step 2: Verify the script syntax is valid**

Run:
```powershell
powershell -NoProfile -NonInteractive -Command "& { [System.Management.Automation.Language.Parser]::ParseFile('scripts/start-backend.ps1', [ref]$null, [ref]$null) | Out-Null; 'syntax ok' }"
```
Expected output: `syntax ok`

- [ ] **Step 3: Commit**

```powershell
git add scripts/start-backend.ps1
git commit -m "feat(dev): add start-backend.ps1 with PYTHONUNBUFFERED and tee to backend.log"
```

---

### Task 3: Create `scripts/start-frontend.ps1`

**Files:**
- Create: `scripts/start-frontend.ps1`

- [ ] **Step 1: Create start-frontend.ps1**

Create `scripts/start-frontend.ps1` with the following content:

```powershell
$port = 3000
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\frontend"
npm run dev -- --hostname 127.0.0.1 --port 3000 2>&1 |
    Tee-Object -FilePath "$logsDir\frontend.log"
```

- [ ] **Step 2: Verify the script syntax is valid**

Run:
```powershell
powershell -NoProfile -NonInteractive -Command "& { [System.Management.Automation.Language.Parser]::ParseFile('scripts/start-frontend.ps1', [ref]$null, [ref]$null) | Out-Null; 'syntax ok' }"
```
Expected output: `syntax ok`

- [ ] **Step 3: Commit**

```powershell
git add scripts/start-frontend.ps1
git commit -m "feat(dev): add start-frontend.ps1 with tee to frontend.log"
```

---

### Task 4: Update `.vscode/tasks.json`

**Files:**
- Modify: `.vscode/tasks.json`

- [ ] **Step 1: Replace tasks.json with the following content**

Replace the entire `.vscode/tasks.json` with:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Start Redis",
      "type": "shell",
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-NonInteractive",
        "-File",
        "${workspaceFolder}/scripts/start-redis.ps1"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "isBackground": true,
      "presentation": {
        "echo": true,
        "reveal": "always",
        "focus": false,
        "panel": "shared"
      },
      "problemMatcher": []
    },
    {
      "label": "Start Backend Dev",
      "type": "shell",
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-NonInteractive",
        "-File",
        "${workspaceFolder}/scripts/start-backend.ps1"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "isBackground": true,
      "presentation": {
        "echo": true,
        "reveal": "always",
        "focus": false,
        "panel": "shared"
      },
      "problemMatcher": []
    },
    {
      "label": "Start Frontend Dev",
      "type": "shell",
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-NonInteractive",
        "-File",
        "${workspaceFolder}/scripts/start-frontend.ps1"
      ],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "isBackground": true,
      "presentation": {
        "echo": true,
        "reveal": "always",
        "focus": false,
        "panel": "shared"
      },
      "problemMatcher": []
    },
    {
      "label": "Run All Dev (CRM & Backend)",
      "dependsOn": [
        "Start Redis",
        "Start Backend Dev",
        "Start Frontend Dev"
      ],
      "dependsOrder": "parallel",
      "presentation": {
        "echo": true,
        "reveal": "always",
        "focus": false,
        "panel": "shared"
      },
      "problemMatcher": []
    }
  ]
}
```

- [ ] **Step 2: Verify JSON is valid**

Run:
```powershell
Get-Content ".vscode/tasks.json" | ConvertFrom-Json | Out-Null; "json ok"
```
Expected output: `json ok`

- [ ] **Step 3: Commit**

```powershell
git add .vscode/tasks.json
git commit -m "feat(dev): refactor tasks.json — thin launchers calling ps1 scripts"
```

---

### Task 5: Remove `_setup_file_logging()` from `backend/app/main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Remove the `logging.handlers` import**

In `backend/app/main.py`, line 3, remove:
```python
import logging.handlers
```

The remaining imports at the top should be:
```python
import asyncio
import logging
import os
from contextlib import asynccontextmanager
```

- [ ] **Step 2: Remove `_LOG_FMT` and `_setup_file_logging()`**

Remove lines 20–51 (the `_LOG_FMT` variable and the full `_setup_file_logging()` function):

```python
_LOG_FMT = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")


def _setup_file_logging() -> None:
    """Add a RotatingFileHandler to all loggers when LOG_FILE env var is set.

    Called inside lifespan so it runs after uvicorn has configured its own
    handlers (uvicorn.access has propagate=False and needs its own handler).
    """
    log_file = os.environ.get("LOG_FILE")
    if not log_file:
        return

    log_dir = os.path.dirname(os.path.abspath(log_file))
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
        delay=False,
    )
    fh.setFormatter(_LOG_FMT)

    # uvicorn.error propagates to uvicorn (propagate=False), so "uvicorn"
    # already covers it — adding to both would double-write those entries.
    for name in ("", "uvicorn", "uvicorn.access"):
        lg = logging.getLogger(name)
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in lg.handlers):
            lg.addHandler(fh)
```

- [ ] **Step 3: Remove the `_setup_file_logging()` call from `lifespan()`**

In the `lifespan()` function, remove the call:
```python
    _setup_file_logging()
```

The `lifespan()` function should now start with:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=5, socket_timeout=5,
    )
```

- [ ] **Step 4: Verify `import os` is still needed**

Check that `os` is still used in `main.py` (it is used in `_setup_file_logging` which we removed). If `os` is not used elsewhere, remove `import os` as well.

Search: `grep -n "os\." backend/app/main.py` — if no output, remove `import os`.

- [ ] **Step 5: Verify the backend starts cleanly**

Run from the `backend/` directory:
```powershell
Set-Location backend
$env:PYTHONUNBUFFERED = "1"
& ..\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```
Expected: uvicorn starts without `ImportError` or `AttributeError`. Press Ctrl+C to stop.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/main.py
git commit -m "refactor(backend): remove _setup_file_logging — log mirroring now handled by Tee-Object in dev scripts"
```

---

### Task 6: Verify end-to-end log mirroring

**Files:** None (verification only)

- [ ] **Step 1: Verify `logs/` directory exists with `.gitkeep`**

Run:
```powershell
Test-Path "logs\.gitkeep"
```
Expected: `True`

- [ ] **Step 2: Test Redis script manually**

Run in a separate terminal:
```powershell
powershell -NoProfile -File scripts/start-redis.ps1
```
Expected: Terminal shows Redis container log lines AND `logs/redis.log` is populated with the same content:
```powershell
Get-Content logs/redis.log
```

- [ ] **Step 3: Test Backend script manually**

Run in a separate terminal:
```powershell
powershell -NoProfile -File scripts/start-backend.ps1
```
Expected: Terminal shows uvicorn startup AND `logs/backend.log` contains:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001 ...
```
Press Ctrl+C to stop.

- [ ] **Step 4: Test Frontend script manually**

Run in a separate terminal:
```powershell
powershell -NoProfile -File scripts/start-frontend.ps1
```
Expected: Terminal shows Next.js startup AND `logs/frontend.log` is populated. Press Ctrl+C to stop.

- [ ] **Step 5: Verify each run resets the log**

Run the backend script a second time. After it starts:
```powershell
Get-Content logs/backend.log | Select-Object -First 3
```
Expected: Log contains only entries from the current run (timestamp will be recent), not appended to the previous run.

- [ ] **Step 6: Final commit — spec and plan docs**

```powershell
git add docs/superpowers/specs/2026-05-22-realtime-log-mirroring-design.md
git add docs/superpowers/plans/2026-05-22-realtime-log-mirroring.md
git commit -m "docs: add spec and plan for real-time log mirroring"
```
