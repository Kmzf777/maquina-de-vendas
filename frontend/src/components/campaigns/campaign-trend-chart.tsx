"use client";

interface TrendData {
  date: string;
  sent: number;
  responded: number;
}

export function CampaignTrendChart({ data }: { data: TrendData[] }) {
  if (!data.length) {
    return <p className="text-[14px] text-[#7b7b78] text-center py-8">Sem dados no periodo</p>;
  }

  const maxVal = Math.max(...data.map((d) => Math.max(d.sent, d.responded)), 1);
  const height = 160;
  const width = data.length * 40;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${Math.max(width, 400)} ${height + 30}`} className="w-full" style={{ minWidth: 400 }}>
        {data.map((d, i) => {
          const x = (i / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20;
          const ySent = height - (d.sent / maxVal) * height;
          const yResp = height - (d.responded / maxVal) * height;

          return (
            <g key={d.date}>
              {i > 0 && (
                <>
                  <line
                    x1={((i - 1) / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20}
                    y1={height - (data[i - 1].sent / maxVal) * height}
                    x2={x}
                    y2={ySent}
                    stroke="#dedbd6"
                    strokeWidth="2"
                  />
                  <line
                    x1={((i - 1) / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20}
                    y1={height - (data[i - 1].responded / maxVal) * height}
                    x2={x}
                    y2={yResp}
                    stroke="#0bdf50"
                    strokeWidth="2"
                  />
                </>
              )}
              <circle cx={x} cy={ySent} r="3" fill="#dedbd6" />
              <circle cx={x} cy={yResp} r="3" fill="#0bdf50" />
              {i % Math.ceil(data.length / 8) === 0 && (
                <text x={x} y={height + 18} textAnchor="middle" fontSize="10" fill="#7b7b78">
                  {d.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}
        <text x="10" y="12" fontSize="10" fill="#7b7b78">Enviadas</text>
        <text x="80" y="12" fontSize="10" fill="#0bdf50">Respostas</text>
      </svg>
    </div>
  );
}
