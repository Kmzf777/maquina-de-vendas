from scripts.conversoes import simular_ativacao as sa


def test_cli_imprime_tabela_e_repassa_a_janela(monkeypatch, capsys):
    vistos = {}

    def _sweep(now=None, backfill_days=None):
        vistos["sweep"] = backfill_days
        return {"novos": {("google", "qualified", "31-90d"): 5}, "ja_na_fila": 2, "backfill_days": backfill_days or 90}

    def _sender(now=None, platforms=("meta", "google"), google_stages=None, backfill_days=None):
        vistos["sender"] = backfill_days
        return {"enviaria": {("meta", "qualified", "0-7d"): 1}, "fora_da_janela": 0, "backfill_days": backfill_days or 90}

    monkeypatch.setattr(sa, "simulate_sweep", _sweep)
    monkeypatch.setattr(sa, "simulate_sender", _sender)
    assert sa.main(["--dias", "30"]) == 0
    out = capsys.readouterr().out
    assert vistos == {"sweep": 30, "sender": 30}
    assert "google" in out and "qualified" in out and "5" in out and "SIMULA" in out.upper()
