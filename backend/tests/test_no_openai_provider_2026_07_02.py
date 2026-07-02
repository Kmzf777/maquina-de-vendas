"""Guard test: prevents re-introduction of OpenAI-as-a-PROVIDER code.

Context: Valeria's LLM stack is Gemini-only. The `openai` SDK (`AsyncOpenAI`) is still used
as pure HTTP transport against Gemini's OpenAI-compatible endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`). That usage is intentional and
must keep working. This test only forbids the specific substrings that indicate someone wired
up OpenAI (the company) as an actual model/provider again.

Explicitly PERMITTED (must NOT be flagged by this test):
- `import openai` / `from openai import ...`
- `AsyncOpenAI` (the SDK client class, used as transport for the Gemini-compat endpoint)
- the substring "openai" inside the URL path `/v1beta/openai/`
- comments mentioning "OpenAI-compat" or the standalone word "Whisper" to document the
  limitation/shape of the Gemini endpoint

Forbidden markers (case-sensitive except where noted) and why they're specific:
- "openai_api_key"      -> config/env key naming implies a real OpenAI provider config
- "_get_openai"          -> a provider factory/getter function for OpenAI
- "whisper-1"            -> literal OpenAI Whisper model id (not the bare word "Whisper")
- "audio.transcriptions" -> OpenAI SDK call shape `client.audio.transcriptions...`
                             (with a dot; NOT the `/audio/transcriptions` REST path used in
                             comments describing the Gemini-compat endpoint)
- '"gpt-' and "'gpt-"    -> literal GPT model id string constants
"""

from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
# Scan both the runtime package and the operational scripts (seed_valeria_profile, etc.),
# so a reintroduced `model="gpt-..."` in a seed script is caught too.
SCAN_DIRS = [_BACKEND_DIR / "app", _BACKEND_DIR / "scripts"]

FORBIDDEN_MARKERS = [
    "openai_api_key",
    "_get_openai",
    "whisper-1",
    "audio.transcriptions",
    '"gpt-',
    "'gpt-",
]


def test_no_openai_provider_markers_in_app():
    violations = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.is_dir():
            continue
        for path in sorted(scan_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN_MARKERS:
                if marker in text:
                    violations.append(f"{path}: found forbidden marker {marker!r}")

    assert not violations, (
        "Found OpenAI-provider markers that should not be reintroduced:\n"
        + "\n".join(violations)
    )
