/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const resultado = vi.hoisted(() => ({ atual: { data: null as unknown, error: null as unknown } }));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: (tabela: string) => ({
      select: () => ({
        in: (_c: string, ids: string[]) => Promise.resolve({ ...resultado.atual, _tabela: tabela, _ids: ids }),
      }),
    }),
  }),
}));

import { useRepasseResposta } from "./use-repasse-resposta";

afterEach(() => vi.clearAllMocks());

describe("useRepasseResposta", () => {
  it("devolve a linha do lead", async () => {
    resultado.atual = {
      data: [{ lead_id: "l1", minutos_uteis: 12, respondeu: true }],
      error: null,
    };
    const { result } = renderHook(() => useRepasseResposta("l1"));
    expect(result.current.carregando).toBe(true);
    await waitFor(() => expect(result.current.carregando).toBe(false));
    expect(result.current.linha?.minutos_uteis).toBe(12);
  });

  it("view ausente (erro) → linha nula, sem exceção", async () => {
    resultado.atual = { data: null, error: { message: 'relation "vw_repasse_resposta" does not exist' } };
    const { result } = renderHook(() => useRepasseResposta("l1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));
    expect(result.current.linha).toBeNull();
  });
});
