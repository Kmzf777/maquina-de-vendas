# Painel de Follow-up: toque, funil e etapa — plano

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-29-painel-toque-funil-design.md`
**Branch:** `feat/painel-toque-funil`, a partir de `origin/master` (`bac70c53`)

**Goal:** A lista de jobs mostra em que toque o lead está, de qual esteira, em qual funil
e em que etapa o card está AGORA — sem nenhum rótulo escrito à mão no frontend.

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim. Não delegar.

**ORDEM:** o Lote 2 importa o tipo `BoardJob` que o Lote 1 amplia. Por isso J1 roda
sozinho e é verificado antes de abrir os outros dois.

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 1 | **J1** tipo + rótulo do toque | `lib/followup-board.ts` + teste | — |
| 2 | **J2** a rota | `api/followups/route.ts` + teste | ✅ com J3 |
| 2 | **J3** a tabela | `followup-board.tsx` + teste | ✅ com J2 |

```
cd frontend && npx tsc --noEmit && npx vitest run
```

---

## CONTRATO J1 → J2 e J3

J1 define, J2 preenche, J3 consome. Nomes exatos:

```ts
export type BoardJob = {
  // … os campos de hoje, intocados …
  cadencia: string | null;      // "novo" | "em_conversa" | "proposta" | "reposicao" | "em_atencao"
  funil: string | null;         // "atacado" | "private_label" | "reposicao_atacado" | …
  toque: number | null;         // metadata.toque
  acao: string | null;          // "mover_etapa" quando o job MOVE o card
  etapa_atual: string | null;   // RÓTULO da etapa do card AGORA (já resolvido pela rota)
};

// `rotuloDaCadencia` vem da definição (/api/cadence/definition); null → cai no
// comportamento de hoje. NUNCA um mapa hardcoded aqui dentro.
export function touchTypeLabel(
  job: Pick<BoardJob, "job_type" | "sequence" | "toque" | "acao">,
  rotuloDaCadencia?: string | null,
): string;
```

`etapa_atual` já chega como RÓTULO ("Cliente Ativo"), não como key — a resolução é da
rota, que tem o banco à mão. A tela nunca traduz key.

---

# LOTE 1 (sozinho)

## Task J1: o tipo e o rótulo do toque

**Files:** `frontend/src/lib/followup-board.ts`, `frontend/src/lib/followup-board.test.ts`

- [ ] `BoardJob` ganha os cinco campos do CONTRATO acima.
- [ ] `touchTypeLabel` ganha o 2º parâmetro (opcional) e passa a resolver, nesta ordem:
      1. `acao === "mover_etapa"` → **"move o card"** (antes de qualquer número: esse job
         não é toque, e com `sequence` = último+1 ele apareceria como um toque que nunca
         existiu);
      2. job do João (`job_type` começa com `joao_`) → `"<rótulo> · <n>º toque"`, com o
         número vindo de `toque` e `sequence` como reserva. Sem rótulo (definição ainda
         não carregou) → só `"<n>º toque"`, **nunca** a chave crua;
      3. o resto — `standard`/null → `T<seq>`; os quatro rótulos de `JOB_TYPE_LABELS` →
         como hoje, sem mudança.
- [ ] **A chave crua não pode mais vazar para a tela em nenhum caminho.** O fallback
      `?? jt` de hoje é o defeito; substitua-o.
- [ ] **Mutação obrigatória:** fazer o ramo do João devolver `jt` e exigir vermelho.
      Relate.
- [ ] Teste também: `standard` e os quatro tipos antigos continuam **idênticos** — é a
      garantia de que a tela da ValerIA não muda.

---

# LOTE 2 — paralelo (depois de J1 verificado)

## Task J2: a rota expõe o contexto e resolve a etapa atual

**Files:** `frontend/src/app/api/followups/route.ts` + teste

A rota já faz `select` do `metadata` inteiro — os quatro primeiros campos são extração,
não coleta nova.

- [ ] Repassa `cadencia`, `funil`, `toque`, `acao` do `metadata` (ao lado do `objetivo`
      que já existe).
- [ ] `etapa_atual`: UMA consulta EM LOTE para a página inteira (no máximo 200 jobs),
      juntando `deals` → `pipeline_stages` pelos `metadata.deal_id` distintos, e
      devolvendo o **rótulo** (`label`) da etapa em que o card está AGORA.
      **Nunca uma consulta por job.**
- [ ] **A etapa vem do `deals`, NÃO de `metadata.stage_id`** (spec §3.4). Esse é o ponto
      da entrega: o metadata guarda a etapa da matrícula, e a diferença entre as duas é
      exatamente o que o operador precisa ver, porque card que mudou de coluna vai ter a
      esteira cancelada. Teste com os dois valores DIFERENTES e prove qual vence.
- [ ] **Fail-soft:** erro na consulta da etapa → `etapa_atual: null` e a resposta sai
      normalmente. Um painel de observação não pode quebrar por causa de uma coluna.
- [ ] Job sem `deal_id` (todos os da ValerIA) → `etapa_atual: null`, sem consulta.

## Task J3: a tabela

**Files:** `frontend/src/components/campaigns/followup-board.tsx` + seu teste

`FollowupBoard` já tem `definition` no state e renderiza a tabela no mesmo componente —
não há prop drilling.

- [ ] A coluna **Toque** passa a chamar `touchTypeLabel(j, rotulo)`, com o rótulo tirado
      de `definition.joao.funis[].cadencias[]` casando `j.funil` + `j.cadencia`.
- [ ] Coluna nova **"Funil / Etapa"**: rótulo do funil em cima (de
      `definition.joao.funis[].rotulo`), `etapa_atual` embaixo. Job sem funil (ValerIA)
      → traço.
- [ ] **Nenhum rótulo hardcoded.** Tudo sai da definição. **Mutação obrigatória:** trocar
      o rótulo dentro da definição de teste e provar que a tela acompanha — se ela mostrar
      o valor antigo, há um mapa escondido. Relate.
- [ ] Definição ainda não carregada (`definition === null`, a tabela carrega antes) → a
      coluna mostra o código ou traço, **nunca** quebra e nunca escreve "undefined".
- [ ] A tabela já rola na horizontal; confira que a coluna nova não estoura o layout no
      celular.
- [ ] NOTA DE AMBIENTE: se faltar `node_modules`, rode `npm ci` de verdade. **Não** crie
      symlink para o `node_modules` do repo principal — o Turbopack recusa e o
      `next build` quebra.

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e merge de `origin/master`.
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD` — vazio.
- [ ] `tsc`, `vitest` e `next build` verdes.
- [ ] Nenhuma chave crua (`joao_`) chega à tela em nenhum caminho.
- [ ] O motor não foi tocado: `git diff --stat origin/master..HEAD -- backend/` vazio.
- [ ] **Não** pushar sem autorização.
