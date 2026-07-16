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

// O componente era cego a severidade: TODO alerta não-resolvido virava modal
// vermelho "Alerta Crítico" 🚨 — inclusive o relatório informativo de QA diário
// (severity="info") e os warnings de SLA do watchdog (10/07/2026). Agora a
// severidade gravada no banco comanda o tratamento visual:
//   critical/error → modal vermelho bloqueante (comportamento original)
//   warning        → modal âmbar "Atenção" (mesmo layout, urgência honesta)
//   info           → cartão discreto no canto inferior direito, SEM backdrop
//                    (um relatório diário não pode sequestrar a tela).
const SEVERITY_RANK: Record<string, number> = { critical: 0, error: 0, warning: 1, info: 2 };

function rank(a: SystemAlert): number {
  return SEVERITY_RANK[a.severity] ?? 0; // severidade desconhecida = trata como crítica
}

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
        const unseen = all
          .filter((a) => !dismissed.has(a.id))
          .sort((a, b) => rank(a) - rank(b)); // críticos primeiro, informativos por último
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
  const severity = SEVERITY_RANK[alert.severity] ?? 0;

  // ── INFO: cartão discreto, não-bloqueante ────────────────────────────────
  if (severity === 2) {
    return (
      <div className="fixed bottom-4 right-4 z-[9999] w-full max-w-md">
        <div className="rounded-xl overflow-hidden shadow-xl border border-sky-700 bg-sky-950">
          <div className="bg-sky-900 px-4 py-3 flex items-start gap-3">
            <span className="text-xl select-none">📊</span>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-widest text-sky-300 mb-0.5">
                Informativo
              </p>
              <h2 className="text-white text-sm font-bold leading-tight">{alert.title}</h2>
            </div>
            <button
              onClick={() => dismiss(alert.id)}
              className="text-sky-300 hover:text-white text-sm font-bold px-2"
              aria-label="Dispensar"
            >
              ✕
            </button>
          </div>
          <div className="px-4 py-3">
            <p className="text-sky-100 text-xs leading-relaxed whitespace-pre-line">
              {alert.message}
            </p>
            {alerts.length > 1 && (
              <button
                onClick={() => setCurrent((c) => (c + 1) % alerts.length)}
                className="mt-2 text-sky-400 hover:text-white text-xs underline"
              >
                Ver próximo ({current + 1} de {alerts.length})
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── CRITICAL/ERROR (vermelho) e WARNING (âmbar): modal bloqueante ────────
  const isWarning = severity === 1;
  const palette = isWarning
    ? {
        border: "border-amber-600",
        header: "bg-amber-500",
        headerLabel: "text-amber-100",
        body: "bg-amber-950",
        bodyText: "text-amber-100",
        footer: "bg-amber-900",
        nextBtn: "text-amber-300 hover:text-white hover:bg-amber-700",
        okBtn: "bg-white text-amber-700 hover:bg-amber-100",
        note: "text-amber-400",
        icon: "⚠️",
        label: "Atenção",
      }
    : {
        border: "border-red-700",
        header: "bg-red-600",
        headerLabel: "text-red-200",
        body: "bg-red-950",
        bodyText: "text-red-100",
        footer: "bg-red-900",
        nextBtn: "text-red-300 hover:text-white hover:bg-red-700",
        okBtn: "bg-white text-red-700 hover:bg-red-100",
        note: "text-red-500",
        icon: "🚨",
        label: "Alerta Crítico",
      };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70" />

      {/* Modal */}
      <div
        className={`relative z-10 w-full max-w-lg mx-4 rounded-2xl overflow-hidden shadow-2xl border-4 ${palette.border}`}
      >
        {/* Header */}
        <div className={`${palette.header} px-6 py-5 flex items-start gap-4`}>
          <span className="text-4xl select-none">{palette.icon}</span>
          <div className="flex-1 min-w-0">
            <p
              className={`text-xs font-bold uppercase tracking-widest ${palette.headerLabel} mb-1`}
            >
              {palette.label}
            </p>
            <h2 className="text-white text-xl font-bold leading-tight">{alert.title}</h2>
          </div>
        </div>

        {/* Body */}
        <div className={`${palette.body} px-6 py-5`}>
          <p className={`${palette.bodyText} text-sm leading-relaxed`}>{alert.message}</p>

          {/* Bloco de remediação escrito para o alerta de billing — só faz sentido nele.
              Renderizá-lo em outros tipos misturava instruções erradas (ex.: SLA de handoff
              com "quite o débito"). */}
          {alert.type === "billing_payment_issue" && (
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
          )}

          {alerts.length > 1 && (
            <p className={`mt-3 ${palette.note} text-xs text-center`}>
              {current + 1} de {alerts.length} alertas não resolvidos
            </p>
          )}

          <p className={`mt-3 ${palette.note} text-xs text-center`}>
            Dispensar oculta apenas para você — outros usuários continuam vendo este alerta.
          </p>
        </div>

        {/* Footer */}
        <div className={`${palette.footer} px-6 py-4 flex gap-3 justify-end`}>
          {alerts.length > 1 && (
            <button
              onClick={() => setCurrent((c) => (c + 1) % alerts.length)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${palette.nextBtn}`}
            >
              Ver próximo
            </button>
          )}
          <button
            onClick={() => dismiss(alert.id)}
            className={`px-5 py-2 rounded-lg text-sm font-bold transition-colors ${palette.okBtn}`}
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}
