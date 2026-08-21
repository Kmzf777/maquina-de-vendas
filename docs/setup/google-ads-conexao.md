# Tutorial — Conectar o CRM à API do Google Ads (ROAS no /trafego)

Este guia mostra como obter as **6 credenciais** que o CRM precisa para puxar o
**investimento (spend) por campanha** do Google Ads e calcular o **ROAS** na página
`/trafego`. Ao final você terá 6 secrets, aplicará 1 migration e agendará 1 cron.

> **Como funciona:** um job diário (`scripts/sync_google_ads_spend.py`) chama a API do
> Google Ads, grava o custo por campanha/dia na tabela `ad_spend`, e o relatório junta esse
> custo à receita por campanha (casando **`utm_campaign` = nome da campanha do Google Ads**).
> Sem as credenciais, tudo fica inerte e o ROAS aparece como "—" (nada quebra).

## As 6 variáveis de ambiente

| Variável | O que é |
|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Token de desenvolvedor da sua conta Google Ads (API Center) |
| `GOOGLE_ADS_CLIENT_ID` | Client ID do OAuth2 (Google Cloud) |
| `GOOGLE_ADS_CLIENT_SECRET` | Client Secret do OAuth2 (Google Cloud) |
| `GOOGLE_ADS_REFRESH_TOKEN` | Refresh token OAuth2 (escopo AdWords) |
| `GOOGLE_ADS_CUSTOMER_ID` | ID da conta Google Ads a consultar (10 dígitos, sem traços) |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | ID da conta MCC/gerente (sem traços). Se não usa MCC, use o mesmo do customer_id |

---

## Passo 1 — Developer Token (Google Ads)

1. Entre no **Google Ads** (ads.google.com) com a conta **MCC/gerente** (o developer token
   vive na conta gerente).
2. Menu **Ferramentas → Configuração → Central de API** (API Center).
3. Copie o **Developer token**. → `GOOGLE_ADS_DEVELOPER_TOKEN`.
4. **Nível de acesso:** um token novo começa como **Test account access**, que só consulta
   contas de teste. Para ler a conta real de produção, solicite **Basic access** no mesmo
   painel (formulário de aplicação; aprovação do Google costuma levar de horas a poucos dias).
   *Enquanto o acesso for "Test", a integração roda mas retorna 0 para contas reais.*

## Passo 2 — Projeto no Google Cloud + OAuth Client

1. Acesse **console.cloud.google.com**, crie (ou selecione) um projeto.
2. **APIs e serviços → Biblioteca →** ative a **Google Ads API**.
3. **APIs e serviços → Tela de consentimento OAuth**: configure (User type "External" serve;
   adicione seu e-mail em "usuários de teste" se ficar em modo de teste).
4. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**:
   - Tipo de aplicativo: **Desktop app** (mais simples para gerar o refresh token).
   - Copie **Client ID** → `GOOGLE_ADS_CLIENT_ID` e **Client Secret** → `GOOGLE_ADS_CLIENT_SECRET`.

## Passo 3 — Refresh Token (escopo AdWords)

O jeito mais rápido, usando o **OAuth 2.0 Playground**:

1. Abra **developers.google.com/oauthplayground**.
2. Clique na engrenagem (⚙, canto superior direito) → marque **"Use your own OAuth
   credentials"** → cole o **Client ID** e **Client Secret** do Passo 2.
3. No campo **"Input your own scopes"** (Step 1 à esquerda), digite:
   `https://www.googleapis.com/auth/adwords`
4. Clique **Authorize APIs** → faça login com a conta que tem acesso ao Google Ads → permita.
5. Em **Step 2**, clique **Exchange authorization code for tokens**.
6. Copie o **Refresh token** → `GOOGLE_ADS_REFRESH_TOKEN`.

> ⚠️ Se a tela de consentimento estiver em modo **"Testing"**, o refresh token pode expirar em
> 7 dias. Para produção, publique o app OAuth (status "In production") na tela de consentimento.

## Passo 4 — Customer IDs

1. **`GOOGLE_ADS_CUSTOMER_ID`**: o ID da **conta que veicula os anúncios** (aparece no topo
   direito do Google Ads, formato `123-456-7890`). Grave **sem traços**: `1234567890`.
2. **`GOOGLE_ADS_LOGIN_CUSTOMER_ID`**: o ID da **conta MCC/gerente** que engloba a conta
   acima (também sem traços). **Se você não usa MCC**, use o mesmo valor do customer_id.

## Passo 5 — Setar os secrets

**Produção (deploy):** GitHub → repositório → **Settings → Secrets and variables → Actions →
New repository secret** — crie os 6 secrets com os nomes exatos da tabela. O deploy os injeta
no container do backend.

**Local (`.env` / `.env.local`):** para testar na sua máquina, adicione as 6 linhas
`GOOGLE_ADS_...=valor` ao `.env`/`.env.local` do backend.

> As credenciais são lidas via `os.getenv` no `backend/app/campaigns/google_ads.py`. Se
> qualquer uma das 6 faltar, `google_ads_enabled()` retorna False e o sync/relatório viram
> no-op (ROAS "—").

## Passo 6 — Migration + Cron

1. **Migration:** rode `supabase/migrations/20260805_ad_spend.sql` no Supabase (SQL Editor).
2. **Cron diário do sync** (na VPS): agende, 1×/dia, dentro do diretório `backend/`:
   ```
   cd /srv/Maquinadevendascanastra/backend && python -m scripts.sync_google_ads_spend
   ```
   Ex. crontab às 05:00: `0 5 * * * cd /srv/.../backend && python -m scripts.sync_google_ads_spend >> /var/log/gads_sync.log 2>&1`
   *(o sync puxa os últimos 30 dias e faz upsert idempotente — rodar de novo não duplica.)*

## Passo 7 — Verificar

1. Rode o sync manualmente 1×: `cd backend; python -m scripts.sync_google_ads_spend`
   → deve imprimir `ad_spend sync: N linhas` (N > 0 se houver spend na janela).
2. Confira a tabela `ad_spend` no Supabase (linhas com `platform='google'`, `campaign_name`,
   `date`, `cost`).
3. Abra `/trafego` como admin → as linhas de canal **Google Ads** devem mostrar
   **Investimento** e **ROAS**.

## Versão da API — a armadilha que já nos custou 10 dias

O Google **descontinua cada versão da API ~1 ano depois do lançamento**. A versão morta não
devolve um erro tratável: devolve **404 em HTML**. Como o client é fail-soft, isso virava
"nenhum spend retornado" e o sync seguia reportando sucesso — em 11/08/2026 a v21 morreu e o
investimento do Google ficou dez dias congelado sem ninguém perceber.

Hoje: `_DEFAULT_API_VERSION` em `backend/app/campaigns/google_ads.py` (**v22**), e o env
`GOOGLE_ADS_API_VERSION` sobrepõe sem redeploy quando a próxima cair.

Para descobrir quais versões estão vivas:

```bash
curl -s "https://googleads.googleapis.com/\$discovery/rest?version=v22" | head -3
# 404 com "Discovery document not found" = versão morta
```

O botão **Atualizar** do /trafego agora diferencia "API não respondeu" de "não há gasto no
período" — se aparecer a mensagem de erro citando a versão, é isso.

## Casamento campanha ↔ ROAS

O relatório é ancorado na **campanha da plataforma**, não no slug de utm: cada campanha do
Google Ads vira uma linha e recebe seu gasto **exatamente uma vez**. Vários `utm_campaign`
que apontam para a mesma campanha (ex.: `terceirizacao` e `leads_search_terceirizacao`, ou os
sufixos `_sitelink_NN`) somam leads na MESMA linha em vez de cobrarem o custo cheio cada um.

O casamento usa os tokens do `utm_campaign` contra o nome da campanha, com o `utm_medium`
como desempate (`medium=pmax` escolhe "PMAX | Atacado" quando "atacado" também caberia na
campanha de Search). Sem casamento confiável o lead cai em **"(não atribuído)"** — nunca é
chutado numa campanha, porque errar a campanha é pior que admitir que não sabe.

Campanha que gastou e não gerou lead **continua aparecendo** com leads = 0: escondê-la
subestimaria o investimento do canal e inflaria o ROAS.

> Quer atribuição perfeita por linha? Padronize o `utm_campaign` com o nome da campanha, ou
> adicione `{campaignid}` ao tracking template — o id é imune a renomeação de campanha.

## Diagnóstico rápido

| Sintoma | Causa provável |
|---|---|
| ROAS "—" em tudo | secrets ausentes, cron não rodou, ou `ad_spend` vazia |
| ROAS "—" só em algumas campanhas | `utm_campaign` ≠ nome da campanha no Google Ads |
| Sync imprime 0 linhas | **versão da API descontinuada (404)**, developer token em "Test access", janela sem gasto, ou credenciais inválidas |
| Investimento parado numa data | quase sempre versão da API morta — ver seção acima |
| Linha "(não atribuído)" com leads | `utm_campaign` não casa com nenhuma campanha (ou casa com 2 e o `utm_medium` não desempata) |
| Erro de auth no log | refresh token expirado (republicar o app OAuth) ou client id/secret errados |
