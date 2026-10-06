/**
 * @vitest-environment jsdom
 *
 * Atribuição manual de campanha (call de 01/10, P2): select agrupado por canal, "Atribuir"
 * manda PATCH com canal/id/nome, "Remover atribuição" manda {remover: true}, erro do
 * backend aparece em texto. `<select>` nativo: o Radix Select não roda no jsdom.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CampaignAttribution, type AtribuicaoManual } from "./campaign-attribution";

const CAMPANHAS = [
  { canal: "meta", campanha_id: "m1", campanha_nome: "Atacado WA", investimento: 500 },
  { canal: "google", campanha_id: "g1", campanha_nome: "PMAX | Atacado", investimento: 300 },
];
const SEM: AtribuicaoManual = {
  atribuicao_manual: false, campanha_manual_canal: null, campanha_manual_id: null, campanha_manual_nome: null,
};
const COM: AtribuicaoManual = {
  atribuicao_manual: true, campanha_manual_canal: "google", campanha_manual_id: "g1", campanha_manual_nome: "PMAX | Atacado",
};

type Chamada = { url: string; init?: RequestInit };

function mockFetch(patch: { ok: boolean; body: unknown }) {
  const chamadas: Chamada[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    chamadas.push({ url, init });
    const data = url === "/api/traffic/campanhas" ? { campanhas: CAMPANHAS } : patch.body;
    const ok = url === "/api/traffic/campanhas" ? true : patch.ok;
    return { ok, status: ok ? 200 : 422, json: async () => data };
  }));
  return chamadas;
}

const patches = (c: Chamada[]) => c.filter((x) => x.init?.method === "PATCH");

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CampaignAttribution", () => {
  it("agrupa as campanhas por canal", async () => {
    mockFetch({ ok: true, body: {} });
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    const grupos = Array.from(container.querySelectorAll("optgroup")).map((g) => g.getAttribute("label"));
    expect(grupos).toEqual(["Meta Ads", "Google Ads"]);
  });

  it("atribui com PATCH e avisa o pai", async () => {
    const chamadas = mockFetch({ ok: true, body: {
      atribuicao_manual: true, campanha_manual_canal: "meta", campanha_manual_id: "m1", campanha_manual_nome: "Atacado WA",
    } });
    const onChange = vi.fn();
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} onChange={onChange} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Campanha"), { target: { value: "meta:m1" } });
    fireEvent.click(screen.getByRole("button", { name: "Atribuir" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [p] = patches(chamadas);
    expect(p.url).toBe("/api/traffic/leads/L1/campanha");
    expect(JSON.parse(String(p.init?.body))).toEqual({ canal: "meta", campanha_id: "m1", campanha_nome: "Atacado WA" });
    expect(onChange.mock.calls[0][0]).toMatchObject({ atribuicao_manual: true, campanha_manual_id: "m1" });
  });

  it("mostra o selo manual e remove a atribuição", async () => {
    const chamadas = mockFetch({ ok: true, body: {
      atribuicao_manual: false, campanha_manual_canal: null, campanha_manual_id: null, campanha_manual_nome: null,
    } });
    const onChange = vi.fn();
    render(<CampaignAttribution leadId="L1" atual={COM} onChange={onChange} />);
    expect(screen.getByText("manual")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remover atribuição" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(JSON.parse(String(patches(chamadas)[0].init?.body))).toEqual({ remover: true });
    expect(onChange.mock.calls[0][0]).toMatchObject({ atribuicao_manual: false });
  });

  it("mostra o erro do backend", async () => {
    mockFetch({ ok: false, body: { detail: "canal deve ser 'meta' ou 'google'" } });
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Campanha"), { target: { value: "google:g1" } });
    fireEvent.click(screen.getByRole("button", { name: "Atribuir" }));
    expect(await screen.findByText("canal deve ser 'meta' ou 'google'")).toBeTruthy();
  });
});
