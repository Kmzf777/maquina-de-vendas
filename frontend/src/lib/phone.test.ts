import { describe, it, expect } from "vitest";
import { normalizePhoneBR, phoneVariantsBR } from "@/lib/phone";

describe("normalizePhoneBR", () => {
  it("injects the 9th digit for 12-digit BR mobile numbers", () => {
    expect(normalizePhoneBR("553284316333")).toBe("5532984316333");
  });
  it("leaves a correct 13-digit number unchanged", () => {
    expect(normalizePhoneBR("5532984316333")).toBe("5532984316333");
  });
  it("prepends 55 to an 11-digit number (DDD + 9 digits)", () => {
    expect(normalizePhoneBR("32984316333")).toBe("5532984316333");
  });
  it("prepends 55 and injects 9 for a 10-digit number (DDD + 8 digits)", () => {
    expect(normalizePhoneBR("3284316333")).toBe("5532984316333");
  });
  it("strips formatting characters", () => {
    expect(normalizePhoneBR("(32) 98431-6333")).toBe("5532984316333");
  });
  it("drops a leading 0", () => {
    expect(normalizePhoneBR("032984316333")).toBe("5532984316333");
  });
  it("returns null for too-short input", () => {
    expect(normalizePhoneBR("123")).toBeNull();
  });
  it("returns null for empty input", () => {
    expect(normalizePhoneBR("")).toBeNull();
  });
  it("returns null for a 12/13-digit number that does not start with 55", () => {
    expect(normalizePhoneBR("123456789012")).toBeNull();
  });
});

describe("phoneVariantsBR", () => {
  it("lista o canônico e as formas antigas (sem 9, sem 55, sem os dois)", () => {
    expect(phoneVariantsBR("5549999170363")).toEqual([
      "5549999170363",
      "554999170363",
      "49999170363",
      "4999170363",
    ]);
  });
  it("número fixo com 9 injetado também acha a forma de 12 dígitos", () => {
    expect(phoneVariantsBR("5549934415750")).toEqual([
      "5549934415750",
      "554934415750",
      "49934415750",
      "4934415750",
    ]);
  });
  it("valor que não é canônico de 13 dígitos devolve só ele mesmo", () => {
    expect(phoneVariantsBR("123")).toEqual(["123"]);
  });
});
