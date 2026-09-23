# As esteiras do João, versão 2 — três cadências por funil, com saída para "Em Atenção"

**Data:** 2026-09-23
**Branch:** `feat/esteiras-joao-v2`, a partir de `origin/master` (`b675bcaf`)
**Depende de:** `2026-09-18-motor-followup-joao-design.md` (o motor) e
`2026-09-21-followup-funil-por-funil-design.md` (a estrutura funil-primeiro). Este spec
**reformula as cadências** de João - Atacado e João - Private Label; não reescreve o motor.

## 1. O que muda

Hoje, em Atacado e Private Label, existem duas cadências: `novo` (1 toque) e
`em_conversa` (7 toques ao longo de ~30 dias). O dono do funil pediu três, mais curtas,
e com uma saída explícita quando o lead nunca responde.

| Cadência | Vigia | Gatilho | Toques (dias desde a matrícula) | Fim |
|---|---|---|---|---|
| `novo` | etapa `novo` ("Novo") | 2 dias de silêncio | T1=0, T2=2, T3=4 | dia 5 → move para "Em Atenção" |
| `em_conversa` | etapa `respondeu` ("Em conversa") | 2 dias de silêncio | T1=0, T2=2, T3=4, T4=9 | dia 10 → move para "Em Atenção" |
| `proposta` **(nova)** | etapa `proposta_enviada` ("Proposta Enviada") | 1 dia na etapa | T1=0, T2=1, T3=4, T4=8 | dia 9 → move para "Em Atenção" |

Idêntico nos dois funis. **Reposição Atacado e Reposição Private Label não são tocados** —
as cadências `reposicao` e `em_atencao` seguem exatamente como estão em produção.

## 2. Todos os toques nascem SEM template

Decisão explícita do dono (2026-09-23): nenhum toque das três cadências referencia
template. `template_name=None` em todos os 22 toques (3+4+4, vezes dois funis).

Consequência, e ela é o ponto: **nenhuma das três cadências pode ser ligada** enquanto
ninguém preencher os textos. É a mesma trava que já existe (`toques_sem_template` →
`pode_ligar=False` → a API recusa `ativa:true` nomeando cada toque vazio), e é a mesma
declaração que a cadência `em_atencao` já faz hoje. Quem preenche é a tela, sem deploy.

Os 16 templates hoje referenciados (`joao_novo_*_t1` e os 14 `joao_conversa_*`) ficam
**desconectados**: continuam aprovados na Meta, apenas nenhum código aponta para eles.
Isso é deliberado — a forma da cadência mudou (7 toques viraram 4) e escolher quais 4
dos 7 sobreviveriam seria uma decisão de texto tomada por quem não escreve o texto.

## 3. Mecanismo novo: a cadência move o card no fim

O motor nunca moveu card, e isso está escrito como decisão no spec de 18/09. Esta é a
primeira exceção, e ela é estreita.

`Cadencia` ganha três campos:

```python
etapa_final_key: str | None = None       # "em_atencao"
etapa_final_rotulo: str | None = None    # "Em atenção" — para a tela, hardcoded
dias_ate_mover: int = 1                  # 24h depois do último toque
```

Na matrícula, `_montar_jobs_da_matricula` cria os jobs dos toques **e mais um job**,
sem template, com `metadata["acao"] = "mover_etapa"`, agendado para
`último_toque.offset + dias_ate_mover`. O handler (`_process_joao_touch`) vê a marca e
move o card em vez de enviar mensagem.

**Por que um job e não uma varredura à parte:** porque a resposta do lead já cancela
todos os jobs `pending` da matrícula (`cancel_followups_by_phone`, motivo
`client_replied`, disparado em `webhook/meta_router.py`). Sendo um job, o "mover" é
cancelado junto — lead que responde não recebe mais nada **e** não tem o card movido,
sem uma única regra nova. Uma varredura separada precisaria reimplementar essa
condição, e divergiria dela no primeiro ajuste.

**O move é defensivo**, no mesmo padrão de `quotes/router.py::_move_deal_to_proposal`:
só move se o card ainda estiver na etapa vigiada. Se o João já moveu à mão, não desfaz.
Se a etapa de destino não existe no funil, registra e não faz nada.

**O job de mover NÃO conta para a trava de ativação.** `toques_sem_template` olha
`touches`, e o move não é um `Touch` — é uma propriedade da cadência. Se contasse, a
cadência jamais poderia ser ligada nem com todos os textos preenchidos.

O job de mover passa pelo mesmo `_clamp_to_business_window` dos toques. Um move
empurrado das 2h para as 8h é invisível para o lead, e a alternativa seria um ramo a
mais no laço que monta os jobs.

## 4. O trinco de 90 dias — reentrada por matrícula

Hoje `motivo_para_pular_joao` bloqueia a reentrada assim:

```python
corte = now - timedelta(days=JOAO_COOLDOWN_DIAS)   # 90
for job in jobs_do_card:
    if job["job_type"] != cadencia.job_type: continue
    if job["status"] == "cancelled": continue      # já ignora os cancelados
    if nascimento(job) > corte: return "cooldown"
```

A regra já ignora job `cancelled` — a intenção sempre foi "cadência que morreu não
segura reentrada". Mas quando o lead responde no meio, os toques que **já saíram**
ficam `sent`, e são eles que disparam o cooldown. Resultado: um lead que responde no T2
e volta a sumir fica 90 dias sem esteira nenhuma — o oposto de "se responder, reinicia".

**A correção:** a contagem passa a ser **por matrícula**, agrupando por
`metadata.matricula_id` (que já é gravado hoje):

- matrícula com **algum** job `cancelled` = **interrompida** → não conta para cooldown;
- matrícula com todos os jobs `sent`/`failed` = **rodou até o fim** → conta.

É exatamente a distinção entre "a esteira terminou o trabalho dela" e "o lead
respondeu no meio". Job sem `matricula_id` (nenhum em produção, mas o campo é lido de
`metadata`) é tratado como matrícula própria, conservadoramente: conta para o cooldown.

**Onde o cooldown NÃO vive:** a RPC `get_deals_stage_stagnant` também tem um cooldown,
mas ele é correlacionado a `campaign_enrollments` por `p_campaign_id`. O João chama a
RPC sem esse argumento, então aquele filtro não se aplica — verificado no corpo da RPC
(`20260904_esteiras_vendedor.sql`). A regra Python é a única. Não mexer na RPC.

### O que já funciona e não precisa de código

- **Lead responde → a esteira para.** `cancel_followups_by_phone(reason="client_replied")`
  já cancela todos os jobs `pending` do João.
- **Lead responde em "Novo" → o card já anda sozinho para "Em conversa".**
  `advance_deal_on_reply` roda mesmo com `ai_enabled=False` (está escrito assim no
  `buffer/processor.py`) e os funis do João têm a etapa `respondeu`. Ou seja: "reinicia
  a esteira" no Novo é, na prática, "Novo para e Em Conversa assume 2 dias depois" —
  que é o comportamento pedido, emendando as duas esteiras em vez de repetir a primeira.
- **O card já vai para "Proposta Enviada" sozinho** quando a proposta é criada no
  `/orcamento` (`quotes/router.py:540`).
- **"caso o lead não tenha ido para fechado ganho"** não precisa de regra: a cadência
  vigia a etapa `proposta_enviada`, e um card que fechou não está mais nela.

## 5. Gatilho por silêncio (Novo e Em Conversa) e por etapa (Proposta)

O dono escreveu "2 dias **sem conversar**" para Novo e Em Conversa, e "24h depois" para
Proposta. São relógios diferentes, e a RPC suporta os dois por parâmetros separados
(`p_stage_days` e `p_silence_days`, que combinam por AND; 0 desliga o respectivo filtro).

Hoje o código passa `p_silence_days=0` com a justificativa de que "o relógio da ata é o
da ETAPA". Isso muda:

| Cadência | `p_stage_days` | `p_silence_days` |
|---|---|---|
| `novo` | 2 | 2 |
| `em_conversa` | 2 | 2 |
| `proposta` | 1 | 0 (desligado) |

`Cadencia` ganha `gatilho_silencio_dias: int = 0`. As cadências de Reposição continuam
com 0 — o relógio delas é mesmo o da etapa ("45 dias em Cliente Ativo").

`p_last_speaker` continua `"qualquer"` em todas: um lead calado há 2 dias merece
follow-up tanto se a última palavra foi dele quanto se foi nossa.

**Nota sobre a tela:** o prazo editável (`gatilho_dias`, já na tabela de sobreposição) é
o de ETAPA. O de silêncio fica só no código nesta entrega — abrir um segundo campo
editável é escopo novo, e o número de silêncio é o mesmo 2 em ambas as cadências que o
usam. A tela mostra os dois números, edita um.

## 6. Mudanças arquivo a arquivo

### `backend/app/follow_up/cadence_joao.py`
- `Cadencia` ganha `gatilho_silencio_dias`, `etapa_final_key`, `etapa_final_rotulo`,
  `dias_ate_mover`.
- `_NOVO_*` passa de 1 para 3 toques (0, 2, 4), todos `template_name=None`.
- `_EM_CONVERSA_*` passa de 7 para 4 toques (0, 2, 4, 9), todos `None`.
- `_PROPOSTA_ATACADO` / `_PROPOSTA_PRIVATE_LABEL`: novos, 4 toques (0, 1, 4, 8), todos
  `None`, vigiando `proposta_enviada` / "Proposta Enviada".
- As três declaram `etapa_final_key="em_atencao"`, `etapa_final_rotulo="Em atenção"`,
  `dias_ate_mover=1`.
- `FUNIS`: Atacado e Private Label passam a ter 3 cadências; os dois de Reposição ficam
  como estão; Recuperação segue vazio.
- `CadenciaResolvida` carrega os campos novos (o agendador precisa deles).
- `JOB_TYPES` ganha `joao_proposta` automaticamente (é derivado de `FUNIS`).

### `backend/app/follow_up/service.py`
- `_varrer_cadencia_joao`: `p_silence_days` passa a vir de
  `cadencia.gatilho_silencio_dias` em vez de ser fixo em 0.
- `_montar_jobs_da_matricula`: cria o job de `mover_etapa` quando
  `etapa_final_key` está declarada e a cadência não é `repete_ultimo`.
- `motivo_para_pular_joao`: cooldown por matrícula (§4).
- `JOAO_COOLDOWN_DIAS` continua 90 — só muda **o que** conta, não por quanto tempo.

### `backend/app/follow_up/scheduler.py`
- `JOAO_JOB_TYPES` (frozenset hardcoded) ganha `joao_proposta`.
- `_process_joao_touch`: ramo novo no topo — `metadata.acao == "mover_etapa"` move o
  card e retorna, sem tocar em template, canal ou envio.
- Função nova `_mover_card_joao(deal_id, etapa_key)`, defensiva, no padrão de
  `_move_deal_to_proposal`.
- `_stop_reason_applies`: **nada a fazer, mas confirmar com teste.** A isenção de
  `ai_disabled` para o João é por PREFIXO (`job_type.startswith("joao_")`), não pela
  tabela `_STOP_REASON_EXEMPT_JOB_TYPES` — verificado no código. `joao_proposta` já
  nasce isento. O teste existe porque o custo de estar errado já foi medido: o
  `handoff_rescue` criou 144 jobs entre 22 e 27/07 e cancelou os 144 com `ai_disabled`,
  zero enviados. O lead do vendedor tem `ai_enabled=False` por definição.

### `backend/app/follow_up/api.py`
- O payload de cada cadência ganha `gatilho_silencio_dias`, `etapa_final_rotulo` e
  `dias_ate_mover` (só leitura — a tela mostra, não edita).
- Nada mais muda: `proposta` entra sozinha por ser mais uma cadência dentro do funil.

### `supabase/migrations/20260918_followup_joao_config.sql`
Editada **no lugar** de novo — segue **não aplicada** em produção, então não há dado a
migrar (confirmar com `SELECT` antes de editar; se houver linha, parar e reportar).

- `followup_joao_cadencia_par_valido`: Atacado e Private Label passam a aceitar
  `proposta` além de `novo` e `em_conversa`.
- `followup_joao_toque_dentro_da_cadencia`: `novo` passa a aceitar toque 1-3,
  `em_conversa` 1-4, e `proposta` 1-4 entra na lista. `reposicao` (1-4) e `em_atencao`
  (1) não mudam.

### `frontend/src/components/campaigns/followup-board.tsx`
- Os tipos ganham os três campos novos.
- O cabeçalho da cadência passa a dizer o relógio completo e o destino, em português
  chão: *"Dispara com 2 dia(s) sem conversa na etapa Novo · depois do último toque,
  espera 1 dia e move o card para Em atenção"*.
- Nenhuma mudança de navegação: Proposta Enviada aparece sozinha como terceira cadência
  do funil, porque a tela já renderiza `funil.cadencias` inteiro.

## 7. O que NÃO muda

- Os funis de Reposição e suas duas cadências.
- O funil Recuperação (segue vazio).
- O caminho `standard` da ValerIA — nenhuma linha.
- O teto por passagem, a blacklist, o opt-out, o adiamento de 60 dias, a partição
  `reposicao`/`em_atencao`.
- `JOAO_COOLDOWN_DIAS = 90`.
- Tudo continua nascendo **desligado** (`ativa=False` no código; migration sem `INSERT`).

## 8. Testes

- **Prazos**: uma tabela de teste com as três cadências × dois funis conferindo
  `offset.days` de cada toque e o `fire_at` do job de mover. É o teste que protege os
  números da reunião.
- **Todos os toques sem template**: `toques_sem_template` devolve todas as sequences, e
  `pode_ligar` é `False` nas três cadências dos dois funis.
- **O move é cancelado junto**: simular resposta do lead e provar que o job
  `mover_etapa` fica `cancelled` e o card não anda.
- **O move é defensivo**: card já fora da etapa vigiada → não move; etapa de destino
  inexistente no funil → não move, não levanta.
- **Cooldown por matrícula** (o teste mais importante do lote): matrícula interrompida
  (com job `cancelled`) **não** bloqueia reentrada; matrícula completa (todos `sent`)
  bloqueia. Mutação: voltar a contar job `sent` de matrícula interrompida e exigir
  vermelho.
- **`p_silence_days` chega na RPC** com 2 em `novo`/`em_conversa` e 0 em `proposta` e
  nas de Reposição.
- **`joao_proposta` isento de `ai_disabled`** e presente em `JOAO_JOB_TYPES`.
- **Regressão da ValerIA**: suíte `standard` idêntica antes/depois.
- **Texto do SQL**: os CHECKs novos cruzados contra o que `cadence_joao.FUNIS` declara
  de verdade — o mesmo teste que impede código e banco de divergirem.
- Frontend: `tsc` + `vitest`, cobrindo a terceira cadência e o texto do cabeçalho.
