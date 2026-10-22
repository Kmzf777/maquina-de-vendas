/**
 * Segmento do lead (`leads.segmento`) separado da fase (`leads.stage`) — cartão b67f1c6b.
 *
 * Espelho de `backend/app/leads/segmento.py`. Puro (sem imports de servidor): usado pelas
 * telas e pelas rotas.
 *
 * Transição: até o backfill F2/F3 rodar, o segmento ainda pode estar em `stage` e a
 * triagem ainda pode se chamar "secretaria". Os leitores daqui caem no `stage` antigo
 * quando `segmento` está vazio; "secretaria" aparece como "Em triagem".
 */
import { AGENT_STAGES } from "@/lib/constants";

export const SEGMENTOS = ["atacado", "private_label", "consumo", "exportacao"] as const;
export const FASES = ["pending", "novo", "triagem", "qualificando", "perdido"] as const;

export type Segmento = (typeof SEGMENTOS)[number];
export type Fase = (typeof FASES)[number];

/** Rótulos das fases. "secretaria" (legado) é a fase triagem. */
export const FASE_LABELS: Record<string, string> = {
  pending: "Pendente",
  novo: "Novo",
  triagem: "Em triagem",
  qualificando: "Qualificando",
  perdido: "Perdido",
  secretaria: "Em triagem",
};

const SEGMENTO_LABELS: Record<string, string> = Object.fromEntries(
  AGENT_STAGES.map((s) => [s.key, s.label]),
);

/** O mínimo de lead que os helpers leem. */
export interface LeadSegmentoLike {
  segmento?: string | null;
  stage?: string | null;
}

/** "Private Label"/"private-label" -> "private_label"; fase, "secretaria" ou lixo -> null. */
export function normalizarSegmento(v: string | null | undefined): Segmento | null {
  if (!v) return null;
  const chave = v
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  return (SEGMENTOS as readonly string[]).includes(chave) ? (chave as Segmento) : null;
}

export function faseValida(v: string | null | undefined): v is Fase {
  return !!v && (FASES as readonly string[]).includes(v);
}

/** `leads.segmento`; se vazio, o `stage` antigo (lead ainda não migrado). */
export function segmentoDoLead(lead: LeadSegmentoLike | null | undefined): Segmento | null {
  if (!lead) return null;
  return normalizarSegmento(lead.segmento) ?? normalizarSegmento(lead.stage);
}

/** Lead em triagem: fase `triagem` ou o "secretaria" antigo. */
function emTriagem(lead: LeadSegmentoLike): boolean {
  return lead.stage === "triagem" || lead.stage === "secretaria";
}

/**
 * Chave de `AGENT_STAGES` do lead: o segmento, ou "triagem" se ainda está em triagem.
 * Demais fases sem segmento (pending, novo, qualificando, perdido) -> null.
 */
export function agentStageKeyDoLead(lead: LeadSegmentoLike | null | undefined): Segmento | "triagem" | null {
  if (!lead) return null;
  const seg = segmentoDoLead(lead);
  if (seg) return seg;
  return emTriagem(lead) ? "triagem" : null;
}

/** O lead está na coluna/aba/filtro `chave` de AGENT_STAGES? */
export function leadCasaAgentStage(lead: LeadSegmentoLike, chave: string): boolean {
  if (chave === "triagem") return !segmentoDoLead(lead) && emTriagem(lead);
  return segmentoDoLead(lead) === chave;
}

/** Rótulo para exibir o lead: o segmento, senão a fase. */
export function rotuloDoLead(lead: LeadSegmentoLike | null | undefined): string {
  const seg = segmentoDoLead(lead);
  if (seg) return SEGMENTO_LABELS[seg] ?? seg;
  const stage = lead?.stage;
  if (!stage) return "—";
  return FASE_LABELS[stage] ?? stage;
}

export type ResultadoSegmentoFase =
  | { ok: true; campos: { stage?: Fase; segmento?: Segmento | null } }
  | { ok: false; erro: string };

/**
 * Valida `stage`/`segmento` vindos de um PATCH de lead.
 *
 * - `segmento`: um dos SEGMENTOS (normalizado) ou vazio/null (= ainda não sabe).
 * - `stage`: só FASE. Para não quebrar telas antigas que mandam o segmento em `stage`:
 *   segmento em `stage` vira `segmento` + fase `qualificando`; "secretaria" vira `triagem`
 *   sem segmento (mesma regra de `apply_stage_transition`). Um `segmento` explícito no
 *   corpo vence o derivado.
 */
export function resolverSegmentoFase(body: Record<string, unknown>): ResultadoSegmentoFase {
  const campos: { stage?: Fase; segmento?: Segmento | null } = {};

  if ("stage" in body && body.stage !== undefined) {
    const stage = typeof body.stage === "string" ? body.stage.trim() : "";
    const seg = normalizarSegmento(stage);
    if (faseValida(stage)) campos.stage = stage;
    else if (seg) {
      campos.segmento = seg;
      campos.stage = "qualificando";
    } else if (stage === "secretaria") {
      campos.segmento = null;
      campos.stage = "triagem";
    } else {
      return { ok: false, erro: `Fase inválida: "${stage}". Use ${FASES.join(", ")}.` };
    }
  }

  if ("segmento" in body && body.segmento !== undefined) {
    const bruto = body.segmento;
    if (bruto === null || bruto === "") campos.segmento = null;
    else {
      const seg = typeof bruto === "string" ? normalizarSegmento(bruto) : null;
      if (!seg) {
        return { ok: false, erro: `Segmento inválido: "${String(bruto)}". Use ${SEGMENTOS.join(", ")}.` };
      }
      campos.segmento = seg;
    }
  }

  return { ok: true, campos };
}
