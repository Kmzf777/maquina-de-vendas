"use client";

import Link from "next/link";
import { Check, FileDown, Pencil, Receipt, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Quote } from "@/lib/types";
import {
  formatarBRL,
  numeroDoOrcamento,
  podeConverter,
  podeEditar,
  quoteStatus,
  type QuoteTone,
} from "@/lib/quotes/quote-display";

/**
 * Gramatica de cor da coluna "Situação".
 *
 * Seis situacoes sao demais para o vendedor ler palavra por palavra numa lista
 * de vinte e cinco linhas, entao a cor faz a triagem antes do texto:
 *
 *  - `waiting` ("Enviado") e o UNICO uso do laranja Fin nesta tela, porque e o
 *    unico estado que espera resposta do cliente — o que exige acao. O DESIGN.md
 *    proibe usar o laranja como enfeite justamente para que ele signifique algo
 *    quando aparecer.
 *  - `locked` ("Convertido") e solido em preto, nao tingido como os outros: e o
 *    fim da linha, e a diferenca de PESO (fundo cheio, texto branco) diz "isto
 *    esta fechado" sem depender de o vendedor distinguir dois verdes.
 *  - `draft` fica no cinza da propria interface porque rascunho e ausencia de
 *    estado, nao um estado.
 */
const TONE_CLASS: Record<QuoteTone, string> = {
  draft: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  waiting: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/25",
  approved: "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/30",
  refused: "bg-[#c41c1c]/8 text-[#c41c1c] border-[#c41c1c]/25",
  locked: "bg-[#111111] text-white border-[#111111]",
};

const TH =
  "py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium border-b border-[#dedbd6] h-auto";
const ACAO =
  "p-1 h-7 w-7 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#f0ede8] transition-colors";

interface QuotesTableProps {
  quotes: Quote[];
  loading: boolean;
  count: number;
  page: number;
  onPageChange: (p: number) => void;
  onEdit: (quote: Quote) => void;
  onStatusChange: (quote: Quote, status: "aprovado" | "nao_aprovado") => void;
  onConvert: (quote: Quote) => void;
  /**
   * Ids com uma chamada em voo. A pagina ja recusa o segundo clique, mas sem o
   * botao mudar de estado o vendedor nao tem como saber disso — e "Converter"
   * cria um pedido no ERP, entao a espera silenciosa convida exatamente ao
   * clique repetido que nao pode acontecer.
   */
  busyIds: ReadonlySet<string>;
}

const LIMIT = 25;

function StatusPill({ status }: { status: string }) {
  const view = quoteStatus(status);
  return (
    <span
      className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${TONE_CLASS[view.tone]}`}
    >
      {view.label}
    </span>
  );
}

export function QuotesTable({
  quotes,
  loading,
  count,
  page,
  onPageChange,
  onEdit,
  onStatusChange,
  onConvert,
  busyIds,
}: QuotesTableProps) {
  const totalPages = Math.ceil(count / LIMIT);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-12 bg-[#dedbd6]/30 rounded-[6px] animate-pulse" />
        ))}
      </div>
    );
  }

  if (quotes.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#7b7b78]">
          Nenhum orçamento encontrado para os filtros selecionados.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent border-[#dedbd6]">
              <TableHead className={TH}>Nº</TableHead>
              <TableHead className={TH}>Cliente</TableHead>
              <TableHead className={TH}>Vendedor</TableHead>
              <TableHead className={TH}>Data</TableHead>
              <TableHead className={`${TH} text-right`}>Itens</TableHead>
              <TableHead className={`${TH} text-right`}>Total</TableHead>
              <TableHead className={TH}>Situação</TableHead>
              <TableHead className={`${TH} text-right`}>Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {quotes.map((quote) => {
              // Durante a chamada em voo a linha INTEIRA congela, nao so o botao
              // clicado: aprovar enquanto uma conversao esta a caminho mandaria
              // duas situacoes diferentes para o Bling em ordem imprevisivel.
              // Desabilitado, e nao escondido — sumir com os botoes faria a
              // fileira encolher e reaparecer a cada acao.
              const ocupada = busyIds.has(quote.id);
              const editavel = podeEditar(quote);
              const convertivel = podeConverter(quote);
              return (
                <TableRow
                  key={quote.id}
                  className="border-b border-[#dedbd6]/50 hover:bg-[#faf9f6] transition-colors"
                >
                  <TableCell className="py-3 px-3 text-[#111111] font-medium whitespace-nowrap">
                    {numeroDoOrcamento(quote)}
                  </TableCell>
                  <TableCell className="py-3 px-3">
                    {quote.leads ? (
                      <Link
                        href={`/conversas?lead_id=${quote.lead_id}`}
                        className="text-[#111111] hover:underline truncate block max-w-[180px]"
                      >
                        {quote.leads.name || quote.leads.phone}
                      </Link>
                    ) : (
                      <span className="text-[#7b7b78]">—</span>
                    )}
                  </TableCell>
                  <TableCell className="py-3 px-3 text-[#7b7b78] max-w-[150px] truncate">
                    {quote.created_by || "—"}
                  </TableCell>
                  <TableCell className="py-3 px-3 text-[#7b7b78] whitespace-nowrap">
                    {/* `quoted_at` e `date` ("2026-08-25"). `new Date()` numa
                        string dessas parseia como UTC meia-noite e, num fuso
                        negativo como o de Sao Paulo, imprime o DIA ANTERIOR.
                        Reordenar os pedacos evita a data mentir por um dia. */}
                    {quote.quoted_at
                      ? quote.quoted_at.slice(0, 10).split("-").reverse().join("/")
                      : "—"}
                  </TableCell>
                  <TableCell className="py-3 px-3 text-[#7b7b78] text-right">
                    {/* Ausente (rota que nao embute) e diferente de vazio, mas os
                        dois viram "0" aqui: a coluna e uma contagem, e "—" num
                        lugar onde o vendedor espera um numero pareceria defeito. */}
                    {quote.quote_items?.length ?? 0}
                  </TableCell>
                  <TableCell className="py-3 px-3 text-[#111111] text-right whitespace-nowrap font-medium">
                    {formatarBRL(quote.total)}
                  </TableCell>
                  <TableCell className="py-3 px-3">
                    <StatusPill status={quote.status} />
                    {/* O convertido perde todas as acoes menos o PDF, entao o
                        atalho para a venda e a unica continuacao possivel da
                        linha — sem ele, o vendedor teria que procurar a venda
                        pelo nome no outro painel. */}
                    {quote.sale_id && (
                      <Link
                        href={`/painel-vendas?sale_id=${quote.sale_id}`}
                        className="ml-1.5 text-[11px] text-[#7b7b78] hover:text-[#111111] hover:underline inline-flex items-center gap-1 align-middle"
                        title="Abrir a venda gerada por este orçamento"
                      >
                        <Receipt size={11} />
                        venda
                      </Link>
                    )}
                  </TableCell>
                  <TableCell className="py-3 px-3 text-right whitespace-nowrap">
                    <div className="inline-flex items-center gap-1">
                      {/* Link de verdade, nao um fetch: `download` deixa o
                          navegador cuidar do arquivo (barra de progresso, pasta
                          de downloads, retomada) e o `Content-Disposition` que a
                          rota repassa e quem nomeia o arquivo. Baixar por fetch
                          exigiria segurar o PDF inteiro em memoria e inventar um
                          nome do lado do cliente. */}
                      <Button asChild variant="ghost" size="icon-sm" className={ACAO}>
                        <a
                          href={`/api/quotes/${quote.id}/pdf`}
                          download
                          title="Baixar PDF do orçamento"
                          aria-label="Baixar PDF do orçamento"
                        >
                          <FileDown size={14} />
                        </a>
                      </Button>

                      {/* Some — nao fica desabilitado — depois de convertido: o
                          PUT responderia 409 `quote_converted`, e um botao
                          apagado convida ao clique que nao vai funcionar. */}
                      {editavel && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          title="Editar orçamento"
                          aria-label="Editar orçamento"
                          onClick={() => onEdit(quote)}
                          disabled={ocupada}
                          className={ACAO}
                        >
                          <Pencil size={14} />
                        </Button>
                      )}

                      {/* "Aprovado" e "Não aprovado" só aparecem enquanto a
                          situação ainda pode mudar, e cada um some quando já é o
                          estado atual — marcar de novo o que já está marcado só
                          gastaria uma chamada ao Bling. */}
                      {editavel && quote.status !== "aprovado" && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          title="Marcar como aprovado"
                          aria-label="Marcar como aprovado"
                          onClick={() => onStatusChange(quote, "aprovado")}
                          disabled={ocupada}
                          className={`${ACAO} hover:text-[#0f9d43] hover:bg-[#0bdf50]/10`}
                        >
                          <Check size={14} />
                        </Button>
                      )}
                      {editavel && quote.status !== "nao_aprovado" && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          title="Marcar como não aprovado"
                          aria-label="Marcar como não aprovado"
                          onClick={() => onStatusChange(quote, "nao_aprovado")}
                          disabled={ocupada}
                          className={`${ACAO} hover:text-[#c41c1c] hover:bg-[#c41c1c]/8`}
                        >
                          <X size={14} />
                        </Button>
                      )}

                      {/* Converter é a única ação irreversível da linha, e a
                          única com rótulo em vez de ícone: um ícone a mais na
                          fileira seria clicado por engano, e "cria um pedido no
                          Bling e trava este orçamento" não cabe em nenhum
                          desenho. O contorno preto a separa das ações de ícone
                          sem competir com o verde de "Registrar Venda" no topo. */}
                      {convertivel && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => onConvert(quote)}
                          disabled={ocupada}
                          title="Criar o pedido de venda no Bling a partir deste orçamento"
                          className="ml-1 h-7 rounded-[4px] border-[#111111] bg-transparent text-[#111111] text-[12px] px-2.5 hover:bg-[#111111] hover:text-white transition-colors"
                        >
                          {ocupada ? "Convertendo…" : "Converter"}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4">
          <p className="text-[12px] text-[#7b7b78]">
            {count} orçamentos · página {page} de {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
              className="rounded-[4px] border-[#dedbd6] bg-white text-[#111111] text-[12px] hover:bg-[#faf9f6]"
            >
              Anterior
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="rounded-[4px] border-[#dedbd6] bg-white text-[#111111] text-[12px] hover:bg-[#faf9f6]"
            >
              Próxima
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
