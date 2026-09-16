/**
 * `contaTravadaDaVenda` decide se o vendedor pode trocar a conta Bling ao
 * editar uma venda — errar aqui na direcao "liberado" deixaria um PUT tentar
 * alterar um pedido usando o CNPJ errado (o `bling_order_id` so existe na
 * conta em que nasceu). Testado isolado da UI, mesmo padrao de
 * `lib/bling-accounts.test.ts`.
 */
import { describe, expect, it } from "vitest";
import { contaTravadaDaVenda } from "./sale-create-modal";
import { CONTA_PADRAO } from "@/lib/bling-accounts";

/**
 * `Sale` tem dezenas de campos obrigatorios que nao importam para esta
 * funcao — ela so le `bling_order_id`, `bling_order_number` e
 * `bling_account`. O cast via `unknown` documenta que o fixture e
 * deliberadamente parcial, nao um descuido de tipagem.
 */
type VendaFixture = Parameters<typeof contaTravadaDaVenda>[0];
const venda = (campos: {
  bling_order_id: number | null;
  bling_order_number?: number;
  bling_account?: string;
}): VendaFixture => campos as unknown as VendaFixture;

describe("contaTravadaDaVenda", () => {
  it("nao trava ao criar uma venda nova (isEditing false)", () => {
    expect(contaTravadaDaVenda(null, false, true)).toBeUndefined();
  });

  it("nao trava editando uma venda sem pedido no Bling (nada a proteger)", () => {
    expect(
      contaTravadaDaVenda(venda({ bling_order_id: null, bling_account: "secundaria" }), true, true),
    ).toBeUndefined();
  });

  it("nao trava quando blingEditable e false (edicao local, sem PUT no ERP)", () => {
    expect(
      contaTravadaDaVenda(venda({ bling_order_id: 123, bling_account: "secundaria" }), true, false),
    ).toBeUndefined();
  });

  it("trava na conta gravada quando ha pedido no Bling", () => {
    const v = venda({ bling_order_id: 123, bling_order_number: 456, bling_account: "secundaria" });
    expect(contaTravadaDaVenda(v, true, true)).toEqual({
      valor: "secundaria",
      dica: "Definido pelo pedido #456",
    });
  });

  it("cai para CONTA_PADRAO quando a venda e anterior a migration (bling_account ausente)", () => {
    const v = venda({ bling_order_id: 123, bling_order_number: 456 });
    expect(contaTravadaDaVenda(v, true, true)).toEqual({
      valor: CONTA_PADRAO,
      dica: "Definido pelo pedido #456",
    });
  });

  it("dica sem numero do pedido nao deixa '#' solto", () => {
    const v = venda({ bling_order_id: 123, bling_account: CONTA_PADRAO });
    expect(contaTravadaDaVenda(v, true, true)).toEqual({
      valor: CONTA_PADRAO,
      dica: "Definido pelo pedido",
    });
  });
});
