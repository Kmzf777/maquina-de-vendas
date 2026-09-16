/**
 * Espelho de teste do `GET /api/campaigns/node-schema` — a resposta que
 * `backend/app/campaigns/node_registry.py::para_json()` produz.
 *
 * POR QUE ISTO EXISTE E POR QUE NÃO É "A CÓPIA DE NOVO"
 * ────────────────────────────────────────────────────
 * O bug que esta leva mata é a tela manter uma cópia do contrato em CÓDIGO DE
 * PRODUÇÃO — um `<select>` hard-coded que grava rótulo de coluna onde o motor lê
 * segmento de lead. Nada aqui é lido em produção: é fixture de teste, usada por
 * `node-schema.test.ts`, `cadence-flow/helpers.test.ts` e `inspector.test.tsx`.
 *
 * O que impede a DIVERGÊNCIA entre este arquivo e o registro real é a divisão de
 * responsabilidade entre as duas suítes:
 *   • `backend/tests/test_node_registry.py` cruza o registro com o motor por regex —
 *     `cfg.get("...")` novo em engine.py/triggers.py quebra a suíte até ser declarado.
 *   • os testes daqui provam que a TELA renderiza pelo VOCABULÁRIO do campo, nunca
 *     pelo nome do subtipo. Um vocabulário novo herda o renderizador certo mesmo que
 *     esta fixture envelheça.
 */
import type { NodeSchema } from "./node-schema";

/** Atalho de leitura: a maioria dos campos é opcional e sem default. */
function campo(
  chave: string,
  vocab: string,
  rotulo: string,
  extra: { obrigatorio?: boolean; default?: unknown; ajuda?: string } = {},
) {
  return {
    chave,
    vocab,
    rotulo,
    obrigatorio: extra.obrigatorio ?? false,
    default: "default" in extra ? extra.default : null,
    ajuda: extra.ajuda ?? "",
  };
}

const OPERADOR = campo("operator", "operador", "Operador", { default: "gte" });

export const NODE_SCHEMA_FIXTURE: NodeSchema = {
  tipos: [
    // ─── Gatilhos ──────────────────────────────────────────────────────────────
    {
      tipo: "trigger", subtipo: "no_message", rotulo: "Sem mensagem", icone: "💤",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("days", "numero", "Dias em silencio", { default: 30 }),
        campo("stage_filter", "segmento_lead", "Segmento do lead (opcional)", {
          ajuda: "Vazio = qualquer segmento. Compara com `leads.stage`, NAO com a coluna do Kanban.",
        }),
      ],
    },
    {
      tipo: "trigger", subtipo: "stage_stagnation", rotulo: "Parado no segmento", icone: "🕐",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("stage_filter", "segmento_lead", "Segmento do lead", {
          obrigatorio: true,
          ajuda: "Sem este campo o motor PULA o gatilho inteiro, em silencio.",
        }),
        campo("days", "numero", "Dias parado no segmento", { default: 7 }),
      ],
    },
    {
      tipo: "trigger", subtipo: "no_sale_in_stage", rotulo: "Sem venda no segmento", icone: "📉",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("stage_filter", "segmento_lead", "Segmento do lead", { obrigatorio: true }),
        campo("days", "numero", "Dias no segmento sem venda", { default: 7 }),
      ],
    },
    {
      tipo: "trigger", subtipo: "stage_enter", rotulo: "Entrou em segmento", icone: "⚡",
      na_paleta: true, requer_um_de: [],
      campos: [campo("stage_filter", "segmento_lead", "Segmento do lead (opcional)")],
    },
    {
      tipo: "trigger", subtipo: "deal_stage_enter", rotulo: "Card entrou em etapa", icone: "🤝",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("stage_filter", "etapa_key", "Etapa do funil (opcional)", {
          ajuda: "Aqui e `pipeline_stages.key` — nao o rotulo, nao o segmento do lead.",
        }),
      ],
    },
    {
      tipo: "trigger", subtipo: "deal_stage_stagnation", rotulo: "Card parado no funil", icone: "📋",
      na_paleta: true, requer_um_de: [["stage_id", "stage_key"]],
      campos: [
        campo("stage_id", "etapa_id", "Etapa exata (uuid)"),
        campo("stage_key", "etapa_key", "Etapa por key"),
        campo("pipeline_id", "funil_id", "Funil"),
        campo("stage_days", "numero", "Dias parado na etapa", { default: 0 }),
        campo("silence_days", "numero", "Dias sem mensagem", { default: 0 }),
        campo("last_speaker", "falante", "Quem falou por ultimo", { default: "qualquer" }),
        campo("limit", "numero", "Cards por tick", { default: 20 }),
        campo("on_reply", "politica_resposta", "Se o lead responder", {
          default: "pause", ajuda: "Vale para a esteira toda. Ausente = pausar.",
        }),
      ],
    },
    {
      tipo: "trigger", subtipo: "keyword_received", rotulo: "Palavra-chave recebida", icone: "🔍",
      na_paleta: true, requer_um_de: [],
      campos: [campo("keywords", "lista_texto", "Palavras-chave", { obrigatorio: true })],
    },
    {
      tipo: "trigger", subtipo: "repurchase_window", rotulo: "Janela de recompra", icone: "🔄",
      na_paleta: true, requer_um_de: [],
      campos: [campo("days", "numero", "Dias desde a ultima compra", { obrigatorio: true, default: 30 })],
    },
    {
      tipo: "trigger", subtipo: "sale_created", rotulo: "Venda criada", icone: "💰",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("min_value", "numero", "Valor minimo (R$, opcional)"),
        campo("product_filter", "texto", "Filtro de produto (opcional)"),
      ],
    },
    {
      tipo: "trigger", subtipo: "tag_added", rotulo: "Tag adicionada", icone: "🏷️",
      na_paleta: true, requer_um_de: [],
      campos: [campo("tag_name", "tag", "Tag (opcional)")],
    },
    {
      tipo: "trigger", subtipo: "deal_closed_lost", rotulo: "Card perdido", icone: "❌",
      na_paleta: true, requer_um_de: [], campos: [],
    },
    {
      // SEM `replied_only`: o campo saía da tela, ia como `False` fixo e ninguém o lia.
      tipo: "trigger", subtipo: "post_broadcast", rotulo: "Pos-disparo", icone: "📡",
      na_paleta: true, requer_um_de: [], campos: [],
    },

    // ─── Ações ─────────────────────────────────────────────────────────────────
    {
      tipo: "action", subtipo: "move_stage", rotulo: "Mover segmento do lead", icone: "📋",
      na_paleta: true, requer_um_de: [],
      campos: [campo("stage", "segmento_lead", "Segmento de destino", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "move_deal_stage", rotulo: "Mover card de etapa", icone: "🔀",
      na_paleta: true, requer_um_de: [],
      campos: [campo("stage_id", "etapa_id", "Etapa de destino", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "mark_deal_won", rotulo: "Marcar card como ganho", icone: "🏆",
      na_paleta: true, requer_um_de: [],
      campos: [campo("stage_id", "etapa_id", "Etapa de ganho", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "mark_deal_lost", rotulo: "Marcar card como perdido", icone: "💔",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("stage_id", "etapa_id", "Etapa de perda", { obrigatorio: true }),
        campo("lost_reason", "texto", "Motivo da perda (opcional)"),
      ],
    },
    {
      tipo: "action", subtipo: "add_tag", rotulo: "Adicionar tag", icone: "🏷️",
      na_paleta: true, requer_um_de: [],
      campos: [campo("tag_name", "tag", "Tag", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "remove_tag", rotulo: "Remover tag", icone: "🏷️",
      na_paleta: true, requer_um_de: [],
      campos: [campo("tag_name", "tag", "Tag", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "create_deal", rotulo: "Criar card", icone: "💼",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("title_template", "texto", "Titulo do card", { default: "Deal automático" }),
        campo("pipeline_id", "funil_id", "Funil de destino", {
          obrigatorio: true,
          ajuda: "Sem funil explicito o card cai no PRIMEIRO pipeline do banco.",
        }),
        campo("stage_key", "etapa_key", "Etapa inicial (opcional)"),
        campo("category", "texto", "Categoria (opcional)"),
        campo("dedupe_open", "booleano", "Reaproveitar card aberto", { default: false }),
      ],
    },
    {
      tipo: "action", subtipo: "assign_to", rotulo: "Atribuir a vendedor", icone: "👤",
      na_paleta: true, requer_um_de: [],
      campos: [campo("user_id", "usuario_id", "Vendedor", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "assign_round_robin", rotulo: "Atribuir (round-robin)", icone: "🎯",
      na_paleta: true, requer_um_de: [],
      campos: [campo("user_ids", "lista_usuario_id", "Vendedores no rodizio", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "add_note", rotulo: "Adicionar nota", icone: "📝",
      na_paleta: true, requer_um_de: [],
      campos: [campo("note_template", "texto_longo", "Texto da nota", { obrigatorio: true })],
    },
    {
      tipo: "action", subtipo: "alert_seller", rotulo: "Avisar vendedor", icone: "🔔",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("severity", "severidade", "Gravidade", { default: "warning" }),
        campo("title", "texto", "Titulo do alerta", { obrigatorio: true }),
        campo("message_template", "texto_longo", "Mensagem do alerta"),
      ],
    },
    {
      tipo: "action", subtipo: "activate_agent", rotulo: "Ativar a IA no lead", icone: "🤖",
      na_paleta: true, requer_um_de: [], campos: [],
    },
    {
      tipo: "action", subtipo: "deactivate_agent", rotulo: "Desativar a IA no lead", icone: "🤖",
      na_paleta: true, requer_um_de: [], campos: [],
    },

    // ─── Condições (as NOVE, uma a uma na paleta) ──────────────────────────────
    {
      tipo: "condition", subtipo: "replied_recently", rotulo: "Respondeu recentemente", icone: "💬",
      na_paleta: true, requer_um_de: [],
      campos: [campo("days", "numero", "Nos ultimos X dias", { default: 5 })],
    },
    {
      tipo: "condition", subtipo: "in_stage", rotulo: "Esta no segmento", icone: "📋",
      na_paleta: true, requer_um_de: [],
      campos: [campo("stage", "segmento_lead", "Segmento", { ajuda: "Compara com `leads.stage`." })],
    },
    {
      tipo: "condition", subtipo: "has_deal", rotulo: "Tem card no CRM", icone: "💼",
      na_paleta: true, requer_um_de: [], campos: [],
    },
    {
      tipo: "condition", subtipo: "has_tag", rotulo: "Possui tag", icone: "🏷️",
      na_paleta: true, requer_um_de: [],
      campos: [campo("tag_name", "tag", "Tag")],
    },
    {
      tipo: "condition", subtipo: "sale_count", rotulo: "Numero de vendas", icone: "🧾",
      na_paleta: true, requer_um_de: [],
      campos: [OPERADOR, campo("value", "numero", "Quantidade", { default: 1 })],
    },
    {
      tipo: "condition", subtipo: "total_spend", rotulo: "Gasto total (R$)", icone: "💰",
      na_paleta: true, requer_um_de: [],
      campos: [OPERADOR, campo("value", "numero", "Valor em R$", { default: 0 })],
    },
    {
      tipo: "condition", subtipo: "last_sale_value", rotulo: "Valor da ultima venda", icone: "💵",
      na_paleta: true, requer_um_de: [],
      campos: [OPERADOR, campo("value", "numero", "Valor em R$", { default: 0 })],
    },
    {
      tipo: "condition", subtipo: "deal_value", rotulo: "Valor do card", icone: "🏷️",
      na_paleta: true, requer_um_de: [],
      campos: [OPERADOR, campo("value", "numero", "Valor em R$", { default: 0 })],
    },
    {
      tipo: "condition", subtipo: "repurchase_days", rotulo: "Dias desde a ultima compra", icone: "🔄",
      na_paleta: true, requer_um_de: [],
      campos: [OPERADOR, campo("value", "numero", "Dias", { default: 30 })],
    },

    // ─── Envio, espera e fim ───────────────────────────────────────────────────
    {
      tipo: "send", subtipo: null, rotulo: "Enviar template", icone: "📨",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("template_name", "template", "Template aprovado", { obrigatorio: true }),
        campo("template_language", "texto", "Idioma do template", { default: "pt_BR" }),
        campo("template_variables", "mapa", "Variaveis do template"),
        campo("channel_id", "canal_id", "Canal (opcional)"),
        campo("on_reply", "politica_resposta", "Se o lead responder NESTE toque", {
          ajuda: "Vazio = herda a politica do gatilho (o normal). Preencher aqui SOBREPOE a esteira inteira, so neste toque.",
        }),
      ],
    },
    {
      tipo: "send_text", subtipo: null, rotulo: "Enviar texto livre", icone: "💬",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("message_text", "texto_longo", "Mensagem", { obrigatorio: true }),
        campo("channel_id", "canal_id", "Canal (opcional)"),
        campo("on_reply", "politica_resposta", "Se o lead responder NESTE toque", {
          ajuda: "Mesma regra do `send`: vazio herda do gatilho.",
        }),
      ],
    },
    {
      tipo: "wait", subtipo: null, rotulo: "Aguardar", icone: "⏱",
      na_paleta: true, requer_um_de: [],
      campos: [
        campo("days", "numero", "Dias", { default: 1 }),
        campo("hours", "numero", "Horas", { default: 0 }),
        campo("send_start_hour", "numero", "Inicio da janela (opcional)"),
        campo("send_end_hour", "numero", "Fim da janela (opcional)"),
        campo("skip_weekends", "booleano", "Pular fim de semana (opcional)"),
      ],
    },
    {
      tipo: "end", subtipo: null, rotulo: "Encerrar", icone: "🏁",
      na_paleta: true, requer_um_de: [],
      campos: [campo("label", "texto", "Rotulo do encerramento", { default: "" })],
    },
  ],
  valores_fixos: {
    segmento_lead: [
      ["secretaria", "Secretaria (triagem)"],
      ["atacado", "Atacado"],
      ["private_label", "Private Label"],
      ["exportacao", "Exportacao"],
      ["consumo", "Consumo"],
      ["pending", "Pendente (importado, sem triagem)"],
      ["perdido", "Perdido"],
    ],
    operador: [
      ["gte", ">= (maior ou igual)"],
      ["lte", "<= (menor ou igual)"],
      ["gt", "> (maior)"],
      ["lt", "< (menor)"],
      ["eq", "= (igual)"],
    ],
    politica_resposta: [
      ["pause", "Pausar a esteira"],
      ["cancel", "Cancelar a esteira"],
      ["reset", "Voltar ao primeiro toque"],
    ],
    severidade: [
      ["info", "Informativo"],
      ["warning", "Atencao"],
      ["critical", "Critico"],
    ],
    falante: [
      ["qualquer", "Tanto faz"],
      ["lead", "O lead falou por ultimo"],
      ["nos", "Nos falamos por ultimo"],
    ],
  },
};
