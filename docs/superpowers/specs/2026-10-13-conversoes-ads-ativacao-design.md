# Ativação da devolução de conversões para Meta e Google Ads — spec

**Data:** 2026-10-13
**Cartão:** "O dado de fechado ganho precisa voltar pro google e pra Meta" (23ab1cc4, quadro BEEINSIDE CANSTRA CRM)
**Branch:** `agente/23ab1cc4`, criado de `feat/conversoes-ads` (6b0318bd, que existia só na VPS em
`/root/crm-wt/conversoes-ads`)
**Base:** `2026-10-08-conversoes-ads-design.md` (mesmo branch) — esta spec não redesenha; termina, corrige
e publica.

---

## 1. Problema

Nas palavras do Rafael: "o dado de fechado ganho precisa voltar pro Google e pra Meta". O código para isso
foi escrito em 07–08/10 (`feat/conversoes-ads`, 36 commits, 7.272 testes de backend passando), mas nunca
saiu da VPS: não está no GitHub, nem no `master`, nem em produção. A migration `20261008_ad_conversions.sql`
já foi aplicada no banco (tabelas `ad_conversions` e `ad_conversion_values` existem, vazias). Faltava a
configuração nas plataformas, que foi feita nesta sessão (§3).

## 2. Decisões desta sessão

| Tema | Decisão |
|---|---|
| Escopo | Terminar e publicar `feat/conversoes-ads` como está na spec de 08/10, com as correções da §4. |
| Etapas enviadas | **Qualificado, Oportunidade e Venda** para Meta e Google. A etapa **Lead (clique) não vai ao Google**: já é contada pelas conversões do site ("Atacado 2 obg", "Terceirização 2 Obg") e por "Leads de mensagens"; mandar de novo contaria a mesma pessoa duas vezes. Para a Meta ela já não ia. |
| Valor | **Venda com o valor real do pedido. Qualificado e Oportunidade sem valor** (só contagem). Pesquisa de mercado (Kommo manda Lead sem valor e Purchase com valor; HubSpot/agências usam valor esperado = ticket × taxa de fechamento, ou nenhum valor quando não há histórico confiável). O valor esperado calculado do nosso histórico deu R$ 0,39–3,54 por qualificado — irrelevante. `ad_conversion_values` fica vazia; reavaliar em ~90 dias. |
| Google — ações | Lead_Qualificado `7832684373`, Oportunidade_Criada `7832557577`, Venda_Fechada `7832537162` (todas `UPLOAD_CLICKS`, conta 186-141-6291 via MCC 364-380-9068). A Tati deixou Venda_Fechada e Lead_Qualificado como **principais** em 13/10. |
| Meta — token | Reusa o token do canal `meta_cloud` (system user **Sistema_API**), que já tem `whatsapp_business_manage_events`. Não há token novo. |
| Meta — dataset | `950217978158864`, criado em 13/10 pelo `criar_dataset_meta` e ligado ao WABA `1399531671927018`. Fica no portfólio dono do WABA, **"Café Canastra Torrefação de Cafés Especiais"** (`1338125734024745`); o Rafael tem acesso pela conta principal. |

## 3. Já feito nesta sessão (fora do código)

- Google Cloud, projeto **GAds-CRM** (conta canastrainteligencia@gmail.com): **Data Manager API ativada**.
  App OAuth já estava "Em produção".
- **Refresh token novo** com `adwords` + `datamanager`, gerado pela conta canastrainteligencia (que acessa a
  MCC). Testado: Google Ads API 200; Data Manager `validateOnly` 200 nas 3 ações.
- **Dataset Meta criado** (950217978158864). Eventos de teste com o código ativo `TEST28277` chegaram na aba
  Testar eventos (confirmado pelo Rafael).
- Tudo guardado em `/root/.secrets/conversoes-ads.env` (root, 600) na VPS. **O `.env` de produção não foi
  tocado.**
- **Incidente:** antes do código ativo, 3 eventos com código de teste inventado foram processados como
  **reais** pela Meta (LeadSubmitted, InitiateCheckout, Purchase de R$ 1, lead `9bb78dc2`). Não há como
  desfazer. Regra daqui em diante: Meta só com o código ativo da aba Testar eventos.

## 4. O que muda no código

Repo: `ValerIA` (maquina-de-vendas). Arquivos em `backend/app/conversions/`.

1. **`google.py` — `eventSource` obrigatório (bug).** A Data Manager API responde 400
   `events[0].event_source: REQUIRED_FIELD_MISSING` sem esse campo; com `"eventSource": "OTHER"` as 3 ações
   validam. Incluir `eventSource: "OTHER"` (conversão offline, fechada por WhatsApp/telefone) em
   `build_event`. Teste: payload tem o campo; teste existente do formato atualizado.
2. **`sweep.py` — etapa `lead` não é enfileirada para o Google.** Hoje a varredura cria linhas
   `google/lead` que ficariam `pendente` para sempre (sem `GOOGLE_ADS_CONVERSION_ACTION_LEAD`) e poluiriam a
   aba. Remover a etapa `lead` da varredura (Meta já não a recebia). Teste: rodada de varredura com lead de
   clique Google não cria linha `lead`; as outras etapas seguem.
3. **Merge do `master` atual** (20 commits à frente, sem conflito) no branch.
4. Spec/roteiro: `docs/setup/conversoes-ads.md` ganha os IDs, o portfólio do dataset, a regra do código de
   teste ativo e a etapa lead fora.

Nada muda em frontend além do que já está no branch (aba "Conversões enviadas" no /trafego, só admin).

## 5. Como testar em modo teste

Onde: worktree `agente/23ab1cc4` (local) e um container descartável na VPS com a imagem `canastra-api` e o
código do branch montado (mesmo método usado nesta sessão; não toca nos serviços).

1. **Testes automatizados:** suíte do backend no container (`python -m pytest -q tests`) e do frontend
   (`npm run type-check && npm run test` em `frontend/`). Tudo verde.
2. **Varredura a seco contra o banco de produção:** rodar a função de varredura do branch num container
   descartável **sem gravar** (modo dry-run/contagem) para ver quantas linhas seriam criadas por
   plataforma × etapa nos 90 dias. Esperado: zero `lead`; qualificado/oportunidade/venda com números
   coerentes (referência de 08/10: ~65 repasses com clique por semana; 40 vendas com clique).
3. **Envio de teste por plataforma**, container descartável, `CONVERSIONS_TEST_MODE=true`:
   - Google: `validateOnly` em 1 linha de cada etapa → 200.
   - Meta: com o Rafael de aba Testar eventos aberta e o código **ativo** dela → os eventos aparecem na tela.
     Sem código ativo, não envia.
4. **Print:** aba "Conversões enviadas" do /trafego rodando o frontend do branch localmente
   (`print-frontend.mjs`), mostrando contadores e lista.

## 6. Como publicar

Depois do [Liberar produção]:

1. Merge de `agente/23ab1cc4` em `master` + `git push origin master`. O push dispara o GitHub Actions
   (`deploy.yml`): build de `canastra-api`, `docker stack deploy` de `canastra`, `--force` em api e worker;
   e o mesmo para `crm_crm` (frontend).
2. A migration 20261008 já está aplicada (conferido: tabelas existem). Não reaplicar a 20261006b.
3. Primeiro deploy **com as duas plataformas desligadas** (`CONVERSIONS_*_ENABLED` ausentes). A tarefa
   `conversions-sweep` enche a fila; conferência por SQL (`select platform, stage, status, count(*) from
   ad_conversions group by 1,2,3`).
4. Copiar as variáveis de `/root/.secrets/conversoes-ads.env` para
   `/srv/Maquinadevendascanastra/backend/.env`: `GOOGLE_ADS_REFRESH_TOKEN` (substitui o antigo, que só tinha
   `adwords` — o novo cobre os dois), `META_CAPI_DATASET_ID`, `GOOGLE_ADS_CONVERSION_ACTION_{QUALIFIED,
   OPPORTUNITY,PURCHASE}`; `META_CAPI_ACCESS_TOKEN` = token do canal `meta_cloud`. Backup do `.env` antes
   (`backend/.env.bak-23ab1cc4`). `docker service update --force canastra_api canastra_worker`.
5. Ligar `CONVERSIONS_GOOGLE_ENABLED=true` (Google recebe o histórico de 90 dias), conferir, depois
   `CONVERSIONS_META_ENABLED=true`.

**Voltar atrás:** desligar `CONVERSIONS_*_ENABLED` no `.env` + `service update --force` (para o envio na
hora, a fila fica `pendente`). Para o código: `git revert` do merge em `master` + push (redeploy). O
refresh token antigo fica no backup do `.env`. Eventos já enviados às plataformas não têm como ser
retirados.

## 7. Como testar em produção

- Logs do worker (`docker service logs canastra_worker`) com as linhas `[CONVERSOES]`; contagem por status
  em `ad_conversions` (`enviado`/`erro`/`fora_da_janela`).
- Aba "Conversões enviadas" no /trafego (print).
- Google Ads: as ações deixam de mostrar "Configuração incorreta" e passam a contar conversões importadas
  (pode levar algumas horas).
- Meta: Gerenciador de Eventos do dataset 950217978158864 mostra LeadSubmitted / InitiateCheckout /
  Purchase chegando.

**Ação real com efeito externo:** sim, e é o objetivo do cartão — ao ligar cada plataforma, conversões
**reais** de leads reais (qualificado, oportunidade e venda dos últimos 90 dias no Google, 7 dias na Meta)
passam a ser enviadas e entram nas métricas e nos lances das campanhas. Não há mensagem a cliente, venda,
pedido, NF ou cobrança.

## 8. Fora de escopo

- Valor nas etapas Qualificado/Oportunidade (reavaliar em ~90 dias com dado acumulado).
- Etapa Lead no Google.
- Retirar/cancelar conversão já enviada (venda cancelada depois fica só na aba).
- Os 3 eventos reais de R$ 1 enviados por engano à Meta em 13/10.
- Mudanças de estratégia de lance no Google Ads/Meta (com a Tati).
- Lead sem ID de clique (só telefone) e tráfego de site da Meta (`fbclid`).
