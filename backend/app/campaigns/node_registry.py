"""Registro dos tipos de no do builder de cadencias (/campanhas) — o CONTRATO unico
entre a tela e o motor (`app/automation/engine.py` + `app/automation/triggers.py`).

POR QUE ISTO EXISTE
───────────────────
O builder foi construido e NUNCA foi usado: 16 campanhas, 0 ativas, 0 matriculas na
historia. Toda falha medida em 16/09/2026 tem a mesma raiz — o inspector grava uma
chave de config e o motor le OUTRA COISA no mesmo nome:

1. `stage_filter` servia a DOIS vocabularios diferentes com um unico <select>, e errado
   para os dois. O inspector oferece as colunas de Kanban e grava o ROTULO
   (`value={s.label}` — "Em conversa"). Mas o motor compara `stage_filter` com:
      • `leads.stage`         — o SEGMENTO do lead, em `no_message`, `stage_stagnation`,
                                `no_sale_in_stage` e `stage_enter`;
      • `pipeline_stages.key` — a KEY da coluna, em `deal_stage_enter`.
   Rotulo nunca e igual a nenhum dos dois. Resultado: 5 dos 12 gatilhos NUNCA casavam.
   E o segmento do lead nem sequer e o vocabulario que a tela mostrava: `leads.stage`
   guarda `pending`/`secretaria`/`atacado`/`private_label`/`exportacao`/`consumo`
   (ver `AGENT_STAGES` no frontend e `apply_stage_transition` em agent/tools.py) —
   nada a ver com as colunas de funil que o <select> listava.
2. `stage_stagnation` e `no_sale_in_stage` fazem `if not stage: continue` — sem o
   filtro o gatilho inteiro e PULADO, sem log de erro. E o default do builder
   (`getDefaultConfig`) nao escreve `stage_filter`: campanha ativa, verde na tela, e
   muda. Por isso os dois campos nascem `obrigatorio=True` aqui.
3. A acao `create_deal` chama `create_deal(lead_id, title, cfg.get("category"))` sem
   `pipeline_id` — cai no fallback "primeiro pipeline" e cria o card no funil errado.
   O campo e declarado OBRIGATORIO para que a tela pare de deixar a escolha implicita.
4. `replied_only` do `post_broadcast` existe no inspector, e mandado como `False` fixo
   por `broadcast/worker.py` e nao e lido por NINGUEM. Nao esta declarado aqui: campo
   que nao existe no contrato some da tela.

A partir daqui a tela, os defaults e a validacao de ativacao DERIVAM deste modulo.
`tests/test_node_registry.py` cruza o registro com o codigo do motor por regex: todo
`cfg.get("...")` novo em engine.py/triggers.py quebra a suite ate ser declarado. Esse
teste e a unica coisa que impede a divergencia de voltar.

DUAS REGRAS QUE VALEM PARA TODO O ARQUIVO
─────────────────────────────────────────
• `obrigatorio=True` significa "sem isto a campanha nao pode ser ATIVADA" — NUNCA
  "sem isto nao salva". Montar rascunho incompleto e legitimo e e como o builder e
  usado de verdade (as 6 esteiras do Joao nascem `draft` e sem template de proposito,
  ver `esteiras_joao.ESTEIRAS_ARMADAS`).
• `default` e O QUE O MOTOR ASSUME QUANDO A CHAVE ESTA AUSENTE, nao o que a tela
  gosta de mostrar. Onde os dois divergem hoje ha um comentario dizendo qual e qual.
  `default=None` significa "ausente tem sentido proprio" — e o caso do `on_reply` dos
  nos de envio e da janela de envio do `wait`, onde gravar um valor explicito
  SEQUESTRA a configuracao da esteira/campanha (ver os comentarios no lugar).

Sem I/O e sem importar o motor: este modulo e lido por engine/triggers/tela/validacao,
e qualquer import de volta fecharia ciclo. Ele e dado puro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─── Vocabularios ────────────────────────────────────────────────────────────────
#
# O `vocab` de um campo diz DE ONDE vem o valor e contra o que ele vai ser comparado.
# E o remedio do bug 1: `stage_filter` do `stage_enter` e `stage_filter` do
# `deal_stage_enter` tem o mesmo NOME e vocabularios incompativeis, e so declarando
# isso da para a tela oferecer a lista certa em cada um.
#
# Os tres que mais importam:
#   segmento_lead — `leads.stage`. Valores em VALORES_FIXOS["segmento_lead"].
#   etapa_key     — `pipeline_stages.key` ('novo', 'respondeu', 'fechado_ganho'...).
#                   NUNCA o rotulo da coluna; o rotulo e editavel pelo dono do funil.
#   etapa_id      — `pipeline_stages.id` (uuid). O motor le `stage_id` SEM fallback
#                   por key nas acoes de deal (engine `_execute_action`), entao id e
#                   id: mandar key ali nao move card nenhum.
VOCABULARIOS = {
    "texto", "texto_longo", "numero", "booleano",
    "segmento_lead", "etapa_key", "etapa_id", "funil_id", "canal_id",
    "template", "tag", "usuario_id", "lista_usuario_id", "lista_texto",
    "operador", "politica_resposta", "severidade",
    # Dois vocabularios ALEM da lista original do plano, ambos pela mesma razao: sem
    # eles a tela renderizaria o controle errado e reintroduziria o bug que este
    # modulo existe para matar.
    #   mapa    — `template_variables` e um DICIONARIO
    #             ({"__params_type__": "positional", "1": "{{primeiro_nome}}"}), lido
    #             por `broadcast/worker._build_template_components`. Tipar como
    #             "texto_longo" faria a tela gravar string onde o worker espera dict.
    #   falante — `last_speaker` so aceita 'qualquer' | 'lead' | 'nos' (o CASE de
    #             `falante` em 20260904_esteiras_vendedor.sql). Como texto livre, um
    #             "vendedor" digitado a mao faz a RPC devolver conjunto vazio para
    #             sempre, em silencio.
    "mapa", "falante",
}

# Valores aceitos dos vocabularios FECHADOS — os que nao vem do banco. A tela monta o
# <select> daqui; a validacao de ativacao recusa valor fora da lista. Formato:
# (valor_gravado, rotulo_humano).
VALORES_FIXOS: dict[str, tuple[tuple[str, str], ...]] = {
    # `leads.stage`. 'pending' e 'secretaria' sao estados de TRIAGEM (o lead ainda nao
    # foi classificado) e por isso nao costumam ser alvo de acao — mas existem no
    # banco e um gatilho pode legitimamente filtrar por eles, entao estao aqui.
    # 'perdido' e escrito por `registrar_sem_interesse_atual` (agent/tools.py).
    "segmento_lead": (
        ("secretaria", "Secretaria (triagem)"),
        ("atacado", "Atacado"),
        ("private_label", "Private Label"),
        ("exportacao", "Exportacao"),
        ("consumo", "Consumo"),
        ("pending", "Pendente (importado, sem triagem)"),
        ("perdido", "Perdido"),
    ),
    # engine `_compare`. Qualquer outro operador devolve False em TODA comparacao —
    # a condicao vira um "nao" permanente sem erro nenhum.
    "operador": (
        ("gte", ">= (maior ou igual)"),
        ("lte", "<= (menor ou igual)"),
        ("gt", "> (maior)"),
        ("lt", "< (menor)"),
        ("eq", "= (igual)"),
    ),
    # worker `_apply_reply_policy`. 'reset' rebobina a matricula para o primeiro no
    # (esteira "Em conversa", reuniao de 10/09/2026); 'cancel' vindo do NO so vale em
    # no `send`; ausencia/valor desconhecido => pausa.
    #
    # 'optout' (16/09/2026, §11) e o unico que sai da matricula e toca o LEAD: grava
    # `leads.opt_out`, move os cards para o funil Blacklist e cancela os follow-ups
    # pendentes — os MESMOS campos de `agent/tools.py::registrar_optout`, pelo mesmo
    # corpo (`worker._gravar_optout`) — e so entao cancela a matricula. Existe porque
    # `is_optout_reply` so reconhece DUAS frases exatas ("parar mensagens", "nao tenho
    # interesse"): um botao rotulado "Parar atendimento" era decorativo, cancelava um
    # enrollment e nada mais, e a reinscricao das esteiras trazia o lead de volta dias
    # depois. Com este valor, o rotulo que conta passa a ser DECLARADO no no.
    "politica_resposta": (
        ("pause", "Pausar a esteira"),
        ("cancel", "Cancelar a esteira"),
        ("reset", "Voltar ao primeiro toque"),
        ("optout", "Descadastrar (opt-out + Blacklist)"),
    ),
    # alerts/service.create_system_alert
    "severidade": (
        ("info", "Informativo"),
        ("warning", "Atencao"),
        ("critical", "Critico"),
    ),
    # RPC get_deals_stage_stagnant, parametro p_last_speaker.
    "falante": (
        ("qualquer", "Tanto faz"),
        ("lead", "O lead falou por ultimo"),
        ("nos", "Nos falamos por ultimo"),
    ),
}


@dataclass(frozen=True)
class Campo:
    """Um campo do `config` de um no. `chave` e literalmente o que o motor faz
    `cfg.get(...)` — o teste de contrato compara os dois conjuntos."""
    chave: str
    vocab: str
    rotulo: str
    obrigatorio: bool = False     # obrigatorio para ATIVAR, nunca para salvar rascunho
    default: Any = None
    ajuda: str = ""


@dataclass(frozen=True)
class TipoDeNo:
    tipo: str                      # trigger|send|send_text|wait|condition|action|end
    subtipo: str | None
    rotulo: str
    icone: str
    campos: tuple[Campo, ...]
    # Grupos "pelo menos um destes". Existe porque ha campo que nao e obrigatorio
    # sozinho mas cuja ausencia CONJUNTA quebra o no — ver `deal_stage_stagnation`.
    requer_um_de: tuple[tuple[str, ...], ...] = ()
    # False = o tipo continua valido e renderizavel (campanha antiga que ja o usa nao
    # pode virar lixo na tela), mas some da paleta de tipos novos. Nenhum tipo esta
    # aposentado hoje; o flag existe para que aposentar um seja uma linha, e nao uma
    # caca a `if` espalhado pelo frontend.
    na_paleta: bool = True


# ─── Gatilhos ────────────────────────────────────────────────────────────────────
#
# COMO CADA GATILHO E DISPARADO (verificado em 16/09/2026). Sao TRES caminhos, e
# procurar so por `fire_trigger(` no Python enxerga apenas um deles:
#
#   a) POLLING — `automation/triggers.py::check_polling_triggers`, a cada 30s:
#      no_message, stage_stagnation, no_sale_in_stage, repurchase_window,
#      deal_stage_stagnation, keyword_received.
#   b) EVENTO INTERNO — `fire_trigger(...)` chamado direto no backend:
#      message_received (buffer/processor.py) -> roteia para keyword_received;
#      post_broadcast (broadcast/worker.py).
#   c) EVENTO VIA HTTP — rotas do Next fazem POST em `/api/automation/trigger`, e
#      `automation/router.py` repassa para `fire_trigger` em background:
#        deal_stage_enter, deal_closed_lost  <- frontend/src/app/api/deals/[id]/route.ts
#        stage_enter                         <- frontend/src/app/api/leads/[id]/route.ts
#        tag_added                           <- frontend/src/app/api/leads/[id]/tags/route.ts
#        sale_created                        <- frontend/src/app/api/sales/route.ts
#
# Os doze tem emissor. O defeito destes cinco do caminho (c) nunca foi falta de quem
# dispare — e o VOCABULARIO do filtro, que e o motivo deste registro existir.

_GATILHOS: tuple[TipoDeNo, ...] = (
    TipoDeNo(
        tipo="trigger", subtipo="no_message", rotulo="Sem mensagem", icone="💤",
        campos=(
            Campo("days", "numero", "Dias em silencio", default=30,
                  ajuda="Compara com `leads.last_msg_at`. O inspector exibe 0 como "
                        "valor inicial, mas o motor assume 30 quando a chave falta."),
            # O UNICO gatilho com `stage_filter` que o inspector nao oferece hoje: o
            # bloco de "Filtro de stage" cobre stage_stagnation/stage_enter/
            # no_sale_in_stage/deal_stage_enter e deixa este de fora. Nao e
            # obrigatorio — aqui `if not stage` NAO pula o gatilho, so nao filtra.
            Campo("stage_filter", "segmento_lead", "Segmento do lead (opcional)",
                  ajuda="Vazio = qualquer segmento. Compara com `leads.stage`, NAO "
                        "com a coluna do Kanban."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="stage_stagnation", rotulo="Parado no segmento", icone="🕐",
        campos=(
            # OBRIGATORIO por causa do `if not stage: continue` em
            # triggers.check_polling_triggers — sem ele o gatilho e pulado inteiro,
            # todo tick, sem uma linha de log.
            Campo("stage_filter", "segmento_lead", "Segmento do lead", obrigatorio=True,
                  ajuda="Sem este campo o motor PULA o gatilho inteiro, em silencio. "
                        "Compara com `leads.stage`."),
            Campo("days", "numero", "Dias parado no segmento", default=7,
                  ajuda="Compara com `leads.entered_stage_at`. O motor assume 7 na "
                        "ausencia da chave; o inspector cria o no com 30 (o default "
                        "generico de gatilho)."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="no_sale_in_stage", rotulo="Sem venda no segmento", icone="📉",
        campos=(
            # Mesmo `if not stage: continue` do stage_stagnation.
            Campo("stage_filter", "segmento_lead", "Segmento do lead", obrigatorio=True,
                  ajuda="Sem este campo o motor PULA o gatilho inteiro, em silencio. "
                        "Vai como `p_stage` para a RPC get_leads_no_sale_in_stage."),
            Campo("days", "numero", "Dias no segmento sem venda", default=7,
                  ajuda="Mesma divergencia do stage_stagnation: motor assume 7, "
                        "inspector cria o no com 30."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="stage_enter", rotulo="Entrou em segmento", icone="⚡",
        campos=(
            Campo("stage_filter", "segmento_lead", "Segmento do lead (opcional)",
                  ajuda="Disparado por api/leads/[id]/route.ts via POST "
                        "/api/automation/trigger. Vazio = qualquer segmento; "
                        "compara com `data['stage']`, que carrega o SEGMENTO do lead."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="deal_stage_enter", rotulo="Card entrou em etapa", icone="🤝",
        campos=(
            # O unico gatilho cujo `stage_filter` NAO e segmento de lead: aqui o
            # motor compara com a etapa do funil. Mesmo nome de chave, vocabulario
            # oposto — a razao de ser deste registro.
            Campo("stage_filter", "etapa_key", "Etapa do funil (opcional)",
                  ajuda="Disparado por api/deals/[id]/route.ts via POST "
                        "/api/automation/trigger, que manda a KEY da coluna. Aqui e "
                        "`pipeline_stages.key` — nao o rotulo, nao o segmento do lead."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="deal_stage_stagnation", rotulo="Card parado no funil", icone="📋",
        campos=(
            Campo("stage_id", "etapa_id", "Etapa exata (uuid)",
                  ajuda="Identifica UMA coluna de UM funil. Alternativa a stage_key."),
            Campo("stage_key", "etapa_key", "Etapa por key",
                  ajuda="Casa a mesma key em todos os funis do escopo — use junto "
                        "com pipeline_id para restringir."),
            Campo("pipeline_id", "funil_id", "Funil",
                  ajuda="Restringe a busca a um funil. Sem ele, `stage_key` casa a "
                        "mesma coluna em TODOS os funis."),
            Campo("stage_days", "numero", "Dias parado na etapa", default=0,
                  ajuda="0 = sem filtro de tempo na etapa. Combina por E com "
                        "silence_days."),
            Campo("silence_days", "numero", "Dias sem mensagem", default=0,
                  ajuda="0 = sem filtro de silencio."),
            Campo("last_speaker", "falante", "Quem falou por ultimo", default="qualquer"),
            Campo("limit", "numero", "Cards por tick", default=20,
                  ajuda="Teto de matriculas por passagem do polling. Em base grande "
                        "este numero e o que segura a avalanche do primeiro tick."),
            # A politica da ESTEIRA INTEIRA mora no gatilho, nao no envio: a matricula
            # passa a maior parte da vida parada num `wait`, e e ali que a resposta
            # chega (worker._trigger_on_reply). Ver o par deste campo em `send`.
            Campo("on_reply", "politica_resposta", "Se o lead responder", default="pause",
                  ajuda="Vale para a esteira toda. Ausente = pausar."),
        ),
        # `stage_id` e `stage_key` sao opcionais SOZINHOS (da para usar um ou outro),
        # mas a RPC get_deals_stage_stagnant e FAIL-CLOSED com os dois nulos: devolve
        # conjunto vazio. Antes de ser fail-closed, os dois nulos varriam TODO card
        # aberto de TODO funil — uma esteira ligada antes de configurada disparava
        # template para a base inteira. Declarar o grupo faz a tela dizer isso.
        requer_um_de=(("stage_id", "stage_key"),),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="keyword_received", rotulo="Palavra-chave recebida", icone="🔍",
        campos=(
            Campo("keywords", "lista_texto", "Palavras-chave", obrigatorio=True,
                  ajuda="Lista vazia = o gatilho nunca casa (triggers pula antes do "
                        "match). Casamento por palavra inteira: 'sim' nao casa "
                        "'assim'."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="repurchase_window", rotulo="Janela de recompra", icone="🔄",
        campos=(
            Campo("days", "numero", "Dias desde a ultima compra", obrigatorio=True, default=30,
                  ajuda="Vai como `cutoff_date` para a RPC get_leads_for_repurchase."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="sale_created", rotulo="Venda criada", icone="💰",
        campos=(
            Campo("min_value", "numero", "Valor minimo (R$, opcional)",
                  ajuda="Disparado por api/sales/route.ts via POST /api/automation/trigger. "
                        "0/vazio = sem piso."),
            Campo("product_filter", "texto", "Filtro de produto (opcional)",
                  ajuda="Casamento por SUBSTRING, sem insensibilidade a acento."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="tag_added", rotulo="Tag adicionada", icone="🏷️",
        campos=(
            Campo("tag_name", "tag", "Tag (opcional)",
                  ajuda="Disparado por api/leads/[id]/tags/route.ts via POST /api/automation/trigger. "
                        "Vazio = qualquer tag."),
        ),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="deal_closed_lost", rotulo="Card perdido", icone="❌",
        campos=(),
    ),
    TipoDeNo(
        tipo="trigger", subtipo="post_broadcast", rotulo="Pos-disparo", icone="📡",
        # SEM `replied_only`, de proposito — ver o item 4 do cabecalho. O campo
        # existia na tela, saia de `broadcast/worker.py` como `False` fixo e nao era
        # lido por ninguem: prometia "so quem respondeu" e matriculava todo mundo.
        # Para ressuscita-lo e preciso primeiro alguem que o LEIA no `_passes_filter`.
        campos=(),
    ),
)


# ─── Acoes ───────────────────────────────────────────────────────────────────────

_ACOES: tuple[TipoDeNo, ...] = (
    TipoDeNo(
        tipo="action", subtipo="move_stage", rotulo="Mover segmento do lead", icone="📋",
        campos=(
            # Sem `stage`, engine `_execute_action` nao faz nada e devolve False (log
            # "skipped"). Obrigatorio para ativar.
            Campo("stage", "segmento_lead", "Segmento de destino", obrigatorio=True,
                  ajuda="Grava em `leads.stage`. O motor tambem aceita a chave legada "
                        "`stage_name`, que a tela nunca deve escrever."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="move_deal_stage", rotulo="Mover card de etapa", icone="🔀",
        campos=(
            Campo("stage_id", "etapa_id", "Etapa de destino", obrigatorio=True,
                  ajuda="uuid da coluna. O motor NAO tem fallback por key: sem "
                        "stage_id a acao retorna sem tocar o card."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="mark_deal_won", rotulo="Marcar card como ganho", icone="🏆",
        campos=(
            Campo("stage_id", "etapa_id", "Etapa de ganho", obrigatorio=True,
                  ajuda="Mesma mecanica do mover: e um move para a coluna de ganho, "
                        "e e ele que dispara a conversao da etapa."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="mark_deal_lost", rotulo="Marcar card como perdido", icone="💔",
        campos=(
            Campo("stage_id", "etapa_id", "Etapa de perda", obrigatorio=True),
            Campo("lost_reason", "texto", "Motivo da perda (opcional)",
                  ajuda="Grava `deals.lost_reason` — aparece no card e nos relatorios."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="add_tag", rotulo="Adicionar tag", icone="🏷️",
        campos=(
            Campo("tag_name", "tag", "Tag", obrigatorio=True,
                  ajuda="A tag precisa EXISTIR em `tags`; o motor procura por nome e "
                        "nao cria. Nome que nao existe = acao silenciosamente nula."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="remove_tag", rotulo="Remover tag", icone="🏷️",
        campos=(
            Campo("tag_name", "tag", "Tag", obrigatorio=True),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="create_deal", rotulo="Criar card", icone="💼",
        campos=(
            # O acento em "automático" NAO e descuido: `default` e o texto que o
            # motor usa quando a chave falta, e ele esta assim no engine. Um default
            # "parecido" aqui faria a tela semear um titulo diferente do que o motor
            # cria — pequeno, mas e exatamente o tipo de divergencia que este modulo
            # existe para nao ter.
            Campo("title_template", "texto", "Titulo do card", default="Deal automático",
                  ajuda="Aceita variaveis ({{nome}}, {{empresa}}...)."),
            # Item 3 do cabecalho. `engine._execute_action` chama create_deal SEM
            # pipeline_id e o card nasce no "primeiro pipeline" — funil errado, em
            # silencio. Obrigatorio aqui para que a escolha pare de ser implicita;
            # fazer o motor repassar o valor e a outra metade do conserto.
            Campo("pipeline_id", "funil_id", "Funil de destino", obrigatorio=True,
                  ajuda="Sem funil explicito o card cai no PRIMEIRO pipeline do banco."),
            Campo("stage_key", "etapa_key", "Etapa inicial (opcional)",
                  ajuda="KEY da coluna dentro do funil escolhido. Vazio = primeira "
                        "etapa do funil."),
            Campo("category", "texto", "Categoria (opcional)",
                  ajuda="Grava `deals.category` (atacado, private_label, exportacao, "
                        "consumo). E rotulo do card, nao decide o funil."),
            Campo("dedupe_open", "booleano", "Reaproveitar card aberto", default=False,
                  ajuda="True = se o lead ja tem card aberto, reaproveita em vez de "
                        "criar outro. E como o resto do sistema chama create_deal "
                        "(reposicao, follow-up, tools do agente)."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="assign_to", rotulo="Atribuir a vendedor", icone="👤",
        campos=(
            Campo("user_id", "usuario_id", "Vendedor", obrigatorio=True),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="assign_round_robin", rotulo="Atribuir (round-robin)", icone="🎯",
        campos=(
            Campo("user_ids", "lista_usuario_id", "Vendedores no rodizio", obrigatorio=True,
                  ajuda="Lista vazia = a acao nao faz nada. O indice do rodizio vive "
                        "em `campaigns.last_assigned_index`, por campanha."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="add_note", rotulo="Adicionar nota", icone="📝",
        campos=(
            Campo("note_template", "texto_longo", "Texto da nota", obrigatorio=True,
                  ajuda="Aceita variaveis. Vazio = nenhuma nota e criada."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="alert_seller", rotulo="Avisar vendedor", icone="🔔",
        campos=(
            Campo("severity", "severidade", "Gravidade", default="warning"),
            # Obrigatorio porque o fallback do motor ("Esteira encerrada") e generico
            # a ponto de o vendedor nao saber do que se trata.
            Campo("title", "texto", "Titulo do alerta", obrigatorio=True,
                  ajuda="Aceita variaveis. Ausente = o motor usa 'Esteira encerrada'."),
            Campo("message_template", "texto_longo", "Mensagem do alerta",
                  ajuda="Cria alerta no sistema E nota na timeline. Nao envia nada "
                        "ao lead."),
        ),
    ),
    TipoDeNo(
        tipo="action", subtipo="activate_agent", rotulo="Ativar a IA no lead", icone="🤖",
        campos=(),
    ),
    TipoDeNo(
        tipo="action", subtipo="deactivate_agent", rotulo="Desativar a IA no lead", icone="🤖",
        campos=(),
    ),
)


# ─── Condicoes ───────────────────────────────────────────────────────────────────
#
# As dez entram na paleta UMA A UMA. Ate 16/09/2026 a paleta tinha um unico item
# "Condicao" que nascia `replied_recently`, e as outras oito so existiam num <select>
# escondido dentro do inspector — ninguem que nao conhecesse o codigo sabia que
# existiam. A decima (`clicou_botao`) nasceu ja na paleta.
#
# Condicao sem o seu campo preenchido NAO bloqueia a ativacao (nao ha `obrigatorio`
# abaixo): diferente do gatilho, que e pulado em silencio, uma condicao incompleta
# apenas cai sempre no ramo NAO — um caminho que o dono desenhou e consegue ver no
# canvas.

_OP = Campo("operator", "operador", "Operador", default="gte",
            ajuda="Operador desconhecido faz `_compare` devolver False SEMPRE.")

_CONDICOES: tuple[TipoDeNo, ...] = (
    TipoDeNo(
        tipo="condition", subtipo="replied_recently", rotulo="Respondeu recentemente", icone="💬",
        campos=(
            Campo("days", "numero", "Nos ultimos X dias", default=5,
                  ajuda="Procura mensagem com role='user' na janela."),
        ),
    ),
    TipoDeNo(
        tipo="condition", subtipo="in_stage", rotulo="Esta no segmento", icone="📋",
        campos=(
            # MESMO bug do `stage_filter`: o inspector oferece as colunas de Kanban e
            # grava o rotulo, enquanto o motor compara com `leads.stage`. Esta e a
            # SEXTA ocorrencia do bug (as outras cinco sao gatilhos).
            Campo("stage", "segmento_lead", "Segmento",
                  ajuda="Compara com `leads.stage`. Vazio = a condicao responde NAO "
                        "sempre."),
        ),
    ),
    TipoDeNo(
        tipo="condition", subtipo="has_deal", rotulo="Tem card no CRM", icone="💼",
        campos=(),
    ),
    TipoDeNo(
        tipo="condition", subtipo="has_tag", rotulo="Possui tag", icone="🏷️",
        campos=(
            Campo("tag_name", "tag", "Tag",
                  ajuda="Tag inexistente = responde NAO, sem erro."),
        ),
    ),
    TipoDeNo(
        tipo="condition", subtipo="sale_count", rotulo="Numero de vendas", icone="🧾",
        campos=(_OP, Campo("value", "numero", "Quantidade", default=1)),
    ),
    TipoDeNo(
        tipo="condition", subtipo="total_spend", rotulo="Gasto total (R$)", icone="💰",
        campos=(_OP, Campo("value", "numero", "Valor em R$", default=0)),
    ),
    TipoDeNo(
        tipo="condition", subtipo="last_sale_value", rotulo="Valor da ultima venda", icone="💵",
        campos=(_OP, Campo("value", "numero", "Valor em R$", default=0)),
    ),
    TipoDeNo(
        tipo="condition", subtipo="deal_value", rotulo="Valor do card", icone="🏷️",
        campos=(_OP, Campo("value", "numero", "Valor em R$", default=0,
                           ajuda="Olha o card MAIS RECENTE do lead, nao o do enrollment.")),
    ),
    TipoDeNo(
        tipo="condition", subtipo="repurchase_days", rotulo="Dias desde a ultima compra", icone="🔄",
        campos=(_OP, Campo("value", "numero", "Dias", default=30,
                           ajuda="Lead que nunca comprou responde NAO em qualquer "
                                 "operador — nao ha data para comparar.")),
    ),
    # A decima, de 16/09/2026 (§11). As outras nove olham o CRM (segmento, cards,
    # vendas, tags); esta olha a ULTIMA RESPOSTA do lead, gravada em
    # `campaign_enrollments.metadata.ultima_resposta` por `worker.handle_campaign_reply`.
    # E o que faltava para RAMIFICAR no meio da cadencia: sem ela, um clique so
    # conseguia encerrar a esteira (via `on_reply_por_botao`), nunca desvia-la.
    TipoDeNo(
        tipo="condition", subtipo="clicou_botao", rotulo="Clicou no botao", icone="🔘",
        campos=(
            Campo("botao", "texto", "Rotulo do botao",
                  ajuda="Comparacao por IGUALDADE normalizada (minuscula, sem acento, "
                        "sem pontuacao) — nao substring. Vazio = a condicao responde "
                        "NAO sempre. O motor nao distingue clique de digitacao: quem "
                        "digitar o rotulo cai no mesmo ramo, e isso e aceito."),
        ),
    ),
)


# ─── Envio, espera e fim ─────────────────────────────────────────────────────────
#
# `on_reply_por_botao` (§11, 16/09/2026) e o campo que tira a decisao de saida do
# frozenset global de duas frases e a poe NO NO. Um so `on_reply` por no aplicava a
# mesma politica ao clique em "Continuar" e ao clique em "Parar atendimento": o botao
# de saida era decorativo. Aqui o dono declara `{rotulo: politica}` e o motor
# (`worker._politica_do_botao`) casa por IGUALDADE normalizada — minuscula, sem acento,
# sem pontuacao, nos DOIS lados, porque o rotulo e digitado por gente na tela.
#
# Vocabulario `mapa` pelo mesmo motivo de `template_variables`: e um DICIONARIO, e
# tipar como "texto_longo" faria a tela gravar string onde o motor espera dict.
#
# default None e nao {}: `_politica_do_botao` exige `isinstance(mapa, dict)`, entao
# ausente e vazio dao no mesmo — e um dict literal aqui seria compartilhado por todos
# os nos (dataclass frozen congela a referencia, nao o conteudo).
_BOTOES = Campo(
    "on_reply_por_botao", "mapa", "Politica por botao do template", default=None,
    ajuda="{rotulo do botao: politica}. Vence o campo acima, mas SO para o rotulo que "
          "casar; qualquer outra resposta cai na politica do no e depois na do gatilho. "
          "Ex.: {'parar atendimento': 'optout', 'continuar': 'reset'}.",
)

_DEMAIS: tuple[TipoDeNo, ...] = (
    TipoDeNo(
        tipo="send", subtipo=None, rotulo="Enviar template", icone="📨",
        campos=(
            # `worker._execute_send_node` faz cfg["template_name"] — acesso direto,
            # nao .get: nome vazio levanta KeyError e a matricula entra em retry.
            Campo("template_name", "template", "Template aprovado", obrigatorio=True,
                  ajuda="Precisa estar APROVADO na Meta. Nome repetido entre toques "
                        "manda o mesmo texto duas vezes: o motor de cadencias nao tem "
                        "o dedup por (lead, template) que o broadcast tem."),
            Campo("template_language", "texto", "Idioma do template", default="pt_BR"),
            # default None e nao {}: `_build_template_components` faz
            # `template_variables or {}`, entao ausente e vazio dao no mesmo — e um
            # dict literal aqui seria compartilhado por todos os nos (dataclass
            # frozen congela a referencia, nao o conteudo).
            Campo("template_variables", "mapa", "Variaveis do template", default=None,
                  ajuda="Vazio = template sem variaveis. Dicionario resolvido no "
                        "instante do envio "
                        "({'__params_type__': 'positional', '1': '{{primeiro_nome}}'})."),
            Campo("channel_id", "canal_id", "Canal (opcional)",
                  ajuda="Vazio = usa o canal da campanha."),
            # DEFAULT None E OBRIGATORIO AQUI. O motor da precedencia ao NO sobre o
            # GATILHO (worker._apply_reply_policy), entao gravar 'pause' em todo no de
            # envio — como `getDefaultConfig` faz hoje — SEQUESTRA a politica da
            # esteira: um gatilho com on_reply='reset' (esteira "Em conversa") pausaria
            # na primeira resposta em vez de rebobinar, sem erro em lugar nenhum. E a
            # mesma armadilha documentada em `esteiras_joao._send`.
            Campo("on_reply", "politica_resposta", "Se o lead responder NESTE toque",
                  default=None,
                  ajuda="Vazio = herda a politica do gatilho (o normal). Preencher "
                        "aqui SOBREPOE a esteira inteira, so neste toque."),
            _BOTOES,
        ),
    ),
    TipoDeNo(
        tipo="send_text", subtipo=None, rotulo="Enviar texto livre", icone="💬",
        campos=(
            Campo("message_text", "texto_longo", "Mensagem", obrigatorio=True,
                  ajuda="So sai DENTRO da janela de 24h desse canal; fora dela o no e "
                        "reagendado e, no fim das tentativas, cancelado."),
            Campo("channel_id", "canal_id", "Canal (opcional)",
                  ajuda="Vazio = usa o canal da campanha. Aqui o canal tambem decide "
                        "QUAL janela de 24h vale (a janela e por canal)."),
            Campo("on_reply", "politica_resposta", "Se o lead responder NESTE toque",
                  default=None,
                  ajuda="Mesma regra do `send`: vazio herda do gatilho."),
            _BOTOES,
        ),
    ),
    TipoDeNo(
        tipo="wait", subtipo=None, rotulo="Aguardar", icone="⏱",
        campos=(
            Campo("days", "numero", "Dias", default=1,
                  ajuda="Soma com `hours`. O inspector cria nos novos com 3."),
            Campo("hours", "numero", "Horas", default=0,
                  ajuda="Permite espera sub-diaria (days=0 + hours=N)."),
            # OS TRES ABAIXO TEM DEFAULT None DE PROPOSITO. `_wait_target` faz
            # cfg.get("send_start_hour", camp.get("send_start_hour", 7)): o valor do
            # NO vence o da CAMPANHA. Gravar 7/18 em todo no novo — como o builder fez
            # ate 13/09/2026 — fazia o no "opinar" sempre, e a janela configurada na
            # campanha nunca valia para nada montado na tela.
            Campo("send_start_hour", "numero", "Inicio da janela (opcional)", default=None,
                  ajuda="Vazio = herda a janela da campanha. Horario de Brasilia."),
            Campo("send_end_hour", "numero", "Fim da janela (opcional)", default=None,
                  ajuda="Vazio = herda a janela da campanha."),
            Campo("skip_weekends", "booleano", "Pular fim de semana (opcional)", default=None,
                  ajuda="Vazio = herda da campanha."),
        ),
    ),
    TipoDeNo(
        tipo="end", subtipo=None, rotulo="Encerrar", icone="🏁",
        campos=(
            # So documentacao: o motor le `final_actions` deste no (chave interna,
            # montada pela tela como uma lista de configs de acao) e NAO le `label`.
            Campo("label", "texto", "Rotulo do encerramento", default="",
                  ajuda="So aparece no canvas e no log — o motor nao le este campo."),
        ),
    ),
)


REGISTRO: dict[tuple[str, str | None], TipoDeNo] = {
    (t.tipo, t.subtipo): t
    for t in (*_GATILHOS, *_ACOES, *_CONDICOES, *_DEMAIS)
}


def para_json() -> list[dict]:
    """O registro em JSON puro, na ordem de declaracao — e o que a tela consome.

    Ordem importa: e a ordem em que os tipos aparecem na paleta. Dicts e listas
    (nunca dataclass nem tupla), para atravessar `json.dumps` sem `default=`.
    """
    return [
        {
            "tipo": t.tipo,
            "subtipo": t.subtipo,
            "rotulo": t.rotulo,
            "icone": t.icone,
            "na_paleta": t.na_paleta,
            "requer_um_de": [list(grupo) for grupo in t.requer_um_de],
            "campos": [
                {
                    "chave": c.chave,
                    "vocab": c.vocab,
                    "rotulo": c.rotulo,
                    "obrigatorio": c.obrigatorio,
                    "default": c.default,
                    "ajuda": c.ajuda,
                }
                for c in t.campos
            ],
        }
        for t in REGISTRO.values()
    ]
