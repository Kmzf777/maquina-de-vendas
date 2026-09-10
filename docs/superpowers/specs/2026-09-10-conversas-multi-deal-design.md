# /conversas — painel do lead com múltiplas oportunidades

**Data:** 2026-09-10
**Escopo:** frontend apenas. Sem migration, sem backend, sem tocar no Kanban (`/vendas`).

---

## 1. Problema

O painel lateral de `/conversas` (aba **Perfil**) tem hoje duas seções que falam da mesma
entidade:

- **Estágio** — permite trocar o stage de **um** deal, escolhido implicitamente.
- **Oportunidades** — lista **todos** os deals do lead, somente leitura.

O sistema permite (e usa) mais de um deal ativo por lead: o ciclo de reposição pós-venda
cria um card no funil do João enquanto o card de atacado da ValerIA segue aberto. O painel
mostra 3 cards e deixa editar 1.

### Os três defeitos concretos

1. **Deals irmãos no mesmo funil ficam inalcançáveis.**
   `crm-perfil-tab.tsx:73` — `dealForSelectedPipeline` casa o deal por `pipeline_id`, não
   por `id`. Dois deals abertos no mesmo funil → só o primeiro do array é editável; o
   segundo não tem como ser alcançado por nenhuma interação da tela.

2. **Deal fechado não tem volta.**
   O filtro `CLOSED_KEYS` (`crm-perfil-tab.tsx:46`) exclui deals em `fechado_ganho` /
   `fechado_perdido` do editor. Não existe caminho no `/conversas` para reabrir um card
   perdido — o vendedor precisa sair da conversa e ir ao Kanban.

3. **O select "Funil" mente.**
   Ele parece mover o deal de funil; na verdade só troca qual deal está sendo editado.
   Trocar para um funil onde o lead não tem card exibe *"Sem deal neste funil"*, que o
   vendedor lê como "perdi o card".

### Defeito adjacente encontrado na investigação

`contact-detail.tsx:139` — `handleDealStageChange` faz `if (res.ok) await fetchDeals()`.
Erro de rede, 500 ou **403 do guard de permissão de funil**
(`assertCanWriteDealsInPipeline`) são engolidos em silêncio: o select volta ao valor antigo
sem explicação. Com N deals de funis diferentes editáveis na mesma lista, esse silêncio
deixa de ser tolerável.

---

## 2. Decisões

| Questão | Decisão |
|---|---|
| Multi-deal ativo é bug de dados ou de UI? | **De UI.** Multi-deal ativo é comportamento legítimo. Nada de guard no backend. |
| Como editar vários deals? | **Stage inline por card.** Uma seção só, cada deal com seu próprio dropdown. |
| Deals fechados? | **Read-only + botão "Reabrir".** Fechar um deal continua sendo pelo Kanban. |
| Onde fica "Atribuído a"? | **Bloco Identificação** — é campo do lead, não do deal. |

O motivo de não trazer o fechamento para a sidebar: mover para `fechado_perdido` exige
motivo (`LostReasonModal`, regra do Kanban em `vendas/page.tsx:193`). Importar essa regra
para um painel de 320px duplica superfície de negócio por pouco ganho.

---

## 3. Desenho

### 3.1 Ordem nova do painel

```
Oportunidades          ← nova seção fundida (era Estágio + Oportunidades)
Vendas
Orçamentos
Identificação          ← + campo "Atribuído a" no fim
Empresa B2B
Tags
Cadências
```

As seções **Estágio** e **Oportunidades (read-only)** deixam de existir separadamente.

### 3.2 Anatomia da seção

```
┌────────────────────────────────┐
│ OPORTUNIDADES              [+] │
│                                │
│ ● Atacado 60kg      R$ 4.200   │   deal aberto
│   Valeria - Atacado            │
│   [ Qualificação          ▾ ]  │
│                                │
│ ● Reposição Café    R$ 1.100   │   deal aberto, outro funil
│   João - Reposição             │
│   [ Negociação            ▾ ]  │
│                                │
│ ○ Atacado 20kg      R$ 900     │   deal fechado
│   João - Reposição             │
│   Fechado/Perdido    [Reabrir] │
│   ⤷ motivo: preço alto         │
└────────────────────────────────┘
```

Ordenação: **abertos primeiro** (por `updated_at` desc), fechados depois (por `updated_at`
desc). O trabalho vivo fica no topo; o histórico não empurra o que importa para baixo.

### 3.3 Regras por linha

- **Aberto** (stage não protegido) — dot na `dot_color` do stage; `<select>` com os stages
  **não-protegidos daquele funil**. Troca otimista: o select muda na hora, e em falha
  reverte para o valor anterior e mostra o erro em vermelho **dentro da linha**.
- **Fechado** (stage protegido) — dot vazado, opacidade reduzida, stage como texto,
  `lost_reason` embaixo quando houver, botão **Reabrir**.
- **Sem `pipeline_id`** — read-only, rótulo "Sem funil". Não há stages para oferecer.

O estado de `salvando`/`erro` é **por linha**, nunca global: com N deals visíveis, um 403
em um funil não pode borrar o painel inteiro.

### 3.4 Patch de reabertura

`PATCH /api/deals/[id]` grava `closed_at` ao entrar em stage protegido
(`deals/[id]/route.ts:75`) mas **nunca limpa ao sair**. Como o botão "Reabrir" é novo, ele
seria a origem de dados sujos. O patch envia:

```json
{ "stage_id": "<1º stage não-protegido por order_index>", "closed_at": null, "lost_reason": null }
```

O route faz `{...body}` no update, então isso funciona **sem tocar no backend**.

### 3.5 Stages de N funis

Hoje o componente busca os stages de **um** pipeline. A lista nova precisa dos stages de
cada funil distinto presente nos deals do lead. Um hook resolve: deduplica os
`pipeline_id`, dispara um fetch por funil em paralelo, guarda em cache por `pipeline_id`
(troca de conversa dentro do mesmo funil não refaz o fetch) e aborta no unmount.

---

## 4. Unidades

O projeto tem um idioma claro e ele será seguido: **lógica pura em `src/lib/*.ts` com
`.test.ts` ao lado, componente fino**. O vitest roda em `environment: "node"` e coleta
apenas `src/**/*.test.ts` — **não existe teste de componente React neste repositório**.
`src/lib/quote-modal-state.ts`, já consumido por esta mesma aba, é o precedente.

| Arquivo | Responsabilidade | Depende de |
|---|---|---|
| `src/lib/deal-rows.ts` *(novo)* | Puro. Ordena os deals, classifica aberto/fechado, monta as opções de stage por funil, resolve o stage de reabertura e o patch. | tipos apenas |
| `src/lib/deal-rows.test.ts` *(novo)* | Cobre o acima, incluindo dois deals abertos no mesmo funil. | vitest |
| `src/hooks/use-pipeline-stages.ts` *(novo)* | Busca stages de N funis, cache por `pipeline_id`, abort no unmount. | `/api/pipelines/[id]/stages` |
| `src/components/conversas/deal-stage-row.tsx` *(novo)* | Apresentação de uma linha + estado `salvando`/`erro` local. | `deal-rows.ts` |
| `src/components/conversas/tabs/crm-perfil-tab.tsx` | Remove as 2 seções antigas, insere a nova no topo, move "Atribuído a". ~453 → ~330 linhas. | acima |
| `src/components/conversas/contact-detail.tsx` | `handleDealStageChange` → `handleDealUpdate(dealId, patch)`, que **lança** em falha. | — |

`LeadDeal` ganha `lost_reason: string | null` — a API já devolve o campo
(`leads/[id]/deals/route.ts:14`), o tipo é que não o declarava.

### Contrato de `onDealUpdate`

```ts
onDealUpdate: (dealId: string, patch: Record<string, unknown>) => Promise<void>
```

Resolve em sucesso; **lança `Error` com mensagem legível** em falha. A linha captura e
exibe. Substitui `onDealStageChange` na prop pública de `ContactDetail` — nenhum consumidor
externo passa essa prop hoje (`conversas/page.tsx` usa as duas instâncias sem informá-la).

---

## 5. Critérios de aceite

1. Lead com **dois deals abertos no mesmo funil**: ambos aparecem, ambos com dropdown
   próprio, e trocar o stage de um não altera o outro.
2. Lead com deals em **funis diferentes**: cada linha oferece os stages do **seu** funil.
3. Deal **fechado**: sem dropdown; "Reabrir" o devolve ao primeiro stage ativo e limpa
   `closed_at` e `lost_reason`.
4. PATCH que falha (403/500): o select **reverte** e a mensagem aparece **naquela linha**;
   as demais linhas seguem intactas.
5. A seção Oportunidades está **acima** de Vendas; "Estágio" não existe mais; "Atribuído a"
   está em Identificação.
6. Lead **sem nenhum deal**: mensagem "Nenhuma oportunidade" + botão de criar.
7. `npm run test`, `npm run lint` e `npm run type-check` verdes.

---

## 6. Fora do escopo — reportado, não corrigido

1. **`GET /api/leads/[id]/deals` não filtra por permissão de funil.** Usa service client
   direto, enquanto `GET /api/deals/[id]` aplica `getAllowedPipelineIds`. O painel já
   exibe deals de funis que o vendedor não pode acessar; tornando-os editáveis, o 403 que
   antes era invisível passa a aparecer. O erro inline expõe isso honestamente em vez de
   mascarar — mas a inconsistência de escopo de leitura permanece.
2. **`closed_at` sujo ao arrastar um card de volta no Kanban.** Mesmo defeito de origem;
   corrigido apenas no caminho novo do "Reabrir".
3. **`dedupe_open` não é escopado por funil** (`leads/service.py:1117`) — reaproveita
   qualquer deal aberto do lead, o que já colocou cards de reposição no funil errado.
   Problema de backend, independente deste trabalho.
