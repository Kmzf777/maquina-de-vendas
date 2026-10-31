import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { leadTemConversa } from "./lead-has-conversation";

/** Dublê do encadeamento from().select().eq().neq() que grava os filtros. */
function fakeSb(resultado: { count: number | null; error: { message: string } | null } | Error) {
  const filtros: string[] = [];
  const q = {
    select: vi.fn(() => q),
    eq: vi.fn((c: string, v: string) => { filtros.push(`eq ${c}=${v}`); return q; }),
    neq: vi.fn(async (c: string, v: string) => {
      filtros.push(`neq ${c}=${v}`);
      if (resultado instanceof Error) throw resultado;
      return resultado;
    }),
  };
  const sb = { from: vi.fn(() => q) } as unknown as SupabaseClient;
  return { sb, filtros, q };
}

describe("leadTemConversa", () => {
  it("conta conversas do lead que não estão bloqueadas", async () => {
    const { sb, filtros, q } = fakeSb({ count: 2, error: null });
    expect(await leadTemConversa(sb, "L1")).toBe(true);
    expect(sb.from).toHaveBeenCalledWith("conversations");
    expect(q.select).toHaveBeenCalledWith("id", { count: "exact", head: true });
    expect(filtros).toEqual(["eq lead_id=L1", "neq status=blocked"]);
  });

  it("zero conversas → false", async () => {
    expect(await leadTemConversa(fakeSb({ count: 0, error: null }).sb, "L1")).toBe(false);
  });

  it("erro da consulta → null (desconhecido, o botão fica habilitado)", async () => {
    expect(await leadTemConversa(fakeSb({ count: null, error: { message: "x" } }).sb, "L1")).toBeNull();
    expect(await leadTemConversa(fakeSb(new Error("rede")).sb, "L1")).toBeNull();
  });
});
