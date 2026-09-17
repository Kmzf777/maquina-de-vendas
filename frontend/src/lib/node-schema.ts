/**
 * O contrato dos nós de cadência, servido por `GET /api/campaigns/node-schema`
 * (backend: `app/campaigns/node_registry.py` → `para_json()`).
 *
 * POR QUE A TELA PAROU DE TER CÓPIA
 * ─────────────────────────────────
 * O builder mantinha, dentro do inspector, uma lista hard-coded dos campos de cada
 * tipo de nó — e o motor lia outra coisa com o mesmo nome. O caso que custou caro:
 * `stage_filter` era populado das colunas do Kanban e gravava o RÓTULO ("Em
 * conversa"), enquanto o motor compara com `leads.stage` (o SEGMENTO do lead) em
 * quatro gatilhos e com `pipeline_stages.key` num quinto. Cinco dos doze gatilhos
 * nunca casavam, em silêncio.
 *
 * A cura não é corrigir as listas: é a tela renderizar pelo `vocab` de cada campo.
 * Vocabulário novo no registro passa a ter um renderizador e TODO campo que o usa
 * herda o comportamento certo — inclusive os que ainda não existem.
 *
 * `default: null` NÃO é "sem valor por preguiça": é "ausente tem sentido próprio".
 * É assim que `on_reply` dos nós de envio e a janela do `wait` herdam a configuração
 * do gatilho/da campanha em vez de sequestrá-la (o motor dá precedência ao NÓ).
 */
import { useEffect, useState } from "react";

export interface NodeSchemaField {
  /** Literalmente o que o motor faz `cfg.get(...)`. */
  chave: string;
  /** De onde vem o valor e contra o que ele vai ser comparado. Decide o controle. */
  vocab: string;
  rotulo: string;
  /** Obrigatório para ATIVAR a campanha — nunca para salvar rascunho. */
  obrigatorio: boolean;
  /** O que o MOTOR assume quando a chave está ausente. `null` = ausente tem sentido. */
  default: unknown;
  ajuda: string;
}

export interface NodeSchemaType {
  tipo: string;
  subtipo: string | null;
  rotulo: string;
  icone: string;
  na_paleta: boolean;
  /** Grupos "pelo menos um destes" — ver `deal_stage_stagnation`. */
  requer_um_de: string[][];
  campos: NodeSchemaField[];
}

/** `[valor_gravado, rotulo_humano]` dos vocabulários fechados. */
export type FixedValue = [string, string];

export interface NodeSchema {
  tipos: NodeSchemaType[];
  valores_fixos: Record<string, FixedValue[]>;
}

export const NODE_SCHEMA_URL = "/api/campaigns/node-schema";

/** O schema usa `null` para os tipos sem subtipo (send/send_text/wait/end); a tela
 *  usa `""`. Os dois falam do mesmo nó. */
export function normalizeSubtype(subtipo: string | null | undefined): string | null {
  return subtipo ? subtipo : null;
}

// ─── Parsing ────────────────────────────────────────────────────────────────────

function parseCampo(raw: Record<string, unknown>): NodeSchemaField | null {
  if (typeof raw?.chave !== "string" || typeof raw?.vocab !== "string") return null;
  return {
    chave: raw.chave,
    vocab: raw.vocab,
    rotulo: typeof raw.rotulo === "string" ? raw.rotulo : raw.chave,
    obrigatorio: raw.obrigatorio === true,
    default: raw.default ?? null,
    ajuda: typeof raw.ajuda === "string" ? raw.ajuda : "",
  };
}

function parseTipo(raw: Record<string, unknown>): NodeSchemaType | null {
  if (typeof raw?.tipo !== "string") return null;
  const campos = Array.isArray(raw.campos)
    ? (raw.campos as Record<string, unknown>[]).map(parseCampo).filter((c): c is NodeSchemaField => c !== null)
    : [];
  return {
    tipo: raw.tipo,
    subtipo: typeof raw.subtipo === "string" && raw.subtipo ? raw.subtipo : null,
    rotulo: typeof raw.rotulo === "string" ? raw.rotulo : raw.tipo,
    icone: typeof raw.icone === "string" ? raw.icone : "⚡",
    // Ausente = na paleta. Um tipo novo aparece por padrão; aposentar é explícito.
    na_paleta: raw.na_paleta !== false,
    requer_um_de: Array.isArray(raw.requer_um_de)
      ? (raw.requer_um_de as unknown[]).filter(Array.isArray).map(g => (g as unknown[]).map(String))
      : [],
    campos,
  };
}

/** Resposta estranha vira schema VAZIO, nunca exceção: a tela degrada, não quebra. */
export function parseNodeSchema(raw: unknown): NodeSchema {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const tipos = Array.isArray(obj.tipos)
    ? (obj.tipos as Record<string, unknown>[]).map(parseTipo).filter((t): t is NodeSchemaType => t !== null)
    : [];

  const valores_fixos: Record<string, FixedValue[]> = {};
  const fixos = (obj.valores_fixos ?? {}) as Record<string, unknown>;
  for (const [vocab, lista] of Object.entries(fixos)) {
    if (!Array.isArray(lista)) continue;
    valores_fixos[vocab] = (lista as unknown[])
      .filter((par): par is unknown[] => Array.isArray(par) && par.length >= 2)
      .map(par => [String(par[0]), String(par[1])] as FixedValue);
  }
  return { tipos, valores_fixos };
}

export async function fetchNodeSchema(url: string = NODE_SCHEMA_URL): Promise<NodeSchema> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`node-schema respondeu ${res.status}`);
  return parseNodeSchema(await res.json());
}

// ─── Leitura ────────────────────────────────────────────────────────────────────

export function findNodeType(
  schema: NodeSchema | null,
  tipo: string,
  subtipo: string | null | undefined,
): NodeSchemaType | undefined {
  if (!schema) return undefined;
  const alvo = normalizeSubtype(subtipo);
  return schema.tipos.find(t => t.tipo === tipo && t.subtipo === alvo);
}

export function fieldsOf(
  schema: NodeSchema | null,
  tipo: string,
  subtipo: string | null | undefined,
): NodeSchemaField[] {
  return findNodeType(schema, tipo, subtipo)?.campos ?? [];
}

export function fixedValues(schema: NodeSchema | null, vocab: string): FixedValue[] {
  return schema?.valores_fixos?.[vocab] ?? [];
}

/** Os tipos que a paleta oferece. `na_paleta=false` continua válido e renderizável
 *  (campanha antiga que já o usa não vira lixo), mas some da lista de tipos novos. */
export function paletteTypes(schema: NodeSchema | null, tipo?: string): NodeSchemaType[] {
  if (!schema) return [];
  return schema.tipos.filter(t => t.na_paleta && (tipo === undefined || t.tipo === tipo));
}

/**
 * Os defaults DECLARADOS de um tipo de nó. Campo com `default` nulo fica de fora:
 * gravar valor onde o registro diz "ausente" é exatamente como o builder sequestrava
 * a política de resposta da esteira e a janela de envio da campanha.
 */
export function schemaDefaults(
  schema: NodeSchema | null,
  tipo: string,
  subtipo: string | null | undefined,
): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const campo of fieldsOf(schema, tipo, subtipo)) {
    if (campo.default === null || campo.default === undefined) continue;
    config[campo.chave] = campo.default;
  }
  return config;
}

// ─── Cache de módulo ────────────────────────────────────────────────────────────
//
// A paleta (`constants.ts`) e os defaults (`helpers.getDefaultConfig`) são lidos por
// código SÍNCRONO que não é hook e não tem como esperar um fetch. Por isso o contrato
// vive num cache de módulo, preenchido uma vez por carregamento da tela.

let cached: NodeSchema | null = null;
let inflight: Promise<NodeSchema | null> | null = null;
const listeners = new Set<(schema: NodeSchema) => void>();

export function getCachedNodeSchema(): NodeSchema | null {
  return cached;
}

/** Publica um schema (ou limpa o cache com `null`). Usado pelo fetch e pelos testes. */
export function primeNodeSchema(schema: NodeSchema | null): void {
  cached = schema;
  if (schema) for (const cb of listeners) cb(schema);
}

export function subscribeNodeSchema(cb: (schema: NodeSchema) => void): () => void {
  listeners.add(cb);
  if (cached) cb(cached);
  return () => { listeners.delete(cb); };
}

/** Busca uma vez e memoriza. Falha devolve `null` e NUNCA escreve no cache — um
 *  endpoint fora do ar não pode apagar um contrato que já chegou. */
export function ensureNodeSchema(): Promise<NodeSchema | null> {
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = fetchNodeSchema()
      .then(schema => { primeNodeSchema(schema); return schema; })
      .catch(() => null)
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function useNodeSchema(): NodeSchema | null {
  const [schema, setSchema] = useState<NodeSchema | null>(() => getCachedNodeSchema());
  useEffect(() => {
    let vivo = true;
    const unsub = subscribeNodeSchema(s => { if (vivo) setSchema(s); });
    void ensureNodeSchema();
    return () => { vivo = false; unsub(); };
  }, []);
  return schema;
}

// O fetch começa no import, no navegador: quando o operador arrasta o primeiro nó
// para o canvas, o contrato já chegou e `getDefaultConfig` não precisa degradar.
// Fora do navegador (SSR, testes em ambiente `node`) nada acontece.
if (typeof window !== "undefined") void ensureNodeSchema();
