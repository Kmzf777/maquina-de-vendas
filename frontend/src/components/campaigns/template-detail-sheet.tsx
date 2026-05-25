// frontend/src/components/campaigns/template-detail-sheet.tsx
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
  pending_category_review: { label: "Rev. categoria", colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

const HEADER_TYPE_LABEL: Record<string, string> = {
  TEXT: "Texto",
  IMAGE: "Imagem",
  VIDEO: "Vídeo",
  DOCUMENT: "Documento",
};

// ─── Body renderer ──────────────────────────────────────────────────────────────

function BodyWithVars({ body }: { body: string }) {
  const segments = body.split(/(\{\{[\w]+\}\})/g).filter((s) => s !== "");
  return (
    <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
      {segments.map((seg, i) =>
        /^\{\{[\w]+\}\}$/.test(seg) ? (
          <span
            key={i}
            className="inline-flex items-center px-1 rounded text-[12px] font-mono font-medium text-[#7a5a00] bg-[#fff8e0]"
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

// ─── Props ─────────────────────────────────────────────────────────────────────

interface TemplateDetailSheetProps {
  template: MessageTemplate | null;
  onClose: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function TemplateDetailSheet({ template, onClose }: TemplateDetailSheetProps) {
  const cat = CATEGORY_CONFIG[(template?.category ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = STATUS_CONFIG[template?.status ?? ""] ?? STATUS_CONFIG.cancelled;

  return (
    <Sheet open={template !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-[420px] sm:w-[480px] overflow-y-auto">
        {template && (
          <>
            <SheetHeader className="pb-4 border-b border-[#dedbd6]">
              <SheetTitle className="text-[16px] font-medium text-[#111111] leading-tight break-all">
                {template.name}
              </SheetTitle>
              <SheetDescription className="sr-only">
                Detalhes do template {template.name}
              </SheetDescription>
              <div className="flex flex-wrap gap-1.5 pt-1">
                <Badge
                  className="rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5"
                  style={{ color: cat.color, backgroundColor: cat.bg }}
                >
                  {cat.label}
                </Badge>
                <Badge className={`rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5 ${st.colorClass}`}>
                  {st.label}
                </Badge>
                <Badge
                  variant="outline"
                  className="rounded-[4px] h-auto text-[11px] font-normal px-2 py-0.5 text-[#7b7b78]"
                >
                  {template.language}
                </Badge>
              </div>
            </SheetHeader>

            <div className="py-4 space-y-5">

              {/* Header */}
              {template.header && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Cabeçalho · {HEADER_TYPE_LABEL[template.header.type] ?? template.header.type}
                  </p>
                  {template.header.type === "TEXT" && template.header.text ? (
                    <p className="text-[14px] font-semibold text-[#111111]">{template.header.text}</p>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-[13px] text-[#7b7b78] border border-[#dedbd6] px-2.5 py-1 rounded-[4px] bg-[#faf9f6]">
                      {template.header.type === "IMAGE" && "🖼"}
                      {template.header.type === "VIDEO" && "🎥"}
                      {template.header.type === "DOCUMENT" && "📄"}
                      Mídia {HEADER_TYPE_LABEL[template.header.type]?.toLowerCase()}
                    </span>
                  )}
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Body */}
              {template.body && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Corpo</p>
                  <BodyWithVars body={template.body} />
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Footer */}
              {template.footer && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Rodapé</p>
                  <p className="text-[13px] text-[#7b7b78] italic">{template.footer}</p>
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Variables */}
              {template.params && template.params.length > 0 && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Variáveis ({template.params.length})
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {template.params.map((p) => (
                      <div key={p.paramName} className="border border-[#dedbd6] rounded-[4px] px-2.5 py-1.5 bg-[#faf9f6]">
                        <span className="text-[12px] font-mono text-[#7a5a00]">
                          {template.paramsType === "positional" ? `{{${p.index}}}` : `{{${p.paramName}}}`}
                        </span>
                        {p.example && (
                          <span className="text-[11px] text-[#7b7b78] ml-2">ex: {p.example}</span>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Buttons */}
              {template.buttons && template.buttons.length > 0 && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Botões ({template.buttons.length})
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {template.buttons.map((btn, i) => (
                      <div key={i} className="border border-[#dedbd6] rounded-[4px] px-2.5 py-1.5 bg-[#faf9f6] flex items-center gap-1.5">
                        <span className="text-[10px] uppercase tracking-[0.5px] text-[#b0aca6]">{btn.type}</span>
                        <span className="text-[13px] text-[#111111]">{btn.text}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Empty content fallback */}
              {!template.body && !template.header && (!template.buttons || template.buttons.length === 0) && (
                <p className="text-[13px] text-[#7b7b78] text-center py-4">
                  Conteúdo não disponível para este template.
                </p>
              )}

            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
