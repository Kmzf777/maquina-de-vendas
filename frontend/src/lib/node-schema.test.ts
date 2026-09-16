import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  NODE_SCHEMA_URL,
  fetchNodeSchema,
  findNodeType,
  fieldsOf,
  fixedValues,
  schemaDefaults,
  paletteTypes,
  getCachedNodeSchema,
  primeNodeSchema,
  ensureNodeSchema,
  subscribeNodeSchema,
} from "./node-schema";
import { NODE_SCHEMA_FIXTURE } from "./node-schema.fixture";

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  primeNodeSchema(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  primeNodeSchema(null);
});

describe("fetchNodeSchema", () => {
  it("busca o endpoint do contrato e tipa a resposta", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse(NODE_SCHEMA_FIXTURE));
    vi.stubGlobal("fetch", fetchMock);

    const schema = await fetchNodeSchema();

    expect(fetchMock).toHaveBeenCalledWith(NODE_SCHEMA_URL);
    expect(NODE_SCHEMA_URL).toBe("/api/campaigns/node-schema");
    expect(schema.tipos.length).toBe(NODE_SCHEMA_FIXTURE.tipos.length);
    expect(schema.valores_fixos.segmento_lead).toContainEqual(["atacado", "Atacado"]);
  });

  it("resposta com forma estranha não derruba a tela — vira schema vazio", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse({ lixo: 1 })));
    const schema = await fetchNodeSchema();
    expect(schema.tipos).toEqual([]);
    expect(schema.valores_fixos).toEqual({});
  });

  it("status ruim vira erro (quem chama decide degradar)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) } as Response));
    await expect(fetchNodeSchema()).rejects.toThrow(/500/);
  });
});

describe("helpers de leitura do schema", () => {
  const schema = NODE_SCHEMA_FIXTURE;

  it("acha o tipo por (tipo, subtipo)", () => {
    expect(findNodeType(schema, "trigger", "stage_stagnation")?.rotulo).toBe("Parado no segmento");
    expect(findNodeType(schema, "action", "create_deal")?.rotulo).toBe("Criar card");
  });

  it("subtipo vazio e null são o mesmo nó para send/wait/end", () => {
    expect(findNodeType(schema, "send", "")?.rotulo).toBe("Enviar template");
    expect(findNodeType(schema, "send", null)?.rotulo).toBe("Enviar template");
    expect(findNodeType(schema, "wait", "")?.campos.map(c => c.chave)).toEqual([
      "days", "hours", "send_start_hour", "send_end_hour", "skip_weekends",
    ]);
  });

  it("tipo desconhecido devolve undefined e lista de campos vazia", () => {
    expect(findNodeType(schema, "trigger", "inventado")).toBeUndefined();
    expect(fieldsOf(schema, "trigger", "inventado")).toEqual([]);
  });

  it("mesma CHAVE, vocabulários diferentes — é o bug que o registro existe para matar", () => {
    const leadStage = fieldsOf(schema, "trigger", "stage_stagnation").find(c => c.chave === "stage_filter");
    const dealStage = fieldsOf(schema, "trigger", "deal_stage_enter").find(c => c.chave === "stage_filter");
    expect(leadStage?.vocab).toBe("segmento_lead");
    expect(dealStage?.vocab).toBe("etapa_key");
  });

  it("fixedValues devolve o vocabulário fechado, e [] para vocabulário aberto", () => {
    expect(fixedValues(schema, "politica_resposta").map(v => v[0])).toEqual(["pause", "cancel", "reset"]);
    expect(fixedValues(schema, "etapa_id")).toEqual([]);
  });

  it("paletteTypes filtra por na_paleta e, opcionalmente, por tipo", () => {
    expect(paletteTypes(schema, "condition")).toHaveLength(9);
    expect(paletteTypes(schema, "trigger")).toHaveLength(12);
    expect(paletteTypes(schema).length).toBe(schema.tipos.length);
  });
});

describe("schemaDefaults", () => {
  const schema = NODE_SCHEMA_FIXTURE;

  it("devolve só os defaults DECLARADOS — `null` significa ausente, e ausente tem sentido", () => {
    // `on_reply` do nó de envio é o caso crítico: o motor dá precedência ao NÓ sobre
    // o GATILHO (`_apply_reply_policy`), então gravar "pause" aqui sequestraria em
    // silêncio um gatilho com on_reply='reset'.
    expect(schemaDefaults(schema, "send", null)).toEqual({ template_language: "pt_BR" });
    expect(schemaDefaults(schema, "send_text", null)).toEqual({});
    expect(schemaDefaults(schema, "wait", null)).toEqual({ days: 1, hours: 0 });
  });

  it("default `false` e `\"\"` são valores de verdade e sobrevivem", () => {
    expect(schemaDefaults(schema, "action", "create_deal")).toEqual({
      title_template: "Deal automático",
      dedupe_open: false,
    });
    expect(schemaDefaults(schema, "end", null)).toEqual({ label: "" });
  });
});

describe("cache do schema", () => {
  it("primeNodeSchema publica para quem já está inscrito", () => {
    const visto: unknown[] = [];
    const unsub = subscribeNodeSchema(s => visto.push(s));
    primeNodeSchema(NODE_SCHEMA_FIXTURE);
    expect(visto).toEqual([NODE_SCHEMA_FIXTURE]);
    expect(getCachedNodeSchema()).toBe(NODE_SCHEMA_FIXTURE);
    unsub();
  });

  it("ensureNodeSchema busca uma vez só e memoriza", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse(NODE_SCHEMA_FIXTURE));
    vi.stubGlobal("fetch", fetchMock);

    const [a, b] = await Promise.all([ensureNodeSchema(), ensureNodeSchema()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
    expect(await ensureNodeSchema()).toBe(getCachedNodeSchema());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("endpoint fora do ar devolve null e NÃO envenena um schema já carregado", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const pendente = ensureNodeSchema();
    primeNodeSchema(NODE_SCHEMA_FIXTURE);
    await pendente;
    expect(getCachedNodeSchema()).toBe(NODE_SCHEMA_FIXTURE);
  });
});
