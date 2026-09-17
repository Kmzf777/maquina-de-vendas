# Aba de Funil no Modal de Lead — Design

**Data:** 2026-09-17
**Branch:** `feat/valeria-recuperacao-botoes` (trabalho novo sai em branch propria)
**Escopo:** frontend `/leads` + uma trava no `PATCH /api/deals/[id]`

---

## Problema

Na pagina `/leads`, nem ao criar nem ao editar um lead existe caminho para coloca-lo
num funil. Quem cadastra um lead ali precisa sair para `/vendas`, achar o lead de novo
no combobox do "Novo Card" e criar a oportunidade — um lead cadastrado em `/leads`
nasce fora do Kanban.

O modal de edicao tem hoje um bloco "Oportunidades" dentro de "Dados Gerais", mas ele
esta desatualizado em tres pontos:

1. Le a coluna legada `deals.stage` (texto) via Supabase no cliente, nao `stage_id`/
   `pipeline_stages`. O rotulo vem do array fixo `DEAL_STAGES`, entao uma etapa
   customizada de funil aparece como o texto cru `"novo"`.
2. Nao mostra a qual funil o card pertence. Com os funis do Joao (Vendas, Reposicao,
   Recuperacao...) a lista fica ambigua.
3. E somente leitura: nao da para mover o card nem trocar de etapa.

## O que ja existe (e vai ser reusado inteiro)

| Peca | Onde | Papel aqui |
|---|---|---|
| `GET /api/leads/[id]/deals` | `api/leads/[id]/deals/route.ts` | Cards do lead com `pipeline_stages` e `pipelines` embutidos |
| `buildDealRows`, `distinctPipelineIds`, `reopenPatch`, `isDealClosed` | `lib/deal-rows.ts` | Monta a linha por card e trata etapa-fora-do-funil, etapa de fechamento e etapas-ainda-nao-carregadas |
| `DealStageRow` | `components/conversas/deal-stage-row.tsx` | Linha com dropdown de etapa, "Reabrir", erro por linha |
| `DealCreateModal` | `components/deals/deal-create-modal.tsx` | Criacao de card com `preselectedLead`; funil + etapa + observacoes |
| `StageTargetPicker` | `components/deals/stage-target-picker.tsx` | Par funil+etapa consistente, com o guard `{pipelineId, stages}` do commit 02a6b54d |
| `POST /api/deals` | `api/deals/route.ts` | Ja valida acesso ao funil e que a etapa pertence a ele |
| `PATCH /api/deals/[id]` | `api/deals/[id]/route.ts` | Guard de escrita na origem e no destino; dispara `deal_stage_enter` |

A implementacao e essencialmente **composicao**: nenhum controle de UI novo e desenhado
do zero.

## Decisoes tomadas

| Questao | Decisao |
|---|---|
| Modal de **criacao** | Selects opcionais "Funil" e "Etapa" no fim do formulario atual. Sem abas — o form tem 8 campos e cabe numa tela. |
| Poderes da aba no modal de **edicao** | Criar card, trocar etapa, mover para outro funil. **Sem excluir card** (fora de escopo). |
| Bloco "Oportunidades" antigo | **Sai** de "Dados Gerais". A aba nova passa a ser o unico lugar onde funil/card aparece. O botao "Registrar Venda" fica onde esta. |
| Card duplicado no mesmo funil | **Avisa e deixa criar.** Nada no banco impede dois cards, e ha caso legitimo (dois pedidos no mesmo funil). |

## Arquitetura

```
leads/page.tsx
  ├─ fetch /api/pipelines ──────────► pipelines: Pipeline[]
  ├─ LeadCreateModal   (pipelines)  ── onCreate({ lead, funnel }) ─┐
  └─ LeadDetailModal   (pipelines)                                 │
       └─ aba "Funis" → LeadFunisTab (leadId, leadName, pipelines) │
            ├─ useLeadDeals(leadId) → { deals, stagesByPipeline,   │
            │                           refetch, updateDeal }      │
            ├─ buildDealRows ──► DealStageRow  (trocar etapa)      │
            ├─ LeadCardMoveRow  → StageTargetPicker (mover funil)  │
            └─ DealCreateModal(preselectedLead)  (criar card)      │
                                                                   │
POST /api/leads ──► lead.id ──► POST /api/deals ◄──────────────────┘
```

### 1. `lib/lead-funnel-actions.ts` (novo, logica pura)

Tres funcoes sem React e sem rede, com teste unitario:

```ts
/** Primeiro card ABERTO do lead no funil dado, ou null. Base do aviso de duplicata. */
export function findOpenDealInPipeline(deals: LeadDeal[], pipelineId: string): LeadDeal | null;

/** Titulo convencional do card: "<nome do lead> - <nome do funil>". */
export function buildDealTitle(leadName: string, pipelineName: string): string;

/** true quando o destino escolhido e onde o card ja esta — nao vale gastar um PATCH. */
export function isSameTarget(deal: LeadDeal, pipelineId: string, stageId: string): boolean;
```

`findOpenDealInPipeline` usa `isDealClosed` de `deal-rows.ts` — um card ja fechado
naquele funil **nao** gera aviso, porque criar um novo ali e justamente o fluxo normal
de recompra/reposicao. `buildDealTitle` centraliza o titulo que hoje esta inline em
`DealCreateModal` (`${leadName} - ${pipeline.name}`), para a criacao pelo modal de lead
gerar exatamente o mesmo formato.

### 2. `hooks/use-lead-deals.ts` (novo, camada de dados)

Encapsula o que hoje vive solto dentro de `contact-detail.tsx`:

```ts
export function useLeadDeals(leadId: string | undefined): {
  deals: LeadDeal[];
  stagesByPipeline: StagesByPipeline;
  refetch: () => Promise<void>;   // LANCA em falha
  updateDeal: (dealId: string, patch: Record<string, unknown>) => Promise<void>; // LANCA em falha
};
```

Regras que o hook preserva do original (cada uma existe por um bug real ja corrigido em
`contact-detail.tsx`, e as tres estao documentadas em comentario lado a lado no codigo de origem):

- **`reqId` monotonico:** dois PATCH quase simultaneos disparam dois refetch; o mais
  antigo chegando por ultimo reverteria a linha mais nova em silencio. Resposta obsoleta
  e descartada.
- **`refetch` e `updateDeal` lancam:** engolir 403 do guard de funil fazia o `<select>`
  voltar sozinho sem dizer por que. `DealStageRow` captura e mostra o erro na propria linha.
- **Carga inicial engole o erro** (`.catch(() => {})` em quem chama): nao ha acao a
  reverter nem linha onde exibir; o painel so fica sem oportunidades.

O hook busca etapas apenas dos funis que ja tem card: `distinctPipelineIds(deals)`. As
etapas de um funil de **destino** que o usuario abra no "Mover" nao sao
responsabilidade do hook — o `StageTargetPicker` busca as suas proprias etapas remotas.

`contact-detail.tsx` **nao** e refatorado para usar o hook nesta entrega. E um painel de
producao que o vendedor usa todo dia, o ganho e cosmetico e o risco nao e. Fica como
follow-up registrado no fim deste documento.

### 3. `components/leads/lead-funis-tab.tsx` (novo)

```
FUNIS DO LEAD                                   [+ Novo card]
──────────────────────────────────────────────────────────────
● Joao Silva - Vendas                              R$ 1.200
  Joao - Vendas
  [ Negociacao                    v ]        [ Mover ]

○ Joao Silva - Reposicao
  Joao - Reposicao
  [ Aguardando reposicao          v ]        [ Mover ]
──────────────────────────────────────────────────────────────
(vazio) "Este lead nao esta em nenhum funil."   [+ Novo card]
```

- A lista e `buildDealRows(deals, stagesByPipeline).map(row => <DealStageRow .../>)`.
- "Mover" expande, na propria linha, um `LeadCardMoveRow` com `StageTargetPicker`
  (`autoSelectFirstStage={false}`, `currentStageId={deal.stage_id}`) e os botoes
  Cancelar/Mover. Confirmar chama `updateDeal(deal.id, { pipeline_id, stage_id })`.
  Com `isSameTarget` verdadeiro o botao fica desabilitado.
- "+ Novo card" abre o `DealCreateModal` com `preselectedLead` e `pipelines`, e o
  `onCreate` chama `POST /api/deals` e depois `refetch()`.
- O aviso de duplicata mora no `DealCreateModal`: com `existingDealLookup` fornecido,
  ele exibe uma faixa de aviso nomeando o card e a etapa. Sem a prop, o modal se comporta
  exatamente como hoje (`/vendas` e `/conversas` nao mudam de comportamento).

### 4. `components/leads/lead-create-modal.tsx` (alterado)

Uma secao "Funil (opcional)" no fim do form, com `StageTargetPicker`. O contrato do
`onCreate` passa a separar as duas coisas:

```ts
onCreate: (payload: {
  lead: Record<string, string>;
  funnel: { pipeline_id: string; stage_id: string } | null;
}) => Promise<{ error?: string }>;
```

Sem funil escolhido, `funnel` e `null` e nada muda em relacao a hoje.

### 5. `leads/page.tsx` (alterado)

- Busca `/api/pipelines` uma vez e passa `pipelines` para os dois modais.
- `handleCreateLead` vira dois passos: `POST /api/leads` → pega `id` do 201 →
  se `funnel`, `POST /api/deals` com `buildDealTitle(nome, nomeDoFunil)`.

### 6. `api/deals/[id]/route.ts` (alterado — trava de servidor)

O `PATCH` nao confere que `stage_id` pertence ao `pipeline_id`. Hoje quem garante o par
e so o cliente (`StageTargetPicker`); esta entrega adiciona um **segundo** cliente que
move cards entre funis, e cinco bugs dessa forma exata — card desaparece do board de
destino — ja sairam em review neste repo.

Trava: quando o corpo traz `stage_id`, resolver o funil efetivo e confirmar que a etapa
pertence a ele. Se nao pertencer, **422** com mensagem legivel e nenhuma escrita. A
consulta que hoje busca `key` para decidir `closed_at` passa a buscar
`key, pipeline_id` — sem request extra.

A decisao de qual funil vale fica num modulo puro e testavel, fora da rota:

```ts
// lib/deal-patch-guard.ts
/** Funil que a etapa do corpo precisa respeitar: o destino, se houver; senao o atual. */
export function resolveEffectivePipelineId(
  body: { pipeline_id?: string | null },
  current: { pipeline_id: string | null }
): string | null;
```

## Fluxo de erro

| Falha | Comportamento |
|---|---|
| `GET /api/pipelines` falha | Selects de funil somem; criar lead e criar card seguem funcionando sem funil. A aba mostra "Nao foi possivel carregar os funis." |
| `POST /api/leads` falha | Mensagem no modal de criacao, como hoje. Nenhum card e criado. |
| Lead criado mas `POST /api/deals` falha | Modal fecha (o lead **existe**) e a pagina mostra: "Lead criado, mas nao foi possivel criar o card no funil." Nunca se reporta sucesso total. |
| `PATCH` de etapa/mover falha (403/422/500) | Erro na propria linha via `DealStageRow`/`LeadCardMoveRow`; o `<select>` volta a verdade do servidor sozinho. |
| `refetch` falha depois de um PATCH que funcionou | O erro sobe (o hook lanca) e aparece na linha; nao se finge que a mudanca nao pegou. |

## Testes

`jsdom` esta declarado no `package.json` mas **nao esta instalado** no `node_modules`
desta maquina, e os 2 arquivos `.test.tsx` existentes falham hoje na coleta
(`Cannot find package 'jsdom'`). Baseline medida antes de comecar: **60 arquivos, 786
testes verdes, 2 erros** de coleta por esse motivo.

Logo, os testes desta entrega sao `.test.ts` de logica pura no ambiente `node` — que e
o padrao dominante do repo — e nao dependem de jsdom:

- `lib/lead-funnel-actions.test.ts`
  - card aberto no funil → encontrado
  - card **fechado** no funil → `null` (fluxo de reposicao nao deve avisar)
  - card em outro funil → `null`
  - dois cards abertos no mesmo funil → devolve o primeiro
  - `buildDealTitle` com nome vazio cai no telefone; formato identico ao do `DealCreateModal`
  - `isSameTarget` true so quando funil **e** etapa coincidem
- `lib/deal-patch-guard.test.ts` — o resolvedor puro do funil efetivo
  (`body.pipeline_id ?? atual`) usado pela trava do `PATCH`, incluindo o caso de mover e
  trocar etapa no mesmo corpo.

Verificacao final obrigatoria: `npx tsc --noEmit`, `npm run lint` e `npx vitest run`
(esperado: 786 + novos testes verdes, os mesmos 2 erros de jsdom pre-existentes).

## Fora de escopo

- Excluir/desvincular card (nao pedido).
- Refatorar `contact-detail.tsx` para usar `useLeadDeals`.
- Instalar `jsdom` / consertar os 2 testes de componente pre-existentes.
- Filtrar `GET /api/leads/[id]/deals` por funil permitido. A rota usa service role e
  nao aplica `getAllowedPipelineIds`, entao um vendedor ve cards de funil alheio nesta
  aba — exatamente como ja ve hoje no painel de `/conversas`. Corrigir aqui mudaria o
  que `/conversas` mostra, o que e escopo proprio. **Fica registrado como divida.**

## Follow-ups

1. `GET /api/leads/[id]/deals` sem filtro de funil permitido (leitura fora de escopo do vendedor).
2. `contact-detail.tsx` duplica a logica de fetch que virou `useLeadDeals`.
3. `jsdom` ausente no `node_modules` deixa 2 testes de componente sem rodar.
