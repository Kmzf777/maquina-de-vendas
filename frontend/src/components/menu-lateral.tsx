"use client";

/**
 * Estado do menu lateral (desktop): aberto (220 px) ou recolhido (só ícones).
 *
 * Cartão a22d0f72: o painel de orçamento/venda tampava o chat em telas < 1280
 * e o vendedor não conseguia copiar CPF/endereço da conversa. Recolher o menu
 * devolve ~164 px, o bastante para o painel caber ao lado do chat a partir de
 * 1100 px. O painel recolhe o menu sozinho ao abrir e devolve ao fechar —
 * só se foi ele quem recolheu; a escolha manual (salva no localStorage)
 * sempre vence.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from "react";

export type EstadoMenu = { recolhido: boolean; peloPainel: boolean };
export type AcaoMenu =
  | { tipo: "alternar" }
  | { tipo: "recolherPeloPainel" }
  | { tipo: "restaurarDoPainel" }
  | { tipo: "carregar"; recolhido: boolean };

export const CHAVE_MENU = "valeria:menu-recolhido";

export function reduzirMenu(estado: EstadoMenu, acao: AcaoMenu): EstadoMenu {
  switch (acao.tipo) {
    case "alternar":
      return { recolhido: !estado.recolhido, peloPainel: false };
    case "recolherPeloPainel":
      return estado.recolhido ? estado : { recolhido: true, peloPainel: true };
    case "restaurarDoPainel":
      return estado.peloPainel ? { recolhido: false, peloPainel: false } : estado;
    case "carregar":
      return { recolhido: acao.recolhido, peloPainel: false };
  }
}

type MenuLateral = {
  recolhido: boolean;
  alternar: () => void;
  recolherPeloPainel: () => void;
  restaurarDoPainel: () => void;
};

const nada = () => {};
const MenuLateralContext = createContext<MenuLateral>({
  recolhido: false,
  alternar: nada,
  recolherPeloPainel: nada,
  restaurarDoPainel: nada,
});

export function MenuLateralProvider({ children }: { children: React.ReactNode }) {
  const [estado, despachar] = useReducer(reduzirMenu, { recolhido: false, peloPainel: false });

  // Depois de montar: o servidor não conhece o localStorage, e nascer aberto
  // nos dois lados evita erro de hidratação.
  useEffect(() => {
    try {
      if (localStorage.getItem(CHAVE_MENU) === "1") despachar({ tipo: "carregar", recolhido: true });
    } catch {}
  }, []);

  // Grava só a escolha manual: o recolher do painel é temporário.
  const alternar = useCallback(() => {
    const novo = !estado.recolhido;
    despachar({ tipo: "alternar" });
    try {
      localStorage.setItem(CHAVE_MENU, novo ? "1" : "0");
    } catch {}
  }, [estado.recolhido]);

  const recolherPeloPainel = useCallback(() => despachar({ tipo: "recolherPeloPainel" }), []);
  const restaurarDoPainel = useCallback(() => despachar({ tipo: "restaurarDoPainel" }), []);

  const valor = useMemo(
    () => ({ recolhido: estado.recolhido, alternar, recolherPeloPainel, restaurarDoPainel }),
    [estado.recolhido, alternar, recolherPeloPainel, restaurarDoPainel],
  );
  return <MenuLateralContext value={valor}>{children}</MenuLateralContext>;
}

export function useMenuLateral(): MenuLateral {
  return useContext(MenuLateralContext);
}
