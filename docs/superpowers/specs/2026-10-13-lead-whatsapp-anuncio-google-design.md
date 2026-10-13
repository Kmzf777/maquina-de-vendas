# Lead do botão de WhatsApp do anúncio Google — design

Cartão: "Temos que pegar o dado de quem clica no iniciar conversa na extensão de whatsapp do google" (1b4e178b).
Branch: `agente/1b4e178b`. Repositório: ValerIA.

## Problema

Nas palavras do Rafael: "temos que pegar o dado de quem clica no iniciar conversa na extensão de whatsapp do google".

O anúncio do Google Ads tem o botão de mensagem/WhatsApp ("Iniciar conversa"). Quem clica cai direto no
WhatsApp com o texto pronto **"Olá, encontrei vocês pelo Google e gostaria de obter mais informações."**
Não passa pela landing page, então não chega `gclid` nem UTM. Hoje esse lead aparece como
"WhatsApp direto" (orgânico) e fica fora das contas de leads, ROAS e conversão do Google.

Medido em produção (SELECT, 13/10/2026): desde 01/07/2026, **140 leads** abriram a conversa com esse texto,
**130** estão sem nenhuma origem gravada. Os dos últimos 20 dias (22) chegaram pelo canal Meta Cloud,
sem `referral` (o Google não manda dado de clique ao WhatsApp).

Decisão do Rafael: basta marcar como **Google Ads**, sem identificar a campanha (opção A).

## O que muda

1. **Regra pura** `google_message_asset_tracking(text) -> dict | None` (novo módulo
   `backend/app/leads/google_message_asset.py`):
   - Normaliza o texto (minúsculas, sem acento, espaços colapsados) e reconhece quando ele contém
     `encontrei voces pelo google`.
   - Se reconhecer, devolve `{"utm_source": "google", "utm_medium": "cpc"}`. Se não, devolve `None`.
   - Com `google` + `cpc`, o lead já cai como "Google Ads" no `derive_channel` (backend, /trafego) e no
     `paidPlatform` (frontend, origem em /conversas e /leads), sem mexer nessas telas.
2. **Carimbo na entrada** `stamp_google_message_asset(lead, text)` (mesmo módulo):
   - Só grava se o lead ainda **não tem nenhuma atribuição** (`gclid`, `fbclid`, `ctwa_clid`,
     `meta_ad_id`, `utm_source`, `utm_medium`, `utm_campaign` vazios). Atribuição anterior (LP, CTWA)
     nunca é sobrescrita.
   - Grava `utm_source='google'`, `utm_medium='cpc'`, `traffic_type='paid'` via `update_lead`.
   - Fail-soft: erro só gera log, nunca derruba o registro do lead nem a conversa.
3. **Ligação nos webhooks**: o `_register_lead` da Meta Cloud (`backend/app/webhook/meta_router.py`,
   caminho ativo) e o da Evolution (`backend/app/webhook/router.py`, legado, só uma linha) passam a
   receber o texto da mensagem e chamam `stamp_google_message_asset` depois do `get_or_create_lead`.
   O Dev Router continua antes do parsing (não é tocado).
4. **Correção dos antigos**: script `backend/scripts/backfill_google_message_asset.py`.
   - Por padrão roda em **dry-run**: lista os leads sem atribuição cuja PRIMEIRA mensagem do cliente
     contém o texto e não grava nada.
   - Com `--apply`, grava os mesmos 3 campos só nesses leads e salva os ids alterados em
     `backfill_google_message_asset_<timestamp>.json`, que serve para desfazer.
   - Com `--revert <arquivo.json>`, volta `utm_source`, `utm_medium` e `traffic_type` para NULL nesses ids.

## Onde

- Repo `ValerIA`, só backend: `backend/app/leads/google_message_asset.py` (novo),
  `backend/app/webhook/router.py`, `backend/app/webhook/meta_router.py`,
  `backend/scripts/backfill_google_message_asset.py` (novo) e os testes em `backend/tests/`.
- Serviços afetados no deploy: `canastra_api` e `canastra_worker`. O CRM (`crm_crm`) não muda.

## Como testar em modo teste

- No worktree `ValerIA-agente-1b4e178b`, com TDD (`pytest`):
  - regra pura: texto exato, variações (sem acento, maiúsculas, espaços extras, texto a mais depois),
    textos que não podem casar ("Olá", "Boa tarde", "achei no google maps"…), vazio e None;
  - carimbo: lead sem atribuição recebe os 3 campos; lead com `gclid`, `ctwa_clid`, `meta_ad_id` ou
    UTM não é tocado; erro do Supabase não propaga;
  - webhooks: Evolution e Meta chamam o carimbo com o texto da mensagem;
  - `derive_channel` devolve "Google Ads" para um lead carimbado.
- Suíte inteira do backend verde (é o mesmo gate do deploy).
- Dry-run do backfill contra o banco de produção (somente leitura): conferir que lista ~130 leads e que
  nenhum deles tem atribuição. A saída do dry-run (contagem e amostra) é a evidência. Não há tela nova,
  então não há print nesta fase.

## Como publicar

1. No worktree: `git pull origin master`, rodar a suíte, depois `git push origin agente/1b4e178b:master`.
   O push dispara o GitHub Actions (`deploy.yml`), que roda os testes e faz o deploy de `canastra_api`
   e `canastra_worker`.
2. Conferir na VPS: `docker service ls` (réplicas 1/1), `docker service logs canastra_api` sem erro novo.
3. Rodar o backfill dentro do container `canastra_api`: primeiro o dry-run, conferir a contagem, depois
   `--apply`. Guardar o JSON de ids gerado.
4. **Voltar atrás:** código, `git revert` do merge + push em master (novo deploy). Dados,
   `--revert <json>` no container.

## Como testar em produção

- Depois do backfill: SELECT confirmando que os leads do JSON estão com `utm_source='google'`,
  `utm_medium='cpc'` e `traffic_type='paid'`, e que nenhum lead com atribuição anterior mudou.
- Prints: origem de um desses leads em /conversas (deve mostrar "Google Ads") e a tela /trafego com o
  Google somando esses leads.
- Lead novo: sem mensagem de teste. Aguardar o próximo lead real que chegar pelo botão (média de mais de
  1 por dia) e conferir no banco e nos logs que foi carimbado na entrada.
- Sem efeito externo: nenhuma mensagem é enviada, nada no Bling, nenhuma conversão disparada para
  Meta ou Google. Só 3 colunas de rastreio são gravadas em leads existentes.

## Fora do escopo

- Identificar a campanha do Google de cada lead (opção B: texto diferente por campanha).
- Enviar conversão offline para o Google Ads.
- Botão de WhatsApp do Perfil da Empresa no Google (Maps).
- Outros textos prontos (ex.: os das landing pages) e mudanças de tela no CRM.
