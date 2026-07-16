# Plan — Abertura cadenciada de private label + guardas na rede do "?"

**Spec:** `docs/superpowers/specs/2026-07-11-fix-abertura-privatelabel.md`
**Branch:** `fix/inbound-audit-fixes` (continua; push p/ master somente com autorização)
**Execução:** 1 subagente implementador + 1 revisor (escopo pequeno e coeso). AGUARDANDO autorização do usuário para a fase de Execution.

## Task 1 — Guardas na rede do "?" (código, TDD primeiro)
1. Grep dos testes existentes do splitter (`backend/tests/`, padrão `split_into_bubbles`/`splitter`) — inventariar asserts atuais antes de tocar.
2. Testes novos (red): caso Fabi (bolha fundida 286 chars, starter "o que", declarativa) → sem "?"; bolha curta com starter → com "?" (comportamento preservado); limites 120/121 chars; bolha curta com `\n\n` interno → sem "?".
3. Implementar as duas guardas em `_ensure_question_mark` (`backend/app/humanizer/splitter.py:112-128`): early-return se `"\n\n" in bubble` ou `len(bubble) > 120`. Comentário pt-BR citando o caso Fabi (falso positivo em clivada fundida) ao lado do comentário existente do caso 5531999844461.

## Task 2 — Abertura cadenciada (prompt)
1. Localizar o script/exemplo de abertura em `backend/app/agent/prompts/valeria_inbound/private_label.py` (âncora: texto que gera "o que está incluso é o design da embalagem...") e verificar gêmeo em `valeria_inbound/secretaria.py`.
2. Regra nova (máx. 3 linhas, imperativa): abertura ≤2 bolhas curtas — saudação+valor em 1 frase e UMA pergunta de descoberta; PROIBIDO listar o processo completo na abertura; explicação em partes conforme o lead pergunta.
3. Reescrever o exemplo de abertura do prompt no novo formato (exemplos > regras no Flash).
4. Grep em tests/ por literais do exemplo antigo; atualizar asserts que o citem, sem afrouxar.

## Validação
- Suíte completa `pytest` de `backend/` verde; review de task (spec+qualidade); gate final do controller re-executa a suíte.
- Pós-deploy (quando autorizado): conferir no primeiro lead real de private label que a abertura saiu com ≤2 bolhas e pergunta real.

## Riscos
- Guarda de 120 chars pode silenciar um caso legítimo de pergunta longa sem "?" — aceito: a rede é *best effort*; o prompt (regra 23: perguntas SEMPRE terminam com "?") continua sendo a linha principal.
- Mudar o exemplo de abertura altera o tom dos primeiros turnos — mitigado pela revisão do texto no diff e pelos transcripts de QA do dia seguinte.
