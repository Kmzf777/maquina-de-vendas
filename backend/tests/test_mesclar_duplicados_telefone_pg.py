"""Mesclagem por telefone de verdade num Postgres 17 com o esquema de producao.

Pula sem `MESCLAR_TEL_PG_URL` (ex.: postgresql://postgres:scratch@127.0.0.1:55433) ou sem
`psql`. Roda no HOST (o container canastra-api nao tem psql):
  MESCLAR_TEL_PG_URL=... <venv>/bin/python -m pytest --noconftest \\
      backend/tests/test_mesclar_duplicados_telefone_pg.py
O banco-modelo `crm_schema` (esquema de producao) precisa existir no servidor.
"""
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

URL = os.environ.get("MESCLAR_TEL_PG_URL")
pytestmark = pytest.mark.skipif(not URL or not shutil.which("psql"),
                                reason="sem MESCLAR_TEL_PG_URL/psql")

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "leads" / "mesclar_duplicados_telefone.py"
P0 = RAIZ / "supabase" / "migrations" / "20261006_call_semanal_base.sql"
BANCO = "mesclar_tel"

# Trio Douglas (o sobrevivente e o A, o mais antigo)
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
# Par Francine e um lead sozinho
F1 = "f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1"
F2 = "f2f2f2f2-f2f2-4f2f-8f2f-f2f2f2f2f2f2"
SOLO = "50505050-5050-4050-8050-505050505050"

CANAL = "00000000-0000-4000-8000-0000000000c1"
CONV_A = "00000000-0000-4000-8000-0000000000fa"
CONV_B = "00000000-0000-4000-8000-0000000000fb"
PIPE = "00000000-0000-4000-8000-0000000000e1"
FUP_A = "00000000-0000-4000-8000-00000000f0a1"
FUP_B = "00000000-0000-4000-8000-00000000f0b1"
BROAD = "00000000-0000-4000-8000-0000000000b1"
TAG = "00000000-0000-4000-8000-0000000000d1"
VENDA_B = "00000000-0000-4000-8000-0000000005b1"
ORC_B = "00000000-0000-4000-8000-0000000009b1"

SEED = f"""
insert into public.channels (id, name, phone, provider)
  values ('{CANAL}', 'Joao', '553491461669', 'meta_cloud');
insert into public.leads (id, phone, name, created_at)
  values ('{A}', '4999170363', 'Douglas', '2026-05-08 10:00+00'),
         ('{C}', '554999170363', 'Douglas', '2026-09-04 10:00+00'),
         ('{F1}', '5551981162558', 'Francine', '2026-03-01 10:00+00'),
         ('{F2}', '555181162558', 'Francine', '2026-07-01 10:00+00'),
         ('{SOLO}', '5511987654321', 'Sozinho', '2026-01-01 10:00+00');
insert into public.leads (id, phone, name, email, bsuid, opt_out, opt_out_at, opt_out_channel,
                          created_at)
  values ('{B}', '5549999170363', 'Douglas S', 'douglas@exemplo.com', 'BR.douglas', true,
          '2026-06-20 10:00+00', 'whatsapp_texto', '2026-06-15 10:00+00');

insert into public.conversations (id, lead_id, channel_id)
  values ('{CONV_A}', '{A}', '{CANAL}'), ('{CONV_B}', '{B}', '{CANAL}');
insert into public.messages (lead_id, conversation_id, role, content)
  values ('{A}', '{CONV_A}', 'user', 'oi, sou o Douglas'),
         ('{A}', '{CONV_A}', 'assistant', 'oi Douglas'),
         ('{B}', '{CONV_B}', 'user', 'quero cafe'),
         ('{B}', '{CONV_B}', 'assistant', 'temos o kit');
-- estado das conversas DEPOIS das mensagens (o gatilho de messages mexe na conversa)
update public.conversations set stage = 'secretaria', status = 'active',
       last_msg_at = '2026-06-01 10:00+00', unread_count = 2, followup_enabled = true,
       last_seller_response_at = '2026-06-01 09:00+00'
 where id = '{CONV_A}';
update public.conversations set stage = 'vendedor', status = 'em_atendimento',
       last_msg_at = '2026-07-01 10:00+00', unread_count = 3, followup_enabled = false,
       last_seller_response_at = '2026-07-01 09:00+00'
 where id = '{CONV_B}';
insert into public.sales (id, lead_id, conversation_id, product, value, sold_at)
  values ('{VENDA_B}', '{B}', '{CONV_B}', 'Kit', 60, '2026-07-01 12:00+00');
insert into public.quotes (id, lead_id, conversation_id, quoted_at)
  values ('{ORC_B}', '{B}', '{CONV_B}', '2026-06-30');

insert into public.pipelines (id, name) values ('{PIPE}', 'Vendas');
insert into public.deals (lead_id, title, pipeline_id)
  values ('{B}', 'Kit B', '{PIPE}'), ('{C}', 'Kit C', '{PIPE}');

insert into public.follow_up_jobs (id, conversation_id, lead_id, channel_id, sequence, fire_at,
                                   status, job_type)
  values ('{FUP_A}', '{CONV_A}', '{A}', '{CANAL}', 1, now() + interval '1 day', 'pending',
          'joao_reativacao'),
         ('{FUP_B}', '{CONV_B}', '{B}', '{CANAL}', 2, now() + interval '1 day', 'pending',
          'joao_reativacao');

insert into public.broadcasts (id, name, template_name) values ('{BROAD}', 'Promo', 'promo');
insert into public.broadcast_leads (broadcast_id, lead_id)
  values ('{BROAD}', '{A}'), ('{BROAD}', '{B}');

-- controle humano, notas, campanha manual e resumo (re-revisao de 14/10)
update public.leads set notes = 'primeira nota' where id = '{A}';
update public.leads set human_control = true, ai_enabled = false,
       notes = 'cliente pediu desconto', campanha_manual_canal = 'meta',
       campanha_manual_id = 'cmp1', campanha_manual_nome = 'Promo Junho',
       rolling_summary = 'resumo do B' where id = '{B}';
update public.leads set notes = 'nota do C', campanha_manual_id = 'cmp2',
       campanha_manual_nome = 'Outra' where id = '{C}';

insert into public.tags (id, name) values ('{TAG}', 'cliente');
insert into public.lead_tags (lead_id, tag_id) values ('{A}', '{TAG}'), ('{B}', '{TAG}');
"""


def _psql(banco, sql):
    out = subprocess.run(["psql", f"{URL}/{banco}", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                         input=sql, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def q(sql):
    return _psql(BANCO, sql)


@pytest.fixture()
def banco():
    _psql("postgres", f"drop database if exists {BANCO};")
    _psql("postgres", f"create database {BANCO} template crm_schema;")
    colunas_p0 = _psql(BANCO, "select count(*) from information_schema.columns"
                              " where table_schema = 'public' and table_name = 'lead_events'"
                              " and column_name in ('occurred_at', 'source', 'dedupe_key')")
    if colunas_p0 != "3":  # P0 e idempotente; producao ja tem
        _psql(BANCO, P0.read_text(encoding="utf-8"))
    _psql(BANCO, SEED)
    yield f"psql {URL}/{BANCO}"
    _psql("postgres", f"drop database if exists {BANCO};")


def _script():
    spec = importlib.util.spec_from_file_location("mesclar_tel_pg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ler(caminho):
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _csv_aprovado(dry, destino, extra=()):
    """pares.csv do dry-run + as linhas do revisar.csv aprovadas a mao (o fluxo do Rafael)."""
    linhas = _ler(Path(dry) / "pares.csv") + list(extra)
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["canonico", "sobrevivente", "duplicados", "motivo"],
                           extrasaction="ignore")
        w.writeheader()
        for lin in linhas:
            w.writerow(lin)
    return destino


def _aplicar_com_douglas(m, banco, saida):
    dry = Path(saida) / "dry"
    m.executar(m.Psql(banco), dry)
    douglas = [r for r in _ler(dry / "revisar.csv") if r["canonico"] == "5549999170363"]
    csv_ = _csv_aprovado(dry, Path(saida) / "aprovado.csv", douglas)
    return m.executar(m.Psql(banco), saida, aplicar=True, pares_csv=csv_)


def test_dry_run_nao_escreve_e_relata(banco, tmp_path):
    m = _script()
    antes = q("select count(*) from public.leads")
    r = m.executar(m.Psql(banco), tmp_path)
    assert q("select count(*) from public.leads") == antes
    assert q(f"select phone from public.leads where id = '{A}'") == "4999170363"
    assert r["contagens"]["grupos"] == 2
    pares = _ler(tmp_path / "pares.csv")
    assert [(p["canonico"], p["sobrevivente"], p["duplicados"]) for p in pares] == \
        [("5551981162558", F1, F2)]
    revisar = _ler(tmp_path / "revisar.csv")
    assert [(x["canonico"], x["sobrevivente"], x["duplicados"], x["motivo"]) for x in revisar] == \
        [("5549999170363", A, f"{B}|{C}", "3 leads no grupo")]
    deals = _ler(tmp_path / "deals_repetidos.csv")
    assert [(d["canonico"], d["pipeline_id"]) for d in deals] == [("5549999170363", PIPE)]


def test_aplicar_funde_o_trio_e_o_par(banco, tmp_path):
    m = _script()
    total_msgs = q("select count(*) from public.messages")
    r = _aplicar_com_douglas(m, banco, tmp_path)
    assert r["contagens"]["aplicados_ok"] == 2, r["aplicados"]

    assert q(f"select string_agg(id::text, ',' order by id) from public.leads"
             f" where id in ('{A}', '{B}', '{C}', '{F1}', '{F2}')") == f"{A},{F1}"
    assert q(f"select phone from public.leads where id = '{A}'") == "5549999170363"
    assert q(f"select phone from public.leads where id = '{F1}'") == "5551981162558"

    # todas as mensagens no A, numa unica conversa no canal c1, nenhuma perdida
    assert q("select count(*) from public.messages") == total_msgs
    assert q(f"select count(*) from public.messages where lead_id = '{A}'") == "4"
    assert q(f"select string_agg(distinct conversation_id::text, ',') from public.messages"
             f" where lead_id = '{A}'") == CONV_A
    assert q(f"select count(*) from public.conversations where lead_id = '{A}'"
             f" and channel_id = '{CANAL}'") == "1"
    assert q(f"select count(*) from public.conversations where id = '{CONV_B}'") == "0"
    # a conversa que fica herda: follow-up desligado (o do B era false), nao lidas somadas,
    # ultimas datas pelo maior, etapa/status da mais recente (a do B)
    assert q(f"select followup_enabled::text || '|' || unread_count || '|' || stage || '|'"
             f" || status || '|' || to_char(last_msg_at at time zone 'UTC', 'YYYY-MM-DD')"
             f" || '|' || to_char(last_seller_response_at at time zone 'UTC', 'YYYY-MM-DD')"
             f" from public.conversations where id = '{CONV_A}'") == \
        "false|5|vendedor|em_atendimento|2026-07-01|2026-07-01"
    # venda e orcamento da conversa do B foram para a do A
    assert q(f"select lead_id || '|' || conversation_id from public.sales"
             f" where id = '{VENDA_B}'") == f"{A}|{CONV_A}"
    assert q(f"select lead_id || '|' || conversation_id from public.quotes"
             f" where id = '{ORC_B}'") == f"{A}|{CONV_A}"

    assert q(f"select count(*) from public.deals where lead_id = '{A}'") == "2"
    assert q(f"select opt_out::text || '|' || opt_out_channel || '|' || email || '|' || bsuid"
             f" from public.leads where id = '{A}'") == \
        "true|whatsapp_texto|douglas@exemplo.com|BR.douglas"
    assert q(f"select name from public.leads where id = '{A}'") == "Douglas"
    # controle humano: IA desligada e humano no controle (vieram do B)
    assert q(f"select ai_enabled::text || '|' || human_control::text || '|'"
             f" || coalesce(on_hold::text, 'null') from public.leads where id = '{A}'") == \
        "false|true|false"
    # notas concatenadas com o telefone de origem, na ordem de created_at
    assert q(f"select notes from public.leads where id = '{A}'") == (
        "primeira nota\n\n--- mesclado de 5549999170363 ---\ncliente pediu desconto"
        "\n\n--- mesclado de 554999170363 ---\nnota do C")
    # campanha manual inteira do duplicado mais antigo que tinha (B, nao C)
    assert q(f"select campanha_manual_canal || '|' || campanha_manual_id || '|'"
             f" || campanha_manual_nome from public.leads where id = '{A}'") == \
        "meta|cmp1|Promo Junho"
    assert q(f"select rolling_summary from public.leads where id = '{A}'") == "resumo do B"
    # o evento guarda a linha inteira do duplicado
    assert q(f"select metadata->'duplicado'->>'notes' || '|'"
             f" || (metadata->'duplicado'->>'human_control') from public.lead_events"
             f" where dedupe_key = 'mesclagem:{B}'") == "cliente pediu desconto|true"

    # follow-up: o do B foi cancelado (nao apagado), mudou de dono e de conversa
    assert q(f"select status || '|' || cancel_reason || '|' || lead_id || '|' || conversation_id"
             f" from public.follow_up_jobs where id = '{FUP_B}'") == \
        f"cancelled|mesclagem|{A}|{CONV_A}"
    assert q(f"select status from public.follow_up_jobs where id = '{FUP_A}'") == "pending"

    assert q(f"select count(*) from public.broadcast_leads where broadcast_id = '{BROAD}'") == "1"
    assert q(f"select lead_id from public.broadcast_leads where broadcast_id = '{BROAD}'") == A
    assert q(f"select count(*) from public.lead_tags where lead_id = '{A}'") == "1"

    assert q(f"select string_agg(dedupe_key, ',' order by dedupe_key) from public.lead_events"
             f" where lead_id = '{A}' and event_type = 'mesclagem'") == \
        f"mesclagem:{B},mesclagem:{C}"
    movidos_b = json.loads(q(f"select metadata->'movidos' from public.lead_events"
                             f" where dedupe_key = 'mesclagem:{B}'"))
    (fundida,) = movidos_b["conversas_fundidas"]
    assert (fundida["de"], fundida["para"]) == (CONV_B, CONV_A)
    assert fundida["para_antes"]["unread_count"] == 2  # estado do A antes da fusao
    assert movidos_b["follow_up_jobs_cancelados"] == [FUP_B]
    # reapontamentos com a conversa de origem: da para desfazer
    assert len(movidos_b["messages_fundidas"]) == 2
    assert {x["de"] for x in movidos_b["messages_fundidas"]} == {CONV_B}
    assert movidos_b["follow_up_jobs_reapontados"] == [{"id": FUP_B, "de": CONV_B}]
    assert movidos_b["sales_reapontadas"] == [{"id": VENDA_B, "de": CONV_B}]
    assert movidos_b["quotes_reapontadas"] == [{"id": ORC_B, "de": CONV_B}]
    # colisoes apagadas vao inteiras para o evento
    assert [x["lead_id"] for x in movidos_b["broadcast_leads_apagados"]] == [B]
    assert [x["tag_id"] for x in movidos_b["lead_tags_apagados"]] == [TAG]

    (arq_backup,) = tmp_path.glob("backup-*.json")  # o --aplicar grava com carimbo de hora
    backup = json.loads(arq_backup.read_text(encoding="utf-8"))
    por_id = {b["lead"]["id"]: b for b in backup}
    assert {B, C, F2} <= set(por_id)
    assert [c["id"] for c in por_id[B]["conversas_duplicados"]] == [CONV_B]
    assert por_id[B]["sobrevivente_antes"]["phone"] == "4999170363"
    assert por_id[B]["movidos"] == movidos_b

    # segunda rodada: nada mais a mesclar
    r2 = m.executar(m.Psql(banco), tmp_path / "2")
    assert r2["contagens"]["grupos"] == 0


def test_erro_num_grupo_faz_rollback_so_dele(banco, tmp_path):
    q(f"""
create function public._teste_falha() returns trigger language plpgsql as $$
begin raise exception 'falha de teste'; end $$;
create trigger _teste_falha before update on public.messages
  for each row when (old.lead_id = '{B}') execute function public._teste_falha();
""")
    m = _script()
    r = _aplicar_com_douglas(m, banco, tmp_path)
    resultado = {a["canonico"]: a["resultado"] for a in r["aplicados"]}
    assert resultado == {"5549999170363": "erro", "5551981162558": "ok"}, r["aplicados"]
    assert "falha de teste" in next(a["erro"] for a in r["aplicados"] if a["resultado"] == "erro")
    # Douglas intacto
    assert q(f"select count(*) from public.leads where id in ('{A}', '{B}', '{C}')") == "3"
    assert q(f"select phone from public.leads where id = '{A}'") == "4999170363"
    assert q(f"select count(*) from public.messages where lead_id = '{B}'") == "2"
    assert q(f"select count(*) from public.conversations where id = '{CONV_B}'") == "1"
    assert q(f"select status from public.follow_up_jobs where id = '{FUP_B}'") == "pending"
    # Francine aplicada
    assert q(f"select count(*) from public.leads where id = '{F2}'") == "0"


def test_linha_com_sobrevivente_que_nao_bate_e_recusada(banco, tmp_path):
    m = _script()
    csv_ = tmp_path / "errado.csv"
    csv_.write_text(f"canonico,sobrevivente,duplicados\n5549999170363,{B},{A}|{C}\n",
                    encoding="utf-8")
    r = m.executar(m.Psql(banco), tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert r["contagens"]["aplicados_recusados"] == 1 and r["contagens"]["aplicados_ok"] == 0
    assert "sobrevivente" in r["aplicados"][0]["erro"]
    assert q(f"select count(*) from public.leads where id in ('{A}', '{B}', '{C}')") == "3"


def _grupo_douglas(m):
    leads = m.Psql(f"psql {URL}/{BANCO}").linhas(m.Q_LEADS)
    return next(g for g in m.agrupar(leads) if g["canonico"] == "5549999170363")


def test_lead_travado_por_outra_transacao_cai_por_lock_timeout(banco, tmp_path):
    # outra sessao segura o lead B por 15s; o grupo Douglas desiste em 5s e a Francine aplica
    trava = subprocess.Popen(
        ["psql", f"{URL}/{BANCO}", "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    trava.stdin.write(f"begin; select 1 from public.leads where id = '{B}' for update;"
                      " select pg_sleep(15); commit;\n")
    trava.stdin.flush()
    try:
        for _ in range(50):
            if q("select count(*) from pg_locks l join pg_stat_activity a using (pid)"
                 " where a.pid <> pg_backend_pid() and a.query like '%pg_sleep%'"
                 " and l.locktype = 'transactionid'") != "0":
                break
            time.sleep(0.2)
        m = _script()
        r = _aplicar_com_douglas(m, banco, tmp_path)
    finally:
        trava.stdin.close()
        trava.wait(timeout=30)
    erro = {a["canonico"]: a for a in r["aplicados"]}
    assert erro["5549999170363"]["resultado"] == "erro"
    assert "lock timeout" in erro["5549999170363"]["erro"]
    assert erro["5551981162558"]["resultado"] == "ok"
    assert q(f"select count(*) from public.leads where id in ('{A}', '{B}', '{C}')") == "3"


def test_telefone_que_mudou_depois_do_calculo_aborta_o_grupo(banco):
    m = _script()
    grupo = _grupo_douglas(m)
    q(f"update public.leads set phone = '5511900000000' where id = '{C}'")
    db = m.Psql(banco)
    tabelas = {r["table_name"] for r in db.linhas(m.bling.Q_TABELAS)}
    colunas = {}
    for r in db.linhas(m.Q_COLUNAS):
        colunas.setdefault(r["table_name"], set()).add(r["column_name"])
    with pytest.raises(RuntimeError) as exc:
        db.executar(m.sql_mesclar_grupo(grupo, tabelas, None, colunas))
    assert "telefone de algum lead mudou" in str(exc.value)
    assert q(f"select count(*) from public.leads where id in ('{A}', '{B}', '{C}')") == "3"


def test_possivel_fixo_fica_com_o_canonico_de_13_digitos(banco, tmp_path):
    fixo1 = "00000000-0000-4000-8000-00000000f101"
    fixo2 = "00000000-0000-4000-8000-00000000f102"
    q(f"insert into public.leads (id, phone, name, created_at) values"
      f" ('{fixo1}', '4934415750', 'Loja', '2026-02-01 10:00+00'),"
      f" ('{fixo2}', '554934415750', 'Loja', '2026-04-01 10:00+00');")
    m = _script()
    m.executar(m.Psql(banco), tmp_path / "dry")
    fixo = [r for r in _ler(tmp_path / "dry" / "revisar.csv") if r["canonico"] == "5549934415750"]
    assert fixo and fixo[0]["motivo"] == "possivel telefone fixo (confira)"
    csv_ = _csv_aprovado(tmp_path / "dry", tmp_path / "fixo.csv")
    csv_.write_text("canonico,sobrevivente,duplicados\n"
                    f"5549934415750,{fixo1},{fixo2}\n", encoding="utf-8")
    r = m.executar(m.Psql(banco), tmp_path, aplicar=True, pares_csv=csv_)
    assert r["contagens"]["aplicados_ok"] == 1, r["aplicados"]
    assert q(f"select phone from public.leads where id = '{fixo1}'") == "5549934415750"
    assert q(f"select count(*) from public.leads where id = '{fixo2}'") == "0"


def test_fk_desconhecida_para_conversations_aborta(banco, tmp_path):
    q("alter table public.quotes add constraint quotes_conv_fk_teste"
      " foreign key (conversation_id) references public.conversations(id);")
    m = _script()
    with pytest.raises(m.FKDesconhecida) as exc:
        m.executar(m.Psql(banco), tmp_path)
    assert "quotes.conversation_id" in str(exc.value)
