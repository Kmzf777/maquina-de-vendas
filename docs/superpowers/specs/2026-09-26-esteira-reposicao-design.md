# A esteira de Reposição, e o teto diário de disparos

**Data:** 2026-09-26
**Branch:** `feat/reposicao-esteira`, a partir de `origin/master` (`17b5586c`)
**Estende:** `2026-09-23-esteiras-joao-v2-design.md` e
`2026-09-25-esteira-vive-na-etapa-design.md`.

## 1. A jornada pedida

| Quando | O que acontece |
|---|---|
| Venda fecha em "João - Atacado" | card nasce em **Cliente Ativo** (`ensure_reposicao_deal`, já funciona) |
| +45 dias parado lá (editável) | toque 1 → e o card **move para "Já chamado"** |
| +15, +30, +45 | toques 2, 3 e 4 |
| fim, sem ter ido para Proposta Enviada | card **move para "Em atenção"** |

Vale igual em Reposição Atacado e Reposição Private Label.

## 2. Quatro coisas que a ideia original quebraria, e o que fazer

### 2.1 Mover para "Já chamado" mataria a esteira no toque 1

A guarda de 25/09 cancela todo toque cujo card saiu da etapa vigiada, e a esteira de
Reposição vigia `novo` ("Cliente Ativo"). Mover no toque 1 cancelaria os toques 2, 3 e 4
— pela guarda que acabou de ser criada para proteger o funil. É a mesma parede que matou
a abordagem do builder em setembro (`_guard_broken`).

**Correção:** separar *onde o card ENTRA* de *onde ele CONTINUA VIVO*.

- `gatilho_stage_key` (já existe) — a etapa de ENTRADA, sempre UMA. É o que a RPC filtra.
- `etapas_vivas` (novo) — o CONJUNTO de etapas em que a esteira segue viva. Default
  vazio, que significa "só a de entrada" — assim as quatro cadências existentes não
  mudam de comportamento.

Reposição: entra por `novo`, vive em `("novo", "chamado_reposicao")`.

Isso resolve o item 2.2 de graça: como a matrícula continua acontecendo só a partir de
Cliente Ativo, card parado em "Já chamado" **não é varrido**.

### 2.2 "Já chamado" já tem 698 cards, com outro significado

Medido em 26/09/2026:

| Funil | Cliente Ativo | Já chamado | Já chamado c/ 45d+ |
|---|---|---|---|
| Reposição Atacado | 170 (0 vencidos) | **698** | **672** |
| Reposição Private Label | 18 (0 vencidos) | 0 | 0 |

Esses 698 foram postos lá por gente/importação, sem ter recebido disparo nenhum — o
motor nunca rodou. Sob o significado novo ("recebeu o 1º toque"), eles estariam mentindo.

**Decisão do dono (26/09):** disparar para eles. Ver §5 (backfill).

### 2.3 Os botões descritos não existem — e os que existem são melhores

Os templates JÁ APROVADOS de Reposição trazem **três** botões:

```
[Preciso repor]  [Ainda tenho estoque]  [Parar mensagens]
```
(o positivo varia por toque: "Preciso repor", "Quero a tabela", "Quero repor agora")

Isto é melhor que os dois propostos ("sim me chame depois" / "não quero pedir"): tem
caminho positivo, adiamento e saída limpa. **Nenhum template novo, nenhuma submissão à
Meta nesta entrega.**

O furo real é outro: **o motor não reconhece o botão positivo.** Ele conhece
`"ainda tenho estoque"` (adia) e as duas frases de saída. "Preciso repor" — o sinal mais
quente que existe — cai no ramo genérico e adia 3 dias, mandando outro "ainda tem
estoque?" depois, possivelmente enquanto o João já negocia. É a mesma classe de botão
morto que já apareceu duas vezes nesta base.

**Correção:** vocabulário declarado novo, `ROTULOS_INTERESSE`, e classificação
`RESPOSTA_INTERESSE` → **encerra a esteira** (decisão do dono: o objetivo foi alcançado,
o João assume). Não notifica ninguém — o lead responde no número do João e ele vê no
/conversas. Precedência: saída → interesse → adiamento → resposta comum.

### 2.4 O teto de hoje não limita volume diário

`JOAO_TETO_PADRAO = 20` é **por passagem**, e o polling roda a cada 30s — até 2.400
matrículas/hora numa esteira. Com os 672 elegíveis, o toque 1 sairia para todos em
minutos. É a forma já medida em 16/09 ("888 cards em 6 minutos").

**Correção:** ver §4.

## 3. As mudanças no motor

### 3.1 `etapas_vivas` (guarda por conjunto)

`Cadencia` e `CadenciaResolvida` ganham `etapas_vivas: tuple[str, ...] = ()`, com uma
propriedade efetiva que cai em `(gatilho_stage_key,)` quando vazia. A guarda de envio e o
`etapa_vigiada` do job de mover passam a testar PERTENCIMENTO AO CONJUNTO em vez de
igualdade.

### 3.2 Toque que move card

`Touch` ganha `move_para: str | None = None`. Ordem obrigatória: **envia, marca `sent`,
depois move**. Se o move falhar, o toque permanece `sent` e não é retentado — a mensagem
já saiu, e reenviar seria pior que o card ficar na etapa antiga. Loga `error`.

Reusa `_mover_card_joao`, com a guarda de conjunto: o card só é movido se estiver numa
etapa viva da cadência.

Reposição: o toque 1 declara `move_para="chamado_reposicao"`.

### 3.3 O botão positivo encerra

`ROTULOS_INTERESSE` (normalizado, igualdade exata — nunca substring):
`{"preciso repor", "quero a tabela", "quero repor agora"}`.

A suíte **cruza esse conjunto com os botões reais dos templates aprovados**, como já faz
com `aceita_adiamento` — um rótulo que não casa é botão morto, e é exatamente o defeito
que esta regra existe para impedir.

Ação: cancela os jobs `pending` da matrícula (toques restantes **e** o job de mover), com
`cancel_reason="lead_demonstrou_interesse"`. Não é blacklist.

### 3.4 `ADIAMENTO_ESTOQUE`: 60 → 30 dias, e editável

Passa a ser sobreposto pelo banco (ver §3.5). O default de código vira 30.

### 3.5 Ajustes globais (tabela nova)

Os dois números que o dono quer editar não são por cadência — são do motor. Tabela nova,
`followup_joao_ajustes`, chave/valor:

| chave | default de código | o que é |
|---|---|---|
| `teto_diario_disparos` | 100 | máximo de templates por dia, somando as 5 esteiras |
| `adiamento_estoque_dias` | 30 | espera do botão "Ainda tenho estoque" |

Leitura **fail-closed para o código** (tabela ausente → defaults), mesma disciplina de
`carregar_overrides_joao`. CHECK nas chaves válidas e em valor ≥ 1. Migration NOVA e
INDEPENDENTE da `20260918` — as duas podem ser aplicadas em qualquer ordem.

## 4. O teto diário de disparos

**Unidade: DISPARO, não matrícula.** Uma matrícula agenda 4 toques ao longo de 45 dias;
limitar matrícula não limita envio, e limitar envio sem limitar matrícula constrói fila
que nunca drena (o toque do dia 15 chega no dia 40, corrompendo a cadência em silêncio).

**Escopo:** as 5 esteiras do João (todos os `JOB_TYPES` do João). **NÃO** inclui o
caminho `standard` da ValerIA — lá é texto livre do LLM dentro da janela de 24h aberta,
dirigido por resposta, e é o único follow-up que roda de verdade em produção (8.140
jobs). Teto diário ali arriscaria quebrar o que funciona sem reduzir o risco que motiva
esta regra. **Nem** os disparos manuais (broadcasts) — decisão do dono.

**Contagem:** jobs do João com `sent_at` dentro do dia corrente em `America/Sao_Paulo`.
UMA consulta por tick, nunca uma por job.

**Ao estourar:**

- no ENVIO: o job é **adiado** — `fire_at` empurrado para o início da janela comercial de
  amanhã. **Nunca cancelado.** Cancelar jogaria o toque no lixo e, pior, o cooldown por
  matrícula leria job cancelado como "o lead respondeu no meio" e liberaria a
  rematrícula: viraria laço. Este é o mesmo raciocínio que levou `_mover_card_joao` a
  marcar `sent` em vez de `cancelled` quando não move.
- na MATRÍCULA: para de matricular quando o saldo do dia acabou. O toque 1 sai
  praticamente na hora, então matricular N cards gasta N do orçamento — o teto se
  autoequilibra sem precisar de uma segunda regra.

O teto por passagem (20) **continua existindo**: ele protege contra "varrer a base inteira
numa consulta", que é um problema diferente.

## 5. O backfill dos 672 (SQL à mão, não aplicado pelo deploy)

Move de "Já chamado" para "Cliente Ativo" **preservando o relógio**. O relógio é
`deals.entered_stage_at`, mantido por `trg_update_deal_entered_stage_at` — um
`BEFORE UPDATE` que faz `NEW.entered_stage_at = now()` sempre que `stage_id` **ou**
`stage` muda. Então uma instrução só **zeraria a data** e os 672 esperariam 45 dias.

Duas instruções, em transação:

1. `UPDATE` de `stage_id` (e da coluna legada `stage`, para não divergirem) → o trigger
   carimba `now()`;
2. `UPDATE` de `entered_stage_at` de volta ao valor capturado → **não** dispara o
   trigger, porque não toca em etapa.

Escopo guardado: só Reposição Atacado, só cards hoje em `chamado_reposicao`, só com
`entered_stage_at` de 45+ dias. `SELECT` de conferência antes e depois. Private Label não
entra (não tem backlog).

Com o teto de 100/dia, os 672 drenam em ~7 dias de matrícula, cada coorte rodando seu
ciclo de 45 dias com o espaçamento correto.

## 6. Um achado de brinde: o move não escrevia a coluna legada

`_mover_card_joao` escreve só `stage_id`. A coluna de texto `deals.stage` fica para trás
— e o trigger observa as duas justamente porque "caminhos legados ainda escrevem o texto"
(comentário de `20260904`). Enquanto mover card era exceção (só o fim da cadência) isso
era latente; agora que o toque 1 move também, passa a acontecer em todo card de
Reposição. Corrigido junto: o move escreve as duas colunas.

## 7. A tela

- O cabeçalho passa a contar a jornada inteira quando ela tem escala:
  *"Entra em Cliente Ativo · o 1º toque move para Já chamado · no fim move para Em
  atenção"*. Nas cadências sem move intermediário, nada muda.
- Dois campos globais novos e editáveis: **teto diário de disparos** e **espera do botão
  "Ainda tenho estoque"**. Ficam fora do bloco por-cadência, porque valem para o motor
  todo.
- Nenhuma chave crua de etapa vaza hoje (conferido: a tela só exibe
  `gatilho_stage_rotulo` e `etapa_final_rotulo`). Se houver outro ponto, é fora do escopo
  desta spec até alguém apontá-lo.

## 8. O que NÃO muda

- Os templates: nenhum novo, nenhuma submissão à Meta. Os aprovados já têm os 3 botões.
- As três esteiras de prospecção (Novo, Em conversa, Proposta Enviada).
- O caminho `standard` da ValerIA, em nenhuma linha.
- `ensure_reposicao_deal` (já resolve por UUID e é fail-closed).
- O teto por passagem, a blacklist, o opt-out, o guard de `followup_enabled`, o cooldown
  por matrícula.
- Tudo continua nascendo desligado.

## 9. Testes

- **`etapas_vivas`:** toque em card que foi para "Já chamado" **sobrevive**; card em
  "Fechado Ganho" ou "Proposta Enviada" **não**; as quatro cadências antigas mantêm o
  comportamento de etapa única (default vazio). **Mutação:** default virar
  "aceita qualquer etapa" → exigir vermelho.
- **Toque que move:** ordem envia→marca→move; falha no move **não** reenvia; o card só
  move se estiver em etapa viva.
- **Botão positivo:** encerra a matrícula inteira (toques restantes E o move); a
  precedência saída > interesse > adiamento > comum; e o cruzamento de
  `ROTULOS_INTERESSE` com os botões reais dos templates aprovados.
- **Teto diário:** estourar ADIA e não cancela (mutação: trocar por cancel → exigir
  vermelho, porque cancelar libera rematrícula); a contagem é por dia de
  `America/Sao_Paulo`; a matrícula respeita o saldo; e os `job_type` da ValerIA **não**
  são contados nem barrados.
- **Backfill:** teste sobre o TEXTO do SQL — duas instruções, escopo guardado, e que a
  segunda não mexe em etapa (é o que preserva o relógio).
- **Regressão da ValerIA:** suíte `standard` idêntica antes e depois.
