# Plan — Handoff responde antes + CTA obrigatório pós-preço

**Spec:** `docs/superpowers/specs/2026-07-11-fix-comportamento-handoff-cta.md`
**Branch:** `fix/inbound-audit-fixes` (continua; push p/ master só com autorização do usuário)
**Execução:** 1 subagente implementador (escopo coeso: prompts/tools/adherence/orchestrator) + 1 revisor.

## Task 1 — Cat. 2: handoff responde antes (texto + telemetria)
1. `tools.py`: frases novas na descrição da tool (spec 1a) e do parâmetro `mensagem_despedida` (spec 1b) — máx. 3 linhas cada, imperativo.
2. Prompts `valeria_inbound/private_label.py` + `atacado.py`: 1 frase no bloco de handoff de 10/07 (spec 1c).
3. Telemetria `[HANDOFF SEM RESPOSTA]` (spec 1d) — implementador escolhe o ponto com acesso a última msg do lead + mensagem_despedida; fail-open; teste com caplog provando warning + handoff intacto.

## Task 2 — Cat. 3: CTA pós-preço (texto + telemetria)
1. `base.py`: regra "PRECO NUNCA SOLTO" no bloco de preços (spec 2a) + item novo no checklist (spec 2b, numeração sequencial).
2. `adherence.py`: `price_without_cta(text) -> bool` (função pura, TDD com tabela de casos, incluindo R$1.000 separador de milhar e preço em bolha inicial com pergunta na última).
3. Orchestrator: chamada no padrão do `[PROMPT ECHO]` (~1348), isenta quando o turno encerrou via handoff; teste caplog + prova de que a resposta não é mutada.

## Restrições
- NENHUM bloqueio/mutação de resposta; telemetria é warning puro.
- Instruções novas curtas (esforço cognitivo do Flash) — nada de checklist novo longo.
- Verificar testes que asserem literais das descrições/prompts alterados (grep antes); rehearsal/fallback intocados.
- Commits com Co-Authored-By padrão; sem push.

## Validação
- Suíte completa `pytest` (backend) verde; review de task (spec+qualidade); gate final do controller re-executa a suíte.
