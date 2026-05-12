"use client";

import { useState, useEffect, useCallback } from "react";
import type { MessageTemplate } from "@/lib/types";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; style: string }> = {
  approved:                { label: "Aprovado",       style: "text-[#1a7a3a] bg-[#e6faf0]" },
  pending:                 { label: "Pendente",       style: "text-[#7a5a00] bg-[#fff8e0]" },
  pending_category_review: { label: "Rev. categoria", style: "text-[#7a5a00] bg-[#fff8e0]" },
  cancelled:               { label: "Cancelado",      style: "text-[#7b7b78] bg-[#f0ede8]" },
  rejected:                { label: "Rejeitado",      style: "text-[#c41c1c] bg-[#fef0f0]" },
};

export function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/templates");
    if (res.ok) setTemplates(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => { loadTemplates(); }, [loadTemplates]);

  // Poll only while there are pending templates
  useEffect(() => {
    const hasPending = templates.some(
      (t) => t.status === "pending" || t.status === "pending_category_review"
    );
    if (!hasPending) return;
    const id = setInterval(loadTemplates, 30_000);
    return () => clearInterval(id);
  }, [templates, loadTemplates]);

  const cat = (c: string | null) =>
    CATEGORY_CONFIG[(c ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = (s: string) => STATUS_CONFIG[s] ?? STATUS_CONFIG.pending;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2
          style={{ letterSpacing: "-0.3px" }}
          className="text-[20px] font-normal text-[#111111]"
        >
          Templates
        </h2>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          + Novo Template
        </button>
      </div>

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[8px] animate-pulse" />
          ))}
        </div>
      )}

      {!loading && templates.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum template cadastrado.</p>
          <button
            onClick={() => setShowCreate(true)}
            className="mt-3 text-[13px] text-[#111111] underline"
          >
            Criar primeiro template
          </button>
        </div>
      )}

      {!loading && templates.length > 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {["Nome", "Categoria", "Status", "Idioma", "Criado em"].map((h) => (
                  <th
                    key={h}
                    className="text-left text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] px-4 py-3 font-normal"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => {
                const c = cat(t.category);
                const s = st(t.status);
                return (
                  <tr
                    key={t.id}
                    className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]"
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#111111] font-medium">{t.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="text-[11px] font-medium px-2 py-0.5 rounded-[4px]"
                        style={{ color: c.color, backgroundColor: c.bg }}
                      >
                        {c.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded-[4px] ${s.style}`}>
                        {s.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">{t.language}</td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">
                      {new Date(t.created_at).toLocaleDateString("pt-BR")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <CreateTemplateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          loadTemplates();
        }}
      />
    </div>
  );
}
