# Spec: Correção do Bug do 9º Dígito (WhatsApp Brasil)

**Data:** 2026-05-01  
**Status:** Aprovado  
**Prioridade:** Crítica — disparo ativo de 122 leads

---

## Problema

Números brasileiros de celular migraram de 8 para 9 dígitos locais. O WhatsApp retorna o número no formato moderno (13 dígitos: `55` + DDD + 9 dígitos), mas leads importados via CSV podem estar salvos no formato antigo (12 dígitos: `55` + DDD + 8 dígitos).

Exemplo:
- Salvo no banco: `553898422923` (12 dígitos)
- Retornado pelo webhook Meta: `5538998422923` (13 dígitos)

O sistema faz exact match ao buscar o lead. Como as strings diferem, cria um lead duplicado em vez de encontrar o existente.

Existem **duas** implementações de normalização sem essa regra:
- `backend/app/leads/service.py::_normalize_phone`
- `backend/app/campaign/importer.py::normalize_phone`

---

## Escopo

Quatro mudanças coordenadas:

1. **Função de normalização unificada** — injeta o 9º dígito
2. **Webhook e importer** — usam a função unificada
3. **Migração SQL** — normaliza registros existentes (hotfix para 122 leads)
4. **Script de merge** — limpa duplicatas já criadas, preservando todo o histórico

---

## Seção 1 — Função de Normalização Unificada

### Localização
`backend/app/leads/service.py`

### Mudança
`_normalize_phone` (privada) vira `normalize_phone` (pública) e ganha a regra do 9º dígito:

```
strip non-digits
→ remove prefixo "whatsapp:"
→ SE len == 12 E começa com "55":
    return phone[:4] + "9" + phone[4:]
→ retorna como está
```

Transformações:
| Entrada | Saída | Motivo |
|---------|-------|--------|
| `553898422923` | `5538998422923` | 12 dígitos BR → injeta 9 |
| `5538998422923` | `5538998422923` | 13 dígitos → inalterado |
| `+5511999990000` | `5511999990000` | remove + |
| `whatsapp:5511999990000` | `5511999990000` | remove prefixo |
| `5511999990000` | `5511999990000` | já normalizado |

### `get_or_create_lead` — backfill path
O mecanismo de backfill existente (busca pelo número cru se o normalizado não for encontrado) já cobre o caso legacy. Após a normalização incluir o 9º dígito, leads com 12 dígitos no banco que ainda não foram migrados pela SQL serão encontrados pelo fallback e atualizados on-the-fly.

---

## Seção 2 — Pontos de Integração

### `backend/app/campaign/importer.py`
- Remove a função `normalize_phone` local
- Importa `normalize_phone` de `app.leads.service`
- Sem mudança de comportamento visível para o usuário

### `backend/app/webhook/meta_router.py` — `_track_inbound_message_time`
Atualmente faz `.eq("phone", raw_phone)`. Após migração do banco, se o Meta enviar um número 12-dígitos (raro, mas possível), o update de `last_customer_message_at` silenciosamente falha.

Correção: normalizar o `phone` antes do query.

### `backend/tests/test_phone_normalization.py`
Adicionar casos de teste:
- `("553898422923", "5538998422923")` — 12 dígitos → injeta 9
- `("5538998422923", "5538998422923")` — 13 dígitos → inalterado
- `("5511900000000", "5511900000000")` — 13 dígitos → inalterado
- `("55119000000", "55119000000")` — 11 dígitos (não BR válido) → inalterado

---

## Seção 3 — Migração SQL (Hotfix Emergencial)

### Arquivo
`backend/migrations/20260501_normalize_phones_9th_digit.sql`

### Lógica
```sql
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

- Leads sem conflito de duplicata: normalizados imediatamente (inclui os 122 do disparo ativo)
- Leads com duplicata já existente: pulados — tratados pelo script de merge (Seção 4)

### Ordem de execução
```
1. Deploy do código (Seções 1 e 2)
2. Rodar merge_duplicate_leads.sql   ← elimina duplicatas
3. Rodar 20260501_normalize_phones_9th_digit.sql  ← normaliza restantes
```

---

## Seção 4 — Script de Merge de Duplicatas

### Arquivo
`backend/scripts/merge_duplicate_leads.sql`

### Critério de "Lead Pai"
O lead que possui registros em `broadcast_leads` ou `messages`. Em caso de empate (ambos têm, ou nenhum tem), o mais antigo (`created_at` menor) é o pai.

### Algoritmo (tudo dentro de uma transação)

Para cada par `(filho_id, pai_id)` identificado:

#### Tabelas Tipo 1 — UPDATE direto (sem unique constraint em lead_id+X)
`messages`, `deals`, `lead_events`, `lead_notes`, `token_usage`

```sql
UPDATE <tabela> SET lead_id = pai_id WHERE lead_id = filho_id;
```

#### Tabelas Tipo 2 — Merge com tratamento de conflito

**`conversations` — `UNIQUE(lead_id, channel_id)`**
```
Para cada conversa do filho:
  SE pai já tem conversa para o mesmo channel_id:
    → UPDATE messages SET conversation_id = conv_pai WHERE conversation_id = conv_filho
    → DELETE conversations WHERE id = conv_filho
  SENÃO:
    → UPDATE conversations SET lead_id = pai WHERE lead_id = filho
```

**`broadcast_leads` — `UNIQUE(broadcast_id, lead_id)`**
```
DELETE broadcast_leads
  WHERE lead_id = filho_id
    AND broadcast_id IN (SELECT broadcast_id FROM broadcast_leads WHERE lead_id = pai_id);
UPDATE broadcast_leads SET lead_id = pai_id WHERE lead_id = filho_id;
```

**`cadence_enrollments` — `UNIQUE(cadence_id, lead_id)`**
```
DELETE cadence_enrollments
  WHERE lead_id = filho_id
    AND cadence_id IN (SELECT cadence_id FROM cadence_enrollments WHERE lead_id = pai_id);
UPDATE cadence_enrollments SET lead_id = pai_id WHERE lead_id = filho_id;
```

**`lead_tags` — `PK (lead_id, tag_id)`**
```
DELETE lead_tags
  WHERE lead_id = filho_id
    AND tag_id IN (SELECT tag_id FROM lead_tags WHERE lead_id = pai_id);
UPDATE lead_tags SET lead_id = pai_id WHERE lead_id = filho_id;
```

**`cadence_state`**
```
DELETE cadence_state WHERE lead_id = filho_id
  AND EXISTS (SELECT 1 FROM cadence_state WHERE lead_id = pai_id);
UPDATE cadence_state SET lead_id = pai_id WHERE lead_id = filho_id;
```

#### Passo final
```sql
DELETE FROM leads WHERE id = filho_id;
```

### Identificação dos pares duplicados
```sql
-- Pares onde um tem 12 dígitos e o outro é sua versão com 9º dígito (13 dígitos)
SELECT
  filho.id   AS filho_id,
  pai.id     AS pai_id
FROM leads filho
JOIN leads pai
  ON pai.phone = LEFT(filho.phone, 4) || '9' || RIGHT(filho.phone, 8)
WHERE LENGTH(filho.phone) = 12
  AND filho.phone LIKE '55%';
-- Critério: pai = quem tem broadcast_leads ou messages; empate = mais antigo
```

---

## Invariantes e Garantias

- Todo o merge roda em uma **única transação** — qualquer erro causa rollback completo
- Nenhum registro de `messages`, `deals`, `lead_events`, `lead_notes` é perdido — todos migram para o pai
- Conflitos em tabelas com unique constraints são resolvidos priorizando o pai; dados do filho que duplicam são descartados (o pai já os tem)
- A constraint `UNIQUE` em `leads.phone` é satisfeita antes do DELETE do filho (porque os UPDATEs de lead_id acontecem antes)
- Após execução: zero leads com 12 dígitos BR, zero duplicatas

---

## Arquivos Modificados

| Arquivo | Tipo | Mudança |
|---------|------|---------|
| `backend/app/leads/service.py` | Código | `_normalize_phone` → `normalize_phone` + 9º dígito |
| `backend/app/campaign/importer.py` | Código | Remove local, importa de `leads.service` |
| `backend/app/webhook/meta_router.py` | Código | Normaliza phone em `_track_inbound_message_time` |
| `backend/tests/test_phone_normalization.py` | Testes | Adiciona casos do 9º dígito |
| `backend/migrations/20260501_normalize_phones_9th_digit.sql` | SQL | Hotfix para leads existentes |
| `backend/scripts/merge_duplicate_leads.sql` | SQL | Merge de duplicatas |
