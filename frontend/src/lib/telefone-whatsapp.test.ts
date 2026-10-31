import { describe, expect, it } from "vitest";
import { telefoneWhatsapp } from "./telefone-whatsapp";

describe("telefoneWhatsapp", () => {
  it("aceita número com DDI, com ou sem o 9", () => {
    expect(telefoneWhatsapp("5534988861441")).toBe("5534988861441");
    expect(telefoneWhatsapp("554991505316")).toBe("554991505316");
  });
  it("limpa máscara", () => {
    expect(telefoneWhatsapp("+55 (34) 98886-1441")).toBe("5534988861441");
  });
  it("recusa placeholder do Bling, vazio e curto/longo demais", () => {
    expect(telefoneWhatsapp("bling-18479369687")).toBeNull();
    expect(telefoneWhatsapp("")).toBeNull();
    expect(telefoneWhatsapp(null)).toBeNull();
    expect(telefoneWhatsapp("123456789")).toBeNull();
    expect(telefoneWhatsapp("55349888614411")).toBeNull();
  });
});
