# Design/Spec — Context Caching e Enxugamento do Prefixo do Prompt

**Data:** 2026-07-27
**Branch:** `perf/gemini-context-caching`
**Origem:** Incidente de 5 dias com a Valéria muda (19–27/07) por estouro do teto de gasto mensal da Gemini API.

---

## Contexto

Em 27/07 a Valéria foi reportada como "off". A investigação encontrou:

- `GET /debug/agent` em produção retornava `429 RESOURCE_EXHAUSTED` com a mensagem
  `"Your project has exceeded its monthly spending cap."`
- Última resposta real da IA (`messages.sent_by='agent' AND role='assistant'`): **22/07 20:48 UTC**.
- Entre 23/07 e 27/07: **zero** respostas geradas. Nos dias 25 e 26/07 (fim de semana), zero
  respostas humanas também — 75 inbounds abandonados.
- **102 leads únicos** receberam handoff cego (`handoff_context` com *"Erro ao gerar resumo
  automático"*) entre 19/07 e 27/07 — o resumo de handoff também depende do LLM.

Após o usuário elevar o teto no AI Studio, o quadro mudou parcialmente:

| Chamada | Modelo | Tamanho | Resultado |
|---|---|---|---|
| `ping` de diagnóstico | `gemini-2.5-flash` | ~10 tok | ✅ OK |
| `rolling_summary` (workers) | `gemini-2.5-flash-lite` | ~570 tok | ✅ OK |
| **Turno real do agente** | `gemini-2.5-flash` | **~36.079 tok** | ❌ 429 em 12/12 tentativas |

Requisições pequenas passam; a do agente não. A falha é determinística (12 tentativas ao longo
de ~15 min, nenhuma passou), o que descarta pico de tráfego e aponta para **limite de taxa
(TPM) por requisição**, não mais para o teto de gasto.

---

## Medições (produção, tabela `token_usage`)

### Anatomia do turno do agente

Média real de `call_type='response'` no período saudável (13–18/07): **36.079 tokens de
entrada** para **47 tokens de saída** — razão de ~767:1.

| Bloco | Origem | Chars | Tokens (est. 4 ch/tok) | Estático? |
|---|---|---:|---:|---|
| `BASE_STATIC` | `prompts/base.py` | 81.544 | **~20.400** | ✅ idêntico em toda chamada |
| ├─ `<role>` | | 4.347 | ~1.090 | ✅ |
| ├─ `<constraints>` | | **44.916** | **~11.230** | ✅ |
| ├─ `<instructions>` | | 31.296 | ~7.820 | ✅ |
| └─ `<examples>` | | 8.222 | ~2.060 | ✅ |
| Prompt do stage | `prompts/valeria_*/` | ~25.900 | ~6.500 | ✅ por (prompt_key, stage) |
| Catálogo | tabela `products` | ~7.100 | ~1.800 | ✅ por setor |
| `FINAL_INSTRUCTION` | `prompts/base.py` | 259 | ~64 | ✅ |
| `<context>` + histórico + dossiê | runtime | — | ~7.400 | ❌ volátil |

**Achado que contraria a hipótese inicial:** o catálogo de produtos é responsável por apenas
~1.800 tokens (26 produtos em Atacado, 6 em Private Label). O peso real está em
`BASE_STATIC` — ~57% do turno inteiro — e dentro dele, em `<constraints>`.

### Eficácia do caching atual

O implicit caching **já está ativo** e a ordenação cache-first foi feita em 12/07
(FinOps P1, comentário em `build_system_prompt`). Taxa de acerto medida:

| Dia | Chamadas | Tokens in | Cached | Hit |
|---|---:|---:|---:|---:|
| 11/07 | 249 | 8.239.011 | 822.081 | 10,0% |
| 13/07 | 275 | 9.328.031 | 1.446.581 | 15,5% |
| 15/07 | 302 | 10.900.297 | 2.216.840 | 20,3% |
| 17/07 | 114 | 3.921.383 | 791.449 | 20,2% |
| 18/07 | 111 | 4.079.705 | 1.300.016 | 31,9% |

Teto teórico (todo o bloco estático): **~78%**. O hit médio real (~7.300 tokens) é **menor que
o próprio `BASE_STATIC`** (~20.400), que é byte-idêntico entre todas as chamadas. Conclusão: o
implicit caching não está retendo nem o prefixo comum.

**Causa provável:** o implicit caching é *best-effort* e depende do prefixo estar "quente". Com
~300 chamadas/dia distribuídas em ~10h e fragmentadas em até 10 variantes
(`prompt_key` × `stage`), cada variante recebe uma chamada a cada ~20 min — o cache esfria
entre turnos. Não há garantia contratual de retenção.

### Custo real

Julho inteiro (01–27/07), estimado com o tarifário público:

| Modelo | Tokens in | Cached | Tokens out | USD est. |
|---|---:|---:|---:|---:|
| `gemini-2.5-flash` | 77.644.644 | 11.883.757 | 482.331 | **21,29** |
| `gemini-2.5-flash-lite` | 859.289 | 0 | 222.793 | 0,18 |
| outros | 418.042 | 228.725 | 17.661 | 0,11 |

**Total: ~US$ 21,58/mês.** O teto que estourou era baixo — não houve consumo anômalo. O
kill-switch interno (`LLM_DAILY_COST_LIMIT_USD`, default **US$ 8/dia** ≈ US$ 240/mês) nunca
chegou perto de disparar, então **o teto do Google estourou sem que nenhuma proteção interna
percebesse**.

### Tarifário `gemini-2.5-flash` (padrão, pago)

| Item | Preço |
|---|---|
| Input | US$ 0,30 / 1M |
| Output (inclui thinking) | US$ 2,50 / 1M |
| **Input em cache (hit)** | **US$ 0,03 / 1M** (desconto de 90%) |
| **Storage de cache explícito** | **US$ 1,00 / 1M tokens / hora** |
| Mínimo p/ cache explícito (2.5 Flash) | 2.048 tokens |
| TTL default | 1 hora |

---

## Fato determinante: caching NÃO resolve o 429

A documentação do Google é explícita: *"There are no special rate or usage limits on context
caching; the standard rate limits for GenerateContent apply, and token limits include cached
tokens."*

**Tokens em cache continuam contando para o TPM.** Portanto:

| Objetivo | Caching resolve? |
|---|---|
| Reduzir custo (evitar estourar o teto de novo) | ✅ Sim — 90% de desconto no prefixo |
| Destravar o `429 RESOURCE_EXHAUSTED` atual | ❌ **Não** |

O 429 só é resolvido por (a) subir o tier do projeto — ação no console do Google, fora do
código — ou (b) **reduzir o número absoluto de tokens por requisição**. Esta spec cobre (b);
(a) é ação operacional do dono da conta.

---

## Brainstorming — alternativas avaliadas

Base de cálculo: 2.156 chamadas/mês (77,6M ÷ 36k), prefixo estático ~28.700 tokens
(`BASE_STATIC` + stage + catálogo), hoje com 15,3% já descontado pelo implicit.

### A) Cache explícito 24/7, um cache por (prompt_key, stage)

Até 10 caches × ~28.700 tok = 287k tokens residentes.
- Storage: 0,287M × 24h × 30d × US$1,00 = **US$ 206,64/mês**
- Economia máxima: ~US$ 17/mês
- **Veredito: descartado.** Prejuízo de ~10× o gasto atual total.

### B) Cache explícito 24/7, cache único de `BASE_STATIC`

1 cache × 20.400 tok (comum a todas as variantes).
- Storage: 0,0204M × 24h × 30d × US$1,00 = **US$ 14,69/mês**
- Economia: 2.156 × 20.400 × (0,30−0,03)/1M = US$ 11,87/mês
- **Veredito: descartado.** Líquido **negativo** (−US$ 2,82/mês).

### C) Cache explícito com TTL gerenciado (lazy create, só em tráfego)

Cache criado sob demanda, TTL de 1h renovado enquanto há tráfego; expira sozinho fora do
horário comercial e em fins de semana (medido: 25–26/07 tiveram tráfego de IA ~zero).
- Janela ativa estimada: ~10h/dia × 22 dias úteis = 220h/mês
- Storage: 0,0204M × 220h × US$1,00 = **US$ 4,49/mês**
- Economia: US$ 11,87/mês − US$ 3,21/mês (já obtido hoje pelo implicit) = US$ 8,66/mês
- **Líquido: ~+US$ 4,17/mês.** Positivo, porém modesto.
- **Ganho não-financeiro (o principal):** o hit deixa de ser 15% aleatório e vira ~57%
  **determinístico**. Previsibilidade é o que faltou no incidente.

### D) Enxugar o `BASE_STATIC`

Reduzir os 81.544 chars de persona/regras. Cada token cortado reduz **custo e TPM
simultaneamente** — é a única alavanca que toca o 429.
- Meta conservadora de 30% em `<constraints>` + `<instructions>`: ~5.700 tokens/chamada
- Economia: 2.156 × 5.700 × 0,30/1M = **US$ 3,69/mês**
- **TPM: −5.700 tokens por requisição (−16% do turno).**
- **Veredito: adotado.** Maior impacto por esforço, e é o único item que ataca o 429.

### E) Mover o catálogo para uma tool sob demanda

- Economia: ~1.800 tok/chamada → US$ 1,17/mês
- Custo: +1 round-trip de LLM quando o catálogo for necessário (que é a maioria dos turnos
  comerciais) — provavelmente **aumenta** o consumo total.
- **Veredito: descartado.**

### F) Não fazer nada e só monitorar

- Custo zero, mas o incidente se repete no próximo teto.
- **Veredito: descartado como solução única**, mas o alerta preventivo é incorporado ao
  escopo (ver Fase 3) — foi a ausência dele que custou 5 dias.

### Decisão

**C + D + alerta preventivo.** C entrega previsibilidade de custo; D entrega redução real de
tokens (custo + TPM); o alerta garante que o próximo estouro seja visto em horas, não em dias.

---

## Design

### Fase 1 — Enxugar `BASE_STATIC` — ❌ **ABANDONADA APÓS LEITURA INTEGRAL**

**Esta fase foi especificada, investigada e descartada com base na evidência.** O registro
fica aqui porque a conclusão é o entregável mais importante desta seção.

A hipótese era que 81.544 chars conteriam 25-30% de gordura consolidável. A leitura integral
de `<constraints>` e `<instructions>` **refutou isso**. O prompt é notavelmente denso:

- As regras são numeradas (1 a 35), específicas e mutuamente não-sobrepostas.
- **Praticamente toda regra cita o incidente real que a originou**, com identificação do lead
  e data: *"falha real do lead 5575992317829"* (vazamento de código de tool), *"falha real
  08/07: 'esse celular não é mais da magda' → lead renomeado 'Magda'"*, *"falha real: lead
  5561991573036 — CTA de handoff repetido 4x"*, *"falha real 02/07: lead recebeu 'vou te passar
  um cupom de 10%' e o cupom nunca veio"*, entre muitas outras.
- Não há prosa cerimonial, preâmbulo nem exemplo decorativo. O que parece repetição
  (proibição de vazar código em `<constraints>` e reforçada em `<instructions>`) é **reforço
  deliberado de prompt engineering** em ponto de aplicação — remover reduz aderência.

Duplicações genuínas existem, mas são pequenas: `"me diz uma coisa"` proibido em 3 lugares,
limite de `"!"` em 3, regra de ponto final em 2, anti-premissa em 2, identidade-IA em 3.
Somadas, ficam na casa de **3-6%** — não 25-30%.

**Cálculo do risco/retorno:** cortar 30% renderia US$ 3,69/mês. O custo potencial é
reintroduzir falhas que já queimaram leads reais (handoff fantasma, lead renomeado
indevidamente, CTA repetido, promessa sem entrega). **Não compensa.** Executar a Fase 1 como
escrita teria sido destruir valor com aparência de otimização.

**Recomendação para o futuro:** se a redução de tokens voltar a ser necessária (ex.: para
aliviar TPM), o caminho não é cortar regras — é mover as seções que só valem para um funil
específico do `BASE_STATIC` para os prompts de stage, onde já vivem os roteiros. Isso reduz o
prompt *por chamada* sem perder nenhuma regra do repertório. Trabalho para uma spec própria,
com validação de aderência dedicada.

### Fase 2 — Cache explícito gerenciado (atrás de flag)

Novo módulo `backend/app/agent/prompt_cache.py`:

```
get_or_create(model, static_prefix, ttl_seconds) -> str | None
```

- **Chave:** `sha256(model + static_prefix)[:16]` — muda o prefixo, muda o cache.
- **Estado:** dicionário em memória `{key: (cache_name, expires_at)}`. Sem Redis: o cache do
  Google é a fonte de verdade; a memória local é só um índice. Processos distintos criam
  caches distintos — aceitável (custo marginal, e o TTL os recolhe).
- **Lazy create:** só cria na primeira chamada que precisa. Fora de tráfego, nada é criado e
  nada é cobrado.
- **Piso de tokens:** não tenta criar cache abaixo de 2.048 tokens (rejeitado pela API).
- **Fail-open absoluto:** qualquer exceção → retorna `None` → `generate()` segue pelo caminho
  atual com `system_instruction` normal. **O cache nunca pode derrubar um turno.** Este é o
  mesmo princípio já adotado em `get_products_by_funnel`.

Integração em `gemini_client.generate()`: quando há cache válido, a chamada usa
`cached_content=<name>` e **não** envia `system_instruction` (a API trata o cache como prefixo
do prompt; enviar os dois é conflito). A parte volátil (`<context>`, histórico) segue em
`contents`.

**Risco conhecido e não resolvido pela documentação:** não está documentado se `tools` podem
ser enviadas no request quando `cached_content` está presente. O agente **sempre** usa tools.
Por isso:

- A flag `GEMINI_EXPLICIT_CACHE` nasce **`off`**.
- A validação com tools é feita em dev (`https://dev.canastrainteligencia.com`) antes de
  qualquer ativação em produção.
- Se a API rejeitar tools + `cached_content`, a Fase 2 é abandonada sem prejuízo — a Fase 1 e
  a Fase 3 entregam valor sozinhas.

### Fase 3 — Alerta preventivo de teto

O incidente durou 5 dias porque nada avisou. `_fire_llm_down_alert` existe (limiar de 3 falhas
consecutivas) mas não impediu o apagão. Escopo mínimo:

- Registrar no log, a cada turno, o gasto acumulado do dia e a taxa de cache hit.
- Alertar quando o gasto mensal projetado ultrapassar um limiar configurável — **antes** do
  teto do provedor, não depois.

---

## Critérios de aceite

1. ~~**Nenhuma regra perdida**~~ — sem objeto: a Fase 1 foi abandonada, `BASE_STATIC` está
   intocado. ✅ (por não-ação)
2. **Suíte verde:** ✅ **2.656 passaram, 3 skipped** — suíte completa de `backend/tests/`.
3. **Ordem cache-first preservada:** ✅ `test_finops_p0_p1_2026_07_12.py` verde; o corte
   estático/volátil respeita exatamente a fronteira estabelecida em 12/07.
4. ~~**Redução de 25% no `BASE_STATIC`**~~ — **descartado por evidência** (ver Fase 1).
5. **Fail-open comprovado:** ✅ `test_falha_na_criacao_devolve_none`,
   `test_cache_sem_name_devolve_none`, `test_leitura_do_mes_e_fail_open`.
6. **Flag desligada por padrão:** ✅ `test_flag_desligada_por_default` e
   `test_flag_off_nao_chama_api` — sem `GEMINI_EXPLICIT_CACHE=on`, a API nem é tocada e o
   comportamento é idêntico ao de hoje. O deploy é inerte até alguém ligar.
7. **Compatibilidade byte-a-byte:** ✅ `test_partes_concatenadas_sao_o_prompt_completo` —
   `build_system_prompt` continua devolvendo exatamente a mesma string de antes.
8. **Alerta mensal armado:** ✅ `test_limiar_nasce_armado` + dedup 1x/mês.

---

## Riscos

| Risco | Mitigação |
|---|---|
| Enxugar o prompt degrada a qualidade da Valéria | Inventário 1:1 + suíte de aderência; validação em dev antes do push |
| `tools` incompatíveis com `cached_content` | Flag `off` por padrão; validar em dev; Fase 2 é descartável |
| Cache explícito derruba turno em produção | Fail-open absoluto: exceção → `None` → caminho atual |
| Storage do cache custar mais que a economia | TTL gerenciado (alternativa C); alternativas A e B já descartadas por cálculo |
| Regressão silenciosa no hit de cache | Registrar hit rate no log por turno (Fase 3) |

---

## Fora de escopo

- **Subir o tier do projeto no Google AI Studio** — é o que realmente destrava o 429 atual, mas
  é ação no console do provedor, não em código.
- **Recuperar os 102 leads** que receberam handoff cego — trabalho separado; existe
  `backend/scripts/recover_valeria_warm_leads.py` como ponto de partida.
- **Corrigir a classificação do 429 de teto mensal** (hoje cai em `LLMUnavailableError`
  genérico → parking de 30 min → handoff cego, em vez de exaustão longa). Bug real, encontrado
  na mesma investigação, mas independente desta spec.
