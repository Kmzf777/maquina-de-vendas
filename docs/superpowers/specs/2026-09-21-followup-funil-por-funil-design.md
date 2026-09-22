# Tela de Follow-up — personalização por funil, não por cadência

**Data:** 2026-09-21
**Branch:** `feat/followup-funil-ui`, a partir de `origin/master`
**Depende de:** `docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md` (o motor já
em produção — este spec reformula sua estrutura de dados e sua tela, não o motor em si)

## 1. O problema, confirmado no código

O motor do João (produção, `origin/master`) organiza tudo por **cadência** (Novo, Em
conversa, Reposição, Em atenção). Dentro de cada cadência existe uma "linha" — uma
string genérica, `"atacado"` ou `"private_label"` — que aponta para um `pipeline_id`.

O bug de identidade: a MESMA string `"atacado"` aponta para pipelines DIFERENTES
dependendo da cadência em que está:

| Cadência   | `linha="atacado"` aponta para |
|---|---|
| Novo, Em conversa | `João - Atacado` (`9706a14a…`) |
| Reposição, Em atenção | `João - Reposição Atacado` (`79e35e6b…`) |

Confirmado em `backend/app/follow_up/scheduler.py` (`_LINHA_POR_PIPELINE`): esse mesmo
dicionário mapeia os DOIS pipelines diferentes para a mesma chave `"atacado"` — um
dado a mais de que a colisão não é só na tela, está também no fallback do handler que
resolve a linha pelo `pipeline_id` do card quando o job não carrega `metadata.linha`.

Na tela (`followup-board.tsx`, `JoaoEditor`), a navegação principal é por cadência; a
seção de dentro só mostra o rótulo genérico ("Atacado"/"Private Label"), sem o nome do
funil. Resultado: quem abre a aba "Reposição" e vê a seção "Atacado" não tem como saber
que está editando `João - Reposição Atacado`, e não `João - Atacado`. O gatilho também
aparece cru — `<code>novo</code>` — sem dizer que "novo" é a etapa "Cliente Ativo" no
funil de Reposição.

Existe ainda um QUINTO funil que o motor não conhece: **João - Recuperação**
(`fa94029b…`, funil manual do vendedor: Entrada de Inativos → Em Follow-UP →
Recuperado → Perdido Churn). Ele não tem cadência nenhuma hoje. Decisão do usuário
(brainstorming, 2026-09-21): entra nesta entrega **só como espaço reservado** — aparece
na tela como funil de verdade, com zero cadências, pronto para ganhar uma quando
alguém definir o gatilho e os toques.

## 2. Direção aprovada: funil é o eixo, cadência é o que existe dentro dele

Inverter a estrutura: hoje é `cadência → {linha: pipeline}`; passa a ser
`funil → [cadências deste funil]`. Cada funil é uma entidade só sua — identificada
pelo `pipeline_id` (o mesmo contrato estável que `PIPELINE_ATACADO` etc. já usam), não
pelo nome digitável na tela do CRM.

```
João - Atacado                  → [Novo, Em conversa]
João - Private Label            → [Novo, Em conversa]
João - Reposição Atacado        → [Reposição, Em atenção]
João - Reposição Private Label  → [Reposição, Em atenção]
João - Recuperação              → []          (vazio de propósito)
```

Os NÚMEROS de cada cadência (dias, toques, templates) não mudam — só onde eles moram.
A partição por fato entre `reposicao` e `em_atencao` (`_reposicao_concluida`, lida do
job) continua igual, só que agora cada metade dela vive isolada dentro do seu próprio
funil de Reposição.

### Decisão 1 — Atacado e Private Label deixam de estar acoplados

Hoje uma única linha em `followup_joao_cadencia` (chave só `cadencia`) liga/desliga e
define o prazo das DUAS linhas ao mesmo tempo — "ligar só metade seria uma quinta
alavanca", diz o comentário original. Com funil como eixo, isso deixa de fazer
sentido: cada um dos 5 funis passa a ter seu próprio liga/desliga e seu próprio prazo
de gatilho, independente dos outros. É o que "cada um com seus delays
personalizáveis" pede. **Aprovado pelo usuário em 2026-09-21.**

### Decisão 2 — rótulo de etapa vem do código, não do banco

A tela vai mostrar o nome da etapa do gatilho (ex. "Cliente Ativo") em vez da chave
crua (`novo`). Esse rótulo é **hardcoded em `cadence_joao.py`**, no mesmo padrão já
usado no módulo de contas do Bling (rótulo é decisão de código; o `label` gravado em
`pipeline_stages` é editável por qualquer operador no CRM e não é um contrato estável
para esta tela se ancorar). **Aprovado pelo usuário em 2026-09-21.**

### Armadilha a evitar na implementação

As quatro pipelines (Atacado, Private Label, Reposição Atacado, Reposição Private
Label) têm, cada uma, uma etapa DE VERDADE chamada `em_atencao` / "Em atenção"
(confirmado via `pipeline_stages`). A CADÊNCIA "Em atenção" **não vigia essa etapa** —
ela vigia `novo` ("Cliente Ativo") aos 90 dias, junto com "Reposição". O rótulo
hardcoded do gatilho da cadência "Em atenção" tem que ser "Cliente Ativo", nunca "Em
atenção" — usar o nome da cadência como se fosse o nome da etapa reintroduziria a
mesma classe de confusão que este spec corrige.

## 3. `cadence_joao.py` — nova forma

```python
@dataclass(frozen=True)
class Touch:                    # sem mudança de forma
    sequence: int
    offset: timedelta
    template_name: str | None
    aceita_adiamento: bool = False

@dataclass(frozen=True)
class Cadencia:
    """Uma cadência DENTRO de um funil — antes era `Linha`."""
    codigo: str                 # "novo" | "em_conversa" | "reposicao" | "em_atencao"
    rotulo: str                 # "Novo", "Em conversa", ...
    gatilho_stage_key: str
    gatilho_stage_rotulo: str   # NOVO — "Cliente Ativo", nunca lido do banco
    gatilho_dias: int
    touches: tuple[Touch, ...]
    repete_ultimo: bool = False
    ativa: bool = False

    @property
    def job_type(self) -> str:
        return f"joao_{self.codigo}"

@dataclass(frozen=True)
class Funil:
    codigo: str                 # "atacado" | "private_label" | "reposicao_atacado"
                                 # | "reposicao_private_label" | "recuperacao"
    rotulo: str                 # "João - Atacado"
    pipeline_id: str
    cadencias: tuple[Cadencia, ...]   # () para recuperacao

FUNIS: tuple[Funil, ...] = (
    Funil("atacado", "João - Atacado", PIPELINE_ATACADO, (novo_atacado, em_conversa_atacado)),
    Funil("private_label", "João - Private Label", PIPELINE_PRIVATE_LABEL, (...)),
    Funil("reposicao_atacado", "João - Reposição Atacado", PIPELINE_REPOSICAO_ATACADO, (...)),
    Funil("reposicao_private_label", "João - Reposição Private Label", PIPELINE_REPOSICAO_PRIVATE_LABEL, (...)),
    Funil("recuperacao", "João - Recuperação", PIPELINE_RECUPERACAO, ()),
)
```

`PIPELINE_RECUPERACAO = "fa94029b-d524-4550-919e-67233dfe3a94"` — constante nova, mesma
convenção das outras quatro (comentário citando a fonte e a suíte que cruza o valor).

`CadenciaResolvida` troca o campo `linha: str` por `funil: str` (o código do Funil, não
mais `"atacado"`/`"private_label"`). Mantém `codigo`, `job_type`, `pipeline_id`,
`gatilho_stage_key`, `gatilho_dias`, `ativa`, `repete_ultimo`, `touches`. Ganha
`gatilho_stage_rotulo`.

Funções públicas mudam de assinatura `(codigo, linha, overrides)` para
`(funil, codigo, overrides)` — **atenção à ordem dos parâmetros**, `funil` primeiro:
- `resolver_cadencia(funil, codigo, overrides) -> tuple[Touch, ...]`
- `resolver(funil, codigo, overrides) -> CadenciaResolvida`
- `toques_sem_template(funil, codigo, overrides) -> tuple[int, ...]`

`validar_toques`, `classificar_resposta`, `adiar_toques`, `ADIAMENTO_ESTOQUE`,
`ROTULOS_ADIAMENTO` — sem mudança de assinatura, só de onde os dados vêm.

**`CADENCIAS`/`CODIGOS`/`cadencia_por_job_type` deixam de fazer sentido e são
removidos.** No código de hoje, `CADENCIAS: Mapping[str, Cadencia]` funciona porque
existe UMA `Cadencia` por código, contendo as duas linhas dentro dela (`.linhas`). Na
forma nova, cada funil declara sua PRÓPRIA instância de `Cadencia` para o mesmo código
— `Funil("atacado", ...)` tem um `Cadencia(codigo="novo", touches=(...template do
Atacado...))` e `Funil("private_label", ...)` tem OUTRO `Cadencia(codigo="novo",
touches=(...template do Private Label...))` — são objetos diferentes (touches
diferentes) com o mesmo `codigo`. Um mapa achatado por `codigo` teria que escolher
arbitrariamente qual dos dois devolver, o que reintroduziria a ambiguidade que este
spec elimina. **Verificado antes de escrever este spec:** `cj.CADENCIAS`/`cj.CODIGOS`
só são consumidos dentro de `api.py` (linhas 265, 318, 484, 489), e todos os três
call sites já estão sendo reescritos na Seção 5; `cadencia_por_job_type` não tem
NENHUM chamador em código de produção, só em `test_cadence_joao_2026_09_18.py` — o
teste é adaptado junto.

Helpers públicos novos, que substituem os removidos:

```python
FUNIL_CODIGOS: tuple[str, ...] = tuple(f.codigo for f in FUNIS)
_POR_FUNIL: Mapping[str, Funil] = {f.codigo: f for f in FUNIS}

def funil(codigo: str) -> Funil | None:
    """O funil pelo código, ou None. Usa `.cadencias` para saber o que ele tem."""
    return _POR_FUNIL.get(codigo)

def cadencia_do_funil(funil_codigo: str, cadencia_codigo: str) -> Cadencia | None:
    """A cadência de UM funil, ou None se o par não existe (ex. qualquer par com
    `funil_codigo="recuperacao"`, ou `funil_codigo="atacado"` com
    `cadencia_codigo="reposicao"`). É o `cj.CADENCIAS[codigo]` de hoje, com o funil
    como parte obrigatória da chave — o mesmo motivo da Seção 1."""
    f = _POR_FUNIL.get(funil_codigo)
    if not f:
        return None
    return next((c for c in f.cadencias if c.codigo == cadencia_codigo), None)
```

`JOB_TYPES` continua existindo (frozenset dos 4 `job_type` possíveis,
`f"joao_{codigo}"` para os 4 códigos de cadência) — só depende de `codigo`, não de
funil, então nada muda nele. Note que `scheduler.py` já tem seu próprio
`JOAO_JOB_TYPES` hardcoded (duplicação preexistente, fora do escopo deste spec) — não
precisa sincronizar os dois, só não quebrar o que já existe lá.

`job_type` continua ambíguo entre funis que compartilham cadência (ex.
`reposicao_atacado` e `reposicao_private_label` compartilham
`job_type="joao_reposicao"`) — **é assim hoje também** (Atacado e Private Label já
compartilhavam `joao_novo`). O handler resolve o funil certo pelo `metadata` do job,
não pelo `job_type`.

Remover: `Linha`, `LINHA_ATACADO`, `LINHA_PRIVATE_LABEL`, `LINHAS`, `CADENCIAS`,
`CODIGOS`, `cadencia_por_job_type`.

## 4. Migração das tabelas de sobreposição

Editar `supabase/migrations/20260918_followup_joao_config.sql` **no lugar** — ela nunca
foi aplicada em produção (confirmado: leitura fail-closed, zero linha inserida), então
não há dado real para migrar. Trocar a chave:

```sql
CREATE TABLE IF NOT EXISTS followup_joao_cadencia (
  funil          text NOT NULL,
  cadencia       text NOT NULL,
  gatilho_dias   integer,
  ativa          boolean,
  atualizado_por text,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (funil, cadencia),
  CONSTRAINT followup_joao_cadencia_par_valido CHECK (
       (funil = 'atacado'                  AND cadencia IN ('novo','em_conversa'))
    OR (funil = 'private_label'            AND cadencia IN ('novo','em_conversa'))
    OR (funil = 'reposicao_atacado'        AND cadencia IN ('reposicao','em_atencao'))
    OR (funil = 'reposicao_private_label'  AND cadencia IN ('reposicao','em_atencao'))
    -- 'recuperacao' não tem par válido ainda: zero cadência = zero linha aceita.
  ),
  CONSTRAINT followup_joao_cadencia_gatilho_positivo
    CHECK (gatilho_dias IS NULL OR gatilho_dias >= 1)
);

CREATE TABLE IF NOT EXISTS followup_joao_toque (
  funil          text    NOT NULL,
  cadencia       text    NOT NULL,
  toque          integer NOT NULL,
  dias           integer,
  template_name  text,
  atualizado_por text,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (funil, cadencia, toque),
  CONSTRAINT followup_joao_toque_numero_positivo CHECK (toque >= 1),
  CONSTRAINT followup_joao_toque_dias_positivo CHECK (dias IS NULL OR dias >= 0),
  CONSTRAINT followup_joao_toque_dentro_da_cadencia CHECK (
       (cadencia = 'novo'        AND toque = 1)
    OR (cadencia = 'em_conversa' AND toque BETWEEN 1 AND 7)
    OR (cadencia = 'reposicao'   AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'em_atencao'  AND toque = 1)
  )
);
```

A coluna `linha` desaparece de `followup_joao_toque` (o `funil` já carrega essa
distinção — manter as duas seria duas colunas dizendo a mesma coisa, o padrão que
`docs/…20260918…` já rejeitava para `cadencia`/`gatilho_stage_key`). RLS, triggers de
`updated_at` e o `NOTIFY pgrst, 'reload schema'` continuam iguais, só trocando os nomes
de policy/trigger para refletir a PK nova. Continua **não aplicada pelo deploy** —
mesmo cabeçalho de aviso, mesma disciplina de "roda à mão".

## 5. `backend/app/follow_up/api.py`

`GET /api/cadence/definition` — `joao` troca `cadencias: [...]` por `funis: [...]`:

```json
"joao": {
  "funis": [
    {
      "codigo": "atacado", "rotulo": "João - Atacado",
      "pipeline_id": "9706a14a-...",
      "cadencias": [
        {
          "codigo": "novo", "rotulo": "Novo", "job_type": "joao_novo",
          "gatilho_stage_key": "novo", "gatilho_stage_rotulo": "Novo",
          "gatilho_dias": 2, "gatilho_dias_codigo": 2,
          "ativa": false, "repete_ultimo": false, "pode_ligar": true,
          "toques": [{"sequence":1,"dias":0,"dias_codigo":0,
                      "template_name":"joao_novo_atacado_t1",
                      "template_name_codigo":"joao_novo_atacado_t1",
                      "aceita_adiamento":false}],
          "toques_sem_template": []
        },
        { "codigo": "em_conversa", ... }
      ]
    },
    { "codigo": "recuperacao", "rotulo": "João - Recuperação",
      "pipeline_id": "fa94029b-...", "cadencias": [] }
  ]
}
```

`PUT /api/cadence/joao` — corpo troca `linha?` (opcional) por `funil` (**obrigatório**):

```
{ funil, cadencia, gatilho_dias?, ativa?, atualizado_por?, toques?: {sequence: {dias?, template_name?}} }
```

`funil` ausente ou fora de `cj.FUNIL_CODIGOS` → 404, mesma forma de erro que hoje.
`(funil, cadencia)` que não é um par válido (ex. `funil=atacado, cadencia=reposicao`)
→ 404 nomeando as cadências válidas DAQUELE funil — não a lista inteira de 4 códigos,
que confundiria mais do que ajudaria. Isso substitui o `linha_obrigatoria` de hoje: a
condicional "linha ausente aplica nas duas" desaparece porque não existe mais "as
duas" — cada PUT é sempre um funil só. `Problema.linha` vira `Problema.funil` (mesma
função, campo renomeado).

`_ROTULO_DA_LINHA` desaparece — o rótulo do funil já vem de `Funil.rotulo` no próprio
`cadence_joao.py`, não precisa de segunda tabela de tradução na API.

## 6. `backend/app/follow_up/scheduler.py`

`_LINHA_POR_PIPELINE` (hoje mapeia `PIPELINE_JOAO_ATACADO` e
`PIPELINE_JOAO_REPOSICAO_ATACADO` para a MESMA string `"atacado"` — a mesma colisão
descrita na seção 1) vira `_FUNIL_POR_PIPELINE`, um dicionário 1:1 sem colisão:

```python
_FUNIL_POR_PIPELINE: dict[str, str] = {
    PIPELINE_JOAO_ATACADO: "atacado",
    PIPELINE_JOAO_PRIVATE_LABEL: "private_label",
    PIPELINE_JOAO_REPOSICAO_ATACADO: "reposicao_atacado",
    PIPELINE_JOAO_REPOSICAO_PRIVATE_LABEL: "reposicao_private_label",
}
```

`_normalize_joao_linha`/`_resolve_joao_linha` viram `_normalize_joao_funil`/
`_resolve_joao_funil`, lendo `metadata.funil` em vez de `metadata.linha` (mesma ordem
de fallback: metadata → pipeline_id do metadata → pipeline_id consultado do deal).
`_joao_template_name` lê `metadata.template_por_funil` em vez de
`metadata.template_por_linha`. Logs que hoje imprimem `linha=%s` passam a imprimir
`funil=%s` — grep por `linha=` nos logs deste módulo antes de considerar a task
pronta, para não deixar nenhum rastro do nome antigo.

Nenhuma mudança no despacho por `job_type`, em `_stop_reason_applies`, no guard de
blacklist recém-mesclado (`is_lead_blacklisted`, PR #13) ou em qualquer parte do
caminho `standard` da ValerIA.

## 7. `backend/app/follow_up/service.py`

`carregar_overrides_joao()` muda de forma: hoje devolve
`{codigo: {gatilho_dias, ativa, linhas: {linha: {toques}}}}`; passa a devolver
`{funil: {codigo: {gatilho_dias, ativa, toques}}}` — `gatilho_dias`/`ativa` descem para
o nível `(funil, cadencia)`, espelhando a nova PK de `followup_joao_cadencia`.

`resolver_para_agendar(funil, codigo, overrides_do_par)` — mesma função, assinatura
com `funil` primeiro, override já achatado (sem o aninhamento `linhas.X.toques` que só
existia porque uma cadência tinha duas linhas).

O laço duplo do agendador:
```python
for codigo in CODIGOS:
    for linha in JOAO_LINHAS:
        ...
```
vira um laço único sobre funis, cada um perguntando SUAS PRÓPRIAS cadências:
```python
for funil in cj.FUNIS:
    for cadencia_do_codigo in funil.cadencias:
        ov = overrides.get(funil.codigo, {}).get(cadencia_do_codigo.codigo, {})
        cadencia = resolver_para_agendar(funil.codigo, cadencia_do_codigo.codigo, ov)
        ...
```
Isso já resolve sozinho o caso `recuperacao`: `funil.cadencias` é `()`, o laço interno
não roda nenhuma vez, nada é varrido — sem `if` especial para o funil vazio.

`_montar_jobs_da_matricula` grava `metadata["funil"]` em vez de `metadata["linha"]`.
`motivo_para_pular_joao` **não muda**: já decide por `cadencia.codigo`
(`"reposicao"`/`"em_atencao"`), não por linha/funil — confirmado lendo a função
(`service.py:976-1016`), a partição por fato continua igual.

`JOAO_LINHAS` (hoje `= cj.LINHAS`, reexportado) é removido; quem precisar da lista de
funis usa `cj.FUNIL_CODIGOS`.

## 8. Frontend — `frontend/src/components/campaigns/followup-board.tsx`

Tipos — os dois de hoje (`JoaoLinha`, e o `JoaoCadencia` de topo com campo `linhas:
JoaoLinha[]`) somem, e viram dois tipos novos que espelham o payload da Seção 5:

```ts
type JoaoCadenciaDoFunil = {
  codigo: string; rotulo: string; job_type: string;
  gatilho_stage_key: string; gatilho_stage_rotulo: string;
  gatilho_dias: number; gatilho_dias_codigo: number;
  ativa: boolean; repete_ultimo: boolean; pode_ligar: boolean;
  toques: JoaoTouch[]; toques_sem_template: number[];
};

type JoaoFunil = {
  codigo: string; rotulo: string; pipeline_id: string;
  cadencias: JoaoCadenciaDoFunil[];   // [] para Recuperação
};
```

`JoaoCadenciaDoFunil` reúne o que hoje está espalhado entre o `JoaoCadencia` de topo
(gatilho, `ativa`, `pode_ligar`) e o `JoaoLinha` de dentro (`toques`,
`toques_sem_template`) — não é um puro renome de um ou outro, é a fusão dos dois menos
`pipeline_id` (que sobe para `JoaoFunil`, uma vez por funil, não uma vez por
cadência). `JoaoTouch` não muda. Cadência deixa de ser navegável sozinha — agora está
sempre dentro de um funil.

`JoaoEditor` recebe `funis: JoaoFunil[]` em vez de `cadencias: JoaoCadencia[]`. A pílula
de topo passa a listar os 5 FUNIS (`funil.rotulo` — nome completo, "João - Reposição
Atacado", não mais "Atacado" genérico). Dentro do funil selecionado, uma sub-navegação
(ou lista vertical, já que são no máximo 2) pelas cadências daquele funil; funil com
`cadencias: []` (Recuperação) mostra um estado vazio: "Nenhuma cadência configurada
ainda para este funil."

Estado de rascunho: hoje `rascunhos: Record<string /*codigo*/, Rascunho>`, com
`gatilho_dias`/`ativa` por cadência e `toques` aninhado por linha. Como gatilho/ativa
agora são por `(funil, cadencia)`, a chave do rascunho passa a ser a STRING composta
`` `${funil}:${cadencia}` `` (evita um segundo nível de `Record` só para isso). O bloco
`toques` de um rascunho deixa de ser aninhado por linha — já é de UMA cadência de UM
funil só.

`salvar()`: hoje monta até 2 PUTs por linha + 1 PUT da cadência (comum às duas linhas).
Passa a montar sempre **1 PUT só** por rascunho (`{funil, cadencia, gatilho_dias?,
ativa?, toques?}`) — mais simples que hoje, não mais complexo, porque não existe mais
"aplicar a ambas as linhas".

O gatilho mostra `cadencia.gatilho_stage_rotulo` (ex. "Cliente Ativo · 45 dia(s)") em
vez de `<code>{gatilho_stage_key}</code>`.

`DefinitionStrip`: `definition.joao?.cadencias` vira `definition.joao?.funis`; a
condição `temJoao` passa a ser `funis.length > 0` (verdadeiro mesmo que todas as
`cadencias` de dentro estejam vazias — o seletor Valéria/João continua aparecendo
sempre que o backend manda o bloco `joao`, igual hoje).

## 9. O que NÃO muda

- O motor em si: os números de cada cadência (dias, toques, templates), a partição
  reposição/em-atenção, o teto por passagem, a exigência de template aprovado para
  ligar, o guard de blacklist recém-mesclado — nada disso é tocado.
- `follow_up/cadence.py` (ValeriA) e o topo do payload de `/api/cadence/definition`
  (`touches`, `outbound_nudge`, `min_gap_hours`, `business_window`, `valeria`).
- Tudo continua nascendo **desligado**: as `Cadencia` no código mantêm `ativa=False`; a
  migration editada continua sem nenhum `INSERT`; a leitura de overrides continua
  fail-closed.

## 10. Testes

Espelhar a suíte já existente (`test_cadence_joao_2026_09_18.py`,
`test_scheduler_joao_2026_09_18.py`, `test_agendador_joao_2026_09_18.py`,
`test_api_definicao_joao_2026_09_18.py`), adaptando para a forma nova — não descartar
os casos, RENOMEAR e ajustar assinatura:
- `resolver_cadencia`/`resolver`/`toques_sem_template` com `funil` no lugar de `linha`;
- `FUNIS[4].cadencias == ()` (Recuperação vazia) e `agendar_cadencias_joao` não gera
  nenhum job para ela sem precisar de um `if` dedicado no teste;
- CHECK novo do SQL testado por texto (padrão `test_sql_cards_extraviados_2026_09_16`),
  cruzando os pares `(funil, cadencia)` válidos com o que `cadence_joao.FUNIS` declara;
- regressão do caminho `standard` da ValerIA idêntica antes/depois (é o teste mais
  importante de novo, mesmo motivo do spec de 18/09);
- frontend: `tsc --noEmit` + `vitest run` cobrindo o funil vazio (Recuperação) e o PUT
  único por rascunho.
