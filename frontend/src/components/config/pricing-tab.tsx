"use client";

import { useState, useEffect } from "react";

const API_BASE = "";

interface ModelPrice {
  id: string;
  model: string;
  price_per_input_token: number;
  price_per_output_token: number;
  updated_at: string;
}

export function PricingTab() {
  const [models, setModels] = useState<ModelPrice[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Record<string, { input: string; output: string }>>({});

  useEffect(() => {
    fetch(`${API_BASE}/api/model-pricing`)
      .then((r) => r.json())
      .then((data) => {
        setModels(data.data);
        const initial: Record<string, { input: string; output: string }> = {};
        for (const m of data.data) {
          initial[m.model] = {
            input: (m.price_per_input_token * 1_000_000).toFixed(2),
            output: (m.price_per_output_token * 1_000_000).toFixed(2),
          };
        }
        setEditValues(initial);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleSave = async (model: string) => {
    const vals = editValues[model];
    if (!vals) return;

    setSaving(model);
    try {
      await fetch(`${API_BASE}/api/model-pricing/${model}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          price_per_input_token: parseFloat(vals.input) / 1_000_000,
          price_per_output_token: parseFloat(vals.output) / 1_000_000,
        }),
      });
      const res = await fetch(`${API_BASE}/api/model-pricing`);
      const data = await res.json();
      setModels(data.data);
    } catch (e) {
      console.error("Failed to save pricing:", e);
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] h-20 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-[14px] text-[#7b7b78] mb-4">
        Precos por 1M tokens (USD). Estes valores sao usados para calcular o custo de cada chamada ao agente.
      </p>

      {models.map((m) => (
        <div key={m.model} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[14px] font-normal text-[#111111]">
              {m.model}
            </h3>
            <span className="text-[11px] text-[#7b7b78]">
              Atualizado: {new Date(m.updated_at).toLocaleDateString("pt-BR")}
            </span>
          </div>

          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Input ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={editValues[m.model]?.input ?? ""}
                onChange={(e) =>
                  setEditValues((prev) => ({
                    ...prev,
                    [m.model]: { ...prev[m.model], input: e.target.value },
                  }))
                }
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Output ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={editValues[m.model]?.output ?? ""}
                onChange={(e) =>
                  setEditValues((prev) => ({
                    ...prev,
                    [m.model]: { ...prev[m.model], output: e.target.value },
                  }))
                }
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              />
            </div>
            <button
              onClick={() => handleSave(m.model)}
              disabled={saving === m.model}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
            >
              {saving === m.model ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
