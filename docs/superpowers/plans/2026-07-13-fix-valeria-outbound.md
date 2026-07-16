# Plano — Playbook Hunter da Valéria Outbound (13/07/2026)

Spec: `docs/superpowers/specs/2026-07-13-fix-valeria-outbound.md`

## Task 1 — `valeria_outbound/playbook.py` (novo)
Criar `POSTURA_HUNTER`: literal estático com as 4 leis do spec (Ponte de Contexto, Postura Ativa + blacklist,
Cliente conhecido = recompra / override da regra 26, Anti-carimbo). Sem nenhum campo volátil (cache).

## Task 2 — `prompts/__init__.py`
Prefixar `POSTURA_HUNTER` aos 5 prompts de estágio do `valeria_outbound` no `PROMPT_REGISTRY`.
O registry do `valeria_inbound` fica byte-idêntico.

## Task 3 — `valeria_outbound/secretaria.py`
- Regra de Ouro 2 (lead que já é cliente): trocar "se coloque à disposição e encerre" por condução à recompra.
- Arco vencedor, passo 3: "pergunta leve de rapport" → **pergunta investigativa** (a Valéria escolhe o assunto),
  e o passo 2 (transparência) passa a exigir o MOTIVO do contato, não só a origem.
- Bloco "POSTURA OUTBOUND — VOCE CONDUZ": endurecer o "NAO faca" com a blacklist literal.

## Task 4 — `valeria_outbound/context.py`
Arco do 1º turno (frame frio): passo (2) vira PONTE DE CONTEXTO (fecha o template + declara o motivo) e passo (3) exige
pergunta investigativa; proibir explicitamente o fecho passivo. O frame `warm_lp` também termina em pergunta ativa.

## Task 5 — Teste
`backend/tests/test_outbound_postura_hunter_2026_07_13.py`:
- cada um dos 5 prompts outbound (via `PROMPT_REGISTRY["valeria_outbound"]`) contém a lei de postura ativa e a blacklist;
- nenhum prompt outbound contém instrução de fechar turno com "posso te ajudar";
- `build_outbound_first_turn_context` (frio) exige motivo do contato e pergunta ativa;
- prompts inbound inalterados (regra 26 do base preservada).

## Task 6 — Validação e deploy
1. `pytest` (suíte completa) verde.
2. Deletar `scripts/temp_audit_outbound.py`.
3. `git pull origin master` → `git push origin <branch>:master` (deploy de produção).
