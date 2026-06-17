export interface Lead {
  id: string;
  phone: string;
  name: string | null;
  company: string | null;
  stage: string;
  status: string;
  last_msg_at: string | null;
  last_customer_message_at: string | null;
  created_at: string;
  assigned_to: string | null;
  human_control: boolean;
  channel: string;
  // B2B fields
  cnpj: string | null;
  razao_social: string | null;
  nome_fantasia: string | null;
  endereco: string | null;
  telefone_comercial: string | null;
  email: string | null;
  instagram: string | null;
  inscricao_estadual: string | null;
  // Metrics
  entered_stage_at: string | null;
  first_response_at: string | null;
  on_hold: boolean;
  ai_enabled: boolean;
  notes: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface Pipeline {
  id: string;
  name: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface PipelineStage {
  id: string;
  pipeline_id: string;
  label: string;
  key: string | null; // 'fechado_ganho' | 'fechado_perdido' | null
  dot_color: string;
  order_index: number;
  is_protected: boolean;
  created_at: string;
}

export interface Deal {
  id: string;
  lead_id: string;
  pipeline_id: string | null;
  stage_id: string | null;
  title: string;
  value: number;
  stage: string;
  category: string | null;
  expected_close_date: string | null;
  assigned_to: string | null;
  closed_at: string | null;
  lost_reason: string | null;
  created_at: string;
  updated_at: string;
  // Joined fields
  leads?: {
    id: string;
    name: string | null;
    company: string | null;
    phone: string;
    nome_fantasia: string | null;
    notes: string | null;
  };
  pipeline_stages?: PipelineStage | null;
}

export interface ReactionTarget {
  content: string | null;
  role: string;
  message_type?: string | null;
}

export interface Message {
  id: string;
  lead_id: string;
  role: string;       // "user" | "assistant" | "system"
  content: string;
  stage: string | null;
  sent_by: string;    // "agent" | "seller" | "cadence" | "user"
  created_at: string;
  message_type?: string;
  media_url?: string;
  document_name?: string | null;
  media_mime?: string | null;
  metadata?: Record<string, unknown> | null;
  wamid?: string | null;
  delivery_status?: "sent" | "delivered" | "read" | null;
  quoted_wamid?: string | null;
  quoted_message_id?: string | null;
  quoted_message?: QuotedMessage | null;
  reaction_target?: ReactionTarget | null;
}

export interface QuotedMessage {
  id: string;
  content: string | null;
  role: string;
  message_type?: string | null;
}

export interface Tag {
  id: string;
  name: string;
  color: string;
  created_at: string;
}

export interface QuickReply {
  id: string;
  shortcut: string | null;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface EvolutionChat {
  id: string;
  remoteJid: string;
  pushName: string | null;
  profilePicUrl: string | null;
  lastMessage: {
    content: string;
    timestamp: number;
  } | null;
  unreadCount: number;
}

export interface EvolutionMessage {
  key: {
    remoteJid: string;
    fromMe: boolean;
    id: string;
  };
  message: {
    conversation?: string;
    imageMessage?: { caption?: string; url?: string };
    audioMessage?: { url?: string };
    documentMessage?: { fileName?: string; url?: string };
    stickerMessage?: Record<string, unknown>;
    videoMessage?: { caption?: string; url?: string };
  };
  messageType?: string;
  messageTimestamp: number;
  pushName?: string;
}

export interface Broadcast {
  id: string;
  name: string;
  channel_id: string | null;
  template_name: string;
  template_preset_id: string | null;
  template_variables: Record<string, unknown>;
  total_leads: number;
  sent: number;
  failed: number;
  delivered: number;
  template_language_code: string;
  status: "draft" | "scheduled" | "running" | "paused" | "completed" | "failed";
  scheduled_at: string | null;
  send_interval_min: number;
  send_interval_max: number;
  cadence_id: string | null;
  agent_profile_id: string | null;
  move_to_stage_id: string | null;
  created_at: string;
  updated_at: string;
  // Joined
  move_to_stage?: {
    id: string;
    label: string;
    pipeline_id: string;
    pipelines: { name: string } | null;
  } | null;
}

export interface BroadcastLead {
  id: string;
  broadcast_id: string;
  lead_id: string;
  status: "pending" | "sent" | "failed" | "delivered";
  sent_at: string | null;
  error_message: string | null;
  deal_moved_at: string | null;
  first_replied_at: string | null;
  leads?: { id: string; name: string | null; phone: string };
}

export interface BroadcastMetrics {
  replied_count: number;
  reply_rate: number;        // 0–100
  avg_reply_secs: number | null;
  median_reply_secs: number | null;
}


export interface MessageTemplate {
  id: string;
  channel_id: string;
  name: string;
  language: string;
  category: string | null;
  requested_category: string | null;
  status: string;
  created_at: string;
  // Campos enriquecidos (parseados de components — presentes quando retornados por /api/templates)
  body?: string;
  header?: { type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT"; text?: string; example?: string } | null;
  footer?: string | null;
  buttons?: { type: string; text: string }[];
  params?: { index: number; paramName: string; example: string }[];
  paramsType?: "positional" | "named" | "none";
}

export interface TemplatePreset {
  id: string;
  name: string;
  template_name: string;
  variables: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface LeadNote {
  id: string;
  lead_id: string;
  author: string;
  content: string;
  created_at: string;
}

export interface LeadEvent {
  id: string;
  lead_id: string;
  event_type: string;
  old_value: string | null;
  new_value: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles?: { id: string; name: string } | null;
  mode?: "ai" | "human";
  is_active: boolean;
  created_at: string;
}

export interface AgentProfile {
  id: string;
  name: string;
  model: string;
  stages: Record<string, {
    prompt: string;
    model: string;
    tools: string[];
  }>;
  base_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  lead_id: string;
  channel_id: string;
  stage: string;
  status: string;
  last_msg_at: string | null;
  created_at: string;
  agent_profile_id: string | null;
  last_message_text: string | null;
  unread_count: number;
  // Janela de 24h POR CANAL: última mensagem do cliente NESTA conversa (lead+canal).
  // Fonte da janela independente por canal — não confundir com Lead.last_customer_message_at (global).
  last_customer_message_at: string | null;
  whatsapp_window_expires_at: string | null;
  followup_enabled: boolean;
  deal_pipeline_name?: string | null;
  deal_stage_label?: string | null;
  deal_stage_dot_color?: string | null;
  first_seller_response_at: string | null;
  last_seller_response_at: string | null;
  leads?: Lead;
  channels?: { id: string; name: string; phone: string; provider: string; agent_profile_id: string | null; mode?: "ai" | "human" } | null;
  agent_profiles?: { id: string; name: string } | null;
}

export interface LeadBroadcastEntry {
  id: string;
  broadcast_id: string;
  broadcast_name: string;
  broadcast_status: string;
  message_status: string; // pending | sent | delivered | failed
  sent_at: string | null;
  first_replied_at: string | null;
}

export interface SpamConflict {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  last_broadcast_id: string;
  last_broadcast_name: string;
  last_sent_at: string;
}

// ─── Campaigns ────────────────────────────────────────────────────────────────

export type CampaignNodeType = "trigger" | "send" | "send_text" | "wait" | "condition" | "action" | "end";

export interface CampaignNode {
  id: string;
  campaign_id: string;
  type: CampaignNodeType;
  config: Record<string, unknown>;
  position_x: number;
  position_y: number;
  next_node_id: string | null;
  yes_node_id: string | null;
  no_node_id: string | null;
  created_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  description: string | null;
  status: "draft" | "active" | "paused" | "archived";
  priority?: number;
  frequency_cap?: number;
  channel_id: string | null;
  send_start_hour?: number;
  send_end_hour?: number;
  env_tag: string;
  start_date: string | null;
  created_at: string;
  updated_at: string;
  nodes?: CampaignNode[];
}

export interface CampaignEnrollment {
  id: string;
  campaign_id: string;
  lead_id: string;
  deal_id: string | null;
  status: "active" | "paused" | "completed" | "failed" | "removed" | "cancelled";
  current_node_id: string | null;
  next_execute_at: string | null;
  enrolled_at: string;
  completed_at: string | null;
  paused_at: string | null;
  env_tag: string;
  retry_count?: number;
  last_error?: string | null;
  leads?: {
    id: string;
    name: string | null;
    phone: string;
    company: string | null;
    stage: string | null;
  } | null;
  current_node?: {
    id: string;
    type: string;
    config: Record<string, unknown>;
  } | null;
  campaigns?: { id: string; name: string; status: string; created_at: string } | null;
}

export interface Sale {
  id: string;
  lead_id: string;
  sold_at: string;
  value: number;
  product: string;
  sold_by: string | null;
  deal_id: string | null;
  conversation_id: string | null;
  notes: string | null;
  created_at: string;
  leads?: { id: string; name: string | null; phone: string; company: string | null } | null;
  deals?: { id: string; title: string } | null;
}

export interface TeamUser {
  id: string;
  email: string;
  name: string;
}
