# Plano — Compliance Gemini dos prompts do Playbook Hunter (13/07/2026)

Spec: `docs/superpowers/specs/2026-07-13-gemini-prompt-compliance.md`

## Task 1 — `valeria_outbound/playbook.py` (D1, D2, D4)
Reescrever `POSTURA_HUNTER`:
- envelope `<outbound_playbook priority="max">` com sub-blocos por lei;
- bloco `<definicoes>` no topo (conversa viva / pergunta investigativa / fecho de turno);
- toda linha em imperativo (OBRIGATÓRIO / PROIBIDO / faça X); retórica removida;
- conteúdo normativo das 4 leis preservado palavra por palavra no sentido.

## Task 2 — `valeria_outbound/secretaria.py` (D3)
Adicionar UM par few-shot ao bloco `<few_shot_examples>` já existente, no formato dos vizinhos
(`User:` / `Assistant:` / `Nota:`): a falha real de 13/07 (lead confirma o template → "como posso te ajudar hoje?")
e o turno correto (reconhecimento → ponte de contexto com motivo → pergunta investigativa).

## Task 3 — `valeria_outbound/context.py`
Verificar aderência: separar fatos (contexto) das ordens (arco) e garantir imperativo. Ajustar só se houver desvio.

## Task 4 — Validação e deploy
1. `pytest tests/test_outbound_postura_hunter_2026_07_13.py` (20 casos) verde, sem afrouxar asserção.
2. Suíte `pytest` completa verde.
3. Commit → `git pull origin master` → `git push origin <branch>:master`.
