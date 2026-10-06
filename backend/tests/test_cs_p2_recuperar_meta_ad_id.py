"""scripts/trafego/recuperar_meta_ad_id.py — casamento lead ↔ referral CTWA (P2.5).

Caso real: Serginho Sinop entrou em 20/08/2026, um dia antes de o webhook gravar o anúncio.
O referral dele continua em meta_webhook_logs, com o número SEM o 9º dígito."""
import csv
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "trafego" / "recuperar_meta_ad_id.py"
_spec = importlib.util.spec_from_file_location("recuperar_meta_ad_id", _SCRIPT)
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

CLID = ("Afhy6J1tOh0F3ozUBbh5oQqoxKBS-G0WeKHOoN0cVAHXVy6M_TvbvyschdfLlIraaREmSnuz_Mb5c1Pk"
        "r-wKL2XK6lA6CrpHLSGO0zL21K3u-dtmIMYunVFstnX9rdds0rQdDdNRNw")
AD = "120250785520090163"
SERGINHO = {"id": "7c8638ee-0f89-4050-ba5a-de025d93b2da", "name": "Serginho Sinop",
            "phone": "5566997222209", "created_at": "2026-08-20 16:33:47.213672+00", "ctwa_clid": CLID}
REF = {"received_at": "2026-08-20 16:33:47.155459+00", "from_number": "556697222209",
       "ctwa_clid": CLID, "source_id": AD, "source_type": "ad"}


def _ref(**kw):
    return {**REF, **kw}


def test_serginho_casa_pelo_ctwa_clid():
    [r] = rec.casar([SERGINHO], [REF])
    assert (r["status"], r["metodo"], r["meta_ad_id"]) == ("recuperado", "ctwa_clid", AD)


def test_serginho_casa_pelo_telefone_sem_o_nono_digito():
    [r] = rec.casar([SERGINHO], [_ref(ctwa_clid=None)])
    assert (r["status"], r["metodo"], r["meta_ad_id"]) == ("recuperado", "telefone", AD)


def test_fallback_pega_o_referral_mais_proximo_antes_da_entrada():
    refs = [_ref(ctwa_clid=None, received_at="2026-08-20 14:33:00+00", source_id="111"),
            _ref(ctwa_clid=None, received_at="2026-08-20 16:03:00+00", source_id="222"),
            _ref(ctwa_clid=None, received_at="2026-08-20 16:43:00+00", source_id="333")]  # depois
    [r] = rec.casar([SERGINHO], refs)
    assert r["meta_ad_id"] == "222"


def test_fallback_nao_passa_de_24_horas():
    [r] = rec.casar([SERGINHO], [_ref(ctwa_clid=None, received_at="2026-08-19 16:00:00+00")])
    assert r["status"] == "sem_referral" and r["meta_ad_id"] == ""


def test_mesmo_clid_com_dois_anuncios_e_ambiguo():
    [r] = rec.casar([SERGINHO], [REF, _ref(source_id="999")])
    assert r["status"] == "ambiguo"


def test_referral_que_nao_e_anuncio_e_ignorado():
    [r] = rec.casar([SERGINHO], [_ref(source_type="post")])
    assert r["status"] == "sem_referral"


@pytest.mark.parametrize("tipo", [None, "", "  "])
def test_referral_sem_source_type_nao_recupera_e_conta_a_parte(tipo):
    """A spec só aceita referral de anúncio: sem source_type não dá para afirmar que é anúncio."""
    [r] = rec.casar([SERGINHO], [_ref(source_type=tipo)])
    assert r["status"] == "sem_source_type"
    assert r["metodo"] == "ctwa_clid" and r["meta_ad_id"] == AD  # para a revisão humana no CSV
    sql, n = rec.sql_de_aplicacao([r])
    assert (sql, n) == ("", 0)


def test_referral_sem_source_type_pelo_telefone_tambem_conta_a_parte():
    [r] = rec.casar([SERGINHO], [_ref(source_type=None, ctwa_clid=None)])
    assert (r["status"], r["metodo"]) == ("sem_source_type", "telefone")


def test_referral_de_anuncio_vence_o_sem_source_type():
    [r] = rec.casar([SERGINHO], [REF, _ref(source_type=None, source_id="999")])
    assert (r["status"], r["meta_ad_id"]) == ("recuperado", AD)


def test_chaves_telefone_com_e_sem_o_nove():
    assert rec.chaves_telefone("5566997222209") == {"5566997222209", "556697222209"}
    assert rec.chaves_telefone("556697222209") == {"556697222209", "5566997222209"}
    assert rec.chaves_telefone("+55 (66) 9 9722-2209") == {"5566997222209", "556697222209"}
    assert rec.chaves_telefone(None) == frozenset()


def test_sql_de_aplicacao_so_preenche_nulos_e_rejeita_lixo():
    ok = {"status": "recuperado", "lead_id": SERGINHO["id"], "meta_ad_id": AD}
    lixo = {"status": "recuperado", "lead_id": SERGINHO["id"], "meta_ad_id": "1'; drop table leads; --"}
    sql, n = rec.sql_de_aplicacao([ok, lixo, {"status": "ambiguo", "lead_id": "x", "meta_ad_id": "1|2"}])
    assert n == 1
    assert sql == (f"update public.leads set meta_ad_id = '{AD}' "
                   f"where id = '{SERGINHO['id']}' and meta_ad_id is null;\n")


def _executar_falso(sql):
    if "to_regclass" in sql:
        return [{"tem": "f"}]
    if "from public.leads" in sql:
        return [SERGINHO]
    if "meta_webhook_logs" in sql:
        return [REF]
    if "meta_ad_campaigns" in sql:
        return [{"ad_id": AD, "campaign_name": "Cafeterias | Vídeo"}]
    raise AssertionError(sql)


def test_main_dry_run_escreve_csv_e_nao_grava(tmp_path, capsys):
    def _nao_pode(sql):
        pytest.fail("dry-run não pode gravar")
    assert rec.main(["--saida", str(tmp_path)], executar=_executar_falso, aplicar=_nao_pode) == 0
    [arq] = list(tmp_path.glob("recuperar_meta_ad_id_*.csv"))
    [linha] = list(csv.DictReader(arq.open(encoding="utf-8")))
    assert (linha["status"], linha["meta_ad_id"], linha["campanha"]) == ("recuperado", AD, "Cafeterias | Vídeo")
    saida = capsys.readouterr().out
    assert "fonte: log" in saida and "recuperado: 1" in saida
    assert "sem_source_type: 0" in saida


def test_main_aplicar_manda_os_updates(tmp_path):
    recebido = []
    def _aplicar(sql):
        recebido.append(sql)
        return "UPDATE 1\n"
    assert rec.main(["--saida", str(tmp_path), "--aplicar"], executar=_executar_falso, aplicar=_aplicar) == 0
    assert "and meta_ad_id is null" in recebido[0]
