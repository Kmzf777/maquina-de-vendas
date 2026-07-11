// Descrição em LINGUAGEM DE OPERADOR do que um nó faz com a config atual.
// Função pura — exibida no cartão "O que este nó faz" do Inspector, calculada do
// rascunho (atualiza ao vivo enquanto o operador edita).
import type { CampaignNodeType } from "@/lib/types";
import { TRIGGER_LABELS, ACTION_LABELS } from "./constants";

type Config = Record<string, unknown>;

const ON_REPLY: Record<string, string> = {
  pause: "o fluxo PAUSA e aguarda",
  cancel: "o fluxo é CANCELADO (a conversa segue com a Valéria)",
  continue: "o fluxo continua mesmo assim",
};

const OPERATORS: Record<string, string> = { gte: "≥", lte: "≤", gt: ">", lt: "<", eq: "=" };

function dias(n: unknown): string {
  const v = Number(n ?? 0);
  return v === 1 ? "1 dia" : `${v} dias`;
}

function describeTrigger(c: Config): string {
  const tipo = (c.trigger_type as string) ?? "";
  const nome = TRIGGER_LABELS[tipo] ?? tipo ?? "—";
  switch (tipo) {
    case "no_message":
      return Number(c.days ?? 0) === 0
        ? "Inicia o fluxo quando o lead fica em silêncio (sem nova mensagem dele)."
        : `Inicia o fluxo quando o lead fica ${dias(c.days)} sem mandar mensagem.`;
    case "stage_stagnation":
      return `Inicia quando o lead fica ${dias(c.days)} parado${c.stage_filter ? ` no stage "${c.stage_filter}"` : " no mesmo stage"}.`;
    case "stage_enter":
      return `Inicia quando o lead entra${c.stage_filter ? ` no stage "${c.stage_filter}"` : " em qualquer stage"}.`;
    case "post_broadcast":
      return c.replied_only
        ? "Inicia após um disparo, SÓ para quem respondeu."
        : "Inicia após um disparo em massa.";
    case "sale_created":
      return `Inicia quando uma venda é criada${c.min_value ? ` (valor mínimo R$ ${c.min_value})` : ""}${c.product_filter ? ` contendo "${c.product_filter}"` : ""}.`;
    case "tag_added":
      return `Inicia quando a tag "${(c.tag_name as string) || "…"}" é adicionada ao lead.`;
    case "keyword_received": {
      const kws = Array.isArray(c.keywords) ? (c.keywords as string[]) : [];
      return kws.length
        ? `Inicia quando o lead envia uma destas palavras: ${kws.join(", ")}.`
        : "Inicia quando o lead envia uma palavra-chave (nenhuma configurada ainda).";
    }
    default:
      return `Inicia o fluxo no evento: ${nome}.`;
  }
}

function describeCondition(c: Config): string {
  const tipo = (c.condition_type as string) ?? "";
  const op = OPERATORS[(c.operator as string) ?? ""] ?? "≥";
  const v = c.value ?? "…";
  const regra: Record<string, string> = {
    replied_recently: `o lead respondeu nos últimos ${dias(c.days)}`,
    in_stage: `o lead está no stage "${(c.stage as string) || "…"}"`,
    has_tag: `o lead tem a tag "${(c.tag_name as string) || "…"}"`,
    sale_count: `o nº de vendas do lead é ${op} ${v}`,
    total_spend: `o total gasto pelo lead é ${op} R$ ${v}`,
    last_sale_value: `a última venda foi ${op} R$ ${v}`,
    deal_value: `o valor do deal é ${op} R$ ${v}`,
    repurchase_days: `os dias desde a última compra são ${op} ${v}`,
  };
  return `Verifica se ${regra[tipo] ?? tipo ?? "…"} — se SIM segue pelo ramo verde; se NÃO, pelo vermelho.`;
}

export function describeNode(type: CampaignNodeType, config: Config): string {
  switch (type) {
    case "trigger":
      return describeTrigger(config);
    case "send": {
      const nome = (config.template_name as string) || "(template não escolhido)";
      const lang = (config.template_language as string) || "pt_BR";
      const reply = ON_REPLY[(config.on_reply as string) ?? "pause"] ?? ON_REPLY.pause;
      return (
        `Envia o template aprovado "${nome}" (${lang}) pela Meta — o único formato aceito ` +
        `mesmo com a janela de 24h fechada. Se o lead responder, ${reply}.`
      );
    }
    case "send_text": {
      const texto = ((config.message_text as string) || "").trim();
      const previa = texto ? `"${texto.length > 140 ? texto.slice(0, 140) + "…" : texto}"` : "(mensagem vazia)";
      const reply = ON_REPLY[(config.on_reply as string) ?? "pause"] ?? ON_REPLY.pause;
      return (
        `Envia mensagem de TEXTO LIVRE: ${previa}. Só é aceito pela Meta com a janela de 24h ` +
        `ABERTA (lead falou há menos de 24h) — fora dela o motor bloqueia o envio. ` +
        `Se o lead responder, ${reply}.`
      );
    }
    case "wait": {
      const hIni = config.send_start_hour ?? 7;
      const hFim = config.send_end_hour ?? 18;
      const d = Number(config.days ?? 1);
      const h = Number(config.hours ?? 0);
      const espera =
        d && h ? `${dias(d)} e ${h === 1 ? "1 hora" : `${h} horas`}`
        : !d && h ? (h === 1 ? "1 hora" : `${h} horas`)
        : dias(d);
      return `Espera ${espera} antes do próximo passo; o passo seguinte só sai entre ${hIni}h e ${hFim}h.`;
    }
    case "condition":
      return describeCondition(config);
    case "action": {
      const tipo = (config.action_type as string) ?? "";
      const nome = ACTION_LABELS[tipo] ?? tipo ?? "…";
      const alvo =
        (config.stage as string) || (config.tag_name as string) || (config.title_template as string) || "";
      return `Executa: ${nome}${alvo ? ` — "${alvo}"` : ""}. Não envia mensagem ao lead.`;
    }
    case "end": {
      const rotulo = (config.label as string) || "Fim do fluxo";
      const acoes = Array.isArray(config.final_actions) ? (config.final_actions as unknown[]).length : 0;
      return `Encerra o fluxo aqui: "${rotulo}".${acoes ? ` Executa ${acoes} ação(ões) final(is) antes de encerrar.` : ""}`;
    }
    default:
      return "Nó sem descrição disponível.";
  }
}
