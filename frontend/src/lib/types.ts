export interface Lead {
  id: string;
  phone: string;
  name: string | null;
  company: string | null;
  stage: string;
  status: string;
  last_msg_at: string | null;
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
}

export interface Deal {
  id: string;
  lead_id: string;
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
  };
}

export interface Message {
  id: string;
  lead_id: string;
  role: string;       // "user" | "assistant" | "system"
  content: string;
  stage: string | null;
  sent_by: string;    // "agent" | "seller" | "cadence" | "user"
  created_at: string;
}

export interface Tag {
  id: string;
  name: string;
  color: string;
  created_at: string;
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
  status: "draft" | "scheduled" | "running" | "paused" | "completed" | "failed";
  scheduled_at: string | null;
  send_interval_min: number;
  send_interval_max: number;
  cadence_id: string | null;
  agent_profile_id: string | null;
  created_at: string;
  updated_at: string;
  // Joined
  cadences?: { id: string; name: string } | null;
}

export interface BroadcastLead {
  id: string;
  broadcast_id: string;
  lead_id: string;
  status: "pending" | "sent" | "failed" | "delivered";
  sent_at: string | null;
  error_message: string | null;
  leads?: { id: string; name: string | null; phone: string };
}

export interface Cadence {
  id: string;
  name: string;
  description: string | null;
  target_type: "manual" | "lead_stage" | "deal_stage";
  target_stage: string | null;
  stagnation_days: number | null;
  send_start_hour: number;
  send_end_hour: number;
  cooldown_hours: number;
  max_messages: number;
  status: "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}

export interface CadenceStep {
  id: string;
  cadence_id: string;
  step_order: number;
  message_text: string;
  delay_days: number;
  created_at: string;
}

export interface CadenceEnrollment {
  id: string;
  cadence_id: string;
  lead_id: string;
  deal_id: string | null;
  broadcast_id: string | null;
  current_step: number;
  status: "active" | "paused" | "responded" | "exhausted" | "completed";
  total_messages_sent: number;
  next_send_at: string | null;
  cooldown_until: string | null;
  responded_at: string | null;
  enrolled_at: string;
  completed_at: string | null;
  leads?: { id: string; name: string | null; phone: string; company: string | null; stage: string };
  deals?: { id: string; title: string; stage: string } | null;
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
  ai_enabled: boolean;
  leads?: Lead;
  channels?: { id: string; name: string; phone: string; provider: string; agent_profile_id: string | null } | null;
  agent_profiles?: { id: string; name: string } | null;
}
