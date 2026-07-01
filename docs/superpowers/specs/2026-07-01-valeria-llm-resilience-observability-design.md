# Spec — Resiliência e Observabilidade da Valéria contra Queda de LLM

- **Data:** 2026-07-01
- **Status:** Aprovado (design)
- **Origem:** Investigação forense do atendimento `5564984794946` (lead Welita)

---

## 1. Contexto e causa raiz (fundamentado em dados de produção)

### Sintoma confirmado
- Última chamada LLM bem-sucedida (`token_usage`): **2026-07-01 18:02:12 UTC**. Depois disso, **zero** chamadas ao Gemini em toda a base.
- Última resposta real da Valéria (persona `valeria_*`): **18:02:27 UTC**.
- Respostas por hora: 17h=40, 18h=21, **19h=0, 20h=0, 21h=0** — seca total.
- Lead **Welita (`5564984794946`)**, 20:41 UTC: inbound salvo → `mark_read` (20:41:13) → `typing_on` (20:41:16 e 20:41:27) → **nenhum envio, nenhuma mensagem de assistente, nenhum erro logado, zero `token_usage`**.
- `system_alerts` **vazio** no período: ninguém foi avisado do apagão.

### Cadeia de causa (confirmada no código)
1. Toda chamada ao Gemini falha desde 18:02.
2. `_create_with_retry` (`backend/app/agent/orchestrator.py:375`) só retenta **erros de conexão** (`APIConnectionError`, `APITimeoutError`, `httpx.TransportError`). Qualquer erro de status HTTP (429 quota/rate-limit, 5xx) é **relançado imediatamente**.
3. A exceção propaga para fora de `run_agent` → o processor (`backend/app/buffer/processor.py:820-843`) tenta 3× com 5s de backoff (≈11s de pulsos "digitando", batendo com o gap 20:41:16→20:41:27) → `[AGENT FAILED]` → `_update_last_msg` + `return` **silencioso**.
4. O lead é fantasmado, sem fallback, sem handoff, sem alerta.

### Causa imediata provável
Esgotamento de **quota/rate-limit do Gemini** (`gemini-2.5-flash`, erro 429) por volta de 18:02 UTC — o corte seco e total é a assinatura clássica. O deploy da série BSUID do mesmo dia **não tocou** o caminho do LLM (cliente, modelo, tools, mensagens) e não é a causa. A causa exata (429 vs. outro) não é 100% confirmável sem os logs do Docker Swarm, indisponíveis nesta investigação; o **defeito estrutural** — falha silenciosa sem fallback nem alerta — é confirmado no código e é o alvo desta spec.

---

## 2. Objetivo

Garantir que **nenhum lead seja fantasmado** quando o LLM cai, e tornar o apagão **visível** para o operador. Escopo restrito a resiliência de LLM; sem novos recursos, refatorações ou abstrações fora disso.

---

## 3. Arquitetura (3 componentes isolados)

### Componente 1 — Endurecer o retry do LLM
**Arquivo:** `backend/app/agent/orchestrator.py` (`_create_with_retry`, linha ~375)

- Além dos erros de conexão já tratados, retentar erros HTTP **transitórios** do Gemini:
  - **429** (`openai.RateLimitError`) — rate-limit/quota, honrando o header `Retry-After` quando presente.
  - **5xx** (`openai.InternalServerError` e demais `openai.APIStatusError` com `status_code >= 500`).
- Backoff exponencial **limitado** (reutiliza `_LLM_RETRY_ATTEMPTS=3` / `_LLM_RETRY_DELAY=2`; delay = `_LLM_RETRY_DELAY * 2**(attempt-1)`, respeitando `Retry-After` quando maior).
- Erros **não-retentáveis** (400 `BadRequestError`, 401 `AuthenticationError`, demais 4xx) continuam **relançando imediatamente**, sem alteração.
- Após **esgotar** as tentativas em erro retentável de indisponibilidade (conexão/429/5xx), lançar uma exceção **tipada** nova `LLMUnavailableError(Exception)` (definida em `orchestrator.py`), em vez de propagar o erro cru. Isso permite ao processor distinguir "LLM fora" de um bug qualquer.

**Contrato:** `_create_with_retry` retorna a resposta em sucesso; lança `LLMUnavailableError` quando o LLM está persistentemente indisponível; relança o erro original para falhas não-retentáveis (4xx).

### Componente 2 — Matar a falha silenciosa (fallback com handoff)
**Arquivo:** `backend/app/buffer/processor.py` (ramo `[AGENT FAILED]`, linha ~836-843)

- Hoje: `_update_last_msg` + `return` mudo.
- Novo: quando a exceção capturada for `LLMUnavailableError` (LLM fora), antes do `return`, acionar o handoff humano reutilizando a tool existente:
  ```python
  await execute_tool(
      "encaminhar_humano",
      {"vendedor": "Joao Bras",
       "motivo": "IA temporariamente indisponível — atendimento encaminhado ao humano"},
      lead_id=lead["id"], phone=phone, conversation_id=conversation["id"],
  )
  ```
- `encaminhar_humano` (`backend/app/agent/tools.py:681`) já executa, de forma **fail-soft com LLM fora**:
  - Envia a despedida + **o cartão de contato do João ao lead** (`provider.send_contact(..., contact_name=_SUPERVISOR_NAME, contact_phone=_SUPERVISOR_PHONE)`, `tools.py:793-802`) — este é o "disparo do número do João para o lead".
  - Desativa `ai_enabled`, cria o deal do vendedor, cancela follow-ups, agenda o rescue.
  - O resumo de qualificação (que usaria o LLM) já cai na **nota estática de transbordo** quando falha (`tools.py:758-768`).
- Envolver a chamada em `try/except` fail-soft (uma falha no handoff nunca pode escalar); manter o `_update_last_msg` + `return` ao final.
- **Idempotência:** o gate `lead.ai_enabled=false` (`processor.py:683`) faz turnos seguintes do mesmo lead saírem **antes** de reenviar o card; a dedup de despedida (`_despedida_ja_enviada`, `tools.py:779`) é rede adicional.

### Componente 3 — Observabilidade (`system_alerts`)
**Arquivos:** `backend/app/buffer/processor.py` + `backend/app/alerts/service.py` (reutiliza `create_system_alert`)

- Contador de **falhas consecutivas de LLM** cross-turno em Redis (chave global, ex.: `llm:consecutive_failures`), incrementado no ramo `LLMUnavailableError` e **zerado no primeiro sucesso** de `run_agent`.
- Ao atingir o limiar (**3** falhas consecutivas), gravar **uma** linha em `system_alerts` via `create_system_alert(type="llm_down", severity="critical", title=..., message=...)`, com **dedup** no padrão de `fire_billing_alert` (1 alerta não-resolvido por hora) para não spammar.
- Fail-soft: qualquer erro no contador/alerta nunca derruba o atendimento.

---

## 4. Fluxo de dados

```
inbound → processor → typing → run_agent → _create_with_retry (retenta 429/5xx c/ backoff)
   ├─ sucesso → zera contador de falhas → resposta normal
   └─ indisponível persistente → lança LLMUnavailableError
        → processor: incrementa contador consecutivo
           → (se ≥ limiar) create_system_alert(type="llm_down")  [dedup 1/h]
           → fallback: execute_tool("encaminhar_humano", …)
                (IA off + cartão do João ao lead + deal + cancel follow-ups + rescue)
           → _update_last_msg → return
```

---

## 5. Tratamento de erros / bordas

- **Distinção:** `LLMUnavailableError` (LLM fora → handoff) ≠ turno vazio genuíno com LLM respondendo (mantém `_SAFETY_FALLBACK_GENERIC` da Change C intacto). Erros não-retentáveis 4xx **não** viram `LLMUnavailableError`.
- **Sem duplicação:** dedup de despedida (`_despedida_ja_enviada`) + gate `ai_enabled` cobrem turnos repetidos do mesmo lead.
- **Fail-soft:** contador/alerta e a própria chamada de handoff no fallback nunca escalam exceção.
- **Inalterados:** re-coalescing, gates de canal/AI, e todo o caminho feliz.

---

## 6. Testes (TDD)

**`_create_with_retry`** (novo arquivo `backend/tests/test_llm_retry_resilience_2026_07_01.py`):
- Retenta em **429** (`RateLimitError`) e depois **sucede** → retorna resposta; respeita nº de tentativas.
- Retenta em **503** (`InternalServerError`/5xx) e depois sucede.
- **Esgota** as tentativas em 429/5xx/conexão → lança **`LLMUnavailableError`**.
- **Não** retenta **400** (`BadRequestError`) → relança o erro original imediatamente (sem virar `LLMUnavailableError`).

**Processor** (novo arquivo `backend/tests/test_processor_llm_down_handoff_2026_07_01.py`):
- `run_agent` lança `LLMUnavailableError` → assert `execute_tool("encaminhar_humano", …)` foi acionado (vendedor `"Joao Bras"`), resultando em `ai_enabled=False` e `send_contact` chamado com o número do João — **em vez** de `return` mudo.
- Regressão: outra exceção de `run_agent` (não-LLM) mantém o comportamento atual (`[AGENT FAILED]` + return mudo, sem handoff).

**Alerta:**
- N (=3) falhas consecutivas → **1** linha em `system_alerts` (`type="llm_down"`); dedup impede a 2ª dentro da janela.
- Um sucesso de `run_agent` **reseta** o contador.

**Regressão geral:** fluxo normal e turno-vazio-genuíno intactos; handoff não duplica no gate `ai_enabled`.

---

## 7. Fora de escopo (explícito)

- Mensagem de espera antes do card; ajuste de limiares além de 3.
- Fallback de modelo alternativo (ex.: OpenAI) quando o Gemini esgota quota.
- Qualquer refatoração, utilitário ou melhoria além da resiliência de LLM descrita.
