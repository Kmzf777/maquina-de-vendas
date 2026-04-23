import type { Message } from "@/lib/types";

function formatTime(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function truncate(str: string, max = 55): string {
  return str.length > max ? str.slice(0, max) + "…" : str;
}

type EventInfo = {
  type: string;
  label: string;
  bg: string;
  color: string;
};

function parseEvent(content: string): EventInfo {
  if (content.startsWith("[encaminhar_humano]")) {
    const label = truncate(content.replace("[encaminhar_humano]", "").trim());
    return { type: "encaminhar_humano", label, bg: "#EFF6FF", color: "#2563EB" };
  }
  if (content.startsWith("stage alterado para:")) {
    const value = content.replace("stage alterado para:", "").trim();
    return { type: "mudar_stage", label: truncate("Stage: " + value), bg: "#F5F3FF", color: "#7C3AED" };
  }
  if (content.startsWith("[enviar_fotos]")) {
    const label = truncate(content.replace("[enviar_fotos]", "").trim());
    return { type: "enviar_fotos", label, bg: "#F0FDF4", color: "#16A34A" };
  }
  if (content.startsWith("[enviar_foto_produto]")) {
    const label = truncate(content.replace("[enviar_foto_produto]", "").trim());
    return { type: "enviar_foto_produto", label, bg: "#F0FDF4", color: "#16A34A" };
  }
  if (content.startsWith("Pedido registrado:")) {
    const label = truncate(content.replace("Pedido registrado:", "").trim());
    return { type: "registrar_pedido_simples", label, bg: "#FFFBEB", color: "#D97706" };
  }
  if (content.startsWith("Nome salvo:")) {
    const value = content.replace("Nome salvo:", "").trim();
    return { type: "salvar_nome", label: truncate("Nome: " + value), bg: "#F9FAFB", color: "#6B7280" };
  }
  return { type: "generic", label: truncate(content), bg: "#F9FAFB", color: "#6B7280" };
}

function EventIcon({ type, color }: { type: string; color: string }) {
  const props = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: color,
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    style: { flexShrink: 0 },
  };

  if (type === "encaminhar_humano") {
    return (
      <svg {...props}>
        <path d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 9l3 3m0 0-3 3m3-3H3" />
      </svg>
    );
  }
  if (type === "mudar_stage") {
    return (
      <svg {...props}>
        <path d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
      </svg>
    );
  }
  if (type === "enviar_fotos" || type === "enviar_foto_produto") {
    return (
      <svg {...props}>
        <path d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
      </svg>
    );
  }
  if (type === "registrar_pedido_simples") {
    return (
      <svg {...props}>
        <path d="M11.35 3.836c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 3.54 8.25 4.509 8.25 5.628v4.052M8.25 9.75H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V16.5a9 9 0 0 0-9-9Z" />
        <path d="m4.5 12.75 3 3 4.5-4.5" />
      </svg>
    );
  }
  if (type === "salvar_nome") {
    return (
      <svg {...props}>
        <path d="M17.982 18.725A7.488 7.488 0 0 0 12 15.75a7.488 7.488 0 0 0-5.982 2.975m11.963 0a9 9 0 1 0-11.963 0m11.963 0A8.966 8.966 0 0 1 12 21a8.966 8.966 0 0 1-5.982-2.275M15 9.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      </svg>
    );
  }
  return (
    <svg {...props}>
      <path d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
    </svg>
  );
}

interface EventCardProps {
  message: Message;
}

export function EventCard({ message }: EventCardProps) {
  const { type, label, bg, color } = parseEvent(message.content);
  const time = formatTime(message.created_at);

  return (
    <div className="flex items-center gap-2 my-3 px-2">
      <div className="flex-1 h-px bg-[#dedbd6]" />
      <div
        className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-medium whitespace-nowrap"
        style={{ backgroundColor: bg, color }}
      >
        <EventIcon type={type} color={color} />
        <span>{label}</span>
        <span style={{ color, opacity: 0.6 }}>·</span>
        <span style={{ opacity: 0.7 }}>{time}</span>
      </div>
      <div className="flex-1 h-px bg-[#dedbd6]" />
    </div>
  );
}
