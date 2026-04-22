# Plano — Melhorias da Valéria (pós-baseline rehearsal V2)

**Data:** 2026-04-22
**Baseline contra qual comparar:** `ebf5557` (`docs/superpowers/plans/pilot/rehearsal-runs/2026-04-22T11-47-10/`)
**Fontes:** CSVs em `rags/` + transcripts + `priorities.md`

---

## 1. Contexto e objetivo

A baseline do rehearsal V2 expôs 4 gaps sistêmicos:

| # | Gap | Evidência |
|---|---|---|
| A | **Não-handoff** | 3 de 4 personas bateram max_turns sem chamar `encaminhar_humano` |
| B | **Preço como compromisso** | R1 disse "R$27,70", "R$46,70" → violou forbid PRECO_FRETE |
| C | **Desconto improvisado** | R2 ofereceu R$44,90 "já com embalagem" → violou DESCONTO |
| D | **Alucinação de terceiros** | R3 inventou 2 torrefações no RJ com nome/endereço/telefone |

Cruzando com os CSVs em `rags/`, apareceu um **5º problema anterior a todos**:

> **O prompt atual `prompts/arthur/atacado.txt` está com preços DESATUALIZADOS em relação ao CSV autoritativo `catalogo_produtos_atacado_canastra_rag.csv`.** Toda linha que a Valéria fala preço de atacado está errada.

Divergências preço prompt vs CSV (amostra — ver seção 2):

| Produto | Prompt atual | CSV (autoritativo) |
|---|---|---|
| Clássico moído 250g | R$27,70 | **R$28,70** |
| Clássico moído 500g | R$46,70 | **R$52,70** |
| Clássico grãos 1kg | R$88,70 | **R$97,70** |
| Granel 2kg | R$155,70 | **R$169,70** |
| Cápsula Nespresso | R$17,70 | **R$22,90** |

Além disso, 4 categorias inteiras **não existem no prompt**: Kits Amostra, Drip Coffee com tabela progressiva, Néctar de Minas (Gourmet + Blend), Moedor Canastra.

**Objetivo do plano:** em 3 fases, alinhar a Valéria com os dados reais (CSV) e fechar os buracos de comportamento detectados no rehearsal, medindo o ganho contra a baseline.

**Princípio guia (MVP-first, alinhado com o CLAUDE.md do repo):** cada fase deve terminar com um rehearsal rodável e comparável à baseline — nada de refactor grande antes de baixar métricas.

---

## 2. Verdades objetivas descobertas nos CSVs

### 2.1 Preços atacado corretos (fonte: `catalogo_produtos_atacado_canastra_rag.csv`)

**Pacotes Clássico / Suave:**
- moído 250g: R$28,70
- moído 500g: R$52,70
- grãos 250g: R$31,70
- grãos 500g: R$54,70
- grãos 1kg: R$97,70

**Canela:** moído 250g R$28,70
**Microlote:** 250g moído/grãos R$32,70
**Granel:** Clássico/Suave 2kg grãos R$169,70
**Displays:** Drip Suave R$24,90 | Cápsula Clássico R$22,90 | Cápsula Canela R$22,90

### 2.2 Produtos que o prompt não menciona

- **Néctar de Minas Gourmet** (75 SCA): moído 500g R$39,70 | grãos 1kg R$88,70 | Kit 10×500g R$357,00
- **Néctar de Minas Blend Arábica+Robusta** (espresso): moído 1kg R$79,70 | grãos 1kg R$79,70
- **Moedor Café Canastra:** sozinho R$949 | com 10 pacotes granel R$599 | **grátis com 20 pacotes granel**
- **Drip Coffee — Queima de Estoque** (val. 25/07/26, sem troca): tabela progressiva 1→10 displays, 5%→26% OFF (R$24,90 → R$184,26)

### 2.3 Kits Amostra (fonte: `amostras_canastra_rag.csv`) — **NOVO**

- **Kit 1 — Moídos:** 40g Suave + 40g Clássico + 40g Canela + 3 drips. R$60 (Sul/Sudeste/CO) ou R$90 (N/NE), **frete incluso**
- **Kit 2 — Grãos:** 100g Suave + 100g Clássico (grãos) + 40g Canela moído + 3 drips. Mesmo preço

**Implicação direta para R5:** o lead pediu amostra, a Valéria ofereceu microlote (café diferente, não amostra). A solução já existia — a Valéria não conhece.

### 2.4 Private Label — bate com o prompt

Preços do `private_label_canastra_rag_pl.csv` batem com `private-label.txt`. Ok.

---

## 3. Plano por fases

### Fase 1 — Alinhar verdade + regras duras (P0, **obrigatório antes de novo rehearsal**)

Objetivo: eliminar os 4 gaps do rehearsal e remover a mentira silenciosa dos preços.

#### Task 1.1 — Sincronizar preços de atacado

- **Arquivo:** `prompts/arthur/atacado.txt` (seção "Precos Atacado")
- **Ação:** substituir tabela atual pelos valores do CSV (seção 2.1 acima)
- **Teste:** rodar smoke R1 (representante-portfolio) — espera-se que a Valéria cite valores da nova tabela quando questionada sobre preço

#### Task 1.2 — Adicionar Kits Amostra como caminho de fluxo

- **Novo arquivo:** `prompts/arthur/amostras.txt` (ou seção em `atacado.txt` — decidir por menor blast radius)
- **Gatilho:** lead cita "amostra", "degustar", "experimentar", "testar antes" ou "primeira compra pequena"
- **Resposta canônica:** oferecer Kit 1 ou Kit 2 de acordo com perfil (moído vs grãos/cafeteria), preço com frete incluso, **sem minimizar que é um produto pago**
- **Teste:** smoke R5 isolada — espera-se que, frente à objeção "100un é muito pra testar", a Valéria ofereça Kit Amostra em vez de microlote

#### Task 1.3 — Regra "preço é referência, nunca compromisso"

- **Arquivo:** `prompts/arthur/base.txt` (nova entrada em REGRAS ABSOLUTAS) + ajuste em `atacado.txt` / `private-label.txt` seção "COMO APRESENTAR PRECOS"
- **Texto a adicionar:**

```
12. PRECO E REFERENCIA, NUNCA COMPROMISSO FINAL
   - Use SEMPRE verbo de referência: "gira em torno de", "fica por volta de", "na faixa de".
   - Nunca diga "sai a", "fica", "é" em valor final.
   - Nunca some produtos, nunca arredonde pra baixo, nunca invente combo.
   - Se o lead insistir em fechamento, valor total, desconto ou condicao especial,
     chame encaminhar_humano — esse é o papel do Joao Bras.
   - Desconto / frete gratis / prazo diferente do tabelado: SEMPRE encaminhar_humano.
```

- **Ajuste nos exemplos:** trocar `"o classico moido 250g sai R$27,70"` por `"o classico moido 250g gira em torno de R$28,70"` (e análogos).
- **Teste:** assertiva no juiz Gemini + forbids regex já existentes (PRECO_FRETE, DESCONTO) — esperado 0 violações.

#### Task 1.4 — Proibição explícita de inventar terceiros (hallucination guard)

- **Arquivo:** `prompts/arthur/base.txt` (REGRAS ABSOLUTAS)
- **Texto a adicionar:**

```
13. NUNCA MENCIONAR TERCEIROS QUE VOCE NAO TEM NA BASE
   - Proibido citar nomes, telefones, enderecos ou marcas de torrefacoes,
     cafeterias, distribuidores, clientes parceiros ou concorrentes.
   - Se o lead pedir indicacao de parceiro, revendedor ou ponto de venda
     fisico, responda que essa informacao e passada pelo supervisor e
     chame encaminhar_humano.
   - Dados permitidos: apenas os da Cafe Canastra (fazenda em Pratinha-MG,
     CD em Uberlandia-MG, supervisor Joao Bras) e links oficiais.
```

- **Teste novo (verifier):** `FORBID_TERCEIROS` — regex `(?i)\b(torrefa[çc][aã]o|cafeteria|distribuidora)\s+[A-Z]` (ou lista de cidades comuns + "rua/av"). Já aplicamos FORBID_PONTO_VENDA_FISICO — ampliar escopo.

#### Task 1.5 — Circuit breaker anti-loop → handoff forçado

- **Arquivo:** `prompts/arthur/base.txt` (seção nova "CIRCUIT BREAKER")
- **Texto:**

```
# CIRCUIT BREAKER — QUANDO ENCAMINHAR SEM PERGUNTAR

Chame encaminhar_humano IMEDIATAMENTE (sem perguntar "quer falar com o
vendedor?") nestes casos:
- Lead repetiu a MESMA objecao 2 vezes e voce nao conseguiu contornar.
- Voce esta prestes a oferecer "quer que eu te explique/envie X?" pela 3a vez
  no mesmo topico.
- Conversa tem 15+ turnos sem avanco de stage ou intencao registrada.
- Lead pediu diretamente "fechamento", "orcamento", "boleto", "nota fiscal",
  "prazo de pagamento" ou "transportadora".

Handoff e vitoria, nao desistencia. O Joao Bras fecha melhor do que voce
continuar em loop.
```

- **Teste:** rerun R2, R3, R5. Esperado: terminated_by = encaminhar_humano em todas.

#### Task 1.6 — Novo rehearsal V2.1 + comparação com baseline

- **Ação:** rodar runner contra R1-R5 com os 5 patches acima aplicados
- **Artefato:** `docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/comparison.md` com:
  - bot_score delta por persona
  - forbids violations delta
  - % handoff (baseline 25% → meta ≥75%)

**Deliverable da Fase 1:** 1 PR só com prompt + 1 teste novo de forbid. Sem mudança de código backend além do forbids.

---

### Fase 2 — Ampliar catálogo e polir condução (P1)

Só começa depois de Fase 1 fechada e rehearsal passando.

#### Task 2.1 — Adicionar produtos ausentes no atacado

- Néctar de Minas Gourmet + Blend Arábica-Robusta → nova seção em `atacado.txt`
- Moedor Café Canastra → nova seção (destacar promoção "grátis com 20 pacotes granel")
- Drip Coffee Queima de Estoque com tabela progressiva → nova seção, **com aviso "validade 25/07/26, não trocamos"**

#### Task 2.2 — Regra clara de quando oferecer microlote

- **Arquivo:** `prompts/arthur/private-label.txt` (seção "COMO APRESENTAR PRECOS")
- **Texto:** `Microlote so e alternativa de pedido minimo se o lead tem embalagem propria (50un). Nunca ofereca microlote como substituto de amostra do cafe que ele ja provou — e cafe diferente (86 SCA vs blend 84 SCA).`

#### Task 2.3 — Pergunta dupla → resposta dupla

- **Arquivo:** `prompts/arthur/base.txt` (CHECKLIST ANTES DE RESPONDER)
- **Item novo:** `11. Se o lead fez 2+ perguntas, respondo TODAS antes de avancar — a regra de 1 pergunta por turno se aplica a MINHAS perguntas, nao a respostas.`

#### Task 2.4 — Reduzir bordões robóticos

- **Ajuste:** cortar "quer que eu te explique/envie..." repetitivo. Variar com "posso te mostrar", "te passo isso" ou apenas executar a ação (ex: enviar fotos sem pedir permissão quando claramente solicitado).

#### Task 2.5 — Novo rehearsal V2.2 + comparação

---

### Fase 3 — RAG real + guardrails automáticos (P2, backlog)

Só se Fase 2 deixar gaps que não são resolvíveis só com prompt.

#### Task 3.1 — Migrar catálogo para RAG

- **Problema:** preço hard-coded no prompt desacopla da fonte. Se o Arthur atualizar o CSV, a Valéria continua mentindo.
- **Proposta:** o backend carrega `rags/*.csv` em tempo de inicialização e injeta apenas a seção relevante ao stage atual via retrieval (ou simplesmente `cat` inteiro se < 20kb). Preço vira "o que está no CSV" e o prompt só ensina **como apresentar**.
- **Diretório de dados já existe:** `/home/Kelwin/Kelwin - Maquinadevendascanastra/rags/`
- **Cuidado:** manter idempotência (mesmo CSV → mesmo comportamento).

#### Task 3.2 — Hard check `no_stage_stagnation`

- Novo hard_check: se o stage não mudou em 10 turnos E não houve intention registrada, falha. Força o prompt a não travar.

#### Task 3.3 — Ampliar `FORBIDS`

- `FORBID_TERCEIROS`: regex para nomes próprios + endereços em mensagens da Valéria.
- `FORBID_BOLETO_PRAZO_PAGAMENTO`: já implícito em outros, mas isolar.

#### Task 3.4 — Persona R4 estável

- R4 crashou com ReadTimeout 60s. Investigar se o backend tem turn lento, ou se sobe timeout para 120s. Registrar na gotchas memory.

---

## 4. Ordem de ataque recomendada (MVP-first)

1. **Task 1.3** (preço = referência) + **Task 1.4** (terceiros proibidos) + **Task 1.5** (circuit breaker) — só prompt, alto leverage. **1 commit.**
2. **Task 1.1** (preços corretos do CSV) — só prompt. **1 commit.**
3. **Task 1.2** (kit amostra) — só prompt. **1 commit.**
4. **Task 1.6** — roda rehearsal, gera `comparison.md`, commita baseline novo. **1 commit.**
5. Parar → usuário testa em conversa real (whitelist dev router) → só depois push pra master.
6. Fase 2 só começa se a Fase 1 baixar violações e subir handoff%.

---

## 5. Critérios de sucesso (quantitativos)

| Métrica | Baseline | Meta Fase 1 | Meta Fase 2 |
|---|---|---|---|
| % handoff (5 personas) | 25% (1/4) | ≥75% | 100% |
| Forbids violations (total) | 2 | 0 | 0 |
| Bot score médio | 5,75 | ≥7 | ≥8 |
| Personas com resposta_incorreta | 3/4 | ≤1/4 | 0 |
| Preços corretos vs CSV | ❌ | ✅ | ✅ |

---

## 6. Riscos

- **Prompts são sensíveis a ordem:** adicionar muita regra nova degrada naturalidade. Se score cair após Fase 1 apesar de forbids 0, é sinal de prompt engorda demais → considerar refactor/consolidação antes da Fase 2.
- **RAG (Fase 3) muda a arquitetura do prompt builder:** não fazer antes de validar que o problema continua após Fase 1/2.
- **Rehearsal é simulação:** scores altos no rehearsal não garantem venda real. A validação final só vem do whitelist dev router com número real (MVP-first rule da memória).

---

## 7. Próximo passo concreto

Se o usuário aprovar, começar por **Task 1.3 + 1.4 + 1.5** (3 edições em `prompts/arthur/base.txt`), commit, e rodar smoke R2 (pior caso) isolado antes de subir para rehearsal completo.
