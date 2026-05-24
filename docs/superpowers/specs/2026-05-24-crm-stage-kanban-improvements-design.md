# CRM: Stage Hierárquico, Modal "Novo Card" e Funil Customizável

**Data:** 2026-05-24  
**Status:** Aprovado

---

## Contexto

Três melhorias solicitadas para as telas de Conversas (`/conversas`) e Vendas (`/vendas`):

1. Substituir o select estático "Status CRM" por seletores hierárquicos Funil → Stage
2. Reformular o modal de criação de deal: renomear para "Novo Card", simplificar campos, adicionar stage selecionável e observações
3. Confirmar que o Kanban já é dinâmico (e comunicar ao usuário)

---

## 1. Painel de Conversas — Seção "Estágio"

### Onde fica
`frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` — linhas 140–155

### Estado atual
Seção `"Status CRM"` com um `<select>` hardcoded usando `AGENT_STAGES` (secretaria, atacado, private_label, exportacao, consumo). O campo salvo é `lead.stage` — **usado pela IA Valéria no backend** (variáveis de template, motor de automações).

### Design da mudança

**O que remove:** Título da seção `"Status CRM"` e o select de `AGENT_STAGES`.

**O que adiciona:**
- Label renomeado para `"Estágio"`
- **Select 1 — Funil:** lista os `pipelines` (já chegam via prop `pipelines[]` existente)
- **Select 2 — Stage:** lista `pipeline_stages` do funil selecionado (fetch ao mudar funil via `/api/pipelines/{id}/stages` ou direto do Supabase)
- Estado inicial: exibe funil + stage do deal mais recente não-fechado do lead (baseado nos `deals[]` já passados como prop)
  - "Não-fechado" = `pipeline_stages.key` não é `'fechado_ganho'` nem `'fechado_perdido'`
- Ao mudar stage: `PATCH /api/deals/{deal.id}` com `{ stage_id: novoStageId }`
- Ao mudar funil: recarregar stages do novo funil; se o lead tiver um deal nesse funil, selecionar o stage atual desse deal; caso contrário, selecionar o primeiro stage disponível mas **não salvar** até o usuário confirmar mudança de stage
- **Sem deal ativo:** exibir badge `"Sem oportunidade"` + botão que dispara `onCreateDeal()` (já existe no componente)
- O campo `lead.stage` (da IA) **não é alterado** — zero impacto no agente

**Campo "Atribuído a"** permanece logo abaixo, sem mudanças.

### Arquivos afetados
- `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` — substituir seção Status CRM
- `frontend/src/components/conversas/contact-detail.tsx` — verificar se `deals` e `pipelines` já chegam como props (já chegam)

---

## 2. Modal "Novo Card" + Botão

### Onde fica
- Botão: `frontend/src/app/(authenticated)/vendas/page.tsx` linha 289
- Modal: `frontend/src/components/deals/deal-create-modal.tsx`

### Estado atual
Botão texto `"Nova Oportunidade"`. Modal tem: Lead (combobox), Funil (select), Título (input), Valor, Categoria, Data de previsão. Sem seleção de Stage (sempre usa o primeiro stage do pipeline automaticamente). Sem campo Observações.

### Design da mudança

**Botão:** `"Nova Oportunidade"` → `"Novo Card"`

**Formulário reformulado (campos em ordem):**

| Campo | Tipo | Obrigatório | Detalhe |
|---|---|---|---|
| Lead | Combobox pesquisável | Sim | Mantido exatamente como está |
| Funil | Select | Sim | Mantido como está |
| Stage | Select dependente | Sim | **Novo** — carrega stages do funil selecionado; exclui stages protegidos |
| Observações | Textarea (3 linhas) | Não | **Novo** — salvo em `lead_notes` após criar o deal |

**Campos removidos:** Título, Valor, Categoria, Data de previsão.

**Título auto-gerado:** `"[lead.name || lead.phone] - [pipeline.name]"` — construído no frontend antes do POST.

**Fluxo de criação:**
1. POST `/api/deals` com `{ lead_id, title (auto), pipeline_id, stage_id, value: 0 }`
2. Se observações preenchidas → POST `/api/leads/{lead_id}/notes` com `{ author: "Usuário", content: observacoes }`
3. Fechar modal

**Mudança no backend (`/api/deals` POST):**
- Aceitar `stage_id` no body
- Se `stage_id` fornecido e pertence ao `pipeline_id`: usá-lo diretamente
- Caso contrário: comportamento atual (primeiro stage não-protegido do pipeline)

**Load de stages no modal:**
- Quando o funil mudar, fetch `pipeline_stages` para aquele `pipeline_id` (stages não-protegidos, ordenados por `order_index`)
- Popular o Select de Stage; pré-selecionar o primeiro

### Arquivos afetados
- `frontend/src/app/(authenticated)/vendas/page.tsx` — texto do botão
- `frontend/src/components/deals/deal-create-modal.tsx` — reformulação do formulário
- `frontend/src/app/api/deals/route.ts` (POST) — aceitar `stage_id` opcional

---

## 3. Funil Customizável — Já implementado

**Situação:** O `PipelineEditModal` já suporta 100% do pedido original:
- Adicionar stage (botão dashed no modal)
- Renomear stage (input inline editável)
- Mudar cor (color picker no hover)
- Reordenar (drag-and-drop via @dnd-kit)
- Excluir (botão X por stage, bloqueado em stages protegidos)

**Acesso atual:** `PipelineSwitcher` → menu `"···"` → `"Editar Funil"`

**Melhoria opcional (baixa prioridade):** deixar o botão de edição mais visível no header da página.

**Nenhuma mudança de backend necessária** para este ponto.

---

## Decisões e restrições

- `lead.stage` (campo do agente IA) **não é alterado** em nenhum cenário
- Observações do Novo Card → `lead_notes` (sem nova coluna no banco, sem migration)
- O `title` de um deal criado via "Novo Card" é sempre auto-gerado — não exposto ao usuário
- `stage_id` no POST de deals é opcional para manter compatibilidade com outros usos

---

## Arquivos a modificar (resumo)

| Arquivo | Mudança |
|---|---|
| `crm-perfil-tab.tsx` | Substituir seção "Status CRM" por Funil+Stage hierárquico |
| `deal-create-modal.tsx` | Reformular formulário (remover campos, adicionar Stage + Observações) |
| `vendas/page.tsx` | Renomear botão; passar `stages` carregados para o modal |
| `api/deals/route.ts` (POST) | Aceitar `stage_id` opcional no body |

**Nenhuma migration de banco necessária.**
