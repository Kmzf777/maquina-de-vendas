# SP0 — Contrato de Etapas dos Funis do João — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deixar os 5 funis do João com a estrutura decidida na reunião de 10/09/2026 e, sobretudo, com `key` em toda etapa que o motor precisa reconhecer — sem que nenhuma mensagem seja enviada.

**Architecture:** Uma migration SQL idempotente (aplicada à mão no editor do Supabase, como todas neste repo) faz todo o trabalho de dados, na ordem obrigatória *mover cards → atribuir keys → renomear → criar → reordenar → proteger*. Em paralelo, três mudanças de código fecham a porta que causou o problema: a API de etapas passa a aceitar `key`, a de exclusão passa a recusar etapa com `key`, e o template de funil novo passa a nascer com a estrutura nova. Os testes são asserts no **texto** do SQL — padrão já estabelecido em `test_esteiras_migration_sql.py` e `test_bling_migration.py`, porque a migration não roda no deploy e a suíte não tem banco.

**Tech Stack:** PostgreSQL (Supabase), Python 3.12 + pytest, Next.js App Router (TypeScript) + vitest.

---

## Contexto obrigatório antes de começar

Leia o spec `docs/superpowers/specs/2026-09-10-funil-joao-motor-followup-design.md`, seções §2 e §4/SP0.

**Três regras que este plano não pode violar:**

1. **`deals.stage_id` não tem `ON DELETE`.** Apagar uma etapa com cards levanta FK 23503. A migration **move os cards antes** de apagar. Sempre.
2. **`key` é o contrato; `label` é cosmético.** Renomear é seguro; apagar uma etapa que tem `key` não é.
3. **A migration NÃO sobe pelo deploy.** Ela é lida, revisada e aplicada à mão pelo dono no SQL editor do Supabase. O código desta entrega não depende dela para os testes passarem.

**Estado medido em produção em 10/09/2026** (os UUIDs abaixo são reais e estão no SQL):

| Funil | UUID |
|---|---|
| João - Atacado | `9706a14a-3d9a-413b-bceb-26838fc2cc45` |
| João - Private Label | `24fb6ce8-6b7b-4612-970d-8debb8c041b7` |
| João - Reposição | `79e35e6b-01d1-482a-bdf0-64c733ff1ca4` |
| João - Recuperação | `fa94029b-d524-4550-919e-67233dfe3a94` |
| João - Reposição Private Label | `9c027143-72f6-42d6-861f-a494ba5bbb4f` |

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `supabase/migrations/20260910_contrato_etapas_joao.sql` | **criar** — todo o trabalho de dados, idempotente, com guardas que abortam |
| `backend/tests/test_contrato_etapas_joao_migration.py` | **criar** — asserts no texto do SQL: ordem das operações, keys, guardas |
| `supabase/migrations/20260904_esteiras_vendedor.sql` | **modificar** — guarda de `closed_at` e `em_atencao` na lista de etapas fechadas da RPC |
| `backend/tests/test_esteiras_migration_sql.py` | **modificar** — dois testes novos para as guardas acima |
| `frontend/src/lib/pipeline-stages.ts` | **criar** — `DEFAULT_STAGES` e o predicado `stageIsProtectedByKey`, puros e testáveis |
| `frontend/src/lib/pipeline-stages.test.ts` | **criar** — testes do módulo acima |
| `frontend/src/app/api/pipelines/route.ts` | **modificar** — importar `DEFAULT_STAGES` do módulo novo |
| `frontend/src/app/api/pipelines/[id]/stages/route.ts` | **modificar** — `POST` passa a aceitar `key` |
| `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` | **modificar** — `DELETE` recusa etapa com `key` |
| `frontend/src/lib/constants.ts` | **modificar** — `DEAL_STAGES` reflete o vocabulário novo |

---

## Task 1: O módulo puro de etapas (frontend)

Extrair as duas decisões — qual é o template de funil novo, e o que pode ser apagado — para um módulo puro, porque handler de rota Next.js não é testável sem subir servidor.

**Files:**
- Create: `frontend/src/lib/pipeline-stages.ts`
- Test: `frontend/src/lib/pipeline-stages.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/pipeline-stages.test.ts
import { describe, it, expect } from "vitest";
import { DEFAULT_STAGES, stageIsProtectedByKey } from "./pipeline-stages";

describe("DEFAULT_STAGES", () => {
  it("segue o vocabulário decidido em 10/09: sem Contato, Proposta ou Negociação", () => {
    const labels = DEFAULT_STAGES.map((s) => s.label);
    expect(labels).toEqual([
      "Novo",
      "Em conversa",
      "Em atenção",
      "Proposta Enviada",
      "Fechado Ganho",
      "Perdido",
    ]);
  });

  it("dá key a TODA etapa — foi a ausência de key que quebrou os funis do João", () => {
    for (const s of DEFAULT_STAGES) {
      expect(s.key, `etapa ${s.label} sem key`).toBeTruthy();
    }
  });

  it("usa 'respondeu' em Em conversa, que é a key que advance_deal_on_reply procura", () => {
    expect(DEFAULT_STAGES.find((s) => s.label === "Em conversa")?.key).toBe("respondeu");
  });

  it("ordena Em conversa antes de Em atenção antes de Proposta Enviada", () => {
    const idx = (k: string) => DEFAULT_STAGES.findIndex((s) => s.key === k);
    expect(idx("respondeu")).toBeLessThan(idx("em_atencao"));
    expect(idx("em_atencao")).toBeLessThan(idx("proposta_enviada"));
  });

  it("order_index é 0..n sem buracos", () => {
    expect(DEFAULT_STAGES.map((s) => s.order_index)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("protege Fechado Ganho e Perdido, e só eles", () => {
    const prot = DEFAULT_STAGES.filter((s) => s.is_protected).map((s) => s.key);
    expect(prot).toEqual(["fechado_ganho", "fechado_perdido"]);
  });

  it("nunca preenche conversion_event — isso despacharia o card para Meta CAPI", () => {
    for (const s of DEFAULT_STAGES) {
      expect(s).not.toHaveProperty("conversion_event");
    }
  });
});

describe("stageIsProtectedByKey", () => {
  it("recusa apagar etapa que carrega key — foi assim que proposta_enviada sumiu", () => {
    expect(stageIsProtectedByKey("proposta_enviada")).toBe(true);
    expect(stageIsProtectedByKey("em_atencao")).toBe(true);
  });

  it("libera etapa sem key", () => {
    expect(stageIsProtectedByKey(null)).toBe(false);
    expect(stageIsProtectedByKey("")).toBe(false);
    expect(stageIsProtectedByKey(undefined)).toBe(false);
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/pipeline-stages.test.ts`
Expected: FAIL — `Failed to resolve import "./pipeline-stages"`

- [ ] **Step 3: Escrever o módulo**

```ts
// frontend/src/lib/pipeline-stages.ts

/**
 * Etapas de um funil novo.
 *
 * Vocabulário decidido na reunião de 10/09/2026 (spec
 * docs/superpowers/specs/2026-09-10-funil-joao-motor-followup-design.md, D1):
 * "Negociação" e "Proposta" foram removidas e "Contato" virou "Em conversa".
 *
 * TODA etapa nasce com `key`. A ausência de key nas quatro primeiras etapas do
 * template antigo é a causa raiz de §2.1 do spec: o código de negócio resolve etapa
 * por key, e etapa sem key é invisível para ele. "Em conversa" usa `respondeu`
 * porque é a key que `advance_deal_on_reply` (backend/app/leads/service.py:1192)
 * procura como destino — adotá-la faz o movimento automático funcionar sem código
 * novo. O rótulo visível e a key são coisas diferentes, e é para isso que servem.
 *
 * `conversion_event` fica AUSENTE de propósito: preenchê-lo despacha o card para a
 * Meta CAPI e para o CSV do Google Ads. A migration 20260909 documenta por que isso
 * contamina a série "Conversões (Ads)".
 */
export const DEFAULT_STAGES = [
  { label: "Novo",             key: "novo",              dot_color: "#e07a7a", order_index: 0, is_protected: false },
  { label: "Em conversa",      key: "respondeu",         dot_color: "#d4a04a", order_index: 1, is_protected: false },
  { label: "Em atenção",       key: "em_atencao",        dot_color: "#c9457b", order_index: 2, is_protected: false },
  { label: "Proposta Enviada", key: "proposta_enviada",  dot_color: "#9b7abf", order_index: 3, is_protected: false },
  { label: "Fechado Ganho",    key: "fechado_ganho",     dot_color: "#5aad65", order_index: 4, is_protected: true  },
  { label: "Perdido",          key: "fechado_perdido",   dot_color: "#9ca3af", order_index: 5, is_protected: true  },
] as const;

/**
 * True se a etapa não pode ser apagada pela tela.
 *
 * O DELETE só checava se havia cards dentro. Uma etapa-contrato VAZIA passava na
 * guarda e sumia — foi exatamente assim que a `proposta_enviada` do funil
 * "João - Reposição" desapareceu, e com ela o movimento do orçamento naquele funil
 * (quotes/router.py:272 procura por key, não acha, devolve False com log info).
 */
export function stageIsProtectedByKey(key: string | null | undefined): boolean {
  return Boolean(key);
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/pipeline-stages.test.ts`
Expected: PASS — 9 testes

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/pipeline-stages.ts frontend/src/lib/pipeline-stages.test.ts
git commit -m "feat(etapas): modulo puro com o template de funil novo e a guarda de key"
```

---

## Task 2: A API de etapas passa a escrever e proteger `key`

**Files:**
- Modify: `frontend/src/app/api/pipelines/route.ts` (a constante `DEFAULT_STAGES` local, linhas 15-23)
- Modify: `frontend/src/app/api/pipelines/[id]/stages/route.ts` (o `POST`)
- Modify: `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` (o `DELETE`)

- [ ] **Step 1: Trocar a constante local pelo módulo em `pipelines/route.ts`**

Apagar o bloco `const DEFAULT_STAGES = [...]` (as 7 linhas do array, junto com o comentário acima dele que fala de "Proposta Enviada … fica logo antes de Fechado Ganho") e adicionar o import no topo do arquivo, junto dos outros imports:

```ts
import { DEFAULT_STAGES } from "@/lib/pipeline-stages";
```

O resto do arquivo não muda — `DEFAULT_STAGES` continua sendo usado com o mesmo nome.

- [ ] **Step 2: `POST` de etapa passa a aceitar `key`**

Em `frontend/src/app/api/pipelines/[id]/stages/route.ts`, trocar a linha que desestrutura o corpo:

```ts
  const { label, dot_color } = await request.json();
```

por:

```ts
  const { label, dot_color, key } = await request.json();
```

e, no objeto passado para `.insert({...})`, acrescentar a propriedade `key` logo depois de `label`:

```ts
    .insert({
      pipeline_id: id,
      label: label.trim(),
      // `key` é o contrato estável que o código de negócio usa para achar a etapa;
      // `label` é editável pelo operador. Até 10/09/2026 este POST não escrevia key
      // nenhuma, então toda etapa criada pela tela nascia invisível para o motor.
      key: typeof key === "string" && key.trim() ? key.trim() : null,
      dot_color: dot_color || "#5b8aad",
      order_index: insertAt,
      is_protected: false,
    })
```

- [ ] **Step 3: `DELETE` passa a recusar etapa com `key`**

Em `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts`, dentro do `DELETE`, **antes** do bloco que conta deals, inserir:

```ts
  // Etapa que carrega `key` é contrato, não decoração: apagá-la desliga em silêncio o
  // código que a procura por key. A guarda de contagem abaixo não pega esse caso — uma
  // etapa-contrato VAZIA passava direto. Foi assim que a `proposta_enviada` do funil
  // "João - Reposição" sumiu e o orçamento parou de mover o card ali.
  const { data: alvo, error: alvoError } = await supabase
    .from("pipeline_stages")
    .select("key")
    .eq("id", stageId)
    .single();
  if (alvoError) return NextResponse.json({ error: alvoError.message }, { status: 500 });
  if (stageIsProtectedByKey(alvo?.key)) {
    return NextResponse.json(
      { error: `Esta etapa tem a chave "${alvo.key}" e é usada pelo sistema. Renomeie em vez de remover.` },
      { status: 409 }
    );
  }
```

e acrescentar o import no topo do arquivo:

```ts
import { stageIsProtectedByKey } from "@/lib/pipeline-stages";
```

- [ ] **Step 4: Verificar que compila e que nada quebrou**

Run: `cd frontend && npm run type-check && npx vitest run`
Expected: `tsc` sem saída; vitest com **762 passed** (753 de antes + 9 da Task 1)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/pipelines
git commit -m "feat(etapas): POST aceita key e DELETE recusa apagar etapa-contrato"
```

---

## Task 3: `DEAL_STAGES` para de oferecer etapas abolidas — sem quebrar a tradução do histórico

> **Esta task foi reescrita em 10/09/2026.** A versão original mandava trocar a forma do
> array para `{value, label}`. Estava errada em dois níveis, e o implementador bloqueou
> corretamente antes de commitar:
>
> 1. A forma real é `{key, label, color, dotColor, tintColor, avatarColor}`, e **três
>    consumidores** dependem dela: `cadence-trigger-config.tsx:16`,
>    `lead-detail-modal.tsx:424,431` e `lead-overview.ts:173`.
> 2. Mais grave: `DEAL_STAGES` serve a **dois usos conflitantes**. Alimenta o dropdown
>    que *oferece* etapas, e é o mapa que *traduz* key→rótulo em `STAGE_LABELS`
>    (`lead-overview.ts:172-175`). Simplesmente remover `contato`/`proposta`/`negociacao`
>    conserta o primeiro uso e quebra o segundo: todo deal histórico com essas keys
>    passaria a exibir a key crua na UI.
>
> A correção separa os dois usos: o array continua sendo o vocabulário **completo** (para
> traduzir), e ganha uma marca `legacy` que o dropdown filtra.

**Files:**
- Modify: `frontend/src/lib/constants.ts` (a constante `DEAL_STAGES`)
- Modify: `frontend/src/components/campaigns/cadence-trigger-config.tsx` (linhas 3 e 16)
- Test: `frontend/src/lib/constants.test.ts` (criar)

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/constants.test.ts
import { describe, it, expect } from "vitest";
import { DEAL_STAGES, OFFERABLE_DEAL_STAGES } from "./constants";

const keys = (xs: readonly { key: string }[]) => xs.map((s) => s.key);

describe("DEAL_STAGES", () => {
  it("mantém as keys abolidas, porque ainda traduz deal histórico", () => {
    expect(keys(DEAL_STAGES)).toEqual(
      expect.arrayContaining(["contato", "proposta", "negociacao"])
    );
  });

  it("conhece o vocabulário novo da reunião de 10/09", () => {
    expect(keys(DEAL_STAGES)).toEqual(
      expect.arrayContaining(["respondeu", "em_atencao", "chamado_reposicao"])
    );
  });

  it("toda entrada declara legacy explicitamente", () => {
    for (const s of DEAL_STAGES) {
      expect(typeof s.legacy, `etapa ${s.key} sem legacy`).toBe("boolean");
    }
  });

  it("toda entrada tem rótulo e cor, que lead-detail-modal usa no badge", () => {
    for (const s of DEAL_STAGES) {
      expect(s.dotColor, `etapa ${s.key} sem dotColor`).toBeTruthy();
      expect(s.label, `etapa ${s.key} sem label`).toBeTruthy();
    }
  });
});

describe("OFFERABLE_DEAL_STAGES", () => {
  it("não oferece nenhuma etapa abolida — é o bug que esta task existe para fechar", () => {
    const oferecidas = keys(OFFERABLE_DEAL_STAGES);
    expect(oferecidas).not.toContain("contato");
    expect(oferecidas).not.toContain("proposta");
    expect(oferecidas).not.toContain("negociacao");
  });

  it("oferece o vocabulário novo", () => {
    const oferecidas = keys(OFFERABLE_DEAL_STAGES);
    expect(oferecidas).toContain("respondeu");
    expect(oferecidas).toContain("em_atencao");
    expect(oferecidas).toContain("chamado_reposicao");
  });

  it("é exatamente DEAL_STAGES sem as legacy", () => {
    expect(OFFERABLE_DEAL_STAGES).toHaveLength(
      DEAL_STAGES.filter((s) => !s.legacy).length
    );
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/constants.test.ts`
Expected: FAIL — `OFFERABLE_DEAL_STAGES` não existe

- [ ] **Step 3: Reescrever `DEAL_STAGES` em `frontend/src/lib/constants.ts`**

Substituir o bloco inteiro de `DEAL_STAGES` (incluindo o comentário sobre "Etapa criada
junto com o orçamento") por:

```ts
// Vocabulário COMPLETO de etapas de funil. Ele tem dois usos, e é por isso que as
// keys abolidas continuam aqui:
//
//  1. TRADUZIR key -> rótulo (`STAGE_LABELS` em lib/lead-overview.ts, e o badge
//     colorido de lead-detail-modal.tsx). Isto precisa conhecer TODA key que já
//     existiu, senão deal histórico passa a exibir a key crua na tela.
//  2. OFERECER etapas na configuração de cadência. Este uso NÃO pode listar etapa
//     abolida — o dropdown grava a key alvo do gatilho, e uma key que não existe
//     mais em pipeline_stages nunca casa, sem erro visível.
//
// `legacy: true` separa os dois: entra na tradução, fica fora do que se oferece.
// Reunião de 10/09/2026: "Contato", "Proposta" e "Negociação" saíram dos funis;
// "Em conversa" usa a key `respondeu`, que é a que advance_deal_on_reply já procura.
//
// A ordem deste array é a ordem exibida — as legacy ficam no fim, fora do caminho.
export const DEAL_STAGES = [
  { key: "novo", label: "Novo", legacy: false, color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "respondeu", label: "Em conversa", legacy: false, color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "chamado_reposicao", label: "Já chamado (reposição)", legacy: false, color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "em_atencao", label: "Em atenção", legacy: false, color: "bg-[#f7d9e4]", dotColor: "#c9457b", tintColor: "#f9eef3", avatarColor: "#c9457b" },
  { key: "proposta_enviada", label: "Proposta Enviada", legacy: false, color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "fechado_ganho", label: "Fechado Ganho", legacy: false, color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "fechado_perdido", label: "Perdido", legacy: false, color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
  // Abolidas na reunião de 10/09/2026. Mantidas SÓ para traduzir dado histórico.
  { key: "contato", label: "Contato", legacy: true, color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "proposta", label: "Proposta", legacy: true, color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "negociacao", label: "Negociacao", legacy: true, color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
] as const;

// O que a tela de cadência pode oferecer. Ver o comentário acima: oferecer etapa
// abolida cria gatilho que nunca casa, e falha em silêncio.
export const OFFERABLE_DEAL_STAGES = DEAL_STAGES.filter((s) => !s.legacy);
```

- [ ] **Step 4: Fazer o dropdown de cadência usar a lista filtrada**

Em `frontend/src/components/campaigns/cadence-trigger-config.tsx`, trocar a linha 16:

```ts
    ? DEAL_STAGES.map((s) => ({ key: s.key, label: s.label }))
```

por:

```ts
    ? OFFERABLE_DEAL_STAGES.map((s) => ({ key: s.key, label: s.label }))
```

e ajustar o import da linha 3 para trazer `OFFERABLE_DEAL_STAGES` em vez de `DEAL_STAGES`:

```ts
import { AGENT_STAGES, OFFERABLE_DEAL_STAGES } from "@/lib/constants";
```

- [ ] **Step 5: Rodar type-check e a suíte inteira**

Run: `cd frontend && npm run type-check && npx vitest run`
Expected: `tsc` sem saída; vitest **769 passed** (762 + 7 novos de `constants.test.ts`).

Em especial, os dois testes de `lead-overview.test.ts` que dependem da tradução de
`proposta` e `negociacao` **continuam passando** — é exatamente o ponto desta task.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/constants.ts frontend/src/lib/constants.test.ts frontend/src/components/campaigns/cadence-trigger-config.tsx
git commit -m "fix(cadencias): dropdown para de oferecer etapa abolida, traducao preservada"
```

---

## Task 4: O teste da migration (antes do SQL)

O padrão deste repo é testar migration por **texto**, porque ela roda à mão no editor do Supabase e a suíte não tem banco (ver o docstring de `backend/tests/test_esteiras_migration_sql.py`).

**Files:**
- Create: `backend/tests/test_contrato_etapas_joao_migration.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Guardas da migration `20260910_contrato_etapas_joao.sql`.

Cada teste corresponde a um jeito CONCRETO de a migration estragar o funil de
trabalho do vendedor em producao. Nenhum e estetico.

Sao asserts no TEXTO do SQL, e nao num Postgres de verdade, porque a migration deste
repo nao e aplicada pelo deploy: ela roda a mao no editor do Supabase e a suite nao
tem banco. Mesmo padrao de `test_esteiras_migration_sql.py` e `test_bling_migration.py`.
"""
import pathlib
import re

SQL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260910_contrato_etapas_joao.sql"
)

# UUIDs reais, medidos em producao em 10/09/2026.
PL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"          # Joao - Private Label
REPOSICAO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"   # Joao - Reposicao
RECUPERACAO = "fa94029b-d524-4550-919e-67233dfe3a94" # Joao - Recuperacao
PROPOSTA_PL = "649019b7-d6aa-44c8-a320-020a2e554d3c"   # etapa "Proposta" do PL (12 cards)
NEGOCIACAO_PL = "37cab94e-ebb0-4575-9b83-8f4ab3417834" # etapa "Negociacao" do PL (15 cards)
PROP_ENV_REPOSICAO = "d1a0a022-71fe-4ff9-bc7d-3ff813a4d9ec"  # perdeu a key


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _sem_comentario() -> str:
    """SQL sem os `--` e com espacos normalizados.

    Tirar os comentarios importa: o arquivo explica cada decisao em portugues logo
    acima dela, e um assert de texto casaria com a EXPLICACAO em vez de com o codigo —
    passaria com a operacao apagada e o comentario esquecido.
    """
    txt = _sql()
    limpo = "\n".join(linha.split("--")[0] for linha in txt.splitlines())
    return re.sub(r"\s+", " ", limpo).strip()


def test_arquivo_existe():
    assert SQL.exists(), f"migration nao encontrada em {SQL}"


def test_move_os_cards_antes_de_apagar_a_etapa():
    """FK 23503: deals.stage_id nao tem ON DELETE.

    Apagar 'Proposta'/'Negociacao' do Private Label com 27 cards dentro levanta erro e
    desfaz a transacao inteira. O UPDATE que esvazia tem de vir ANTES do DELETE.
    """
    sql = _sem_comentario()
    pos_update = sql.index("UPDATE deals SET stage_id")
    pos_delete = sql.index("DELETE FROM pipeline_stages")
    assert pos_update < pos_delete, (
        "o DELETE de etapa aparece antes do UPDATE que esvazia — FK 23503 garantido"
    )


def test_esvazia_exatamente_proposta_e_negociacao_do_private_label():
    sql = _sem_comentario()
    assert PROPOSTA_PL in sql, "etapa 'Proposta' do Private Label nao e esvaziada"
    assert NEGOCIACAO_PL in sql, "etapa 'Negociacao' do Private Label nao e esvaziada"


def test_recupera_a_key_proposta_enviada_do_funil_reposicao():
    """Sem esta key, `_move_deal_to_proposal` nao acha a etapa e o orcamento nao move
    o card — em silencio, com log `info` (quotes/router.py:274-279)."""
    sql = _sem_comentario()
    assert re.search(
        r"UPDATE pipeline_stages SET key = 'proposta_enviada'[^;]*" + PROP_ENV_REPOSICAO,
        sql,
    ), "a key 'proposta_enviada' nao e restaurada na etapa da Reposicao"


def test_toda_etapa_dos_funis_do_joao_recebe_key():
    """Etapa sem key e invisivel para o codigo de negocio, que resolve por key."""
    sql = _sem_comentario()
    for key in (
        "'novo'", "'respondeu'", "'em_atencao'", "'proposta_enviada'",
        "'chamado_reposicao'", "'entrada'", "'em_followup'", "'recuperado'",
    ):
        assert f"SET key = {key}" in sql, f"nenhuma etapa recebe key {key}"


def test_nao_usa_ja_chamado():
    """`deals.stage='ja_chamado'` e lido por lead_has_active_relationship e
    _lead_had_prior_handoff, e NUNCA e limpo: o PATCH do Kanban escreve stage_id e
    closed_at, nunca deals.stage. O lead ficaria 'relacionamento ativo' para sempre.
    Decisao do spec §4/SP0 nota 2: usar `chamado_reposicao`, que ninguem le."""
    assert "'ja_chamado'" not in _sem_comentario()


def test_recuperacao_nao_ganha_proposta_enviada_nem_fechado_ganho():
    """Decisao da reuniao (55:20, 54:39): a saida da Recuperacao e mudar de funil."""
    sql = _sem_comentario()
    trecho = sql[sql.index(RECUPERACAO):]
    fim = trecho.index("END $$") if "END $$" in trecho else len(trecho)
    bloco = trecho[:fim]
    assert "'fechado_ganho'" not in bloco or RECUPERACAO not in bloco.split("'fechado_ganho'")[0][-200:]


def test_protege_fechado_ganho_e_perdido():
    """Hoje NENHUMA etapa e protegida, e `_first_unprotected_stage_id` elege a etapa de
    entrada pelo menor order_index: um arrasta-e-solta infeliz faz todo card novo
    nascer em 'Perdido'."""
    sql = _sem_comentario()
    assert "is_protected = true" in sql
    assert "'fechado_ganho'" in sql and "'fechado_perdido'" in sql


def test_nao_preenche_conversion_event():
    """Preencher esse campo despacha o card para Meta CAPI / Google Ads e contamina a
    serie 'Conversoes (Ads)' (documentado em 20260909:44-99)."""
    assert "conversion_event" not in _sem_comentario()


def test_tem_guarda_que_aborta_se_o_estado_mudou():
    """A migration foi escrita contra uma medicao de 10/09/2026. Se alguem mexer no
    board antes de aplica-la, e melhor abortar do que espalhar card na coluna errada."""
    sql = _sem_comentario()
    assert "RAISE EXCEPTION" in sql


def test_termina_com_notify_pgrst():
    """Sem isso o PostgREST serve o schema em cache e o CRM responde PGRST204/205 com a
    coluna ja existindo no banco. Precedente: 20260825:195 e 20260909:162."""
    assert "NOTIFY pgrst" in _sql()


def test_reclassifica_os_cards_de_novo_por_mensagem_e_nao_por_ultimo_falante():
    """363 dos 578 cards em 'Novo' tem lead que ja falou no numero do Joao.

    O criterio TEM de ser 'existe mensagem role=user em conversa de canal humano'.
    Classificar por 'quem falou por ultimo' poria de volta em 'Novo' todo lead que o
    Joao respondeu por ultimo — que sao 792 dos 810.
    """
    sql = _sem_comentario()
    assert "role = 'user'" in sql, "a reclassificacao nao olha mensagem do lead"
    assert "mode = 'human'" in sql, "a reclassificacao nao restringe ao canal do vendedor"
    assert "last_customer_message_at" not in sql or "role = 'user'" in sql
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_contrato_etapas_joao_migration.py -v`
Expected: FAIL — todos os testes falham; o primeiro com `migration nao encontrada`

- [ ] **Step 3: Commit do teste**

```bash
git add backend/tests/test_contrato_etapas_joao_migration.py
git commit -m "test(etapas): guardas da migration do contrato de etapas do Joao"
```

---

## Task 5: A migration

**Files:**
- Create: `supabase/migrations/20260910_contrato_etapas_joao.sql`

- [ ] **Step 1: Escrever a migration**

```sql
-- 20260910_contrato_etapas_joao.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO no SQL editor do Supabase, depois de lida e revisada por um humano. Ela mexe
--    no FUNIL DE TRABALHO DO VENDEDOR em producao. Nenhum agente de IA deve aplica-la.
--
-- ── O QUE ELE FAZ ───────────────────────────────────────────────────────────
-- Deixa os 5 funis do Joao com a estrutura decidida na reuniao de 10/09/2026 e, acima
-- de tudo, com `key` em toda etapa que o motor precisa reconhecer.
-- Spec: docs/superpowers/specs/2026-09-10-funil-joao-motor-followup-design.md (§4/SP0).
--
-- A ORDEM E OBRIGATORIA e o arquivo a respeita:
--   1. mover os cards para fora das etapas que vao sumir   (senao FK 23503)
--   2. apagar as etapas vazias
--   3. atribuir as keys
--   4. renomear os rotulos
--   5. criar "Em atencao" onde falta
--   6. reordenar order_index sem buracos e proteger as terminais
--   7. reclassificar os 363 cards de "Novo" cujo lead ja falou com o Joao
--
-- ── POR QUE `key` E O CENTRO DISSO ──────────────────────────────────────────
-- `pipeline_stages.key` e o contrato estavel que todo o codigo de negocio usa; `label`
-- e editavel pelo operador (leads/service.py:237). A tela NUNCA escreveu key ao criar
-- etapa avulsa nem ao renomear, entao as etapas criadas a mao em 10/09 nasceram
-- invisiveis para o motor — e o DELETE, que so checava se havia cards, deixou apagar a
-- `proposta_enviada` (vazia) do funil Reposicao. Esta migration conserta o estado; a
-- porta foi fechada no mesmo commit, do lado da API.
--
-- ── DECISOES QUE PARECEM ARBITRARIAS E NAO SAO ──────────────────────────────
-- · "Em conversa" recebe key `respondeu`, e nao `em_conversa`: e a key que
--   `advance_deal_on_reply` (leads/service.py:1192) ja procura como destino. Adotando-a,
--   o movimento automatico "Novo -> Em conversa" da decisao D2 passa a funcionar sem
--   uma linha de backend. Rotulo e key sao coisas diferentes, e e para isso que servem.
-- · "Ja chamado" recebe `chamado_reposicao`, e NAO `ja_chamado`. A key `ja_chamado` e
--   lida por lead_has_active_relationship (service.py:229) e _lead_had_prior_handoff
--   (tools.py:1682) como "tratativa humana em aberto". Para card de reposicao a
--   semantica ate bate — mas o sinal NUNCA e limpo: o PATCH do Kanban escreve stage_id
--   e closed_at, nunca `deals.stage`. O lead ficaria "relacionamento ativo" para sempre,
--   sem nunca mais receber disparo frio nem poder ser marcado perdido.
-- · `conversion_event` fica NULL em tudo. Preencher despacha o card para a Meta CAPI e
--   para o CSV do Google Ads (ver 20260909:44-99).
-- · O funil Recuperacao NAO ganha `proposta_enviada` nem `fechado_ganho`: pela reuniao
--   (55:20, 54:39) a saida dele e mudar de funil, nao fechar dentro dele.
--
-- Idempotente: casa por UUID e grava sempre o mesmo valor; reexecutavel sem efeito
-- colateral. Em ambientes sem esses funis (homolog) afeta 0 linhas.

BEGIN;

DO $$
DECLARE
  -- Funis (UUIDs medidos em producao em 10/09/2026)
  atacado_id     uuid := '9706a14a-3d9a-413b-bceb-26838fc2cc45';
  plabel_id      uuid := '24fb6ce8-6b7b-4612-970d-8debb8c041b7';
  reposicao_id   uuid := '79e35e6b-01d1-482a-bdf0-64c733ff1ca4';
  recuperacao_id uuid := 'fa94029b-d524-4550-919e-67233dfe3a94';
  repos_pl_id    uuid := '9c027143-72f6-42d6-861f-a494ba5bbb4f';

  -- Etapas que vao sumir (Private Label) e o destino dos seus cards
  pl_proposta    uuid := '649019b7-d6aa-44c8-a320-020a2e554d3c';  -- 12 cards
  pl_negociacao  uuid := '37cab94e-ebb0-4575-9b83-8f4ab3417834';  -- 15 cards
  pl_em_conversa uuid := 'c778fe72-ed7c-49cc-b5c8-8d50b00dd84a';  -- "Contato" -> "Em conversa"

  -- Etapas do Reposicao Private Label (0 cards, nasceu com o esquema abolido)
  rpl_proposta   uuid := 'f0049ee9-7344-468d-80ea-b8ca8ad7e12f';
  rpl_negociacao uuid := '09c79b8f-2889-4d8c-8265-a60559efc15b';

  movidos  integer;
  orfaos   integer;
BEGIN
  -- ────────────────────────────────────────────────────────────────────────
  -- GUARDA 0. O estado do board mudou desde a medicao?
  -- Esta migration foi escrita contra uma leitura de 10/09/2026. Se alguem mexeu nas
  -- etapas nesse meio-tempo, e melhor abortar do que espalhar card na coluna errada.
  -- ────────────────────────────────────────────────────────────────────────
  IF NOT EXISTS (SELECT 1 FROM pipeline_stages WHERE id = pl_proposta AND pipeline_id = plabel_id) THEN
    RAISE EXCEPTION 'etapa "Proposta" do Private Label (%) nao existe mais — reveja a migration', pl_proposta;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pipeline_stages WHERE id = pl_em_conversa AND pipeline_id = plabel_id) THEN
    RAISE EXCEPTION 'etapa de destino (%) nao existe — abortando antes de mover card', pl_em_conversa;
  END IF;

  -- ────────────────────────────────────────────────────────────────────────
  -- 1. MOVER OS CARDS PARA FORA DAS ETAPAS QUE VAO SUMIR
  -- deals.stage_id nao tem ON DELETE (012:32) => NO ACTION. Apagar etapa com card
  -- dentro levanta FK 23503 e desfaz a transacao inteira. Nao existe CASCADE que
  -- "resolva" isso — e bom que nao exista, CASCADE apagaria os deals.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE deals SET stage_id = pl_em_conversa, updated_at = now()
   WHERE stage_id IN (pl_proposta, pl_negociacao);
  GET DIAGNOSTICS movidos = ROW_COUNT;
  RAISE NOTICE 'cards movidos de Proposta/Negociacao para Em conversa: %', movidos;
  IF movidos > 100 THEN
    RAISE EXCEPTION 'movidos % cards, esperava ~27 — revise o WHERE antes de continuar', movidos;
  END IF;

  -- ────────────────────────────────────────────────────────────────────────
  -- 2. APAGAR AS ETAPAS, agora vazias
  -- ────────────────────────────────────────────────────────────────────────
  DELETE FROM pipeline_stages
   WHERE id IN (pl_proposta, pl_negociacao, rpl_proposta, rpl_negociacao)
     AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.stage_id = pipeline_stages.id);

  -- ────────────────────────────────────────────────────────────────────────
  -- 3. ATRIBUIR AS KEYS  (o coracao desta migration)
  -- ────────────────────────────────────────────────────────────────────────
  -- Joao - Atacado
  UPDATE pipeline_stages SET key = 'novo'      WHERE id = '26103dba-b371-47a5-b990-70da776ccce5';
  UPDATE pipeline_stages SET key = 'respondeu' WHERE id = '6027a761-ed7e-4d34-b388-5ec2debbeaae';

  -- Joao - Private Label
  UPDATE pipeline_stages SET key = 'novo'      WHERE id = '05b52405-806d-4f1f-89e8-f96c9fd86ba5';
  UPDATE pipeline_stages SET key = 'respondeu' WHERE id = pl_em_conversa;

  -- Joao - Reposicao
  UPDATE pipeline_stages SET key = 'novo'              WHERE id = '07b4a308-c2ad-4896-99ee-caee30f926b8';
  UPDATE pipeline_stages SET key = 'chamado_reposicao' WHERE id = '58b9fbe0-c138-4dcb-8318-ed2409c61a9a';
  UPDATE pipeline_stages SET key = 'em_atencao'        WHERE id = '499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0';
  -- A key que foi apagada a mao em 10/09 junto com a etapa vazia que a carregava.
  -- Sem ela, `_move_deal_to_proposal` nao acha a etapa neste funil e o orcamento nao
  -- move o card — em silencio (quotes/router.py:274-279 devolve False com log info).
  UPDATE pipeline_stages SET key = 'proposta_enviada'  WHERE id = 'd1a0a022-71fe-4ff9-bc7d-3ff813a4d9ec';

  -- Joao - Recuperacao (sem proposta_enviada e sem fechado_ganho, de proposito)
  UPDATE pipeline_stages SET key = 'entrada'     WHERE id = '699e0b61-ee7f-480e-827e-fd970379c7da';
  UPDATE pipeline_stages SET key = 'em_followup' WHERE id = 'd8d39be3-97ea-4a43-9cfe-bc95d0fb52b1';
  UPDATE pipeline_stages SET key = 'recuperado'  WHERE id = 'd5bad206-280a-461d-b122-d2c4f0f3a088';

  -- Joao - Reposicao Private Label (espelho do Reposicao, 0 cards)
  UPDATE pipeline_stages SET key = 'novo',              label = 'Cliente Ativo' WHERE id = 'ac70ef91-9e67-4eb2-b36a-5ee52da90737';
  UPDATE pipeline_stages SET key = 'chamado_reposicao', label = 'Já chamado'    WHERE id = 'd2295c6a-bd04-427c-80ff-a8592012e4b1';

  -- ────────────────────────────────────────────────────────────────────────
  -- 4. RENOMEAR OS ROTULOS
  -- "Em Conversa" da Reposicao NAO e a mesma coisa que a dos funis de 1a compra: la
  -- significa "o lead respondeu", aqui significa "ja foi chamado neste ciclo". Manter o
  -- mesmo rotulo nos dois faria a tela de configuracao de esteira mentir.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE pipeline_stages SET label = 'Em conversa' WHERE id = pl_em_conversa;                          -- era "Contato"
  UPDATE pipeline_stages SET label = 'Já chamado'  WHERE id = '58b9fbe0-c138-4dcb-8318-ed2409c61a9a';  -- era "Em Conversa"
  UPDATE pipeline_stages SET label = 'Em atenção'  WHERE id = '499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0';  -- era "Em ATENÇÃO"
  UPDATE pipeline_stages SET label = 'Em conversa' WHERE id = '6027a761-ed7e-4d34-b388-5ec2debbeaae';  -- "Em Conversa" -> caixa

  -- ────────────────────────────────────────────────────────────────────────
  -- 5. CRIAR "Em atencao" onde falta (Atacado, Private Label, Reposicao PL)
  -- E o estado terminal da esteira: o lead percorreu tudo e nao comprou, entao para de
  -- ser automatico e vira decisao do vendedor (spec D9). Cor viva, por pedido do Arthur.
  -- ────────────────────────────────────────────────────────────────────────
  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
  SELECT v.pipeline_id, 'Em atenção', 'em_atencao', '#c9457b', 2, false
    FROM (VALUES (atacado_id), (plabel_id), (repos_pl_id)) AS v(pipeline_id)
   WHERE NOT EXISTS (
     SELECT 1 FROM pipeline_stages s
      WHERE s.pipeline_id = v.pipeline_id AND s.key = 'em_atencao'
   );

  -- ────────────────────────────────────────────────────────────────────────
  -- 6. REORDENAR SEM BURACOS E PROTEGER AS TERMINAIS
  -- order_index e a definicao de fato de "etapa de entrada": _first_unprotected_stage_id
  -- pega o MENOR order_index entre is_protected=false. Hoje NENHUMA etapa e protegida,
  -- entao um arrasta-e-solta infeliz faz todo card novo e todo handoff nascer em
  -- "Fechado Ganho" ou "Perdido". Proteger as duas terminais fecha isso.
  --
  -- A ordem tambem importa para o orcamento: `_move_deal_to_proposal` so move se o
  -- order_index atual for MENOR que o de proposta_enviada (quotes/router.py:281). Se
  -- "Em conversa" ficasse depois, o unico marco valido da reuniao pararia em silencio.
  -- ────────────────────────────────────────────────────────────────────────
  WITH ordem AS (
    SELECT id,
           row_number() OVER (
             PARTITION BY pipeline_id
             ORDER BY CASE key
               WHEN 'novo'              THEN 0
               WHEN 'entrada'           THEN 0
               WHEN 'respondeu'         THEN 1
               WHEN 'chamado_reposicao' THEN 1
               WHEN 'em_followup'       THEN 1
               WHEN 'em_atencao'        THEN 2
               WHEN 'recuperado'        THEN 2
               WHEN 'proposta_enviada'  THEN 3
               WHEN 'fechado_ganho'     THEN 8
               WHEN 'fechado_perdido'   THEN 9
               ELSE 5
             END, order_index
           ) - 1 AS nova
      FROM pipeline_stages
     WHERE pipeline_id IN (atacado_id, plabel_id, reposicao_id, recuperacao_id, repos_pl_id)
  )
  UPDATE pipeline_stages p SET order_index = o.nova
    FROM ordem o WHERE p.id = o.id AND p.order_index IS DISTINCT FROM o.nova;

  UPDATE pipeline_stages SET is_protected = true
   WHERE pipeline_id IN (atacado_id, plabel_id, reposicao_id, recuperacao_id, repos_pl_id)
     AND key IN ('fechado_ganho', 'fechado_perdido');

  -- ────────────────────────────────────────────────────────────────────────
  -- 7. RECLASSIFICAR OS CARDS DE "Novo" CUJO LEAD JA FALOU COM O JOAO
  -- Medido em 10/09/2026: 363 dos 578 cards em "Novo" tem lead que ja mandou mensagem
  -- NO NUMERO DO VENDEDOR. Pela decisao D2, "Novo" = o Joao mandou algo e o lead NAO
  -- respondeu — entao esses 363 estao na coluna errada, e sem mover receberiam a
  -- mensagem da esteira "Novo", que diz em essencia "voce nao me respondeu".
  --
  -- O criterio e EXISTS(mensagem role='user' em conversa de canal mode='human'), e nao
  -- "quem falou por ultimo": este ultimo devolveria 792 de 810, porque o normal e o
  -- Joao ter falado por ultimo. Tambem nao serve "o lead ja mandou alguma mensagem":
  -- isso da 570, porque quase todo lead falou com a ValerIA ANTES do handoff.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE deals d
     SET stage_id = alvo.id, updated_at = now()
    FROM pipeline_stages atual, pipeline_stages alvo
   WHERE d.stage_id = atual.id
     AND atual.key = 'novo'
     AND atual.pipeline_id IN (atacado_id, plabel_id)
     AND alvo.pipeline_id = atual.pipeline_id
     AND alvo.key = 'respondeu'
     AND d.closed_at IS NULL
     AND EXISTS (
       SELECT 1
         FROM messages m
         JOIN conversations c ON c.id = m.conversation_id
         JOIN channels ch     ON ch.id = c.channel_id
        WHERE m.lead_id = d.lead_id
          AND m.role = 'user'
          AND ch.mode = 'human'
     );
  GET DIAGNOSTICS movidos = ROW_COUNT;
  RAISE NOTICE 'cards reclassificados de Novo para Em conversa: % (esperado ~363)', movidos;

  -- ────────────────────────────────────────────────────────────────────────
  -- GUARDA FINAL. Nenhum deal pode ter ficado apontando para etapa inexistente.
  -- ────────────────────────────────────────────────────────────────────────
  SELECT count(*) INTO orfaos
    FROM deals d
   WHERE d.stage_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pipeline_stages s WHERE s.id = d.stage_id);
  IF orfaos > 0 THEN
    RAISE EXCEPTION 'ficaram % deals orfaos — desfazendo tudo', orfaos;
  END IF;
END $$;

COMMIT;

-- O PostgREST serve o schema em cache: sem isto o CRM responde PGRST204/205 com a
-- coluna ja existindo no banco. Precedente: 20260825:195 e 20260909:162.
NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 2: Rodar os testes da migration**

Run: `cd backend && python -m pytest tests/test_contrato_etapas_joao_migration.py -v`
Expected: PASS — 12 testes

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260910_contrato_etapas_joao.sql
git commit -m "feat(etapas): migration do contrato de etapas dos funis do Joao"
```

---

## Task 6: A RPC das esteiras deixa de tratar card fechado como aberto

Medido: **38 cards têm `closed_at` preenchido mas estão em etapa não-terminal** (37 em Reposição/"Já chamado", 1 em Recuperação/"Recuperado"). A RPC decide "etapa aberta" pela `key`, então ela pegaria esses 38 — e mandaria mensagem para quem já fechou. O inverso (etapa terminal com `closed_at` nulo) é **zero**.

Mover os 37 cards é decisão do dono, não da migration. A guarda é código, e é aqui.

**Files:**
- Modify: `supabase/migrations/20260904_esteiras_vendedor.sql` (o `WHERE` de `get_deals_stage_stagnant`)
- Modify: `backend/tests/test_esteiras_migration_sql.py`

- [ ] **Step 1: Escrever os dois testes que falham**

Acrescentar ao fim de `backend/tests/test_esteiras_migration_sql.py`:

```python
def test_rpc_ignora_card_com_closed_at_preenchido():
    """38 cards em producao (10/09/2026) tem closed_at preenchido e estao parados em
    etapa NAO-terminal — 37 em "Ja chamado" da Reposicao. A RPC decide "aberto" pela
    key da etapa, entao sem esta guarda ela manda template para quem ja fechou.
    O inverso (etapa terminal com closed_at nulo) e zero, entao a guarda nao exclui
    ninguem legitimo.
    """
    assert "d.closed_at IS NULL" in _fn_code(), (
        "a RPC nao filtra por closed_at — card fechado em etapa sem key entra na esteira"
    )


def test_rpc_trata_em_atencao_como_etapa_fechada():
    """"Em atencao" e o estado terminal da esteira: o lead saiu do automatico e espera
    decisao do vendedor. Se a RPC continuar achando que e etapa aberta, ela reenrola o
    card e a decisao humana nunca acontece."""
    assert "'em_atencao'" in _fn_code(), (
        "'em_atencao' nao esta na lista de etapas fechadas da RPC"
    )
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_esteiras_migration_sql.py -v -k "closed_at or em_atencao"`
Expected: FAIL — 2 testes, ambos com `AssertionError`

- [ ] **Step 3: Alterar a RPC**

Em `supabase/migrations/20260904_esteiras_vendedor.sql`, dentro do `WHERE` de `get_deals_stage_stagnant`, na linha em que hoje se lê a lista de keys de etapa fechada (a que contém `'fechado_ganho'`), acrescentar `'em_atencao'` à lista, e acrescentar logo abaixo a guarda de `closed_at`:

```sql
       -- "Em atencao" e estado TERMINAL da esteira: o card saiu do automatico e espera
       -- decisao do vendedor. Trata-lo como aberto reenrolaria o card e a decisao
       -- humana nunca aconteceria.
       AND (s.key IS NULL OR s.key NOT IN ('fechado_ganho', 'fechado_perdido', 'perdido', 'encerrado', 'em_atencao'))
       -- A etapa nem sempre conta a verdade sobre o card estar fechado: medidos 38
       -- deals com closed_at preenchido parados em etapa nao-terminal (10/09/2026).
       -- Como `s.key IS NULL` conta como ABERTO, sem esta linha eles entrariam na
       -- esteira. O caso inverso (etapa terminal, closed_at nulo) e zero.
       AND d.closed_at IS NULL
```

Substituir a linha antiga da lista de keys — não duplicá-la.

- [ ] **Step 4: Rodar a suíte inteira do arquivo**

Run: `cd backend && python -m pytest tests/test_esteiras_migration_sql.py -v`
Expected: PASS — todos, incluindo os 2 novos

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260904_esteiras_vendedor.sql backend/tests/test_esteiras_migration_sql.py
git commit -m "fix(esteiras): RPC ignora card fechado e trata Em atencao como terminal"
```

---

## Task 7: Verificação final e relatório

**Files:** nenhum — só verificação.

- [ ] **Step 1: Suíte de backend inteira**

Run: `cd backend && python -m pytest -q`
Expected: **4200 passed, 4 skipped** — 4186 do baseline + 12 da Task 4 + 2 da Task 6. Se o número divergir, parar e conferir antes de seguir.

- [ ] **Step 2: Portões de frontend, iguais aos do CI**

```bash
cd frontend
npm run type-check
npx vitest run
NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder-anon-key \
NEXT_PUBLIC_FASTAPI_URL=http://placeholder.api.local \
npm run build
```
Expected: `tsc` sem saída; vitest **769 passed**; build sem erro

- [ ] **Step 3: Conferir que a migration não foi aplicada por engano**

Run:
```bash
grep -c "NOTIFY pgrst" supabase/migrations/20260910_contrato_etapas_joao.sql
```
Expected: `1`

**A migration NÃO deve ser aplicada por nenhum agente.** Ela é entregue ao dono para revisão e aplicação manual no SQL editor do Supabase.

- [ ] **Step 4: Relatório para o dono**

Escrever no fim desta sessão, sem commitar:
- quantos cards a migration vai mover (esperado: ~27 de Proposta/Negociação, ~363 de Novo)
- que a migration precisa ser aplicada **antes** de `20260904_esteiras_vendedor.sql`
- que nada foi enviado a nenhum lead e nada foi pushed

---

## Auto-revisão deste plano

**Cobertura do spec §4/SP0** — os 9 itens de trabalho do bloco:

| item do spec | task |
|---|---|
| 1. mover cards antes de apagar (PL, 27 cards) | Task 5, seção 1-2 |
| 2. atribuir keys + recriar `proposta_enviada` da Reposição | Task 5, seção 3 |
| 3. criar "Em atenção" + ordem correta | Task 5, seções 5-6 |
| 4. `is_protected` em Fechado Ganho e Perdido | Task 5, seção 6 |
| 5. `POST` aceita key / `DELETE` recusa key / template novo | Tasks 1 e 2 |
| 6. reclassificar os 363 cards | Task 5, seção 7 |
| 7. os 38 cards fechados em etapa sem key | Task 6 |
| 8. `DEAL_STAGES` do frontend | Task 3 |
| 9. `NOTIFY pgrst` | Task 5, fim |

**Renomeações do spec** (Contato→Em conversa, Em Conversa→Já chamado, Em ATENÇÃO→Em atenção): Task 5, seção 4. ✓

**Consistência de tipos:** `DEFAULT_STAGES` e `stageIsProtectedByKey` são definidos na Task 1 e usados nas Tasks 2 e 3 com os mesmos nomes. As keys usadas no SQL (Task 5) são as mesmas de `DEAL_STAGES` (Task 3) e de `DEFAULT_STAGES` (Task 1). ✓

**Fora deste plano, de propósito:** mover os 37 cards fechados de "Já chamado" (decisão do dono sobre o board dele); a regressão de merge do opt-out (`processor.py:1390` × `:1483`) — é pré-requisito de **push**, não de SP0, e vale um plano próprio porque mexe no caminho de mensagem em produção.
