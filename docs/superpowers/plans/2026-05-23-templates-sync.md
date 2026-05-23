# Templates Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os três bugs da aba Templates em `/campanhas`: filtro implícito de idioma, status desatualizado e categoria desatualizada — através de um mecanismo de sincronização com a Meta API.

**Architecture:** Nova rota Next.js `POST /api/templates/sync?channel_id={uuid}` busca todos os templates de um canal na Meta (com paginação), insere os novos e atualiza status/categoria dos existentes no Supabase, sem sobrescrever `requested_category`. O componente `TemplatesTab` auto-sincroniza no mount e expõe botão manual com spinner e toast.

**Tech Stack:** Next.js 14 App Router, Supabase JS v2, Meta Graph API, shadcn/ui Badge, TypeScript

---

## File Map

| Ação | Arquivo |
|---|---|
| CREATE | `supabase/migrations/20260523_templates_sync_unique_constraint.sql` |
| CREATE | `frontend/src/app/api/templates/sync/route.ts` |
| MODIFY | `frontend/src/components/campaigns/templates-tab.tsx` |

---

## Task 1: Criar branch de trabalho

**Files:**
- (sem alteração de código)

- [ ] **Step 1: Criar e entrar na branch**

```bash
git checkout -b feat/templates-sync
```

Expected: `Switched to a new branch 'feat/templates-sync'`

- [ ] **Step 2: Confirmar branch ativa**

```bash
git branch --show-current
```

Expected: `feat/templates-sync`

---

## Task 2: Migration — constraint única em `(channel_id, name, language)`

**Files:**
- Create: `supabase/migrations/20260523_templates_sync_unique_constraint.sql`

**Contexto:** A tabela `message_templates` precisa de uma constraint única em `(channel_id, name, language)` — não apenas em `(channel_id, name)` — porque a Meta permite o mesmo nome de template em vários idiomas. O upsert da rota de sync depende desta constraint.

- [ ] **Step 1: Verificar constraints atuais na tabela**

Use a ferramenta MCP Supabase `execute_sql` com a query:

```sql
SELECT c.conname, array_agg(a.attname ORDER BY a.attname) AS columns
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
WHERE t.relname = 'message_templates'
AND c.contype = 'u'
GROUP BY c.conname;
```

Anote os nomes das constraints retornadas (se houver). Se existir alguma em `{channel_id, name}`, o Step 3 do SQL a removerá.

- [ ] **Step 2: Criar arquivo de migration**

Crie `supabase/migrations/20260523_templates_sync_unique_constraint.sql` com o conteúdo:

```sql
-- Migration: templates_sync_unique_constraint
-- Replace any (channel_id, name) unique constraint with (channel_id, name, language)
-- to correctly support the same template name in multiple languages.

-- Step A: Drop any existing unique constraint on exactly (channel_id, name)
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'message_templates'
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname ORDER BY a.attname)
        FROM pg_attribute a
        WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
      ) = ARRAY['channel_id', 'name']::text[]
  LOOP
    EXECUTE 'ALTER TABLE message_templates DROP CONSTRAINT ' || quote_ident(r.conname);
    RAISE NOTICE 'Dropped constraint: %', r.conname;
  END LOOP;
END $$;

-- Step B: Add correct unique constraint on (channel_id, name, language) — idempotent
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'message_templates'
      AND c.conname = 'message_templates_channel_name_lang_key'
  ) THEN
    ALTER TABLE message_templates
      ADD CONSTRAINT message_templates_channel_name_lang_key
      UNIQUE (channel_id, name, language);
    RAISE NOTICE 'Created constraint: message_templates_channel_name_lang_key';
  ELSE
    RAISE NOTICE 'Constraint already exists, skipping.';
  END IF;
END $$;
```

- [ ] **Step 3: Aplicar a migration via MCP Supabase**

Use a ferramenta `apply_migration` do MCP Supabase com:
- `name`: `templates_sync_unique_constraint`
- `query`: conteúdo do arquivo SQL acima

- [ ] **Step 4: Verificar constraint criada**

Use `execute_sql`:

```sql
SELECT c.conname, array_agg(a.attname ORDER BY a.attname) AS columns
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
WHERE t.relname = 'message_templates' AND c.contype = 'u'
GROUP BY c.conname;
```

Expected: deve existir uma linha com `conname = 'message_templates_channel_name_lang_key'` e `columns = {channel_id, language, name}`.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260523_templates_sync_unique_constraint.sql
git commit -m "feat(db): add unique constraint (channel_id, name, language) on message_templates"
```

---

## Task 3: Criar rota `POST /api/templates/sync`

**Files:**
- Create: `frontend/src/app/api/templates/sync/route.ts`

**Comportamento:**
- Recebe `channel_id` como query param
- Busca TODOS os templates do canal via Meta API (paginação automática)
- Insere templates novos (nunca vistos no BD local) com `requested_category = category`
- Atualiza templates existentes: apenas `status`, `category`, `language`, `components`, `meta_template_id` (preserva `requested_category`)
- Ghost cleanup: marca como `cancelled` templates locais cujo `meta_template_id` não apareceu na resposta da Meta

- [ ] **Step 1: Criar arquivo e estrutura base**

Crie `frontend/src/app/api/templates/sync/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

// ─── Meta API types ────────────────────────────────────────────────────────────

interface MetaTemplateItem {
  id: string;
  name: string;
  status: string;
  language: string;
  category: string;
  components: unknown[];
}

interface MetaPageResponse {
  data: MetaTemplateItem[];
  paging?: { next?: string };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function fetchAllMetaTemplates(
  wabaId: string,
  accessToken: string,
  version: string
): Promise<MetaTemplateItem[]> {
  const all: MetaTemplateItem[] = [];
  let url: string | null =
    `https://graph.facebook.com/${version}/${wabaId}/message_templates` +
    `?fields=name,status,language,category,components&limit=200`;

  while (url) {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Meta API ${res.status}: ${err}`);
    }
    const json: MetaPageResponse = await res.json();
    all.push(...(json.data ?? []));
    url = json.paging?.next ?? null;
  }

  return all;
}

// ─── Route handler ────────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");

  if (!channelId) {
    return NextResponse.json({ error: "channel_id is required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // 1. Load and validate channel
  const { data: channel, error: channelError } = await supabase
    .from("channels")
    .select("id, provider, is_active, provider_config")
    .eq("id", channelId)
    .single();

  if (channelError || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 400 });
  }

  if (channel.provider !== "meta_cloud" || !channel.is_active) {
    return NextResponse.json(
      { error: "Channel is not an active meta_cloud channel" },
      { status: 400 }
    );
  }

  const config = channel.provider_config as Record<string, string>;
  const { access_token, waba_id, api_version } = config;

  if (!access_token || !waba_id) {
    return NextResponse.json(
      { error: "Channel missing access_token or waba_id" },
      { status: 400 }
    );
  }

  // 2. Paginated fetch from Meta (abort early on any page failure)
  let metaTemplates: MetaTemplateItem[];
  try {
    metaTemplates = await fetchAllMetaTemplates(
      waba_id,
      access_token,
      api_version || "v20.0"
    );
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Meta API fetch failed" },
      { status: 502 }
    );
  }

  // 3. Load existing local templates for this channel
  const { data: existingRows } = await supabase
    .from("message_templates")
    .select("id, name, language, meta_template_id")
    .eq("channel_id", channelId);

  const existingMap = new Map(
    (existingRows ?? []).map((r) => [`${r.name}::${r.language}`, r])
  );

  // 4. Split: new templates to INSERT vs existing to UPDATE
  const toInsert: Record<string, unknown>[] = [];
  const toUpdate: { id: string; data: Record<string, unknown> }[] = [];

  for (const t of metaTemplates) {
    const key = `${t.name}::${t.language}`;
    const sharedFields = {
      status: t.status.toLowerCase(),
      category: (t.category || "utility").toLowerCase(),
      language: t.language,
      components: t.components ?? [],
      meta_template_id: t.id,
    };

    if (existingMap.has(key)) {
      toUpdate.push({ id: existingMap.get(key)!.id, data: sharedFields });
    } else {
      toInsert.push({
        channel_id: channelId,
        name: t.name,
        requested_category: (t.category || "utility").toLowerCase(),
        ...sharedFields,
      });
    }
  }

  // 5. Insert new templates
  if (toInsert.length > 0) {
    const { error: insertError } = await supabase
      .from("message_templates")
      .insert(toInsert);
    if (insertError) {
      return NextResponse.json({ error: insertError.message }, { status: 500 });
    }
  }

  // 6. Update existing templates (preserves requested_category)
  for (const { id, data } of toUpdate) {
    await supabase.from("message_templates").update(data).eq("id", id);
  }

  // 7. Ghost cleanup: mark as cancelled any local template not returned by Meta
  //    Only runs after a full successful fetch (metaTemplates is complete at this point)
  const fetchedMetaIds = new Set(metaTemplates.map((t) => t.id).filter(Boolean));
  const ghostIds = (existingRows ?? [])
    .filter((r) => r.meta_template_id && !fetchedMetaIds.has(r.meta_template_id))
    .map((r) => r.id);

  if (ghostIds.length > 0) {
    await supabase
      .from("message_templates")
      .update({ status: "cancelled" })
      .in("id", ghostIds);
  }

  return NextResponse.json({ synced: metaTemplates.length });
}
```

- [ ] **Step 2: Verificar que o arquivo foi criado corretamente**

Use a ferramenta Read para confirmar que `frontend/src/app/api/templates/sync/route.ts` existe e tem o conteúdo correto.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/templates/sync/route.ts
git commit -m "feat(api): add POST /api/templates/sync with pagination and ghost cleanup"
```

---

## Task 4: Atualizar `TemplatesTab` — auto-sync, botão, toasts e badges

**Files:**
- Modify: `frontend/src/components/campaigns/templates-tab.tsx`

**Mudanças:**
1. Remove o `useEffect` de polling de 30s (era ineficaz — consultava BD local que nunca atualiza)
2. Adiciona auto-sync no mount (substitui o polling)
3. Adiciona botão "Sincronizar" com spinner SVG animado
4. Adiciona toast de sucesso/erro (pattern igual ao `quickSendToast` de `page.tsx`)
5. Troca `<span>` inline por `<Badge>` do shadcn para Status e Categoria
6. Adiciona badge de Idioma

- [ ] **Step 1: Substituir o conteúdo completo do arquivo**

Substitua `frontend/src/components/campaigns/templates-tab.tsx` com:

```typescript
"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import type { MessageTemplate } from "@/lib/types";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; colorClass: string }> = {
  approved:                { label: "Aprovado",       colorClass: "bg-[#e6faf0] text-[#1a7a3a]" },
  pending:                 { label: "Pendente",       colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  pending_category_review: { label: "Rev. categoria", colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

interface Channel {
  id: string;
  provider: string;
  is_active: boolean;
}

export function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncToast, setSyncToast] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const hasSyncedOnMount = useRef(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/templates");
    if (res.ok) setTemplates(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const syncTemplates = useCallback(async () => {
    setSyncing(true);
    try {
      const channelsRes = await fetch("/api/channels");
      const channelsData: Channel[] = channelsRes.ok ? await channelsRes.json() : [];
      const metaChannels = (Array.isArray(channelsData) ? channelsData : []).filter(
        (c) => c.provider === "meta_cloud" && c.is_active
      );

      let errors = 0;
      for (const channel of metaChannels) {
        const res = await fetch(`/api/templates/sync?channel_id=${channel.id}`, {
          method: "POST",
        });
        if (!res.ok) errors++;
      }

      await loadTemplates();
      setSyncToast(
        errors === 0
          ? { type: "success", message: "Templates sincronizados com sucesso." }
          : { type: "error", message: `Sincronização concluída com ${errors} erro(s).` }
      );
    } catch {
      setSyncToast({ type: "error", message: "Erro ao sincronizar templates." });
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncToast(null), 5000);
    }
  }, [loadTemplates]);

  // Auto-sync once on mount (replaces the broken 30s polling)
  useEffect(() => {
    if (hasSyncedOnMount.current) return;
    hasSyncedOnMount.current = true;
    syncTemplates();
  }, [syncTemplates]);

  const cat = (c: string | null) =>
    CATEGORY_CONFIG[(c ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = (s: string) => STATUS_CONFIG[s] ?? STATUS_CONFIG.pending;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2
          style={{ letterSpacing: "-0.3px" }}
          className="text-[20px] font-normal text-[#111111]"
        >
          Templates
        </h2>
        <div className="flex gap-2">
          <button
            onClick={syncTemplates}
            disabled={syncing}
            className="flex items-center gap-2 bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={syncing ? "animate-spin" : ""}
            >
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
              <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
              <path d="M8 16H3v5" />
            </svg>
            {syncing ? "Sincronizando..." : "Sincronizar"}
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Novo Template
          </button>
        </div>
      </div>

      {/* Loading skeletons */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[8px] animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && templates.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum template cadastrado.</p>
          <button
            onClick={() => setShowCreate(true)}
            className="mt-3 text-[13px] text-[#111111] underline"
          >
            Criar primeiro template
          </button>
        </div>
      )}

      {/* Templates table */}
      {!loading && templates.length > 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {["Nome", "Categoria", "Status", "Idioma", "Criado em"].map((h) => (
                  <th
                    key={h}
                    className="text-left text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] px-4 py-3 font-normal"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => {
                const c = cat(t.category);
                const s = st(t.status);
                return (
                  <tr
                    key={t.id}
                    className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]"
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#111111] font-medium">{t.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        className="rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5"
                        style={{ color: c.color, backgroundColor: c.bg }}
                      >
                        {c.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        className={`rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5 ${s.colorClass}`}
                      >
                        {s.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className="rounded-[4px] h-auto text-[11px] font-normal px-2 py-0.5 text-[#7b7b78]"
                      >
                        {t.language}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">
                      {new Date(t.created_at).toLocaleDateString("pt-BR")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Sync toast */}
      {syncToast && (
        <div
          className={`fixed bottom-6 right-6 z-50 text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3 ${
            syncToast.type === "success" ? "bg-[#111111]" : "bg-[#c41c1c]"
          }`}
        >
          <span>{syncToast.message}</span>
          <button
            onClick={() => setSyncToast(null)}
            className="text-white/60 hover:text-white transition-colors leading-none text-lg"
          >
            &times;
          </button>
        </div>
      )}

      <CreateTemplateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          loadTemplates();
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verificar TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: zero erros de tipagem relacionados aos arquivos modificados. Erros pré-existentes em outros arquivos são aceitáveis.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/templates-tab.tsx
git commit -m "feat(ui): templates-tab auto-sync, sync button, toast, and badge upgrades"
```

---

## Task 5: Verificação manual e commit final

**Files:**
- (sem alteração de código — apenas verificação)

- [ ] **Step 1: Conferir os arquivos alterados no diff**

```bash
git log --oneline feat/templates-sync ^master
```

Expected: 3 commits listados:
```
feat(ui): templates-tab auto-sync, sync button, toast, and badge upgrades
feat(api): add POST /api/templates/sync with pagination and ghost cleanup
feat(db): add unique constraint (channel_id, name, language) on message_templates
```

- [ ] **Step 2: Checar se o servidor de desenvolvimento sobe sem erros**

```bash
cd frontend && npx next build 2>&1 | tail -20
```

Expected: build termina sem erros TypeScript nos arquivos modificados (`templates-tab.tsx`, `templates/sync/route.ts`).

- [ ] **Step 3: Checklist de comportamento esperado (verificar no browser)**

Ao abrir `/campanhas?tab=templates`:
1. A aba dispara automaticamente um sync no mount — o botão "Sincronizar" aparece com spinner enquanto carrega
2. Após o sync, templates em outros idiomas (ex: `en_US`) aparecem na tabela
3. O status de templates aprovados/rejeitados no Meta reflete corretamente (verde = "Aprovado", vermelho = "Rejeitado", amarelo = "Pendente")
4. A coluna Idioma exibe o badge com o código do idioma (ex: `pt_BR`, `en_US`)
5. Templates deletados diretamente no Meta aparecem como "Cancelado" após sync
6. Clicar em "Sincronizar" novamente dispara novo sync com spinner animado
7. Toast de sucesso aparece em `bottom-right` e some após 5 segundos
8. O botão "Sincronizar" fica desabilitado durante o sync

- [ ] **Step 4: Avisar usuário para testar e aguardar autorização de push**

Informar: "Implementação concluída na branch `feat/templates-sync`. Por favor teste no ambiente dev. Após validar, autorize o push para master."

---

## Self-Review

**Spec coverage:**

| Requisito do spec | Task que implementa |
|---|---|
| Unique key `(channel_id, name, language)` | Task 2 (migration) |
| Paginação via `paging.next` | Task 3 (`fetchAllMetaTemplates` loop) |
| Escopo por canal (`channel_id` obrigatório) | Task 3 (query param validation) |
| Não sobrescreve `requested_category` | Task 3 (split insert/update) |
| Ghost cleanup (templates deletados na Meta) | Task 3 (Steps 6-7 no handler) |
| Auto-sync no mount | Task 4 (`hasSyncedOnMount` ref + useEffect) |
| Botão manual com spinner | Task 4 (SVG + `animate-spin`) |
| Toast de sucesso/erro | Task 4 (`syncToast` state + fixed div) |
| Badges para Status, Categoria, Idioma | Task 4 (shadcn `<Badge>`) |
| Branch de trabalho | Task 1 |

**Placeholder scan:** Nenhum TBD, TODO ou "implementar depois" encontrado.

**Type consistency:** 
- `MetaTemplateItem` definida em Task 3 e usada apenas dentro de `route.ts`
- `Channel` interface definida em Task 4 e usada apenas em `templates-tab.tsx`
- `MessageTemplate` importada de `@/lib/types` (tipo existente, não modificado)
- `syncToast` tipado como `{ type: "success" | "error"; message: string } | null` — consistente em todo o componente
