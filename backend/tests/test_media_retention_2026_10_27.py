"""Cartão da1f51a7: rotação de mídia — só mensagem velha, só prefixo permitido, dry-run por padrão."""
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase

import pytest

from app.media_retention import service as s

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)
BASE = "https://supabase.x/storage/v1/object/public/"


def msg(i, dias, url, md=None):
    return {"id": f"m{i}", "media_url": url, "metadata": md,
            "created_at": (NOW - timedelta(days=dias)).isoformat()}


class FakeSB:
    """Implementa só o que service.py usa — a interface está em service._Store."""
    def __init__(self, msgs):
        self.msgs = msgs
        self.removed: list[tuple[str, list[str]]] = []
        self.updated: dict[str, dict] = {}
        self.logs: list[dict] = []
        self.fail_remove = False


@pytest.fixture
def store_factory():
    def make(msgs, origin=None, filtro_banco=True):
        """filtro_banco=False simula um banco que devolve tudo, para testar a 2ª barreira (Python)."""
        fake = FakeSB(msgs)

        class Store(s._Store):
            def __init__(self):
                self.origin = origin

            def candidatas(self, cutoff, after, limit):
                # Espelha o filtro do banco: só prefixos permitidos e só o host do projeto.
                padroes = (s._padroes_like(self.origin) if filtro_banco
                           else ["*/storage/v1/object/public/*"])
                rows = [m for m in fake.msgs
                        if m["created_at"] < cutoff and (after is None or m["created_at"] > after)
                        and any(fnmatchcase(m["media_url"] or "", p) for p in padroes)
                        and not ((m["metadata"] or {}).get("media_expired"))]
                return sorted(rows, key=lambda m: m["created_at"])[:limit]

            def urls_em_uso_recente(self, urls, cutoff):
                return {m["media_url"] for m in fake.msgs
                        if m["media_url"] in urls and m["created_at"] >= cutoff}

            def tamanho(self, url):
                # Depois de apagado, o HEAD não acharia mais o arquivo: mede antes.
                assert not any(url.endswith("/" + p) for _, ps in fake.removed for p in ps)
                return 1000

            def remover(self, bucket, paths):
                if fake.fail_remove:
                    raise RuntimeError("storage down")
                fake.removed.append((bucket, list(paths)))

            def marcar_expirada(self, row):
                md = dict(row["metadata"] or {})
                md["media_expired"] = True
                row["metadata"] = md
                fake.updated[row["id"]] = md

            def registrar(self, linhas):
                fake.logs.extend(linhas)

        return Store(), fake
    return make


def test_parse_storage_url():
    assert s.parse_storage_url(BASE + "whatsapp-media/outbound/1_a%20b.pdf") == ("whatsapp-media", "outbound/1_a b.pdf")
    assert s.parse_storage_url(BASE + "audio/123.ogg") == ("audio", "123.ogg")
    assert s.parse_storage_url(BASE + "audio/123.ogg?t=1") == ("audio", "123.ogg")
    assert s.parse_storage_url("12345") is None
    assert s.parse_storage_url(None) is None


def test_prefixos_permitidos():
    assert s.is_allowed("audio", "123.ogg")
    assert s.is_allowed("whatsapp-media", "inbound/1.jpg")
    assert s.is_allowed("whatsapp-media", "outbound/1.jpg")
    assert not s.is_allowed("whatsapp-media", "valeria-botoes/cafe.png")
    assert not s.is_allowed("whatsapp-media", "1.jpg")
    assert not s.is_allowed("outro", "inbound/1.jpg")


def test_caminho_estranho_nunca_e_permitido():
    assert not s.is_allowed("whatsapp-media", "inbound/../valeria-botoes/cafe.png")
    assert not s.is_allowed("audio", "../whatsapp-media/valeria-botoes/cafe.png")
    assert not s.is_allowed("whatsapp-media", "inbound//x.jpg")
    assert not s.is_allowed("audio", "/x.ogg")
    assert not s.is_allowed("whatsapp-media", "inbound/")
    assert not s.is_allowed("audio", "a\\..\\b.ogg")


def test_dry_run_e_padrao(monkeypatch):
    monkeypatch.delenv("MEDIA_RETENTION_DRY_RUN", raising=False)
    assert s.dry_run_enabled() is True
    monkeypatch.setenv("MEDIA_RETENTION_DRY_RUN", "")
    assert s.dry_run_enabled() is True
    monkeypatch.setenv("MEDIA_RETENTION_DRY_RUN", "talvez")
    assert s.dry_run_enabled() is True
    monkeypatch.setenv("MEDIA_RETENTION_DRY_RUN", "false")
    assert s.dry_run_enabled() is False


def test_dias_configuravel(monkeypatch):
    monkeypatch.delenv("MEDIA_RETENTION_DAYS", raising=False)
    assert s.retention_days() == 180
    monkeypatch.setenv("MEDIA_RETENTION_DAYS", "90")
    assert s.retention_days() == 90
    monkeypatch.setenv("MEDIA_RETENTION_DAYS", "abc")
    assert s.retention_days() == 180


def test_apaga_so_o_velho_e_permitido(store_factory):
    store, fake = store_factory([
        msg(1, 200, BASE + "whatsapp-media/inbound/a.jpg"),
        msg(2, 200, BASE + "audio/b.ogg"),
        msg(3, 100, BASE + "whatsapp-media/inbound/novo.jpg"),          # novo demais
        msg(4, 200, BASE + "whatsapp-media/valeria-botoes/cafe.png"),   # protegido
        msg(5, 200, "1234567890"),                                       # media_id da Meta
    ], filtro_banco=False)
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    removidos = {(b, p) for b, ps in fake.removed for p in ps}
    assert removidos == {("whatsapp-media", "inbound/a.jpg"), ("audio", "b.ogg")}
    assert set(fake.updated) == {"m1", "m2"}
    assert r["deleted"] == 2 and r["skipped"] == 1 and r["bytes"] == 2000
    assert all(l["dry_run"] is False and l["apagado_em"] for l in fake.logs)
    assert all(l["size_bytes"] == 1000 for l in fake.logs)


def test_pula_url_usada_por_mensagem_recente(store_factory):
    url = BASE + "whatsapp-media/outbound/foto.jpg"
    store, fake = store_factory([msg(1, 200, url), msg(2, 10, url)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert fake.removed == [] and r["skipped"] == 1 and fake.updated == {}


def test_dry_run_nao_apaga_nem_marca(store_factory):
    store, fake = store_factory([
        msg(1, 200, BASE + "audio/b.ogg"),
        msg(2, 200, BASE + "whatsapp-media/valeria-botoes/cafe.png"),
    ])
    r = s.run_retention(store=store, now=NOW, dry_run=True, days=180, batch=500)
    assert fake.removed == [] and fake.updated == {}
    assert r["candidates"] == 1 and r["deleted"] == 0 and r["bytes"] == 1000
    assert len(fake.logs) == 1
    assert fake.logs[0]["dry_run"] is True and fake.logs[0]["apagado_em"] is None
    assert fake.logs[0]["path"] == "b.ogg"


def test_dry_run_e_o_padrao_do_run(store_factory, monkeypatch):
    monkeypatch.delenv("MEDIA_RETENTION_DRY_RUN", raising=False)
    store, fake = store_factory([msg(1, 200, BASE + "audio/b.ogg")])
    r = s.run_retention(store=store, now=NOW, days=180, batch=500)
    assert r["dry_run"] is True and fake.removed == [] and fake.updated == {}


def test_falha_no_remove_nao_marca(store_factory):
    store, fake = store_factory([msg(1, 200, BASE + "audio/b.ogg")])
    fake.fail_remove = True
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert fake.updated == {} and r["errors"] == 1 and r["deleted"] == 0
    assert fake.logs == []


def test_lotes(store_factory):
    store, fake = store_factory([msg(i, 200 + i, BASE + f"audio/{i}.ogg") for i in range(7)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=3)
    assert r["deleted"] == 7
    assert all(len(ps) <= 3 for _, ps in fake.removed)


def test_mesma_url_em_duas_mensagens_velhas(store_factory):
    url = BASE + "audio/x.ogg"
    store, fake = store_factory([msg(1, 200, url), msg(2, 190, url)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert r["deleted"] == 1 and set(fake.updated) == {"m1", "m2"}


def test_url_de_outro_projeto_supabase_e_pulada(store_factory):
    store, fake = store_factory([
        msg(1, 200, "https://outro.supabase.co/storage/v1/object/public/audio/b.ogg"),
        msg(2, 200, BASE + "audio/c.ogg"),
    ], origin="https://supabase.x/", filtro_banco=False)
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert fake.removed == [("audio", ["c.ogg"])] and r["skipped"] == 1


def test_worker_registra_media_retention():
    from app.worker.main import TASK_SPECS
    specs = {name: (kind, secs) for name, kind, _fn, secs in TASK_SPECS}
    assert specs["media-retention"] == ("periodic", 86400)


def test_tick_do_worker_chama_run_retention(monkeypatch):
    import asyncio
    from app.worker import main as wm
    chamadas = []
    monkeypatch.setattr(s, "run_retention", lambda: chamadas.append(1) or {})
    asyncio.run(wm._media_retention_tick())
    assert chamadas == [1]


def test_store_real_usa_a_api_do_supabase_py():
    """Confere as chamadas do _Store de verdade contra o supabase-py (sem rede)."""
    from unittest.mock import MagicMock
    sb = MagicMock()
    st = s._Store(sb)
    st.candidatas("2026-06-01", "2026-01-01", 10)
    q = sb.table.return_value.select.return_value
    q.lt.assert_called_with("created_at", "2026-06-01")
    q.lt.return_value.or_.assert_called_with(
        'media_url.like."*/storage/v1/object/public/audio/*",'
        'media_url.like."*/storage/v1/object/public/whatsapp-media/inbound/*",'
        'media_url.like."*/storage/v1/object/public/whatsapp-media/outbound/*"')
    q.lt.return_value.or_.return_value.is_.assert_called_with("metadata->media_expired", "null")
    st.remover("audio", ["a.ogg"])
    sb.storage.from_.assert_called_with("audio")
    sb.storage.from_.return_value.remove.assert_called_with(["a.ogg"])
    st.registrar([{"bucket": "audio", "path": "a.ogg"}])
    sb.table.return_value.upsert.assert_called_with(
        [{"bucket": "audio", "path": "a.ogg"}], on_conflict="bucket,path")
    st.marcar_expirada({"id": "m1", "metadata": {"x": 1}})
    sb.table.return_value.update.assert_called_with({"metadata": {"x": 1, "media_expired": True}})


def test_urls_em_uso_consulta_em_pedacos():
    from unittest.mock import MagicMock
    sb = MagicMock()
    q = sb.table.return_value.select.return_value
    q.in_.return_value.gte.return_value.execute.return_value.data = [{"media_url": "u1"}]
    st = s._Store(sb)
    assert st.urls_em_uso_recente([f"u{i}" for i in range(100)], "2026-06-01") == {"u1"}
    assert q.in_.call_count == 3
    assert all(len(c.args[1]) <= 40 for c in q.in_.call_args_list)
    assert st.urls_em_uso_recente([], "x") == set()


def test_candidatas_filtra_no_banco_so_prefixo_permitido_do_proprio_host():
    """O filtro vai para o banco: valeria-botoes/ e host morto nunca voltam na consulta."""
    from unittest.mock import MagicMock
    sb = MagicMock()
    st = s._Store(sb)
    st.origin = "https://proj.supabase.co/"
    st.candidatas("2026-06-01", None, 10)
    q = sb.table.return_value.select.return_value
    q.lt.return_value.or_.assert_called_once_with(
        'media_url.like."https://proj.supabase.co/storage/v1/object/public/audio/*",'
        'media_url.like."https://proj.supabase.co/storage/v1/object/public/whatsapp-media/inbound/*",'
        'media_url.like."https://proj.supabase.co/storage/v1/object/public/whatsapp-media/outbound/*"')
    q.lt.return_value.like.assert_not_called()


def test_store_real_pega_origin_do_settings_sem_barra(monkeypatch):
    from unittest.mock import MagicMock
    from app.config import settings
    import app.db.supabase as dbs
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co/")
    monkeypatch.setattr(dbs, "get_supabase", lambda: MagicMock())
    assert s._Store().origin == "https://proj.supabase.co"


def test_30_mil_linhas_puladas_nao_travam_a_rotacao(store_factory):
    origin = "https://supabase.x"
    puladas = []
    for i in range(30000):
        url = (BASE + f"whatsapp-media/valeria-botoes/{i}.jpg" if i % 2
               else f"https://tshmvxxxyxgctrdkqvam.supabase.co/storage/v1/object/public/audio/{i}.ogg")
        puladas.append(msg(f"p{i}", 400 - i / 1000, url))  # todas mais velhas que as apagáveis
    apagaveis = [msg(f"a{i}", 200, BASE + f"audio/a{i}.ogg") for i in range(3)]
    store, fake = store_factory(puladas + apagaveis, origin=origin)
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert r["deleted"] == 3
    assert fake.removed == [("audio", ["a0.ogg", "a1.ogg", "a2.ogg"])]
