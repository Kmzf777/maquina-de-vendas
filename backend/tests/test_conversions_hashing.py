# backend/tests/test_conversions_hashing.py
import hashlib

from app.conversions.hashing import (
    google_email_hash, google_phone_hash, meta_email_hash, meta_phone_hash, normalize_br_phone,
)


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def test_normalize_br_phone_aceita_mascara_e_ddi():
    assert normalize_br_phone("(34) 99200-9777") == "5534992009777"
    assert normalize_br_phone("+55 34 99200-9777") == "5534992009777"
    assert normalize_br_phone("5534992009777") == "5534992009777"
    assert normalize_br_phone("034992009777") == "5534992009777"  # zero de tronco


def test_normalize_br_phone_vazio_ou_curto_vira_none():
    assert normalize_br_phone(None) is None
    assert normalize_br_phone("") is None
    assert normalize_br_phone("123") is None


def test_meta_phone_so_digitos_com_ddi():
    assert meta_phone_hash("(34) 99200-9777") == _h("5534992009777")


def test_google_phone_e164_com_mais():
    assert google_phone_hash("(34) 99200-9777") == _h("+5534992009777")


def test_meta_email_trim_lower():
    assert meta_email_hash("  Joao@Exemplo.COM ") == _h("joao@exemplo.com")


def test_google_email_gmail_sem_pontos():
    assert google_email_hash("Jo.Ao@gmail.com") == _h("joao@gmail.com")
    assert google_email_hash("jo.ao@empresa.com") == _h("jo.ao@empresa.com")


def test_email_invalido_vira_none():
    assert meta_email_hash("sem-arroba") is None
    assert google_email_hash(None) is None


def test_celular_sem_o_nono_digito_ganha_o_9():
    """wa_id do WhatsApp costuma vir sem o 9 (55 + DDD + 8 dígitos); o celular de verdade tem.
    Sem o 9 o hash não casa com o telefone da conta na plataforma."""
    assert normalize_br_phone("553492009777") == "5534992009777"
    assert normalize_br_phone("3482009777") == "5534982009777"
    assert normalize_br_phone("+55 34 6200-9777") == "5534962009777"
    assert meta_phone_hash("553492009777") == _h("5534992009777")
    assert google_phone_hash("553492009777") == _h("+5534992009777")


def test_fixo_com_8_digitos_nao_ganha_o_9():
    assert normalize_br_phone("553432009777") == "553432009777"
    assert normalize_br_phone("(34) 3200-9777") == "553432009777"
    assert normalize_br_phone("553452009777") == "553452009777"
