"use client";

/**
 * Casca dos formulários de venda e orçamento: painel à direita SEM overlay.
 *
 * O `Dialog` borrava e bloqueava o chat — o vendedor fechava o modal para
 * copiar um dado da conversa e perdia o pedido (call de 01/10). Aqui o painel
 * é não-modal: a conversa continua visível, clicável e selecionável.
 *
 * `Sheet` com `modal={false}`: o Radix não renderiza o overlay nesse modo, não
 * trava o foco nem o `pointer-events` do body. Clicar fora fecharia o painel
 * por padrão — e "fora" é justamente o chat —, por isso `onInteractOutside`
 * cancela o fechamento. Fecha pelo X, por "Cancelar" ou pelo Esc — este só
 * com o foco DENTRO do painel: o Esc do Radix escuta o documento inteiro, e
 * um Esc dado no chat (fechar emoji, sair da busca) descartava o pedido.
 *
 * `components/ui/dialog.tsx` não é tocado: é compartilhado pelo CRM inteiro.
 *
 * Modo ACOPLADO (só em /conversas, via `PainelAcopladoContext`): mesmo sem
 * overlay, o Sheet ficava POR CIMA do chat e cortava as mensagens — inclusive
 * a que tinha CPF, endereço e e-mail que o vendedor precisava copiar (print de
 * 07/10, tela de 1600 px). Acoplado, o painel é renderizado no próprio lugar,
 * sem portal, e vira uma coluna do layout ao lado do chat; a página recolhe a
 * lista de conversas para abrir espaço. As demais telas não fornecem o
 * contexto e seguem com o Sheet sobreposto, idênticas.
 */
import { createContext, useContext, useEffect, useId, useRef } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

/** `true` = renderizar como coluna do layout (sem portal). Padrão: sobreposto. */
export const PainelAcopladoContext = createContext(false);

// Sem "xl" (896 px): o orçamento usava e cobria quase todo o chat, que é
// justamente o que o painel não-modal existe para deixar à vista.
const LARGURA = {
  md: "data-[side=right]:sm:max-w-md",
  lg: "data-[side=right]:sm:max-w-2xl",
} as const;

// Acoplado: as MESMAS larguras (28rem/42rem) fixas, para o formulário não
// ficar mais apertado que no modo sobreposto. Quem cede espaço é o chat.
const LARGURA_ACOPLADO = {
  md: "w-[28rem]",
  lg: "w-[42rem]",
} as const;

/**
 * Título do painel com o nome do lead: com o painel não-modal e a conversa
 * visível ao lado, o título é o que diz para quem a venda ou o orçamento está sendo feito.
 */
export function comNome(titulo: string, nome: string | null | undefined): string {
  const n = (nome ?? "").trim();
  return n ? `${titulo} — ${n}` : titulo;
}

interface PainelLateralProps {
  titulo: string;
  largura?: keyof typeof LARGURA;
  onFechar: () => void;
  children: React.ReactNode;
}

export function PainelLateral({
  titulo,
  largura = "lg",
  onFechar,
  children,
}: PainelLateralProps) {
  const acoplado = useContext(PainelAcopladoContext);
  const conteudo = useRef<HTMLDivElement>(null);
  if (acoplado) {
    return (
      <PainelAcoplado titulo={titulo} largura={largura} onFechar={onFechar}>
        {children}
      </PainelAcoplado>
    );
  }
  return (
    <Sheet
      open
      modal={false}
      onOpenChange={(aberto) => {
        if (!aberto) onFechar();
      }}
    >
      <SheetContent
        side="right"
        showCloseButton={false}
        aria-describedby={undefined}
        ref={conteudo}
        data-largura={largura}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          const foco = document.activeElement;
          if (!foco || !conteudo.current?.contains(foco)) e.preventDefault();
        }}
        className={`bg-white border-l border-[#dedbd6] p-0 gap-0 flex flex-col data-[side=right]:w-full ${LARGURA[largura]}`}
      >
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-[#dedbd6]">
          <SheetTitle className="text-[15px] font-medium text-[#111111]">{titulo}</SheetTitle>
          <BotaoFechar onFechar={onFechar} />
        </div>
        <div className="min-h-0 flex-1 flex flex-col">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

function BotaoFechar({ onFechar }: { onFechar: () => void }) {
  return (
    <button
      type="button"
      onClick={onFechar}
      aria-label="Fechar"
      className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
    >
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  );
}

/**
 * Coluna inline. O Esc é ouvido no próprio painel, então só dispara com o foco
 * dentro dele (mesma regra do modo sobreposto). Um Esc que um popover/select
 * de dentro já consumiu chega com `defaultPrevented` — o DismissableLayer do
 * Radix escuta em captura no documento e chama `preventDefault` ao fechar a
 * camada — e não pode descartar o pedido junto.
 */
function PainelAcoplado({
  titulo,
  largura,
  onFechar,
  children,
}: Required<Omit<PainelLateralProps, "children">> & { children: React.ReactNode }) {
  const raiz = useRef<HTMLElement>(null);
  const idTitulo = useId();
  // Foco no painel ao abrir (o Sheet fazia isso sozinho): o botão que abriu
  // fica escondido junto com o detalhe do contato e o foco cairia no body.
  useEffect(() => {
    raiz.current?.focus({ preventScroll: true });
  }, []);
  return (
    <section
      ref={raiz}
      role="dialog"
      aria-modal="false"
      aria-labelledby={idTitulo}
      tabIndex={-1}
      data-slot="painel-acoplado"
      data-largura={largura}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !e.defaultPrevented) {
          e.preventDefault();
          onFechar();
        }
      }}
      className={`h-full shrink-0 bg-white border-l border-[#dedbd6] flex flex-col outline-none ${LARGURA_ACOPLADO[largura]}`}
    >
      <div className="shrink-0 flex items-center justify-between gap-3 px-5 py-4 border-b border-[#dedbd6]">
        <h2 id={idTitulo} className="min-w-0 truncate text-[15px] font-medium text-[#111111]" title={titulo}>
          {titulo}
        </h2>
        <BotaoFechar onFechar={onFechar} />
      </div>
      <div className="min-h-0 flex-1 flex flex-col">{children}</div>
    </section>
  );
}
