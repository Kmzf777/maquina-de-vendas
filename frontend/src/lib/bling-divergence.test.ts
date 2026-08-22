import { describe, it, expect } from "vitest";
import { divergenceFrom, shouldMarkDivergent } from "@/lib/bling-divergence";

describe("shouldMarkDivergent", () => {
  it("recusa de validacao marca divergencia", () => {
    expect(shouldMarkDivergent(422)).toBe(true);
  });

  // O teste que separa negocio de infraestrutura: erro transitorio e
  // retentativa, nao decisao de divergir.
  it("erro transitorio NAO marca divergencia", () => {
    expect(shouldMarkDivergent(202)).toBe(false);
    expect(shouldMarkDivergent(503)).toBe(false);
  });

  it("sucesso nao marca", () => {
    expect(shouldMarkDivergent(200)).toBe(false);
  });
});

describe("divergenceFrom", () => {
  it("registra so os campos que mudaram", () => {
    const d = divergenceFrom(
      { value: 400, notes: "a" },
      { value: 500, notes: "a" },
      "2026-08-21T10:00:00Z"
    );
    expect(d.fields).toEqual(["value"]);
    expect(d.bling).toEqual({ value: 400 });
    expect(d.crm).toEqual({ value: 500 });
    expect(d.at).toBe("2026-08-21T10:00:00Z");
  });

  it("sem mudanca, sem divergencia", () => {
    expect(divergenceFrom({ value: 1 }, { value: 1 }, "x").fields).toEqual([]);
  });
});
