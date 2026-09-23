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
