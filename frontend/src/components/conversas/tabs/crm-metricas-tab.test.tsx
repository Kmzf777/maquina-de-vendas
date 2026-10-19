/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Lead } from "@/lib/types";
import type { RepasseResposta } from "@/lib/repasse-resposta";

vi.mock("@/hooks/use-repasse-resposta", () => ({
  useRepasseResposta: vi.fn(),
}));

import { CrmMetricasTab } from "./crm-metricas-tab";
import { useRepasseResposta } from "@/hooks/use-repasse-resposta";

const LEAD = {
  id: "lead-1",
  created_at: "2026-10-01T12:00:00Z",
  // Dias depois da criação: o cálculo antigo (first_response_at - created_at) daria "216h".
  first_response_at: "2026-10-10T12:00:00Z",
  last_msg_at: null,
  entered_stage_at: null,
  channel: "meta",
} as unknown as Lead;

const linha = (p: Partial<RepasseResposta>): RepasseResposta => ({
  lead_id: "lead-1",
  repasse_em: "2026-10-01T13:00:00Z",
  vendedor_id: "v1",
  primeira_resposta_em: null,
  minutos_uteis: null,
  minutos_uteis_em_aberto: null,
  respondeu: false,
  ...p,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CrmMetricasTab — tempo até o closer assumir", () => {
  it("mostra os minutos úteis da view, com o rótulo novo", () => {
    vi.mocked(useRepasseResposta).mockReturnValue({
      carregando: false,
      linha: linha({ minutos_uteis: 104, respondeu: true, primeira_resposta_em: "2026-10-01T15:00:00Z" }),
    });
    render(<CrmMetricasTab lead={LEAD} />);
    expect(useRepasseResposta).toHaveBeenCalledWith("lead-1");
    expect(screen.getByTestId("tempo-closer").textContent).toBe("1h 44min");
    expect(screen.getByText("Tempo até o closer assumir (horário comercial)")).toBeTruthy();
    expect(screen.queryByText("216h")).toBeNull();
  });

  it("lead sem linha na view (ou view indisponível) → travessão", () => {
    vi.mocked(useRepasseResposta).mockReturnValue({ carregando: false, linha: null });
    render(<CrmMetricasTab lead={LEAD} />);
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
  });

  it("repassado e ainda sem resposta → travessão e o tempo em aberto", () => {
    vi.mocked(useRepasseResposta).mockReturnValue({
      carregando: false,
      linha: linha({ minutos_uteis_em_aberto: 25 }),
    });
    render(<CrmMetricasTab lead={LEAD} />);
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
    expect(screen.getByText("Aguardando há 25 min")).toBeTruthy();
  });
});
