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

/** Aplica o toggle de visibilidade do espelho do motor (decisão executiva 10/07):
 *  quando oculto, o espelho some das listagens; campanhas convencionais nunca são
 *  afetadas. Só apresentação — status/guardas do backend intactos. */
export function visibleCampaigns<T extends { id: string }>(
  campaigns: T[],
  mirrorVisible: boolean,
): T[] {
  if (mirrorVisible) return campaigns;
  return campaigns.filter((c) => !isSystemCampaign(c.id));
}
