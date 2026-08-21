"use client";

/**
 * Itens, forma de pagamento e parcelas do pedido Bling.
 *
 * Casca de renderização: toda a regra (linha completa, total, payload, parcelas)
 * vive em `@/lib/bling-order-state` e `@/lib/bling`, que são testados. Aqui só
 * há estado de tela e formatação.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { CheckIcon, ChevronDownIcon, PlusIcon, XIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { parseTerms } from "@/lib/bling";
import {
  addLine,
  applyProduct,
  blankLine,
  buildOrderPayload,
  defaultPaymentMethodId,
  lineTotal,
  removeLine,
  updateLine,
  type BlingPaymentMethod,
  type BlingProduct,
  type OrderLine,
  type OrderPayloadResult,
} from "@/lib/bling-order-state";

interface BlingOrderFormProps {
  /** Campos do pedido que pertencem ao modal, não a este bloco. */
  meta: {
    leadId: string;
    dealId: string | null;
    soldAt: string;
    soldBy: string | null;
    notes: string;
  };
  /** `condicao_pagamento` do contato no Bling, quando o modal a conhece. */
  condicaoPagamento?: string | null;
  onChange: (result: OrderPayloadResult) => void;
}

const label = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]";
const control =
  "h-[34px] w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 text-[13px] text-[#111111] tabular-nums focus:border-[#111111] focus:outline-none focus:ring-0";
const grid =
  "grid grid-cols-[minmax(0,1fr)_58px_92px_58px_86px_26px] gap-2 items-center";

const brl = (valor: number) =>
  valor.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

/** "2026-09-17" -> "17/09/2026", sem passar por Date (fuso não altera o dia). */
const diaMesAno = (iso: string) =>
  `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

const toNumber = (raw: string) => {
  const n = Number(raw.replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : 0;
};

/** Zero aparece como campo vazio para o vendedor digitar por cima. */
const numText = (n: number) => (n ? String(n) : "");

/** Campos numéricos da linha que o vendedor edita. */
type CampoNumerico = "quantidade" | "valorUnitario" | "descontoPercentual";

export function BlingOrderForm({
  meta,
  condicaoPagamento,
  onChange,
}: BlingOrderFormProps) {
  const { leadId, dealId, soldAt, soldBy, notes } = meta;

  const [linhas, setLinhas] = useState<OrderLine[]>([blankLine()]);
  const [paymentMethodId, setPaymentMethodId] = useState<number | null>(null);
  // Enquanto o vendedor não digita nada, os prazos são os do contato no Bling —
  // derivado, não copiado, para que a condição valha mesmo se chegar depois do
  // primeiro render (o modal pode buscá-la em paralelo).
  const [termsEdit, setTermsEdit] = useState<string | null>(null);
  const termsRaw = termsEdit ?? condicaoPagamento ?? "";

  const [metodos, setMetodos] = useState<BlingPaymentMethod[]>([]);
  const [resultados, setResultados] = useState<BlingProduct[]>([]);
  const [conhecidos, setConhecidos] = useState<Record<number, BlingProduct>>({});
  const [busca, setBusca] = useState("");
  // Texto cru do campo numérico em edição (um por vez): ver `numeroProps`.
  const [rascunho, setRascunho] = useState<{ chave: string; texto: string } | null>(
    null,
  );
  const [aberta, setAberta] = useState<number | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [falhaCatalogo, setFalhaCatalogo] = useState<string | null>(null);

  // ── catálogo e formas de pagamento ───────────────────────────────────────
  const pedidoRef = useRef(0);

  useEffect(() => {
    let vivo = true;
    fetch("/api/bling/payment-methods")
      .then((r) => r.json())
      .then((d) => {
        if (!vivo) return;
        const lista: BlingPaymentMethod[] = Array.isArray(d?.data) ? d.data : [];
        setMetodos(lista);
        setPaymentMethodId((atual) => atual ?? defaultPaymentMethodId(lista));
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, []);

  // Busca no espelho a cada tecla (com respiro), porque o catálogo pode ser
  // maior do que uma página — filtrar só o que veio no mount esconderia produto.
  useEffect(() => {
    const termo = busca.trim();
    const atraso = termo ? 250 : 0;
    const timer = setTimeout(() => {
      const meu = ++pedidoRef.current;
      setCarregando(true);
      fetch(
        `/api/bling/products?limit=${termo ? 50 : 100}${
          termo ? `&q=${encodeURIComponent(termo)}` : ""
        }`,
      )
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error("http"))))
        .then((d) => {
          if (meu !== pedidoRef.current) return; // resposta atrasada, descarta
          const lista: BlingProduct[] = Array.isArray(d?.data) ? d.data : [];
          setResultados(lista);
          setConhecidos((antes) => {
            const mapa = { ...antes };
            for (const p of lista) mapa[p.id] = p;
            return mapa;
          });
          setFalhaCatalogo(null);
          setCarregando(false);
        })
        .catch(() => {
          if (meu !== pedidoRef.current) return;
          setFalhaCatalogo("Não foi possível carregar o catálogo do Bling.");
          setCarregando(false);
        });
    }, atraso);
    return () => clearTimeout(timer);
  }, [busca]);

  // ── resultado publicado para o modal ─────────────────────────────────────
  const result = useMemo(
    () =>
      buildOrderPayload(linhas, {
        leadId,
        dealId,
        soldAt,
        soldBy,
        notes,
        paymentMethodId,
        terms: parseTerms(termsRaw),
      }),
    [linhas, leadId, dealId, soldAt, soldBy, notes, paymentMethodId, termsRaw],
  );

  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  useEffect(() => {
    onChangeRef.current(result);
  }, [result]);

  // ── render ───────────────────────────────────────────────────────────────
  const semParcela = result.total > 0 && result.installments.length === 0;

  /**
   * Campo numérico da linha.
   *
   * O texto cru do campo em edição fica num rascunho até o blur porque o número
   * sozinho não representa o que está sendo digitado: "0," e "0,5" viram 0, e o
   * campo se limparia no meio da digitação — venda por peso (1,5 kg) ficaria
   * impossível. `type="text"` com `inputMode="decimal"` também é de propósito:
   * `type="number"` descarta a vírgula, que é como se digita preço em pt-BR.
   */
  const numeroProps = (i: number, campo: CampoNumerico, linha: OrderLine) => {
    const chave = `${i}:${campo}`;
    return {
      type: "text" as const,
      inputMode: "decimal" as const,
      value: rascunho?.chave === chave ? rascunho.texto : numText(linha[campo]),
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
        const texto = e.target.value;
        const valor = toNumber(texto);
        setRascunho({ chave, texto });
        setLinhas((atuais) =>
          updateLine(
            atuais,
            i,
            campo === "quantidade"
              ? { quantidade: valor }
              : campo === "valorUnitario"
                ? { valorUnitario: valor }
                : { descontoPercentual: valor },
          ),
        );
      },
      onBlur: () => setRascunho(null),
    };
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className={label}>Itens do pedido *</span>
          {falhaCatalogo && (
            <span className="text-[11px] text-[#c41c1c]">{falhaCatalogo}</span>
          )}
        </div>

        <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <div
            className={`${grid} bg-[#faf9f6] border-b border-[#dedbd6] px-3 py-2 text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]`}
          >
            <span>Produto</span>
            <span className="text-right">Qtd</span>
            <span className="text-right">Valor un.</span>
            <span className="text-right">Desc %</span>
            <span className="text-right">Total</span>
            <span />
          </div>

          {linhas.map((linha, i) => {
            const produto = linha.blingProductId
              ? conhecidos[linha.blingProductId]
              : undefined;
            const saldo = produto?.saldo_virtual;
            return (
              <div
                key={i}
                className={`${grid} px-3 py-2 border-b border-[#dedbd6] last:border-b-0`}
              >
                {/* Produto */}
                <Popover
                  open={aberta === i}
                  onOpenChange={(open) => {
                    setAberta(open ? i : null);
                    if (open) setBusca("");
                  }}
                >
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      className="h-[34px] w-full flex items-center justify-between gap-2 bg-white border border-[#dedbd6] rounded-[4px] px-2.5 text-[13px] text-left text-[#111111] hover:border-[#c9c5be] focus:border-[#111111] focus:outline-none"
                    >
                      <span className="min-w-0 truncate">
                        {linha.descricao || (
                          <span className="text-[#8a8a8a]">Selecione o produto</span>
                        )}
                      </span>
                      <ChevronDownIcon className="size-4 shrink-0 text-[#8a8a8a]" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent className="p-0 w-(--radix-popover-trigger-width) min-w-[280px]" portal={false}>
                    <div className="p-2 border-b border-[#eee]">
                      <input
                        autoFocus
                        value={busca}
                        onChange={(e) => setBusca(e.target.value)}
                        placeholder="Buscar por nome ou SKU..."
                        className="h-8 w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
                      />
                    </div>
                    <div className="max-h-64 overflow-y-auto p-1">
                      {carregando && (
                        <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">
                          Buscando...
                        </div>
                      )}
                      {!carregando && resultados.length === 0 && (
                        <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">
                          Nenhum produto encontrado.
                        </div>
                      )}
                      {resultados.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => {
                            setLinhas((atuais) =>
                              applyProduct(atuais, i, p.id, resultados),
                            );
                            setAberta(null);
                            setBusca("");
                          }}
                          className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-[#f4f2ee]"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-[13px] text-[#111111]">
                              {p.nome}
                            </span>
                            <span className="block text-[11px] text-[#7b7b78]">
                              {p.codigo ?? "sem SKU"}
                              {p.preco != null && ` · R$ ${brl(p.preco)}`}
                              {p.saldo_virtual != null &&
                                ` · saldo ${p.saldo_virtual}`}
                            </span>
                          </span>
                          {linha.blingProductId === p.id && (
                            <CheckIcon className="size-4 shrink-0" />
                          )}
                        </button>
                      ))}
                    </div>
                  </PopoverContent>
                </Popover>

                <input
                  {...numeroProps(i, "quantidade", linha)}
                  placeholder="0"
                  aria-label="Quantidade"
                  className={`${control} text-right`}
                />
                <input
                  {...numeroProps(i, "valorUnitario", linha)}
                  placeholder="0,00"
                  aria-label="Valor unitário"
                  className={`${control} text-right`}
                />
                <input
                  {...numeroProps(i, "descontoPercentual", linha)}
                  placeholder="0"
                  aria-label="Desconto percentual"
                  className={`${control} text-right`}
                />

                <span className="text-[13px] text-[#111111] tabular-nums text-right">
                  {brl(lineTotal(linha))}
                </span>

                <button
                  type="button"
                  onClick={() => setLinhas((atuais) => removeLine(atuais, i))}
                  disabled={linhas.length <= 1}
                  aria-label="Remover item"
                  title="Remover item"
                  className="w-[26px] h-[26px] flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#f0ede8] hover:text-[#c41c1c] disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-[#7b7b78] transition-colors"
                >
                  <XIcon className="size-3.5" />
                </button>

                {/* Linha de apoio: SKU, unidade e saldo — informação, nunca trava */}
                {produto && (
                  <p className="col-span-6 -mt-0.5 text-[11px] text-[#7b7b78]">
                    {produto.codigo ?? "sem SKU"}
                    {produto.unidade ? ` · ${produto.unidade}` : ""}
                    {saldo != null && (
                      <span className={saldo <= 0 ? "text-[#ff5600]" : undefined}>
                        {` · saldo no Bling: ${saldo}`}
                      </span>
                    )}
                  </p>
                )}
              </div>
            );
          })}

          <div className="flex items-center justify-between bg-[#faf9f6] border-t border-[#dedbd6] px-3 py-2">
            <button
              type="button"
              onClick={() => setLinhas((atuais) => addLine(atuais))}
              className="inline-flex items-center gap-1 text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors"
            >
              <PlusIcon className="size-3.5" />
              Adicionar item
            </button>
            <span className="text-[13px] text-[#111111] tabular-nums">
              Total{" "}
              <strong className="font-medium">R$ {brl(result.total)}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* Pagamento */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={`${label} block mb-1`}>Forma de pagamento *</label>
          <Select
            value={paymentMethodId ? String(paymentMethodId) : undefined}
            onValueChange={(v) => setPaymentMethodId(Number(v))}
          >
            <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
              <SelectValue placeholder="Selecione" />
            </SelectTrigger>
            <SelectContent position="popper">
              {metodos.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>
                  {m.descricao}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className={`${label} block mb-1`}>Prazos (dias)</label>
          <input
            type="text"
            value={termsRaw}
            onChange={(e) => setTermsEdit(e.target.value)}
            placeholder="30/60/90 — vazio = à vista"
            className="h-[37px] w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0"
          />
        </div>
      </div>

      {/* Parcelas */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] px-3 py-2.5">
        <span className={label}>
          {result.installments.length === 1
            ? "Parcela"
            : `${result.installments.length || ""} Parcelas`.trim()}
        </span>
        {semParcela ? (
          <p className="mt-1 text-[12px] text-[#c41c1c]">
            Não é possível dividir R$ {brl(result.total)} em{" "}
            {parseTerms(termsRaw).length} parcelas — alguma ficaria sem valor.
          </p>
        ) : result.installments.length === 0 ? (
          <p className="mt-1 text-[12px] text-[#7b7b78]">
            Escolha os itens para ver a previsão das parcelas.
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {result.installments.map((p, i) => (
              <li
                key={i}
                className="flex items-center justify-between text-[13px] text-[#111111] tabular-nums"
              >
                <span className="text-[#7b7b78]">
                  {i + 1}ª · {diaMesAno(p.dataVencimento)}
                </span>
                <span>R$ {brl(p.valor)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
