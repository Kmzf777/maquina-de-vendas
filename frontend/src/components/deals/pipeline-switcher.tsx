"use client";

import { useState, useRef, useEffect } from "react";
import type { Pipeline } from "@/lib/types";

interface PipelineSwitcherProps {
  pipelines: Pipeline[];
  activePipelineId: string | null;
  isAdmin: boolean;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
  onEdit: () => void;
  onDelete: (pipeline: Pipeline) => void;
}

export function PipelineSwitcher({
  pipelines, activePipelineId, isAdmin, onSelect, onCreateNew, onEdit, onDelete,
}: PipelineSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const dropdownRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const activePipeline = pipelines.find((p) => p.id === activePipelineId);

  useEffect(() => {
    if (!isAdmin) return;
    fetch("/api/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: { id: string; name: string }[]) =>
        setNames(Object.fromEntries(list.map((u) => [u.id, u.name]))))
      .catch(() => setNames({}));
  }, [isAdmin]);

  function ownerLabel(p: Pipeline): string | null {
    if (!isAdmin) return null;
    if (p.is_universal) return "Universal";
    if (!p.owner_user_id) return "Administrativo";
    return names[p.owner_user_id] ?? "—";
  }

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
        setOpen(false);
      if (menuRef.current && !menuRef.current.contains(e.target as Node))
        setMenuOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Funil</p>
      <div className="flex items-center gap-2">
        {/* Dropdown trigger */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 group"
          >
            <h1
              style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
              className="text-[32px] font-normal text-[#111111] hover:text-[#7b7b78] transition-colors"
            >
              {activePipeline?.name ?? "Selecionar funil"}
            </h1>
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="#7b7b78"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`mt-1 transition-transform ${open ? "rotate-180" : ""}`}
            >
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>

          {open && (
            <div className="absolute top-full left-0 mt-2 bg-white border border-[#dedbd6] rounded-[8px] shadow-sm z-50 min-w-[220px] py-1">
              {pipelines.map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    onSelect(p.id);
                    setOpen(false);
                  }}
                  className={`w-full text-left px-4 py-2.5 text-[13px] transition-colors flex items-center justify-between ${
                    p.id === activePipelineId
                      ? "text-[#111111] bg-[#faf9f6]"
                      : "text-[#313130] hover:bg-[#faf9f6]"
                  }`}
                >
                  <span className="flex flex-col">
                    <span>{p.name}</span>
                    {ownerLabel(p) && (
                      <span className="text-[11px] text-[#7b7b78]">{ownerLabel(p)}</span>
                    )}
                  </span>
                  {p.id === activePipelineId && (
                    <svg
                      width="14"
                      height="14"
                      fill="none"
                      viewBox="0 0 16 16"
                      stroke="#111111"
                      strokeWidth="2"
                      strokeLinecap="round"
                    >
                      <path d="M3 8l4 4 6-6" />
                    </svg>
                  )}
                </button>
              ))}
              <div className="border-t border-[#dedbd6] mt-1 pt-1">
                <button
                  onClick={() => {
                    onCreateNew();
                    setOpen(false);
                  }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#7b7b78] hover:bg-[#faf9f6] transition-colors flex items-center gap-2"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  >
                    <line x1="8" y1="3" x2="8" y2="13" />
                    <line x1="3" y1="8" x2="13" y2="8" />
                  </svg>
                  Novo Funil
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ⋯ menu */}
        {activePipeline && (
          <div className="relative mt-2" ref={menuRef}>
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="w-7 h-7 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <circle cx="8" cy="3" r="1.2" />
                <circle cx="8" cy="8" r="1.2" />
                <circle cx="8" cy="13" r="1.2" />
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute top-full left-0 mt-1 bg-white border border-[#dedbd6] rounded-[8px] shadow-sm z-50 min-w-[160px] py-1">
                <button
                  onClick={() => {
                    onEdit();
                    setMenuOpen(false);
                  }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#313130] hover:bg-[#faf9f6] transition-colors"
                >
                  Editar Funil
                </button>
                <button
                  onClick={() => {
                    onDelete(activePipeline);
                    setMenuOpen(false);
                  }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#e07a7a] hover:bg-[#faf9f6] transition-colors"
                >
                  Excluir Funil
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
