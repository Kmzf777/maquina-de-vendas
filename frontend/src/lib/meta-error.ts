// Classificação de erros da Graph API para o envio de reações.
// Fail-soft exigido pelo plano 11/07: janela de 24h fechada (131047) ou mensagem
// antiga demais para reagir (131009) não são falhas de infra — viram 422 com
// mensagem acionável para o operador; o resto degrada para 502 genérico.

const WINDOW_CLOSED_CODES = new Set([131047, 131009]);

export interface MetaReactionErrorInfo {
  status: 422 | 502;
  error: string;
}

export function describeMetaReactionError(rawBody: string): MetaReactionErrorInfo {
  let code: number | undefined;
  try {
    const parsed = JSON.parse(rawBody) as { error?: { code?: number } };
    code = parsed?.error?.code;
  } catch {
    // corpo não-JSON (HTML de proxy, etc.) — trata como erro genérico
  }
  if (code !== undefined && WINDOW_CLOSED_CODES.has(code)) {
    return {
      status: 422,
      error:
        "Reação não entregue: a janela de 24h está fechada (ou a mensagem é antiga demais para reagir).",
    };
  }
  return { status: 502, error: "Falha ao enviar reação" };
}
