# Sincronização diária dos públicos PL/Atacado — Plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: superpowers:subagent-driven-development. Os passos usam checkbox (`- [ ]`).

**Objetivo:** criar um job no `canastra_worker` que, todo dia depois da 01:00 (SP), refaz o conteúdo de 2 públicos do Meta (`usersreplace`) e de 2 do Google (Data Manager `audienceMembers:ingest`/`remove`) com os compradores PL e Atacado.

**Arquitetura:** pacote `backend/app/audiences/`.
- Funções puras (normalização, segmento, diff, montagem dos payloads) testadas sem rede.
- Uma classe `Store` concentra todo o acesso ao Supabase, e os testes trocam por um fake.
- Os clientes HTTP recebem um `transport` injetável (`httpx.MockTransport` nos testes).
- O serviço orquestra com lock no Redis e roda cada plataforma em `try` próprio.

**Stack:** Python 3.12, httpx, supabase-py (PostgREST), redis.asyncio, pytest. Os testes rodam em `backend/` com `python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-10-31-sync-publicos-pl-atacado-design.md`.

**Validação prévia da regra (31/10, read-only em produção):** a consulta da Task 1 aplicada à regra do cartão dá:

| Total | PL | Atacado por classe | CNPJ sem classe | Os dois | Fora |
|---|---|---|---|---|---|
| 571 | 78 | 309 | 103 | 35 | 116 |

Isso bate com a tabela do cartão, que conta "só PL" = 78 − 35 = 43 e "só Atacado" = 309 − 35 = 274 ≈ 275.

**Atenção à `null` no SQL:** `segmento` é null para 490 compradores. Por isso a classificação fica em Python, onde `None == 'atacado'` é `False`.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `backend/app/audiences/__init__.py` | vazio |
| `backend/app/audiences/types.py` | dataclasses `Fatos`, `Pessoa`, `Detalhe`; constante `AUDIENCES` |
| `backend/app/audiences/normalize.py` | celular, e-mail, nome, cidade, UF, CEP e hashes de nome/endereço |
| `backend/app/audiences/segment.py` | `dentro_da_janela`, `classificar`, `montar_pessoa` |
| `backend/app/audiences/diff.py` | `ident_hash`, `diff_identificadores` |
| `backend/app/audiences/meta.py` | `build_rows`, `build_batches`, `replace`, `check_audience` |
| `backend/app/audiences/google.py` | `build_member`, `build_body`, `ingest`, `remove` |
| `backend/app/audiences/source.py` | `Store` (Supabase): fatos, detalhes, membros, runs |
| `backend/app/audiences/bling_details.py` | `atualizar_detalhes` (GET /contatos/{id}, só leitura) |
| `backend/app/audiences/service.py` | `run`, `tick`, lock, regra das 01:00 |
| `backend/app/audiences/__main__.py` | CLI `python -m app.audiences [--dry-run]` |
| `backend/app/worker/main.py` | tick `audience-sync` a cada 600 s |
| `supabase/migrations/20261031_4e04_audience_sync.sql` | 3 tabelas + função `audience_sync_facts()` |
| `backend/tests/test_audiences_*.py` | testes por módulo |

---

## Task 0: tipos e normalização (o controlador faz antes dos paralelos)

**Files:**
- Create: `backend/app/audiences/__init__.py`, `types.py`, `normalize.py`
- Test: `backend/tests/test_audiences_normalize_2026_10_31.py`

Interface (`types.py`):

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class Audience:
    key: str            # meta_pl | meta_atacado | google_pl | google_atacado
    platform: str       # meta | google
    segment: str        # pl | atacado
    audience_id: str

AUDIENCES = (
    Audience("meta_pl", "meta", "pl", "120252789539440163"),
    Audience("meta_atacado", "meta", "atacado", "120252789580640163"),
    Audience("google_pl", "google", "pl", "9496018532"),
    Audience("google_atacado", "google", "atacado", "9496602202"),
)

@dataclass
class Fatos:            # uma linha de audience_sync_facts()
    lead_id: str
    ultima_compra: datetime
    receita_365: float
    nome: str | None
    lead_phone: str | None
    lead_email: str | None
    pipeline_pl: bool = False
    pipeline_atacado: bool = False
    tag_pl: bool = False
    tag_atacado: bool = False
    fotolito: bool = False
    produto_pl: bool = False
    segmento: str | None = None
    docs: list[str] = field(default_factory=list)
    fones_bling: list[str] = field(default_factory=list)   # celular_e164 e telefone_e164
    emails_bling: list[str] = field(default_factory=list)
    contatos_bling: list[tuple[str, int]] = field(default_factory=list)  # (account, id)

@dataclass
class Detalhe:          # linha de audience_contact_details
    email: str | None = None
    municipio: str | None = None
    uf: str | None = None
    cep: str | None = None

@dataclass
class Pessoa:
    lead_id: str
    pl: bool
    atacado: bool
    celulares: list[str]      # "55DDD9XXXXXXXX", distintos, ordem estável
    emails: list[str]         # minúsculo, sem espaços, distintos
    nome: str | None          # primeiro nome normalizado
    sobrenome: str | None     # último nome normalizado
    cidade: str | None
    uf: str | None
    cep: str | None           # 8 dígitos
    valor: float              # receita 365 d em BRL
```

`Fatos.from_row(dict)` converte a linha JSON: `ultima_compra` em ISO para datetime aware, `receita_365` para float, e `contatos_bling` de `[{"account","id"}]` para tuplas.

`normalize.py` (reaproveita `app/conversions/hashing.py`):
- `celular_br(raw) -> str | None`: `normalize_br_phone(raw)`; aceita só 13 dígitos com `d[4] == "9"`. O formato antigo de 12 dígitos começando em 6–9 ganha o 9 pela própria `normalize_br_phone`. Fixo (12 dígitos começando em 2–5) → None. `"bling-123"` → None.
- `email(raw) -> str | None`: `strip().lower()`, sem espaços internos, precisa ter um `@` no meio.
- `texto(raw) -> str`: NFKD, sem acento, minúsculo, só `[a-z0-9 ]`, espaços colapsados.
- `nome_sobrenome(raw) -> (str|None, str|None)`: tokens de `texto`; primeiro e último (sobrenome None se houver 1 token só).
- `cidade(raw)`: `texto(raw).replace(" ", "")` ou None.
- `uf(raw)`: 2 letras minúsculas ou None.
- `cep(raw)`: 8 dígitos ou None.
- `sha(s)`: sha256 hex de string já normalizada; `""` se vazia.

Testes (um por caso):
- `celular_br`:
  - `"+55 (34) 99123-4567"` → `"5534991234567"`;
  - `"553491234567"` → `"5534991234567"`;
  - `"553432321000"` → None;
  - `"bling-55"` → None;
  - None → None.
- `email`: `" Fulano@Gmail.COM "` → `"fulano@gmail.com"`; `"semarroba"` → None.
- `nome_sobrenome`: `"José da Silva-Júnior."` → `("jose", "silvajunior")`. A pontuação sai **sem** virar espaço, para bater com "sem pontuação". `"Ana"` → `("ana", None)`.
- `cidade`: `"São João del-Rei"` → `"saojoaodelrei"`. `uf`: `"MG"` → `"mg"`. `cep`: `"38.400-123"` → `"38400123"`; `"123"` → None.

- [ ] Escrever os testes, ver falhar, implementar, ver passar, commit `feat(audiences): tipos e normalizacao (4e0494e0)`.

---

## Task 1: migration (paralela)

**Files:** Create `supabase/migrations/20261031_4e04_audience_sync.sql`

Cabeçalho no padrão de `20261027_da1f_media_retention_log.sql`: cartão, spec, "só cria objetos, reexecutar é seguro, depois SIGUSR1 no PostgREST" e o ROLLBACK com os `drop`.

```sql
create table if not exists public.audience_sync_runs (
  id bigserial primary key,
  run_id uuid not null,
  trigger text not null check (trigger in ('automatica','manual')),
  dry_run boolean not null,
  audience_key text not null,
  platform text not null,
  audience_id text not null,
  pessoas int not null default 0,
  com_celular int not null default 0,
  com_email int not null default 0,
  linhas_enviadas int not null default 0,
  removidos int not null default 0,
  api_response jsonb,
  erro text,
  iniciado_em timestamptz not null default now(),
  terminado_em timestamptz
);
create index if not exists audience_sync_runs_iniciado_idx on public.audience_sync_runs (iniciado_em desc);

create table if not exists public.audience_sync_members (
  audience_key text not null,
  ident_hash text not null,
  ident jsonb not null,
  lead_id uuid,
  primeiro_envio timestamptz not null default now(),
  ultimo_envio timestamptz not null default now(),
  removido_em timestamptz,
  primary key (audience_key, ident_hash)
);

create table if not exists public.audience_contact_details (
  account text not null,
  bling_contact_id bigint not null,
  email text,
  municipio text,
  uf text,
  cep text,
  buscado_em timestamptz not null default now(),
  primary key (account, bling_contact_id)
);
```

- RLS ligado nas 3 tabelas.
- `grant select, insert, update on ... to service_role` e `grant usage, select on sequence public.audience_sync_runs_id_seq to service_role`.
- `select` a `consulta_ro` só em `audience_sync_runs`, dentro de `do $$ begin if exists (select 1 from pg_roles where rolname='consulta_ro') then ... end if; end $$;`.

Função: `public.audience_sync_facts() returns jsonb language sql stable security definer set search_path = public, analytics`.
- Corpo: `select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) from (<consulta>) x`.
- `revoke all on function ... from public, anon, authenticated; grant execute on function ... to service_role;`.
- `<consulta>` é a consulta abaixo, validada em produção. Ela lista **todo** comprador com venda `registrada`; o corte de 365 dias é feito em Python.

```sql
with compradores as (
  select lead_id, max(sold_at) ultima_compra,
         sum(coalesce(value,0)) filter (where sold_at >= now() - interval '365 days') receita_365
  from public.sales where status = 'registrada' and lead_id is not null group by lead_id
),
pip as (
  select d.lead_id, bool_or(p.name ilike '%private label%') pl, bool_or(p.name ilike '%atacado%') at
  from public.deals d join public.pipelines p on p.id = d.pipeline_id group by d.lead_id
),
tg as (
  select lt.lead_id, bool_or(t.name = 'Marca Própria') pl, bool_or(t.name = 'Revenda') at
  from public.lead_tags lt join public.tags t on t.id = lt.tag_id group by lt.lead_id
),
it as (
  select s.lead_id, bool_or(si.descricao ilike '%fotolito%') foto
  from public.sales s join public.sale_items si on si.sale_id = s.id where s.status='registrada' group by s.lead_id
),
pr as (select lead_id, bool_or(product = 'PL') pl from public.sales where status='registrada' group by lead_id),
bc as (
  select l.lead_id,
    array_agg(distinct c.doc_digits) filter (where c.doc_digits is not null) docs,
    array_agg(distinct p) filter (where p is not null) fones,
    array_agg(distinct c.email) filter (where c.email is not null and c.email <> '') emails,
    jsonb_agg(distinct jsonb_build_object('account', l.account, 'id', l.bling_contact_id)) contatos
  from public.lead_bling_contacts l
  join public.bling_contacts c on c.id = l.bling_contact_id and c.account = l.account
  left join lateral unnest(array[c.celular_e164, c.telefone_e164]) p on true
  group by l.lead_id
)
select c.lead_id, c.ultima_compra, coalesce(c.receita_365,0) receita_365, ld.name nome, ld.phone lead_phone, ld.email lead_email,
  coalesce(pip.pl,false) pipeline_pl, coalesce(pip.at,false) pipeline_atacado,
  coalesce(tg.pl,false) tag_pl, coalesce(tg.at,false) tag_atacado,
  coalesce(it.foto,false) fotolito, coalesce(pr.pl,false) produto_pl,
  vc.segmento, coalesce(bc.docs,'{}') docs, coalesce(bc.fones,'{}') fones_bling,
  coalesce(bc.emails,'{}') emails_bling, coalesce(bc.contatos,'[]'::jsonb) contatos_bling
from compradores c join public.leads ld on ld.id = c.lead_id
left join pip using (lead_id) left join tg using (lead_id) left join it using (lead_id)
left join pr using (lead_id) left join analytics.vw_clientes vc using (lead_id) left join bc using (lead_id)
```

Validação sem gravar:
```
ssh ... 'docker exec -i <supabase_db> psql -U postgres -d postgres -v ON_ERROR_STOP=1' <<< "begin; \i ...; select jsonb_array_length(public.audience_sync_facts()); rollback;"
```
(envie o arquivo pelo stdin, entre `begin;` e `rollback;`). O esperado é ~570 linhas.

- [ ] Escrever, validar com begin/rollback, commit `feat(db): tabelas e funcao de fatos da sincronizacao de publicos (4e0494e0)`.

---

## Task 2: segmento e diff (paralela, depende da Task 0)

**Files:** Create `segment.py`, `diff.py`; Test `tests/test_audiences_segment_2026_10_31.py`.

`segment.py`:
- `dentro_da_janela(f: Fatos, agora: datetime) -> bool`: `agora - f.ultima_compra <= timedelta(days=365)`.
- `classificar(f) -> tuple[bool, bool]`:
  - `pl = pipeline_pl or tag_pl or fotolito or produto_pl or segmento == "private_label"`;
  - `at = pipeline_atacado or tag_atacado or segmento == "atacado"`;
  - se `not pl and not at`, `at = any(len(d) == 14 for d in docs)`.
- `montar_pessoa(f, detalhes: dict[tuple[str,int], Detalhe]) -> Pessoa | None`:
  - None se não for PL nem Atacado;
  - celulares: `lead_phone`, depois cada `fones_bling`, por `celular_br`, distintos;
  - e-mails: `lead_email`, `emails_bling` e `detalhes[c].email` de cada contato, por `normalize.email`, distintos;
  - nome/sobrenome de `f.nome`;
  - cidade/UF/CEP do primeiro contato com `Detalhe.cep`;
  - `valor = round(f.receita_365, 2)`.

`diff.py`:
- `ident_hash(ident: dict) -> str`: sha256 de `json.dumps(ident, sort_keys=True, separators=(",", ":"))`.
- `diff_identificadores(antes: set[str], agora: set[str]) -> tuple[set[str], set[str]]`: devolve `(entram, saem)`.

Testes:
- **janela:** 364 dias entra, 366 sai, exatamente 365 entra.
- **segmento**, um teste por critério:
  - PL: `pipeline_pl`, `tag_pl`, `fotolito`, `produto_pl`, `segmento=private_label`;
  - Atacado: `pipeline_atacado`, `tag_atacado`, `segmento=atacado`;
  - CNPJ (14 dígitos) sem classe → Atacado;
  - CPF (11) sem classe → fora (`montar_pessoa` → None);
  - PL + Atacado → os dois True;
  - PL com CNPJ → só PL, porque o CNPJ só vale para quem não caiu em nenhum.
- **pessoa:**
  - celular fixo e `bling-…` não entram;
  - celular duplicado entre lead e Bling aparece 1 vez;
  - e-mail do detalhe entra;
  - endereço vem do detalhe;
  - `segmento=None` não quebra.
- **diff:** antes {a, b}, agora {b, c} → entram {c}, saem {a}.

- [ ] TDD, commit `feat(audiences): regra de segmento e diff (4e0494e0)`.

---

## Task 3: Meta (paralela, depende da Task 0)

**Files:** Create `meta.py`; Test `tests/test_audiences_meta_2026_10_31.py`.

- `GRAPH = "https://graph.facebook.com"`.
- Versão: `os.getenv("META_AUDIENCES_API_VERSION") or "v25.0"`, a mesma de `app/conversions/meta.py`.
- Token: `META_AUDIENCES_ACCESS_TOKEN`. Ausente → `replace` levanta `RuntimeError("META_AUDIENCES_ACCESS_TOKEN não configurado")`.

Montagem:
- `SCHEMA = ["EMAIL","PHONE","FN","LN","CT","ST","ZIP","COUNTRY","LOOKALIKE_VALUE"]`.
- `build_rows(pessoas) -> list[list]`: por pessoa, `zip_longest(emails, celulares)`. Pessoa sem e-mail e sem celular é pulada.
  - Cada linha: `[meta_email_hash(e) or "", meta_phone_hash(c) or "", sha(nome), sha(sobrenome), sha(cidade), sha(uf), sha(cep), sha("br"), valor]`.
  - `meta_*_hash` vêm de `app.conversions.hashing`, e `sha` de `normalize`.
- `build_batches(rows, session_id, max_rows=10000) -> list[dict]`: um dict por lote, `{"payload": {"schema": SCHEMA, "data": [...]}, "session": {"session_id", "batch_seq": i (1..n), "last_batch_flag": i == n, "estimated_num_total": len(rows)}}`. Com 0 linhas, devolve 1 lote vazio com `last_batch_flag` True: substituir por vazio é o certo quando ninguém se qualifica.

Envio:
- `replace(audience_id, pessoas, *, transport=None, session_id=None) -> dict`:
  - `POST {GRAPH}/{ver}/{audience_id}/usersreplace`, form data `payload=json.dumps(...)`, `session=json.dumps(...)` e `access_token`;
  - devolve `{"session_id", "lotes", "linhas", "num_received" (soma), "num_invalid_entries" (soma), "respostas": [...]}`;
  - HTTP ≠ 200 → `RuntimeError` com `error.message` (nunca o token).
- `check_audience(audience_id, *, transport=None) -> dict`: `GET /{audience_id}?fields=name,operation_status,approximate_count_lower_bound,approximate_count_upper_bound,is_value_based`.

Testes, com `httpx.MockTransport` gravando os requests:
- schema e ordem das colunas;
- e-mail e telefone em hash conforme `hashing.py`;
- `LOOKALIKE_VALUE` sem hash;
- pessoa com 2 e-mails e 1 celular gera 2 linhas (a 2ª com PHONE `""`);
- pessoa sem contato é pulada;
- 3 linhas com `max_rows=2` geram 2 lotes com `batch_seq` 1 e 2, `last_batch_flag` só no último e `estimated_num_total` 3;
- `replace` soma `num_received`;
- erro 400 vira RuntimeError sem token na mensagem;
- sem token → RuntimeError.

- [ ] TDD, commit `feat(audiences): envio usersreplace do Meta (4e0494e0)`.

---

## Task 4: Google (paralela, depende da Task 0)

**Files:** Create `google.py`; Test `tests/test_audiences_google_2026_10_31.py`.

- URLs: `https://datamanager.googleapis.com/v1/audienceMembers:ingest` e `...:remove`.
- Token: reusar `app.conversions.google._access_token(client)`, que devolve `(token, erro, auth)`. Token None → `RuntimeError(erro)`.
- `identificadores(p: Pessoa) -> list[dict]`, no máximo 10, nesta ordem:
  - `{"emailAddress": google_email_hash(e)}` por e-mail;
  - `{"phoneNumber": google_phone_hash(c)}` por celular;
  - `{"address": {"givenName": sha(nome), "familyName": sha(sobrenome), "regionCode": "BR", "postalCode": cep}}` se nome, sobrenome e cep existirem.
- `build_body(audience_id, members: list[dict], *, validate_only: bool) -> dict`:
  - `destinations`: `[{"operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": <GOOGLE_ADS_CUSTOMER_ID dígitos>}, "productDestinationId": audience_id}]`, mais `loginAccount` com `GOOGLE_ADS_LOGIN_CUSTOMER_ID` quando for diferente;
  - `audienceMembers: members`;
  - `consent: {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}`, `encoding: "HEX"`;
  - `termsOfService: {"customerMatchTermsOfServiceStatus": "ACCEPTED"}`, `validateOnly`.
  - O corpo do `remove` não leva `termsOfService` nem `consent`.
- `ingest(audience_id, members, *, validate_only, transport=None) -> list[dict]` e `remove(...)`:
  - lotes de 10.000 membros;
  - devolvem a lista de respostas (`requestId`, `fieldWarnings`);
  - HTTP ≠ 200 → `RuntimeError(f"HTTP {status}: {message}")`;
  - lista vazia → não chama a API e devolve `[]`.
- Cada membro de ingest: `{"userData": {"userIdentifiers": identificadores(p)}}`.
- Cada membro de remove: `{"userData": {"userIdentifiers": [ident]}}`, um identificador por membro, porque o diff é por identificador.

Testes com MockTransport:
- o token OAuth vem do POST para `oauth2.googleapis.com/token`. Use `_reset_token_cache()` de `app.conversions.google` no setup e as envs `GOOGLE_ADS_*` via monkeypatch;
- telefone com `+`, e-mail do Gmail sem ponto (via `hashing.py`);
- endereço só com nome + sobrenome + cep;
- no máximo 10 identificadores;
- destino com `loginAccount`;
- `validateOnly` repassado;
- 10.001 membros geram 2 requests;
- 400 vira RuntimeError com a mensagem;
- lista vazia não faz request.

- [ ] TDD, commit `feat(audiences): ingest e remove na Data Manager API (4e0494e0)`.

---

## Task 5: Store e detalhes do Bling (paralela, depende da Task 0)

**Files:** Create `source.py`, `bling_details.py`; Test `tests/test_audiences_bling_details_2026_10_31.py`.

`source.py`, `class Store` (padrão `_Store` de `app/media_retention/service.py`; `sb=None` → `get_supabase()`). Paginação de tabela com `app.db.paginacao.paginar` e `.order()` por chave única.
- `fatos() -> list[Fatos]`: `sb.rpc("audience_sync_facts").execute().data`. É um jsonb array; se vier string, aplicar `json.loads`. Cada linha passa por `Fatos.from_row`.
- `detalhes(chaves: list[tuple[str,int]]) -> dict[tuple[str,int], tuple[Detalhe, datetime]]`: lê `audience_contact_details` por conta, em pedaços de 200 IDs com `.in_()`.
- `salvar_detalhes(rows: list[dict])`: upsert por (`account`, `bling_contact_id`).
- `membros_ativos(audience_key) -> dict[str, dict]`: `{ident_hash: ident}` com `removido_em is null`.
- `upsert_membros(audience_key, rows: list[dict])`: rows com `ident_hash`, `ident`, `lead_id`, `ultimo_envio` e `removido_em: None`. O `primeiro_envio` fica com o default do banco, e o upsert não o manda.
- `marcar_removidos(audience_key, hashes, quando_iso)`: update em pedaços de 200.
- `registrar_run(row: dict)`: insert em `audience_sync_runs`.
- `rodada_automatica_desde(inicio_iso) -> bool`: existe linha `trigger='automatica' and dry_run=false and iniciado_em >= inicio_iso`.

`bling_details.py`:
- `async atualizar_detalhes(chaves, store, *, agora, client_factory=None, max_idade_dias=30) -> dict[(account,id), Detalhe]`:
  - busca no Bling só as chaves sem detalhe ou com `buscado_em` de mais de 30 dias;
  - por conta, um `BlingClient(account=conta)` (`async with`), com `await client.get(f"/contatos/{id}")` → `data`;
  - e-mail: `email` ou, se vazio, `emailNotaFiscal`;
  - município/UF/CEP de `endereco.geral`;
  - erro num contato: log warning e segue, sem gravar esse contato;
  - salva em lote com `store.salvar_detalhes` e devolve o mapa completo (cache + novos);
  - nunca chama método que não seja `get`.

Testes (`client_factory` fake e store fake em memória):
- contato com detalhe recente não é buscado;
- detalhe com 31 dias é buscado de novo;
- `emailNotaFiscal` vira fallback;
- erro num contato não derruba os outros;
- o client fake falha o teste se chamarem `post`/`put`.

- [ ] TDD, commit `feat(audiences): store e enriquecimento de contatos do Bling (4e0494e0)`.

---

## Task 6: serviço, CLI e worker (depois das Tasks 2–5)

**Files:** Create `service.py`, `__main__.py`; Modify `app/worker/main.py` e `tests/test_worker_main.py` (se ele listar os nomes dos ticks); Test `tests/test_audiences_service_2026_10_31.py`.

`service.py`:
- `TZ = ZoneInfo("America/Sao_Paulo")`, `LOCK_KEY = "audience_sync:lock"`, `LOCK_TTL = 3600`.
- `enabled()`: env `AUDIENCE_SYNC_ENABLED` em ("1","true","yes","on").
- `async run(*, trigger, dry_run, store=None, redis=None, agora=None, meta_mod=meta, google_mod=google, bling=bling_details.atualizar_detalhes) -> dict`. Os módulos injetáveis servem aos testes.
  1. `SET LOCK_KEY <run_id> NX EX 3600`; se não pegar, devolve `{"status": "lock"}`.
  2. `fatos` → filtra `dentro_da_janela` → classifica.
  3. `atualizar_detalhes` dos contatos das pessoas selecionadas.
  4. `montar_pessoa`.
  5. Para cada `Audience` de `AUDIENCES`, em `try/except Exception` próprio:
     - **Meta:** `dry_run` → `check_audience` (resposta em `api_response`, `linhas_enviadas` = `len(build_rows)`); real → `replace`.
     - **Google:**
       - monta `ident_hash → (ident, lead_id)` das pessoas atuais e lê `membros_ativos`;
       - calcula o diff;
       - chama `ingest` (todos os atuais) e `remove` (só os que saíram), com `validate_only = dry_run`;
       - fora do dry-run: `upsert_membros` dos atuais e `marcar_removidos` dos que saíram.
     - Em qualquer caso, `registrar_run` com pessoas, `com_celular`, `com_email`, `linhas_enviadas`, `removidos`, `api_response`, `erro` (str da exceção, até 1000 caracteres) e os horários.
  6. Libera o lock só se o valor ainda for o `run_id`.
  7. Devolve um resumo: `{"run_id", "contagem": {"total", "pl", "atacado", "dois", "fora", "cnpj_sem_classe"}, "por_publico": {key: {...}}}`.
- `async tick(*, agora=None, store=None, runner=run)`:
  - não faz nada se `not enabled()` ou se a hora em SP for < 1;
  - `inicio = 01:00 de hoje em SP`, em UTC ISO; se `store.rodada_automatica_desde(inicio)`, não faz nada;
  - senão, `await runner(trigger="automatica", dry_run=False)`.

`__main__.py`: argparse `--dry-run`, chama `asyncio.run(run(trigger="manual", dry_run=args.dry_run))` e imprime o resumo em JSON (`ensure_ascii=False`, `indent=2`).

`worker/main.py`:
- acrescentar `async def _audience_sync_tick()`, que importa `from app.audiences.service import tick` e faz `await tick()`;
- acrescentar `("audience-sync", "periodic", _audience_sync_tick, 600)` em `TASK_SPECS`, com o comentário curto do cartão.

Testes (store, redis, meta, google e bling fakes):
- falha no Meta não impede o Google, e as 4 linhas de run são gravadas, com `erro` na do Meta;
- lock ocupado → `{"status": "lock"}` e nenhum envio;
- dry-run: Meta só `check_audience`, Google com `validate_only=True` e sem `upsert_membros`/`marcar_removidos`;
- quem saiu é removido no Google e marcado;
- tick antes da 01:00 não roda; às 01:05 sem rodada roda; com rodada hoje não roda; desligado não roda;
- contagem do resumo, incluindo "os dois" e "fora".

- [ ] TDD, depois a suíte inteira (`python -m pytest -q`), commit `feat(audiences): servico, CLI e tick diario no worker (4e0494e0)`.

---

## Task 7: modo teste na VPS (o controlador faz)

1. Aplicar a migration em produção (aditiva): `psql -v ON_ERROR_STOP=1 < migration`, depois `docker kill -s SIGUSR1 <supabase_rest>`.
2. Levar o código: `git archive agente/4e0494e0 backend | ssh ... 'rm -rf /root/agente-4e0494e0 && mkdir -p /root/agente-4e0494e0 && tar -x -C /root/agente-4e0494e0'`, e `docker build -t canastra-api:agente-4e0494e0 /root/agente-4e0494e0/backend`.
3. Dry-run: `docker run --rm --env-file /srv/Maquinadevendascanastra/backend/.env -e META_AUDIENCES_ACCESS_TOKEN="$(cat token)" --network canastrainteligencia canastra-api:agente-4e0494e0 python -m app.audiences --dry-run`.
   - O token vai por um arquivo temporário na VPS (`/root/.meta_aud_token`, chmod 600), apagado no fim.
4. Conferir `select ... from audience_sync_runs where dry_run order by id desc limit 4` e a contagem.
5. Apagar a imagem de teste no fim (`docker rmi canastra-api:agente-4e0494e0`).
