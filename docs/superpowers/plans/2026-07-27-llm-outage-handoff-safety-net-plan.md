# Plano — Rede de Segurança do Handoff durante Indisponibilidade do LLM

**Spec:** `docs/superpowers/specs/2026-07-27-llm-outage-handoff-safety-net-design.md`
**Branch:** `fix/llm-outage-handoff-safety-net`
**Base:** `63f8525`
**Data:** 2026-07-27

---

## Ordem de execução

As três fases são **independentes**. Qualquer uma pode ser abandonada sem afetar as outras.
A ordem abaixo é por impacto: a Fase 1 devolve ~28 minutos de tempo de resposta a cada lead,
a Fase 2 restaura o anteparo que teria salvo o Wilson, a Fase 3 melhora a qualidade do que
chega ao vendedor.

Cada fase é TDD: teste primeiro (vermelho), implementação (verde), suíte.

Todos os testes vivem em `backend/tests/test_llm_outage_handoff_safety_net_2026_07_27.py`.

---

## Fase 1 — Deadline do parking sensível à duração do apagão

### Passo 1.1 — Testes (vermelho)

Alvo: `parking._compute_deadline` — função pura, sem rede.

| Teste | Entrada | Esperado |
|---|---|---|
| `test_transient_curto_mantem_30min` | `reason="transient"`, `failure_count=0` | `parked_at + 30min` |
| `test_transient_abaixo_do_limiar_mantem_30min` | `failure_count=9` | `parked_at + 30min` |
| `test_transient_apagao_sustentado_encurta` | `failure_count=10` | `parked_at + 3min` |
| `test_transient_apagao_longo_encurta` | `failure_count=158` | `parked_at + 3min` |
| `test_budget_ignora_failure_count` | `reason="budget"`, `failure_count=999` | idêntico ao deadline de budget de hoje |
| `test_quota_ignora_failure_count` | `reason="quota"`, `failure_count=999` | idêntico ao deadline de quota de hoje |
| `test_knobs_por_env` | `LLM_PARK_OUTAGE_FAILURES=2`, `LLM_PARK_OUTAGE_MINUTES=1` | limiar e janela respeitam o env |
| `test_default_failure_count_preserva_comportamento` | chamada sem o parâmetro | `parked_at + 30min` |

O último é o teste de compatibilidade: garante que qualquer chamador que não passe a contagem
mantém exatamente o contrato de hoje.

### Passo 1.2 — Implementação

**`backend/app/buffer/parking.py`**

```python
def _outage_failures() -> int:      # LLM_PARK_OUTAGE_FAILURES, default 10
def _outage_minutes() -> int:       # LLM_PARK_OUTAGE_MINUTES, default 3
```

`_compute_deadline(reason, parked_at, failure_count: int = 0)` — no ramo `transient`, escolhe
entre `_park_max_minutes()` e `_outage_minutes()` conforme `failure_count >= _outage_failures()`.
Ramos `budget`/`quota` inalterados.

`park_turn(..., failure_count: int = 0)` — repassa a contagem para `_compute_deadline` e grava
o `failure_count` na entrada Redis (campo novo, para diagnóstico no drain; leitura tolerante a
entrada legada sem o campo).

**`backend/app/buffer/processor.py`** — `_handle_llm_down`:

`_count` passa a ser inicializado como `0` **antes** do `try` que chama `_record_llm_failure()`
(hoje ele só existe dentro do bloco; se o Redis falhar, o nome não é ligado). Depois é repassado:
`park_turn(conversation, lead, phone, inbound_text, reason=reason, failure_count=_count)`.

### Passo 1.3 — Verificação

```
cd backend && python -m pytest tests/test_llm_outage_handoff_safety_net_2026_07_27.py -q
cd backend && python -m pytest tests/ -k "park or llm_down or parking" -q
```

**Critério de saída:** os 8 testes verdes; nenhum teste existente de parking quebrado.

---

## Fase 2 — `handoff_rescue` imune ao stop `ai_disabled`

### Passo 2.1 — Testes (vermelho)

Alvo: helper puro `_stop_reason_applies(reason, job_type)`.

| Teste | Entrada | Esperado |
|---|---|---|
| `test_ai_disabled_nao_cancela_handoff_rescue` | `("ai_disabled", "handoff_rescue")` | `False` |
| `test_ai_disabled_cancela_cadencia_normal` | `("ai_disabled", "followup")` | `True` |
| `test_ai_disabled_cancela_lp_welcome` | `("ai_disabled", "lp_welcome")` | `True` |
| `test_opt_out_cancela_handoff_rescue` | `("opt_out", "handoff_rescue")` | `True` |
| `test_wrong_number_cancela_handoff_rescue` | `("wrong_number", "handoff_rescue")` | `True` |
| `test_blacklisted_cancela_handoff_rescue` | `("blacklisted", "handoff_rescue")` | `True` |
| `test_reason_none_nunca_aplica` | `(None, qualquer)` | `False` |

Mais um teste de regressão sobre `_lead_stop_reason`, que **não** deve mudar:
`ai_enabled=False` continua devolvendo `"ai_disabled"`.

### Passo 2.2 — Implementação

**`backend/app/follow_up/scheduler.py`**

Constante e helper ao lado de `_lead_stop_reason`:

```python
_STOP_REASON_EXEMPT_JOB_TYPES: dict[str, frozenset[str]] = {
    "ai_disabled": frozenset({"handoff_rescue"}),
}

def _stop_reason_applies(reason: str | None, job_type: str | None) -> bool: ...
```

No laço de `process_due_followups` (bloco do backstop, hoje `:598`), trocar
`if stop_reason:` por `if _stop_reason_applies(stop_reason, job.get("job_type")):`.

Comentário no ponto da exceção explicando a circularidade (o handoff desliga a IA e é ele quem
agenda o resgate), com referência ao caso Wilson Demuth 26/07.

### Passo 2.3 — Verificação

```
cd backend && python -m pytest tests/test_llm_outage_handoff_safety_net_2026_07_27.py -q
cd backend && python -m pytest tests/test_stopped_lead_backstop_2026_07_15.py -q
cd backend && python -m pytest tests/ -k "followup or scheduler or handoff" -q
```

`test_stopped_lead_backstop_2026_07_15.py` é o teste do caso que motivou o backstop — **precisa
continuar verde**. Se ele cobrir `handoff_rescue` com `ai_disabled` esperando cancelamento, o
teste codifica o bug e deve ser atualizado com justificativa registrada no relatório.

**Critério de saída:** 8 testes novos verdes, backstop original preservado.

---

## Fase 3 — Dossiê determinístico quando o resumo falha

### Passo 3.1 — Testes (vermelho)

Alvo: função pura `summary._fallback_briefing(history, lead, motivo, handoff_at)`.

| Teste | Esperado |
|---|---|
| `test_briefing_contem_dados_do_lead` | nome, empresa e segmento aparecem |
| `test_briefing_contem_motivo_e_data` | motivo e `handoff_at` aparecem |
| `test_briefing_inclui_mensagens_do_lead` | conteúdo das mensagens `role="user"` aparece |
| `test_briefing_exclui_falas_da_valeria` | conteúdo de `role="assistant"` **não** aparece |
| `test_briefing_limita_a_6_mensagens` | com 10 inbounds, só as 6 últimas |
| `test_briefing_trunca_mensagem_longa` | mensagem de 1000 chars truncada em 280 + reticências |
| `test_briefing_sem_historico_nao_quebra` | history vazio → string válida, sem exceção |
| `test_briefing_campos_ausentes` | lead sem nome/empresa → "Não informado", sem `None` no texto |
| `test_briefing_mantem_cabecalho` | começa com `## NOVO LEAD QUALIFICADO PELA VALÉRIA` |
| `test_briefing_nunca_diz_erro_ao_gerar` | string `Erro ao gerar resumo` ausente |

Mais dois testes de integração com `generate_qualification_summary` (mock de `generate`):

- `test_excecao_do_llm_cai_no_briefing` — `generate` levanta → resultado é o briefing.
- `test_resposta_vazia_cai_no_briefing` — `generate` devolve texto vazio → resultado é o briefing.
- `test_sucesso_do_llm_inalterado` — `generate` devolve texto → resultado é exatamente esse texto.

### Passo 3.2 — Implementação

**`backend/app/agent/summary.py`**

Constantes `_FALLBACK_MAX_MSGS = 6`, `_FALLBACK_MAX_CHARS = 280`.

`_fallback_briefing(...)` pura, e os dois ramos de falha de `generate_qualification_summary`
(`except` e `if not result.text`) passam a chamá-la. O ramo de sucesso fica inalterado.

O ramo `if not history` (`:79-80`) fica como está — sem histórico não há briefing a montar.

### Passo 3.3 — Verificação

```
cd backend && python -m pytest tests/test_llm_outage_handoff_safety_net_2026_07_27.py -q
cd backend && python -m pytest tests/ -k "summary or handoff or dossie" -q
```

**Critério de saída:** 13 testes verdes; nenhum teste de summary existente quebrado.

---

## Validação final

```
cd backend && python -m pytest -q
```

Suíte completa verde. Registrar no relatório: contagem de testes antes/depois e qualquer teste
existente que tenha precisado mudar (com o porquê).

**Sem push para `master` sem autorização explícita do usuário** (CLAUDE.md §1, passo 4).

---

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Janela de 3 min curta demais para um blip de 2-3 min que já acumulou 10 falhas em rajada | O limiar conta falhas **consecutivas sem nenhum sucesso**; o drain zera no 1º sucesso. Knob `LLM_PARK_OUTAGE_FAILURES` permite subir sem deploy. |
| Isentar `handoff_rescue` reabre a porta para spam ao vendedor | A isenção é **só** de `ai_disabled`. `opt_out`/`blacklist`/`wrong_number` seguem cancelando, e o handler dedicado já checa se o lead contatou o João nos últimos 15 min. |
| Briefing determinístico expõe conteúdo cru do lead ao vendedor | É o mesmo conteúdo que o vendedor veria abrindo a conversa no CRM. Sem dado novo, só antecipado. |
| Conflito com a branch `perf/gemini-context-caching` | Zero interseção de arquivos (ver spec, seção Escopo). Ambos partem de `63f8525`. |

---

## Rollback

- Fase 1: `LLM_PARK_OUTAGE_FAILURES=999999` no ambiente — volta à janela de 30 min sem deploy.
- Fase 2: `git revert` do commit de `scheduler.py`.
- Fase 3: aditiva no ramo de falha; caminho feliz intocado.
