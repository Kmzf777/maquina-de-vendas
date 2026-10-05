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
 * cancela o fechamento. Fecha pelo X, por "Cancelar" ou pelo Esc.
 *
 * `components/ui/dialog.tsx` não é tocado: é compartilhado pelo CRM inteiro.
 */
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

const LARGURA = {
  md: "data-[side=right]:sm:max-w-md",
  lg: "data-[side=right]:sm:max-w-2xl",
  xl: "data-[side=right]:sm:max-w-4xl",
} as const;

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
        onInteractOutside={(e) => e.preventDefault()}
        className={`bg-white border-l border-[#dedbd6] p-0 gap-0 flex flex-col data-[side=right]:w-full ${LARGURA[largura]}`}
      >
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-[#dedbd6]">
          <SheetTitle className="text-[15px] font-medium text-[#111111]">{titulo}</SheetTitle>
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
        </div>
        <div className="min-h-0 flex-1 flex flex-col">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
