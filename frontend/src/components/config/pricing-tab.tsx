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
          <div key={i} className="h-20 rounded-xl animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-[13px] mb-4" style={{ color: "var(--text-muted)" }}>
        Precos por 1M tokens (USD). Estes valores sao usados para calcular o custo de cada chamada ao agente.
      </p>

      {models.map((m) => (
        <div key={m.model} className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[14px] font-semibold" style={{ color: "var(--text-primary)" }}>
              {m.model}
            </h3>
            <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              Atualizado: {new Date(m.updated_at).toLocaleDateString("pt-BR")}
            </span>
          </div>

          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="block text-[12px] font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
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
                className="w-full px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white focus:outline-none focus:ring-2 focus:ring-[#c8cc8e]"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[12px] font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
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
                className="w-full px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white focus:outline-none focus:ring-2 focus:ring-[#c8cc8e]"
              />
            </div>
            <button
              onClick={() => handleSave(m.model)}
              disabled={saving === m.model}
              className="px-5 py-2 text-[13px] font-medium rounded-lg text-white transition-all disabled:opacity-50"
              style={{ backgroundColor: "var(--accent-olive)" }}
            >
              {saving === m.model ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
