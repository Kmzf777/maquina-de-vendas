# Plan — Correções da Auditoria Inbound 10/07/2026

**Spec:** `docs/superpowers/specs/2026-07-10-fix-inbound-audit.md`
**Branch:** `fix/inbound-audit-fixes` (push p/ master somente com autorização do usuário, conforme CLAUDE.md)
**Execução:** 2 subagentes por domínio + validação final na sessão principal.

---

## Trilha A — Infra/Persistência (Subagente 1)

### A1. Helper de placeholder de mídia (backend)
- Criar `describe_media_placeholder(row: dict) -> str` (função pura) em `backend/app/conversations/service.py` (ou módulo utilitário próximo, seguindo o padrão do repo).
- Regra: `content` não-vazio → retorna `content` intocado; vazio + `message_type` mapeado → placeholder (`[áudio]`, `[imagem]`, `[vídeo]`, `[documento]`, `[sticker]`, `[localização]`, `[contato]`, fallback `[mídia]`); vazio + `text`/None → retorna vazio (comportamento atual).
- TDD: testes unitários primeiro (tabela de casos), em `backend/tests/`.

### A2. Aplicar nos dois `get_history`
- `backend/app/conversations/service.py:357` e `backend/app/leads/service.py:1532`: mapear `content` de cada row pelo helper antes de retornar.
- Teste: row com `content=""`+`message_type="audio"` sai com `[áudio]`; row de texto normal inalterada (contrato preservado — mesmas chaves/ordem).

### A3. Rota `send-media` (frontend)
- `frontend/src/app/api/conversations/[id]/send-media/route.ts`:
  - Ler `sendResp.json()` e extrair `messages[0].id` → persistir como `wamid` no insert (paridade com `send/route.ts:133`; tolerar ausência sem quebrar o envio).
  - `content`: áudio → `[áudio]`, imagem → `[imagem]`, vídeo → `[vídeo]`; documento permanece `originalFilename`.
- Teste vitest se houver harness para rotas API; senão, garantir `npm run build`/`vitest` verdes e revisar tipos.

## Trilha B — Comportamento LLM (Subagente 2)

### B1. Gatilho determinístico de entrada
- Constante `PREFILL_STAGE_TRIGGERS` (frase normalizada → stage) + `match_prefill_stage(text) -> str | None` em módulo do buffer/leads (núcleo puro, testável). Normalização: caixa baixa, sem acentos, espaços colapsados, pontuação final tolerada.
- Entrada inicial: `"ola! quero saber mais sobre ter a marca propria de cafe"` → `private_label`.
- Integração em `backend/app/buffer/processor.py`: antes de rodar o agente, se stage da conversa ∈ {`pending`, `secretaria`, vazio/None} e alguma mensagem do lote casa → aplicar transição (update conversa+lead, `ensure_segment_deal`, marcador system `stage alterado para: <stage>`), fail-open.
- TDD: matcher (variações de caixa/acento/pontuação; não-match por substring parcial) + teste de integração do processor.

### B2. Anti-flapping de `mudar_stage`
- Descrição da tool (`backend/app/agent/tools.py:199`): acrescentar critério de estabilidade (declaração explícita do lead; ambíguo/social não muda; reverter exige correção explícita).
- Executor `mudar_stage` (`tools.py:767`): telemetria `[STAGE FLAP]` (warning) quando a transição reverte para stage presente em marcador `stage alterado para:` dos últimos 15 min da conversa — sem bloqueio.

### B3. Critério de qualificação do handoff
- Descrição de `encaminhar_humano` caso (1) (`tools.py:222`): exigir finalidade concreta + sinal ativo de avanço; emojis/aplausos/monossílabos/simpatia não qualificam; na dúvida, `qualificar_lead`.
- Prompts `valeria_inbound/private_label.py` e `valeria_inbound/atacado.py`: regra curta espelhando o critério + "oferta condicionada aguarda resposta afirmativa".
- Cuidado: não criar checklist longo (diretriz anti-engessamento); verificar que testes de aderência/prompt existentes continuam verdes.

### B4. Métrica no daily QA report
- Adicionar ao relatório diário a contagem de marcadores `handoff verbalizado sem tool-call (guarda deterministica)` (mesmo padrão das métricas existentes do report).

## Validação (sessão principal)

1. `pytest` — suíte hermética completa do backend.
2. `vitest` — suíte do frontend (rota send-media e previews).
3. Revisão do diff consolidado (code-review) antes de commitar.
4. Commit na branch; push p/ master **somente após autorização do usuário**.
