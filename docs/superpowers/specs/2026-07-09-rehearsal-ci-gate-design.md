# P2 — Rehearsal como gate de regressão do agente (eval contínuo em CI)

**Data:** 2026-07-09
**Status:** aprovado para implementação

## Problema

A categoria de incidente mais frequente do projeto ("Valéria se comportou errado com o lead X") é descoberta em produção. O ativo para prevenir isso já existe — o harness de rehearsal (`backend/scripts/rehearsal_runner.py` + `outbound_rehearsal_runner.py`) com **10 arquétipos** (T1–T6 inbound, O1–O4 outbound) e verificação determinística passa/falha (hard checks de stage/tool/regex + forbids anti-alucinação de preço/PIX/prazo/desconto; o juiz LLM `gemini-2.5-pro` é informativo, não afeta o gate) — mas só roda manualmente na máquina do desenvolvedor.

## Design

Novo workflow `.github/workflows/rehearsal.yml`, **desacoplado do deploy** (custo de LLM não entra no push):

- **Triggers:** `schedule` (cron diário `0 9 * * *` = 06:00 BRT, fora do horário comercial de disparo) + `workflow_dispatch` (com input opcional `only` → repassado como `REHEARSAL_ONLY` para rodar um arquétipo).
- **Topologia no runner:** Redis via `services:` (`redis:7-alpine`), backend `uvicorn app.main:app --port 8001` em background com `REHEARSAL_MODE=true` apontando para o **Supabase homolog** (o runner faz wipe de leads sintéticos — jamais prod; os guards anti-prod do harness abortam se a URL contiver o ref de produção), depois `python -m scripts.rehearsal_runner` (T1–T6) e `python -m scripts.outbound_rehearsal_runner` (O1–O4) em sequência (ranges de telefone sintético separados).
- **Gate:** exit code ≠ 0 de qualquer runner falha o job. O runner inbound já retorna 1 em falha (`rehearsal_runner.py:410-411`); o **outbound não tem exit code** — correção incluída (mesma regra do inbound, `sys.exit(1 if any_fail else 0)`).
- **Relatório:** step final publica tabela passa/falha por arquétipo no `GITHUB_STEP_SUMMARY` (a partir dos `run.json`) e sobe os artefatos (`run.json`, `verification.json`, `transcript.md`) via `actions/upload-artifact` (retenção 14 dias). Os artefatos NÃO são commitados.
- **Timeout do job:** 45 min (runs históricos ~30 min).

### Secrets novos (GitHub → Settings → Secrets)

| Secret | Uso |
|---|---|
| `REHEARSAL_SUPABASE_URL` | Supabase **homolog** (`mosbwmsqfcwqdypucgtc`) |
| `REHEARSAL_SUPABASE_SERVICE_KEY` | service key do homolog |
| `REHEARSAL_GEMINI_API_KEY` | chave da Valéria no backend do run — **isolada, nunca a de produção** (lição do estouro de cota de jul/2026) |
| `GEMINI_API_KEY_DEV` | ator (flash-lite) + juiz (pro) — o harness **aborta** se ausente ou igual à chave do backend (`gemini_actor.py:29-51`) |

### Custo estimado por run

10 arquétipos × (~5–20 turnos × [1 ator flash-lite + 1–3 Valéria flash]) + 10 juízes pro ≈ algumas centenas de chamadas, dominadas por flash/flash-lite. Diário e agendado — não entra no caminho do deploy.

## Fora de escopo (YAGNI)

Novos arquétipos (indicação, frustração, autoresponder — gaps conhecidos, ficam para iteração futura); migração do `gemini_actor.py` para o SDK novo (`google-generativeai` deprecated continua, é só o harness); paralelização entre os dois runners; comentário automático em PR (o fluxo não usa PRs).

## Riscos

- **Flakiness de LLM** (comportamento não-determinístico) → o gate usa somente checks determinísticos; falhas intermitentes aparecem no histórico do workflow sem bloquear deploy algum.
- **Schema do homolog atrás do prod** (memória do projeto) → primeira execução via `workflow_dispatch` valida; divergências de schema aparecem como erro de setup, não como falso "regressão".
- **Segredo errado (prod)** → guards do harness abortam por construção.
