"use client";

import { AGENT_STAGES } from "@/lib/constants";
import { usePipelines, usePipelineStages } from "@/hooks/use-pipelines";
import type { SearchTab } from "@/lib/universal-search";
import type { UniversalSearchFilters } from "@/hooks/use-universal-search";

const inputClass =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none";
const selectClass = `${inputClass} cursor-pointer`;

interface SearchFiltersBarProps {
  tab: SearchTab;
  filters: UniversalSearchFilters;
  onChange: (filters: UniversalSearchFilters) => void;
}

/** Filtros adaptativos por aba: período em todas, + segmento/funil/etapa/documentos conforme a entidade. */
export function SearchFiltersBar({ tab, filters, onChange }: SearchFiltersBarProps) {
  const { pipelines } = usePipelines();
  const { stages } = usePipelineStages(filters.pipelineId || null);

  const showLeadStage = tab === "leads";
  const showPipelineStage = tab === "deals";
  const showDocsOnly = tab === "conversations";

  function update(patch: Partial<UniversalSearchFilters>) {
    onChange({ ...filters, ...patch });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 py-3">
      <input
        type="date"
        value={filters.dateFrom}
        onChange={(e) => update({ dateFrom: e.target.value })}
        className={inputClass}
        aria-label="Data inicial"
      />
      <span className="text-[13px] text-[#7b7b78]">até</span>
      <input
        type="date"
        value={filters.dateTo}
        onChange={(e) => update({ dateTo: e.target.value })}
        className={inputClass}
        aria-label="Data final"
      />

      {showLeadStage && (
        <select
          value={filters.leadStage}
          onChange={(e) => update({ leadStage: e.target.value })}
          className={selectClass}
          aria-label="Segmento do lead"
        >
          <option value="">Todos os segmentos</option>
          {AGENT_STAGES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      )}

      {showPipelineStage && (
        <>
          <select
            value={filters.pipelineId}
            onChange={(e) => update({ pipelineId: e.target.value, stageId: "" })}
            className={selectClass}
            aria-label="Funil"
          >
            <option value="">Todos os funis</option>
            {pipelines.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={filters.stageId}
            onChange={(e) => update({ stageId: e.target.value })}
            disabled={!filters.pipelineId}
            className={`${selectClass} disabled:opacity-40 disabled:cursor-not-allowed`}
            aria-label="Etapa do funil"
          >
            <option value="">Todas as etapas</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </>
      )}

      {showDocsOnly && (
        <label className="flex items-center gap-1.5 text-[13px] text-[#111111] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={filters.docsOnly}
            onChange={(e) => update({ docsOnly: e.target.checked })}
            className="cursor-pointer accent-[#ff5600]"
          />
          Só documentos/mídia
        </label>
      )}
    </div>
  );
}
