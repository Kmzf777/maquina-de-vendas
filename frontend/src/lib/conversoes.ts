// Rótulos e tradução de erro da aba "Conversões enviadas" (/trafego).
export const STAGE_LABEL: Record<string, string> = {
  lead: "Lead", qualified: "Qualificado", opportunity: "Oportunidade", purchase: "Venda",
};
export const STATUS_LABEL: Record<string, string> = {
  pendente: "Pendente", enviado: "Enviado", erro: "Com erro", fora_da_janela: "Fora da janela", ignorado: "Ignorado",
};
export const PLATFORM_LABEL: Record<string, string> = { meta: "Meta Ads", google: "Google Ads" };
export const STAGES = ["lead", "qualified", "opportunity", "purchase"] as const;
export const PLATFORMS = ["meta", "google"] as const;

// O erro bruto vem do backend em inglês/técnico; o admin precisa saber o que fazer, não o stack.
export function traduzErro(err: string | null | undefined): string {
  if (!err) return "";
  if (/não configurado/i.test(err)) return `Falta configuração no servidor: ${err}`;
  if (/access token/i.test(err)) return "O Google recusou a autorização — regerar o refresh token.";
  if (/HTTP 4\d\d/.test(err)) return `A plataforma recusou o evento: ${err.replace(/^HTTP \d+:\s*/, "")}`;
  if (/HTTP 5\d\d|rede:/i.test(err)) return "A plataforma não respondeu; o sistema tenta de novo sozinho.";
  return err;
}
