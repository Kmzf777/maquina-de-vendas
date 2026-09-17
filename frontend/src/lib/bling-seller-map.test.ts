import { describe, expect, it } from "vitest";
import { comVinculo, indexarVinculos, vinculoDe } from "./bling-seller-map";

describe("indexarVinculos", () => {
  it("guarda um vinculo por conta para o MESMO e-mail", () => {
    const mapa = indexarVinculos([
      { user_email: "joao@x.com", account: "default", bling_seller_id: 111 },
      { user_email: "joao@x.com", account: "secundaria", bling_seller_id: 222 },
    ]);

    expect(vinculoDe(mapa, "default", "joao@x.com")).toBe(111);
    expect(vinculoDe(mapa, "secundaria", "joao@x.com")).toBe(222);
  });
});

describe("comVinculo", () => {
  it("desvincular numa conta NAO mexe no vinculo da outra", () => {
    const mapa = indexarVinculos([
      { user_email: "joao@x.com", account: "default", bling_seller_id: 111 },
      { user_email: "joao@x.com", account: "secundaria", bling_seller_id: 222 },
    ]);

    const depois = comVinculo(mapa, "secundaria", "joao@x.com", null);

    expect(vinculoDe(depois, "secundaria", "joao@x.com")).toBeNull();
    expect(vinculoDe(depois, "default", "joao@x.com")).toBe(111);
  });
});
