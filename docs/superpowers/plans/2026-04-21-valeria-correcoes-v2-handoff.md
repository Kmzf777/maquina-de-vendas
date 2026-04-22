# Handoff: Valéria Correções v2 — Contexto completo para nova sessão

## Situação atual

Branch: `fix/conversas-display-bugs`
Working directory: `/home/Kelwin/Kelwin - Maquinadevendascanastra`

Acabamos de executar o plano `2026-04-20-valeria-correcoes-pos-rehearsal-v1.md` completo e rodamos o rehearsal.
**Resultado: 1/5 arquétipos passando. KRs não atingidos — sem push para master ainda.**

---

## O que foi feito na v1 (já commitado, não refazer)

| Commit | O que fez |
|--------|-----------|
| `fb34429` | tools.py: prefixar system messages com `[tool:X]` |
| `9d3c17b` | orchestrator.py: emitir `[event:stage]` após mudar_stage |
| `87594fa` | archetypes.py: comentar prefix-match de has_tool_call |
| `27fbfa5` | test_rehearsal_verifier.py: cobrir has_tool_call com marker |
| `8341261` | chat-view.tsx: strip de prefixos na renderização |
| `6f11e10` | base.py: política amostras + answer-before-qualify + restrições encaminhar_humano |
| `2327117` | atacado.py: ETAPA 4 explícita (A+B+C => registrar => encaminhar) |
| `1266522` | private_label.py + exportacao.py: ETAPA FINAL explícita de handoff |
| SQL | Supabase: agent_profiles.model: gemini-2.0-flash → gpt-4.1-mini (ambos os profiles) |

---

## Resultado do rehearsal (2026-04-21T17:34:09)

| Arquétipo | Hard antes | Hard agora | Bot antes | Bot agora | Por quê falhou |
|-----------|-----------|------------|-----------|-----------|----------------|
| A1 cafeteria-atacado | FAIL | **FAIL** | 2 | 4 | Volume não confirmado; bot ignora perguntas de preço por kg |
| A2 private-label | FAIL | **FAIL** | 6 | 6 | `encaminhar_humano` não chamada (run termina em 2 turnos) |
| A3 multi-intent | FAIL | **FAIL** | 3 | 2 | Bot preso em `atacado`, nunca usa `mudar_stage('private_label')`, contradições de preço |
| A4 objetor-preço | FAIL | **PASS ✅** | 3 | 8 | — passou |
| A5 exportação | ABORT | **FAIL** | — | 8 | Stage atingido mas bot faz pergunta extra em vez de encaminhar |

Bot_score médio: **5,6** (KR era ≥6)

---

## Correções necessárias (v2) — o que fazer agora

### Fix 1 — A1: `atacado.py` — responder preço quando perguntado diretamente

**Arquivo:** `backend/app/agent/prompts/valeria_inbound/atacado.py`

**Problema:** O bot diz "preciso entender melhor sua demanda antes" quando o lead pergunta o preço por kg. A regra answer-before-qualify no `base.py` não está sendo suficiente — precisa de instrução específica no contexto de atacado.

**O que adicionar:** Logo antes ou dentro da seção `## ETAPA 3: PRECOS E CALL TO ACTION`, adicionar:

```
### REGRA: Cliente pergunta preco antes de informar volume

Se o lead perguntar o preco por kg OU o preco de qualquer produto ANTES de informar o volume ou confirmar o produto, RESPONDA IMEDIATAMENTE com o preco minimo de tabela. NAO diga "preciso entender primeiro" ou "qual o volume?". Dê o preco e DEPOIS pergunte o volume.

Exemplo correto:
Lead: "qual o preco do quilo?"
Voce: "o classico graos 1kg sai R$88,70 no atacado. qual seria o volume que voce taria precisando por mes?"

NAO FAZER:
Lead: "qual o preco do quilo?"
Voce: "antes de te passar os precos, me conta um pouco sobre o seu negocio..." ❌
```

---

### Fix 2 — A3: `atacado.py` — mudar_stage quando lead quer os dois (multi-intenção)

**Arquivo:** `backend/app/agent/prompts/valeria_inbound/atacado.py`

**Problema:** O bot tem a instrução `mudar_stage("private_label")` na seção SITUACOES ADVERSAS, mas quando o lead quer TANTO atacado QUANTO private label simultaneamente, o bot fica preso em atacado respondendo sobre preços de atacado e nunca transiciona.

O A3 transcript mostra: lead pediu tabela de private label várias vezes, bot continuou dando preços de atacado e até confundiu preços dos dois (contradição).

**O que adicionar:** Na seção `## SITUACOES ADVERSAS`, expandir a instrução de private_label:

```
### Cliente quer montar marca propria (Private Label)
Execute mudar_stage("private_label") e pergunte: "voce ja possui uma marca de cafe ou ta pensando em criar uma do zero?"

IMPORTANTE — MULTI-INTENCAO: Se o lead quer TANTO atacado QUANTO private label na mesma conversa:
1. Responda a pergunta atual de atacado em UMA bolha
2. Diga: "mas percebi que voce tambem tem interesse em private label — vou te explicar como funciona"
3. Execute mudar_stage("private_label") IMEDIATAMENTE
4. Continue a conversa no contexto de private label
NAO tente explicar os dois servicos no mesmo stage — isso gera confusao e contradictions de preco.
```

---

### Fix 3 — A5: `exportacao.py` — encaminhar sem exigir A+B+C completo

**Arquivo:** `backend/app/agent/prompts/valeria_inbound/exportacao.py`

**Problema:** O bot transiciona para `exportacao` corretamente, mas faz uma pergunta qualificadora (país/volume) em vez de chamar `encaminhar_humano` imediatamente. O lead já sinalizou exportação claramente, e o runner termina o run em 2 turnos — não há tempo para A+B+C.

**O que mudar na ETAPA FINAL:** Simplificar o threshold de handoff. Se o lead menciona exportação + tem qualquer informação de contexto (país, tipo de negócio, ou qualquer sinal), encaminhar imediatamente.

Substituir o critério A+B+C por:

```
# ETAPA FINAL — HANDOFF (meta desta conversa)

Exportacao e HANDOFF RAPIDO. Assim que o lead confirmar interesse em exportacao:

PASSO 1: Confirme o pais de destino com UMA pergunta direta ("exportacao pra qual pais?")
PASSO 2: Com qualquer resposta (mesmo estimativa), chame encaminhar_humano IMEDIATAMENTE:
         encaminhar_humano(vendedor='Joao Bras', motivo='exportacao — {pais}, {tipo de negocio se souber}')
PASSO 3: Uma ultima bolha: "passei pro Joao Bras que cuida do comercial de exportacao. ele te chama aqui com a proposta e a documentacao necessaria".

NAO exija volume, frequencia ou tipo de negocio antes de encaminhar. O Joao Bras faz essa qualificacao.
Se o lead ja falou o pais na primeira mensagem, pule o PASSO 1 e encaminhe DIRETAMENTE.
```

---

### Fix 4 — A2: `private_label.py` — critérios de handoff simplificados

**Arquivo:** `backend/app/agent/prompts/valeria_inbound/private_label.py`

**Problema:** O bot alcança `private_label` rapidamente (2 turnos), mas a ETAPA FINAL exige A+B+C (conceito + marca/volume + interesse concreto). Isso não cabe em 2 turnos.

**O que mudar:** Simplificar para A+B (ouviu o conceito + demonstrou interesse). Volume e marca são coletados pelo Joao Bras.

Substituir os critérios da ETAPA FINAL por:

```
# ETAPA FINAL — HANDOFF (meta desta conversa)

Voce handoff quando o cliente:
(A) ouviu o conceito de private label (MOQ, prazo, embalagem com sua logo)
(B) demonstrou interesse em avancar (qualquer sinal positivo: "interessante", "quero saber mais", confirmou que tem uma marca ou quer criar)

NAO precisa saber volume exato nem nome da marca antes de encaminhar. O Joao Bras faz essa qualificacao detalhada.

Entao:
PASSO 1: Confirme o interesse em UMA bolha curta ("legal! voce ja tem uma marca ou ta pensando em criar uma do zero?")
PASSO 2: Com qualquer resposta, chame encaminhar_humano(vendedor='Joao Bras', motivo='private label — {contexto da marca/interesse do lead}').
PASSO 3: Uma ultima bolha: "passei seu projeto pro Joao Bras, ele e quem conduz os proximos passos de arte, amostra piloto e fechamento. ele fala com voce aqui mesmo em instantes".
```

---

## Como executar

Use `superpowers:executing-plans` ou `superpowers:subagent-driven-development` para implementar os 4 fixes.

Ordem sugerida:
1. Fix 1 + Fix 2 juntos (mesmo arquivo `atacado.py`)
2. Fix 3 (`exportacao.py`)
3. Fix 4 (`private_label.py`)
4. Rodar rehearsal novamente: `cd backend && python -m scripts.rehearsal_runner`

Backend dev já está rodando em `http://127.0.0.1:8001` (porta 8001, não 8000).
Variáveis de ambiente já configuradas em `backend/.env.local`.

### Commits esperados

```bash
git add backend/app/agent/prompts/valeria_inbound/atacado.py
git commit -m "feat(valeria/atacado): responder preco direto + mudar_stage em multi-intencao"

git add backend/app/agent/prompts/valeria_inbound/exportacao.py
git commit -m "feat(valeria/exportacao): handoff imediato — sem exigir A+B+C completo"

git add backend/app/agent/prompts/valeria_inbound/private_label.py
git commit -m "feat(valeria/private_label): simplificar threshold de handoff para A+B"
```

---

## Critério de sucesso (KRs)

- **≥ 4/5 arquétipos** com todos os hard_checks passando
- **bot_score médio ≥ 6**
- A1: bot responde preço por kg quando perguntado
- A2: `encaminhar_humano` chamada após interesse confirmado
- A3: bot visita stages `atacado` + `private_label` na mesma conversa
- A5: `encaminhar_humano` chamada logo após confirmar país

Se atingido: merge para master com `git push origin fix/conversas-display-bugs:master`.

---

## Estado atual do repo

```
Branch: fix/conversas-display-bugs
Commits à frente de master: ~10 commits
Último commit: d7ffa8f docs(rehearsal): analise pos-correcoes v1
```

Artefatos do último rehearsal em:
`docs/superpowers/plans/pilot/rehearsal-runs/2026-04-21T17-34-09/`
