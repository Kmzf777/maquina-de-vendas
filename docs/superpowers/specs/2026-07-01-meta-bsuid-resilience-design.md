# Design: Resiliência a BSUID / Nomes de Usuário — Meta WhatsApp

**Data:** 2026-07-01
**Branch:** `feat/meta-bsuid-resilience`
**Escopo aprovado:** Resiliência a BSUID (não perder mensagem/lead quando o telefone for omitido). Identidade: coluna `bsuid` + merge no telefone.

---

## 1. Problema

A partir da adoção de **nomes de usuário** pelo WhatsApp, a Meta passa a **omitir o número de telefone** das cargas de webhook, enviando apenas o **BSUID** (Business-Scoped User ID):

- Mensagens recebidas: `messages[].from` pode ser omitido; `messages[].from_user_id` traz o BSUID.
- Bloco `contacts`: `wa_id` pode ser omitido; `user_id` traz o BSUID; `profile.username` traz o nome de usuário.
- Webhooks de status: `statuses[].recipient_id` pode ser omitido; `statuses[].recipient_user_id` traz o BSUID.

Formato do BSUID: código de país ISO 3166 alpha-2 (duas letras) + ponto + até 128 alfanuméricos, ex.: `US.13491208655302741918`. É **único por par usuário+portfólio** e **estável** (só muda se o usuário troca de número). BSUIDs já aparecem em webhooks desde abril/2026; as APIs de envio aceitam BSUID desde julho/2026.

O sistema atual é **phone-keyed de ponta a ponta**. Um webhook só-BSUID hoje causaria:

- **Dev router** (`_extract_from_number`) → `None` → falha o isolamento de testes.
- **Lead** (`get_or_create_lead("")`) → lead-lixo com `phone=""`.
- **Buffer** (`buffer:{channel_id}:{phone}`) → todos os usuários só-BSUID colidem na mesma chave `buffer:{channel_id}:`.
- **Envio** → impossível responder sem o campo `recipient`.

Consequência: perda silenciosa de conversas de qualquer lead que adotar username. Requisito da Meta: suporte a BSUID é **obrigatório** para não perder a capacidade de processar mensagens.

## 2. Objetivos e não-objetivos

**Objetivos:**
1. Nunca perder uma mensagem/lead por ausência de telefone.
2. Rotear (dev router), bufferizar, identificar lead e **responder** usando BSUID quando o telefone estiver ausente.
3. Fazer **backfill/merge** do telefone no lead quando ele reaparecer (cache 30 dias, contato compartilhado, agenda).
4. Preservar 100% do comportamento phone-first existente.

**Não-objetivos (fora de escopo):**
- Botão `REQUEST_CONTACT_INFO` (pedir telefone ativamente).
- API de agenda de contatos (contact book).
- Adoção/gestão de nome de usuário **comercial**.
- **BSUID principal** (`parent_user_id`) — o portfólio não está inscrito. Será tratado defensivamente (ignorado sem quebrar), não implementado.

## 3. Abordagem escolhida (roteamento de envio)

**Detecção por formato em `_post`.** O BSUID casa `^[A-Z]{2}\.` (contém letras + ponto); telefones são só dígitos. O `_post` do `MetaCloudClient` escolhe automaticamente entre `recipient` (BSUID) e `to` (telefone). Zero mudança de assinatura nos métodos de envio; um único ponto de decisão.

Alternativas descartadas: parâmetro `recipient=` explícito em ~8 métodos (superfície grande, sem ganho); prefixo-sentinela `bsuid:` na string (gambiarra — o formato já desambigua).

## 4. Componentes / mudanças

### 4.1 Modelo de identificador — `IncomingMessage` (`webhook/parser.py`)
Novos campos: `bsuid: str | None = None`, `username: str | None = None`. `from_number` permanece, podendo ser `""`.

Helper `webhook_identity(msg) -> str`: retorna `from_number` se presente, senão `bsuid`. É a **chave de roteamento** canônica.

### 4.2 Parsing (`webhook/meta_parser.py`)
- Extrair `msg.get("from_user_id")` → `bsuid` (fallback: contacts `user_id`).
- Extrair `contacts[0].profile.username` → `username`.
- `push_name`: usa `profile.name` e cai para `username` quando não há nome de exibição.
- `parent_user_id` / `from_parent_user_id`: ignorados (defensivo).

### 4.3 Dev router (`webhook/meta_router.py`)
`_extract_from_number` passa a retornar telefone **ou** BSUID: checa `msg.from` → `msg.from_user_id`; em statuses, `recipient_id` → `recipient_user_id`. Continua operando no **payload bruto, antes do parsing** (regra CLAUDE.md §2). A whitelist Redis (`dev:phone_routes`) pode conter um BSUID como chave.

### 4.4 Buffer (`buffer/manager.py`, `buffer/flusher.py`)
Chave passa a ser `normalize_phone(msg.from_number) or msg.bsuid`. Como o BSUID é único por usuário+portfólio, não há colisão. O `flusher` usa a mesma chave já persistida — nenhuma mudança de formato de chave além da origem do valor.

### 4.5 Identidade do lead (`leads/service.py` + migration)
- **Migration** `2026-07-01_leads_bsuid.sql`: coluna `bsuid text` nullable + índice único parcial `WHERE bsuid IS NOT NULL`.
- `get_or_create_lead` ganha parâmetro opcional `bsuid`:
  - Lookup por telefone primeiro (toda a lógica atual de match/backfill intacta).
  - Se telefone ausente/sem match, lookup por `bsuid`.
  - Cria lead keyed por bsuid (com `phone` vazio/sentinela) quando não há telefone.
- **Merge/backfill** (`resolve_lead_identity`): quando chega telefone + bsuid:
  - Se existe lead com esse `bsuid` e sem telefone → backfill `phone`/`wa_id`.
  - Se existe lead com esse telefone **e** um lead separado com esse bsuid → prefere o lead-telefone, carimba o `bsuid` nele e marca/reconcilia o duplicado (log; não apaga automaticamente sem sinal claro).
  - Sempre carimba `bsuid` no lead quando ainda não tiver.

### 4.6 Envio (`whatsapp/meta.py` + `resolve_send_target`)
- `resolve_send_target(lead, fallback)` → `wa_id or phone or bsuid or fallback`.
- `_post`: helper `_recipient_field(target)` decide `{"recipient": target}` (BSUID) vs `{"to": target}` (telefone). Aplicado a todos os payloads de envio (`send_text`, `send_image*`, `send_audio`, `send_contact`, `send_template`). Callers inalterados.

### 4.7 Status de entrega (`webhook/meta_router.py::_handle_delivery_status`)
Já roteia por `wamid` — sem mudança de roteamento. Adição: quando o bloco `contacts`/`statuses` traz `wa_id` **e** `user_id`, carimbar o telefone no lead-bsuid (recuperação gratuita de telefone).

## 5. Fluxo de dados (inbound só-BSUID)

```
webhook → dev router (bruto: from_user_id) → [se whitelist] forward/drop
        → parse_meta_webhook_payload → IncomingMessage(from_number="", bsuid=..., username=...)
        → dedup por wamid
        → _register_lead(identity=bsuid) → get_or_create_lead(phone="", bsuid=...)
        → push_to_buffer (key = bsuid)
        → flush → processor → resolve_send_target(lead) → send_text(bsuid, ...) → _post → {"recipient": bsuid}
```

Quando o telefone reaparecer num webhook futuro: `resolve_lead_identity` faz merge/backfill; envios subsequentes voltam a preferir `wa_id`/`phone`.

## 6. Tratamento de erros
- BSUID malformado / ausente de telefone E bsuid → loga e descarta (não cria lead-lixo).
- Erro Meta `131062` (BSUID não suportado para este tipo de mensagem) — logar; não retry infinito.
- Merge com conflito (dois leads reais) — nunca apagar automaticamente; logar para reconciliação manual.
- Toda a resiliência mantém o fail-open existente do dedup/buffer/dev-router.

## 7. Testes
Convenção `backend/tests/test_*_2026_07_01.py`, com shapes reais do documento Meta:

1. `test_meta_bsuid_parser_2026_07_01.py` — (a) username, telefone omitido; (b) username, telefone presente; (c) sem-username (BSUID+telefone); (d) status só-BSUID; extração de `bsuid`/`username`/`push_name`.
2. `test_bsuid_dev_router_2026_07_01.py` — `_extract_from_number` retorna BSUID quando `from` ausente; whitelist por BSUID.
3. `test_bsuid_buffer_key_2026_07_01.py` — chave de buffer = bsuid; dois BSUIDs distintos não colidem.
4. `test_bsuid_lead_identity_2026_07_01.py` — criação por bsuid; merge/backfill quando telefone reaparece; preferência pelo lead-telefone.
5. `test_bsuid_send_routing_2026_07_01.py` — `_post` emite `recipient` p/ BSUID e `to` p/ telefone; `resolve_send_target` prioriza `wa_id > phone > bsuid`.

## 8. Migration
`backend/migrations/2026-07-01_leads_bsuid.sql`:
```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bsuid text;
CREATE UNIQUE INDEX IF NOT EXISTS leads_bsuid_key ON leads (bsuid) WHERE bsuid IS NOT NULL;
```
Aplicação manual pendente no Supabase (workflow do projeto).

## 9. Riscos
- **Paridade dev/prod** (CLAUDE.md §3): o código deve funcionar sem `localhost`; nada de novo endereço fixo.
- **Dev router antes do parsing** (CLAUDE.md §2): manter a extração de BSUID no payload bruto.
- **Merge de leads**: risco de duplicidade se dois leads reais convergirem; mitigado por não-apagar-automático + log.
