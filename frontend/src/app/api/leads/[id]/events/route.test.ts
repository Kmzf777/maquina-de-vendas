import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { TIPOS_DA_LINHA_DO_TEMPO } from "@/lib/lead-event-types";

/** Fake do query builder que registra cada chamada `.not(...)`. */
function fakeSupabase(data: unknown[]) {
  const nots: unknown[][] = [];
  const builder: Record<string, unknown> = {};
  for (const m of ["select", "eq", "order"]) builder[m] = () => builder;
  builder.not = (...args: unknown[]) => { nots.push(args); return builder; };
  builder.then = (resolve: (r: unknown) => unknown) =>
    Promise.resolve({ data, error: null }).then(resolve);
  return { nots, from: () => builder };
}

const call = (id = "lead-1") =>
  GET(new Request(`http://localhost/api/leads/${id}/events`) as never, { params: Promise.resolve({ id }) });

describe("GET /api/leads/[id]/events", () => {
  it("deixa fora os eventos da linha do tempo (a aba de notas não vira um mar de 'entrada')", async () => {
    const fake = fakeSupabase([{ id: "e1", event_type: "stage_change" }]);
    vi.mocked(getServiceSupabase).mockResolvedValue(fake as never);

    const res = await call();

    expect(res.status).toBe(200);
    expect(fake.nots).toEqual([["event_type", "in", `(${TIPOS_DA_LINHA_DO_TEMPO.join(",")})`]]);
    expect(await res.json()).toEqual([{ id: "e1", event_type: "stage_change" }]);
  });
});
