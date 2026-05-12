"use client";

import React from "react";

const AUTO_VARS = new Set(["first_name", "primeiro_nome", "nome", "name", "phone"]);

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: string[];
  buttons?: { type: string; text: string }[];
}

interface TemplatePreviewCardProps {
  template: MetaTemplate;
  varValues: Record<string, string>;
  onVarChange: (paramName: string, value: string) => void;
}

export function TemplatePreviewCard({ template, varValues, onVarChange }: TemplatePreviewCardProps) {
  const cat = CATEGORY_CONFIG[template.category?.toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const manualParams = template.params.filter((p) => !AUTO_VARS.has(p.toLowerCase()));
  const autoParams = template.params.filter((p) => AUTO_VARS.has(p.toLowerCase()));

  const renderBody = () => {
    let idx = 0;
    const parts: React.ReactNode[] = [];
    const raw = template.body ?? "";
    const segments = raw.split(/(\{\{\d+\}\})/g);

    for (const seg of segments) {
      if (/^\{\{\d+\}\}$/.test(seg)) {
        const param = template.params[idx] ?? `var${idx + 1}`;
        const isAuto = AUTO_VARS.has(param.toLowerCase());
        const val = varValues[param];
        if (isAuto) {
          parts.push(
            <span key={idx} className="inline-flex items-center gap-0.5 px-1 rounded text-[12px] font-medium text-[#1a7a3a] bg-[#e6faf0]">
              ⚡ {param}
            </span>
          );
        } else {
          parts.push(
            <span key={idx} className={`inline-flex items-center px-1 rounded text-[12px] font-medium ${val ? "text-[#7a5a00] bg-[#fff8e0]" : "text-[#c41c1c] bg-[#fef0f0]"}`}>
              {val || `[${param}]`}
            </span>
          );
        }
        idx++;
      } else {
        parts.push(seg);
      }
    }
    return parts;
  };

  return (
    <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
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

      <div className="px-4 py-3 bg-white">
        <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
          {renderBody()}
        </p>
      </div>

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

      {autoParams.length > 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5">
          {autoParams.map((p) => (
            <span key={p} className="text-[11px] text-[#1a7a3a] bg-[#e6faf0] px-2 py-0.5 rounded-[4px] flex items-center gap-1">
              ⚡ <strong>{p}</strong> preenchido automaticamente do lead
            </span>
          ))}
        </div>
      )}

      {manualParams.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-[#f0ede8] space-y-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Preencher manualmente</p>
          {manualParams.map((p) => (
            <div key={p} className="flex items-center gap-2">
              <label className="text-[12px] text-[#111111] w-28 flex-shrink-0">{p}</label>
              <input
                value={varValues[p] ?? ""}
                onChange={(e) => onVarChange(p, e.target.value)}
                placeholder={`Valor de ${p}`}
                className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
