/**
 * O único leitor da FORMA DO ERRO do modal "ValerIA de Botões".
 *
 * ── Por que este arquivo existe (e não é uma linha em outro) ────────────────────
 * `mensagemDeErro` nasceu em `valeria-flow-modal.tsx` porque a casca era quem fazia
 * `fetch`. Só que `valeria-flow-channels.tsx` faz os seus dois (`GET /channels` e
 * `POST /activate`) e precisa da MESMA leitura — e no instante em que a casca passou a
 * importar o painel, o painel importando a casca fechou um ciclo de módulos. O ciclo
 * era benigno por acidente (`function` declaration é hoisted e ninguém a chama em
 * tempo de avaliação), e "benigno por acidente" é o tipo de coisa que para de ser
 * verdade sem avisar: basta alguém trocar por `const mensagemDeErro = (...) =>` ou
 * chamá-la no topo do módulo para virar `undefined` em runtime, num caminho que só
 * roda quando o backend recusa.
 *
 * Então a função desceu para um módulo que não importa nenhum dos dois. Um leitor da
 * forma do erro, nenhuma seta de volta.
 *
 * Não mora em `valeria-flow-types.ts` de propósito: os quatro arquivos de tipos do
 * repo (`lib/types.ts`, `components/dashboard/types.ts`,
 * `components/campaigns/cadence-flow/types.ts` e o daqui) são SÓ declarações, e todos
 * os importadores usam `import type`. Um valor em tempo de execução ali quebraria essa
 * leitura e o cabeçalho daquele arquivo, que diz o que ele guarda.
 *
 * Pelo mesmo motivo moram aqui as constantes de VERSÃO (v1/v2) e a montagem da query
 * `?flow_id=`: a casca e o painel de canais montam URLs, e as duas montagens têm de
 * concordar sobre o que a v1 manda (nada — a v1 continua batendo nas URLs de sempre).
 */
import type { FlowIdValeria } from "./valeria-flow-types";

export const FLOW_V1: FlowIdValeria = "valeria_botoes_v1";
export const FLOW_V2: FlowIdValeria = "valeria_botoes_v2";

/** As versões na ordem do seletor, com o rótulo que o operador lê. */
export const VERSOES: { id: FlowIdValeria; rotulo: string; curto: string; descricao: string }[] = [
  { id: FLOW_V1, rotulo: "v1", curto: "v1", descricao: "Roteiro de botões original" },
  { id: FLOW_V2, rotulo: "v2 (vitrine)", curto: "v2", descricao: "Vitrine com carrossel e tabela de preços" },
];

/**
 * A query de versão para uma URL de `/api/valeria-flow`: vazia na v1, de propósito. O
 * backend já responde pela v1 sem `flow_id`, e manter a v1 nas URLs de sempre é o que
 * deixa a v1 se comportar IGUAL a antes do seletor existir.
 */
export function queryDoFluxo(flowId: FlowIdValeria): string {
  return flowId === FLOW_V1 ? "" : `?flow_id=${encodeURIComponent(flowId)}`;
}

/** "v1"/"v2" para um `flow_id` de perfil, ou `null` se não for da ValerIA de Botões. */
export function versaoCurta(flowId: string | null | undefined): string | null {
  return VERSOES.find((versao) => versao.id === flowId)?.curto ?? null;
}

/**
 * A mensagem do backend, ou `padrao` se não houver nenhuma.
 *
 * Ordem: `detail` (FastAPI), `error` (o que o proxy devolve quando é ELE que falha —
 * "Backend indisponível"), `message`. Um `detail` de lista é o 422 do Pydantic (cada
 * item com `msg`); um `detail` de objeto é a forma que `campaigns/router.py` usa
 * (`{problemas: [...]}`) e que pode reaparecer aqui.
 */
export function mensagemDeErro(corpo: unknown, padrao: string): string {
  const body = (corpo ?? {}) as Record<string, unknown>;
  for (const bruto of [body.detail, body.error, body.message]) {
    if (typeof bruto === "string" && bruto.trim()) return bruto.trim();
    if (Array.isArray(bruto)) {
      const textos = bruto
        .map((item) => {
          if (typeof item === "string") return item;
          const campo = item as Record<string, unknown> | null;
          const msg = campo?.mensagem ?? campo?.msg;
          return typeof msg === "string" ? msg : null;
        })
        .filter((texto): texto is string => Boolean(texto && texto.trim()));
      if (textos.length) return textos.join(" · ");
    }
    if (bruto && typeof bruto === "object") {
      const campo = bruto as Record<string, unknown>;
      const aninhado = campo.mensagem ?? campo.msg ?? campo.problemas;
      if (typeof aninhado === "string" && aninhado.trim()) return aninhado.trim();
      if (Array.isArray(aninhado)) {
        const textos = aninhado
          .map((item) => {
            const campoItem = item as Record<string, unknown> | null;
            const msg = campoItem?.mensagem ?? campoItem?.msg;
            return typeof msg === "string" ? msg : null;
          })
          .filter((texto): texto is string => Boolean(texto && texto.trim()));
        if (textos.length) return textos.join(" · ");
      }
    }
  }
  return padrao;
}
