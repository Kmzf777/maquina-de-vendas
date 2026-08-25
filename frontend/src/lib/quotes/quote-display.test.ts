import { describe, it, expect } from "vitest";
import {
  quoteStatus,
  podeEditar,
  podeConverter,
  numeroDoOrcamento,
  contarAprovacoes,
  taxaDeAprovacao,
  formatarTaxa,
  formatarBRL,
  type QuoteStatus,
} from "@/lib/quotes/quote-display";

const TODOS: QuoteStatus[] = [
  "rascunho",
  "enviado",
  "aprovado",
  "nao_aprovado",
  "convertido",
  "cancelado",
];

describe("quoteStatus", () => {
  it("cobre os seis status do vocabulario", () => {
    for (const s of TODOS) {
      expect(quoteStatus(s).label).not.toBe("—");
    }
  });

  it("convertido tem tom proprio — e o unico estado sem volta", () => {
    expect(quoteStatus("convertido").tone).toBe("locked");
    expect(quoteStatus("aprovado").tone).toBe("approved");
  });

  it("cancelado e nao aprovado compartilham o tom de recusa", () => {
    expect(quoteStatus("cancelado").tone).toBe(quoteStatus("nao_aprovado").tone);
  });

  // `quotes.status` e `text` sem CHECK: um backfill ou uma correcao manual no
  // SQL editor pode gravar qualquer coisa. Sem o fallback, `.tone` de undefined
  // derrubaria a renderizacao da tabela inteira por causa de UMA linha.
  it("status desconhecido nao quebra a celula", () => {
    const view = quoteStatus("expirado_2027");
    expect(view.label).toBe("expirado_2027");
    expect(view.tone).toBe("draft");
  });

  it("status vazio vira travessao", () => {
    expect(quoteStatus("").label).toBe("—");
  });
});

describe("podeEditar / podeConverter", () => {
  it("convertido trava a edicao — o PUT responderia 409", () => {
    expect(podeEditar({ status: "convertido" })).toBe(false);
  });

  it("todos os outros status sao editaveis", () => {
    for (const s of TODOS.filter((s) => s !== "convertido")) {
      expect(podeEditar({ status: s })).toBe(true);
    }
  });

  it("convertido nao converte de novo — o POST responderia 409", () => {
    expect(podeConverter({ status: "convertido" })).toBe(false);
  });

  // Cliente que volta atras depois de um "não aprovado" existe; a decisao e do
  // vendedor. A tela so bloqueia o que o backend bloqueia.
  it("nao aprovado ainda pode virar venda", () => {
    expect(podeConverter({ status: "nao_aprovado" })).toBe(true);
  });
});

describe("numeroDoOrcamento", () => {
  it("mostra o numero do Bling quando ele chegou", () => {
    expect(numeroDoOrcamento({ bling_proposal_number: 137 })).toBe("#137");
  });

  // Ausencia de numero e estado esperado: o POST devolve so o id e o numero vem
  // de um GET best-effort. O orcamento existe e tem PDF mesmo assim.
  it("sem numero mostra travessao, nao erro", () => {
    expect(numeroDoOrcamento({ bling_proposal_number: null })).toBe("—");
  });

  // Zero nao e numero de proposta valido no Bling; se aparecer, e lixo — e
  // "#0" seria pior que o travessao porque parece um numero de verdade.
  it("zero cai no travessao", () => {
    expect(numeroDoOrcamento({ bling_proposal_number: 0 })).toBe("—");
  });
});

describe("contarAprovacoes", () => {
  it("aprovado e convertido contam como aceite", () => {
    expect(contarAprovacoes(["aprovado", "convertido"])).toEqual({ approved: 2, decided: 2 });
  });

  // Sem isto a taxa despencaria toda vez que o vendedor comecasse a montar uma
  // proposta — o indicador viraria um desincentivo a usar a ferramenta.
  it("rascunho fica fora do denominador", () => {
    expect(contarAprovacoes(["rascunho", "rascunho", "aprovado"])).toEqual({
      approved: 1,
      decided: 1,
    });
  });

  // Literal do §5 da spec ("todos menos rascunho"). Tirar o cancelado daria ao
  // vendedor uma forma de melhorar a propria taxa cancelando o que foi recusado.
  it("cancelado conta no denominador", () => {
    expect(contarAprovacoes(["cancelado", "aprovado"])).toEqual({ approved: 1, decided: 2 });
  });

  it("enviado conta no denominador mas nao no numerador", () => {
    expect(contarAprovacoes(["enviado", "enviado"])).toEqual({ approved: 0, decided: 2 });
  });

  it("periodo vazio nao conta nada", () => {
    expect(contarAprovacoes([])).toEqual({ approved: 0, decided: 0 });
  });
});

describe("taxaDeAprovacao", () => {
  it("divide aprovados por decididos", () => {
    expect(taxaDeAprovacao({ approved: 3, decided: 4 })).toBe(0.75);
  });

  // O ponto inteiro da funcao: 0/0 em JS e NaN, que renderiza "NaN%".
  it("denominador zero devolve null, nao NaN", () => {
    expect(taxaDeAprovacao({ approved: 0, decided: 0 })).toBeNull();
  });

  // E devolver 0 seria pior que NaN por ser crivel: afirmaria que nada foi
  // aprovado, quando o verdadeiro e que nada foi decidido ainda.
  it("denominador zero nao vira zero", () => {
    expect(taxaDeAprovacao({ approved: 0, decided: 0 })).not.toBe(0);
  });

  it("nenhum aprovado com decididos e zero de verdade", () => {
    expect(taxaDeAprovacao({ approved: 0, decided: 5 })).toBe(0);
  });

  it("denominador corrompido cai no null em vez de taxa negativa", () => {
    expect(taxaDeAprovacao({ approved: 1, decided: -2 })).toBeNull();
    expect(taxaDeAprovacao({ approved: 1, decided: NaN })).toBeNull();
  });
});

describe("formatarTaxa", () => {
  it("null vira travessao — nunca NaN%, nunca 0%", () => {
    expect(formatarTaxa(null)).toBe("—");
  });

  it("zero real e mostrado como 0%", () => {
    expect(formatarTaxa(0)).toBe("0%");
  });

  it("arredonda para inteiro", () => {
    expect(formatarTaxa(0.624)).toBe("62%");
    expect(formatarTaxa(0.626)).toBe("63%");
    expect(formatarTaxa(1)).toBe("100%");
  });
});

describe("formatarBRL", () => {
  it("usa o formato pt-BR com duas casas", () => {
    expect(formatarBRL(1234.5)).toBe("R$ 1.234,50");
  });

  // O PostgREST devolve `numeric` como string em algumas rotas e o total pode
  // vir nulo de um orcamento recem-criado; nos dois casos o card precisa de um
  // numero, nao de "R$ NaN".
  it("nulo e indefinido viram zero, nao NaN", () => {
    expect(formatarBRL(null as unknown as number)).toBe("R$ 0,00");
    expect(formatarBRL(undefined as unknown as number)).toBe("R$ 0,00");
  });
});
