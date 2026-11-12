# Envio do CRM pelo wa_id + motivo da falha — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** As rotas de envio do CRM mandam para o endereço WhatsApp entregável do lead (`wa_id`), e toda mensagem que a Meta recusar mostra o motivo na bolha.

**Architecture:** Helper TS `resolveSendTarget` espelha o `resolve_send_target` do backend e é usado nas 4 rotas Meta do CRM. O webhook de status grava `messages.metadata.delivery_error` em `failed`. A bolha lê esse campo via `deliveryErrorText` e mostra uma linha vermelha. Um SQL único preenche falhas antigas a partir de `meta_webhook_logs`.

**Tech Stack:** Next.js App Router + vitest (frontend), FastAPI + pytest + supabase-py (backend), Postgres.

Spec: `docs/superpowers/specs/2026-11-06-envio-crm-wa-id-motivo-falha-design.md`.

Trabalhe sempre no worktree `C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\.claude\worktrees\agente-7c6b70e7` (branch `agente/7c6b70e7`). Não faça push. Não toque em caminhos Evolution (CLAUDE.md §6).

---

## Task 1: Envio pelo endereço entregável (frontend)

**Files:**
- Create: `frontend/src/lib/whatsapp/send-target.ts`
- Create: `frontend/src/lib/whatsapp/send-target.test.ts`
- Modify: `frontend/src/app/api/conversations/[id]/send/route.ts` (select do lead + `sendViaMeta(..., lead.phone, ...)` no ramo `meta_cloud`)
- Modify: `frontend/src/app/api/conversations/[id]/send-media/route.ts` (select + `to: lead.phone`)
- Modify: `frontend/src/app/api/conversations/[id]/react/route.ts` (select + `to: lead.phone`)
- Modify: `frontend/src/app/api/conversations/[id]/send-template/route.ts` (select + `lead.phone` no envio)
- Create: `frontend/src/app/api/conversations/[id]/send/route.test.ts`
- Modify: `frontend/src/app/api/conversations/[id]/send-template/route.test.ts`
- Create: `frontend/src/app/api/conversations/[id]/send-media/route.test.ts`, `frontend/src/app/api/conversations/[id]/react/route.test.ts`

- [ ] **Step 1: Teste do helper (falha)**

```ts
// frontend/src/lib/whatsapp/send-target.test.ts
import { describe, expect, it } from "vitest";
import { resolveSendTarget, LEAD_SEND_FIELDS } from "./send-target";

const carolaine = {
  phone: "5537932140027",
  wa_id: "553732140027",
  wa_id_confirmed_at: "2026-09-23T14:29:31Z",
  last_customer_message_at: null,
  bsuid: null,
};

describe("resolveSendTarget", () => {
  it("prefere o wa_id real (número fixo sem o 9) ao phone normalizado", () => {
    expect(resolveSendTarget(carolaine)).toBe("553732140027");
  });
  it("sem wa_id usa o phone", () => {
    expect(resolveSendTarget({ ...carolaine, wa_id: null })).toBe("5537932140027");
  });
  it("sem wa_id e sem phone usa o bsuid", () => {
    expect(resolveSendTarget({ phone: null, wa_id: null, bsuid: "BR.123" })).toBe("BR.123");
  });
  it("caminho frio: wa_id sem procedência é ignorado", () => {
    const semProc = { ...carolaine, wa_id_confirmed_at: null, last_customer_message_at: null };
    expect(resolveSendTarget(semProc, { requireInboundProvenance: true })).toBe("5537932140027");
  });
  it("caminho frio: wa_id com procedência é usado", () => {
    expect(resolveSendTarget(carolaine, { requireInboundProvenance: true })).toBe("553732140027");
    const viaInbound = { ...carolaine, wa_id_confirmed_at: null, last_customer_message_at: "2026-11-06T17:58:12Z" };
    expect(resolveSendTarget(viaInbound, { requireInboundProvenance: true })).toBe("553732140027");
  });
  it("lead nulo devolve string vazia", () => {
    expect(resolveSendTarget(null)).toBe("");
  });
  it("LEAD_SEND_FIELDS traz as colunas que o helper lê", () => {
    for (const c of ["phone", "wa_id", "wa_id_confirmed_at", "last_customer_message_at", "bsuid"]) {
      expect(LEAD_SEND_FIELDS).toContain(c);
    }
  });
});
```

Run: `cd frontend && npx vitest run src/lib/whatsapp/send-target.test.ts` → FAIL (módulo não existe).

- [ ] **Step 2: Implementar o helper**

```ts
// frontend/src/lib/whatsapp/send-target.ts
/**
 * Endereço WhatsApp ENTREGÁVEL do lead — espelho de `resolve_send_target`
 * (backend/app/leads/service.py). Manter os dois iguais.
 *
 * `leads.phone` é normalizado e ganha o 9º dígito; números fixos (e alguns celulares
 * antigos) estão registrados na Meta SEM ele. Enviar para o `phone` faz a Meta aceitar
 * (HTTP 200 + wamid) e depois falhar com 131026 "Message undeliverable" — o caso da
 * Carolaine/MVX (phone 5537932140027, wa_id 553732140027), 06/11/2026.
 *
 * `requireInboundProvenance` (caminho frio, ex.: modelo como 1º contato): o wa_id só
 * vale se o lead já provou tráfego (wa_id_confirmed_at ou last_customer_message_at).
 */
export interface SendTargetLead {
  phone?: string | null;
  wa_id?: string | null;
  wa_id_confirmed_at?: string | null;
  last_customer_message_at?: string | null;
  bsuid?: string | null;
}

/** Colunas de `leads` que o helper precisa — use no select embutido das rotas. */
export const LEAD_SEND_FIELDS = "phone, wa_id, wa_id_confirmed_at, last_customer_message_at, bsuid";

export function hasWaIdProvenance(lead: SendTargetLead): boolean {
  return Boolean(lead.wa_id_confirmed_at) || Boolean(lead.last_customer_message_at);
}

export function resolveSendTarget(
  lead: SendTargetLead | null | undefined,
  opts: { requireInboundProvenance?: boolean } = {},
): string {
  if (!lead) return "";
  const waId = lead.wa_id;
  if (waId && (!opts.requireInboundProvenance || hasWaIdProvenance(lead))) return waId;
  return lead.phone || lead.bsuid || "";
}
```

Run o teste do Step 1 → PASS.

- [ ] **Step 3: Teste da rota `send` (falha)** — criar `frontend/src/app/api/conversations/[id]/send/route.test.ts` copiando o padrão de mocks de `send-template/route.test.ts` (mock de `@/lib/supabase/api` e `@/lib/supabase/lead-blocked`, Supabase falso com `select/eq/limit/update/single/maybeSingle/insert/then`). Diferenças:
  - `CONV.leads = { id: "lead-1", phone: "5537932140027", wa_id: "553732140027", wa_id_confirmed_at: "2026-09-23T14:29:31Z", last_customer_message_at: null, bsuid: null, opt_out: false }`.
  - `global.fetch = vi.fn(async (url) => ({ ok: true, status: 200, json: async () => ({ messages: [{ id: "wamid.X" }] }), text: async () => "" }))`.
  - Corpo do POST: `{ text: "Boa tarde, tudo joia?" }`.
  - Asserts: achar a chamada do fetch cuja URL contém `graph.facebook.com`; `JSON.parse(init.body).to === "553732140027"`. Segundo caso: `wa_id: null` → `to === "5537932140027"`.
  - O fetch também é chamado para `/followup/schedule` e `/read-receipt` (fire-and-forget); filtre pela URL.

Run: `npx vitest run "src/app/api/conversations/[id]/send/route.test.ts"` → FAIL (`to` = `5537932140027`).

- [ ] **Step 4: Corrigir `send/route.ts`**
  - `import { resolveSendTarget, LEAD_SEND_FIELDS } from "@/lib/whatsapp/send-target";`
  - Select: `` `*, leads(id, ${LEAD_SEND_FIELDS}, opt_out), channels(id, provider, provider_config)` ``.
  - Tipo do `lead`: `{ id: string; opt_out?: boolean | null } & SendTargetLead`.
  - Guarda: `const target = resolveSendTarget(lead); if (!channel || !lead || !target) → 400 "Invalid conversation data"`.
  - No ramo `meta_cloud`: `sendViaMeta(channel.provider_config, target, text.trim(), quoted_wamid ?? null)`. O ramo `evolution` e o bloco `evo_` ficam como estão (`lead.phone`).

Run o teste → PASS.

- [ ] **Step 5: `send-media`, `react`, `send-template`** — mesmo padrão TDD para cada rota:
  - Teste novo/atualizado que prova `to === "553732140027"` para o lead da Carolaine (ler o corpo do fetch para graph.facebook.com; em `send-media` o upload também chama graph — filtre pela chamada a `/messages`).
  - `send-template`: usar `resolveSendTarget(lead, { requireInboundProvenance: true })`. Dois testes: com `wa_id_confirmed_at` → `553732140027`; com `wa_id` mas sem `wa_id_confirmed_at` e sem `last_customer_message_at` → `5537932140027`. Manter os testes existentes passando (o `CONV` deles tem só `phone` → continua enviando para o phone).
  - Trocar o select para incluir `LEAD_SEND_FIELDS` e o envio para o `target`. Não mexer em caminhos `provider === "evolution"`.

Run: `cd frontend && npx vitest run src/app/api/conversations src/lib/whatsapp` → PASS.

- [ ] **Step 6: Type-check e commit**

Run: `cd frontend && npx tsc --noEmit` → sem erros.

```bash
git add frontend/src/lib/whatsapp frontend/src/app/api/conversations
git commit -m "fix(envio-crm): CRM envia para o wa_id real do lead, nao para o phone com 9 a mais"
```

---

## Task 2: Gravar o motivo da falha + backfill (backend)

**Files:**
- Modify: `backend/app/webhook/meta_router.py` (`_handle_delivery_status`, novas funções `_record_delivery_error` / `_retry_record_delivery_error`)
- Create: `backend/tests/test_delivery_error_metadata_2026_11_06.py`
- Create: `backend/scripts/backfill_delivery_error.sql`

- [ ] **Step 1: Testes (falham)**

```python
# backend/tests/test_delivery_error_metadata_2026_11_06.py
"""Motivo da falha da Meta gravado na mensagem (cartão 7c6b70e7, 06/11/2026).

O webhook de status 'failed' traz errors[] (ex.: 131026 "Message undeliverable"), mas
só o caminho de broadcast guardava o erro. Mensagens do vendedor ficavam com o ícone
vermelho sem motivo. Agora qualquer 'failed' grava metadata.delivery_error, com merge
(sem apagar metadata.interativo etc.).
"""
from unittest.mock import MagicMock, patch

import pytest

ERR_131026 = {
    "code": 131026,
    "title": "Message undeliverable",
    "message": "Message undeliverable",
    "error_data": {"details": "Message Undeliverable."},
}


def _sb_with_row(row):
    sb = MagicMock()
    msgs = MagicMock()
    sel = msgs.select.return_value.eq.return_value.limit.return_value.execute
    sel.return_value = MagicMock(data=[row] if row else [])
    sb.table.return_value = msgs
    return sb, msgs


def test_record_delivery_error_merges_into_existing_metadata():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": {"interativo": {"tipo": "botoes"}}})
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], "1793988307") is True
    payload = msgs.update.call_args[0][0]
    md = payload["metadata"]
    assert md["interativo"] == {"tipo": "botoes"}
    assert md["delivery_error"]["code"] == 131026
    assert md["delivery_error"]["title"] == "Message undeliverable"
    assert md["delivery_error"]["details"] == "Message Undeliverable."
    assert md["delivery_error"]["at"].startswith("2026-11-06T")
    msgs.update.return_value.eq.assert_called_with("id", "m1")


def test_record_delivery_error_null_metadata():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": None})
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], None) is True
    assert msgs.update.call_args[0][0]["metadata"]["delivery_error"]["code"] == 131026


def test_record_delivery_error_row_missing_returns_false():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row(None)
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], None) is False
    msgs.update.assert_not_called()


def test_record_delivery_error_without_errors_is_noop():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": {}})
    assert _record_delivery_error(sb, "wamid.X", [], None) is True
    msgs.update.assert_not_called()


@pytest.mark.asyncio
async def test_handle_failed_records_error():
    from app.webhook import meta_router
    sb = MagicMock()
    with patch.object(meta_router, "get_supabase", return_value=sb), \
         patch.object(meta_router, "_apply_message_status", return_value=True), \
         patch.object(meta_router, "_record_delivery_error", return_value=True) as rec, \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await meta_router._handle_delivery_status("wamid.X", "failed", [ERR_131026], "5537932140027")
    rec.assert_called_once()
    assert rec.call_args[0][1] == "wamid.X"


@pytest.mark.asyncio
async def test_handle_delivered_does_not_record_error():
    from app.webhook import meta_router
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    with patch.object(meta_router, "get_supabase", return_value=sb), \
         patch.object(meta_router, "_apply_message_status", return_value=True), \
         patch.object(meta_router, "_record_delivery_error") as rec, \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await meta_router._handle_delivery_status("wamid.X", "delivered", [], "553732140027")
    rec.assert_not_called()
```

Antes de rodar, conferir se o repo usa `pytest.mark.asyncio` (grep em `backend/tests`); se usar outro padrão (ex.: `asyncio.run`), adaptar os dois testes async. Conferir também a assinatura real de `_handle_delivery_status` e como o timestamp do status chega (hoje não é passado; ver Step 3).

Run: `cd backend && python -m pytest tests/test_delivery_error_metadata_2026_11_06.py -v` → FAIL (`_record_delivery_error` não existe).

- [ ] **Step 2: Implementar `_record_delivery_error`** em `meta_router.py`, logo após `_retry_message_status`:

```python
def _record_delivery_error(sb, wamid: str, errors: list | None, timestamp: str | None) -> bool:
    """Grava o motivo da falha da Meta em messages.metadata.delivery_error (merge).

    True  → nada mais a fazer (gravou, ou não há erro para gravar).
    False → a linha ainda não existe (corrida com a persistência) — retentar.
    """
    if not errors:
        return True
    err = errors[0] or {}
    row = sb.table("messages").select("id, metadata").eq("wamid", wamid).limit(1).execute()
    if not row.data:
        return False
    try:
        at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        at = datetime.now(timezone.utc)
    metadata = dict(row.data[0].get("metadata") or {})
    metadata["delivery_error"] = {
        "code": err.get("code"),
        "title": err.get("title") or err.get("message"),
        "details": (err.get("error_data") or {}).get("details"),
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    sb.table("messages").update({"metadata": metadata}).eq("id", row.data[0]["id"]).execute()
    return True


async def _retry_record_delivery_error(wamid: str, errors: list, timestamp: str | None) -> None:
    for delay in _STATUS_RETRY_DELAYS:
        await asyncio.sleep(delay)
        try:
            if _record_delivery_error(get_supabase(), wamid, errors, timestamp):
                return
        except Exception as e:
            logger.warning("[DELIVERY] retentativa de delivery_error falhou p/ wamid=%s: %s", wamid, e)
```

- [ ] **Step 3: Ligar no handler.** `_handle_delivery_status` ganha parâmetro opcional `timestamp: str | None = None` (no fim, para não quebrar chamadas existentes). No laço de `_extract_statuses` (por volta da linha 565), passar `status_event.get("timestamp")`. Logo após o bloco `try: ... _apply_message_status ...`, e antes do bloco de prova de tráfego:

```python
    if status == "failed":
        try:
            if not _record_delivery_error(sb, wamid, errors, timestamp):
                asyncio.create_task(_retry_record_delivery_error(wamid, errors or [], timestamp))
        except Exception as e:
            logger.warning("[DELIVERY] Failed to record delivery_error for wamid=%s: %s", wamid, e)
```

(`sb` é definido dentro do `try` anterior; garanta que exista — mova `sb = get_supabase()` para antes do `try` se precisar.) O bloco `elif status == "failed"` de broadcast segue igual.

Run os testes do Step 1 → PASS. Depois a suíte inteira: `cd backend && python -m pytest -q` → verde (compare com a contagem de falhas pré-existentes em `origin/master`, se houver alguma; não pode surgir falha nova). Conferir que o Dev Router segue antes do parsing (CLAUDE.md §2) — a mudança é só no handler de status.

- [ ] **Step 4: SQL de preenchimento** — criar `backend/scripts/backfill_delivery_error.sql`:

```sql
-- Preenche messages.metadata.delivery_error das falhas antigas a partir dos webhooks
-- de status guardados em meta_webhook_logs (últimos 90 dias). Só ACRESCENTA a chave.
-- Desfazer: update messages set metadata = metadata - 'delivery_error' where metadata ? 'delivery_error';
-- Uso: psql -v ON_ERROR_STOP=1 -f backfill_delivery_error.sql   (cartão 7c6b70e7)
with ev as (
  select distinct on (s->>'id')
         s->>'id'                        as wamid,
         s->'errors'->0                  as err,
         (s->>'timestamp')::bigint       as ts
    from meta_webhook_logs w,
         jsonb_array_elements(w.payload->'entry')        en,
         jsonb_array_elements(en->'changes')             ch,
         jsonb_array_elements(ch->'value'->'statuses')   s
   where w.received_at > now() - interval '90 days'
     and jsonb_typeof(w.payload->'entry') = 'array'
     and s->>'status' = 'failed'
     and jsonb_typeof(s->'errors') = 'array'
     and jsonb_array_length(s->'errors') > 0
   order by s->>'id', w.received_at desc
)
update messages m
   set metadata = coalesce(m.metadata, '{}'::jsonb) || jsonb_build_object(
         'delivery_error', jsonb_build_object(
           'code',    (ev.err->>'code')::int,
           'title',   coalesce(ev.err->>'title', ev.err->>'message'),
           'details', ev.err->'error_data'->>'details',
           'at',      to_char(to_timestamp(ev.ts) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')))
  from ev
 where m.wamid = ev.wamid
   and m.delivery_status = 'failed'
   and not (coalesce(m.metadata, '{}'::jsonb) ? 'delivery_error');
```

Validação em modo teste (SÓ LEITURA, na VPS): rodar a CTE `ev` como `select count(*) ... from ev join messages m on m.wamid = ev.wamid where m.delivery_status='failed'` dentro de `begin; ... rollback;` ou só como SELECT, e conferir que a Carolaine (wamid `wamid.HBgNNTUzNzkzMjE0MDAyNxUCABEYEjhGNDlGNjY3NzlFMkMwRkREOQA=`) aparece com code 131026. NÃO rodar o UPDATE neste turno.

- [ ] **Step 5: Commit**

```bash
git add backend/app/webhook/meta_router.py backend/tests/test_delivery_error_metadata_2026_11_06.py backend/scripts/backfill_delivery_error.sql
git commit -m "feat(delivery): grava o motivo da falha da Meta na mensagem + backfill das antigas"
```

---

## Task 3: Linha vermelha com o motivo na bolha (frontend)

**Files:**
- Create: `frontend/src/lib/delivery-error.ts`
- Create: `frontend/src/lib/delivery-error.test.ts`
- Modify: `frontend/src/components/conversas/message-bubble.tsx` (`DeliveryTick` ~linha 17; rodapé ~linha 804)
- Modify: `frontend/src/components/conversas/message-bubble.test.tsx`

- [ ] **Step 1: Teste do texto (falha)**

```ts
// frontend/src/lib/delivery-error.test.ts
import { describe, expect, it } from "vitest";
import { deliveryErrorText } from "./delivery-error";

const md = (code: number, title = "X") => ({ delivery_error: { code, title } });

describe("deliveryErrorText", () => {
  it("131026", () => {
    expect(deliveryErrorText("failed", md(131026))).toBe(
      "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou.",
    );
  });
  it("131047", () => {
    expect(deliveryErrorText("failed", md(131047))).toBe(
      "Não entregue: passou a janela de 24h. Só dá para enviar modelo aprovado.",
    );
  });
  it("131042", () => {
    expect(deliveryErrorText("failed", md(131042))).toBe("Não entregue: problema de pagamento na conta da Meta.");
  });
  it("131049", () => {
    expect(deliveryErrorText("failed", md(131049))).toBe(
      "Não entregue: a Meta limitou mensagens de marketing para este cliente.",
    );
  });
  it("código desconhecido usa o título da Meta", () => {
    expect(deliveryErrorText("failed", md(130472, "User's number is part of an experiment"))).toBe(
      "Não entregue: User's number is part of an experiment (código 130472).",
    );
  });
  it("failed sem erro gravado", () => {
    expect(deliveryErrorText("failed", null)).toBe("Não entregue (motivo não registrado).");
    expect(deliveryErrorText("failed", { interativo: {} })).toBe("Não entregue (motivo não registrado).");
  });
  it("undelivered", () => {
    expect(deliveryErrorText("undelivered", null)).toBe("Entrega não confirmada pela Meta.");
  });
  it("demais status não têm texto", () => {
    for (const s of ["accepted", "sent", "delivered", "read", null, undefined] as const) {
      expect(deliveryErrorText(s, md(131026))).toBeNull();
    }
  });
});
```

Run: `cd frontend && npx vitest run src/lib/delivery-error.test.ts` → FAIL.

- [ ] **Step 2: Implementar**

```ts
// frontend/src/lib/delivery-error.ts
/**
 * Texto do motivo de não-entrega, em pt-BR, para a bolha do vendedor.
 * O backend grava o erro da Meta em messages.metadata.delivery_error
 * (meta_router._record_delivery_error) quando o status vira 'failed'.
 */
type Status = "accepted" | "sent" | "delivered" | "read" | "failed" | "undelivered" | null | undefined;

const POR_CODIGO: Record<number, string> = {
  131026: "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou.",
  131047: "Não entregue: passou a janela de 24h. Só dá para enviar modelo aprovado.",
  131042: "Não entregue: problema de pagamento na conta da Meta.",
  131049: "Não entregue: a Meta limitou mensagens de marketing para este cliente.",
};

export function deliveryErrorText(status: Status, metadata: Record<string, unknown> | null | undefined): string | null {
  if (status === "undelivered") return "Entrega não confirmada pela Meta.";
  if (status !== "failed") return null;
  const err = (metadata?.delivery_error ?? null) as { code?: number | string | null; title?: string | null } | null;
  const code = err?.code != null ? Number(err.code) : null;
  if (code == null || Number.isNaN(code)) return "Não entregue (motivo não registrado).";
  if (POR_CODIGO[code]) return POR_CODIGO[code];
  return `Não entregue: ${err?.title || "erro da Meta"} (código ${code}).`;
}
```

Run o teste → PASS.

- [ ] **Step 3: Teste da bolha (falha)** — em `message-bubble.test.tsx`, seguindo o padrão de render já usado no arquivo, adicionar:
  - mensagem `role: "assistant"`, `sent_by: "seller"`, `delivery_status: "failed"`, `metadata: { delivery_error: { code: 131026, title: "Message undeliverable" } }` → `screen.getByText("Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou.")` existe; o ícone (`aria-label="Entrega não confirmada"`) tem `title` com o mesmo texto.
  - mesma mensagem com `delivery_status: "read"` → `queryByText(/Não entregue/)` é null.
  - mensagem do cliente (`role: "user"`) com `delivery_status: "failed"` → sem a linha.

Run → FAIL.

- [ ] **Step 4: Implementar na bolha**
  - `import { deliveryErrorText } from "@/lib/delivery-error";`
  - `DeliveryTick` ganha prop `reason?: string | null`; no `<svg>` do caso failed/undelivered, adicionar `<title>{reason ?? "Entrega não confirmada"}</title>` como primeiro filho (mantenha o `aria-label`).
  - No corpo: `const falhaTexto = isFromMe && !isTemp ? deliveryErrorText(message.delivery_status, message.metadata as Record<string, unknown> | null) : null;`
  - `<DeliveryTick status={message.delivery_status} reason={falhaTexto} />`
  - Logo após o `</div>` da linha da hora (antes dos botões interativos):

```tsx
        {falhaTexto && (
          <p className="mt-1 text-[11px] leading-snug text-[#ff8a8d]" role="status">
            {falhaTexto}
          </p>
        )}
```

  (A bolha do vendedor é preta — `#ff8a8d` mantém contraste; o ícone segue `#e5484d`.) Se o teste do `title` usar `getByTitle`, `<title>` dentro do SVG atende.

Run: `cd frontend && npx vitest run src/components/conversas/message-bubble.test.tsx src/lib/delivery-error.test.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/delivery-error.ts frontend/src/lib/delivery-error.test.ts frontend/src/components/conversas/message-bubble.tsx frontend/src/components/conversas/message-bubble.test.tsx
git commit -m "feat(conversas): bolha mostra o motivo quando a mensagem nao chega"
```

---

## Task 4: Verificação final em modo teste (controlador)

- [ ] `cd frontend && npm test` → tudo verde; `npx tsc --noEmit`; `npm run build`.
- [ ] `cd backend && python -m pytest -q` → verde (sem falha nova versus master).
- [ ] SELECT de validação do backfill na VPS (só leitura).
- [ ] Frontend local (`npm run dev` no worktree, `.env.local` copiado do repo principal, só leitura) → print de `/conversas` na conversa da Carolaine (conv `0f26afca-825a-45ab-9458-2df4629771da`), mostrando "Não entregue (motivo não registrado)." nas bolhas do vendedor. Salvar em `.claude/worktrees/prints/agente-7c6b70e7/`.
- [ ] Nada de push, merge ou deploy.
