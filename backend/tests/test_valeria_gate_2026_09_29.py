"""O gate passa a ser POR FLUXO, e os dois fluxos são independentes.

Uma env var fechava os dois: ligar a ValerIA de botões armaria a Recuperação junto
— que está desligada, roda no número pessoal de um vendedor, e tem 3 bloqueantes.
"""
from app.button_flow import config, runner

FLUXO_VALERIA = "valeria_botoes_v1"
FLUXO_RECUP = "recuperacao_v1"


def test_ambos_desligados_por_default(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert config.enabled(FLUXO_RECUP) is False
    assert config.enabled(FLUXO_VALERIA) is False


def test_ligar_a_valeria_nao_liga_a_recuperacao(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    assert config.enabled(FLUXO_VALERIA) is True
    assert config.enabled(FLUXO_RECUP) is False


def test_ligar_a_recuperacao_nao_liga_a_valeria(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert config.enabled(FLUXO_RECUP) is True
    assert config.enabled(FLUXO_VALERIA) is False


def test_fluxo_desconhecido_e_desligado(monkeypatch):
    """flow_id gravado à mão num perfil não pode virar exceção no inbound."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    assert config.enabled("fluxo_que_nao_existe") is False


# ── O resolvedor de fluxo da conversa ─────────────────────────────────────
def test_perfil_sem_flow_id_e_recuperacao(monkeypatch):
    """Compatibilidade: o perfil que já existe em produção não tem a coluna."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) == FLUXO_RECUP


def test_perfil_com_flow_id_da_valeria(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) == FLUXO_VALERIA


def test_perfil_llm_nao_tem_fluxo(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "llm", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_fluxo_com_a_chave_desligada_e_none(monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_conversa_vence_o_canal(monkeypatch):
    """runner.py:96 — os canais da ValerIA e do João apontam para o MESMO perfil."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    canal = {"agent_profiles": {"kind": "llm", "flow_id": None}}
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, canal) == FLUXO_VALERIA


def test_cai_no_canal_quando_a_conversa_nao_tem_perfil(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    runner.limpar_cache_de_perfis()
    canal = {"agent_profiles": {"kind": "button_flow", "flow_id": None}}
    assert runner.fluxo_da_conversa({}, canal) == FLUXO_RECUP


def test_erro_ao_resolver_e_fail_open(monkeypatch):
    """Fail-CLOSED sequestraria conversa humana num erro de leitura."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    def explode(_id):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(runner, "get_agent_profile", explode)
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_is_button_flow_conversation_segue_funcionando(monkeypatch):
    """Regressão: o processor da recuperação chama esta função hoje."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.is_button_flow_conversation({"agent_profile_id": "p1"}, {}) is True


def test_is_button_flow_conversation_e_falsa_para_a_valeria(monkeypatch):
    """A função antiga responde só pela recuperação; a ValerIA tem runner próprio."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    assert runner.is_button_flow_conversation({"agent_profile_id": "p1"}, {}) is False
