import { describe, expect, it } from "vitest";
import {
  detalheCampanhaUrl, escolherAtribuicao, jornadaCampaignQuery, passouPorTexto, passouPorTooltip,
  type Jornada,
} from "@/lib/traffic-jornada";

const META_GOOGLE: Jornada = {
  primeira_origem: "Meta Ads", primeira_em: "2026-10-01T12:00:00+00:00",
  ultima_origem: "Google Ads", ultima_em: "2026-10-09T12:00:00+00:00",
  origens: ["Meta Ads", "Google Ads"],
  toques: [{ canal: "Meta Ads", em: "2026-10-01T12:00:00+00:00" }, { canal: "Google Ads", em: "2026-10-09T12:00:00+00:00" }],
  n_toques: 2, multicanal: true, estimado: false,
};

describe("passou por", () => {
  it("canais na ordem com seta e datas no tooltip", () => {
    expect(passouPorTexto(META_GOOGLE)).toBe("Meta Ads → Google Ads");
    expect(passouPorTooltip(META_GOOGLE)).toBe("Meta Ads em 01/10 · Google Ads em 09/10");
  });
  it("lead sem entrada mostra o canal estimado", () => {
    const j = { ...META_GOOGLE, origens: ["Cliente antigo"], toques: [], n_toques: 0, estimado: true };
    expect(passouPorTexto(j)).toBe("Cliente antigo (estimado)");
    expect(passouPorTooltip(j)).toMatch(/estimado/);
  });
  it("sem jornada (backend antigo) é —", () => {
    expect(passouPorTexto(null)).toBe("—");
    expect(passouPorTooltip(undefined)).toBeUndefined();
  });
});

describe("escolherAtribuicao", () => {
  const ultima = { rows: [{ channel: "Google Ads" }], total: { leads: 1 }, channel_subtotals: {} };
  const primeira = { rows: [{ channel: "Meta Ads" }], total: { leads: 1 }, channel_subtotals: {} };
  it("pega a parte pedida", () => {
    const r = { ...ultima, por_atribuicao: { ultima, primeira } };
    expect(escolherAtribuicao(r, "primeira").rows[0].channel).toBe("Meta Ads");
    expect(escolherAtribuicao(r, "ultima").rows[0].channel).toBe("Google Ads");
  });
  it("backend sem F5 devolve o próprio relatório", () => {
    expect(escolherAtribuicao(ultima, "primeira")).toBe(ultima);
  });
});

describe("detalhe da campanha", () => {
  it("primeira origem usa a rota da jornada; última, a de sempre", () => {
    expect(detalheCampanhaUrl("a=1", "primeira")).toBe("/api/traffic/jornada/campaign?a=1");
    expect(detalheCampanhaUrl("a=1", "ultima")).toBe("/api/traffic/campaign?a=1");
    expect(detalheCampanhaUrl("a=1", null)).toBe("/api/traffic/campaign?a=1");
  });
  it("o proxy só repassa os parâmetros conhecidos", () => {
    const qs = jornadaCampaignQuery("http://x/api?channel=Meta%20Ads&campaign=A&atribuicao=primeira&evil=1&mode=sale");
    expect(new URLSearchParams(qs).get("evil")).toBeNull();
    expect(Object.fromEntries(new URLSearchParams(qs))).toEqual({
      channel: "Meta Ads", campaign: "A", mode: "sale", atribuicao: "primeira",
    });
  });
});
