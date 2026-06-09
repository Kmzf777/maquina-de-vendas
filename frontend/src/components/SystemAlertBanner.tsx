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

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-600 text-white border-red-700",
  error: "bg-red-500 text-white border-red-600",
  warning: "bg-amber-500 text-white border-amber-600",
};

const SEVERITY_ICON: Record<string, string> = {
  critical: "🚨",
  error: "⚠️",
  warning: "⚠️",
};

export default function SystemAlertBanner() {
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);

  useEffect(() => {
    async function fetchAlerts() {
      try {
        const res = await fetch("/api/system-alerts", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          setAlerts(Array.isArray(data) ? data : []);
        }
      } catch {
        // silently ignore — banner is best-effort
      }
    }
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 60_000);
    return () => clearInterval(interval);
  }, []);

  async function dismiss(id: string) {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
    await fetch("/api/system-alerts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
  }

  if (alerts.length === 0) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 flex flex-col gap-0">
      {alerts.map((alert) => {
        const style = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.error;
        const icon = SEVERITY_ICON[alert.severity] ?? "⚠️";
        return (
          <div
            key={alert.id}
            className={`flex items-start gap-3 px-4 py-3 border-b text-sm font-medium ${style}`}
          >
            <span className="text-base shrink-0">{icon}</span>
            <div className="flex-1 min-w-0">
              <span className="font-bold">{alert.title}</span>
              <span className="mx-2">—</span>
              <span className="font-normal opacity-90">{alert.message}</span>
            </div>
            <button
              onClick={() => dismiss(alert.id)}
              className="shrink-0 opacity-70 hover:opacity-100 text-lg leading-none"
              aria-label="Dispensar alerta"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
