import { describe, expect, it } from "vitest";
import {
  fetchRepasseResposta,
  formatarMinutos,
  mapRepasseOverview,
  resumirTempoCloser,
  type RepasseResposta,
} from "./repasse-resposta";

const linha = (lead_id: string, minutos_uteis: number | null, respondeu = minutos_uteis != null): RepasseResposta => ({
  lead_id,
  repasse_em: "2026-10-01T13:00:00Z",
  vendedor_id: "v1",
  primeira_resposta_em: respondeu ? "2026-10-01T14:00:00Z" : null,
  minutos_uteis,
  minutos_uteis_em_aberto: respondeu ? null : 30,
  respondeu,
});

describe("formatarMinutos", () => {
  it("ausente vira travessão", () => {
    expect(formatarMinutos(null)).toBe("—");
    expect(formatarMinutos(undefined)).toBe("—");
  });
  it("menos de 1h em minutos arredondados", () => {
    expect(formatarMinutos(0)).toBe("0 min");
    expect(formatarMinutos(12.4)).toBe("12 min");
    expect(formatarMinutos(59)).toBe("59 min");
  });
  it("1h ou mais em horas e minutos; hora cheia sem minutos", () => {
    expect(formatarMinutos(60)).toBe("1h");
    expect(formatarMinutos(104)).toBe("1h 44min");
    expect(formatarMinutos(600)).toBe("10h");
  });
});

describe("resumirTempoCloser", () => {
  it("média e mediana só dos leads da lista que o closer já assumiu", () => {
    const mapa = new Map([
      ["a", linha("a", 10)],
      ["b", linha("b", 30)],
      ["c", linha("c", 110)],
      ["d", linha("d", null, false)], // ainda não respondido
      ["fora", linha("fora", 999)], // não está na lista
    ]);
    expect(resumirTempoCloser(mapa, ["a", "b", "c", "d", "e"])).toEqual({ amostras: 3, media: 50, mediana: 30 });
  });
  it("mediana com número par de amostras é a média dos dois do meio", () => {
    const mapa = new Map([
      ["a", linha("a", 10)],
      ["b", linha("b", 20)],
    ]);
    expect(resumirTempoCloser(mapa, ["a", "b"]).mediana).toBe(15);
  });
  it("sem amostras → nulos", () => {
    expect(resumirTempoCloser(new Map(), ["a"])).toEqual({ amostras: 0, media: null, mediana: null });
  });
});

describe("fetchRepasseResposta", () => {
  function clienteFalso(resultado: { data: unknown; error: unknown }) {
    const lotes: string[][] = [];
    const sb = {
      from: (tabela: string) => {
        expect(tabela).toBe("vw_repasse_resposta");
        return {
          select: () => ({
            in: (_col: string, ids: string[]) => {
              lotes.push(ids);
              return Promise.resolve(resultado);
            },
          }),
        };
      },
    };
    return { sb: sb as never, lotes };
  }

  it("busca em lotes de 200 e indexa por lead_id", async () => {
    const ids = Array.from({ length: 450 }, (_, i) => `l${i}`);
    const { sb, lotes } = clienteFalso({ data: [linha("l1", 5)], error: null });
    const mapa = await fetchRepasseResposta(sb, ids);
    expect(lotes.map((l) => l.length)).toEqual([200, 200, 50]);
    expect(mapa.get("l1")?.minutos_uteis).toBe(5);
  });

  it("lista vazia não consulta", async () => {
    const { sb, lotes } = clienteFalso({ data: [], error: null });
    expect((await fetchRepasseResposta(sb, [])).size).toBe(0);
    expect(lotes).toHaveLength(0);
  });

  it("erro do banco (ex.: view ainda não criada) é propagado", async () => {
    const { sb } = clienteFalso({ data: null, error: { message: "relation does not exist" } });
    await expect(fetchRepasseResposta(sb, ["a"])).rejects.toBeTruthy();
  });
});

describe("mapRepasseOverview", () => {
  it("linha crua → resumo do painel; número que chega string vira número", () => {
    expect(
      mapRepasseOverview({ lead_id: "l", repasse_em: "2026-10-01T13:00:00Z", minutos_uteis: "12.5", respondeu: true }),
    ).toEqual({ repasse_em: "2026-10-01T13:00:00Z", minutos_uteis: 12.5, respondeu: true });
  });
  it("sem linha → null; sem minutos → null", () => {
    expect(mapRepasseOverview(null)).toBeNull();
    expect(mapRepasseOverview({ repasse_em: "x", minutos_uteis: null, respondeu: false })).toEqual({
      repasse_em: "x",
      minutos_uteis: null,
      respondeu: false,
    });
  });
});
