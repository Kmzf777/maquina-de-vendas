# Plano de Implementacao — Aba de Funil no Modal de Lead

Spec: `2026-09-17-aba-funil-no-modal-de-lead-design.md`

**Baseline medida antes de comecar:** `npx vitest run` → 60 arquivos, 786 testes verdes,
2 erros de coleta pre-existentes (`Cannot find package 'jsdom'` em
`stage-target-picker.test.tsx` e no outro `.test.tsx`).

**Paralelizacao:** tres ondas. Dentro de cada onda os agentes tocam **arquivos
disjuntos** — nenhum arquivo aparece em duas tarefas da mesma onda. Erro de tipo
transitorio entre ondas e esperado; o typecheck vale so no fim da Onda 3.

---

## Onda 1 — fundacao (3 agentes em paralelo)

### T1. `lib/lead-funnel-actions.ts` + teste
**Arquivos:** `frontend/src/lib/lead-funnel-actions.ts` (novo),
`frontend/src/lib/lead-funnel-actions.test.ts` (novo). **Nao toca mais nada.**

Implementar as tres funcoes do spec secao 1, reusando `isDealClosed` e o tipo `LeadDeal`
de `@/lib/deal-rows` (nao redeclarar tipo de deal).

- `findOpenDealInPipeline(deals, pipelineId)`: primeiro card **aberto** (`!isDealClosed`)
  com `deal.pipeline_id === pipelineId`; `null` se nenhum. `pipelineId` vazio → `null`.
- `buildDealTitle(leadName, pipelineName)`: `` `${leadName} - ${pipelineName}` ``, com os
  dois lados `.trim()`. Espelha o `autoTitle` de `deal-create-modal.tsx` — ler o arquivo
  e casar o formato exatamente, incluindo o fallback `"Funil"` quando o nome do funil vem
  vazio e `"Lead"` quando o nome do lead vem vazio.
- `isSameTarget(deal, pipelineId, stageId)`: `true` so quando `deal.pipeline_id` **e**
  `deal.stage_id` coincidem com os argumentos.

Testes (TDD: escrever primeiro, ver falhar, implementar): os 6 casos listados no spec
secao "Testes". Rodar `npx vitest run src/lib/lead-funnel-actions.test.ts` e colar a
saida real no relatorio final.

### T2. `hooks/use-lead-deals.ts`
**Arquivos:** `frontend/src/hooks/use-lead-deals.ts` (novo). **Nao toca mais nada** — em
especial **nao** alterar `contact-detail.tsx`.

Extrair para um hook o fetch que hoje vive inline em
`frontend/src/components/conversas/contact-detail.tsx` (ler as linhas 55-150 antes de
escrever). Contrato exato no spec secao 2.

Preservar as tres regras, **com os comentarios explicando o porque** (copiar o espirito
dos comentarios do original, que documentam bugs reais):
1. `reqId` monotonico via `useRef`, descartando resposta obsoleta.
2. `refetch` e `updateDeal` **lancam** `Error` com mensagem legivel em falha (inclusive
   403 do guard de funil) — quem chama e que decide exibir.
3. Carga inicial no `useEffect` chama `.catch(() => {})`.

`stagesByPipeline`: para cada `distinctPipelineIds(deals)`, buscar
`/api/pipelines/${id}/stages` e montar o `Record`. Um funil cujo fetch falhou fica
**ausente** do record (nao entra como `[]`): `buildDealRows` distingue "etapas
desconhecidas" de "funil sem etapas abertas" por `pipelineId in stagesByPipeline`, e
gravar `[]` faria toda linha aberta virar read-only em vez de esperar.

`leadId` `undefined` → nao busca nada, devolve listas vazias.

Sem teste unitario (hook de rede; o repo nao tem jsdom instalado). A cobertura vem do
typecheck e da verificacao em navegador da Onda 3.

### T3. Trava de servidor no `PATCH /api/deals/[id]`
**Arquivos:** `frontend/src/lib/deal-patch-guard.ts` (novo),
`frontend/src/lib/deal-patch-guard.test.ts` (novo),
`frontend/src/app/api/deals/[id]/route.ts` (alterado). **Nao toca mais nada.**

1. `resolveEffectivePipelineId(body, current)` — contrato no spec secao 6. Teste puro:
   so `stage_id` no corpo → funil atual; `pipeline_id` + `stage_id` → funil do corpo;
   `pipeline_id: null` explicito no corpo → cai no atual; ambos ausentes → `null`.
2. No `PATCH`, dentro do bloco `if (body.stage_id)` que hoje busca `key`: trocar o select
   para `key, pipeline_id`, e comparar com `resolveEffectivePipelineId(body, currentDeal)`.
   Divergencia → `return NextResponse.json({ error: "A etapa escolhida nao pertence ao
   funil de destino." }, { status: 422 })` **antes** do `.update()`. Etapa inexistente
   (`stage` nulo) → 422 tambem: hoje passa direto e grava um `stage_id` orfao.
   Funil efetivo `null` (deal sem funil) → nao bloqueia, para nao mudar o comportamento
   de deals legados sem `pipeline_id`.
3. Comentario curto na rota dizendo por que a trava existe (cliente era a unica garantia
   do par; cinco bugs de "card sumiu do board" ja sairam em review).

Rodar `npx vitest run src/lib/deal-patch-guard.test.ts` e colar a saida real.

---

## Onda 2 — componentes (2 agentes em paralelo)

### T4. `LeadFunisTab` + `LeadCardMoveRow`
**Arquivos:** `frontend/src/components/leads/lead-funis-tab.tsx` (novo),
`frontend/src/components/leads/lead-card-move-row.tsx` (novo),
`frontend/src/components/deals/deal-create-modal.tsx` (alterado — prop opcional).
**Nao toca** `lead-detail-modal.tsx` nem `leads/page.tsx`.

Depende de T1 e T2 (ja prontos). Layout e comportamento no spec secao 3.

- `LeadFunisTab({ leadId, lead, pipelines })`: usa `useLeadDeals`, `buildDealRows`,
  renderiza `DealStageRow` por linha, botao "+ Novo card", estado vazio
  "Este lead nao esta em nenhum funil.", e "Nao foi possivel carregar os funis." quando
  `pipelines` vem vazio.
- `LeadCardMoveRow({ row, pipelines, onMove })`: `StageTargetPicker` com
  `autoSelectFirstStage={false}`, `currentStageId={row.deal.stage_id}`,
  `localPipelineId={null}`, `localStages={[]}`; botoes Cancelar/Mover; "Mover"
  desabilitado quando `isSameTarget` ou `stageId` vazio; erro exibido na propria linha.
- `DealCreateModal`: adicionar **prop opcional** `existingOpenDeal?: { title: string;
  stageLabel: string } | null`, derivada pelo chamador com `findOpenDealInPipeline` a
  partir do funil selecionado. Quando presente, exibir faixa de aviso amarela nomeando o
  card e a etapa, com o texto do spec, e **manter o botao ativo**. Ausente → modal
  identico ao de hoje. Confirmar que `/vendas` e `/conversas`, que nao passam a prop,
  seguem compilando e com comportamento inalterado.

Estilo: seguir `crm-perfil-tab.tsx` e o proprio `lead-detail-modal.tsx` — mesma paleta
(`#dedbd6`, `#7b7b78`, `#111111`, `#faf9f6`), `text-[13px]`/`text-[11px] uppercase
tracking-[0.6px]` nos rotulos, `rounded-[6px]`. Nao introduzir biblioteca de UI nova.

### T5. Funil opcional no modal de criacao
**Arquivos:** `frontend/src/components/leads/lead-create-modal.tsx` (alterado).
**Nao toca** `leads/page.tsx`.

Spec secao 4. Adicionar props `pipelines?: Pipeline[]`, uma secao "Funil (opcional)"
separada por `border-t` no fim do form usando `StageTargetPicker`
(`autoSelectFirstStage={false}`, `currentStageId={null}`, `localPipelineId={null}`,
`localStages={[]}`), e trocar a assinatura de `onCreate` para o payload
`{ lead, funnel }` do spec. Escolher funil sem etapa → nao envia funil (ou desabilita o
submit; escolher o que ficar mais claro e dizer qual no relatorio). `pipelines` ausente
ou vazio → secao inteira nao renderiza.

---

## Onda 3 — fiacao e verificacao (1 agente, sem paralelismo)

### T6. Ligar tudo em `/leads`
**Arquivos:** `frontend/src/app/(authenticated)/leads/page.tsx`,
`frontend/src/components/leads/lead-detail-modal.tsx`.

1. `page.tsx`: buscar `/api/pipelines` num `useEffect` (guardando `Array.isArray`), passar
   `pipelines` para `LeadCreateModal` e `LeadDetailModal`. `handleCreateLead` recebe
   `{ lead, funnel }`: `POST /api/leads` → em 201, se `funnel`, `POST /api/deals` com
   `buildDealTitle`. Falha no segundo POST → **nao** reportar sucesso total; superficie de
   erro conforme a tabela de erros do spec.
2. `lead-detail-modal.tsx`: nova aba `funis` em `TABS` com label `"Funis"`, posicionada
   logo depois de "Dados Gerais"; renderiza `LeadFunisTab`. Remover o bloco
   "Oportunidades" de "Dados Gerais" **mantendo** o botao "Registrar Venda" onde esta.
   Remover o estado `leadDeals` e o `fetchLeadDeals` (fetch Supabase no cliente) que
   ficam sem uso, e o import de `DEAL_STAGES` se ficar orfao.
3. Verificacao final, **com saida colada no relatorio**. Os criterios abaixo foram
   CORRIGIDOS depois de medir a arvore de verdade — a versao original deste plano pedia
   "tsc zero erros" e "lint limpo", e nenhum dos dois e verdade neste repo hoje:

   - `npx tsc --noEmit` → **exatamente os 4 erros pre-existentes** de
     `@testing-library/react` ausente no `node_modules` (2 de modulo nao encontrado em
     `esteiras-tab.test.tsx` e `stage-target-picker.test.tsx`, mais 2 `TS18046` em
     cascata em `stage-target-picker.test.tsx`). Zero erros fora desses 4 — em especial,
     o `TS2322` de `leads/page.tsx:364` (call site antigo do `LeadCreateModal`) tem de
     desaparecer, e e T6 quem o resolve.
   - `npm run lint` → **nao pode ficar pior que a baseline**, que ja e vermelha: 69
     problemas (33 erros, 36 warnings), dos quais 23 sao `react-hooks/set-state-in-effect`
     — regra que ja dispara em `use-lead-sales.ts` e `use-lead-quotes.ts`, arquivos
     commitados. `use-lead-deals.ts` herda esse mesmo aviso por seguir a convencao dos
     irmaos; isso e aceito, e nao se adiciona `eslint-disable` para esconder.
   - `npx vitest run` → 786 + os novos testes verdes, e os **mesmos 2 erros de coleta**
     por jsdom ausente. Nada novo em vermelho.

---

## Depois das ondas (eu, nao agente)

- Revisar o diff completo.
- `/leads` no navegador: criar lead com funil, criar card pela aba, trocar etapa, mover
  entre funis, e conferir o card no Kanban de `/vendas`.
- Commit na branch. **Push para `master` so com autorizacao explicita** (CLAUDE.md passo 4).
