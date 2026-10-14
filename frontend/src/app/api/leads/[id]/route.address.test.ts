/**
 * PATCH /api/leads/[id] com campos de endereço: normaliza CEP/UF, regrava o
 * texto legado `leads.endereco` formatado e, com o endereço completo, pede ao
 * backend que atualize o(s) contato(s) vinculado(s) no Bling (cartão b3788533).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { PATCH } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; metodo: string; args: unknown[] };

/** Builder encadeável por `from()`; resultados saem da fila na ordem dos `from()`. */
function instalar(respostas: unknown[]) {
  const chamadas: Chamada[] = [];
  let n = 0;
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: () => {
      const idx = n++;
      const r = respostas[idx];
      const resultado =
        r instanceof Error ? { data: null, error: { message: r.message } } : { data: r ?? null, error: null };
      const builder: Record<string, unknown> = {};
      for (const metodo of ["select", "in", "neq", "eq", "order", "limit", "insert", "update"]) {
        builder[metodo] = (...args: unknown[]) => {
          chamadas.push({ from: idx, metodo, args });
          return builder;
        };
      }
      for (const metodo of ["single", "maybeSingle"]) {
        builder[metodo] = () => {
          chamadas.push({ from: idx, metodo, args: [] });
          return Promise.resolve(resultado);
        };
      }
      builder.then = (ok: (r: unknown) => unknown) => Promise.resolve(resultado).then(ok);
      return builder;
    },
  } as never);
  return chamadas;
}

const patch = (id: string, body: unknown) =>
  PATCH(
    new NextRequest(`http://localhost/api/leads/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
    { params: Promise.resolve({ id }) },
  );

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const ATUAL = { stage: "secretaria", phone: "5534999990000" };
const ENDERECO = {
  cep: "38400-100",
  logradouro: "Av. Rondon Pacheco",
  numero: "123",
  complemento: "",
  bairro: "Centro",
  municipio: "Uberlândia",
  uf: "mg",
};
/** O lead como o banco devolve depois do update (CEP/UF já normalizados). */
const GRAVADO = {
  id: "l2",
  stage: "secretaria",
  endereco: null,
  ...ENDERECO,
  cep: "38400100",
  uf: "MG",
};
const FORMATADO = "Av. Rondon Pacheco, 123 - Centro - Uberlândia/MG 38400-100";

const chamadasAoBling = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/bling/contacts/address"));

describe("PATCH /api/leads/[id] — endereço", () => {
  it("body sem campo de endereço não chama o backend nem devolve bling_endereco", async () => {
    const chamadas = instalar([ATUAL, { id: "l2", name: "X" }]);

    const res = await patch("l2", { name: "X" });

    expect(res.status).toBe(200);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await res.json()).toEqual({ id: "l2", name: "X" });
    expect(chamadas.filter((c) => c.metodo === "update")).toHaveLength(1);
  });

  it("normaliza CEP e UF antes de gravar", async () => {
    const chamadas = instalar([ATUAL, { ...GRAVADO }, { id: "l2" }]);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ status: "updated", contas: [] })));

    await patch("l2", ENDERECO);

    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toMatchObject({
      cep: "38400100",
      uf: "MG",
    });
  });

  it("endereço completo regrava o texto formatado e atualiza o Bling", async () => {
    const chamadas = instalar([ATUAL, { ...GRAVADO }, { id: "l2" }]);
    const bling = { status: "updated", contas: [{ account: "default", contact_id: 7, status: "updated" }] };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(bling)));

    const res = await patch("l2", ENDERECO);

    expect(res.status).toBe(200);
    const updates = chamadas.filter((c) => c.metodo === "update");
    expect(updates[1]?.args[0]).toEqual({ endereco: FORMATADO });

    const blingCalls = chamadasAoBling();
    expect(blingCalls).toHaveLength(1);
    const [, init] = blingCalls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ lead_id: "l2" });

    const json = await res.json();
    expect(json.endereco).toBe(FORMATADO);
    expect(json.bling_endereco).toEqual(bling);
  });

  it("texto legado já igual ao formatado não é regravado", async () => {
    const chamadas = instalar([ATUAL, { ...GRAVADO, endereco: FORMATADO }]);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ status: "updated", contas: [] })));

    await patch("l2", ENDERECO);

    expect(chamadas.filter((c) => c.metodo === "update")).toHaveLength(1);
  });

  it("endereço incompleto não chama o Bling e devolve status incomplete", async () => {
    instalar([ATUAL, { ...GRAVADO, numero: "" }, { id: "l2" }]);

    const res = await patch("l2", { ...ENDERECO, numero: "" });

    expect(res.status).toBe(200);
    expect(chamadasAoBling()).toHaveLength(0);
    expect((await res.json()).bling_endereco).toEqual({ status: "incomplete" });
  });

  it("backend fora do ar: PATCH continua 200 e devolve status error", async () => {
    instalar([ATUAL, { ...GRAVADO }, { id: "l2" }]);
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const res = await patch("l2", ENDERECO);

    expect(res.status).toBe(200);
    expect((await res.json()).bling_endereco).toEqual({
      status: "error",
      message: "Bling indisponível — tente salvar de novo",
    });
  });

  it("backend responde erro HTTP: status error", async () => {
    instalar([ATUAL, { ...GRAVADO }, { id: "l2" }]);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ error: "lead_not_found" }), { status: 404 }));

    const res = await patch("l2", ENDERECO);

    expect(res.status).toBe(200);
    expect((await res.json()).bling_endereco.status).toBe("error");
  });
});
