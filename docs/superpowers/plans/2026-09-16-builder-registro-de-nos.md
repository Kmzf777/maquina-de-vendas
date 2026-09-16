# Builder: registro de nós — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development`.
> Passos usam checkbox (`- [ ]`).

**Spec:** `docs/superpowers/specs/2026-09-16-builder-registro-de-nos-design.md`
**Worktree:** `.claude/worktrees/builder-registro-nos` — branch `feat/builder-registro-nos`

**Goal:** Tornar o builder de `/campanhas` a única ferramenta de cadências, com o
contrato do motor declarado num registro único do qual derivam tela, defaults e
validação.

**Architecture:** `node_registry.py` (dado puro, sem I/O) → consumido por
`validation.py` (Python), pelo endpoint `GET /api/campaigns/node-schema` e, via esse
endpoint, pelo inspector. Ativação migra para o FastAPI; a rota Next vira proxy.

**Tech Stack:** FastAPI + Supabase (Python 3.12, pytest) · Next.js App Router
(TypeScript, vitest).

---

## Disciplina de paralelismo

Os lotes abaixo são **disjuntos por arquivo**. Um agente só pode tocar os arquivos
listados na sua task. Se precisar de outro arquivo, **pare e reporte** em vez de editar.

**Proibido a todo agente:** `git checkout`, `git restore`, `git reset`, `git stash`,
`git rebase`, `git merge`, `git push`. Commit é permitido (`git add` dos SEUS arquivos +
`git commit`).

| Lote | Tasks | Paralelo? |
|---|---|---|
| 1 | T1 | não (fundação) |
| 2 | T2, T3, T4 | sim |
| 3 | T5, T6 | sim |
| 4 | T7, T8 | sim |
| 5 | T9 | não |
| 6 | T10, T11 | sim |
| 7 | T12 | não |

Comandos de verificação (do worktree):
```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

---

# LOTE 1 — fundação

## Task 1: o registro de nós

**Files:**
- Create: `backend/app/campaigns/node_registry.py`
- Test: `backend/tests/test_node_registry.py`

- [ ] **Passo 1 — escrever o teste que trava o contrato**

O teste central varre o motor e exige que nada seja lido fora do registro. É ele que
impede a próxima divergência.

```python
# backend/tests/test_node_registry.py
import re, io, pathlib
from app.campaigns.node_registry import REGISTRO, VOCABULARIOS

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "app" / "automation"

def _chaves_lidas(arquivo: str) -> set[str]:
    txt = io.open(RAIZ / arquivo, encoding="utf-8").read()
    return set(re.findall(r'cfg\.get\(\s*"([a-z_]+)"', txt))

def test_toda_chave_lida_pelo_motor_esta_no_registro():
    declaradas = {c.chave for t in REGISTRO.values() for c in t.campos}
    # chaves de controle do motor, nao configuraveis pela tela
    internas = {"trigger_type", "action_type", "condition_type", "final_actions",
                "stage_name", "limit"}
    lidas = _chaves_lidas("engine.py") | _chaves_lidas("triggers.py")
    faltando = lidas - declaradas - internas
    assert not faltando, f"motor le chaves fora do registro: {sorted(faltando)}"

def test_vocabulario_de_stage_filter_por_gatilho():
    """O bug de 16/09: um select servindo dois vocabularios, errado para os dois."""
    esperado = {
        "no_message": "segmento_lead", "stage_stagnation": "segmento_lead",
        "no_sale_in_stage": "segmento_lead", "stage_enter": "segmento_lead",
        "deal_stage_enter": "etapa_key",
    }
    for sub, vocab in esperado.items():
        campo = next(c for c in REGISTRO[("trigger", sub)].campos
                     if c.chave == "stage_filter")
        assert campo.vocab == vocab, f"{sub}: {campo.vocab} != {vocab}"

def test_stage_filter_obrigatorio_onde_o_motor_pula_sem_ele():
    """`if not stage: continue` em triggers.py — sem filtro o gatilho e inerte."""
    for sub in ("stage_stagnation", "no_sale_in_stage"):
        campo = next(c for c in REGISTRO[("trigger", sub)].campos
                     if c.chave == "stage_filter")
        assert campo.obrigatorio, f"{sub}: stage_filter tem de ser obrigatorio"

def test_create_deal_exige_funil():
    campos = {c.chave: c for c in REGISTRO[("action", "create_deal")].campos}
    assert campos["pipeline_id"].vocab == "funil_id"
    assert campos["pipeline_id"].obrigatorio
    assert "stage_key" in campos and campos["stage_key"].vocab == "etapa_key"

def test_send_exige_template():
    campo = next(c for c in REGISTRO[("send", None)].campos if c.chave == "template_name")
    assert campo.vocab == "template" and campo.obrigatorio

def test_deal_stage_stagnation_requer_etapa_por_id_ou_key():
    assert ("stage_id", "stage_key") in REGISTRO[("trigger", "deal_stage_stagnation")].requer_um_de

def test_on_reply_existe_no_gatilho_e_nao_tem_default_no_no():
    gat = {c.chave: c for c in REGISTRO[("trigger", "deal_stage_stagnation")].campos}
    assert gat["on_reply"].vocab == "politica_resposta"
    envio = {c.chave: c for c in REGISTRO[("send", None)].campos}
    assert envio["on_reply"].default is None, "default no no mataria o reset do gatilho"

def test_replied_only_nao_existe():
    """post_broadcast: o toggle nao era lido por ninguem."""
    campos = {c.chave for c in REGISTRO[("trigger", "post_broadcast")].campos}
    assert "replied_only" not in campos

def test_todo_vocabulario_usado_e_conhecido():
    for t in REGISTRO.values():
        for c in t.campos:
            assert c.vocab in VOCABULARIOS, f"{t.subtipo}.{c.chave}: {c.vocab}"

def test_as_nove_condicoes_estao_na_paleta():
    conds = [t for (tipo, _), t in REGISTRO.items() if tipo == "condition"]
    assert len(conds) == 9
    assert all(t.na_paleta for t in conds)
```

- [ ] **Passo 2 — rodar e ver falhar**

`cd backend && python -m pytest tests/test_node_registry.py -q` → ModuleNotFoundError.

- [ ] **Passo 3 — implementar o registro**

Conteúdo exato na §3.1 do spec. Estruturas:

```python
from dataclasses import dataclass, field
from typing import Any

VOCABULARIOS = {
    "texto", "texto_longo", "numero", "booleano",
    "segmento_lead", "etapa_key", "etapa_id", "funil_id", "canal_id",
    "template", "tag", "usuario_id", "lista_usuario_id", "lista_texto",
    "operador", "politica_resposta", "severidade",
}

@dataclass(frozen=True)
class Campo:
    chave: str
    vocab: str
    rotulo: str
    obrigatorio: bool = False
    default: Any = None
    ajuda: str = ""

@dataclass(frozen=True)
class TipoDeNo:
    tipo: str
    subtipo: str | None
    rotulo: str
    icone: str
    campos: tuple[Campo, ...]
    requer_um_de: tuple[tuple[str, ...], ...] = ()
    na_paleta: bool = True

REGISTRO: dict[tuple[str, str | None], TipoDeNo] = { ... }

def para_json() -> list[dict]:
    """Forma serializavel consumida por GET /api/campaigns/node-schema."""
```

A docstring do módulo deve registrar **por que** ele existe: o inspector escrevia rótulo
de coluna onde o motor lia segmento de lead, e cinco gatilhos nunca casavam.

- [ ] **Passo 4 — testes verdes**

- [ ] **Passo 5 — commit**
```bash
git add backend/app/campaigns/node_registry.py backend/tests/test_node_registry.py
git commit -m "feat(builder): registro de nos como contrato unico do motor"
```

---

# LOTE 2 — paralelo (3 agentes)

## Task 2: `create_deal` do motor ganha funil, etapa e dedupe

**Files:** Modify `backend/app/automation/engine.py` · Test
`backend/tests/test_create_deal_action_2026_09_16.py`

- [ ] **Passo 1 — teste**: nó `create_deal` com `pipeline_id`/`stage_key`/`dedupe_open`
      repassa os três para `leads.service.create_deal`; sem `pipeline_id` a ação devolve
      `False` e loga `skipped` (em vez de criar no "primeiro funil").
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar:**
```python
elif action_type == "create_deal":
    from app.leads.service import create_deal
    pipeline_id = cfg.get("pipeline_id")
    if not pipeline_id:
        # Sem funil explicito, `create_deal` cai no fallback "primeiro pipeline" e o
        # card nasce no funil errado — foi o que espalhou 19 cards de reposicao em
        # "Valeria - Importacao Leads Frios". Melhor nao agir.
        logger.warning("[AUTOMATION] create_deal sem pipeline_id — nao cria")
        return False
    title = substitute_variables(cfg.get("title_template", "Deal automático"), lead, enrollment)
    create_deal(
        enrollment["lead_id"], title, cfg.get("category"),
        pipeline_id=pipeline_id,
        stage_key=cfg.get("stage_key") or None,
        dedupe_open=bool(cfg.get("dedupe_open")),
        dedupe_pipeline_id=pipeline_id if cfg.get("dedupe_open") else None,
    )
    agiu = True
```
- [ ] **Passo 4 — suíte backend verde.**
- [ ] **Passo 5 — commit** `fix(builder): acao create_deal exige funil em vez de cair no primeiro`

## Task 3: `dedupe_open` move o card reaproveitado para a etapa pedida

**Files:** Modify `backend/app/leads/service.py` · Test
`backend/tests/test_dedupe_open_move_2026_09_16.py`

- [ ] **Passo 1 — teste**: com `dedupe_open=True` + `stage_key="novo"`, card existente
      numa **outra** etapa do mesmo funil é **movido** para `novo` e `entered_stage_at`
      é atualizado; card já em `novo` não sofre update; sem `stage_key`, nada muda.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar** no bloco `if dedupe_open:` de `create_deal`: se
      `stage_key` foi informado, resolver `stage_id_by_key(...)` no funil do card
      existente e, se diferente do atual, `update` de `stage_id` + `entered_stage_at`.
      Comentar o porquê: `entered_stage_at` é o relógio de `deal_stage_stagnation`;
      reaproveitar sem mover deixa a etapa de destino permanentemente vazia.
- [ ] **Passo 4 — suíte verde.** Atenção: `test_reposicao*.py` já existem — se algum
      travar o comportamento antigo, **traduza** a expectativa (não apague o teste) e
      explique no commit.
- [ ] **Passo 5 — commit** `fix(reposicao): card reaproveitado vai para a etapa pedida`

## Task 4: script SQL dos 19 cards extraviados

**Files:** Create `scripts/corrige_cards_reposicao_extraviados.sql` · Test
`backend/tests/test_sql_cards_extraviados_2026_09_16.py`

- [ ] **Passo 1 — teste sobre o TEXTO do SQL** (a suíte não tem banco): o arquivo
      contém `BEGIN`/`COMMIT`, filtra por `title = 'Reposição'`, restringe ao funil
      `Valéria - Importação Leads Frios`, e **não** contém `DELETE` nem `DROP`.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — escrever o SQL**: `SELECT` de conferência comentado no topo, depois o
      `UPDATE` que move cada card para o funil de reposição correspondente à origem,
      etapa `novo`, atualizando `entered_stage_at`. Cabeçalho explicando que **não é
      migration** e é aplicado à mão após revisão.
- [ ] **Passo 4 — teste verde.**
- [ ] **Passo 5 — commit** `chore(reposicao): SQL de correcao dos cards extraviados`

---

# LOTE 3 — paralelo (2 agentes)

## Task 5: camada de validação

**Files:** Create `backend/app/campaigns/validation.py` · Test
`backend/tests/test_campaign_validation_2026_09_16.py`

- [ ] **Passo 1 — um teste por regra, cada um por INJEÇÃO** (monta o grafo violando e
      exige recusa). Regras 1–8 da §4 do spec. Mais: grafo válido → `[]`.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar:**
```python
@dataclass(frozen=True)
class Problema:
    no_id: str | None
    codigo: str
    mensagem: str

def validar(campanha: dict, nos: list[dict],
            templates_aprovados: set[str] | None) -> list[Problema]:
    """Pura. `templates_aprovados=None` = consulta falhou → pula SÓ a regra 8."""
```
      Ciclo por DFS; alcançabilidade por BFS do gatilho.
- [ ] **Passo 4 — suíte verde.**
- [ ] **Passo 5 — commit** `feat(builder): validacao de campanha antes de ativar`

## Task 6: endpoint do schema

**Files:** Modify `backend/app/campaigns/router.py` · Test
`backend/tests/test_node_schema_endpoint_2026_09_16.py`

- [ ] **Passo 1 — teste**: `GET /api/campaigns/node-schema` devolve 200 com uma entrada
      por item do `REGISTRO`, cada uma com `tipo`, `subtipo`, `rotulo`, `icone`,
      `campos[]` (com `chave`, `vocab`, `obrigatorio`, `default`) e `na_paleta`.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar** `@router.get("/node-schema")` chamando
      `node_registry.para_json()`. **Sem** tocar em `/activate` (é da Task 7).
- [ ] **Passo 4 — verde.**
- [ ] **Passo 5 — commit** `feat(builder): endpoint do schema de nos`

---

# LOTE 4 — paralelo (2 agentes)

## Task 7: ativação validada no FastAPI

**Files:** Modify `backend/app/campaigns/router.py` · Test
`backend/tests/test_activate_guards_2026_09_16.py`
*(depende de T5 e T6 — o arquivo já terá o endpoint do schema; não o altere)*

- [ ] **Passo 1 — teste**: activate com template pendente → **400** com os nomes na
      mensagem; com campo obrigatório vazio → 400; com grafo em ciclo → 400; válido →
      200 e `status='active'`. Consulta de templates falhando → **não** bloqueia por
      causa da regra 8 (fail-open) mas ainda aplica as demais.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar** em `api_activate_campaign`: carregar nós, buscar
      `message_templates` dos nomes usados, chamar `validation.validar`, e em caso de
      problemas `raise HTTPException(400, detail={"problemas": [...]})`.
- [ ] **Passo 4 — verde.**
- [ ] **Passo 5 — commit** `feat(builder): ativar exige campanha valida e template aprovado`

## Task 8: rotas Next viram proxy

**Files:** Modify `frontend/src/app/api/campaigns/[id]/activate/route.ts`,
`frontend/src/app/api/campaigns/[id]/route.ts` · Test
`frontend/src/app/api/campaigns/__tests__/activate-proxy.test.ts`

- [ ] **Passo 1 — teste**: o `POST` encaminha para
      `${FASTAPI_URL}/api/campaigns/{id}/activate` e repassa status e corpo do upstream;
      o `PATCH` responde **400** quando o corpo traz `status`.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar** seguindo o padrão de
      `frontend/src/app/api/automation/[...path]/route.ts`. No `PATCH`, recusar `status`
      com a mensagem "use /activate ou /pause".
- [ ] **Passo 4 — `npx tsc --noEmit && npx vitest run` verde.**
- [ ] **Passo 5 — commit** `refactor(builder): ativacao passa pelo FastAPI`

---

# LOTE 5 — inspector (1 agente, arquivos acoplados)

## Task 9: tela derivada do schema

**Files:** Create `frontend/src/lib/node-schema.ts` · Modify
`frontend/src/components/campaigns/cadence-flow/helpers.ts`,
`.../constants.ts`, `.../inspector.tsx` · Tests: `node-schema.test.ts`,
`helpers.test.ts` (existe), `inspector.test.tsx` (novo)

- [ ] **Passo 1 — testes:**
  - `getDefaultConfig(tipo, sub)` devolve exatamente os defaults do schema.
  - Campo de vocabulário `segmento_lead` é populado com segmentos de lead; `etapa_key`
    com keys de coluna; `etapa_id` com UUID de coluna; `funil_id` com funis.
  - Template **não aprovado é selecionável** (sem `disabled`) e o nó mostra pendência.
  - `on_reply` aparece no gatilho; nos nós `send` é rotulado como override e **não** tem
    default.
  - `replied_only` não é renderizado.
  - Paleta expõe as 9 condições.
- [ ] **Passo 2 — falhar.**
- [ ] **Passo 3 — implementar:** `node-schema.ts` busca `/api/campaigns/node-schema` e
      tipa a resposta; `helpers.getDefaultConfig` passa a derivar do schema;
      `constants.ts` monta a paleta do schema (`na_paleta`); `inspector.tsx` escolhe a
      lista de opções **pelo vocabulário do campo**, não pelo nome do subtipo.
- [ ] **Passo 4 — `tsc` + `vitest` verdes.**
- [ ] **Passo 5 — commit** `feat(builder): inspector derivado do schema de nos`

---

# LOTE 6 — paralelo (2 agentes)

## Task 10: aposentar a aba Esteiras

**Files:** Delete `backend/app/campaigns/esteiras_router.py`,
`frontend/src/components/campaigns/esteiras-tab.tsx`, `esteiras-tab.test.tsx`,
`frontend/src/app/api/automation/esteiras/**`, `backend/tests/test_esteiras_router.py` ·
Modify `backend/app/main.py`, `frontend/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Passo 1** — remover `"esteiras"` de `VALID_TABS` e o `<EsteirasTab />`; remover
      `include_router(esteiras_router)`.
- [ ] **Passo 2** — apagar os arquivos. `backend/app/campaigns/esteiras.py` **fica**.
- [ ] **Passo 3** — suítes verdes (backend + frontend + `tsc`).
- [ ] **Passo 4 — commit** `refactor(campanhas): builder substitui a aba Esteiras`

## Task 11: limpar campanhas de teste

**Files:** Create `scripts/apaga_campanhas_de_teste.sql` · Test
`backend/tests/test_sql_campanhas_teste_2026_09_16.py`

- [ ] **Passo 1 — teste sobre o texto**: só apaga as três por nome exato
      (`Tiburcio-Miranda-2`, `cadencia`, `Cadencia Teste deletar`), exige
      `status = 'draft'` e ausência de matrículas, e está em transação.
- [ ] **Passo 2/3/4** — escrever, verde, **não aplicar**.
- [ ] **Passo 5 — commit** `chore(campanhas): SQL para apagar campanhas de teste`

## Task 11b: aposentar o corretivo antigo de cards extraviados

Achado pelo agente da Task 4, fora do escopo dela.

**Files:** Modify `scripts/recuperacao/corrigir_deals_reposicao.sql`,
`backend/tests/test_recuperacao_migration_2026_09_09.py`

Existem DOIS scripts corretivos para o mesmo incidente, e o antigo está errado:
`corrigir_deals_reposicao.sql` (09/09/2026) só conhece **um** destino — João - Reposição
Atacado — com a etapa por UUID cravado, porque foi escrito **antes** de o funil
Private Label existir (10/09/2026). Aplicado hoje, mandaria para o funil errado todo
card cuja venda de origem fosse Private Label. Nunca foi aplicado.

- [ ] **Passo 1** — teste em `test_recuperacao_migration_2026_09_09.py` exigindo que o
      arquivo antigo comece com um aviso `SUPERSEDIDO` apontando para
      `scripts/corrige_cards_reposicao_extraviados.sql` e explicando o defeito do
      destino único.
- [ ] **Passo 2** — ver falhar.
- [ ] **Passo 3** — escrever o cabeçalho de aviso. **Não apagar o script** nem o resto
      do teste: o arquivo documenta o incidente de 09/09 e a classe
      `TestCorretivoDosDealsExtraviados` trava o conteúdo dele.
- [ ] **Passo 4** — suíte verde.
- [ ] **Passo 5 — commit** `chore(reposicao): marca o corretivo de 09/09 como supersedido`

---

# LOTE 7 — fechamento

## Task 12: revisão final e build

- [ ] Suíte backend completa verde.
- [ ] `npx tsc --noEmit`, `npx vitest run`, `npx next build` (copiar `.env.local` e
      `.env.build` do repo principal para o worktree — são gitignored).
- [ ] Conferir `git diff --diff-filter=D --name-only origin/master..HEAD` — apagados
      devem ser **apenas** os arquivos da Task 10.
- [ ] **Não** fazer push. A branch fica para revisão.
