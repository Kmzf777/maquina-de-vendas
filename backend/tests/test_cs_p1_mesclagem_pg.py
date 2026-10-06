"""P1.1 — mesclagem de verdade num Postgres 17 com o esquema de producao + P0.

Pula sem `CS_P1_PG_URL` (ex.: postgresql://postgres:scratch@127.0.0.1:55432) ou sem `psql`.
Roda no HOST (o container canastra-api nao tem psql):
  CS_P1_PG_URL=... <venv>/bin/python -m pytest --noconftest backend/tests/test_cs_p1_mesclagem_pg.py
O banco-modelo `crm_schema` (esquema de producao) precisa existir no servidor.
"""
import csv
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

URL = os.environ.get("CS_P1_PG_URL")
pytestmark = pytest.mark.skipif(not URL or not shutil.which("psql"),
                                reason="sem CS_P1_PG_URL/psql")

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "bling" / "mesclar_leads_duplicados.py"
P0 = RAIZ / "supabase" / "migrations" / "20261006_call_semanal_base.sql"
BANCO = "p1_mesclagem"

DUP = "8b915450-bf36-4bd6-be1b-fde35858f9ed"
SOB = "eb8ffb98-fbb2-4847-997c-89b7a0c04ac7"
CANAL = "00000000-0000-0000-0000-0000000000c1"

SEED = f"""
insert into public.channels (id, name, phone, provider)
  values ('{CANAL}', 'Joao', '553491461669', 'meta_cloud');
insert into public.leads (id, phone, name, channel, created_at)
  values ('{SOB}', '5543999565650', 'Hiago Angelucci', 'meta', '2026-09-22 10:00+00');
insert into public.leads (id, phone, name, channel, cnpj, razao_social, email, metadata, created_at)
  values ('{DUP}', 'bling-18410375514', 'Jovens Com Uma Missao', 'bling', '06132231000135',
          'Jovens Com Uma Missao Jocum', 'jocum@exemplo.org',
          '{{"origem": "bling_webhook", "id_bling": "18410375514"}}', '2026-09-25 15:53+00');
insert into public.bling_contacts (account, id, nome, doc_digits, telefone_e164)
  values ('secundaria', 18410375514, 'Jovens Com Uma Missao', '06132231000135', '5543999565650');
insert into public.lead_bling_contacts (lead_id, account, bling_contact_id)
  values ('{DUP}', 'secundaria', 18410375514);
insert into public.sales (id, lead_id, product, value, origin, status, sold_at)
  values ('00000000-0000-0000-0000-00000000b001', '{DUP}', 'Kit', 60, 'bling', 'registrada',
          '2026-09-25 12:00+00'),
         ('00000000-0000-0000-0000-00000000a001', '{SOB}', 'Kit', 60, 'manual', 'registrada',
          '2026-09-24 15:00+00');
insert into public.conversations (id, lead_id, channel_id)
  values ('00000000-0000-0000-0000-0000000000f1', '{SOB}', '{CANAL}');
insert into public.messages (lead_id, conversation_id, role, content)
  values ('{SOB}', '00000000-0000-0000-0000-0000000000f1', 'user', 'quero o kit'),
         ('{DUP}', null, 'user', 'mensagem presa no duplicado');
"""


def _psql(banco, sql):
    out = subprocess.run(["psql", f"{URL}/{banco}", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                         input=sql, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.fixture()
def banco():
    _psql("postgres", f"drop database if exists {BANCO};")
    _psql("postgres", f"create database {BANCO} template crm_schema;")
    _psql(BANCO, P0.read_text(encoding="utf-8"))
    _psql(BANCO, SEED)
    yield f"psql {URL}/{BANCO}"
    _psql("postgres", f"drop database if exists {BANCO};")


def _script():
    spec = importlib.util.spec_from_file_location("mesclar_pg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_nao_escreve_e_relata(banco, tmp_path):
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path)
    assert r["contagens"]["pares"] == 1 and r["contagens"]["gemeas"] == 1
    assert _psql(BANCO, f"select count(*) from public.leads where id = '{DUP}'") == "1"
    with open(tmp_path / "pares.csv", encoding="utf-8") as f:
        pares = list(csv.DictReader(f))
    assert pares[0]["sobrevivente"] == SOB
    backup = json.loads((tmp_path / "backup.json").read_text(encoding="utf-8"))
    assert backup[0]["lead"]["id"] == DUP
    assert backup[0]["lead_bling_contacts"][0]["bling_contact_id"] == 18410375514


def test_aplicar_move_tudo_para_o_sobrevivente(banco, tmp_path):
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path, aplicar=True)
    assert r["contagens"]["aplicados_ok"] == 1, r["aplicados"]

    def q(sql):
        return _psql(BANCO, sql)

    assert q(f"select count(*) from public.leads where id = '{DUP}'") == "0"
    assert q(f"select count(*) from public.sales where lead_id = '{SOB}'") == "2"
    assert q(f"select count(*) from public.messages where lead_id = '{SOB}'") == "2"
    assert q(f"select account||':'||bling_contact_id from public.lead_bling_contacts"
             f" where lead_id = '{SOB}'") == "secundaria:18410375514"
    assert q(f"select cnpj||'|'||razao_social||'|'||email from public.leads"
             f" where id = '{SOB}'") == "06132231000135|Jovens Com Uma Missao Jocum|jocum@exemplo.org"
    assert q(f"select name from public.leads where id = '{SOB}'") == "Hiago Angelucci"
    assert q(f"select event_type||'|'||source||'|'||dedupe_key||'|'"
             f"||(metadata->'duplicado'->>'phone') from public.lead_events"
             f" where lead_id = '{SOB}' and event_type = 'mesclagem'") \
        == f"mesclagem|sistema|mesclagem:{DUP}|bling-18410375514"

    # segunda rodada: nada mais a mesclar
    r2 = m.executar(m.Psql(banco), tmp_path / "2", aplicar=True)
    assert r2["contagens"]["pares"] == 0 and r2["contagens"]["candidatos"] == 0


def test_par_com_erro_faz_rollback_so_dele(banco, tmp_path):
    # conversa do duplicado no MESMO canal: (lead_id, channel_id) colide → rollback do par
    _psql(BANCO, f"insert into public.conversations (lead_id, channel_id)"
                 f" values ('{DUP}', '{CANAL}');")
    m = _script()
    r = m.executar(m.Psql(banco), tmp_path, aplicar=True)
    assert r["contagens"]["aplicados_erro"] == 1
    assert _psql(BANCO, f"select count(*) from public.leads where id = '{DUP}'") == "1"
    assert _psql(BANCO, f"select count(*) from public.sales where lead_id = '{DUP}'") == "1"


def test_aplicar_sem_p0_aborta(tmp_path):
    _psql("postgres", f"drop database if exists {BANCO}_sem_p0;")
    _psql("postgres", f"create database {BANCO}_sem_p0 template crm_schema;")
    try:
        m = _script()
        with pytest.raises(SystemExit):
            m.executar(m.Psql(f"psql {URL}/{BANCO}_sem_p0"), tmp_path, aplicar=True)
    finally:
        _psql("postgres", f"drop database if exists {BANCO}_sem_p0;")
