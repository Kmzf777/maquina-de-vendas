"use client";

import React from "react";

// ─── Types (must match route.ts output) ───────────────────────────────────────

interface TemplateParam {
  index: number;
  paramName: string;
  example: string;
}

interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
}

// ─── Token options ────────────────────────────────────────────────────────────

const LEAD_TOKENS = [
  { value: "{{primeiro_nome}}", label: "Primeiro nome" },
  { value: "{{nome_completo}}", label: "Nome completo" },
  { value: "{{telefone}}", label: "Telefone" },
  { value: "{{empresa}}", label: "Empresa" },
] as const;

type TokenValue = (typeof LEAD_TOKENS)[number]["value"];
const KNOWN_TOKENS = new Set<string>(LEAD_TOKENS.map((t) => t.value));

// ─── Category config ──────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function autoSuggestToken(example: string): string {
  if (!example) return "";
  if (/^[\d\s\-\(\)\+]+$/.test(example) && example.replace(/\D/g, "").length >= 8) {
    return "{{telefone}}";
  }
  if (!example.includes(" ")) return "{{primeiro_nome}}";
  if (example.trim().split(/\s+/).length <= 3) return "{{nome_completo}}";
  return "";
}

function resolvePreview(value: string): string {
  const token = LEAD_TOKENS.find((t) => t.value === value);
  if (token) return `[${token.label}]`;
  return value || "…";
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface TemplatePreviewCardProps {
  template: MetaTemplate;
  varValues: Record<string, string>;
  onVarChange: (paramName: string, value: string) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function TemplatePreviewCard({
  template,
  varValues,
  onVarChange,
}: TemplatePreviewCardProps) {
  const cat =
    CATEGORY_CONFIG[template.category?.toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const hasMediaHeader =
    template.header !== null && template.header.type !== "TEXT";
  const headerUrl = varValues["__header_url__"] ?? "";

  // ── Body preview with inline variable substitution ─────────────────────────
  const renderBody = () => {
    const parts: React.ReactNode[] = [];
    const raw = template.body ?? "";
    // Split on {{word}} or {{N}} patterns
    const segments = raw.split(/(\{\{[\w]+\}\})/g);
    let paramIdx = 0;

    for (const seg of segments) {
      if (/^\{\{[\w]+\}\}$/.test(seg)) {
        const param = template.params[paramIdx];
        const paramName = param?.paramName ?? seg.slice(2, -2);
        const val = varValues[paramName] ?? "";
        const preview = resolvePreview(val);
        parts.push(
          <span
            key={`p-${paramIdx}`}
            className={`inline-flex items-center px-1 rounded text-[12px] font-medium ${
              val
                ? "text-[#7a5a00] bg-[#fff8e0]"
                : "text-[#c41c1c] bg-[#fef0f0]"
            }`}
          >
            {preview}
          </span>
        );
        paramIdx++;
      } else {
        parts.push(seg);
      }
    }
    return parts;
  };

  // ── Token picker per variable slot ─────────────────────────────────────────
  const renderSlot = (param: TemplateParam) => {
    const val = varValues[param.paramName] ?? "";
    const isToken = KNOWN_TOKENS.has(val);
    const selectVal: string = isToken ? val : "texto_fixo";
    const slotLabel =
      template.paramsType === "positional"
        ? `{{${param.index}}}`
        : `{{${param.paramName}}}`;

    return (
      <div key={param.paramName} className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[#7b7b78] font-mono w-20 flex-shrink-0 truncate">
            {slotLabel}
          </span>
          <select
            value={selectVal}
            onChange={(e) => {
              const mode = e.target.value;
              if (mode !== "texto_fixo") {
                onVarChange(param.paramName, mode as TokenValue);
              } else {
                onVarChange(param.paramName, "");
              }
            }}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
          >
            {LEAD_TOKENS.map((t) => (
              <option key={t.value} value={t.value}>
                ⚡ {t.label}
              </option>
            ))}
            <option value="texto_fixo">✏ Texto fixo</option>
          </select>
        </div>

        {selectVal === "texto_fixo" && (
          <div className="pl-[88px]">
            <input
              value={val}
              onChange={(e) => onVarChange(param.paramName, e.target.value)}
              placeholder={
                param.example ? `Ex: ${param.example}` : "Digite o texto..."
              }
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
            />
          </div>
        )}
      </div>
    );
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[#faf9f6] border-b border-[#dedbd6]">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
          style={{ color: cat.color, backgroundColor: cat.bg }}
        >
          {cat.label}
        </span>
        <span className="text-[12px] text-[#7b7b78] truncate">{template.name}</span>
        <span className="text-[10px] text-[#b0aca6] ml-auto">{template.language}</span>
      </div>

      {/* Media header URL input */}
      {hasMediaHeader && (
        <div className="px-4 pt-3 pb-2 border-b border-[#f0ede8]">
          <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
            URL da mídia ({template.header!.type.toLowerCase()}){" "}
            <span className="text-[#c41c1c]">*</span>
          </label>
          <input
            value={headerUrl}
            onChange={(e) => onVarChange("__header_url__", e.target.value)}
            placeholder={template.header!.example ?? "https://..."}
            className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1.5 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
          />
          {headerUrl && template.header!.type === "IMAGE" && (
            <div className="mt-2 rounded-[4px] overflow-hidden bg-[#f0ede8] h-20 flex items-center justify-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={headerUrl}
                alt="preview"
                className="h-full w-full object-cover"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
              />
            </div>
          )}
          {headerUrl && template.header!.type !== "IMAGE" && (
            <p className="mt-1 text-[12px] text-[#1a7a3a]">
              {template.header!.type === "VIDEO" ? "🎥" : "📄"} URL de{" "}
              {template.header!.type.toLowerCase()} configurada.
            </p>
          )}
        </div>
      )}

      {/* TEXT header */}
      {template.header?.type === "TEXT" && template.header.text && (
        <div className="px-4 pt-3 pb-1">
          <p className="text-[14px] font-semibold text-[#111111]">
            {template.header.text}
          </p>
        </div>
      )}

      {/* Body preview */}
      <div className="px-4 py-3 bg-white">
        <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
          {renderBody()}
        </p>
      </div>

      {/* Footer */}
      {template.footer && (
        <div className="px-4 pb-2">
          <p className="text-[12px] text-[#7b7b78] italic">{template.footer}</p>
        </div>
      )}

      {/* Buttons */}
      {template.buttons && template.buttons.length > 0 && (
        <div className="px-4 pb-3 flex flex-wrap gap-1.5">
          {template.buttons.map((btn, i) => (
            <span
              key={i}
              className="text-[12px] text-[#7b7b78] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-[#faf9f6]"
            >
              {btn.text}
            </span>
          ))}
        </div>
      )}

      {/* Variable slots */}
      {template.params.length > 0 && (
        <div className="px-4 pb-3 pt-2 border-t border-[#f0ede8] space-y-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Variáveis da mensagem
          </p>
          {template.params.map(renderSlot)}
        </div>
      )}
    </div>
  );
}
