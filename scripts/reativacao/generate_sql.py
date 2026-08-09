# scripts/reativacao/generate_sql.py
"""Gera o SQL da preparacao de reativacao. Nao executa nada.

O artefato revisavel e o proprio arquivo .sql: ele e inspecionado antes de rodar
via psql, dentro de uma transacao, depois do pg_dump. Ver
docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
"""
import argparse
import csv
import json
import os
import sys

import transform

LOTE = "reativacao_bling_2026-08-10"
ORIGEM = "reativacao_bling"
JOAO_UUID = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"
CANAL_JOAO = "553491461669"
AUTOR_NOTA = "Sistema — Reativação Bling"

# Guardrail: o SQL gerado nunca pode tocar o disparo.
TABELAS_PROIBIDAS = ("broadcasts", "broadcast_leads")

# Guardrail: colunas que nunca podem ser sobrescritas nos leads pre-existentes.
COLUNAS_INTOCAVEIS = ("stage", "status", "human_control", "ai_enabled")

# Decisao D7 do spec: recebem lead + nota, mas ficam fora da campanha.
MOTIVOS_EXCLUSAO = {
    "5511996057340": "operação de café encerrada — o cliente avisou",
    "5511989374541": "o número é o atendimento automático da loja",
    "5516997442292": "LEAD QUENTE — pediu portfólio e cápsulas/drip; responder o pedido dele, não disparar template",
    "5554996324731": "declinou com gatilho — retomar quando o estoque dela baixar",
}

# Decisao D9: telefone a normalizar antes dos inserts.
NORMALIZACOES = (("11981154002", "5511981154002"),)

# Campos que vem da planilha master, nao do CSV de disparo.
CAMPOS_DA_MASTER = ("qtd_nfe", "orcamentos", "valor_vencido", "titulos_vencidos",
                    "dias_atraso_max", "qtd_top1")


def sql_literal(valor):
    """Escapa para literal SQL; vazio/None viram NULL."""
    if valor is None:
        return "NULL"
    texto = str(valor).strip()
    if not texto:
        return "NULL"
    return "'" + texto.replace("'", "''") + "'"


def _metadata_json(dados):
    return {
        "origem": ORIGEM,
        "lote": LOTE,
        "id_bling": (dados.get("id_bling") or "").strip(),
        "icp_score": (dados.get("icp_score") or "").strip(),
        "phone_raw": (dados.get("whatsapp") or "").strip(),
    }


def gerar_insert_lead(dados, nome_crm):
    """INSERT idempotente de um lead novo.

    Grava "criado_por_lote" no metadata — marcador explicito, distinto de
    "lote" (que tambem e escrito por gerar_update_conservador em leads
    pre-existentes). O rollback usa esse marcador para saber com certeza
    quem este lote CRIOU, em vez de inferir isso por "nao tem mensagens"
    (proxy falsa: leads pre-existentes tambem podem nao ter mensagens).
    gerar_update_conservador NUNCA deve escrever essa chave.
    """
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    nome = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    metadata_dict = _metadata_json(dados)
    metadata_dict["criado_por_lote"] = LOTE
    metadata = json.dumps(metadata_dict, ensure_ascii=False)
    return (
        "INSERT INTO leads (phone, name, company, stage, status, channel, "
        "assigned_to, cnpj, razao_social, nome_fantasia, email, endereco, metadata)\n"
        "VALUES (%s, %s, %s, 'pending', 'imported', %s, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb)\n"
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(phone),
            sql_literal(nome),
            sql_literal(dados.get("razao_social") or dados.get("nome")),
            sql_literal(CANAL_JOAO),
            sql_literal(JOAO_UUID),
            sql_literal(dados.get("cpf_cnpj")),
            sql_literal(dados.get("razao_social")),
            sql_literal(dados.get("saudacao")),
            sql_literal(dados.get("email")),
            sql_literal("/".join(p for p in [(dados.get("cidade") or "").strip(),
                                             (dados.get("uf") or "").strip()] if p)),
            sql_literal(metadata),
        )
    )


def gerar_update_conservador(dados, tem_dono):
    """UPDATE que so preenche o que esta vazio (decisao D5 do spec).

    Nunca emite as COLUNAS_INTOCAVEIS. metadata recebe merge com ||, nunca
    substituicao. assigned_to so entra quando o lead nao tem dono.
    """
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    metadata = json.dumps(_metadata_json(dados), ensure_ascii=False)
    local = "/".join(p for p in [(dados.get("cidade") or "").strip(),
                                 (dados.get("uf") or "").strip()] if p)
    sets = [
        "cnpj = COALESCE(NULLIF(cnpj, ''), %s)" % sql_literal(dados.get("cpf_cnpj")),
        "razao_social = COALESCE(NULLIF(razao_social, ''), %s)" % sql_literal(dados.get("razao_social")),
        "nome_fantasia = COALESCE(NULLIF(nome_fantasia, ''), %s)" % sql_literal(dados.get("saudacao")),
        "email = COALESCE(NULLIF(email, ''), %s)" % sql_literal(dados.get("email")),
        "endereco = COALESCE(NULLIF(endereco, ''), %s)" % sql_literal(local),
        "metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb" % sql_literal(metadata),
    ]
    if not tem_dono:
        sets.append("assigned_to = COALESCE(assigned_to, %s::uuid)" % sql_literal(JOAO_UUID))
    return "UPDATE leads SET\n  %s\nWHERE phone = %s;" % (
        ",\n  ".join(sets), sql_literal(phone))


def gerar_insert_nota(dados, nome_crm):
    """Nota de briefing, so se ainda nao existir a nota deste lote."""
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    dados_briefing = dict(dados)
    dados_briefing["saudacao"] = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    conteudo = transform.montar_briefing(dados_briefing)
    return (
        "INSERT INTO lead_notes (lead_id, author, content)\n"
        "SELECT l.id, %s, %s\n"
        "FROM leads l\n"
        "WHERE l.phone = %s\n"
        "  AND NOT EXISTS (\n"
        "    SELECT 1 FROM lead_notes n\n"
        "    WHERE n.lead_id = l.id AND n.content LIKE %s\n"
        "  );" % (
            sql_literal(AUTOR_NOTA),
            sql_literal(conteudo),
            sql_literal(phone),
            sql_literal("%" + LOTE + "%"),
        )
    )


def gerar_update_optout(telefone, quando, disse):
    """Marca opt_out e registra a evidencia no metadata.

    O metadata leva "lote" junto com a evidencia (Finding 2 do fix round 1):
    sem isso, o rollback de opt-outs nao tem como saber que opt-out foi
    aplicado POR ESTE lote, e desfaria opt-outs de qualquer lote — reabrindo
    contato com quem pediu para nao ser contactado em outra campanha.
    """
    phone = transform.normalizar_telefone(telefone)
    evidencia = json.dumps(
        {
            "optout_quando": quando,
            "optout_disse": (disse or "")[:200],
            "optout_fonte": "mensagem_do_cliente",
            "lote": LOTE,
        },
        ensure_ascii=False,
    )
    return (
        "UPDATE leads SET\n"
        "  opt_out = true,\n"
        "  metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb\n"
        "WHERE regexp_replace(phone, '[^0-9]', '', 'g') IN (%s, %s)\n"
        "  AND opt_out IS NOT TRUE;" % (
            sql_literal(evidencia), sql_literal(phone), sql_literal(phone[2:] if phone.startswith("55") else phone))
    )


def gerar_normalizacao_telefone(antigo, novo):
    """Corrige um phone para E.164, sem colidir com registro existente (D9)."""
    return (
        "UPDATE leads SET phone = %s\n"
        "WHERE phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM leads outro WHERE outro.phone = %s);" % (
            sql_literal(novo), sql_literal(antigo), sql_literal(novo))
    )


# NOTA (defeito do brief task-6): o cabecalho de referencia do brief citava
# literalmente "broadcasts/broadcast_leads" no comentario, o que quebra a
# propria garantia que o guardrail TABELAS_PROIBIDAS deveria proteger (o teste
# test_nunca_menciona_tabelas_de_disparo varre o SQL inteiro, comentarios
# inclusive). Reformulado para nao nomear as tabelas proibidas, preservando a
# mensagem "este arquivo nao cria disparo".
CABECALHO = """-- Preparacao da campanha de reativacao — lote %s
-- Gerado por scripts/reativacao/generate_sql.py. NAO editar a mao.
-- Spec:  docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md
-- Plano: docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
--
-- PRE-REQUISITO: pg_dump feito. Rodar com:
--   psql -U postgres -v ON_ERROR_STOP=1 -f preparar.sql
--
-- Este arquivo NAO cria disparo. Nenhuma escrita nas tabelas de campanha/fila
-- de envio (fora do escopo desta preparacao de dados).
\\set ON_ERROR_STOP on
BEGIN;
""" % LOTE

def _bloco_verificacao(rotulo, expressao_where, esperado):
    """Um DO $$ ... $$ que aborta a transacao (RAISE EXCEPTION) se a
    contagem nao bater com o esperado.

    Fix round 1, Finding 3 (Important): um SELECT count(*) que so faz
    \\echo nao impede o COMMIT quando a contagem esta errada — psql -f roda
    o arquivo inteiro de uma vez, e o COMMIT roda na mesma passada em que a
    contagem errada foi so exibida. Precisa de algo que force o rollback da
    transacao sozinho, num banco sem backup.
    """
    return (
        "\\echo '--- %s (esperado: %d) ---'\n"
        "DO $$\n"
        "DECLARE n integer;\n"
        "BEGIN\n"
        "  SELECT count(*) INTO n FROM %s;\n"
        "  IF n <> %d THEN\n"
        "    RAISE EXCEPTION 'esperado %d %s, encontrado %%', n;\n"
        "  END IF;\n"
        "END $$;"
    ) % (rotulo, esperado, expressao_where, esperado, esperado, rotulo)


def _gerar_rodape(qtd_leads_esperado, qtd_notas_esperado, qtd_optouts_esperado):
    """Rodape com as 3 verificacoes de contagem + COMMIT.

    Os numeros esperados sao parametros derivados de len(novos) +
    len(existentes) e len(optouts) em montar_arquivo — nunca literais fixos
    do lote atual — para que o check nunca possa divergir da realidade do
    que de fato foi passado para montar_arquivo.
    """
    blocos = [
        "-- ── Verificacao (dentro da transacao; aborta se a contagem nao bater) ─────",
        _bloco_verificacao(
            "leads do lote",
            "leads WHERE metadata->>'lote' = %s" % sql_literal(LOTE),
            qtd_leads_esperado,
        ),
        _bloco_verificacao(
            "notas do lote",
            "lead_notes WHERE content LIKE %s" % sql_literal("%" + LOTE + "%"),
            qtd_notas_esperado,
        ),
        _bloco_verificacao(
            "opt-outs marcados",
            "leads WHERE opt_out AND metadata->>'lote' = %s AND metadata->>'optout_fonte' = 'mensagem_do_cliente'"
            % sql_literal(LOTE),
            qtd_optouts_esperado,
        ),
        "COMMIT;",
    ]
    return "\n\n".join(blocos) + "\n"


def montar_arquivo(novos, existentes, optouts, normalizacoes):
    """SQL completo, em transacao unica.

    Ordem importa: normalizacoes de telefone vem antes dos INSERTs, senao o
    registro com telefone curto viraria duplicata logica do novo.
    """
    partes = [CABECALHO]

    partes.append("\n-- ── 1. Normalizacao de telefone (decisao D9) ──────────────────────────────")
    for antigo, novo in normalizacoes:
        partes.append(gerar_normalizacao_telefone(antigo, novo))

    partes.append("\n-- ── 2. Leads novos ────────────────────────────────────────────────────────")
    for dados, nome_crm, _ in novos:
        partes.append(gerar_insert_lead(dados, nome_crm))

    partes.append("\n-- ── 3. Leads existentes: preencher apenas vazios (decisao D5) ─────────────")
    for dados, _nome_crm, tem_dono in existentes:
        partes.append(gerar_update_conservador(dados, tem_dono))

    partes.append("\n-- ── 4. Notas de briefing ──────────────────────────────────────────────────")
    for dados, nome_crm, _ in list(novos) + list(existentes):
        partes.append(gerar_insert_nota(dados, nome_crm))

    partes.append("\n-- ── 5. Opt-outs pendentes ─────────────────────────────────────────────────")
    for telefone, quando, disse in optouts:
        partes.append(gerar_update_optout(telefone, quando, disse))

    qtd_leads_e_notas_esperado = len(novos) + len(existentes)
    partes.append(_gerar_rodape(qtd_leads_e_notas_esperado, qtd_leads_e_notas_esperado, len(optouts)))
    return "\n\n".join(partes)


def montar_rollback():
    """Desfaz exatamente este lote.

    Fix round 1, Finding 1 (CRITICAL): o sinal PRIMARIO de "este lote criou
    este lead" e o marcador explicito metadata.criado_por_lote — escrito
    apenas por gerar_insert_lead, nunca por gerar_update_conservador.
    "NOT EXISTS (messages)" e mantido como uma SEGUNDA rede de seguranca
    independente, nao mais como sinal primario: em produção, 3 dos 40 leads
    pre-existentes (um deles ja secretaria/active) nao tinham mensagem
    nenhuma e seriam apagados por engano se "sem mensagem" fosse o unico
    criterio. Um lead pre-existente que recebeu merge no metadata (tem
    metadata.lote mas NAO tem metadata.criado_por_lote) sobrevive sempre.

    Fix round 1, Finding 2 (Important): o UPDATE que desfaz opt-out so pode
    atingir opt-outs aplicados por ESTE lote (metadata->>'lote'), senao um
    rollback futuro reabriria contato com quem pediu para nao ser
    contactado em OUTRO lote.
    """
    return """-- Rollback do lote %(lote)s
-- Remove SO o que este lote criou. Leads pre-existentes que receberam merge de
-- metadata ou nota permanecem — apenas a nota e o metadata do lote saem.
\\set ON_ERROR_STOP on
BEGIN;

DELETE FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

UPDATE leads
SET opt_out = false
WHERE opt_out AND metadata->>'lote' = '%(lote)s' AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

DELETE FROM leads l
WHERE l.metadata->>'criado_por_lote' = '%(lote)s'
  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id);

UPDATE leads SET metadata = metadata - 'lote' - 'origem' - 'id_bling' - 'icp_score' - 'criado_por_lote'
WHERE metadata->>'lote' = '%(lote)s';

\\echo '--- deve retornar 0 ---'
SELECT count(*) AS restantes FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

COMMIT;
""" % {"lote": LOTE}


def carregar_disparo(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def carregar_master(caminho):
    """id_bling -> dict, para puxar os campos que o CSV de disparo nao tem."""
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return {linha["id_bling"]: linha for linha in csv.DictReader(fh)}


def carregar_nomes_crm(caminho):
    """Le o TSV 'telefone<TAB>nome' dos leads que ja existem no CRM.

    Fix round 1, Finding 1 (CRITICAL): a extracao de origem (psql \\copy)
    pode gravar a sequencia LITERAL de dois caracteres "\\t" em vez de um TAB
    real (bug tipico de usar E'\\t' errado no \\copy). O parser tolera os
    dois formatos: tenta um TAB real primeiro; se a linha nao tiver TAB real
    mas tiver a sequencia literal "\\t", usa ela.

    Um CRM vazio nao e um estado plausivel (a base tem milhares de leads) —
    se nenhuma linha for parseavel, explode com o caminho do arquivo e a
    primeira linha bruta, em vez de devolver silenciosamente um dict vazio
    que faria o script tratar TODOS os leads existentes como novos.
    """
    nomes = {}
    primeira_linha_bruta = ""
    vista_primeira_linha = False
    with open(caminho, encoding="utf-8") as fh:
        for bruta in fh:
            linha = bruta.rstrip("\n")
            if not vista_primeira_linha:
                primeira_linha_bruta = linha
                vista_primeira_linha = True
            if "\t" in linha:
                fone, nome = linha.split("\t", 1)
            elif "\\t" in linha:
                fone, nome = linha.split("\\t", 1)
            else:
                continue
            if fone.strip():
                nomes[fone.strip()] = nome.strip()
    if not nomes:
        raise ValueError(
            "nomes_crm: nenhuma linha com TAB encontrada em %s; primeira linha: %r"
            % (caminho, primeira_linha_bruta)
        )
    return nomes


def excluir_optouts_ja_marcados(optouts, ja_marcados):
    """Remove da lista os telefones que ja estao marcados opt_out=true no banco.

    Fix round 1, Finding 2 (CRITICAL): gerar_update_optout so atualiza quem
    tem "opt_out IS NOT TRUE", mas o rodape de verificacao espera
    len(optouts) linhas atualizadas. Se o arquivo de opt-outs incluir quem
    ja foi marcado por outro motivo, o UPDATE atualiza menos linhas do que
    o esperado e o RAISE EXCEPTION do rodape aborta a transacao inteira —
    inclusive os leads e notas que nada tinham a ver com opt-out. Filtrar
    aqui, antes de montar_arquivo, garante que len(optouts) reflita
    exatamente o que o UPDATE vai atualizar.

    Devolve (lista_filtrada, quantidade_pulada).
    """
    filtrados = [item for item in optouts if item[0] not in ja_marcados]
    pulados = len(optouts) - len(filtrados)
    return filtrados, pulados


def enriquecer(linhas, master, nomes_crm, donos):
    """Separa (novos, existentes) e completa cada dict.

    nomes_crm: telefone E.164 -> leads.name (vazio quando o CRM nao tem nome)
    donos:     telefones que ja tem assigned_to preenchido
    """
    novos, existentes = [], []
    for linha in linhas:
        dados = dict(linha)
        phone = transform.normalizar_telefone(dados.get("whatsapp"))
        da_master = master.get((dados.get("id_bling") or "").strip(), {})
        for campo in CAMPOS_DA_MASTER:
            dados.setdefault(campo, "")
            if not dados.get(campo) and da_master.get(campo):
                dados[campo] = da_master[campo]
        dados["motivo_exclusao"] = MOTIVOS_EXCLUSAO.get(phone, "")
        nome_crm = nomes_crm.get(phone) or None
        entrada = (dados, nome_crm, phone in donos)
        (existentes if phone in nomes_crm else novos).append(entrada)
    return novos, existentes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o SQL da preparacao de reativacao.")
    parser.add_argument("--disparo", required=True, help="CSV da lista de disparo")
    parser.add_argument("--master", required=True, help="CSV master de leads")
    parser.add_argument("--nomes-crm", required=True,
                        help="TSV 'telefone<TAB>nome' dos leads que ja existem no CRM")
    parser.add_argument("--donos", default="",
                        help="arquivo com um telefone por linha que ja tem assigned_to")
    parser.add_argument("--optouts", required=True,
                        help="JSON telefone -> {data, texto} contendo APENAS opt-outs que "
                             "ainda NAO estao marcados (opt_out=false) no banco — a contagem "
                             "deste arquivo e usada como assercao exata no SQL gerado. "
                             "Quem ja esta marcado deve ir em --optouts-ja-marcados.")
    parser.add_argument("--optouts-ja-marcados", default="",
                        help="arquivo com um telefone por linha ja marcado opt_out=true no "
                             "banco; qualquer telefone aqui presente e removido da lista de "
                             "--optouts para a contagem de verificacao do SQL nao divergir")
    parser.add_argument("--esperado-novos", type=int, default=None,
                        help="se informado, aborta (sem escrever SQL) se a contagem de leads "
                             "novos nao bater exatamente com este numero")
    parser.add_argument("--esperado-existentes", type=int, default=None,
                        help="se informado, aborta (sem escrever SQL) se a contagem de leads "
                             "existentes nao bater exatamente com este numero")
    parser.add_argument("--saida", required=True, help="diretorio de saida")
    args = parser.parse_args(argv)

    try:
        nomes_crm = carregar_nomes_crm(args.nomes_crm)
    except ValueError as erro:
        print("ERRO: %s" % erro, file=sys.stderr)
        return 1

    donos = set()
    if args.donos and os.path.exists(args.donos):
        with open(args.donos, encoding="utf-8") as fh:
            donos = {l.strip() for l in fh if l.strip()}

    with open(args.optouts, encoding="utf-8") as fh:
        optout_raw = json.load(fh)
    optouts_brutos = [(fone, dado.get("data", ""), dado.get("texto", ""))
                      for fone, dado in optout_raw.items()]

    optouts_ja_marcados = set()
    if args.optouts_ja_marcados and os.path.exists(args.optouts_ja_marcados):
        with open(args.optouts_ja_marcados, encoding="utf-8") as fh:
            optouts_ja_marcados = {l.strip() for l in fh if l.strip()}
    optouts, optouts_pulados = excluir_optouts_ja_marcados(optouts_brutos, optouts_ja_marcados)

    linhas = carregar_disparo(args.disparo)
    master = carregar_master(args.master)
    novos, existentes = enriquecer(linhas, master, nomes_crm, donos)

    # Fix round 1, Finding 1: um humano comparando os numeros impressos so
    # pegaria uma divergencia se soubesse os numeros esperados de cor. Com
    # --esperado-novos/--esperado-existentes, a ferramenta se recusa a
    # escrever qualquer SQL quando a contagem nao bate.
    erros_contagem = []
    if args.esperado_novos is not None and len(novos) != args.esperado_novos:
        erros_contagem.append(
            "novos: esperado %d, obtido %d" % (args.esperado_novos, len(novos)))
    if args.esperado_existentes is not None and len(existentes) != args.esperado_existentes:
        erros_contagem.append(
            "existentes: esperado %d, obtido %d" % (args.esperado_existentes, len(existentes)))
    if erros_contagem:
        print("ERRO: contagem nao bate com o esperado -> %s" % "; ".join(erros_contagem),
              file=sys.stderr)
        return 1

    os.makedirs(args.saida, exist_ok=True)
    caminho_sql = os.path.join(args.saida, "preparar.sql")
    caminho_rb = os.path.join(args.saida, "rollback.sql")
    with open(caminho_sql, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_arquivo(novos, existentes, optouts, NORMALIZACOES))
    with open(caminho_rb, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_rollback())

    print("leads novos:      %d" % len(novos))
    print("leads existentes: %d" % len(existentes))
    print("notas:            %d" % (len(novos) + len(existentes)))
    print("opt-outs:         %d (pulados por ja estarem marcados: %d)" % (
        len(optouts), optouts_pulados))
    print("exclusoes:        %d" % sum(
        1 for d, _, _ in list(novos) + list(existentes) if d["motivo_exclusao"]))
    print("gerado: %s" % caminho_sql)
    print("gerado: %s" % caminho_rb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
