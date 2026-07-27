# Design/Spec — Rede de Segurança do Handoff durante Indisponibilidade do LLM

**Data:** 2026-07-27
**Branch:** `fix/llm-outage-handoff-safety-net`
**Origem:** auditoria do apagão de `gemini-2.5-flash` iniciado em 22/07/2026 17:48 BRT (ainda ativo na data desta spec).

---

## Contexto

Apagão em produção: a última resposta real da Valéria foi em **22/07 17:48**. Desde então
`gemini-2.5-flash` (modelo de resposta do agente) acumula **158+ falhas consecutivas** sem um
único sucesso. `gemini-2.5-flash-lite` (usado por `rolling_summary` / `qualification_summary` /
`media_transcription`) **voltou a funcionar hoje às 07:24** — mesma chave, mesmo projeto. O
apagão é específico do modelo de resposta.

A auditoria dos dados de produção (Supabase, read-only) mostrou que **o fallback funciona**:

| Dia | Inbounds | Respostas IA | Handoffs |
|---|---|---|---|
| 21/07 | 9 | 297 | 37 |
| 22/07 | 46 | 3 | 30 |
| 23/07 | 53 | 0 | 38 |
| 24/07 | 38 | 0 | 24 |
| 25/07 | 21 | 0 | 18 |
| 26/07 | 34 | 0 | 25 |
| 27/07 | 32 | 0 | 22 |

Todos os handoffs dispararam entre **30,5 e 31,9 min** após a última mensagem do lead (n=29,
média 31,2). Dois casos foram acompanhados ao vivo durante a auditoria e confirmam o padrão:

- lead `5541991953960` — inbound 14:05:00, handoff 14:35:42 (**30,7 min**);
- lead `5548998014080` — inbound 14:14:25, handoff 14:45:32 (**31,1 min**).

Esse atraso é exatamente `LLM_PARK_MAX_MINUTES=30` (parking, `buffer/parking.py`) mais o tick
do worker. **Nada está quebrado no caminho do handoff.** O que a auditoria revelou foram três
defeitos adjacentes que só se manifestam quando o apagão é LONGO.

---

## Diagnóstico

### Defeito 1 — o parking de 30 min é contraproducente em apagão sustentado

`buffer/parking.py:_compute_deadline` dá `parked_at + 30min` para `reason="transient"`. O
parking existe por um motivo legítimo e documentado (Onda 2, 09/07): um outage de 13 minutos
não pode custar o funil inteiro do lead com um handoff cego.

Mas o `reason` é derivado do **tipo da exceção** (`processor._llm_down_reason`), não da
**duração** do apagão. Um apagão de 5 dias continua classificado como `transient`, então cada
lead novo é estacionado por 30 minutos antes de um handoff que já era certo desde o primeiro
tick. Resultado medido: **31 minutos de silêncio absoluto** para cada um dos ~24 leads/dia,
sem sequer uma mensagem de espera (o `_HOLD_MSG` só existe para `budget`/`quota`).

O sistema **já sabe** que o apagão é longo — `llm:consecutive_failures` estava em 158. A
informação existe e não é usada na decisão do deadline.

### Defeito 2 — `handoff_rescue` é morto pelo próprio backstop de parada

**144 jobs `handoff_rescue` criados em 5 dias. 0 enviados. 144 cancelados com
`cancel_reason="ai_disabled"`.**

`follow_up/scheduler.py:579-604` — a rede de segurança de parada roda para **qualquer**
`job_type`, logo após a reivindicação e antes de qualquer despacho. Ela cancela o job quando
`_lead_stop_reason` devolve algo, e `_lead_stop_reason` (`:850`) devolve `"ai_disabled"` sempre
que `lead.ai_enabled is False`.

O problema é circular: `encaminhar_humano` **desliga a IA** ao fazer o handoff, e é esse mesmo
handoff que agenda o `handoff_rescue`. O job nasce, portanto, já condenado — o roteador dedicado
(`:607`, comentado como "antes de qualquer guard padrão") nunca é alcançado.

O backstop foi introduzido para um caso real e correto (5511910402026, 15/07: a cliente pediu
ao humano para a IA parar e os toques seguiram). Ele deve continuar valendo para cadência
automática. Mas `handoff_rescue` **não é cadência ao lead** — é uma notificação por template ao
**vendedor**, cuja pré-condição é justamente `ai_enabled=False`.

Consequência medida: **lead Wilson Demuth (5547992221012)** recebeu handoff + cartão em 26/07
16:04, mandou um áudio às 17:32 e nunca apareceu no canal do João. Ficou >21h no vácuo. O
`handoff_rescue` era exatamente o anteparo desse caso.

### Defeito 3 — o João recebe todos os leads sem contexto

**63 de 64 dossiês** da janela do apagão saíram com `*Erro ao gerar resumo automático.*`
(`agent/summary.py:126-132`). O bloco `except` devolve uma string que descarta tudo que o
sistema já tem em mãos — histórico da conversa, motivo do handoff, timestamp — e entrega ao
vendedor apenas segmento e nome.

O resumo é gerado por LLM e é legítimo que falhe quando o provedor está fora. O defeito é o
fallback ser **vazio de informação** quando existe informação determinística disponível de graça.

---

## Decisões de design

### D1 — Deadline do parking sensível à DURAÇÃO do apagão

O `reason` continua vindo do tipo da exceção. O que muda é que `transient` passa a ter **duas
janelas**, escolhidas pela contagem de falhas consecutivas já disponível no chamador:

- falhas < `LLM_PARK_OUTAGE_FAILURES` (default **10**) → janela atual, `LLM_PARK_MAX_MINUTES`
  (30 min). Blip de minutos segue integralmente protegido.
- falhas ≥ limiar → janela curta, `LLM_PARK_OUTAGE_MINUTES` (default **3 min**). Ainda dá uma
  chance de recuperação ao próximo tick, mas o lead vai ao João em ~3 min em vez de 31.

**A contagem é passada por parâmetro, não relida do Redis.** `_handle_llm_down` já chama
`_record_llm_failure()` e tem o número em mãos; reler seria uma segunda ida ao Redis e tornaria
`_compute_deadline` impura e não testável. Assinatura: `park_turn(..., failure_count: int = 0)`
→ `_compute_deadline(reason, parked_at, failure_count)`.

`budget` e `quota` ficam **intocados**: já têm deadline próprio (virada do dia) e já enviam
`_HOLD_MSG`. O modo "cofre vazio" é uma categoria com semântica distinta e não deve ser
contaminada por contagem de falhas.

Default de 10 falhas: o alerta `llm_down` já dispara em 3 (`_LLM_DOWN_ALERT_THRESHOLD`) — 10 é
folgado o bastante para não confundir uma rajada curta com apagão, e apertado o bastante para
que o segundo ou terceiro lead de um apagão real já pegue a janela curta.

### D2 — Isenção do `handoff_rescue` no backstop, por MOTIVO e não por tipo

Não basta pular o backstop inteiro para `handoff_rescue`: `opt_out`, `blacklisted` e
`wrong_number` **devem** continuar cancelando o resgate (não se manda template para quem pediu
para sair, nem para número errado). Só `ai_disabled` é o motivo circular.

Modela-se isso como um mapa explícito, não como um `if` solto:

```python
_STOP_REASON_EXEMPT_JOB_TYPES: dict[str, frozenset[str]] = {
    "ai_disabled": frozenset({"handoff_rescue"}),
}
```

com um helper puro `_stop_reason_applies(reason, job_type) -> bool`. O mapa documenta a
exceção no ponto onde ela é decidida e torna trivial adicionar/testar novos pares no futuro.

`_lead_stop_reason` fica **inalterada** — ela responde "este lead está marcado para parar?",
que continua sendo verdade. Quem decide se aquele motivo se aplica àquele job é o chamador.

### D3 — Dossiê determinístico como fallback do resumo

Substituir o texto de erro por um briefing montado a partir do que já está em memória: nome,
empresa, segmento, motivo do handoff, data/hora e as **últimas mensagens do lead na íntegra**.

Decisões:

- Só mensagens do **lead** (`role == "user"`) entram no trecho verbatim — o que o vendedor
  precisa é o que o cliente pediu; reproduzir falas da Valéria num dossiê que existe porque a
  Valéria falhou é ruído.
- Teto de **6 mensagens** e **280 chars** por mensagem — o dossiê vai por WhatsApp e precisa
  ser lido no celular.
- O bloco é **marcado como automático e sem IA**, para o vendedor saber que não houve triagem.
- Mantém o cabeçalho `## NOVO LEAD QUALIFICADO PELA VALÉRIA` — é o que o CRM e o histórico do
  João já reconhecem.
- Função **pura** (`_fallback_briefing`), testável sem rede, usada tanto no ramo `except` quanto
  no ramo de resposta vazia.

O caminho feliz (LLM respondeu) fica **byte-idêntico** ao atual.

---

## Escopo

### Arquivos tocados

| Arquivo | Defeito |
|---|---|
| `backend/app/buffer/parking.py` | 1 |
| `backend/app/buffer/processor.py` | 1 (propagar a contagem) |
| `backend/app/follow_up/scheduler.py` | 2 |
| `backend/app/agent/summary.py` | 3 |
| `backend/tests/test_llm_outage_handoff_safety_net_2026_07_27.py` | novo |

### Coordenação com o trabalho em andamento

Há outro dev ativo no repo principal (`canastra/maquina-de-vendas`) na branch
`perf/gemini-context-caching`, com alterações **não commitadas** em:

- `backend/app/agent/gemini_client.py` (modificado)
- `backend/app/agent/orchestrator.py` (modificado)
- `backend/app/agent/prompt_cache.py` (novo)
- `backend/tests/test_prompt_cache_2026_07_27.py` (novo)

O plano dele (`2026-07-27-gemini-context-caching-plan.md`) prevê ainda
`backend/app/agent/prompts/base.py` (Fase 1) e `backend/app/agent/budget_guard.py` (Fase 3).

**Interseção com esta spec: nenhuma.** Este trabalho não toca nenhum desses seis arquivos.
`agent/summary.py` é do mesmo pacote mas não aparece em nenhuma fase do plano dele. Trabalhamos
em worktree separado (`canastra/feats2`), ambos a partir de `63f8525`.

### Fora de escopo

- **Causa raiz do apagão do `gemini-2.5-flash`.** Requer os logs do container em produção
  (erro exato: 404 de modelo / quota / permissão). Nada aqui tenta adivinhar ou contornar.
- **Recuperação do lead Wilson Demuth (5547992221012).** É ação de operação, não de código —
  o D2 restaura a rede daqui para frente, mas não alcança um job já cancelado.
- Alertas `ai_unresponsive` sem ação automática associada.

---

## Critérios de aceitação

1. Com `llm:consecutive_failures` abaixo do limiar, o deadline transient continua sendo
   `parked_at + 30min` — comportamento atual preservado byte a byte.
2. Acima do limiar, o deadline transient passa a ser `parked_at + 3min`.
3. `budget` e `quota` produzem exatamente os mesmos deadlines de hoje, qualquer que seja a
   contagem de falhas.
4. Um job `handoff_rescue` de lead com `ai_enabled=False` (e sem opt-out/blacklist/número
   errado) **não** é cancelado pelo backstop e chega ao handler dedicado.
5. O mesmo job, para lead com `opt_out=True`, **continua** sendo cancelado.
6. Jobs de cadência normal (`followup`) de lead com `ai_enabled=False` **continuam** sendo
   cancelados com `ai_disabled`.
7. Falha do LLM no resumo produz um dossiê contendo nome, segmento, motivo e as mensagens do
   lead — nunca a string `Erro ao gerar resumo automático`.
8. Sucesso do LLM no resumo devolve `result.text` inalterado.
9. Suíte completa verde (`cd backend && python -m pytest -q`).

---

## Rollback

- Defeito 1: `LLM_PARK_OUTAGE_FAILURES=999999` no ambiente restaura a janela de 30 min sem
  deploy.
- Defeito 2: `git revert` do commit de `scheduler.py`.
- Defeito 3: aditivo no ramo de falha; sem efeito no caminho feliz.
