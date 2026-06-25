import { describe, it, expect } from "vitest";
import { resolveSearchChannelScope } from "./message-search";

describe("resolveSearchChannelScope", () => {
  it("admin sem channel_id => null (sem restrição)", () => {
    expect(resolveSearchChannelScope(null, null)).toEqual({ kind: "all" });
  });
  it("admin com channel_id => restringe a esse canal", () => {
    expect(resolveSearchChannelScope(null, "ch1")).toEqual({ kind: "ids", ids: ["ch1"] });
  });
  it("vendedor sem channel_id => seus canais", () => {
    expect(resolveSearchChannelScope(["a", "b"], null)).toEqual({ kind: "ids", ids: ["a", "b"] });
  });
  it("vendedor com channel_id permitido => só esse", () => {
    expect(resolveSearchChannelScope(["a", "b"], "a")).toEqual({ kind: "ids", ids: ["a"] });
  });
  it("vendedor com channel_id NÃO permitido => vazio (bloqueia)", () => {
    expect(resolveSearchChannelScope(["a", "b"], "c")).toEqual({ kind: "empty" });
  });
  it("vendedor sem canais => vazio", () => {
    expect(resolveSearchChannelScope([], null)).toEqual({ kind: "empty" });
  });
});
