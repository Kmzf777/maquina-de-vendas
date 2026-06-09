"use client";

import { useEffect, useState } from "react";

interface SystemAlert {
  id: string;
  type: string;
  severity: string;
  title: string;
  message: string;
  created_at: string;
}

const STORAGE_KEY = "crm_dismissed_alerts";

function getDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function saveDismissed(ids: Set<string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch {}
}

export default function SystemAlertBanner() {
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const [current, setCurrent] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    async function fetchAlerts() {
      try {
        const res = await fetch("/api/system-alerts", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const all: SystemAlert[] = Array.isArray(data) ? data : [];
        const dismissed = getDismissed();
        const unseen = all.filter((a) => !dismissed.has(a.id));
        setAlerts(unseen);
        if (unseen.length > 0) setVisible(true);
      } catch {}
    }
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 60_000);
    return () => clearInterval(interval);
  }, []);

  function dismiss(id: string) {
    const dismissed = getDismissed();
    dismissed.add(id);
    saveDismissed(dismissed);
    const next = alerts.filter((a) => a.id !== id);
    setAlerts(next);
    if (next.length === 0) {
      setVisible(false);
    } else {
      setCurrent((c) => Math.min(c, next.length - 1));
    }
  }

  if (!visible || alerts.length === 0) return null;

  const alert = alerts[current];

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg mx-4 rounded-2xl overflow-hidden shadow-2xl border-4 border-red-700">
        {/* Header */}
        <div className="bg-red-600 px-6 py-5 flex items-start gap-4">
          <span className="text-4xl select-none">🚨</span>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold uppercase tracking-widest text-red-200 mb-1">
              Alerta Crítico
            </p>
            <h2 className="text-white text-xl font-bold leading-tight">
              {alert.title}
            </h2>
          </div>
        </div>

        {/* Body */}
        <div className="bg-red-950 px-6 py-5">
          <p className="text-red-100 text-sm leading-relaxed">{alert.message}</p>

          <div className="mt-4 rounded-lg bg-red-900/60 border border-red-700 px-4 py-3">
            <p className="text-red-300 text-xs font-semibold uppercase tracking-wider mb-1">
              O que fazer agora
            </p>
            <p className="text-red-100 text-sm">
              Acesse o{" "}
              <a
                href="https://business.facebook.com/billing_hub/accounts/details/?business_id=1338125734024745&asset_id=1399531671927018&wizard_name=PAY_NOW&account_type=whatsapp-business-account"
                target="_blank"
                rel="noopener noreferrer"
                className="underline font-bold text-white hover:text-red-200"
              >
                Business Manager da Meta
              </a>{" "}
              e quite o débito para retomar os envios.
            </p>
          </div>

          {alerts.length > 1 && (
            <p className="mt-3 text-red-400 text-xs text-center">
              {current + 1} de {alerts.length} alertas não resolvidos
            </p>
          )}

          <p className="mt-3 text-red-500 text-xs text-center">
            Dispensar oculta apenas para você — outros usuários continuam vendo este alerta.
          </p>
        </div>

        {/* Footer */}
        <div className="bg-red-900 px-6 py-4 flex gap-3 justify-end">
          {alerts.length > 1 && (
            <button
              onClick={() => setCurrent((c) => (c + 1) % alerts.length)}
              className="px-4 py-2 rounded-lg text-sm font-medium text-red-300 hover:text-white hover:bg-red-700 transition-colors"
            >
              Ver próximo
            </button>
          )}
          <button
            onClick={() => dismiss(alert.id)}
            className="px-5 py-2 rounded-lg text-sm font-bold bg-white text-red-700 hover:bg-red-100 transition-colors"
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}
