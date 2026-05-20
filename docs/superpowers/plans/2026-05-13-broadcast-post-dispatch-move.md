# Broadcast Post-Dispatch Move Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Frontend agents:** REQUIRED SUB-SKILL: Use superpowers:frontend-design for every task that touches frontend files.

**Goal:** Add an optional "Ação pós-disparo" step (step 4) to the broadcast creation wizard that moves each lead's deal to a chosen Kanban stage after their message is successfully sent.

**Architecture:** A new `move_to_stage_id` nullable UUID column on `broadcasts` stores the target stage. The frontend wizard gains a fifth step between Leads and Revisão with cascading pipeline→stage selectors. The Python broadcast worker, after `mark_broadcast_lead_sent()`, checks this field and updates all matching deals for that lead in the target pipeline.

**Tech Stack:** Next.js 15 App Router, React (client component), Supabase (postgres + JS client), FastAPI + Python backend worker.

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Add step 4 UI, new state, pipeline/stage loaders, updated canAdvance, updated handleCreate and resetForm |
| `frontend/src/app/api/broadcasts/route.ts` | Accept `move_to_stage_id` in POST body |
| `backend/app/broadcast/worker.py` | After successful send: move deals if `move_to_stage_id` set |

Database column must be added manually (Task 1).

---

## Task 1: Add column to Supabase

**Files:** none (Supabase dashboard / SQL editor)

- [ ] **Step 1: Run this SQL in the Supabase SQL editor for the project**

```sql
ALTER TABLE broadcasts
  ADD COLUMN IF NOT EXISTS move_to_stage_id UUID
    REFERENCES pipeline_stages(id) ON DELETE SET NULL;
```

- [ ] **Step 2: Verify the column exists**

In Supabase Table Editor → `broadcasts` → confirm column `move_to_stage_id` appears with type `uuid`, nullable, no default.

- [ ] **Step 3: Commit a note**

```bash
git commit --allow-empty -m "chore: add move_to_stage_id column to broadcasts (SQL run in Supabase)"
```

---

## Task 2: Backend API — accept move_to_stage_id in POST /api/broadcasts

**Files:**
- Modify: `frontend/src/app/api/broadcasts/route.ts`

- [ ] **Step 1: Read the current file**

```
frontend/src/app/api/broadcasts/route.ts
```

Current insert block (lines ~21-37):
```typescript
const { data, error } = await supabase
  .from("broadcasts")
  .insert({
    name: body.name,
    channel_id: body.channel_id || null,
    template_name: body.template_name,
    template_preset_id: body.template_preset_id || null,
    template_variables: body.template_variables || {},
    send_interval_min: body.send_interval_min || 3,
    send_interval_max: body.send_interval_max || 8,
    cadence_id: body.cadence_id || null,
    agent_profile_id: body.agent_profile_id || null,
    scheduled_at: body.scheduled_at || null,
    status: body.scheduled_at ? "scheduled" : "draft",
    env_tag: APP_ENV,
  })
```

- [ ] **Step 2: Add `move_to_stage_id` to the insert object**

Add one line after `agent_profile_id`:
```typescript
    move_to_stage_id: body.move_to_stage_id || null,
```

Full updated insert:
```typescript
const { data, error } = await supabase
  .from("broadcasts")
  .insert({
    name: body.name,
    channel_id: body.channel_id || null,
    template_name: body.template_name,
    template_preset_id: body.template_preset_id || null,
    template_variables: body.template_variables || {},
    send_interval_min: body.send_interval_min || 3,
    send_interval_max: body.send_interval_max || 8,
    cadence_id: body.cadence_id || null,
    agent_profile_id: body.agent_profile_id || null,
    move_to_stage_id: body.move_to_stage_id || null,
    scheduled_at: body.scheduled_at || null,
    status: body.scheduled_at ? "scheduled" : "draft",
    env_tag: APP_ENV,
  })
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/broadcasts/route.ts
git commit -m "feat(broadcasts): accept move_to_stage_id in POST"
```

---

## Task 3: Frontend — new wizard step "Ação pós-disparo"

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

> **REQUIRED:** Use superpowers:frontend-design skill before making any changes.

This is the largest task. Read the full file before starting.

### 3a — New local types

- [ ] **Step 1: Add two local interfaces near the top of the file (after the existing `Lead` interface, around line 27)**

```typescript
interface MovePipeline {
  id: string;
  name: string;
}

interface MoveStage {
  id: string;
  label: string;
  dot_color: string;
}
```

### 3b — New state variables

- [ ] **Step 2: Add new state variables in the "Step 3: Leads" state block (after `csvFile` state, around line 102)**

```typescript
// ── Step 4: Post-dispatch action ──────────────────────────────────────────
const [moveAction, setMoveAction] = useState<"none" | "move">("none");
const [movePipelineId, setMovePipelineId] = useState("");
const [moveStageId, setMoveStageId] = useState("");
const [movePipelines, setMovePipelines] = useState<MovePipeline[]>([]);
const [moveStages, setMoveStages] = useState<MoveStage[]>([]);
const [loadingMovePipelines, setLoadingMovePipelines] = useState(false);
const [loadingMoveStages, setLoadingMoveStages] = useState(false);
```

### 3c — Load pipelines when step 4 is entered

- [ ] **Step 3: Add a useEffect after the existing "Load leads on step 3 mount" effect**

```typescript
// Load pipelines when entering step 4
useEffect(() => {
  if (step !== 4 || movePipelines.length > 0) return;
  setLoadingMovePipelines(true);
  fetch("/api/pipelines")
    .then((r) => r.json())
    .then((d) => setMovePipelines(Array.isArray(d) ? d : []))
    .catch(() => setMovePipelines([]))
    .finally(() => setLoadingMovePipelines(false));
}, [step, movePipelines.length]);
```

### 3d — Load stages when pipeline is selected

- [ ] **Step 4: Add a useEffect right after the pipeline loader**

```typescript
// Load stages when a pipeline is selected in step 4
useEffect(() => {
  if (!movePipelineId) {
    setMoveStages([]);
    setMoveStageId("");
    return;
  }
  setLoadingMoveStages(true);
  fetch(`/api/pipelines/${movePipelineId}/stages`)
    .then((r) => r.json())
    .then((d) => setMoveStages(Array.isArray(d) ? d : []))
    .catch(() => setMoveStages([]))
    .finally(() => setLoadingMoveStages(false));
}, [movePipelineId]);
```

### 3e — Update STEPS and canAdvance

- [ ] **Step 5: Update the STEPS constant (currently line ~48)**

From:
```typescript
const STEPS = ["Configuração", "Template", "Leads", "Revisão"] as const;
```

To:
```typescript
const STEPS = ["Configuração", "Template", "Leads", "Ação", "Revisão"] as const;
```

- [ ] **Step 6: Add `canGoToStep5` and update `canAdvance` (currently around line 354)**

Add after `canGoToStep4`:
```typescript
const canGoToStep5 =
  moveAction === "none" || (moveAction === "move" && moveStageId !== "");
```

Update `canAdvance`:
```typescript
const canAdvance =
  step === 1 ? canGoToStep2 :
  step === 2 ? canGoToStep3 :
  step === 3 ? canGoToStep4 :
  step === 4 ? canGoToStep5 :
  true;
```

- [ ] **Step 7: Update the footer button condition (currently `step < 4` and `step === 4`)**

From:
```typescript
{step < 4 ? (
  <button onClick={() => setStep(step + 1)} ...>Próximo</button>
) : (
  <button onClick={handleCreate} ...>Criar Disparo</button>
)}
```

To:
```typescript
{step < 5 ? (
  <button onClick={() => setStep(step + 1)} ...>Próximo</button>
) : (
  <button onClick={handleCreate} ...>Criar Disparo</button>
)}
```

### 3f — Step 4 render block

- [ ] **Step 8: Add the step 4 render block after the step 3 block (before the step 4/Revisão block)**

```tsx
{/* ════════════════════════════════════════════════════════════════
    STEP 4 — Ação pós-disparo
════════════════════════════════════════════════════════════════ */}
{step === 4 && (
  <div className="space-y-4">
    <div>
      <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
        Ação pós-disparo
      </label>
      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="move-action"
            value="none"
            checked={moveAction === "none"}
            onChange={() => {
              setMoveAction("none");
              setMovePipelineId("");
              setMoveStageId("");
            }}
            className="accent-[#111111]"
          />
          <span className="text-[14px] text-[#111111]">Não mover leads</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="move-action"
            value="move"
            checked={moveAction === "move"}
            onChange={() => setMoveAction("move")}
            className="accent-[#111111]"
          />
          <span className="text-[14px] text-[#111111]">Mover para etapa do Kanban</span>
        </label>
      </div>
    </div>

    {moveAction === "move" && (
      <div className="space-y-3 pl-6">
        <div>
          <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
            Funil
          </label>
          {loadingMovePipelines ? (
            <div className="text-[13px] text-[#7b7b78]">Carregando funis...</div>
          ) : (
            <select
              value={movePipelineId}
              onChange={(e) => {
                setMovePipelineId(e.target.value);
                setMoveStageId("");
              }}
              className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            >
              <option value="">Selecionar funil...</option>
              {movePipelines.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
        </div>

        {movePipelineId && (
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
              Etapa de destino
            </label>
            {loadingMoveStages ? (
              <div className="text-[13px] text-[#7b7b78]">Carregando etapas...</div>
            ) : (
              <select
                value={moveStageId}
                onChange={(e) => setMoveStageId(e.target.value)}
                className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              >
                <option value="">Selecionar etapa...</option>
                {moveStages.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            )}
          </div>
        )}

        {moveAction === "move" && moveStageId && (
          <p className="text-[12px] text-[#7b7b78]">
            Os deals dos leads disparados com sucesso serão movidos para esta etapa.
          </p>
        )}
      </div>
    )}
  </div>
)}
```

### 3g — Update Revisão step (was step 4, now step 5)

- [ ] **Step 9: Change `step === 4` to `step === 5` on the Revisão render block**

The existing JSX condition:
```tsx
{step === 4 && (
  <div className="space-y-3">
    <h3 ...>Revisão do disparo</h3>
    ...
```

Change to:
```tsx
{step === 5 && (
  <div className="space-y-3">
    <h3 ...>Revisão do disparo</h3>
    ...
```

- [ ] **Step 10: Add "Ação pós-disparo" line to the Revisão summary, after the "Agente" line**

```tsx
<p>
  <span className="text-[#7b7b78]">Ação pós-disparo:</span>{" "}
  <span className="text-[#111111]">
    {moveAction === "none"
      ? "Não mover leads"
      : moveStageId
      ? `Mover para "${moveStages.find((s) => s.id === moveStageId)?.label ?? "—"}" (${movePipelines.find((p) => p.id === movePipelineId)?.name ?? "—"})`
      : "—"}
  </span>
</p>
```

### 3h — Update handleCreate to send move_to_stage_id

- [ ] **Step 11: In `handleCreate`, add `move_to_stage_id` to the POST body**

Find the existing `fetch("/api/broadcasts", { method: "POST", ... })` call and add one field:
```typescript
move_to_stage_id: moveAction === "move" && moveStageId ? moveStageId : null,
```

Full updated body (inside `JSON.stringify({...})`):
```typescript
{
  name,
  channel_id: channelId || null,
  template_name: selectedTemplate.name,
  template_language_code: selectedTemplate.language,
  template_variables: Object.keys(templateVarValues).length ? templateVarValues : null,
  agent_profile_id: agentProfileId || null,
  move_to_stage_id: moveAction === "move" && moveStageId ? moveStageId : null,
  send_interval_min: intervalMin,
  send_interval_max: intervalMax,
  status: "draft",
}
```

### 3i — Update resetForm

- [ ] **Step 12: Add the new state resets to `resetForm`**

Add after `setCsvFile(null);`:
```typescript
setMoveAction("none");
setMovePipelineId("");
setMoveStageId("");
setMovePipelines([]);
setMoveStages([]);
```

### 3j — Commit

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(broadcast): adicionar passo Ação pós-disparo no wizard"
```

---

## Task 4: Backend worker — move deals after successful send

**Files:**
- Modify: `backend/app/broadcast/worker.py`

- [ ] **Step 1: Read `backend/app/broadcast/worker.py` lines 209–260 to understand the send loop**

The relevant section is inside `process_single_broadcast`, right after:
```python
mark_broadcast_lead_sent(bl["id"])
increment_broadcast_sent(broadcast_id)
```

- [ ] **Step 2: Add deal-move logic after `increment_broadcast_sent`, still inside the `try` block**

Add immediately after `increment_broadcast_sent(broadcast_id)`:

```python
# Move lead's deal to configured Kanban stage if set
move_to_stage_id = broadcast.get("move_to_stage_id")
if move_to_stage_id:
    try:
        stage_row = (
            sb.table("pipeline_stages")
            .select("pipeline_id")
            .eq("id", move_to_stage_id)
            .limit(1)
            .execute()
        )
        if stage_row.data:
            target_pipeline_id = stage_row.data[0]["pipeline_id"]
            sb.table("deals").update({
                "stage_id": move_to_stage_id,
                "pipeline_id": target_pipeline_id,
            }).eq("lead_id", lead["id"]).eq("pipeline_id", target_pipeline_id).execute()
            logger.info(
                "[BROADCAST] Moved deals for lead %s to stage %s",
                lead["id"], move_to_stage_id,
            )
    except Exception as move_err:
        logger.warning(
            "[BROADCAST] Failed to move deal for lead %s: %s",
            lead["id"], move_err,
        )
```

Full context of the section after the edit (for reference):

```python
mark_broadcast_lead_sent(bl["id"])
increment_broadcast_sent(broadcast_id)

# Move lead's deal to configured Kanban stage if set
move_to_stage_id = broadcast.get("move_to_stage_id")
if move_to_stage_id:
    try:
        stage_row = (
            sb.table("pipeline_stages")
            .select("pipeline_id")
            .eq("id", move_to_stage_id)
            .limit(1)
            .execute()
        )
        if stage_row.data:
            target_pipeline_id = stage_row.data[0]["pipeline_id"]
            sb.table("deals").update({
                "stage_id": move_to_stage_id,
                "pipeline_id": target_pipeline_id,
            }).eq("lead_id", lead["id"]).eq("pipeline_id", target_pipeline_id).execute()
            logger.info(
                "[BROADCAST] Moved deals for lead %s to stage %s",
                lead["id"], move_to_stage_id,
            )
    except Exception as move_err:
        logger.warning(
            "[BROADCAST] Failed to move deal for lead %s: %s",
            lead["id"], move_err,
        )

# Always record conversation and persist outbound message
conversation = None
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "feat(broadcast): mover deals no Kanban após envio bem-sucedido"
```

---

## Task 5: Final verification

- [ ] **Step 1: Build check (frontend)**

```bash
cd frontend && npm run build
```

Expected: exits 0, no TypeScript errors.

- [ ] **Step 2: Manual test — happy path**

1. Abrir modal "Novo Disparo"
2. Passo 1: preencher nome e canal → Próximo
3. Passo 2: selecionar template → Próximo
4. Passo 3: selecionar leads → Próximo
5. Passo 4: selecionar "Mover para etapa do Kanban" → escolher funil → escolher etapa → Próximo
6. Passo 5 (Revisão): confirmar que "Ação pós-disparo" aparece com o funil e etapa escolhidos
7. Clicar "Criar Disparo" → broadcast criado
8. No Supabase, verificar que `broadcasts.move_to_stage_id` foi salvo

- [ ] **Step 3: Manual test — skip path**

1. Criar disparo com "Não mover leads" → confirmar que `move_to_stage_id` é `null` no Supabase

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "chore: verificação final broadcast post-dispatch move"
```
