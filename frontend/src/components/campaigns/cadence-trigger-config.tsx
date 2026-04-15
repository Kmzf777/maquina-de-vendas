"use client";

import { AGENT_STAGES, DEAL_STAGES } from "@/lib/constants";

interface CadenceTriggerConfigProps {
  targetType: string;
  targetStage: string | null;
  stagnationDays: number | null;
  onChange: (field: string, value: string | number | null) => void;
}

export function CadenceTriggerConfig({ targetType, targetStage, stagnationDays, onChange }: CadenceTriggerConfigProps) {
  const stages = targetType === "lead_stage"
    ? AGENT_STAGES.map((s) => ({ key: s.key, label: s.label }))
    : targetType === "deal_stage"
    ? DEAL_STAGES.map((s) => ({ key: s.key, label: s.label }))
    : [];

  return (
    <div className="space-y-3">
      <div>
        <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Tipo de trigger</label>
        <select
          value={targetType}
          onChange={(e) => {
            onChange("target_type", e.target.value);
            onChange("target_stage", null);
            onChange("stagnation_days", null);
          }}
          className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
        >
          <option value="manual">Manual</option>
          <option value="lead_stage">Quando lead entra no stage</option>
          <option value="deal_stage">Quando deal entra no stage</option>
        </select>
      </div>

      {targetType !== "manual" && (
        <>
          <div>
            <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Stage</label>
            <select
              value={targetStage || ""}
              onChange={(e) => onChange("target_stage", e.target.value || null)}
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
            >
              <option value="">Selecionar stage...</option>
              {stages.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>

          <div>
            <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">
              Dias parado no stage (opcional — vazio = imediato)
            </label>
            <input
              type="number"
              value={stagnationDays ?? ""}
              onChange={(e) => onChange("stagnation_days", e.target.value ? Number(e.target.value) : null)}
              placeholder="Ex: 3"
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
            />
          </div>
        </>
      )}
    </div>
  );
}
