# Mover deal de funil e etapa — individual e em massa

**Data:** 2026-09-11
**Branch:** `worktree-feat-deal-move-pipeline-stage` (worktree isolado)
**Escopo:** frontend apenas. Sem migration, sem backend.

---

## Problema

O Kanban de `/vendas` só move um card com drag-and-drop, e só **dentro do funil aberto**. Para
levar um deal para outro funil não existe caminho na tela: hoje seria excluir e recriar o card.

Existe um bulk move escondido no menu `···` do cabeçalho de cada coluna
(`bulk-move-deals-modal.tsx`): ele abre uma lista de checkboxes com os deals **daquela coluna** e
move para outra etapa **do mesmo funil**. É pouco descobrível, não cruza colunas e não cruza funis.

## Objetivo

1. No modal de detalhes do deal, poder trocar **funil e etapa**.
2. No board, um modo de seleção em massa que move os selecionados para **outro funil e etapa**.

---

## Decisões tomadas

| Questão | Decisão |
|---|---|
| Bulk existente no menu `···` da coluna | **Substituído.** Remove o menu e o `bulk-move-deals-modal.tsx`. O "Editar Deals" vira o caminho único. |
| Etapas protegidas (Ganho/Perdido) como destino | **Não.** Só etapas ativas. Fechar deal continua sendo drag individual (que pede motivo) ou "Finalizar Venda". |
| Troca de funil/etapa no modal de detalhes | Dentro do formulário do botão **Editar**, aplicada no **Salvar**. Não instantânea. |
| Automações (`deal_stage_enter`) no bulk | **Disparam normalmente**, igual a arrastar card por card. O diálogo avisa. |

---

## O que já existe e não precisa mudar

`PATCH /api/deals/[id]` já atende os dois fluxos sem alteração:

- aceita `pipeline_id` e `stage_id` no mesmo corpo;
- exige permissão de escrita no funil de **origem** e, se houver troca de funil, também no de
  **destino** (`assertCanWriteDealsInPipeline`, `frontend/src/app/api/deals/[id]/route.ts:56-64`);
- seta `closed_at` quando a etapa nova é protegida;
- dispara `deal_stage_enter` no backend quando a etapa muda.

`GET /api/pipelines/[id]/stages` devolve as etapas de qualquer funil — é o que o
`deal-create-modal` já usa para popular o select de etapa.

`usePipelines()` lê a tabela `pipelines` pelo client do browser, então o RLS já limita a lista aos
funis que o usuário enxerga. Nenhum gate de `isAdmin` é necessário: mover em massa é exatamente o
mesmo poder que arrastar um card, só que mais rápido, e a API valida cada PATCH no servidor.

---

## Parte A — Modal de detalhes do deal

**Arquivo:** `frontend/src/components/deals/deal-detail-sidebar.tsx`

### Interface

Nova prop `pipelines: Pipeline[]` (a página `/vendas` já tem essa lista).

No formulário de edição, **acima de "Observacoes do Lead"**, um bloco novo:

```
ETAPA DO FUNIL
Funil   [ João - Reposição      v ]
Etapa   [ Negociação            v ]
```

### Comportamento

- **Funil** começa em `deal.pipeline_id`. Lista `pipelines` ordenada como vem do hook.
- **Etapa** começa em `deal.stage_id`.
- Trocar o funil dispara `fetch("/api/pipelines/{id}/stages")` com `AbortController`, mesmo padrão
  do `deal-create-modal.tsx:35-49`. Enquanto carrega, o select fica `disabled` com texto
  "Carregando...". Ao chegar, filtra `!is_protected` e seleciona a **primeira** etapa.
- Se o funil escolhido é o **atual do deal**, usa a prop `stages` que a página já passa — sem
  fetch.
- Opções da etapa = etapas não-protegidas. **Exceção:** se a etapa atual do deal for protegida
  (deal já fechado), ela entra na lista para o select mostrar o valor real em vez de mentir
  apontando para outra etapa.
- **Cancelar** (sair do modo edição) restaura funil e etapa para os valores do deal.

### Salvar

`handleSave` inclui no payload do `onUpdate` apenas o que mudou:

- `stage_id` se `form.stage_id !== deal.stage_id`
- `pipeline_id` se `form.pipeline_id !== deal.pipeline_id`

Se nada mudou, o payload fica igual ao de hoje.

### Erro

`handleUpdateDeal` em `vendas/page.tsx` hoje lança `new Error("Erro ao atualizar deal")`, jogando
fora a mensagem da API. Passa a ler `body.error` da resposta e repassar. Assim um vendedor que
tenta mover para um funil de outra pessoa lê **"Permissão insuficiente para este funil."** em vez
de um erro genérico. O `saveError` do sidebar já renderiza a mensagem.

### Fechamento

`handleUpdateDeal` já faz `setSelectedDealId(null)` no sucesso. Mantém: depois de mover para outro
funil o card sai do board aberto de qualquer forma.

---

## Parte B — Modo "Editar Deals"

### B1. Botão e estado

**Arquivo:** `frontend/src/app/(authenticated)/vendas/page.tsx`

Estado novo:

```ts
const [selectionMode, setSelectionMode] = useState(false);
const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
const [showBulkMove, setShowBulkMove] = useState(false);
```

Header, ao lado do `+ Novo Card`:

| Estado | Botões |
|---|---|
| Normal | `[Editar Deals]` (contorno) `[+ Novo Card]` (preto) |
| Seleção | `[Cancelar]` (contorno) `[Mover (N)]` (preto) |

- `Editar Deals` → `setSelectionMode(true)`.
- `Cancelar` → `setSelectionMode(false)` + `setSelectedIds(new Set())`.
- `Mover (N)` → `disabled` quando `N === 0`, com `title="Selecione ao menos 1 deal"`. Com N ≥ 1,
  abre o diálogo.

Trocar de funil no `PipelineSwitcher` enquanto o modo está ligado **limpa a seleção e sai do
modo** — os ids selecionados são de outro board e mover às cegas seria surpresa.

### B2. Cards em modo seleção

**Arquivo:** `frontend/src/components/deals/deal-card.tsx`

Props novas, ambas opcionais para não quebrar o `DragOverlay` que renderiza `DealCard` solto:

```ts
selectable?: boolean;
selected?: boolean;
```

O `DealCard` já é um `<button>`. **Não** usar `<input type="checkbox">` dentro dele (interativo
aninhado é HTML inválido e o clique se perde). Em vez disso, quando `selectable`, renderiza um
quadrado de 16px à esquerda do título — borda `#dedbd6` vazia, ou fundo `#111111` com um check
branco quando `selected` — e o próprio botão recebe `aria-pressed={selected}`. Selecionado ganha
`border-[#111111]` para leitura à distância.

Em modo seleção, `onClick` do card **alterna a seleção** em vez de abrir o sidebar.

`DraggableDealCard` não aplica `useDraggable` quando `selectionMode` está ligado: sem isso o
`PointerSensor` compete com o clique e arrastar por engano moveria um card no meio da seleção.

### B3. Selecionar todos da coluna

No cabeçalho de cada `DroppableColumn`, o menu `···` sai e no lugar, **só em modo seleção**,
aparece um quadrado igual ao do card. Clicar marca todos os deals visíveis daquela coluna; se
todos já estiverem marcados, desmarca. Estado indeterminado (alguns marcados) renderiza um traço.

Isso preserva o que o menu `···` fazia — mover uma coluna inteira — sem manter uma segunda UI.

Opera sobre `filteredDeals`, ou seja, respeita os filtros de busca/categoria ativos: o usuário
seleciona o que está vendo.

### B4. Diálogo de movimentação

**Arquivo novo:** `frontend/src/components/deals/bulk-move-modal.tsx`
**Arquivo removido:** `frontend/src/components/deals/bulk-move-deals-modal.tsx`

```
┌─ Mover deals ──────────────────────────── X ─┐
│  12 deals selecionados                        │
│                                               │
│  FUNIL DE DESTINO                             │
│  [ João - Reposição                    v ]    │
│  ETAPA DE DESTINO                             │
│  [ Negociação                          v ]    │
│                                               │
│  ┌───────────────────────────────────────┐    │
│  │ ⚠  Esta ação move 12 deals e não pode │    │
│  │    ser desfeita. As automações da     │    │
│  │    etapa de destino serão disparadas  │    │
│  │    para cada lead.                    │    │
│  └───────────────────────────────────────┘    │
│  [ ] Confirmo que quero mover estes deals     │
│                                               │
│              [ Cancelar ]  [ Mover 12 deals ] │
└───────────────────────────────────────────────┘
```

Props: `count`, `pipelines`, `currentPipelineId`, `currentStages`, `onClose`,
`onMove(pipelineId, stageId)`.

- **Funil de destino** começa no funil aberto. Lista `pipelines`.
- **Etapa de destino** carrega igual à Parte A: funil atual usa `currentStages`, outro funil busca
  em `/api/pipelines/{id}/stages`. Filtra `!is_protected`. Sem pré-seleção — o usuário escolhe,
  para não mover 12 cards para um destino que ele não leu.
- **Mover N deals** fica `disabled` até: etapa escolhida **e** checkbox marcado.
- Enquanto move: botão vira `Movendo 7/12...` e tudo fica travado, inclusive fechar por clique no
  backdrop.

### B5. Execução

`handleBulkMove(dealIds, pipelineId, stageId)` em `vendas/page.tsx` substitui o atual.

O `handleBulkMove` de hoje faz `Promise.all` de **todos** os ids de uma vez. Cada PATCH faz 3
round-trips no Supabase e dispara um webhook de automação; 50 em paralelo é uma martelada
desnecessária no backend. Passa a executar em **lotes de 5**, aguardando cada lote.

O corpo de cada PATCH inclui `pipeline_id` **apenas quando** o funil de destino é diferente do
funil de origem do deal.

Contabiliza sucessos e falhas:

- **Tudo ok:** fecha diálogo, sai do modo seleção, limpa seleção.
- **Parcial:** `alert("28 de 30 deals movidos. 2 falharam: Permissão insuficiente para este
  funil.")`, e os ids que falharam **continuam selecionados** para o usuário tentar de novo ou
  entender quais são. Fecha o diálogo, mantém o modo seleção.

`alert()` é o padrão de erro já usado na página (`handleDragEnd`, `handleBulkMove`,
`handleDeleteDeal`) — manter é consistência, não preguiça.

---

## Testes

Suíte é `vitest` (`npm test` em `frontend/`), 792 testes verdes na baseline. Os testes do projeto
são de lógica pura em `src/lib/*.test.ts`, com exceção de `esteiras-tab.test.tsx`.

**Arquivo novo:** `frontend/src/lib/bulk-move-deals.ts` + `bulk-move-deals.test.ts`

Extrair a lógica que dá para testar sem DOM:

- `buildMovePayload(deal, targetPipelineId, targetStageId)` → objeto do PATCH; inclui
  `pipeline_id` só quando o funil muda.
- `chunk(items, size)` → lotes de 5.
- `summarizeMoveResults(results)` → `{ moved, failed, failedIds, message }`.
- `selectableStages(stages, currentStageId)` → etapas não-protegidas + a atual se for protegida.

Cobertura mínima:

1. Mesmo funil → payload sem `pipeline_id`.
2. Funil diferente → payload com `pipeline_id` e `stage_id`.
3. `chunk` de 12 em lotes de 5 → `[5, 5, 2]`; lista vazia → `[]`.
4. Todos ok → `failed === 0`, mensagem vazia.
5. Parcial → conta certo, devolve os ids que falharam e a mensagem da API.
6. `selectableStages` esconde protegidas, mas mantém a atual quando ela é protegida.

Verificação manual no navegador (`npm run dev`), porque nada disso é coberto por unit test:

- trocar funil no Editar do modal e salvar → card sai do board atual e aparece no outro funil;
- ligar "Editar Deals", marcar cards de duas colunas diferentes, mover → os dois somem juntos;
- "Mover" com 0 selecionados → desabilitado;
- botão de mover travado até marcar o checkbox de confirmação;
- em modo seleção, arrastar um card **não** move nada.

## Fora de escopo

- Copiar deal em vez de mover.
- Desfazer a movimentação.
- Bulk de outras ações (excluir, mudar responsável, mudar categoria).
- Flag `skip_automation` na rota de deals.
- Bug adjacente já existente: `handleCreateDeal` sobrescreve `pipeline_id` com
  `selectedPipelineId`, então o seletor de funil do "Novo Card" é ignorado e o card nasce no funil
  aberto com uma etapa de outro funil. Vale corrigir, mas em outra entrega — mexer nisso aqui
  mistura dois assuntos no mesmo diff.
