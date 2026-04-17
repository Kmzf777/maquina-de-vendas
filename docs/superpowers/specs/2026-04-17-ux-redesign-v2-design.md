# UX/UI Redesign v2 — Stripe+Intercom Approach

**Date:** 2026-04-17  
**Branch:** feat/ux-redesign-v2  
**Status:** Approved  
**References:** Stripe Dashboard + Intercom/Linear editorial

---

## Goal

Transform the CRM from a technically-correct but visually flat implementation into a data-rich, editorially clean dashboard SaaS. Solve the monochromatic problem through (1) surface layers creating depth hierarchy and (2) purposeful color usage on data/status elements. Special focus on the Campanhas module.

**Hard constraint:** 100% backend connection preserved — no API routes, hooks, or data-fetching logic modified.

---

## 1. Design System — Surface Layers & Tokens

### Surface Hierarchy (4 levels)

| Token | Value | Use |
|-------|-------|-----|
| `surface-nav` | `#f0ede8` | Sidebar background — warmer/darker than canvas |
| `surface-canvas` | `#faf9f6` | Page background |
| `surface-card` | `#ffffff` | Cards, modals, panels |
| `surface-raised` | `#f7f5f1` | Grouped sections inside cards, table headers |

### Color Tokens (unchanged)

| Token | Value | Semantic use |
|-------|-------|-------------|
| `#111111` | Off Black | Text, primary buttons |
| `#ff5600` | Fin Orange | Brand accent, AI features, alerts |
| `#dedbd6` | Oat | Borders everywhere |
| `#7b7b78` | Muted | Secondary text, labels |
| `#0bdf50` | Report Green | Active, success, positive numbers |
| `#c41c1c` | Report Red | Negative, lost, errors |
| `#65b5ff` | Report Blue | Informational, neutral stats |
| `#fe4c02` | Report Orange | Warning, paused |
| `#b3e01c` | Report Lime | Secondary positive |

### Typography Hierarchy (4 levels)

| Level | Size | Weight | Tracking | Color | Use |
|-------|------|--------|----------|-------|-----|
| Hero | 48px | 400 | -1.5px | `#111111` | KPI values |
| Page title | 32px | 400 | -0.96px | `#111111` | Page H1 |
| Section heading | 18px | 500 | -0.3px | `#111111` | Card titles, section headers |
| Nav group label | 10px | 500 | 1.2px uppercase | `#7b7b78` | Sidebar group labels |
| Body | 14px | 400 | normal | `#111111` | Content |
| Caption | 11px | 400 | 0.6px uppercase | `#7b7b78` | Field labels, table headers |

### Component Tokens

**Buttons** (unchanged from DESIGN.md):
- Primary: `bg-[#111111] text-white rounded-[4px] px-[14px] py-2 hover:scale-110 active:scale-[0.85]`
- Outlined: `border border-[#111111] text-[#111111] rounded-[4px] px-[14px] py-2 hover:scale-110`
- Danger: `border border-[#c41c1c] text-[#c41c1c] rounded-[4px] px-[14px] py-2 hover:scale-110`

**Cards:** `bg-white border border-[#dedbd6] rounded-[8px]` — NO shadows

**Status Badges:**
```tsx
// active/success
"bg-[#0bdf50]/10 text-[#0bdf50] border border-[#0bdf50]/20 text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
// paused/warning
"bg-[#fe4c02]/10 text-[#fe4c02] border border-[#fe4c02]/20 text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
// draft/neutral
"bg-[#f0ede8] text-[#7b7b78] border border-[#dedbd6] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
// completed
"bg-[#65b5ff]/10 text-[#65b5ff] border border-[#65b5ff]/20 text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
// error/failed
"bg-[#c41c1c]/10 text-[#c41c1c] border border-[#c41c1c]/20 text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
```

**KPI Card (new pattern):**
```tsx
<div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Label</p>
  <p style={{ letterSpacing: '-1.5px' }} className="text-[48px] font-normal text-[#111111] leading-none">247</p>
  <p className="text-[13px] text-[#7b7b78] mt-2">Subtexto contextual</p>
</div>
```

**Stat inline (used inside cards for secondary metrics):**
```tsx
<div className="flex flex-col">
  <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Enviados</span>
  <span className="text-[20px] font-normal text-[#111111]" style={{ letterSpacing: '-0.3px' }}>1.240</span>
</div>
```

---

## 2. Global Layout — Sidebar Grouped

### Structure
```
[f0ede8 sidebar 220px] | [faf9f6 canvas flex-1]
```

### Sidebar Groups
```
ValerIA·  (logo)

── VENDAS ──────────────
  Dashboard
  Visão Agent AI
  Leads
  Funis de venda

── COMUNICAÇÃO ─────────
  WhatsApp
  Campanhas

── DADOS ───────────────
  Tokens AI
  Instâncias

── SISTEMA ─────────────
  Configurações
```

### Sidebar Styling
```tsx
<aside className="w-[220px] flex flex-col h-screen bg-[#f0ede8] border-r border-[#dedbd6]">
  {/* Logo */}
  <div className="px-5 py-5 border-b border-[#dedbd6]">
    <div className="flex items-center gap-2">
      <div className="w-7 h-7 rounded-[4px] bg-[#111111] flex items-center justify-center">
        <span className="text-xs font-medium text-white">V</span>
      </div>
      <span className="text-[15px] font-medium text-[#111111] tracking-tight">
        ValerIA<span className="text-[#ff5600] ml-0.5">·</span>
      </span>
    </div>
  </div>

  {/* Nav groups */}
  <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-4">
    {/* Group */}
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[1.2px] text-[#7b7b78] px-3 mb-1.5">Vendas</p>
      {/* Nav items */}
      <Link className={`flex items-center gap-3 px-3 py-2 rounded-[6px] text-[13px] transition-all ${
        isActive ? "bg-[#111111] text-white" : "text-[#313130] hover:bg-[#dedbd6]/60 hover:text-[#111111]"
      }`}>
        {icon} {label}
      </Link>
    </div>
  </nav>

  {/* User */}
  <div className="border-t border-[#dedbd6] px-3 py-3">
    <div className="flex items-center gap-2.5 px-3 py-2">
      <div className="w-7 h-7 rounded-[6px] bg-[#dedbd6]">{userIcon}</div>
      <p className="text-[13px] text-[#7b7b78] truncate">Cafe Canastra</p>
    </div>
  </div>
</aside>
```

### Page Header Pattern (applies to all pages)
```tsx
<div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between">
  <div>
    <h1 style={{ letterSpacing: '-0.96px', lineHeight: '1.00' }} className="text-[32px] font-normal text-[#111111]">
      {title}
    </h1>
    <p className="text-[14px] text-[#7b7b78] mt-0.5">{subtitle}</p>
  </div>
  <div className="flex gap-2">{actions}</div>
</div>
<div className="p-8">{content}</div>
```

---

## 3. Campanhas — Dashboard Executivo (página principal)

### Layout
```
[Page Header: "Campanhas" | "+ Disparo" "+ Cadência"]
[KPI Row: 5 cards hero em grid 5 cols]
[Trend Chart: full width, com period selector]
[2 colunas: Últimos Disparos (60%) | Últimas Cadências (40%)]
```

### KPI Hero Cards (5)
Usar pattern KPI Card com números 48px:
1. **Disparos Ativos** → número `#111111`, label "rodando agora"
2. **Cadências Ativas** → número `#111111`, label "configuradas"
3. **Leads em Follow-up** → número `text-[#ff5600]` (quando > 0)
4. **Taxa de Resposta** → número com cor dinâmica: >30% = `#0bdf50`, 10-30% = `#fe4c02`, <10% = `#c41c1c`
5. **Responderam** → número `#0bdf50`

### Trend Chart
- `bg-white border border-[#dedbd6] rounded-[8px] p-6`
- Title: "Respostas ao longo do tempo" — 18px font-medium
- Period selector: 3 pills "7d / 30d / 90d" — active `bg-[#111111] text-white rounded-[4px]`, inactive `border border-[#dedbd6] text-[#313130] rounded-[4px]`
- Line color: `#0bdf50`
- Grid lines: `#dedbd6` com opacity 40%

### Mini-listas (abaixo do gráfico)

**Últimos Disparos** (card `bg-white border border-[#dedbd6] rounded-[8px] p-5`):
- Header: "Disparos Recentes" (18px font-medium) + link "Ver todos →"
- Lista de até 5 broadcasts em rows:
  ```
  [status badge] Nome do disparo          [progress bar] 240/500
  ```
- Progress bar: `bg-[#dedbd6]` track, `bg-[#0bdf50]` fill para completed, `bg-[#ff5600]` para running

**Últimas Cadências** (mesmo estilo):
- Header: "Cadências Ativas" + "Ver todos →"
- Lista de até 5 cadências:
  ```
  [status badge] Nome da cadência         [N] leads ativos
  ```

### Navegação entre seções
Abas principais no topo da área de conteúdo (abaixo do header):
```tsx
<div className="border-b border-[#dedbd6] bg-white px-8">
  <div className="flex gap-0">
    <button className="border-b-2 border-[#111111] text-[#111111] px-4 py-3 text-[14px]">Visão Geral</button>
    <button className="border-b-2 border-transparent text-[#7b7b78] px-4 py-3 text-[14px] hover:text-[#111111]">Disparos</button>
    <button className="border-b-2 border-transparent text-[#7b7b78] px-4 py-3 text-[14px] hover:text-[#111111]">Cadências</button>
  </div>
</div>
```

---

## 4. Campanhas — Aba Disparos

### Layout
```
[Search bar | Filtros: Todos / Rascunho / Rodando / Completos]
[Grid 2 cols de BroadcastCards]
```

### BroadcastCard Redesign
```
┌─────────────────────────────────────────────────┐
│ [RODANDO]          Nome do Disparo        [···]  │
│                                                  │
│ Canal: Meta Business · 3 hrs atrás              │
│                                                  │
│ ████████████░░░░░░░░░░░░  48%                  │
│ 240 enviados de 500 leads                        │
│                                                  │
│ ┌──────┬──────┬──────┬──────┐                   │
│ │  240 │  215 │   25 │  261 │                   │
│ │Enviad│Entreg│Falhou│Pendnt│                   │
│ └──────┴──────┴──────┴──────┘                   │
│                                [Pausar] [Editar] │
└─────────────────────────────────────────────────┘
```
- Container: `bg-white border border-[#dedbd6] rounded-[8px] p-5`
- Status badge com cor semântica (ver tokens acima)
- Progress bar: track `bg-[#f0ede8]`, fill dinâmico por status
- Stats grid: `border-t border-[#dedbd6] pt-3 mt-3 grid grid-cols-4`
- Stat value: `text-[20px] font-normal` com tracking -0.3px
- Stat label: `text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]`

---

## 5. Campanhas — Aba Cadências

### CadenceCard Redesign
```
┌─────────────────────────────────────────────────┐
│ [ATIVA]           Nome da Cadência        [···]  │
│ Manual · 5 steps · Janela 7h-18h                │
│                                                  │
│ ┌─────────┬─────────┬─────────┬─────────┐       │
│ │   24    │   8     │   3     │   13    │       │
│ │ Ativos  │Respond. │Esgotado │Completo │       │
│ └─────────┴─────────┴─────────┴─────────┘       │
│                                                  │
│ Última atividade: há 2 horas    [Ver Detalhes →] │
└─────────────────────────────────────────────────┘
```
- Container: `bg-white border border-[#dedbd6] rounded-[8px] p-5`
- Stat "Ativos": `text-[#ff5600]` quando > 0
- Stat "Responderam": `text-[#0bdf50]`
- "Ver Detalhes →": link text `text-[#111111]` underline hover

---

## 6. Cadência — Página de Detalhe `/campanhas/[id]`

### Layout Geral
```
[Page Header: Nome · Status badge · [Pausar/Ativar]]
[Config bar: 3 badges inline — Janela · Cooldown · Max msgs]
[Tabs: Steps | Leads | Configuração]
[Conteúdo da aba]
```

### ABA STEPS — Timeline Visual
Substituir tabela plana por timeline vertical:

```
● Step 1                              [Dia 0]
│  "Olá {{nome}}, tudo bem? Sou da..."
│  [Editar] [Remover]
│
├─ 2 dias ─────────────────────────────
│
● Step 2                              [Dia 2]
│  "Oi {{nome}}, vi que você..."
│  [Editar] [Remover]
│
├─ 3 dias ─────────────────────────────
│
● Step 3                              [Dia 5]
  ...
  
[+ Adicionar Step]
```

Styling da timeline:
```tsx
// Container do step
<div className="flex gap-4">
  {/* Linha vertical */}
  <div className="flex flex-col items-center">
    <div className="w-3 h-3 rounded-full bg-[#111111] mt-1 flex-shrink-0" />
    <div className="w-px bg-[#dedbd6] flex-1 mt-1" />
  </div>
  {/* Conteúdo */}
  <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 mb-2 flex-1">
    <div className="flex justify-between items-start mb-2">
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Step {n}</span>
      <span className="text-[11px] text-[#7b7b78]">Dia {totalDays}</span>
    </div>
    <p className="text-[14px] text-[#111111] leading-relaxed">{message}</p>
    <div className="flex gap-2 mt-3">
      <button className="text-[13px] text-[#7b7b78] hover:text-[#111111]">Editar</button>
      <button className="text-[13px] text-[#c41c1c] hover:text-[#c41c1c]/70">Remover</button>
    </div>
  </div>
</div>
{/* Delay connector */}
<div className="flex items-center gap-2 ml-7 mb-2">
  <div className="h-px flex-1 border-t border-dashed border-[#dedbd6]" />
  <span className="text-[11px] text-[#7b7b78] whitespace-nowrap">{delay} dias</span>
  <div className="h-px flex-1 border-t border-dashed border-[#dedbd6]" />
</div>
```

### ABA LEADS — Monitor
```
[Search | Status filters: Todos / Ativos / Responderam / Esgotados / Completaram]

Tabela:
┌─────────────────┬──────────┬────────────┬─────────────┬──────────┐
│ Lead            │ Status   │ Progresso  │ Próximo env.│ Ações    │
├─────────────────┼──────────┼────────────┼─────────────┼──────────┤
│ João Silva      │ [ATIVO]  │ Step 2/5   │ Amanhã 9h   │ Pausar   │
│ 11 99999-9999   │          │ ████░░     │             │          │
└─────────────────┴──────────┴────────────┴─────────────┴──────────┘
```

- Progress inline: mini progress bar `w-16 h-1.5 bg-[#f0ede8] rounded-full` com fill `bg-[#ff5600]`
- "Próximo envio": se hoje = `text-[#ff5600]`, se futuro = `text-[#7b7b78]`, se respondeu = `text-[#0bdf50]`
- Status "Ativos": badge verde, "Responderam": badge azul, "Esgotados": badge laranja

### ABA CONFIGURAÇÃO
Manter funcionalidade, redesign visual com fieldsets agrupados em cards:
```
[Card: Trigger]    [Card: Janela de Envio]    [Card: Limites]
[Card: Nome e Descrição]
```

---

## 7. Outras Páginas

### Dashboard
- KPI cards com hero numbers (48px) para métricas principais
- Funil: barras horizontais com report palette (azul escurecendo conforme converte)
- Page header pattern com `bg-white border-b`

### Leads
- Page header com `bg-white border-b`
- Filter bar: `bg-[#f0ede8]` para destacar da área de cards
- Lead cards: `bg-white border border-[#dedbd6]` — temperatura como dot colorido (verde/amarelo/vermelho)
- Stage badge: usar as stage colors existentes em `#constants.ts`

### Vendas (Kanban)
- Background das colunas: `bg-[#f7f5f1]` (surface-raised) para diferenciar do canvas
- Deal cards: `bg-white border border-[#dedbd6]`
- Column header: `bg-[#f0ede8]` com count badge `bg-[#111111] text-white`
- Valor total da coluna: exibir em `text-[20px]` com tracking negativo

### Conversas
- Chat list: `bg-[#f0ede8]` — consistente com sidebar
- Chat bubbles: mantém padrão (incoming white, outgoing `#111111`)
- Contact panel: `bg-white border-l` — surface-card para parecer "elevado"

### Login
- Página toda `bg-[#f0ede8]` (surface-nav) — diferente do canvas
- Card central: `bg-white border border-[#dedbd6] rounded-[8px]` com sombra leve `shadow-sm`

---

## 8. Restrições Absolutas

1. **Backend:** Nenhum arquivo em `src/app/api/`, `src/hooks/`, `src/lib/` pode ser modificado
2. **Dados:** Todos os props, callbacks e estados existentes devem ser preservados
3. **Geist font:** Mantém — já configurado
4. **Tokens CSS:** Apenas adicionar novos — não remover os existentes em globals.css
5. **TypeScript:** Zero erros após cada commit

---

## 9. Globals.css — Novos tokens a adicionar

```css
:root {
  /* Surface layers */
  --surface-nav: #f0ede8;
  --surface-canvas: #faf9f6;
  --surface-card: #ffffff;
  --surface-raised: #f7f5f1;
}
```
