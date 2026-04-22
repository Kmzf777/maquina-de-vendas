"use client";

import { useState, useRef, useEffect } from "react";

interface EditableFieldProps {
  label: string;
  value: string | null;
  onSave: (value: string) => void;
  placeholder?: string;
  mask?: "currency";
}

export function EditableField({ label, value, onSave, placeholder, mask }: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function handleSave() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed !== (value || "")) {
      onSave(trimmed);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSave();
    if (e.key === "Escape") {
      setDraft(value || "");
      setEditing(false);
    }
  }

  const displayValue = mask === "currency" && value
    ? `R$ ${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`
    : value;

  return (
    <div>
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">
        {label}
      </span>
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
        />
      ) : (
        <button
          onClick={() => { setDraft(value || ""); setEditing(true); }}
          className="text-[14px] text-[#111111] hover:bg-[#dedbd6]/30 px-2 py-0.5 rounded-[4px] -ml-2 transition-colors w-full text-left min-h-[28px]"
        >
          {displayValue || <span className="text-[#7b7b78] italic text-[13px]">{placeholder || "Clique para editar"}</span>}
        </button>
      )}
    </div>
  );
}
