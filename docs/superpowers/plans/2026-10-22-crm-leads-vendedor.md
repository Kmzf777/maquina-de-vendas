# CRM leads e vendedor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar a spec `docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md` (cartão b67f1c6b): cadastro único de vendedores, `leads.segmento` separado da fase, origem do lead, evento `qualificado` e dashboard pela D1.

**Architecture:** Onda 0 entrega o contrato (3 módulos Python pequenos e os nomes SQL). Na Onda 1, 4 agentes trabalham em paralelo, cada um com seus próprios arquivos e sua migration. Na Onda 2, um único agente integra o caminho do repasse (`tools.py` e companhia), que é onde todos colidem. Na Onda 3 entram os scripts de backfill e a revisão. Na Onda 4 rodam a suíte completa e os testes `*_pg` no Postgres descartável `crm-scratch-pg-b67f1c6b`.

**Tech Stack:** FastAPI + supabase-py (backend, pytest `asyncio_mode=auto`), Next.js App Router (frontend, vitest), Postgres 17 (Supabase self-hosted), testes SQL via `psql` por ssh, no padrão de `backend/tests/test_repasse_sla_pg.py`.

**Regras para todo subagente:**
- Trabalhe só nos arquivos da sua tarefa.
- TDD: escreva o teste, veja falhar, implemente, veja passar.
- Commit pequeno, com mensagem terminando em `(b67f1c6b)` e a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nada de push, merge, deploy ou escrita em produção. Em produção só se faz SELECT, por `ssh -i "C:\Users\rafae\.ssh\agente_crm" root@173.249.15.11 'docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -tA' < arquivo.sql`.
- Scratch: `docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres`.
- Migrations são idempotentes (`if not exists`, `create or replace`, `drop ... if exists` só quando a spec manda recriar) e trazem `SET LOCAL lock_timeout='5s'` dentro de `begin; … commit;`.
- Testes do backend: `cd backend && python -m pytest -q <arquivos>`.
- Testes do frontend: `cd frontend && npx vitest run <arquivos>`. O `node_modules` é uma junction para `../../../../frontend/node_modules`, criada na Onda 0.

---

## Contrato comum (Onda 0 — fixo; ninguém renomeia)

**SQL**

| Objeto | Definição |
|---|---|
| `public.vendedores` | `id uuid PK references auth.users(id) on delete restrict`, `email text not null unique check (email = lower(email))`, `nome text not null`, `apelidos text[] not null default '{}'`, `segmentos text[] not null default '{}'`, `atende_no_crm boolean not null default true`, `ativo boolean not null default true`, `created_at`, `updated_at timestamptz default now()` |
| `bling_seller_map.vendedor_id` | `uuid references vendedores(id)` |
| `fn_vendedor_id(p text) returns uuid` | stable. Aceita um uuid existente, um e-mail (`lower`) ou um nome/apelido (unaccent+lower, comparado com o `nome` e com cada apelido; também casa pelo 1º token do nome). Se casar com 0 ou com mais de 1 linha, devolve NULL |
| `deals.assigned_to` | `uuid references vendedores(id)` (`alter type uuid using null` — hoje 0 linhas preenchidas) |
| `leads.segmento` | `text check (segmento in ('atacado','private_label','consumo','exportacao'))` + índice `idx_leads_segmento` |
| `fn_lead_b2b(p_lead uuid) returns boolean` | stable. Verdadeiro se `segmento in ('atacado','private_label')`, ou se tem deal em pipeline `name ~* '(atacado\|private label)'`, ou se tem contato Bling com `length(doc_digits)=14`, via `lead_bling_contacts (account, bling_contact_id)` ou `leads.bling_contact_id` |
| fases de `leads.stage` | `pending`, `novo`, `triagem`, `qualificando`, `perdido`. O CHECK `leads_stage_fase_check` entra só na migration f |
| `leads.origem_cadastro` | `text not null default 'inbound' check (origem_cadastro in ('inbound','manual','bling_import','reativacao_import','csv_import'))` |
| `lead_events` tipo `qualificado` | `event_type='qualificado'`, `dedupe_key='qualificado:'||lead_id`, `metadata={criterio:'repasse'\|'score', segmento, b2b, motivo, vendedor_id}`, `source` igual ao do repasse ou `'score'` |
| `dashboard_kpis` | Mesmos parâmetros e mesmas colunas de hoje, mais `contacts_new bigint` no fim |

**Python (criado na Onda 0, com testes)**

```python
# backend/app/vendedores/service.py
def listar(ativos: bool | None = None) -> list[dict]          # linhas de vendedores (cache 60 s)
def resolver_vendedor(chave: str | None) -> str | None        # uuid | e-mail | nome/apelido -> id; ambíguo/nada -> None
def vendedor_do_segmento(segmento: str | None) -> dict | None # 1º vendedor ATIVO com segmento em `segmentos`; consumo/None -> None
def por_id(vendedor_id: str | None) -> dict | None
def limpar_cache() -> None                                     # para testes

# backend/app/leads/segmento.py
SEGMENTOS = ("atacado", "private_label", "consumo", "exportacao")
FASES = ("pending", "novo", "triagem", "qualificando", "perdido")
SEGMENTOS_B2B = ("atacado", "private_label")
def normalizar_segmento(v: str | None) -> str | None   # "Private Label"/"private-label" -> "private_label"; "secretaria"/"pending"/lixo -> None
def fase_valida(v: str | None) -> bool
def lead_e_b2b(lead_id: str) -> bool                   # rpc fn_lead_b2b; erro -> False (fail-soft, loga)

# backend/app/leads/qualificado.py
MOTIVOS_EXCLUIDOS = ("ia temporariamente indisponível", "bot de recuperação", "escalonamento")  # mesmo texto de conversions/eligibility.py
def motivo_qualifica(motivo: str | None) -> bool        # False se o motivo (lower) contém algum excluído
def registrar_qualificado(*, lead_id: str, criterio: str, source: str, occurred_at: str | None = None,
                          segmento: str | None = None, b2b: bool | None = None, motivo: str | None = None,
                          vendedor_id: str | None = None) -> bool   # insert em lead_events; erro/duplicado -> False sem levantar
```

`registrar_repasse` (`backend/app/leads/repasse.py`) passa a chamar `registrar_qualificado(criterio='repasse', …)` depois de gravar o evento de repasse, se `motivo_qualifica(motivo)`. Com isso os dois caminhos de repasse ganham o evento sem mexer em `tools.py` nem `effects.py`.

---

## Onda 0 (coordenador, sequencial)

### Task 0.1: junction do node_modules + baseline

- [ ] `cmd /c mklink /J frontend\node_modules ..\..\..\frontend\node_modules`, rodado na raiz do worktree. O node_modules do repo principal tem as mesmas dependências; conferir com `diff` do `package.json`.
- [ ] Baseline: `cd backend && python -m pytest -q -m "not integration"`. Guardar a lista de falhas que já existem antes da mudança.
- [ ] Baseline do frontend: `cd frontend && npx vitest run`.

### Task 0.2: `app/leads/segmento.py`

**Files:** Create `backend/app/leads/segmento.py`, `backend/tests/test_segmento_b67f.py`

- [ ] Teste:

```python
from app.leads import segmento as s

def test_normaliza():
    assert s.normalizar_segmento("Private Label") == "private_label"
    assert s.normalizar_segmento("private-label") == "private_label"
    assert s.normalizar_segmento(" ATACADO ") == "atacado"
    assert s.normalizar_segmento("exportação") == "exportacao"
    for v in (None, "", "secretaria", "pending", "perdido", "novo", "xyz"):
        assert s.normalizar_segmento(v) is None

def test_fase():
    assert s.fase_valida("triagem") and s.fase_valida("qualificando")
    assert not s.fase_valida("atacado") and not s.fase_valida("secretaria") and not s.fase_valida(None)

def test_b2b_failsoft(monkeypatch):
    class Boom:
        def rpc(self, *a, **k): raise RuntimeError("x")
    monkeypatch.setattr(s, "get_supabase", lambda: Boom())
    assert s.lead_e_b2b("l1") is False

def test_b2b_rpc(monkeypatch):
    class R:
        def __init__(self, d): self.data = d
    class Q:
        def __init__(self, d): self.d = d
        def execute(self): return R(self.d)
    class SB:
        def rpc(self, nome, args):
            assert nome == "fn_lead_b2b" and args == {"p_lead": "l1"}
            return Q(True)
    monkeypatch.setattr(s, "get_supabase", lambda: SB())
    assert s.lead_e_b2b("l1") is True
```

- [ ] Ver falhar, implementar (unicodedata para tirar acento, `re.sub(r"[\s\-]+","_")`), ver passar, commit.

### Task 0.3: `app/vendedores/service.py`

**Files:** Create `backend/app/vendedores/__init__.py`, `backend/app/vendedores/service.py`, `backend/tests/test_vendedores_service_b67f.py`

- [ ] Teste com tabela fake, injetada via monkeypatch de `service._carregar`, que devolve as linhas:

```python
JOAO = {"id": "u-joao", "email": "joao@cafecanastra.com", "nome": "João Brás", "apelidos": ["Joao Bras", "João - Café Canastra"], "segmentos": ["atacado", "private_label"], "atende_no_crm": True, "ativo": True}
ARTHUR = {"id": "u-arthur", "email": "arthur@cafecanastra.com", "nome": "Arthur", "apelidos": ["Arthur - Café Canastra"], "segmentos": ["exportacao"], "atende_no_crm": False, "ativo": True}
RAFAEL = {"id": "u-rafael", "email": "rafael@cafecanastra.com", "nome": "Rafael", "apelidos": [], "segmentos": [], "atende_no_crm": True, "ativo": False}
```

Casos:
- `resolver_vendedor("u-joao")=="u-joao"`
- `resolver_vendedor("JOAO@cafecanastra.com")=="u-joao"`
- `resolver_vendedor("Joao Bras")=="u-joao"`, e o mesmo para "João Brás" e "João - Café Canastra"
- `resolver_vendedor("arthur")=="u-arthur"`
- `resolver_vendedor("Rafael")=="u-rafael"`
- `resolver_vendedor("Vendedor") is None`
- `resolver_vendedor(None) is None`
- `vendedor_do_segmento("exportacao")["id"]=="u-arthur"`
- `vendedor_do_segmento("private_label")["id"]=="u-joao"`
- `vendedor_do_segmento("consumo") is None`
- `vendedor_do_segmento(None) is None`
- Ambíguo: com dois vendedores de 1º nome "Ana", `resolver_vendedor("Ana") is None`.

- [ ] Implementar. `_carregar()` faz `select * from vendedores` (cache de 60 s por `time.monotonic`). A normalização tira acento, passa para minúsculas e compara com o nome completo, com cada apelido e com o 1º token do nome. Se der erro ao carregar, devolve `[]` e loga. Ver passar, commit.

### Task 0.4: `app/leads/qualificado.py` + gancho em `registrar_repasse`

**Files:** Create `backend/app/leads/qualificado.py`, `backend/tests/test_qualificado_b67f.py`. Modify `backend/app/leads/repasse.py`.

- [ ] Testes:
  - `motivo_qualifica("handoff proativo — âncoras")` é True; `motivo_qualifica("IA temporariamente indisponível (fallback)")` é False; `motivo_qualifica(None)` é True.
  - `registrar_qualificado` faz insert com `event_type='qualificado'`, `dedupe_key='qualificado:L'` e a metadata do contrato.
  - Se o insert levanta exceção, a função devolve False e não propaga.
  - `registrar_repasse(..., motivo="bot de recuperação")` não chama `registrar_qualificado`.
  - Com motivo comum, chama uma vez, com `criterio='repasse'`, o mesmo `occurred_at`, `segmento` e `vendedor_id`.
- [ ] Implementar. Rodar `python -m pytest -q tests/test_qualificado_b67f.py tests/test_repasse_evento.py`. Commit.

### Task 0.5: commit do contrato

- [ ] Commit "contrato onda 0". As tarefas da Onda 1 partem deste commit.

---

## Onda 1 (4 agentes em paralelo)

### Task A: vendedores (B2)

**Files (exclusivos):**
- `supabase/migrations/20261022a_vendedores.sql`
- `backend/app/automation/variables.py`
- `backend/app/watchdog/service.py`
- `frontend/src/app/api/vendedores/route.ts` (novo)
- `frontend/src/components/**/deal-detail-sidebar.tsx`, `deal-card.tsx`, `lead-detail-modal.tsx`, `crm-perfil-tab.tsx`
- `frontend/src/app/api/deals/route.ts`
- `frontend/src/lib/types.ts` (só o campo `assigned_to` de deal)
- testes correspondentes, mais `backend/tests/test_vendedores_pg.py` (novo)

- [ ] Migration a, conforme o contrato:
  - cria `vendedores` e `fn_vendedor_id`;
  - cria `bling_seller_map.vendedor_id`;
  - altera `deals.assigned_to` para uuid FK, guardado por `do $$ … if (select data_type …)='text' and not exists(select 1 from deals where assigned_to is not null)`. Se houver linha preenchida, `raise exception`;
  - RLS em `vendedores`: select para `authenticated`, escrita só para service_role;
  - `grant select on vendedores to authenticated, consulta_ro`; `grant execute on function fn_vendedor_id(text) to authenticated, service_role, consulta_ro`.
  - Não insere linhas (isso é o F1).
- [ ] `test_vendedores_pg.py`, no padrão de `test_repasse_sla_pg.py`, com env `B67F_PSQL`, `begin…rollback` e ids `b67f1c6b-…`. Semeia `auth.users` e `vendedores` e cobre:
  - `fn_vendedor_id` por uuid, por e-mail em maiúsculas, por 'Joao Bras' contra o nome 'João Brás', por apelido;
  - 'Vendedor' devolve NULL; o caso ambíguo devolve NULL;
  - `deals.assigned_to` recusa uuid fora de `vendedores`.
- [ ] Aplicar a migration 2× no scratch (idempotência). Rodar o teste pg.
- [ ] `variables._fill_seller_var`: troca `team_users` por `vendedores.service.por_id(lead.assigned_to)["nome"]`. Atualizar `test_automation_variables.py`.
- [ ] `watchdog.check_handoff_sla`: pula o lead cujo vendedor (`assigned_to`, ou `metadata.handoff.vendedor_id`) tem `atende_no_crm=false`. Teste novo em `test_watchdog_handoff_sla_lead.py`.
- [ ] Frontend:
  - `GET /api/vendedores?ativos=1` devolve `{id,nome,email}[]` (supabase server client, padrão de `api/users/route.ts`).
  - Componente `VendedorSelect` (`frontend/src/components/vendedor-select.tsx`): lista de seleção com opção "Sem vendedor", grava o id.
  - Usar o componente na sidebar do deal, no modal do lead e no `crm-perfil-tab`.
  - `deal-card` mostra a inicial do nome, buscado por id.
  - `api/deals` POST/PATCH valida uuid. Vitest para `VendedorSelect` e para a validação.
- [ ] `npx vitest run` nos arquivos tocados e `npx tsc --noEmit -p .` sem erro novo. Commit por item.

### Task B: segmento (B9)

**Files (exclusivos):**
- `supabase/migrations/20261022b_segmento.sql`, `supabase/migrations/20261022f_stage_fase_check.sql`
- `backend/app/leads/service.py`, exceto `vendor_user_id_for_segment`, que é da Onda 2
- `backend/app/automation/engine.py`, `backend/app/automation/triggers.py`, `backend/app/campaigns/node_registry.py`
- `frontend/src/lib/constants.ts`, `frontend/src/app/(authenticated)/qualificacao/page.tsx`, `conversas/chat-list.tsx`, `api/conversations/route.ts`, `leads/page.tsx`, `chat-header*`, `lib/lead-overview.ts`, `cadence-flow/constants.ts`, `api/leads/[id]/route.ts`
- testes correspondentes + `backend/tests/test_segmento_pg.py` (novo)

- [ ] Migration b: coluna `segmento` + índice + `fn_lead_b2b` (contrato) + `grant execute … to authenticated, service_role, consulta_ro`.
- [ ] Migration f:
  - pré-checagem `do $$ if exists(select 1 from leads where stage not in (fases)) then raise exception 'rodar F3 antes' $$`;
  - depois `alter table leads add constraint leads_stage_fase_check check (stage in ('pending','novo','triagem','qualificando','perdido')) not valid; validate constraint`;
  - `alter column stage set default 'pending'`.
- [ ] `test_segmento_pg.py`:
  - `fn_lead_b2b` é verdadeiro por segmento, por pipeline "João - Atacado", por contato Bling com CNPJ (via `lead_bling_contacts` e via `leads.bling_contact_id`);
  - é falso para consumo sem CNPJ e para CPF;
  - o CHECK de segmento recusa 'secretaria';
  - a migration f falha com stage 'atacado' presente e passa depois de o stage virar fase.
- [ ] `leads/service.py`:
  - `reset_lead` grava `stage='triagem'`;
  - `CATEGORY_PIPELINE_NAMES`, `move_deal_to_vendor_pipeline`, `mark_deal_qualificado`, `ensure_segment_deal` e `_perdido_target_for_category` recebem o segmento já normalizado. Quem chama passa `lead.segmento`, sem mudar a assinatura; a troca nos chamadores é da Onda 2;
  - helper novo `segmento_do_lead(lead: dict) -> str | None`: devolve `normalizar_segmento(lead.get("segmento"))` e, se for None, `normalizar_segmento(lead.get("stage"))` (transição: lead que ainda não passou pelo backfill);
  - testes em `test_leads_service_segmento_b67f.py`.
- [ ] `node_registry`:
  - vocabulário `fase_lead` = FASES;
  - `segmento_lead` = SEGMENTOS;
  - a ação `move_stage` passa a ter o rótulo "Mover fase" e as opções de `fase_lead`;
  - a validação de ativação recusa valor fora da lista.
- [ ] `engine._execute_action('move_stage')` ignora (loga e não grava) valor que não seja fase.
- [ ] `triggers` (`stage_enter`/`in_stage`): quando o valor configurado for segmento, compara com `lead.segmento`; quando for fase, com `stage`.
- [ ] Testes de engine e registry.
- [ ] Frontend:
  - `AGENT_STAGES` passa a ser os segmentos, mais o filtro "Em triagem" (`stage='triagem'`);
  - kanban `qualificacao`, abas de `chat-list`, filtro de `api/conversations` (`leads.segmento`), filtro de `leads`, cor do `chat-header` e `stageLabel` passam a ler `segmento`, com reserva no `stage` antigo enquanto o backfill não roda;
  - `api/leads/[id]` PATCH aceita `segmento` (validado) e `stage` (só fase);
  - vitest dos helpers.
- [ ] Commit por item.

### Task C: origem + dashboard (B8 + parte de 5)

**Files (exclusivos):**
- `supabase/migrations/20261022c_origem_cadastro.sql`
- `supabase/migrations/20261022d_qualificado_dashboard.sql`, só as partes `dashboard_kpis` e `dashboard_funnel_conversion`; a taxa usa o evento `qualificado` do contrato
- `backend/app/campaigns/traffic_report.py`, `backend/app/bling/contacts.py` (só o payload de criação de lead)
- `backend/tests/test_cs_p3_timeline_migration.py`
- `frontend/src/app/(authenticated)/dashboard/page.tsx`, `components/kpi-card.tsx`, `lib/dashboard-mappers.ts`, `app/api/dashboard/kpis/route.ts`
- `app/api/leads/route.ts` e `app/api/leads/import/route.ts`: grava `origem_cadastro` e troca o default 'secretaria' por 'triagem'
- `lib/lead-origin.ts`
- testes + `backend/tests/test_origem_dashboard_pg.py` (novo)

- [ ] Ler em produção (SELECT `pg_get_functiondef`) a definição vigente de `dashboard_kpis`, `dashboard_funnel_conversion`, `fn_lead_canal` (todas as sobrecargas), `fn_lead_events_leads_entrada`, `fn_lead_tem_rastreio` e de quem chama `fn_lead_canal`. Guardar cópia literal em `scripts/leads_vendedor/defs_antes/*.sql`, que alimenta o rollback.
- [ ] Migration c:
  - coluna `origem_cadastro`;
  - `fn_lead_canal` com `p_origem text default null` no fim: drop da assinatura antiga + create, na mesma transação, reaplicando os grants. Regra: se `p_origem in ('bling_import','reativacao_import')`, devolve 'Bling' logo depois das regras de click-id;
  - atualizar quem chama passando `NEW.origem_cadastro`/`l.origem_cadastro`.
- [ ] Gatilho de entrada:
  - no INSERT, se não tem rastreio e `origem_cadastro='inbound'`, grava `entrada` com canal 'Orgânico', `source='inbound'` e a dedupe_key `entrada:lead:<id>:inicial` de hoje;
  - no UPDATE só de `meta_ad_id`, sem `entrada` existente, grava a `entrada`, e não "enriquece o nada";
  - com rastreio chegando em menos de 30 min, a fusão atual atualiza o canal.
- [ ] Migration d, parte dashboard. Partir **literalmente** da versão vigente (`20261019_repasse_sla.sql`) e mudar só:
  - `leads_new`/`leads_prev` = `count(distinct lead_id)` da 1ª `entrada` de cada lead caindo no período, `join leads` com `origem_cadastro not in ('bling_import','reativacao_import')` e `coalesce(ja_era_cliente,false)=false`;
  - `contacts_new` = a contagem antiga por `created_at`;
  - `qualification_rate` = leads distintos com `qualificado` no período ÷ leads atendidos no período (conversas com mensagem `role='user'` e resposta `sent_by in ('agent','valeria_botoes')` no período).
  
  `dashboard_funnel_conversion`: o cohort vira o mesmo conjunto D1. DROP + CREATE com grants.
- [ ] `test_origem_dashboard_pg.py`:
  - D1 exclui importado e `ja_era_cliente`;
  - reentrada não conta duas vezes;
  - `contacts_new` conta tudo;
  - taxa = 1/2 num cenário semeado;
  - entrada Orgânico no INSERT inbound sem rastreio;
  - importado não ganha entrada;
  - `meta_ad_id` sozinho gera entrada;
  - `fn_lead_canal(..., 'bling_import')` = 'Bling'.
  
  Aplicar c e d 2× no scratch.
- [ ] `traffic_report`:
  - `derive_channel` ganha a regra Bling, igual ao SQL;
  - `_lead_cols` inclui `origem_cadastro`;
  - `_fetch_leads` exclui importados e `ja_era_cliente`.
  
  Atualizar o teste de espelho para ler a migration c e os testes `test_traffic_report*`.
- [ ] `bling/contacts.py`: o payload de lead grava `status='active'` e `origem_cadastro='bling_import'`. Teste em `test_bling_contacts.py`.
- [ ] Frontend:
  - `KpiCard` aceita a prop `hint` (tooltip com o `title` + ícone "i", conforme o padrão do projeto);
  - card "Todos os contatos" (`contacts_new`);
  - tooltips com o texto exato da spec;
  - `mapKpis`/`KpisRow` com `contacts_new`;
  - `api/leads` POST grava `origem_cadastro:'manual'`, import grava `'csv_import'`, e o default de `stage` vira 'triagem';
  - `lead-origin.ts` usa `origem_cadastro` quando existir;
  - vitest de `dashboard-mappers` e `lead-origin`.
- [ ] Commit por item.

### Task D: qualificação (B4) + analytics

**Files (exclusivos):**
- `supabase/migrations/20261022d1_score_directory.sql` (o `20261022d_qualificado_dashboard.sql` é só do agente C)
- `supabase/migrations/20261022e_analytics.sql`
- `backend/app/button_flow/valeria_runner.py`, `backend/app/lead_score/*`
- `frontend/src/app/api/valeria-score/**`
- `docs/superpowers/specs/2026-10-22-glossario-consulta.md`
- testes + `backend/tests/test_analytics_b67f_pg.py`

- [ ] Ler em produção `pg_get_viewdef` de `valeria_score_directory`, `analytics.dim_vendedor`, `analytics.dim_lead`, `analytics.vw_leads` e das views que dependem delas (`pg_depend`). Guardar em `scripts/leads_vendedor/defs_antes/`.
- [ ] Migration d1: recria `valeria_score_directory` sem `l.stage='atacado'`, mostrando lead com linha em `lead_qualification_scores`. Colunas iguais.
- [ ] Migration e:
  - `analytics.dim_vendedor` vira uma view sobre `vendedores`, com as mesmas colunas de hoje. Se uma coluna não tiver equivalente, mantém o nome e calcula;
  - `dim_lead.segmento` = `l.segmento`;
  - `dim_lead.b2b` = `fn_lead_b2b(l.id)`. Se existir `b2b_fonte`, ela fica: 'segmento'/'pipeline'/'cnpj';
  - `vw_leads` e as views dependentes são recriadas em ordem;
  - `grant select … to consulta_ro`.
  - Depende das migrations a e b.
- [ ] `test_analytics_b67f_pg.py`:
  - lead pending com score aparece no diretório;
  - `dim_lead.b2b` é falso para lead só com score;
  - `dim_vendedor` lista os vendedores semeados.
  
  Aplicar a, b, d1 e e no scratch, 2×.
- [ ] `valeria_runner.aplicar_criterios`:
  - grava o score só se `segmento_do_lead in SEGMENTOS_B2B` ou `lead_e_b2b(lead_id)`;
  - quando o score fecha `final_score>=5` e não é provisório, chama `registrar_qualificado(criterio='score', source='score', b2b=True)`.
  
  Testes em `test_valeria_runner_*` (novo arquivo `test_valeria_runner_qualificado_b67f.py`).
- [ ] `feeling/route.ts` e `valeria-score/route.ts`: tirar `.eq("stage","atacado")`. Vitest `valeria-score/route.test.ts`.
- [ ] Glossário: arquivo `.md` com as tabelas, colunas e funções novas e mudadas, e o que significa cada valor (`segmento`, fases, `origem_cadastro`, `qualificado`, `vendedores`, `fn_lead_b2b`), mais as consultas-exemplo da spec.
- [ ] Commit por item.

---

## Onda 2 (1 agente, depois de A–D integrados)

### Task E: caminho do repasse

**Files:** `backend/app/agent/tools.py`, `backend/app/button_flow/effects.py`, `backend/app/buffer/processor.py`, `backend/app/buffer/parking.py`, `backend/app/follow_up/scheduler.py`, `backend/app/agent/orchestrator.py`, `backend/app/agent/summary.py`, `backend/app/leads/service.py` (só `vendor_user_id_for_segment`) + testes.

- [ ] `apply_stage_transition`:
  - grava `leads.segmento=normalizar_segmento(novo)` e `leads.stage='qualificando'` quando há segmento;
  - "secretaria" grava `stage='triagem'` e `segmento=NULL`;
  - `conversations.stage` continua recebendo o valor de hoje.
  
  Testes: `test_prefill_stage_trigger_*`, `test_stage_flap_telemetry_*`, `test_post_stage_transition_closing`, `test_memory_refresh_on_stage_change`, ajustados e com casos novos.
- [ ] Os leitores de segmento passam a usar `segmento_do_lead(lead)`:
  - `encaminhar_humano`;
  - `move_deal_to_vendor_pipeline`;
  - `create_deal(category=…)`;
  - `marcar_interesse`/`mark_deal_qualificado`;
  - `retomar_contato_vendedor`;
  - o portão do score (`tools.py`, `_t_qualificar_lead`): grava o score se o segmento for B2B ou `lead_e_b2b`;
  - `summary.py`;
  - `effects.py`.
- [ ] `vendor_user_id_for_segment(seg)` passa a devolver `vendedor_do_segmento(seg)["id"]`, ou None. Remove a reserva `JOAO_USER_ID` do roteamento, mantendo a constante só se outro código a importa. Repasse sem segmento: o card não muda de funil e `assigned_to` = `resolver_vendedor(vendedor_do_LLM)` ou, se não resolver, `resolver_vendedor("joao@cafecanastra.com")`.
- [ ] Carimbo: `_t_encaminhar_humano`, `_aplicar_handoff` e os 8 repasses com "Joao Bras" fixo gravam `metadata.handoff.vendedor_id` (id resolvido) e `vendedor` = `por_id(id)["nome"]`. `registrar_repasse` recebe o `vendedor_id`.
- [ ] Exportação: quando `segmento_do_lead(lead)=='exportacao'`:
  - cartão `EXPORTACAO_NAME/EXPORTACAO_PHONE` (o fixo);
  - despedida citando o Arthur (o mesmo texto do fluxo de botões, `valeria_runner.CARTOES`);
  - `assigned_to` = id do Arthur, via `vendedor_do_segmento('exportacao')`;
  - mensagem `[encaminhar_humano] cartão de contato de Arthur - Café Canastra enviado`.
  
  Teste em `test_encaminhar_humano_pipeline.py`: segmento exportação manda o cartão do Arthur e grava `vendedor_id` do Arthur; atacado continua mandando o do João.
- [ ] `_vendedor_da_ponte`: resolve primeiro por `metadata.handoff.vendedor_id` via `por_id`, mapeando para o cartão: o Arthur usa EXPORTACAO, o resto usa SUPERVISOR. Sem id, usa o token do nome, como hoje. Teste em `test_processor_handoff_bridge_*`.
- [ ] `[qualificar_lead]` só é gravado quando há âncora nova não vazia: compara com `metadata.qualificacao` anterior; `volume`/`finalidade`/`prazo` None ou "" não contam. Teste em `test_qualificar_lead_portao_*`.
- [ ] `_t_marcar_interesse`: chama `mark_deal_qualificado` só com nível "quente". Teste em `test_marcar_interesse.py`.
- [ ] Rodar todos os testes listados na spec ("Como testar em modo teste" item 1). Commit por item.

---

## Onda 3 (paralelo)

### Task F: scripts de backfill F1–F7

**Files:** `scripts/leads_vendedor/f1_vendedores.sql` … `f7_qualificado.sql`, cada um com o seu `fN_rollback.sql`, mais `scripts/leads_vendedor/README.md`, `scripts/leads_vendedor/rollback_migrations.sql` e `scripts/leads_vendedor/relatorios/*.sql` (só SELECT).

Cada script segue esta forma:

```sql
begin;
set local lock_timeout = '5s';
-- contagem prévia
create temp table _alvo on commit drop as select … ;
do $$ declare n int := (select count(*) from _alvo); begin
  raise notice 'F2 alvo=%', n;
  if n > :teto then raise exception 'F2 acima do teto: %', n; end if; end $$;
create table if not exists public.backup_b67f_f2 (id uuid primary key, valor_anterior jsonb, gravado_em timestamptz default now());
insert into public.backup_b67f_f2 (id, valor_anterior) select id, to_jsonb(...) from _alvo on conflict do nothing;
update … from _alvo where … and <condição que torna idempotente>;
commit;
```

- [ ] Três agentes:
  - F1+F6 (vendedores);
  - F2+F3 (segmento/fase) + F4 (origem);
  - F5+F7 (eventos) + relatórios: ambíguos de vendedor, pending com segmento inferível, 123 cards em `qualificado` sem repasse, duplicados (wa_id, últimos 10 dígitos, máscara Bling, CNPJ), 248 com `human_control` sem repasse.
- [ ] Cada script roda no scratch com seed mínimo: sem erro, aplicado duas vezes sem mudar nada na segunda, rollback devolve o estado, teto estoura com seed acima do teto.
- [ ] Contagem prévia em produção só com SELECT (o `_alvo` em `begin read only`). Registrar no README o número de hoje e o teto (+10%).
- [ ] `rollback_migrations.sql` recria as definições de `defs_antes/` e remove as colunas e funções novas na ordem inversa. Testar no scratch: depois do rollback, `md5(prosrc)` de `dashboard_kpis` bate com produção.

### Task G: revisão

- [ ] Agente revisor (superpowers:requesting-code-review) lê `git diff origin/master...HEAD` contra a spec e reporta lacunas e bugs. O coordenador corrige ou delega.

---

## Onda 4 (coordenador)

- [ ] `cd backend && python -m pytest -q -m "not integration"`: nenhuma falha nova em relação ao baseline da 0.1.
- [ ] `cd frontend && npx vitest run && npx tsc --noEmit -p . && npm run build`.
- [ ] Scratch: aplicar todas as migrations a, b, c, d, d1 e e em sequência, 2×. Rodar todos os `*_pg.py` com `B67F_PSQL`. Rodar F1–F7 no seed. Aplicar a migration f e rodar `rollback_migrations.sql`.
- [ ] Prints em modo teste: o CRM local (`npm run dev`) aponta para o Supabase de produção, que não tem as migrations novas. Por isso os prints de modo teste mostram só as telas que já funcionam sem elas, sem gravar nada (tooltip e card do dashboard com a resposta mockada não valem como print de verdade). Se não houver como mostrar com dado real sem as migrations, registrar no resumo que os prints serão feitos em produção, como a spec prevê.
- [ ] Resumo + `[[PRONTO_PRODUCAO]]`.
