# Análise de Custo Unitário Global — Atendimento IA (Valéria)

**Data da análise:** 2026-07-12
**Analista:** Auditoria FinOps automatizada (read-only, produção)
**Fonte:** tabela `token_usage` do Supabase de produção (`tshmvxxxyxgctrdkqvam`), paginada via `.range()` para furar o teto `max-rows=1000` do PostgREST.

---

## 1. Data de Corte (descoberta via Git + GitHub Actions)

| Item | Valor |
|---|---|
| Commit do fix de precificação | `f5f7458` — `feat(finops): telemetria de cache + roteamento flash-lite + cartao de voz + harmonizacao de preco` |
| Commit criado | 2026-07-08 21:25:26 −03:00 |
| Deploy em produção (GitHub Actions, `success`) | 2026-07-09 00:21:13 UTC |
| **Corte usado na análise** | **2026-07-09 01:00:00 UTC** (margem de conclusão do deploy) |

Esse commit é o que mudou a **matemática do `total_cost`** (token_tracker.py): desconto de implicit caching (token cacheado = 25% do preço de input), colunas `cached_tokens`/`thoughts_tokens` (migração `20260708`), preços `gemini-2.5-*` versionados e roteamento de transcrição/dossiê para flash-lite. Antes dele o custo era **superestimado** nos hits de cache — por isso só dados pós-corte valem para unit economics. O fix de frontend do dashboard (`20f90ce`/`dbc29b8`, 11/07 — RPCs de agregação) foi ignorado conforme escopo: ele não muda a gravação do custo, só a leitura.

---

## 2. Volumetria analisada (2026-07-09 01:00 UTC → 2026-07-12 ~13h BRT)

| Métrica | Valor |
|---|---|
| Linhas de `token_usage` | 981 |
| Custo total do período | **$4,9151** |
| Leads distintos com algum custo | 354 |
| Linhas órfãs (sem `lead_id`) | 0 |

**Distinção metodológica crítica:** dos 354 leads com custo, **291 foram tocados apenas pelo worker de dossiê** (`rolling_summary` em `gemini-2.5-flash-lite`, ~$0,00014/lead, $0,0414 somados — 0,8% do custo total). Esses leads **não são atendimentos**. Um **atendimento real** foi definido como lead com ≥1 chamada da família `response*` ou `followup` (turno de conversa da IA) no período.

- **Atendimentos reais: 63 leads** — concentram $4,8737 (99,2% do custo).
- Segmentação Inbound × Outbound seguiu a regra de produção (`app/agent/persona.py`): outbound = conversa semeada por disparo `cold_reactivation` sem intervenção humana; caso contrário, inbound.

---

## 3. Unit Economics — custo por atendimento completo (USD)

### Global (63 atendimentos, Inbound + Outbound)

| Métrica | Valor |
|---|---|
| **Custo Médio (Average)** | **$0,0774** |
| **Mediana (P50)** | **$0,0714** |
| P90 | $0,1496 |
| P95 | $0,1788 |
| **Máximo** | **$0,2293** |
| **Mínimo** | **$0,0100** |

### Por segmento

| Segmento | N | Média | Mediana | Máximo | Mínimo |
|---|---|---|---|---|---|
| Inbound | 43 | $0,0909 | $0,0801 | $0,2293 | $0,0102 |
| Outbound (frios) | 20 | $0,0483 | $0,0233 | $0,2183 | $0,0100 |

O atendimento outbound custa **~metade** do inbound na média (conversas mais curtas — muitos leads frios respondem pouco). O inbound carrega conversas de qualificação longas.

### Distribuição (histograma dos 63 atendimentos)

| Faixa de custo | Atendimentos | % |
|---|---|---|
| $0,01 – $0,05 | 24 | 38% |
| $0,05 – $0,10 | 19 | 30% |
| $0,10 – $0,25 | 20 | 32% |
| ≥ $0,25 | **0** | 0% |

---

## 4. Análise de distorções (outliers)

**Não há outliers patológicos.** A tese "a média é alta porque 2 clientes custaram $2,00 em conversa infinita" **não se confirma**: o atendimento mais caro do período custou **$0,2293** (João Marcos Martins, inbound, 40 chamadas) e média ($0,0774) e mediana ($0,0714) estão praticamente coladas — assinatura de distribuição saudável, sem cauda pesada. O top 10 fica todo entre $0,138 e $0,229 e são conversas legitimamente longas (18–40 turnos), não loops.

Pontos de atenção reais encontrados nos dados:

1. **Retries = 10,4% do custo total.** `response_retry` ($0,352, 44 chamadas) + `response_retry2` ($0,157, 18 chamadas) somam $0,509. Cada retry re-paga o prompt inteiro (~30K tokens). É o maior alavancador de redução de custo disponível hoje.
2. **Pico diário em 11/07: $2,75** (vs. $0,81 em 09/07, $0,69 em 10/07, $0,66 em 12/07 parcial) — consistente com o volume de atendimentos auditados naquele dia, não com anomalia de precificação.
3. **Resíduo do incidente do falso sunset (09/07):** 15 chamadas em `gemini-3.5-flash` custaram $0,380 (7,7% do total) — custo por chamada ~4× o do 2.5-flash. Já revertido (`af58de8`); não recorre.
4. **Dossiê em flash-lite funcionou:** 430 chamadas de `rolling_summary` por $0,060 totais — o loop que inflava custo (pré-`53bcdf2`) segue morto.

### Custo por tipo de chamada (período completo)

| call_type | Chamadas | Custo | % do total |
|---|---|---|---|
| response | 418 | $4,2994 | 87,5% |
| response_retry | 44 | $0,3521 | 7,2% |
| response_retry2 | 18 | $0,1575 | 3,2% |
| rolling_summary | 430 | $0,0605 | 1,2% |
| qualification_summary | 31 | $0,0374 | 0,8% |
| media_transcription | 35 | $0,0049 | 0,1% |
| followup | 5 | $0,0034 | 0,1% |

---

## 5. Veredito

**O custo por atendimento está CONTROLADO.** Com média de **$0,077** e teto observado de **$0,23**, mesmo o pior atendimento custa menos de R$ 1,30 (câmbio ~5,5). A economia unitária comporta folga ampla para o funil B2B (um único pedido de atacado paga milhares de atendimentos). Não há vazamento de custo por conversa infinita; o único vetor de otimização material é a taxa de retry (10,4% do gasto).

## 6. Adendo — Conciliação da fatura de 11/07 (R$ 13,70)

Janela 11/07 no fuso BRT (11/07 03:00 UTC → 12/07 03:00 UTC), produção:

| Item | Valor |
|---|---|
| Custo rastreado (`token_usage`, cache-aware) | **$2,3943** |
| Homolog/dev (mesma GEMINI_API_KEY) | $0,00 (dev não rodou no dia) |
| Fatura reportada | R$ 13,70 |
| Conciliação | $2,39 × câmbio (~5,0–5,3) ≈ R$ 12,0–12,7 + impostos da fatura Google Brasil ≈ **R$ 13,7** ✓ |

**A fatura está 100% explicada pela telemetria — não há consumo fora do radar.** O dia foi o mais caro do período pós-fix por volume: 28 atendimentos reais (vs. média ~18/dia), 252 chamadas `response*`, 8,3M tokens de input.

**Anatomia do custo do dia (por que parece alto):**

- **Input = ~96% do custo.** Cada turno da IA custa ~$0,010 (≈33K tokens de prompt: persona ~30K + histórico + catálogo). Um atendimento médio tem 7–8 turnos → $0,0855 (≈ R$ 0,45–0,49 com impostos).
- **Cache hit de apenas 10,9%** (670K de 7,06M tokens de prompt nas chamadas `response`). O prefixo estático (`a7a287e`) mirava ~50% — o implicit caching do Gemini só dá hit se outra chamada com o mesmo prefixo ocorrer dentro do TTL (minutos), e a cadência esparsa de conversas reais raramente satisfaz isso. **Maior alavanca disponível: explicit context caching (TTL controlado) sobre o prefixo da persona → corta até ~65% do custo de input.**
- **Retries = 12,9% do custo do dia** ($0,308 — `response_retry` + `response_retry2`, este último com 0 tokens cacheados por rodar com temperatura/opções diferentes).

**Projeção de escala:** a R$ ~0,47/atendimento, 100 atendimentos/dia ≈ R$ 47/dia (R$ 1,4K/mês). Se o disparo em massa dos frios escalar, o custo cresce linear com a taxa de resposta — otimizar cache antes de escalar o volume.

### Ressalvas metodológicas

- Janela curta (3,5 dias). Atendimentos ainda ativos em 12/07 podem acumular custo adicional (o custo por lead é uma foto, não um filme fechado).
- Leads cujas conversas começaram **antes** do corte entram apenas com o custo pós-corte (subestimação marginal nesses casos).
- A classificação outbound ignora o escape hatch de intervenção humana apenas quando a intervenção ocorreu em conversa distinta da semeada pelo disparo (fidelidade ~total à regra de produção).
- `total_cost` já é cache-aware (desconto de 75% no token cacheado) — é o custo real faturável estimado, não o custo de tabela cheia.
