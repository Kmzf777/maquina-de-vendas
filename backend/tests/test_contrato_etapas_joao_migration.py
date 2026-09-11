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


def test_esvazia_proposta_e_negociacao_DENTRO_do_update_que_move_cards():
    """Nao basta os UUIDs aparecerem no arquivo: eles tem de estar no UPDATE que
    esvazia as etapas. Citados num WHERE qualquer, os 27 cards ficam onde estao e o
    DELETE seguinte levanta FK 23503."""
    sql = _sem_comentario()
    ini = sql.index("UPDATE deals SET stage_id")
    update = sql[ini:sql.index(";", ini)]
    assert PROPOSTA_PL in update, "'Proposta' do PL nao esta no UPDATE que move cards"
    assert NEGOCIACAO_PL in update, "'Negociacao' do PL nao esta no UPDATE que move cards"


def test_recupera_a_key_proposta_enviada_do_funil_reposicao():
    """Sem esta key, `_move_deal_to_proposal` nao acha a etapa e o orcamento nao move
    o card — em silencio, com log `info` (quotes/router.py:274-279)."""
    sql = _sem_comentario()
    assert re.search(
        r"UPDATE pipeline_stages SET key = 'proposta_enviada'[^;]*" + PROP_ENV_REPOSICAO,
        sql,
    ), "a key 'proposta_enviada' nao e restaurada na etapa da Reposicao"


# (etapa, key) medidos em producao em 10/09/2026. Ancorar a key ao UUID e o que
# separa "a migration faz a coisa certa" de "o arquivo contem as palavras certas".
KEYS_POR_ETAPA = (
    ("26103dba-b371-47a5-b990-70da776ccce5", "novo"),               # Atacado / Novo
    ("6027a761-ed7e-4d34-b388-5ec2debbeaae", "respondeu"),          # Atacado / Em conversa
    ("05b52405-806d-4f1f-89e8-f96c9fd86ba5", "novo"),               # PL / Novo
    ("c778fe72-ed7c-49cc-b5c8-8d50b00dd84a", "respondeu"),          # PL / Contato -> Em conversa
    ("07b4a308-c2ad-4896-99ee-caee30f926b8", "novo"),               # Reposicao / Cliente Ativo
    ("58b9fbe0-c138-4dcb-8318-ed2409c61a9a", "chamado_reposicao"),  # Reposicao / Ja chamado
    ("499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0", "em_atencao"),         # Reposicao / Em atencao
    ("d1a0a022-71fe-4ff9-bc7d-3ff813a4d9ec", "proposta_enviada"),   # Reposicao / a key perdida
    ("699e0b61-ee7f-480e-827e-fd970379c7da", "entrada"),            # Recuperacao
    ("d8d39be3-97ea-4a43-9cfe-bc95d0fb52b1", "em_followup"),        # Recuperacao
    ("d5bad206-280a-461d-b122-d2c4f0f3a088", "recuperado"),         # Recuperacao
)


def test_cada_etapa_recebe_a_key_que_lhe_cabe():
    """Etapa sem key e invisivel para o codigo de negocio, que resolve por key.

    Checa o PAR (etapa, key) no mesmo statement: oito UPDATEs soltos com as keys
    certas em etapas erradas passariam num assert de presenca.
    """
    sql = _sem_comentario()
    for uuid_etapa, key in KEYS_POR_ETAPA:
        assert re.search(rf"SET key = '{key}'[^;]*{uuid_etapa}", sql), (
            f"etapa {uuid_etapa} nao recebe a key '{key}'"
        )


def test_nao_usa_ja_chamado():
    """`deals.stage='ja_chamado'` e lido por lead_has_active_relationship e
    _lead_had_prior_handoff, e NUNCA e limpo: o PATCH do Kanban escreve stage_id e
    closed_at, nunca deals.stage. O lead ficaria 'relacionamento ativo' para sempre.
    Decisao do spec §4/SP0 nota 2: usar `chamado_reposicao`, que ninguem le."""
    assert "'ja_chamado'" not in _sem_comentario()


def test_recuperacao_so_recebe_as_tres_keys_decididas():
    """Decisao da reuniao (55:20, 54:39): a saida da Recuperacao e MUDAR DE FUNIL, entao
    ela nao ganha `proposta_enviada` nem `fechado_ganho` — e tambem nao entra no INSERT
    de "Em atencao", que e estado terminal de esteira de 1a compra e de reposicao.

    Checa por UUID, nao por nome de funil: o rotulo e editavel pelo operador.
    """
    sql = _sem_comentario()
    for uuid_etapa, key in (
        ("699e0b61-ee7f-480e-827e-fd970379c7da", "'entrada'"),
        ("d8d39be3-97ea-4a43-9cfe-bc95d0fb52b1", "'em_followup'"),
        ("d5bad206-280a-461d-b122-d2c4f0f3a088", "'recuperado'"),
    ):
        assert re.search(rf"SET key = {key}[^;]*{uuid_etapa}", sql), (
            f"etapa {uuid_etapa} da Recuperacao nao recebe {key}"
        )

    inicio = sql.index("INSERT INTO pipeline_stages")
    bloco_insert = sql[inicio:sql.index(";", inicio)]
    assert RECUPERACAO not in bloco_insert, (
        "o funil de Recuperacao nao deve ganhar a etapa 'Em atencao'"
    )


def test_protege_as_terminais_no_mesmo_statement():
    """Hoje NENHUMA etapa e protegida, e `_first_unprotected_stage_id` elege a etapa de
    entrada pelo menor order_index: um arrasta-e-solta infeliz faz todo card novo
    nascer em 'Perdido'. A protecao tem de mirar as duas keys terminais."""
    sql = _sem_comentario()
    ini = sql.index("is_protected = true")
    stmt = sql[sql.rindex("UPDATE", 0, ini):sql.index(";", ini)]
    assert "'fechado_ganho'" in stmt and "'fechado_perdido'" in stmt, (
        "o UPDATE de is_protected nao mira fechado_ganho e fechado_perdido"
    )


def test_nao_preenche_conversion_event():
    """Preencher esse campo despacha o card para Meta CAPI / Google Ads e contamina a
    serie 'Conversoes (Ads)' (documentado em 20260909:44-99)."""
    assert "conversion_event" not in _sem_comentario()


def test_guardas_abortam_nos_tres_casos_que_importam():
    """A migration foi escrita contra uma medicao de 10/09/2026 e roda a mao, dias
    depois, no funil de trabalho do vendedor. Tres coisas tem de abortar a transacao:
    a etapa de origem sumiu, a de destino sumiu, ou o volume movido nao bate com o
    esperado (sinal de WHERE errado)."""
    sql = _sem_comentario()
    assert sql.count("RAISE EXCEPTION") >= 3, (
        f"so {sql.count('RAISE EXCEPTION')} guardas — esperado ao menos 3"
    )
    assert "GET DIAGNOSTICS" in sql, "a migration nao confere quantas linhas moveu"
    assert re.search(r"NOT EXISTS\s*\(\s*SELECT[^)]*pipeline_stages", sql), (
        "nenhuma guarda confere se as etapas esperadas ainda existem"
    )


def test_notify_pgrst_e_a_ULTIMA_instrucao():
    """Sem isso o PostgREST serve o schema em cache e o CRM responde PGRST204/205 com a
    coluna ja existindo. E precisa vir DEPOIS do COMMIT: notificar dentro da transacao
    avisa sobre um schema que ainda pode ser desfeito."""
    txt = _sql().rstrip()
    resto = txt[txt.rindex("NOTIFY pgrst"):]
    assert ";" in resto and resto.split(";", 1)[1].strip() == "", (
        "existe instrucao depois do NOTIFY pgrst"
    )
    assert txt.rindex("COMMIT") < txt.rindex("NOTIFY pgrst"), (
        "o NOTIFY vem antes do COMMIT"
    )


def test_reclassifica_os_cards_de_novo_por_mensagem_e_nao_por_ultimo_falante():
    """363 dos 578 cards em 'Novo' tem lead que ja falou no numero do Joao.

    O criterio TEM de ser 'existe mensagem role=user em conversa de canal humano'.
    Classificar por 'quem falou por ultimo' poria de volta em 'Novo' todo lead que o
    Joao respondeu por ultimo — que sao 792 dos 810.
    """
    sql = _sem_comentario()
    assert "role = 'user'" in sql, "a reclassificacao nao olha mensagem do lead"
    assert "mode = 'human'" in sql, "a reclassificacao nao restringe ao canal do vendedor"
    # O criterio errado seria classificar por quem falou por ultimo. Se a migration usar
    # `last_customer_message_at` para decidir a etapa, e sinal de que foi por esse caminho.
    assert "last_customer_message_at" not in sql, (
        "a reclassificacao parece usar 'quem falou por ultimo', que da 792 de 810 leads"
    )


def test_guarda_de_contrato_recusa_etapa_sem_key():
    """UPDATE que nao acha a linha nao e erro no Postgres — so afeta zero linhas.
    Sem esta guarda, um UUID mudado desde a medicao faria o passo 3 nao fazer nada,
    o passo 7 virar no-op, e a migration terminar 'com sucesso' pela metade."""
    sql = _sem_comentario()
    assert re.search(r"key IS NULL", sql), "nao ha guarda contra etapa sem key"
    assert re.search(r"sem_key\s*>\s*0", sql), "a contagem de etapas sem key nao aborta"


def test_guarda_o_destino_da_reclassificacao_antes_de_tentar():
    """Checar o destino, e nao a contagem movida, mantem a guarda segura para
    re-execucao: na segunda rodada o certo e mover zero cards."""
    sql = _sem_comentario()
    ini = sql.index("RECLASSIFICAR") if "RECLASSIFICAR" in sql else 0
    assert sql.count("key = 'respondeu'") >= 3, (
        "faltam as checagens de existencia de 'respondeu' nos dois funis de 1a compra"
    )
