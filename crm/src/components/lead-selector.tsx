"use client";

import { useState, useEffect, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import { AGENT_STAGES } from "@/lib/constants";
import type { Lead, Tag } from "@/lib/types";

interface LeadSelectorProps {
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
}

export function LeadSelector({ selectedIds, onSelectionChange }: LeadSelectorProps) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, Tag[]>>({});
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState<string[]>([]);
  const [tagFilter, setTagFilter] = useState<string[]>([]);

  const supabase = createClient();

  useEffect(() => {
    async function load() {
      const [leadsRes, tagsRes, ltRes] = await Promise.all([
        supabase.from("leads").select("*").order("created_at", { ascending: false }),
        supabase.from("tags").select("*"),
        supabase.from("lead_tags").select("lead_id, tag_id"),
      ]);

      if (leadsRes.data) setLeads(leadsRes.data);
      if (tagsRes.data) setTags(tagsRes.data);

      if (tagsRes.data && ltRes.data) {
        const map: Record<string, Tag[]> = {};
        ltRes.data.forEach((row: { lead_id: string; tag_id: string }) => {
          const tag = tagsRes.data!.find((t: Tag) => t.id === row.tag_id);
          if (tag) {
            if (!map[row.lead_id]) map[row.lead_id] = [];
            map[row.lead_id].push(tag);
          }
        });
        setLeadTagsMap(map);
      }

      setLoading(false);
    }
    load();
  }, []);

  const filtered = useMemo(() => {
    return leads.filter((l) => {
      if (stageFilter.length > 0 && !stageFilter.includes(l.stage)) return false;
      if (tagFilter.length > 0) {
        const lt = leadTagsMap[l.id] || [];
        if (!tagFilter.some((tid) => lt.some((t) => t.id === tid))) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        return (
          (l.name || "").toLowerCase().includes(q) ||
          (l.company || "").toLowerCase().includes(q) ||
          (l.nome_fantasia || "").toLowerCase().includes(q) ||
          l.phone.includes(q)
        );
      }
      return true;
    });
  }, [leads, stageFilter, tagFilter, search, leadTagsMap]);

  function toggleAll() {
    if (filtered.every((l) => selectedIds.has(l.id))) {
      const next = new Set(selectedIds);
      filtered.forEach((l) => next.delete(l.id));
      onSelectionChange(next);
    } else {
      const next = new Set(selectedIds);
      filtered.forEach((l) => next.add(l.id));
      onSelectionChange(next);
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectionChange(next);
  }

  const allSelected = filtered.length > 0 && filtered.every((l) => selectedIds.has(l.id));

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-8 justify-center">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <span className="text-[13px] text-[#5f6368]">Carregando leads...</span>
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <MultiSelect
          label="Stage"
          options={AGENT_STAGES.map((s) => ({ value: s.key, label: s.label }))}
          selected={stageFilter}
          onChange={setStageFilter}
        />
        <MultiSelect
          label="Tags"
          options={tags.map((t) => ({ value: t.id, label: t.name }))}
          selected={tagFilter}
          onChange={setTagFilter}
        />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar nome, telefone, empresa..."
          className="input-field text-[13px] w-52 ml-auto"
        />
      </div>

      {/* Table */}
      <div className="border border-[#ededea] rounded-xl overflow-hidden max-h-[340px] overflow-y-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-white z-10">
            <tr className="text-left border-b border-[#e5e5dc]">
              <th className="px-4 py-3 w-10">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  className="accent-[#1f1f1f]"
                />
              </th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Nome</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Telefone</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Stage</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Tags</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((l) => {
              const stageInfo = AGENT_STAGES.find((s) => s.key === l.stage);
              const lt = leadTagsMap[l.id] || [];

              return (
                <tr
                  key={l.id}
                  className="border-b border-[#ededea] last:border-0 hover:bg-[#f6f7ed]/50 transition-colors cursor-pointer"
                  onClick={() => toggleOne(l.id)}
                >
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(l.id)}
                      onChange={() => toggleOne(l.id)}
                      className="accent-[#1f1f1f]"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="px-4 py-2.5 text-[#1f1f1f] font-medium">{l.name || l.phone}</td>
                  <td className="px-4 py-2.5 text-[#5f6368]">{l.phone}</td>
                  <td className="px-4 py-2.5">
                    {stageInfo && (
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${stageInfo.color}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: stageInfo.dotColor }} />
                        {stageInfo.label}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-1 flex-wrap">
                      {lt.slice(0, 3).map((tag) => (
                        <span
                          key={tag.id}
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{ backgroundColor: tag.color + "20", color: tag.color }}
                        >
                          {tag.name}
                        </span>
                      ))}
                      {lt.length > 3 && (
                        <span className="text-[10px] text-[#9ca3af]">+{lt.length - 3}</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-[13px] text-[#9ca3af]">
                  Nenhum lead encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Counter */}
      <div className="mt-3 text-[12px] text-[#5f6368]">
        {selectedIds.size} lead{selectedIds.size !== 1 ? "s" : ""} selecionado{selectedIds.size !== 1 ? "s" : ""}
        {filtered.length > 0 && ` de ${filtered.length} filtrados`}
      </div>
    </div>
  );
}

/* Simple multi-select dropdown */
function MultiSelect({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);

  function toggle(value: string) {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors flex items-center gap-1.5 ${
          selected.length > 0
            ? "bg-[#1f1f1f] text-white"
            : "bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc]"
        }`}
      >
        {label}
        {selected.length > 0 && (
          <span className="bg-white/20 text-[10px] px-1.5 py-0.5 rounded-full">{selected.length}</span>
        )}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <polyline points="3 5 6 8 9 5" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-white border border-[#ededea] rounded-xl shadow-lg z-50 min-w-[180px] py-1 max-h-[200px] overflow-y-auto">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggle(opt.value)}
                className="w-full text-left px-3 py-2 text-[12px] hover:bg-[#f6f7ed] flex items-center gap-2 transition-colors"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  readOnly
                  className="accent-[#1f1f1f]"
                />
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
