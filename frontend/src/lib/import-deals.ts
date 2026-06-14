export interface ImportDealLead {
  id: string;
  name: string | null;
  phone: string;
}

export interface ImportDealRow {
  lead_id: string;
  title: string;
  value: number;
  pipeline_id: string;
  stage_id: string;
  stage: string;
}

/**
 * Monta as linhas de `deals` para os leads importados.
 * - Pula leads que já possuem um deal no funil escolhido (anti-duplicação).
 * - Título segue o padrão do deal-create-modal: "<nome ou telefone> - <funil>".
 */
export function buildImportDeals(params: {
  leads: ImportDealLead[];
  pipelineId: string;
  stageId: string;
  pipelineName: string;
  existingDealLeadIds: Set<string>;
}): ImportDealRow[] {
  const { leads, pipelineId, stageId, pipelineName, existingDealLeadIds } = params;
  return leads
    .filter((l) => !existingDealLeadIds.has(l.id))
    .map((l) => ({
      lead_id: l.id,
      title: `${l.name || l.phone} - ${pipelineName}`,
      value: 0,
      pipeline_id: pipelineId,
      stage_id: stageId,
      stage: "novo",
    }));
}
