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
    <div className="space-y-4">
      <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
        <h3 style={{ letterSpacing: '-0.3px' }} className="text-[18px] font-medium text-[#111111] mb-4">Acionamento</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Tipo de trigger</label>
            <select
              value={targetType}
              onChange={(e) => {
                onChange("target_type", e.target.value);
                onChange("target_stage", null);
                onChange("stagnation_days", null);
              }}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
            >
              <option value="manual">Manual</option>
              <option value="lead_stage">Quando lead entra no stage</option>
              <option value="deal_stage">Quando deal entra no stage</option>
            </select>
          </div>

          {targetType !== "manual" && (
            <>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage</label>
                <select
                  value={targetStage || ""}
                  onChange={(e) => onChange("target_stage", e.target.value || null)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">Selecionar stage...</option>
                  {stages.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Dias parado no stage (opcional — vazio = imediato)
                </label>
                <input
                  type="number"
                  value={stagnationDays ?? ""}
                  onChange={(e) => onChange("stagnation_days", e.target.value ? Number(e.target.value) : null)}
                  placeholder="Ex: 3"
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
