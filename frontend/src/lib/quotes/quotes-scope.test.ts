import { describe, it, expect } from "vitest";
import { quotesScopeFilter, podeVerOrcamento } from "@/lib/quotes/quotes-scope";

const admin = { userId: "u1", email: "comercial@cafecanastra.com", role: "admin" };
const vendedor = { userId: "u2", email: "joao@cafecanastra.com", role: "vendedor" };

describe("quotesScopeFilter", () => {
  it("admin nao tem escopo", () => {
    expect(quotesScopeFilter(admin, true)).toBeNull();
  });

  it("flag desligada devolve o comportamento global", () => {
    expect(quotesScopeFilter(vendedor, false)).toBeNull();
  });

  it("vendedor ve so os proprios orcamentos", () => {
    expect(quotesScopeFilter(vendedor, true)).toBe("created_by.ilike.joao@cafecanastra.com");
  });

  // A diferenca de regra para `salesScopeFilter`, escrita como teste para que
  // uma copia distraida do filtro de vendas quebre aqui: nao ha orcamento
  // importado do ERP (decisao 17), entao nada de `origin.eq.bling` — que, se
  // entrasse, faria todo orcamento com `origin` nulo... nem existe a coluna.
  // Colar a regra de vendas produziria um 400 do PostgREST em producao.
  it("nao carrega a excecao de origem que vendas tem", () => {
    expect(quotesScopeFilter(vendedor, true)).not.toContain("origin");
  });

  // `ilike` e o que torna a comparacao insensivel a maiusculas. O e-mail vem com
  // a grafia da conta do Supabase; com `eq`, uma inicial maiuscula casaria zero
  // linhas e a tela abriria vazia — sem erro, o que e o pior modo de falhar.
  it("usa ilike, nao eq", () => {
    expect(quotesScopeFilter({ ...vendedor, email: "Joao@Cafecanastra.com" }, true)).toBe(
      "created_by.ilike.Joao@Cafecanastra.com",
    );
  });

  // Fail-closed. Devolver null aqui significaria "sem escopo" e abriria os
  // orcamentos de toda a operacao para um usuario sem e-mail; o chamador trata
  // a excecao como 401.
  it("vendedor sem e-mail e recusado, nao liberado", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "" }, true)).toThrow();
  });

  it("e-mail so com espacos e recusado", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "   " }, true)).toThrow();
  });

  it("e-mail indefinido e recusado", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: undefined }, true)).toThrow();
  });

  // Os quatro casos abaixo cobrem a defesa importada de `sales-scope.ts`. Estao
  // duplicados de proposito: sao a garantia de que o filtro de orcamento
  // continua PASSANDO pela validacao. Se alguem "simplificar" este arquivo
  // trocando `emailSeguroParaFiltro(user.email)` por `user.email`, os testes de
  // vendas seguem verdes e so estes pegam a regressao.
  it("e-mail com virgula e recusado — injetaria um termo no or", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "a,b@x.com" }, true)).toThrow();
  });

  it("e-mail com asterisco e recusado — alargaria o escopo", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "j*@x.com" }, true)).toThrow();
  });

  it("e-mail com porcento e recusado — e curinga de ILIKE", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "j%@x.com" }, true)).toThrow();
  });

  it("e-mail com parenteses e recusado", () => {
    expect(() => quotesScopeFilter({ ...vendedor, email: "a(b)@x.com" }, true)).toThrow();
  });

  // Contrapartida: os dois caracteres que PRECISAM passar. Recusar o ponto
  // travaria todo mundo (todo dominio tem um) e recusar o underscore travaria
  // uma parte dos usuarios reais.
  it("ponto no dominio e aceito", () => {
    expect(quotesScopeFilter(vendedor, true)).toContain("joao@cafecanastra.com");
  });

  it("underscore no e-mail e aceito", () => {
    expect(quotesScopeFilter({ ...vendedor, email: "joao_silva@x.com" }, true)).toContain(
      "joao_silva@x.com",
    );
  });

  // Espaco em volta e erro de digitacao no cadastro, nao motivo para recusar —
  // mas tem que sair antes de virar valor de filtro, senao o `ilike` procura um
  // e-mail com espaco e nao acha nada.
  it("apara espacos em volta", () => {
    expect(quotesScopeFilter({ ...vendedor, email: "  joao@x.com  " }, true)).toBe(
      "created_by.ilike.joao@x.com",
    );
  });

  // Papel diferente de `role`: qualquer coisa que nao seja exatamente "admin" e
  // tratada como vendedor. Um role novo ("gestor", "suporte") entra escopado por
  // padrao em vez de ganhar acesso total por omissao.
  it("role desconhecido e tratado como vendedor, nao como admin", () => {
    expect(quotesScopeFilter({ ...vendedor, role: "gestor" }, true)).toBe(
      "created_by.ilike.joao@cafecanastra.com",
    );
    expect(quotesScopeFilter({ ...vendedor, role: undefined }, true)).toBe(
      "created_by.ilike.joao@cafecanastra.com",
    );
  });
});

describe("podeVerOrcamento", () => {
  const meu = { created_by: "joao@cafecanastra.com" };
  const alheio = { created_by: "comercial2@cafecanastra.com" };

  it("admin ve qualquer orcamento", () => {
    expect(podeVerOrcamento(alheio, admin, true)).toBe(true);
  });

  it("flag desligada devolve o comportamento global", () => {
    expect(podeVerOrcamento(alheio, vendedor, false)).toBe(true);
  });

  it("vendedor ve o proprio", () => {
    expect(podeVerOrcamento(meu, vendedor, true)).toBe(true);
  });

  // O defeito que esta funcao existe para fechar: com o UUID na mao, ler ou
  // baixar o PDF de um orcamento alheio era operacao livre para qualquer
  // usuario autenticado. O PDF carrega preco negociado e margem — vaza mais que
  // a linha da tabela.
  it("vendedor NAO ve o de outro vendedor", () => {
    expect(podeVerOrcamento(alheio, vendedor, true)).toBe(false);
  });

  // Caixa: o e-mail gravado tem a grafia da conta do Supabase, que ja apareceu
  // com maiuscula em producao ("Comercial2@..."). Comparacao sensivel a caixa
  // esconderia do vendedor os proprios orcamentos.
  it("compara sem diferenciar maiusculas", () => {
    expect(podeVerOrcamento({ created_by: "Joao@CafeCanastra.com" }, vendedor, true)).toBe(true);
  });

  // Fail-closed, e o INVERSO de `podeVerVenda`: la, venda sem dono (origin
  // 'bling') e material legitimo de conferencia; aqui nao existe orcamento
  // importado, entao `created_by` nulo so pode ser defeito nosso — e defeito
  // nao vira permissao.
  it("orcamento sem dono nao e visivel para vendedor", () => {
    expect(podeVerOrcamento({ created_by: null }, vendedor, true)).toBe(false);
    expect(podeVerOrcamento({ created_by: "" }, vendedor, true)).toBe(false);
  });

  // A mesma defesa do filtro vale aqui: e-mail ausente ou com curinga do
  // PostgREST LEVANTA em vez de devolver `false` silencioso, para a rota
  // transformar em 401 em vez de 404.
  it("e-mail inutilizavel levanta em vez de decidir", () => {
    expect(() => podeVerOrcamento(meu, { ...vendedor, email: undefined }, true)).toThrow();
    expect(() => podeVerOrcamento(meu, { ...vendedor, email: "jo*@x.com" }, true)).toThrow();
  });
});
