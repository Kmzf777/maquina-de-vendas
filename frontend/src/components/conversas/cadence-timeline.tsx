"use client";

import { useEffect, useState } from "react";
import { touchStateLabel, objectiveLabel, isCadenceTouch, type FollowupJob } from "@/lib/cadence-display";
import { formatDayLabel } from "@/lib/datetime";

const DOT: Record<string, string> = {
  Agendado: "bg-[#7b7b78]",
  "Texto enviado": "bg-[#ff5600]",
  "Template enviado": "bg-[#1e6ee8]",
  "Contexto atualizado": "bg-[#1e6ee8]",
  Cancelado: "bg-[#dedbd6]",
};

export function CadenceTimeline({ leadId }: { leadId: string }) {
  const [jobs, setJobs] = useState<FollowupJob[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`/api/leads/${leadId}/followups`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { if (active) { setJobs(Array.isArray(data) ? data : []); setLoaded(true); } })
      .catch(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [leadId]);

  const cadenceJobs = jobs.filter(isCadenceTouch);

  if (!loaded || cadenceJobs.length === 0) return null;

  return (
    <div className="px-4 py-3 border-t border-[#dedbd6]">
      <h4 className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
        Cadência
      </h4>
      <ol className="flex flex-col gap-2">
        {cadenceJobs.map((job, idx) => {
          const state = touchStateLabel(job);
          const when = job.sent_at || job.fire_at;
          return (
            <li key={idx} className="flex items-start gap-2">
              <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${DOT[state] ?? "bg-[#7b7b78]"}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] font-medium text-[#111111]">
                    {job.sequence ? `T${job.sequence}` : "—"} · {objectiveLabel(job.objetivo)}
                  </span>
                </div>
                <div className="text-[11px] text-[#7b7b78]">
                  {state}
                  {state === "Cancelado" && job.cancel_reason ? ` · ${job.cancel_reason}` : ""}
                  {when ? ` · ${formatDayLabel(when)}` : ""}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
