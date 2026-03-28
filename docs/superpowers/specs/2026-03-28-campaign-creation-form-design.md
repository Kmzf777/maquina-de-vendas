# Campaign Creation Form — Design Spec

**Data:** 2026-03-28
**Status:** Aprovado

## Resumo

Substituir o formulario inline de criacao de campanha por um modal wizard completo com 2 steps: configuracao basica e selecao de leads (filtros do CRM + importacao CSV). Inclui novo campo `type` (bot/seller), campo `instance_name`, e endpoint `assign-leads` no backend.

## Decisoes de Design

| Decisao | Escolha |
|---------|---------|
| Layout do formulario | Modal wizard 2 steps |
| Selecao de leads | Filtros (stage, tags, funil vendedor, busca) + checkboxes individuais |
| CSV | Mantido como aba alternativa dentro do step 2, com feedback |
| Tipo de campanha | Campo `type`: bot ou seller (toggle cards) |
| Instancia WhatsApp | Dropdown com instancias conectadas (prepara para multiplas) |
| Config de cadencia | Nao inclusa na criacao — configura depois na pagina de detalhe |

## 1. Modal Wizard

### Step 1 — Configuracao

**Campos:**

| Campo | Tipo | Obrigatorio | Default |
|-------|------|-------------|---------|
| Tipo | Toggle cards (Bot / Vendedor) | sim | bot |
| Instancia WhatsApp | Dropdown | sim | primeira conectada |
| Nome | Input texto | sim | — |
| Template | Input texto | sim | — |
| Intervalo min (s) | Input numerico | nao | 3 |
| Intervalo max (s) | Input numerico | nao | 8 |

**Tipo de campanha:**
- Duas cards lado a lado com icone + label
- "Bot (ValerIA)" — icone robo
- "Vendedor" — icone pessoa
- Selecao muda a borda para accent-olive

**Instancia WhatsApp:**
- Busca status via `/api/evolution/status`
- Se conectada: mostra nome da instancia + numero
- Se desconectada: "Nenhuma instancia conectada" (desabilitado)
- Campo preparado para listar multiplas instancias no futuro

**Validacao:** Nome, template e instancia obrigatorios. Botao "Proximo" desabilitado ate preencher.

### Step 2 — Selecao de Leads

Duas abas: "Selecionar do CRM" (default) e "Importar CSV"

#### Aba "Selecionar do CRM"

**Filtros (barra horizontal):**
- Stage: multi-select dropdown (secretaria, atacado, private_label, exportacao, consumo)
- Tags: multi-select dropdown (busca tags do Supabase)
- Funil Vendedor: multi-select dropdown (novo, em_contato, negociacao, fechado, perdido)
- Busca: input texto (nome, telefone, empresa)

**Tabela:**
- Header com checkbox "Selecionar todos (N)"
- Colunas: [ ] Nome | Telefone | Stage | Funil Vendedor | Tags
- Hover row highlight
- Exclui leads que ja estao em campanha ativa (campaign_id de campanha running)

**Rodape:** Contador "N leads selecionados" + botao "Criar Campanha"

**Dados:** Busca leads e tags via Supabase client (mesmo padrao da QualificacaoPage). Filtros aplicados client-side.

#### Aba "Importar CSV"

- Area de upload drag & drop (estilo existente)
- Apos upload: parse client-side ou server-side mostra feedback:
  - "150 numeros validos, 3 invalidos"
  - Lista dos numeros invalidos (primeiros 20)
- Botao "Criar Campanha" no rodape

### Fluxo de criacao

1. Usuario clica "Nova Campanha"
2. Modal abre no step 1
3. Preenche config, clica "Proximo"
4. Step 2: seleciona leads via filtros OU importa CSV
5. Clica "Criar Campanha"
6. Frontend faz:
   - `POST /api/campaigns` com config (nome, template, type, instance_name, intervalos)
   - Se CSV: `POST /api/campaigns/{id}/import` com arquivo
   - Se leads selecionados: `POST /api/campaigns/{id}/assign-leads` com lead_ids
7. Modal fecha, lista atualiza via Supabase Realtime

### Estilo

Segue design system existente:
- Modal: bg branco, rounded-2xl, max-w-3xl, max-h-[85vh], overflow scroll
- Header com titulo + botao fechar (X)
- Step indicator: dois circulos com label, conectados por linha, ativo = dark, inativo = muted
- Cards de tipo: borda 2px, selecionado = border-[#c8cc8e] bg-[#f2f3eb]
- Filtros: pills/dropdowns com mesmo estilo dos filtros de cadence-leads-table
- Tabela: mesmo estilo das tabelas existentes (campanhas, leads)
- Botoes: btn-primary, btn-secondary (ja definidos no globals.css)

## 2. Backend

### Migracao SQL (`004_campaign_type.sql`)

```sql
ALTER TABLE campaigns ADD COLUMN type text NOT NULL DEFAULT 'bot';
ALTER TABLE campaigns ADD COLUMN instance_name text;
```

### Novo endpoint: assign-leads

`POST /api/campaigns/{campaign_id}/assign-leads`

**Body:**
```json
{ "lead_ids": ["uuid1", "uuid2", ...] }
```

**Logica:**
- Para cada lead_id: update `campaign_id = campaign_id`, `status = 'imported'`
- Skip leads que ja tem `campaign_id` de campanha com status `running`
- Atualiza `total_leads` da campanha com o total vinculado

**Response:**
```json
{ "assigned": 45, "skipped": 3 }
```

### Ajustes no CampaignCreate

Adicionar campos ao Pydantic model:
```python
class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    type: str = "bot"                    # NOVO
    instance_name: str | None = None     # NOVO
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_interval_hours: int = 24
    cadence_send_start_hour: int = 7
    cadence_send_end_hour: int = 18
    cadence_cooldown_hours: int = 48
    cadence_max_messages: int = 8
```

## 3. Tipos TypeScript

Adicionar ao Campaign interface:
```typescript
export interface Campaign {
  // ... campos existentes ...
  type: "bot" | "seller";
  instance_name: string | null;
}
```

## 4. Componentes

| Componente | Responsabilidade |
|-----------|-----------------|
| `components/create-campaign-modal.tsx` | Modal wizard 2 steps (novo) |
| `components/lead-selector.tsx` | Tabela de leads com filtros e checkboxes (novo) |
| `campanhas/page.tsx` | Remover form inline, usar modal (modificar) |
| `lib/types.ts` | Adicionar type e instance_name (modificar) |
| `campaign/router.py` | Adicionar assign-leads + campos (modificar) |
| `migrations/004_campaign_type.sql` | Migracao (novo) |
