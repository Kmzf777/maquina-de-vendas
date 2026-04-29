"use client";

import { useEffect, useState } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Variant = "compact" | "header" | "banner";
type State = "active" | "warning" | "critical" | "expired" | "none";

interface Props {
  expiresAt: string | null;
  variant: Variant;
  className?: string;
}

const TOOLTIP_TEXT =
  "Após 24h sem nova mensagem do lead, só é possível enviar templates aprovados pela Meta. Aguarde resposta ou use a aba de reativação.";

const computeState = (expiresAt: string | null): { state: State; minutesLeft: number } => {
  if (!expiresAt) return { state: "none", minutesLeft: 0 };
  const exp = new Date(expiresAt).getTime();
  if (isNaN(exp)) return { state: "none", minutesLeft: 0 };
  const minutesLeft = Math.floor((exp - Date.now()) / 60000);
  if (minutesLeft <= 0) return { state: "expired", minutesLeft: 0 };
  if (minutesLeft < 60) return { state: "critical", minutesLeft };
  if (minutesLeft < 240) return { state: "warning", minutesLeft };
  return { state: "active", minutesLeft };
};

const labelFor = (state: State, minutesLeft: number): string => {
  if (state === "expired") return "Janela expirada";
  if (state === "critical") return `${minutesLeft}min restantes`;
  if (state === "warning" || state === "active") {
    const hours = Math.floor(minutesLeft / 60);
    return `${hours}h restantes`;
  }
  return "";
};

// Design system tokens:
// active:   muted neutral — #7b7b78 (--color-muted)
// warning:  warm amber — amber tones (no cool gray)
// critical: Fin Orange (#ff5600) — brand accent, with pulse
// expired:  locked oat — #dedbd6 (--color-oat-border) dot, muted text

const dotClassFor = (state: State): string => {
  switch (state) {
    case "active":
      return "bg-[#7b7b78]";
    case "warning":
      return "bg-amber-500";
    case "critical":
      return "bg-[#ff5600] animate-pulse";
    case "expired":
      return "bg-[#dedbd6]";
    default:
      return "bg-[#dedbd6]";
  }
};

// Pill styles aligned to design system warm palette
const pillClassFor = (state: State): string => {
  switch (state) {
    case "active":
      return "bg-[#faf9f6] text-[#7b7b78] border-[#dedbd6]";
    case "warning":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "critical":
      // Fin Orange accent bg (very light warm orange), Fin Orange border
      return "bg-[#fff3ed] text-[#ff5600] border-[#ff5600]/30";
    case "expired":
      return "bg-[#faf9f6] text-[#7b7b78] border-[#dedbd6]";
    default:
      return "bg-[#faf9f6] text-[#7b7b78] border-[#dedbd6]";
  }
};

export function WhatsappWindowIndicator({ expiresAt, variant, className }: Props) {
  // Re-render a cada minuto para o countdown ficar vivo
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const { state, minutesLeft } = computeState(expiresAt);

  if (state === "none" && variant !== "banner") return null;

  if (variant === "compact") {
    return (
      <span className={cn("inline-flex items-center gap-1 text-xs text-[#7b7b78]", className)}>
        <span
          className={cn("inline-block h-1.5 w-1.5 rounded-full", dotClassFor(state))}
          aria-hidden
        />
        {state !== "active" && state !== "none" && (
          <span>{labelFor(state, minutesLeft)}</span>
        )}
      </span>
    );
  }

  if (variant === "header") {
    return (
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-[4px] border px-2 py-0.5 text-xs font-medium cursor-default",
                pillClassFor(state),
                className,
              )}
            >
              <span
                className={cn("inline-block h-1.5 w-1.5 rounded-full", dotClassFor(state))}
                aria-hidden
              />
              <span>{labelFor(state, minutesLeft) || "Janela 24h"}</span>
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="text-xs leading-relaxed">{TOOLTIP_TEXT}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // banner — only shown when expired
  if (state !== "expired") return null;
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-2 text-sm text-[#626260]",
        className,
      )}
      role="status"
    >
      <span className={cn("inline-block h-2 w-2 rounded-full", dotClassFor(state))} aria-hidden />
      <span className="font-medium text-[#111111]">Janela 24h expirada</span>
      <span className="text-[#7b7b78]">— só é possível enviar templates aprovados.</span>
    </div>
  );
}
