# Multi-Pipeline (Funis Editáveis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **REGRA OBRIGATÓRIA:** Todo agente que tocar frontend DEVE invocar a skill `frontend-design` antes de escrever qualquer JSX, CSS ou classe Tailwind.
>
> **COMMITS:** Nenhum commit até autorização explícita do usuário. Escreva os arquivos, mas NÃO faça `git commit`.

**Goal:** Transformar /vendas em um sistema de múltiplos funis dinâmicos, onde cada funil tem seus próprios stages editáveis (renomear, reordenar, adicionar, remover cores), com dois stages protegidos (Fechado Ganho / Perdido) que sempre existem.

**Architecture:** Duas novas tabelas no Supabase (`pipelines` e `pipeline_stages`) + `pipeline_id`/`stage_id` na tabela `deals`. Frontend usa um hook `usePipelines` + `useRealtimeDeals` filtrado por pipeline. O seletor de funis fica no header da página via dropdown. Editor de stages em modal com drag-and-drop (@dnd-kit/sortable já instalado).

**Tech Stack:** Next.js App Router, Supabase (realtime), @dnd-kit/core + @dnd-kit/sortable, TypeScript, Tailwind CSS

---

## File Map

### Novos arquivos
- `backend/migrations/012_multi_pipeline.sql` — tabelas pipelines + pipeline_stages, migração de dados
- `frontend/src/app/api/pipelines/route.ts` — GET lista pipelines, POST cria pipeline com stages default
- `frontend/src/app/api/pipelines/[id]/route.ts` — PATCH renomeia, DELETE (bloqueado se tem deals)
- `frontend/src/app/api/pipelines/[id]/stages/route.ts` — GET stages do pipeline, POST cria stage
- `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` — PATCH atualiza, DELETE (bloqueado se protegido ou tem deals)
- `frontend/src/hooks/use-pipelines.ts` — hook com realtime para pipelines e stages do pipeline ativo
- `frontend/src/components/deals/pipeline-switcher.tsx` — dropdown no header para trocar de funil
- `frontend/src/components/deals/pipeline-create-modal.tsx` — modal para criar novo funil
- `frontend/src/components/deals/pipeline-edit-modal.tsx` — modal para editar stages (drag-and-drop)

### Arquivos modificados
- `frontend/src/lib/types.ts` — adicionar `Pipeline`, `PipelineStage`; atualizar `Deal`
- `frontend/src/hooks/use-realtime-deals.ts` — aceitar `pipelineId`, filtrar por pipeline, incluir stage join
- `frontend/src/app/api/deals/route.ts` — GET aceita `?pipeline_id=`, POST requer `pipeline_id` e usa stage_id
- `frontend/src/app/api/deals/[id]/route.ts` — PATCH aceita `stage_id`, detecta stage protegido via key
- `frontend/src/app/(authenticated)/vendas/page.tsx` — refactor completo com pipeline state
- `frontend/src/components/deals/deal-kanban-metrics.tsx` — usar `pipeline_stages.key` em vez de `stage` string
- `frontend/src/components/deals/deal-detail-sidebar.tsx` — usar `deal.pipeline_stages` em vez de `DEAL_STAGES`
- `frontend/src/components/deals/deal-create-modal.tsx` — aceitar + enviar `pipeline_id`
- `frontend/src/lib/constants.ts` — remover export `DEAL_STAGES`

---

## Task 1: SQL Migration

**Files:**
- Create: `backend/migrations/012_multi_pipeline.sql`

- [ ] **Step 1: Criar o arquivo de migration**

```sql
-- 012_multi_pipeline.sql
-- Cria tabelas pipelines e pipeline_stages, migra deals existentes

-- 1. Tabela de pipelines
CREATE TABLE IF NOT EXISTS pipelines (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  order_index int  NOT NULL DEFAULT 0,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

-- 2. Tabela de stages por pipeline
CREATE TABLE IF NOT EXISTS pipeline_stages (
  id           uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id  uuid    NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  label        text    NOT NULL,
  key          text,           -- só preenchido em stages protegidos: 'fechado_ganho' | 'fechado_perdido'
  dot_color    text    NOT NULL DEFAULT '#5b8aad',
  order_index  int     NOT NULL DEFAULT 0,
  is_protected boolean NOT NULL DEFAULT false,
  created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_stages_pipeline_id ON pipeline_stages(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_stages_order ON pipeline_stages(pipeline_id, order_index);

-- 3. Adicionar colunas na tabela deals
ALTER TABLE deals ADD COLUMN IF NOT EXISTS pipeline_id uuid REFERENCES pipelines(id);
ALTER TABLE deals ADD COLUMN IF NOT EXISTS stage_id    uuid REFERENCES pipeline_stages(id);

CREATE INDEX IF NOT EXISTS idx_deals_pipeline_id ON deals(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage_id    ON deals(stage_id);

-- 4. Seed: Funil Principal com 6 stages default + migrar deals existentes
DO $$
DECLARE
  v_pid  uuid;
  v_s0   uuid; -- Novo
  v_s1   uuid; -- Contato
  v_s2   uuid; -- Proposta
  v_s3   uuid; -- Negociação
  v_s4   uuid; -- Fechado Ganho (protegido)
  v_s5   uuid; -- Perdido (protegido)
BEGIN
  INSERT INTO pipelines (name, order_index) VALUES ('Funil Principal', 0)
    RETURNING id INTO v_pid;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Novo', null, '#e07a7a', 0, false) RETURNING id INTO v_s0;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Contato', null, '#d4a04a', 1, false) RETURNING id INTO v_s1;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Proposta', null, '#9b7abf', 2, false) RETURNING id INTO v_s2;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Negociação', null, '#5b8aad', 3, false) RETURNING id INTO v_s3;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Fechado Ganho', 'fechado_ganho', '#5aad65', 4, true) RETURNING id INTO v_s4;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Perdido', 'fechado_perdido', '#9ca3af', 5, true) RETURNING id INTO v_s5;

  -- Migrar deals existentes para o Funil Principal
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s0 WHERE stage = 'novo';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s1 WHERE stage = 'contato';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s2 WHERE stage = 'proposta';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s3 WHERE stage = 'negociacao';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s4 WHERE stage = 'fechado_ganho';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s5 WHERE stage = 'fechado_perdido';
  -- Fallback: deals com stage desconhecido vão para 'Novo'
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s0 WHERE pipeline_id IS NULL;
END $$;

-- 5. Habilitar realtime
ALTER PUBLICATION supabase_realtime ADD TABLE pipelines;
ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_stages;
```

- [ ] **Step 2: Aplicar a migration no Supabase**

No Supabase Dashboard → SQL Editor, cole e execute o conteúdo do arquivo acima.
Verifique: `SELECT * FROM pipelines;` deve retornar 1 linha ("Funil Principal").
Verifique: `SELECT * FROM pipeline_stages;` deve retornar 6 linhas.
Verifique: `SELECT COUNT(*) FROM deals WHERE pipeline_id IS NULL;` deve retornar 0.

---

## Task 2: API — Pipelines CRUD

**Files:**
- Create: `frontend/src/app/api/pipelines/route.ts`
- Create: `frontend/src/app/api/pipelines/[id]/route.ts`

- [ ] **Step 1: Criar `/api/pipelines/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

const DEFAULT_STAGES = [
  { label: "Novo",         key: null,              dot_color: "#e07a7a", order_index: 0, is_protected: false },
  { label: "Contato",      key: null,              dot_color: "#d4a04a", order_index: 1, is_protected: false },
  { label: "Proposta",     key: null,              dot_color: "#9b7abf", order_index: 2, is_protected: false },
  { label: "Negociação",   key: null,              dot_color: "#5b8aad", order_index: 3, is_protected: false },
  { label: "Fechado Ganho",key: "fechado_ganho",   dot_color: "#5aad65", order_index: 4, is_protected: true  },
  { label: "Perdido",      key: "fechado_perdido", dot_color: "#9ca3af", order_index: 5, is_protected: true  },
];

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipelines")
    .select("*")
    .order("order_index", { ascending: true });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const { name } = await request.json();
  if (!name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });
  const supabase = await getServiceSupabase();

  const { data: pipeline, error: pipelineError } = await supabase
    .from("pipelines")
    .insert({ name: name.trim() })
    .select()
    .single();
  if (pipelineError) return NextResponse.json({ error: pipelineError.message }, { status: 500 });

  const stages = DEFAULT_STAGES.map((s) => ({ ...s, pipeline_id: pipeline.id }));
  const { error: stagesError } = await supabase.from("pipeline_stages").insert(stages);
  if (stagesError) return NextResponse.json({ error: stagesError.message }, { status: 500 });

  return NextResponse.json(pipeline, { status: 201 });
}
```

- [ ] **Step 2: Criar `/api/pipelines/[id]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { name } = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipelines")
    .update({ name: name.trim(), updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { count } = await supabase
    .from("deals")
    .select("*", { count: "exact", head: true })
    .eq("pipeline_id", id);
  if (count && count > 0) {
    return NextResponse.json(
      { error: `Funil tem ${count} deal(s). Mova ou remova os deals antes de excluir.` },
      { status: 409 }
    );
  }
  const { error } = await supabase.from("pipelines").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

---

## Task 3: API — Pipeline Stages CRUD

**Files:**
- Create: `frontend/src/app/api/pipelines/[id]/stages/route.ts`
- Create: `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts`

- [ ] **Step 1: Criar `/api/pipelines/[id]/stages/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipeline_stages")
    .select("*")
    .eq("pipeline_id", id)
    .order("order_index", { ascending: true });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { label, dot_color } = await request.json();
  if (!label?.trim()) return NextResponse.json({ error: "Label é obrigatório" }, { status: 400 });
  const supabase = await getServiceSupabase();

  // Inserir antes dos stages protegidos (que ficam sempre no final)
  const { data: lastNormal } = await supabase
    .from("pipeline_stages")
    .select("order_index")
    .eq("pipeline_id", id)
    .eq("is_protected", false)
    .order("order_index", { ascending: false })
    .limit(1);

  const insertAt = (lastNormal?.[0]?.order_index ?? -1) + 1;

  // Shiftar stages protegidos para abrir espaço
  await supabase.rpc("increment_stage_order", {
    p_pipeline_id: id,
    p_from_order: insertAt,
  });

  const { data, error } = await supabase
    .from("pipeline_stages")
    .insert({
      pipeline_id: id,
      label: label.trim(),
      dot_color: dot_color || "#5b8aad",
      order_index: insertAt,
      is_protected: false,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

> **Nota:** A função `increment_stage_order` precisa ser criada no Supabase. Adicione ao migration:
> ```sql
> CREATE OR REPLACE FUNCTION increment_stage_order(p_pipeline_id uuid, p_from_order int)
> RETURNS void LANGUAGE sql AS $$
>   UPDATE pipeline_stages
>   SET order_index = order_index + 1
>   WHERE pipeline_id = p_pipeline_id AND order_index >= p_from_order;
> $$;
> ```
> Adicione esse bloco ao final de `012_multi_pipeline.sql` antes de aplicar.

- [ ] **Step 2: Criar `/api/pipelines/[id]/stages/[stageId]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; stageId: string }> }
) {
  const { stageId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const updates: Record<string, unknown> = {};
  if (body.label !== undefined) updates.label = body.label;
  if (body.dot_color !== undefined) updates.dot_color = body.dot_color;
  if (body.order_index !== undefined) updates.order_index = body.order_index;
  const { data, error } = await supabase
    .from("pipeline_stages")
    .update(updates)
    .eq("id", stageId)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; stageId: string }> }
) {
  const { stageId } = await params;
  const supabase = await getServiceSupabase();

  const { data: stage } = await supabase
    .from("pipeline_stages")
    .select("is_protected")
    .eq("id", stageId)
    .single();
  if (stage?.is_protected) {
    return NextResponse.json({ error: "Stages protegidos não podem ser removidos." }, { status: 409 });
  }

  const { count } = await supabase
    .from("deals")
    .select("*", { count: "exact", head: true })
    .eq("stage_id", stageId);
  if (count && count > 0) {
    return NextResponse.json(
      { error: `Stage tem ${count} deal(s). Mova os deals antes de remover.` },
      { status: 409 }
    );
  }

  const { error } = await supabase.from("pipeline_stages").delete().eq("id", stageId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

---

## Task 4: API — Atualizar rotas de Deals

**Files:**
- Modify: `frontend/src/app/api/deals/route.ts`
- Modify: `frontend/src/app/api/deals/[id]/route.ts`

- [ ] **Step 1: Atualizar `deals/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const pipelineId = searchParams.get("pipeline_id");
  const supabase = await getServiceSupabase();

  let query = supabase
    .from("deals")
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .order("updated_at", { ascending: false });

  if (pipelineId) query = query.eq("pipeline_id", pipelineId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  // Buscar o primeiro stage não-protegido do pipeline
  const { data: firstStage } = await supabase
    .from("pipeline_stages")
    .select("id")
    .eq("pipeline_id", body.pipeline_id)
    .eq("is_protected", false)
    .order("order_index", { ascending: true })
    .limit(1)
    .single();

  const { data, error } = await supabase
    .from("deals")
    .insert({
      lead_id: body.lead_id,
      title: body.title,
      value: body.value || 0,
      pipeline_id: body.pipeline_id,
      stage_id: firstStage?.id ?? null,
      stage: "novo", // mantido por compatibilidade
      category: body.category || null,
      expected_close_date: body.expected_close_date || null,
      assigned_to: body.assigned_to || null,
    })
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Atualizar `deals/[id]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const updates: Record<string, unknown> = { ...body, updated_at: new Date().toISOString() };

  // Se stage_id foi fornecido, detectar se é stage protegido para setar closed_at
  if (body.stage_id) {
    const { data: stage } = await supabase
      .from("pipeline_stages")
      .select("key")
      .eq("id", body.stage_id)
      .single();
    if (stage?.key === "fechado_ganho" || stage?.key === "fechado_perdido") {
      updates.closed_at = new Date().toISOString();
    }
  }

  const { data, error } = await supabase
    .from("deals")
    .update(updates)
    .eq("id", id)
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("deals").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

---

## Task 5: Types e Hooks

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/hooks/use-pipelines.ts`
- Modify: `frontend/src/hooks/use-realtime-deals.ts`

- [ ] **Step 1: Adicionar novos tipos em `types.ts`**

Adicionar **antes** da interface `Deal` existente:

```typescript
export interface Pipeline {
  id: string;
  name: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface PipelineStage {
  id: string;
  pipeline_id: string;
  label: string;
  key: string | null; // 'fechado_ganho' | 'fechado_perdido' | null
  dot_color: string;
  order_index: number;
  is_protected: boolean;
  created_at: string;
}
```

Atualizar a interface `Deal` — adicionar campos:

```typescript
export interface Deal {
  id: string;
  lead_id: string;
  pipeline_id: string | null;   // ← novo
  stage_id: string | null;      // ← novo
  title: string;
  value: number;
  stage: string;                // mantido por compatibilidade
  category: string | null;
  expected_close_date: string | null;
  assigned_to: string | null;
  closed_at: string | null;
  lost_reason: string | null;
  created_at: string;
  updated_at: string;
  // Joined fields
  pipeline_stages?: PipelineStage | null;  // ← novo
  leads?: {
    id: string;
    name: string | null;
    company: string | null;
    phone: string;
    nome_fantasia: string | null;
  };
}
```

- [ ] **Step 2: Criar `use-pipelines.ts`**

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Pipeline, PipelineStage } from "@/lib/types";

export function usePipelines() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchPipelines = useCallback(async () => {
    const { data } = await supabase
      .from("pipelines")
      .select("*")
      .order("order_index", { ascending: true });
    if (data) setPipelines(data);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchPipelines();
    const channel = supabase
      .channel("pipelines-changes")
      .on("postgres_changes", { event: "*", schema: "public", table: "pipelines" }, fetchPipelines)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchPipelines, supabase]);

  return { pipelines, loading, refetch: fetchPipelines };
}

export function usePipelineStages(pipelineId: string | null) {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const supabase = createClient();

  const fetchStages = useCallback(async () => {
    if (!pipelineId) { setStages([]); return; }
    const { data } = await supabase
      .from("pipeline_stages")
      .select("*")
      .eq("pipeline_id", pipelineId)
      .order("order_index", { ascending: true });
    if (data) setStages(data);
  }, [pipelineId, supabase]);

  useEffect(() => {
    fetchStages();
    if (!pipelineId) return;
    const channel = supabase
      .channel(`pipeline-stages-${pipelineId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "pipeline_stages" }, fetchStages)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchStages, pipelineId, supabase]);

  return { stages, refetch: fetchStages };
}
```

- [ ] **Step 3: Atualizar `use-realtime-deals.ts`**

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Deal } from "@/lib/types";

export function useRealtimeDeals(pipelineId: string | null) {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchDeals = useCallback(async () => {
    if (!pipelineId) { setDeals([]); setLoading(false); return; }
    const { data } = await supabase
      .from("deals")
      .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
      .eq("pipeline_id", pipelineId)
      .order("updated_at", { ascending: false });
    if (data) setDeals(data);
    setLoading(false);
  }, [pipelineId, supabase]);

  useEffect(() => {
    setLoading(true);
    fetchDeals();
    const channel = supabase
      .channel(`deals-changes-${pipelineId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "deals" }, fetchDeals)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchDeals, pipelineId, supabase]);

  return { deals, loading };
}
```

---

## Task 6: Componente PipelineSwitcher

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever qualquer JSX/Tailwind.

**Files:**
- Create: `frontend/src/components/deals/pipeline-switcher.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`**

Antes de escrever o componente, invoque a skill `frontend-design`. Só escreva o código após seguir as instruções da skill.

- [ ] **Step 2: Criar `pipeline-switcher.tsx`**

```typescript
"use client";

import { useState, useRef, useEffect } from "react";
import type { Pipeline } from "@/lib/types";

interface PipelineSwitcherProps {
  pipelines: Pipeline[];
  activePipelineId: string | null;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
  onEdit: () => void;
  onDelete: (pipeline: Pipeline) => void;
}

export function PipelineSwitcher({
  pipelines, activePipelineId, onSelect, onCreateNew, onEdit, onDelete,
}: PipelineSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const activePipeline = pipelines.find((p) => p.id === activePipelineId);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setOpen(false);
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Funil</p>
      <div className="flex items-center gap-2">
        {/* Dropdown trigger */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 group"
          >
            <h1
              style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
              className="text-[32px] font-normal text-[#111111] hover:text-[#7b7b78] transition-colors"
            >
              {activePipeline?.name ?? "Selecionar funil"}
            </h1>
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="#7b7b78"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`mt-1 transition-transform ${open ? "rotate-180" : ""}`}
            >
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>

          {open && (
            <div className="absolute top-full left-0 mt-2 bg-white border border-[#dedbd6] rounded-[8px] shadow-sm z-50 min-w-[220px] py-1">
              {pipelines.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { onSelect(p.id); setOpen(false); }}
                  className={`w-full text-left px-4 py-2.5 text-[13px] transition-colors flex items-center justify-between ${
                    p.id === activePipelineId
                      ? "text-[#111111] bg-[#faf9f6]"
                      : "text-[#313130] hover:bg-[#faf9f6]"
                  }`}
                >
                  {p.name}
                  {p.id === activePipelineId && (
                    <svg width="14" height="14" fill="none" viewBox="0 0 16 16" stroke="#111111" strokeWidth="2" strokeLinecap="round">
                      <path d="M3 8l4 4 6-6" />
                    </svg>
                  )}
                </button>
              ))}
              <div className="border-t border-[#dedbd6] mt-1 pt-1">
                <button
                  onClick={() => { onCreateNew(); setOpen(false); }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#7b7b78] hover:bg-[#faf9f6] transition-colors flex items-center gap-2"
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
                  </svg>
                  Novo Funil
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ⋯ menu */}
        {activePipeline && (
          <div className="relative mt-2" ref={menuRef}>
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="w-7 h-7 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <circle cx="8" cy="3" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="8" cy="13" r="1.2" />
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute top-full left-0 mt-1 bg-white border border-[#dedbd6] rounded-[8px] shadow-sm z-50 min-w-[160px] py-1">
                <button
                  onClick={() => { onEdit(); setMenuOpen(false); }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#313130] hover:bg-[#faf9f6] transition-colors"
                >
                  Editar Funil
                </button>
                <button
                  onClick={() => { onDelete(activePipeline); setMenuOpen(false); }}
                  className="w-full text-left px-4 py-2.5 text-[13px] text-[#e07a7a] hover:bg-[#faf9f6] transition-colors"
                >
                  Excluir Funil
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## Task 7: Modais de Pipeline

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever qualquer JSX/Tailwind.

**Files:**
- Create: `frontend/src/components/deals/pipeline-create-modal.tsx`
- Create: `frontend/src/components/deals/pipeline-edit-modal.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`**

Antes de escrever qualquer modal, invoque a skill `frontend-design`. Só escreva o código após seguir as instruções da skill.

- [ ] **Step 2: Criar `pipeline-create-modal.tsx`**

```typescript
"use client";

import { useState } from "react";

interface PipelineCreateModalProps {
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}

export function PipelineCreateModal({ onClose, onCreate }: PipelineCreateModalProps) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    await onCreate(name.trim());
    setSaving(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-sm p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Novo Funil
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome do Funil *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Funil Atacado"
              autoFocus
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
            />
            <p className="text-[11px] text-[#7b7b78] mt-1.5">O funil será criado com os stages padrão (Novo, Contato, Proposta, Negociação, Fechado Ganho, Perdido).</p>
          </div>
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving || !name.trim()} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Funil"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Criar `pipeline-edit-modal.tsx`**

```typescript
"use client";

import { useState } from "react";
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy,
  useSortable, arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PipelineStage } from "@/lib/types";

const COLOR_PALETTE = [
  "#e07a7a", "#d4a04a", "#d4b84a", "#5aad65",
  "#5b8aad", "#9b7abf", "#9ca3af", "#111111",
];

interface EditableStage extends PipelineStage {
  _dirty?: boolean;
}

interface PipelineEditModalProps {
  pipelineId: string;
  pipelineName: string;
  stages: PipelineStage[];
  onClose: () => void;
  onSaved: () => void;
}

function SortableStageRow({
  stage, onChange, onDelete,
}: {
  stage: EditableStage;
  onChange: (id: string, field: keyof EditableStage, value: string) => void;
  onDelete: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: stage.id, disabled: stage.is_protected });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }}
      className="flex items-center gap-3 py-2.5 px-3 bg-white border border-[#dedbd6] rounded-[6px] mb-2"
    >
      {/* Drag handle */}
      <div
        {...(stage.is_protected ? {} : { ...listeners, ...attributes })}
        className={`flex-shrink-0 ${stage.is_protected ? "opacity-20 cursor-not-allowed" : "cursor-grab active:cursor-grabbing"}`}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="#7b7b78">
          <circle cx="5" cy="4" r="1.2" /><circle cx="11" cy="4" r="1.2" />
          <circle cx="5" cy="8" r="1.2" /><circle cx="11" cy="8" r="1.2" />
          <circle cx="5" cy="12" r="1.2" /><circle cx="11" cy="12" r="1.2" />
        </svg>
      </div>

      {/* Color picker */}
      <div className="relative flex-shrink-0 group">
        <div className="w-4 h-4 rounded-full cursor-pointer border border-[#dedbd6]" style={{ backgroundColor: stage.dot_color }} />
        {!stage.is_protected && (
          <div className="absolute left-0 top-full mt-1 bg-white border border-[#dedbd6] rounded-[6px] p-2 z-10 hidden group-hover:grid grid-cols-4 gap-1 w-[88px] shadow-sm">
            {COLOR_PALETTE.map((c) => (
              <button key={c} type="button" onClick={() => onChange(stage.id, "dot_color", c)}
                className={`w-4 h-4 rounded-full border ${stage.dot_color === c ? "border-[#111111]" : "border-transparent"}`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Label input */}
      <input
        value={stage.label}
        onChange={(e) => onChange(stage.id, "label", e.target.value)}
        disabled={stage.is_protected}
        className="flex-1 text-[13px] text-[#111111] bg-transparent focus:outline-none disabled:text-[#7b7b78] min-w-0"
      />

      {/* Protected badge or delete */}
      {stage.is_protected ? (
        <span className="text-[10px] uppercase tracking-[0.4px] text-[#7b7b78] border border-[#dedbd6] px-2 py-0.5 rounded-full flex-shrink-0">
          Protegido
        </span>
      ) : (
        <button type="button" onClick={() => onDelete(stage.id)}
          className="flex-shrink-0 text-[#7b7b78] hover:text-[#e07a7a] transition-colors"
        >
          <svg width="14" height="14" fill="none" viewBox="0 0 16 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      )}
    </div>
  );
}

export function PipelineEditModal({
  pipelineId, pipelineName, stages: initialStages, onClose, onSaved,
}: PipelineEditModalProps) {
  const [stages, setStages] = useState<EditableStage[]>(initialStages);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleChange(id: string, field: keyof EditableStage, value: string) {
    setStages((prev) => prev.map((s) => s.id === id ? { ...s, [field]: value, _dirty: true } : s));
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setStages((prev) => {
      const oldIndex = prev.findIndex((s) => s.id === active.id);
      const newIndex = prev.findIndex((s) => s.id === over.id);
      return arrayMove(prev, oldIndex, newIndex).map((s, i) => ({ ...s, order_index: i, _dirty: true }));
    });
  }

  async function handleAddStage() {
    const { data } = await fetch(`/api/pipelines/${pipelineId}/stages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "Novo Stage", dot_color: "#5b8aad" }),
    }).then((r) => r.json().then((d) => ({ data: d })));
    if (data?.id) setStages((prev) => [...prev, data]);
  }

  async function handleDelete(stageId: string) {
    const res = await fetch(`/api/pipelines/${pipelineId}/stages/${stageId}`, { method: "DELETE" });
    if (!res.ok) {
      const { error: msg } = await res.json();
      setError(msg);
      return;
    }
    setStages((prev) => prev.filter((s) => s.id !== stageId));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    const dirty = stages.filter((s) => s._dirty);
    await Promise.all(
      dirty.map((s) =>
        fetch(`/api/pipelines/${pipelineId}/stages/${s.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: s.label, dot_color: s.dot_color, order_index: s.order_index }),
        })
      )
    );
    setSaving(false);
    onSaved();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-md p-6 max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-1" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Editar Funil
        </h3>
        <p className="text-[13px] text-[#7b7b78] mb-4">{pipelineName}</p>

        {error && (
          <div className="bg-[#fee2e2] border border-[#fca5a5] rounded-[6px] px-3 py-2 text-[13px] text-[#991b1b] mb-3">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Stages</p>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              {stages.map((stage) => (
                <SortableStageRow key={stage.id} stage={stage} onChange={handleChange} onDelete={handleDelete} />
              ))}
            </SortableContext>
          </DndContext>
          <button type="button" onClick={handleAddStage}
            className="w-full border border-dashed border-[#dedbd6] text-[13px] text-[#7b7b78] py-2.5 rounded-[6px] hover:border-[#111111] hover:text-[#111111] transition-colors flex items-center justify-center gap-2"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
            Adicionar Stage
          </button>
        </div>

        <div className="flex gap-2 justify-end pt-4 border-t border-[#dedbd6] mt-4">
          <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">
            Cancelar
          </button>
          <button onClick={handleSave} disabled={saving} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

---

## Task 8: Refatorar VendasPage e Componentes Existentes

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever qualquer JSX/Tailwind.

**Files:**
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`
- Modify: `frontend/src/components/deals/deal-kanban-metrics.tsx`
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`
- Modify: `frontend/src/components/deals/deal-create-modal.tsx`
- Modify: `frontend/src/lib/constants.ts`

- [ ] **Step 1: Invocar skill `frontend-design`**

Antes de escrever qualquer alteração de componente, invoque a skill `frontend-design`. Só escreva o código após seguir as instruções da skill.

- [ ] **Step 2: Reescrever `vendas/page.tsx`**

```typescript
"use client";

import { useState, useEffect } from "react";
import {
  DndContext, DragOverlay, closestCorners, PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent,
} from "@dnd-kit/core";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { usePipelines, usePipelineStages } from "@/hooks/use-pipelines";
import { DealCard } from "@/components/deals/deal-card";
import { DealKanbanMetrics } from "@/components/deals/deal-kanban-metrics";
import { DealKanbanFilters } from "@/components/deals/deal-kanban-filters";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { DealDetailSidebar } from "@/components/deals/deal-detail-sidebar";
import { LostReasonModal } from "@/components/deals/lost-reason-modal";
import { PipelineSwitcher } from "@/components/deals/pipeline-switcher";
import { PipelineCreateModal } from "@/components/deals/pipeline-create-modal";
import { PipelineEditModal } from "@/components/deals/pipeline-edit-modal";
import type { Deal, Pipeline, PipelineStage } from "@/lib/types";

function DroppableColumn({
  id, title, dotColor, deals, onDealClick,
}: {
  id: string; title: string; dotColor: string; deals: Deal[]; onDealClick: (deal: Deal) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="bg-[#f7f5f1] border border-[#dedbd6] rounded-[8px] flex flex-col min-h-[200px] w-72 flex-shrink-0">
      <div className="px-4 py-3 bg-[#f0ede8] border-b border-[#dedbd6] rounded-t-[8px] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[13px] font-medium text-[#111111] uppercase tracking-[0.6px]">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          {columnValue > 0 && <span className="text-[11px] text-[#7b7b78]">{fmt(columnValue)}</span>}
          <span className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-2 py-0.5">{deals.length}</span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`flex-1 py-2 overflow-y-auto transition-all duration-200 ${isOver ? "ring-2 ring-[#111111] ring-inset rounded-b-[8px]" : ""}`}
      >
        {deals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#7b7b78]">Nenhum deal</p>
          </div>
        )}
        {deals.map((deal) => (
          <DraggableDealCard key={deal.id} deal={deal} onClick={onDealClick} />
        ))}
      </div>
    </div>
  );
}

function DraggableDealCard({ deal, onClick }: { deal: Deal; onClick: (deal: Deal) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id, data: deal });
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className={isDragging ? "opacity-30" : ""}>
      <DealCard deal={deal} onClick={onClick} />
    </div>
  );
}

export default function VendasPage() {
  const { pipelines, loading: pipelinesLoading } = usePipelines();
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null);
  const { stages } = usePipelineStages(selectedPipelineId);
  const { deals, loading: dealsLoading } = useRealtimeDeals(selectedPipelineId);
  const { leads } = useRealtimeLeads();

  const [selectedDeal, setSelectedDeal] = useState<Deal | null>(null);
  const [activeDrag, setActiveDrag] = useState<Deal | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showPipelineCreate, setShowPipelineCreate] = useState(false);
  const [showPipelineEdit, setShowPipelineEdit] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [lostDeal, setLostDeal] = useState<{ deal: Deal; stageId: string } | null>(null);

  // Auto-selecionar primeiro pipeline
  useEffect(() => {
    if (pipelines.length > 0 && !selectedPipelineId) {
      setSelectedPipelineId(pipelines[0].id);
    }
  }, [pipelines, selectedPipelineId]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  function handleDragStart(event: DragStartEvent) { setActiveDrag(event.active.data.current as Deal); }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const deal = active.data.current as Deal;
    const newStageId = over.id as string;
    if (deal.stage_id === newStageId) return;
    const newStage = stages.find((s) => s.id === newStageId);
    if (newStage?.key === "fechado_perdido") {
      setLostDeal({ deal, stageId: newStageId });
      return;
    }
    await fetch(`/api/deals/${deal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: newStageId }),
    });
  }

  async function handleLostConfirm(reason: string) {
    if (!lostDeal) return;
    await fetch(`/api/deals/${lostDeal.deal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: lostDeal.stageId, lost_reason: reason }),
    });
    setLostDeal(null);
  }

  async function handleCreateDeal(data: {
    lead_id: string; title: string; value: number; category: string; expected_close_date: string;
  }) {
    if (!selectedPipelineId) return;
    await fetch("/api/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, pipeline_id: selectedPipelineId }),
    });
  }

  async function handleUpdateDeal(dealId: string, data: Record<string, unknown>) {
    await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    setSelectedDeal(null);
  }

  async function handleCreatePipeline(name: string) {
    const res = await fetch("/api/pipelines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const pipeline = await res.json();
    if (pipeline?.id) setSelectedPipelineId(pipeline.id);
  }

  async function handleDeletePipeline(pipeline: Pipeline) {
    const res = await fetch(`/api/pipelines/${pipeline.id}`, { method: "DELETE" });
    if (!res.ok) {
      const { error } = await res.json();
      alert(error);
      return;
    }
    setSelectedPipelineId(pipelines.find((p) => p.id !== pipeline.id)?.id ?? null);
  }

  const loading = pipelinesLoading || dealsLoading;

  if (loading && pipelines.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
          <span className="text-[14px] text-[#7b7b78]">Carregando...</span>
        </div>
      </div>
    );
  }

  const filteredDeals = deals.filter((d) => {
    const stage = stages.find((s) => s.id === d.stage_id);
    if (showActive && stage?.is_protected) return false;
    if (category && d.category !== category) return false;
    if (search) {
      const q = search.toLowerCase();
      const lead = d.leads;
      const match =
        d.title.toLowerCase().includes(q) ||
        (lead?.name || "").toLowerCase().includes(q) ||
        (lead?.company || "").toLowerCase().includes(q) ||
        (lead?.phone || "").includes(q);
      if (!match) return false;
    }
    return true;
  });

  const activePipeline = pipelines.find((p) => p.id === selectedPipelineId) ?? null;

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0">
        <PipelineSwitcher
          pipelines={pipelines}
          activePipelineId={selectedPipelineId}
          onSelect={setSelectedPipelineId}
          onCreateNew={() => setShowPipelineCreate(true)}
          onEdit={() => setShowPipelineEdit(true)}
          onDelete={handleDeletePipeline}
        />
        <button
          onClick={() => setShowCreate(true)}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-2"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Nova Oportunidade
        </button>
      </div>

      {/* Kanban content area */}
      <div className="flex-1 overflow-auto bg-[#faf9f6]">
        <DealKanbanMetrics deals={deals} stages={stages} />
        <div className="px-6 pt-4">
          <DealKanbanFilters
            search={search} onSearchChange={setSearch}
            category={category} onCategoryChange={setCategory}
            showActive={showActive} onToggleActive={() => setShowActive(!showActive)}
          />
        </div>

        <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="flex gap-3 overflow-x-auto p-6 pt-2">
            {stages.map((stage) => {
              const stageDeals = filteredDeals.filter((d) => d.stage_id === stage.id);
              return (
                <DroppableColumn
                  key={stage.id}
                  id={stage.id}
                  title={stage.label}
                  dotColor={stage.dot_color}
                  deals={stageDeals}
                  onDealClick={setSelectedDeal}
                />
              );
            })}
          </div>
          <DragOverlay>
            {activeDrag ? (
              <div className="w-[270px] opacity-90 rotate-[2deg]">
                <DealCard deal={activeDrag} onClick={() => {}} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>

      {selectedDeal && (
        <DealDetailSidebar deal={selectedDeal} stages={stages} onClose={() => setSelectedDeal(null)} onUpdate={handleUpdateDeal} />
      )}
      {showCreate && selectedPipelineId && (
        <DealCreateModal leads={leads} onClose={() => setShowCreate(false)} onCreate={handleCreateDeal} />
      )}
      {lostDeal && (
        <LostReasonModal onConfirm={handleLostConfirm} onCancel={() => setLostDeal(null)} />
      )}
      {showPipelineCreate && (
        <PipelineCreateModal onClose={() => setShowPipelineCreate(false)} onCreate={handleCreatePipeline} />
      )}
      {showPipelineEdit && activePipeline && (
        <PipelineEditModal
          pipelineId={activePipeline.id}
          pipelineName={activePipeline.name}
          stages={stages}
          onClose={() => setShowPipelineEdit(false)}
          onSaved={() => {}}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Atualizar `deal-kanban-metrics.tsx`**

A prop `deals` agora virá filtrada por pipeline. Substituir referências a `d.stage` por `d.pipeline_stages?.key`:

```typescript
import type { Deal, PipelineStage } from "@/lib/types";

interface DealKanbanMetricsProps {
  deals: Deal[];
  stages: PipelineStage[];
}

export function DealKanbanMetrics({ deals, stages }: DealKanbanMetricsProps) {
  const activeDeals = deals.filter((d) => !d.pipeline_stages?.is_protected);
  const pipelineValue = activeDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const wonThisMonth = deals.filter(
    (d) => d.pipeline_stages?.key === "fechado_ganho" && d.closed_at && new Date(d.closed_at) >= monthStart
  );
  const wonValue = wonThisMonth.reduce((sum, d) => sum + (d.value || 0), 0);

  const totalClosed = deals.filter((d) => d.pipeline_stages?.is_protected).length;
  const totalWon = deals.filter((d) => d.pipeline_stages?.key === "fechado_ganho").length;
  const conversionRate = totalClosed > 0 ? Math.round((totalWon / totalClosed) * 100) : 0;

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="bg-[#f7f5f1] border-b border-[#dedbd6] px-6 py-3 flex gap-8 flex-shrink-0">
      <div className="flex flex-col">
        <span style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">{activeDeals.length}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Pipeline ativo</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{fmt(pipelineValue)}</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#0bdf50]">{fmt(wonValue)}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Ganho no mes</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{wonThisMonth.length} deals</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">{conversionRate}%</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Taxa de conversao</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{totalWon} de {totalClosed} fechados</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">{deals.length}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Total de deals</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{fmt(deals.reduce((sum, d) => sum + (d.value || 0), 0))}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Atualizar `deal-detail-sidebar.tsx`**

Remover import de `DEAL_STAGES`. Adicionar prop `stages: PipelineStage[]`. Substituir `stageInfo`:

```typescript
// Remover esta linha:
// import { DEAL_STAGES, DEAL_CATEGORIES } from "@/lib/constants";
// Adicionar:
import { DEAL_CATEGORIES } from "@/lib/constants";
import type { Deal, PipelineStage } from "@/lib/types";

interface DealDetailSidebarProps {
  deal: Deal;
  stages: PipelineStage[];  // ← novo
  onClose: () => void;
  onUpdate: (dealId: string, data: Record<string, unknown>) => Promise<void>;
}

export function DealDetailSidebar({ deal, stages, onClose, onUpdate }: DealDetailSidebarProps) {
  // ...
  // Substituir:
  // const stageInfo = DEAL_STAGES.find((s) => s.key === deal.stage);
  // Por:
  const stageInfo = deal.pipeline_stages ?? stages.find((s) => s.id === deal.stage_id) ?? null;
  // ...
  // No JSX, usar stageInfo?.dot_color e stageInfo?.label normalmente (interface compatível)
}
```

- [ ] **Step 5: Remover `DEAL_STAGES` de `constants.ts`**

Remover as linhas 9-16 de `frontend/src/lib/constants.ts` (o bloco `export const DEAL_STAGES = [...]`).

Verificar que nenhum outro arquivo importa `DEAL_STAGES`:
```bash
grep -r "DEAL_STAGES" frontend/src/ --include="*.ts" --include="*.tsx"
```
Se houver outros arquivos, atualizar cada um para usar `pipeline_stages` do deal ou o array de stages passado via prop.

---

## Self-Review

**Spec coverage check:**
- ✅ Múltiplos funis → Tasks 2, 8
- ✅ Stages customizáveis → Tasks 3, 7
- ✅ Stages protegidos (is_protected) → Tasks 1, 3, 7
- ✅ Stages default na criação de funil → Task 2 (DEFAULT_STAGES)
- ✅ Deal pertence a um funil → Tasks 1, 4, 5
- ✅ Migração não destrutiva → Task 1
- ✅ Seletor de funis no header → Tasks 6, 8
- ✅ Editor de stages com DnD → Task 7
- ✅ API protege deleção de stages com deals → Task 3
- ✅ Realtime para pipelines e stages → Task 5

**Placeholder scan:** Nenhum TBD ou placeholder encontrado.

**Type consistency:**
- `PipelineStage.id` usado consistentemente nos componentes
- `Deal.stage_id` referencia `PipelineStage.id` em todos os lugares
- `Deal.pipeline_stages` (join) usado em metrics e sidebar
- `stages` prop passada de VendasPage → DealKanbanMetrics, DealDetailSidebar
