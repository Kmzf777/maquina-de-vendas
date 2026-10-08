# Devolução de conversões para Meta e Google Ads — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O CRM envia automaticamente para a Meta (CAPI for Business Messaging) e para o Google (Data Manager API) as etapas lead → qualificado → oportunidade → venda dos leads que vieram de clique de anúncio, com valor, e mostra o que foi enviado numa aba do /trafego.

**Architecture:** Uma varredura periódica no worker (`conversions-sweep`, 1800 s) lê o banco (entradas da linha do tempo, repasses, orçamentos, vendas), aplica regras de elegibilidade puras e insere na fila `ad_conversions` com `dedupe_key` única. Um sender periódico (`conversions-send`, 300 s) reivindica as pendentes, envia uma por request para a plataforma, e registra sucesso/erro/retentativa. Nada de PII fica na fila: o hash é feito na hora do envio.

**Tech Stack:** Python 3.12, FastAPI, supabase-py (PostgREST), httpx síncrono, pytest; Next.js 16 App Router, React 19, vitest; Postgres (migrations aplicadas à mão).

**Spec:** `docs/superpowers/specs/2026-10-08-conversoes-ads-design.md` — leia antes de começar.

---

## Convenções para todos os tasks

- Worktree: `/root/crm-wt/conversoes-ads`, branch `feat/conversoes-ads`. **Nunca** trabalhe em `/srv/Maquinadevendascanastra` (alvo de deploy, sofre `git reset --hard`).
- Vários agentes trabalham em paralelo no mesmo worktree. **Commite só os seus arquivos** (`git add <caminhos explícitos>`, nunca `git add -A`/`.`). Se der `index.lock`, espere 2 s e tente de novo.
- Testes do backend (não há pytest no host; o venv local está quebrado). Rodar um arquivo:
  ```bash
  docker run --rm --user root -v /root/crm-wt/conversoes-ads:/repo -w /repo/backend \
    -e SUPABASE_URL=https://example.supabase.co -e SUPABASE_SERVICE_KEY=ci-dummy \
    canastra-api:latest sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1; \
    python -m pytest -q -p no:cacheprovider tests/<arquivo>.py"
  ```
  Abaixo isso é abreviado como `PYTEST tests/<arquivo>.py`.
- Testes do frontend: `cd /root/crm-wt/conversoes-ads/frontend && npx vitest run <arquivo>` (se `node_modules` não existir: `npm ci` primeiro).
- Comentários e docstrings em português, no tom do repo (explicam o *porquê*).
- Mensagens de commit: `feat(conversoes): ...` / `test(conversoes): ...`, terminando com a linha
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Env vars lidas com `os.getenv` (mesmo padrão de `app/campaigns/google_ads.py`), não em `app/config.py`.

## Mapa de arquivos

| Arquivo | Task | Responsabilidade |
|---|---|---|
| `supabase/migrations/20261008_ad_conversions.sql` | 1 | Tabelas `ad_conversions`, `ad_conversion_values`; colunas `leads.gbraid/wbraid`; trigger de entrada considera gbraid/wbraid |
| `backend/app/conversions/__init__.py` | 2 | Pacote |
| `backend/app/conversions/eligibility.py` | 2 | Regras puras: cliques, janela, segmento, repasse válido, chaves |
| `backend/app/conversions/hashing.py` | 2 | Normalização + SHA-256 (Meta e Google) |
| `backend/app/conversions/meta.py` | 3 | Payload e envio Meta CAPI Business Messaging |
| `backend/app/conversions/google.py` | 4 | Payload e envio Google Data Manager API |
| `backend/app/conversions/types.py` | 2 | `SendResult` (compartilhado por meta/google/sender) |
| `backend/app/conversions/sweep.py` | 5 | Varredura: candidatos (puro) + I/O |
| `backend/app/conversions/sender.py` | 6 | Claim, janela, envio, backoff |
| `backend/app/conversions/router.py` | 7 | `GET /api/conversions/ads` |
| `backend/app/worker/main.py` | 7 | Registrar as duas tasks |
| `backend/app/main.py` | 7 | Registrar o router |
| `backend/app/leads/service.py`, `backend/app/lp_webhook/*` | 8 | gbraid/wbraid na captura |
| Remoção do caminho antigo | 9 | conversions.py, conversion_log.py, google_export.py, envio do capi_dispatcher, chamadas em triggers/engine/leads router, CSV |
| `backend/scripts/conversoes/calcular_valores.py`, `criar_dataset_meta.py` | 10 | Scripts operacionais |
| `frontend/src/app/api/traffic/conversoes/route.ts`, `frontend/src/components/trafego/conversoes-enviadas.tsx`, `frontend/src/lib/conversoes.ts`, página /trafego | 11 | Aba |
| `docs/setup/conversoes-ads.md` | 12 | Roteiro técnico de configuração e rollout |

**Ondas de paralelismo:** Onda A = Tasks 1, 2, 3, 4, 8, 11, 12 (3 e 4 dependem só das interfaces de `hashing.py`/`types.py` definidas aqui — se a Task 2 ainda não commitou, crie os arquivos exatamente como especificado na Task 2). Onda B = 5, 6, 10. Onda C = 7, 9.

---

### Task 1: Migration

**Files:**
- Create: `supabase/migrations/20261008_ad_conversions.sql`
- Test: `backend/tests/test_ad_conversions_migration.py`

Contexto: migrations deste repo **não** são aplicadas pelo deploy; rodam à mão, são idempotentes e usam `begin; … commit;`. O trigger de entrada da linha do tempo está em `supabase/migrations/20261006b_lead_timeline_triggers.sql` (funções `fn_lead_tem_rastreio`, `fn_lead_entrada_metadata`, `fn_lead_canal` e o trigger de `leads`). Leia esse arquivo inteiro antes.

- [ ] **Step 1: Teste que lê o SQL (padrão de `tests/test_recuperacao_migration_2026_09_09.py`)**

```python
"""A migration de ad_conversions é aplicada à mão — o teste trava o contrato do SQL."""
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "supabase/migrations/20261008_ad_conversions.sql").read_text()


def test_tabela_fila_tem_dedupe_key_unica():
    assert "create table if not exists public.ad_conversions" in SQL.lower()
    assert "dedupe_key      text not null unique" in SQL


def test_status_e_etapas_fechados():
    for v in ("'pendente'", "'enviado'", "'erro'", "'fora_da_janela'", "'ignorado'"):
        assert v in SQL
    for v in ("'lead'", "'qualified'", "'opportunity'", "'purchase'"):
        assert v in SQL


def test_valores_estimados_sem_purchase():
    assert "create table if not exists public.ad_conversion_values" in SQL.lower()
    assert "check (stage in ('lead','qualified','opportunity'))" in SQL


def test_leads_ganham_gbraid_wbraid():
    assert "add column if not exists gbraid text" in SQL
    assert "add column if not exists wbraid text" in SQL


def test_trigger_de_entrada_ve_gbraid_wbraid():
    assert "'gbraid', new.gbraid" in SQL or "'gbraid', p_gbraid" in SQL
    assert "new.gbraid is not distinct from old.gbraid" in SQL


def test_nao_dropa_conversion_events():
    # o script de mesclagem (scripts/bling/mesclar_leads_duplicados.py) ainda a referencia
    assert "drop table" not in SQL.lower()


def test_rls_sem_policy_e_transacao():
    assert "enable row level security" in SQL.lower()
    assert SQL.strip().lower().startswith("--")
    assert "begin;" in SQL.lower() and "commit;" in SQL.lower()
```

- [ ] **Step 2: Rodar e ver falhar** — `PYTEST tests/test_ad_conversions_migration.py` → FAIL (arquivo não existe).

- [ ] **Step 3: Escrever a migration**

```sql
-- 20261008_ad_conversions.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao, DEPOIS da 20261006b_lead_timeline_triggers.sql.
--    Idempotente: pode rodar de novo sem efeito colateral.
--
-- Devolucao de conversoes para Meta e Google Ads (spec
-- docs/superpowers/specs/2026-10-08-conversoes-ads-design.md).
--   1. ad_conversions        fila + registro do que foi enviado (dedupe_key UNIQUE)
--   2. ad_conversion_values  valor estimado por segmento x etapa (aprovado a mao)
--   3. leads.gbraid/wbraid   cliques de iOS do Google
--   4. trigger de entrada    passa a considerar gbraid/wbraid
-- conversion_events (vazia) NAO e dropada: scripts/bling/mesclar_leads_duplicados.py a referencia.

begin;

create table if not exists public.ad_conversions (
  id              uuid primary key default gen_random_uuid(),
  lead_id         uuid not null references public.leads(id) on delete cascade,
  platform        text not null check (platform in ('meta','google')),
  stage           text not null check (stage in ('lead','qualified','opportunity','purchase')),
  sale_id         uuid null references public.sales(id) on delete set null,
  click_id        text not null,
  click_id_type   text not null check (click_id_type in ('ctwa_clid','gclid','gbraid','wbraid')),
  click_at        timestamptz not null,
  campaign_name   text null,
  dedupe_key      text not null unique,
  event_at        timestamptz not null,
  event_id        text not null,
  segment         text not null check (segment in ('atacado','private_label','geral')),
  value           numeric null,
  currency        text not null default 'BRL',
  status          text not null default 'pendente'
                  check (status in ('pendente','enviado','erro','fora_da_janela','ignorado')),
  attempts        int not null default 0,
  next_attempt_at timestamptz not null default now(),
  claimed_at      timestamptz null,
  last_error      text null,
  last_response   jsonb null,
  sent_at         timestamptz null,
  created_at      timestamptz not null default now()
);

create index if not exists ad_conversions_due_idx
  on public.ad_conversions (next_attempt_at) where status = 'pendente';
create index if not exists ad_conversions_event_at_idx
  on public.ad_conversions (event_at desc);
create index if not exists ad_conversions_lead_idx
  on public.ad_conversions (lead_id);

comment on table public.ad_conversions is
  'Fila + auditoria das conversoes devolvidas a Meta/Google. Gravada pela varredura do worker '
  '(app/conversions/sweep.py); enviada por app/conversions/sender.py. Sem PII: o hash e feito no envio.';

alter table public.ad_conversions enable row level security;

create table if not exists public.ad_conversion_values (
  segment     text not null check (segment in ('atacado','private_label','geral')),
  stage       text not null check (stage in ('lead','qualified','opportunity')),
  value       numeric not null check (value >= 0),
  updated_at  timestamptz not null default now(),
  updated_by  text not null,
  primary key (segment, stage)
);

comment on table public.ad_conversion_values is
  'Valor estimado (BRL) por segmento x etapa. Calculado por backend/scripts/conversoes/calcular_valores.py '
  'e gravado so depois de aprovado. Mudar valor reinicia o aprendizado das campanhas.';

alter table public.ad_conversion_values enable row level security;

alter table public.leads add column if not exists gbraid text;
alter table public.leads add column if not exists wbraid text;

-- (a) Recrie aqui, com CREATE OR REPLACE, as funcoes da 20261006b que precisam de gbraid/wbraid:
--     fn_lead_tem_rastreio, fn_lead_entrada_metadata, fn_lead_canal e a funcao do trigger de
--     leads. Copie o corpo ATUAL de cada uma e acrescente os parametros/colunas gbraid e wbraid:
--       * fn_lead_tem_rastreio: gbraid/wbraid preenchido tambem conta como rastreio;
--       * fn_lead_canal: gbraid/wbraid => 'Google Ads' (mesma regra do gclid);
--       * fn_lead_entrada_metadata: inclui 'gbraid', p_gbraid e 'wbraid', p_wbraid no jsonb;
--       * trigger de leads: no UPDATE, compara tambem
--           new.gbraid is not distinct from old.gbraid
--           and new.wbraid is not distinct from old.wbraid
--         e passa new.gbraid/new.wbraid para as funcoes.
--     Assinatura nova = parametros novos NO FIM com default null, para nao quebrar chamadas
--     existentes. Se a assinatura mudar, faca DROP FUNCTION IF EXISTS da antiga ANTES do CREATE
--     (e recrie o trigger), senao o Postgres fica com duas sobrecargas.
--     Mantenha SECURITY DEFINER, search_path fixo e o bloco begin/exception when others then
--     raise warning do arquivo original.

commit;
```

O bloco (a) é instrução para você, não para o arquivo: **substitua-o pelo SQL real** das funções, copiado da 20261006b e modificado como descrito. O arquivo final não pode conter o comentário "(a) Recrie aqui".

- [ ] **Step 4: Rodar os testes** — `PYTEST tests/test_ad_conversions_migration.py` → PASS. Rodar também `PYTEST tests/test_cs_p3_timeline_migration.py` (testa as listas de canal da 20261006b; não deve quebrar).

- [ ] **Step 5: Validar o SQL num Postgres descartável** (sem tocar produção):
```bash
docker run -d --name pg-conv-test -e POSTGRES_PASSWORD=x postgres:15 && sleep 6
docker exec -i pg-conv-test psql -U postgres -c "create table leads(id uuid primary key default gen_random_uuid(), gclid text, fbclid text, ctwa_clid text, meta_ad_id text, utm_source text, utm_medium text, utm_campaign text, created_at timestamptz default now()); create table sales(id uuid primary key default gen_random_uuid()); create table lead_events(id uuid primary key default gen_random_uuid(), lead_id uuid, event_type text not null, old_value text, new_value text, metadata jsonb, created_at timestamptz default now(), occurred_at timestamptz not null default now(), source text, dedupe_key text unique);"
docker exec -i pg-conv-test psql -U postgres -v ON_ERROR_STOP=1 < supabase/migrations/20261008_ad_conversions.sql
docker exec -i pg-conv-test psql -U postgres -v ON_ERROR_STOP=1 < supabase/migrations/20261008_ad_conversions.sql   # 2a vez: idempotente
docker rm -f pg-conv-test
```
Se a 20261006b depender de mais tabelas/funções, crie os stubs mínimos necessários no primeiro `psql -c`. Expected: as duas aplicações sem erro.

- [ ] **Step 6: Commit** — `git add supabase/migrations/20261008_ad_conversions.sql backend/tests/test_ad_conversions_migration.py && git commit -m "feat(conversoes): migration da fila ad_conversions e gbraid/wbraid"`

---

### Task 2: Regras puras (eligibility, hashing, types)

**Files:**
- Create: `backend/app/conversions/__init__.py` (vazio, só docstring)
- Create: `backend/app/conversions/types.py`
- Create: `backend/app/conversions/hashing.py`
- Create: `backend/app/conversions/eligibility.py`
- Test: `backend/tests/test_conversions_eligibility.py`, `backend/tests/test_conversions_hashing.py`

- [ ] **Step 1: Escrever `types.py` e `__init__.py`** (contrato compartilhado com Tasks 3, 4, 6)

```python
# backend/app/conversions/__init__.py
"""Devolução de conversões do CRM para Meta e Google Ads (spec 2026-10-08-conversoes-ads)."""
```

```python
# backend/app/conversions/types.py
"""Tipos compartilhados entre os clientes de plataforma e o sender."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SendResult:
    """Resultado de UM envio. `permanent` = não adianta tentar de novo (payload inválido,
    permissão) — o sender marca `erro` direto em vez de agendar retentativa."""
    ok: bool
    permanent: bool = False
    error: str | None = None
    response: dict[str, Any] | None = field(default=None)
```

- [ ] **Step 2: Testes de hashing**

```python
# backend/tests/test_conversions_hashing.py
import hashlib

from app.conversions.hashing import (
    google_email_hash, google_phone_hash, meta_email_hash, meta_phone_hash, normalize_br_phone,
)


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def test_normalize_br_phone_aceita_mascara_e_ddi():
    assert normalize_br_phone("(34) 99200-9777") == "5534992009777"
    assert normalize_br_phone("+55 34 99200-9777") == "5534992009777"
    assert normalize_br_phone("5534992009777") == "5534992009777"
    assert normalize_br_phone("034992009777") == "5534992009777"  # zero de tronco


def test_normalize_br_phone_vazio_ou_curto_vira_none():
    assert normalize_br_phone(None) is None
    assert normalize_br_phone("") is None
    assert normalize_br_phone("123") is None


def test_meta_phone_so_digitos_com_ddi():
    assert meta_phone_hash("(34) 99200-9777") == _h("5534992009777")


def test_google_phone_e164_com_mais():
    assert google_phone_hash("(34) 99200-9777") == _h("+5534992009777")


def test_meta_email_trim_lower():
    assert meta_email_hash("  Joao@Exemplo.COM ") == _h("joao@exemplo.com")


def test_google_email_gmail_sem_pontos():
    assert google_email_hash("Jo.Ao@gmail.com") == _h("joao@gmail.com")
    assert google_email_hash("jo.ao@empresa.com") == _h("jo.ao@empresa.com")


def test_email_invalido_vira_none():
    assert meta_email_hash("sem-arroba") is None
    assert google_email_hash(None) is None
```

- [ ] **Step 3: Rodar e ver falhar** — `PYTEST tests/test_conversions_hashing.py` → FAIL (ImportError).

- [ ] **Step 4: Implementar `hashing.py`**

```python
# backend/app/conversions/hashing.py
"""Normalização + SHA-256 dos identificadores de usuário.

Meta e Google normalizam DIFERENTE e um hash de formato errado simplesmente não casa (sem
erro nenhum): a Meta quer o telefone só com dígitos e DDI (`5534...`); o Google quer E.164 com
`+` (`+5534...`) e o e-mail do Gmail sem os pontos antes do `@`.
"""
import hashlib
import re

_NAO_DIGITO = re.compile(r"\D+")
_GMAIL = ("gmail.com", "googlemail.com")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalize_br_phone(phone: str | None) -> str | None:
    """Dígitos com DDI 55. Aceita máscara, '+', zero de tronco. Menos de 10 dígitos → None."""
    if not phone:
        return None
    d = _NAO_DIGITO.sub("", phone).lstrip("0")
    if len(d) < 10:
        return None
    if not d.startswith("55") or len(d) <= 11:
        d = "55" + d
    return d


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = email.strip().lower()
    if "@" not in e or e.startswith("@") or e.endswith("@"):
        return None
    return e


def meta_phone_hash(phone: str | None) -> str | None:
    d = normalize_br_phone(phone)
    return _sha256(d) if d else None


def google_phone_hash(phone: str | None) -> str | None:
    d = normalize_br_phone(phone)
    return _sha256("+" + d) if d else None


def meta_email_hash(email: str | None) -> str | None:
    e = _normalize_email(email)
    return _sha256(e) if e else None


def google_email_hash(email: str | None) -> str | None:
    e = _normalize_email(email)
    if not e:
        return None
    local, domain = e.split("@", 1)
    if domain in _GMAIL:
        local = local.replace(".", "")
    return _sha256(f"{local}@{domain}")
```

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversions_hashing.py` → PASS.

- [ ] **Step 6: Testes de elegibilidade**

```python
# backend/tests/test_conversions_eligibility.py
from datetime import datetime, timedelta, timezone

from app.conversions.eligibility import (
    Click, attributed_click, build_dedupe_key, build_event_id, clicks_from_entradas,
    clicks_from_lead_fallback, qualified_handoff_ok, segment_for, stage_allowed,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _entrada(at, **meta):
    return {"occurred_at": at.isoformat(), "metadata": meta}


def test_clicks_from_entradas_separa_por_plataforma():
    entradas = [
        _entrada(T0, ctwa_clid="C1", campanha_nome="PL | WA", meta_ad_id="ad1"),
        _entrada(T0 + timedelta(days=1), gclid="G1", campanha_nome="Atacado Search"),
        _entrada(T0 + timedelta(days=2), gbraid="B1"),
        _entrada(T0 + timedelta(days=3), utm_source="google"),  # sem ID de clique: ignora
    ]
    clicks = clicks_from_entradas(entradas)
    assert [(c.platform, c.click_id_type, c.click_id) for c in clicks] == [
        ("meta", "ctwa_clid", "C1"), ("google", "gclid", "G1"), ("google", "gbraid", "B1"),
    ]
    assert clicks[0].campaign_name == "PL | WA"


def test_fallback_do_lead_so_para_clique_sem_entrada():
    lead = {"ctwa_clid": "C1", "gclid": "G9", "created_at": T0.isoformat()}
    ja = [Click("meta", "C1", "ctwa_clid", T0, None)]
    extra = clicks_from_lead_fallback(lead, ja)
    assert [(c.click_id, c.click_at) for c in extra] == [("G9", T0)]


def test_attributed_click_pega_o_mais_recente_antes_do_evento():
    clicks = [
        Click("meta", "C1", "ctwa_clid", T0, None),
        Click("meta", "C2", "ctwa_clid", T0 + timedelta(days=2), None),
        Click("meta", "C3", "ctwa_clid", T0 + timedelta(days=9), None),  # depois do evento
    ]
    c = attributed_click(clicks, "meta", T0 + timedelta(days=3))
    assert c.click_id == "C2"


def test_attributed_click_respeita_janela_meta_7_dias():
    clicks = [Click("meta", "C1", "ctwa_clid", T0, None)]
    assert attributed_click(clicks, "meta", T0 + timedelta(days=7)) is not None
    assert attributed_click(clicks, "meta", T0 + timedelta(days=7, seconds=1)) is None


def test_attributed_click_google_90_dias():
    clicks = [Click("google", "G1", "gclid", T0, None)]
    assert attributed_click(clicks, "google", T0 + timedelta(days=89)) is not None
    assert attributed_click(clicks, "google", T0 + timedelta(days=91)) is None


def test_segment_for():
    assert segment_for("atacado") == "atacado"
    assert segment_for("private_label") == "private_label"
    for s in ("pending", "consumo", "secretaria", "exportacao", None, ""):
        assert segment_for(s) == "geral"


def test_qualified_handoff_ok_exclui_fallbacks():
    assert qualified_handoff_ok({"at": "x", "motivo": "private label qualificado"})
    assert qualified_handoff_ok({"at": "x", "motivo": "bot de botões da ValerIA: lead pediu atendimento do vendedor"})
    assert not qualified_handoff_ok({"at": "x", "motivo": "IA temporariamente indisponível — atendimento encaminhado ao humano"})
    assert not qualified_handoff_ok({"at": "x", "motivo": "bot de recuperação: lead pediu atendimento do vendedor"})
    assert not qualified_handoff_ok({"at": "x", "motivo": "ESCALONAMENTO — reclamacao sobre atendimento: x"})
    assert not qualified_handoff_ok({"motivo": "lead qualificado"})  # sem data
    assert not qualified_handoff_ok(None)


def test_stage_allowed_ja_era_cliente_so_venda():
    assert stage_allowed("purchase", True)
    for st in ("lead", "qualified", "opportunity"):
        assert not stage_allowed(st, True)
        assert stage_allowed(st, None)
        assert stage_allowed(st, False)


def test_chaves_deterministicas():
    assert build_dedupe_key("meta", "qualified", "C1", None) == "meta:qualified:C1"
    assert build_dedupe_key("google", "purchase", "G1", "sale-1") == "google:purchase:sale-1"
    e1 = build_event_id("qualified", "lead-1", "C1", None)
    assert e1 == build_event_id("qualified", "lead-1", "C1", None)
    assert e1.startswith("qualified:lead-1:") and len(e1) <= 64
    assert build_event_id("purchase", "lead-1", "C1", "sale-1") == "purchase:sale-1"
```

- [ ] **Step 7: Rodar e ver falhar** — `PYTEST tests/test_conversions_eligibility.py` → FAIL.

- [ ] **Step 8: Implementar `eligibility.py`**

```python
# backend/app/conversions/eligibility.py
"""Regras de elegibilidade — funções puras, sem I/O.

O "clique atribuído" de um evento é a entrada mais recente do lead, da mesma plataforma, que
aconteceu ANTES do evento e dentro da janela. `leads.ctwa_clid` é sobrescrito a cada clique
novo, então a fonte do histórico é a linha do tempo (`lead_events` tipo `entrada`).
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Meta: janela de atribuição padrão por clique (7 dias) — e a CAPI recusa event_time > 7 dias.
# Google: clique importável até 90 dias.
WINDOW = {"meta": timedelta(days=7), "google": timedelta(days=90)}
CLICK_TYPES = {"meta": ("ctwa_clid",), "google": ("gclid", "gbraid", "wbraid")}
_PLATFORM_OF = {t: p for p, ts in CLICK_TYPES.items() for t in ts}

# Repasses que NÃO são qualificação: o fallback de LLM fora do ar repassa todo mundo, o bot de
# Recuperação trabalha a base própria (não é tráfego pago) e escalonamento é reclamação.
_MOTIVOS_EXCLUIDOS = ("ia temporariamente indisponível", "bot de recuperação", "escalonamento")

SEGMENTOS = ("atacado", "private_label")


@dataclass(frozen=True)
class Click:
    platform: str
    click_id: str
    click_id_type: str
    click_at: datetime
    campaign_name: str | None


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def clicks_from_entradas(entradas: list[dict[str, Any]]) -> list[Click]:
    """Uma entrada pode ter mais de um ID (raro); cada ID vira um Click."""
    out: list[Click] = []
    for e in entradas:
        at = parse_ts(e.get("occurred_at"))
        meta = e.get("metadata") or {}
        if at is None:
            continue
        for ctype, platform in _PLATFORM_OF.items():
            cid = (meta.get(ctype) or "").strip()
            if cid:
                out.append(Click(platform, cid, ctype, at, meta.get("campanha_nome")))
    return out


def clicks_from_lead_fallback(lead: dict[str, Any], known: list[Click]) -> list[Click]:
    """Lead com ID de clique que nunca virou entrada (4 de 699 no Google em 08/10/2026):
    usa `created_at` como hora do clique."""
    known_ids = {c.click_id for c in known}
    at = parse_ts(lead.get("created_at"))
    if at is None:
        return []
    out = []
    for ctype, platform in _PLATFORM_OF.items():
        cid = (lead.get(ctype) or "").strip()
        if cid and cid not in known_ids:
            out.append(Click(platform, cid, ctype, at, None))
    return out


def attributed_click(clicks: list[Click], platform: str, event_at: datetime) -> Click | None:
    window = WINDOW[platform]
    cands = [c for c in clicks
             if c.platform == platform and c.click_at <= event_at and event_at - c.click_at <= window]
    return max(cands, key=lambda c: c.click_at) if cands else None


def segment_for(lead_stage: str | None) -> str:
    return lead_stage if lead_stage in SEGMENTOS else "geral"


def qualified_handoff_ok(handoff: dict[str, Any] | None) -> bool:
    if not handoff or not parse_ts(handoff.get("at")):
        return False
    motivo = (handoff.get("motivo") or "").strip().lower()
    return not motivo.startswith(_MOTIVOS_EXCLUIDOS)


def stage_allowed(stage: str, ja_era_cliente: bool | None) -> bool:
    """Quem já era cliente só gera venda: lead/qualificado dele ensinariam o algoritmo a
    buscar a base atual. NULL = o sistema não sabe → trata como novo."""
    return stage == "purchase" or ja_era_cliente is not True


def build_dedupe_key(platform: str, stage: str, click_id: str, sale_id: str | None) -> str:
    if stage == "purchase":
        return f"{platform}:purchase:{sale_id}"
    return f"{platform}:{stage}:{click_id}"


def build_event_id(stage: str, lead_id: str, click_id: str, sale_id: str | None) -> str:
    """Mesmo ID nas duas plataformas (event_id na Meta, transactionId no Google)."""
    if stage == "purchase":
        return f"purchase:{sale_id}"
    h = hashlib.sha256(click_id.encode()).hexdigest()[:12]
    return f"{stage}:{lead_id}:{h}"
```

- [ ] **Step 9: Rodar** — `PYTEST tests/test_conversions_eligibility.py tests/test_conversions_hashing.py` → PASS.

- [ ] **Step 10: Commit** — `git add backend/app/conversions/__init__.py backend/app/conversions/types.py backend/app/conversions/hashing.py backend/app/conversions/eligibility.py backend/tests/test_conversions_eligibility.py backend/tests/test_conversions_hashing.py && git commit -m "feat(conversoes): regras puras de elegibilidade e hash por plataforma"`

---

### Task 3: Cliente Meta (CAPI for Business Messaging)

**Files:**
- Create: `backend/app/conversions/meta.py`
- Test: `backend/tests/test_conversions_meta.py`

Referência: https://developers.facebook.com/docs/marketing-api/conversions-api/business-messaging — **abra com WebFetch e confira os nomes dos campos antes de commitar.** Se a doc divergir do código abaixo, siga a doc e ajuste o teste.

Env: `META_CAPI_DATASET_ID`, `META_CAPI_ACCESS_TOKEN`, `META_CAPI_API_VERSION` (default `v23.0`), `META_CAPI_TEST_EVENT_CODE`, `META_WABA_ID`, `CONVERSIONS_TEST_MODE`.

- [ ] **Step 1: Testes**

```python
# backend/tests/test_conversions_meta.py
import hashlib
from datetime import datetime, timezone

import httpx
import pytest

from app.conversions import meta

ROW = {
    "stage": "qualified", "event_at": "2026-10-07T15:00:00+00:00", "event_id": "qualified:L1:abc",
    "click_id": "CTWA1", "value": 120.0, "currency": "BRL",
}
LEAD = {"id": "L1", "wa_id": "5534992009777", "phone": None, "email": " Joao@X.com "}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_build_event_business_messaging():
    ev = meta.build_event(ROW, LEAD, waba_id="WABA9")
    assert ev["event_name"] == "QualifiedLead"
    assert ev["event_time"] == int(datetime(2026, 10, 7, 15, tzinfo=timezone.utc).timestamp())
    assert ev["action_source"] == "business_messaging"
    assert ev["messaging_channel"] == "whatsapp"
    assert ev["event_id"] == "qualified:L1:abc"
    ud = ev["user_data"]
    assert ud["whatsapp_business_account_id"] == "WABA9"
    assert ud["ctwa_clid"] == "CTWA1"
    assert ud["ph"] == [_h("5534992009777")]
    assert ud["em"] == [_h("joao@x.com")]
    assert ev["custom_data"] == {"value": 120.0, "currency": "BRL"}


@pytest.mark.parametrize("stage,name", [
    ("lead", "LeadSubmitted"), ("qualified", "QualifiedLead"),
    ("opportunity", "InitiateCheckout"), ("purchase", "Purchase"),
])
def test_nomes_padrao(stage, name):
    assert meta.build_event({**ROW, "stage": stage}, LEAD, waba_id="W")["event_name"] == name


def test_sem_valor_nao_manda_custom_data():
    ev = meta.build_event({**ROW, "value": None}, LEAD, waba_id="W")
    assert "custom_data" not in ev


def test_payload_em_modo_teste(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "true")
    monkeypatch.setenv("META_CAPI_TEST_EVENT_CODE", "TEST123")
    assert meta.build_payload({"x": 1}) == {"data": [{"x": 1}], "test_event_code": "TEST123"}
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "false")
    assert meta.build_payload({"x": 1}) == {"data": [{"x": 1}]}


def _env(monkeypatch):
    monkeypatch.setenv("META_CAPI_DATASET_ID", "DS1")
    monkeypatch.setenv("META_CAPI_ACCESS_TOKEN", "TOK")
    monkeypatch.setenv("META_WABA_ID", "WABA9")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "false")


def test_send_ok(monkeypatch):
    _env(monkeypatch)
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"events_received": 1, "fbtrace_id": "T"})

    r = meta.send(ROW, LEAD, transport=httpx.MockTransport(handler))
    assert r.ok and not r.permanent
    assert "/DS1/events" in seen["url"] and "access_token=TOK" in seen["url"]


def test_send_400_e_permanente(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"message": "Invalid parameter", "code": 100}}))
    r = meta.send(ROW, LEAD, transport=t)
    assert not r.ok and r.permanent and "Invalid parameter" in r.error


def test_send_500_e_429_sao_transitorios(monkeypatch):
    _env(monkeypatch)
    for code in (500, 429):
        t = httpx.MockTransport(lambda req, c=code: httpx.Response(c, json={"error": {"message": "x"}}))
        r = meta.send(ROW, LEAD, transport=t)
        assert not r.ok and not r.permanent


def test_send_sem_config_e_permanente(monkeypatch):
    monkeypatch.delenv("META_CAPI_DATASET_ID", raising=False)
    r = meta.send(ROW, LEAD)
    assert not r.ok and r.permanent and "META_CAPI_DATASET_ID" in r.error


def test_enabled(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "true")
    assert meta.enabled()
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    assert not meta.enabled()
```

- [ ] **Step 2: Rodar e ver falhar** — `PYTEST tests/test_conversions_meta.py` → FAIL.

- [ ] **Step 3: Implementar**

```python
# backend/app/conversions/meta.py
"""Meta Conversions API for Business Messaging — um evento por request.

CTWA não usa pixel nem `fbc`: a Meta casa o evento pelo `ctwa_clid` + WABA. Um evento por
request de propósito: um único evento fora da janela de 7 dias derruba o lote inteiro, e o
volume (dezenas por dia) não justifica lote.
"""
import os
from typing import Any

import httpx

from app.conversions.eligibility import parse_ts
from app.conversions.hashing import meta_email_hash, meta_phone_hash
from app.conversions.types import SendResult

GRAPH = "https://graph.facebook.com"
EVENT_NAMES = {
    "lead": "LeadSubmitted",
    "qualified": "QualifiedLead",
    "opportunity": "InitiateCheckout",
    "purchase": "Purchase",
}
_TIMEOUT = 15.0


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _truthy("CONVERSIONS_META_ENABLED")


def build_event(row: dict[str, Any], lead: dict[str, Any], *, waba_id: str) -> dict[str, Any]:
    user_data: dict[str, Any] = {
        "whatsapp_business_account_id": waba_id,
        "ctwa_clid": row["click_id"],
    }
    ph = meta_phone_hash(lead.get("wa_id") or lead.get("phone"))
    em = meta_email_hash(lead.get("email"))
    if ph:
        user_data["ph"] = [ph]
    if em:
        user_data["em"] = [em]
    ev: dict[str, Any] = {
        "event_name": EVENT_NAMES[row["stage"]],
        "event_time": int(parse_ts(row["event_at"]).timestamp()),
        "event_id": row["event_id"],
        "action_source": "business_messaging",
        "messaging_channel": "whatsapp",
        "user_data": user_data,
    }
    if row.get("value") is not None:
        ev["custom_data"] = {"value": float(row["value"]), "currency": row.get("currency") or "BRL"}
    return ev


def build_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": [event]}
    code = os.getenv("META_CAPI_TEST_EVENT_CODE")
    if _truthy("CONVERSIONS_TEST_MODE") and code:
        payload["test_event_code"] = code
    return payload


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"HTTP {resp.status_code}: {err.get('message') or resp.text[:300]}"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


def send(row: dict[str, Any], lead: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    for var in ("META_CAPI_DATASET_ID", "META_CAPI_ACCESS_TOKEN", "META_WABA_ID"):
        if not os.getenv(var):
            return SendResult(ok=False, permanent=True, error=f"{var} não configurado")
    version = os.getenv("META_CAPI_API_VERSION") or "v23.0"
    url = f"{GRAPH}/{version}/{os.getenv('META_CAPI_DATASET_ID')}/events"
    payload = build_payload(build_event(row, lead, waba_id=os.getenv("META_WABA_ID")))
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            resp = client.post(url, params={"access_token": os.getenv("META_CAPI_ACCESS_TOKEN")}, json=payload)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, permanent=False, error=f"rede: {exc}")
    if resp.status_code == 200:
        return SendResult(ok=True, response=resp.json())
    permanent = 400 <= resp.status_code < 500 and resp.status_code != 429
    body = None
    try:
        body = resp.json()
    except ValueError:
        pass
    return SendResult(ok=False, permanent=permanent, error=_error_message(resp), response=body)
```

- [ ] **Step 4: Conferir a doc oficial** (WebFetch na URL de referência) — campos `user_data.whatsapp_business_account_id`, `ctwa_clid`, `messaging_channel`, nomes de evento. Ajuste se divergir.

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversions_meta.py` → PASS.

- [ ] **Step 6: Commit** — `git add backend/app/conversions/meta.py backend/tests/test_conversions_meta.py && git commit -m "feat(conversoes): cliente Meta CAPI for Business Messaging"`

---

### Task 4: Cliente Google (Data Manager API)

**Files:**
- Create: `backend/app/conversions/google.py`
- Test: `backend/tests/test_conversions_google.py`

Referências (abra com WebFetch **antes** de implementar e siga a doc se divergir do código abaixo):
- https://developers.google.com/data-manager/api/devguides/events/google-ads/offline/send-events
- https://developers.google.com/data-manager/api/devguides/events/google-ads/offline/upgrade/field-mappings
- Referência REST de `events:ingest` (Destination, ProductAccount, Event, AdIdentifiers, UserData, Consent).

Env: `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN` (já existem), `GOOGLE_ADS_CUSTOMER_ID` (já existe, ex. `186-141-6291`), `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (já existe; se igual ao customer, omitir `loginAccount`), `GOOGLE_ADS_CONVERSION_ACTION_{LEAD,QUALIFIED,OPPORTUNITY,PURCHASE}`, `CONVERSIONS_TEST_MODE`, `CONVERSIONS_GOOGLE_ENABLED`.

- [ ] **Step 1: Testes**

```python
# backend/tests/test_conversions_google.py
import hashlib
import json

import httpx
import pytest

from app.conversions import google

ROW = {
    "stage": "purchase", "event_at": "2026-10-07T15:00:00+00:00", "event_id": "purchase:S1",
    "click_id": "GCLID1", "click_id_type": "gclid", "value": 2570.0, "currency": "BRL",
}
LEAD = {"id": "L1", "wa_id": "5534992009777", "email": "Jo.Ao@gmail.com"}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _env(monkeypatch, test_mode="false"):
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "186-141-6291")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-000-1111")
    monkeypatch.setenv("GOOGLE_ADS_CONVERSION_ACTION_PURCHASE", "777")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", test_mode)


def test_build_event():
    ev = google.build_event(ROW, LEAD)
    assert ev["adIdentifiers"] == {"gclid": "GCLID1"}
    assert ev["transactionId"] == "purchase:S1"
    assert ev["eventTimestamp"] == "2026-10-07T12:00:00-03:00"  # fuso da conta (São Paulo)
    assert ev["conversionValue"] == 2570.0 and ev["currency"] == "BRL"
    ids = ev["userData"]["userIdentifiers"]
    assert {"emailAddress": _h("joao@gmail.com")} in ids
    assert {"phoneNumber": _h("+5534992009777")} in ids


def test_gbraid_vai_no_campo_certo():
    ev = google.build_event({**ROW, "click_id_type": "gbraid", "click_id": "B1"}, LEAD)
    assert ev["adIdentifiers"] == {"gbraid": "B1"}


def test_build_request(monkeypatch):
    _env(monkeypatch, test_mode="true")
    req = google.build_request(ROW, LEAD)
    d = req["destinations"][0]
    assert d["operatingAccount"]["accountId"] == "1861416291"
    assert d["loginAccount"]["accountId"] == "9990001111"
    assert d["productDestinationId"] == "777"
    assert req["validateOnly"] is True
    assert req["encoding"] == "HEX"
    assert req["consent"] == {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}
    assert len(req["events"]) == 1


def test_sem_action_id_da_etapa_e_permanente(monkeypatch):
    _env(monkeypatch)
    r = google.send({**ROW, "stage": "lead"}, LEAD)
    assert not r.ok and r.permanent and "GOOGLE_ADS_CONVERSION_ACTION_LEAD" in r.error


def _transport(status, body):
    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        assert req.headers["Authorization"] == "Bearer AT"
        assert req.url.path.endswith("/v1/events:ingest")
        json.loads(req.content)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_send_ok(monkeypatch):
    _env(monkeypatch)
    r = google.send(ROW, LEAD, transport=_transport(200, {"requestId": "R1"}))
    assert r.ok and r.response == {"requestId": "R1"}


def test_send_400_permanente_500_transitorio(monkeypatch):
    _env(monkeypatch)
    r = google.send(ROW, LEAD, transport=_transport(400, {"error": {"message": "INVALID_ARGUMENT x"}}))
    assert not r.ok and r.permanent and "INVALID_ARGUMENT" in r.error
    r = google.send(ROW, LEAD, transport=_transport(503, {"error": {"message": "x"}}))
    assert not r.ok and not r.permanent


def test_token_falhou_e_transitorio(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
    r = google.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent and "token" in r.error.lower()
```

- [ ] **Step 2: Rodar e ver falhar** — `PYTEST tests/test_conversions_google.py` → FAIL.

- [ ] **Step 3: Implementar**

```python
# backend/app/conversions/google.py
"""Google Data Manager API (`events:ingest`) — conversões offline por clique.

Desde 15/06/2026 o UploadClickConversions da Google Ads API recusa developer tokens que não o
usavam antes; a Data Manager API é o caminho para integração nova e não exige developer token.
Um evento por request: a API não tem partial_failure — um erro rejeita o lote inteiro.
"""
import os
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.conversions.eligibility import parse_ts
from app.conversions.hashing import google_email_hash, google_phone_hash
from app.conversions.types import SendResult

INGEST_URL = "https://datamanager.googleapis.com/v1/events:ingest"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_TZ_CONTA = ZoneInfo("America/Sao_Paulo")  # fuso da conta 186-141-6291
_TIMEOUT = 20.0


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _truthy("CONVERSIONS_GOOGLE_ENABLED")


def _digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def build_event(row: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    ts = parse_ts(row["event_at"]).astimezone(_TZ_CONTA).isoformat(timespec="seconds")
    ids = []
    em = google_email_hash(lead.get("email"))
    ph = google_phone_hash(lead.get("wa_id") or lead.get("phone"))
    if em:
        ids.append({"emailAddress": em})
    if ph:
        ids.append({"phoneNumber": ph})
    ev: dict[str, Any] = {
        "adIdentifiers": {row["click_id_type"]: row["click_id"]},
        "transactionId": row["event_id"],
        "eventTimestamp": ts,
        "currency": row.get("currency") or "BRL",
    }
    if row.get("value") is not None:
        ev["conversionValue"] = float(row["value"])
    if ids:
        ev["userData"] = {"userIdentifiers": ids}
    return ev


def _action_env(stage: str) -> str:
    return f"GOOGLE_ADS_CONVERSION_ACTION_{stage.upper()}"


def build_request(row: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    customer = _digits(os.getenv("GOOGLE_ADS_CUSTOMER_ID"))
    login = _digits(os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    dest: dict[str, Any] = {
        "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": customer},
        "productDestinationId": os.getenv(_action_env(row["stage"])) or "",
    }
    if login and login != customer:
        dest["loginAccount"] = {"accountType": "GOOGLE_ADS", "accountId": login}
    return {
        "destinations": [dest],
        "encoding": "HEX",
        # Brasil não é EEE; a base legal (LGPD) está na política de privacidade.
        "consent": {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"},
        "validateOnly": _truthy("CONVERSIONS_TEST_MODE"),
        "events": [build_event(row, lead)],
    }


def _access_token(client: httpx.Client) -> str | None:
    resp = client.post(TOKEN_URL, data={
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"HTTP {resp.status_code}: {err.get('message') or resp.text[:300]}"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


def send(row: dict[str, Any], lead: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    for var in ("GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
                "GOOGLE_ADS_REFRESH_TOKEN", _action_env(row["stage"])):
        if not os.getenv(var):
            return SendResult(ok=False, permanent=True, error=f"{var} não configurado")
    body = build_request(row, lead)
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            token = _access_token(client)
            if not token:
                return SendResult(ok=False, permanent=False, error="falha ao obter access token do Google")
            resp = client.post(INGEST_URL, headers={"Authorization": f"Bearer {token}"}, json=body)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, permanent=False, error=f"rede: {exc}")
    if resp.status_code == 200:
        return SendResult(ok=True, response=resp.json())
    permanent = 400 <= resp.status_code < 500 and resp.status_code not in (401, 429)
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    return SendResult(ok=False, permanent=permanent, error=_error_message(resp), response=payload)
```

Nota: 401 (token) é transitório de propósito — o refresh token regenerado resolve sem perder a fila.

- [ ] **Step 4: Conferir a doc oficial** (WebFetch) — nomes `operatingAccount`/`loginAccount`/`accountType`, `productDestinationId`, `adIdentifiers`, `userIdentifiers`, `encoding`, `consent`, `validateOnly`, formato de `eventTimestamp`. Ajuste código e teste se divergirem.

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversions_google.py` → PASS.

- [ ] **Step 6: Commit** — `git add backend/app/conversions/google.py backend/tests/test_conversions_google.py && git commit -m "feat(conversoes): cliente Google Data Manager API"`

---

### Task 5: Varredura (sweep)

**Files:**
- Create: `backend/app/conversions/sweep.py`
- Test: `backend/tests/test_conversions_sweep.py`

Depende de: Task 2.

Fontes (todas via `get_supabase()`, paginadas — **o PostgREST corta em 1000 linhas**, use `.range(i, i+999)` em loop até vir menos de 1000):
- `lead_events` com `event_type='entrada'` e `occurred_at >= now-90d` → `lead_id`, `occurred_at`, `metadata`.
- `leads` com `created_at >= now-90d` e (`ctwa_clid` ou `gclid` ou `gbraid` ou `wbraid` não nulos) — fallback de lead sem entrada.
- Para o conjunto de `lead_id`s (em blocos de 200 com `.in_("id", bloco)`):
  - `leads`: `id, stage, ja_era_cliente, metadata, created_at, ctwa_clid, gclid, gbraid, wbraid`
  - todas as `lead_events` `entrada` desses leads (sem corte de data — o clique atribuído pode ser anterior aos 90 dias? não: janela máx. 90 dias; mas busque por lead para não perder entradas antigas que ainda valem)
  - `sales`: `id, lead_id, sold_at, value, status` com `sold_at >= now-90d`
  - `quotes`: `lead_id, status, quoted_at, created_at` com `status in ('enviado','aprovado','convertido')`
  - `lead_events` `etapa` com `metadata->>para_key = 'proposta_enviada'` (filtro PostgREST: `.eq("metadata->>para_key", "proposta_enviada")`) → `lead_id, occurred_at`
- `ad_conversion_values` → dict `{(segment, stage): value}`.

- [ ] **Step 1: Testes da parte pura `build_candidates`**

```python
# backend/tests/test_conversions_sweep.py
from datetime import datetime, timedelta, timezone

from app.conversions.sweep import build_candidates

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
CLICK = NOW - timedelta(days=2)


def _lead(**kw):
    base = {"id": "L1", "stage": "atacado", "ja_era_cliente": None, "metadata": {},
            "created_at": CLICK.isoformat(), "ctwa_clid": "C1", "gclid": None, "gbraid": None, "wbraid": None}
    base.update(kw)
    return base


ENTRADAS = [{"occurred_at": CLICK.isoformat(), "metadata": {"ctwa_clid": "C1", "campanha_nome": "Atacado | WA"}}]
VALUES = {("atacado", "lead"): 5.0, ("atacado", "qualified"): 80.0, ("atacado", "opportunity"): 300.0}


def _keys(rows):
    return sorted(r["dedupe_key"] for r in rows)


def test_lead_com_clique_gera_evento_lead_com_valor():
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]
    r = rows[0]
    assert r["platform"] == "meta" and r["stage"] == "lead" and r["value"] == 5.0
    assert r["segment"] == "atacado" and r["campaign_name"] == "Atacado | WA"
    assert r["event_at"] == CLICK.isoformat() and r["click_id_type"] == "ctwa_clid"
    assert r["status"] == "pendente"


def test_repasse_valido_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1", "meta:qualified:C1"]
    assert next(r for r in rows if r["stage"] == "qualified")["value"] == 80.0


def test_repasse_de_fallback_nao_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": CLICK.isoformat(), "motivo": "IA temporariamente indisponível — x"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_oportunidade_e_venda():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 180, "status": "registrada"},
             {"id": "S2", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 99, "status": "cancelada"}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales,
                            opportunity_at=CLICK + timedelta(hours=20), values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1", "meta:opportunity:C1", "meta:purchase:S1"]
    p = next(r for r in rows if r["stage"] == "purchase")
    assert p["value"] == 180.0 and p["sale_id"] == "S1" and p["event_id"] == "purchase:S1"


def test_venda_fora_da_janela_meta_nao_entra_mas_google_entra():
    entradas = ENTRADAS + [{"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1"}}]
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=10)).isoformat(), "value": 500, "status": None}]
    rows = build_candidates(lead=_lead(), entradas=entradas, sales=sales, opportunity_at=None, values=VALUES,
                            now=CLICK + timedelta(days=11))
    assert "google:purchase:S1" in _keys(rows)
    assert "meta:purchase:S1" not in _keys(rows)


def test_ja_era_cliente_so_venda():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 180, "status": None}]
    lead = _lead(ja_era_cliente=True, metadata={"handoff": {"at": CLICK.isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=sales, opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:purchase:S1"]


def test_segmento_geral_sem_valor_configurado_vai_none():
    rows = build_candidates(lead=_lead(stage="pending"), entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows[0]["segment"] == "geral" and rows[0]["value"] is None


def test_evento_mais_velho_que_a_janela_de_envio_nao_entra():
    # Meta: event_time > 7 dias antes de agora é recusado — não adianta enfileirar.
    old = NOW - timedelta(days=8)
    entradas = [{"occurred_at": old.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    rows = build_candidates(lead=_lead(created_at=old.isoformat()), entradas=entradas, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_lead_sem_entrada_usa_fallback():
    rows = build_candidates(lead=_lead(), entradas=[], sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]
```

- [ ] **Step 2: Rodar e ver falhar** — `PYTEST tests/test_conversions_sweep.py` → FAIL.

- [ ] **Step 3: Implementar `build_candidates` e o I/O**

```python
# backend/app/conversions/sweep.py
"""Varredura: lê o banco e enfileira em `ad_conversions` o que for elegível.

Varredura (e não trigger no banco) de propósito: venda lançada pelo Bling cai num lead
duplicado sem clique, que só é mesclado depois (caso "Jovens com uma missão", call de 01/10).
Relendo a cada 30 min, a venda entra assim que for movida para o lead certo. A idempotência é
da `dedupe_key` UNIQUE + upsert com ignore_duplicates: rodar de novo nunca duplica.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.conversions.eligibility import (
    WINDOW, attributed_click, build_dedupe_key, build_event_id, clicks_from_entradas,
    clicks_from_lead_fallback, parse_ts, qualified_handoff_ok, segment_for, stage_allowed,
)
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(days=90)
_PAGE = 1000
_CHUNK = 200


def _row(*, lead: dict, platform: str, stage: str, click, event_at: datetime, segment: str,
         value: float | None, sale_id: str | None = None) -> dict[str, Any]:
    return {
        "lead_id": lead["id"],
        "platform": platform,
        "stage": stage,
        "sale_id": sale_id,
        "click_id": click.click_id,
        "click_id_type": click.click_id_type,
        "click_at": click.click_at.isoformat(),
        "campaign_name": click.campaign_name,
        "dedupe_key": build_dedupe_key(platform, stage, click.click_id, sale_id),
        "event_at": event_at.isoformat(),
        "event_id": build_event_id(stage, lead["id"], click.click_id, sale_id),
        "segment": segment,
        "value": value,
        "currency": "BRL",
        "status": "pendente",
    }


def build_candidates(*, lead: dict[str, Any], entradas: list[dict[str, Any]], sales: list[dict[str, Any]],
                     opportunity_at: datetime | None, values: dict[tuple[str, str], float],
                     now: datetime) -> list[dict[str, Any]]:
    clicks = clicks_from_entradas(entradas)
    clicks += clicks_from_lead_fallback(lead, clicks)
    segment = segment_for(lead.get("stage"))
    ja_cliente = lead.get("ja_era_cliente")

    # (stage, event_at, value, sale_id)
    eventos: list[tuple[str, datetime, float | None, str | None]] = []
    for c in clicks:
        eventos.append(("lead", c.click_at, values.get((segment, "lead")), None))
    handoff = (lead.get("metadata") or {}).get("handoff")
    if qualified_handoff_ok(handoff):
        eventos.append(("qualified", parse_ts(handoff["at"]), values.get((segment, "qualified")), None))
    if opportunity_at:
        eventos.append(("opportunity", opportunity_at, values.get((segment, "opportunity")), None))
    for s in sales:
        if (s.get("status") or "") == "cancelada":
            continue
        at = parse_ts(s.get("sold_at"))
        if at:
            eventos.append(("purchase", at, float(s["value"]) if s.get("value") is not None else None, s["id"]))

    out: dict[str, dict[str, Any]] = {}
    for stage, event_at, value, sale_id in eventos:
        if not stage_allowed(stage, ja_cliente):
            continue
        for platform in ("meta", "google"):
            if now - event_at > WINDOW[platform]:
                continue  # a plataforma recusaria; não enfileira
            if stage == "lead":
                # o evento lead é o próprio clique — só o clique daquela plataforma
                cands = [c for c in clicks if c.platform == platform and c.click_at == event_at]
                click = max(cands, key=lambda c: c.click_at) if cands else None
            else:
                click = attributed_click(clicks, platform, event_at)
            if click is None:
                continue
            r = _row(lead=lead, platform=platform, stage=stage, click=click, event_at=event_at,
                     segment=segment, value=value, sale_id=sale_id)
            out.setdefault(r["dedupe_key"], r)
    return list(out.values())


# ── I/O ─────────────────────────────────────────────────────────────────────

def _paged(query_factory) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    i = 0
    while True:
        page = query_factory().range(i, i + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        i += _PAGE


def _chunks(ids: list[str]):
    for i in range(0, len(ids), _CHUNK):
        yield ids[i:i + _CHUNK]


def _candidate_lead_ids(sb, since: str) -> list[str]:
    ids = {r["lead_id"] for r in _paged(lambda: sb.table("lead_events").select("lead_id")
                                        .eq("event_type", "entrada").gte("occurred_at", since)) if r.get("lead_id")}
    ids |= {r["id"] for r in _paged(lambda: sb.table("leads").select("id").gte("created_at", since)
                                    .or_("ctwa_clid.not.is.null,gclid.not.is.null,gbraid.not.is.null,wbraid.not.is.null"))}
    return sorted(ids)


def run_sweep(now: datetime | None = None) -> int:
    """Enfileira o que for elegível. Retorna quantas linhas foram oferecidas ao upsert."""
    now = now or datetime.now(timezone.utc)
    since = (now - LOOKBACK).isoformat()
    sb = get_supabase()
    values = {(v["segment"], v["stage"]): float(v["value"])
              for v in (sb.table("ad_conversion_values").select("segment,stage,value").execute().data or [])}
    lead_ids = _candidate_lead_ids(sb, since)
    total = 0
    for bloco in _chunks(lead_ids):
        leads = sb.table("leads").select(
            "id,stage,ja_era_cliente,metadata,created_at,ctwa_clid,gclid,gbraid,wbraid"
        ).in_("id", bloco).execute().data or []
        entradas = sb.table("lead_events").select("lead_id,occurred_at,metadata") \
            .eq("event_type", "entrada").in_("lead_id", bloco).execute().data or []
        sales = sb.table("sales").select("id,lead_id,sold_at,value,status") \
            .in_("lead_id", bloco).gte("sold_at", since).execute().data or []
        quotes = sb.table("quotes").select("lead_id,status,quoted_at,created_at") \
            .in_("lead_id", bloco).in_("status", ["enviado", "aprovado", "convertido"]).execute().data or []
        propostas = sb.table("lead_events").select("lead_id,occurred_at") \
            .eq("event_type", "etapa").eq("metadata->>para_key", "proposta_enviada") \
            .in_("lead_id", bloco).execute().data or []

        opp: dict[str, datetime] = {}
        for q in quotes:
            at = parse_ts(q.get("quoted_at") or q.get("created_at"))
            if at and (q["lead_id"] not in opp or at < opp[q["lead_id"]]):
                opp[q["lead_id"]] = at
        for p in propostas:
            at = parse_ts(p.get("occurred_at"))
            if at and (p["lead_id"] not in opp or at < opp[p["lead_id"]]):
                opp[p["lead_id"]] = at

        rows: list[dict[str, Any]] = []
        for lead in leads:
            lid = lead["id"]
            rows += build_candidates(
                lead=lead,
                entradas=[e for e in entradas if e["lead_id"] == lid],
                sales=[s for s in sales if s["lead_id"] == lid],
                opportunity_at=opp.get(lid),
                values=values,
                now=now,
            )
        if rows:
            sb.table("ad_conversions").upsert(rows, on_conflict="dedupe_key", ignore_duplicates=True).execute()
            total += len(rows)
    logger.info("[CONVERSOES] varredura: %d leads, %d candidatos", len(lead_ids), total)
    return total
```

- [ ] **Step 4: Teste do I/O com supabase mockado** — acrescente ao arquivo de teste:

```python
from unittest.mock import MagicMock

from app.conversions import sweep as sweep_mod


class _Q:
    """Query builder fake: devolve `data` fixo por tabela, ignora filtros."""
    def __init__(self, data):
        self._data = data
    def __getattr__(self, name):
        return lambda *a, **k: self
    def execute(self):
        return MagicMock(data=self._data)


def test_run_sweep_faz_upsert_com_ignore_duplicates(monkeypatch):
    lead = _lead()
    tables = {
        "ad_conversion_values": [{"segment": "atacado", "stage": "lead", "value": 5}],
        "lead_events": [{"lead_id": "L1", "occurred_at": CLICK.isoformat(), "metadata": {"ctwa_clid": "C1"}}],
        "leads": [lead],
        "sales": [], "quotes": [],
    }
    sb = MagicMock()
    sb.table.side_effect = lambda name: _Q(tables.get(name, []))
    upserts = []
    def _table(name):
        if name == "ad_conversions":
            q = MagicMock()
            q.upsert.side_effect = lambda rows, **kw: upserts.append((rows, kw)) or MagicMock()
            return q
        return _Q(tables.get(name, []))
    sb.table.side_effect = _table
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: sb)
    n = sweep_mod.run_sweep(now=NOW)
    assert n >= 1
    rows, kw = upserts[0]
    assert kw == {"on_conflict": "dedupe_key", "ignore_duplicates": True}
    assert any(r["dedupe_key"] == "meta:lead:C1" for r in rows)
```

(Note: o `_Q` devolve a mesma lista para as duas consultas de `lead_events`; o teste só verifica que o upsert é chamado com as opções certas.)

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversions_sweep.py` → PASS.

- [ ] **Step 6: Commit** — `git add backend/app/conversions/sweep.py backend/tests/test_conversions_sweep.py && git commit -m "feat(conversoes): varredura que enfileira as etapas elegíveis"`

---

### Task 6: Sender

**Files:**
- Create: `backend/app/conversions/sender.py`
- Test: `backend/tests/test_conversions_sender.py`

Depende de: Tasks 2, 3, 4.

- [ ] **Step 1: Testes das partes puras**

```python
# backend/tests/test_conversions_sender.py
from datetime import datetime, timedelta, timezone

from app.conversions.sender import BACKOFF, next_state, outside_window
from app.conversions.types import SendResult

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def _row(**kw):
    r = {"id": "R1", "platform": "meta", "stage": "qualified", "attempts": 0,
         "event_at": (NOW - timedelta(days=1)).isoformat(), "click_at": (NOW - timedelta(days=2)).isoformat()}
    r.update(kw)
    return r


def test_outside_window_meta_pelo_evento():
    assert not outside_window(_row(), NOW)
    assert outside_window(_row(event_at=(NOW - timedelta(days=7, minutes=1)).isoformat()), NOW)


def test_outside_window_google_pelo_clique():
    r = _row(platform="google", event_at=(NOW - timedelta(days=30)).isoformat(),
             click_at=(NOW - timedelta(days=89)).isoformat())
    assert not outside_window(r, NOW)
    assert outside_window({**r, "click_at": (NOW - timedelta(days=91)).isoformat()}, NOW)


def test_next_state_ok():
    s = next_state(_row(), SendResult(ok=True, response={"a": 1}), NOW)
    assert s["status"] == "enviado" and s["sent_at"] == NOW.isoformat()
    assert s["attempts"] == 1 and s["claimed_at"] is None and s["last_response"] == {"a": 1}


def test_next_state_transitorio_agenda_backoff():
    s = next_state(_row(attempts=0), SendResult(ok=False, error="HTTP 500"), NOW)
    assert s["status"] == "pendente"
    assert s["next_attempt_at"] == (NOW + timedelta(seconds=BACKOFF[0])).isoformat()
    s = next_state(_row(attempts=2), SendResult(ok=False, error="x"), NOW)
    assert s["next_attempt_at"] == (NOW + timedelta(seconds=BACKOFF[2])).isoformat()


def test_next_state_esgota_tentativas():
    s = next_state(_row(attempts=len(BACKOFF)), SendResult(ok=False, error="x"), NOW)
    assert s["status"] == "erro" and s["last_error"] == "x"


def test_next_state_permanente_vira_erro_direto():
    s = next_state(_row(), SendResult(ok=False, permanent=True, error="HTTP 400: bad"), NOW)
    assert s["status"] == "erro" and s["attempts"] == 1
```

- [ ] **Step 2: Rodar e ver falhar** — `PYTEST tests/test_conversions_sender.py` → FAIL.

- [ ] **Step 3: Implementar**

```python
# backend/app/conversions/sender.py
"""Envia as linhas pendentes de `ad_conversions`.

Claim atômico por `claimed_at` (mesmo padrão de follow_up/scheduler._claim_followup_job):
duas réplicas do worker nunca enviam a mesma linha. Claim com mais de 10 min é considerado
abandonado (worker morreu no meio) e pode ser retomado.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.conversions import google, meta
from app.conversions.eligibility import WINDOW, parse_ts
from app.conversions.types import SendResult
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BACKOFF = (60, 300, 1800, 7200, 43200)  # 1 min, 5 min, 30 min, 2 h, 12 h; a 6ª falha vira erro
_STALE_CLAIM = timedelta(minutes=10)
_CLIENTS = {"meta": meta, "google": google}


def outside_window(row: dict[str, Any], now: datetime) -> bool:
    """Meta recusa event_time > 7 dias antes do envio; Google recusa clique > 90 dias."""
    if row["platform"] == "meta":
        return now - parse_ts(row["event_at"]) > WINDOW["meta"]
    return now - parse_ts(row["click_at"]) > WINDOW["google"]


def next_state(row: dict[str, Any], result: SendResult, now: datetime) -> dict[str, Any]:
    attempts = int(row.get("attempts") or 0) + 1
    upd: dict[str, Any] = {"attempts": attempts, "claimed_at": None, "last_response": result.response}
    if result.ok:
        upd.update(status="enviado", sent_at=now.isoformat(), last_error=None)
    elif result.permanent or attempts > len(BACKOFF):
        upd.update(status="erro", last_error=result.error)
    else:
        upd.update(status="pendente", last_error=result.error,
                   next_attempt_at=(now + timedelta(seconds=BACKOFF[attempts - 1])).isoformat())
    return upd


def _claim(sb, row_id: str, now: datetime) -> bool:
    stale = (now - _STALE_CLAIM).isoformat()
    res = sb.table("ad_conversions").update({"claimed_at": now.isoformat()}) \
        .eq("id", row_id).eq("status", "pendente") \
        .or_(f"claimed_at.is.null,claimed_at.lt.{stale}").execute()
    return bool(res.data)


def run_sender(now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    platforms = [p for p, c in _CLIENTS.items() if c.enabled()]
    counts = {"enviado": 0, "pendente": 0, "erro": 0, "fora_da_janela": 0, "ignorado": 0}
    if not platforms:
        return counts
    sb = get_supabase()
    due = sb.table("ad_conversions").select("*").eq("status", "pendente") \
        .in_("platform", platforms).lte("next_attempt_at", now.isoformat()) \
        .order("next_attempt_at").limit(limit).execute().data or []
    if not due:
        return counts
    lead_ids = sorted({r["lead_id"] for r in due})
    leads = {l["id"]: l for l in (sb.table("leads").select("id,email,phone,wa_id")
                                  .in_("id", lead_ids).execute().data or [])}
    sale_ids = sorted({r["sale_id"] for r in due if r.get("sale_id")})
    canceladas = set()
    if sale_ids:
        canceladas = {s["id"] for s in (sb.table("sales").select("id,status").in_("id", sale_ids)
                                        .execute().data or []) if s.get("status") == "cancelada"}

    for row in due:
        if not _claim(sb, row["id"], now):
            continue
        if outside_window(row, now):
            upd = {"status": "fora_da_janela", "claimed_at": None}
        elif row.get("sale_id") in canceladas:
            upd = {"status": "ignorado", "claimed_at": None, "last_error": "venda cancelada antes do envio"}
        else:
            result = _CLIENTS[row["platform"]].send(row, leads.get(row["lead_id"]) or {})
            upd = next_state(row, result, now)
            if not result.ok:
                logger.warning("[CONVERSOES] %s %s %s falhou: %s", row["platform"], row["stage"], row["id"], result.error)
        sb.table("ad_conversions").update(upd).eq("id", row["id"]).execute()
        counts[upd["status"]] += 1
    logger.info("[CONVERSOES] envio: %s", counts)
    return counts
```

- [ ] **Step 4: Teste do `run_sender` com mocks** — acrescente:

```python
from unittest.mock import MagicMock

from app.conversions import sender as sender_mod


def test_run_sender_plataformas_desligadas_nao_toca_no_banco(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sender_mod.run_sender(now=NOW)["enviado"] == 0
    called.assert_not_called()


def test_run_sender_envia_e_grava(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "true")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    row = {**_row(), "lead_id": "L1", "sale_id": None, "click_id": "C1", "event_id": "e", "value": None}
    updates = []

    class Q:
        def __init__(self, data): self.data = data
        def __getattr__(self, n): return lambda *a, **k: self
        def update(self, u): updates.append(u); return Q([{"id": "R1"}])
        def execute(self): return MagicMock(data=self.data)

    sb = MagicMock()
    sb.table.side_effect = lambda n: Q([row]) if n == "ad_conversions" else Q([{"id": "L1", "wa_id": "5534992009777"}])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={"events_received": 1}))
    counts = sender_mod.run_sender(now=NOW)
    assert counts["enviado"] == 1
    assert updates[-1]["status"] == "enviado"
```

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversions_sender.py` → PASS.

- [ ] **Step 6: Commit** — `git add backend/app/conversions/sender.py backend/tests/test_conversions_sender.py && git commit -m "feat(conversoes): sender com claim atômico, janela e backoff"`

---

### Task 7: Worker + API da aba

**Files:**
- Modify: `backend/app/worker/main.py` (funções de tick + `TASK_SPECS`)
- Create: `backend/app/conversions/router.py`
- Modify: `backend/app/main.py` (registrar router, perto da linha 146/169)
- Test: `backend/tests/test_conversions_router.py`, `backend/tests/test_worker_task_specs_conversoes.py`

Depende de: Tasks 5, 6.

- [ ] **Step 1: Testes**

```python
# backend/tests/test_worker_task_specs_conversoes.py
from app.worker.main import TASK_SPECS


def test_tasks_de_conversao_registradas():
    specs = {name: (kind, secs) for name, kind, _fn, secs in TASK_SPECS}
    assert specs["conversions-sweep"] == ("periodic", 1800)
    assert specs["conversions-send"] == ("periodic", 300)
```

```python
# backend/tests/test_conversions_router.py
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.conversions import router as router_mod
from app.conversions.router import summarize


def test_summarize_conta_por_etapa_plataforma_status():
    rows = [
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "purchase", "platform": "google", "status": "erro"},
    ]
    assert summarize(rows) == [
        {"stage": "purchase", "platform": "google", "status": "erro", "n": 1},
        {"stage": "qualified", "platform": "meta", "status": "enviado", "n": 2},
    ]


def test_endpoint(monkeypatch):
    class Q:
        def __getattr__(self, n): return lambda *a, **k: self
        def execute(self): return MagicMock(data=[{"id": "R1", "stage": "lead", "platform": "meta", "status": "enviado",
                                                   "lead": {"name": "Ana"}}])
    sb = MagicMock(); sb.table.return_value = Q()
    monkeypatch.setattr(router_mod, "get_supabase", lambda: sb)
    from app.main import app
    r = TestClient(app).get("/api/conversions/ads?period=30d")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["lead"]["name"] == "Ana"
    assert body["counts"] == [{"stage": "lead", "platform": "meta", "status": "enviado", "n": 1}]
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Worker** — em `backend/app/worker/main.py`, acrescente as funções antes de `TASK_SPECS` e as entradas no fim da lista:

```python
async def _conversions_sweep_tick() -> None:
    from app.conversions.sweep import run_sweep
    await asyncio.to_thread(run_sweep)


async def _conversions_send_tick() -> None:
    from app.conversions.sender import run_sender
    await asyncio.to_thread(run_sender)
```

```python
    # Devolução de conversões (spec 2026-10-08-conversoes-ads): a varredura relê ~3 mil leads de
    # 90 dias, então roda a cada 30 min; o envio é barato e roda a cada 5. A janela mais curta
    # (Meta, 7 dias) torna essa latência irrelevante.
    ("conversions-sweep", "periodic", _conversions_sweep_tick, 1800),
    ("conversions-send", "periodic", _conversions_send_tick, 300),
```

- [ ] **Step 4: Router**

```python
# backend/app/conversions/router.py
"""API da aba "Conversões enviadas" do /trafego. Proteção admin fica na proxy do Next
(frontend/src/app/api/traffic/conversoes), como nas outras leituras do /trafego."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/conversions", tags=["conversions"])
_TZ = ZoneInfo("America/Sao_Paulo")
_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c = Counter((r["stage"], r["platform"], r["status"]) for r in rows)
    return [{"stage": s, "platform": p, "status": st, "n": n} for (s, p, st), n in sorted(c.items())]


def _range(period: str, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    if date_from or date_to:
        ini = datetime.fromisoformat(date_from).replace(tzinfo=_TZ).isoformat() if date_from else None
        fim = (datetime.fromisoformat(date_to).replace(tzinfo=_TZ) + timedelta(days=1)).isoformat() if date_to else None
        return ini, fim
    days = _PERIODS.get(period)
    if not days:
        return None, None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), None


@router.get("/ads")
async def conversions_ads(period: str = "30d", date_from: str | None = None, date_to: str | None = None,
                          platform: str | None = None, stage: str | None = None, status: str | None = None):
    ini, fim = _range(period, date_from, date_to)
    q = get_supabase().table("ad_conversions").select(
        "id,lead_id,platform,stage,status,event_at,value,currency,segment,campaign_name,"
        "click_id_type,attempts,last_error,sent_at,lead:leads(name)"
    )
    if ini:
        q = q.gte("event_at", ini)
    if fim:
        q = q.lt("event_at", fim)
    if platform:
        q = q.eq("platform", platform)
    if stage:
        q = q.eq("stage", stage)
    if status:
        q = q.eq("status", status)
    rows = q.order("event_at", desc=True).limit(1000).execute().data or []
    return {"rows": rows, "counts": summarize(rows), "truncated": len(rows) == 1000}
```

- [ ] **Step 5: Registrar** — em `backend/app/main.py`: `from app.conversions.router import router as conversions_ads_router` junto aos imports da linha ~146 e `app.include_router(conversions_ads_router)` junto à linha ~169. (O prefixo `/api/conversions` é o mesmo do router antigo; as rotas não colidem — `/ads` é nova.)

- [ ] **Step 6: Rodar** — `PYTEST tests/test_conversions_router.py tests/test_worker_task_specs_conversoes.py` → PASS. Rode também qualquer teste existente que verifique `TASK_SPECS` (`grep -rln TASK_SPECS backend/tests`) e ajuste contagens fixas se houver.

- [ ] **Step 7: Commit** — `git add backend/app/worker/main.py backend/app/conversions/router.py backend/app/main.py backend/tests/test_conversions_router.py backend/tests/test_worker_task_specs_conversoes.py && git commit -m "feat(conversoes): tasks do worker e API da aba de conversões"`

---

### Task 8: Captura de gbraid/wbraid

**Files:**
- Modify: `backend/app/leads/service.py:417-425` (`TRACKING_COLUMNS`)
- Modify: `backend/app/lp_webhook/router.py` e `backend/app/lp_webhook/service.py` (aceitar os campos)
- Modify: `docs/setup/lp-rastreamento.md` e `docs/handoff/lp-utm-attribution.md` (documentar `gbraid`/`wbraid` no payload)
- Test: o teste existente de lp_webhook (`grep -rln "lp_webhook" backend/tests`) — acrescente um caso

- [ ] **Step 1: Teste** — no arquivo de teste de `lp_webhook` existente, acrescente um teste que posta um payload com `gbraid: "B1"` e verifica que `get_or_create_lead` recebeu `tracking` contendo `gbraid == "B1"` (copie o padrão de mocks do teste vizinho que verifica `gclid`). E em `tests/` de leads/service, um teste: `assert "gbraid" in TRACKING_COLUMNS and "wbraid" in TRACKING_COLUMNS`.

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar** — acrescente `"gbraid",  # Google click id de iOS (app → web)` e `"wbraid",  # Google click id de iOS (web → web)` em `TRACKING_COLUMNS` logo após `gclid`; no modelo Pydantic do `lp_webhook/router.py` acrescente `gbraid: str | None = None` e `wbraid: str | None = None` ao lado de `gclid`; confira em `lp_webhook/service.py` que o filtro por `TRACKING_COLUMNS` já repassa os campos novos (se houver lista própria, acrescente). Verifique `derive_traffic_type` (`leads/service.py:441-465`): gbraid/wbraid devem contar como pago, igual a gclid — acrescente se a função listar IDs explicitamente.

- [ ] **Step 4: Docs** — nos dois docs, onde o payload lista `gclid`, acrescente `gbraid` e `wbraid` com uma linha: "o Google manda um destes no lugar do gclid em cliques de iPhone; a LP deve capturá-los da URL igual ao gclid."

- [ ] **Step 5: Rodar** — os testes de lp_webhook e leads/service → PASS.

- [ ] **Step 6: Commit** — só os arquivos tocados.

---

### Task 9: Aposentar o caminho antigo

**Files:**
- Delete: `backend/app/campaigns/conversions.py`, `backend/app/campaigns/conversion_log.py`, `backend/app/campaigns/google_export.py`
- Delete: `backend/tests/test_conversion_log.py`, `backend/tests/test_conversions_orchestrator.py`, `backend/tests/test_google_export.py`, `backend/tests/test_stage_conversion_trigger.py`
- Modify: `backend/app/campaigns/capi_dispatcher.py` → **delete** o arquivo e `backend/tests/test_capi_dispatcher.py` se, depois das remoções, nada mais o importar (`grep -rn capi_dispatcher backend/app`); senão mantenha só o que ainda é importado.
- Modify: `backend/app/automation/triggers.py` (remover `_maybe_fire_stage_conversion` e sua chamada, linhas ~12 e ~96-115)
- Modify: `backend/app/automation/engine.py:~672-679` (remover o bloco que chama `fire_conversion_for_deal_stage`)
- Modify: `backend/app/leads/router.py:~160-191` (`POST /api/leads/{id}/won`: remover só o disparo de conversão; o resto do endpoint fica)
- Modify: `backend/app/campaigns/conversions_router.py` (remover `/google-export.csv` e `/stats`; `/dashboard` fica)
- Modify: `backend/app/campaigns/conversion_analytics.py` (ler `ad_conversions`)
- Modify: `backend/tests/test_conversion_analytics.py`, `backend/tests/test_won_sale.py`, `backend/tests/test_watchdog_checks_2026_07_02.py`, `backend/tests/test_button_flow_effects_2026_08_20.py` (o que referenciar o caminho removido)
- Modify: `scripts/bling/mesclar_leads_duplicados.py:216` (acrescentar `"ad_conversions"` à lista de tabelas com `lead_id`) e `backend/tests/test_cs_p1_mesclagem.py:147` (mesma lista)
- Modify: `frontend/src/components/dashboard/conversions-section.tsx` (remover o botão "Baixar conversões Google (CSV)" ~linha 542 e qualquer uso de `/api/conversions/stats`)
- Delete: `frontend/src/app/api/conversions/google-export/` e `frontend/src/app/api/conversions/stats/` (se só o dashboard antigo usava)
- Modify: `frontend/src/components/deals/pipeline-edit-modal.tsx` (remover o seletor de evento de conversão e o campo de valor, linhas ~56-150 e ~280-286) e `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts:40-52` (parar de aceitar `conversion_event`/`conversion_value`)

Depende de: Tasks 5, 6, 7 (para não deixar a seção do dashboard sem fonte).

- [ ] **Step 1: Mapear** — `grep -rn "fire_stage_conversion\|fire_conversion_for_deal_stage\|conversion_log\|google_export\|capi_dispatcher\|conversion_events\|conversion_event" backend/app frontend/src scripts` e anote cada ocorrência. As migrations antigas e os testes que só **leem SQL de migration** (ex.: `test_recuperacao_migration_2026_09_09.py`, `test_sql_cards_extraviados_2026_09_16.py`, `test_reativacao_lote_completo.py`) **não mudam**.

- [ ] **Step 2: `conversion_analytics.py`** — troque a fonte: onde lia `conversion_events` (campos `event`, `created_at`, `value`), leia `ad_conversions` com `status='enviado'`, mapeando `stage→event` e `event_at→created_at` antes de passar para `build_timeseries`/`aggregate_value_by_traffic` (as funções puras não mudam). Conte cada (lead, stage) uma vez — a mesma etapa vai para Meta **e** Google e não pode contar 2×: deduplique por `(lead_id, stage, sale_id)` antes de agregar. Remova o import de `google_export.conversion_stats`; se o dashboard usava esses números, calcule-os em `conversion_analytics.py` a partir de `ad_conversions` (totais por stage e status). Atualize `tests/test_conversion_analytics.py` para o mock da nova tabela.

- [ ] **Step 3: Remover os gatilhos antigos e os módulos** conforme a lista de arquivos. Em `leads/router.py`, mantenha o endpoint `/won` funcionando (ele registra a venda; a conversão agora sai pela varredura).

- [ ] **Step 4: Mesclagem** — acrescente `"ad_conversions"` às duas listas (script e teste). Uma linha de `ad_conversions` do lead perdedor que colidir em `dedupe_key` com o vencedor: o UPDATE de `lead_id` não muda `dedupe_key`, então não colide — confira lendo como o script move as linhas.

- [ ] **Step 5: Frontend** — remova botão, rotas e campos listados. `npx tsc --noEmit -p frontend` (ou `npm run build` se tsc não pegar o App Router) sem erro novo. `npx vitest run` nos testes de `deals`/`dashboard` existentes → PASS.

- [ ] **Step 6: Suíte inteira do backend** —
```bash
docker run --rm --user root -v /root/crm-wt/conversoes-ads:/repo -w /repo/backend \
  -e SUPABASE_URL=https://example.supabase.co -e SUPABASE_SERVICE_KEY=ci-dummy \
  canastra-api:latest sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1; \
  python -m pytest -q -m 'not integration' -p no:cacheprovider"
```
Expected: verde (baseline ~4437 passed antes deste trabalho; o número muda pelos testes removidos/adicionados). Nenhuma falha nova.

- [ ] **Step 7: Commit** — `git add` explícito de cada arquivo alterado/removido (`git rm` para os deletados) → `git commit -m "refactor(conversoes): aposenta o gatilho por etapa do Kanban e o CSV do Google"`

---

### Task 10: Scripts operacionais

**Files:**
- Create: `backend/scripts/conversoes/__init__.py` (vazio)
- Create: `backend/scripts/conversoes/calcular_valores.py`
- Create: `backend/scripts/conversoes/criar_dataset_meta.py`
- Test: `backend/tests/test_conversoes_calcular_valores.py`

Depende de: Task 2.

- [ ] **Step 1: Teste da parte pura do cálculo**

```python
# backend/tests/test_conversoes_calcular_valores.py
from datetime import datetime, timedelta, timezone

from scripts.conversoes.calcular_valores import propor_valores

T = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_valor_e_receita_em_30_dias_dividida_pelos_leads_da_etapa():
    # 4 leads atacado chegaram a "qualified"; 1 comprou 1000 em 10 dias, 1 comprou kit 120 em 40 dias (fora)
    marcos = [{"lead_id": f"L{i}", "segment": "atacado", "stage": "qualified", "at": T} for i in range(4)]
    vendas = [
        {"lead_id": "L0", "sold_at": T + timedelta(days=10), "value": 1000.0, "kit": False},
        {"lead_id": "L1", "sold_at": T + timedelta(days=40), "value": 120.0, "kit": True},
    ]
    p = propor_valores(marcos, vendas)
    cel = p[("atacado", "qualified")]
    assert cel["n"] == 4
    assert cel["valor"] == 250.0
    assert cel["receita_kit"] == 0.0 and cel["receita_nao_kit"] == 1000.0
    assert cel["pouco_dado"] is True  # n < 20
```

O módulo precisa ser importável como `scripts.conversoes.calcular_valores` a partir de `backend/` (confira como outros testes importam `scripts.*` — ex. `grep -rn "from scripts" backend/tests | head` — e siga o mesmo padrão; se os outros usam `importlib` com caminho, use igual).

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar `calcular_valores.py`**

```python
# backend/scripts/conversoes/calcular_valores.py
"""Propõe o valor estimado por segmento x etapa para `ad_conversion_values`.

valor = receita das vendas em até 30 dias dos leads com clique que atingiram a etapa
        ÷ número desses leads (janela de 180 dias).

Só imprime a proposta. Grava SÓ com --aplicar, depois de aprovada: mudar valor reinicia o
aprendizado das campanhas.

Uso (de dentro do container da API, em /app):
    python -m scripts.conversoes.calcular_valores
    python -m scripts.conversoes.calcular_valores --aplicar --por "Rafael"
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

JANELA_VENDA = timedelta(days=30)
HISTORICO = timedelta(days=180)
N_MINIMO = 20


def propor_valores(marcos: list[dict[str, Any]], vendas: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """marcos: [{lead_id, segment, stage, at}]; vendas: [{lead_id, sold_at, value, kit}]."""
    por_lead = defaultdict(list)
    for v in vendas:
        por_lead[v["lead_id"]].append(v)
    cel: dict[tuple[str, str], dict[str, Any]] = {}
    grupos = defaultdict(list)
    for m in marcos:
        grupos[(m["segment"], m["stage"])].append(m)
    for chave, ms in grupos.items():
        kit = nao_kit = 0.0
        for m in ms:
            for v in por_lead.get(m["lead_id"], []):
                if m["at"] <= v["sold_at"] <= m["at"] + JANELA_VENDA:
                    if v["kit"]:
                        kit += float(v["value"] or 0)
                    else:
                        nao_kit += float(v["value"] or 0)
        n = len(ms)
        cel[chave] = {
            "n": n,
            "valor": round((kit + nao_kit) / n, 2) if n else 0.0,
            "receita_kit": round(kit, 2),
            "receita_nao_kit": round(nao_kit, 2),
            "pouco_dado": n < N_MINIMO,
        }
    return cel


def _carregar(sb, agora: datetime) -> tuple[list[dict], list[dict]]:
    """Marcos com as MESMAS regras da varredura (clique, repasse válido, já era cliente), mas
    sem a janela de envio — aqui é histórico de 180 dias."""
    from app.conversions.eligibility import (
        clicks_from_entradas, clicks_from_lead_fallback, parse_ts, qualified_handoff_ok,
        segment_for, stage_allowed,
    )
    desde = (agora - HISTORICO).isoformat()
    entradas: list[dict] = []
    i = 0
    while True:
        page = sb.table("lead_events").select("lead_id,occurred_at,metadata").eq("event_type", "entrada") \
            .gte("occurred_at", desde).range(i, i + 999).execute().data or []
        entradas += page
        if len(page) < 1000:
            break
        i += 1000
    ids = sorted({e["lead_id"] for e in entradas if e.get("lead_id")})
    marcos: list[dict] = []
    vendas: list[dict] = []
    for j in range(0, len(ids), 200):
        bloco = ids[j:j + 200]
        leads = sb.table("leads").select("id,stage,ja_era_cliente,metadata,created_at,ctwa_clid,gclid,gbraid,wbraid") \
            .in_("id", bloco).execute().data or []
        sales = sb.table("sales").select("id,lead_id,sold_at,value,status").in_("lead_id", bloco) \
            .gte("sold_at", desde).execute().data or []
        sale_ids = [s["id"] for s in sales]
        itens = sb.table("sale_items").select("sale_id,descricao").in_("sale_id", sale_ids).execute().data or [] \
            if sale_ids else []
        kits = {it["sale_id"] for it in itens if "kit degust" in (it.get("descricao") or "").lower()}
        for s in sales:
            at = parse_ts(s.get("sold_at"))
            if s.get("status") != "cancelada" and at:
                vendas.append({"lead_id": s["lead_id"], "sold_at": at, "value": s.get("value"), "kit": s["id"] in kits})
        for lead in leads:
            seg = segment_for(lead.get("stage"))
            ja = lead.get("ja_era_cliente")
            clicks = clicks_from_entradas([e for e in entradas if e["lead_id"] == lead["id"]])
            clicks += clicks_from_lead_fallback(lead, clicks)
            if clicks and stage_allowed("lead", ja):
                primeiro = min(c.click_at for c in clicks)
                marcos.append({"lead_id": lead["id"], "segment": seg, "stage": "lead", "at": primeiro})
            h = (lead.get("metadata") or {}).get("handoff")
            if clicks and qualified_handoff_ok(h) and stage_allowed("qualified", ja):
                marcos.append({"lead_id": lead["id"], "segment": seg, "stage": "qualified", "at": parse_ts(h["at"])})
    return marcos, vendas


def main() -> None:
    from app.db.supabase import get_supabase
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--por", default="script")
    args = ap.parse_args()
    sb = get_supabase()
    marcos, vendas = _carregar(sb, datetime.now(timezone.utc))
    prop = propor_valores(marcos, vendas)
    print(f"{'segmento':<15}{'etapa':<12}{'N':>6}{'valor R$':>12}{'kit R$':>12}{'não-kit R$':>14}  aviso")
    for (seg, st), c in sorted(prop.items()):
        aviso = "N<20: considere usar o valor de 'geral'" if c["pouco_dado"] else ""
        print(f"{seg:<15}{st:<12}{c['n']:>6}{c['valor']:>12.2f}{c['receita_kit']:>12.2f}{c['receita_nao_kit']:>14.2f}  {aviso}")
    if args.aplicar:
        rows = [{"segment": s, "stage": st, "value": c["valor"], "updated_by": args.por,
                 "updated_at": datetime.now(timezone.utc).isoformat()} for (s, st), c in prop.items()]
        sb.table("ad_conversion_values").upsert(rows, on_conflict="segment,stage").execute()
        print(f"gravado: {len(rows)} linhas")


if __name__ == "__main__":
    main()
```

Nota sobre `opportunity`: há poucos dados (orçamentos existem desde 01/10). O script não propõe valor de `opportunity`; na aprovação, o Rafael define manualmente (sugestão: média entre qualified e purchase do segmento) e grava com um `INSERT` documentado em `docs/setup/conversoes-ads.md`.

- [ ] **Step 4: `criar_dataset_meta.py`**

```python
# backend/scripts/conversoes/criar_dataset_meta.py
"""Cria (ou devolve, se já existir) o dataset da Meta ligado ao WABA — passo único.

A CAPI for Business Messaging exige um dataset associado ao WABA. Doc:
https://developers.facebook.com/docs/marketing-api/conversions-api/business-messaging
Uso (container da API): python -m scripts.conversoes.criar_dataset_meta
Saída: o ID para pôr em META_CAPI_DATASET_ID.
"""
import os
import sys

import httpx


def main() -> None:
    waba = os.getenv("META_WABA_ID")
    token = os.getenv("META_CAPI_ACCESS_TOKEN")
    version = os.getenv("META_CAPI_API_VERSION") or "v23.0"
    if not waba or not token:
        sys.exit("defina META_WABA_ID e META_CAPI_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{version}/{waba}/dataset"
    with httpx.Client(timeout=20) as c:
        got = c.get(url, params={"access_token": token})
        if got.status_code == 200 and (got.json().get("data") or []):
            print("dataset já existe:", got.json()["data"][0].get("id"))
            return
        resp = c.post(url, params={"access_token": token})
    resp.raise_for_status()
    print("dataset criado:", resp.json().get("id"))


if __name__ == "__main__":
    main()
```

Antes de commitar, confira na doc (WebFetch) o endpoint exato de criação/consulta do dataset do WABA e ajuste.

- [ ] **Step 5: Rodar** — `PYTEST tests/test_conversoes_calcular_valores.py` → PASS.

- [ ] **Step 6: Commit** — só os arquivos da task.

---

### Task 11: Aba "Conversões enviadas" no /trafego

**Files:**
- Create: `frontend/src/lib/conversoes.ts` (rótulos e tradução de erro — puro)
- Create: `frontend/src/lib/conversoes.test.ts`
- Create: `frontend/src/app/api/traffic/conversoes/route.ts`
- Create: `frontend/src/components/trafego/conversoes-enviadas.tsx`
- Modify: `frontend/src/app/(authenticated)/trafego/page.tsx`

Contrato da API (Task 7): `GET /api/conversions/ads?period=30d|7d|90d|all&date_from&date_to&platform&stage&status` → `{rows: Row[], counts: {stage, platform, status, n}[], truncated: boolean}`, `Row = {id, lead_id, platform, stage, status, event_at, value, currency, segment, campaign_name, click_id_type, attempts, last_error, sent_at, lead: {name} | null}`.

- [ ] **Step 1: Teste do helper**

```ts
// frontend/src/lib/conversoes.test.ts
import { describe, expect, it } from "vitest";
import { STAGE_LABEL, STATUS_LABEL, PLATFORM_LABEL, traduzErro } from "./conversoes";

describe("conversoes", () => {
  it("rotula etapas, status e plataformas", () => {
    expect(STAGE_LABEL.qualified).toBe("Qualificado");
    expect(STATUS_LABEL.fora_da_janela).toBe("Fora da janela");
    expect(PLATFORM_LABEL.google).toBe("Google Ads");
  });
  it("traduz erros conhecidos", () => {
    expect(traduzErro("META_CAPI_DATASET_ID não configurado")).toMatch(/configuração/i);
    expect(traduzErro("HTTP 400: Invalid parameter")).toMatch(/recusou/i);
    expect(traduzErro("falha ao obter access token do Google")).toMatch(/autoriza/i);
    expect(traduzErro(null)).toBe("");
  });
});
```

- [ ] **Step 2: Rodar e ver falhar** — `npx vitest run src/lib/conversoes.test.ts`.

- [ ] **Step 3: Helper**

```ts
// frontend/src/lib/conversoes.ts
// Rótulos e tradução de erro da aba "Conversões enviadas" (/trafego).
export const STAGE_LABEL: Record<string, string> = {
  lead: "Lead", qualified: "Qualificado", opportunity: "Oportunidade", purchase: "Venda",
};
export const STATUS_LABEL: Record<string, string> = {
  pendente: "Pendente", enviado: "Enviado", erro: "Com erro", fora_da_janela: "Fora da janela", ignorado: "Ignorado",
};
export const PLATFORM_LABEL: Record<string, string> = { meta: "Meta Ads", google: "Google Ads" };
export const STAGES = ["lead", "qualified", "opportunity", "purchase"] as const;
export const PLATFORMS = ["meta", "google"] as const;

export function traduzErro(err: string | null | undefined): string {
  if (!err) return "";
  if (/não configurado/i.test(err)) return `Falta configuração no servidor: ${err}`;
  if (/access token/i.test(err)) return "O Google recusou a autorização — regerar o refresh token.";
  if (/HTTP 4\d\d/.test(err)) return `A plataforma recusou o evento: ${err.replace(/^HTTP \d+:\s*/, "")}`;
  if (/HTTP 5\d\d|rede:/i.test(err)) return "A plataforma não respondeu; o sistema tenta de novo sozinho.";
  return err;
}
```

- [ ] **Step 4: Proxy** — `frontend/src/app/api/traffic/conversoes/route.ts`: copie a estrutura de `frontend/src/app/api/traffic/report/route.ts` (checagem `getCurrentUser` admin, `NEXT_PUBLIC_FASTAPI_URL`, `cache: "no-store"`, erros 502/status), repassando os parâmetros `period, date_from, date_to, platform, stage, status` (só os presentes, com `encodeURIComponent`) para `${backendUrl}/api/conversions/ads`.

- [ ] **Step 5: Componente** — `conversoes-enviadas.tsx` (`"use client"`), props `{ period: string; dateFrom: string; dateTo: string; refreshTick: number }`. Estado: filtros `platform`, `stage`, `status` (Select do `@/components/ui/select`, opção "Todas"), `data`, `loading`. `useEffect` busca `/api/traffic/conversoes?...`. Layout no estilo da página (cartões `bg-white border border-[#dedbd6] rounded-[8px]`, texto `#111111`/`#7b7b78`, `Skeleton` no loading):
  - **Grade de contadores:** linhas = `STAGES`, colunas = `PLATFORMS`; cada célula mostra o nº de `enviado` grande e, abaixo, em cinza, `com erro N · fora da janela N · pendente N` (só os não-zero). Somatório a partir de `counts`.
  - **Tabela:** colunas Data (event_at em `America/Sao_Paulo`, `dd/MM HH:mm`), Lead (nome com link `/conversas?lead=<lead_id>` — confira na página de conversas qual query param abre um lead: `grep -rn "searchParams.get(\"lead" frontend/src/app` e use o mesmo), Etapa, Plataforma, Campanha, Valor (`R$` com `toLocaleString("pt-BR")`, `—` se null), Status (ponto colorido: enviado `#0bdf50`, erro `#ff5a4d`, fora_da_janela/ignorado `#7b7b78`, pendente `#ffb020` — mesmo padrão do toast da página) e, se `last_error`, uma linha cinza abaixo com `traduzErro(last_error)`.
  - Se `truncated`, aviso "Mostrando os 1.000 eventos mais recentes — estreite o período."
  - Vazio: "Nenhuma conversão no período."

- [ ] **Step 6: Página** — em `trafego/page.tsx`: estado `const [view, setView] = useState<"campanhas" | "conversoes">("campanhas")`; no header, à esquerda dos filtros, um seletor segmentado de dois botões ("Campanhas" | "Conversões enviadas") com o estilo do botão Atualizar (ativo = `bg-[#111111] text-white`). O switch "Por venda" só aparece em `view === "campanhas"`. No conteúdo, quando `view === "conversoes"` renderize `<ConversoesEnviadas period={period} dateFrom={dateFrom} dateTo={dateTo} refreshTick={refreshTick} />` no lugar do resumo+tabela (o `useEffect` do relatório pode continuar rodando; não precisa condicionar).

- [ ] **Step 7: Verificar** — `npx vitest run src/lib/conversoes.test.ts` → PASS; `npx tsc --noEmit` (na pasta frontend) sem erro novo; `npx eslint src/components/trafego/conversoes-enviadas.tsx src/app/api/traffic/conversoes/route.ts "src/app/(authenticated)/trafego/page.tsx"` sem erro.

- [ ] **Step 8: Commit** — só os arquivos da task.

---

### Task 12: Roteiro técnico de configuração

**Files:**
- Create: `docs/setup/conversoes-ads.md`

Público: o Rafael (técnico). O passo a passo para a gestora de tráfego é outro documento (artefato), feito depois.

- [ ] **Step 1: Escrever** com estas seções, em português, no tom de `docs/setup/google-ads-conexao.md` (leia-o antes):
  1. **O que é** — 3 linhas + link para a spec.
  2. **Variáveis de ambiente** — tabela da §10 da spec, com onde cada uma é usada e default.
  3. **Ordem de ativação** — exatamente a §11 da spec, com os comandos:
     - aplicar a migration: `docker exec -i $(docker ps --format '{{.Names}}' | grep supabase_db | head -1) psql -U postgres -d postgres -v ON_ERROR_STOP=1 < supabase/migrations/20261008_ad_conversions.sql`
     - conferir a fila sem enviar: `select platform, stage, status, count(*) from ad_conversions group by 1,2,3 order by 1,2,3;`
     - valores: `python -m scripts.conversoes.calcular_valores` e `--aplicar --por "<nome>"`; `INSERT` manual para `opportunity` (`insert into ad_conversion_values(segment,stage,value,updated_by) values ('atacado','opportunity',<v>,'<nome>') on conflict (segment,stage) do update set value=excluded.value, updated_by=excluded.updated_by, updated_at=now();`)
     - preencher valor nas pendentes depois de aprovar: `update ad_conversions c set value = v.value from ad_conversion_values v where c.status='pendente' and c.value is null and c.stage=v.stage and c.segment=v.segment;`
     - modo teste: `CONVERSIONS_TEST_MODE=true` + ligar uma plataforma; onde conferir (Events Manager → Test Events; Google: linha `enviado` com `validateOnly`, nada aparece na conta).
     - ligar de verdade: `CONVERSIONS_TEST_MODE=false`, Google primeiro, Meta depois.
  4. **Meta** — criar o token de system user com `whatsapp_business_management` + `whatsapp_business_manage_events`; rodar `python -m scripts.conversoes.criar_dataset_meta`; pôr o ID em `META_CAPI_DATASET_ID`.
  5. **Google** — regerar `GOOGLE_ADS_REFRESH_TOKEN` com os escopos `https://www.googleapis.com/auth/adwords` e `https://www.googleapis.com/auth/datamanager` (mesmo fluxo OAuth de `docs/setup/google-ads-conexao.md`, só acrescentando o escopo); pegar o ID numérico de cada ação "Importar de cliques" (Google Ads → Metas → Conversões → ação → o `ctId=` da URL) e pôr em `GOOGLE_ADS_CONVERSION_ACTION_*`.
  6. **Operação** — o que cada status significa; como reenviar uma linha com erro depois de corrigir a causa (`update ad_conversions set status='pendente', attempts=0, next_attempt_at=now(), last_error=null where id='...';`); como desligar (env `CONVERSIONS_*_ENABLED=false`).
  7. **Verificações pendentes** — §12 da spec.

- [ ] **Step 2: Commit** — `git add docs/setup/conversoes-ads.md && git commit -m "docs(conversoes): roteiro de configuração e ativação"`

---

## Encerramento (orquestrador)

- [ ] Suíte inteira do backend verde (comando da Task 9, Step 6) e vitest do frontend verde (`cd frontend && npx vitest run`).
- [ ] Revisão de código final sobre o diff `origin/master...feat/conversoes-ads`.
- [ ] Artefato passo a passo para a gestora de tráfego (Meta + Google Ads) — antes do deploy.
- [ ] Deploy (`git pull origin master` + `git push origin feat/conversoes-ads:master`) com as duas plataformas **desligadas**, migration aplicada à mão, conferência da fila.
