# Respostas Rápidas (`/` no chat) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir inserir mensagens prontas no compositor de `/conversas` digitando `/` (lista filtrável + variáveis de lead), gerenciadas por um modal em `/config`.

**Architecture:** Lógica pura testável em `src/lib` (gatilho, inserção, filtro, resolver de variáveis); CRUD via route handlers Next clonados de `tags`; tabela global `quick_replies` no Supabase. UI: dropdown custom no `chat-view.tsx` e modal de gestão em `/config`. Zero dependência nova.

**Tech Stack:** Next.js 16 (App Router, Server/Client Components), React 19, TypeScript, Tailwind v4, Supabase (service-role nas rotas), Vitest (`environment: node`).

> **REGRA DE FRONTEND (todo subagente que tocar frontend):** tentar invocar a skill `frontend-design` (no momento **não instalada** neste ambiente → se retornar "Unknown skill", aplicar os princípios na mão); **reusar componentes/estilos existentes** (paleta `#111111`/`#7b7b78`/`#dedbd6`/`#faf9f6`, radius 4–8px, botões pretos com `hover:scale-110`); **consultar padrões em `frontend/src/app` antes de criar** — não confiar em memória pra APIs/rotas do App Router.
>
> **Comandos de teste:** rodar a partir de `frontend/`. Suite: `cd frontend && npx vitest run`. Arquivo único: `cd frontend && npx vitest run src/lib/<arquivo>.test.ts` (PowerShell: troque `&&` por `;`).

---

## Estrutura de arquivos

| Ação | Arquivo | Responsabilidade |
|---|---|---|
| Criar | `backend/migrations/20260617_quick_replies.sql` | Tabela global `quick_replies` |
| Modificar | `frontend/src/lib/types.ts` | Interface `QuickReply` |
| Criar | `frontend/src/lib/lead-variables.ts` | `LEAD_RESOLVERS` + `resolveLeadVariables` |
| Criar | `frontend/src/lib/lead-variables.test.ts` | Testes do resolver |
| Modificar | `frontend/src/components/conversas/template-dispatch-modal.tsx` | Importar `LEAD_RESOLVERS` do novo módulo |
| Criar | `frontend/src/lib/quick-replies.ts` | `getSlashQuery`, `applyQuickReply`, `filterQuickReplies` (puro) |
| Criar | `frontend/src/lib/quick-replies.test.ts` | Testes da lógica do `/` |
| Criar | `frontend/src/app/api/quick-replies/route.ts` | GET (lista) + POST (cria) |
| Criar | `frontend/src/app/api/quick-replies/[id]/route.ts` | PUT + DELETE |
| Criar | `frontend/src/components/conversas/quick-reply-menu.tsx` | Dropdown do `/` (apresentacional) |
| Modificar | `frontend/src/components/conversas/chat-view.tsx` | Gatilho, teclado, inserção, render do menu |
| Criar | `frontend/src/components/config/quick-replies-modal.tsx` | Modal de gestão (CRUD) |
| Modificar | `frontend/src/app/(authenticated)/config/page.tsx` | Aba "Respostas Rápidas" + modal + deep-link |

---

### Task 1: Migration + tipo `QuickReply`

**Files:**
- Create: `backend/migrations/20260617_quick_replies.sql`
- Modify: `frontend/src/lib/types.ts` (após a interface `Tag`, linha ~117)

- [ ] **Step 1: Criar a migration**

```sql
-- backend/migrations/20260617_quick_replies.sql
--
-- Respostas rápidas (canned replies de texto livre) inseridas via "/" no compositor de /conversas.
-- Biblioteca GLOBAL (sem dono), acessada via route handlers com service-role — mesmo padrão de `tags`.
-- NÃO confundir com `message_templates` (templates HSM da Meta).

create table if not exists public.quick_replies (
  id          uuid primary key default gen_random_uuid(),
  shortcut    text,                       -- atalho do "/" (opcional). Ex.: "saudacao"
  title       text not null,              -- rótulo exibido na lista
  content     text not null,              -- corpo; pode conter {{primeiro_nome}} etc.
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists quick_replies_shortcut_idx on public.quick_replies (shortcut);
```

- [ ] **Step 2: Adicionar o tipo `QuickReply`** em `frontend/src/lib/types.ts`, logo após a interface `Tag`:

```ts
export interface QuickReply {
  id: string;
  shortcut: string | null;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem novos erros relacionados a `QuickReply`.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/20260617_quick_replies.sql frontend/src/lib/types.ts
git commit -m "feat(quick-replies): migration da tabela quick_replies + tipo QuickReply"
```

> ⚠️ **Aplicação manual:** a migration precisa ser rodada no Supabase (igual `20260615_conversations_last_customer_message_at.sql`). Sinalizar ao usuário ao final — não roda automaticamente.

---

### Task 2: `lead-variables.ts` (extração + TDD) e refactor do modal de template

**Files:**
- Create: `frontend/src/lib/lead-variables.ts`
- Test: `frontend/src/lib/lead-variables.test.ts`
- Modify: `frontend/src/components/conversas/template-dispatch-modal.tsx:21-30`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/lead-variables.test.ts
import { describe, it, expect } from "vitest";
import { resolveLeadVariables } from "@/lib/lead-variables";

describe("resolveLeadVariables", () => {
  it("troca {{primeiro_nome}} pelo primeiro nome", () => {
    expect(resolveLeadVariables("Olá {{primeiro_nome}}!", { name: "João Silva" }))
      .toBe("Olá João!");
  });

  it("resolve telefone e empresa", () => {
    expect(resolveLeadVariables("Tel {{telefone}} / {{empresa}}", { phone: "11999", company: "ACME" }))
      .toBe("Tel 11999 / ACME");
  });

  it("mantém o placeholder quando o valor é vazio", () => {
    expect(resolveLeadVariables("Olá {{primeiro_nome}}!", { name: "" }))
      .toBe("Olá {{primeiro_nome}}!");
  });

  it("mantém tokens desconhecidos intactos", () => {
    expect(resolveLeadVariables("{{desconhecido}}", {})).toBe("{{desconhecido}}");
  });

  it("texto sem variáveis passa igual", () => {
    expect(resolveLeadVariables("sem variaveis", {})).toBe("sem variaveis");
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/lib/lead-variables.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/lead-variables"`.

- [ ] **Step 3: Implementar `lead-variables.ts`**

```ts
// frontend/src/lib/lead-variables.ts
// Mirrors _LEAD_FIELD_TOKENS in backend/app/broadcast/worker.py
// (extraído de template-dispatch-modal.tsx para reuso nas respostas rápidas)

export type LeadLike = { name?: string | null; phone?: string | null; company?: string | null };

export const LEAD_RESOLVERS: Record<string, (l: LeadLike) => string> = {
  primeiro_nome: (l) => (l.name ?? "").split(" ")[0],
  nome_completo: (l) => l.name ?? "",
  telefone: (l) => l.phone ?? "",
  empresa: (l) => l.company ?? "",
  first_name: (l) => (l.name ?? "").split(" ")[0],
  lead_name: (l) => l.name ?? "",
  phone: (l) => l.phone ?? "",
};

// Resolve {{token}} em texto livre. Token desconhecido OU valor vazio → mantém {{token}}.
export function resolveLeadVariables(text: string, lead: LeadLike): string {
  return text.replace(/\{\{(\w+)\}\}/g, (full, token) => {
    const resolver = LEAD_RESOLVERS[token as string];
    if (!resolver) return full;
    return resolver(lead) || full;
  });
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/lib/lead-variables.test.ts`
Expected: PASS (5 testes).

- [ ] **Step 5: Refatorar `template-dispatch-modal.tsx`** — remover o `const LEAD_RESOLVERS` local (linhas 21-30) e importar do novo módulo.

Remover este bloco (linhas 21-30):
```ts
// Mirrors _LEAD_FIELD_TOKENS in backend/app/broadcast/worker.py
const LEAD_RESOLVERS: Record<string, (l: { name?: string | null; phone?: string; company?: string | null }) => string> = {
  primeiro_nome: (l) => (l.name ?? "").split(" ")[0],
  nome_completo: (l) => l.name ?? "",
  telefone: (l) => l.phone ?? "",
  empresa: (l) => l.company ?? "",
  first_name: (l) => (l.name ?? "").split(" ")[0],
  lead_name: (l) => l.name ?? "",
  phone: (l) => l.phone ?? "",
};
```

E adicionar o import junto aos demais no topo (após a linha 4, `import type { Conversation } from "@/lib/types";`):
```ts
import { LEAD_RESOLVERS } from "@/lib/lead-variables";
```

- [ ] **Step 6: Type-check + suite completa (garantir que o refactor não quebrou nada)**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: sem erros; testes passam.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/lead-variables.ts frontend/src/lib/lead-variables.test.ts frontend/src/components/conversas/template-dispatch-modal.tsx
git commit -m "refactor(variables): extrai LEAD_RESOLVERS para lib/lead-variables + resolveLeadVariables (testado)"
```

---

### Task 3: `quick-replies.ts` — gatilho/inserção/filtro (TDD)

**Files:**
- Create: `frontend/src/lib/quick-replies.ts`
- Test: `frontend/src/lib/quick-replies.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/quick-replies.test.ts
import { describe, it, expect } from "vitest";
import { getSlashQuery, applyQuickReply, filterQuickReplies } from "@/lib/quick-replies";
import type { QuickReply } from "@/lib/types";

const make = (p: Partial<QuickReply>): QuickReply => ({
  id: "1", shortcut: null, title: "", content: "",
  created_at: "", updated_at: "", ...p,
});

describe("getSlashQuery", () => {
  it("abre no '/' isolado", () => {
    expect(getSlashQuery("/", 1)).toEqual({ query: "", start: 0 });
  });
  it("captura o texto após a '/'", () => {
    expect(getSlashQuery("/saud", 5)).toEqual({ query: "saud", start: 0 });
  });
  it("abre após espaço", () => {
    expect(getSlashQuery("oi /sa", 6)).toEqual({ query: "sa", start: 3 });
  });
  it("não abre no meio de palavra (e/ou)", () => {
    expect(getSlashQuery("e/ou", 4)).toBeNull();
  });
  it("não abre em URL (http://)", () => {
    expect(getSlashQuery("http://x", 8)).toBeNull();
  });
  it("fecha ao digitar espaço depois do token", () => {
    expect(getSlashQuery("/sa ", 4)).toBeNull();
  });
});

describe("applyQuickReply", () => {
  it("substitui '/token' isolado pelo conteúdo", () => {
    expect(applyQuickReply("/saud", 5, 0, "Olá!")).toEqual({ text: "Olá!", caret: 4 });
  });
  it("preserva texto antes e depois do trecho", () => {
    expect(applyQuickReply("oi /sa fim", 6, 3, "X")).toEqual({ text: "oi X fim", caret: 4 });
  });
});

describe("filterQuickReplies", () => {
  const items = [
    make({ id: "a", shortcut: "saud", title: "Saudação", content: "Olá tudo bem" }),
    make({ id: "b", shortcut: "cond", title: "Condições", content: "Pagamento" }),
  ];
  it("query vazia retorna tudo", () => {
    expect(filterQuickReplies(items, "")).toHaveLength(2);
  });
  it("filtra por shortcut/título/conteúdo (case-insensitive)", () => {
    expect(filterQuickReplies(items, "SAUD").map((i) => i.id)).toEqual(["a"]);
    expect(filterQuickReplies(items, "pagamento").map((i) => i.id)).toEqual(["b"]);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/lib/quick-replies.test.ts`
Expected: FAIL — import não resolve.

- [ ] **Step 3: Implementar `quick-replies.ts`**

```ts
// frontend/src/lib/quick-replies.ts
import type { QuickReply } from "@/lib/types";

export interface SlashQuery {
  query: string; // texto após a "/" (filtro)
  start: number; // índice da "/" no texto completo
}

// Detecta um gatilho "/" ativo no texto até o caret. null se não houver.
export function getSlashQuery(text: string, caret: number): SlashQuery | null {
  const before = text.slice(0, caret);
  const match = before.match(/(?:^|\s)\/(\S*)$/);
  if (!match) return null;
  const query = match[1];
  return { query, start: caret - query.length - 1 };
}

// Substitui o trecho [start, caret) pelo conteúdo; retorna novo texto + posição do caret.
export function applyQuickReply(
  text: string,
  caret: number,
  start: number,
  content: string
): { text: string; caret: number } {
  const head = text.slice(0, start);
  const tail = text.slice(caret);
  return { text: head + content + tail, caret: head.length + content.length };
}

// Filtra por shortcut + título + conteúdo (case-insensitive). Query vazia → tudo.
export function filterQuickReplies(items: QuickReply[], query: string): QuickReply[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter(
    (it) =>
      (it.shortcut ?? "").toLowerCase().includes(q) ||
      it.title.toLowerCase().includes(q) ||
      it.content.toLowerCase().includes(q)
  );
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/lib/quick-replies.test.ts`
Expected: PASS (todos os describes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/quick-replies.ts frontend/src/lib/quick-replies.test.ts
git commit -m "feat(quick-replies): lógica pura do gatilho /, inserção e filtro (testada)"
```

---

### Task 4: Route handlers CRUD

**Files:**
- Create: `frontend/src/app/api/quick-replies/route.ts`
- Create: `frontend/src/app/api/quick-replies/[id]/route.ts`

> Clonado de `frontend/src/app/api/tags/`. Sem teste unitário — segue a convenção do repo (rotas de `tags` não têm teste; mockar o service client seria custo sem retorno). Verificação é manual (Task 8).

- [ ] **Step 1: Criar `route.ts` (GET + POST)**

```ts
// frontend/src/app/api/quick-replies/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_replies")
    .select("*")
    .order("title", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { shortcut, title, content } = await request.json();

  if (!title?.trim() || !content?.trim()) {
    return NextResponse.json({ error: "title e content são obrigatórios" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("quick_replies")
    .insert({ shortcut: shortcut?.trim() || null, title: title.trim(), content })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Criar `[id]/route.ts` (PUT + DELETE)**

```ts
// frontend/src/app/api/quick-replies/[id]/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { shortcut, title, content } = await request.json();

  const { data, error } = await supabase
    .from("quick_replies")
    .update({
      shortcut: shortcut?.trim() || null,
      title: title?.trim(),
      content,
      updated_at: new Date().toISOString(),
    })
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { error } = await supabase.from("quick_replies").delete().eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/quick-replies/
git commit -m "feat(quick-replies): rotas CRUD /api/quick-replies"
```

---

### Task 5: Componente `QuickReplyMenu` (dropdown do `/`)

**Files:**
- Create: `frontend/src/components/conversas/quick-reply-menu.tsx`

> Apresentacional puro (recebe itens já filtrados + índice destacado). **Usa `onMouseDown` + `preventDefault`** nos itens para não tirar o foco do textarea (senão o `onBlur` fecha o menu antes do clique). Aplicar princípios `frontend-design`/shadcn + paleta existente.

- [ ] **Step 1: Criar o componente**

```tsx
// frontend/src/components/conversas/quick-reply-menu.tsx
"use client";

import type { QuickReply } from "@/lib/types";

interface Props {
  items: QuickReply[];
  highlightedIndex: number;
  onSelect: (item: QuickReply) => void;
  onCreate: () => void;
  onHighlight: (index: number) => void;
}

export function QuickReplyMenu({ items, highlightedIndex, onSelect, onCreate, onHighlight }: Props) {
  return (
    <div className="absolute bottom-full left-3 right-3 mb-2 z-20 max-h-56 overflow-y-auto bg-white border border-[#dedbd6] rounded-[6px] shadow-lg">
      {items.length === 0 ? (
        <div className="px-3 py-3 text-[13px] text-[#7b7b78]">Nenhuma resposta rápida encontrada.</div>
      ) : (
        <ul className="py-1">
          {items.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); onSelect(item); }}
                onMouseEnter={() => onHighlight(i)}
                className={
                  "w-full text-left px-3 py-2 transition-colors " +
                  (i === highlightedIndex ? "bg-[#f5f3f0]" : "bg-transparent hover:bg-[#faf9f6]")
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] text-[#111111] font-normal truncate">{item.title}</span>
                  {item.shortcut && (
                    <span className="text-[12px] text-[#7b7b78] flex-shrink-0">/{item.shortcut}</span>
                  )}
                </div>
                <p className="text-[12px] text-[#7b7b78] truncate">{item.content}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onMouseDown={(e) => { e.preventDefault(); onCreate(); }}
        className="w-full text-left px-3 py-2 border-t border-[#dedbd6] text-[14px] text-[#111111] hover:bg-[#faf9f6] transition-colors"
      >
        + Criar mensagem
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros (componente ainda não usado — ok).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/quick-reply-menu.tsx
git commit -m "feat(quick-replies): componente QuickReplyMenu (dropdown do /)"
```

---

### Task 6: Integrar o `/` no `chat-view.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx` (imports; estado ~40; effect de reset 71-87; `handleKeyDown` 201-206; bloco do input 634/665-673)

- [ ] **Step 1: Adicionar imports** no topo do arquivo.

Trocar a linha 4:
```ts
import type { Message, Conversation, Tag } from "@/lib/types";
```
por:
```ts
import type { Message, Conversation, Tag, QuickReply } from "@/lib/types";
```

E adicionar, junto aos demais imports (após a linha 11):
```ts
import { useRouter } from "next/navigation";
import { QuickReplyMenu } from "@/components/conversas/quick-reply-menu";
import { getSlashQuery, applyQuickReply, filterQuickReplies } from "@/lib/quick-replies";
import { resolveLeadVariables } from "@/lib/lead-variables";
```

- [ ] **Step 2: Adicionar estado** logo após `const [text, setText] = useState("");` (linha 40):

```ts
const router = useRouter();
const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
const [qrOpen, setQrOpen] = useState(false);
const [qrQuery, setQrQuery] = useState("");
const [qrIndex, setQrIndex] = useState(0);
```

- [ ] **Step 3: Buscar a lista 1x** — adicionar um effect (perto dos demais `useEffect`, após o bloco 89-95):

```ts
useEffect(() => {
  fetch("/api/quick-replies")
    .then((res) => (res.ok ? res.json() : []))
    .then((data) => setQuickReplies(Array.isArray(data) ? data : []))
    .catch(() => {});
}, []);

const qrFiltered = useMemo(() => filterQuickReplies(quickReplies, qrQuery), [quickReplies, qrQuery]);
```

- [ ] **Step 4: Resetar o menu ao trocar de conversa** — dentro do effect de reset (linhas 71-87), adicionar antes do fechamento:

```ts
setQrOpen(false);
setQrQuery("");
setQrIndex(0);
```

- [ ] **Step 5: Handlers de mudança de texto, inserção e criação** — adicionar logo antes de `handleKeyDown` (linha 201):

```ts
function handleTextChange(e: ChangeEvent<HTMLTextAreaElement>) {
  const value = e.target.value;
  setText(value);
  const caret = e.target.selectionStart ?? value.length;
  const slash = getSlashQuery(value, caret);
  if (slash) {
    setQrOpen(true);
    setQrQuery(slash.query);
    setQrIndex(0);
  } else {
    setQrOpen(false);
  }
}

function insertQuickReply(item: QuickReply) {
  const el = textareaRef.current;
  const caret = el?.selectionStart ?? text.length;
  const slash = getSlashQuery(text, caret);
  const start = slash ? slash.start : caret;
  const resolved = resolveLeadVariables(item.content, lead ?? {});
  const result = applyQuickReply(text, caret, start, resolved);
  setText(result.text);
  setQrOpen(false);
  setQrQuery("");
  requestAnimationFrame(() => {
    const node = textareaRef.current;
    if (node) {
      node.focus();
      node.setSelectionRange(result.caret, result.caret);
    }
  });
}

function handleCreateQuickReply() {
  setQrOpen(false);
  router.push("/config?tab=respostas-rapidas&new=1");
}
```

- [ ] **Step 6: Estender `handleKeyDown`** (linhas 201-206) para tratar o menu primeiro:

```ts
function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
  if (qrOpen) {
    if (e.key === "Escape") { e.preventDefault(); setQrOpen(false); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setQrIndex((i) => Math.min(i + 1, Math.max(qrFiltered.length - 1, 0))); return; }
    if (e.key === "ArrowUp")   { e.preventDefault(); setQrIndex((i) => Math.max(i - 1, 0)); return; }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      if (qrFiltered.length > 0) {
        insertQuickReply(qrFiltered[qrIndex] ?? qrFiltered[0]);
      } else {
        setQrOpen(false); // menu aberto sem resultados: fecha, NÃO envia
      }
      return;
    }
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}
```

- [ ] **Step 7: Ligar o textarea e renderizar o menu.** No bloco do input (linha 634), trocar `<div className="p-3 flex gap-2">` por `<div className="relative p-3 flex gap-2">` e inserir o menu como primeiro filho:

```tsx
<div className="relative p-3 flex gap-2">
  {qrOpen && (
    <QuickReplyMenu
      items={qrFiltered}
      highlightedIndex={qrIndex}
      onSelect={insertQuickReply}
      onCreate={handleCreateQuickReply}
      onHighlight={setQrIndex}
    />
  )}
  {/* ...input de arquivo e botões existentes... */}
```

E no `<textarea>` (linhas 665-673), trocar `onChange={(e) => setText(e.target.value)}` por `onChange={handleTextChange}` e adicionar `onBlur={() => setQrOpen(false)}`:

```tsx
<textarea
  ref={textareaRef}
  value={text}
  onChange={handleTextChange}
  onKeyDown={handleKeyDown}
  onBlur={() => setQrOpen(false)}
  placeholder="Digitar mensagem..."
  rows={1}
  className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
/>
```

- [ ] **Step 8: Type-check + verificação manual**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros.

Manual (rodar o dev e abrir uma conversa em `/conversas`):
- Digitar `/` → menu abre acima do input com a lista (ou "Nenhuma..." se vazio) + "+ Criar mensagem".
- Digitar `/saud` → filtra.
- ↑/↓ navega, **Enter insere (não envia)**, Esc fecha.
- Após inserir, variáveis `{{primeiro_nome}}` aparecem resolvidas; caret ao fim.
- Enter com menu fechado → **envia** normalmente (comportamento atual intacto).
- "+ Criar mensagem" → vai pra `/config` (Task 7).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(quick-replies): gatilho / no compositor de conversas (lista, teclado, inserção, variáveis)"
```

---

### Task 7: Modal de gestão + aba em `/config` + deep-link

**Files:**
- Create: `frontend/src/components/config/quick-replies-modal.tsx`
- Modify: `frontend/src/app/(authenticated)/config/page.tsx`

- [ ] **Step 1: Criar o modal de gestão** (CRUD; overlay fixo; botões de inserir variável). Aplicar princípios `frontend-design`/shadcn + paleta existente.

```tsx
// frontend/src/components/config/quick-replies-modal.tsx
"use client";

import { useState, useEffect } from "react";
import type { QuickReply } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  initialCreate?: boolean;
}

const VARIABLES = ["primeiro_nome", "nome_completo", "telefone", "empresa"];

export function QuickRepliesModal({ open, onClose, initialCreate = false }: Props) {
  const [items, setItems] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [shortcut, setShortcut] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  useEffect(() => {
    if (!open) return;
    fetchItems();
    if (initialCreate) startCreate();
  }, [open, initialCreate]);

  async function fetchItems() {
    setLoading(true);
    const res = await fetch("/api/quick-replies");
    if (res.ok) setItems(await res.json());
    setLoading(false);
  }

  function resetForm() {
    setShortcut(""); setTitle(""); setContent(""); setEditingId(null); setShowForm(false);
  }
  function startCreate() { setShortcut(""); setTitle(""); setContent(""); setEditingId(null); setShowForm(true); }
  function startEdit(it: QuickReply) {
    setEditingId(it.id); setShortcut(it.shortcut ?? ""); setTitle(it.title); setContent(it.content); setShowForm(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    const payload = { shortcut: shortcut.trim() || null, title: title.trim(), content };
    const res = editingId
      ? await fetch(`/api/quick-replies/${editingId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      : await fetch("/api/quick-replies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (res.ok) { resetForm(); fetchItems(); }
  }

  async function handleDelete(id: string) {
    if (!confirm("Excluir esta resposta rápida?")) return;
    const res = await fetch(`/api/quick-replies/${id}`, { method: "DELETE" });
    if (res.ok) fetchItems();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-[8px] border border-[#dedbd6] w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[18px] font-normal text-[#111111]">Respostas Rápidas</h2>
          <button onClick={onClose} className="text-[#7b7b78] hover:text-[#111111] transition-colors" aria-label="Fechar">✕</button>
        </div>

        {!showForm && (
          <button
            onClick={startCreate}
            className="mb-5 bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Nova resposta
          </button>
        )}

        {showForm && (
          <form onSubmit={handleSubmit} className="mb-6 p-4 bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] space-y-3">
            <div className="flex gap-3">
              <input
                value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Título" autoFocus
                className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none"
              />
              <input
                value={shortcut} onChange={(e) => setShortcut(e.target.value)} placeholder="atalho (opcional)"
                className="w-40 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <textarea
              value={content} onChange={(e) => setContent(e.target.value)} placeholder="Mensagem... use {{primeiro_nome}} para personalizar"
              rows={4}
              className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none resize-none"
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-[#7b7b78]">Inserir variável:</span>
              {VARIABLES.map((v) => (
                <button
                  key={v} type="button" onClick={() => setContent((c) => c + `{{${v}}}`)}
                  className="text-[12px] px-2 py-1 rounded-[4px] border border-[#dedbd6] text-[#111111] hover:bg-[#faf9f6] transition-colors"
                >
                  {`{{${v}}}`}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <button type="submit" className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                {editingId ? "Salvar" : "Criar"}
              </button>
              <button type="button" onClick={resetForm} className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                Cancelar
              </button>
            </div>
          </form>
        )}

        {loading ? (
          <p className="text-[#7b7b78] text-[14px] py-4">Carregando...</p>
        ) : items.length === 0 ? (
          <p className="text-[#7b7b78] text-[14px] py-4">Nenhuma resposta rápida criada ainda.</p>
        ) : (
          <div className="space-y-2">
            {items.map((it) => (
              <div key={it.id} className="flex items-start gap-3 p-3 bg-white border border-[#dedbd6] rounded-[8px]">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] text-[#111111] font-normal truncate">{it.title}</span>
                    {it.shortcut && <span className="text-[12px] text-[#7b7b78]">/{it.shortcut}</span>}
                  </div>
                  <p className="text-[13px] text-[#7b7b78] truncate">{it.content}</p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button onClick={() => startEdit(it)} className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#faf9f6] transition-colors" title="Editar">✎</button>
                  <button onClick={() => handleDelete(it.id)} className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors" title="Excluir">🗑</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Integrar em `config/page.tsx`** — aba + modal + deep-link via `window.location.search` (evita o requisito de Suspense do `useSearchParams`).

Adicionar imports (após a linha 8):
```ts
import { QuickRepliesModal } from "@/components/config/quick-replies-modal";
```

Adicionar `"respostas-rapidas"` ao `BASE_TABS` (linha 10-14):
```ts
const BASE_TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
  { key: "lp-webhook", label: "Landing Pages" },
  { key: "respostas-rapidas", label: "Respostas Rápidas" },
] as const;
```

Atualizar o tipo `TabKey` (linha 16):
```ts
type TabKey = "tags" | "pricing" | "lp-webhook" | "sla" | "respostas-rapidas";
```

Adicionar estado e deep-link dentro de `ConfigPage`, junto aos `useState`/`useEffect` (após a linha 20):
```ts
const [qrModalOpen, setQrModalOpen] = useState(false);
const [qrInitialCreate, setQrInitialCreate] = useState(false);

useEffect(() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get("tab") === "respostas-rapidas") {
    setActiveTab("respostas-rapidas");
    if (params.get("new") === "1") {
      setQrInitialCreate(true);
      setQrModalOpen(true);
    }
  }
}, []);
```

Adicionar o conteúdo da aba + o modal, junto aos demais `{activeTab === ...}` (após a linha 60):
```tsx
{activeTab === "respostas-rapidas" && (
  <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
    <div className="flex items-center justify-between mb-2">
      <h2 className="text-[14px] font-normal text-[#111111]">Respostas Rápidas</h2>
      <button
        onClick={() => { setQrInitialCreate(false); setQrModalOpen(true); }}
        className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
      >
        Gerenciar
      </button>
    </div>
    <p className="text-[#7b7b78] text-[14px]">Mensagens prontas inseridas com &quot;/&quot; no chat. Use variáveis como {"{{primeiro_nome}}"} para personalizar.</p>
  </div>
)}

<QuickRepliesModal
  open={qrModalOpen}
  onClose={() => { setQrModalOpen(false); setQrInitialCreate(false); }}
  initialCreate={qrInitialCreate}
/>
```

> Nota: o `<QuickRepliesModal>` deve ficar **dentro** do JSX retornado mas pode ser irmão do bloco de abas (ele se auto-oculta quando `open` é false). Coloque-o logo antes do fechamento do container `max-w-3xl` ou após ele — desde que dentro do return.

- [ ] **Step 3: Type-check + verificação manual**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros.

Manual:
- `/config` → aba "Respostas Rápidas" → "Gerenciar" abre o modal com a lista.
- Criar (com variável), editar, excluir → persistem (refetch).
- No `/conversas`, "+ Criar mensagem" no menu do `/` → navega pra `/config`, abre o modal **em modo criação**.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/config/quick-replies-modal.tsx "frontend/src/app/(authenticated)/config/page.tsx"
git commit -m "feat(quick-replies): modal de gestão em /config + deep-link de criação"
```

---

### Task 8: Verificação final

**Files:** nenhum (verificação).

- [ ] **Step 1: Suite + type-check + lint + build**

Run:
```bash
cd frontend && npx vitest run && npx tsc --noEmit && npm run lint && npm run build
```
Expected: testes verdes; sem erros de tipo/lint; build conclui.

- [ ] **Step 2: Aplicar a migration no Supabase** — rodar `backend/migrations/20260617_quick_replies.sql` no SQL editor do Supabase (a tabela precisa existir para as rotas funcionarem). **Sinalizar ao usuário.**

- [ ] **Step 3: Smoke test manual** (dev rodando, conversa aberta):
  - [ ] `/` abre o menu; filtro funciona; ↑/↓/Enter/Esc corretos; Enter **não** envia com menu aberto.
  - [ ] Inserção resolve `{{primeiro_nome}}` e posiciona o caret ao fim.
  - [ ] Enter com menu fechado **envia** (regressão do comportamento atual).
  - [ ] Janela 24h fechada / preview de mídia / gravação → menu **não** aparece (só monta no branch de input normal).
  - [ ] Modo reply ativo + inserir resposta rápida → coexistem; menu acima da barra de reply.
  - [ ] Mobile: menu abre pra cima com scroll, sem cobrir o input.
  - [ ] `/config` CRUD completo; deep-link "+ Criar mensagem" abre o modal em criação.

- [ ] **Step 4: Commit final (se houver ajustes do smoke test)**

```bash
git add -A
git commit -m "chore(quick-replies): ajustes finais pós-verificação"
```

---

## Self-review (cobertura do spec)

- **Gatilho `/` (lista filtrável, shortcut opcional)** → Task 3 (`getSlashQuery`/`filterQuickReplies`) + Task 6.
- **Escopo global** → Task 1 (tabela sem dono) + Task 4 (rotas sem filtro de usuário).
- **Variáveis `{{...}}` reusando resolvers** → Task 2 (extração + `resolveLeadVariables`) + Task 6 (inserção resolve).
- **Gestão = modal em `/config`** → Task 7. **Botão redireciona pra criação** → Task 6 (`handleCreateQuickReply`) + Task 7 (deep-link `new=1`).
- **Permissões: todos editam** → rotas service-role sem gate (Task 4).
- **Teclado não quebra o Enter→enviar** → Task 3 (teste) + Task 6 (handler ordena menu antes do envio).
- **Não tocar no keepalive** → nenhum listener global novo; `onBlur`/handlers locais ao componente (Task 5/6).
- **Fora de escopo (privacidade por vendedor, categorias, mídia, caret-pixel)** → não implementados. ✅
