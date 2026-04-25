# Rehearsal Runner — Paralelização com Telefones Isolados

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o loop sequencial do `rehearsal_runner.py` por execução paralela com `asyncio.gather`, usando telefones únicos por índice de arquétipo para garantir isolamento total no Supabase.

**Architecture:** Três mudanças cirúrgicas em sequência: (1) remover `write_run_summary` de `logger.py` e seus dois testes; (2) fazer `_run_archetype` receber `phone: str` como parâmetro explícito, eliminando a global `REHEARSAL_PHONE` e padronizando os prefixos de log; (3) adicionar `_run_with_jitter` como wrapper fino e substituir o loop por `asyncio.gather(*tasks, return_exceptions=True)`.

**Tech Stack:** Python 3.10+, asyncio, httpx, google-generativeai (Gemini SDK)

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `backend/scripts/rehearsal/logger.py` | Remover função `write_run_summary` (linhas 57–88) |
| `backend/tests/test_rehearsal_logger.py` | Remover dois testes de `write_run_summary`; corrigir slug no teste remanescente |
| `backend/tests/test_rehearsal_runner_phones.py` | **Criar** — testa a função de geração de telefones |
| `backend/scripts/rehearsal_runner.py` | Remover `REHEARSAL_PHONE` global; parametrizar phone; adicionar `_run_with_jitter`; paralelizar `main()` |

---

## Task 1: Remover `write_run_summary` e limpar os testes do logger

**Files:**
- Modify: `backend/scripts/rehearsal/logger.py`
- Modify: `backend/tests/test_rehearsal_logger.py`

- [ ] **Step 1: Remover a função `write_run_summary` de `logger.py`**

Apague as linhas 57–88 do arquivo `backend/scripts/rehearsal/logger.py` (a função `write_run_summary` completa, do `def write_run_summary` até o `}` do `run.json`). O arquivo deve terminar com o `return archetype_dir` da função `write_archetype_artifacts`.

O arquivo resultante deve ter apenas as funções `_render_transcript` e `write_archetype_artifacts`.

- [ ] **Step 2: Limpar `test_rehearsal_logger.py`**

No arquivo `backend/tests/test_rehearsal_logger.py`:

1. **Apague** as funções `test_write_run_summary` (linhas 47–70) e `test_run_summary_shows_forbid_violations` (linhas 73–102).

2. **Corrija** a asserção no teste remanescente — o slug de `T1` é `"b2b-revenda"` e o id é `"T1"`, mas o teste usa a string antiga `"R1-representante-portfolio"`. Corrija a linha:

```python
# antes
assert archetype_dir.name == "R1-representante-portfolio"
# depois
assert archetype_dir.name == "T1-b2b-revenda"
```

O arquivo final deve conter apenas `test_write_artifacts_creates_expected_files`, com a asserção corrigida.

- [ ] **Step 3: Verificar que o único teste restante passa**

```bash
cd backend && python -m pytest tests/test_rehearsal_logger.py -v
```

Esperado:
```
PASSED tests/test_rehearsal_logger.py::test_write_artifacts_creates_expected_files
1 passed
```

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/rehearsal/logger.py backend/tests/test_rehearsal_logger.py
git commit -m "refactor(rehearsal): remove write_run_summary from logger and tests"
```

---

## Task 2: Parametrizar phone em `_run_archetype`, remover `REHEARSAL_PHONE`, adicionar prefixos de log

**Files:**
- Create: `backend/tests/test_rehearsal_runner_phones.py`
- Modify: `backend/scripts/rehearsal_runner.py`

- [ ] **Step 1: Criar o teste de geração de telefones**

Crie o arquivo `backend/tests/test_rehearsal_runner_phones.py` com o conteúdo:

```python
"""Testa a lógica de geração de telefones únicos por índice de arquétipo."""


def _phone_for_index(idx: int) -> str:
    return f"5511{(idx + 1):08d}"


def test_phone_index_zero():
    assert _phone_for_index(0) == "551100000001"


def test_phone_index_five():
    assert _phone_for_index(5) == "551100000006"


def test_phones_are_unique():
    phones = [_phone_for_index(i) for i in range(6)]
    assert len(set(phones)) == 6


def test_phones_are_strings():
    assert isinstance(_phone_for_index(0), str)
```

- [ ] **Step 2: Rodar o teste para confirmar que passa**

```bash
cd backend && python -m pytest tests/test_rehearsal_runner_phones.py -v
```

Esperado:
```
PASSED tests/test_rehearsal_runner_phones.py::test_phone_index_zero
PASSED tests/test_rehearsal_runner_phones.py::test_phone_index_five
PASSED tests/test_rehearsal_runner_phones.py::test_phones_are_unique
PASSED tests/test_rehearsal_runner_phones.py::test_phones_are_strings
4 passed
```

- [ ] **Step 3: Remover `REHEARSAL_PHONE` e `import subprocess` de `rehearsal_runner.py`**

Em `backend/scripts/rehearsal_runner.py`:

Remova a linha:
```python
REHEARSAL_PHONE = os.environ.get("REHEARSAL_PHONE", "").strip()
```

Remova a linha:
```python
import subprocess
```

Remova a função `_git_sha()` completa (linhas 65–69):
```python
def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"
```

- [ ] **Step 4: Adicionar parâmetro `phone: str` à assinatura de `_run_archetype`**

Altere a assinatura da função de:
```python
async def _run_archetype(
    archetype: Archetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
```

para:
```python
async def _run_archetype(
    archetype: Archetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
    phone: str,
) -> dict:
```

- [ ] **Step 5: Substituir todas as ocorrências de `REHEARSAL_PHONE` dentro de `_run_archetype` por `phone`**

Dentro do corpo de `_run_archetype`, substitua as 5 ocorrências de `REHEARSAL_PHONE` por `phone`:

1. `supabase_io.wipe_lead(REHEARSAL_PHONE)` → `supabase_io.wipe_lead(phone)`
2. `await supabase_io.wipe_redis_buffer(REHEARSAL_PHONE, redis)` → `await supabase_io.wipe_redis_buffer(phone, redis)`
3. `await _send_user_message(client, REHEARSAL_PHONE, archetype.first_message)` → `await _send_user_message(client, phone, archetype.first_message)`
4. `lead = supabase_io.get_lead_by_phone(REHEARSAL_PHONE)` → `lead = supabase_io.get_lead_by_phone(phone)`
5. `await _send_user_message(client, REHEARSAL_PHONE, next_user_msg)` → `await _send_user_message(client, phone, next_user_msg)`

- [ ] **Step 6: Padronizar todos os `log.*` dentro de `_run_archetype` com prefixo `[{archetype.id}]`**

Substitua todas as chamadas de log dentro de `_run_archetype` pelas versões abaixo (mantenha a mesma lógica, apenas padronize o prefixo):

```python
log.info(f"[{archetype.id}] Iniciando ({archetype.slug}) phone={phone}")
```

```python
log.error(f"[{archetype.id}] Lead nao criado em {TURN_TIMEOUT}s — abortando")
```

```python
log.warning(f"[{archetype.id}] Turno {turns} sem resposta (timeout #{consecutive_timeouts})")
```

```python
log.info(f"[{archetype.id}] Turno {turns + 1} — Lead: {next_user_msg[:80]}")
```

```python
log.error(f"[{archetype.id}] Gemini falhou — {e}")
```

```python
log.warning(f"[{archetype.id}] Gemini retornou vazio — encerrando")
```

```python
log.info(f"[{archetype.id}] Finalizado: status={verification['status']} turns={turns} by={terminated_by}")
```

- [ ] **Step 7: Atualizar `main()` — remover validação de `REHEARSAL_PHONE` e `run_meta`**

Remova o bloco de validação:
```python
if not REHEARSAL_PHONE:
    raise SystemExit("REHEARSAL_PHONE nao definido em .env.local")
```

Remova as variáveis `started_at` e `run_meta` (e o `_now_iso()` call que as gerava no topo de `main()`).

Remova também as duas chamadas `rlogger.write_run_summary(...)` que existiam dentro e após o loop sequencial.

**Substitua temporariamente** o loop `for archetype in archetypes:` por uma versão que usa o novo parâmetro `phone` com valor fixo (será substituída definitivamente na Task 3):

```python
verifications: list[dict] = []
async with httpx.AsyncClient() as client:
    await _health_check(client)
    for idx, archetype in enumerate(archetypes):
        phone = f"5511{(idx + 1):08d}"
        try:
            v = await _run_archetype(archetype, client, redis, run_dir, phone=phone)
        except Exception as e:
            log.exception(f"[{archetype.id}] Erro catastrofico")
            v = {
                "archetype_id": archetype.id,
                "archetype_slug": archetype.slug,
                "status": "error",
                "error": str(e),
                "turns_count": 0,
                "terminated_by": "crash",
                "hard_checks": [],
                "soft_check": {},
                "stages_visited": [],
            }
        verifications.append(v)
```

- [ ] **Step 8: Rodar a suíte de testes de rehearsal**

```bash
cd backend && python -m pytest tests/test_rehearsal_runner_phones.py tests/test_rehearsal_logger.py tests/test_rehearsal_verifier.py tests/test_rehearsal_forbids_integration.py -v
```

Esperado: todos passam.

- [ ] **Step 9: Commit**

```bash
git add backend/scripts/rehearsal_runner.py backend/tests/test_rehearsal_runner_phones.py
git commit -m "refactor(rehearsal): parametrize phone per archetype, remove REHEARSAL_PHONE global"
```

---

## Task 3: Adicionar `_run_with_jitter` e paralelizar `main()` com `asyncio.gather`

**Files:**
- Modify: `backend/scripts/rehearsal_runner.py`

- [ ] **Step 1: Adicionar a função `_run_with_jitter` em `rehearsal_runner.py`**

Logo acima da função `main()`, adicione:

```python
async def _run_with_jitter(
    idx: int,
    archetype: Archetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
    phone = f"5511{(idx + 1):08d}"
    log.info(f"[{archetype.id}] Agendado — phone={phone} jitter={idx * 2.0}s")
    await asyncio.sleep(idx * 2.0)
    return await _run_archetype(archetype, client, redis, run_dir, phone)
```

- [ ] **Step 2: Substituir o loop sequencial por `asyncio.gather` em `main()`**

Dentro do bloco `async with httpx.AsyncClient() as client:`, substitua o loop `for idx, archetype in enumerate(archetypes):` pelo seguinte:

```python
        await _health_check(client)
        tasks = [
            _run_with_jitter(idx, archetype, client, redis, run_dir)
            for idx, archetype in enumerate(archetypes)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

verifications: list[dict] = []
for archetype, result in zip(archetypes, raw_results):
    if isinstance(result, Exception):
        log.exception(f"[{archetype.id}] Erro catastrofico", exc_info=result)
        verifications.append({
            "archetype_id": archetype.id,
            "archetype_slug": archetype.slug,
            "status": "error",
            "error": str(result),
            "turns_count": 0,
            "terminated_by": "crash",
            "hard_checks": [],
            "soft_check": {},
            "stages_visited": [],
        })
    else:
        verifications.append(result)
```

**Atenção ao indenting:** o bloco `for archetype, result in zip(...)` deve ficar **fora** do `async with httpx.AsyncClient()` (mesmo nível que `await redis.close()`).

- [ ] **Step 3: Verificar o estado final de `main()`**

Após as alterações, `main()` deve ter esta estrutura:

```python
async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY nao definido em .env.local")

    only = os.environ.get("REHEARSAL_ONLY")
    archetypes = [a for a in ALL_ARCHETYPES if (not only or a.id == only)]
    if not archetypes:
        raise SystemExit(f"Nenhum arquetipo encontrado com REHEARSAL_ONLY={only}")

    run_ts = _utc_ts_path_component()
    run_dir = OUTPUT_ROOT / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with httpx.AsyncClient() as client:
        await _health_check(client)
        tasks = [
            _run_with_jitter(idx, archetype, client, redis, run_dir)
            for idx, archetype in enumerate(archetypes)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    verifications: list[dict] = []
    for archetype, result in zip(archetypes, raw_results):
        if isinstance(result, Exception):
            log.exception(f"[{archetype.id}] Erro catastrofico", exc_info=result)
            verifications.append({
                "archetype_id": archetype.id,
                "archetype_slug": archetype.slug,
                "status": "error",
                "error": str(result),
                "turns_count": 0,
                "terminated_by": "crash",
                "hard_checks": [],
                "soft_check": {},
                "stages_visited": [],
            })
        else:
            verifications.append(result)

    await redis.close()

    log.info(f"Run completo. Artefatos em: {run_dir}")
    any_fail = any(v.get("status") != "passed" for v in verifications)
    sys.exit(1 if any_fail else 0)
```

- [ ] **Step 4: Rodar a suíte de testes completa de rehearsal**

```bash
cd backend && python -m pytest tests/test_rehearsal_runner_phones.py tests/test_rehearsal_logger.py tests/test_rehearsal_verifier.py tests/test_rehearsal_forbids_integration.py -v
```

Esperado: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rehearsal_runner.py
git commit -m "feat(rehearsal): parallelize archetypes with asyncio.gather and jitter per index"
```

---

## Notas de implementação

- **Isolamento Redis**: cada arquétipo usa chaves Redis com seu próprio telefone (`buffer:551100000001`, `buffer:551100000002`…). Zero risco de conflito.
- **`httpx.AsyncClient` compartilhado**: seguro para uso concorrente — o cliente gerencia um pool de conexões internamente.
- **`return_exceptions=True`**: um crash em T3 não cancela T1, T2, T4… Os outros continuam normalmente.
- **`FINAL_STAGES`** (dict com `"R1"–"R5"` no topo do runner): dead code preexistente — fora do escopo, não toque.
- **Modo `REHEARSAL_ONLY`**: continua funcionando — `enumerate(archetypes)` com 1 elemento usa `idx=0`, phone = `551100000001`, jitter = `0.0s`.
