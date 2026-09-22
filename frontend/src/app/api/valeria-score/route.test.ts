import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({
  getCurrentUser: vi.fn().mockRejectedValue(new Error("no session")),
}));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { PUT } from "./[leadId]/feeling/route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

describe("Valeria Score routes", () => {
  it("rejects an unauthenticated score-directory request before using the service client", async () => {
    const response = await GET(new Request("http://localhost/api/valeria-score?page=2") as never);
    expect(response.status).toBe(401);
  });

  it("rejects an unauthenticated Feeling update", async () => {
    const response = await PUT(
      new Request("http://localhost/api/valeria-score/lead-1/feeling", { method: "PUT", body: JSON.stringify({ feeling: "alto", justification: "Cotação solicitada" }) }) as never,
      { params: Promise.resolve({ leadId: "lead-1" }) },
    );
    expect(response.status).toBe(401);
  });

  it("allows only vendedores to save Feeling", async () => {
    vi.mocked(getCurrentUser).mockResolvedValueOnce({ userId: "admin-1", role: "admin" });
    const response = await PUT(
      new Request("http://localhost/api/valeria-score/lead-1/feeling", { method: "PUT", body: JSON.stringify({ feeling: "alto", justification: "Cotação solicitada" }) }) as never,
      { params: Promise.resolve({ leadId: "lead-1" }) },
    );
    expect(response.status).toBe(403);
  });
});
