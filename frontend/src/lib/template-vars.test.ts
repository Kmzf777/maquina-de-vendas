import { describe, expect, it } from "vitest";
import { autoSuggestToken, buildTemplateVarDefaults } from "./template-vars";
import type { TemplateHeader, TemplateParam } from "@/lib/template-parser";

// Fixture minima no formato que /api/channels/[id]/templates devolve.
function tpl(over: {
  params?: TemplateParam[];
  paramsType?: "positional" | "named" | "none";
  header?: TemplateHeader | null;
}) {
  return {
    params: over.params ?? [],
    paramsType: over.paramsType ?? "none",
    header: over.header ?? null,
  };
}

describe("buildTemplateVarDefaults — chaves reservadas", () => {
  // REGRESSAO: o Disparo Rapido montava as variaveis sem __params_type__.
  // backend/app/broadcast/worker.py:278 faz .get("__params_type__", "named"),
  // entao um template POSICIONAL virava payload nomeado com parameter_name="1",
  // que a Meta rejeita — o disparo nunca chegava no cliente.
  it("grava __params_type__=positional para template posicional", () => {
    const out = buildTemplateVarDefaults(
      tpl({
        paramsType: "positional",
        params: [
          { index: 1, paramName: "1", example: "Rafael" },
          { index: 2, paramName: "2", example: "Cafe Canastra" },
        ],
      })
    );
    expect(out["__params_type__"]).toBe("positional");
  });

  it("grava __params_type__=named para template nomeado", () => {
    const out = buildTemplateVarDefaults(
      tpl({
        paramsType: "named",
        params: [{ index: 1, paramName: "primeiro_nome", example: "Rafael" }],
      })
    );
    expect(out["__params_type__"]).toBe("named");
  });

  it("nao grava __params_type__ quando o template nao tem parametros", () => {
    const out = buildTemplateVarDefaults(tpl({ paramsType: "none" }));
    expect(out).not.toHaveProperty("__params_type__");
  });

  it("grava __header_type__ quando o template tem header", () => {
    const out = buildTemplateVarDefaults(tpl({ header: { type: "IMAGE" } }));
    expect(out["__header_type__"]).toBe("IMAGE");
  });

  it("nao grava __header_type__ quando nao ha header", () => {
    const out = buildTemplateVarDefaults(tpl({ header: null }));
    expect(out).not.toHaveProperty("__header_type__");
  });
});

describe("buildTemplateVarDefaults — variaveis do corpo", () => {
  it("pre-preenche cada parametro com o token sugerido pelo exemplo", () => {
    const out = buildTemplateVarDefaults(
      tpl({
        paramsType: "named",
        params: [
          { index: 1, paramName: "primeiro_nome", example: "Rafael" },
          { index: 2, paramName: "nome_completo", example: "Rafael Reis Silva" },
          { index: 3, paramName: "fone", example: "34988861441" },
        ],
      })
    );
    expect(out["primeiro_nome"]).toBe("{{primeiro_nome}}");
    expect(out["nome_completo"]).toBe("{{nome_completo}}");
    expect(out["fone"]).toBe("{{telefone}}");
  });

  it("deixa vazio o parametro sem exemplo, para o operador preencher", () => {
    const out = buildTemplateVarDefaults(
      tpl({
        paramsType: "positional",
        params: [{ index: 1, paramName: "1", example: "" }],
      })
    );
    expect(out["1"]).toBe("");
  });

  // As chaves reservadas nao podem colidir com nome de variavel do corpo.
  it("mantem parametros e chaves reservadas lado a lado", () => {
    const out = buildTemplateVarDefaults(
      tpl({
        paramsType: "positional",
        header: { type: "DOCUMENT" },
        params: [{ index: 1, paramName: "1", example: "Rafael" }],
      })
    );
    expect(out).toEqual({
      __params_type__: "positional",
      __header_type__: "DOCUMENT",
      "1": "{{primeiro_nome}}",
    });
  });
});

describe("autoSuggestToken", () => {
  it("reconhece telefone", () => {
    expect(autoSuggestToken("34988861441")).toBe("{{telefone}}");
    expect(autoSuggestToken("(34) 98886-1441")).toBe("{{telefone}}");
  });

  it("reconhece primeiro nome e nome completo", () => {
    expect(autoSuggestToken("Rafael")).toBe("{{primeiro_nome}}");
    expect(autoSuggestToken("Rafael Reis Silva")).toBe("{{nome_completo}}");
  });

  it("nao sugere nada para texto livre", () => {
    expect(autoSuggestToken("")).toBe("");
    expect(autoSuggestToken("reposicao para cafes especiais do mes")).toBe("");
  });
});
