# Sincronizar todo dia à 01:00 os públicos de Private Label e Atacado (Meta e Google)

Cartão 4e0494e0, quadro BEEINSIDE CANASTRA CRM. Branch `agente/4e0494e0`, partindo de `origin/master` (abfefd77, que é o que está em produção e já tem `app/conversions/hashing.py`).

## Problema

Hoje a Tati sobe na mão, a partir de uma planilha, os compradores de Private Label e de Atacado para 4 públicos. Esse trabalho passa para um job no backend do ValerIA: todo dia à 01:00 (America/Sao_Paulo) ele refaz o conteúdo dos 4 públicos com os compradores atuais de cada segmento. O ID do público não muda, só o conteúdo. O job não cria, não renomeia e não apaga público, e não mexe em campanha.

| Chave | Plataforma | Nome | ID |
|---|---|---|---|
| `meta_pl` | Meta, act_3023084178002518 | Lista \| Private Label | 120252789539440163 |
| `meta_atacado` | Meta, act_3023084178002518 | Lista \| Atacado \| v3 | 120252789580640163 |
| `google_pl` | Google Ads 1861416291 (MCC 3643809068) | Lista Bling Private Label | 9496018532 |
| `google_atacado` | Google Ads 1861416291 (MCC 3643809068) | Lista Bling Atacado | 9496602202 |

Os IDs ficam fixos no código, numa constante: eles não mudam e não são configuração.

## O que já foi conferido (31/10, só leitura)

- **Token do Meta:** existe um token novo do system user "CRM Canastra" (61593017769828), no app "CRM Canastra ADS read", com `ads_management` + `ads_read` e validade Nunca. O `debug_token` foi conferido localmente. Os termos de Públicos Personalizados e de públicos com base em valor já estavam aceitos. Os 2 públicos respondem 200 e são `is_value_based: true`. O token está em `C:\Users\rafae\.secrets\meta_audiences_token.txt` e vai para a VPS como `META_AUDIENCES_ACCESS_TOKEN`.
- **E-mail e endereço:** o Bling `GET /contatos` (listagem) não traz `email` nem `endereco`. O `GET /contatos/{id}` traz `email`, `emailNotaFiscal` e `endereco.geral` (municipio/uf/cep). No espelho `bling_contacts`, só 1 dos 6.740 contatos tem endereço e nenhum tem e-mail.
- **Telefone:** 168 compradores têm `leads.phone = 'bling-…'`, um marcador e não um número. De 571 compradores com venda nos últimos 12 meses:
  - 423 têm celular por `leads.phone` real ou pelo campo `celular` do Bling;
  - 437 têm celular contando também o campo `telefone`, quando o número é de celular.
- **Pipelines** com "Private Label" ou "Atacado" no nome: os 6 citados no cartão. As tabelas `tags`/`lead_tags` e a view `analytics.vw_clientes` existem.
- **Deploy:** o push em `master` dispara o GitHub Actions, que faz `docker build` + `stack deploy` + `update --force` em `canastra_api` e `canastra_worker`. As variáveis vêm de `/srv/Maquinadevendascanastra/backend/.env` (`env_file`). Migrations são aplicadas à mão com `psql`, seguidas de SIGUSR1 no PostgREST.

## Decisões

1. **Celular:** vale o número, não o campo, como já faz `app.bling.contacts._celular_br`.
   - Entram `leads.phone` (quando é número), `bling_contacts.celular_e164` e `bling_contacts.telefone_e164` **só quando o número é celular** (55 + DDD + 9 + 8 dígitos, ou o formato antigo de 12 dígitos começando em 6–9, que ganha o 9).
   - Fixo nunca entra. Isso põe mais 14 compradores com celular.
   - Se o Rafael preferir o cartão ao pé da letra, é tirar uma fonte só.
2. **E-mail e endereço do Bling:** ficam numa tabela própria, `audience_contact_details`, e não no espelho `bling_contacts`. Motivo: o `sync_contacts` diário faz upsert com o que a listagem traz (e-mail e endereço vazios) e apagaria o enriquecimento.
   - A cada rodada: `GET /contatos/{id}` só dos contatos vinculados aos compradores selecionados que ainda não têm detalhe ou cujo detalhe tem mais de 30 dias.
   - Pelo `BlingClient`, que já respeita `ratelimit.py`. O Bling fica só em leitura.
   - E-mail: `email`; se vier vazio, `emailNotaFiscal`.
3. **Primeira carga no Google:** o que a Tati subiu na mão continua lá (a Data Manager não tem "apagar tudo") e expira pela associação de 540 dias. Daqui em diante o job remove quem ele mesmo enviou e saiu.
   - No Meta isso não acontece: o `usersreplace` substitui tudo, inclusive o conteúdo antigo.
4. **Horário:** o worker não tem cron, só ticks periódicos. Um tick `audience-sync` a cada 10 min roda a sincronização quando todas estas condições valem:
   - a hora em São Paulo é ≥ 01:00;
   - não existe rodada `automatica` concluída hoje em `audience_sync_runs`;
   - `AUDIENCE_SYNC_ENABLED` é verdadeiro.
   Isso também cobre o worker reiniciado às 01:05.
5. **Lock:** `SET audience_sync:lock NX EX 3600` no Redis. Rodada manual e automática respeitam o mesmo lock.

## O que muda (repo ValerIA, só `backend/` + 1 migration)

Pacote novo `backend/app/audiences/`:

| Arquivo | Faz |
|---|---|
| `normalize.py` | Nome (primeiro nome e sobrenome, minúsculos, sem acento e sem pontuação), cidade, UF, CEP (8 dígitos) e celular. Reaproveita `normalize_br_phone`, `meta_*_hash` e `google_*_hash` de `app/conversions/hashing.py`, e acrescenta o hash de nome e endereço. |
| `segment.py` | Função pura `classificar(fatos) -> {pl, atacado}` com a regra do cartão: PL por pipeline, tag `Marca Própria`, fotolito ou `product='PL'`, ou `segmento='private_label'`; Atacado por pipeline, tag `Revenda` ou `segmento='atacado'`, ou CNPJ de 14 dígitos quando não caiu em nenhum dos dois. Recebe `hoje` e aplica o corte de 365 dias. |
| `source.py` | Lê do Postgres, via a função SQL `audience_sync_facts()`, os fatos de cada comprador com venda `registrada`: data da última compra, receita de 365 dias, flags de pipeline/tag/fotolito/PL/segmento, documentos, telefones, e-mails e IDs Bling. |
| `bling_details.py` | Enriquecimento descrito na decisão 2. |
| `meta.py` | Monta e envia o `POST /{id}/usersreplace`. Schema `EMAIL, PHONE, FN, LN, CT, ST, ZIP, COUNTRY, LOOKALIKE_VALUE`, uma linha por par (pessoa, e-mail/celular). O `session` tem `session_id`, `batch_seq`, `last_batch_flag` e `estimated_num_total`, com lotes de até 10.000 linhas. `LOOKALIKE_VALUE` é a receita de 365 dias, sem hash. Grava `num_received`/`num_invalid_entries`. |
| `google.py` | Data Manager API `audienceMembers:ingest` / `audienceMembers:remove`. O destino tem `productDestinationId = userListId`, `operatingAccount` 1861416291 e `loginAccount` 3643809068. Identificadores: `emailAddress`, `phoneNumber` (`+55…`) e `address` (nome e sobrenome com hash, `regionCode BR`, `postalCode`) quando houver CEP. Usa `consent` GRANTED, `encoding HEX` e lotes de até 10.000. O token OAuth vem de `app/conversions/google.py` (`_access_token`), reaproveitado. Plano B, se a Data Manager recusar: `OfflineUserDataJobService` (`remove_all` + `create`). Se as duas recusarem por elegibilidade ou developer token, a rodada grava o erro e para só o Google. |
| `diff.py` | Função pura: dados os identificadores enviados antes (`audience_sync_members`) e os de agora, devolve o que entra e o que sai. O diff é feito por identificador, então e-mail trocado sai e e-mail novo entra. |
| `service.py` | `run(trigger, dry_run)`: pega o lock, lê os fatos, enriquece, classifica, e roda Meta e Google cada um em `try` próprio (fail-soft). Grava uma linha por público em `audience_sync_runs`. |
| `__main__.py` | `python -m app.audiences [--dry-run]` para rodada manual. |

`backend/app/worker/main.py` ganha `("audience-sync", "periodic", _audience_sync_tick, 600)`.

**Migration** `supabase/migrations/20261031_4e04_audience_sync.sql`. Ela só cria objetos, reexecutar é seguro, e o rollback é um `drop` dos objetos novos:

- `audience_sync_runs`:
  - `id`, `run_id` (uuid da rodada), `trigger` (`automatica`/`manual`), `dry_run`, `audience_key`, `platform`, `audience_id`;
  - `pessoas`, `com_celular`, `com_email`, `linhas_enviadas`, `removidos`;
  - `api_response` jsonb (Meta: `num_received`, `num_invalid_entries`, `session_id`; Google: `requestId`/status), `erro`, `iniciado_em`, `terminado_em`.
- `audience_sync_members`:
  - colunas `audience_key`, `ident_hash` (sha256 do JSON canônico do identificador), `ident` jsonb (o identificador já em hash, guardado para poder remover), `lead_id`, `primeiro_envio`, `ultimo_envio`, `removido_em`;
  - unique (`audience_key`, `ident_hash`).
- `audience_contact_details`: `account`, `bling_contact_id`, `email`, `municipio`, `uf`, `cep`, `buscado_em`, com PK (`account`, `bling_contact_id`).
- Função `audience_sync_facts()` (security definer, só leitura).
- RLS ligado, grants a `service_role` e, onde `consulta_ro` existir, `select` a ela, como nas outras migrations.

**Variáveis novas** em `backend/.env` da VPS:
- `META_AUDIENCES_ACCESS_TOKEN` (o token novo);
- `AUDIENCE_SYNC_ENABLED`: fica `false` até a rodada manual dar certo, depois `true`.

O `META_ADS_ACCESS_TOKEN` não é alterado.

## Como testar em modo teste (antes de publicar)

1. **Testes sem rede** (pytest, em `backend/tests/test_audiences_2026_10_31.py`):
   - normalização de celular (inclusive fixo recusado e o 9 inserido), e-mail e nome com acento e pontuação;
   - corte de 365 dias (364 entra, 366 sai);
   - regra de segmento, cobrindo cada critério, o caso "nos dois", CNPJ sem classe indo para Atacado e CPF sem classe ficando fora;
   - montagem do payload do Meta (schema, hash, valor sem hash, `session` nos vários lotes) e do Google (identificadores, destino, lotes);
   - diff de quem saiu;
   - lock e a regra das 01:00.

   Mais a suíte inteira do backend.
2. **Migration** aplicada na produção antes do push. É aditiva (só cria tabelas e uma função de leitura) e o código em produção não a usa. Depois, SIGUSR1 no PostgREST.
3. **Dry-run com dados reais, na VPS, sem publicar:**
   - fazer o build da imagem `canastra-api:agente-4e0494e0` a partir do branch, num diretório separado (`/root/agente-4e0494e0`);
   - rodar `docker run --rm --env-file /srv/Maquinadevendascanastra/backend/.env --network canastrainteligencia canastra-api:agente-4e0494e0 python -m app.audiences --dry-run`;
   - o token do Meta vai só por `-e` nesse comando, para não mexer no `.env` ainda.

   O dry-run:
   - lê o banco e faz os `GET /contatos/{id}` no Bling (só leitura);
   - grava em `audience_contact_details` e `audience_sync_runs` com `dry_run = true`;
   - no Google, manda `validateOnly: true`, que valida sem gravar no público;
   - no Meta, não chama o `usersreplace` (não existe validação sem efeito) e só confere com GET o público e a permissão.

   Evidência para o Rafael: a contagem por público (PL / Atacado / os dois / fora), quantos têm celular e e-mail, e a resposta do `validateOnly` do Google. Não há tela, então não há print: a evidência é a saída do comando e um SELECT em `audience_sync_runs`.

## Como publicar

1. `git pull origin master` no branch, e depois `git push origin agente/4e0494e0:master`. O Actions faz o build e o `update --force` de `canastra_api`/`canastra_worker`.
2. Na VPS:
   - backup de `backend/.env` (`.env.bak-4e0494e0`);
   - acrescentar `META_AUDIENCES_ACCESS_TOKEN=…` (lido do arquivo local, sem eco no terminal) e `AUDIENCE_SYNC_ENABLED=false`;
   - `docker service update --force canastra_worker canastra_api`, para recarregar o `env_file`;
   - conferir que o worker subiu (`docker service logs canastra_worker`) e que as variáveis existem, listando só os nomes.
3. **Voltar atrás:**
   - `AUDIENCE_SYNC_ENABLED=false` + `update --force` desliga o job;
   - para voltar o código, `git revert` do merge + push;
   - as tabelas podem ficar (não são usadas por mais nada).
   - O conteúdo dos públicos não tem "desfazer". A garantia é o dry-run antes, e a Tati pode subir a planilha de novo se precisar.

## Como testar em produção

1. **Rodada manual real:** `docker exec <worker> python -m app.audiences`. Ela tem efeito externo, porque substitui o conteúdo dos 2 públicos do Meta e acrescenta membros nos 2 do Google. É exatamente o objetivo do cartão, com os IDs fixos acima; não toca em campanha nem cria público.
   - Conferir em `audience_sync_runs`: pessoas, linhas, `num_received`/`num_invalid_entries` no Meta e o `requestId` do Google.
   - Conferir pela API (GET): `approximate_count_lower_bound`/`operation_status` no Meta e `size_for_search`/`size_for_display` no Google.
2. Se der certo: `AUDIENCE_SYNC_ENABLED=true` + `update --force canastra_worker`. O log do worker mostra o tick `audience-sync` registrado.
3. **Na manhã seguinte (01/11):** conferir em `audience_sync_runs` a rodada `automatica` depois da 01:00 nos 4 públicos e os tamanhos que cada plataforma devolveu.
4. **Comentário final no cartão** com:
   - a tabela de contagem por segmento (comparada com a de 31/10);
   - quantos têm celular e e-mail;
   - os tamanhos do dia seguinte.

## Fora do escopo

- Criar, renomear ou apagar públicos; mexer em campanha ou conjunto de anúncios.
- Escrever no Bling.
- Telefone fixo como identificador.
- Limpar no Google o conteúdo antigo subido à mão (decisão 3).
- Tela no CRM para ver as rodadas: o log fica na tabela.
