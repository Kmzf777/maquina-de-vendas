# Phone Normalization — 9th Digit Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar duplicação de leads causada pelo bug do 9º dígito WhatsApp no Brasil, corrigindo a normalização de telefone em toda a stack e limpando a base existente.

**Architecture:** Fix cirúrgico na função `normalize_phone` de `leads/service.py` (adiciona injeção do 9º dígito), atualiza o importer para delegar a normalização final à mesma função, corrige o `meta_router` e executa dois scripts SQL — primeiro merge de duplicatas já existentes, depois migração em lote dos 122 leads ativos.

**Tech Stack:** Python 3.12, FastAPI, Supabase (PostgreSQL), pytest

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `backend/app/leads/service.py` | Modificar | Renomear `_normalize_phone` → `normalize_phone` (público) + injetar 9º dígito |
| `backend/app/campaign/importer.py` | Modificar | Remover implementação local, delegar à `normalize_phone` de `leads.service` |
| `backend/app/webhook/meta_router.py` | Modificar | Normalizar phone em `_track_inbound_message_time` |
| `backend/tests/test_phone_normalization.py` | Modificar | Atualizar import + adicionar casos do 9º dígito |
| `backend/tests/test_importer.py` | Modificar | Atualizar expected values + adicionar caso 12-digit |
| `backend/migrations/20260501_normalize_phones_9th_digit.sql` | Criar | Hotfix SQL para normalizar registros existentes |
| `backend/scripts/merge_duplicate_leads.sql` | Criar | Script transacional de merge de duplicatas |

---

## Task 1: Fix `normalize_phone` em `leads/service.py`

**Files:**
- Modify: `backend/tests/test_phone_normalization.py`
- Modify: `backend/app/leads/service.py`

- [ ] **Step 1: Atualizar os testes — trocar import e adicionar casos do 9º dígito**

Substituir o conteúdo completo de `backend/tests/test_phone_normalization.py`:

```python
import pytest
from app.leads.service import normalize_phone


@pytest.mark.parametrize("raw,expected", [
    # casos existentes (comportamento inalterado)
    ("+5511999990000", "5511999990000"),
    ("5511999990000", "5511999990000"),
    ("+55 11 99999-0000", "5511999990000"),
    ("(11) 99999-0000", "11999990000"),       # sem DDI — aceita como está
    ("whatsapp:+5511999990000", "5511999990000"),
    ("whatsapp:5511999990000", "5511999990000"),
    (" +55 11 9 9999 0000 ", "5511999990000"),
    ("", ""),
    (None, ""),
    # casos do 9º dígito
    ("553898422923", "5538998422923"),          # 12 dígitos BR → injeta 9
    ("+553898422923", "5538998422923"),          # + prefix + 12 dígitos → injeta 9
    ("5538998422923", "5538998422923"),          # já 13 dígitos → inalterado
    ("whatsapp:553898422923", "5538998422923"),  # whatsapp prefix + 12 dígitos
    ("551299990000", "5512999990000"),           # DDD 12 (SP interior) sem 9
    ("5521912345678", "5521912345678"),          # 13 dígitos RJ → inalterado
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
```

- [ ] **Step 2: Rodar os testes — confirmar que falham**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra/backend
python -m pytest tests/test_phone_normalization.py -v
```

Resultado esperado: `ImportError: cannot import name 'normalize_phone'` (função ainda é `_normalize_phone`).

- [ ] **Step 3: Atualizar a implementação em `leads/service.py`**

Substituir o bloco `_PHONE_RE` + `_normalize_phone` + a chamada interna em `get_or_create_lead`:

**Antes** (linhas ~11–20):
```python
_PHONE_RE = re.compile(r"[^\d]+")

def _normalize_phone(phone: str | None) -> str:
    """Strip everything but digits. Keeps country code as provided — does NOT invent '55'."""
    if not phone:
        return ""
    # Drop common wrappers like 'whatsapp:' prefix
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    return _PHONE_RE.sub("", phone)
```

**Depois:**
```python
_PHONE_RE = re.compile(r"[^\d]+")


def normalize_phone(phone: str | None) -> str:
    """Normalize to E.164 without '+'. Injects the Brazilian 9th digit when missing."""
    if not phone:
        return ""
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    digits = _PHONE_RE.sub("", phone)
    # Brazilian mobiles stored without 9th digit: 55 + 2-digit DDD + 8 digits = 12 total
    if len(digits) == 12 and digits.startswith("55"):
        digits = digits[:4] + "9" + digits[4:]
    return digits
```

E na função `get_or_create_lead`, trocar a única chamada `_normalize_phone` → `normalize_phone`:

**Antes:**
```python
def get_or_create_lead(phone: str) -> dict[str, Any]:
    sb = get_supabase()
    normalized = _normalize_phone(phone)
```

**Depois:**
```python
def get_or_create_lead(phone: str) -> dict[str, Any]:
    sb = get_supabase()
    normalized = normalize_phone(phone)
```

- [ ] **Step 4: Rodar os testes — confirmar que passam**

```bash
python -m pytest tests/test_phone_normalization.py -v
```

Resultado esperado: todos os 15 parâmetros `PASSED`.

- [ ] **Step 5: Commit**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra
git add backend/app/leads/service.py backend/tests/test_phone_normalization.py
git commit -m "fix(phone): inject Brazilian 9th digit in normalize_phone; make function public"
```

---

## Task 2: Atualizar `importer.py` para usar `normalize_phone` de `leads.service`

**Files:**
- Modify: `backend/tests/test_importer.py`
- Modify: `backend/app/campaign/importer.py`

- [ ] **Step 1: Atualizar os testes do importer**

Substituir o conteúdo completo de `backend/tests/test_importer.py`:

```python
from app.campaign.importer import normalize_phone, parse_csv


def test_normalize_full_number():
    # 13 dígitos já normalizados → inalterado
    assert normalize_phone("5534999999999") == "5534999999999"


def test_normalize_without_country():
    # 11 dígitos sem DDI → add 55 → já 13 dígitos → inalterado
    assert normalize_phone("34999999999") == "5534999999999"


def test_normalize_with_plus():
    assert normalize_phone("+5534999999999") == "5534999999999"


def test_normalize_with_formatting():
    assert normalize_phone("(34) 99999-9999") == "5534999999999"


def test_normalize_landline():
    # 10 dígitos (sem DDI) → add 55 → 12 dígitos → injeta 9 (contexto WhatsApp = mobile only)
    assert normalize_phone("3432221111") == "5534932221111"


def test_normalize_old_mobile_12digits():
    # CSV com número no formato antigo (12 dígitos com DDI) → injeta 9
    assert normalize_phone("553898422923") == "5538998422923"


def test_normalize_invalid():
    assert normalize_phone("123") is None
    assert normalize_phone("abcdefghij") is None


def test_parse_csv_basic():
    csv_content = "telefone\n5534999999999\n5534888888888\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 2
    assert result.valid[0] == "5534999999999"


def test_parse_csv_normalizes_old_format():
    # CSV com número antigo (12 dígitos) → deve sair normalizado (13 dígitos)
    csv_content = "telefone\n553898422923\n"
    result = parse_csv(csv_content)
    assert result.valid[0] == "5538998422923"


def test_parse_csv_with_invalid():
    csv_content = "phone\n5534999999999\n123\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 1
    assert len(result.invalid) == 1
```

- [ ] **Step 2: Rodar os testes — confirmar que falham**

```bash
python -m pytest tests/test_importer.py -v
```

Resultado esperado: `test_normalize_landline` e `test_normalize_old_mobile_12digits` e `test_parse_csv_normalizes_old_format` falham (função local retorna 12 dígitos sem injetar 9).

- [ ] **Step 3: Atualizar a implementação do importer**

Substituir o conteúdo completo de `backend/app/campaign/importer.py`:

```python
import csv
import io
import re
from dataclasses import dataclass

from app.leads.service import normalize_phone as _canonical_normalize


@dataclass
class ImportResult:
    valid: list[str]
    invalid: list[str]


def normalize_phone(phone: str) -> str | None:
    """Normalize a Brazilian phone number to E.164 without '+'.
    Handles missing country code, then delegates to canonical normalization
    (which includes 9th digit injection for 12-digit BR numbers).
    Returns None if the number is structurally invalid.
    """
    digits = re.sub(r"\D", "", phone)

    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) in (10, 11):
        digits = "55" + digits
    elif len(digits) in (12, 13):
        if not digits.startswith("55"):
            return None
    else:
        return None

    if len(digits) not in (12, 13):
        return None

    return _canonical_normalize(digits)


def parse_csv(file_content: str | bytes) -> ImportResult:
    """Parse a CSV file and extract valid phone numbers."""
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")

    valid = []
    invalid = []

    reader = csv.reader(io.StringIO(file_content))
    header = next(reader, None)

    phone_col = 0
    if header:
        for i, col in enumerate(header):
            if col.strip().lower() in ("phone", "telefone", "numero", "whatsapp", "celular"):
                phone_col = i
                break

    for row in reader:
        if not row or len(row) <= phone_col:
            continue

        raw = row[phone_col].strip()
        if not raw:
            continue

        normalized = normalize_phone(raw)
        if normalized:
            valid.append(normalized)
        else:
            invalid.append(raw)

    return ImportResult(valid=valid, invalid=invalid)
```

- [ ] **Step 4: Rodar os testes — confirmar que passam**

```bash
python -m pytest tests/test_importer.py -v
```

Resultado esperado: todos os 10 testes `PASSED`.

- [ ] **Step 5: Rodar a suite completa para verificar regressões**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Resultado esperado: sem novos erros além dos já existentes (se houver).

- [ ] **Step 6: Commit**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra
git add backend/app/campaign/importer.py backend/tests/test_importer.py
git commit -m "fix(importer): delegate final normalization to leads.service.normalize_phone"
```

---

## Task 3: Corrigir `_track_inbound_message_time` no `meta_router.py`

**Files:**
- Modify: `backend/app/webhook/meta_router.py`

- [ ] **Step 1: Adicionar `normalize_phone` ao import existente**

**Antes** (linha ~12):
```python
from app.leads.service import get_or_create_lead, reset_lead
```

**Depois:**
```python
from app.leads.service import get_or_create_lead, normalize_phone, reset_lead
```

- [ ] **Step 2: Normalizar o phone em `_track_inbound_message_time`**

**Antes:**
```python
def _track_inbound_message_time(phone: str) -> None:
    """Update last_customer_message_at so the 24h window status stays current."""
    try:
        sb = get_supabase()
        sb.table("leads").update(
            {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
        ).eq("phone", phone).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {phone}: {e}")
```

**Depois:**
```python
def _track_inbound_message_time(phone: str) -> None:
    """Update last_customer_message_at so the 24h window status stays current."""
    try:
        sb = get_supabase()
        sb.table("leads").update(
            {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
        ).eq("phone", normalize_phone(phone)).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {phone}: {e}")
```

- [ ] **Step 3: Rodar os testes do webhook**

```bash
python -m pytest tests/test_webhook_parser.py tests/test_webhook_dev_routing.py -v
```

Resultado esperado: todos `PASSED`.

- [ ] **Step 4: Commit**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra
git add backend/app/webhook/meta_router.py
git commit -m "fix(webhook): normalize phone in _track_inbound_message_time"
```

---

## Task 4: SQL Migration — Hotfix para registros existentes

**Files:**
- Create: `backend/migrations/20260501_normalize_phones_9th_digit.sql`

- [ ] **Step 1: Criar o arquivo de migração**

Criar `backend/migrations/20260501_normalize_phones_9th_digit.sql` com o conteúdo:

```sql
-- 20260501_normalize_phones_9th_digit.sql
--
-- Normaliza números brasileiros de celular de 12 dígitos para 13 dígitos
-- injetando o 9º dígito após o DDD.
--
-- PRECONDIÇÃO: rodar merge_duplicate_leads.sql PRIMEIRO para eliminar duplicatas.
-- Esta migração pula registros que já têm o par de 13 dígitos na base
-- (eles seriam tratados pelo merge, não aqui).
--
-- Verificação antes de rodar:
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--
-- Verificação depois:
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--   -- Deve retornar 0.

UPDATE leads
SET phone = LEFT(phone, 4) || '9' || RIGHT(phone, 8)
WHERE LENGTH(phone) = 12
  AND phone LIKE '55%'
  AND NOT EXISTS (
    SELECT 1 FROM leads l2
    WHERE l2.phone = LEFT(leads.phone, 4) || '9' || RIGHT(leads.phone, 8)
      AND l2.id != leads.id
  );
```

- [ ] **Step 2: Verificar quantos registros serão afetados (dry-run de contagem)**

Rodar no Supabase SQL Editor (não modifica dados):

```sql
SELECT COUNT(*) AS serao_normalizados
FROM leads
WHERE LENGTH(phone) = 12
  AND phone LIKE '55%'
  AND NOT EXISTS (
    SELECT 1 FROM leads l2
    WHERE l2.phone = LEFT(leads.phone, 4) || '9' || RIGHT(leads.phone, 8)
      AND l2.id != leads.id
  );

-- Separado: quantos serão pulados por já ter duplicata:
SELECT COUNT(*) AS tem_duplicata
FROM leads
WHERE LENGTH(phone) = 12
  AND phone LIKE '55%'
  AND EXISTS (
    SELECT 1 FROM leads l2
    WHERE l2.phone = LEFT(leads.phone, 4) || '9' || RIGHT(leads.phone, 8)
      AND l2.id != leads.id
  );
```

- [ ] **Step 3: Commit do arquivo de migração**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra
git add backend/migrations/20260501_normalize_phones_9th_digit.sql
git commit -m "fix(db): migration to normalize BR phones to 13-digit E.164"
```

> ⚠️ **NÃO executar a migração ainda.** Executar após o merge script (Task 5) e após o usuário autorizar.

---

## Task 5: Script de Merge de Duplicatas

**Files:**
- Create: `backend/scripts/merge_duplicate_leads.sql`

- [ ] **Step 1: Criar o script de merge**

Criar `backend/scripts/merge_duplicate_leads.sql`:

```sql
-- merge_duplicate_leads.sql
--
-- Unifica leads duplicados causados pelo bug do 9º dígito WhatsApp.
-- Para cada par (lead 12-dígitos, lead 13-dígitos que representam a mesma pessoa):
--   - Determina o "pai" (quem tem dados em broadcast_leads ou messages; empate → mais antigo)
--   - Migra todos os registros dependentes do "filho" para o "pai"
--   - Deleta o "filho"
--   - Normaliza o phone do "pai" para 13 dígitos (caso tenha ficado com 12)
--
-- ╔══ COMO USAR ══════════════════════════════════════════════════════════════╗
-- ║  DRY RUN (sem commit — só para inspecionar o RAISE NOTICE):              ║
-- ║    BEGIN; [cole este script]; ROLLBACK;                                  ║
-- ║                                                                          ║
-- ║  EXECUTAR DE VERDADE:                                                    ║
-- ║    BEGIN; [cole este script]; COMMIT;                                    ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝

DO $$
DECLARE
    r            RECORD;
    conv_conflict RECORD;
BEGIN
    FOR r IN (
        WITH raw_pairs AS (
            SELECT
                filho.id         AS d12_id,
                pai.id           AS d13_id,
                filho.created_at AS d12_created,
                pai.created_at   AS d13_created,
                (
                    EXISTS (SELECT 1 FROM broadcast_leads bl WHERE bl.lead_id = filho.id)
                    OR EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = filho.id)
                ) AS d12_has_data,
                (
                    EXISTS (SELECT 1 FROM broadcast_leads bl WHERE bl.lead_id = pai.id)
                    OR EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = pai.id)
                ) AS d13_has_data
            FROM leads filho
            JOIN leads pai
              ON pai.phone = LEFT(filho.phone, 4) || '9' || RIGHT(filho.phone, 8)
            WHERE LENGTH(filho.phone) = 12
              AND filho.phone LIKE '55%'
        )
        SELECT
            -- filho_id = o que será DELETADO
            -- pai_id   = o que será MANTIDO
            CASE
                WHEN d12_has_data AND NOT d13_has_data THEN d13_id   -- 12-dígitos tem dados → mantém 12, deleta 13
                WHEN d13_has_data AND NOT d12_has_data THEN d12_id   -- 13-dígitos tem dados → mantém 13, deleta 12
                WHEN d12_created < d13_created         THEN d13_id   -- empate/nenhum: mantém o mais antigo (12)
                ELSE d12_id                                           -- fallback: mantém 13-dígitos
            END AS filho_id,
            CASE
                WHEN d12_has_data AND NOT d13_has_data THEN d12_id
                WHEN d13_has_data AND NOT d12_has_data THEN d13_id
                WHEN d12_created < d13_created         THEN d12_id
                ELSE d13_id
            END AS pai_id
        FROM raw_pairs
    )
    LOOP
        RAISE NOTICE 'Merge: filho=% → pai=%', r.filho_id, r.pai_id;

        -- ── Tipo 1: UPDATE direto (sem unique constraint em lead_id+X) ────────

        UPDATE messages           SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE deals              SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE lead_events        SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE lead_notes         SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE token_usage        SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── conversations: UNIQUE(lead_id, channel_id) ────────────────────────
        -- Para cada conversa do filho que conflita com o pai (mesmo channel),
        -- reassina as mensagens da conversa do filho para a do pai, depois deleta.

        FOR conv_conflict IN (
            SELECT c_filho.id AS filho_conv_id, c_pai.id AS pai_conv_id
            FROM conversations c_filho
            JOIN conversations c_pai
              ON c_pai.lead_id    = r.pai_id
             AND c_pai.channel_id = c_filho.channel_id
            WHERE c_filho.lead_id = r.filho_id
        ) LOOP
            UPDATE messages
               SET conversation_id = conv_conflict.pai_conv_id
             WHERE conversation_id = conv_conflict.filho_conv_id;
            DELETE FROM conversations WHERE id = conv_conflict.filho_conv_id;
        END LOOP;
        -- Conversas restantes (sem conflito de channel) simplesmente migram
        UPDATE conversations SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── broadcast_leads: UNIQUE(broadcast_id, lead_id) ───────────────────

        DELETE FROM broadcast_leads
        WHERE lead_id = r.filho_id
          AND broadcast_id IN (
              SELECT broadcast_id FROM broadcast_leads WHERE lead_id = r.pai_id
          );
        UPDATE broadcast_leads SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── cadence_enrollments: UNIQUE(cadence_id, lead_id) ─────────────────

        DELETE FROM cadence_enrollments
        WHERE lead_id = r.filho_id
          AND cadence_id IN (
              SELECT cadence_id FROM cadence_enrollments WHERE lead_id = r.pai_id
          );
        UPDATE cadence_enrollments SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── lead_tags: PK (lead_id, tag_id) ──────────────────────────────────

        DELETE FROM lead_tags
        WHERE lead_id = r.filho_id
          AND tag_id IN (
              SELECT tag_id FROM lead_tags WHERE lead_id = r.pai_id
          );
        UPDATE lead_tags SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── cadence_state: UNIQUE em lead_id (uma linha por lead) ─────────────

        DELETE FROM cadence_state
        WHERE lead_id = r.filho_id
          AND EXISTS (SELECT 1 FROM cadence_state WHERE lead_id = r.pai_id);
        UPDATE cadence_state SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── Deletar o lead filho ──────────────────────────────────────────────

        DELETE FROM leads WHERE id = r.filho_id;

        -- ── Normalizar phone do pai para 13 dígitos ───────────────────────────
        -- Necessário quando o pai era o lead 12-dígitos (o "mais rico")

        UPDATE leads
           SET phone = LEFT(phone, 4) || '9' || RIGHT(phone, 8)
         WHERE id = r.pai_id
           AND LENGTH(phone) = 12;

        RAISE NOTICE 'OK: filho=% deletado, pai=% preservado', r.filho_id, r.pai_id;
    END LOOP;
END $$;
```

- [ ] **Step 2: Commit do script**

```bash
cd /home/Kelwin/Kelwin\ -\ Maquinadevendascanastra
git add backend/scripts/merge_duplicate_leads.sql
git commit -m "fix(db): script to merge duplicate leads caused by 9th digit bug"
```

---

## Ordem de Execução em Produção

Após o deploy do código (Tasks 1–3), executar os scripts na seguinte ordem no **Supabase SQL Editor**:

```
PASSO 1 ─ DRY RUN do merge (verificar os pares que serão mesclados):
  BEGIN;
    [conteúdo de merge_duplicate_leads.sql]
  ROLLBACK;
  → Inspecionar os NOTICE logs para validar os pares filho/pai.

PASSO 2 ─ EXECUTAR o merge:
  BEGIN;
    [conteúdo de merge_duplicate_leads.sql]
  COMMIT;

PASSO 3 ─ EXECUTAR a migração de normalização:
  [conteúdo de 20260501_normalize_phones_9th_digit.sql]

PASSO 4 ─ VERIFICAÇÃO FINAL:
  SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
  -- Deve retornar 0.
```

---

## Self-Review

**Spec coverage:**
- ✅ Seção 1 (normalize_phone unificada): Tasks 1, 2, 3
- ✅ Seção 2 (webhook + importer): Tasks 2, 3
- ✅ Seção 3 (migração SQL hotfix): Task 4
- ✅ Seção 4 (merge script com preservação de histórico): Task 5
- ✅ Caso Moisés (pai com disparos + filho com messages): coberto pelo algoritmo de merge em Task 5 — `messages` migram via UPDATE direto, `broadcast_leads` via delete-then-update

**Consistência de tipos:**
- `normalize_phone` exportada de `leads.service` e importada por `importer.py` e `meta_router.py`
- `_canonical_normalize` em `importer.py` é alias local para `leads.service.normalize_phone`
- Assinaturas idênticas: `normalize_phone(phone: str | None) -> str` no service; `normalize_phone(phone: str) -> str | None` no importer (diferença intencional: importer valida formato e retorna None para inválidos)

**Placeholders:** nenhum.
