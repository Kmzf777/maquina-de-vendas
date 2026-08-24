# Spec: Presença Online no Dashboard

**Data:** 2026-06-10  
**Branch:** feature/presence-online-users  
**Status:** Aprovado

---

## Contexto

O dashboard do CRM (`/dashboard`) precisa mostrar, em tempo real, quais usuários da equipe estão com o sistema aberto naquele momento e em qual página estão. Isso aumenta visibilidade entre o time de vendas e admins sem precisar de comunicação externa.

---

## Usuários conhecidos (fonte de verdade hardcoded)

```ts
[
  { email: "arthur@cafecanastra.com",  name: "Arthur", role: "vendedor" },
  { email: "rafael@cafecanastra.com",  name: "Rafael", role: "admin"    },
  { email: "kelwin@cafecanastra.com",  name: "Kelwin", role: "admin"    },
  { email: "joao@cafecanastra.com",    name: "João",   role: "vendedor" },
]
```

A lista é fixa. Qualquer usuário da lista não detectado como online aparece como "ausente".

---

## Tecnologia de Presença

**Supabase Realtime Presence** — channel `crm-presence`.

Cada tab autenticada entra no channel e publica:
```ts
{ name: string, email: string, role: string, page: string, status: "online" | "ausente" }
```

- `page` = pathname atual via `usePathname()`
- `status` muda para `"ausente"` quando a tab fica oculta (`document.visibilitychange`)
- Quando a tab fecha/desconecta, o usuário sai do channel → tratado como ausente via diff com KNOWN_USERS

---

## Arquitetura

### 1. Hook `use-presence-tracker` (tracker — montado no shell)

- Arquivo: `frontend/src/hooks/use-presence-tracker.ts`
- Montado em: `authenticated-shell.tsx`
- Responsabilidade: entra no channel, faz `track()` com o estado do usuário logado, atualiza page ao navegar, atualiza status ao esconder/mostrar tab
- Não retorna nada (side-effect puro)

### 2. Hook `use-presence` (reader — usado no dashboard)

- Arquivo: `frontend/src/hooks/use-presence.ts`
- Montado em: `OnlineUsersSection`
- Responsabilidade: escuta eventos `sync` e `join`/`leave` do channel, retorna lista de `UserPresenceState[]` combinando presence channel + KNOWN_USERS (ausentes preenchidos)
- Retorna: `UserPresenceState[]` sempre com os 4 usuários

### 3. Componente `OnlineUsersSection`

- Arquivo: `frontend/src/components/dashboard/online-users-section.tsx`
- Posição no dashboard: **antes** da `SlaHeroSection` (primeiro card após o header)
- Usa shadcn/ui: `Badge`, `Tooltip`, `TooltipProvider`

---

## UX/UI do Card

```
┌─────────────────────────────────────────────────────────┐
│ EQUIPE ONLINE                              2 de 4 online │
├─────────────────────────────────────────────────────────┤
│  ●  Rafael   admin     /conversas                       │
│  ●  Arthur   vendedor  /leads                           │
│  ○  Kelwin   admin     ausente                          │
│  ○  João     vendedor  ausente                          │
└─────────────────────────────────────────────────────────┘
```

**Indicadores de status:**
- `●` verde (`#22c55e`) = online (status "online" no channel)
- `●` âmbar (`#f59e0b`) = ausente mas conectado (status "ausente" no channel — tab oculta)
- `○` cinza (`#dedbd6`) = offline (fora do channel)

**Layout de cada linha:**
- Dot de status (8px)
- Avatar circular com iniciais (32px, bg baseado na inicial)
- Nome + badge de role (Admin em roxo discreto, Vendedor em azul discreto)
- Página atual (texto muted `#7b7b78`, label amigável — ex: "Dashboard", "Leads", "Conversas")

**Card:**
- Fundo branco, borda `#dedbd6`, radius 8px
- Header com label uppercase + contador de online
- Padding consistente com KpiCard existente

---

## Mapa de labels de páginas

```ts
const PAGE_LABELS: Record<string, string> = {
  "/dashboard":    "Dashboard",
  "/leads":        "Leads",
  "/conversas":    "Conversas",
  "/campanhas":    "Campanhas",
  "/qualificacao": "Qualificação",
  "/vendas":       "Vendas",
  "/canais":       "Canais",
  "/estatisticas": "Estatísticas",
  "/config":       "Configurações",
}
```

Páginas não mapeadas exibem o pathname bruto.

---

## Estado de Loading

Skeleton de 4 linhas (mesma altura do card populado) enquanto o channel ainda não sincronizou.

---

## Arquivos a criar/modificar

| Ação | Arquivo |
|---|---|
| Criar | `frontend/src/hooks/use-presence-tracker.ts` |
| Criar | `frontend/src/hooks/use-presence.ts` |
| Criar | `frontend/src/components/dashboard/online-users-section.tsx` |
| Modificar | `frontend/src/components/authenticated-shell.tsx` |
| Modificar | `frontend/src/app/(authenticated)/dashboard/page.tsx` |

---

## Fora de escopo

- Notificação quando alguém entra/sai
- Histórico de presença
- Presença em outras páginas além do dashboard
- Adição de novos usuários via UI (lista é hardcoded)
