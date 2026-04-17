"use client";

import { useState, useEffect } from "react";
import type { CadenceStep } from "@/lib/types";

interface CadenceStepsTableProps {
  cadenceId: string;
}

const cumulativeDays = (steps: CadenceStep[], index: number): number =>
  steps.slice(0, index + 1).reduce((sum, s, i) => (i === 0 ? 0 : sum + steps[i].delay_days), 0);

export function CadenceStepsTable({ cadenceId }: CadenceStepsTableProps) {
  const [steps, setSteps] = useState<CadenceStep[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editDelay, setEditDelay] = useState(0);
  const [newText, setNewText] = useState("");
  const [newDelay, setNewDelay] = useState(1);

  useEffect(() => {
    fetch(`/api/cadences/${cadenceId}/steps`)
      .then((r) => r.json())
      .then((d) => setSteps(d.data || d));
  }, [cadenceId]);

  const handleSave = async (stepId: string) => {
    await fetch(`/api/cadences/${cadenceId}/steps/${stepId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_text: editText, delay_days: editDelay }),
    });
    setSteps(steps.map((s) => s.id === stepId ? { ...s, message_text: editText, delay_days: editDelay } : s));
    setEditingId(null);
  };

  const handleAdd = async () => {
    const res = await fetch(`/api/cadences/${cadenceId}/steps`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ step_order: steps.length + 1, message_text: newText, delay_days: newDelay }),
    });
    const step = await res.json();
    setSteps([...steps, step.data || step]);
    setNewText("");
    setNewDelay(1);
  };

  const handleDelete = async (stepId: string) => {
    await fetch(`/api/cadences/${cadenceId}/steps/${stepId}`, { method: "DELETE" });
    setSteps(steps.filter((s) => s.id !== stepId));
  };

  const startEdit = (step: CadenceStep) => {
    setEditingId(step.id);
    setEditText(step.message_text);
    setEditDelay(step.delay_days);
  };

  return (
    <div className="space-y-0">
      {steps.map((step, index) => (
        <div key={step.id}>
          {/* Step row: dot + card */}
          <div className="flex gap-4">
            {/* Vertical line + dot */}
            <div className="flex flex-col items-center flex-shrink-0 w-6">
              <div className="w-3 h-3 rounded-full bg-[#111111] mt-1.5 flex-shrink-0" />
              {index < steps.length - 1 && <div className="w-px bg-[#dedbd6] flex-1 mt-1 mb-0" />}
            </div>
            {/* Step card */}
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 mb-2 flex-1">
              <div className="flex justify-between items-start mb-2">
                <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Step {step.step_order}</span>
                <span className="text-[11px] text-[#7b7b78]">Dia {cumulativeDays(steps, index)}</span>
              </div>
              {editingId === step.id ? (
                // Edit mode
                <div className="space-y-3">
                  <textarea value={editText} onChange={e => setEditText(e.target.value)}
                    className="w-full bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none resize-none min-h-[80px]" />
                  <div className="flex items-center gap-2">
                    <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Delay (dias):</label>
                    <input type="number" value={editDelay} onChange={e => setEditDelay(Number(e.target.value))}
                      className="w-16 bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleSave(step.id)} className="bg-[#111111] text-white px-3 py-1.5 rounded-[4px] text-[13px] hover:scale-110 transition-transform active:scale-[0.85]">Salvar</button>
                    <button onClick={() => setEditingId(null)} className="border border-[#dedbd6] text-[#7b7b78] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] hover:text-[#111111]">Cancelar</button>
                  </div>
                </div>
              ) : (
                // View mode
                <div>
                  <p className="text-[14px] text-[#111111] leading-relaxed">{step.message_text}</p>
                  <div className="flex gap-3 mt-3">
                    <button onClick={() => startEdit(step)} className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors">Editar</button>
                    <button onClick={() => handleDelete(step.id)} className="text-[13px] text-[#c41c1c] hover:text-[#c41c1c]/70 transition-colors">Remover</button>
                  </div>
                </div>
              )}
            </div>
          </div>
          {/* Delay connector between steps */}
          {index < steps.length - 1 && (
            <div className="flex items-center gap-2 ml-10 mb-2">
              <div className="h-px flex-1 border-t border-dashed border-[#dedbd6]" />
              <span className="text-[11px] text-[#7b7b78] whitespace-nowrap flex-shrink-0">
                + {steps[index + 1].delay_days} dia{steps[index + 1].delay_days !== 1 ? "s" : ""}
              </span>
              <div className="h-px flex-1 border-t border-dashed border-[#dedbd6]" />
            </div>
          )}
        </div>
      ))}

      {/* Add step form */}
      <div className="mt-4 bg-[#f7f5f1] border border-dashed border-[#dedbd6] rounded-[8px] p-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Adicionar Step</p>
        <textarea value={newText} onChange={e => setNewText(e.target.value)} placeholder="Mensagem do step... Use {{nome}}, {{empresa}}"
          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none min-h-[80px] mb-3" />
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Delay (dias):</label>
            <input type="number" value={newDelay} onChange={e => setNewDelay(Number(e.target.value))}
              className="w-16 bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] focus:border-[#111111] focus:outline-none" />
          </div>
          <button onClick={handleAdd} disabled={!newText.trim()}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100">
            + Adicionar Step
          </button>
        </div>
      </div>
    </div>
  );
}
