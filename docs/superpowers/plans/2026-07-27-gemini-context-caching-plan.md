# Plano — Context Caching e Enxugamento do Prefixo

**Spec:** `docs/superpowers/specs/2026-07-27-gemini-context-caching-design.md`
**Branch:** `perf/gemini-context-caching`
**Data:** 2026-07-27

---

## Ordem de execução

As fases são independentes por construção. Se a Fase 2 for abandonada (risco de `tools` +
`cached_content`), as Fases 1 e 3 continuam entregando valor.

---

> **RESULTADO DA EXECUÇÃO (27/07):** Fase 1 **abandonada** após a leitura integral do
> `BASE_STATIC` — o prompt não tem a gordura que a spec presumia (quase toda regra cita o
> incidente real que a originou; duplicações somam 3-6%, não 25-30%). Ver a seção "Fase 1" da
> spec para a evidência e o caminho alternativo recomendado. Fases 2 e 3: **entregues**, suíte
> completa verde (2.665 passaram, 3 skipped). `BASE_STATIC` ficou intocado.

## Fase 1 — Enxugar `BASE_STATIC` (NÃO EXECUTADA — ver nota acima)

**Arquivo:** `backend/app/agent/prompts/base.py`

### Passo 1.1 — Inventário de regras (antes de tocar em qualquer texto)

Ler `<constraints>` (offset 4.356–49.272) e `<instructions>` (49.288–80.584) na íntegra e
produzir uma lista numerada de regras de comportamento. Cada entrada:

```
R##  | seção origem | regra em uma linha | duplicada em?
```

Gravar o inventário em `docs/superpowers/specs/2026-07-27-base-static-inventario-regras.md`.
Este artefato é o contrato de não-perda — sem ele a Fase 1 não pode ser validada.

### Passo 1.2 — Reescrita densa

Reescrever as duas seções mantendo:
- A hierarquia XML (`<role>`, `<constraints>`, `<instructions>`, `<examples>`).
- `BASE_STATIC` como string literal **estática** (nunca f-string — qualquer byte volátil
  quebra o prefixo de cache).
- Toda regra do inventário, verificada 1:1.

Consolidações previstas:
- Proibição de vazar código de ferramenta: hoje repetida em `<constraints>` e `<instructions>`
  → uma única declaração no bloco de prioridade máxima.
- Regras de verbosidade/formato dispersas → um bloco único.
- `<examples>` que apenas reencenam regras já enunciadas → remover o exemplo, manter a regra.

### Passo 1.3 — Verificação

```
python -c "import ast; ..."   # medir chars antes/depois
cd backend && python -m pytest tests/test_base_prompt.py tests/test_prompts_frente_c_2026_07_03.py \
  tests/test_outbound_postura_hunter_2026_07_13.py tests/test_outbound_pedido_direto_2026_07_15.py \
  tests/test_finops_p0_p1_2026_07_12.py -q
```

Depois a suíte completa. Registrar a redução obtida no inventário.

**Critério de saída:** ≥25% de redução em chars, inventário 100% coberto, suíte verde.

---

## Fase 2 — Cache explícito gerenciado

### Passo 2.1 — Módulo novo

**Arquivo:** `backend/app/agent/prompt_cache.py`

```python
def cache_enabled() -> bool          # GEMINI_EXPLICIT_CACHE, default "off"
def _ttl_seconds() -> int            # GEMINI_CACHE_TTL_SECONDS, default 3600
def _min_chars() -> int              # piso ~8192 chars (~2048 tokens da API)
async def get_or_create(model, static_prefix) -> str | None
def invalidate(model, static_prefix) -> None
```

Contrato:
- Chave `sha256(model + "\x00" + static_prefix)[:16]`.
- Índice em memória `{key: (cache_name, expires_at_monotonic)}`; entrada vencida é descartada
  e recriada.
- Renova ao usar (estende o TTL enquanto houver tráfego); sem tráfego, expira sozinha no
  Google e nada é cobrado.
- **Fail-open absoluto:** todo caminho de erro retorna `None` e loga em `warning`. Nunca levanta.
- Abaixo do piso de chars, retorna `None` sem chamar a API.

### Passo 2.2 — Integração

**Arquivo:** `backend/app/agent/gemini_client.py`

`generate()` ganha o parâmetro keyword-only `cacheable_prefix: str | None = None`
(a assinatura é fechada por contrato do módulo — adicionar parâmetro é mudança deliberada,
documentada no docstring).

Quando `cache_enabled()` e há prefixo cacheável:
1. `name = await prompt_cache.get_or_create(model, cacheable_prefix)`
2. Se `name`: montar `GenerateContentConfig(cached_content=name, ...)` **sem**
   `system_instruction`.
3. Se `None`: caminho atual, inalterado.

Em `404`/`INVALID_ARGUMENT` referente ao cache: `invalidate()` + uma retentativa pelo caminho
sem cache (o cache pode ter expirado no servidor entre o índice local e a chamada).

### Passo 2.3 — Separação estático/volátil no orquestrador

**Arquivo:** `backend/app/agent/orchestrator.py`

`build_system_prompt` passa a expor as duas metades sem mudar o resultado concatenado:

```python
def build_system_prompt_parts(...) -> tuple[str, str]:   # (estático, volátil)
def build_system_prompt(...) -> str:                     # "\n\n".join(parts) — comportamento atual
```

Com a flag **off**, `run_agent` continua chamando `build_system_prompt` e nada muda.

### Passo 2.4 — Testes

**Arquivo:** `backend/tests/test_prompt_cache_2026_07_27.py`

- Flag off ⇒ `get_or_create` nem chama a API.
- Prefixo curto ⇒ `None` sem chamar a API.
- Exceção na criação ⇒ `None` (fail-open), turno gerado normalmente.
- Chave estável: mesmo prefixo ⇒ mesma chave; um byte diferente ⇒ chave diferente.
- Entrada expirada ⇒ recriação.
- `build_system_prompt_parts` concatenado é **idêntico** ao `build_system_prompt` atual.

### Passo 2.5 — Validação em dev (obrigatória antes de ligar)

Com `GEMINI_EXPLICIT_CACHE=on` **apenas** em `.env.local`, exercitar um turno real com tools
via `https://dev.canastrainteligencia.com` e confirmar:
- A API aceita `tools` junto com `cached_content`.
- `usage_metadata.cached_content_token_count` reflete o prefixo.

Se a API rejeitar: **encerrar a Fase 2**, manter a flag off, registrar o resultado na spec.
Fases 1 e 3 seguem válidas.

---

## Fase 3 — Observabilidade preventiva

**Arquivos:** `backend/app/agent/orchestrator.py` (log por turno), `backend/app/agent/budget_guard.py`

- Logar por turno: tokens de entrada, `cached_content_token_count` e hit %.
- Alerta quando o gasto mensal projetado cruzar um limiar configurável
  (`LLM_MONTHLY_ALERT_USD`), disparando **antes** do teto do provedor.

**Teste:** `backend/tests/test_budget_monthly_alert_2026_07_27.py` — projeção cruza o limiar
⇒ alerta dispara uma vez; abaixo do limiar ⇒ silêncio.

---

## Validação final

```
cd backend && python -m pytest -q
```

Suíte completa verde. Sem push para `master` sem autorização explícita do usuário
(CLAUDE.md §1, passo 4).

---

## Rollback

- Fase 1: `git revert` do commit de `base.py`.
- Fase 2: remover `GEMINI_EXPLICIT_CACHE` do ambiente — o código volta ao caminho atual sem
  deploy.
- Fase 3: aditiva (log + alerta), sem efeito no caminho do turno.
