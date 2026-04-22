# ValerIA CRM Kanban — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CRM with dual Kanban (agent qualification + seller pipeline), integrated WhatsApp chat, dashboard with metrics, and campaign management for Cafe Canastra's sales team.

**Architecture:** Next.js 14 App Router reads from Supabase (Postgres + Realtime) for live updates. Chat messages are sent via Next.js API routes that proxy to Evolution API or Meta Cloud API based on lead's `channel` field. The existing FastAPI backend continues handling webhooks, agent logic, and campaigns independently.

**Tech Stack:** Next.js 14 (App Router), Tailwind CSS, Supabase JS client (@supabase/supabase-js + @supabase/ssr), @dnd-kit (drag & drop), Recharts (dashboard charts), TypeScript

---

## File Structure

```
crm/
├── .env.local                          # Supabase + API keys
├── package.json
├── tailwind.config.ts
├── tsconfig.json
├── next.config.ts
├── middleware.ts                        # Auth redirect guard
├── src/
│   ├── lib/
│   │   ├── supabase/
│   │   │   ├── client.ts               # Browser Supabase client
│   │   │   └── server.ts               # Server-side Supabase client
│   │   ├── types.ts                    # DB types (Lead, Message, Campaign)
│   │   └── constants.ts                # Stage/status labels, colors
│   ├── hooks/
│   │   ├── use-realtime-leads.ts       # Realtime subscription for leads
│   │   ├── use-realtime-messages.ts    # Realtime subscription for messages
│   │   └── use-realtime-campaigns.ts   # Realtime subscription for campaigns
│   ├── components/
│   │   ├── sidebar.tsx                 # Fixed sidebar navigation
│   │   ├── lead-card.tsx               # Shared lead card (used in both kanbans)
│   │   ├── chat-panel.tsx              # Read-only chat (qualificacao)
│   │   ├── chat-active.tsx             # Active chat with input (vendas)
│   │   ├── lead-detail-sidebar.tsx     # Lead data sidebar
│   │   ├── kanban-column.tsx           # Single kanban column
│   │   ├── kpi-card.tsx                # Dashboard KPI card
│   │   ├── funnel-chart.tsx            # Dashboard funnel
│   │   └── campaign-table.tsx          # Campaigns list table
│   ├── app/
│   │   ├── layout.tsx                  # Root layout with sidebar
│   │   ├── page.tsx                    # Redirect to /dashboard
│   │   ├── login/
│   │   │   └── page.tsx                # Login page
│   │   ├── dashboard/
│   │   │   └── page.tsx                # Dashboard with KPIs + funnel + campaign metrics
│   │   ├── qualificacao/
│   │   │   └── page.tsx                # Read-only kanban (agent stages)
│   │   ├── vendas/
│   │   │   └── page.tsx                # Active kanban (seller pipeline)
│   │   ├── campanhas/
│   │   │   └── page.tsx                # Campaign management
│   │   ├── config/
│   │   │   └── page.tsx                # Settings page
│   │   └── api/
│   │       └── chat/
│   │           └── send/
│   │               └── route.ts        # POST: send message via Evolution/Meta API
backend-evolution/
├── migrations/
│   └── 002_crm_columns.sql             # New columns for CRM
├── app/agent/tools.py                  # Modify encaminhar_humano
```

---

### Task 1: Database Migration — Add CRM Columns

**Files:**
- Create: `backend-evolution/migrations/002_crm_columns.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 002_crm_columns.sql
-- Run this in Supabase SQL Editor after 001_initial.sql

-- CRM columns on leads
ALTER TABLE leads ADD COLUMN IF NOT EXISTS seller_stage text DEFAULT 'novo';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS assigned_to uuid;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS human_control boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS channel text DEFAULT 'evolution';

-- Indexes for CRM queries
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_human_control ON leads(human_control);

-- Sender tracking on messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_by text DEFAULT 'agent';

-- Enable Realtime on tables the CRM subscribes to
ALTER PUBLICATION supabase_realtime ADD TABLE leads;
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/migrations/002_crm_columns.sql
git commit -m "feat: add CRM columns migration (seller_stage, human_control, channel, sent_by)"
```

---

### Task 2: Modify encaminhar_humano Tool

**Files:**
- Modify: `backend-evolution/app/agent/tools.py` (the `encaminhar_humano` branch in `execute_tool`)

- [ ] **Step 1: Update encaminhar_humano to set CRM fields**

In `backend-evolution/app/agent/tools.py`, find the `encaminhar_humano` branch inside `execute_tool` and change it from:

```python
elif tool_name == "encaminhar_humano":
    update_lead(lead_id, status="converted")
    save_message(lead_id, "system", f"Lead encaminhado para {args['vendedor']}: {args['motivo']}")
    return f"Lead encaminhado para {args['vendedor']}"
```

To:

```python
elif tool_name == "encaminhar_humano":
    update_lead(lead_id, status="converted", human_control=True, seller_stage="novo")
    save_message(lead_id, "system", f"Lead encaminhado para {args['vendedor']}: {args['motivo']}")
    return f"Lead encaminhado para {args['vendedor']}"
```

- [ ] **Step 2: Verify update_lead accepts kwargs**

Read `backend-evolution/app/leads/service.py` and confirm `update_lead` uses `**fields` pattern so it can accept `human_control` and `seller_stage` without changes.

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/app/agent/tools.py
git commit -m "feat: set human_control and seller_stage on encaminhar_humano"
```

---

### Task 3: Scaffold Next.js Project

**Files:**
- Create: `crm/` directory with Next.js boilerplate

- [ ] **Step 1: Create Next.js app**

```bash
cd "C:/Users/rafae/OneDrive/Desktop/Canastra Inteligencia/Agentes AI/ValerIA"
npx create-next-app@latest crm --typescript --tailwind --eslint --app --src-dir --no-import-alias --use-npm
```

Accept defaults. This creates the full Next.js scaffold.

- [ ] **Step 2: Install dependencies**

```bash
cd crm
npm install @supabase/supabase-js @supabase/ssr @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities recharts
```

- [ ] **Step 3: Create .env.local**

Create `crm/.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
EVOLUTION_API_URL=your_evolution_api_url
EVOLUTION_API_KEY=your_evolution_api_key
EVOLUTION_INSTANCE=your_instance_name
META_PHONE_NUMBER_ID=your_meta_phone_number_id
META_ACCESS_TOKEN=your_meta_access_token
META_API_VERSION=v21.0
```

- [ ] **Step 4: Create .env.example (same file without values)**

Create `crm/.env.example`:

```env
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
EVOLUTION_API_URL=
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=
META_PHONE_NUMBER_ID=
META_ACCESS_TOKEN=
META_API_VERSION=v21.0
```

- [ ] **Step 5: Commit**

```bash
git add crm/
git commit -m "feat: scaffold Next.js CRM project with dependencies"
```

---

### Task 4: Supabase Clients + Types + Constants

**Files:**
- Create: `crm/src/lib/supabase/client.ts`
- Create: `crm/src/lib/supabase/server.ts`
- Create: `crm/src/lib/types.ts`
- Create: `crm/src/lib/constants.ts`

- [ ] **Step 1: Create browser Supabase client**

Create `crm/src/lib/supabase/client.ts`:

```typescript
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}
```

- [ ] **Step 2: Create server Supabase client**

Create `crm/src/lib/supabase/server.ts`:

```typescript
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          );
        },
      },
    }
  );
}
```

- [ ] **Step 3: Create TypeScript types**

Create `crm/src/lib/types.ts`:

```typescript
export interface Lead {
  id: string;
  phone: string;
  name: string | null;
  company: string | null;
  stage: string;
  status: string;
  campaign_id: string | null;
  last_msg_at: string | null;
  created_at: string;
  seller_stage: string;
  assigned_to: string | null;
  human_control: boolean;
  channel: string;
}

export interface Message {
  id: string;
  lead_id: string;
  role: string;       // "user" | "assistant" | "system"
  content: string;
  stage: string | null;
  sent_by: string;    // "agent" | "seller"
  created_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  template_name: string;
  template_params: Record<string, unknown> | null;
  total_leads: number;
  sent: number;
  failed: number;
  replied: number;
  status: string;
  send_interval_min: number;
  send_interval_max: number;
  created_at: string;
}
```

- [ ] **Step 4: Create constants**

Create `crm/src/lib/constants.ts`:

```typescript
export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-gray-100" },
  { key: "atacado", label: "Atacado", color: "bg-blue-100" },
  { key: "private_label", label: "Private Label", color: "bg-purple-100" },
  { key: "exportacao", label: "Exportacao", color: "bg-green-100" },
  { key: "consumo", label: "Consumo", color: "bg-yellow-100" },
] as const;

export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-red-100" },
  { key: "em_contato", label: "Em Contato", color: "bg-orange-100" },
  { key: "negociacao", label: "Negociacao", color: "bg-blue-100" },
  { key: "fechado", label: "Fechado", color: "bg-green-100" },
  { key: "perdido", label: "Perdido", color: "bg-gray-100" },
] as const;

export const CAMPAIGN_STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-200 text-gray-700",
  running: "bg-green-200 text-green-700",
  paused: "bg-yellow-200 text-yellow-700",
  completed: "bg-blue-200 text-blue-700",
};
```

- [ ] **Step 5: Commit**

```bash
git add crm/src/lib/
git commit -m "feat: add Supabase clients, types, and constants"
```

---

### Task 5: Auth — Login Page + Middleware Guard

**Files:**
- Create: `crm/src/app/login/page.tsx`
- Create: `crm/middleware.ts`

- [ ] **Step 1: Create login page**

Create `crm/src/app/login/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setError("Email ou senha incorretos");
      setLoading(false);
      return;
    }

    router.push("/dashboard");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white p-8 rounded-lg shadow-md w-full max-w-sm"
      >
        <h1 className="text-2xl font-bold mb-6 text-center text-gray-900">
          ValerIA CRM
        </h1>
        {error && (
          <p className="text-red-600 text-sm mb-4 text-center">{error}</p>
        )}
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 mb-3 text-gray-900"
          required
        />
        <input
          type="password"
          placeholder="Senha"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 mb-4 text-gray-900"
          required
        />
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-gray-900 text-white py-2 rounded hover:bg-gray-800 disabled:opacity-50"
        >
          {loading ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Create middleware for auth guard**

Create `crm/middleware.ts`:

```typescript
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            request.cookies.set(name, value);
            supabaseResponse.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user && !request.nextUrl.pathname.startsWith("/login")) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  if (user && request.nextUrl.pathname.startsWith("/login")) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/login/ crm/middleware.ts
git commit -m "feat: add login page and auth middleware guard"
```

---

### Task 6: Layout — Sidebar + Root Layout

**Files:**
- Create: `crm/src/components/sidebar.tsx`
- Modify: `crm/src/app/layout.tsx`
- Modify: `crm/src/app/page.tsx`

- [ ] **Step 1: Create sidebar component**

Create `crm/src/components/sidebar.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/qualificacao", label: "Qualificacao" },
  { href: "/vendas", label: "Vendas" },
  { href: "/campanhas", label: "Campanhas" },
  { href: "/config", label: "Configuracoes" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <aside className="w-56 bg-gray-900 text-white min-h-screen flex flex-col">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold">ValerIA CRM</h1>
      </div>
      <nav className="flex-1 p-2">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`block px-3 py-2 rounded text-sm mb-1 ${
              pathname === item.href
                ? "bg-gray-700 text-white"
                : "text-gray-300 hover:bg-gray-800"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="p-4 border-t border-gray-700">
        <button
          onClick={handleLogout}
          className="text-gray-400 text-sm hover:text-white"
        >
          Sair
        </button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Update root layout**

Replace the content of `crm/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ValerIA CRM",
  description: "CRM Cafe Canastra",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Create authenticated layout wrapper**

Create `crm/src/app/(authenticated)/layout.tsx`:

```tsx
import { Sidebar } from "@/components/sidebar";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 bg-gray-50 p-6 overflow-auto">{children}</main>
    </div>
  );
}
```

- [ ] **Step 4: Redirect root to dashboard**

Replace `crm/src/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/dashboard");
}
```

- [ ] **Step 5: Move all page routes under (authenticated) group**

Create the following directory structure — all page files will be created in subsequent tasks, but create placeholder pages now:

Create `crm/src/app/(authenticated)/dashboard/page.tsx`:
```tsx
export default function DashboardPage() {
  return <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>;
}
```

Create `crm/src/app/(authenticated)/qualificacao/page.tsx`:
```tsx
export default function QualificacaoPage() {
  return <h1 className="text-2xl font-bold text-gray-900">Qualificacao</h1>;
}
```

Create `crm/src/app/(authenticated)/vendas/page.tsx`:
```tsx
export default function VendasPage() {
  return <h1 className="text-2xl font-bold text-gray-900">Vendas</h1>;
}
```

Create `crm/src/app/(authenticated)/campanhas/page.tsx`:
```tsx
export default function CampanhasPage() {
  return <h1 className="text-2xl font-bold text-gray-900">Campanhas</h1>;
}
```

Create `crm/src/app/(authenticated)/config/page.tsx`:
```tsx
export default function ConfigPage() {
  return <h1 className="text-2xl font-bold text-gray-900">Configuracoes</h1>;
}
```

- [ ] **Step 6: Verify dev server starts**

```bash
cd crm && npm run dev
```

Open `http://localhost:3000` — should redirect to `/login`. Expected: login form visible.

- [ ] **Step 7: Commit**

```bash
git add crm/src/components/sidebar.tsx crm/src/app/
git commit -m "feat: add sidebar layout, auth redirect, and placeholder pages"
```

---

### Task 7: Realtime Hooks

**Files:**
- Create: `crm/src/hooks/use-realtime-leads.ts`
- Create: `crm/src/hooks/use-realtime-messages.ts`
- Create: `crm/src/hooks/use-realtime-campaigns.ts`

- [ ] **Step 1: Create realtime leads hook**

Create `crm/src/hooks/use-realtime-leads.ts`:

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Lead } from "@/lib/types";

export function useRealtimeLeads(filter?: { human_control?: boolean }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchLeads = useCallback(async () => {
    let query = supabase.from("leads").select("*").order("last_msg_at", { ascending: false, nullsFirst: false });

    if (filter?.human_control !== undefined) {
      query = query.eq("human_control", filter.human_control);
    }

    const { data } = await query;
    if (data) setLeads(data);
    setLoading(false);
  }, [filter?.human_control]);

  useEffect(() => {
    fetchLeads();

    const channel = supabase
      .channel("leads-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "leads" },
        () => {
          fetchLeads();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchLeads]);

  return { leads, loading };
}
```

- [ ] **Step 2: Create realtime messages hook**

Create `crm/src/hooks/use-realtime-messages.ts`:

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Message } from "@/lib/types";

export function useRealtimeMessages(leadId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchMessages = useCallback(async () => {
    if (!leadId) {
      setMessages([]);
      setLoading(false);
      return;
    }

    const { data } = await supabase
      .from("messages")
      .select("*")
      .eq("lead_id", leadId)
      .order("created_at", { ascending: true })
      .limit(200);

    if (data) setMessages(data);
    setLoading(false);
  }, [leadId]);

  useEffect(() => {
    fetchMessages();

    if (!leadId) return;

    const channel = supabase
      .channel(`messages-${leadId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `lead_id=eq.${leadId}`,
        },
        (payload) => {
          setMessages((prev) => [...prev, payload.new as Message]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [leadId, fetchMessages]);

  return { messages, loading };
}
```

- [ ] **Step 3: Create realtime campaigns hook**

Create `crm/src/hooks/use-realtime-campaigns.ts`:

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Campaign } from "@/lib/types";

export function useRealtimeCampaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchCampaigns = useCallback(async () => {
    const { data } = await supabase
      .from("campaigns")
      .select("*")
      .order("created_at", { ascending: false });

    if (data) setCampaigns(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchCampaigns();

    const channel = supabase
      .channel("campaigns-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "campaigns" },
        () => {
          fetchCampaigns();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchCampaigns]);

  return { campaigns, loading };
}
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/hooks/
git commit -m "feat: add realtime hooks for leads, messages, and campaigns"
```

---

### Task 8: Kanban Column + Lead Card Components

**Files:**
- Create: `crm/src/components/kanban-column.tsx`
- Create: `crm/src/components/lead-card.tsx`

- [ ] **Step 1: Create lead card component**

Create `crm/src/components/lead-card.tsx`:

```tsx
import type { Lead } from "@/lib/types";

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

interface LeadCardProps {
  lead: Lead;
  onClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  unreadCount?: number;
}

export function LeadCard({ lead, onClick, showAgentStage, unreadCount }: LeadCardProps) {
  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-white rounded-lg shadow-sm border border-gray-200 p-3 hover:shadow-md transition-shadow"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-gray-900 text-sm truncate">
          {lead.name || lead.phone}
        </span>
        {unreadCount && unreadCount > 0 ? (
          <span className="bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
            {unreadCount}
          </span>
        ) : null}
      </div>

      {showAgentStage && (
        <p className="text-xs text-gray-500 mb-1">
          {lead.stage} · {timeAgo(lead.last_msg_at)}
        </p>
      )}

      {!showAgentStage && (
        <p className="text-xs text-gray-500 mb-1">
          {lead.phone} {lead.company ? `· ${lead.company}` : ""}
        </p>
      )}

      <p className="text-xs text-gray-400 truncate">
        {timeAgo(lead.last_msg_at)}
      </p>
    </button>
  );
}
```

- [ ] **Step 2: Create kanban column component**

Create `crm/src/components/kanban-column.tsx`:

```tsx
import type { Lead } from "@/lib/types";
import { LeadCard } from "./lead-card";

interface KanbanColumnProps {
  title: string;
  leads: Lead[];
  colorClass: string;
  onLeadClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  id?: string;
  children?: React.ReactNode;
}

export function KanbanColumn({
  title,
  leads,
  colorClass,
  onLeadClick,
  showAgentStage,
  children,
}: KanbanColumnProps) {
  return (
    <div className="flex-shrink-0 w-72">
      <div className={`rounded-t-lg px-3 py-2 ${colorClass}`}>
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-sm text-gray-800">{title}</h3>
          <span className="text-xs text-gray-600 bg-white/60 rounded-full px-2 py-0.5">
            {leads.length}
          </span>
        </div>
      </div>
      <div className="bg-gray-100 rounded-b-lg p-2 min-h-[calc(100vh-200px)] space-y-2 overflow-y-auto">
        {children}
        {!children &&
          leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onClick={onLeadClick}
              showAgentStage={showAgentStage}
            />
          ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/kanban-column.tsx crm/src/components/lead-card.tsx
git commit -m "feat: add KanbanColumn and LeadCard components"
```

---

### Task 9: Chat Panel (Read-Only) + Chat Active Components

**Files:**
- Create: `crm/src/components/chat-panel.tsx`
- Create: `crm/src/components/chat-active.tsx`
- Create: `crm/src/components/lead-detail-sidebar.tsx`

- [ ] **Step 1: Create read-only chat panel**

Create `crm/src/components/chat-panel.tsx`:

```tsx
"use client";

import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import type { Lead } from "@/lib/types";

interface ChatPanelProps {
  lead: Lead;
  onClose: () => void;
}

export function ChatPanel({ lead, onClose }: ChatPanelProps) {
  const { messages, loading } = useRealtimeMessages(lead.id);

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-xl border-l border-gray-200 flex flex-col z-50">
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        <div>
          <h2 className="font-medium text-gray-900">
            {lead.name || lead.phone}
          </h2>
          <p className="text-xs text-gray-500">{lead.stage} · Somente leitura</p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-xl"
        >
          &times;
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading && <p className="text-gray-400 text-sm">Carregando...</p>}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                msg.role === "user"
                  ? "bg-green-100 text-gray-900"
                  : msg.role === "system"
                  ? "bg-gray-200 text-gray-500 italic text-xs text-center w-full"
                  : "bg-gray-100 text-gray-900"
              }`}
            >
              {msg.role === "assistant" && (
                <p className="text-xs text-gray-400 mb-1">
                  {msg.sent_by === "seller" ? "Vendedor" : "Agente"}
                </p>
              )}
              <p className="whitespace-pre-wrap">{msg.content}</p>
              <p className="text-xs text-gray-400 mt-1">
                {new Date(msg.created_at).toLocaleTimeString("pt-BR", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create active chat component**

Create `crm/src/components/chat-active.tsx`:

```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import type { Lead } from "@/lib/types";

interface ChatActiveProps {
  lead: Lead;
  onClose: () => void;
  onOpenDetails: () => void;
}

export function ChatActive({ lead, onClose, onOpenDetails }: ChatActiveProps) {
  const { messages, loading } = useRealtimeMessages(lead.id);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || sending) return;

    setSending(true);
    try {
      const res = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leadId: lead.id, text: text.trim() }),
      });
      if (res.ok) setText("");
    } finally {
      setSending(false);
    }
  }

  const handoffIndex = messages.findIndex(
    (m) => m.role === "system" && m.content.includes("encaminhado")
  );

  return (
    <div className="fixed inset-y-0 right-0 w-[480px] bg-white shadow-xl border-l border-gray-200 flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 mr-3">
          &larr;
        </button>
        <div className="flex-1">
          <h2 className="font-medium text-gray-900">
            {lead.name || lead.phone}
          </h2>
          <p className="text-xs text-gray-500">
            {lead.stage} · {lead.seller_stage}
          </p>
        </div>
        <button
          onClick={onOpenDetails}
          className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 rounded px-2 py-1"
        >
          Dados
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading && <p className="text-gray-400 text-sm">Carregando...</p>}
        {messages.map((msg, i) => (
          <div key={msg.id}>
            {i === handoffIndex && (
              <div className="flex items-center my-4">
                <div className="flex-1 border-t border-gray-300" />
                <span className="px-3 text-xs text-gray-400">
                  Vendedor assumiu o chat
                </span>
                <div className="flex-1 border-t border-gray-300" />
              </div>
            )}
            <div
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  msg.role === "user"
                    ? "bg-green-100 text-gray-900"
                    : msg.role === "system"
                    ? "bg-gray-200 text-gray-500 italic text-xs text-center w-full"
                    : msg.sent_by === "seller"
                    ? "bg-blue-100 text-gray-900"
                    : "bg-gray-100 text-gray-900"
                }`}
              >
                {msg.role === "assistant" && (
                  <p className="text-xs text-gray-400 mb-1">
                    {msg.sent_by === "seller" ? "Vendedor" : "Agente"}
                  </p>
                )}
                <p className="whitespace-pre-wrap">{msg.content}</p>
                <p className="text-xs text-gray-400 mt-1">
                  {new Date(msg.created_at).toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="border-t border-gray-200 p-3 flex gap-2"
      >
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Digite uma mensagem..."
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm text-gray-900"
        />
        <button
          type="submit"
          disabled={sending || !text.trim()}
          className="bg-gray-900 text-white px-4 py-2 rounded text-sm hover:bg-gray-800 disabled:opacity-50"
        >
          Enviar
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Create lead detail sidebar**

Create `crm/src/components/lead-detail-sidebar.tsx`:

```tsx
"use client";

import type { Lead } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";

interface LeadDetailSidebarProps {
  lead: Lead;
  onClose: () => void;
}

export function LeadDetailSidebar({ lead, onClose }: LeadDetailSidebarProps) {
  const supabase = createClient();

  async function markAsLost() {
    await supabase
      .from("leads")
      .update({ seller_stage: "perdido" })
      .eq("id", lead.id);
    onClose();
  }

  return (
    <div className="fixed inset-y-0 right-0 w-80 bg-white shadow-xl border-l border-gray-200 z-50 p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-bold text-gray-900">Dados do Lead</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">
          &times;
        </button>
      </div>

      <div className="space-y-4 text-sm">
        <div>
          <label className="text-gray-500">Nome</label>
          <p className="text-gray-900">{lead.name || "—"}</p>
        </div>
        <div>
          <label className="text-gray-500">Telefone</label>
          <p className="text-gray-900">{lead.phone}</p>
        </div>
        <div>
          <label className="text-gray-500">Empresa</label>
          <p className="text-gray-900">{lead.company || "—"}</p>
        </div>
        <div>
          <label className="text-gray-500">Stage (Agente)</label>
          <p className="text-gray-900">{lead.stage}</p>
        </div>
        <div>
          <label className="text-gray-500">Stage (Vendedor)</label>
          <p className="text-gray-900">{lead.seller_stage}</p>
        </div>
        <div>
          <label className="text-gray-500">Canal</label>
          <p className="text-gray-900">{lead.channel}</p>
        </div>
        <div>
          <label className="text-gray-500">Criado em</label>
          <p className="text-gray-900">
            {new Date(lead.created_at).toLocaleDateString("pt-BR")}
          </p>
        </div>
        <div>
          <label className="text-gray-500">Ultima mensagem</label>
          <p className="text-gray-900">
            {lead.last_msg_at
              ? new Date(lead.last_msg_at).toLocaleString("pt-BR")
              : "—"}
          </p>
        </div>
      </div>

      <div className="mt-8">
        <button
          onClick={markAsLost}
          className="w-full border border-red-300 text-red-600 py-2 rounded text-sm hover:bg-red-50"
        >
          Marcar como perdido
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/components/chat-panel.tsx crm/src/components/chat-active.tsx crm/src/components/lead-detail-sidebar.tsx
git commit -m "feat: add ChatPanel (read-only), ChatActive, and LeadDetailSidebar components"
```

---

### Task 10: API Route — Send Chat Message

**Files:**
- Create: `crm/src/app/api/chat/send/route.ts`

- [ ] **Step 1: Create the send message API route**

Create `crm/src/app/api/chat/send/route.ts`:

```typescript
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    }
  );

  // Verify auth
  const anonSupabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    }
  );
  const { data: { user } } = await anonSupabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { leadId, text } = await request.json();

  if (!leadId || !text) {
    return NextResponse.json({ error: "leadId and text required" }, { status: 400 });
  }

  // Fetch lead
  const { data: lead, error: leadError } = await supabase
    .from("leads")
    .select("*")
    .eq("id", leadId)
    .single();

  if (leadError || !lead) {
    return NextResponse.json({ error: "Lead not found" }, { status: 404 });
  }

  // Send via appropriate channel
  try {
    if (lead.channel === "evolution") {
      await sendViaEvolution(lead.phone, text);
    } else {
      await sendViaMeta(lead.phone, text);
    }
  } catch (err) {
    console.error("Failed to send message:", err);
    return NextResponse.json({ error: "Failed to send" }, { status: 500 });
  }

  // Save message to DB
  await supabase.from("messages").insert({
    lead_id: leadId,
    role: "assistant",
    content: text,
    stage: lead.stage,
    sent_by: "seller",
  });

  // Update last_msg_at
  await supabase
    .from("leads")
    .update({ last_msg_at: new Date().toISOString() })
    .eq("id", leadId);

  return NextResponse.json({ ok: true });
}

async function sendViaEvolution(phone: string, text: string) {
  const url = process.env.EVOLUTION_API_URL!;
  const key = process.env.EVOLUTION_API_KEY!;
  const instance = process.env.EVOLUTION_INSTANCE!;

  const res = await fetch(`${url}/message/sendText/${instance}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: key,
    },
    body: JSON.stringify({
      number: phone,
      text: text,
    }),
  });

  if (!res.ok) {
    throw new Error(`Evolution API error: ${res.status}`);
  }
}

async function sendViaMeta(phone: string, text: string) {
  const phoneNumberId = process.env.META_PHONE_NUMBER_ID!;
  const accessToken = process.env.META_ACCESS_TOKEN!;
  const apiVersion = process.env.META_API_VERSION || "v21.0";

  const res = await fetch(
    `https://graph.facebook.com/${apiVersion}/${phoneNumberId}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({
        messaging_product: "whatsapp",
        to: phone,
        type: "text",
        text: { body: text },
      }),
    }
  );

  if (!res.ok) {
    throw new Error(`Meta API error: ${res.status}`);
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/api/chat/send/route.ts
git commit -m "feat: add API route to send messages via Evolution or Meta API"
```

---

### Task 11: Kanban Qualificacao Page

**Files:**
- Modify: `crm/src/app/(authenticated)/qualificacao/page.tsx`

- [ ] **Step 1: Implement qualificacao page**

Replace `crm/src/app/(authenticated)/qualificacao/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { AGENT_STAGES } from "@/lib/constants";
import { KanbanColumn } from "@/components/kanban-column";
import { ChatPanel } from "@/components/chat-panel";
import type { Lead } from "@/lib/types";

export default function QualificacaoPage() {
  const { leads, loading } = useRealtimeLeads();
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);

  if (loading) {
    return <p className="text-gray-400">Carregando...</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-4">Qualificacao</h1>
      <div className="flex gap-4 overflow-x-auto pb-4">
        {AGENT_STAGES.map((stage) => {
          const stageLeads = leads.filter((l) => l.stage === stage.key);
          return (
            <KanbanColumn
              key={stage.key}
              title={stage.label}
              leads={stageLeads}
              colorClass={stage.color}
              onLeadClick={setSelectedLead}
            />
          );
        })}
      </div>

      {selectedLead && (
        <ChatPanel
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/qualificacao/page.tsx
git commit -m "feat: implement Kanban Qualificacao page with read-only chat"
```

---

### Task 12: Kanban Vendas Page (Drag & Drop)

**Files:**
- Modify: `crm/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Implement vendas page with drag & drop**

Replace `crm/src/app/(authenticated)/vendas/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { SELLER_STAGES } from "@/lib/constants";
import { LeadCard } from "@/components/lead-card";
import { ChatActive } from "@/components/chat-active";
import { LeadDetailSidebar } from "@/components/lead-detail-sidebar";
import { createClient } from "@/lib/supabase/client";
import type { Lead } from "@/lib/types";
import { useDroppable } from "@dnd-kit/core";
import { useDraggable } from "@dnd-kit/core";

function DroppableColumn({
  id,
  title,
  colorClass,
  leads,
  onLeadClick,
}: {
  id: string;
  title: string;
  colorClass: string;
  leads: Lead[];
  onLeadClick: (lead: Lead) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });

  return (
    <div className="flex-shrink-0 w-72">
      <div className={`rounded-t-lg px-3 py-2 ${colorClass}`}>
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-sm text-gray-800">{title}</h3>
          <span className="text-xs text-gray-600 bg-white/60 rounded-full px-2 py-0.5">
            {leads.length}
          </span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`bg-gray-100 rounded-b-lg p-2 min-h-[calc(100vh-200px)] space-y-2 overflow-y-auto transition-colors ${
          isOver ? "bg-blue-50" : ""
        }`}
      >
        {leads.map((lead) => (
          <DraggableLeadCard
            key={lead.id}
            lead={lead}
            onClick={onLeadClick}
          />
        ))}
      </div>
    </div>
  );
}

function DraggableLeadCard({
  lead,
  onClick,
}: {
  lead: Lead;
  onClick: (lead: Lead) => void;
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
      <LeadCard lead={lead} onClick={onClick} showAgentStage />
    </div>
  );
}

export default function VendasPage() {
  const { leads, loading } = useRealtimeLeads({ human_control: true });
  const [chatLead, setChatLead] = useState<Lead | null>(null);
  const [detailLead, setDetailLead] = useState<Lead | null>(null);
  const [activeDrag, setActiveDrag] = useState<Lead | null>(null);
  const supabase = createClient();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveDrag(event.active.data.current as Lead);
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;

    const lead = active.data.current as Lead;
    const newStage = over.id as string;

    if (lead.seller_stage === newStage) return;

    await supabase
      .from("leads")
      .update({ seller_stage: newStage })
      .eq("id", lead.id);
  }

  if (loading) {
    return <p className="text-gray-400">Carregando...</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-4">Vendas</h1>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-4 overflow-x-auto pb-4">
          {SELLER_STAGES.map((stage) => {
            const stageLeads = leads.filter(
              (l) => l.seller_stage === stage.key
            );
            return (
              <DroppableColumn
                key={stage.key}
                id={stage.key}
                title={stage.label}
                colorClass={stage.color}
                leads={stageLeads}
                onLeadClick={setChatLead}
              />
            );
          })}
        </div>
        <DragOverlay>
          {activeDrag ? (
            <div className="w-72 opacity-80">
              <LeadCard lead={activeDrag} onClick={() => {}} showAgentStage />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {chatLead && !detailLead && (
        <ChatActive
          lead={chatLead}
          onClose={() => setChatLead(null)}
          onOpenDetails={() => setDetailLead(chatLead)}
        />
      )}

      {detailLead && (
        <LeadDetailSidebar
          lead={detailLead}
          onClose={() => setDetailLead(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/vendas/page.tsx
git commit -m "feat: implement Kanban Vendas page with drag-and-drop and active chat"
```

---

### Task 13: Dashboard Page

**Files:**
- Create: `crm/src/components/kpi-card.tsx`
- Create: `crm/src/components/funnel-chart.tsx`
- Create: `crm/src/components/campaign-table.tsx`
- Modify: `crm/src/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Create KPI card component**

Create `crm/src/components/kpi-card.tsx`:

```tsx
interface KpiCardProps {
  label: string;
  value: string | number;
}

export function KpiCard({ label, value }: KpiCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  );
}
```

- [ ] **Step 2: Create funnel chart component**

Create `crm/src/components/funnel-chart.tsx`:

```tsx
"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface FunnelChartProps {
  data: { name: string; count: number }[];
}

export function FunnelChart({ data }: FunnelChartProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <h3 className="text-sm font-medium text-gray-700 mb-4">
        Funil de Qualificacao
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <XAxis type="number" />
          <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 12 }} />
          <Tooltip />
          <Bar dataKey="count" fill="#374151" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Create campaign table component**

Create `crm/src/components/campaign-table.tsx`:

```tsx
import type { Campaign } from "@/lib/types";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";

interface CampaignTableProps {
  campaigns: Campaign[];
}

export function CampaignMetricsTable({ campaigns }: CampaignTableProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <h3 className="text-sm font-medium text-gray-700 mb-4">
        Metricas de Campanha
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b">
            <th className="pb-2">Nome</th>
            <th className="pb-2">Status</th>
            <th className="pb-2">Progresso</th>
            <th className="pb-2">Resposta</th>
          </tr>
        </thead>
        <tbody>
          {campaigns.map((c) => {
            const responseRate =
              c.sent > 0
                ? `${Math.round((c.replied / c.sent) * 100)}%`
                : "—";
            const progress =
              c.total_leads > 0
                ? Math.round((c.sent / c.total_leads) * 100)
                : 0;
            return (
              <tr key={c.id} className="border-b last:border-0">
                <td className="py-2 text-gray-900">{c.name}</td>
                <td className="py-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      CAMPAIGN_STATUS_COLORS[c.status] || ""
                    }`}
                  >
                    {c.status}
                  </span>
                </td>
                <td className="py-2">
                  <div className="flex items-center gap-2">
                    <div className="w-24 bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-gray-700 rounded-full h-2"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <span className="text-gray-500 text-xs">
                      {c.sent}/{c.total_leads}
                    </span>
                  </div>
                </td>
                <td className="py-2 text-gray-700">{responseRate}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Implement dashboard page**

Replace `crm/src/app/(authenticated)/dashboard/page.tsx`:

```tsx
"use client";

import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { AGENT_STAGES } from "@/lib/constants";
import { KpiCard } from "@/components/kpi-card";
import { FunnelChart } from "@/components/funnel-chart";
import { CampaignMetricsTable } from "@/components/campaign-table";

export default function DashboardPage() {
  const { leads, loading: leadsLoading } = useRealtimeLeads();
  const { campaigns, loading: campaignsLoading } = useRealtimeCampaigns();

  if (leadsLoading || campaignsLoading) {
    return <p className="text-gray-400">Carregando...</p>;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const leadsToday = leads.filter(
    (l) => new Date(l.created_at) >= today
  ).length;

  const awaitingSeller = leads.filter(
    (l) => l.human_control && l.seller_stage === "novo"
  ).length;

  const converted = leads.filter(
    (l) => l.human_control && l.seller_stage === "fechado"
  ).length;
  const totalHandoff = leads.filter((l) => l.human_control).length;
  const conversionRate =
    totalHandoff > 0 ? `${Math.round((converted / totalHandoff) * 100)}%` : "—";

  const funnelData = AGENT_STAGES.map((stage) => ({
    name: stage.label,
    count: leads.filter((l) => l.stage === stage.key).length,
  }));
  funnelData.push({
    name: "Convertidos",
    count: totalHandoff,
  });

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <KpiCard label="Leads hoje" value={leadsToday} />
        <KpiCard label="Aguardando vendedor" value={awaitingSeller} />
        <KpiCard label="Total leads" value={leads.length} />
        <KpiCard label="Taxa de conversao" value={conversionRate} />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-2 gap-4">
        <FunnelChart data={funnelData} />
        <CampaignMetricsTable campaigns={campaigns} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add crm/src/components/kpi-card.tsx crm/src/components/funnel-chart.tsx crm/src/components/campaign-table.tsx crm/src/app/(authenticated)/dashboard/page.tsx
git commit -m "feat: implement Dashboard with KPIs, funnel chart, and campaign metrics"
```

---

### Task 14: Campanhas Page

**Files:**
- Modify: `crm/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Step 1: Implement campanhas page**

Replace `crm/src/app/(authenticated)/campanhas/page.tsx`:

```tsx
"use client";

import { useState, useRef } from "react";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

export default function CampanhasPage() {
  const { campaigns, loading } = useRealtimeCampaigns();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);

    const res = await fetch(`${FASTAPI_URL}/api/campaigns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        template_name: templateName,
        send_interval_min: intervalMin,
        send_interval_max: intervalMax,
      }),
    });

    if (res.ok) {
      const campaign = await res.json();

      // Upload CSV if selected
      const file = fileRef.current?.files?.[0];
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      setShowForm(false);
      setName("");
      setTemplateName("");
    }
    setCreating(false);
  }

  async function handleAction(campaignId: string, action: "start" | "pause") {
    await fetch(`${FASTAPI_URL}/api/campaigns/${campaignId}/${action}`, {
      method: "POST",
    });
  }

  if (loading) {
    return <p className="text-gray-400">Carregando...</p>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Campanhas</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-gray-900 text-white px-4 py-2 rounded text-sm hover:bg-gray-800"
        >
          Nova Campanha
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6 grid grid-cols-2 gap-4"
        >
          <div>
            <label className="block text-sm text-gray-600 mb-1">Nome</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900"
              required
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Template</label>
            <input
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900"
              required
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Intervalo min (s)
            </label>
            <input
              type="number"
              value={intervalMin}
              onChange={(e) => setIntervalMin(Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Intervalo max (s)
            </label>
            <input
              type="number"
              value={intervalMax}
              onChange={(e) => setIntervalMax(Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-sm text-gray-600 mb-1">
              CSV de leads
            </label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="w-full text-sm text-gray-900"
            />
          </div>
          <div className="col-span-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="border border-gray-300 text-gray-700 px-4 py-2 rounded text-sm"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={creating}
              className="bg-gray-900 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
            >
              {creating ? "Criando..." : "Criar"}
            </button>
          </div>
        </form>
      )}

      {/* Campaign list */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="p-3">Nome</th>
              <th className="p-3">Status</th>
              <th className="p-3">Progresso</th>
              <th className="p-3">Respondidos</th>
              <th className="p-3">Taxa</th>
              <th className="p-3">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {campaigns.map((c) => {
              const progress =
                c.total_leads > 0
                  ? Math.round((c.sent / c.total_leads) * 100)
                  : 0;
              const rate =
                c.sent > 0
                  ? `${Math.round((c.replied / c.sent) * 100)}%`
                  : "—";
              return (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="p-3 text-gray-900">{c.name}</td>
                  <td className="p-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        CAMPAIGN_STATUS_COLORS[c.status] || ""
                      }`}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-gray-700 rounded-full h-2"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500">
                        {c.sent}/{c.total_leads}
                      </span>
                    </div>
                  </td>
                  <td className="p-3 text-gray-700">{c.replied}</td>
                  <td className="p-3 text-gray-700">{rate}</td>
                  <td className="p-3">
                    {c.status === "draft" || c.status === "paused" ? (
                      <button
                        onClick={() => handleAction(c.id, "start")}
                        className="text-green-600 hover:text-green-800 text-xs font-medium"
                      >
                        Iniciar
                      </button>
                    ) : c.status === "running" ? (
                      <button
                        onClick={() => handleAction(c.id, "pause")}
                        className="text-yellow-600 hover:text-yellow-800 text-xs font-medium"
                      >
                        Pausar
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add NEXT_PUBLIC_FASTAPI_URL to .env.local and .env.example**

Append to `crm/.env.local`:
```
NEXT_PUBLIC_FASTAPI_URL=http://localhost:8000
```

Append to `crm/.env.example`:
```
NEXT_PUBLIC_FASTAPI_URL=
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/campanhas/page.tsx crm/.env.example
git commit -m "feat: implement Campanhas page with create form and campaign controls"
```

---

### Task 15: Config Page

**Files:**
- Modify: `crm/src/app/(authenticated)/config/page.tsx`

- [ ] **Step 1: Implement config page**

Replace `crm/src/app/(authenticated)/config/page.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

export default function ConfigPage() {
  const supabase = createClient();
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user?.email) setEmail(user.email);
    });
  }, []);

  async function handlePasswordChange(e: React.FormEvent) {
    e.preventDefault();
    if (!newPassword) return;

    const { error } = await supabase.auth.updateUser({
      password: newPassword,
    });

    if (error) {
      setMessage("Erro ao atualizar senha");
    } else {
      setMessage("Senha atualizada");
      setNewPassword("");
    }
  }

  return (
    <div className="max-w-lg">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Configuracoes</h1>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h2 className="font-medium text-gray-900 mb-4">Perfil</h2>

        <div className="mb-4">
          <label className="block text-sm text-gray-500 mb-1">Email</label>
          <p className="text-gray-900">{email}</p>
        </div>

        <form onSubmit={handlePasswordChange}>
          <label className="block text-sm text-gray-500 mb-1">
            Nova senha
          </label>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 mb-3"
            placeholder="Deixe vazio para manter"
          />
          <button
            type="submit"
            className="bg-gray-900 text-white px-4 py-2 rounded text-sm hover:bg-gray-800"
          >
            Atualizar senha
          </button>
          {message && (
            <p className="text-sm text-green-600 mt-2">{message}</p>
          )}
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/config/page.tsx
git commit -m "feat: implement Config page with password update"
```

---

### Task 16: Final Verification

- [ ] **Step 1: Run build to check for TypeScript/import errors**

```bash
cd crm && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 2: Fix any build errors**

Address any TypeScript errors, missing imports, or module resolution issues.

- [ ] **Step 3: Run dev server and verify all pages render**

```bash
cd crm && npm run dev
```

Check each route manually:
- `/login` — login form renders
- `/dashboard` — KPIs and charts render (empty data is fine)
- `/qualificacao` — kanban columns render
- `/vendas` — kanban columns with drag & drop render
- `/campanhas` — campaign table and create form render
- `/config` — settings form renders

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "fix: resolve build issues and finalize CRM"
```
