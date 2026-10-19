/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Lead } from "@/lib/types";
import type { RepasseResposta } from "@/lib/repasse-resposta";

vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({}) }));
vi.mock("@/lib/repasse-resposta", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/repasse-resposta")>()),
  fetchRepasseRespostaTodas: vi.fn(),
}));

import { KanbanMetricsBar } from "./kanban-metrics-bar";
import { fetchRepasseRespostaTodas } from "@/lib/repasse-resposta";

const lead = (id: string, extra: Partial<Lead> = {}) =>
  ({ id, created_at: "2026-01-01T12:00:00Z", first_response_at: null, ...extra }) as Lead;

const linha = (lead_id: string, minutos_uteis: number | null): RepasseResposta => ({
  lead_id,
  repasse_em: "2026-10-01T13:00:00Z",
  vendedor_id: null,
  primeira_resposta_em: minutos_uteis == null ? null : "2026-10-01T14:00:00Z",
  minutos_uteis,
  minutos_uteis_em_aberto: minutos_uteis == null ? 15 : null,
  respondeu: minutos_uteis != null,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("KanbanMetricsBar — tempo até o closer assumir", () => {
  it("mostra a mediana (e a média) dos leads da lista que o closer assumiu, em minutos úteis", async () => {
    vi.mocked(fetchRepasseRespostaTodas).mockResolvedValue(
      new Map([
        ["a", linha("a", 10)],
        ["b", linha("b", 30)],
        ["c", linha("c", 110)],
        ["d", linha("d", null)],
        ["fora", linha("fora", 5000)],
      ]),
    );
    // first_response_at - created_at daria dias; não pode ser usado.
    render(
      <KanbanMetricsBar
        leads={[lead("a", { first_response_at: "2026-01-09T12:00:00Z" }), lead("b"), lead("c"), lead("d")]}
      />,
    );
    expect(await screen.findByText("30 min")).toBeTruthy();
    expect(screen.getByText(/média 50 min · 3 leads/)).toBeTruthy();
    expect(screen.getByText("Tempo até o closer assumir (horário comercial)")).toBeTruthy();
  });

  it("view indisponível (erro) mostra travessão sem quebrar", async () => {
    vi.mocked(fetchRepasseRespostaTodas).mockRejectedValue(new Error("relation does not exist"));
    render(<KanbanMetricsBar leads={[lead("a")]} />);
    await vi.waitFor(() => expect(fetchRepasseRespostaTodas).toHaveBeenCalled());
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
    expect(screen.getByText("1")).toBeTruthy(); // total no funil continua
  });

  it("nenhum lead da lista assumido → travessão", async () => {
    vi.mocked(fetchRepasseRespostaTodas).mockResolvedValue(new Map([["a", linha("a", null)]]));
    render(<KanbanMetricsBar leads={[lead("a")]} />);
    await vi.waitFor(() => expect(fetchRepasseRespostaTodas).toHaveBeenCalled());
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
  });

  it("busca a view uma vez só, mesmo com a lista mudando (filtro)", async () => {
    vi.mocked(fetchRepasseRespostaTodas).mockResolvedValue(new Map([["a", linha("a", 10)]]));
    const { rerender } = render(<KanbanMetricsBar leads={[lead("a"), lead("b")]} />);
    expect(await screen.findByText("10 min")).toBeTruthy();
    rerender(<KanbanMetricsBar leads={[lead("a")]} />);
    expect(screen.getByText("10 min")).toBeTruthy();
    expect(fetchRepasseRespostaTodas).toHaveBeenCalledTimes(1);
  });
});
