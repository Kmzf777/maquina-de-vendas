# Design: Correções de Visibilidade para Perfil Vendedor

**Data:** 2026-06-10  
**Branch:** fix/vendedor-ui-visibility  
**Escopo:** Renderização condicional de componentes de UI com base no perfil do usuário

---

## Contexto

Usuários com perfil `vendedor` estavam visualizando elementos de UI sem ação disponível:

1. Cabeçalhos de grupo "Dados" e "Sistema" no menu lateral, mesmo com todos os itens filtrados
2. Seletor de canal em `/conversas`, mesmo tendo acesso a apenas 1 canal

---

## Mudanças

### 1. Sidebar — Ocultar grupos vazios (`sidebar.tsx`)

**Arquivo:** `frontend/src/components/sidebar.tsx`

**Causa raiz:** `NAV_GROUPS.map()` renderiza todos os grupos. Os itens dentro de "Dados" e "Sistema" já têm `roles: ["admin"]` e são filtrados corretamente, mas o cabeçalho do grupo continua visível como seção vazia.

**Solução:** Adicionar `.filter()` no nível do grupo antes do `.map()`, usando a mesma lógica já aplicada aos itens:

```tsx
NAV_GROUPS
  .filter((group) =>
    group.items.some((item) => !item.roles || item.roles.includes(role))
  )
  .map((group) => ...)
```

**Regra:** Um grupo só é renderizado se pelo menos um de seus itens passar no filtro de role.

---

### 2. ChatList — Ocultar seletor de canal com 1 item (`chat-list.tsx`)

**Arquivo:** `frontend/src/components/conversas/chat-list.tsx`

**Causa raiz:** O bloco `{/* Channel filter */}` (linhas 156–176) é renderizado incondicionalmente, independentemente do número de canais disponíveis.

**Solução:** Envolver o bloco com uma condição `channels.length > 1`:

```tsx
{channels.length > 1 && (
  <div className="px-3 pt-3 pb-2">
    {/* ... select existente ... */}
  </div>
)}
```

**Regra:** Se só há 1 canal disponível, o seletor não faz sentido — não há o que selecionar.

---

## Trade-offs

| Opção | Escolhida | Motivo |
|---|---|---|
| Filtro no nível do grupo | Sim | Uma linha, sem novos tipos nem props |
| Campo `roles` no `NavGroup` | Não | Verboso sem benefício adicional |
| Prop `showChannelSelector` | Não | `channels.length` já contém a informação |
| Check `role === "vendedor"` no ChatList | Não | Data-driven é mais robusto |

---

## Validação

Após implementação: `npm run build` para confirmar ausência de erros de tipagem.
