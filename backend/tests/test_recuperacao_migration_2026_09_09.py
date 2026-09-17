"""Guard-rails de DADO do agente ValerIA Recuperação: migração, tags, funil, backfill.

Testar SQL como texto parece pobre. Aqui é o único guard-rail que existe: as
migrações deste repo são aplicadas À MÃO no Supabase (o GitHub Actions sobe imagem,
não roda migration), então uma tag com o nome errado ou uma etapa faltando só
apareceria em produção — e apareceria em SILÊNCIO, que é o problema.

Os três silêncios que estes testes cobrem, todos medidos em 09/09/2026:

1. `add_tags_to_lead` (leads/service.py) resolve tag por NOME EXATO e nunca cria
   tag. Um nome divergente entre flows.py e o seed devolve sem erro, sem log e sem
   vínculo. O desfecho de 1.208 leads sumiria do CRM sem uma linha de exceção.
   → `TestTagsDoDesfecho` lê os dois lados e trava a igualdade.

2. `create_deal` (leads/service.py:1131-1147) resolve pipeline por `.eq("name", ...)`
   e, não achando, cai calado no fallback "primeiro pipeline por order_index" — e
   SEIS funis empatam em order_index = 0. Foi assim que 19 deals automáticos de
   reposição foram parar em "Valeria - Importação Leads Frios" entre 07/08 e
   04/09/2026, invisíveis para o João.
   → `TestPipelineDeReposicao` trava a constante contra o nome real.

3. O template T-B da campanha (`"a última compra da {{2}} foi em {{3}} — {{4}}"`)
   lê `{{4}}` de `leads.metadata.produto_top1`, chave que HOJE não existe: o dado só
   está em texto livre em `lead_notes`. Sem backfill o template perde a única
   alavanca de memória concreta que tem.
   → `TestBackfillMetadata` exercita a lógica pura do promotor.

4. `pipeline_stages.conversion_event` não é rótulo, é GATILHO: entrar na etapa faz
   `automation/triggers.py:35-44` gravar uma linha em `conversion_events`, e
   `build_timeseries` (`campaigns/conversion_analytics.py:33-51`) soma
   qualified/opportunity/purchase de TODOS os funis na série de conversão de
   ANÚNCIO do Dashboard. Marcar "Quer repor" como 'qualified' inflaria, em
   silêncio, o número que decide verba de tráfego.
   → `TestNaoPoluiSerieDeAnuncio` trava o NULL e demonstra o mecanismo.

5. Corrigir a constante do funil de reposição estanca o sangramento e não devolve
   os 19 deals que já foram parar no funil errado. O corretivo é um .sql para
   revisão humana — e um .sql corretivo que ninguém trava desalinha do código na
   primeira mudança de título/constante, calado.
   → `TestCorretivoDosDealsExtraviados` amarra o script ao código que o gerou.
"""
import csv
import re
import sys
from datetime import date
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MIGRACOES = RAIZ / "supabase" / "migrations"

sys.path.insert(0, str(RAIZ / "scripts" / "recuperacao"))

import backfill_metadata  # noqa: E402
from app.button_flow import flows  # noqa: E402

SQL_STAGES = MIGRACOES / "20260909_recuperacao_stages_optout.sql"
SQL_AGENTE = MIGRACOES / "20260820_button_flow_agent.sql"
SQL_CORRETIVO = RAIZ / "scripts" / "recuperacao" / "corrigir_deals_reposicao.sql"

# Funil Reativação Bling — 1.208 leads importados do ERP em 14/08/2026.
PIPELINE = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"

# Os dois funis do incidente dos 19 deals, conferidos por SELECT em 09/09/2026.
FUNIL_FRIO = "a9487d77-ae93-42fe-89b8-9747d5e9cdf4"       # Valeria - Importação Leads Frios
# O id não muda: só o RÓTULO mudou, duas vezes (09/09 e 10/09/2026) — primeiro o
# nome estava invertido, depois ganhou o sufixo "Atacado" quando surgiu o segundo
# funil de reposição (Private Label, Task 6). Prova de que o contrato não pode ser
# por nome — ver TestPipelineDeReposicao abaixo.
FUNIL_REPOSICAO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"  # João - Reposição Atacado
ETAPA_NOVO = "07b4a308-c2ad-4896-99ee-caee30f926b8"       # "Cliente Ativo" (era "Novo"), order_index 0, key 'novo'
FUNIL_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"    # João - Atacado (origem que gera o card de reposição)


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_STAGES.exists(), f"migração não encontrada em {SQL_STAGES}"
    return SQL_STAGES.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_agente() -> str:
    assert SQL_AGENTE.exists(), f"migração não encontrada em {SQL_AGENTE}"
    return SQL_AGENTE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_corretivo() -> str:
    assert SQL_CORRETIVO.exists(), (
        f"corretivo dos 19 deals extraviados não encontrado em {SQL_CORRETIVO}"
    )
    return SQL_CORRETIVO.read_text(encoding="utf-8")


def _linha_do_values(sql_texto: str, key: str) -> str:
    """A ÚNICA linha de VALUES que declara a etapa `key`. Comentário não conta.

    O casamento é por `l.lstrip().startswith("('")` de propósito: o bloco de
    comentário acima do INSERT cita os nomes dos eventos canônicos ao explicar por
    que não os usa, e um `in sql` cru leria o comentário como se fosse o dado.
    """
    linhas = [
        l for l in sql_texto.splitlines()
        if f"'{key}'" in l and l.lstrip().startswith("('")
    ]
    assert len(linhas) == 1, f"esperava UMA linha de VALUES para {key}, achei {len(linhas)}"
    return linhas[0]


# ── 1. Etapas de desfecho ───────────────────────────────────────────────────
class TestEtapasDeDesfecho:
    @pytest.mark.parametrize("key,label,order_index", [
        ("quer_repor", "Quer repor", 8),
        ("recontato_agendado", "Recontato agendado", 9),
        ("descadastrado", "Descadastrado", 10),
    ])
    def test_as_tres_etapas_com_rotulo_e_posicao(self, sql, key, label, order_index):
        assert f"'{key}'" in sql, f"etapa {key!r} ausente — o desfecho não teria para onde ir"
        linha = _linha_do_values(sql, key)
        # O funil já tem 8 etapas (order_index 0..7); 8/9/10 é o que continua a fila
        # sem embaralhar as etapas de recência, que são a segmentação da campanha.
        # Regex e não substring porque as colunas são alinhadas com espaço variável.
        assert f"'{label}'" in linha
        assert re.search(rf",\s*{order_index}\s*,", linha), (
            f"order_index {order_index} não aparece na linha de {key}: {linha}")

    def test_no_funil_certo(self, sql):
        assert PIPELINE in sql

    def test_insert_de_etapa_e_idempotente(self, sql):
        # Sem a guarda, reaplicar a migração cria três colunas duplicadas no Kanban
        # do João — e o Kanban não distingue "Quer repor" de "Quer repor".
        # A guarda tem que ser por (pipeline_id, key): por `id` deixaria passar uma
        # etapa criada antes pela UI, que teria outro uuid.
        trecho = sql[sql.index("INSERT INTO pipeline_stages"):]
        assert "WHERE NOT EXISTS" in trecho
        assert "s.key = v.key" in trecho
        assert "s.pipeline_id" in trecho


# ── 1b. A etapa de desfecho não pode entrar na régua do tráfego pago ────────
# VOCABULÁRIO canônico de conversão: 20260702_conversion_attribution.sql:16 —
# lead|qualified|opportunity|purchase.
EVENTOS_CANONICOS = ("lead", "qualified", "opportunity", "purchase")


class TestNaoPoluiSerieDeAnuncio:
    """A versão anterior desta migração marcava "Quer repor" com 'qualified'.

    `conversion_event` não é um rótulo descritivo, é um GATILHO: entrar na etapa faz
    `automation/triggers.py:35-44` chamar `fire_conversion_for_deal_stage`, que grava
    a linha em `conversion_events` e despacha o evento para a Meta. E quem lê essa
    tabela é a série de conversão de ANÚNCIO do Dashboard
    (`campaigns/conversions_router.py:15-18` → `conversion_dashboard`), que soma os
    eventos SEM filtro de funil.

    Medido em produção em 09/09/2026: `conversion_events` tem ZERO linhas e NENHUMA
    etapa do banco tem `conversion_event` preenchido — "Quer repor" seria a primeira
    e a única, e a régua de verba de tráfego passaria a ser 100% cliques de um bot de
    reativação de base própria.
    """

    @pytest.mark.parametrize("key", ["quer_repor", "recontato_agendado", "descadastrado"])
    def test_nenhuma_das_tres_etapas_dispara_conversao(self, sql, key):
        linha = _linha_do_values(sql, key)
        for evento in EVENTOS_CANONICOS:
            assert f"'{evento}'" not in linha, (
                f"etapa {key!r} marcada como conversão de anúncio ({evento!r}): "
                "cada entrada viraria uma linha em conversion_events e entraria na "
                "série do Dashboard de Ads"
            )
        assert "NULL" in linha, (
            f"a linha de {key!r} precisa declarar conversion_event explicitamente "
            "como NULL — omitir a coluna esconde a decisão"
        )

    def test_o_cast_do_null_esta_declarado(self, sql):
        # As três linhas do VALUES ficaram sem literal nesta coluna; sem um
        # `NULL::text` o Postgres não infere o tipo e o INSERT morre com
        # "column conversion_event is of type text but expression is of type unknown".
        assert "NULL::text" in _linha_do_values(sql, "quer_repor")

    def test_a_serie_do_dashboard_nao_filtra_por_funil(self):
        """O MECANISMO do defeito, exercitado: qualquer 'qualified' entra na série.

        Não há como `build_timeseries` distinguir a origem — ele recebe
        `select("event, created_at")` (conversion_analytics.py:106-109), sem funil,
        sem deal, sem lead. Um clique de botão da recuperação seria indistinguível
        de uma conversão de anúncio no gráfico.
        """
        from app.campaigns import conversion_analytics as ca

        evento_da_recuperacao = {
            "event": "qualified",  # o que 'quer_repor' geraria
            "created_at": "2026-09-09T15:00:00+00:00",
        }
        serie = ca.build_timeseries(
            [evento_da_recuperacao], days=1, today=date(2026, 9, 9)
        )
        assert serie[0]["qualified"] == 1, (
            "se este assert cair, o mecanismo mudou e a justificativa do NULL "
            "precisa ser reavaliada"
        )

    def test_um_evento_fora_do_vocabulario_tambem_nao_serve(self):
        """Por que não inventar um evento próprio ('recuperacao_quer_repor').

        Ele ficaria fora da série (test acima), mas dois consumidores caem no nome
        CRU quando não reconhecem o evento: o CAPI mandaria um evento inventado para
        a Meta, e o CSV de conversões offline escreveria esse nome na coluna
        "Conversion Name" — uma ação inexistente reprova o arquivo inteiro no Google
        Ads. Dispara só para lead com ctwa_clid/gclid; 1 dos 1.208 tem ctwa_clid.
        """
        from app.campaigns.capi_dispatcher import meta_event_name
        from app.campaigns.google_export import conversion_name_for

        inventado = "recuperacao_quer_repor"
        assert meta_event_name(inventado) == inventado
        assert conversion_name_for(inventado) == inventado


# ── 2. Evidência de opt-out ─────────────────────────────────────────────────
class TestColunasDeOptOut:
    @pytest.mark.parametrize("coluna,tipo", [
        ("opt_out_at", "timestamptz"),
        ("opt_out_channel", "text"),
        ("opt_out_evidence", "jsonb"),
    ])
    def test_coluna_criada_de_forma_idempotente(self, sql, coluna, tipo):
        assert f"ADD COLUMN IF NOT EXISTS {coluna}" in sql
        linha = next(l for l in sql.splitlines() if f"ADD COLUMN IF NOT EXISTS {coluna}" in l)
        assert tipo in linha

    @pytest.mark.parametrize("coluna", ["opt_out_at", "opt_out_channel", "opt_out_evidence"])
    def test_cada_coluna_tem_comment(self, sql, coluna):
        # O COMMENT não é decoração: é onde vive o vocabulário de opt_out_channel e
        # o formato de opt_out_evidence. Quem for defender o legítimo interesse na
        # ANPD lê o schema, não este arquivo.
        assert f"COMMENT ON COLUMN leads.{coluna} IS" in sql

    def test_nenhuma_coluna_e_not_null(self, sql):
        # Os opt-outs anteriores a 09/09/2026 não têm data nem evidência. NOT NULL
        # obrigaria a forjar uma — pior do que admitir a lacuna.
        trecho = sql[sql.index("ALTER TABLE leads"):sql.index("COMMENT ON COLUMN leads.opt_out_at")]
        assert "NOT NULL" not in trecho

    def test_recarrega_o_cache_do_postgrest(self, sql):
        # Sem o reload, um UPDATE em leads.opt_out_at responde PGRST204
        # ("column not found") mesmo com a coluna já criada.
        assert "NOTIFY pgrst, 'reload schema';" in sql


# ── 3. Tags do desfecho: o seed tem que espelhar flows.py ───────────────────
def _tags_do_fluxo() -> list[str]:
    """Todo nome de tag que o motor pode pedir. Derivado de flows.py, nunca copiado.

    Copiar as strings para cá recriaria exatamente o bug que este teste existe para
    pegar: os dois lados poderiam divergir e o teste continuaria verde.
    """
    return [
        flows.TAG_QUENTE, flows.TAG_RECUSOU, flows.TAG_HUMANO,
        flows.TAG_CADASTRO_MANTIDO, flows.TAG_ENGANO,
        *(p.tag for p in flows.PRAZOS),
    ]


class TestTagsDoDesfecho:
    @pytest.mark.parametrize("tag", _tags_do_fluxo())
    def test_toda_tag_do_fluxo_esta_semeada(self, sql_agente, tag):
        assert f"('{tag}'," in sql_agente, (
            f"tag {tag!r} não semeada em 20260820_button_flow_agent.sql — "
            "add_tags_to_lead a ignoraria sem erro e sem log"
        )

    def test_sao_oito(self):
        # Se um desfecho novo entrar em flows.py sem tag no seed, o teste acima já
        # pega. Este aqui pega o contrário: alguém apagar um desfecho e esquecer o
        # seed, deixando tag órfã no banco.
        assert len(_tags_do_fluxo()) == 8

    @pytest.mark.parametrize("antiga", [
        "Reativação: Quente", "Reativação: 1 mês", "Reativação: 3 meses",
        "Reativação: 6 meses", "Reativação: Recusou", "Reativação: Atendimento humano",
    ])
    def test_nomes_antigos_sumiram_do_seed(self, sql_agente, antiga):
        # O seed original usava "Reativação: ..." e prazos em meses. Deixar os dois
        # conjuntos no arquivo criaria 14 tags, das quais 6 nunca receberiam vínculo
        # — lixo permanente numa tabela que a UI de filtro lista inteira.
        assert f"('{antiga}'," not in sql_agente

    def test_prazos_sao_em_dias(self):
        # 30/60/90 e não 1/3/6 meses: o intervalo médio entre compras desta coorte
        # é 78-122 dias, então 90 é o ciclo natural.
        assert [p.dias for p in flows.PRAZOS] == [30, 60, 90]

    def test_o_comentario_de_flows_aponta_para_a_migracao_que_semeia(self, sql, sql_agente):
        """O ponteiro do comentário tem que levar ao arquivo onde o seed está.

        Ele dizia "semeadas em 20260909_recuperacao_stages_optout.sql" e estava
        errado: aquela migração cria as ETAPAS e as colunas de opt-out, e a §3 dela é
        só uma nota dizendo que as tags NÃO moram lá. Quem fosse conferir um nome de
        tag pelo comentário abriria o arquivo errado — e nome divergente não levanta
        nada: `add_tags_to_lead` resolve por nome exato e devolve em silêncio.
        """
        fonte = Path(flows.__file__).read_text(encoding="utf-8")
        linha = next(l for l in fonte.splitlines() if "Tags de desfecho" in l)
        assert "20260820_button_flow_agent.sql" in linha, linha
        assert "20260909_recuperacao_stages_optout.sql" not in linha, linha
        # E o ponteiro tem que ser VERDADE, não só consistente consigo mesmo:
        # as tags estão no arquivo apontado e em nenhum outro.
        for tag in _tags_do_fluxo():
            assert f"('{tag}'," in sql_agente
            assert f"('{tag}'," not in sql


# ── 4. O funil de reposição ─────────────────────────────────────────────────
class TestPipelineDeReposicao:
    """Task 6 (10/09/2026): o nome do funil mudou DE NOVO — "João - Reposição" virou
    "João - Reposição Atacado" e passou a existir um segundo funil de reposição
    (Private Label). REPOSICAO_PIPELINE_NAME foi REMOVIDA: reposicao.py não resolve
    mais o destino por nome, resolve por um MAPA DE UUID indexado pelo funil de
    ORIGEM (reposicao.reposicao_pipeline_para). A guarda original — "o card de
    reposição vai para o funil de reposição certo, não para qualquer um" — não
    desapareceu, só trocou de mecanismo: o nome já quebrou em silêncio duas vezes
    (09/09 e 10/09/2026); UUID não muda quando alguém edita o rótulo na tela.
    """

    def test_atacado_resolve_para_o_funil_de_reposicao_real(self):
        # Sucessor de test_nome_bate_com_o_funil_real: em vez de comparar uma
        # constante de nome com uma string, confere que a função de mapa resolve a
        # origem real (João - Atacado) para o destino real — o MESMO id
        # (79e35e6b-...) que esta suíte já travava em 09/09/2026; só o rótulo mudou.
        from app.leads import reposicao
        assert reposicao.reposicao_pipeline_para(FUNIL_ATACADO) == FUNIL_REPOSICAO

    def test_origem_desconhecida_nao_cai_em_fallback_silencioso(self):
        # Sucessor de test_o_nome_invertido_nao_volta: lá, um nome errado não
        # levantava nada — create_deal caía calado no fallback "primeiro pipeline por
        # order_index" (foi assim que 19 deals foram parar no funil errado). Aqui não
        # existe fallback nenhum: origem fora do mapa devolve None, e
        # ensure_reposicao_deal (fail-closed) não cria o card.
        from app.leads import reposicao
        assert reposicao.reposicao_pipeline_para("00000000-0000-0000-0000-000000000000") is None


# ── 4b. O corretivo dos 19 deals já extraviados ─────────────────────────────
class TestCorretivoDosDealsExtraviados:
    """Consertar a constante estanca o sangramento; não devolve os 19 deals.

    Eles continuam em "Valeria - Importação Leads Frios" (owner NULL), invisíveis
    para o João, que é dono de "João - Reposição". O corretivo é um .sql para
    revisão e aplicação MANUAL — nunca executado por agente.

    O que estes testes travam não é o SQL (ninguém roda SQL aqui): é o ALINHAMENTO
    entre o script e o código que gerou o problema. Um corretivo que seleciona por
    `title = 'Reposição'` vira um no-op silencioso no dia em que alguém mudar esse
    literal em reposicao.py — e ninguém percebe, porque o script já foi lido e
    aprovado.
    """

    def test_o_arquivo_existe(self):
        assert SQL_CORRETIVO.exists(), (
            f"{SQL_CORRETIVO} não existe — os 19 deals continuam no funil errado"
        )

    def test_avisa_que_nao_pode_ser_executado_sem_autorizacao(self, sql_corretivo):
        # Mesmo contrato de scripts/recuperacao/honrar_optouts_pendentes.sql: o
        # arquivo escreve em PRODUÇÃO e o alvo é o funil de trabalho do vendedor.
        cabecalho = sql_corretivo[:2000]
        assert "NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO" in cabecalho
        assert "Nenhum agente de IA deve rodar" in cabecalho
        assert "PRODUÇÃO" in cabecalho

    def test_declara_quantas_linhas_afeta(self, sql_corretivo):
        # Medido por leitura em produção em 09/09/2026, não de cabeça.
        assert "19 deals" in sql_corretivo
        assert "19 leads distintos" in sql_corretivo

    def test_o_seletor_casa_com_o_titulo_que_o_codigo_grava(self, sql_corretivo):
        # `ensure_reposicao_deal` chama create_deal(title="Reposição"). Se esse
        # literal mudar, o WHERE do corretivo passa a casar zero linhas.
        from app.leads import reposicao
        fonte = Path(reposicao.__file__).read_text(encoding="utf-8")
        assert 'title="Reposição"' in fonte
        assert "d.title = 'Reposição'" in sql_corretivo

    def test_o_destino_e_o_funil_da_constante_na_etapa_de_entrada(self, sql_corretivo):
        # Task 6 (10/09/2026): REPOSICAO_PIPELINE_NAME foi removida — reposicao.py
        # resolve o destino por UUID, não por nome (ver TestPipelineDeReposicao). A
        # guarda "o script tem que nomear o funil de destino para quem revisa
        # conferir" sobrevive na asserção de FUNIL_REPOSICAO abaixo, que já era por
        # UUID (quem era por NOME era a constante do módulo, não o script). Medido em
        # produção em 10/09/2026: o corretivo segue executável sem qualquer alteração
        # — o UUID do funil (79e35e6b-...) e o UUID da etapa (07b4a308-..., ETAPA_NOVO)
        # não mudaram; só os RÓTULOS mudaram ("João - Reposição" → "...Atacado";
        # "Novo" → "Cliente Ativo"). É exatamente por isso que o script seleciona por
        # UUID, não por rótulo.
        assert FUNIL_REPOSICAO in sql_corretivo, (
            "o script tem que nomear o funil de destino (por UUID) para quem revisa conferir"
        )
        assert ETAPA_NOVO in sql_corretivo
        # E a etapa não pode estar chumbada sem conferência: create_deal resolve a
        # primeira NÃO-protegida por order_index, e o board do João é editável na UI.
        assert "is_protected = false" in sql_corretivo
        assert "ORDER BY s.order_index" in sql_corretivo

    def test_a_origem_e_so_o_funil_frio(self, sql_corretivo):
        # Não tocar em nada que já esteja no lugar certo.
        assert FUNIL_FRIO in sql_corretivo

    def test_so_move_card_aberto_e_comprovadamente_automatico(self, sql_corretivo):
        # Errar aqui mexe no funil de trabalho do vendedor: cada critério exclui uma
        # forma de "alguém já assumiu este card".
        for criterio in (
            "d.closed_at IS NULL",
            "d.assigned_to IS NULL",
            "d.category IS NULL",
            "coalesce(d.value, 0) = 0",
            "d.updated_at - d.created_at < interval '1 minute'",
        ):
            assert criterio in sql_corretivo, f"critério ausente: {criterio}"

    def test_tem_conferencia_antes_e_depois(self, sql_corretivo):
        assert "=== ANTES" in sql_corretivo
        assert "=== DEPOIS" in sql_corretivo
        # A conferência DEPOIS tem que provar o que mais importa: ninguém ficou com
        # dois cards abertos (o duplicado que `dedupe_open` existe para evitar).
        assert "cards_abertos" in sql_corretivo
        assert "HAVING count(*) > 1" in sql_corretivo
        # …e tem que agrupar por lead_id, não por nome: entre os 19 há DOIS leads
        # distintos chamados "Edson", que agrupados por nome viram um falso duplicado
        # e reprovariam uma correção correta.
        assert "GROUP BY l.id, l.name" in sql_corretivo

    def test_e_transacional_com_guarda_de_teto(self, sql_corretivo):
        assert "BEGIN;" in sql_corretivo and "COMMIT;" in sql_corretivo
        assert "RAISE EXCEPTION" in sql_corretivo
        assert "alvo > 50" in sql_corretivo, (
            "sem teto, um WHERE que passe a casar meio banco moveria meio banco"
        )
        assert "alvo = 0" in sql_corretivo, (
            "zero linhas tem que abortar: ou já foi aplicado, ou o WHERE mudou"
        )

    def test_nao_cria_deal_nem_escreve_fora_de_deals(self, sql_corretivo):
        # Todos os 19 leads já têm o card; inventar cards novos num backfill
        # histórico só enche o funil de ruído. E nada aqui é assunto de leads/sales.
        assert "INSERT INTO" not in sql_corretivo.upper()
        assert "DELETE" not in sql_corretivo.upper()
        for tabela in ("leads", "sales", "conversion_events", "lead_tags", "messages"):
            assert not re.search(rf"UPDATE\s+{tabela}\b", sql_corretivo), tabela

    def test_nao_toca_a_coluna_legada_stage(self, sql_corretivo):
        # `deals.stage` está CONGELADA (leads/service.py:270-275) e o precedente de
        # mover deal em massa — move_lead_deals_to_blacklist — também não a toca.
        # Escrever nela criaria um segundo lugar de verdade para a mesma informação.
        assert not re.search(r"\bstage\b\s*=", sql_corretivo)

    def test_tem_rollback(self, sql_corretivo):
        assert "ROLLBACK" in sql_corretivo.upper()


# ── 5. Backfill de metadata ─────────────────────────────────────────────────
CABECALHO = (
    "id_bling;nome;cidade;uf;ticket_medio;pedidos_faturados;dias_sem_comprar;"
    "ultima_compra;produto_top1;qtd_top1"
)


def _csv_fixture(tmp_path: Path, *linhas: str) -> Path:
    caminho = tmp_path / "bling.csv"
    caminho.write_text("\n".join((CABECALHO, *linhas)) + "\n", encoding="utf-8-sig")
    return caminho


def _linha(**kw) -> dict:
    base = {
        "id_bling": "5845664414", "nome": "360 IMP E DISTRIBUIDORA LTDA",
        "cidade": "Lajeado", "uf": "RS", "ticket_medio": "3207,00",
        "pedidos_faturados": "126", "dias_sem_comprar": "1109",
        "ultima_compra": "2023-07-26",
        "produto_top1": "Café Canastra Clássico Moído 250g", "qtd_top1": "1190",
    }
    base.update(kw)
    return base


class TestBackfillMetadata:
    def test_le_o_csv_com_bom_e_ponto_e_virgula(self, tmp_path):
        caminho = _csv_fixture(
            tmp_path,
            "1;Alfa;Lajeado;RS;3207,00;126;1109;2023-07-26;Café Clássico;1190",
            "2;Beta;Uberlândia;MG;80,00;1;136;2026-03-25;Kit Degustação;1",
        )
        indice = backfill_metadata.carregar_csv(caminho)
        assert set(indice) == {"1", "2"}
        # O acento tem que sobreviver: é ele que vai para dentro da mensagem.
        assert indice["2"]["cidade"] == "Uberlândia"

    def test_linha_sem_id_bling_e_descartada(self, tmp_path):
        caminho = _csv_fixture(
            tmp_path,
            ";Sem id;Lajeado;RS;10,00;1;1;2023-07-26;Café;1",
            "7;Com id;Lajeado;RS;10,00;1;1;2023-07-26;Café;1",
        )
        # Sem chave não há como casar com o CRM — entrar no índice com chave ""
        # faria toda linha sem id sobrescrever a anterior, em silêncio.
        assert set(backfill_metadata.carregar_csv(caminho)) == {"7"}

    def test_patch_completo(self):
        patch = backfill_metadata.patch_do_lead(_linha())
        assert patch == {
            "produto_top1": "Café Canastra Clássico Moído 250g",
            "produto_top1_qtd": 1190,
            "cidade_uf": "Lajeado/RS",
            # '3207,00' é formato BR: 3207.0, não 3.20700.
            "ticket_medio": 3207.0,
            "pedidos_faturados": 126,
            "dias_sem_comprar": 1109,
            "data_ultima_compra": "2023-07-26",
            "bling_snapshot": "2026-08-08",
        }

    def test_carimba_a_data_do_snapshot(self):
        # dias_sem_comprar é um número CONGELADO em 08/08/2026. Quem for montar a
        # mensagem tem que recalcular a recência de `sales` no disparo — 15 leads da
        # coorte compraram DEPOIS do corte do CSV, um em 06/09. Sem o carimbo, o
        # consumidor não tem como saber a idade do dado.
        assert backfill_metadata.patch_do_lead(_linha())["bling_snapshot"] == "2026-08-08"

    def test_chave_vazia_fica_fora_do_patch(self):
        patch = backfill_metadata.patch_do_lead(
            _linha(produto_top1="", qtd_top1="0", ticket_medio="0,00",
                   pedidos_faturados="0", dias_sem_comprar="0", cidade="", uf="")
        )
        # Gravar "" ou 0 é pior que não gravar: o renderizador checa PRESENÇA, e
        # produto_top1="" renderiza "você levava  — hoje ele está…" com um buraco.
        # E 0 pedidos é informação falsa nos 103 `lead_sem_compra` da coorte.
        assert patch == {"bling_snapshot": "2026-08-08",
                         "data_ultima_compra": "2023-07-26"}

    def test_produto_sem_quantidade_ainda_entra(self):
        patch = backfill_metadata.patch_do_lead(_linha(qtd_top1=""))
        assert patch["produto_top1"] == "Café Canastra Clássico Moído 250g"
        assert "produto_top1_qtd" not in patch

    def test_data_sentinela_do_bling_nao_entra(self):
        # O Bling usa '0000-00-00' (e variantes de ano zero) como "não definida".
        # Gravá-la faria o template dizer "sua última compra foi em 00/00/0000".
        for sentinela in ("0000-00-00", "0000-01-01", "", "n/a"):
            patch = backfill_metadata.patch_do_lead(_linha(ultima_compra=sentinela))
            assert "data_ultima_compra" not in patch, sentinela

    def test_cidade_uf_nunca_tem_barra_solta(self):
        # Cadastros estrangeiros do Bling vêm com uf='EX' e cidade às vezes vazia.
        assert backfill_metadata.cidade_uf({"cidade": "Santa Fe", "uf": "EX"}) == "Santa Fe/EX"
        assert backfill_metadata.cidade_uf({"cidade": "", "uf": "EX"}) == "EX"
        assert backfill_metadata.cidade_uf({"cidade": "Lajeado", "uf": ""}) == "Lajeado"
        assert backfill_metadata.cidade_uf({"cidade": "", "uf": ""}) == ""

    def test_diferenca_so_devolve_o_que_muda(self):
        patch = {"produto_top1": "Café", "ticket_medio": 10.0}
        assert backfill_metadata.diferenca({"produto_top1": "Café"}, patch) == {
            "ticket_medio": 10.0}
        assert backfill_metadata.diferenca({"produto_top1": "Chá"}, patch) == patch
        assert backfill_metadata.diferenca(dict(patch), patch) == {}
        assert backfill_metadata.diferenca(None, patch) == patch

    def test_update_preserva_o_metadata_existente(self):
        # `SET metadata = '<json>'` apagaria id_bling, lote e origem — e com eles o
        # alvo do rollback do lote de 14/08 (lote_completo.py:montar_rollback).
        sql = backfill_metadata.sql_update([("abc-123", {"produto_top1": "Café"})])
        assert "metadata = COALESCE(l.metadata, '{}'::jsonb) || v.patch::jsonb" in sql
        assert "abc-123" in sql

    def test_update_escapa_apostrofo_do_nome_do_produto(self):
        # Há produto com apóstrofo no catálogo do Bling; sem o escape, o UPDATE
        # vira SQL quebrado — ou pior, injetável.
        sql = backfill_metadata.sql_update([("abc", {"produto_top1": "Cafe d'Or"})])
        assert "d''Or" in sql

    def test_o_default_e_dry_run(self):
        # O script escreve em PRODUÇÃO. `--apply` tem que ser explícito, e o
        # argumento tem que ser store_true (um `--apply=false` que ligasse a
        # escrita seria o pior default possível).
        fonte = Path(backfill_metadata.__file__).read_text(encoding="utf-8")
        assert '"--apply", action="store_true"' in fonte
        assert "if not args.apply:" in fonte


def test_o_csv_de_producao_existe_e_casa_por_id_bling():
    """O arquivo real é a fonte do backfill; sem ele o T-B perde a variável 4.

    Não é um teste de dado (o CSV não está versionado em todo checkout) — é um
    smoke test do formato quando ele existe: separador ';', BOM utf-8, e a coluna
    de junção `id_bling` presente e única.
    """
    caminho = RAIZ / "leads-bling-completo-2026-08-08-br (1).csv"
    if not caminho.exists():
        pytest.skip("CSV do Bling não está neste checkout")
    indice = backfill_metadata.carregar_csv(caminho)
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
    assert len(indice) == len(linhas), "id_bling duplicado no CSV — o join escolheria um a esmo"
    assert len(indice) > 2000


# ── 4c. O corretivo de 09/09 foi substituído pelo de 16/09/2026 ─────────────
class TestCorretivoAntigoMarcadoComoSupersedido:
    """scripts/recuperacao/corrigir_deals_reposicao.sql (09/09/2026) só conhece
    UM destino (João - Reposição Atacado, funil e etapa cravados por UUID) —
    foi escrito um dia ANTES de existir o funil "João - Reposição Private
    Label" (10/09/2026, ver `_ORIGEM_PARA_REPOSICAO` em
    backend/app/leads/reposicao.py). Aplicado hoje, mandaria para o funil
    errado todo card cuja venda de origem fosse Private Label. Nunca foi
    aplicado.

    O substituto (scripts/corrige_cards_reposicao_extraviados.sql, 16/09/2026,
    guardado por test_sql_cards_extraviados_2026_09_16.py) resolve o destino de
    CADA card pelo funil de origem da venda do próprio lead. O arquivo antigo
    não é apagado — ele documenta o incidente de 09/09 e o resto desta suíte
    (TestCorretivoDosDealsExtraviados, acima) trava o conteúdo dele — só ganha
    um aviso no topo para que ninguém o aplique por engano supondo que é o
    corretivo vigente.
    """

    SUBSTITUTO = "scripts/corrige_cards_reposicao_extraviados.sql"

    def test_comeca_com_aviso_supersedido(self, sql_corretivo):
        inicio = sql_corretivo[:200].upper()
        assert "SUPERSEDIDO" in inicio, (
            "o arquivo tem que COMEÇAR com o aviso — é a primeira coisa que "
            "quem abre o arquivo precisa ver, antes até do aviso de autorização"
        )

    def test_aponta_o_substituto_pelo_caminho(self, sql_corretivo):
        cabecalho = sql_corretivo[:2000]
        assert self.SUBSTITUTO in cabecalho

    def test_explica_o_defeito_do_destino_unico(self, sql_corretivo):
        cabecalho = sql_corretivo[:2000].lower()
        # Não basta dizer SUPERSEDIDO: tem que dizer o porquê — destino único
        # e escrito antes de existir o funil Private Label.
        assert "único destino" in cabecalho
        assert "private label" in cabecalho
        assert "10/09/2026" in sql_corretivo[:2000]

    def test_aviso_novo_nao_empurra_o_aviso_de_autorizacao_para_fora_do_cabecalho(
        self, sql_corretivo
    ):
        # O cabeçalho novo não pode deslocar "NÃO EXECUTAR SEM AUTORIZAÇÃO..."
        # para fora da janela [:2000] que test_avisa_que_nao_pode_ser_executado_
        # sem_autorizacao (acima, em TestCorretivoDosDealsExtraviados) audita.
        cabecalho = sql_corretivo[:2000]
        assert "NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO" in cabecalho

    def test_arquivo_continua_existindo_com_o_conteudo_original(self, sql_corretivo):
        # Task 11b não apaga o script nem o corretivo em si — só acrescenta um
        # cabeçalho. O UPDATE original e a transação continuam lá.
        assert "UPDATE deals d" in sql_corretivo
        assert "BEGIN;" in sql_corretivo and "COMMIT;" in sql_corretivo
