"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import type { MessageTemplate } from "@/lib/types";

// ─── Config ────────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; colorClass: string }> = {
  approved:                { label: "Aprovado",       colorClass: "bg-[#e6faf0] text-[#1a7a3a]" },
  pending:                 { label: "Pendente",       colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  pending_category_review: { label: "Em revisão",     colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

const BUTTON_TYPE_LABEL: Record<string, string> = {
  QUICK_REPLY:   "Resposta rápida",
  URL:           "Link",
  PHONE_NUMBER:  "Telefone",
  COPY_CODE:     "Copiar código",
};

// ─── Media placeholder ─────────────────────────────────────────────────────────

function MediaPlaceholder({ type }: { type: string }) {
  const configs = {
    IMAGE:    { icon: "🖼", label: "Imagem",   bg: "#f0f2f5" },
    VIDEO:    { icon: "▶",  label: "Vídeo",    bg: "#f0f2f5" },
    DOCUMENT: { icon: "📄", label: "Documento", bg: "#f0f2f5" },
  } as Record<string, { icon: string; label: string; bg: string }>;

  const cfg = configs[type] ?? { icon: "📎", label: type, bg: "#f0f2f5" };

  return (
    <div
      className="flex flex-col items-center justify-center gap-1 rounded-xl mx-1 mt-1"
      style={{ backgroundColor: cfg.bg, height: 120 }}
    >
      <span style={{ fontSize: 28, lineHeight: 1 }}>{cfg.icon}</span>
      <span className="text-[11px] text-[#8696a0]">{cfg.label}</span>
    </div>
  );
}

// ─── Body renderer ─────────────────────────────────────────────────────────────

function BodyWithVars({ body }: { body: string }) {
  const segments = body.split(/(\{\{[\w]+\}\})/g).filter((s) => s !== "");
  return (
    <p className="text-[14px] leading-relaxed whitespace-pre-wrap" style={{ color: "#111b21" }}>
      {segments.map((seg, i) =>
        /^\{\{[\w]+\}\}$/.test(seg) ? (
          <span
            key={i}
            className="inline-flex items-center px-1 rounded text-[12px] font-mono font-semibold"
            style={{ color: "#c2590a", background: "rgba(194,89,10,0.08)" }}
          >
            {seg}
          </span>
        ) : (
          <span key={i}>{seg}</span>
        )
      )}
    </p>
  );
}

// ─── WhatsApp bubble ───────────────────────────────────────────────────────────

function MessageBubble({ template }: { template: MessageTemplate }) {
  const hasContent = template.body || template.header || (template.buttons && template.buttons.length > 0);

  if (!hasContent) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-[12px]" style={{ color: "#8696a0" }}>Conteúdo não disponível</p>
      </div>
    );
  }

  return (
    <div className="flex justify-end">
      <div className="max-w-[88%] min-w-[60%]">
        {/* Bubble */}
        <div
          className="rounded-2xl rounded-tr-none overflow-hidden"
          style={{
            background: "#ffffff",
            boxShadow: "0 1px 2px rgba(11,20,26,0.13)",
          }}
        >
          {/* Media header */}
          {template.header && template.header.type !== "TEXT" && (
            <MediaPlaceholder type={template.header.type} />
          )}

          <div className="px-3 pt-2 pb-1">
            {/* Text header */}
            {template.header?.type === "TEXT" && template.header.text && (
              <p className="text-[14px] font-bold mb-1" style={{ color: "#111b21" }}>
                {template.header.text}
              </p>
            )}

            {/* Body */}
            {template.body && <BodyWithVars body={template.body} />}

            {/* Footer */}
            {template.footer && (
              <p className="text-[12px] mt-1" style={{ color: "#8696a0" }}>
                {template.footer}
              </p>
            )}

            {/* Timestamp ghost */}
            <div className="flex justify-end mt-1">
              <span className="text-[11px]" style={{ color: "#8696a0" }}>{"✓✓"}</span>
            </div>
          </div>

          {/* Buttons — separated by line, inside bubble */}
          {template.buttons && template.buttons.length > 0 && (
            <div style={{ borderTop: "1px solid #e9edef" }}>
              {template.buttons.map((btn, i) => (
                <div
                  key={i}
                  className="flex items-center justify-center gap-1.5 py-2.5"
                  style={{
                    borderTop: i > 0 ? "1px solid #e9edef" : undefined,
                    color: "#009de2",
                  }}
                >
                  {btn.type === "URL" && (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                    </svg>
                  )}
                  {btn.type === "PHONE_NUMBER" && (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.4 2 2 0 0 1 3.59 1h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.56a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
                    </svg>
                  )}
                  {btn.type === "COPY_CODE" && (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
                    </svg>
                  )}
                  {btn.type === "QUICK_REPLY" && (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
                    </svg>
                  )}
                  <span className="text-[13px] font-medium">{btn.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Bubble tail */}
        <div className="flex justify-end -mt-px pr-0">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path d="M0 0 Q10 0 10 10 L0 10 Z" fill="#ffffff" />
          </svg>
        </div>
      </div>
    </div>
  );
}

// ─── Props ─────────────────────────────────────────────────────────────────────

interface TemplateDetailSheetProps {
  template: MessageTemplate | null;
  onClose: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function TemplateDetailSheet({ template, onClose }: TemplateDetailSheetProps) {
  const cat = CATEGORY_CONFIG[(template?.category ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st  = STATUS_CONFIG[template?.status ?? ""] ?? STATUS_CONFIG.cancelled;

  return (
    <Sheet open={template !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent
        className="flex flex-col gap-0 p-0 border-l border-[#dedbd6]"
        style={{ width: 460, maxWidth: "90vw" }}
      >
        {template && (
          <>
            {/* ── Header ── */}
            <SheetHeader className="flex-shrink-0 px-5 pt-5 pb-4 border-b border-[#dedbd6] bg-white">
              <SheetTitle className="text-[13px] font-mono font-medium text-[#111111] leading-snug break-all pr-6">
                {template.name}
              </SheetTitle>
              <SheetDescription className="sr-only">
                Detalhes do template {template.name}
              </SheetDescription>
              <div className="flex flex-wrap items-center gap-1.5 pt-2">
                <Badge
                  className="rounded-[4px] border-0 h-auto text-[10px] font-semibold uppercase tracking-[0.4px] px-2 py-0.5"
                  style={{ color: cat.color, backgroundColor: cat.bg }}
                >
                  {cat.label}
                </Badge>
                <Badge className={`rounded-[4px] border-0 h-auto text-[10px] font-semibold uppercase tracking-[0.4px] px-2 py-0.5 ${st.colorClass}`}>
                  {st.label}
                </Badge>
                <Badge
                  variant="outline"
                  className="rounded-[4px] h-auto text-[10px] font-normal px-2 py-0.5 text-[#7b7b78] border-[#dedbd6]"
                >
                  {template.language}
                </Badge>
              </div>
            </SheetHeader>

            {/* ── Scrollable body ── */}
            <div className="flex-1 overflow-y-auto">

              {/* WhatsApp preview area */}
              <div
                className="px-5 py-5"
                style={{
                  background: "#e5ddd5",
                  backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c8bfb5' fill-opacity='0.18'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
                }}
              >
                <p className="text-[10px] uppercase tracking-[0.7px] mb-3" style={{ color: "#7b7b78" }}>
                  Prévia
                </p>
                <MessageBubble template={template} />
              </div>

              {/* ── Variables section ── */}
              {template.params && template.params.length > 0 && (
                <div className="px-5 py-4 border-t border-[#f0ede8]">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-[10px] uppercase tracking-[0.7px] text-[#7b7b78] font-medium">
                      Variáveis
                    </span>
                    <span
                      className="text-[10px] font-semibold tabular-nums rounded-full px-1.5 py-0"
                      style={{ background: "#f0ede8", color: "#7b7b78" }}
                    >
                      {template.params.length}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {template.params.map((p) => {
                      const label = template.paramsType === "positional"
                        ? `{{${p.index}}}`
                        : `{{${p.paramName}}}`;
                      return (
                        <div
                          key={p.paramName}
                          className="flex items-center justify-between gap-3 rounded-[6px] px-3 py-2"
                          style={{ background: "#faf9f6", border: "1px solid #f0ede8" }}
                        >
                          <span
                            className="text-[12px] font-mono font-semibold flex-shrink-0"
                            style={{ color: "#c2590a" }}
                          >
                            {label}
                          </span>
                          {p.example ? (
                            <span
                              className="text-[12px] text-right truncate"
                              style={{ color: "#7b7b78" }}
                              title={p.example}
                            >
                              {p.example}
                            </span>
                          ) : (
                            <span className="text-[11px] italic" style={{ color: "#b0aca6" }}>
                              sem exemplo
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* ── Buttons section ── */}
              {template.buttons && template.buttons.length > 0 && (
                <div className="px-5 py-4 border-t border-[#f0ede8]">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-[10px] uppercase tracking-[0.7px] text-[#7b7b78] font-medium">
                      Botões
                    </span>
                    <span
                      className="text-[10px] font-semibold tabular-nums rounded-full px-1.5 py-0"
                      style={{ background: "#f0ede8", color: "#7b7b78" }}
                    >
                      {template.buttons.length}
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {template.buttons.map((btn, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between rounded-[6px] px-3 py-2"
                        style={{ background: "#faf9f6", border: "1px solid #f0ede8" }}
                      >
                        <span className="text-[13px] font-medium" style={{ color: "#111111" }}>
                          {btn.text}
                        </span>
                        <span
                          className="text-[10px] uppercase tracking-[0.4px] font-medium ml-3 flex-shrink-0"
                          style={{ color: "#7b7b78" }}
                        >
                          {BUTTON_TYPE_LABEL[btn.type] ?? btn.type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Bottom padding */}
              <div className="h-4" />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
