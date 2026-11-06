/**
 * @vitest-environment jsdom
 *
 * Frente F1: o detalhe da campanha aberto sem ?mode= segue o padrão "por venda" e mostra a frase.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

let busca = "channel=Meta+Ads&campaign=Atacado";
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(busca) }));
vi.mock("next/link", () => ({ default: ({ children }: { children: unknown }) => <a>{children as string}</a> }));
vi.mock("@/hooks/use-current-role", () => ({ useCurrentRole: () => ({ role: "admin", loading: false }) }));
vi.mock("@/components/trafego/campaign-kpis", () => ({ CampaignKpis: () => null }));
vi.mock("@/components/trafego/campaign-timeseries", () => ({ CampaignTimeseries: () => null }));
vi.mock("@/components/trafego/campaign-leads-table", () => ({ CampaignLeadsTable: () => null }));

import CampaignDetailPage from "./page";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function stubFetch(urls: string[]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    return { ok: true, status: 200, json: async () => ({ summary: {}, leads: [], timeseries: [] }) };
  }));
}

describe("CampaignDetailPage", () => {
  it("sem ?mode= pede por venda e mostra a frase", async () => {
    busca = "channel=Meta+Ads&campaign=Atacado";
    const urls: string[] = [];
    stubFetch(urls);
    render(<CampaignDetailPage />);
    expect((await screen.findByTestId("frase-modo")).textContent).toBe("Por venda: toda venda do período, de lead novo ou antigo");
    await vi.waitFor(() => expect(urls[0]).toContain("mode=sale"));
  });

  it("com ?mode=lead respeita o link", async () => {
    busca = "channel=Meta+Ads&campaign=Atacado&mode=lead";
    const urls: string[] = [];
    stubFetch(urls);
    render(<CampaignDetailPage />);
    expect((await screen.findByTestId("frase-modo")).textContent).toContain("Por lead");
    await vi.waitFor(() => expect(urls[0]).toContain("mode=lead"));
  });
});
