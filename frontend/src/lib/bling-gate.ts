/**
 * Decide em que modo o modal de venda opera.
 *
 * Existe como funcao pura porque a regra tem uma consequencia que precisa de
 * teste: quando a consulta a `/api/bling/status` FALHA, o modal bloqueia em vez
 * de cair no modo legado. Cair no legado reintroduziria o defeito que esta fase
 * conserta (venda avulsa entrando no CRM sem ninguem perceber), so que
 * intermitente. Falha de rede e transitoria; venda gravada fora do ERP e
 * permanente.
 *
 * `isEditing` NAO influencia mais o modo (Fase E): editar uma venda agora pode
 * significar um PUT no pedido do Bling, entao confirmar a conexao importa tanto
 * quanto na criacao. Ate 21/08/2026 `isEditing` forcava modo legado aqui — a
 * edicao era PATCH puramente local e o ERP nunca era tocado.
 */
export type BlingMode = "loading" | "bling" | "legacy" | "error";

export interface BlingGateInput {
  loading: boolean;
  error: string | null;
  enabled: boolean | null;
  isEditing: boolean;
}

export interface BlingGate {
  mode: BlingMode;
  canSubmit: boolean;
  message?: string;
}

export function blingGate({ loading, error, enabled }: BlingGateInput): BlingGate {
  if (loading) return { mode: "loading", canSubmit: false };

  if (error) {
    return {
      mode: "error",
      canSubmit: false,
      message:
        "Nao foi possivel confirmar a conexao com o Bling. " +
        "Registrar agora criaria uma venda fora do ERP, entao o envio esta bloqueado.",
    };
  }

  return enabled ? { mode: "bling", canSubmit: true } : { mode: "legacy", canSubmit: true };
}
