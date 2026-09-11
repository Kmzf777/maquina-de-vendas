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


def test_esvazia_exatamente_proposta_e_negociacao_do_private_label():
    sql = _sem_comentario()
    assert PROPOSTA_PL in sql, "etapa 'Proposta' do Private Label nao e esvaziada"
    assert NEGOCIACAO_PL in sql, "etapa 'Negociacao' do Private Label nao e esvaziada"


def test_recupera_a_key_proposta_enviada_do_funil_reposicao():
    """Sem esta key, `_move_deal_to_proposal` nao acha a etapa e o orcamento nao move
    o card — em silencio, com log `info` (quotes/router.py:274-279)."""
    sql = _sem_comentario()
    assert re.search(
        r"UPDATE pipeline_stages SET key = 'proposta_enviada'[^;]*" + PROP_ENV_REPOSICAO,
        sql,
    ), "a key 'proposta_enviada' nao e restaurada na etapa da Reposicao"


def test_toda_etapa_dos_funis_do_joao_recebe_key():
    """Etapa sem key e invisivel para o codigo de negocio, que resolve por key."""
    sql = _sem_comentario()
    for key in (
        "'novo'", "'respondeu'", "'em_atencao'", "'proposta_enviada'",
        "'chamado_reposicao'", "'entrada'", "'em_followup'", "'recuperado'",
    ):
        assert f"SET key = {key}" in sql, f"nenhuma etapa recebe key {key}"


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


def test_protege_fechado_ganho_e_perdido():
    """Hoje NENHUMA etapa e protegida, e `_first_unprotected_stage_id` elege a etapa de
    entrada pelo menor order_index: um arrasta-e-solta infeliz faz todo card novo
    nascer em 'Perdido'."""
    sql = _sem_comentario()
    assert "is_protected = true" in sql
    assert "'fechado_ganho'" in sql and "'fechado_perdido'" in sql


def test_nao_preenche_conversion_event():
    """Preencher esse campo despacha o card para Meta CAPI / Google Ads e contamina a
    serie 'Conversoes (Ads)' (documentado em 20260909:44-99)."""
    assert "conversion_event" not in _sem_comentario()


def test_tem_guarda_que_aborta_se_o_estado_mudou():
    """A migration foi escrita contra uma medicao de 10/09/2026. Se alguem mexer no
    board antes de aplica-la, e melhor abortar do que espalhar card na coluna errada."""
    sql = _sem_comentario()
    assert "RAISE EXCEPTION" in sql


def test_termina_com_notify_pgrst():
    """Sem isso o PostgREST serve o schema em cache e o CRM responde PGRST204/205 com a
    coluna ja existindo no banco. Precedente: 20260825:195 e 20260909:162."""
    assert "NOTIFY pgrst" in _sql()


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
