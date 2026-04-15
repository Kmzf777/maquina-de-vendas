"use client";

import { useState, useEffect } from "react";
import type { CadenceStep } from "@/lib/types";

interface CadenceStepsTableProps {
  cadenceId: string;
}

export function CadenceStepsTable({ cadenceId }: CadenceStepsTableProps) {
  const [steps, setSteps] = useState<CadenceStep[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editDelay, setEditDelay] = useState(0);
  const [newText, setNewText] = useState("");
  const [newDelay, setNewDelay] = useState(1);
  const [showAdd, setShowAdd] = useState(false);

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
    setShowAdd(false);
  };

  const handleDelete = async (stepId: string) => {
    await fetch(`/api/cadences/${cadenceId}/steps/${stepId}`, { method: "DELETE" });
    setSteps(steps.filter((s) => s.id !== stepId));
  };

  return (
    <div>
      <div className="bg-[#f4f4f0] rounded-xl overflow-hidden">
        <div className="grid grid-cols-[50px_1fr_100px_80px] gap-2 px-4 py-2 text-[11px] text-[#9ca3af] uppercase tracking-wider font-medium">
          <span>#</span>
          <span>Mensagem</span>
          <span>Delay</span>
          <span>Acoes</span>
        </div>

        {steps.map((step) => (
          <div key={step.id} className="grid grid-cols-[50px_1fr_100px_80px] gap-2 px-4 py-3 border-t border-[#e5e5dc] items-start">
            <span className="text-[14px] font-bold text-[#c8cc8e]">{step.step_order}</span>

            {editingId === step.id ? (
              <>
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="w-full px-2 py-1 rounded border border-[#e5e5dc] text-[13px] min-h-[60px]"
                />
                <input
                  type="number"
                  value={editDelay}
                  onChange={(e) => setEditDelay(Number(e.target.value))}
                  className="w-full px-2 py-1 rounded border border-[#e5e5dc] text-[13px]"
                />
                <div className="flex gap-1">
                  <button onClick={() => handleSave(step.id)} className="text-[11px] text-[#2d6a3f] font-medium">Salvar</button>
                  <button onClick={() => setEditingId(null)} className="text-[11px] text-[#5f6368]">Cancelar</button>
                </div>
              </>
            ) : (
              <>
                <p className="text-[13px] text-[#1f1f1f] whitespace-pre-wrap">{step.message_text}</p>
                <span className="text-[13px] text-[#5f6368]">
                  {step.delay_days === 0 ? "Imediato" : `${step.delay_days} dia${step.delay_days > 1 ? "s" : ""}`}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setEditingId(step.id); setEditText(step.message_text); setEditDelay(step.delay_days); }}
                    className="text-[11px] text-[#5b8aad] font-medium"
                  >
                    Editar
                  </button>
                  <button onClick={() => handleDelete(step.id)} className="text-[11px] text-[#a33] font-medium">
                    Remover
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {showAdd ? (
        <div className="mt-3 p-4 border border-dashed border-[#e5e5dc] rounded-xl space-y-3">
          <textarea
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            placeholder="Mensagem do step... (use {{nome}}, {{empresa}})"
            className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] min-h-[80px]"
          />
          <div className="flex items-center gap-3">
            <label className="text-[12px] text-[#5f6368]">Delay (dias):</label>
            <input type="number" value={newDelay} onChange={(e) => setNewDelay(Number(e.target.value))} className="w-20 px-2 py-1 rounded border border-[#e5e5dc] text-[13px]" />
            <button onClick={handleAdd} disabled={!newText} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white disabled:opacity-50">
              Adicionar
            </button>
            <button onClick={() => setShowAdd(false)} className="text-[12px] text-[#5f6368]">Cancelar</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} className="mt-3 w-full py-2 border border-dashed border-[#e5e5dc] rounded-xl text-[12px] text-[#5f6368] hover:bg-[#f6f7ed] transition-colors">
          + Adicionar step
        </button>
      )}
    </div>
  );
}
