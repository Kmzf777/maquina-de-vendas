# SLA por Vendedor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Medir o SLA de atendimento por usuário vendedor (canal 1:1), com janela de horário individual configurável, anulação de dias (folgas/viagens/feriados) e definição correta de "lead em atraso", substituindo o cálculo hardcoded do João.

**Architecture:** Mantém o motor de horário comercial client-side (`business-hours.ts`), parametrizando-o para janela por vendedor + dias anulados. Um passe cronológico único ("rodada de espera") gera média, atraso e pior SLA de forma coerente. Config e anulações vivem em 3 tabelas Supabase, lidas direto pelo dashboard e escritas por rotas admin (service role). UI nova em `/config` (aba SLA) e dashboard em tabela por vendedor.

**Tech Stack:** Next.js (App Router) + TypeScript, Supabase (Postgres + Auth + Realtime), Vitest (novo, para os testes do motor puro), Tailwind.

**Spec:** `docs/superpowers/specs/2026-06-11-sla-por-vendedor-design.md`

---

## File Structure

**Criar:**
- `frontend/vitest.config.ts` — config do test runner (alias `@`)
- `frontend/src/lib/sla-rounds.ts` — algoritmo puro da rodada de espera (`collectRounds`, `summarizeRounds`)
- `frontend/src/lib/sla-rounds.test.ts` — testes do algoritmo
- `frontend/src/lib/business-hours.test.ts` — testes do motor parametrizado
- `frontend/src/hooks/use-sla-stats.ts` — hook que busca dados e monta linhas por vendedor + total
- `frontend/src/components/dashboard/sla-table.tsx` — tabela do dashboard
- `frontend/src/components/config/sla-tab.tsx` — aba de configuração (admin)
- `frontend/src/app/api/admin/sla/config/route.ts` — GET/POST configs de vendedor
- `frontend/src/app/api/admin/sla/vendedores/route.ts` — GET usuários role=vendedor
- `frontend/src/app/api/admin/sla/target/route.ts` — GET/PUT alvo global
- `frontend/src/app/api/admin/sla/overrides/route.ts` — GET/POST anulações
- `frontend/src/app/api/admin/sla/overrides/[id]/route.ts` — DELETE anulação
- `frontend/src/lib/admin-auth.ts` — helper de checagem de admin nas rotas
- `migrations/20260611_sla_per_seller.sql` — tabelas + RLS + seed + drop RPC

**Modificar:**
- `frontend/package.json` — devDeps vitest + script `test`
- `frontend/src/lib/business-hours.ts` — parametrizar janela + dias anulados
- `frontend/src/app/(authenticated)/dashboard/page.tsx` — trocar `SlaHeroSection` por `SlaTable`
- `frontend/src/app/(authenticated)/config/page.tsx` — adicionar aba SLA

**Remover (Task 9):**
- `frontend/src/hooks/use-joao-sla-stats.ts`
- `frontend/src/components/dashboard/sla-hero-section.tsx`

---

## Task 1: Setup do Vitest no frontend

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/lib/__smoke__.test.ts` (temporário, removido no fim da task)

- [ ] **Step 1: Instalar vitest**

Run (no diretório `frontend`):
```bash
npm install -D vitest@^2.1.0
```
Expected: adiciona `vitest` em devDependencies sem erros.

- [ ] **Step 2: Criar `frontend/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

- [ ] **Step 3: Adicionar script `test` em `frontend/package.json`**

No bloco `"scripts"`, adicionar a linha `test`:
```json
    "lint": "eslint",
    "type-check": "tsc --noEmit",
    "test": "vitest run"
```

- [ ] **Step 4: Criar smoke test temporário `frontend/src/lib/__smoke__.test.ts`**

```ts
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 5: Rodar e verificar verde**

Run (em `frontend`): `npm test`
Expected: 1 passed.

- [ ] **Step 6: Remover o smoke test**

Run (em `frontend`): `git rm src/lib/__smoke__.test.ts` (ou apagar o arquivo).

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts
git commit -m "chore(frontend): adiciona vitest para testes do motor de SLA"
```

---

## Task 2: Migration — tabelas, RLS, seed, drop da RPC

**Files:**
- Create: `migrations/20260611_sla_per_seller.sql`

> Esta migration é aplicada manualmente no Supabase pelo usuário (padrão do projeto). O arquivo é a fonte de verdade versionada.

- [ ] **Step 1: Criar `migrations/20260611_sla_per_seller.sql`**

```sql
-- ============================================================
-- SLA por vendedor: config individual, alvo global, anulações
-- ============================================================

-- 1. Config por vendedor (canal 1:1)
CREATE TABLE IF NOT EXISTS sla_seller_config (
  user_id              uuid PRIMARY KEY,
  channel_id           uuid NOT NULL UNIQUE,
  display_name         text NOT NULL DEFAULT '',
  window_start_minute  int  NOT NULL DEFAULT 600,   -- 10h00
  window_end_minute    int  NOT NULL DEFAULT 960,   -- 16h00
  active_weekdays      int[] NOT NULL DEFAULT '{1,2,3,4,5}', -- 0=dom..6=sáb
  active               boolean NOT NULL DEFAULT true,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

-- 2. Configuração global (singleton)
CREATE TABLE IF NOT EXISTS sla_settings (
  id             int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  target_minutes int NOT NULL DEFAULT 20,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- 3. Anulações (dias inteiros; user_id NULL = global)
CREATE TABLE IF NOT EXISTS sla_overrides (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid,                       -- NULL = todos os vendedores
  start_date date NOT NULL,
  end_date   date NOT NULL,
  reason     text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_sla_overrides_user ON sla_overrides(user_id);
CREATE INDEX IF NOT EXISTS idx_sla_overrides_dates ON sla_overrides(start_date, end_date);

-- 4. RLS: leitura para autenticados; escrita só via service role (rotas admin)
ALTER TABLE sla_seller_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_settings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_overrides     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sla_seller_config_read ON sla_seller_config;
CREATE POLICY sla_seller_config_read ON sla_seller_config
  FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS sla_settings_read ON sla_settings;
CREATE POLICY sla_settings_read ON sla_settings
  FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS sla_overrides_read ON sla_overrides;
CREATE POLICY sla_overrides_read ON sla_overrides
  FOR SELECT TO authenticated USING (true);

-- 5. Seed: alvo global + config do João (não regredir o dashboard atual)
INSERT INTO sla_settings (id, target_minutes)
  VALUES (1, 20)
  ON CONFLICT (id) DO NOTHING;

-- João: canal a3a607b1-..., janela 10-16h seg-sex.
-- user_id derivado do canal (assume coluna channels.owner_user_id; ajustar se o
-- vínculo real for outro). Se não houver user vinculado ainda, o admin completa
-- pela aba SLA — o seed abaixo é best-effort e não falha se já existir.
INSERT INTO sla_seller_config (user_id, channel_id, display_name)
  SELECT gen_random_uuid(), 'a3a607b1-6bff-4370-8609-b275eef270dd', 'João'
  WHERE NOT EXISTS (
    SELECT 1 FROM sla_seller_config
    WHERE channel_id = 'a3a607b1-6bff-4370-8609-b275eef270dd'
  );

-- 6. Remover RPC obsoleta (substituída pelo passe único client-side)
DROP FUNCTION IF EXISTS get_seller_overdue_candidates(uuid);
```

> NOTA para o executor: o seed do João usa `gen_random_uuid()` como placeholder de
> `user_id` porque o vínculo real usuário↔canal será definido pelo admin na aba SLA.
> Se o projeto já tiver uma coluna que liga canal a usuário, troque o `SELECT` para
> usá-la. Confirme com o usuário antes de aplicar no Supabase.

- [ ] **Step 2: Commit**

```bash
git add migrations/20260611_sla_per_seller.sql
git commit -m "feat(sla): migration de tabelas, RLS, seed e drop da RPC antiga"
```

> A aplicação no Supabase é feita pelo usuário (PARAR e avisar, conforme CLAUDE.md).

---

## Task 3: Parametrizar `business-hours.ts` (TDD)

**Files:**
- Modify: `frontend/src/lib/business-hours.ts`
- Test: `frontend/src/lib/business-hours.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

Create `frontend/src/lib/business-hours.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import {
  businessMinutesBetween,
  spDateString,
  type BusinessWindow,
} from "@/lib/business-hours";

// Helper: janela custom
function win(p: Partial<BusinessWindow> = {}): BusinessWindow {
  return {
    startMin: 600,
    endMin: 960,
    weekdays: new Set([1, 2, 3, 4, 5]),
    excludedDates: new Set<string>(),
    ...p,
  };
}

describe("spDateString", () => {
  it("retorna a data SP em YYYY-MM-DD", () => {
    // 2026-06-11 12:00 UTC = 09:00 SP (mesmo dia)
    expect(spDateString(new Date("2026-06-11T12:00:00Z"))).toBe("2026-06-11");
    // 2026-06-12 02:00 UTC = 2026-06-11 23:00 SP (dia anterior em SP)
    expect(spDateString(new Date("2026-06-12T02:00:00Z"))).toBe("2026-06-11");
  });
});

describe("businessMinutesBetween com janela default", () => {
  it("caso canônico sex 15h55 -> seg 10h10 = 15 min", () => {
    // sexta 2026-06-12 15:55 SP = 18:55 UTC
    const from = new Date("2026-06-12T18:55:00Z");
    // segunda 2026-06-15 10:10 SP = 13:10 UTC
    const to = new Date("2026-06-15T13:10:00Z");
    expect(businessMinutesBetween(from, to, win())).toBe(15);
  });

  it("intervalo dentro do mesmo dia útil", () => {
    // quarta 2026-06-10 10:00 SP -> 11:00 SP = 60 min
    const from = new Date("2026-06-10T13:00:00Z");
    const to = new Date("2026-06-10T14:00:00Z");
    expect(businessMinutesBetween(from, to, win())).toBe(60);
  });
});

describe("businessMinutesBetween com janela custom", () => {
  it("respeita startMin/endMin diferentes (8h-18h)", () => {
    // quarta 2026-06-10 08:30 SP -> 09:30 SP = 60 min com janela 8h-18h
    const from = new Date("2026-06-10T11:30:00Z"); // 08:30 SP
    const to = new Date("2026-06-10T12:30:00Z");   // 09:30 SP
    expect(
      businessMinutesBetween(from, to, win({ startMin: 480, endMin: 1080 }))
    ).toBe(60);
  });

  it("respeita weekdays custom (inclui sábado)", () => {
    // sábado 2026-06-13 10:00 SP -> 11:00 SP
    const from = new Date("2026-06-13T13:00:00Z");
    const to = new Date("2026-06-13T14:00:00Z");
    // default (sem sábado) = 0
    expect(businessMinutesBetween(from, to, win())).toBe(0);
    // com sábado (6) = 60
    expect(
      businessMinutesBetween(from, to, win({ weekdays: new Set([1, 2, 3, 4, 5, 6]) }))
    ).toBe(60);
  });
});

describe("businessMinutesBetween com dias anulados", () => {
  it("zera um dia inteiro presente em excludedDates", () => {
    // quarta 2026-06-10 inteira anulada
    const from = new Date("2026-06-10T13:00:00Z"); // 10:00 SP qua
    const to = new Date("2026-06-10T16:00:00Z");   // 13:00 SP qua
    expect(
      businessMinutesBetween(from, to, win({ excludedDates: new Set(["2026-06-10"]) }))
    ).toBe(0);
  });

  it("par que atravessa um dia anulado conta só os dias válidos", () => {
    // ter 2026-06-09 15:00 SP -> qui 2026-06-11 11:00 SP, qua 10 anulada.
    // ter: 15:00->16:00 = 60; qua: 0 (anulada); qui: 10:00->11:00 = 60. Total 120.
    const from = new Date("2026-06-09T18:00:00Z"); // 15:00 SP ter
    const to = new Date("2026-06-11T14:00:00Z");   // 11:00 SP qui
    expect(
      businessMinutesBetween(from, to, win({ excludedDates: new Set(["2026-06-10"]) }))
    ).toBe(120);
  });
});
```

- [ ] **Step 2: Rodar e verificar que falha**

Run (em `frontend`): `npm test src/lib/business-hours.test.ts`
Expected: FAIL — `spDateString`/`BusinessWindow` não existem e a assinatura nova não bate.

- [ ] **Step 3: Refatorar `business-hours.ts` para aceitar a janela**

Substituir o topo do arquivo (após o comentário de cabeçalho, mantendo `TZ`, `BIZ_START_MIN`, `BIZ_END_MIN`, `SP_OFFSET_MS`, `TZParts`, `WEEKDAY_MAP`, `tzParts`, `isWeekday`, `midnightSPtoUTC`, `localMinutesOfDay`) adicionando a interface e o default logo após `BIZ_END_MIN`:

```ts
export interface BusinessWindow {
  startMin: number;           // minutos desde meia-noite (default 600 = 10h)
  endMin: number;             // default 960 = 16h
  weekdays: Set<number>;      // 0=dom..6=sáb (default seg-sex)
  excludedDates: Set<string>; // 'YYYY-MM-DD' em SP -> 0 min
}

export const DEFAULT_WINDOW: BusinessWindow = {
  startMin: BIZ_START_MIN,
  endMin: BIZ_END_MIN,
  weekdays: new Set([1, 2, 3, 4, 5]),
  excludedDates: new Set<string>(),
};

/** Data SP em 'YYYY-MM-DD' (para casar com excludedDates). */
export function spDateString(date: Date): string {
  const p = tzParts(date);
  const mm = String(p.month).padStart(2, "0");
  const dd = String(p.day).padStart(2, "0");
  return `${p.year}-${mm}-${dd}`;
}
```

Substituir `bizMinutesInSegment` para receber a janela e a data do dia:
```ts
function bizMinutesInSegment(
  intervalStart: Date,
  intervalEnd: Date,
  weekday: number,
  dayMidnightUTC: Date,
  win: BusinessWindow,
  dateStr: string
): number {
  if (!win.weekdays.has(weekday)) return 0;
  if (win.excludedDates.has(dateStr)) return 0;

  const bizStart = new Date(dayMidnightUTC.getTime() + win.startMin * 60_000);
  const bizEnd   = new Date(dayMidnightUTC.getTime() + win.endMin   * 60_000);

  const effectiveStart = intervalStart > bizStart ? intervalStart : bizStart;
  const effectiveEnd   = intervalEnd   < bizEnd   ? intervalEnd   : bizEnd;

  return Math.max(0, (effectiveEnd.getTime() - effectiveStart.getTime()) / 60_000);
}
```

Substituir `businessMinutesBetween` para propagar a janela e calcular `dateStr` no loop:
```ts
export function businessMinutesBetween(
  from: Date,
  to: Date,
  win: BusinessWindow = DEFAULT_WINDOW
): number {
  if (from >= to) return 0;

  let total = 0;

  const startParts = tzParts(from);
  let year  = startParts.year;
  let month = startParts.month;
  let day   = startParts.day;

  let segStart = from;

  while (segStart < to) {
    const dayMidnight  = midnightSPtoUTC(year, month, day);
    const nextMidnight = new Date(dayMidnight.getTime() + 24 * 60 * 60 * 1000);

    const segEnd = to < nextMidnight ? to : nextMidnight;

    const parts = tzParts(segStart);
    const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    total += bizMinutesInSegment(segStart, segEnd, parts.weekday, dayMidnight, win, dateStr);

    segStart = nextMidnight;
    if (segStart >= to) break;

    const nextParts = tzParts(segStart);
    year  = nextParts.year;
    month = nextParts.month;
    day   = nextParts.day;
  }

  return total;
}
```

Substituir `businessMinutesElapsed`:
```ts
export function businessMinutesElapsed(
  from: Date,
  win: BusinessWindow = DEFAULT_WINDOW
): number {
  return businessMinutesBetween(from, new Date(), win);
}
```

> `isInBusinessHours` e `formatBusinessDuration` permanecem inalterados.

- [ ] **Step 4: Rodar e verificar verde**

Run (em `frontend`): `npm test src/lib/business-hours.test.ts`
Expected: todos PASS.

- [ ] **Step 5: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros novos. (O hook antigo `use-joao-sla-stats.ts` ainda chama `businessMinutesBetween(a,b)` sem janela — continua válido pelo default. OK.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/business-hours.ts frontend/src/lib/business-hours.test.ts
git commit -m "feat(sla): parametriza business-hours com janela e dias anulados"
```

---

## Task 4: Algoritmo da rodada de espera — `sla-rounds.ts` (TDD)

**Files:**
- Create: `frontend/src/lib/sla-rounds.ts`
- Test: `frontend/src/lib/sla-rounds.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

Create `frontend/src/lib/sla-rounds.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { collectRounds, summarizeRounds, type SlaConversation } from "@/lib/sla-rounds";
import { DEFAULT_WINDOW } from "@/lib/business-hours";

// Datas em horário comercial SP. 13:00 UTC = 10:00 SP (qua 2026-06-10).
const U = (sp: string) => new Date(`2026-06-10T${sp}Z`).toISOString();

function conv(messages: { sent_by: string; t: string }[], last_seller_response_at: string | null = null): SlaConversation {
  return {
    id: Math.random().toString(36).slice(2),
    last_seller_response_at,
    messages: messages.map((m) => ({ sent_by: m.sent_by, created_at: U(m.t) })),
  };
}

describe("collectRounds — rodada de espera", () => {
  it("rajada do cliente ancora na PRIMEIRA mensagem sem resposta", () => {
    // 10:00 user, 10:10 user, 10:30 seller -> espera = 30 min (de 10:00)
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "user", t: "13:10:00" },
      { sent_by: "seller", t: "13:30:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([30]);
    expect(r.openElapsed).toEqual([]);
  });

  it("só a PRIMEIRA resposta do vendedor fecha a rodada", () => {
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "seller", t: "13:05:00" },
      { sent_by: "seller", t: "13:06:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([5]);
  });

  it("mensagem proativa do vendedor (sem espera aberta) é ignorada", () => {
    const c = conv([
      { sent_by: "seller", t: "13:00:00" },
      { sent_by: "user", t: "13:10:00" },
      { sent_by: "seller", t: "13:20:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([10]);
  });

  it("rodada aberta vira openElapsed (sem fechar)", () => {
    // cliente às 10:00 SP, sem resposta; now fixo às 10:25 SP
    const c = conv([{ sent_by: "user", t: "13:00:00" }]);
    const now = new Date("2026-06-10T13:25:00Z");
    const r = collectRounds([c], DEFAULT_WINDOW, now);
    expect(r.closed).toEqual([]);
    expect(r.openElapsed).toEqual([25]);
  });

  it("fallback Finalizar fecha a rodada via last_seller_response_at", () => {
    // cliente 10:00, sem msg de seller, mas Finalizar às 10:15
    const c = conv([{ sent_by: "user", t: "13:00:00" }], U("13:15:00"));
    const r = collectRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(r.closed).toEqual([15]);
    expect(r.openElapsed).toEqual([]);
  });
});

describe("summarizeRounds", () => {
  it("média, pior (inclui abertas) e atraso por alvo", () => {
    const rounds = { closed: [10, 20], openElapsed: [40] };
    const s = summarizeRounds(rounds, 30);
    expect(s.avgMinutes).toBe(15);        // média só das fechadas
    expect(s.worstMinutes).toBe(40);      // pior inclui aberta
    expect(s.overdueCount).toBe(1);       // 40 > 30
  });

  it("sem rodadas -> nulos e zero", () => {
    const s = summarizeRounds({ closed: [], openElapsed: [] }, 20);
    expect(s.avgMinutes).toBeNull();
    expect(s.worstMinutes).toBeNull();
    expect(s.overdueCount).toBe(0);
  });
});
```

- [ ] **Step 2: Rodar e verificar que falha**

Run (em `frontend`): `npm test src/lib/sla-rounds.test.ts`
Expected: FAIL — módulo não existe.

- [ ] **Step 3: Implementar `frontend/src/lib/sla-rounds.ts`**

```ts
import {
  businessMinutesBetween,
  businessMinutesElapsed,
  type BusinessWindow,
} from "@/lib/business-hours";

export interface SlaMessage {
  sent_by: string;       // só 'user' e 'seller' importam
  created_at: string;    // ISO
}

export interface SlaConversation {
  id: string;
  last_seller_response_at: string | null;
  messages: SlaMessage[]; // ordem cronológica, apenas 'user'/'seller'
}

export interface SellerRounds {
  closed: number[];       // minutos comerciais de rodadas respondidas
  openElapsed: number[];  // minutos comerciais decorridos de rodadas abertas
}

export interface SellerSlaResult {
  avgMinutes: number | null;
  overdueCount: number;
  worstMinutes: number | null;
}

/**
 * Percorre as conversas e extrai as rodadas de espera.
 * Rodada = primeira msg do cliente sem resposta -> primeira resposta do vendedor
 * (msg do vendedor ou Finalizar). Rajadas do cliente não reiniciam o relógio.
 */
export function collectRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): SellerRounds {
  const closed: number[] = [];
  const openElapsed: number[] = [];

  for (const conv of conversations) {
    let waitStart: string | null = null;

    for (const msg of conv.messages) {
      if (msg.sent_by === "user") {
        if (waitStart === null) waitStart = msg.created_at;
      } else if (msg.sent_by === "seller") {
        if (waitStart !== null) {
          const mins = businessMinutesBetween(new Date(waitStart), new Date(msg.created_at), win);
          if (mins >= 0) closed.push(mins);
          waitStart = null;
        }
      }
    }

    if (waitStart !== null) {
      const finalize = conv.last_seller_response_at;
      if (finalize && finalize > waitStart) {
        const mins = businessMinutesBetween(new Date(waitStart), new Date(finalize), win);
        if (mins >= 0) closed.push(mins);
      } else {
        const elapsed = businessMinutesBetween(new Date(waitStart), now, win);
        openElapsed.push(elapsed);
      }
    }
  }

  return { closed, openElapsed };
}

/** Resume rodadas em média (fechadas), pior (fechadas+abertas) e atraso (>alvo). */
export function summarizeRounds(
  rounds: SellerRounds,
  targetMinutes: number
): SellerSlaResult {
  const { closed, openElapsed } = rounds;

  const avgMinutes =
    closed.length > 0 ? closed.reduce((a, b) => a + b, 0) / closed.length : null;

  const all = [...closed, ...openElapsed];
  const worstMinutes = all.length > 0 ? Math.max(...all) : null;

  const overdueCount = openElapsed.filter((m) => m > targetMinutes).length;

  return { avgMinutes, overdueCount, worstMinutes };
}
```

> NOTA: `businessMinutesElapsed` é exportado para uso externo, mas aqui usamos
> `businessMinutesBetween(start, now, win)` diretamente para permitir `now` injetável
> nos testes. O import de `businessMinutesElapsed` não é necessário — remova-o se o
> linter reclamar de import não usado. (Mantido fora do código acima.)

- [ ] **Step 4: Rodar e verificar verde**

Run (em `frontend`): `npm test src/lib/sla-rounds.test.ts`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/sla-rounds.ts frontend/src/lib/sla-rounds.test.ts
git commit -m "feat(sla): algoritmo da rodada de espera (media, atraso, pior)"
```

---

## Task 5: Hook `use-sla-stats.ts`

**Files:**
- Create: `frontend/src/hooks/use-sla-stats.ts`

> Sem teste unitário (depende de I/O Supabase + tempo). A lógica pura já está coberta
> nas Tasks 3-4. Validação manual no dashboard (Task 8).

- [ ] **Step 1: Implementar o hook**

Create `frontend/src/hooks/use-sla-stats.ts`:
```ts
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { spDateString, type BusinessWindow } from "@/lib/business-hours";
import {
  collectRounds,
  summarizeRounds,
  type SlaConversation,
  type SellerRounds,
  type SellerSlaResult,
} from "@/lib/sla-rounds";

export type DateFilter = "1d" | "7d" | "30d" | "all";

interface SellerConfigRow {
  user_id: string;
  channel_id: string;
  display_name: string;
  window_start_minute: number;
  window_end_minute: number;
  active_weekdays: number[];
  active: boolean;
}

interface OverrideRow {
  user_id: string | null;
  start_date: string; // 'YYYY-MM-DD'
  end_date: string;
}

interface ConvRow {
  id: string;
  channel_id: string;
  last_seller_response_at: string | null;
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

export interface SlaRow extends SellerSlaResult {
  userId: string;
  displayName: string;
}

export interface SlaTableData {
  rows: SlaRow[];
  total: SellerSlaResult;
  loading: boolean;
}

function getCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const days = filter === "1d" ? 1 : filter === "7d" ? 7 : 30;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}

/** Expande overrides (do vendedor + globais) em datas 'YYYY-MM-DD'. */
function buildExcludedDates(overrides: OverrideRow[], userId: string): Set<string> {
  const out = new Set<string>();
  for (const o of overrides) {
    if (o.user_id !== null && o.user_id !== userId) continue;
    const start = new Date(`${o.start_date}T12:00:00Z`);
    const end = new Date(`${o.end_date}T12:00:00Z`);
    for (let d = start; d <= end; d = new Date(d.getTime() + 86_400_000)) {
      out.add(spDateString(d));
    }
  }
  return out;
}

function windowFor(cfg: SellerConfigRow, overrides: OverrideRow[]): BusinessWindow {
  return {
    startMin: cfg.window_start_minute,
    endMin: cfg.window_end_minute,
    weekdays: new Set(cfg.active_weekdays),
    excludedDates: buildExcludedDates(overrides, cfg.user_id),
  };
}

async function fetchConversations(
  supabase: ReturnType<typeof createClient>,
  channelIds: string[],
  cutoff: Date | null
): Promise<ConvRow[]> {
  if (channelIds.length === 0) return [];
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;
  while (true) {
    let q = supabase
      .from("conversations")
      .select("id, channel_id, last_seller_response_at")
      .in("channel_id", channelIds)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);
    if (cutoff) q = q.gte("created_at", cutoff.toISOString());
    const { data, error } = await q;
    if (error || !data || data.length === 0) break;
    all.push(...(data as ConvRow[]));
    if (data.length < PAGE) break;
    offset += PAGE;
  }
  return all;
}

async function fetchMessages(
  supabase: ReturnType<typeof createClient>,
  convIds: string[]
): Promise<MsgRow[]> {
  if (convIds.length === 0) return [];
  const PAGE = 1000;
  const all: MsgRow[] = [];
  // chunk de ids para não estourar limites de URL
  const CHUNK = 200;
  for (let i = 0; i < convIds.length; i += CHUNK) {
    const slice = convIds.slice(i, i + CHUNK);
    let offset = 0;
    while (true) {
      const { data, error } = await supabase
        .from("messages")
        .select("conversation_id, sent_by, created_at")
        .in("conversation_id", slice)
        .in("sent_by", ["user", "seller"])
        .order("created_at", { ascending: true })
        .range(offset, offset + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as MsgRow[]));
      if (data.length < PAGE) break;
      offset += PAGE;
    }
  }
  return all;
}

function groupConversations(convs: ConvRow[], msgs: MsgRow[]): Map<string, SlaConversation[]> {
  const byConv = new Map<string, MsgRow[]>();
  for (const m of msgs) {
    if (!byConv.has(m.conversation_id)) byConv.set(m.conversation_id, []);
    byConv.get(m.conversation_id)!.push(m);
  }
  const byChannel = new Map<string, SlaConversation[]>();
  for (const c of convs) {
    const slaConv: SlaConversation = {
      id: c.id,
      last_seller_response_at: c.last_seller_response_at,
      messages: byConv.get(c.id) ?? [],
    };
    if (!byChannel.has(c.channel_id)) byChannel.set(c.channel_id, []);
    byChannel.get(c.channel_id)!.push(slaConv);
  }
  return byChannel;
}

export function useSlaStats(filter: DateFilter = "7d"): SlaTableData {
  const [rows, setRows] = useState<SlaRow[]>([]);
  const [total, setTotal] = useState<SellerSlaResult>({
    avgMinutes: null,
    overdueCount: 0,
    worstMinutes: null,
  });
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const cutoff = getCutoff(filter);

    const [{ data: cfgData }, { data: ovData }, { data: settingsData }] = await Promise.all([
      supabase.from("sla_seller_config").select("*").eq("active", true),
      supabase.from("sla_overrides").select("user_id, start_date, end_date"),
      supabase.from("sla_settings").select("target_minutes").eq("id", 1).single(),
    ]);

    const configs = (cfgData ?? []) as SellerConfigRow[];
    const overrides = (ovData ?? []) as OverrideRow[];
    const target = (settingsData?.target_minutes ?? 20) as number;

    const channelIds = configs.map((c) => c.channel_id);
    const convs = await fetchConversations(supabase, channelIds, cutoff);
    const msgs = await fetchMessages(supabase, convs.map((c) => c.id));
    const byChannel = groupConversations(convs, msgs);

    const now = new Date();
    const pooled: SellerRounds = { closed: [], openElapsed: [] };
    const computedRows: SlaRow[] = [];

    for (const cfg of configs) {
      const win = windowFor(cfg, overrides);
      const convsForChannel = byChannel.get(cfg.channel_id) ?? [];
      const rounds = collectRounds(convsForChannel, win, now);
      pooled.closed.push(...rounds.closed);
      pooled.openElapsed.push(...rounds.openElapsed);
      const summary = summarizeRounds(rounds, target);
      computedRows.push({
        userId: cfg.user_id,
        displayName: cfg.display_name || "(sem nome)",
        ...summary,
      });
    }

    computedRows.sort((a, b) => b.overdueCount - a.overdueCount);
    setRows(computedRows);
    setTotal(summarizeRounds(pooled, target));
    setLoading(false);
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const channel = supabase
      .channel("sla-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, fetchAndCompute)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, fetchAndCompute)
      .subscribe();

    const ticker = setInterval(fetchAndCompute, 60_000);

    return () => {
      supabase.removeChannel(channel);
      clearInterval(ticker);
    };
  }, [fetchAndCompute]);

  return { rows, total, loading };
}
```

- [ ] **Step 2: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-sla-stats.ts
git commit -m "feat(sla): hook use-sla-stats com linhas por vendedor e total"
```

---

## Task 6: Rotas admin

**Files:**
- Create: `frontend/src/lib/admin-auth.ts`
- Create: `frontend/src/app/api/admin/sla/config/route.ts`
- Create: `frontend/src/app/api/admin/sla/vendedores/route.ts`
- Create: `frontend/src/app/api/admin/sla/target/route.ts`
- Create: `frontend/src/app/api/admin/sla/overrides/route.ts`
- Create: `frontend/src/app/api/admin/sla/overrides/[id]/route.ts`

- [ ] **Step 1: Helper de checagem admin**

Create `frontend/src/lib/admin-auth.ts`:
```ts
import { createClient as createServerClient } from "@/lib/supabase/server";

/** Retorna { ok } ou { error, status } se o chamador não for admin. */
export async function requireAdmin(): Promise<
  { ok: true } | { ok: false; error: string; status: number }
> {
  const supabase = await createServerClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) return { ok: false, error: "Não autenticado", status: 401 };
  if (user.app_metadata?.role !== "admin")
    return { ok: false, error: "Permissão insuficiente", status: 403 };
  return { ok: true };
}
```

- [ ] **Step 2: Rota de configs de vendedor**

Create `frontend/src/app/api/admin/sla/config/route.ts`:
```ts
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_seller_config")
    .select("*")
    .order("display_name");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const body = await req.json();
  const {
    user_id,
    channel_id,
    display_name,
    window_start_minute,
    window_end_minute,
    active_weekdays,
    active,
  } = body;

  if (!user_id || !channel_id) {
    return NextResponse.json({ error: "user_id e channel_id obrigatórios" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_seller_config")
    .upsert(
      {
        user_id,
        channel_id,
        display_name: display_name ?? "",
        window_start_minute: window_start_minute ?? 600,
        window_end_minute: window_end_minute ?? 960,
        active_weekdays: active_weekdays ?? [1, 2, 3, 4, 5],
        active: active ?? true,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" }
    )
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 3: Rota de vendedores (usuários role=vendedor)**

Create `frontend/src/app/api/admin/sla/vendedores/route.ts`:
```ts
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  const { data, error } = await admin.auth.admin.listUsers({ perPage: 1000 });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const vendedores = data.users
    .filter((u) => u.app_metadata?.role === "vendedor")
    .map((u) => ({ id: u.id, email: u.email }));

  return NextResponse.json(vendedores);
}
```

- [ ] **Step 4: Rota do alvo global**

Create `frontend/src/app/api/admin/sla/target/route.ts`:
```ts
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_settings")
    .select("target_minutes")
    .eq("id", 1)
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PUT(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const { target_minutes } = await req.json();
  if (typeof target_minutes !== "number" || target_minutes <= 0) {
    return NextResponse.json({ error: "target_minutes inválido" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_settings")
    .upsert({ id: 1, target_minutes, updated_at: new Date().toISOString() }, { onConflict: "id" })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
```

- [ ] **Step 5: Rota de overrides (listar/criar)**

Create `frontend/src/app/api/admin/sla/overrides/route.ts`:
```ts
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { createClient as createServerClient } from "@/lib/supabase/server";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_overrides")
    .select("*")
    .order("start_date", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const { user_id, start_date, end_date, reason } = await req.json();
  if (!start_date || !end_date) {
    return NextResponse.json({ error: "start_date e end_date obrigatórios" }, { status: 400 });
  }
  if (end_date < start_date) {
    return NextResponse.json({ error: "end_date deve ser >= start_date" }, { status: 400 });
  }

  // created_by = admin logado
  const authClient = await createServerClient();
  const {
    data: { user },
  } = await authClient.auth.getUser();

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_overrides")
    .insert({
      user_id: user_id ?? null,
      start_date,
      end_date,
      reason: reason ?? null,
      created_by: user?.id ?? null,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 6: Rota de override individual (deletar)**

Create `frontend/src/app/api/admin/sla/overrides/[id]/route.ts`:
```ts
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("sla_overrides").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 7: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/admin-auth.ts frontend/src/app/api/admin/sla
git commit -m "feat(sla): rotas admin para config, vendedores, alvo e anulacoes"
```

---

## Task 7: Aba SLA no /config (admin)

**Files:**
- Create: `frontend/src/components/config/sla-tab.tsx`
- Modify: `frontend/src/app/(authenticated)/config/page.tsx`

- [ ] **Step 1: Criar o componente da aba**

Create `frontend/src/components/config/sla-tab.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";

const WEEKDAYS = [
  { v: 0, label: "Dom" },
  { v: 1, label: "Seg" },
  { v: 2, label: "Ter" },
  { v: 3, label: "Qua" },
  { v: 4, label: "Qui" },
  { v: 5, label: "Sex" },
  { v: 6, label: "Sáb" },
];

interface Channel { id: string; name?: string; phone_number?: string }
interface Vendedor { id: string; email: string }
interface Config {
  user_id: string;
  channel_id: string;
  display_name: string;
  window_start_minute: number;
  window_end_minute: number;
  active_weekdays: number[];
  active: boolean;
}
interface Override {
  id: string;
  user_id: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;
}

function minToTime(m: number): string {
  const h = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  return `${h}:${mm}`;
}
function timeToMin(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

export function SlaTab() {
  const [configs, setConfigs] = useState<Config[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [vendedores, setVendedores] = useState<Vendedor[]>([]);
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [target, setTarget] = useState<number>(20);
  const [loading, setLoading] = useState(true);

  // form: novo vendedor
  const [newUserId, setNewUserId] = useState("");
  const [newChannelId, setNewChannelId] = useState("");
  const [newName, setNewName] = useState("");

  // form: nova anulação
  const [ovUser, setOvUser] = useState<string>(""); // "" = global
  const [ovStart, setOvStart] = useState("");
  const [ovEnd, setOvEnd] = useState("");
  const [ovReason, setOvReason] = useState("");

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    const [cfgRes, chRes, venRes, ovRes, tgtRes] = await Promise.all([
      fetch("/api/admin/sla/config"),
      fetch("/api/channels"),
      fetch("/api/admin/sla/vendedores"),
      fetch("/api/admin/sla/overrides"),
      fetch("/api/admin/sla/target"),
    ]);
    if (cfgRes.ok) setConfigs(await cfgRes.json());
    if (chRes.ok) setChannels(await chRes.json());
    if (venRes.ok) setVendedores(await venRes.json());
    if (ovRes.ok) setOverrides(await ovRes.json());
    if (tgtRes.ok) setTarget((await tgtRes.json()).target_minutes ?? 20);
    setLoading(false);
  }

  async function saveConfig(cfg: Config) {
    const res = await fetch("/api/admin/sla/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    if (res.ok) void loadAll();
  }

  async function addVendedor(e: React.FormEvent) {
    e.preventDefault();
    if (!newUserId || !newChannelId) return;
    await saveConfig({
      user_id: newUserId,
      channel_id: newChannelId,
      display_name: newName.trim(),
      window_start_minute: 600,
      window_end_minute: 960,
      active_weekdays: [1, 2, 3, 4, 5],
      active: true,
    });
    setNewUserId("");
    setNewChannelId("");
    setNewName("");
  }

  async function saveTarget() {
    await fetch("/api/admin/sla/target", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_minutes: target }),
    });
  }

  async function addOverride(e: React.FormEvent) {
    e.preventDefault();
    if (!ovStart || !ovEnd) return;
    const res = await fetch("/api/admin/sla/overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: ovUser || null,
        start_date: ovStart,
        end_date: ovEnd,
        reason: ovReason.trim() || null,
      }),
    });
    if (res.ok) {
      setOvStart("");
      setOvEnd("");
      setOvReason("");
      setOvUser("");
      void loadAll();
    }
  }

  async function deleteOverride(id: string) {
    if (!confirm("Remover esta anulação?")) return;
    const res = await fetch(`/api/admin/sla/overrides/${id}`, { method: "DELETE" });
    if (res.ok) void loadAll();
  }

  function nameForUser(userId: string | null): string {
    if (userId === null) return "Global (todos)";
    const cfg = configs.find((c) => c.user_id === userId);
    if (cfg?.display_name) return cfg.display_name;
    const v = vendedores.find((x) => x.id === userId);
    return v?.email ?? userId.slice(0, 8);
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-6">
        <div className="w-4 h-4 border-2 border-[#dedbd6] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#7b7b78] text-[14px]">Carregando configuração de SLA...</p>
      </div>
    );
  }

  const inputCls =
    "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none";
  const btnDark =
    "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-105 active:scale-[0.9]";

  return (
    <div className="space-y-6">
      {/* Alvo global */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-4">Alvo de SLA</h2>
        <div className="flex items-center gap-3">
          <span className="text-[14px] text-[#7b7b78]">Lead em atraso após</span>
          <input
            type="number"
            min={1}
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
            className={`${inputCls} w-24`}
          />
          <span className="text-[14px] text-[#7b7b78]">minutos comerciais sem resposta</span>
          <button onClick={saveTarget} className={btnDark}>Salvar</button>
        </div>
      </div>

      {/* Vendedores */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-4">Vendedores</h2>

        <div className="space-y-3 mb-5">
          {configs.length === 0 && (
            <p className="text-[#7b7b78] text-[14px]">Nenhum vendedor configurado.</p>
          )}
          {configs.map((cfg) => (
            <div key={cfg.user_id} className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={cfg.display_name}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, display_name: e.target.value } : c))
                  )
                }
                placeholder="Nome"
                className={`${inputCls} w-32`}
              />
              <select
                value={cfg.channel_id}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, channel_id: e.target.value } : c))
                  )
                }
                className={inputCls}
              >
                {channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>{ch.name ?? ch.phone_number ?? ch.id.slice(0, 8)}</option>
                ))}
              </select>
              <input
                type="time"
                value={minToTime(cfg.window_start_minute)}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, window_start_minute: timeToMin(e.target.value) } : c))
                  )
                }
                className={inputCls}
              />
              <span className="text-[#7b7b78]">até</span>
              <input
                type="time"
                value={minToTime(cfg.window_end_minute)}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, window_end_minute: timeToMin(e.target.value) } : c))
                  )
                }
                className={inputCls}
              />
              <div className="flex items-center gap-1">
                {WEEKDAYS.map((wd) => {
                  const on = cfg.active_weekdays.includes(wd.v);
                  return (
                    <button
                      key={wd.v}
                      type="button"
                      onClick={() =>
                        setConfigs((prev) =>
                          prev.map((c) =>
                            c.user_id === cfg.user_id
                              ? {
                                  ...c,
                                  active_weekdays: on
                                    ? c.active_weekdays.filter((d) => d !== wd.v)
                                    : [...c.active_weekdays, wd.v].sort(),
                                }
                              : c
                          )
                        )
                      }
                      className={`px-2 py-1 rounded-[4px] text-[12px] border ${
                        on ? "bg-[#111111] text-white border-[#111111]" : "bg-white text-[#7b7b78] border-[#dedbd6]"
                      }`}
                    >
                      {wd.label}
                    </button>
                  );
                })}
              </div>
              <label className="flex items-center gap-1 text-[13px] text-[#7b7b78]">
                <input
                  type="checkbox"
                  checked={cfg.active}
                  onChange={(e) =>
                    setConfigs((prev) =>
                      prev.map((c) => (c.user_id === cfg.user_id ? { ...c, active: e.target.checked } : c))
                    )
                  }
                />
                Ativo
              </label>
              <button onClick={() => saveConfig(cfg)} className={`${btnDark} ml-auto`}>Salvar</button>
            </div>
          ))}
        </div>

        {/* Adicionar vendedor */}
        <form onSubmit={addVendedor} className="flex flex-wrap items-center gap-3 p-4 bg-white border border-[#dedbd6] rounded-[8px]">
          <select value={newUserId} onChange={(e) => setNewUserId(e.target.value)} className={inputCls} required>
            <option value="">Selecione o vendedor…</option>
            {vendedores.map((v) => (
              <option key={v.id} value={v.id}>{v.email}</option>
            ))}
          </select>
          <select value={newChannelId} onChange={(e) => setNewChannelId(e.target.value)} className={inputCls} required>
            <option value="">Selecione o canal…</option>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.name ?? ch.phone_number ?? ch.id.slice(0, 8)}</option>
            ))}
          </select>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome de exibição"
            className={`${inputCls} w-40`}
          />
          <button type="submit" className={btnDark}>+ Adicionar</button>
        </form>
      </div>

      {/* Anulações */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-1">Anulações</h2>
        <p className="text-[13px] text-[#7b7b78] mb-4">Dias removidos da medição (folgas, viagens, feriados).</p>

        <div className="space-y-2 mb-5">
          {overrides.length === 0 && (
            <p className="text-[#7b7b78] text-[14px]">Nenhuma anulação cadastrada.</p>
          )}
          {overrides.map((ov) => (
            <div key={ov.id} className="flex items-center gap-3 bg-white border border-[#dedbd6] rounded-[8px] px-4 py-2">
              <span className="text-[14px] text-[#111111] font-normal w-40">{nameForUser(ov.user_id)}</span>
              <span className="text-[14px] text-[#7b7b78]">{ov.start_date} → {ov.end_date}</span>
              {ov.reason && <span className="text-[13px] text-[#7b7b78] italic">{ov.reason}</span>}
              <button
                onClick={() => deleteOverride(ov.id)}
                className="ml-auto p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors"
                title="Remover"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          ))}
        </div>

        <form onSubmit={addOverride} className="flex flex-wrap items-center gap-3 p-4 bg-white border border-[#dedbd6] rounded-[8px]">
          <select value={ovUser} onChange={(e) => setOvUser(e.target.value)} className={inputCls}>
            <option value="">Global (todos)</option>
            {configs.map((c) => (
              <option key={c.user_id} value={c.user_id}>{c.display_name || c.user_id.slice(0, 8)}</option>
            ))}
          </select>
          <input type="date" value={ovStart} onChange={(e) => setOvStart(e.target.value)} className={inputCls} required />
          <span className="text-[#7b7b78]">até</span>
          <input type="date" value={ovEnd} onChange={(e) => setOvEnd(e.target.value)} className={inputCls} required />
          <input
            type="text"
            value={ovReason}
            onChange={(e) => setOvReason(e.target.value)}
            placeholder="Motivo (folga, viagem…)"
            className={`${inputCls} w-44`}
          />
          <button type="submit" className={btnDark}>+ Adicionar</button>
        </form>
      </div>
    </div>
  );
}
```

> NOTA sobre nomes de coluna do canal: o `<option>` usa `ch.name ?? ch.phone_number`.
> Confirme no schema real de `channels` quais campos existem (ex.: pode ser `name` ou
> `phone`). Ajuste os campos da interface `Channel` e do label conforme o retorno de
> `/api/channels`.

- [ ] **Step 2: Registrar a aba no /config com gating de admin**

Modify `frontend/src/app/(authenticated)/config/page.tsx`. Substituir o conteúdo por:
```tsx
"use client";

import { useState, useEffect } from "react";
import { TagsTab } from "@/components/config/tags-tab";
import { PricingTab } from "@/components/config/pricing-tab";
import { LpWebhookTab } from "@/components/config/lp-webhook-tab";
import { SlaTab } from "@/components/config/sla-tab";
import { createClient } from "@/lib/supabase/client";

const BASE_TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
  { key: "lp-webhook", label: "Landing Pages" },
] as const;

type TabKey = "tags" | "pricing" | "lp-webhook" | "sla";

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("tags");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setIsAdmin(data.user?.app_metadata?.role === "admin");
    });
  }, []);

  const tabs: { key: TabKey; label: string }[] = [
    ...BASE_TABS,
    ...(isAdmin ? [{ key: "sla" as const, label: "SLA" }] : []),
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Configurações</h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Preferências e integrações</p>
      </div>

      <div className="px-4 md:px-8 py-4 md:py-8 overflow-auto flex-1 bg-[#faf9f6]">
        <div className="max-w-3xl">
          <div className="flex border-b border-[#dedbd6] mb-8">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={activeTab === tab.key
                  ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
                  : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "tags" && <TagsTab />}
          {activeTab === "pricing" && <PricingTab />}
          {activeTab === "lp-webhook" && <LpWebhookTab />}
          {activeTab === "sla" && isAdmin && <SlaTab />}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/config/sla-tab.tsx "frontend/src/app/(authenticated)/config/page.tsx"
git commit -m "feat(sla): aba SLA no /config (vendedores, alvo, anulacoes) com gating admin"
```

---

## Task 8: Dashboard — `SlaTable`

**Files:**
- Create: `frontend/src/components/dashboard/sla-table.tsx`
- Modify: `frontend/src/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Criar a tabela**

Create `frontend/src/components/dashboard/sla-table.tsx`:
```tsx
"use client";

import { useState } from "react";
import { useSlaStats, type DateFilter } from "@/hooks/use-sla-stats";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const DATE_FILTER_OPTIONS: { value: DateFilter; label: string }[] = [
  { value: "1d", label: "Hoje" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "all", label: "Tudo" },
];

function dur(m: number | null): string {
  return m !== null ? formatBusinessDuration(m) : "—";
}

export function SlaTable() {
  const [filter, setFilter] = useState<DateFilter>("7d");
  const { rows, total, loading } = useSlaStats(filter);

  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          SLA — Resposta por vendedor
        </p>
        <Select value={filter} onValueChange={(v) => setFilter(v as DateFilter)}>
          <SelectTrigger className="h-7 w-[110px] text-[13px] border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:ring-0 focus:ring-offset-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="text-[13px]">
            {DATE_FILTER_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <table className="w-full text-[14px]">
          <thead>
            <tr className="border-b border-[#dedbd6] text-[#7b7b78] text-[12px] uppercase tracking-[0.4px]">
              <th className="text-left font-normal px-4 py-3">Vendedor</th>
              <th className="text-right font-normal px-4 py-3">Média resp.</th>
              <th className="text-right font-normal px-4 py-3">Em atraso agora</th>
              <th className="text-right font-normal px-4 py-3">Pior SLA</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-[#7b7b78]">Carregando…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-[#7b7b78]">Nenhum vendedor configurado.</td></tr>
            ) : (
              rows.map((r) => (
                <tr key={r.userId} className="border-b border-[#f0ede8] last:border-0">
                  <td className="px-4 py-3 text-[#111111]">{r.displayName}</td>
                  <td className="px-4 py-3 text-right text-[#111111]">{dur(r.avgMinutes)}</td>
                  <td className={`px-4 py-3 text-right font-medium ${r.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                    {r.overdueCount}
                  </td>
                  <td className="px-4 py-3 text-right text-[#111111]">{dur(r.worstMinutes)}</td>
                </tr>
              ))
            )}
          </tbody>
          {!loading && rows.length > 0 && (
            <tfoot>
              <tr className="border-t border-[#dedbd6] bg-[#faf9f6] font-medium">
                <td className="px-4 py-3 text-[#111111]">Total</td>
                <td className="px-4 py-3 text-right text-[#111111]">{dur(total.avgMinutes)}</td>
                <td className={`px-4 py-3 text-right ${total.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                  {total.overdueCount}
                </td>
                <td className="px-4 py-3 text-right text-[#111111]">{dur(total.worstMinutes)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Trocar no dashboard**

Modify `frontend/src/app/(authenticated)/dashboard/page.tsx`:
- Trocar o import na linha 10:
```tsx
import { SlaTable } from "@/components/dashboard/sla-table";
```
- Trocar o uso (linha ~132) de `<SlaHeroSection />` por `<SlaTable />`.

- [ ] **Step 3: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dashboard/sla-table.tsx "frontend/src/app/(authenticated)/dashboard/page.tsx"
git commit -m "feat(sla): dashboard em tabela por vendedor com total"
```

---

## Task 9: Limpeza e verificação final

**Files:**
- Remove: `frontend/src/hooks/use-joao-sla-stats.ts`
- Remove: `frontend/src/components/dashboard/sla-hero-section.tsx`

- [ ] **Step 1: Confirmar que os arquivos antigos não são mais referenciados**

Run (em `frontend`):
```bash
grep -rn "use-joao-sla-stats\|useJoaoSlaStats\|sla-hero-section\|SlaHeroSection\|get_seller_overdue_candidates" src
```
Expected: nenhuma referência (fora dos arquivos a remover).

- [ ] **Step 2: Remover os arquivos obsoletos**

Run (em `frontend`):
```bash
git rm src/hooks/use-joao-sla-stats.ts src/components/dashboard/sla-hero-section.tsx
```

- [ ] **Step 3: Suite de testes completa**

Run (em `frontend`): `npm test`
Expected: todos os testes (business-hours + sla-rounds) PASS.

- [ ] **Step 4: Type-check + lint**

Run (em `frontend`): `npx tsc --noEmit && npm run lint`
Expected: sem erros.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore(sla): remove cálculo antigo do João (substituído pelo SLA por vendedor)"
```

- [ ] **Step 6: PARAR e avisar o usuário**

Conforme CLAUDE.md: não fazer push. Avisar que está pronto para teste no dev, e que a
migration `migrations/20260611_sla_per_seller.sql` precisa ser aplicada no Supabase
(confirmando antes o vínculo real usuário↔canal do João no seed).

---

## Self-Review (preenchido pelo autor do plano)

- **Cobertura do spec:** modelo de dados (Task 2), motor parametrizado (Task 3),
  rodada de espera/definições (Task 4), hook por vendedor + total (Task 5), rotas admin
  (Task 6), UI /config com anulações e alvo (Task 7), dashboard tabela (Task 8),
  remoção da RPC e limpeza (Tasks 2 e 9). ✓
- **Placeholders:** as duas NOTAs (seed do João, nomes de coluna de `channels`) são
  pontos de confirmação com o usuário/schema real, não código faltante — sinalizados
  explicitamente.
- **Consistência de tipos:** `BusinessWindow`, `SlaConversation`, `SellerRounds`,
  `SellerSlaResult`, `SlaRow`, `DateFilter` usados de forma idêntica entre Tasks 3-8.
  `collectRounds`/`summarizeRounds` com as mesmas assinaturas em teste e implementação.
