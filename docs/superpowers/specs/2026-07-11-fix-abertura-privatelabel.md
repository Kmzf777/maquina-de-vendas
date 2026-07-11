# Spec — Abertura cadenciada de private label + rede de segurança do "?" sem falso positivo

**Origem:** atendimento do lead 5561999119005 (Fabi, conv `befd097d`, 11/07 13:26 UTC): abertura despejou o processo inteiro em 3 bolhas e a última terminou com "?" colado numa afirmação ("...os cafés chegam prontos pra você comercializar com a sua marca própria?").

## Diagnóstico (forense read-only, script temp_audit_bug.py)

Cadeia de 3 mecanismos, comprovada no banco e por reprodução das funções puras do splitter:

1. **Information dump vem do PROMPT, não do humanizer.** O modelo gerou **4 parágrafos** na abertura (saudação / definição / lista completa do processo / afirmação de fechamento). Prova: a 3ª bolha persistida tem `\n\n` INTERNO (286 chars) — assinatura da fusão de overflow do clamp `MAX_BUBBLES=3` (`app/humanizer/splitter.py:59-63`), que funde os parágrafos 3+4 na última bolha. O humanizer não "quebrou em 3": ele FUNDIU 4 em 3. O script de abertura do prompt private_label induz a despejar o processo inteiro antes de qualquer descoberta (mesmo padrão nas conversas Ostemberg/Sandro/60ea360a de hoje).
2. **O "?" bizarro é da rede de segurança determinística `_ensure_question_mark` (`splitter.py:112-128`)**, não do modelo: a bolha fundida COMEÇA com "o que" (frase clivada DECLARATIVA: "o que está incluso é...") — que está em `_QUESTION_STARTERS` — e o último parágrafo não tinha pontuação final; a rede viu "starter interrogativo + sem pontuação" e anexou "?" ao fim da bolha fundida. Reproduzido: `_ensure_question_mark(bolha_sem_?)` re-anexa o "?" (True). O defeito estrutural: a heurística decide pelo INÍCIO da bolha e pontua o FIM — numa bolha fundida por overflow, início e fim são parágrafos diferentes.
3. **A regra de CTA do último deploy está INOCENTADA por timing e por mecanismo:** a resposta saiu às 13:26:15 UTC; o deploy da regra (`d7b8db8`, Action 29155571806) concluiu às ~14:16 UTC. Além disso a rede do "?" é pré-existente (comentário no código cita a falha real do lead 5531999844461 que a motivou).

Agravante observado: neste turno o modelo nem gerou a pergunta de descoberta ("você já tem marca criada...?") que os outros openings tiveram — a abertura terminou em afirmação, sem CTA real.

## Abordagens consideradas

- **A) Só prompt (cadenciar a abertura).** Resolve o dump, mas deixa viva a classe de falso positivo do "?" (qualquer declarativa começando com starter + bolha fundida volta a quebrar).
- **B) Prompt cadenciado + endurecer a rede do "?" com guardas conservadoras (ESCOLHIDA).** Ataca as duas causas de forma independente e testável; preserva o fix original da rede (pergunta curta que perdeu o "?").
- **C) Mexer no clamp `MAX_BUBBLES`/fusão de overflow.** Rejeitada: a fusão é a salvaguarda anti-spam de bolhas e o pacing depende dela; com a abertura cadenciada, turnos de 4+ parágrafos viram exceção — YAGNI.

## Mudança 1 — Abertura cadenciada (prompt)

Em `backend/app/agent/prompts/valeria_inbound/private_label.py` (localizar o script/exemplo de abertura que lista o processo completo — "o que está incluso é o design da embalagem..."; conferir se o gêmeo existe em `secretaria.py` inbound e tratar no mesmo padrão):

- Regra curta e imperativa (máx. 3 linhas, limite cognitivo do Flash): **a abertura tem no máximo 2 bolhas curtas** — (1) saudação + UMA frase de valor; (2) UMA pergunta de descoberta real (ex.: "você já tem uma marca criada ou tá pensando em lançar do zero?"). **PROIBIDO listar o processo completo (design→torra→envio) na abertura**; a explicação é entregue em partes, cada parte respondendo ao que o lead acabou de perguntar.
- Ajustar o exemplo de abertura existente no prompt para o novo formato (exemplos pesam mais que regras no Flash).
- A pergunta de fechamento deve ser pergunta REAL de descoberta — nunca afirmação com "?" (reforço de 1 linha; casa com a regra "PREÇO NUNCA SOLTO" já em prod, sem duplicá-la).

## Mudança 2 — Guardas na rede de segurança do "?" (`splitter.py::_ensure_question_mark`)

Adicionar duas condições de NÃO-ação (ambas conservadoras — na dúvida, não anexa):

1. **Bolha fundida:** se a bolha contém `\n\n` interno (fusão de overflow), não anexar — o starter do 1º parágrafo não diz nada sobre o fim do último.
2. **Bolha longa:** se a bolha tem mais de **120 caracteres**, não anexar — a classe de falha que a rede corrige (pergunta que perdeu o "?", caso 5531999844461) é curta; declarativas clivadas longas ("o que está incluso é...") deixam de ser alvo.

O comportamento atual permanece para bolhas curtas e não-fundidas (fix original preservado).

## Testes (TDD)

- Regressão do caso Fabi: bolha fundida de 286 chars começando com "o que ... é ..." → NÃO ganha "?".
- Caso original preservado: "você já tem uma marca criada ou tá pensando em lancar do zero" (curta, starter "você"? — não é starter; usar caso real coberto: "qual desses te chamou mais atenção") → ganha "?".
- Limite: bolha de exatamente 120 chars com starter → ganha "?"; 121 → não.
- Bolha com `\n\n` interno curta → não ganha "?".
- Testes existentes do splitter (grep `test_.*splitter|split_into_bubbles` em tests/) continuam verdes; NENHUM afrouxamento.
- Prompt: testes de aderência que citarem o exemplo antigo de abertura atualizados junto (sem afrouxar asserts de outras regras).

## Fora do escopo
- Clamp/pacing de bolhas, prompts outbound, regra de CTA de preço (já em prod), qualquer bloqueio novo.

## Critérios de aceite
1. Abertura de private label em produção passa a ter ≤2 bolhas e termina com pergunta de descoberta real (validável por transcript de rehearsal/QA).
2. `_ensure_question_mark` nunca anexa "?" a bolha fundida ou >120 chars (testes acima).
3. Suíte completa `pytest` verde.
