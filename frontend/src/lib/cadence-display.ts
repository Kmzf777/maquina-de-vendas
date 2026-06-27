export type FollowupJob = {
  sequence: number | null;
  job_type: string | null;
  status: string;
  fire_at: string | null;
  sent_at: string | null;
  cancel_reason: string | null;
  objetivo: string | null;
};

/** Modalidade do toque derivada de (status, cancel_reason). Ver plano Tier A. */
export function touchStateLabel(job: FollowupJob): string {
  switch (job.status) {
    case "pending":
      return "Agendado";
    case "sent":
      return "Texto enviado";
    case "awaiting_reopen":
      return "Template enviado";
    case "cancelled":
      return job.cancel_reason === "reopen_context_refreshed"
        ? "Contexto atualizado"
        : "Cancelado";
    default:
      return job.status;
  }
}

const OBJECTIVE_LABELS: Record<string, string> = {
  reengajar: "Reengajar",
  reforco_valor: "Reforço de valor",
  prova_social: "Prova social",
  ultima_chamada: "Última chamada",
};

/** Slug do objetivo → rótulo PT; desconhecido/None → "—". */
export function objectiveLabel(objetivo: string | null): string {
  if (!objetivo) return "—";
  return OBJECTIVE_LABELS[objetivo] ?? "—";
}
