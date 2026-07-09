"""Guardas de escuta ativa e micro-humanidade (auditoria outbound 2026-07-08).

Casos reais que motivaram cada guarda:
- detect_autoresponder: Letícia (5562998354407) era o bot da gelateria Duo Gelatto —
  o fallback de LLM-down encaminhou um autoresponder ao João (dois robôs conversando).
- normalize_orthography: a mesma bolha da Nayara saiu com "é" acentuado e
  "torrefacao"/"xicara" sem acento — humano tem UMA digitação.
- is_repeated_question: Luciano recebeu a MESMA pergunta de qualificação 3x
  ("prazer do dia a dia ou projeto?") depois de já tê-la respondido.
- find_verbatim_prompt_echo: o "exemplo vencedor" do prompt foi copiado byte a byte
  para 5 leads distintos no disparo de 08/07.
"""
import random

from app.agent.adherence import (
    detect_autoresponder,
    find_verbatim_prompt_echo,
    is_repeated_question,
    normalize_orthography,
)

GELATO_AUTOREPLY = (
    "‎Duo Gelatto Nova Era agradece seu contato. \n\n"
    "Para entrega acesse os links abaixo:\n\n"
    "*Ifood: Duo Gelatto Açai - Nova Era*\n"
    "https://www.ifood.com.br/delivery/aparecida-de-goiania-go/duo-gelatto-acai\n"
    "*Milk-shake:* https://www.ifood.com.br/delivery/aparecida-de-goiania-go/duo-milk-shakes\n"
    "Para outros assuntos, continue por aqui."
)


# ---------------------------------------------------------------------------
# detect_autoresponder
# ---------------------------------------------------------------------------

def test_autoresponder_gelato_real_case():
    assert detect_autoresponder(GELATO_AUTOREPLY) is True


def test_autoresponder_classic_phrase_pair():
    assert detect_autoresponder(
        "Agradecemos seu contato, retornaremos em breve."
    ) is True


def test_autoresponder_menu_numerado():
    text = (
        "Bem-vindo ao atendimento!\n"
        "1 - Cardápio\n"
        "2 - Horário de funcionamento\n"
        "3 - Falar com atendente"
    )
    assert detect_autoresponder(text) is True


def test_autoresponder_nao_dispara_em_resposta_humana_curta():
    assert detect_autoresponder("Sim") is False
    assert detect_autoresponder("Não") is False


def test_autoresponder_nao_dispara_em_lead_humano_com_um_link():
    assert detect_autoresponder(
        "tenho uma cafeteria, olha meu insta https://instagram.com/minhacafeteria"
    ) is False


def test_autoresponder_nao_dispara_em_pergunta_sobre_cardapio():
    assert detect_autoresponder("vocês têm cardápio de cafés? me manda") is False


# ---------------------------------------------------------------------------
# normalize_orthography
# ---------------------------------------------------------------------------

def test_normaliza_bolha_real_da_nayara():
    # Bolha real de 08/07: "é" acentuado convivendo com "torrefacao"/"xicara" crus.
    entrada = (
        "esse contato era so pra confirmar que falo contigo por aqui, a gente é a "
        "torrefacao de cafe especial da Serra da Canastra, da fazenda pra xicara"
    )
    esperado = (
        "esse contato era só pra confirmar que falo contigo por aqui, a gente é a "
        "torrefação de café especial da Serra da Canastra, da fazenda pra xícara"
    )
    assert normalize_orthography(entrada) == esperado


def test_normaliza_palavras_comuns():
    assert normalize_orthography("voce ja pensou em cafe especial") == (
        "você já pensou em café especial"
    )
    assert normalize_orthography("ta bom, ne") == "tá bom, né"


def test_preserva_urls():
    entrada = "é só acessar www.loja.cafecanastra.com e conferir"
    assert normalize_orthography(entrada) == entrada
    entrada2 = "acessa https://cafecanastra.com/cafe agora"
    assert normalize_orthography(entrada2) == entrada2


def test_idempotente_em_texto_ja_acentuado():
    texto = "não força nada, você já sabe que o café é especial"
    assert normalize_orthography(texto) == texto


def test_preserva_capital_inicial():
    assert normalize_orthography("Voce vai gostar") == "Você vai gostar"


def test_nao_toca_em_palavras_ambiguas():
    # "e" (conjunção) e "esta" (pronome) nunca entram no mapa.
    texto = "pega esta caixa e me fala"
    assert normalize_orthography(texto) == texto


# ---------------------------------------------------------------------------
# is_repeated_question
# ---------------------------------------------------------------------------

_PERGUNTA_LUCIANO = (
    "a gente e a torrefacao de cafe especial da Serra da Canastra e antes de qualquer "
    "coisa gosta de entender quem ta do outro lado, cafe pra voce e mais um prazer do "
    "dia a dia ou tem a ver com algum projeto seu?"
)


def test_repete_pergunta_verbatim():
    candidato = "ah, entendi\n\ne me conta, o cafe pra voce e mais um prazer do dia a dia ou tem a ver com algum projeto seu?"
    assert is_repeated_question(candidato, [_PERGUNTA_LUCIANO]) is not None


def test_repete_pergunta_com_acentos_diferentes():
    prior = (
        "café pra você é mais um prazer do dia a dia ou tem a ver com algum projeto seu?"
    )
    candidato = "cafe pra voce e mais um prazer do dia a dia ou tem a ver com algum projeto seu?"
    assert is_repeated_question(candidato, [prior]) is not None


def test_pergunta_nova_nao_flagra():
    candidato = "e hoje o café na sua casa, continua especial?"
    assert is_repeated_question(candidato, [_PERGUNTA_LUCIANO]) is None


def test_pergunta_curta_de_cortesia_nao_flagra():
    # Saudações/checagens curtas ("tudo bem?") não contam como repetição de funil.
    assert is_repeated_question("tudo bem?", ["tudo bem?"]) is None


def test_sem_pergunta_no_candidato():
    assert is_repeated_question("boa, vou te mandar o resumo", [_PERGUNTA_LUCIANO]) is None


# ---------------------------------------------------------------------------
# find_verbatim_prompt_echo
# ---------------------------------------------------------------------------

def test_echo_de_semente_do_prompt():
    seeds = ("seu contato tava aqui com a gente e imagino que uma hora voce chegou a se interessar",)
    texto = (
        "que bom, Wolmy\n\nseu contato tava aqui com a gente e imagino que uma hora "
        "voce chegou a se interessar pela Canastra, entao quis puxar esse papo com voce"
    )
    assert find_verbatim_prompt_echo(texto, seeds) is not None


def test_texto_original_nao_flagra_echo():
    seeds = ("seu contato tava aqui com a gente e imagino que uma hora voce chegou a se interessar",)
    texto = "opa, que bom te ler por aqui\n\nvi seu número na nossa base e resolvi puxar assunto"
    assert find_verbatim_prompt_echo(texto, seeds) is None
