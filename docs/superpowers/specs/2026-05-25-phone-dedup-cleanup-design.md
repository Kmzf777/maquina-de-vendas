# Design: Correção de Telefones Duplicados na Tabela `leads`

**Data:** 2026-05-25  
**Status:** Aprovado

---

## Contexto

Múltiplos registros na coluna `leads.phone` contêm valores corrompidos no padrão "número+número": o valor é a concatenação exata do número consigo mesmo (ex: `1198115400211981154002` = `11981154002` × 2).

**Causa raiz:** Três caminhos de escrita aceitam phone bruto sem nenhuma sanitização:
1. `quick-add-lead.tsx` → insere diretamente no Supabase sem validação
2. `POST /api/leads/route.ts` → insere `body.phone` verbatim
3. `PATCH /api/leads/[id]/route.ts` → aplica body direto ao Supabase (qualquer campo, inclusive phone)

Os caminhos via webhook Meta e CSV broadcast são seguros (passam por `normalize_phone`).

---

## Escopo da solução

### 1. Script de limpeza do banco (`backend/scripts/fix_duplicated_phones.py`)

- Detecta registros onde `len(phone) > 13`, `len(phone)` é par, e `phone[:half] == phone[half:]`
- Modo DRY RUN (padrão): mostra lista de afetados sem alterar nada
- Modo APPLY (`DRY_RUN=false`): executa `UPDATE leads SET phone = phone[:half] WHERE <condição>`
- Exibe ID, phone corrompido → phone corrigido para cada registro

### 2. Defesa na função `normalize_phone` (`backend/app/leads/service.py`)

Antes de qualquer lógica existente, detectar e desfazer o padrão de duplicação:

```python
# Detecta phone duplicado (ex: "1198115400211981154002" → "11981154002")
if len(digits) > 15 and len(digits) % 2 == 0:
    half = len(digits) // 2
    if digits[:half] == digits[half:]:
        logger.warning("normalize_phone: phone duplicado detectado e corrigido: %s → %s", digits, digits[:half])
        digits = digits[:half]
```

Em seguida, log de warning para phones ainda > 15 dígitos (anomalia não tratável pela regra acima).

### 3. Validação nos endpoints frontend que escapam do backend

**`POST /api/leads/route.ts`:**
- Sanitizar `body.phone`: strip de não-dígitos
- Rejeitar com HTTP 422 se < 8 ou > 15 dígitos após sanitização

**`PATCH /api/leads/[id]/route.ts`:**
- Se `body.phone` presente, aplicar mesma sanitização e rejeitar se inválido

**`quick-add-lead.tsx`:**
- Validação básica no `handleSubmit`: strip de não-dígitos, verificar comprimento 8–15
- Exibir mensagem de erro ao usuário se inválido (sem enviar ao banco)

---

## Fora do escopo

- Injeção do 9º dígito no frontend (`lead-import-modal.tsx`) — bug separado de duplicatas de lead, não causa phone doubled
- Migração de phones legados de 12 → 13 dígitos — já tratado por backfill no `get_or_create_lead`
- Qualquer alteração em Evolution API

---

## Testes

- Script de limpeza: DRY RUN mostrando 0 registros em banco limpo
- `normalize_phone`: caso de teste `"1198115400211981154002"` → `"5511981154002"` (corrigido + DDI + 9º dígito)
- `POST /api/leads` com phone de 22 dígitos deve retornar 422
