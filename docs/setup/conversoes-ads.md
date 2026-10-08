# Roteiro técnico — Devolver conversões para Meta e Google Ads

Público: Rafael (técnico). O passo a passo da gestora de tráfego é outro documento.

## 1. O que é

O CRM varre os leads que vieram de clique de anúncio (CTWA na Meta, `gclid`/`gbraid`/`wbraid` no
Google) e enfileira em `ad_conversions` quatro etapas do funil: `lead`, `qualified` (repasse ao
vendedor), `opportunity` (orçamento/proposta) e `purchase` (venda, com valor real). Um sender no
worker entrega a fila: Meta pela Conversions API for Business Messaging, Google pela Data Manager
API. O resultado é visível na aba "Conversões enviadas" do /trafego.

Spec: `docs/superpowers/specs/2026-10-08-conversoes-ads-design.md`.

## 2. Variáveis de ambiente

Lidas com `os.getenv` (api e worker leem o mesmo `.env`). Plataforma **ligada mas sem
configuração** (falta `META_CAPI_DATASET_ID`/`_ACCESS_TOKEN`/`META_WABA_ID`, ou
`GOOGLE_ADS_CUSTOMER_ID`/`_CLIENT_ID`/`_CLIENT_SECRET`/`_REFRESH_TOKEN`) é **pulada inteira**: o
sender não reivindica nenhuma linha dela, nada gasta tentativa, e o log do worker avisa a cada tick
(`[CONVERSOES] meta ligada mas sem configuração (VAR): nada sai da fila`). Ao configurar e reiniciar,
a fila sai sozinha. O ID da ação do Google é por etapa: se faltar só o de uma etapa, as linhas
dela falham com `GOOGLE_ADS_CONVERSION_ACTION_X não configurado` e entram no backoff (não viram
`erro` direto; viram `erro` só depois das 5 retentativas, ~15 h).

| Variável | Uso | Default |
|---|---|---|
| `CONVERSIONS_META_ENABLED` | Liga o envio para a Meta. Desligada, as linhas ficam `pendente`. | `false` |
| `CONVERSIONS_GOOGLE_ENABLED` | Idem, Google. | `false` |
| `CONVERSIONS_TEST_MODE` | Meta: inclui `test_event_code`; **sem `META_CAPI_TEST_EVENT_CODE` a Meta fica pulada** (o evento sairia como real). Google: `validateOnly: true`. | `false` |
| `META_CAPI_DATASET_ID` | Dataset ligado ao WABA (destino do `POST /{id}/events`). | sem default |
| `META_CAPI_ACCESS_TOKEN` | Token de system user (seção 4). | sem default |
| `META_CAPI_TEST_EVENT_CODE` | Código da aba Test Events. | sem default |
| `META_CAPI_API_VERSION` | Versão do Graph. | `v25.0` |
| `META_WABA_ID` | WABA (já existe; os 3 canais `meta_cloud` usam o mesmo). | já configurado |
| `GOOGLE_ADS_CONVERSION_ACTION_LEAD` / `_QUALIFIED` / `_OPPORTUNITY` / `_PURCHASE` | ID numérico de cada ação "Importar de cliques" (`productDestinationId`). | sem default |
| `GOOGLE_ADS_REFRESH_TOKEN` | Regerado com os escopos `adwords` + `datamanager` (seção 5). | já existe, trocar |
| `GOOGLE_ADS_CLIENT_ID`, `_CLIENT_SECRET`, `_CUSTOMER_ID`, `_LOGIN_CUSTOMER_ID` | Já existem (ver `google-ads-conexao.md`). Customer = `1861416291`; `loginAccount` só vai se for diferente. | já configurados |

Lembrete: o `.env` da VPS é o que vale; depois de editar, reinicie api e worker.

## 3. Ordem de ativação

> **⚠️ Antes de tudo: aplique `supabase/migrations/20261008_ad_conversions.sql` em produção ANTES
> de subir a branch para `master`.** O push para `master` dispara o deploy automático, e o código
> novo já lê colunas que só a migration cria: o /trafego (`traffic_report`) e a origem do lead
> (`/api/leads/[id]/origin`) selecionam `leads.gbraid`/`wbraid`, e o worker lê `ad_conversions`.
> Deploy antes da migration = /trafego e painel de origem quebrados até ela ser aplicada.
>
> Não re-rode a `20261006b_lead_timeline_triggers.sql` depois da 20261008 (recria sobrecargas
> antigas e todo insert em `leads` falha com "function is not unique"); se precisar, re-rode a
> 20261008 logo em seguida.

Tudo começa com as duas plataformas desligadas.

1. **Migration (antes do push) e deploy.** Aplicada à mão (idempotente), a partir da raiz do repo:
   ```bash
   docker exec -i $(docker ps --format '{{.Names}}' | grep supabase_db | head -1) \
     psql -U postgres -d postgres -v ON_ERROR_STOP=1 < supabase/migrations/20261008_ad_conversions.sql
   ```
   Só depois faça o push/deploy, com `CONVERSIONS_*_ENABLED` ausentes/`false`. A tarefa
   `conversions-sweep` (1800 s) enche a fila, inclusive os 90 dias de histórico. Confira o que **seria** enviado:
   ```sql
   select platform, stage, status, count(*) from ad_conversions group by 1,2,3 order by 1,2,3;
   ```
2. **Valores estimados.** No container da API, a partir de `backend/`:
   ```bash
   python -m scripts.conversoes.calcular_valores                     # só imprime a proposta
   python -m scripts.conversoes.calcular_valores --aplicar --por "<nome>"   # depois de aprovada
   ```
   O script propõe só `lead` (calculado só com leads que têm clique Google, porque só o Google
   recebe essa etapa) e `qualified`. Células com N < 20 vêm marcadas: decida se usa `geral` no
   lugar. O valor de `opportunity`, que o script não propõe, é definido à mão:
   ```sql
   insert into ad_conversion_values(segment,stage,value,updated_by)
   values ('atacado','opportunity',<v>,'<nome>')
   on conflict (segment,stage) do update
     set value=excluded.value, updated_by=excluded.updated_by, updated_at=now();
   ```
   Cada mudança de valor reinicia o aprendizado das plataformas; não recalcule por hábito.
   Depois de aprovar, preencha o valor nas linhas que já estão na fila:
   ```sql
   update ad_conversions c set value = v.value
   from ad_conversion_values v
   where c.status='pendente' and c.value is null and c.stage=v.stage and c.segment=v.segment;
   ```
3. **Modo teste.** `CONVERSIONS_TEST_MODE=true` e ligue **uma** plataforma por vez.
   - Meta: o evento aparece em Events Manager, aba Test Events, do dataset. Precisa de
     `META_CAPI_TEST_EVENT_CODE`: com o modo teste ligado e o código vazio, a Meta fica pulada
     (nada é enviado — sem o código o evento iria como real e, como o modo teste não consome a
     linha, sairia de novo a cada 6 h). O log do worker avisa a variável que falta.
   - Google: o envio vai com `validateOnly`; **nada aparece na conta**, a resposta só diz que a
     validação passou.
   Em modo teste o sender manda no máximo 10 linhas por rodada, e um envio aceito **não consome a
   linha**: ela continua `pendente`, sem gastar tentativa, com `last_response` =
   `{"modo_teste": true, "resposta": ...}` e `next_attempt_at` 6 h à frente (para não reenviar a
   mesma amostra a cada 5 min). Falha em modo teste segue as regras normais: um 400 vira `erro`,
   que é justamente o que o teste quer mostrar.
   Ao sair do modo teste, antecipe as linhas que ficaram esperando para que saiam de imediato:
   ```sql
   update ad_conversions set next_attempt_at = now() where status = 'pendente';
   ```
4. **Produção.** `CONVERSIONS_TEST_MODE=false`; ligue o **Google primeiro** (ganha o histórico de
   90 dias na hora), depois a **Meta**. Reinicie o worker a cada mudança de env.

## 4. Meta

1. Em Configurações do Negócio, Usuários do sistema, crie (ou reaproveite) um system user e dê a
   ele o ativo WABA. Gere o token do app com **`whatsapp_business_management`** e
   **`whatsapp_business_manage_events`** (confirmado na doc da Conversions API for Business
   Messaging). Guarde em `META_CAPI_ACCESS_TOKEN`. Não use o `META_ADS_ACCESS_TOKEN` (é só `ads_read`).
2. Crie/associe o dataset ao WABA (passo único), no container da API, a partir de `backend/`:
   ```bash
   python -m scripts.conversoes.criar_dataset_meta
   ```
   Por baixo é `POST /{WABA_ID}/dataset`; a Meta devolve o ID existente se já houver um. Coloque o
   ID impresso em `META_CAPI_DATASET_ID`.
3. Pegue o código de teste em Events Manager, Test Events, e ponha em `META_CAPI_TEST_EVENT_CODE`.

Limites do produto (da spec): `event_time` no máximo 7 dias antes do envio (um evento fora da
janela derruba o request inteiro, por isso o sender confere de novo); a Meta não deduplica, a
dedup é nossa (`dedupe_key`/`event_id`); só eventos padrão (`LeadSubmitted` no repasse, `InitiateCheckout`,
`Purchase`; o clique não vai para a Meta e `QualifiedLead` não é usado).

## 5. Google

1. **Quatro ações de conversão** em Google Ads (conta `1861416291`), cada uma do tipo **"Importar
   de cliques"** (na API, `UPLOAD_CLICKS`; a doc da Data Manager API exige esse tipo). Nomes
   sugeridos: LEAD, QUALIFICADO, OPORTUNIDADE, VENDA. Venda com valor; as demais usam o valor
   estimado. Recomendação à Tati: deixar **qualificado como primária** e "Conversa iniciada" como
   secundária (hoje soma com o formulário e conta a mesma pessoa duas vezes).
2. **ID de cada ação.** Abra a ação em Metas, Conversões, e leia o ID numérico: na UI atual ele
   aparece como parâmetro `ctId=` da URL da página da ação. *Não confirmado em doc oficial nesta
   sessão: confira que o número bate fazendo um envio em modo teste (`validateOnly`), que rejeita ID
   inválido.* Preencha `GOOGLE_ADS_CONVERSION_ACTION_{LEAD,QUALIFIED,OPPORTUNITY,PURCHASE}`.
3. **Regerar o refresh token** com os dois escopos, pelo mesmo fluxo de
   `docs/setup/google-ads-conexao.md` (Passo 3, OAuth Playground com as credenciais do cliente
   OAuth do Passo 2). A diferença é o campo "Input your own scopes", que agora leva os dois,
   separados por espaço:
   ```
   https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/datamanager
   ```
   Antes, no projeto do Google Cloud, ative a **Data Manager API** na Biblioteca e inclua o escopo
   em "Data Access" (Acesso a dados). A doc classifica `datamanager` como escopo sensível: o app
   OAuth em "Testing" gera refresh token que expira em 7 dias; publique o app ("In production")
   para o token durar, e a verificação do Google pode ser pedida. Cole o resultado em
   `GOOGLE_ADS_REFRESH_TOKEN` e reinicie. O sync diário de spend (`adwords`) continua funcionando
   com o token novo, que cobre os dois escopos.
4. A Data Manager API não exige developer token (por isso vale mesmo após 15/06/2026).

## 6. Operação

| Status | Significado |
|---|---|
| `pendente` | Na fila. Também é onde ficam as linhas quando a plataforma está desligada ou aguardando retentativa (`next_attempt_at`). |
| `enviado` | Aceito pela plataforma de verdade. Envio em modo teste nunca vira `enviado`: a linha fica `pendente` com `last_response.modo_teste = true`. |
| `erro` | Erro permanente (4xx de validação) ou 6 falhas seguidas. Veja `last_error` e `last_response`. Token inválido/sem permissão (HTTP 401/403; na Meta também os códigos OAuth 190/102, permissão 10/200–299 e limites 4/17/32/341/613) **não** é permanente: entra no backoff, e a fila espera a troca do token — mas, se passar das 5 retentativas (~15 h), vira `erro` e precisa do `update` abaixo. |
| `fora_da_janela` | O clique ficou velho demais antes do envio (Meta 7 dias, Google 90). Não há o que fazer. |
| `ignorado` | Venda cancelada (`venda cancelada antes do envio`) ou apagada (`venda removida antes do envio`) antes do envio. |

Retentativas: 1 min, 5 min, 30 min, 2 h, 12 h; na 6ª falha vai para `erro`. Variável de ambiente
faltando também entra no backoff (não é permanente) — e, se for credencial da plataforma, a
plataforma nem é processada (seção 2).

**Aba "Conversões enviadas" (/trafego):** só admin. O endpoint `GET /api/conversions/ads` exige o
JWT de admin no próprio backend (`exigir_admin`, o mesmo das rotas de atribuição do /trafego); a
proxy do Next (`/api/traffic/conversoes`) repassa o token pelo `adminProxy`. Chamada direta ao
backend sem token → 401; token de quem não é admin → 403. Os contadores somam **todas** as linhas
do filtro; só a lista para em 1000 (a tela avisa que está truncada).

Reenviar uma linha depois de corrigir a causa (credencial, ID de ação, etc.):
```sql
update ad_conversions set status='pendente', attempts=0, next_attempt_at=now(), last_error=null
where id='...';
```
Linhas `fora_da_janela` não voltam a ser elegíveis.

**Desligar:** `CONVERSIONS_META_ENABLED=false` / `CONVERSIONS_GOOGLE_ENABLED=false` e reiniciar o
worker. A varredura continua enfileirando; nada sai. Venda cancelada depois de enviada não é
retraída nas plataformas (fora de escopo), fica só na aba.

## 7. Verificações pendentes (spec §12, antes do modo teste)

- **Meta:** se a meta "Maximizar o número de leads por mensagens" aparece para a conta e otimiza nos
  `LeadSubmitted` do repasse (≥10 eventos de lead ou compra em 30 dias). `QualifiedLead` não é usado.
  Se não aparecer, a Meta recebe os eventos para medição e otimiza por Purchase quando houver volume.
- **Google:** se a conta exige algum aceite/termo para a Data Manager API. A doc consultada só
  menciona ativar a API no projeto Cloud e o escopo sensível; qualquer aceite na conta Google Ads
  só aparece na prática, no primeiro envio `validateOnly`.
- **ID da ação (`ctId`):** ver seção 5, passo 2.
- **Versão do Graph e endpoint do dataset:** a doc de onboarding cita `v16.0`; o código usa
  `v25.0` por padrão (`META_CAPI_API_VERSION`). Confirme que o `criar_dataset_meta` responde na versão em uso.
