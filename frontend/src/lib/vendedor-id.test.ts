import { describe, expect, it } from "vitest";
import { validarVendedorId } from "./vendedor-id";

const ID = "3f6c2b1a-9d4e-4c7a-8b2f-1a2b3c4d5e6f";

describe("validarVendedorId (deals.assigned_to é uuid FK de vendedores)", () => {
  it("aceita uuid e normaliza para minúsculas", () => {
    expect(validarVendedorId(ID)).toEqual({ ok: true, value: ID });
    expect(validarVendedorId(ID.toUpperCase())).toEqual({ ok: true, value: ID });
  });

  it("vazio, null e undefined viram 'sem vendedor'", () => {
    for (const v of ["", "  ", null, undefined]) {
      expect(validarVendedorId(v)).toEqual({ ok: true, value: null });
    }
  });

  it("recusa nome digitado e outros tipos", () => {
    for (const v of ["João Brás", "joao@cafecanastra.com", "123", 42, {}]) {
      const r = validarVendedorId(v);
      expect(r.ok).toBe(false);
    }
  });
});
