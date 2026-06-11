# SLA por Vendedor — Design

**Data:** 2026-06-11
**Status:** Aprovado

## Problema

O SLA hoje é medido só para o canal do João (`JOAO_CHANNEL_ID` hardcoded) e tem dois
defeitos de cálculo que tornam a métrica imprecisa, além de não suportar janela por
vendedor nem exclusão de períodos (folgas, viagens, feriados).

### Defeito 1 — âncora errada (subestima a espera)

`use-joao-sla-stats.ts` (`computePairs`) ancora o relógio na **última** mensagem do
cliente antes da resposta. Quando o cliente manda uma rajada, a espera real é
subnotificada:

```
10:00  cliente: "oi"
10:10  cliente: "alguém aí?"
10:30  vendedor responde
```

Espera real = 30 min. Cálculo atual = 20 min (mede de 10:10).

A RPC `get_seller_overdue_candidates` tem o mesmo defeito, e pior no "em atraso":
usa `MAX(mensagem do cliente)` como âncora, então um lead sem resposta desde 10:00
que recebe um "?" às 15:00 é medido a partir das 15:00 — o atraso some.

### Defeito 2 — janela e alvo fixos

Janela 10–16h e threshold de 20 min são constantes no código. Não há janela por
vendedor nem como anular dias.

## Decisões de produto

- **Vendedor** = usuário Supabase com `role=vendedor`, vinculado a **1 canal** (1:1).
- **Janela individual** por vendedor (horário início/fim + dias da semana), configurada
  em `/config` (somente admin).
- **Anulações** por **dias inteiros** (intervalo de datas), escopo **por vendedor OU
  global** (ex: feriado).
- **Efeito da anulação:** o dia anulado conta **0 minutos comerciais**, tanto no
  histórico (pares que o atravessam) quanto ao vivo. Justificativa: gestão justa —
  o vendedor não é punido por ausência autorizada.
- **Alvo de SLA** (limite de atraso): **configurável global** (default 20 min).
- **Pior SLA:** **inclui rodadas abertas** (conversas ainda sem resposta), não só
  fechadas. Expõe o pior caso real em vez de escondê-lo.
- **Dashboard:** tabela por vendedor + linha de total.

## Definição central — a "rodada de espera"

Média, atraso e pior caso saem do **mesmo** conceito, calculado num único passe
cronológico por conversa.

> **Rodada de espera** = começa na **primeira** mensagem do cliente ainda não
> respondida e termina na **primeira** resposta do vendedor (mensagem do vendedor
> *ou* clique em "Finalizar"). Mensagens repetidas do cliente dentro da mesma rodada
> **não** reiniciam o relógio. Todo o tempo é contado em **minutos comerciais** da
> janela daquele vendedor, com os dias anulados valendo 0.

Algoritmo (um passe por conversa, mensagens `user`/`seller` em ordem cronológica):

```
estado: esperando = falso, inicioEspera = null

msg do cliente (user):
    se NÃO esperando → esperando = true, inicioEspera = horário
    (se já esperando, ignora — mantém a primeira)

msg do vendedor (seller):
    se esperando → registra businessMinutes(inicioEspera, horário); esperando = false
    (se não esperando → msg proativa, ignora)

fim das mensagens:
    se ainda esperando:
        se conv.last_seller_response_at > inicioEspera (botão Finalizar)
            → registra par fechado businessMinutes(inicioEspera, last_seller_response_at)
        senão
            → rodada ABERTA: decorrido = businessMinutesElapsed(inicioEspera)
```

Derivações, por vendedor:

- **Tempo médio de resposta** = média dos minutos comerciais das rodadas **fechadas**
  no período.
- **Lead em atraso de atendimento** = rodada **aberta** cujo decorrido comercial
  ultrapassa o **alvo global** (default 20 min).
- **Pior SLA** = maior valor entre rodadas fechadas **e** abertas no período.

Mensagens `agent` (IA) e outras (`handoff_context` etc.) são ignoradas — mede-se o
trabalho do vendedor humano, e os canais de vendedor operam em `mode='human'`.

### Limitação conhecida

Um cliente que manda "obrigado!" após ser atendido abre uma rodada nova e pode
aparecer como "em atraso". Não é resolúvel sem detecção de intenção. Mitigação: botão
**Finalizar** (vendedor fecha → rodada não fica aberta). Comportamento mantido.

## Modelo de dados (3 tabelas novas)

### `sla_seller_config` — uma linha por vendedor

| coluna | tipo | nota |
|---|---|---|
| `user_id` | uuid PK | usuário Supabase role=vendedor |
| `channel_id` | uuid UNIQUE NOT NULL | canal dele (1:1) |
| `display_name` | text | nome exibido no dashboard |
| `window_start_minute` | int NOT NULL default 600 | 10h00 |
| `window_end_minute` | int NOT NULL default 960 | 16h00 |
| `active_weekdays` | int[] NOT NULL default `{1,2,3,4,5}` | 0=dom…6=sáb |
| `active` | bool NOT NULL default true | se é medido |
| `created_at` / `updated_at` | timestamptz | |

### `sla_settings` — singleton

| coluna | tipo | nota |
|---|---|---|
| `id` | int PK CHECK (id = 1) | linha única |
| `target_minutes` | int NOT NULL default 20 | alvo global de atraso |
| `updated_at` | timestamptz | |

### `sla_overrides` — anulações (dias inteiros)

| coluna | tipo | nota |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid **nullable** | `null` = global (todos) |
| `start_date` | date NOT NULL | inclusivo (SP) |
| `end_date` | date NOT NULL | inclusivo (SP) |
| `reason` | text | folga / viagem / feriado |
| `created_by` | uuid | admin que criou |
| `created_at` | timestamptz | |

> Dia D é anulado para vendedor V se existe override com
> (`user_id = V` OU `user_id IS NULL`) e `start_date ≤ D ≤ end_date`, datas em SP.

**RLS:** SELECT liberado para autenticados (dashboard lê via supabase client). Escrita
apenas via rotas admin (service role, padrão `set-role`). Migration faz **seed** da
config do João (`a3a607b1-6bff-4370-8609-b275eef270dd`, janela 600/960, seg–sex) para
não regredir.

## Motor de cálculo — `business-hours.ts` parametrizado

As constantes `BIZ_START_MIN`/`BIZ_END_MIN`/seg–sex viram parâmetros opcionais. Assinatura:

```ts
interface BusinessWindow {
  startMin: number;            // minutos desde meia-noite (default 600)
  endMin: number;              // default 960
  weekdays: Set<number>;       // 0=dom…6=sáb (default {1,2,3,4,5})
  excludedDates: Set<string>;  // 'YYYY-MM-DD' em SP → 0 min (default vazio)
}

businessMinutesBetween(from: Date, to: Date, win?: BusinessWindow): number
businessMinutesElapsed(from: Date, win?: BusinessWindow): number
```

Em `bizMinutesInSegment`: usa `win.startMin`/`win.endMin`; checa `win.weekdays`; e
**se a data SP do dia ∈ `win.excludedDates`, retorna 0**. Sem `win`, usa o default
(preserva o caso canônico testado sex 15h55 → seg 10h10 = 15 min).

`excludedDates` por vendedor = expansão dos overrides (dele + globais) em datas
individuais SP. Intervalos são curtos; expansão é barata.

## Hook `useSlaStats` (substitui `useJoaoSlaStats`)

Por vendedor em `sla_seller_config` (active):
1. Monta `BusinessWindow` a partir da config + overrides expandidos.
2. Busca conversas + mensagens (`sent_by IN ('user','seller')`) do `channel_id`
   (paginação existente).
3. Roda o passe único → rodadas fechadas e abertas.
4. Calcula `{ avgMinutes, overdueCount, worstMinutes }` (worst inclui abertas;
   overdue = abertas com decorrido > `target_minutes`).
5. Agrega a linha de total.

Mantém realtime (`conversations`, `messages`) + ticker de 60s ("em atraso agora"
avança com o tempo). A RPC `get_seller_overdue_candidates` fica **obsoleta** — o passe
único já calcula o atraso com a âncora correta — e é **removida**.

## UI do `/config` — nova aba "SLA" (admin)

Aba `{ key: "sla", label: "SLA" }` em `config/page.tsx`, componente `sla-tab.tsx`,
visível/funcional só para `role=admin` (lê `app_metadata.role` do usuário logado).

- **A. Vendedores** — lista das configs. Por linha: `display_name`, canal (dropdown),
  janela (time picker início/fim + toggles de dia da semana), toggle `active`.
  "Adicionar vendedor": escolhe usuário `role=vendedor` (endpoint admin) + canal.
- **B. Alvo de SLA** — input de minutos (default 20) → `sla_settings`.
- **C. Anulações** — lista de overrides com adicionar/remover. Item: escopo
  (Global / vendedor X), data início, data fim, motivo. Ordenada por data.

## Dashboard — `SlaTable` (substitui `SlaHeroSection`)

Tabela por vendedor + total, com filtro de período (1d/7d/30d/tudo):

| Vendedor | Média resp. | Em atraso agora | Pior SLA |
|---|---|---|---|
| João | 12min | 1 | 2h15m |
| Maria | 8min | 0 | 45min |
| **Total** | **10min** | **1** | **2h15m** |

"Em atraso agora" em vermelho quando > 0. Vendedor com folga ativa hoje aparece neutro
(anulação zera). Formatação via `formatBusinessDuration`.

## Rotas admin (Next API, service role, gated — padrão `set-role`)

- `GET/POST /api/admin/sla/config` — listar/upsert configs de vendedor
- `GET /api/admin/sla/vendedores` — usuários `role=vendedor` (Supabase admin API)
- `GET/PUT /api/admin/sla/target` — alvo global
- `GET/POST/DELETE /api/admin/sla/overrides` — anulações

Leituras do dashboard: direto via supabase client (3 tabelas + conversas/mensagens).

## Migrations

1. Criar `sla_seller_config`, `sla_settings`, `sla_overrides` + índices + RLS.
2. Seed: config do João + linha singleton de `sla_settings` (target 20).
3. `DROP FUNCTION get_seller_overdue_candidates`.

## Testes

- **`business-hours`**: janela parametrizada (start/end/weekdays), `excludedDates`
  zerando dias, caso canônico sex→seg intacto com default.
- **Passe unificado**:
  - colapso de rajada → ancora na primeira sem resposta;
  - rodada aberta vira atraso quando decorrido > alvo;
  - fallback Finalizar (`last_seller_response_at`);
  - msg proativa do vendedor (sem espera aberta) ignorada;
  - anulação zerando um dia que um par atravessa;
  - pior SLA considerando rodada aberta.

## Casos de borda

- Primeira msg da conversa é do vendedor (outbound) → sem rodada até o cliente responder.
- Cliente manda várias antes de resposta → uma rodada, ancorada na primeira.
- Vendedor manda várias respostas → só a primeira fecha a rodada.
- Par atravessa dia anulado → aquele dia conta 0.
- "obrigado!" após resolvido → pode abrir rodada (limitação; mitigada por Finalizar).
