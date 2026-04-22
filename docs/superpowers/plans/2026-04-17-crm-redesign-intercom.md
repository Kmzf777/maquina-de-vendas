# CRM Intercom Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **OBRIGATÓRIO:** Todo agente que escrever UI DEVE invocar a skill `frontend-design` antes de escrever qualquer JSX, CSS ou classe Tailwind.

**Goal:** Redesign completo do frontend do CRM ValerIA aplicando o design system Intercom definido em `/DESIGN.md`.

**Architecture:** Fase 1 (foundation sequencial): troca de fonte, reescrita do globals.css e sidebar. Fase 2 (paralela): 5 agentes atacam módulos independentes simultaneamente após a Fase 1 estar completa.

**Tech Stack:** Next.js 15, Tailwind CSS v4, Geist font (next/font/google), TypeScript

**Design tokens obrigatórios:**
- Canvas: `#faf9f6` | Text: `#111111` | Accent: `#ff5600` | Border: `#dedbd6` | Muted: `#7b7b78`
- Buttons: `rounded-[4px]`, `hover:scale-110`, `active:scale-[0.85]`
- Cards: `rounded-[8px]`, sem box-shadow
- Nav items: `rounded-[6px]`

---

## FASE 1 — Foundation (sequencial, deve completar antes da Fase 2)

### Task 1: Trocar fonte DM Sans → Geist em layout.tsx

**Files:**
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Reescrever layout.tsx**

```tsx
import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
});

export const metadata: Metadata = {
  title: "CRM Canastra",
  description: "CRM Cafe Canastra",
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body suppressHydrationWarning className={`${geist.variable} ${geist.className}`}>
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Verificar que compila sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: sem erros relacionados a layout.tsx

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/layout.tsx
git commit -m "feat(design): replace DM Sans with Geist font"
```

---

### Task 2: Reescrever globals.css com tokens Intercom

**Files:**
- Modify: `frontend/src/app/globals.css`

- [ ] **Step 1: Reescrever globals.css completo**

```css
@import "tailwindcss";

:root {
  /* Intercom Design System Tokens */
  --color-off-black: #111111;
  --color-fin: #ff5600;
  --color-warm-cream: #faf9f6;
  --color-oat-border: #dedbd6;
  --color-muted: #7b7b78;
  --color-black-80: #313130;
  --color-black-60: #626260;
  --color-white: #ffffff;
  --color-warm-sand: #d3cec6;

  /* Report palette */
  --color-report-blue: #65b5ff;
  --color-report-green: #0bdf50;
  --color-report-red: #c41c1c;
  --color-report-orange: #fe4c02;
  --color-report-pink: #ff2067;
  --color-report-lime: #b3e01c;

  /* Semantic aliases */
  --bg-canvas: var(--color-warm-cream);
  --bg-card: var(--color-warm-cream);
  --bg-surface: var(--color-white);
  --text-primary: var(--color-off-black);
  --text-secondary: var(--color-black-60);
  --text-muted: var(--color-muted);
  --border-default: var(--color-oat-border);
  --accent-green: #0bdf50;
  --accent-red: #c41c1c;
}

@theme inline {
  --color-background: var(--color-warm-cream);
  --color-foreground: var(--color-off-black);
}

body {
  background: var(--color-warm-cream);
  color: var(--color-off-black);
  font-family: var(--font-geist), system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--color-oat-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--color-warm-sand); }

/* Selection */
::selection { background: var(--color-fin); color: var(--color-white); }

/* Card base — Intercom style */
.card {
  background: var(--color-warm-cream);
  border: 1px solid var(--color-oat-border);
  border-radius: 8px;
}

.card-hover {
  transition: border-color 0.15s ease;
}

.card-hover:hover {
  border-color: var(--color-black-60);
}

/* Button base — Intercom style */
.btn-primary {
  background: var(--color-off-black);
  color: var(--color-white);
  border-radius: 4px;
  padding: 0 14px;
  font-size: 16px;
  line-height: 1.5;
  transition: transform 0.15s ease, background 0.15s ease, color 0.15s ease;
  cursor: pointer;
  border: 1px solid transparent;
}

.btn-primary:hover {
  transform: scale(1.1);
  background: var(--color-white);
  color: var(--color-off-black);
  border-color: var(--color-off-black);
}

.btn-primary:active {
  transform: scale(0.85);
  background: #2c6415;
  color: var(--color-white);
  border-color: transparent;
}

.btn-secondary {
  background: transparent;
  color: var(--color-off-black);
  border: 1px solid var(--color-off-black);
  border-radius: 4px;
  padding: 0 14px;
  font-size: 16px;
  line-height: 1.5;
  transition: transform 0.15s ease;
  cursor: pointer;
}

.btn-secondary:hover { transform: scale(1.1); }
.btn-secondary:active { transform: scale(0.85); }

/* Input base */
.input-field {
  background: var(--color-white);
  border: 1px solid var(--color-oat-border);
  border-radius: 6px;
  color: var(--color-off-black);
  font-size: 0.875rem;
  padding: 0.5rem 0.75rem;
  transition: border-color 0.15s ease;
  outline: none;
}

.input-field:focus {
  border-color: var(--color-off-black);
}

.input-field::placeholder {
  color: var(--color-muted);
}

/* Badge */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.125rem 0.625rem;
  border-radius: 4px;
  font-size: 0.75rem;
  line-height: 1.25rem;
  border: 1px solid var(--color-oat-border);
  background: var(--color-warm-cream);
  color: var(--color-black-80);
  letter-spacing: 0.6px;
  text-transform: uppercase;
}
```

- [ ] **Step 2: Verificar build**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/globals.css
git commit -m "feat(design): rewrite globals.css with Intercom design tokens"
```

---

### Task 3: Reescrever Sidebar — dark → warm cream Intercom

**Files:**
- Modify: `frontend/src/components/sidebar.tsx`
- Modify: `frontend/src/components/authenticated-shell.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

Leia `/home/rafael/maquinadevendas/frontend/src/components/sidebar.tsx` e `/DESIGN.md` antes de escrever qualquer linha.

- [ ] **Step 2: Reescrever sidebar.tsx**

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25a2.25 2.25 0 01-2.25-2.25v-2.25z" />
      </svg>
    ),
  },
  {
    href: "/qualificacao",
    label: "Visão Agent AI",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
      </svg>
    ),
  },
  {
    href: "/leads",
    label: "Leads",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    ),
  },
  {
    href: "/vendas",
    label: "Funis de venda",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
      </svg>
    ),
  },
  {
    href: "/conversas",
    label: "WhatsApp",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
      </svg>
    ),
  },
  {
    href: "/campanhas",
    label: "Campanhas",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 110-9h.75c.704 0 1.402-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 1.511l-.657.38c-.551.318-1.26.117-1.527-.461a20.845 20.845 0 01-1.44-4.282m3.102.069a18.03 18.03 0 01-.59-4.59c0-1.586.205-3.124.59-4.59m0 9.18a23.848 23.848 0 018.835 2.535M10.34 6.66a23.847 23.847 0 008.835-2.535m0 0A23.74 23.74 0 0018.795 3m.38 1.125a23.91 23.91 0 011.014 5.395m-1.014 8.855c-.118.38-.245.754-.38 1.125m.38-1.125a23.91 23.91 0 001.014-5.395m0-3.46c.495.413.811 1.035.811 1.73 0 .695-.316 1.317-.811 1.73m0-3.46a24.347 24.347 0 010 3.46" />
      </svg>
    ),
  },
  {
    href: "/estatisticas",
    label: "Tokens AI",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
  {
    href: "/canais",
    label: "Instâncias",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 8.25h3m-3 3h3m-3 3h3" />
      </svg>
    ),
  },
  {
    href: "/config",
    label: "Configurações",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[220px] flex flex-col h-screen border-r border-[#dedbd6] bg-[#faf9f6]">
      {/* Logo */}
      <div className="px-5 py-6 border-b border-[#dedbd6]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-[4px] bg-[#111111] flex items-center justify-center">
            <span className="text-xs font-medium text-white">V</span>
          </div>
          <span className="text-[15px] font-medium text-[#111111] tracking-tight">
            ValerIA<span className="text-[#ff5600] ml-0.5">·</span>
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-[6px] text-[14px] transition-all duration-150 ${
                isActive
                  ? "bg-[#111111] text-white"
                  : "text-[#313130] hover:bg-[#dedbd6]/50 hover:text-[#111111]"
              }`}
            >
              {item.icon}
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User section */}
      <div className="px-3 pb-4 border-t border-[#dedbd6] pt-3">
        <div className="flex items-center gap-2.5 px-3 py-2">
          <div className="w-7 h-7 rounded-[6px] bg-[#dedbd6] flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-[#7b7b78]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
          </div>
          <p className="text-[13px] text-[#7b7b78] truncate">Cafe Canastra</p>
        </div>
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Atualizar authenticated-shell.tsx** (remover `canvas-texture`)

```tsx
"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";

export function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isConversas = pathname === "/conversas";

  return (
    <div className="flex h-screen bg-[#faf9f6]">
      <Sidebar />
      <main
        className={`flex-1 relative ${
          isConversas ? "overflow-hidden" : "p-8 overflow-auto"
        }`}
      >
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sidebar.tsx frontend/src/components/authenticated-shell.tsx
git commit -m "feat(design): redesign sidebar and shell with Intercom warm cream theme"
```

---

## FASE 2 — Pages (paralela, após Fase 1 completa)

> Todos os 5 agentes abaixo devem rodar em paralelo. Cada um DEVE invocar a skill `frontend-design` antes de qualquer edição de UI.

---

### Task 4: Agent Dashboard

**Files:**
- Modify: `frontend/src/components/kpi-card.tsx`
- Modify: `frontend/src/components/funnel-chart.tsx`
- Modify: `frontend/src/components/dashboard/lead-sources-chart.tsx`
- Modify: `frontend/src/components/dashboard/funnel-movement.tsx`
- Modify: `frontend/src/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

```
Use a skill frontend-design antes de qualquer edição.
```

- [ ] **Step 2: Redesign kpi-card.tsx**

Leia o arquivo atual. Aplique:
- `bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]` no container
- Título: `text-[12px] uppercase tracking-[0.6px] text-[#7b7b78]`
- Número: `text-[32px] font-normal leading-none` com `letterSpacing: '-0.96px'`
- Remover box-shadow
- Ícones: cor `#111111` ou `#7b7b78`, sem backgrounds coloridos saturados
- Trend positivo: `text-[#0bdf50]`, negativo: `text-[#c41c1c]`

- [ ] **Step 3: Redesign funnel-chart.tsx**

Leia o arquivo. Aplique:
- Container: `bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]`
- Cores do funil: use report palette — `#65b5ff`, `#0bdf50`, `#ff5600`, `#fe4c02`
- Texto: `#111111` para labels principais, `#7b7b78` para secundários
- Remover shadows

- [ ] **Step 4: Redesign lead-sources-chart.tsx e funnel-movement.tsx**

Leia cada arquivo. Aplique os mesmos padrões: container warm cream, bordas oat, report palette para dados, sem shadows.

- [ ] **Step 5: Redesign dashboard/page.tsx**

Leia o arquivo. Aplique:
- Título de página: `text-[32px] font-normal leading-none text-[#111111]` com `letterSpacing: '-0.96px'`
- Grid de KPIs: `gap-4`
- Fundo da página: herda `#faf9f6` do body
- Remover qualquer `bg-dark`, `accent-olive`, `accent-yellow`

- [ ] **Step 6: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "dashboard|kpi|funnel" | head -20
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/kpi-card.tsx frontend/src/components/funnel-chart.tsx frontend/src/components/dashboard/ frontend/src/app/\(authenticated\)/dashboard/
git commit -m "feat(design): redesign dashboard with Intercom system"
```

---

### Task 5: Agent Leads

**Files:**
- Modify: `frontend/src/components/lead-card.tsx`
- Modify: `frontend/src/components/leads/lead-grid-card.tsx`
- Modify: `frontend/src/components/leads/leads-filter-bar.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`
- Modify: `frontend/src/components/leads/lead-create-modal.tsx`
- Modify: `frontend/src/components/leads/lead-import-modal.tsx`
- Modify: `frontend/src/components/lead-detail-sidebar.tsx`
- Modify: `frontend/src/components/quick-add-lead.tsx`
- Modify: `frontend/src/components/lead-selector.tsx`
- Modify: `frontend/src/app/(authenticated)/leads/page.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Padrões a aplicar em todos os componentes de leads**

Cards: `bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]`

Botões primários:
```tsx
className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
```

Inputs:
```tsx
className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none"
```

Modais — overlay e container:
```tsx
// overlay
className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center"
// container
className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6"
```

Labels de campo:
```tsx
className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1"
```

- [ ] **Step 3: Redesign leads/page.tsx**

Título: `text-[32px] font-normal leading-none text-[#111111]` + `letterSpacing: '-0.96px'`
Botão "Novo Lead": classe btn-primary ou inline dark button
Remover `accent-olive`, `accent-yellow`, variáveis dark

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "lead|Lead" | head -20
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/lead-card.tsx frontend/src/components/leads/ frontend/src/components/lead-detail-sidebar.tsx frontend/src/components/quick-add-lead.tsx frontend/src/components/lead-selector.tsx frontend/src/app/\(authenticated\)/leads/
git commit -m "feat(design): redesign leads module with Intercom system"
```

---

### Task 6: Agent Conversas (WhatsApp)

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`
- Modify: `frontend/src/components/conversas/chat-view.tsx`
- Modify: `frontend/src/components/conversas/contact-detail.tsx`
- Modify: `frontend/src/components/conversas/editable-field.tsx`
- Modify: `frontend/src/components/chat-panel.tsx`
- Modify: `frontend/src/components/chat-active.tsx`
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Padrões específicos para o chat**

Chat list sidebar: `bg-[#faf9f6] border-r border-[#dedbd6]`
Item de conversa ativo: `bg-white border border-[#dedbd6] rounded-[6px]`
Item hover: `bg-[#dedbd6]/30`

Mensagem recebida (bubble):
```tsx
className="bg-white border border-[#dedbd6] rounded-[8px] px-3 py-2 text-[14px] text-[#111111] max-w-[75%]"
```

Mensagem enviada (bubble):
```tsx
className="bg-[#111111] rounded-[8px] px-3 py-2 text-[14px] text-white max-w-[75%] ml-auto"
```

Input de mensagem:
```tsx
className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none"
```

Botão enviar:
```tsx
className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
```

Contact detail panel: `bg-[#faf9f6] border-l border-[#dedbd6]`

- [ ] **Step 3: Remover qualquer dark background do layout de conversas**

O layout `flex h-screen` já herda `bg-[#faf9f6]` do authenticated-shell.

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "conversa|chat|Chat" | head -20
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/ frontend/src/components/chat-panel.tsx frontend/src/components/chat-active.tsx frontend/src/app/\(authenticated\)/conversas/
git commit -m "feat(design): redesign conversas/WhatsApp with Intercom system"
```

---

### Task 7: Agent Funis de Venda (Kanban)

**Files:**
- Modify: `frontend/src/components/kanban-column.tsx`
- Modify: `frontend/src/components/kanban-filters.tsx`
- Modify: `frontend/src/components/kanban-metrics-bar.tsx`
- Modify: `frontend/src/components/deals/deal-card.tsx`
- Modify: `frontend/src/components/deals/deal-kanban-filters.tsx`
- Modify: `frontend/src/components/deals/deal-create-modal.tsx`
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`
- Modify: `frontend/src/components/deals/deal-kanban-metrics.tsx`
- Modify: `frontend/src/components/deals/lost-reason-modal.tsx`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Padrões para colunas do Kanban**

Coluna:
```tsx
className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] w-72 flex flex-col"
```

Header da coluna:
```tsx
className="px-4 py-3 border-b border-[#dedbd6]"
// título: text-[13px] uppercase tracking-[0.6px] text-[#7b7b78]
// count badge: bg-[#111111] text-white text-[11px] px-2 py-0.5 rounded-[4px]
```

Deal card:
```tsx
className="bg-white border border-[#dedbd6] rounded-[8px] p-3 mx-2 mb-2 cursor-pointer hover:border-[#111111] transition-colors"
```

- [ ] **Step 3: Metrics bar**

`bg-[#faf9f6] border-b border-[#dedbd6] px-6 py-3`
Valores: `text-[20px] font-normal text-[#111111]` + `letterSpacing: '-0.2px'`
Labels: `text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]`

- [ ] **Step 4: Filtros**

Botões de filtro ativos: `bg-[#111111] text-white rounded-[4px] px-3 py-1.5 text-[13px]`
Inativos: `border border-[#dedbd6] text-[#313130] rounded-[4px] px-3 py-1.5 text-[13px] hover:border-[#111111]`

- [ ] **Step 5: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "kanban|deal|Deal|venda" | head -20
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/kanban-column.tsx frontend/src/components/kanban-filters.tsx frontend/src/components/kanban-metrics-bar.tsx frontend/src/components/deals/ frontend/src/app/\(authenticated\)/vendas/
git commit -m "feat(design): redesign vendas kanban with Intercom system"
```

---

### Task 8: Agent Campanhas + Config + Canais + Estatísticas + Login

**Files:**
- Modify: `frontend/src/components/campaigns/` (todos os arquivos)
- Modify: `frontend/src/components/config/` (todos os arquivos)
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`
- Modify: `frontend/src/app/(authenticated)/campanhas/[id]/page.tsx`
- Modify: `frontend/src/app/(authenticated)/estatisticas/page.tsx`
- Modify: `frontend/src/app/(authenticated)/canais/page.tsx`
- Modify: `frontend/src/app/(authenticated)/qualificacao/page.tsx`
- Modify: `frontend/src/app/(authenticated)/config/page.tsx`
- Modify: `frontend/src/app/login/page.tsx`
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Padrões para páginas de configuração e listas**

Tabs de navegação:
```tsx
// tab ativa
className="border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px]"
// tab inativa
className="border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] hover:text-[#111111]"
```

Tabelas:
```tsx
// thead
className="border-b border-[#dedbd6] bg-[#faf9f6]"
// th
className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left"
// tr
className="border-b border-[#dedbd6] hover:bg-[#faf9f6]"
// td
className="px-4 py-3 text-[14px] text-[#111111]"
```

Cards de campanha:
```tsx
className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 hover:border-[#111111] transition-colors"
```

- [ ] **Step 3: Redesign login/page.tsx**

```tsx
// Container da página
className="min-h-screen bg-[#faf9f6] flex items-center justify-center"
// Card do form
className="bg-white border border-[#dedbd6] rounded-[8px] p-8 w-full max-w-sm"
// Título
// <h1 style={{ letterSpacing: '-0.96px', lineHeight: '1.00' }} className="text-[32px] font-normal text-[#111111] mb-2">
//   ValerIA<span className="text-[#ff5600]">·</span>
// </h1>
// Botão submit: btn-primary ou inline dark button
```

- [ ] **Step 4: TypeScript check completo**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Corrija todos os erros encontrados.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/ frontend/src/components/config/ frontend/src/app/\(authenticated\)/campanhas/ frontend/src/app/\(authenticated\)/estatisticas/ frontend/src/app/\(authenticated\)/canais/ frontend/src/app/\(authenticated\)/qualificacao/ frontend/src/app/\(authenticated\)/config/ frontend/src/app/login/ frontend/src/app/page.tsx
git commit -m "feat(design): redesign campanhas, config, canais, estatisticas, qualificacao e login"
```

---

## Verificação Final (após todas as tasks)

- [ ] `npx tsc --noEmit` sem erros
- [ ] Nenhuma referência a `--bg-dark`, `--accent-olive`, `--accent-yellow` nos componentes
- [ ] Sidebar tem background `#faf9f6`
- [ ] Todos os botões têm `rounded-[4px]`
- [ ] Nenhum `box-shadow` nos cards
- [ ] Font Geist carregando (verificar no DevTools)
