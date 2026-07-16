# Plan — Fix S1 (handoff duplicado) + S2 (ponte engolindo pergunta de negócio)

Spec: `docs/superpowers/specs/2026-07-11-fix-handoff-and-bridge.md`. Execução por 2
subagentes independentes (arquivos disjuntos), validação pytest ao final, push direto
p/ master autorizado se verde.

## Etapa 1 — Branch
- [ ] Criar branch `fix/handoff-dedup-bridge-intent` a partir da master atualizada.

## Etapa 2 — Subagente A (S1: sentinel ciente da cascata)
Arquivos: `backend/app/agent/tools.py`, `backend/app/agent/orchestrator.py`,
`backend/tests/test_handoff_cascade_sentinel_2026_07_11.py` (novo).
- [ ] `tools.py`: constante `HANDOFF_RESULT_PREFIX = "Lead encaminhado para "` usada no
      return do branch `encaminhar_humano` (string final idêntica à atual).
- [ ] `orchestrator.py` loop principal: flag `handoff_executed` (por nome OU por prefixo
      no `tool_result`); sentinel e telemetria [HANDOFF SEM RESPOSTA] passam a usá-la.
- [ ] `orchestrator.py` retry (~L1190): mesma detecção por prefixo nos resultados do retry.
- [ ] Atualizar comentário-invariante da guarda verbalizada (cita a cascata).
- [ ] Testes novos: cascata → sentinel None + exatamente 1 execute_tool + nunca
      "encaminhar_humano" via guarda; retorno normal não seta flag; qualificar_lead com
      âncoras completas retorna o prefixo.

## Etapa 3 — Subagente B (S2: via do meio na ponte)
Arquivos: `backend/app/buffer/processor.py`,
`backend/tests/test_bridge_business_question_2026_07_11.py` (novo),
`backend/tests/test_bridge_social_closing_2026_07_11.py` (contrato atualizado).
- [ ] `_BUSINESS_QUESTION_TOKENS` + `_looks_like_business_question` (pura, normalizada).
- [ ] Escada em `_maybe_send_handoff_bridge`: reação → social ❤️ → negócio SILÊNCIO
      (log + marcador system, sem consumir cooldown) → resto carimbo+cartão.
- [ ] Atualizar `test_bridge_duvida_real_segue_enviando_texto` ao novo contrato; caso
      "vácuo puro → carimbo" com texto sem sinal de negócio.
- [ ] Testes novos: detector puro (casos True/False) + comportamento (sem send_text/
      send_contact, cooldown intacto, marcador salvo).

## Etapa 4 — Validação
- [ ] `pytest` completo do backend verde (suíte inteira, não só os novos).
- [ ] Revisão do diff (aderência à spec, fail-soft preservado).

## Etapa 5 — Deploy (fluxo CLAUDE.md, autorizado pelo usuário se testes verdes)
- [ ] `git pull origin master`
- [ ] `git push origin fix/handoff-dedup-bridge-intent:master`
