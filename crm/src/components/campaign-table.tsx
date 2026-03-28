import type { Campaign } from "@/lib/types";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";

interface CampaignTableProps {
  campaigns: Campaign[];
}

export function CampaignMetricsTable({ campaigns }: CampaignTableProps) {
  return (
    <div className="card p-5">
      <h3
        className="text-[13px] font-semibold uppercase tracking-wider mb-5 flex items-center gap-2"
        style={{ color: "var(--text-secondary)" }}
      >
        Metricas de Campanha
        <span className="text-[14px] opacity-50">&rarr;</span>
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr
            className="text-left border-b"
            style={{
              color: "var(--text-secondary)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <th className="pb-3 text-[12px] uppercase tracking-wider font-medium">
              Nome
            </th>
            <th className="pb-3 text-[12px] uppercase tracking-wider font-medium">
              Status
            </th>
            <th className="pb-3 text-[12px] uppercase tracking-wider font-medium">
              Progresso
            </th>
            <th className="pb-3 text-[12px] uppercase tracking-wider font-medium">
              Resposta
            </th>
          </tr>
        </thead>
        <tbody>
          {campaigns.map((c) => {
            const responseRate =
              c.sent > 0
                ? `${Math.round((c.replied / c.sent) * 100)}%`
                : "\u2014";
            const progress =
              c.total_leads > 0
                ? Math.round((c.sent / c.total_leads) * 100)
                : 0;
            return (
              <tr
                key={c.id}
                className="border-b last:border-0"
                style={{ borderColor: "var(--border-subtle)" }}
              >
                <td
                  className="py-3 font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  {c.name}
                </td>
                <td className="py-3">
                  <span
                    className={`badge ${
                      CAMPAIGN_STATUS_COLORS[c.status] || ""
                    }`}
                  >
                    {c.status}
                  </span>
                </td>
                <td className="py-3">
                  <div className="flex items-center gap-2">
                    <div
                      className="w-24 rounded-full h-2"
                      style={{ backgroundColor: "#e5e5dc" }}
                    >
                      <div
                        className="rounded-full h-2 transition-all duration-300"
                        style={{
                          width: `${progress}%`,
                          backgroundColor: "#1f1f1f",
                        }}
                      />
                    </div>
                    <span
                      className="text-[12px]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {c.sent}/{c.total_leads}
                    </span>
                  </div>
                </td>
                <td
                  className="py-3 font-medium"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {responseRate}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
