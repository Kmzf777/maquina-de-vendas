"""Guard test: enforces the 100%-native Google/Gemini LLM stack.

Context (updated 2026-07-02): a migração para o SDK nativo `google-genai` ERRADICOU o
transporte via SDK da OpenAI. Não há mais `import openai`, `AsyncOpenAI`, nem tráfego para
o endpoint de compatibilidade — todo o LLM passa por `app/agent/gemini_native.py`
(`google.genai.Client(...).aio.models.generate_content(...)`). Este guard trava tanto a
volta da OpenAI-como-PROVEDOR quanto a volta do SDK da OpenAI como transporte.

Forbidden markers (case-sensitive except where noted) and why they're specific:
Provedor OpenAI (modelo/infra/config real da empresa):
- "openai_api_key"      -> config/env key naming implies a real OpenAI provider config
- "_get_openai"          -> a provider factory/getter function for OpenAI
- "whisper-1"            -> literal OpenAI Whisper model id (not the bare word "Whisper")
- "audio.transcriptions" -> OpenAI SDK call shape `client.audio.transcriptions...`
                             (with a dot; NOT the `/audio/transcriptions` REST path used in
                             comments describing the native Gemini endpoint)
- '"gpt-' and "'gpt-"    -> literal GPT model id string constants
Transporte OpenAI (o SDK/pacote openai, agora banido — usamos só google-genai):
- "import openai"        -> import do pacote openai (regex, capta "import openai" isolado)
- "from openai"          -> import de símbolos do pacote openai
- "AsyncOpenAI"          -> a classe-cliente do SDK openai
- "v1beta/openai"        -> o path do endpoint de compatibilidade (transporte legado)

Menções em PROSA à palavra "OpenAI" (ex.: docstring explicando o que foi substituído, ou o
param `openai_tools` que descreve o SHAPE do schema) são permitidas — só os padrões acima,
que denotam código de transporte/provedor real, são proibidos.
"""

import re
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
    "AsyncOpenAI",
    "v1beta/openai",
]

# Import statements do pacote openai — regex para não capturar prosa que contenha as palavras.
FORBIDDEN_PATTERNS = [
    re.compile(r"^\s*import\s+openai\b", re.MULTILINE),
    re.compile(r"^\s*from\s+openai\b", re.MULTILINE),
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
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    violations.append(f"{path}: found forbidden import {pattern.pattern!r}")

    assert not violations, (
        "Found OpenAI provider/transport markers that should not be reintroduced:\n"
        + "\n".join(violations)
    )
