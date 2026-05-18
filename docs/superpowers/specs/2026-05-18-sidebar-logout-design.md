# Spec: Botão de Logout na Sidebar

**Data:** 2026-05-18  
**Arquivo principal:** `frontend/src/components/sidebar.tsx`  
**Status:** Aprovado

---

## Problema

O CRM não possui botão de logout. O usuário não tem como encerrar a sessão após a reativação do sistema de login Supabase. O rodapé da sidebar já tem uma área de usuário com avatar e texto estático ("Cafe Canastra") que precisa ser dinamizada e receber o botão de saída.

---

## Design

### Estrutura visual do rodapé (footer da sidebar)

O rodapé existente (`border-t border-[#dedbd6]`) é redesenhado para:

```
┌─────────────────────────────────────────┐
│ [AB]  comercial@cafe...    [→ sair]     │
└─────────────────────────────────────────┘
```

- **Avatar:** círculo/quadrado `w-7 h-7 rounded-[6px] bg-[#dedbd6]` exibindo a **inicial do email** em maiúsculo (`text-[11px] font-medium text-[#7b7b78]`). Se o email ainda não carregou, mostra o ícone de usuário existente como fallback.
- **Email:** `text-[13px] text-[#7b7b78] truncate flex-1` — email completo truncado pelo `truncate`.
- **Botão de logout:** ícone de arrow-right-on-rectangle (sair) à direita. Estilo: `w-7 h-7 rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 hover:text-[#c41c1c] transition-colors`. Sem label de texto. `aria-label="Sair"`.

### Estados

| Estado | Comportamento |
|---|---|
| Carregando sessão | Avatar mostra ícone de usuário genérico, email não aparece, botão de sair não aparece |
| Sessão carregada | Avatar mostra inicial do email, email truncado, botão de sair visível |
| Clique em sair | Desabilita o botão (loading state), chama `signOut()`, redireciona para `/login` |

### Comportamento do logout

1. `supabase.auth.signOut()` — invalida a sessão no cliente
2. `router.push("/login")` — redireciona imediatamente
3. O middleware já protege todas as rotas; a sessão expirada bloqueia automaticamente

---

## Implementação técnica

### Hook `useUser()`

Novo hook no topo de `sidebar.tsx` que retorna `{ email, role, loading }`:

```ts
function useUser() {
  const [state, setState] = useState<{
    email: string;
    role: "admin" | "vendedor";
    loading: boolean;
  }>({ email: "", role: "vendedor", loading: true });

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      const r = session?.user?.app_metadata?.role as "admin" | "vendedor" | undefined;
      setState({
        email: session?.user?.email ?? "",
        role: r === "admin" || r === "vendedor" ? r : "vendedor",
        loading: false,
      });
    });
  }, []);

  return state;
}
```

O hook `useRole()` existente é **substituído** por `useUser()` — o componente `Sidebar` passa a chamar `useUser()` e desestrutura `{ role }` para o filtro de nav e `{ email, loading }` para o footer.

### Função `handleSignOut`

```ts
const [signingOut, setSigningOut] = useState(false);
const router = useRouter();

async function handleSignOut() {
  setSigningOut(true);
  const supabase = createClient();
  await supabase.auth.signOut();
  router.push("/login");
}
```

### Footer atualizado

```tsx
<div className="px-3 pb-4 border-t border-[#dedbd6] pt-3">
  <div className="flex items-center gap-2.5 px-3 py-2">
    <div className="w-7 h-7 rounded-[6px] bg-[#dedbd6] flex items-center justify-center flex-shrink-0">
      {email ? (
        <span className="text-[11px] font-medium text-[#7b7b78]">
          {email[0].toUpperCase()}
        </span>
      ) : (
        /* ícone de usuário existente */
      )}
    </div>
    {!loading && (
      <>
        <p className="text-[13px] text-[#7b7b78] truncate flex-1">{email}</p>
        <button
          onClick={handleSignOut}
          disabled={signingOut}
          aria-label="Sair"
          className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 hover:text-[#c41c1c] transition-colors disabled:opacity-40 flex-shrink-0"
        >
          {/* arrow-right-on-rectangle icon */}
        </button>
      </>
    )}
  </div>
</div>
```

---

## Tokens de design respeitados

| Token | Valor |
|---|---|
| Background sidebar | `#f0ede8` |
| Border | `#dedbd6` |
| Texto primário | `#111111` |
| Texto muted | `#7b7b78` |
| Hover background | `#dedbd6/60` |
| Cor de perigo (hover logout) | `#c41c1c` |
| Border radius botões | `rounded-[4px]` |
| Border radius avatar | `rounded-[6px]` |

---

## Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `frontend/src/components/sidebar.tsx` | Único arquivo modificado. Substituir `useRole()` por `useUser()`, adicionar `useRouter`, `useState` para `signingOut`, e atualizar o bloco footer. |

---

## Critérios de aceitação

- [ ] Email do usuário logado aparece truncado no footer
- [ ] Avatar mostra a inicial do email
- [ ] Botão de sair presente e visível
- [ ] Hover do botão de sair muda para vermelho (`#c41c1c`)
- [ ] Click em sair: desabilita botão, faz signOut, redireciona para `/login`
- [ ] Durante carregamento da sessão, footer não pisca com conteúdo errado
- [ ] TypeScript sem erros
