/**
 * Dublê do `@/components/ui/popover` para testes de componente.
 *
 * Abrir o Popover do Radix no jsdom prende o worker do vitest num laço de
 * posicionamento (floating-ui sem layout). Este dublê mantém só o contrato que
 * os componentes usam — `open`/`onOpenChange` controlados, o gatilho alterna,
 * o conteúdo aparece quando aberto — sem posicionamento nenhum.
 *
 * Uso: `vi.mock("@/components/ui/popover", async () =>
 *   (await import("./popover-duble.test-utils")).dublePopover());`
 */
import * as React from "react";

type Ctx = { open: boolean; setOpen: (v: boolean) => void };

export function dublePopover() {
  const Contexto = React.createContext<Ctx>({ open: false, setOpen: () => {} });

  function Popover({
    open,
    onOpenChange,
    children,
  }: {
    open?: boolean;
    onOpenChange?: (v: boolean) => void;
    children?: React.ReactNode;
  }) {
    return React.createElement(
      Contexto.Provider,
      { value: { open: !!open, setOpen: (v: boolean) => onOpenChange?.(v) } },
      children,
    );
  }

  function PopoverTrigger({ children }: { children: React.ReactElement<{ onClick?: () => void }> }) {
    const ctx = React.useContext(Contexto);
    return React.cloneElement(children, { onClick: () => ctx.setOpen(!ctx.open) });
  }

  function PopoverContent({ children }: { children?: React.ReactNode }) {
    const ctx = React.useContext(Contexto);
    return ctx.open ? React.createElement("div", { "data-testid": "popover" }, children) : null;
  }

  return { Popover, PopoverTrigger, PopoverContent };
}
