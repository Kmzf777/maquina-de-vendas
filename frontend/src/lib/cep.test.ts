import { describe, expect, it, vi } from "vitest";
import { blankContactForm } from "@/lib/bling-contact-form";
import { buscarCep, preencherEndereco } from "@/lib/cep";

const VIACEP_FRUTAL = {
  cep: "38200-000",
  logradouro: "Avenida Brasil",
  complemento: "",
  bairro: "Centro",
  localidade: "Frutal",
  uf: "MG",
  ibge: "3127107",
};

const ok = (corpo: unknown) =>
  vi.fn(async () => ({ ok: true, status: 200, json: async () => corpo }) as Response);

describe("buscarCep", () => {
  it("consulta o ViaCEP só com dígitos e devolve o endereço", async () => {
    const f = ok(VIACEP_FRUTAL);
    const out = await buscarCep("38.200-000", f as unknown as typeof fetch);
    expect(f).toHaveBeenCalledTimes(1);
    expect(String((f.mock.calls[0] as unknown[])[0])).toBe(
      "https://viacep.com.br/ws/38200000/json/",
    );
    expect(out).toEqual({
      logradouro: "Avenida Brasil",
      bairro: "Centro",
      municipio: "Frutal",
      uf: "MG",
    });
  });

  it("município vem com o acento do IBGE", async () => {
    const out = await buscarCep(
      "01001000",
      ok({ ...VIACEP_FRUTAL, localidade: "São Paulo", uf: "SP" }) as unknown as typeof fetch,
    );
    expect(out?.municipio).toBe("São Paulo");
  });

  it("CEP sem 8 dígitos nem consulta", async () => {
    const f = ok(VIACEP_FRUTAL);
    expect(await buscarCep("3820000", f as unknown as typeof fetch)).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });

  it("erro: true (booleano ou texto) vira null", async () => {
    expect(await buscarCep("99999999", ok({ erro: true }) as unknown as typeof fetch)).toBeNull();
    expect(await buscarCep("99999999", ok({ erro: "true" }) as unknown as typeof fetch)).toBeNull();
  });

  it("HTTP de erro, rede caída ou JSON quebrado viram null", async () => {
    const http400 = vi.fn(async () => ({ ok: false, status: 400, json: async () => ({}) }));
    expect(await buscarCep("38200000", http400 as unknown as typeof fetch)).toBeNull();
    const caiu = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(await buscarCep("38200000", caiu as unknown as typeof fetch)).toBeNull();
    const quebrado = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("x");
      },
    }));
    expect(await buscarCep("38200000", quebrado as unknown as typeof fetch)).toBeNull();
  });

  it("timeout aborta a consulta e devolve null", async () => {
    vi.useFakeTimers();
    try {
      const pendurado = vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_res, rej) => {
            init?.signal?.addEventListener("abort", () => rej(new Error("aborted")));
          }),
      );
      const p = buscarCep("38200000", pendurado as unknown as typeof fetch, 4000);
      await vi.advanceTimersByTimeAsync(4000);
      expect(await p).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("preencherEndereco", () => {
  const achado = { logradouro: "Avenida Brasil", bairro: "Centro", municipio: "Frutal", uf: "MG" };

  it("preenche os campos vazios", () => {
    const out = preencherEndereco(blankContactForm({ cep: "38200000", numero: "10" }), achado);
    expect(out).toMatchObject({
      cep: "38200000",
      numero: "10",
      logradouro: "Avenida Brasil",
      bairro: "Centro",
      municipio: "Frutal",
      uf: "MG",
    });
  });

  it("não sobrescreve o que o vendedor já digitou", () => {
    const out = preencherEndereco(
      blankContactForm({ logradouro: "Rua do Cliente", municipio: "Frutal (MG)" }),
      achado,
    );
    expect(out.logradouro).toBe("Rua do Cliente");
    expect(out.municipio).toBe("Frutal (MG)");
    expect(out.bairro).toBe("Centro");
    expect(out.uf).toBe("MG");
  });

  it("campo vazio na resposta não apaga nada (CEP geral de cidade)", () => {
    const out = preencherEndereco(blankContactForm({ bairro: "Jardim" }), {
      ...achado,
      logradouro: "",
      bairro: "",
    });
    expect(out.logradouro).toBe("");
    expect(out.bairro).toBe("Jardim");
  });
});
