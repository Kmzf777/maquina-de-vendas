# Scheduled Broadcasts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Frontend tasks (Tasks 3, 4, 5) MUST invoke the `frontend-design` skill before writing any UI code.**

**Goal:** Permitir que disparos sejam agendados para executar automaticamente em uma data/hora no Horário de Brasília (BRT, UTC-3), com suporte a agendar durante criação ou após, reagendar e cancelar agendamento.

**Architecture:** O worker loop existente (5s tick) ganha uma nova função `process_scheduled_broadcasts()` que detecta broadcasts com `status='scheduled'` e `scheduled_at <= now()` e os inicia automaticamente. O campo `scheduled_at` e o status `'scheduled'` já existem no banco. O frontend ganha um step de agendamento no modal de criação e ações de agendar/reagendar/cancelar na página de detalhes.

**Tech Stack:** Python/FastAPI (backend), Next.js App Router com TypeScript (frontend), Supabase/Postgres (banco), Tailwind CSS (estilo)

---

## Mapa de arquivos

| Arquivo | Tipo | O que muda |
|---|---|---|
| `backend/app/broadcast/worker.py` | Modify | Nova função `process_scheduled_broadcasts()` + chamada no loop |
| `backend/app/broadcast/router.py` | Modify | PATCH: status transitions; DELETE: permite 'scheduled' |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Modify | Step 5 "Agendamento", state, BRT→UTC, payload |
| `frontend/src/components/campaigns/broadcast-detail.tsx` | Modify | UI de agendar/reagendar/cancelar + exibição do horário |
| `frontend/src/components/campaigns/broadcast-card.tsx` | Modify | Exibir horário agendado no card |

---

## Task 1: Backend — process_scheduled_broadcasts()

**Files:**
- Modify: `backend/app/broadcast/worker.py` (função após linha 286, chamada na linha 274)

- [ ] **Step 1: Adicionar a função `process_scheduled_broadcasts()`**

Abrir `backend/app/broadcast/worker.py`. Após a função `process_broadcasts()` (que começa na linha 288), adicionar:

```python
async def process_scheduled_broadcasts():
    """Auto-inicia broadcasts cujo scheduled_at já passou."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    broadcasts = (
        sb.table("broadcasts")
        .select("id, name")
        .eq("status", "scheduled")
        .eq("env_tag", _ENV_TAG)
        .lte("scheduled_at", now)
        .execute()
        .data
    )
    for broadcast in broadcasts:
        broadcast_id = broadcast["id"]
        pending_count = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        ) or 0
        if not pending_count:
            logger.error(
                f"[SCHEDULER] broadcast {broadcast_id} sem leads pendentes — marcando como failed"
            )
            sb.table("broadcasts").update({"status": "failed"}).eq("id", broadcast_id).execute()
            continue
        sb.table("broadcasts").update({"status": "running"}).eq("id", broadcast_id).execute()
        logger.info(
            f"[SCHEDULER] broadcast {broadcast_id} ({broadcast.get('name')}) "
            f"iniciado automaticamente — {pending_count} leads"
        )
```

- [ ] **Step 2: Chamar a função no loop principal**

No `run_worker()` (linha ~271), adicionar `await process_scheduled_broadcasts()` como **primeira chamada**, antes de `await process_broadcasts()`:

```python
async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and stagnation triggers."""
    logger.info("Broadcast + Cadence worker started")

    while True:
        try:
            from app.campaigns.worker import check_campaign_triggers, process_campaign_enrollments
            await process_scheduled_broadcasts()   # ← NOVO (primeira chamada)
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
            await process_due_followups()
            await check_campaign_triggers()
            await process_campaign_enrollments()
            reconcile_broadcast_replies()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)
```

- [ ] **Step 3: Verificar manualmente**

Criar um broadcast com `status='scheduled'` e `scheduled_at` 1 minuto no futuro direto no Supabase. Aguardar o tempo passar. Conferir nos logs do worker que aparece a linha `[SCHEDULER] broadcast ... iniciado automaticamente`. Conferir que o status mudou para `'running'` no banco.

- [ ] **Step 4: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "feat(broadcast): auto-iniciar broadcasts agendados no worker loop"
```

---

## Task 2: Backend — Atualizações no router.py

**Files:**
- Modify: `backend/app/broadcast/router.py` (linhas 69-85)

- [ ] **Step 1: Atualizar endpoint PATCH para gerenciar transições de status**

Substituir o corpo do `update_broadcast` (linhas 69-75) por:

```python
@router.patch("/{broadcast_id}")
async def update_broadcast(broadcast_id: str, body: dict):
    sb = get_supabase()
    from datetime import datetime, timezone

    if "scheduled_at" in body:
        current = (
            sb.table("broadcasts")
            .select("status")
            .eq("id", broadcast_id)
            .single()
            .execute()
            .data
        )
        current_status = current["status"]
        if body["scheduled_at"] is None:
            if current_status == "scheduled":
                body["status"] = "draft"
        else:
            if current_status in ("draft", "scheduled"):
                body["status"] = "scheduled"

    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("broadcasts").update(body).eq("id", broadcast_id).execute()
    return result.data[0]
```

- [ ] **Step 2: Atualizar DELETE para permitir exclusão de broadcasts agendados**

Localizar (linha ~82):
```python
    if broadcast["status"] not in ("draft", "completed"):
        raise HTTPException(400, "Apenas disparos em rascunho ou completos podem ser excluidos")
```

Substituir por:
```python
    if broadcast["status"] not in ("draft", "scheduled", "completed"):
        raise HTTPException(400, "Apenas disparos em rascunho, agendados ou completos podem ser excluidos")
```

- [ ] **Step 3: Verificar manualmente**

Usando curl ou Postman/Thunder Client:

```bash
# Agendar um broadcast draft
curl -X PATCH http://localhost:8000/api/broadcasts/<id> \
  -H "Content-Type: application/json" \
  -d '{"scheduled_at": "2026-12-31T18:00:00Z"}'
# Esperado: status="scheduled" no retorno

# Cancelar agendamento
curl -X PATCH http://localhost:8000/api/broadcasts/<id> \
  -H "Content-Type: application/json" \
  -d '{"scheduled_at": null}'
# Esperado: status="draft" no retorno

# Deletar broadcast agendado
curl -X DELETE http://localhost:8000/api/broadcasts/<id>
# Esperado: {"ok": true}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/broadcast/router.py
git commit -m "feat(broadcast): PATCH gerencia status scheduled, DELETE aceita scheduled"
```

---

## Task 3: Frontend — Step de Agendamento no Modal de Criação

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

> **OBRIGATÓRIO: invocar a skill `frontend-design` antes de escrever qualquer código UI nesta task.**

- [ ] **Step 1: Invocar skill frontend-design**

Invocar a skill `frontend-design` antes de prosseguir com qualquer código de UI.

- [ ] **Step 2: Adicionar "Agendamento" ao array STEPS**

Localizar na linha 41:
```typescript
const STEPS = ["Configuração", "Template", "Leads", "Ação", "Revisão"] as const;
```

Substituir por:
```typescript
const STEPS = ["Configuração", "Template", "Leads", "Ação", "Agendamento", "Revisão"] as const;
```

- [ ] **Step 3: Adicionar state de agendamento (após o state do Step 4, ~linha 104)**

Após o bloco `// ── Step 4: Post-dispatch action`, adicionar:

```typescript
  // ── Step 5: Scheduling ────────────────────────────────────────────────────
  const [scheduleMode, setScheduleMode] = useState<"immediate" | "scheduled">("immediate");
  const [scheduleDate, setScheduleDate] = useState(""); // YYYY-MM-DD
  const [scheduleTime, setScheduleTime] = useState(""); // HH:MM
```

- [ ] **Step 4: Adicionar helper BRT→UTC e validações**

Após o bloco de state (antes da linha `const resetForm`), adicionar:

```typescript
  const brtToUtcIso = (date: string, time: string): string => {
    const [year, month, day] = date.split("-").map(Number);
    const [hour, minute] = time.split(":").map(Number);
    // BRT = UTC-3, adiciona 3h para obter UTC
    return new Date(Date.UTC(year, month - 1, day, hour + 3, minute)).toISOString();
  };

  const scheduleIsValid = (): boolean => {
    if (scheduleMode === "immediate") return true;
    if (!scheduleDate || !scheduleTime) return false;
    const utcIso = brtToUtcIso(scheduleDate, scheduleTime);
    return new Date(utcIso) > new Date();
  };
```

- [ ] **Step 5: Adicionar `canGoToStep6` e atualizar `canAdvance`**

Localizar (~linha 428):
```typescript
  const canGoToStep5 =
    moveAction === "none" || (moveAction === "move" && moveStageId !== "");

  const canAdvance =
    step === 1 ? canGoToStep2 :
    step === 2 ? canGoToStep3 :
    step === 3 ? canGoToStep4 :
    step === 4 ? canGoToStep5 :
    true;
```

Substituir por:
```typescript
  const canGoToStep5 =
    moveAction === "none" || (moveAction === "move" && moveStageId !== "");
  const canGoToStep6 = scheduleIsValid();

  const canAdvance =
    step === 1 ? canGoToStep2 :
    step === 2 ? canGoToStep3 :
    step === 3 ? canGoToStep4 :
    step === 4 ? canGoToStep5 :
    step === 5 ? canGoToStep6 :
    true;
```

- [ ] **Step 6: Atualizar `resetForm` para resetar state de agendamento**

Dentro de `resetForm()`, adicionar ao final do bloco:
```typescript
    setScheduleMode("immediate");
    setScheduleDate("");
    setScheduleTime("");
```

- [ ] **Step 7: Atualizar `handleCreate` para incluir `scheduled_at`**

Localizar dentro de `handleCreate` (~linha 349) o `body: JSON.stringify({...})`. Remover `status: "draft"` (o backend determina o status com base em `scheduled_at`) e adicionar `scheduled_at`:

```typescript
      body: JSON.stringify({
        name,
        channel_id: channelId || null,
        template_name: selectedTemplate.name,
        template_language_code: selectedTemplate.language,
        template_variables: Object.keys(templateVarValues).length ? templateVarValues : null,
        agent_profile_id: agentProfileId || null,
        send_interval_min: intervalMin,
        send_interval_max: intervalMax,
        move_to_stage_id: moveAction === "move" && moveStageId ? moveStageId : null,
        scheduled_at:
          scheduleMode === "scheduled" && scheduleDate && scheduleTime
            ? brtToUtcIso(scheduleDate, scheduleTime)
            : null,
      }),
```

- [ ] **Step 8: Adicionar o JSX do Step 5 (Agendamento)**

No bloco de body do modal, localizar onde está o Step 4 e logo após seu `})}` de fechamento, antes do Step 5 atual (Revisão), adicionar:

```tsx
            {/* ════════════════════════════════════════════════════════════════
                STEP 5 — Agendamento
            ════════════════════════════════════════════════════════════════ */}
            {step === 5 && (
              <div className="space-y-5">
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Quando disparar?
                  </label>
                  <div className="space-y-2">
                    {(
                      [
                        { value: "immediate" as const, label: "Iniciar imediatamente" },
                        { value: "scheduled" as const, label: "Agendar para depois" },
                      ]
                    ).map(({ value, label }) => (
                      <label key={value} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="schedule-mode"
                          value={value}
                          checked={scheduleMode === value}
                          onChange={() => setScheduleMode(value)}
                          className="accent-[#111111]"
                        />
                        <span className="text-[14px] text-[#111111]">{label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {scheduleMode === "scheduled" && (
                  <div className="bg-[#f0ede8] border border-[#dedbd6] rounded-[8px] p-4 space-y-4">
                    <p className="text-[12px] text-[#7b7b78] flex items-center gap-1">
                      🕐 <span>Horário de Brasília (UTC−3)</span>
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                          Data
                        </label>
                        <input
                          type="date"
                          value={scheduleDate}
                          min={new Date().toISOString().slice(0, 10)}
                          onChange={(e) => setScheduleDate(e.target.value)}
                          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                          Horário (BRT)
                        </label>
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        />
                      </div>
                    </div>
                    {scheduleDate && scheduleTime && !scheduleIsValid() && (
                      <p className="text-[12px] text-[#c41c1c]">
                        A data/hora deve ser no futuro.
                      </p>
                    )}
                    {scheduleDate && scheduleTime && scheduleIsValid() && (
                      <p className="text-[12px] text-[#0bdf50]">
                        Disparo agendado para{" "}
                        {new Date(brtToUtcIso(scheduleDate, scheduleTime)).toLocaleString("pt-BR", {
                          timeZone: "America/Sao_Paulo",
                          dateStyle: "short",
                          timeStyle: "short",
                        })}{" "}
                        (Horário de Brasília)
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
```

- [ ] **Step 9: Atualizar o Step da Revisão (era step 5, agora é step 6)**

Localizar `{step === 5 && (` no bloco de Revisão e alterar para `{step === 6 && (`.

Também localizar no footer do modal onde o botão "Criar" aparece. Ele provavelmente tem condição `step === 5` (último step). Atualizar para `step === 6`.

- [ ] **Step 10: Verificar no browser**

Abrir o modal de criação de broadcast. Verificar:
1. Os 6 steps aparecem corretamente no stepper
2. Step 5 "Agendamento" mostra as opções "Iniciar imediatamente" / "Agendar para depois"
3. Ao escolher "Agendar para depois", o picker de data/hora aparece
4. Validação de data passada funciona (mensagem vermelha)
5. Data futura válida mostra confirmação verde
6. Criar com "Iniciar imediatamente": broadcast criado com `status='draft'`
7. Criar com data futura: broadcast criado com `status='scheduled'`

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(broadcast): step de agendamento BRT no modal de criação"
```

---

## Task 4: Frontend — Scheduling UI no broadcast-detail.tsx

**Files:**
- Modify: `frontend/src/components/campaigns/broadcast-detail.tsx`

> **OBRIGATÓRIO: invocar a skill `frontend-design` antes de escrever qualquer código UI nesta task.**

- [ ] **Step 1: Invocar skill frontend-design**

Invocar a skill `frontend-design` antes de prosseguir.

- [ ] **Step 2: Adicionar state de agendamento inline**

Após os estados existentes (~linha 56), adicionar:

```typescript
  const [showSchedulePicker, setShowSchedulePicker] = useState(false);
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [scheduleLoading, setScheduleLoading] = useState(false);
```

- [ ] **Step 3: Adicionar helpers de timezone**

Antes do `return` principal (~linha 200), adicionar:

```typescript
  const brtToUtcIso = (date: string, time: string): string => {
    const [year, month, day] = date.split("-").map(Number);
    const [hour, minute] = time.split(":").map(Number);
    return new Date(Date.UTC(year, month - 1, day, hour + 3, minute)).toISOString();
  };

  const formatScheduledAtBrt = (isoStr: string): string =>
    new Date(isoStr).toLocaleString("pt-BR", {
      timeZone: "America/Sao_Paulo",
      dateStyle: "short",
      timeStyle: "short",
    });

  const schedulePickerValid = (): boolean => {
    if (!scheduleDate || !scheduleTime) return false;
    return new Date(brtToUtcIso(scheduleDate, scheduleTime)) > new Date();
  };
```

- [ ] **Step 4: Adicionar handlers de agendamento**

Após `handleDelete` (~linha 198), adicionar:

```typescript
  const handleScheduleApply = async () => {
    if (!broadcast || !schedulePickerValid() || scheduleLoading) return;
    setScheduleLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduled_at: brtToUtcIso(scheduleDate, scheduleTime) }),
      });
      const updated = await res.json();
      setBroadcast({ ...broadcast, status: updated.status, scheduled_at: updated.scheduled_at });
      setShowSchedulePicker(false);
      setScheduleDate("");
      setScheduleTime("");
    } finally {
      setScheduleLoading(false);
    }
  };

  const handleCancelSchedule = async () => {
    if (!broadcast || scheduleLoading) return;
    if (!confirm("Cancelar o agendamento? O disparo voltará para rascunho.")) return;
    setScheduleLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduled_at: null }),
      });
      const updated = await res.json();
      setBroadcast({ ...broadcast, status: updated.status, scheduled_at: null });
      setShowSchedulePicker(false);
    } finally {
      setScheduleLoading(false);
    }
  };
```

- [ ] **Step 5: Atualizar o bloco de Action buttons para status 'draft' e 'scheduled'**

Localizar o bloco `{broadcast.status === "draft" && (` (~linha 287). Substituir por:

```tsx
          {broadcast.status === "draft" && (
            <>
              <button
                onClick={handleStart}
                disabled={actionLoading}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                ▶ Iniciar
              </button>
              <button
                onClick={() => { setShowSchedulePicker(true); setScheduleDate(""); setScheduleTime(""); }}
                disabled={actionLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                🕐 Agendar
              </button>
              <button
                onClick={handleDelete}
                disabled={actionLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Excluir
              </button>
            </>
          )}
          {broadcast.status === "scheduled" && broadcast.scheduled_at && (
            <>
              <span className="text-[13px] text-[#7b7b78] flex items-center gap-1">
                🕐 {formatScheduledAtBrt(broadcast.scheduled_at)}{" "}
                <span className="text-[11px]">(Horário de Brasília)</span>
              </span>
              <button
                onClick={() => {
                  const d = new Date(broadcast.scheduled_at!);
                  const brt = new Date(d.getTime() - 3 * 60 * 60 * 1000);
                  setScheduleDate(brt.toISOString().slice(0, 10));
                  setScheduleTime(brt.toISOString().slice(11, 16));
                  setShowSchedulePicker(true);
                }}
                disabled={scheduleLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Reagendar
              </button>
              <button
                onClick={handleCancelSchedule}
                disabled={scheduleLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Cancelar agendamento
              </button>
            </>
          )}
```

- [ ] **Step 6: Adicionar o painel inline de date/time picker**

Logo após o fechamento do `</div>` do header (após a div das action buttons, antes de `{/* Main content */}`), adicionar:

```tsx
      {/* Schedule picker inline panel */}
      {showSchedulePicker && (
        <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-8 py-4 flex-shrink-0">
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Data
              </label>
              <input
                type="date"
                value={scheduleDate}
                min={new Date().toISOString().slice(0, 10)}
                onChange={(e) => setScheduleDate(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Horário (Horário de Brasília)
              </label>
              <input
                type="time"
                value={scheduleTime}
                onChange={(e) => setScheduleTime(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <button
              onClick={handleScheduleApply}
              disabled={!schedulePickerValid() || scheduleLoading}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40"
            >
              {scheduleLoading ? "Salvando..." : "Confirmar"}
            </button>
            <button
              onClick={() => setShowSchedulePicker(false)}
              className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
            >
              Cancelar
            </button>
            {scheduleDate && scheduleTime && !schedulePickerValid() && (
              <span className="text-[12px] text-[#c41c1c]">Data/hora deve ser no futuro.</span>
            )}
          </div>
        </div>
      )}
```

- [ ] **Step 7: Verificar no browser**

Abrir a página de detalhes de um broadcast em `status='draft'`:
1. Deve aparecer botão "🕐 Agendar" ao lado de "▶ Iniciar"
2. Clicar em "Agendar" → painel inline aparece abaixo do header
3. Preencher data/hora futura → botão "Confirmar" ativo
4. Confirmar → status muda para "Agendado", horário aparece no header
5. Com status "Agendado": botões "Reagendar" e "Cancelar agendamento" visíveis
6. "Reagendar" → painel abre preenchido com o horário atual (em BRT)
7. "Cancelar agendamento" → confirm → volta para "Rascunho"

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/campaigns/broadcast-detail.tsx
git commit -m "feat(broadcast): UI de agendar/reagendar/cancelar na página de detalhes"
```

---

## Task 5: Frontend — Horário agendado no broadcast-card.tsx

**Files:**
- Modify: `frontend/src/components/campaigns/broadcast-card.tsx`

> **OBRIGATÓRIO: invocar a skill `frontend-design` antes de escrever qualquer código UI nesta task.**

- [ ] **Step 1: Invocar skill frontend-design**

Invocar a skill `frontend-design` antes de prosseguir.

- [ ] **Step 2: Adicionar exibição do horário no card**

No `BroadcastCard`, a prop `broadcast` já tem `scheduled_at` (tipo `Broadcast` de `@/lib/types`). No JSX, localizar o bloco `<h3>` com o nome do broadcast (~linha 41). Após o `<p>` com `broadcast.template_name`, adicionar:

```tsx
          {broadcast.status === "scheduled" && broadcast.scheduled_at && (
            <p className="text-[12px] text-[#65b5ff] mt-0.5">
              🕐{" "}
              {new Date(broadcast.scheduled_at).toLocaleString("pt-BR", {
                timeZone: "America/Sao_Paulo",
                dateStyle: "short",
                timeStyle: "short",
              })}{" "}
              <span className="text-[#7b7b78]">(BRT)</span>
            </p>
          )}
```

- [ ] **Step 3: Verificar no browser**

Na lista de broadcasts, um broadcast com status "Agendado" deve mostrar abaixo do nome a data/hora no formato `21/05/2026, 15:00 (BRT)`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/campaigns/broadcast-card.tsx
git commit -m "feat(broadcast): exibir horário agendado no card de broadcast"
```

---

## Self-review

**Spec coverage:**
- ✅ Auto-start pelo worker (Task 1)
- ✅ Agendar na criação — step 5 no modal (Task 3)
- ✅ Agendar após criação — botão "Agendar" em detail (Task 4)
- ✅ Cancelar agendamento — botão "Cancelar agendamento" em detail (Task 4)
- ✅ Reagendar — botão "Reagendar" em detail (Task 4)
- ✅ BRT sempre, label explícito (Tasks 3, 4, 5)
- ✅ DELETE aceita 'scheduled' (Task 2)
- ✅ Card mostra horário (Task 5)
- ✅ Erro: broadcast sem leads → marca como 'failed' (Task 1)
- ✅ Erro: data passada → validação client-side bloqueia (Tasks 3, 4)
- ✅ Crash recovery: worker reinicia → `process_scheduled_broadcasts()` repega broadcasts ainda 'scheduled' (comportamento natural do loop)

**Placeholders:** Nenhum encontrado.

**Type consistency:** `Broadcast.scheduled_at: string | null` já existe em `frontend/src/lib/types.ts` (linha 142) — nenhuma mudança de tipo necessária. Todos os handlers usam `broadcast.scheduled_at` consistentemente.
