# Design — Loop de Atribuição de Conversões de Anúncios (CRM)

**Data:** 2026-07-02
**Branch alvo:** a definir (destino final `master`)
**Status:** aprovado no brainstorming, pendente revisão da spec

---

## 1. Problema / Demanda

Google Ads e Meta Ads em 2026 **não convertem lead→venda só com UTM**. Eles exigem
identificadores de clique e/ou dados hash do usuário:

- **Google Ads:** `gclid` (+ Enhanced Conversions for Leads com e-mail/telefone SHA-256).
- **Meta Ads (Click-to-WhatsApp):** `ctwa_clid` (+ e-mail/telefone SHA-256); `fbclid` p/ tráfego de site.

O CRM precisa **capturar** esses identificadores, **acompanhar o lead pelo funil** e
**devolver eventos de conversão** às plataformas em cada etapa (Captado → Qualificado →
Oportunidade → Venda), comprovando ROI e alimentando o smart bidding.

## 2. Decisões (definidas no brainstorming)

| Decisão | Escolha |
|---|---|
| **Entrega** | **Híbrida** — Meta direto via CAPI (já vivo); Google via **Planilha Google → Data Manager / Make** (evita aprovação de dev-token do Google Ads) |
| **Etapas** | **As 4** — Lead Captado, Qualificado, Oportunidade, Venda Fechada |
| **Mapeamento etapa→evento** | **Colunas em `pipeline_stages`** (`conversion_event` + `conversion_value`), marcadas na UI de config do Kanban |

## 3. Fronteira de escopo

- **Fora deste repo (projetos de Landing Page / anúncios — outros repositórios):**
  campos ocultos do formulário, JS de captura de `gclid`, config do anúncio CTWA no
  Gerenciador. Tratados como **contrato externo** (ver §9 — inclui os prompts de handoff
  pras IAs desses repos).
- **Dentro deste repo (CRM):** captura (já pronta) → mapeamento etapa→evento → disparo
  multi-etapa → Meta direto (CAPI) + Google via Planilha → dedup/auditoria.

### Já existente (não reconstruir)

| Peça | Status | Onde |
|---|---|---|
| Intake da LP com `gclid/fbclid/utm_*` | ✅ | `lp_webhook/router.py`, `20260618_leads_traffic_tracking.sql` |
| CTWA → captura `ctwa_clid` (+ `bsuid`) no lead | ✅ | `meta_parser.py`, `meta_router.py` |
| Hash SHA-256 de e-mail/telefone | ✅ | `capi_dispatcher.py` |
| Evento Meta CAPI (aceita `event_name`) | ✅ | `capi_dispatcher.py` |
| Corpo de conversão offline Google (a partir do `gclid`) | ✅ (só payload) | `capi_dispatcher.py` |
| Disparo de `Purchase` na venda | ✅ | `leads/router.py`, `automation/engine.py` |
| Detecção de mudança de etapa no Kanban → `deal_stage_enter` no backend | ✅ | `frontend/src/app/api/deals/[id]/route.ts` → `/api/automation/trigger` |

## 4. Arquitetura

```
Mover card no Kanban (Next.js /api/deals/[id]) ──JÁ dispara──► POST /api/automation/trigger
                                                                event=deal_stage_enter {stage:key, deal_id}
                                                                          │
                                                              fire_trigger()  ── ramo NOVO ──► disparo de conversão
                                                                          │
                        ┌──────────────────────────────────────────────────┴──────────────┐
                        ▼                                                                   ▼
             grava linha em conversion_events                                mapeia stage.key → evento canônico
             (dedup: único deal_id+event)                                    (colunas em pipeline_stages)
                        │
             ┌──────────┴───────────┐
             ▼                      ▼
       Meta CAPI (direto, vivo)   Planilha Google (append)
       event_name+valor+ctwa/fbc  (gclid, nome, valor, hashes)
```

**Princípio de reúso:** `capi_dispatcher.py` já faz hash, monta evento CAPI (com
`event_name`) e monta o corpo Google. Generalizamos `dispatch_purchase_conversion` →
`dispatch_conversion(lead, event, value, currency)`. O caminho de Venda atual vira
`event=purchase` — comportamento preservado.

## 5. Componentes (novo/alterado)

| Componente | Mudança | Arquivo |
|---|---|---|
| `pipeline_stages` | **+`conversion_event`** (`text` NULL: `lead\|qualified\|opportunity\|purchase`) **+`conversion_value`** (`numeric` NULL) | migration nova |
| `conversion_events` | **NOVA tabela** — auditoria + dedup; único `(deal_id, event)` | migration nova |
| Gancho etapa→conversão | Em `automation/triggers.py::fire_trigger`, ramo `deal_stage_enter`: resolve `conversion_event` da etapa; se marcado, dispara (background/fail-soft) | `triggers.py` |
| `dispatch_conversion()` | Generaliza `dispatch_purchase_conversion`; mapa canônico→nome-de-evento-Meta; checagem de dedup antes de enviar | `capi_dispatcher.py` |
| `sheets_export.py` | **NOVO** — append de 1 linha por evento na Planilha; service account Google compartilhado na planilha; fail-soft | `campaigns/sheets_export.py` |
| UI config Kanban | Por etapa: `select` de evento + `input` de valor (via skill `frontend-design`) | `frontend` |
| `campaign_id`/`ad_id` (opcional) | Captura `referral.source_id` (ad id) no lead p/ relatório | `meta_parser.py` |

### 5.1 Migrations (esboço)

```sql
-- pipeline_stages: marcação de conversão por etapa
ALTER TABLE pipeline_stages
    ADD COLUMN IF NOT EXISTS conversion_event text NULL,   -- lead|qualified|opportunity|purchase
    ADD COLUMN IF NOT EXISTS conversion_value numeric NULL;

-- auditoria + dedup de eventos de conversão
CREATE TABLE IF NOT EXISTS conversion_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id      uuid NOT NULL REFERENCES leads(id),
    deal_id      uuid NOT NULL REFERENCES deals(id),
    event        text NOT NULL,              -- lead|qualified|opportunity|purchase
    value        numeric NULL,
    currency     text NOT NULL DEFAULT 'BRL',
    platform     text NOT NULL,              -- meta|google|both
    gclid        text NULL,
    ctwa_clid    text NULL,
    sent_meta    boolean NOT NULL DEFAULT false,
    sheet_synced boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (deal_id, event)
);
```

## 6. Fluxo de valores e nomes de evento

- **Valor:** `purchase` = **valor real da venda** (`deals.value`); `qualified`/`opportunity`
  = `conversion_value` fixo da etapa (ex. 50 / 150); `lead` = 0/null.
- **Nomes de evento Meta** (mapa configurável, defaults):
  `qualified → "Lead"`, `opportunity → "Oportunidade_Criada"`, `purchase → "Purchase"`,
  `lead → "Lead"`. (Eventos custom exigem Conversão Personalizada no Gerenciador — fora do código.)
- **Linha da Planilha Google** (colunas conforme o doc da demanda):
  `name, gclid, email, telefone_hash, conversion_name, conversion_date,
  conversion_currency, conversion_value, status_funil`. Append 1 linha por evento;
  importação via **Data Manager / Make** (fora do código).

## 7. Dedup, resiliência, env

- **Dedup:** `UNIQUE (deal_id, event)`. Mover card ida-e-volta não redispara. **Sem
  backfill** de etapas puladas — dispara só a etapa que o card entrou.
- **Fail-soft de ponta a ponta:** falha da Meta, da Planilha ou credencial ausente
  **nunca** quebra o move do Kanban. Linha fica em `conversion_events` com
  `sent_meta=false`/`sheet_synced=false` para varredura de retry.
- **Env-gated:** sem credenciais → no-op logado (seguro em dev/homolog).
- **Variáveis de ambiente novas:**
  `GOOGLE_SHEETS_CONV_ID` (id da planilha), `GOOGLE_SA_JSON` (credencial do service
  account, ou reúso do padrão Google já existente). Já existentes: `META_CAPI_*`.

## 8. Testes

Estendendo o padrão de `tests/test_capi_dispatcher.py`:
- mapeamento `stage.key → conversion_event` (via colunas);
- resolução de valor por tipo (real na venda; fixo nas intermediárias);
- dedup — segundo disparo do mesmo `(deal_id, event)` é no-op;
- formato da linha da Planilha (colunas/ordem exatas);
- evento CAPI correto por tipo canônico (action_source, event_name, user_data);
- fail-soft: exceção em Meta/Sheets não propaga.

## 9. Contrato externo — Prompts de handoff pras IAs dos repos de LP

> Estes prompts são **entregáveis** desta spec. Devem ser colados nos repositórios das
> landing pages / formulários (fora deste CRM). O CRM só garante o **recebimento**; a
> captura na origem é responsabilidade desses repos.

### 9.1 Prompt — Landing Page / Formulário (Google Ads + Meta site)

```
CONTEXTO: Esta landing page gera leads que são enviados ao CRM Canastra. O CRM precisa
dos identificadores de clique de anúncio para atribuir conversões no Google Ads e Meta Ads.
Sua tarefa é capturar esses parâmetros da URL e enviá-los no submit do formulário.

TAREFA:
1. Adicione campos ocultos ao formulário:
   <input type="hidden" name="gclid">
   <input type="hidden" name="fbclid">
   <input type="hidden" name="utm_source">
   <input type="hidden" name="utm_medium">
   <input type="hidden" name="utm_campaign">

2. No carregamento da página, popule esses campos a partir da query string da URL.
   Persista em cookie/localStorage (30 dias) para sobreviver a navegação entre páginas
   antes do submit. Função de referência:
     function getParam(name){var m=window.location.href.match(new RegExp(name+'=([^&]*)'));return m?decodeURIComponent(m[1]):'';}
   Preencher: gclid, fbclid, utm_source, utm_medium, utm_campaign.

3. No submit, faça POST application/json para:
     https://api.canastrainteligencia.com/webhook/landing-page
   com EXATAMENTE este shape (nomes de campo são contrato — não renomear):
   {
     "nome": "<nome>",
     "whatsapp": "<telefone com DDI, só dígitos, ex 5511999999999>",
     "email": "<email>",
     "timestamp": "<ISO8601>",
     "origem": "<slug da LP, ex 'lp-cafe-especial'>",
     "gclid": "<da URL>",
     "fbclid": "<da URL>",
     "utm_source": "<da URL>",
     "utm_medium": "<da URL>",
     "utm_campaign": "<da URL>"
   }

REGRAS:
- Campo ausente → envie string vazia "" (nunca omita a chave).
- O endpoint sempre responde HTTP 200; não trate resposta como validação.
- Não invente novos nomes de campo; o CRM ignora campos fora do contrato acima.
- Telefone: apenas dígitos, com código do país (55). Sem +, espaços ou parênteses.
```

### 9.2 Prompt — Anúncio Click-to-WhatsApp (Meta)

```
CONTEXTO: Campanhas Click-to-WhatsApp (CTWA) da Canastra levam o usuário direto ao
WhatsApp. A Meta anexa um objeto `referral` (com `ctwa_clid`, `source_url`, `headline`,
`body` e o ad id) à PRIMEIRA mensagem. O CRM já captura isso automaticamente pelo webhook
da Meta — NÃO é preciso enviar nada manualmente.

TAREFA (config, não código):
1. Garanta que a conta WhatsApp Business API está conectada ao Business Manager (condição
   obrigatória para a Meta emitir `ctwa_clid`).
2. Ao criar o criativo CTWA, use no `source_url`/deep-link um caminho que identifique o
   segmento/funil (ex.: /atacado, /private-label). O CRM deriva a origem do funil pelo
   PATH do source_url (substring match), então nomes de caminho estáveis importam.
3. Não é necessário passar UTM na CTWA — a atribuição usa `ctwa_clid` + telefone/e-mail.

O CRM cuida de: capturar ctwa_clid/bsuid no lead, e disparar a conversão via Meta CAPI
quando o lead avança no funil.
```

## 10. Fora de escopo (explícito)

- Wire real da Google Ads API via SDK (dev-token) — substituído pela rota da Planilha.
- Importação da Planilha → Google Ads (feita por Data Manager / Make, fora do código).
- Criação de Conversões Personalizadas no Gerenciador da Meta (config manual).
- Qualquer alteração nos repos de LP (só entregamos os prompts de handoff — §9).
- Backfill retroativo de eventos para leads/deals antigos.
