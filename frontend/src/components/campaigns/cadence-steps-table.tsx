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
      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#dedbd6]">
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-12">#</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Mensagem</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-28">Delay</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-24">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => (
              <tr key={step.id} className="border-b border-[#dedbd6] hover:bg-[#faf9f6]">
                <td className="px-4 py-3 text-[14px] text-[#7b7b78]">{step.step_order}</td>

                {editingId === step.id ? (
                  <>
                    <td className="px-4 py-3">
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full min-h-[60px]"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <input
                        type="number"
                        value={editDelay}
                        onChange={(e) => setEditDelay(Number(e.target.value))}
                        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button onClick={() => handleSave(step.id)} className="text-[11px] text-[#0bdf50] uppercase tracking-[0.6px]">Salvar</button>
                        <button onClick={() => setEditingId(null)} className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Cancelar</button>
                      </div>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="px-4 py-3 text-[14px] text-[#111111] whitespace-pre-wrap">{step.message_text}</td>
                    <td className="px-4 py-3 text-[14px] text-[#7b7b78]">
                      {step.delay_days === 0 ? "Imediato" : `${step.delay_days} dia${step.delay_days > 1 ? "s" : ""}`}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          onClick={() => { setEditingId(step.id); setEditText(step.message_text); setEditDelay(step.delay_days); }}
                          className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px] hover:text-[#111111] transition-colors"
                        >
                          Editar
                        </button>
                        <button onClick={() => handleDelete(step.id)} className="text-[11px] text-[#c41c1c] uppercase tracking-[0.6px]">
                          Remover
                        </button>
                      </div>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd ? (
        <div className="mt-3 p-4 border border-dashed border-[#dedbd6] rounded-[8px] space-y-3">
          <textarea
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            placeholder="Mensagem do step... (use {{nome}}, {{empresa}})"
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full min-h-[80px]"
          />
          <div className="flex items-center gap-3">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Delay (dias):</label>
            <input type="number" value={newDelay} onChange={(e) => setNewDelay(Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-20" />
            <button onClick={handleAdd} disabled={!newText} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50">
              Adicionar
            </button>
            <button onClick={() => setShowAdd(false)} className="text-[14px] text-[#7b7b78] hover:text-[#111111] transition-colors">Cancelar</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} className="mt-3 w-full py-2 border border-dashed border-[#dedbd6] rounded-[8px] text-[14px] text-[#7b7b78] hover:bg-[#faf9f6] hover:border-[#111111] transition-colors">
          + Adicionar step
        </button>
      )}
    </div>
  );
}
