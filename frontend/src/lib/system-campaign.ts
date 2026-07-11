// Campanha-espelho do motor de follow-up da Valéria (somente-leitura).
// DEVE ser idêntico a VALERIA_CADENCE_CAMPAIGN_ID no backend
// (backend/app/campaigns/system_cadence.py):
// uuid5(NAMESPACE_URL, "canastra://system/valeria-followup-cadence").
// O teste em system-campaign.test.ts fixa o literal — mudar aqui sem mudar lá quebra
// o banner read-only e o bloqueio de ativação.
export const VALERIA_CADENCE_CAMPAIGN_ID = "d4a7ffa3-62c2-51c4-91fc-5fcc06ec9055";

export function isSystemCampaign(campaignId: string | null | undefined): boolean {
  return campaignId === VALERIA_CADENCE_CAMPAIGN_ID;
}

/** Semântica do toggle EMBUTIDO no card de cadência (padronização 11/07):
 *  card convencional → liga/desliga a campanha (activate/pause do automation engine);
 *  card do espelho do motor → aciona a regra de visibilidade/estado já existente
 *  (Redis via /api/cadence/mirror-visibility) — NUNCA activate/pause: a ativação da
 *  campanha de sistema segue bloqueada (409) no backend, impedindo execução dupla. */
export type CardToggle = { kind: "mirror" | "campaign"; on: boolean };

export function cardToggleState(
  campaign: { id: string; status: string },
  mirrorVisible: boolean,
): CardToggle {
  if (isSystemCampaign(campaign.id)) {
    return { kind: "mirror", on: mirrorVisible };
  }
  return { kind: "campaign", on: campaign.status === "active" };
}
