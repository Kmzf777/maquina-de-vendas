"""Guardas da RPC `get_deals_stage_stagnant` (20260904_esteiras_vendedor.sql).

Cada teste aqui corresponde a um jeito CONCRETO de a esteira mandar template de
WhatsApp para quem nao devia — cliente real de uma torrefacao, pelo numero do
vendedor. Nenhum deles e estetico.

Sao asserts no TEXTO do SQL, e nao num Postgres de verdade, porque a migration deste
repo nao e aplicada pelo deploy: ela roda a mao no editor do Supabase e a suite nao
tem banco. Mesmo padrao de `test_bling_migration.py`.
"""
import pathlib
import re

SQL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260904_esteiras_vendedor.sql"
)

FN = "get_deals_stage_stagnant"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _fn_code() -> str:
    """Corpo de `get_deals_stage_stagnant` SEM comentarios e com espacos normalizados.

    Tirar os `--` importa: o arquivo explica cada guarda em portugues logo acima
    dela, e um assert de texto casaria com a EXPLICACAO em vez de com o codigo —
    passaria com a guarda apagada e o comentario esquecido.
    """
    txt = _sql()
    ini = txt.index(f"CREATE OR REPLACE FUNCTION {FN}")
    fim = txt.index("$$ LANGUAGE sql STABLE", ini)
    sem_comentario = "\n".join(linha.split("--")[0] for linha in txt[ini:fim].splitlines())
    return re.sub(r"\s+", " ", sem_comentario).strip()


def _subselect(marcador: str) -> str:
    """Trecho de um subselect correlacionado, do marcador ate o `)` que o fecha."""
    fn = _fn_code()
    i = fn.index(marcador)
    prof, j = 1, i
    while j < len(fn) and prof:
        if fn[j] == "(":
            prof += 1
        elif fn[j] == ")":
            prof -= 1
        j += 1
    return fn[i:j - 1]


def test_migration_existe():
    assert SQL.exists(), "migration 20260904_esteiras_vendedor.sql nao encontrada"


# ---------------------------------------------------------------------------
# Correcao 1 — cooldown por campanha (a esteira precisa PARAR)
# ---------------------------------------------------------------------------
def test_assinatura_tem_campanha_e_cooldown():
    fn = _fn_code()
    assert "p_campaign_id uuid DEFAULT NULL" in fn
    assert re.search(r"p_cooldown_days int DEFAULT 90", fn)


def test_cooldown_exclui_card_que_ja_passou_pela_campanha():
    fn = _fn_code().lower()
    assert "from campaign_enrollments ce" in fn
    assert "ce.campaign_id = p_campaign_id" in fn
    assert "ce.deal_id = d.id" in fn
    assert "ce.enrolled_at > now() - make_interval(days => p_cooldown_days)" in fn


def test_cooldown_ignora_o_status_do_enrollment():
    """O bug era exatamente este.

    `is_already_enrolled` so conta enrollment 'active'/'paused'. Ao chegar no no
    `end` o enrollment vira 'completed' e some daquele filtro — nada impedia o
    gatilho de reinscrever o MESMO card no tick seguinte. Na esteira
    `novo_reengajamento` isso e um template a cada 3 dias, para sempre. Se o
    NOT EXISTS voltasse a filtrar por status, o loop voltaria junto.
    """
    sub = _subselect("SELECT 1 FROM campaign_enrollments ce").lower()
    assert "status" not in sub


def test_cooldown_e_opcional_para_nao_quebrar_chamador_antigo():
    """Sem `p_campaign_id` (prévia da tela, chamada manual) a RPC segue respondendo."""
    assert re.search(r"p_campaign_id IS NULL OR NOT EXISTS", _fn_code())


def test_cooldown_e_janela_e_nao_exclusao_permanente():
    """Card que sai da etapa e volta meses depois e oportunidade legitima.

    Por isso a exclusao e por JANELA (`enrolled_at > now() - cooldown`) e nao um
    `NOT EXISTS` sem recorte temporal: o que nao pode e a esteira recomecar sozinha
    na semana seguinte.
    """
    sub = _subselect("SELECT 1 FROM campaign_enrollments ce").lower()
    assert "enrolled_at" in sub and "make_interval" in sub


def test_dropa_a_assinatura_antiga_antes_de_recriar():
    """CREATE OR REPLACE com parametro novo cria OVERLOAD, nao substitui.

    Com as duas assinaturas no catalogo, a chamada de 9 argumentos casa com as duas
    e o Postgres levanta `function ... is not unique` — a esteira para de rodar em
    silencio. Mesmo motivo ja documentado no bloco 5 desta migration.
    """
    sql = _sql().lower()
    i_drop = sql.index(f"drop function if exists {FN}")
    i_create = sql.index(f"create or replace function {FN}")
    assert i_drop < i_create


# ---------------------------------------------------------------------------
# Correcao 2 — a fila de 20 nao pode travar em lead sempre pulado
# ---------------------------------------------------------------------------
def test_exclui_opt_out_no_sql():
    """Lead com opt_out era pulado so no Python — e lead pulado nunca recebe
    mensagem, entao seu `last_message_at` nunca muda e ele fica no topo da
    ordenacao PARA SEMPRE, ocupando um dos 20 slots do tick."""
    assert "l.opt_out is not true" in _fn_code().lower()


def test_exclui_deal_no_pipeline_blacklist():
    """Segundo braco de `leads/service.py::is_lead_blacklisted`: lead movido para a
    Blacklist sem o flag `opt_out`."""
    sub = _subselect("SELECT 1 FROM deals bd").lower()
    assert "8988e852-2836-4add-b023-4db4d6cd0e6e" in sub
    assert "bd.lead_id = d.lead_id" in sub


def test_exclui_conversa_finalizada():
    """Conversa que o vendedor fechou em /conversas (`followup_enabled = false`)."""
    sub = _subselect("SELECT 1 FROM conversations cf").lower()
    assert "cf.followup_enabled = false" in sub
    assert "cf.lead_id = d.lead_id" in sub


def test_exclui_numero_errado_e_blacklisted_at():
    """As duas marcas que `follow_up/scheduler.py::_lead_stop_reason` trata como
    parada definitiva. Numero errado tem card aberto, esta em silencio por definicao
    e tem ai_enabled=False: e o candidato PERFEITO da esteira, e cada toque vai para
    um desconhecido — quem mais tende a apertar 'Bloquear'."""
    fn = _fn_code().lower()
    for marca in ("wrong_number_at", "blacklisted_at"):
        assert re.search(rf"l\.metadata->>'{marca}'\)? is null", fn), marca


# ---------------------------------------------------------------------------
# Correcao 3 — fail-closed sem etapa
# ---------------------------------------------------------------------------
def test_sem_etapa_devolve_vazio():
    """`p_stage_id IS NULL` E `p_stage_key IS NULL` significava "qualquer etapa": a
    RPC varria todo card aberto de todo funil. A API das esteiras recusa ativar
    nesse estado, mas o builder de cadencias monta o mesmo gatilho e liga."""
    assert "p_stage_id IS NOT NULL OR p_stage_key IS NOT NULL" in _fn_code()


# ---------------------------------------------------------------------------
# Estrutura do arquivo — a migration roda como UMA query so
# ---------------------------------------------------------------------------
def test_dolar_dolar_e_par():
    """Numero impar de `$$` deixa o resto do arquivo dentro de um literal aberto."""
    assert _sql().count("$$") % 2 == 0


def test_parametros_com_default_ficam_no_fim():
    """Postgres recusa a funcao inteira se um parametro SEM default vier depois de um
    COM default — e o erro aborta o arquivo, nao so o bloco."""
    fn = _fn_code()
    assinatura = fn[fn.index("(") + 1: fn.index(")")]
    viu_default = False
    for p in (x.strip() for x in assinatura.split(",")):
        tem_default = "DEFAULT" in p.upper()
        assert not (viu_default and not tem_default), f"'{p}' sem DEFAULT depois de um com DEFAULT"
        viu_default = viu_default or tem_default
