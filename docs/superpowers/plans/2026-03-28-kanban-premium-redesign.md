# Kanban Premium Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Qualificacao and Vendas kanban boards with dark premium headers, dark metric cards, avatared lead cards, and minimal empty states.

**Architecture:** Update constants with new color tokens (dotColor, tintColor, avatarColor), then rewrite shared components bottom-up: metrics bar → lead card → kanban column → filters → quick-add → page-level integration. All changes are CSS/JSX only — no backend, no new dependencies.

**Tech Stack:** Next.js, React, Tailwind CSS, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-28-kanban-premium-redesign-design.md`

---

### Task 1: Add color tokens to constants

**Files:**
- Modify: `crm/src/lib/constants.ts:1-37`

- [ ] **Step 1: Update AGENT_STAGES with dotColor, tintColor, avatarColor**

Replace the entire `AGENT_STAGES` array at `constants.ts:1-7`:

```typescript
export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-[#f4f4f0]", dotColor: "#c8cc8e", tintColor: "#f2f3eb", avatarColor: "#c8cc8e" },
  { key: "atacado", label: "Atacado", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5aad65" },
  { key: "private_label", label: "Private Label", color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "exportacao", label: "Exportacao", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#e8d44d" },
  { key: "consumo", label: "Consumo", color: "bg-[#f0ecd0]", dotColor: "#d4b84a", tintColor: "#f4f2ea", avatarColor: "#d4b84a" },
] as const;
```

- [ ] **Step 2: Update SELLER_STAGES with dotColor, tintColor, avatarColor**

Replace `SELLER_STAGES` at `constants.ts:9-15`:

```typescript
export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "em_contato", label: "Em Contato", color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "negociacao", label: "Negociacao", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "fechado", label: "Fechado", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "perdido", label: "Perdido", color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
] as const;
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: no errors (existing consumers still use `color`, `key`, `label` which are unchanged)

- [ ] **Step 4: Commit**

```bash
git add crm/src/lib/constants.ts
git commit -m "feat: add dotColor, tintColor, avatarColor tokens to stage constants"
```

---

### Task 2: Redesign KanbanMetricsBar — dark metric cards

**Files:**
- Modify: `crm/src/components/kanban-metrics-bar.tsx:1-44`

- [ ] **Step 1: Rewrite the entire component**

Replace the full contents of `kanban-metrics-bar.tsx`:

```tsx
import type { Lead } from "@/lib/types";

interface KanbanMetricsBarProps {
  leads: Lead[];
}

export function KanbanMetricsBar({ leads }: KanbanMetricsBarProps) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const totalValue = leads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;
  const leadsYesterday = leads.filter((l) => {
    const d = new Date(l.created_at);
    return d >= yesterday && d < today;
  }).length;
  const potentialValue = leads
    .filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado")
    .reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMs =
    withResponse.length > 0
      ? withResponse.reduce(
          (sum, l) =>
            sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime()),
          0
        ) / withResponse.length
      : 0;
  const avgResponseMin = Math.round(avgResponseMs / 60000);
  const responseStr = avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014";

  const fmt = (v: number) =>
    `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const pipelinePct = totalValue > 0 ? Math.round((potentialValue / totalValue) * 100) : 0;

  return (
    <div className="flex gap-3.5 mb-5">
      {/* Total */}
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Total no funil
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leads.length}
          </span>
          <span className="text-[12px] text-[#9ca3af]">leads</span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">{fmt(totalValue)} em pipeline</p>
      </div>

      {/* Novos */}
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Novos hoje / ontem
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leadsToday}
          </span>
          <span className="text-[12px] text-[#9ca3af]">/ {leadsYesterday}</span>
        </div>
        {leadsToday > leadsYesterday && (
          <p className="text-[11px] text-[#5aad65] mt-1.5">↑ crescendo</p>
        )}
        {leadsToday <= leadsYesterday && leadsToday > 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">→ estavel</p>
        )}
        {leadsToday === 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">nenhum hoje</p>
        )}
      </div>

      {/* Vendas em potencial */}
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Vendas em potencial
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-[#5aad65] leading-none">
            {fmt(potentialValue)}
          </span>
        </div>
        <div className="mt-2 h-[3px] bg-[#333] rounded-full">
          <div
            className="h-full bg-[#5aad65] rounded-full transition-all duration-500"
            style={{ width: `${Math.min(pipelinePct, 100)}%` }}
          />
        </div>
      </div>

      {/* Tempo medio */}
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Tempo medio resp.
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {responseStr}
          </span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">agente IA</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/kanban-metrics-bar.tsx
git commit -m "feat: redesign metrics bar with dark premium cards"
```

---

### Task 3: Redesign LeadCard — dark avatar with colored initial

**Files:**
- Modify: `crm/src/components/lead-card.tsx:1-123`

- [ ] **Step 1: Rewrite the entire component**

Replace the full contents of `lead-card.tsx`:

```tsx
import type { Lead, Tag } from "@/lib/types";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins}min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

function formatCurrency(value: number): string {
  if (value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface LeadCardProps {
  lead: Lead;
  onClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  unreadCount?: number;
  tags?: Tag[];
  lastMessage?: string | null;
  avatarColor?: string;
}

export function LeadCard({
  lead,
  onClick,
  showAgentStage,
  unreadCount,
  tags,
  lastMessage,
  avatarColor = "#c8cc8e",
}: LeadCardProps) {
  const currencyStr = formatCurrency(lead.sale_value ?? 0);
  const initial = (lead.name || lead.phone)?.[0]?.toUpperCase() || "?";

  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-white rounded-[10px] border border-[#e5e5dc] p-3 transition-all duration-150 hover:-translate-y-[1px] hover:shadow-[0_4px_12px_rgba(0,0,0,0.08)]"
      style={{ boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}
    >
      {/* Row 1: Avatar + Name + Time */}
      <div className="flex items-center gap-2.5 mb-2">
        <div
          className="w-[34px] h-[34px] rounded-full bg-[#1f1f1f] flex items-center justify-center text-[13px] font-bold flex-shrink-0"
          style={{ color: avatarColor }}
        >
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-[#1f1f1f] truncate">
              {lead.name || lead.phone}
            </span>
            <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
              {unreadCount && unreadCount > 0 ? (
                <span className="bg-[#e8d44d] text-[#1f1f1f] text-[10px] font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                  {unreadCount}
                </span>
              ) : null}
              <span className="text-[10px] text-[#9ca3af]">
                {timeAgo(lead.last_msg_at)}
              </span>
            </div>
          </div>
          {currencyStr && (
            <span className="text-[11px] font-semibold text-[#2d6a3f]">
              {currencyStr}
            </span>
          )}
        </div>
      </div>

      {/* Row 2: Tags */}
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="text-[9px] font-medium px-2 py-0.5 rounded-md"
              style={{ backgroundColor: tag.color + "22", color: tag.color }}
            >
              {tag.name}
            </span>
          ))}
          {showAgentStage && (
            <span className="text-[9px] font-medium text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-md">
              {lead.stage}
            </span>
          )}
          {tags.length > 3 && (
            <span className="text-[9px] text-[#9ca3af]">+{tags.length - 3}</span>
          )}
        </div>
      )}
      {/* Show agent stage even without tags */}
      {showAgentStage && (!tags || tags.length === 0) && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          <span className="text-[9px] font-medium text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-md">
            {lead.stage}
          </span>
        </div>
      )}

      {/* Row 3: Last message preview */}
      {lastMessage && (
        <p className="text-[11px] text-[#9ca3af] truncate italic">
          &ldquo;{lastMessage}&rdquo;
        </p>
      )}
    </button>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/lead-card.tsx
git commit -m "feat: redesign lead card with dark avatar and compact layout"
```

---

### Task 4: Redesign KanbanColumn — dark header + tinted body + empty state

**Files:**
- Modify: `crm/src/components/kanban-column.tsx:1-73`

- [ ] **Step 1: Rewrite the entire component**

Replace the full contents of `kanban-column.tsx`:

```tsx
import type { Lead, Tag } from "@/lib/types";
import { LeadCard } from "./lead-card";

interface KanbanColumnProps {
  title: string;
  leads: Lead[];
  dotColor: string;
  tintColor: string;
  avatarColor: string;
  onLeadClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  leadTagsMap?: Record<string, Tag[]>;
  lastMessagesMap?: Record<string, string>;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}

export function KanbanColumn({
  title,
  leads,
  dotColor,
  tintColor,
  avatarColor,
  onLeadClick,
  showAgentStage,
  leadTagsMap,
  lastMessagesMap,
  children,
  footer,
}: KanbanColumnProps) {
  return (
    <div className="flex-shrink-0 w-[270px]">
      {/* Dark header */}
      <div className="bg-[#1f1f1f] rounded-t-xl px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
          <h3 className="text-[12px] font-semibold text-white">{title}</h3>
        </div>
        <span className="text-[10px] font-semibold text-white bg-white/15 rounded-full px-2 py-0.5">
          {leads.length}
        </span>
      </div>

      {/* Tinted body */}
      <div
        className="rounded-b-xl p-2.5 min-h-[calc(100vh-280px)] space-y-2.5 overflow-y-auto"
        style={{ backgroundColor: tintColor }}
      >
        {children}
        {!children && leads.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#b0adb5] mb-3">Nenhum lead</p>
          </div>
        )}
        {!children &&
          leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onClick={onLeadClick}
              showAgentStage={showAgentStage}
              tags={leadTagsMap?.[lead.id]}
              lastMessage={lastMessagesMap?.[lead.id]}
              avatarColor={avatarColor}
            />
          ))}
        {footer}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: errors in `qualificacao/page.tsx` referencing old `colorClass` prop — expected, will fix in Task 6.

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/kanban-column.tsx
git commit -m "feat: redesign kanban column with dark header and tinted body"
```

---

### Task 5: Update KanbanFilters — add search icon

**Files:**
- Modify: `crm/src/components/kanban-filters.tsx:1-32`

- [ ] **Step 1: Rewrite the component with search icon**

Replace the full contents of `kanban-filters.tsx`:

```tsx
"use client";

interface KanbanFiltersProps {
  search: string;
  onSearchChange: (val: string) => void;
  showActive: boolean;
  onToggleActive: () => void;
}

export function KanbanFilters({ search, onSearchChange, showActive, onToggleActive }: KanbanFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="relative w-80">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar por nome, empresa ou telefone..."
          className="w-full text-[13px] rounded-[10px] pl-9 pr-4 py-2.5 bg-white border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors text-[#1f1f1f] placeholder:text-[#9ca3af]"
        />
      </div>
      <button
        onClick={onToggleActive}
        className={`px-4 py-2.5 rounded-[10px] text-[12px] font-medium transition-colors ${
          showActive
            ? "bg-[#1f1f1f] text-white"
            : "bg-white text-[#5f6368] border border-[#e5e5dc] hover:bg-[#f6f7ed]"
        }`}
      >
        Leads ativos
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/kanban-filters.tsx
git commit -m "feat: add search icon to kanban filters"
```

---

### Task 6: Update QuickAddLead — dashed style consistent with empty state

**Files:**
- Modify: `crm/src/components/quick-add-lead.tsx:44-52`

- [ ] **Step 1: Update the closed-state button**

Replace the button at `quick-add-lead.tsx:44-52`:

```tsx
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-center py-2 text-[12px] text-[#9ca3af] hover:text-[#5f6368] border border-dashed border-[#d4d4c8] hover:border-[#c8cc8e] rounded-[10px] transition-colors mt-2"
      >
        + Adicionar lead
      </button>
    );
  }
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/quick-add-lead.tsx
git commit -m "feat: update quick-add button to dashed style"
```

---

### Task 7: Update Qualificacao page — pass new color props

**Files:**
- Modify: `crm/src/app/(authenticated)/qualificacao/page.tsx:87-101`

- [ ] **Step 1: Update the columns section**

Replace the `<div className="flex gap-5 ...">` block at `qualificacao/page.tsx:87-101`:

```tsx
      <div className="flex gap-3 overflow-x-auto pb-4">
        {AGENT_STAGES.map((stage) => {
          const stageLeads = filteredLeads.filter((l) => l.stage === stage.key);
          return (
            <KanbanColumn
              key={stage.key}
              title={stage.label}
              leads={stageLeads}
              dotColor={stage.dotColor}
              tintColor={stage.tintColor}
              avatarColor={stage.avatarColor}
              onLeadClick={setSelectedLead}
              leadTagsMap={leadTagsMap}
              footer={<QuickAddLead stage={stage.key} />}
            />
          );
        })}
      </div>
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: errors only in vendas page (still using old props) — will fix in Task 8.

- [ ] **Step 3: Commit**

```bash
git add "crm/src/app/(authenticated)/qualificacao/page.tsx"
git commit -m "feat: wire qualificacao kanban to premium column props"
```

---

### Task 8: Update Vendas page — DroppableColumn with premium design

**Files:**
- Modify: `crm/src/app/(authenticated)/vendas/page.tsx:26-83,211-236`

- [ ] **Step 1: Rewrite DroppableColumn with dark header + tinted body**

Replace the `DroppableColumn` function at `vendas/page.tsx:26-83`:

```tsx
function DroppableColumn({
  id,
  title,
  dotColor,
  tintColor,
  avatarColor,
  leads,
  onLeadClick,
  leadTagsMap,
}: {
  id: string;
  title: string;
  dotColor: string;
  tintColor: string;
  avatarColor: string;
  leads: Lead[];
  onLeadClick: (lead: Lead) => void;
  leadTagsMap: Record<string, Tag[]>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });

  return (
    <div className="flex-shrink-0 w-[270px]">
      {/* Dark header */}
      <div className="bg-[#1f1f1f] rounded-t-xl px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
          <h3 className="text-[12px] font-semibold text-white">{title}</h3>
        </div>
        <span className="text-[10px] font-semibold text-white bg-white/15 rounded-full px-2 py-0.5">
          {leads.length}
        </span>
      </div>
      {/* Tinted body */}
      <div
        ref={setNodeRef}
        className={`rounded-b-xl p-2.5 min-h-[calc(100vh-280px)] space-y-2.5 overflow-y-auto transition-all duration-200 ${
          isOver
            ? "ring-2 ring-[#c8cc8e] ring-inset"
            : ""
        }`}
        style={{ backgroundColor: tintColor }}
      >
        {leads.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#b0adb5] mb-3">Nenhum lead</p>
          </div>
        )}
        {leads.map((lead) => (
          <DraggableLeadCard
            key={lead.id}
            lead={lead}
            onClick={onLeadClick}
            tags={leadTagsMap[lead.id]}
            avatarColor={avatarColor}
          />
        ))}
        <QuickAddLead stage="secretaria" sellerStage={id} humanControl />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update DraggableLeadCard to pass avatarColor**

Replace the `DraggableLeadCard` function at `vendas/page.tsx:85-109`:

```tsx
function DraggableLeadCard({
  lead,
  onClick,
  tags,
  avatarColor,
}: {
  lead: Lead;
  onClick: (lead: Lead) => void;
  tags?: Tag[];
  avatarColor?: string;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: lead.id,
    data: lead,
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={isDragging ? "opacity-30" : ""}
    >
      <LeadCard lead={lead} onClick={onClick} showAgentStage tags={tags} avatarColor={avatarColor} />
    </div>
  );
}
```

- [ ] **Step 3: Update the columns mapping to pass new props**

Replace the `SELLER_STAGES.map` block at `vendas/page.tsx:212-228`:

```tsx
        <div className="flex gap-3 overflow-x-auto pb-4">
          {SELLER_STAGES.map((stage) => {
            const stageLeads = filteredLeads.filter(
              (l) => l.seller_stage === stage.key
            );
            return (
              <DroppableColumn
                key={stage.key}
                id={stage.key}
                title={stage.label}
                dotColor={stage.dotColor}
                tintColor={stage.tintColor}
                avatarColor={stage.avatarColor}
                leads={stageLeads}
                onLeadClick={setChatLead}
                leadTagsMap={leadTagsMap}
              />
            );
          })}
        </div>
```

- [ ] **Step 4: Update DragOverlay to use premium card**

Replace the `<DragOverlay>` block:

```tsx
        <DragOverlay>
          {activeDrag ? (
            <div className="w-[270px] opacity-90 rotate-[2deg] shadow-xl">
              <LeadCard lead={activeDrag} onClick={() => {}} showAgentStage />
            </div>
          ) : null}
        </DragOverlay>
```

- [ ] **Step 5: Verify TypeScript compiles clean**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add "crm/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat: wire vendas kanban to premium column and card design"
```

---

### Task 9: Final verification

**Files:** None (read-only verification)

- [ ] **Step 1: Full TypeScript check**

Run: `cd crm && npx tsc --noEmit 2>&1 | tail -10`

Expected: no errors

- [ ] **Step 2: Visual verification reminder**

After all tasks pass TypeScript, open `http://localhost:3000/qualificacao` and `http://localhost:3000/vendas` in browser to visually confirm:

- Dark metric cards with large white numbers
- Dark column headers with colored dots
- Tinted column backgrounds per stage
- Lead cards with dark avatars and colored initials
- Empty states showing "Nenhum lead" + dashed add button
- Search input with magnifying glass icon
- Drag-and-drop still works on Vendas page

- [ ] **Step 3: Commit any fixes if needed, then final commit**

```bash
git status
```

If clean, no commit needed.
