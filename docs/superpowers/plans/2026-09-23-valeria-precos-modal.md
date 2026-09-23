# Preços da ValerIA editáveis em /produtos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin edita em /produtos, num modal, o preço de cada item do catálogo da ValerIA (`products`), e a ValerIA passa a ofertar o valor novo em até 60 s.

**Architecture:** Rota Next `/api/admin/valeria-catalog` (GET/PATCH, `requireAdmin` + service role) grava `products.price_formatted` no formato canônico `R$ 1.234,56`. O backend não ganha endpoint: o cache de `catalog.py` cai de 300 s para 60 s. Os exemplos de preço `R$23,90` saem dos prompts. Spec: `docs/superpowers/specs/2026-09-23-valeria-precos-modal-design.md`.

**Tech Stack:** Next.js App Router (client component), Supabase JS (service role), vitest (ambiente node), FastAPI/Python, pytest.

---

## Regras para quem executa (valem para todas as tasks)

- O working tree é COMPARTILHADO com outra sessão: há arquivos modificados que não são desta feature (`frontend/src/app/(authenticated)/conversas/page.tsx`, `frontend/src/components/authenticated-shell.tsx`, `frontend/src/hooks/use-overdue-leads.ts`). NÃO toque, NÃO faça stash/checkout/reset neles.
- As tasks 2, 3 e 4 rodam em PARALELO. **Não faça commit** — o controlador commita cada task depois da revisão (commits paralelos disputam o `index.lock`). Toque APENAS nos arquivos listados na sua task.
- Frontend: comandos rodam em `frontend/`. Backend: comandos rodam em `backend/`.
- `.tsx` de teste NÃO roda neste repo (jsdom/@testing-library ausentes). Toda lógica testável vai em `.ts` puro.

## File Structure

| Arquivo | Task | Responsabilidade |
|---|---|---|
| `frontend/src/lib/valeria-catalog.ts` (novo) | 1 | Tipo `CatalogItem`; formatar/parsear/validar preço |
| `frontend/src/lib/valeria-catalog.test.ts` (novo) | 1 | Testes da lib |
| `frontend/src/app/api/admin/valeria-catalog/route.ts` (novo) | 2 | GET/PATCH |
| `frontend/src/app/api/admin/valeria-catalog/route.test.ts` (novo) | 2 | Testes da rota |
| `frontend/src/components/produtos/valeria-precos-diff.ts` (novo) | 3 | Calcula alterações e inválidos do modal |
| `frontend/src/components/produtos/valeria-precos-diff.test.ts` (novo) | 3 | Testes do diff |
| `frontend/src/components/produtos/valeria-precos-modal.tsx` (novo) | 3 | Modal |
| `frontend/src/app/(authenticated)/produtos/page.tsx` (mod) | 3 | Botão admin + montar o modal |
| `backend/app/agent/catalog.py` (mod) | 4 | TTL 60 s |
| `backend/app/agent/prompts/base.py` (mod) | 4 | Tirar `23,90` |
| `backend/app/agent/prompts/voice_card.py` (mod) | 4 | Tirar `23,90` |
| `backend/tests/test_valeria_precos_modal_2026_09_23.py` (novo) | 4 | TTL + guarda anti-preço-de-exemplo |

---

### Task 1: Lib de preço do catálogo (controlador, ANTES do disparo paralelo)

**Files:**
- Create: `frontend/src/lib/valeria-catalog.ts`
- Test: `frontend/src/lib/valeria-catalog.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, expect, it } from "vitest";
import { formatPrecoCatalogo, parsePrecoCatalogo, precoValido } from "./valeria-catalog";

describe("formatPrecoCatalogo", () => {
  it("usa o formato canônico do banco, com espaço ASCII", () => {
    expect(formatPrecoCatalogo(28.7)).toBe("R$ 28,70");
    expect(formatPrecoCatalogo(1169.7)).toBe("R$ 1.169,70");
    expect(formatPrecoCatalogo(12345.5)).toBe("R$ 12.345,50");
    expect(formatPrecoCatalogo(599)).toBe("R$ 599,00");
    expect(formatPrecoCatalogo(28.7)).not.toContain(" ");
  });
});

describe("parsePrecoCatalogo", () => {
  it.each([
    ["R$ 28,70", 28.7],
    ["R$ 1.169,70", 1169.7],
    ["28,70", 28.7],
    ["28,7", 28.7],
    ["28.70", 28.7],
    ["1.169,70", 1169.7],
    ["1169,70", 1169.7],
    ["1.169", 1169],
    ["599", 599],
    [" R$ 32,70 ", 32.7],
  ])("%s -> %s", (entrada, esperado) => {
    expect(parsePrecoCatalogo(entrada)).toBe(esperado);
  });

  it.each([[""], ["abc"], ["28,705"], ["1,2,3"], ["12.34.5"], ["-5"], [null], [undefined]])(
    "rejeita %s",
    (entrada) => {
      expect(parsePrecoCatalogo(entrada as string | null | undefined)).toBeNull();
    },
  );

  it("ida e volta com o formatador", () => {
    for (const v of [0.5, 22.9, 97.7, 169.7, 949, 1234.56]) {
      expect(parsePrecoCatalogo(formatPrecoCatalogo(v))).toBe(v);
    }
  });
});

describe("precoValido", () => {
  it("aceita positivo com até 2 casas e até 99.999", () => {
    expect(precoValido(28.7)).toBe(true);
    expect(precoValido(99999)).toBe(true);
  });
  it.each([[0], [-1], [28.705], [100000], [Number.NaN], [Infinity], ["28,70"], [null]])(
    "rejeita %s",
    (v) => {
      expect(precoValido(v)).toBe(false);
    },
  );
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/lib/valeria-catalog.test.ts`
Expected: FAIL (módulo `./valeria-catalog` não existe)

- [ ] **Step 3: Implementar**

```ts
/**
 * Preço do catálogo da ValerIA (tabela `products`). O banco guarda TEXTO no
 * formato "R$ 1.234,56" — é o que vai pro prompt e o que `pricing.parse_brl`
 * (backend) lê. Não use Intl/toLocaleString: ele insere U+00A0 no lugar do
 * espaço e o texto deixa de bater com o resto do catálogo.
 */

export interface CatalogItem {
  id: string;
  sector: string;
  name: string;
  preco: number | null;
  price_formatted: string | null;
}

export const PRECO_MAXIMO = 99999;

export function formatPrecoCatalogo(valor: number): string {
  const centavos = Math.round(valor * 100);
  const inteiro = Math.floor(centavos / 100);
  const decimal = String(centavos % 100).padStart(2, "0");
  const milhar = String(inteiro).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `R$ ${milhar},${decimal}`;
}

/** Aceita "28,70", "28.70", "28,7", "1.169,70", "1169,70", "R$ 28,70". Lixo -> null. */
export function parsePrecoCatalogo(entrada: string | null | undefined): number | null {
  if (entrada == null) return null;
  const s = entrada.replace(/R\$/i, "").replace(/[\s ]/g, "");
  if (!/^\d[\d.,]*$/.test(s)) return null;

  let normal: string;
  const virgula = s.lastIndexOf(",");
  if (virgula >= 0) {
    // Vírgula é o decimal; pontos só podem ser milhar.
    if (s.indexOf(",") !== virgula) return null;
    const inteiro = s.slice(0, virgula);
    const decimal = s.slice(virgula + 1);
    if (decimal.length === 0 || decimal.length > 2) return null;
    if (inteiro.includes(".") && !/^\d{1,3}(\.\d{3})+$/.test(inteiro)) return null;
    normal = `${inteiro.replace(/\./g, "")}.${decimal}`;
  } else if (s.includes(".")) {
    // Só pontos: um único ponto seguido de 1-2 dígitos é decimal ("28.70");
    // grupos de 3 são milhar ("1.169").
    const ponto = s.lastIndexOf(".");
    const decimal = s.slice(ponto + 1);
    if (s.indexOf(".") === ponto && decimal.length >= 1 && decimal.length <= 2) normal = s;
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) normal = s.replace(/\./g, "");
    else return null;
  } else {
    normal = s;
  }

  const n = Number(normal);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}

export function precoValido(valor: unknown): valor is number {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return false;
  if (valor <= 0 || valor > PRECO_MAXIMO) return false;
  return Math.abs(valor * 100 - Math.round(valor * 100)) < 1e-6;
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/lib/valeria-catalog.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/valeria-catalog.ts frontend/src/lib/valeria-catalog.test.ts docs/superpowers/specs/2026-09-23-valeria-precos-modal-design.md docs/superpowers/plans/2026-09-23-valeria-precos-modal.md
git commit -m "feat(produtos): lib de preco do catalogo da ValerIA + spec e plano"
```

---

### Task 2: Rota `/api/admin/valeria-catalog` (paralela)

**Files:**
- Create: `frontend/src/app/api/admin/valeria-catalog/route.ts`
- Test: `frontend/src/app/api/admin/valeria-catalog/route.test.ts`

Contexto: `/api/admin/*` já está no `matcher` do `src/proxy.ts` e em `ADMIN_API_PREFIXES` (`src/lib/auth/roles.ts`) — não mexa neles. Padrão de rota admin: `src/app/api/admin/sla/config/route.ts`. Padrão de mock do Supabase: `src/app/api/valeria-score/route.test.ts`.

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/admin-auth", () => ({ requireAdmin: vi.fn() }));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET, PATCH } from "./route";
import { requireAdmin } from "@/lib/admin-auth";
import { getServiceSupabase } from "@/lib/supabase/api";

type Resultado = { data: unknown; error: unknown };
type Consulta = Record<"select" | "eq" | "in" | "order" | "upsert", ReturnType<typeof vi.fn>>;

// Query builder falso do supabase-js: todo método encadeia e o `await` devolve o resultado.
function consulta(resultado: Resultado): Consulta {
  const q: Record<string, unknown> = {};
  for (const m of ["select", "eq", "in", "order", "upsert"]) q[m] = vi.fn(() => q);
  q.then = (ok: (r: Resultado) => unknown, falha?: (e: unknown) => unknown) =>
    Promise.resolve(resultado).then(ok, falha);
  return q as unknown as Consulta;
}

function supabaseCom(...resultados: Resultado[]) {
  const consultas = resultados.map(consulta);
  let i = 0;
  const from = vi.fn(() => consultas[i++]);
  vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
  return { from, consultas };
}

const admin = () => vi.mocked(requireAdmin).mockResolvedValue({ ok: true });

const patch = (corpo: unknown) =>
  PATCH(
    new NextRequest("http://localhost/api/admin/valeria-catalog", {
      method: "PATCH",
      body: JSON.stringify(corpo),
    }),
  );

const LINHA = {
  id: "a",
  sector: "Atacado",
  name: "Canastra Suave — Moído 250g",
  price_formatted: "R$ 28,70",
  min_lot: null,
  description: null,
  image_urls: null,
  is_active: true,
};

afterEach(() => {
  vi.resetAllMocks();
});

describe("GET /api/admin/valeria-catalog", () => {
  it("repassa o bloqueio de quem não é admin sem tocar no banco", async () => {
    vi.mocked(requireAdmin).mockResolvedValue({ ok: false, error: "Permissão insuficiente", status: 403 });
    const res = await GET();
    expect(res.status).toBe(403);
    expect(getServiceSupabase).not.toHaveBeenCalled();
  });

  it("lista só ativos e converte o texto em número", async () => {
    admin();
    const { consultas } = supabaseCom({
      data: [{ id: "a", sector: "Atacado", name: "X", price_formatted: "R$ 1.169,70" }],
      error: null,
    });
    const res = await GET();
    const corpo = await res.json();
    expect(res.status).toBe(200);
    expect(consultas[0].eq).toHaveBeenCalledWith("is_active", true);
    expect(corpo.data[0]).toEqual({
      id: "a",
      sector: "Atacado",
      name: "X",
      price_formatted: "R$ 1.169,70",
      preco: 1169.7,
    });
  });

  it("texto de preço ilegível vira preco null (a linha aparece vazia)", async () => {
    admin();
    supabaseCom({ data: [{ id: "a", sector: "Atacado", name: "X", price_formatted: "sob consulta" }], error: null });
    const corpo = await (await GET()).json();
    expect(corpo.data[0].preco).toBeNull();
  });
});

describe("PATCH /api/admin/valeria-catalog", () => {
  it.each([
    ["itens vazio", { itens: [] }],
    ["sem itens", {}],
    ["preço zero", { itens: [{ id: "a", preco: 0 }] }],
    ["3 casas decimais", { itens: [{ id: "a", preco: 28.705 }] }],
    ["preço em texto", { itens: [{ id: "a", preco: "28,70" }] }],
    ["id vazio", { itens: [{ id: "", preco: 28.7 }] }],
    ["id repetido", { itens: [{ id: "a", preco: 28.7 }, { id: "a", preco: 29.7 }] }],
  ])("400 quando %s, sem tocar no banco", async (_caso, corpo) => {
    admin();
    const { from } = supabaseCom();
    const res = await patch(corpo);
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it("404 quando algum id não existe ou está inativo, e nada é gravado", async () => {
    admin();
    const { from, consultas } = supabaseCom({ data: [LINHA], error: null });
    const res = await patch({ itens: [{ id: "a", preco: 29.7 }, { id: "zzz", preco: 30 }] });
    expect(res.status).toBe(404);
    expect(from).toHaveBeenCalledTimes(1);
    expect(consultas[0].in).toHaveBeenCalledWith("id", ["a", "zzz"]);
    expect(consultas[0].eq).toHaveBeenCalledWith("is_active", true);
  });

  it("grava no formato canônico num único upsert, repetindo as colunas da linha", async () => {
    admin();
    const { consultas } = supabaseCom(
      { data: [LINHA], error: null },
      { data: [{ id: "a", sector: "Atacado", name: LINHA.name, price_formatted: "R$ 1.234,50" }], error: null },
    );
    const res = await patch({ itens: [{ id: "a", preco: 1234.5 }] });
    expect(res.status).toBe(200);
    expect(consultas[1].upsert).toHaveBeenCalledTimes(1);
    expect(consultas[1].upsert).toHaveBeenCalledWith(
      [
        {
          ...LINHA,
          price_formatted: "R$ 1.234,50",
          updated_at: expect.any(String),
        },
      ],
      { onConflict: "id" },
    );
    const corpo = await res.json();
    expect(corpo.data[0].preco).toBe(1234.5);
  });

  it("500 quando o upsert falha", async () => {
    admin();
    supabaseCom({ data: [LINHA], error: null }, { data: null, error: { message: "boom" } });
    const res = await patch({ itens: [{ id: "a", preco: 29.7 }] });
    expect(res.status).toBe(500);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/app/api/admin/valeria-catalog/route.test.ts`
Expected: FAIL (`./route` não existe)

- [ ] **Step 3: Implementar**

```ts
/**
 * Preços que a ValerIA oferta (tabela `products`). Só admin. O backend relê o
 * catálogo a cada 60 s (`backend/app/agent/catalog.py`), então o valor salvo aqui
 * vira a oferta da ValerIA em até 1 minuto, no prompt e no `calcular_orcamento`.
 */
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";
import {
  formatPrecoCatalogo,
  parsePrecoCatalogo,
  precoValido,
  type CatalogItem,
} from "@/lib/valeria-catalog";

const COLUNAS_LEITURA = "id,sector,name,price_formatted";
// O upsert repete a linha inteira: INSERT ... ON CONFLICT checa NOT NULL antes do
// conflito, então mandar só {id, price_formatted} quebraria em `name`/`sector`.
const COLUNAS_LINHA = "id,sector,name,price_formatted,min_lot,description,image_urls,is_active";

interface LinhaLeitura {
  id: string;
  sector: string;
  name: string;
  price_formatted: string | null;
}

function paraItem(r: LinhaLeitura): CatalogItem {
  return {
    id: r.id,
    sector: r.sector,
    name: r.name,
    price_formatted: r.price_formatted,
    preco: parsePrecoCatalogo(r.price_formatted),
  };
}

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("products")
    .select(COLUNAS_LEITURA)
    .eq("is_active", true)
    .order("sector")
    .order("name");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: ((data ?? []) as LinhaLeitura[]).map(paraItem) });
}

export async function PATCH(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON inválido" }, { status: 400 });
  }

  const itens = (body as { itens?: unknown })?.itens;
  if (!Array.isArray(itens) || itens.length === 0) {
    return NextResponse.json({ error: "Nenhum preço para salvar" }, { status: 400 });
  }

  const precoPorId = new Map<string, number>();
  for (const item of itens as { id?: unknown; preco?: unknown }[]) {
    if (typeof item?.id !== "string" || item.id === "") {
      return NextResponse.json({ error: "Item sem id" }, { status: 400 });
    }
    if (!precoValido(item.preco)) {
      return NextResponse.json({ error: `Preço inválido para ${item.id}` }, { status: 400 });
    }
    if (precoPorId.has(item.id)) {
      return NextResponse.json({ error: `Produto repetido: ${item.id}` }, { status: 400 });
    }
    precoPorId.set(item.id, item.preco);
  }
  const ids = [...precoPorId.keys()];

  const sb = await getServiceSupabase();
  const { data: linhas, error: erroLeitura } = await sb
    .from("products")
    .select(COLUNAS_LINHA)
    .in("id", ids)
    .eq("is_active", true);
  if (erroLeitura) return NextResponse.json({ error: erroLeitura.message }, { status: 500 });
  if ((linhas ?? []).length !== ids.length) {
    return NextResponse.json({ error: "Produto não encontrado ou inativo" }, { status: 404 });
  }

  const agora = new Date().toISOString();
  const payload = (linhas as Record<string, unknown>[]).map((linha) => ({
    ...linha,
    price_formatted: formatPrecoCatalogo(precoPorId.get(linha.id as string)!),
    updated_at: agora,
  }));

  // Um único upsert = uma instrução só no Postgres: grava tudo ou nada.
  const { data, error } = await sb
    .from("products")
    .upsert(payload, { onConflict: "id" })
    .select(COLUNAS_LEITURA);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: ((data ?? []) as LinhaLeitura[]).map(paraItem) });
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/app/api/admin/valeria-catalog/route.test.ts src/lib/auth/proxy-coverage.test.ts`
Expected: PASS

- [ ] **Step 5: Tipos e lint**

Run: `npx tsc --noEmit -p . 2>&1 | grep -i "valeria-catalog" ; npx eslint src/app/api/admin/valeria-catalog`
Expected: nenhuma saída de erro para esses arquivos (erros pré-existentes em outros arquivos não são desta task — reporte, não conserte).

- [ ] **Step 6: NÃO commitar** — reporte ao controlador os arquivos criados e a saída dos testes.

---

### Task 3: Modal + botão em /produtos (paralela)

**Files:**
- Create: `frontend/src/components/produtos/valeria-precos-diff.ts`
- Test: `frontend/src/components/produtos/valeria-precos-diff.test.ts`
- Create: `frontend/src/components/produtos/valeria-precos-modal.tsx`
- Modify: `frontend/src/app/(authenticated)/produtos/page.tsx` (cabeçalho, linhas ~119-125, e imports)

Contexto: a lib `@/lib/valeria-catalog` (Task 1) já existe — importe, não recrie. A rota `/api/admin/valeria-catalog` está sendo escrita em paralelo (Task 2) com o contrato do spec: `GET -> { data: CatalogItem[] }`, `PATCH { itens: {id, preco}[] } -> { data } | { error }`. Antes de mexer no visual, invoque a skill `frontend-design:frontend-design` (regra do projeto) e mantenha a paleta da página (`#faf9f6`, `#dedbd6`, `#111111`, `#7b7b78`, verde `#1f9d57`).

- [ ] **Step 1: Escrever o teste do diff que falha**

```ts
import { describe, expect, it } from "vitest";
import type { CatalogItem } from "@/lib/valeria-catalog";
import { calcularAlteracoes, textoInicial } from "./valeria-precos-diff";

const itens: CatalogItem[] = [
  { id: "a", sector: "Atacado", name: "A", preco: 28.7, price_formatted: "R$ 28,70" },
  { id: "b", sector: "Atacado", name: "B", preco: 1169.7, price_formatted: "R$ 1.169,70" },
  { id: "c", sector: "Private Label", name: "C", preco: null, price_formatted: null },
];

const inalterados = () => Object.fromEntries(itens.map((i) => [i.id, textoInicial(i)]));

describe("textoInicial", () => {
  it("mostra o preço sem o R$ e vazio quando não há preço", () => {
    expect(textoInicial(itens[0])).toBe("28,70");
    expect(textoInicial(itens[1])).toBe("1.169,70");
    expect(textoInicial(itens[2])).toBe("");
  });
});

describe("calcularAlteracoes", () => {
  it("nada mudou -> nada a salvar", () => {
    expect(calcularAlteracoes(itens, inalterados())).toEqual({ alteracoes: [], invalidos: [] });
  });

  it("só a linha editada vai para o PATCH", () => {
    const textos = { ...inalterados(), a: "29,70" };
    expect(calcularAlteracoes(itens, textos)).toEqual({
      alteracoes: [{ id: "a", preco: 29.7 }],
      invalidos: [],
    });
  });

  it("aceita ponto como decimal e reescrita equivalente não conta como mudança", () => {
    expect(calcularAlteracoes(itens, { ...inalterados(), a: "29.7" }).alteracoes).toEqual([
      { id: "a", preco: 29.7 },
    ]);
    expect(calcularAlteracoes(itens, { ...inalterados(), b: "1169,7" }).alteracoes).toEqual([]);
  });

  it("texto ilegível, zero ou vazio (em item que tinha preço) é inválido e não vai para o PATCH", () => {
    const r = calcularAlteracoes(itens, { ...inalterados(), a: "abc", b: "0" });
    expect(r.alteracoes).toEqual([]);
    expect(r.invalidos).toEqual(["a", "b"]);
    expect(calcularAlteracoes(itens, { ...inalterados(), a: "" }).invalidos).toEqual(["a"]);
  });

  it("item sem preço pode ganhar um", () => {
    expect(calcularAlteracoes(itens, { ...inalterados(), c: "25,70" }).alteracoes).toEqual([
      { id: "c", preco: 25.7 },
    ]);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/components/produtos/valeria-precos-diff.test.ts`
Expected: FAIL (módulo não existe)

- [ ] **Step 3: Implementar o diff**

```ts
import {
  formatPrecoCatalogo,
  parsePrecoCatalogo,
  precoValido,
  type CatalogItem,
} from "@/lib/valeria-catalog";

export interface Alteracoes {
  alteracoes: { id: string; preco: number }[];
  invalidos: string[];
}

/** Texto do input ao abrir o modal: "28,70" (sem o "R$ "), ou "" sem preço. */
export function textoInicial(item: CatalogItem): string {
  return item.preco === null ? "" : formatPrecoCatalogo(item.preco).replace(/^R\$ /, "");
}

export function calcularAlteracoes(
  itens: CatalogItem[],
  textos: Record<string, string>,
): Alteracoes {
  const alteracoes: Alteracoes["alteracoes"] = [];
  const invalidos: string[] = [];
  for (const item of itens) {
    const texto = textos[item.id];
    if (texto === undefined) continue;
    if (texto.trim() === "" && item.preco === null) continue; // continua sem preço
    const preco = parsePrecoCatalogo(texto);
    if (preco === null || !precoValido(preco)) {
      invalidos.push(item.id);
      continue;
    }
    if (preco !== item.preco) alteracoes.push({ id: item.id, preco });
  }
  return { alteracoes, invalidos };
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/components/produtos/valeria-precos-diff.test.ts`
Expected: PASS

- [ ] **Step 5: Implementar o modal**

`frontend/src/components/produtos/valeria-precos-modal.tsx` — ponto de partida funcional; o refinamento visual via `frontend-design` não pode mudar o comportamento (carregar, editar, destacar alterado, bloquear inválido, salvar tudo num PATCH, manter edições no erro, Esc fecha).

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import type { CatalogItem } from "@/lib/valeria-catalog";
import { calcularAlteracoes, textoInicial } from "./valeria-precos-diff";

interface Props {
  onClose: () => void;
  onSaved: (quantidade: number) => void;
}

export function ValeriaPrecosModal({ onClose, onSaved }: Props) {
  const [itens, setItens] = useState<CatalogItem[]>([]);
  const [textos, setTextos] = useState<Record<string, string>>({});
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    fetch("/api/admin/valeria-catalog", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((body: { data: CatalogItem[] }) => {
        if (cancelado) return;
        setItens(body.data ?? []);
        setTextos(Object.fromEntries((body.data ?? []).map((i) => [i.id, textoInicial(i)])));
      })
      .catch(() => {
        if (!cancelado) setErro("Não foi possível carregar os preços da ValerIA.");
      })
      .finally(() => {
        if (!cancelado) setCarregando(false);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !salvando) onClose();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onClose, salvando]);

  const { alteracoes, invalidos } = useMemo(() => calcularAlteracoes(itens, textos), [itens, textos]);
  const alterados = useMemo(() => new Set(alteracoes.map((a) => a.id)), [alteracoes]);
  const setores = useMemo(() => {
    const grupos = new Map<string, CatalogItem[]>();
    for (const item of itens) grupos.set(item.sector, [...(grupos.get(item.sector) ?? []), item]);
    return [...grupos.entries()];
  }, [itens]);

  const podeSalvar = alteracoes.length > 0 && invalidos.length === 0 && !salvando;

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      const res = await fetch("/api/admin/valeria-catalog", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itens: alteracoes }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErro(body.error ?? "Não foi possível salvar os preços.");
        return;
      }
      onSaved(alteracoes.length);
      onClose();
    } catch {
      setErro("Não foi possível salvar os preços.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={() => !salvando && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="valeria-precos-titulo"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-[8px] border border-[#dedbd6] bg-white"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[#dedbd6] px-5 py-4">
          <h2 id="valeria-precos-titulo" className="text-[16px] font-semibold text-[#111111]">
            Preços da ValerIA
          </h2>
          <p className="mt-0.5 text-[12px] text-[#7b7b78]">
            Valores que a ValerIA oferece aos leads, por produto.
          </p>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {carregando ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-[6px] bg-[#dedbd6]/30" />
              ))}
            </div>
          ) : (
            setores.map(([setor, doSetor]) => (
              <section key={setor}>
                <h3 className="mb-2 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{setor}</h3>
                <ul className="divide-y divide-[#dedbd6]/60">
                  {doSetor.map((item) => {
                    const invalido = invalidos.includes(item.id);
                    const alterado = alterados.has(item.id);
                    return (
                      <li
                        key={item.id}
                        className={`flex items-center gap-3 py-2 ${alterado ? "bg-[#faf9f6]" : ""}`}
                      >
                        <span className="flex-1 truncate text-[13px] text-[#111111]" title={item.name}>
                          {item.name}
                        </span>
                        <label className="flex items-center gap-1 text-[13px] text-[#7b7b78]">
                          R$
                          <input
                            type="text"
                            inputMode="decimal"
                            aria-label={`Preço de ${item.name}`}
                            aria-invalid={invalido}
                            value={textos[item.id] ?? ""}
                            onChange={(e) => setTextos((t) => ({ ...t, [item.id]: e.target.value }))}
                            className={`w-24 rounded-[4px] border px-2 py-1 text-right text-[13px] text-[#111111] focus:outline-none ${
                              invalido
                                ? "border-red-500"
                                : alterado
                                  ? "border-[#111111] font-medium"
                                  : "border-[#dedbd6] focus:border-[#111111]"
                            }`}
                          />
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
          {erro && <p className="text-[13px] text-red-600">{erro}</p>}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[#dedbd6] px-5 py-3">
          <p className="text-[12px] text-[#7b7b78]">A ValerIA passa a usar os novos valores em até 1 minuto.</p>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              disabled={salvando}
              className="rounded-[4px] border border-[#dedbd6] px-3 py-1.5 text-[12px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40"
            >
              Cancelar
            </button>
            <button
              onClick={salvar}
              disabled={!podeSalvar}
              className="rounded-[4px] bg-[#111111] px-3 py-1.5 text-[12px] text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {salvando ? "Salvando…" : `Salvar (${alteracoes.length})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Botão em /produtos**

Em `frontend/src/app/(authenticated)/produtos/page.tsx`:

Imports (junto dos existentes):
```tsx
import { useCurrentRole } from "@/hooks/use-current-role";
import { ValeriaPrecosModal } from "@/components/produtos/valeria-precos-modal";
```

Dentro de `ProdutosPage`, logo após `const [page, setPage] = useState(1);`:
```tsx
  const { role } = useCurrentRole();
  const [precosAberto, setPrecosAberto] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  useEffect(() => {
    if (!aviso) return;
    const t = setTimeout(() => setAviso(null), 4000);
    return () => clearTimeout(t);
  }, [aviso]);
```

Substituir o bloco do cabeçalho:
```tsx
        <div>
          <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Produtos</h1>
          <p className="text-[13px] text-[#7b7b78] mt-0.5">Catálogo sincronizado do Bling</p>
        </div>
```
por:
```tsx
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Produtos</h1>
            <p className="text-[13px] text-[#7b7b78] mt-0.5">Catálogo sincronizado do Bling</p>
          </div>
          {role === "admin" && (
            <button
              onClick={() => setPrecosAberto(true)}
              className="px-3 py-2 text-[13px] bg-[#111111] text-white rounded-[4px] hover:bg-[#333333] transition-colors whitespace-nowrap"
            >
              Preços da ValerIA
            </button>
          )}
        </div>
        {aviso && <p className="text-[13px] text-[#1f9d57]">{aviso}</p>}
        {precosAberto && (
          <ValeriaPrecosModal
            onClose={() => setPrecosAberto(false)}
            onSaved={(n) => setAviso(`${n} ${n === 1 ? "preço atualizado" : "preços atualizados"} — a ValerIA usa em até 1 minuto.`)}
          />
        )}
```

Atualizar o comentário do topo do arquivo: a tabela do Bling continua somente leitura; o botão "Preços da ValerIA" edita a tabela `products`, que é outra coisa (o catálogo que a ValerIA oferta).

- [ ] **Step 7: Tipos, lint e testes**

Run: `npx vitest run src/components/produtos ; npx tsc --noEmit -p . 2>&1 | grep -iE "produtos|valeria-precos" ; npx eslint src/components/produtos "src/app/(authenticated)/produtos"`
Expected: testes PASS; nenhum erro nesses arquivos. Se o tsc acusar só a falta de `src/app/api/admin/valeria-catalog` (Task 2 em andamento), ignore — o modal só chama a rota por `fetch`.

- [ ] **Step 8: NÃO commitar** — reporte arquivos e saídas ao controlador.

---

### Task 4: Backend — TTL 60 s e fim do preço de exemplo (paralela)

**Files:**
- Modify: `backend/app/agent/catalog.py:28-31`
- Modify: `backend/app/agent/prompts/base.py:771,772,779,783,1081`
- Modify: `backend/app/agent/prompts/voice_card.py:52`
- Test: `backend/tests/test_valeria_precos_modal_2026_09_23.py`

Por quê: o preço agora é editado pelo CRM (`/produtos` → "Preços da ValerIA"); 5 min de cache era demais. E o exemplo `R$23,90` dos prompts vazava como preço real (auditoria 23/09/2026: 3 leads, último em 17/09) — a ValerIA não "segue o modal" enquanto o prompt tiver um preço de exemplo.

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Preços da ValerIA editáveis no CRM (23/09/2026).

O admin troca o preço em /produtos e a ValerIA tem que obedecer:
1. o catálogo em memória vence em 60 s (antes 300 s);
2. nenhum prompt carrega um preço de exemplo — o "R$23,90" dos exemplos de voz era
   copiado como preço real (3 leads até 17/09/2026), por cima do catálogo.
"""
from pathlib import Path

from app.agent import catalog

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "prompts"


def test_catalogo_vence_em_60s():
    assert catalog._CACHE_TTL_SECONDS == 60


def test_nenhum_prompt_tem_preco_de_exemplo_23_90():
    culpados = [
        str(p.relative_to(PROMPTS_DIR))
        for p in PROMPTS_DIR.rglob("*.py")
        if "23,90" in p.read_text(encoding="utf-8")
    ]
    assert culpados == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_valeria_precos_modal_2026_09_23.py -v`
Expected: FAIL nos dois (TTL é 300; `base.py` e `voice_card.py` contêm `23,90`)

- [ ] **Step 3: TTL**

Em `backend/app/agent/catalog.py`, trocar:
```python
# Cache em memória: {funnel_normalizado: (timestamp, markdown)}. TTL curto porque
# ops pode atualizar o CSV a qualquer momento; 5 min é um bom equilíbrio entre
# frescor e não martelar o banco a cada mensagem.
_CACHE_TTL_SECONDS = 300
```
por:
```python
# Cache em memória: {funnel_normalizado: (timestamp, markdown)}. O admin edita os
# preços no CRM (/produtos -> "Preços da ValerIA") e a tela promete que a ValerIA
# obedece em até 1 minuto — por isso 60 s. Custo: uma leitura de ~32 linhas por
# minuto por processo.
_CACHE_TTL_SECONDS = 60
```

- [ ] **Step 4: Prompts**

Use a convenção que o `prompts/valeria_inbound/private_label.py:137` já usa (`R$X`). Trocas exatas:

`backend/app/agent/prompts/base.py`
- linha 771: `Correto: R$23,90` → `Correto: R$X`
- linha 772: `Errado: r$23,90` → `Errado: r$X`
- linha 779: `- r$23,90 a unidade, ja incluso embalagem` → `- r$X a unidade, ja incluso embalagem`
- linha 783: `"o 250g sai R$23,90 a unidade, ja com embalagem e silk da sua logo"` → `"o 250g sai R$X a unidade, ja com embalagem e silk da sua logo"`
- linha 1081: `...fica por volta de R$23,90 a unidade...` → `...fica por volta de R$X a unidade...`. Logo depois dessa linha de exemplo (dentro do mesmo exemplo), NÃO acrescente texto novo. Se o bloco de exemplos tiver um cabeçalho explicando que são exemplos, verifique que ele deixa claro que o valor real vem do `<catalogo_de_produtos>`; se não houver, acrescente UMA linha antes do exemplo: `(R$X = o valor exato do <catalogo_de_produtos> para o item pedido)`.

`backend/app/agent/prompts/voice_card.py`
- linha 52: `- Valores monetarios sempre com R$ maiusculo (R$23,90 — nunca r$).` → `- Valores monetarios sempre com R$ maiusculo (R$X — nunca r$).`

Confira com `grep -rn "23,90" app/agent/prompts --include=*.py` → nenhuma saída.

- [ ] **Step 5: Rodar o teste novo e as suítes vizinhas**

Run: `python -m pytest tests/test_valeria_precos_modal_2026_09_23.py tests/test_catalog.py tests/test_catalog_stale_fallback_2026_07_08.py tests/test_base_prompt.py tests/test_prompt_cache_2026_07_27.py tests/test_prompt_dieta_preco_2026_07_08.py tests/test_outbound_prompt_separation.py tests/test_humanizer.py tests/test_splitter_bubbles.py -q`
Expected: PASS. Se algum teste existente fixar o texto antigo (`23,90`) do PROMPT, atualize a asserção para `R$X` e reporte qual foi. Testes do humanizador/splitter que usam `23,90` como ENTRADA de texto não são prompt — não mexa.

- [ ] **Step 6: Suíte do agente**

Run: `python -m pytest tests -q -x -k "prompt or catalog or orcamento or pricing"`
Expected: PASS (reporte a contagem).

- [ ] **Step 7: NÃO commitar** — reporte arquivos e saídas ao controlador.

---

### Task 5: Integração (controlador, depois das 2-4)

- [ ] **Step 1:** Revisar o diff de cada task contra o spec (spec compliance) e a qualidade (code review).
- [ ] **Step 2:** Rodar tudo junto:
  - `cd frontend && npx vitest run src/lib/valeria-catalog.test.ts src/app/api/admin/valeria-catalog src/components/produtos src/lib/auth/proxy-coverage.test.ts`
  - `cd frontend && npx tsc --noEmit -p .` (comparar com a baseline de erros pré-existentes)
  - `cd backend && python -m pytest tests -q`
- [ ] **Step 3:** Commits separados por task, só com os arquivos da task (`git add <arquivos>`; nunca `git add -A`):
  - `feat(produtos): rota admin de precos da ValerIA`
  - `feat(produtos): modal Precos da ValerIA em /produtos`
  - `fix(valeria): catalogo em 60s e fim do preco de exemplo R$23,90 no prompt`
- [ ] **Step 4:** Validação no navegador fica com o usuário: o dev local escreve no Supabase de PRODUÇÃO, então salvar no modal em dev muda o preço real. Não salvar preço de teste.
- [ ] **Step 5:** Push só com autorização do usuário (`git pull origin master` → `git push origin feat/valeria-precos-modal:master`).
