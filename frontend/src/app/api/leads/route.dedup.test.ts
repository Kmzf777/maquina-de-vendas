/**
 * POST /api/leads — o telefone é normalizado (`normalizePhoneBR`) e, antes de
 * criar, procura-se lead existente em qualquer formato antigo do número
 * (cartão b747da43: leads duplicados por `4999170363` x `5549999170363`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; metodo: string; args: unknown[] };

/**
 * Cada `from()` ganha um builder encadeável; o resultado (await / single)
 * vem da fila `respostas`, na ordem das chamadas de `from()`.
 */
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

const postar = (body: unknown) =>
  POST(
    new NextRequest("http://localhost/api/leads", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
  );

afterEach(() => vi.clearAllMocks());

describe("POST /api/leads — dedupe por telefone", () => {
  it("número já gravado em formato antigo devolve 409 com o lead existente, sem insert", async () => {
    const existente = { id: "l1", name: "Douglas Schutz", phone: "4999170363" };
    const chamadas = instalar([[existente]]);

    const res = await postar({ phone: "(49) 9917-0363", name: "Douglas" });

    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({
      error: "Lead com este telefone já existe: Douglas Schutz",
      lead: existente,
    });
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
    expect(chamadas.find((c) => c.metodo === "in")?.args).toEqual([
      "phone",
      ["5549999170363", "554999170363", "49999170363", "4999170363"],
    ]);
  });

  it("telefone que não normaliza devolve 422", async () => {
    const chamadas = instalar([]);
    const res = await postar({ phone: "123" });
    expect(res.status).toBe(422);
    expect((await res.json()).error).toContain("Telefone inválido");
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);

    // 8 dígitos passava na validação antiga (8–15) e virava lead lixo.
    const curto = await postar({ phone: "9917-0363" });
    expect(curto.status).toBe(422);
    expect((await curto.json()).error).toContain("Telefone inválido");
  });

  it("sem existente cria com o telefone canônico e respeita human_control", async () => {
    const criado = { id: "novo", phone: "5549999170363" };
    const chamadas = instalar([[], criado]);

    const res = await postar({ phone: "49999170363", human_control: true, stage: "secretaria" });

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual(criado);
    const insert = chamadas.find((c) => c.metodo === "insert");
    expect(insert?.args[0]).toMatchObject({
      phone: "5549999170363",
      human_control: true,
      // b67f1c6b: "secretaria" deixou de ser fase; vira triagem
      stage: "triagem",
      origem_cadastro: "manual",
    });
  });

  it("phone que não é texto devolve 422, não 500", async () => {
    const chamadas = instalar([]);
    const res = await postar({ phone: 5549999170363 });
    expect(res.status).toBe(422);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });

  it("erro na busca do existente devolve 500 sem insert", async () => {
    const chamadas = instalar([new Error("boom")]);
    const res = await postar({ phone: "49999170363" });
    expect(res.status).toBe(500);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });
});

describe("POST /api/leads — origem e fase (b67f1c6b)", () => {
  it("sem stage: fase triagem e origem_cadastro manual", async () => {
    const chamadas = instalar([[], { id: "novo" }]);
    const res = await postar({ phone: "49999170363" });
    expect(res.status).toBe(201);
    const insert = chamadas.find((c) => c.metodo === "insert");
    expect(insert?.args[0]).toMatchObject({ stage: "triagem", origem_cadastro: "manual" });
    expect(insert?.args[0]).not.toHaveProperty("segmento");
  });

  it("segmento no stage (kanban de qualificação) vira segmento + fase qualificando", async () => {
    const chamadas = instalar([[], { id: "novo" }]);
    await postar({ phone: "49999170363", stage: "private_label" });
    const insert = chamadas.find((c) => c.metodo === "insert");
    expect(insert?.args[0]).toMatchObject({
      stage: "qualificando",
      segmento: "private_label",
      origem_cadastro: "manual",
    });
  });

  it("fase válida passa como veio", async () => {
    const chamadas = instalar([[], { id: "novo" }]);
    await postar({ phone: "49999170363", stage: "novo" });
    expect(chamadas.find((c) => c.metodo === "insert")?.args[0]).toMatchObject({ stage: "novo" });
  });

  it("stage fora de fase e de segmento devolve 422 sem insert", async () => {
    const chamadas = instalar([[]]);
    const res = await postar({ phone: "49999170363", stage: "xyz" });
    expect(res.status).toBe(422);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });
});
