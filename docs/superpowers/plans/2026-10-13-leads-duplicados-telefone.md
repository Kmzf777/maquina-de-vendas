# Leads duplicados por telefone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Juntar os 389 grupos de leads que são a mesma pessoa com telefone em formatos diferentes e impedir que o CRM crie novos duplicados.

**Architecture:** (1) Script stdlib `scripts/leads/mesclar_duplicados_telefone.py`, irmão do `scripts/bling/mesclar_leads_duplicados.py` (reaproveita `Psql`, `_chave`, `_uuid`, `_texto`, `_csv`, `Q_TABELAS`, `Q_CHAVES`, `Q_COLUNAS_P0`, `movidos_do_stdout`, `SO_MOVER`, `COLISAO`, `TABELAS_IGNORADAS` via importlib): agrupa por telefone canônico, dry-run por padrão, uma transação por grupo. (2) Front: `POST /api/leads`, `PATCH /api/leads/[id]` e o quick-add passam a normalizar com `normalizePhoneBR` e procurar o lead existente por todas as variantes do número.

**Tech Stack:** Python 3.12 stdlib + psql (VPS host), pytest; Next.js App Router + Vitest.

**Worktree:** `C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA-agente-b747da43` (branch `agente/b747da43`). Nunca commitar no diretório principal `ValerIA`.

---

## Decisões técnicas tomadas no plano (registrar no resumo)

1. **Regra do 9 = a do backend.** O backend (`normalize_phone` + `get_or_create_lead`) trata `55DD9XXXXXXXX` como canônico para TODO número de 12 dígitos com 55 (inclusive fixo) e, no inbound, acha e reescreve o de 12 dígitos. O `normalizePhoneBR` do front já faz igual e **não muda**. O script usa a mesma regra para a chave do grupo. Assim front, script e inbound nunca divergem. Os grupos de telefone fixo (canônico `55DD9[2-5]…`) vão para `revisar.csv`, como diz a spec.
2. **`backend/app/campaign/router.py` não muda:** o router não está montado no `main.py` (o app usa `app.campaigns.router`), e o importer dele já normaliza.
3. **POST /api/leads com número existente** continua devolvendo **409** (a página /leads já trata o 409). O corpo passa a trazer `lead: {id, name, phone}` e a mensagem com o nome. O quick-add mostra essa mensagem e não cria nada.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `frontend/src/lib/phone.ts` | + `phoneVariantsBR(canonical)`: as formas antigas de um número canônico |
| `frontend/src/lib/phone.test.ts` | testes do helper |
| `frontend/src/lib/lead-phone-lookup.ts` | `findLeadByPhoneVariants(supabase, canonical, excludeId?)` |
| `frontend/src/app/api/leads/route.ts` | POST normaliza, procura variantes, 409 com o lead, aceita `human_control` |
| `frontend/src/app/api/leads/route.dedup.test.ts` | testes do POST |
| `frontend/src/app/api/leads/[id]/route.ts` | PATCH normaliza o phone e recusa (409) se outro lead já tem uma variante |
| `frontend/src/app/api/leads/[id]/route.phone.test.ts` | testes do PATCH |
| `frontend/src/components/quick-add-lead.tsx` | usa `POST /api/leads` e mostra o erro |
| `scripts/leads/mesclar_duplicados_telefone.py` | o script de mesclagem |
| `backend/tests/test_mesclar_duplicados_telefone.py` | unidade (sem banco) |
| `backend/tests/test_mesclar_duplicados_telefone_pg.py` | integração num Postgres 17 de rascunho (pula sem `MESCLAR_TEL_PG_URL`) |

Tarefas 1–3 (front) e 4–5 (script) são independentes entre si: dá para rodar em paralelo.

---

### Task 1: `phoneVariantsBR`

**Files:** Modify `frontend/src/lib/phone.ts`, `frontend/src/lib/phone.test.ts`

- [ ] **Step 1: Teste que falha.** Acrescentar em `phone.test.ts`:

```ts
import { normalizePhoneBR, phoneVariantsBR } from "@/lib/phone";

describe("phoneVariantsBR", () => {
  it("lista o canônico e as formas antigas (sem 9, sem 55, sem os dois)", () => {
    expect(phoneVariantsBR("5549999170363")).toEqual([
      "5549999170363", "554999170363", "49999170363", "4999170363",
    ]);
  });
  it("número fixo com 9 injetado também acha a forma de 12 dígitos", () => {
    expect(phoneVariantsBR("5549934415750")).toEqual([
      "5549934415750", "554934415750", "49934415750", "4934415750",
    ]);
  });
  it("valor que não é canônico de 13 dígitos devolve só ele mesmo", () => {
    expect(phoneVariantsBR("123")).toEqual(["123"]);
  });
});
```

- [ ] **Step 2:** `cd frontend && npx vitest run src/lib/phone.test.ts` → FAIL (`phoneVariantsBR` não existe).
- [ ] **Step 3: Implementar** em `phone.ts`:

```ts
/**
 * Formas em que um telefone canônico (saída de `normalizePhoneBR`) já foi gravado
 * em `leads.phone` antes de existir normalização: sem o 9, sem o 55, sem os dois.
 * Usado para achar o lead existente antes de criar outro (cartão b747da43).
 */
export function phoneVariantsBR(canonical: string): string[] {
  if (!/^55\d{2}9\d{8}$/.test(canonical)) return [canonical];
  const semNove = canonical.slice(0, 4) + canonical.slice(5);
  return [canonical, semNove, canonical.slice(2), semNove.slice(2)];
}
```

- [ ] **Step 4:** rodar de novo → PASS.
- [ ] **Step 5:** `git add frontend/src/lib/phone.ts frontend/src/lib/phone.test.ts && git commit -m "feat(leads): phoneVariantsBR lista as formas antigas de um telefone"`

### Task 2: POST e PATCH de lead acham o existente por variante

**Files:** Create `frontend/src/lib/lead-phone-lookup.ts`, `frontend/src/app/api/leads/route.dedup.test.ts`, `frontend/src/app/api/leads/[id]/route.phone.test.ts`. Modify `frontend/src/app/api/leads/route.ts` (POST e `sanitizePhone`), `frontend/src/app/api/leads/[id]/route.ts` (bloco "Sanitize phone").

- [ ] **Step 1: Helper**

```ts
// frontend/src/lib/lead-phone-lookup.ts
import { phoneVariantsBR } from "@/lib/phone";

export type LeadPorTelefone = { id: string; name: string | null; phone: string };

/** Lead que já usa o número em qualquer formato antigo (cartão b747da43). */
export async function findLeadByPhoneVariants(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  canonical: string,
  excludeId?: string,
): Promise<LeadPorTelefone | null> {
  let q = supabase.from("leads").select("id, name, phone").in("phone", phoneVariantsBR(canonical));
  if (excludeId) q = q.neq("id", excludeId);
  const { data } = await q.order("created_at", { ascending: true }).limit(1);
  return (data && data[0]) || null;
}
```

- [ ] **Step 2: Testes do POST (falham).** Em `route.dedup.test.ts`, mockar `@/lib/supabase/api` igual ao `route.p4.test.ts` (builder encadeável que registra chamadas; `in`, `neq`, `order`, `limit`, `insert`, `select`, `single` retornam o builder; `then` resolve `{data, error:null}` com dados configuráveis por chamada). Casos:
  1. `POST {phone:"(49) 9917-0363", name:"Douglas"}` com um lead `{id:"l1",name:"Douglas Schutz",phone:"4999170363"}` retornado pela busca → status 409, json `{error: "Lead com este telefone já existe: Douglas Schutz", lead:{id:"l1",...}}`, nenhum `insert` chamado, e `in` chamado com `["5549999170363","554999170363","49999170363","4999170363"]`.
  2. `POST {phone:"123"}` → 422 com `error` contendo "Telefone inválido".
  3. `POST {phone:"49999170363", human_control:true, stage:"secretaria"}` sem lead existente → 201 e o `insert` recebe `phone:"5549999170363"`, `human_control:true`.
- [ ] **Step 3:** `npx vitest run src/app/api/leads/route.dedup.test.ts` → FAIL.
- [ ] **Step 4: Implementar no `route.ts`:** trocar `sanitizePhone` por

```ts
function sanitizePhone(raw: string | undefined | null): { digits: string; error?: string } {
  const canonical = normalizePhoneBR(raw ?? "");
  if (!canonical) {
    const n = (raw ?? "").replace(/\D/g, "").length;
    return { digits: "", error: `Telefone inválido: ${n} dígito(s). Use DDD + número (ex.: 34 99999-9999)` };
  }
  return { digits: canonical };
}
```

e, no POST, substituir o `select("id").eq("phone", …).maybeSingle()` por

```ts
  const existing = await findLeadByPhoneVariants(supabase, phoneDigits);
  if (existing) {
    return NextResponse.json(
      { error: `Lead com este telefone já existe: ${existing.name || existing.phone}`, lead: existing },
      { status: 409 },
    );
  }
```

e acrescentar `human_control: body.human_control === true,` ao insert. Imports: `normalizePhoneBR` de `@/lib/phone`, `findLeadByPhoneVariants` de `@/lib/lead-phone-lookup`.
- [ ] **Step 5:** rodar → PASS; rodar também `npx vitest run src/app/api/leads` (o `route.p4.test.ts` continua verde).
- [ ] **Step 6: Testes do PATCH (falham)** em `[id]/route.phone.test.ts`: (a) `PATCH {phone:"3183016991"}` no lead `l2` com outro lead `l9` achado → 409 com `lead.id === "l9"` e nenhum `update`; (b) sem conflito → `update` recebe `phone:"5531983016991"`; (c) a busca usa `neq("id","l2")`; (d) `PATCH {phone:"12"}` → 422. Mockar `fetch` global (o PATCH dispara automação só quando muda o stage; nos testes não há stage).
- [ ] **Step 7: Implementar no `[id]/route.ts`:**

```ts
  if (body.phone !== undefined) {
    const canonical = normalizePhoneBR(body.phone ?? "");
    if (!canonical) {
      const n = (body.phone ?? "").replace(/\D/g, "").length;
      return NextResponse.json(
        { error: `Telefone inválido: ${n} dígito(s). Use DDD + número (ex.: 34 99999-9999)` },
        { status: 422 },
      );
    }
    const outro = await findLeadByPhoneVariants(supabase, canonical, id);
    if (outro) {
      return NextResponse.json(
        { error: `Outro lead já usa este telefone: ${outro.name || outro.phone}`, lead: outro },
        { status: 409 },
      );
    }
    body.phone = canonical;
  }
```

- [ ] **Step 8:** rodar os testes → PASS. `npm run type-check` limpo.
- [ ] **Step 9:** commit `feat(leads): POST e PATCH normalizam o telefone e acham o lead existente por qualquer formato`.

### Task 3: quick-add passa pela API

**Files:** Modify `frontend/src/components/quick-add-lead.tsx`

- [ ] **Step 1:** Trocar o insert direto no Supabase por

```ts
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim() || null,
        phone: phone.trim(),
        company: company.trim() || null,
        stage,
        human_control: humanControl,
        channel: "manual",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setErro(err.error || "Erro ao criar lead");
      setSaving(false);
      return;
    }
```

com `const [erro, setErro] = useState("")`, `setErro("")` no início do submit e ao cancelar, e `{erro && <p className="text-[11px] text-[#b42318]" role="alert">{erro}</p>}` logo acima dos botões. Remover `createClient` e a validação local de 8–15 dígitos (a API valida). O POST já grava `status: "active"`.
- [ ] **Step 2:** `npm run type-check && npm run lint -- src/components/quick-add-lead.tsx && npx vitest run` → tudo verde.
- [ ] **Step 3:** commit `fix(leads): adicionar lead rápido passa pela API e não duplica número existente`.

### Task 4: script — chave canônica, agrupamento e classificação (unidade)

**Files:** Create `scripts/leads/mesclar_duplicados_telefone.py` (só a parte pura nesta task) e `backend/tests/test_mesclar_duplicados_telefone.py`.

O script carrega o irmão do Bling assim (no topo, depois dos imports stdlib):

```python
_BLING = Path(__file__).resolve().parents[1] / "bling" / "mesclar_leads_duplicados.py"
_spec = importlib.util.spec_from_file_location("_mesclar_bling", _BLING)
bling = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bling)
```

- [ ] **Step 1: Testes (falham)**, carregando o script via `importlib.util.spec_from_file_location` (mesmo padrão do `test_cs_p1_mesclagem.py`):

```python
def test_canonico():
    m = _script()
    assert m.canonico("4999170363") == "5549999170363"
    assert m.canonico("554999170363") == "5549999170363"
    assert m.canonico("5549999170363") == "5549999170363"
    assert m.canonico("(31) 8301-6991") == "5531983016991"
    assert m.canonico("031983016991") == "5531983016991"
    assert m.canonico("554934415750") == "5549934415750"   # fixo: mesma regra do backend
    for lixo in ("bling-123", "US.1349120865", "", None, "123", "123456789012"):
        assert m.canonico(lixo) is None

def test_agrupar_escolhe_o_mais_antigo_e_ignora_unicos():
    m = _script()
    leads = [
        {"id": "a", "phone": "4999170363", "name": "Douglas Schutz", "created_at": "2026-05-08T10:00:00+00:00"},
        {"id": "b", "phone": "5549999170363", "name": "Douglas", "created_at": "2026-06-15T10:00:00+00:00"},
        {"id": "c", "phone": "5534999999999", "name": "Sozinho", "created_at": "2026-06-15T10:00:00+00:00"},
    ]
    gs = m.agrupar(leads)
    assert len(gs) == 1
    g = gs[0]
    assert g["canonico"] == "5549999170363" and g["sobrevivente"]["id"] == "a"
    assert [d["id"] for d in g["duplicados"]] == ["b"]

def test_empate_de_created_at_desempata_pelo_id():
    ...  # dois leads com o mesmo created_at: sobrevivente = menor id

def test_classificar():
    m = _script()
    # mesmo primeiro nome (sem acento/caixa) → automatico
    # um nome vazio → automatico
    # primeiro nome diferente → revisar, motivo "nomes diferentes"
    # 3+ leads → revisar, motivo "3 leads no grupo"
    # canonico 55DD9[2-5]… → revisar, motivo "telefone fixo"
```

(escrever cada caso do `test_classificar` como `assert m.classificar(grupo) == ("automatico", "")` ou `("revisar", "<motivo>")`, montando os grupos com `m.agrupar`).
- [ ] **Step 2:** `cd backend && python -m pytest ../backend/tests/test_mesclar_duplicados_telefone.py -q` (do diretório `backend`: `python -m pytest tests/test_mesclar_duplicados_telefone.py -q`) → FAIL.
- [ ] **Step 3: Implementar:**

```python
def canonico(phone):
    """Mesma regra de backend/app/campaign/importer.normalize_phone + leads.service.normalize_phone
    e do frontend normalizePhoneBR: 55 + DDD + 9 + 8 digitos. None se nao for telefone BR."""
    if not phone or not isinstance(phone, str) or phone.startswith("bling-") or "." in phone:
        return None
    d = re.sub(r"\D", "", phone)
    if d.startswith("0"):
        d = d[1:]
    if len(d) in (10, 11):
        d = "55" + d
    if len(d) not in (12, 13) or not d.startswith("55"):
        return None
    if len(d) == 12:
        d = d[:4] + "9" + d[4:]
    return d if d[4] == "9" else None


def _primeiro_nome(nome):
    n = unicodedata.normalize("NFKD", (nome or "").strip().lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return n.split()[0] if n.split() else ""


def agrupar(leads):
    grupos = {}
    for lead in leads:
        c = canonico(lead.get("phone"))
        if c:
            grupos.setdefault(c, []).append(lead)
    saida = []
    for c, membros in sorted(grupos.items()):
        if len(membros) < 2:
            continue
        membros = sorted(membros, key=lambda l: (str(l["created_at"]), str(l["id"])))
        saida.append({"canonico": c, "sobrevivente": membros[0], "duplicados": membros[1:]})
    return saida


def classificar(grupo):
    if len(grupo["duplicados"]) > 1:
        return "revisar", f"{len(grupo['duplicados']) + 1} leads no grupo"
    if grupo["canonico"][5] in "2345":
        return "revisar", "telefone fixo (9 injetado)"
    nomes = {_primeiro_nome(l.get("name")) for l in [grupo["sobrevivente"], *grupo["duplicados"]]}
    nomes.discard("")
    if len(nomes) > 1:
        return "revisar", "nomes diferentes"
    return "automatico", ""
```

Atenção à ordem de `created_at`: as strings vêm do `json_agg` do Postgres no mesmo formato e fuso, então a comparação textual vale. O teste cobre isso.
- [ ] **Step 4:** testes → PASS.
- [ ] **Step 5:** commit `feat(leads): script de mesclagem por telefone — chave canonica e classificacao`.

### Task 5: script — SQL do grupo, dry-run, `--aplicar`, testes no Postgres de rascunho

**Files:** Modify `scripts/leads/mesclar_duplicados_telefone.py`; Create `backend/tests/test_mesclar_duplicados_telefone_pg.py`; acrescentar casos de unidade do SQL em `backend/tests/test_mesclar_duplicados_telefone.py`.

**Regras do SQL de um grupo** (`sql_mesclar_grupo(grupo, tabelas, chaves)`, uma transação):
1. `begin;` + `select 1 from public.leads where id in (<todos>) for update;` + `do $$` que aborta se `count(*) <> n`.
2. `create temp table _mesclagem_movidos (tabela text not null, chave jsonb) on commit drop;` e `create temp table _dups on commit drop as select * from public.leads where id in (<dups>);`
3. Para cada duplicado `d`, em ordem:
   - **Conversa no mesmo canal:** para cada `dc` de `d` com `sc` do sobrevivente no mesmo `channel_id`: `update messages set lead_id = s, conversation_id = sc where conversation_id = dc` (registrar em `_mesclagem_movidos` como `messages`); `update follow_up_jobs set conversation_id = sc where conversation_id = dc`; `update sales set conversation_id = sc where conversation_id = dc`; registrar `('conversas_fundidas', jsonb_build_object('de', dc, 'para', sc))`; `delete from conversations where id = dc`. Fazer isso num bloco `do $$ … for r in select … loop … end loop $$`.
   - **Colisões que cancelam (não apagam):** `follow_up_jobs` e `campaign_enrollments`, com a condição de `bling.COLISAO[tabela]`: `update public.<t> d set status = 'cancelled' from public.<t> s where d.lead_id = d0 and s.lead_id = s0 and (<cond>) returning to_jsonb(d.id)` → registrar como `<t>_cancelados`.
   - **Demais colisões** (`lead_bling_contacts`, `lead_tags`, `lead_daily_sends`, `lead_seller_feelings`, `lead_qualification_scores`, `broadcast_leads`): `delete … using …`, igual ao Bling (as linhas inteiras estão no backup).
   - **Mover** `lead_id` em toda tabela de `bling.TABELAS_COBERTAS ∩ tabelas`, registrando as chaves com `bling._chave`.
   - `insert into lead_events (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)` com `event_type 'mesclagem'`, `metadata` = `{duplicado: {id, phone, name, channel, created_at}, motivo: 'telefone canonico <c>', movidos: <agregado só deste d>}`, `source 'sistema'`, `dedupe_key 'mesclagem:<d>'`, `on conflict do nothing`. O agregado por `d`: limpar `_mesclagem_movidos` (`truncate`) depois de gravar o evento de cada `d`, acumulando antes numa `_mesclagem_total` para o `select 'movidos=' …` final.
4. `delete from public.leads where id in (<dups>);`
5. `update public.leads s set phone = '<canonico>', <campos> from (select … from _dups) d where s.id = s0;`
   - Campos de texto copiados só se o do sobrevivente está vazio (`coalesce(btrim(s.c),'') = ''`), pegando o primeiro não vazio dos duplicados por `created_at`: `name, company, email, cnpj, razao_social, nome_fantasia, endereco, telefone_comercial, instagram, inscricao_estadual, wa_id, bsuid, ctwa_clid, fbclid, gclid, gbraid, wbraid, utm_source, utm_medium, utm_campaign, meta_ad_id, traffic_type`.
   - Não-texto com `coalesce(s.c, d.c)`: `bling_contact_id, assigned_to, first_response_at, wa_id_confirmed_at`.
   - `opt_out = s.opt_out or bool_or(d.opt_out)` e, se o sobrevivente não tinha, `opt_out_at/opt_out_channel/opt_out_evidence` do duplicado que tinha (**opt-out nunca se perde**).
   - `last_msg_at` e `last_customer_message_at` = `greatest(...)`. `ja_era_cliente = s or bool_or(d)`.
   - `metadata = coalesce(d.metadata,'{}') || coalesce(s.metadata,'{}')`.
6. `select 'movidos=' || <agregado de _mesclagem_total>::text;` e `commit;`

`bsuid` e `bling_contact_id` são únicos em `leads`: por isso a cópia vem depois do `delete`, lendo de `_dups`.

**Leitura (dry-run):**
- `Q_LEADS = "select id, phone, name, created_at from public.leads where phone is not null and phone <> '' and phone not like 'bling-%' order by created_at, id"`.
- `q_deals_abertos(ids)`: `select lead_id, pipeline_id, id from deals where closed_at is null and lead_id = any(...)`. Grupo com 2+ deals abertos no mesmo `pipeline_id` (somando todos os membros) → linha em `deals_repetidos.csv` (`canonico, sobrevivente, pipeline_id, deals`).
- Backup: `bling.q_backup(<ids dos duplicados>, tabelas, chaves)`, mais as conversas inteiras dos duplicados (`select to_jsonb(c) from conversations c where lead_id = any(...)`) em `conversas_duplicados`.

**`executar(db, saida, aplicar=False, limite=None, pares_csv=None, excluir=())`**, espelhando o do Bling:
- `verificar_cobertura` via `bling.verificar_cobertura`.
- Grava `pares.csv` (automáticos) e `revisar.csv` (com `motivo`), colunas `canonico, sobrevivente, sobrevivente_nome, sobrevivente_phone, duplicados, duplicados_nomes, duplicados_phones, motivo` (listas unidas por `|`). Grava também `excluidos.csv`, `deals_repetidos.csv` e `backup.json`.
- `--aplicar` exige `--pares` (um CSV com as colunas `canonico` e `sobrevivente`, que pode ser o `pares.csv` e/ou linhas aprovadas do `revisar.csv`). Para cada linha, recalcula o grupo agora. Só aplica se o canônico ainda tem grupo com o MESMO sobrevivente e os mesmos duplicados. Senão a linha entra em `aplicados.csv` como `recusado`, com o motivo.
- `Q_COLUNAS_P0` precisa devolver 3 colunas, senão `SystemExit`.
- `--limite N` aplica no máximo N grupos (`--limite 0` não aplica nenhum). `--excluir` tira grupos que contenham o id.
- Contagens JSON: `leads_lidos, grupos, automaticos, revisar, excluidos, deals_repetidos, aplicados_ok, aplicados_erro, aplicados_recusados, modo`.
- `main()` com os mesmos argumentos do Bling (`--psql`/env `MESCLAR_PSQL`, `--saida`, `--aplicar`, `--pares`, `--excluir`, `--limite`).

- [ ] **Step 1: Unidade do SQL (falha):** `sql_mesclar_grupo` de um grupo com 2 duplicados contém `for update`, o `delete from public.leads where id in (` vem DEPOIS de todos os `update public.messages`, o `update public.leads s set phone = '5549999170363'` vem depois do delete, contém `set status = 'cancelled'` para `follow_up_jobs` e NÃO contém `delete from public.follow_up_jobs`, e ids não-uuid levantam `ValueError`.
- [ ] **Step 2:** implementar `sql_mesclar_grupo` → unidade verde.
- [ ] **Step 3: Teste de integração** `test_mesclar_duplicados_telefone_pg.py` (pula sem `MESCLAR_TEL_PG_URL` ou sem `psql`). Fixture: `create database mesclar_tel template crm_schema`. Seed:
  - canal `c1`.
  - Trio Douglas: `A` `4999170363` (05/08), `B` `5549999170363` (06/15), `C` `554999170363` (09/04).
  - `A` e `B` com conversa no canal `c1` e mensagens. `B` com 1 deal aberto e `C` com 1 deal aberto no mesmo pipeline. `B` com `opt_out=true`, `email`, `bsuid`.
  - `follow_up_jobs` joao pendente igual em `A` e `B`. `broadcast_leads` do mesmo broadcast em `A` e `B`. `lead_tags` iguais.
  - Par Francine (`5551981162558` × `555181162558`). Um lead sozinho.

  Casos:
  1. Dry-run não escreve; `pares.csv` tem Francine, `revisar.csv` tem Douglas ("3 leads no grupo"), `deals_repetidos.csv` tem o grupo Douglas.
  2. `--aplicar` com `pares.csv` + a linha de Douglas:
     - Restam `A` e Francine-antiga; `A.phone = '5549999170363'`.
     - Todas as mensagens de A/B/C estão em `A`, numa única conversa no canal `c1`; contagem total de `messages` igual à de antes.
     - Os 2 deals estão em `A`.
     - `A.opt_out = true`, `A.email` e `A.bsuid` vieram de `B`.
     - O follow-up de `B` está `cancelled` e em `A`; o de `A` continua `pending`.
     - Um `broadcast_leads` só para `A`.
     - Dois eventos `mesclagem` em `A`.
     - `backup.json` tem `B` e `C` com as conversas.
  3. Segunda rodada: 0 grupos.
  4. Erro em um grupo faz rollback só dele. Forçar com um gatilho de teste que dá `raise` em update de `messages` de um lead específico; o outro grupo aplica.
  5. `--aplicar` com linha cujo sobrevivente não bate → `recusado`.
- [ ] **Step 4:** implementar leitura, CSVs, `executar`, `main` até a unidade passar. O pg roda na Task 6.
- [ ] **Step 5:** commit `feat(leads): mesclagem de leads duplicados por telefone (dry-run, aplicar, backup)`.

### Task 6: rodar o pg num Postgres de rascunho na VPS + dry-run em produção (controlador, não subagente)

- [ ] Subir container descartável (não toca o Supabase): `docker run -d --name pg-scratch-b747 -e POSTGRES_PASSWORD=scratch -p 127.0.0.1:55433:5432 postgres:17`.
- [ ] Esquema atual de produção, só leitura: `docker exec <supabase_db> pg_dump -U postgres -s -n public --no-owner --no-privileges postgres > /root/agente-b747da43/schema.sql`. No rascunho: criar os papéis `anon`, `authenticated`, `service_role`, o schema `auth` com `auth.uid()` de stub e a extensão `pgcrypto`/`uuid-ossp`. Depois `create database crm_schema` e carregar o `schema.sql` (erros de policy/grant são tolerados; tabelas, índices, FKs e triggers precisam existir — conferir com `\dt` e `\d leads`).
- [ ] Copiar `scripts/` e `backend/tests/test_mesclar_duplicados_telefone*.py` para `/root/agente-b747da43/`. Venv com pytest: `python3 -m venv /root/agente-b747da43/.venv && .venv/bin/pip install pytest`. Rodar `MESCLAR_TEL_PG_URL=postgresql://postgres:scratch@127.0.0.1:55433 .venv/bin/python -m pytest --noconftest backend/tests/test_mesclar_duplicados_telefone_pg.py -v` → todos verdes.
- [ ] Dry-run em produção (só lê): `python3 scripts/leads/mesclar_duplicados_telefone.py --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" --saida /root/agente-b747da43/dryrun-prod`. Conferir que as contagens batem com a investigação (~389 grupos) e que nada mudou (`select count(*) from leads` igual antes e depois).
- [ ] Ao fim: `docker rm -f pg-scratch-b747`.

### Task 7: suíte completa + print (controlador)

- [ ] `cd frontend && npm run type-check && npm run lint && npm run test`; `cd backend && python -m pytest -q -m "not integration" -p no:cacheprovider` → verdes.
- [ ] CRM local no worktree (`npm run dev` em `frontend`, com o `.env.local` do repo principal copiado sem imprimir). Testar o quick-add na /qualificacao com um número já existente em formato antigo e ver a mensagem "Lead com este telefone já existe: …" sem lead novo criado. Se o local apontar para o banco de produção e o número não existir, **não** submeter, porque criaria lead real. Nesse caso o print do quick-add fica para o teste em produção, com número de teste.
- [ ] Print com `print-frontend.mjs` e conferir o PNG.
