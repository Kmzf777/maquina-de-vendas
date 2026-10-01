# Três defeitos achados no primeiro dia do fluxo de botões em produção

**Data:** 2026-10-01
**Branch:** `fix/botoes-pos-producao` (de `origin/master`)
**Origem:** avaliação das 10 primeiras conversas reais do fluxo (`valeria_botoes_v1`), ativado
no canal `553492009777` em 01/10 02:47. Leads reais, de anúncios Meta (`12025242`/`12025246`).

Não são hipóteses: cada um foi lido nas mensagens gravadas em produção.

---

## 1. Lead transbordado que volta recebe SILÊNCIO — regressão da ativação

### O que aconteceu

Duas das 10 conversas nunca receberam a tela de entrada. São leads que o João assumiu em
**31/07** e **28/08**. Quando escreveram de novo em 01/10, o fluxo recusou o turno
(`human_control=True`) e **não respondeu nada**.

O caso que dói: **`5511950821962` escreveu "O kilo sai 25 reais" às 12:47 e recebeu
silêncio.** No histórico dele, antes da ativação, a mesma situação era respondida:
*"recebi sua mensagem! seu atendimento já tá com o João e ele te responde…"*.

### Causa

`processor.py:1788` chama `_maybe_send_handoff_bridge` dentro do ramo
`if not lead.get("ai_enabled", True)` — que está **abaixo** do `return` incondicional do gate
de fluxos (`:1754`). Antes da ativação o gate não reivindicava a conversa e o inbound caía no
ramo do `ai_enabled`, onde o bridge disparava. Depois da ativação o gate reivindica,
`_motivo_para_nao_rodar` recusa em `human_control`, `_notificar_sem_rodar` grava a nota, e o
`return` fecha o caminho antes do bridge.

Isto foi **previsto e registrado**: a classe `TestOQueOCarimboAindaNaoAlcanca` fixa
exatamente este estado, e o relatório da época dizia que "com o fluxo ATIVO o bridge nem é
chamado". Eu classifiquei como "vale saber, não observável ainda". Tornou-se observável.

### A solução, e por que não é um fall-through

O `return` incondicional do gate é **o que faz "zero IA" ser um fato** — o comentário dele
registra isso. Deixar o inbound seguir quando o fluxo recusa reabriria o caminho até
`run_agent` para qualquer lead com `ai_enabled=True`, que é precisamente o que o fluxo
existe para impedir.

Então: **o gate chama o bridge e continua retornando.** Para isso ele precisa saber *por que*
o fluxo não rodou, e só um dos motivos justifica o bridge:

| Motivo de `_motivo_para_nao_rodar` | Bridge? |
|---|---|
| `human_control=true` (handoff formal registrado) | **Sim** — o lead está esperando resposta de alguém |
| lead na blacklist | **Não** — pediu para sair; mandar qualquer coisa é o oposto |
| etapa de deal incompatível | **Não** — não há promessa pendente ao lead |

`processar_inbound` passa a devolver o motivo (ou `None` quando atendeu o turno). O call site
é único e compartilhado com o runner da Recuperação, então o da Recuperação devolve `None`
("atendi") e nada muda para ele — e no número do João o bridge nunca rodaria mesmo, porque o
gate de `mode='human'` está acima dele.

**A nota `_notificar_sem_rodar` continua sendo gravada.** Ela diz ao operador que o bot saiu
de cena; o bridge diz ao lead que alguém o atenderá. São dois públicos.

---

## 2. A nota do handoff mente no CRM

### O que aconteceu

Toda entrega ao vendedor grava, em produção:

> 🙋 [ATENDIMENTO HUMANO] Lead insistiu em texto livre no bot de botões da ValerIA; IA desligada, conversa entregue ao vendedor.

Inclusive na conversa `dd221643`, que tem **`nudges=0`** — o lead clicou em todos os botões,
sem digitar uma vez. O João lê um motivo falso sobre um lead que se comportou perfeitamente.

### Causa

`effects._silenciar_ia` (`effects.py:376`) tem o texto fixo. Ele foi escrito para o caminho
do `T_HUMANO` (bloqueio após 3 nudges), onde é verdade — e é reusado pelo handoff, porque
`T_HANDOFF*` também declara `silenciar_ia=True`.

Resultado: **três notas numa só entrega**, uma delas falsa.

### A solução

`_silenciar_ia` **não grava nota quando o efeito também é handoff**. O `_aplicar_handoff` já
escreve duas, melhores e verdadeiras (`[encaminhar_humano]` e `[TRANSBORDO p/ …]`). Não há
informação perdida — há uma mentira removida.

O desligamento da IA continua acontecendo nos dois caminhos; muda só a anotação.

---

## 3. O nudge reenvia a FOTO como mensagem faturada

### O que aconteceu

Conversa `3c236b3c`: o lead recebeu a tela de fechamento (foto + preço + botões), escreveu
**"Valores"**, e a resposta foi **a imagem de novo**, com o texto do nudge na legenda.

### Causa

O nudge devolve `proximo_no = no_atual` e o runner (`valeria_runner.py:296`) decide o tipo de
envio por `no.tela`. Em `N5`/`N5b`/`P4`/`P4b` a tela é `foto_botoes`, então o runner
republica a foto no bucket e manda imagem — para um reoferecimento de botões.

Custo: mensagem de imagem faturada onde bastava texto, e a foto repetida na tela do lead.

### A solução

O runner passa a olhar `decisao.marcar_nudge` (campo que já existe) e, no nudge, envia
**texto + botões sem header de imagem**. O nó não muda; muda a forma de reenviar.

### E o corpo do nudge está errado em contexto

`CORPO_NUDGE` é *"pra eu te passar o valor certo, é só tocar numa das opções 👇"*. Em
produção ele respondeu a um **áudio de número errado** (*"Oi, minha filha, como você está?"*)
e a um **vídeo** — onde a frase não faz sentido nenhum, porque pressupõe que o lead perguntou
preço.

Novo default, neutro: **"pra seguir, é só tocar numa das opções abaixo 👇"**. Continua
editável na tela pela chave `__nudge__`, então é reversível sem deploy.

---

## 4. Mudanças, arquivo por arquivo

| Arquivo | Item | Risco |
|---|---|---|
| `backend/app/button_flow/valeria_runner.py` | 1 (devolver motivo) + 3 (nudge sem foto) | **alto** — caminho de todo inbound do fluxo |
| `backend/app/buffer/processor.py` | 1 (chamar o bridge no motivo certo) | **alto** — caminho de todo inbound |
| `backend/app/button_flow/effects.py` | 2 | médio — compartilhado com a Recuperação, em produção |
| `backend/app/button_flow/valeria_registry.py` | 3 (corpo do nudge) | baixo |

Mitigação: o `return` incondicional **permanece**; o bridge é chamado por um ramo novo e
explícito, restrito a um motivo. Nenhum caminho novo alcança `run_agent`.

## 5. Testes

**Item 1:**
- `processar_inbound` devolve `"human_control"` quando recusa por handoff formal, e `None`
  quando atende o turno.
- Blacklist e etapa incompatível devolvem o motivo delas e **não** acionam o bridge.
- O gate chama `_maybe_send_handoff_bridge` exatamente uma vez no motivo `human_control`, e
  **retorna** (nunca alcança `run_agent`).
- O runner da Recuperação devolve `None` — comportamento byte-idêntico.
- Reprodução do caso real: lead com `human_control=True` escrevendo "O kilo sai 25 reais"
  recebe o bridge, não silêncio.

**Item 2:**
- Handoff grava as duas notas verdadeiras e **nenhuma** nota de "insistiu em texto livre".
- `T_HUMANO` (3 nudges) **continua** gravando a nota — ali é verdade.
- `ai_enabled=False` é escrito nos dois caminhos.
- Recuperação: regressão completa da forma do que ela escreve.

**Item 3:**
- Nudge num nó `foto_botoes` envia **uma** mensagem, **sem** `image_url`.
- A entrada normal no mesmo nó continua enviando **com** `image_url`.
- Nudge num nó de botões comum continua igual.
- A foto não é republicada no bucket durante um nudge.
- `CORPO_NUDGE` default não contém "valor".
