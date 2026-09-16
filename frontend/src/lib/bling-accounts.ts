/**
 * Logica pura de selecao de conta Bling. Fica fora do componente para poder ser
 * testada sem montar o modal inteiro — mesmo padrao de `quote-state.ts`.
 */
export type ContaBling = {
  account: string;
  label: string;
  configured: boolean;
  connected: boolean;
};

/**
 * Slug da conta que existia antes da segunda conta ser criada. Chega assim
 * pelo JSON do backend (`account: "default"` em `/api/bling/status`) — nao e
 * um enum do TypeScript, por isso a comparacao e contra uma string literal, nao
 * contra um tipo. Exportada como constante so para nao espalhar o literal
 * "default" pelos arquivos que forem consumir este modulo (Tasks 15/16).
 */
export const CONTA_PADRAO = "default";

/** So conta conectada pode emitir: sem refresh_token nao ha como falar com o ERP. */
export function contasDisponiveis(contas: ContaBling[]): ContaBling[] {
  return contas.filter((c) => c.configured && c.connected);
}

/**
 * Com uma conta so o seletor nao aparece — a feature inteira fica invisivel ate
 * a segunda conta ser configurada, e nada muda para quem usa o CRM hoje.
 *
 * Some tambem quando `skipBling` esta marcado ("Registrar sem enviar ao
 * Bling"): nesse caminho a venda nao vai para ERP nenhum, entao oferecer uma
 * escolha de CNPJ sugeriria um efeito que nao existe.
 */
export function precisaSeletor(contas: ContaBling[], skipBling = false): boolean {
  if (skipBling) return false;
  return contasDisponiveis(contas).length > 1;
}

/**
 * Conta pre-selecionada quando o seletor aparece: prefere a `CONTA_PADRAO` (e
 * a que todo mundo ja conhece) e cai para a primeira conectada quando a
 * default nao estiver disponivel. `null` so quando nao ha nenhuma conta
 * conectada — o que fazer nesse caso (bloquear? cair no legado?) e decisao do
 * `blingGate`, nao deste modulo.
 */
export function contaPadrao(contas: ContaBling[]): string | null {
  const disponiveis = contasDisponiveis(contas);
  if (disponiveis.length === 0) return null;
  const padrao = disponiveis.find((c) => c.account === CONTA_PADRAO);
  return (padrao ?? disponiveis[0]).account;
}

/**
 * Trocar a conta invalida itens e contato: os SKU/ID nao coincidem entre as
 * contas, entao remapear seria adivinhacao com risco de emitir o produto errado.
 * Confirmar so quando ha algo a perder.
 */
export function trocaLimpaFormulario(
  estado: { itens: number; contatoId: number | null },
): boolean {
  return estado.itens > 0 || estado.contatoId !== null;
}

/**
 * Corpo (ja em JSON) de `GET /api/bling/status`, so os campos que a logica de
 * conta usa. Todos opcionais porque a rota Next devolve um subconjunto para
 * quem nao e admin (ver `app/api/bling/status/route.ts`): sem o papel admin,
 * `accounts` nem chega a existir no payload — sobram so os dois campos de topo.
 */
export interface BlingStatusPayload {
  enabled?: boolean;
  connected?: boolean;
  accounts?: ContaBling[];
}

/** O que `useBlingStatus` guarda em cache depois de interpretar o payload. */
export interface BlingStatusResult {
  enabled: boolean;
  accounts: ContaBling[];
}

/**
 * Traduz o payload bruto de `/api/bling/status` no par que o hook cacheia.
 *
 * `enabled` continua vindo SO dos campos de topo (`enabled` = BLING_ENABLED
 * global, `connected` = a conta default tem refresh_token) e NUNCA de
 * `accounts` — porque `accounts` pode faltar (papel nao-admin, ver acima) ou
 * vir vazio, e mesmo assim o booleano tem que continuar valendo: e ele que
 * impede o modal de cair em modo legado so porque o papel do usuario escondeu
 * a lista de contas. `accounts` ausente vira `[]`, nunca `undefined` — assim
 * quem consome (Tasks 15/16) nao precisa checar nulidade antes de
 * filtrar/mapear.
 */
export function interpretarStatus(body: BlingStatusPayload): BlingStatusResult {
  return {
    enabled: !!body.enabled && !!body.connected,
    accounts: body.accounts ?? [],
  };
}
