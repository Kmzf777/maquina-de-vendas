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
      <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">
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
          className="input-field text-[14px] rounded-lg px-2 py-1 w-full"
        />
      ) : (
        <button
          onClick={() => { setDraft(value || ""); setEditing(true); }}
          className="text-[14px] text-[#1f1f1f] hover:bg-[#f6f7ed] px-2 py-0.5 rounded -ml-2 transition-colors w-full text-left min-h-[28px]"
        >
          {displayValue || <span className="text-[#c8cc8e] italic">{placeholder || "Clique para editar"}</span>}
        </button>
      )}
    </div>
  );
}
