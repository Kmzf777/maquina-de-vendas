# A esteira vive enquanto o card estiver na etapa

**Data:** 2026-09-25
**Branch:** `feat/esteira-vive-na-etapa`, a partir de `origin/master` (`bf93b962`)
**Corrige:** os motores entregues em `2026-09-18-motor-followup-joao-design.md`,
`2026-09-21-followup-funil-por-funil-design.md` e `2026-09-23-esteiras-joao-v2-design.md`.

## 1. Três defeitos, uma raiz

Investigação de 24-25/09/2026, com reprodução rodada contra o motor real.

### Defeito A — card muda de etapa e os toques continuam saindo

A matrícula respeita a etapa: a RPC filtra pela etapa ATUAL do card
(`s.key = p_stage_key` e `s.pipeline_id = p_pipeline_id`) e ainda exclui de propósito
`fechado_ganho`, `fechado_perdido`, `perdido`, `encerrado` e `em_atencao`.

Mas a matrícula agenda TODOS os toques de uma vez, e o handler de envio nunca relê a
etapa. As guardas antes do disparo são: conversa finalizada, telefone, template, canal.
Etapa não está na lista.

Reproduzido: com o card em "Fechado Ganho", os toques 2 e 3 de "Novo" saem.

| Esteira | Vendedor move no dia 1 | Ainda disparam |
|---|---|---|
| Novo | dias 2 e 4 | 2 mensagens |
| Em conversa | dias 2, 4 e 9 | 3 mensagens |
| Proposta Enviada | dias 4 e 8 | 2 mensagens |

Até **3 mensagens de marketing ao longo de 9 dias para quem já comprou**. A intenção de
"nunca tocar em card fechado" está escrita na RPC e é derrotada pelo agendamento
antecipado.

### Defeito B — resposta do lead mata a esteira em vez de adiá-la

`cancel_followups_by_phone(reason="client_replied")` cancela TODOS os job types do João.
Medido: a esteira não morre para sempre (a correção de cooldown por matrícula de 23/09
libera a reentrada), mas ela **recomeça do toque 1** depois de ~2 dias, em vez de
continuar de onde parou. O lead relê as mesmas mensagens, e como cada volta reinicia a
contagem, **não há teto**: simulei 5 voltas interrompidas seguidas e a sexta foi
liberada. Um lead que responde a cada 3 dias fica em laço permanente e nunca chega a
"Em Atenção".

Isso contradiz o objetivo declarado pelo dono do funil: em "Em conversa", a esteira
deve tocar o lead **até o card ir para Proposta Enviada** — responder não é motivo para
parar, é motivo para esperar um pouco.

### Defeito C — "ainda tenho estoque" nunca adia os 60 dias

`processar_resposta_joao` (que aplica opt-out e o adiamento de 60 dias) sai logo no
começo quando não há job `pending`:

```python
pendentes = [j for j in jobs if j.get("status") == "pending"]
if not pendentes:
    return None
```

E quem roda ANTES dele é o cancelamento genérico:

- `cancel_followups_by_phone` é *background task* registrada na INGESTÃO do webhook
  (`meta_router.py:618`) — roda milissegundos depois da resposta HTTP;
- `processar_resposta_joao` só é alcançado via `fire_trigger("message_received")`,
  emitido em `buffer/processor.py:1487`, **depois do debounce do buffer**, e ainda por
  cima como `create_task` não aguardado.

Quando o handler chega, os jobs já estão `cancelled` e ele não faz nada. Resultado: o
lead que aperta "ainda tenho estoque" — literalmente pedindo para não ser incomodado —
é recontatado em ~2 dias em vez de 60. É um botão morto, a mesma classe de defeito já
documentada nos templates (rótulo que não casa = botão que não faz nada).

Correção que repousa numa corrida é defeito mesmo quando a corrida é vencida às vezes.

### A raiz comum

Os três são a mesma pergunta: **o que governa a vida da esteira?**

Hoje a **resposta do lead** governa (responde = morre) e a **etapa não governa**
(move = continua). É o inverso do que o funil precisa. A guarda certa existe no
repositório desde sempre — `automation/engine.py::_guard_broken`, *"True se o card saiu
da etapa que originou este enrollment"* — mas mora no motor de CAMPANHAS, que foi o
caminho abandonado no rollback de 21/09. O scheduler de follow-up nunca teve
equivalente porque a cadência da ValerIA é baseada em conversa, não em etapa. Ao trocar
de motor, a guarda não veio junto.

## 2. A regra

> **A esteira vive enquanto o card estiver na etapa vigiada.
> Mudança de etapa ENCERRA. Resposta do lead ADIA.**

Aprovada pelo dono em 25/09/2026. Consequências que ele confirmou:

- Em "Novo", responder **encerra** a esteira — porque `advance_deal_on_reply` move o
  card de "Novo" para "Em conversa" sozinho (roda mesmo com `ai_enabled=False`), e a
  guarda de etapa encerra o que sobrou. A esteira de "Em conversa" assume depois.
- Quem responde muito **esgota os toques** e vai para "Em Atenção", em vez de ficar em
  laço. O teto volta a existir pelo lado certo: a resposta consome tempo, não reinicia
  a contagem.

## 3. As três mudanças

### 3.1 Guarda de etapa na hora do envio (corrige A)

Em `_process_joao_touch`, no caminho do TOQUE (depois do ramo de `mover_etapa`), antes
de resolver template e canal: relê a etapa atual do card e compara com a vigiada.

A etapa vigiada vem de `cadence_joao.cadencia_do_funil(funil, cadencia)` — a config é a
fonte, **não** `metadata.stage_id`. Duas fontes divergiriam no dia em que alguém mudasse
o gatilho pela tela. É o mesmo caminho que `_mover_card_joao` já usa para o seu
`etapa_vigiada`.

| Situação | O que faz |
|---|---|
| card na etapa vigiada | envia |
| card em qualquer outra etapa | `_cancel_job(..., "card_mudou_de_etapa")` |
| deal não existe mais | `_cancel_job(..., "card_mudou_de_etapa")` — sem card não há trabalho (mesma leitura de `_guard_broken`) |
| cadência não resolvida | não envia, `_mark_sent` — fail-closed, igual ao ramo do move |
| `metadata.deal_id` ausente | `_cancel_job(..., "toque_sem_deal_para_verificar")` — o contrato do agendador sempre grava; ausência é BUG, e job que não dá para verificar não manda mensagem |
| erro de banco na leitura | **não envia e não marca nada** — retorna e o job é retentado no próximo tick |

O erro de banco é o caso que merece cuidado: `_guard_broken` é fail-OPEN (na dúvida,
deixa a esteira correr) porque lá o custo de errar é um toque a mais numa campanha. Aqui
o custo é uma mensagem de marketing para quem acabou de comprar — o botão "Bloquear" e a
reputação do número na Meta. Adiar a decisão até conseguir tomá-la é melhor que os dois
extremos, e é o que o ramo do move já faz com erro transitório.

### 3.2 A resposta do lead deixa de cancelar as esteiras do João (corrige C)

`cancel_followups_by_phone` passa a preservar os `job_type` do João **apenas quando
`reason == "client_replied"`**.

Esse recorte é essencial e não pode virar "preserva sempre": a mesma função é chamada
com motivos TERMINAIS — `handoff`, `sem_interesse_atual`, `cliente_ativo_sem_demanda`,
`lead_already_served` e o caminho de blacklist/opt-out em `leads/service.py`. Nesses, os
jobs do João **devem** continuar sendo cancelados. Preservar sempre reabriria, pela
porta dos fundos, o caso de 15/07 que o backstop existe para cobrir (cliente pediu ao
humano para a IA parar e os toques seguiram).

Com isso `processar_resposta_joao` vira a **única autoridade** sobre o que uma resposta
faz com a cadência do João, e a corrida descrita no defeito C deixa de existir — não
porque alguém ganhou, mas porque não há mais dois competidores.

O caminho `standard` da ValerIA **não muda**: lá responder continua cancelando, porque
aquela cadência existe justamente porque o lead sumiu.

### 3.3 Resposta comum adia 3 dias (corrige B)

`processar_resposta_joao` ganha um terceiro ramo. A precedência passa a ser:

| A resposta é… | O que acontece | Situação |
|---|---|---|
| botão de saída | opt-out real + blacklist + cancela | já existe, intocado |
| "ainda tenho estoque" | adia **60 dias**, sem recomeçar | já existe — passa a ser **alcançável** |
| qualquer outra coisa | adia **3 dias**, sem recomeçar | **novo** |

O `return None` antecipado (quando `classificar_resposta` não classifica) sai: agora
"não é opt-out nem adiamento longo" tem ação própria.

As três usam `_adiar_matriculas_joao` → `cadence_joao.adiar_toques`, que já é testada,
já preserva o espaçamento entre os toques restantes e **já arrasta o job de mover
junto** — então um lead que responde não tem o card mandado para "Em Atenção" no meio da
espera.

`ADIAMENTO_RESPOSTA = timedelta(days=3)` nasce como constante de código em
`cadence_joao.py`, irmã de `ADIAMENTO_ESTOQUE = timedelta(days=60)` que já existe. Não
vira campo editável nesta entrega — mesmo tratamento dado a `gatilho_silencio_dias`.

## 4. A tela

Uma linha a mais no cabeçalho da cadência, dizendo o que a resposta do lead faz — senão
o comportamento fica invisível e alguém vai estranhar o toque 3 dias depois de uma
conversa. Algo como: *"se o lead responder, os toques restantes esperam 3 dias"*.

Só exibição; nada editável. Nas cadências de Reposição a frase é a mesma (elas também
passam a adiar em vez de morrer).

## 5. O que NÃO muda

- Os prazos, os toques e os gatilhos de todas as cinco esteiras.
- A trava de ativação (template aprovado em todo toque) e os 22 toques sem template.
- O cooldown por matrícula de 23/09 — continua valendo, e passa a marcar exatamente os
  casos certos: matrícula interrompida agora só acontece por mudança de etapa ou
  opt-out, que são os dois casos em que rematricular faz sentido se o card voltar.
- O caminho `standard` da ValerIA, em nenhuma linha.
- `JOAO_COOLDOWN_DIAS = 90`, o teto por passagem, a blacklist, o guard de
  `followup_enabled`.
- Tudo continua nascendo desligado.

## 6. Testes

- **Guarda de etapa:** card fora da etapa vigiada não envia e cancela com
  `card_mudou_de_etapa`; card na etapa envia normalmente; deal inexistente cancela;
  erro de banco NÃO marca estado terminal (é retentado); a etapa vigiada vem da config,
  não do `metadata`. **Mutação obrigatória:** remover a guarda e exigir que o teste do
  card em "Fechado Ganho" fique vermelho.
- **Recorte do `client_replied`:** com esse motivo, job do João sobrevive e o `standard`
  da ValerIA é cancelado; com `handoff`/`sem_interesse_atual`/opt-out, o job do João É
  cancelado. **Mutação obrigatória:** preservar em todos os motivos e exigir vermelho.
- **Os três ramos da resposta**, com precedência: opt-out cancela; "ainda tenho estoque"
  desliza 60 dias; texto comum desliza 3 dias; e o job de `mover_etapa` desliza junto
  nos dois adiamentos.
- **Regressão da corrida (defeito C):** um teste que prove que `processar_resposta_joao`
  encontra jobs `pending` depois de um `cancel_followups_by_phone(reason="client_replied")`
  — hoje ele encontraria zero.
- **Continuidade:** lead responde no toque 2 → os toques 3 e 4 continuam existindo
  (não viram matrícula nova) e vencem 3 dias depois do que venceriam.
- **Regressão da ValerIA:** suíte `standard` idêntica antes e depois.
