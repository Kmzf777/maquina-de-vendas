# Plano: Botão de Logout na Sidebar

**Spec:** `docs/superpowers/specs/2026-05-18-sidebar-logout-design.md`  
**Arquivo alvo:** `frontend/src/components/sidebar.tsx`  
**Status:** Aprovado — executar via subagente com skill frontend-design

---

## Passos

### 1. Adicionar import de `useRouter`

Em `sidebar.tsx`, adicionar `useRouter` da `next/navigation` aos imports existentes.

```diff
- import { usePathname } from "next/navigation";
+ import { usePathname, useRouter } from "next/navigation";
```

---

### 2. Substituir `useRole()` por `useUser()`

Remover o hook `useRole()` inteiro e substituir por `useUser()` que retorna `{ email, role, loading }`:

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

---

### 3. Atualizar `Sidebar` para usar `useUser()`

No corpo do componente `Sidebar`, substituir:

```diff
- const role = useRole();
+ const { email, role, loading } = useUser();
+ const [signingOut, setSigningOut] = useState(false);
+ const router = useRouter();
+
+ async function handleSignOut() {
+   setSigningOut(true);
+   const supabase = createClient();
+   await supabase.auth.signOut();
+   router.push("/login");
+ }
```

O filtro de nav items permanece igual: `.filter((item) => !item.roles || item.roles.includes(role))`.

---

### 4. Atualizar o bloco footer

Substituir o bloco `<div className="px-3 pb-4 border-t ...">` existente por:

```tsx
<div className="px-3 pb-4 border-t border-[#dedbd6] pt-3">
  <div className="flex items-center gap-2.5 px-3 py-2">
    {/* Avatar com inicial ou ícone de fallback */}
    <div className="w-7 h-7 rounded-[6px] bg-[#dedbd6] flex items-center justify-center flex-shrink-0">
      {email ? (
        <span className="text-[11px] font-medium text-[#7b7b78]">
          {email[0].toUpperCase()}
        </span>
      ) : (
        <svg className="w-3.5 h-3.5 text-[#7b7b78]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
        </svg>
      )}
    </div>

    {/* Email truncado + botão de sair */}
    {!loading && (
      <>
        <p className="text-[13px] text-[#7b7b78] truncate flex-1">{email}</p>
        <button
          onClick={handleSignOut}
          disabled={signingOut}
          aria-label="Sair"
          className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 hover:text-[#c41c1c] transition-colors disabled:opacity-40 flex-shrink-0"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
          </svg>
        </button>
      </>
    )}
  </div>
</div>
```

---

### 5. Verificação TypeScript

```bash
cd frontend && npx tsc --noEmit
```

Deve retornar sem erros.

---

### 6. Commit e push

```bash
git add frontend/src/components/sidebar.tsx
git commit -m "feat(sidebar): adicionar botao de logout com email do usuario"
git push origin master
```

---

## Checklist de aceitação

- [ ] Email do usuário logado aparece truncado no rodapé
- [ ] Avatar mostra a inicial do email (maiúsculo)
- [ ] Enquanto carrega (`loading: true`), footer mostra apenas o ícone genérico sem email/botão
- [ ] Botão de sair (ícone arrow-left) visível à direita
- [ ] Hover do ícone de sair fica vermelho (`#c41c1c`)
- [ ] Click: desabilita botão, faz `signOut()`, navega para `/login`
- [ ] TypeScript sem erros
- [ ] Comportamento idêntico em mobile (drawer) e desktop (sidebar fixa)
