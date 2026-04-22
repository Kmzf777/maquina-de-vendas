# Design: Integração /vendas ↔ CRM (Conversas-first)

**Data:** 2026-04-22  
**Branch:** `feat/vendas-crm-integration`  
**Status:** Aprovado

---

## Contexto

O CRM tem vendedores que passam a maior parte do tempo em `/conversas` (WhatsApp) mas gerenciam deals em `/vendas`. Hoje os dois mundos são ilhas: criar um deal exige trocar de página, o handoff do bot não cria deal, e não há navegação entre deal e conversa.

A integração deve ser **conversas-first**: tudo que o vendedor precisa sobre deals deve ser acessível sem sair do chat.

---

## Escopo

### O que entra nessa spec

1. Funis de setor padrão (DB seed: Atacado, Private Label, Exportação, Consumo)
2. Backend `create_deal` pipeline-aware — ao criar via bot, associa ao funil correto
3. `encaminhar_humano` cria deal no funil certo automaticamente
4. API `GET /api/leads/[id]/deals` — todos os deals de um lead
5. `ContactDetail` em `/conversas` — painel completo de deals do lead
6. `DealDetailSidebar` em `/vendas` — botão "Abrir conversa"
7. `/conversas` aceita `?lead_id=` na URL para deep-link a partir do /vendas

### O que NÃO entra

- Cadências por deal stage (feature futura separada)
- Dashboard atualizado para novo modelo de pipeline (feature futura separada)
- Notificações push quando deal muda de stage

---

## Arquitetura e Fluxo de Dados

### Fluxo principal: Bot → Deal automático

```
Valéria (stage=atacado)
  → executa encaminhar_humano(vendedor, motivo)
  → tools.py: fetch lead para obter lead.stage
  → create_deal(lead_id, title, category=lead.stage)
  → service.py: lookup pipeline WHERE name ILIKE lead.stage
  → insert deal com pipeline_id + stage_id do stage "Novo"
  → deal aparece no Funil Atacado em /vendas
```

### Fluxo principal: Vendedor cria deal manualmente em /conversas

```
Vendedor abre /conversas → seleciona lead
  → ContactDetail mostra seção "Oportunidades"
  → clica "+ Nova oportunidade"
  → DealCreateModal abre pré-selecionado com o lead
  → vendedor escolhe pipeline, preenche título/valor
  → deal criado via POST /api/deals
  → lista de deals no ContactDetail atualiza via refetch
```

### Fluxo de navegação: /vendas → /conversas

```
Vendedor abre deal no /vendas
  → DealDetailSidebar mostra botão "Abrir conversa"
  → clica → navega para /conversas?lead_id={deal.lead_id}
  → /conversas lê query param e pré-seleciona a conversa do lead
```

---

## Componentes e Mudanças

### 1. DB — Seed funis de setor (via MCP, não código)

Criar 4 pipelines padrão com os 6 stages padrão cada:

| Pipeline       | Categoria     |
|----------------|---------------|
| Atacado        | atacado       |
| Private Label  | private_label |
| Exportação     | exportacao    |
| Consumo        | consumo       |

Cada pipeline recebe os stages padrão: Novo → Contato → Proposta → Negociação → Fechado Ganho (protegido) → Perdido (protegido).

O funil "Principal" já existente permanece intacto.

---

### 2. Backend — `create_deal` pipeline-aware

**Arquivo:** `backend/app/leads/service.py`

Assinatura atual:
```python
def create_deal(lead_id, title, category=None)
```

Lógica nova:
1. Se `category` fornecido, buscar pipeline cujo nome faz match com a categoria (ex: `"atacado"` → pipeline "Atacado"). Match case-insensitive, usando `ilike`.
2. Se não encontrar, buscar o primeiro pipeline por `order_index`.
3. Buscar o primeiro stage não-protegido (`is_protected=False`, menor `order_index`) desse pipeline.
4. Inserir deal com `pipeline_id` e `stage_id`.

```python
def create_deal(lead_id, title, category=None):
    sb = get_supabase()
    pipeline = None
    if category:
        result = sb.table("pipelines").select("id").ilike("name", f"%{category.replace('_', ' ')}%").limit(1).execute()
        if result.data:
            pipeline = result.data[0]
    if not pipeline:
        result = sb.table("pipelines").select("id").order("order_index").limit(1).execute()
        pipeline = result.data[0] if result.data else None

    stage_id = None
    if pipeline:
        s = sb.table("pipeline_stages").select("id").eq("pipeline_id", pipeline["id"]).eq("is_protected", False).order("order_index").limit(1).execute()
        stage_id = s.data[0]["id"] if s.data else None

    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",  # campo legado mantido
        "category": category,
        "pipeline_id": pipeline["id"] if pipeline else None,
        "stage_id": stage_id,
    }
    return sb.table("deals").insert(deal).execute().data[0]
```

---

### 3. Backend — `encaminhar_humano` passa categoria do lead

**Arquivo:** `backend/app/agent/tools.py`

Hoje: `create_deal(lead_id, title=f"{vendedor} - {motivo}")`  
Problema: não passa `category`, então o deal cai no pipeline genérico.

Fix: adicionar `get_lead(lead_id)` em `leads/service.py`, chamá-la em `execute_tool` antes de criar o deal.

```python
# leads/service.py — nova função
def get_lead(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return result.data[0] if result.data else None

# tools.py — imports
from app.leads.service import update_lead, save_message, create_deal, get_lead

# tools.py — dentro de execute_tool
elif tool_name == "encaminhar_humano":
    update_lead(lead_id, status="converted", human_control=True)
    motivo = args.get("motivo", "lead qualificado")
    vendedor = args.get("vendedor", "Vendedor")
    lead = get_lead(lead_id)
    lead_stage = lead.get("stage") if lead else None
    create_deal(lead_id, title=f"{vendedor} - {motivo}", category=lead_stage)
    ...
```

---

### 4. Frontend — API `GET /api/leads/[id]/deals`

**Arquivo novo:** `frontend/src/app/api/leads/[id]/deals/route.ts`

Retorna todos os deals de um lead com join de `pipeline_stages` e `pipelines`, ordenados por `updated_at DESC`.

```typescript
GET /api/leads/:id/deals
→ deals[] com: id, title, value, category, stage_id, pipeline_id,
               pipeline_stages { label, dot_color, key, is_protected },
               pipelines { name }
```

Sem paginação (leads raramente têm mais de 10 deals).

---

### 5. Frontend — `ContactDetail` painel de deals

**Arquivo:** `frontend/src/components/conversas/contact-detail.tsx`

Substituir o bloco `activeDeal` atual (1 deal, somente leitura) por uma seção "Oportunidades" completa:

**Seção Oportunidades:**
- Header com label "Oportunidades" + botão "+ Nova" (ícone +)
- Lista de deals do lead, cada item mostra:
  - Dot colorido com a cor do stage atual
  - Título do deal (truncado)
  - Nome do pipeline em texto pequeno (ex: "Funil Atacado")
  - Stage atual em texto pequeno (ex: "Proposta")
  - Valor em R$ (se > 0)
- Deals em stages protegidos (Fechado Ganho/Perdido) mostrados com opacidade reduzida
- "Nenhuma oportunidade" se lista vazia

**Ação "+ Nova":**
- Abre `DealCreateModal` com `preselectedLead` já preenchido
- Após criação, refetch da lista de deals do lead

**Ausência de navegação profunda:** clicar em um deal no ContactDetail não abre o sidebar de deal — isso seria complexidade extra. O vendedor pode ir ao /vendas para detalhes. Isso pode ser adicionado futuramente.

**Data fetching:** `useEffect` ao montar, refetch após criar deal. Sem realtime nessa seção (overhead alto para ganho baixo).

---

### 6. Frontend — `DealDetailSidebar` botão "Abrir conversa"

**Arquivo:** `frontend/src/components/deals/deal-detail-sidebar.tsx`

Adicionar no header do sidebar, ao lado do botão "Editar":

- Botão "Conversa" com ícone de chat
- `onClick`: `router.push('/conversas?lead_id=' + deal.lead_id)`
- Só aparece se `deal.leads` tiver dados (sempre verdade dado o join)

Requer `useRouter` do Next.js (`next/navigation`).

---

### 7. Frontend — `/conversas` aceita `?lead_id=` 

**Arquivo:** `frontend/src/app/(authenticated)/conversas/page.tsx`

Ao montar a página, ler `searchParams.get('lead_id')`. Quando as conversas carregarem e um `lead_id` for encontrado na URL, pré-selecionar a conversa cujo `lead_id` bate. Limpar o param da URL após selecionar (usando `router.replace`) para não confundir o estado.

---

## Ordem de Implementação

A ordem importa por dependências:

1. **DB seed** (MCP) — funis de setor precisam existir para o backend rotear
2. **Backend `create_deal`** — independente do frontend
3. **Backend `encaminhar_humano`** — depende do `create_deal` pipeline-aware
4. **API `/api/leads/[id]/deals`** — frontend depende desta rota
5. **`ContactDetail` painel de deals** — depende da API acima
6. **`DealDetailSidebar` botão** + **`/conversas` deep-link** — independentes entre si, paralelos

---

## Critérios de Aceite

- [ ] Bot executa `encaminhar_humano` → deal aparece no funil correto em /vendas sem ação manual
- [ ] Bot executa `registrar_pedido_simples` com `categoria=atacado` → deal no Funil Atacado
- [ ] Vendedor em /conversas vê todos os deals do lead na seção Oportunidades
- [ ] Vendedor clica "+ Nova" em /conversas e cria deal sem sair da página
- [ ] Vendedor clica "Conversa" em um deal no /vendas e cai direto na conversa certa
- [ ] Funis Atacado, Private Label, Exportação e Consumo existem no DB com stages padrão
- [ ] Funil "Principal" existente não é afetado pelo seed
- [ ] `create_deal` sem `category` cai no primeiro pipeline por `order_index` (fallback seguro)
