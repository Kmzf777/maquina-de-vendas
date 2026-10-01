"""O follow-up para de falar por cima do fluxo de botões.

O motor decidia por `ai_enabled` e canal humano, e não sabia que fluxos de botões
existem. Um lead que para no meio da árvore tem `ai_enabled=True` — nada o
silenciou — então o `ai_reengage` disparava uma mensagem de LLM por cima de uma
conversa de botões, e a resposta dele caía no motor de botões como texto livre.
"""
import pytest

from app.follow_up import scheduler as S

FLUXO = "valeria_botoes_v1"
CONV_BOTOES = {"id": "c1", "agent_profile_id": "p-botoes"}
CONV_LLM = {"id": "c2", "agent_profile_id": "p-llm"}
CANAL = {"id": "ch1", "mode": "ai", "agent_profiles": {"kind": "llm", "flow_id": None}}
LEAD = {"id": "l1", "ai_enabled": True, "metadata": {}}


@pytest.fixture(autouse=True)
def _sem_blacklist(monkeypatch):
    monkeypatch.setattr(S, "is_lead_blacklisted", lambda _id: False)


@pytest.fixture
def botoes_ligado(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    from app.button_flow import runner as R
    monkeypatch.setattr(R, "get_agent_profile", lambda pid: (
        {"kind": "button_flow", "flow_id": FLUXO} if pid == "p-botoes"
        else {"kind": "llm", "flow_id": None}))
    R.limpar_cache_de_perfis()


def test_conversa_de_botoes_vira_motivo_de_parada(botoes_ligado):
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) == "fluxo_de_botoes"


def test_conversa_de_llm_no_mesmo_canal_nao_para(botoes_ligado):
    """A conversa vence o canal: lead que o disparo apontou para a LLM segue recebendo."""
    assert S._lead_stop_reason(LEAD, CONV_LLM, CANAL) is None


def test_sem_conversa_nem_canal_o_motivo_nao_dispara(botoes_ligado):
    """Chamador antigo: comportamento byte-idêntico ao de hoje."""
    assert S._lead_stop_reason(LEAD) is None


def test_com_o_fluxo_desligado_nao_dispara_e_nao_consulta_o_banco(monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    from app.button_flow import runner as R
    def explode(_pid):
        raise AssertionError("consultou agent_profiles com todos os fluxos desligados")
    monkeypatch.setattr(R, "get_agent_profile", explode)
    R.limpar_cache_de_perfis()
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) is None


def test_erro_ao_resolver_o_perfil_e_fail_open(monkeypatch, botoes_ligado):
    from app.button_flow import runner as R
    def explode(_pid):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(R, "get_agent_profile", explode)
    R.limpar_cache_de_perfis()
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) is None


def test_optout_vence_fluxo_de_botoes(botoes_ligado):
    lead = {**LEAD, "opt_out": True}
    assert S._lead_stop_reason(lead, CONV_BOTOES, CANAL) == "opt_out"


def test_fluxo_de_botoes_vence_ai_disabled(botoes_ligado):
    """`ai_disabled` é consequência; `fluxo_de_botoes` é a causa útil no analytics."""
    lead = {**LEAD, "ai_enabled": False}
    assert S._lead_stop_reason(lead, CONV_BOTOES, CANAL) == "fluxo_de_botoes"


def test_blacklist_vence_fluxo_de_botoes(monkeypatch, botoes_ligado):
    """A ORDEM contra a blacklist, e ela não é estética.

    `fluxo_de_botoes` tem isenção (`handoff_rescue`, `lp_welcome`) e `blacklisted`
    não tem nenhuma — é exatamente o argumento que o comentário de
    `is_lead_blacklisted` registra sobre `ai_disabled`. Se o fluxo de botões viesse
    ANTES da blacklist, o resgate isento voltaria a mandar template sobre um lead
    que está na Blacklist, reabrindo o buraco que aquele comentário fechou.
    """
    monkeypatch.setattr(S, "is_lead_blacklisted", lambda _id: True)
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) == "blacklisted"


@pytest.mark.parametrize("job_type", ["standard", "ai_reengage", "ai_scheduled_return"])
def test_os_tipos_que_falam_com_o_lead_por_llm_sao_bloqueados(job_type):
    assert S._stop_reason_applies("fluxo_de_botoes", job_type) is True


def test_handoff_rescue_e_isento():
    """Notifica o VENDEDOR por template, não o lead. É o anteparo de quem foi
    transbordado e ninguém pegou (caso Wilson Demuth, >21h no vácuo)."""
    assert S._stop_reason_applies("fluxo_de_botoes", "handoff_rescue") is False


def test_lp_welcome_e_isento():
    """Lead de LP ainda NÃO mandou mensagem — não há estado de fluxo. Bloquear
    faria nenhum lead de landing page ser recebido."""
    assert S._stop_reason_applies("fluxo_de_botoes", "lp_welcome") is False


@pytest.mark.parametrize("job_type", ["joao_reposicao", "joao_touch", "joao_em_atencao"])
def test_cadencia_do_joao_e_isenta(job_type):
    """Toque do VENDEDOR: template aprovado, zero LLM, saindo do número do João.

    O nome é verificado no próprio predicado (`_is_joao_job_type`, que casa por
    PREFIXO `joao_` e pela lista nomeada `JOAO_JOB_TYPES`) e não assumido — um tipo
    que não casasse ali cairia no caminho `standard` e o teste passaria mentindo.
    """
    assert S._is_joao_job_type(job_type) is True
    assert S._stop_reason_applies("fluxo_de_botoes", job_type) is False


def test_as_isencoes_de_ai_disabled_nao_mudaram():
    """Regressão: a tabela existente continua valendo."""
    assert S._stop_reason_applies("ai_disabled", "handoff_rescue") is False
    assert S._stop_reason_applies("ai_disabled", "standard") is True
    assert S._stop_reason_applies("opt_out", "handoff_rescue") is True


def test_o_select_do_job_traz_o_perfil():
    """Sem estas colunas o motivo nunca dispara, e os testes acima passariam mentindo."""
    import inspect
    from app.follow_up import service
    fonte = inspect.getsource(service.get_due_followups)
    assert "agent_profile_id" in fonte
    assert "agent_profiles(" in fonte
