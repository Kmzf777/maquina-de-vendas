# Comparação Rehearsal V2.1d vs Baseline

**Baseline:** `2026-04-22T11-47-10` (git SHA: ebf5557)
**V2.1d:** `2026-04-22T16-11-00` (git SHA: 3f45042)
**Patches aplicados:** preços CSV, Kits Amostra, Regras 12+13+Circuit Breaker em base.py

---

## Scorecard geral

| Métrica | Baseline | V2.1d | Delta |
|---|---|---|---|
| Pass rate | 0/4 (0%) | 3/5 (60%) | **+60 pp** |
| Violações forbid | 2 (PRECO_FRETE + DESCONTO) | 0 | **✅ -2** |
| Personas sem handoff | 3/4 | 1/5 | **-2** |
| Bot score médio | 5,75 (4 runs) | 5,8 (5 runs) | ~neutro |
| Max_turns atingido | 3/4 | 1/5 | **-2** |

---

## Por persona

| Arquétipo | Baseline status | Baseline turnos | Baseline score | Baseline forbids | V2.1d status | V2.1d turnos | V2.1d score | V2.1d forbids |
|---|---|---|---|---|---|---|---|---|
| R1 representante-portfolio | ❌ failed | 16 | 9 | PRECO_FRETE | ✅ passed | 10 | 9 | — |
| R2 marca-zero-cautelosa | ❌ failed | 20 | 3 | DESCONTO | ✅ passed | 18 | 3 | — |
| R3 graos-proprios-pragmatico | ❌ failed | 20 | 4 | — | ❌ failed | 20 | **1** | — |
| R4 exploradora-contemplativa | n/a (timeout) | — | — | — | ✅ passed | 10 | 7 | — |
| R5 lojista-objecao-amostra | ❌ failed | 20 | 7 | — | ❌ failed | 7 | 9 | — |

---

## Análise por gap

### Gap B — Preço como compromisso (PRECO_FRETE) ✅ FECHADO
- Baseline: R1 disse "R$27,70", "R$46,70" → violação confirmada
- V2.1d: 0 violações em 5 runs. Regra 12 ("gira em torno de", nunca compromisso) funcionou.

### Gap C — Desconto improvisado (DESCONTO) ✅ FECHADO
- Baseline: R2 improvisou "R$44,90 já com embalagem" → violação confirmada
- V2.1d: 0 violações em 5 runs.

### Gap A — Não-handoff ⚠️ PARCIALMENTE RESOLVIDO
- Baseline: 3/4 personas bateram max_turns sem chamar `encaminhar_humano` (R2, R3, R5)
- V2.1d: apenas R3 ainda bate max_turns. R2 e R5 agora chamam `encaminhar_humano`.
- Pendente: R3 (graos-proprios-pragmatico) continua sem handoff — veja análise abaixo.

### Gap D — Alucinação de terceiros ⚠️ MELHOROU, NÃO FECHADO
- Baseline: R3 inventou 2 torrefações no RJ com nome, endereço e telefone (bot_score=4)
- V2.1d: R3 não inventou mais endereços/contatos, mas entrou em loop robótico com "imagina, sou eu mesma aqui do escritório" repetida 2× e frases de despedida genéricas. Bot_score **caiu para 1** — o pior resultado de todo o histórico.
- Diagnóstico: Regra 13 bloqueou a alucinação de terceiros ✅, mas o circuit breaker não disparou a tempo para evitar o loop de encerramento passivo ("fico no aguardo", "sou eu mesma aqui"). O bot tentou encerrar a conversa graciosamente e travou.

---

## Análise detalhada das falhas restantes

### R3 — graos-proprios-pragmatico (bot_score=1, max_turns=20)
**Motivo do fail:** `has_encaminhar_humano` = false
**Diagnóstico:**
- Lead quer comprar grão cru/saca, algo que o prompt instrui a passar para `encaminhar_humano(vendedor="Joao Bras")`.
- A Valéria reconheceu a limitação e tentou encerrar educadamente, mas entrou em loop de "fico no aguardo" / "sou eu mesma aqui do escritório" ao invés de chamar a tool.
- O circuit breaker adicionado em base.py não foi suficiente: o bot entendia que a conversa acabou e ficou respondendo mensagens do lead sem nunca executar `encaminhar_humano`.
- Frases robóticas repetidas: "imagina, sou eu mesma aqui do escritorio" (×2), "fico no aguardo, ate mais", "se precisar, sabe onde me encontrar".

**Correção necessária:** Em atacado.py, na seção "SITUACOES ADVERSAS > Cliente quer comprar grao cru ou saca de cafe", tornar a chamada `encaminhar_humano` mais explícita e imediata — o bot está reconhecendo o caso mas não executando a tool.

### R5 — lojista-objecao-amostra (bot_score=9, fails hard check)
**Motivo do fail:** `reached_private_label` = false
**Diagnóstico:**
- Lead mencionou "o café que eu vou por a minha marca" (turno 4) — deveria ter trigado `mudar_stage("private_label")`.
- Em turno 7, lead perguntou onde comprar fisicamente para provar antes de fechar. O bot chamou `encaminhar_humano` com motivo "cliente quer informação de ponto de venda físico" — não navegou para private_label.
- Apesar do fail no hard check, o bot tratou bem a objeção do Kit Amostra (bot_score=9). O fail é de **navegação de stage**, não de qualidade de atendimento.
- Linha problemática: "imagina, sou eu mesma aqui do escritório" — non-sequitur para pergunta sobre ponto de venda, classificada como resposta robótica fora de contexto.

**Correção necessária:** Adicionar trigger explícito para detectar "minha marca", "marca própria", "rótulo próprio" nas falas do lead dentro do fluxo atacado e chamar `mudar_stage("private_label")` antes de continuar.

---

## Novos insights (não estavam na baseline)

1. **"imagina, sou eu mesma aqui do escritório"** apareceu em R3 (×2) e R5 (×1) como resposta fora de contexto — claramente uma frase do sistema base que dispara erroneamente quando o lead questiona a identidade do bot. Candidata a remoção ou reformulação no base.py.

2. **R2 bot_score=3 persistente:** as regras duras funcionaram (sem violações), mas a qualidade de condução não melhorou. O juiz reporta: "falhou em responder perguntas diretas e repetidas sobre preço e demonstrou falta de memória contextual". Isso é um problema de contexto de LLM, não de prompt — pode ser ruído do teste ou indica que mais contexto precisa estar disponível.

3. **R4 rodou pela primeira vez** (timeout no baseline) e passou: 10 turnos, encaminhar_humano, bot_score=7.

---

## Conclusão da Fase 1

| Gap | Status |
|---|---|
| B — PRECO_FRETE | ✅ Fechado |
| C — DESCONTO | ✅ Fechado |
| A — Não-handoff | ⚠️ Parcial (R3 ainda falha) |
| D — Alucinação terceiros | ⚠️ Reduzido, não fechado |

**Ganho mensurável:** pass rate 0% → 60%. Violações de forbid zeradas. Max_turns de 3/4 para 1/5.

**Próximos alvos (Fase 2 sugerida):**
1. R3: tornar `encaminhar_humano` explícito e imediato no caso "grao cru / saca" — adicionar como ação obrigatória no próprio turno, não esperar o lead responder.
2. R5: adicionar trigger de private_label para expressões "minha marca" / "marca própria" no fluxo atacado.
3. Remover ou contextualizar "imagina, sou eu mesma aqui do escritório" no base.py — dispara erroneamente fora do contexto de pergunta sobre identidade.
