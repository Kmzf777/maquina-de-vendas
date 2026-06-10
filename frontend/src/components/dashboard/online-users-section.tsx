"use client";

import { usePresence, type UserPresenceState } from "@/hooks/use-presence";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ----- Constants -------------------------------------------------------

const PAGE_LABELS: Record<string, string> = {
  "/dashboard":    "Dashboard",
  "/leads":        "Leads",
  "/conversas":    "Conversas",
  "/campanhas":    "Campanhas",
  "/qualificacao": "Qualificação",
  "/vendas":       "Vendas",
  "/canais":       "Canais",
  "/estatisticas": "Estatísticas",
  "/config":       "Configurações",
};

/** Avatar background colours — one per first letter (cycled). */
const AVATAR_COLORS: Record<string, string> = {
  A: "#e8e2f5", // Arthur — soft violet
  R: "#e2eef5", // Rafael — soft blue
  K: "#e5f0e8", // Kelwin — soft green
  J: "#f5ede2", // João   — soft amber
};
const AVATAR_TEXT_COLORS: Record<string, string> = {
  A: "#6b4fa8",
  R: "#3a6fa8",
  K: "#3a8a52",
  J: "#a87a3a",
};
const DEFAULT_AVATAR_BG   = "#f0ede8";
const DEFAULT_AVATAR_TEXT = "#7b7b78";

function getAvatarBg(name: string): string {
  const initial = name.charAt(0).toUpperCase();
  return AVATAR_COLORS[initial] ?? DEFAULT_AVATAR_BG;
}
function getAvatarText(name: string): string {
  const initial = name.charAt(0).toUpperCase();
  return AVATAR_TEXT_COLORS[initial] ?? DEFAULT_AVATAR_TEXT;
}

function getStatusDot(status: UserPresenceState["status"]): { color: string; title: string } {
  switch (status) {
    case "online":  return { color: "#22c55e", title: "Online"          };
    case "ausente": return { color: "#f59e0b", title: "Ausente (oculto)" };
    case "offline": return { color: "#dedbd6", title: "Offline"          };
  }
}

function getPageLabel(page: string | null): string {
  if (!page) return "ausente";
  return PAGE_LABELS[page] ?? page;
}

// ----- Skeleton ---------------------------------------------------------

function PresenceSkeleton() {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="h-3 w-28 bg-[#dedbd6]/40 rounded animate-pulse" />
        <div className="h-5 w-16 bg-[#dedbd6]/40 rounded animate-pulse" />
      </div>
      <div className="space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-[#dedbd6]/40 animate-pulse flex-shrink-0" />
            <div className="w-8 h-8 rounded-full bg-[#dedbd6]/40 animate-pulse flex-shrink-0" />
            <div className="flex-1 space-y-1">
              <div className="h-3 w-24 bg-[#dedbd6]/40 rounded animate-pulse" />
              <div className="h-3 w-16 bg-[#dedbd6]/30 rounded animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ----- User row ---------------------------------------------------------

function UserRow({ user }: { user: UserPresenceState }) {
  const dot   = getStatusDot(user.status);
  const avatarBg   = getAvatarBg(user.name);
  const avatarText = getAvatarText(user.name);
  const pageLabel  = getPageLabel(user.page);
  const initial    = user.name.charAt(0).toUpperCase();

  return (
    <div className="flex items-center gap-3 py-1">
      {/* Status dot */}
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className="flex-shrink-0 w-2 h-2 rounded-full"
            style={{ backgroundColor: dot.color }}
            aria-label={dot.title}
          />
        </TooltipTrigger>
        <TooltipContent side="top" className="text-[12px]">
          {dot.title}
        </TooltipContent>
      </Tooltip>

      {/* Avatar */}
      <div
        className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold select-none"
        style={{ backgroundColor: avatarBg, color: avatarText }}
      >
        {initial}
      </div>

      {/* Name + role + page */}
      <div className="flex-1 min-w-0 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[13px] font-medium text-[#111111] truncate">
            {user.name}
          </span>
          <Badge
            variant="outline"
            className={
              user.role === "admin"
                ? "text-[11px] border-violet-200 text-violet-600 bg-violet-50 px-1.5 py-0"
                : "text-[11px] border-blue-200 text-blue-600 bg-blue-50 px-1.5 py-0"
            }
          >
            {user.role === "admin" ? "Admin" : "Vendedor"}
          </Badge>
        </div>

        {/* Current page */}
        <span
          className="text-[13px] text-[#7b7b78] truncate max-w-[120px]"
          title={user.page ?? undefined}
        >
          {pageLabel}
        </span>
      </div>
    </div>
  );
}

// ----- Section ----------------------------------------------------------

export function OnlineUsersSection() {
  const { users, loading } = usePresence();

  if (loading) {
    return <div className="mb-8"><PresenceSkeleton /></div>;
  }

  const onlineCount = users.filter((u) => u.status === "online").length;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="mb-8">
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
              Equipe Online
            </p>
            <Badge
              variant="outline"
              className="text-[11px] border-[#dedbd6] text-[#7b7b78] bg-transparent"
            >
              {onlineCount} de {users.length} online
            </Badge>
          </div>

          {/* User list */}
          <div className="space-y-1">
            {users.map((user) => (
              <UserRow key={user.email} user={user} />
            ))}
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
