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
  fetchRepasseResposta: vi.fn(),
}));

import { KanbanMetricsBar } from "./kanban-metrics-bar";
import { fetchRepasseResposta } from "@/lib/repasse-resposta";

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
    vi.mocked(fetchRepasseResposta).mockResolvedValue(
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
    vi.mocked(fetchRepasseResposta).mockRejectedValue(new Error("relation does not exist"));
    render(<KanbanMetricsBar leads={[lead("a")]} />);
    await vi.waitFor(() => expect(fetchRepasseResposta).toHaveBeenCalled());
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
    expect(screen.getByText("1")).toBeTruthy(); // total no funil continua
  });

  it("nenhum lead da lista assumido → travessão", async () => {
    vi.mocked(fetchRepasseResposta).mockResolvedValue(new Map([["a", linha("a", null)]]));
    render(<KanbanMetricsBar leads={[lead("a")]} />);
    await vi.waitFor(() => expect(fetchRepasseResposta).toHaveBeenCalled());
    expect(screen.getByTestId("tempo-closer").textContent).toBe("—");
  });

  it("busca só os leads exibidos (ids da lista), não a view inteira", async () => {
    vi.mocked(fetchRepasseResposta).mockResolvedValue(new Map([["a", linha("a", 10)]]));
    render(<KanbanMetricsBar leads={[lead("b"), lead("a")]} />);
    expect(await screen.findByText("10 min")).toBeTruthy();
    expect(fetchRepasseResposta).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchRepasseResposta).mock.calls[0][1]).toEqual(["a", "b"]);
  });

  it("não refaz a consulta se os ids exibidos não mudaram (re-render/filtro com o mesmo conjunto)", async () => {
    vi.mocked(fetchRepasseResposta).mockResolvedValue(new Map([["a", linha("a", 10)]]));
    const { rerender } = render(<KanbanMetricsBar leads={[lead("a"), lead("b")]} />);
    expect(await screen.findByText("10 min")).toBeTruthy();
    rerender(<KanbanMetricsBar leads={[lead("b"), lead("a")]} />);
    rerender(<KanbanMetricsBar leads={[lead("a"), lead("b")]} />);
    expect(screen.getByText("10 min")).toBeTruthy();
    expect(fetchRepasseResposta).toHaveBeenCalledTimes(1);
  });

  it("ids exibidos mudaram (filtro) → busca de novo só os novos ids", async () => {
    vi.mocked(fetchRepasseResposta)
      .mockResolvedValueOnce(new Map([["a", linha("a", 10)]]))
      .mockResolvedValueOnce(new Map([["c", linha("c", 40)]]));
    const { rerender } = render(<KanbanMetricsBar leads={[lead("a"), lead("b")]} />);
    expect(await screen.findByText("10 min")).toBeTruthy();
    rerender(<KanbanMetricsBar leads={[lead("c")]} />);
    expect(await screen.findByText("40 min")).toBeTruthy();
    expect(fetchRepasseResposta).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchRepasseResposta).mock.calls[1][1]).toEqual(["c"]);
  });
});
