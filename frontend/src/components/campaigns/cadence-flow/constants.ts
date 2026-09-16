import type { CampaignNodeType } from "@/lib/types";
import type { PaletteItem } from "./types";
import { subscribeNodeSchema, type NodeSchema, type NodeSchemaType } from "@/lib/node-schema";

// ─── Fonts ────────────────────────────────────────────────────────────────────
export const FONT_STYLE = `@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
.react-flow__handle { transition: transform .15s, box-shadow .15s; }
.react-flow__handle:hover { transform: scale(1.5) !important; }
.react-flow__node { cursor: grab; }
.react-flow__node:active { cursor: grabbing; }
.react-flow__node.selected > div { box-shadow: 0 0 0 2px #fff, 0 0 0 4px #E85D26, 0 8px 28px rgba(0,0,0,.14) !important; border-color: transparent !important; }
.react-flow__edge-path { transition: stroke .15s; }
.react-flow__controls { box-shadow: 0 2px 8px rgba(0,0,0,.1); border-radius: 8px; border: 1px solid #e8e4df; overflow: hidden; }
.react-flow__controls-button { background: #fff; border-bottom: 1px solid #e8e4df; color: #555; }
.react-flow__controls-button:hover { background: #f5f2ed; }
@keyframes cfb-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
`;

// ─── Design constants ──────────────────────────────────────────────────────────
export const NODE_W = 220;

export const NODE_META: Record<CampaignNodeType, { label: string; kicker: string; icon: string; color: string; iconBg: string }> = {
  trigger:   { label: "Gatilho",         kicker: "GATILHO",  icon: "⚡", color: "#1a1a1a", iconBg: "rgba(26,26,26,.07)" },
  send:      { label: "Enviar template", kicker: "ENVIAR",   icon: "📨", color: "#E85D26", iconBg: "rgba(232,93,38,.1)" },
  send_text: { label: "Enviar texto",    kicker: "TEXTO LIVRE", icon: "💬", color: "#0F766E", iconBg: "rgba(15,118,110,.1)" },
  wait:      { label: "Aguardar",        kicker: "ESPERA",   icon: "⏱", color: "#3B7DD8", iconBg: "rgba(59,125,216,.1)" },
  condition: { label: "Condição",        kicker: "CONDIÇÃO", icon: "🔀", color: "#C4920C", iconBg: "rgba(196,146,12,.1)" },
  action:    { label: "Ação",            kicker: "AÇÃO",     icon: "📋", color: "#7C4DB8", iconBg: "rgba(124,77,184,.1)" },
  end:       { label: "Encerrar",        kicker: "FIM",      icon: "🏁", color: "#1A9B6C", iconBg: "rgba(26,155,108,.1)" },
};

export const STATUS_LABELS: Record<string, string> = {
  draft: "Rascunho", active: "Ativa", paused: "Pausada", archived: "Arquivada",
};
export const STATUS_COLORS: Record<string, { bg: string; color: string; border: string }> = {
  draft:    { bg: "#f5f2ed", color: "#888",    border: "#e0dbd4" },
  active:   { bg: "#edfaf5", color: "#1A9B6C", border: "#a7f0d4" },
  paused:   { bg: "#fff7ed", color: "#C4920C", border: "#fde68a" },
  archived: { bg: "#f5f2ed", color: "#888",    border: "#e0dbd4" },
};

// ─── Rótulos e ícones por subtipo ──────────────────────────────────────────────
//
// SÃO SEMENTES, NÃO A FONTE. O contrato é `node_registry.py`; o que está aqui é o que
// a tela mostra no primeiro paint, antes de `GET /api/campaigns/node-schema`
// responder. Quando o schema chega, `applyNodeSchemaToConstants` (no fim do arquivo)
// sobrescreve estes mapas com `rotulo`/`icone` do registro. Nenhum deles decide
// COMPORTAMENTO — são texto e emoji do canvas; as listas que viram valor gravado
// saem todas do schema, no inspector.
export const TRIGGER_LABELS: Record<string, string> = {
  no_message: "Sem mensagem", stage_stagnation: "Estagnação", stage_enter: "Entrada em stage", post_broadcast: "Pós-disparo",
  sale_created: "Venda criada", repurchase_window: "Janela de recompra", no_sale_in_stage: "Sem venda no stage",
  tag_added: "Tag adicionada", deal_stage_enter: "Entrou em stage (deal)", deal_closed_lost: "Deal perdido",
  keyword_received: "Palavra-chave recebida", deal_stage_stagnation: "Card parado no funil",
};
export const ACTION_LABELS: Record<string, string> = {
  move_stage: "Mover stage do lead",
  activate_agent: "Ativar agente",
  deactivate_agent: "Desativar agente",
  add_tag: "Adicionar tag",
  remove_tag: "Remover tag",
  mark_deal_won: "Marcar deal como ganho",
  mark_deal_lost: "Marcar deal como perdido",
  move_deal_stage: "Mover deal de estágio",
  add_note: "Adicionar nota",
  assign_round_robin: "Atribuir (round-robin)",
  create_deal: "Criar deal",
  assign_to: "Atribuir a vendedor",
  alert_seller: "Avisar vendedor",
};
// As NOVE condições. Até 16/09/2026 não existia mapa nenhum: o card no canvas exibia
// a key crua (`repurchase_days`) e as oito condições fora da paleta só existiam num
// <select> escondido no inspector.
export const CONDITION_LABELS: Record<string, string> = {
  replied_recently: "Respondeu recentemente",
  in_stage: "Está em stage",
  has_deal: "Tem deal ativo",
  has_tag: "Possui tag",
  sale_count: "Número de vendas",
  total_spend: "Gasto total (R$)",
  last_sale_value: "Valor da última venda",
  deal_value: "Valor do deal",
  repurchase_days: "Dias desde última compra",
};

// Ícones por subtype — os nós no canvas mostram o ícone do subtipo, não o genérico
export const TRIGGER_ICONS: Record<string, string> = {
  stage_enter: "⚡", stage_stagnation: "🕐", no_message: "💤", post_broadcast: "📡",
  sale_created: "💰", repurchase_window: "🔄", no_sale_in_stage: "📉",
  tag_added: "🏷️", deal_stage_enter: "🤝", deal_closed_lost: "❌",
  keyword_received: "🔍", deal_stage_stagnation: "📋",
};
export const ACTION_ICONS: Record<string, string> = {
  move_stage: "📋",
  activate_agent: "🤖",
  deactivate_agent: "🤖",
  add_tag: "🏷️",
  remove_tag: "🏷️",
  mark_deal_won: "🏆",
  mark_deal_lost: "💔",
  move_deal_stage: "🔀",
  add_note: "📝",
  assign_round_robin: "🎯",
  create_deal: "💼",
  assign_to: "👤",
  alert_seller: "🔔",
};
export const CONDITION_ICONS: Record<string, string> = {
  replied_recently: "💬",
  in_stage: "📋",
  has_deal: "💼",
  has_tag: "🏷️",
  sale_count: "🧾",
  total_spend: "💰",
  last_sale_value: "💵",
  deal_value: "🏷️",
  repurchase_days: "🔄",
};

// Atalho do "+" no canvas: uma lista CURADA de 18 itens, não um espelho do contrato.
// Ela é renderizada num popover absoluto sem rolagem (`graph-elements.tsx`), onde as
// 26 entradas da paleta completa não caberiam. Por isso continua fixa: não grava
// valor nenhum (só escolhe tipo+subtipo, e o config sai de `getDefaultConfig`), e um
// tipo novo do registro aparece na paleta lateral mesmo sem estar aqui.
export const QUICK_ADD_ITEMS: { type: CampaignNodeType; subtype: string; icon: string; label: string }[] = [
  { type: "send",      subtype: "",                  icon: "📨", label: "Enviar template" },
  { type: "send_text", subtype: "",                  icon: "💬", label: "Enviar texto" },
  { type: "wait",      subtype: "",                  icon: "⏱",  label: "Aguardar" },
  { type: "condition", subtype: "replied_recently",  icon: "🔀", label: "Condição" },
  { type: "action",    subtype: "move_stage",        icon: "📋", label: "Mover stage do lead" },
  { type: "action",    subtype: "move_deal_stage",   icon: "🔀", label: "Mover deal de estágio" },
  { type: "action",    subtype: "mark_deal_won",     icon: "🏆", label: "Marcar deal ganho" },
  { type: "action",    subtype: "mark_deal_lost",    icon: "💔", label: "Marcar deal perdido" },
  { type: "action",    subtype: "add_note",          icon: "📝", label: "Adicionar nota" },
  { type: "action",    subtype: "add_tag",           icon: "🏷️", label: "Adicionar tag" },
  { type: "action",    subtype: "remove_tag",        icon: "🏷️", label: "Remover tag" },
  { type: "action",    subtype: "create_deal",       icon: "💼", label: "Criar deal" },
  { type: "action",    subtype: "activate_agent",    icon: "🤖", label: "Ativar agente" },
  { type: "action",    subtype: "deactivate_agent",  icon: "🤖", label: "Desativar agente" },
  { type: "action",    subtype: "assign_to",         icon: "👤", label: "Atribuir vendedor" },
  { type: "action",    subtype: "assign_round_robin", icon: "🎯", label: "Atribuir round-robin" },
  { type: "action",    subtype: "alert_seller",      icon: "🔔", label: "Avisar vendedor" },
  { type: "end",       subtype: "",                   icon: "🏁", label: "Encerrar" },
];

// ─── Paleta ────────────────────────────────────────────────────────────────────
//
// QUEM ESTÁ NA PALETA É DECISÃO DO REGISTRO (`na_paleta`), não desta lista. Os arrays
// abaixo são a semente do primeiro paint e são REESCRITOS NO LUGAR (`splice`) quando
// o schema chega — `index.tsx` faz `PALETTE_TRIGGERS.map(...)` a cada render, então
// enxerga a lista nova sem precisar de estado. É o que faz as nove condições
// aparecerem: a paleta tinha um único item "Condição" que nascia `replied_recently`.

/** Texto de apoio da paleta. É a ÚNICA coisa local: não vira valor gravado, não
 *  decide comportamento e o registro não tem campo para ele. Tipo ausente daqui
 *  continua aparecendo na paleta — só ganha uma descrição derivada dos campos. */
const PALETTE_DESC: Record<string, string> = {
  "trigger:stage_enter": "Lead entra em segmento",
  "trigger:stage_stagnation": "Parado X dias no segmento",
  "trigger:no_message": "Silêncio X dias",
  "trigger:post_broadcast": "Após broadcast",
  "trigger:sale_created": "Nova venda registrada",
  "trigger:repurchase_window": "X dias desde última compra",
  "trigger:no_sale_in_stage": "Segmento sem venda",
  "trigger:tag_added": "Lead recebeu uma tag",
  "trigger:deal_stage_enter": "Card mudou de etapa",
  "trigger:deal_closed_lost": "Card marcado como perdido",
  "trigger:keyword_received": "Lead enviou palavra-chave",
  "trigger:deal_stage_stagnation": "Card parado numa coluna",
  "send:": "Mensagem HSM Meta",
  "send_text:": "Texto livre (24h)",
  "wait:": "Delay em dias/horas",
  "end:": "Fim da campanha",
  "action:move_stage": "Atualiza leads.stage",
  "action:move_deal_stage": "Pipeline de deals",
  "action:mark_deal_won": "Etapa de ganho",
  "action:mark_deal_lost": "Etapa de perdido",
  "action:add_tag": "Marca o lead",
  "action:remove_tag": "Desmarca o lead",
  "action:add_note": "Texto na timeline",
  "action:create_deal": "Novo card no funil",
  "action:activate_agent": "Liga ValerIA",
  "action:deactivate_agent": "Desliga ValerIA",
  "action:assign_to": "Lead → vendedor fixo",
  "action:assign_round_robin": "Rodízio entre vendedores",
  "action:alert_seller": "Alerta + nota no card",
  "condition:replied_recently": "Respondeu nos últimos dias",
  "condition:in_stage": "Segmento do lead",
  "condition:has_deal": "Card aberto no CRM",
  "condition:has_tag": "Lead tem a tag",
  "condition:sale_count": "Quantas vendas já fez",
  "condition:total_spend": "Quanto já gastou",
  "condition:last_sale_value": "Valor da última venda",
  "condition:deal_value": "Valor do card mais recente",
  "condition:repurchase_days": "Tempo desde a última compra",
};

// Ordem de exibição por tipo. O schema vem na ordem de declaração do registro
// (gatilhos, ações, condições, envio) — boa para ler o contrato, ruim para operar:
// quem monta cadência começa por enviar/esperar.
const ORDEM_DE_TIPO: string[] = ["send", "send_text", "wait", "condition", "action", "end"];

function paletteItem(t: NodeSchemaType): PaletteItem {
  const chave = `${t.tipo}:${t.subtipo ?? ""}`;
  return {
    type: t.tipo as CampaignNodeType,
    subtype: t.subtipo ?? "",
    icon: t.icone,
    label: t.rotulo,
    desc: PALETTE_DESC[chave] ?? t.campos[0]?.rotulo ?? "Sem configuração",
  };
}

/** Monta a paleta a partir do contrato. Gatilhos de um lado (só um por cadência),
 *  todo o resto do outro — a mesma divisão de colunas que a tela já tinha. */
export function buildPaletteFromSchema(schema: NodeSchema): { triggers: PaletteItem[]; actions: PaletteItem[] } {
  const visiveis = schema.tipos.filter(t => t.na_paleta);
  const naOrdem = [...visiveis].sort((a, b) => {
    const ia = ORDEM_DE_TIPO.indexOf(a.tipo);
    const ib = ORDEM_DE_TIPO.indexOf(b.tipo);
    return (ia < 0 ? ORDEM_DE_TIPO.length : ia) - (ib < 0 ? ORDEM_DE_TIPO.length : ib);
  });
  return {
    triggers: visiveis.filter(t => t.tipo === "trigger").map(paletteItem),
    actions: naOrdem.filter(t => t.tipo !== "trigger").map(paletteItem),
  };
}

export const PALETTE_TRIGGERS: PaletteItem[] = [
  { type: "trigger", subtype: "stage_enter",       icon: "⚡", label: "Entrada em stage",       desc: "Lead entra em stage" },
  { type: "trigger", subtype: "stage_stagnation",  icon: "🕐", label: "Estagnação",              desc: "Parado X dias" },
  { type: "trigger", subtype: "no_message",        icon: "💤", label: "Sem mensagem",            desc: "Silêncio X dias" },
  { type: "trigger", subtype: "post_broadcast",    icon: "📡", label: "Pós-disparo",             desc: "Após broadcast" },
  { type: "trigger", subtype: "sale_created",      icon: "💰", label: "Venda criada",            desc: "Nova venda registrada" },
  { type: "trigger", subtype: "repurchase_window", icon: "🔄", label: "Janela de recompra",      desc: "X dias desde última compra" },
  { type: "trigger", subtype: "no_sale_in_stage",  icon: "📉", label: "Sem venda no stage",      desc: "Stage avançado sem venda" },
  { type: "trigger", subtype: "tag_added",         icon: "🏷️", label: "Tag adicionada",          desc: "Lead recebeu uma tag" },
  { type: "trigger", subtype: "deal_stage_enter",  icon: "🤝", label: "Entrou em stage (deal)",  desc: "Deal mudou de stage" },
  { type: "trigger", subtype: "deal_closed_lost",  icon: "❌", label: "Deal perdido",             desc: "Deal marcado como perdido" },
  { type: "trigger", subtype: "keyword_received",  icon: "🔍", label: "Palavra-chave",            desc: "Lead enviou palavra-chave" },
  { type: "trigger", subtype: "deal_stage_stagnation", icon: "📋", label: "Card parado no funil", desc: "Parado X dias numa coluna" },
];
export const PALETTE_ACTIONS: PaletteItem[] = [
  { type: "send",      subtype: "",                  icon: "📨", label: "Enviar template",       desc: "Mensagem HSM Meta" },
  { type: "send_text", subtype: "",                  icon: "💬", label: "Enviar texto",          desc: "Texto livre (24h)" },
  { type: "wait",      subtype: "",                  icon: "⏱",  label: "Aguardar",              desc: "Delay em dias" },
  { type: "condition", subtype: "replied_recently",  icon: "🔀", label: "Condição",              desc: "Ramificação lógica" },
  { type: "action",    subtype: "move_stage",        icon: "📋", label: "Mover stage do lead",   desc: "Atualiza leads.stage" },
  { type: "action",    subtype: "move_deal_stage",   icon: "🔀", label: "Mover deal estágio",    desc: "Pipeline de deals" },
  { type: "action",    subtype: "mark_deal_won",     icon: "🏆", label: "Marcar deal ganho",     desc: "Stage de ganho" },
  { type: "action",    subtype: "mark_deal_lost",    icon: "💔", label: "Marcar deal perdido",   desc: "Stage de perdido" },
  { type: "action",    subtype: "add_tag",           icon: "🏷️", label: "Adicionar tag",         desc: "Marca o lead" },
  { type: "action",    subtype: "remove_tag",        icon: "🏷️", label: "Remover tag",           desc: "Desmarca o lead" },
  { type: "action",    subtype: "add_note",          icon: "📝", label: "Adicionar nota",        desc: "Texto na timeline" },
  { type: "action",    subtype: "create_deal",       icon: "💼", label: "Criar deal",            desc: "Novo deal no lead" },
  { type: "action",    subtype: "activate_agent",    icon: "🤖", label: "Ativar agente",         desc: "Liga ValerIA" },
  { type: "action",    subtype: "deactivate_agent",  icon: "🤖", label: "Desativar agente",      desc: "Desliga ValerIA" },
  { type: "action",    subtype: "assign_to",         icon: "👤", label: "Atribuir vendedor",     desc: "Lead → vendedor fixo" },
  { type: "action",    subtype: "assign_round_robin", icon: "🎯", label: "Round-robin",          desc: "Rodízio entre vendedores" },
  { type: "action",    subtype: "alert_seller",      icon: "🔔", label: "Avisar vendedor",       desc: "Alerta + nota no card" },
  { type: "end",       subtype: "",                  icon: "🏁", label: "Encerrar",              desc: "Fim da campanha" },
];

// ─── O contrato assume o comando ───────────────────────────────────────────────
//
// Uma vez por carregamento da tela, quando `GET /api/campaigns/node-schema` responde.
// Reescreve NO LUGAR (splice/atribuição de chave) em vez de reatribuir a const:
// `index.tsx` e `helpers.ts` já importaram estes objetos, e um `=` novo não chegaria
// neles. A partir daqui, quem decide o que existe é `node_registry.py`.
subscribeNodeSchema(schema => {
  const { triggers, actions } = buildPaletteFromSchema(schema);
  PALETTE_TRIGGERS.splice(0, PALETTE_TRIGGERS.length, ...triggers);
  PALETTE_ACTIONS.splice(0, PALETTE_ACTIONS.length, ...actions);

  for (const t of schema.tipos) {
    if (!t.subtipo) continue;
    if (t.tipo === "trigger")   { TRIGGER_LABELS[t.subtipo] = t.rotulo;   TRIGGER_ICONS[t.subtipo] = t.icone; }
    if (t.tipo === "action")    { ACTION_LABELS[t.subtipo] = t.rotulo;    ACTION_ICONS[t.subtipo] = t.icone; }
    if (t.tipo === "condition") { CONDITION_LABELS[t.subtipo] = t.rotulo; CONDITION_ICONS[t.subtipo] = t.icone; }
  }
});
