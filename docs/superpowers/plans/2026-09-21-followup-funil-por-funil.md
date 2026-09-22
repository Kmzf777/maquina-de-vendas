# Editor por funil — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-21-followup-funil-por-funil-design.md`
**Branch:** `feat/followup-funil-ui`, a partir de `origin/master`

**Goal:** A tela de Follow-up navega pelos 5 funis do João (não mais por cadência),
cada um com seu próprio liga/desliga, prazo de gatilho e templates. Recuperação
aparece como funil vazio. Motor (números, partição, teto, trava de ativação) intacto.

**Architecture:** `cadence_joao.py` troca `Cadencia{linhas}` por `Funil{cadencias}`.
`CadenciaResolvida.linha` vira `.funil`. `scheduler.py`/`service.py`/`api.py` seguem o
mesmo rename na leitura de metadata/overrides. Frontend segue o payload novo.

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim. Não delegar em background.

**ORDEM, não tudo paralelo:** o Lote 2 IMPORTA símbolos novos de `cadence_joao.py`
(`Funil`, `CadenciaResolvida.funil`, `cadencia_do_funil`, etc.) — os testes dele só
importam de verdade depois que o Lote 1 estiver no disco. Por isso o Lote 1 roda
**sozinho e é verificado** antes de abrir o Lote 2.

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 1 | **F1** `cadence_joao.py` + migration | `cadence_joao.py`, migration, teste | — (sozinho) |
| 2 | **F2** scheduler | `scheduler.py`, teste | ✅ com F3, F4 |
| 2 | **F3** agendador | `service.py`, teste | ✅ com F2, F4 |
| 2 | **F4** API | `api.py`, teste | ✅ com F2, F3 |
| 3 | **F5** a tela | `followup-board.tsx`, testes | — (sozinho) |

```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

---

# LOTE 1 (sozinho)

## Task F1: `cadence_joao.py` vira funil-primeiro

**Files:** `backend/app/follow_up/cadence_joao.py`,
`supabase/migrations/20260918_followup_joao_config.sql`,
`backend/tests/test_cadence_joao_2026_09_18.py` (adaptar, não recriar do zero)

**LEIA:** o arquivo atual inteiro antes de mexer — a spec (§3) descreve a forma nova,
mas os NÚMEROS de cada cadência (offsets, nomes de template, `aceita_adiamento`) são
os que já estão em produção e **não mudam**. Copie-os, não reinvente.

- [ ] `Touch` sem mudança. `Linha` é removido; `Cadencia` passa a viver DENTRO de um
      funil (spec §3): ganha `gatilho_stage_rotulo: str` (hardcoded — ver a armadilha
      da spec §2: a cadência "Em atenção" tem rótulo de gatilho **"Cliente Ativo"**,
      NUNCA "Em atenção", porque ela vigia a etapa `novo`, não a etapa `em_atencao`).
- [ ] `Funil{codigo, rotulo, pipeline_id, cadencias: tuple[Cadencia,...]}`. Cinco
      instâncias em `FUNIS` — as quatro com os números atuais movidos para dentro
      (cada `Cadencia` de cada funil carrega SUA PRÓPRIA tupla de touches — "novo" do
      funil `atacado` e "novo" do funil `private_label` são dois objetos `Cadencia`
      diferentes, com templates diferentes, mesmo `codigo`), e
      `Funil("recuperacao", "João - Recuperação", PIPELINE_RECUPERACAO, ())` — vazio.
- [ ] `PIPELINE_RECUPERACAO = "fa94029b-d524-4550-919e-67233dfe3a94"`, mesmo padrão de
      comentário das outras quatro constantes (fonte + suíte cruza o valor).
- [ ] `CadenciaResolvida`: campo `linha: str` vira `funil: str`.
      `resolver_cadencia`, `resolver`, `toques_sem_template` trocam de assinatura
      `(codigo, linha, overrides)` para **`(funil, codigo, overrides)`** — funil
      primeiro (spec §3). Atualize TODOS os chamadores internos deste arquivo.
- [ ] Novos helpers públicos: `FUNIL_CODIGOS`, `funil(codigo) -> Funil | None`,
      `cadencia_do_funil(funil_codigo, cadencia_codigo) -> Cadencia | None` (spec §3,
      bloco de código exato). Remover `CADENCIAS`, `CODIGOS`, `cadencia_por_job_type`,
      `Linha`, `LINHA_ATACADO`, `LINHA_PRIVATE_LABEL`, `LINHAS` — **confirme antes de
      apagar** que nada além deste arquivo e do teste os usa (`grep -rn` em
      `backend/app`; a spec §3 já fez essa varredura e não achou uso em produção fora
      de `api.py`, que é o Lote 2 — mas confira de novo, o código pode ter mudado).
      `JOB_TYPES` fica (só depende de `codigo`, não de funil).
- [ ] `validar_toques`, `classificar_resposta`, `adiar_toques`, `ADIAMENTO_ESTOQUE`,
      `ROTULOS_ADIAMENTO`, `RESPOSTA_ADIAR`, `RESPOSTA_OPTOUT` — sem mudança de
      assinatura.
- [ ] Migration: editar `20260918_followup_joao_config.sql` **no lugar** (spec §4) —
      chave de `followup_joao_cadencia` vira `(funil, cadencia)`, de
      `followup_joao_toque` vira `(funil, cadencia, toque)` (a coluna `linha`
      desaparece). CHECK novo cruzando os pares `(funil, cadencia)` válidos — os
      cinco funis, `recuperacao` sem nenhum par aceito. Mantenha o cabeçalho de aviso
      ("não é aplicada pelo deploy") e o `NOTIFY pgrst, 'reload schema'`.
- [ ] Teste: adapte `test_cadence_joao_2026_09_18.py` para a assinatura
      `(funil, codigo, overrides)`. Casos que a spec pede explicitamente: sem override
      vale o código; com override vale o banco; `FUNIS` tem exatamente 5 entradas e a
      de `recuperacao` tem `cadencias == ()`; o par `(funil="atacado",
      cadencia="reposicao")` não existe (`cadencia_do_funil` devolve `None`); teste
      sobre o TEXTO do SQL (padrão `test_sql_cards_extraviados_2026_09_16.py`)
      cruzando os pares do CHECK com o que `cadence_joao.FUNIS` declara de verdade —
      **é este teste que impede o código e o banco de divergir silenciosamente**.
- [ ] Suíte verde (só este arquivo de teste vai passar sozinho ainda — os outros três
      quebram até o Lote 2, e isso é esperado). Reporte quais outros arquivos de teste
      já quebraram por causa do rename, para o orquestrador saber o que o Lote 2 herda.

**Ao terminar:** reporte a lista exata de símbolos públicos novos/removidos do módulo —
o Lote 2 depende dela.

---

# LOTE 2 — paralelo (só abre depois do F1 verificado)

## Task F2: scheduler segue o rename linha→funil

**Files:** `backend/app/follow_up/scheduler.py`,
`backend/tests/test_scheduler_joao_2026_09_18.py`

**LEIA ANTES:** as funções `_normalize_joao_linha`, `_resolve_joao_linha`,
`_joao_template_name`, `_LINHA_POR_PIPELINE` (linhas ~111-118, ~1645-1730 na versão
atual — confira o número real, o arquivo pode ter mudado) e todo `_process_joao_touch`.

**O caminho `standard` da ValerIA e o guard de blacklist recém-mesclado
(`is_lead_blacklisted`, PR #13, `_lead_stop_reason`) não podem mudar UMA LINHA.**

- [ ] `_LINHA_POR_PIPELINE` vira `_FUNIL_POR_PIPELINE` (spec §6) — **este é o fix de um
      bug latente**: o dicionário atual mapeia `PIPELINE_JOAO_ATACADO` e
      `PIPELINE_JOAO_REPOSICAO_ATACADO` para a MESMA string `"atacado"` (confirmado ao
      escrever a spec). O novo é 1:1, sem colisão — cinco valores possíveis
      (`atacado`, `private_label`, `reposicao_atacado`, `reposicao_private_label`; sem
      entrada para `recuperacao`, que não tem cadência que a gere).
- [ ] `_normalize_joao_linha`/`_resolve_joao_linha` → `_normalize_joao_funil`/
      `_resolve_joao_funil`, lendo `metadata.funil` (mesma ordem de fallback:
      metadata → `metadata.pipeline_id` → pipeline_id consultado do deal).
- [ ] `_joao_template_name` lê `metadata.template_por_funil` (era
      `template_por_linha`).
- [ ] `grep -n "linha" app/follow_up/scheduler.py` no fim da task: toda ocorrência que
      sobrar tem que ser sobre "quebra de linha" de texto (as duas do meio do arquivo,
      não relacionadas) ou sobre outra coisa — nenhuma sobre a cadência do João. Logs
      que hoje imprimem `linha=%s` passam a `funil=%s`.
- [ ] **Teste de regressão do caminho `standard`**: rode a suíte da ValerIA antes e
      depois — mesmo resultado. É o teste mais importante desta task, de novo.
- [ ] `JOAO_JOB_TYPES` (hardcoded neste arquivo, independente de `cj.JOB_TYPES`) — não
      mexe, os quatro `job_type` (`joao_novo`, `joao_em_conversa`, `joao_reposicao`,
      `joao_em_atencao`) não mudam de nome.

## Task F3: agendador vira funil-primeiro

**Files:** `backend/app/follow_up/service.py`,
`backend/tests/test_agendador_joao_2026_09_18.py`

**LEIA ANTES:** `carregar_overrides_joao`, `resolver_para_agendar`,
`_montar_jobs_da_matricula`, `_varrer_cadencia_joao`, `agendar_cadencias_joao`,
`motivo_para_pular_joao` — nesta ordem, é a ordem em que os dados fluem.

- [ ] `carregar_overrides_joao()`: nova forma `{funil: {codigo: {gatilho_dias, ativa,
      toques}}}` (spec §7) — lendo `followup_joao_cadencia`/`followup_joao_toque` já
      com a PK nova (`funil, cadencia[, toque]`). Continua **fail-closed**: erro de
      leitura (tabela ausente) devolve `{}`, aviso uma vez por processo — não mude
      esse comportamento, só a forma do dicionário.
- [ ] `resolver_para_agendar(funil, codigo, overrides_do_par)` — funil primeiro,
      overrides já achatado (sem o aninhamento `linhas.X.toques` de hoje, que só
      existia por causa das duas linhas).
- [ ] O laço duplo `for codigo in CODIGOS: for linha in JOAO_LINHAS:` vira um laço
      sobre `cj.FUNIS`, cada um perguntando só as SUAS cadências
      (`for cadencia_do_codigo in funil.cadencias`) — spec §7 tem o pseudocódigo
      exato. Recuperação sai de graça: `cadencias == ()`, zero iteração, sem `if`
      especial.
- [ ] `_montar_jobs_da_matricula` grava `metadata["funil"]` (era `metadata["linha"]`).
- [ ] `motivo_para_pular_joao` **não muda** — já decide por `cadencia.codigo`, não por
      linha/funil (confirmado lendo a função antes de escrever a spec). Não toque
      nela; só confirme que a suíte continua verde.
- [ ] `JOAO_LINHAS` (reexport de `cj.LINHAS`) é removido; troque pelos usos de
      `cj.FUNIL_CODIGOS` onde ainda fizer sentido iterar funis direto.
- [ ] Teste: cadência ativa só num funil não vaza para o outro; `recuperacao` nunca
      gera job (a suíte prova isso testando o comportamento, não checando um `if`);
      teto por passagem continua valendo por `(funil, cadencia)`.

## Task F4: API — GET devolve funis, PUT exige funil

**Files:** `backend/app/follow_up/api.py`,
`backend/tests/test_api_definicao_joao_2026_09_18.py`

**LEIA ANTES:** o arquivo inteiro — é pequeno o bastante (~650 linhas) e a mudança
toca a maior parte dele. A forma exata do payload GET e do corpo PUT está na spec §5,
copie literalmente.

- [ ] `_ROTULO_DA_LINHA` é removido — o rótulo do funil vem de `Funil.rotulo`.
- [ ] `_sobreposicao`/`_overrides` leem as tabelas pela PK nova (`funil, cadencia[,
      toque]`).
- [ ] `_cadencia_payload` (renomeie se fizer sentido) monta UM payload por `(funil,
      cadencia)` — `gatilho_stage_rotulo` incluso, lido de `Cadencia` do código, nunca
      do banco. `build_joao_definition` vira `{"funis": [...]}` iterando `cj.FUNIS` e,
      dentro, `funil.cadencias`.
- [ ] PUT: corpo passa a exigir `funil` (**não mais opcional**) — remova a lógica de
      "sem linha, aplica nas duas". `funil` fora de `cj.FUNIL_CODIGOS` → 404. Par
      `(funil, cadencia)` inválido (`cj.cadencia_do_funil` devolve `None`) → 404
      nomeando as cadências válidas DAQUELE funil (não a lista dos 4 códigos
      inteiros — confundiria mais do que ajudaria, spec §5).
- [ ] `Problema.linha` vira `Problema.funil` (mesmo dataclass, campo renomeado) — a
      resposta de erro que a tela lê muda de forma, o Lote 3 depende disso.
- [ ] A trava de ativação (template aprovado em todo toque) continua igual, agora
      escopada a UM `(funil, cadencia)` por vez em vez de "duas linhas" — mais simples
      que hoje, não mais complexo.
- [ ] Teste: GET devolve 5 funis, o de `recuperacao` com `cadencias: []`; PUT sem
      `funil` → 400/404 (não mais "aplica nas duas"); PUT com par inválido nomeia as
      cadências certas do funil pedido.

---

# LOTE 3 (sozinho, depois do Lote 2 verificado)

## Task F5: a tela

**Files:** `frontend/src/components/campaigns/followup-board.tsx`, testes do arquivo

**LEIA ANTES:** o componente inteiro (`JoaoEditor`, `DefinitionStrip`, os tipos no
topo do arquivo) — a spec §8 descreve a forma nova dos tipos e do estado de rascunho,
mas a UI (cores, classes Tailwind, padrão de rascunho→PUT→sucesso/erro) segue o
mesmo estilo do que já existe. Não é um redesenho visual, é uma reestruturação de
navegação.

- [ ] Tipos: `JoaoCadenciaDoFunil` e `JoaoFunil` (spec §8, bloco de código exato) no
      lugar de `JoaoLinha` e do `JoaoCadencia` de topo antigo.
- [ ] `JoaoEditor` recebe `funis: JoaoFunil[]`. Pílula de topo lista os 5 FUNIS pelo
      nome completo (`funil.rotulo` — "João - Reposição Atacado", não "Atacado").
      Dentro do funil selecionado, as cadências dele (no máximo 2); `cadencias.length
      === 0` (Recuperação) mostra estado vazio: "Nenhuma cadência configurada ainda
      para este funil."
- [ ] Estado de rascunho: chave composta `` `${funilCodigo}:${cadenciaCodigo}` ``
      (spec §8) — gatilho/ativa por par, toques não aninhados por linha (já são de
      uma cadência de um funil só).
- [ ] `salvar()`: **1 PUT por rascunho** (`{funil, cadencia, gatilho_dias?, ativa?,
      toques?}`) — mais simples que hoje (que montava até 2 PUTs de toque + 1 de
      cadência). A recusa do backend (agora com `Problema.funil`) continua aparecendo
      na tela — não repita o bug de 16/09 (validação recusa, tela fica muda).
- [ ] Gatilho mostra `cadencia.gatilho_stage_rotulo` (ex. "Cliente Ativo") em vez de
      `<code>{gatilho_stage_key}</code>`.
- [ ] `DefinitionStrip`: `definition.joao?.cadencias` vira `definition.joao?.funis`;
      `temJoao` = `funis.length > 0`.
- [ ] `tsc --noEmit` + `vitest run` verdes, cobrindo: funil vazio (Recuperação) sem
      quebrar a tela; 1 PUT por rascunho; erro do backend aparecendo com o funil certo
      nomeado.

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e **merge de `origin/master`** de novo (pode ter andado
      desde o início desta sessão de trabalho).
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD` — nenhum arquivo fora
      dos listados nas tasks acima deveria ser deletado.
- [ ] Backend inteiro (`pytest -q -p no:warnings`), `tsc`, `vitest`, `next build`
      verdes.
- [ ] Confirmar as 4 cadências continuam `ativa=False` no código e a migration
      editada continua sem nenhum `INSERT`.
- [ ] Confirmar a suíte da ValerIA (`standard`) idêntica antes/depois — zero
      regressão no único caminho que roda em produção hoje.
- [ ] **Não** pushar sem autorização.
