# Tutorial — Conectar o CRM à Meta Ads (ROAS no /trafego)

Este guia mostra como obter as **2 credenciais** que o CRM precisa para puxar o
**investimento (spend) por campanha** do Meta Ads e calcular o ROAS na página `/trafego`.

> **Como funciona:** o mesmo job diário que já busca o Google Ads passa a buscar também o
> Meta (via Marketing API), grava o custo por campanha/dia na tabela `ad_spend`
> (`platform='meta'`), e o relatório junta com a receita por campanha (casando `utm_campaign`
> com o **nome da campanha no Meta**, com tolerância a números/variações). Sem as credenciais,
> fica inerte e o ROAS aparece como "—" (nada quebra).

## As 2 variáveis de ambiente

| Variável | O que é |
|---|---|
| `META_ADS_ACCESS_TOKEN` | Token de **System User** com permissão **`ads_read`** na conta de anúncios |
| `META_AD_ACCOUNT_ID` | ID da conta de anúncios (só os dígitos, ou com prefixo `act_`) |

*(Reaproveita `META_API_VERSION` já existente; default `v21.0`. Se `META_ADS_ACCESS_TOKEN`
faltar, o código tenta o `META_ACCESS_TOKEN` — mas o do WhatsApp geralmente **não** tem `ads_read`.)*

---

## Passo 1 — Ad Account ID

1. Abra o **Gerenciador de Anúncios** (business.facebook.com) ou **Configurações do Negócio →
   Contas → Contas de anúncio**.
2. Copie o **ID da conta de anúncios** (formato `act_1234567890` ou só `1234567890`).
   → `META_AD_ACCOUNT_ID` (pode gravar com ou sem o `act_`; o código normaliza).

## Passo 2 — System User (usuário do sistema)

1. **Configurações do Negócio** (business.facebook.com/settings) → **Usuários → Usuários do sistema**.
2. **Adicionar** → dê um nome (ex.: "CRM Canastra – Leitura Ads") → função **Funcionário** (Employee) já basta para leitura.

## Passo 3 — Dar acesso à conta de anúncios (ads_read)

1. Ainda em **Usuários do sistema**, selecione o system user criado → **Adicionar ativos**.
2. Escolha **Contas de anúncio** → marque a **conta alvo** (a do Passo 1).
3. Ative a permissão de **"Ver desempenho"** (isso concede leitura/`ads_read`). Salvar.

## Passo 4 — Gerar o token

1. No mesmo system user → **Gerar novo token**.
2. Selecione o **App** do negócio (o mesmo App que o CRM já usa — o dono do `META_APP_SECRET`).
3. Em permissões, marque **`ads_read`** → **Gerar token**.
4. Copie o token → `META_ADS_ACCESS_TOKEN`.
   *(Tokens de system user são de longa duração/permanentes — não expiram como os de usuário.)*

## Passo 5 — Setar os secrets

- **VPS (`.env`):** adicione as 2 linhas ao `.env` do backend (api **e** worker leem o mesmo `.env`):
  ```
  META_ADS_ACCESS_TOKEN=EAAG...
  META_AD_ACCOUNT_ID=1234567890
  ```
- Reinicie os containers (ou faça o deploy). **Sem migration** — a tabela `ad_spend` já suporta `platform='meta'`.

## Passo 6 — Verificar

1. Após o deploy, o **worker** roda o sync no boot; ou clique **"Atualizar"** no `/trafego`.
2. No Supabase, confira a tabela `ad_spend` com linhas `platform='meta'` (campaign_name, date, cost).
3. No `/trafego`, as linhas de canal **Meta Ads** devem mostrar **Investimento** e **ROAS**.

## Casamento campanha ↔ ROAS (importante)

O ROAS por linha só aparece quando o **`utm_campaign` do lead** se relaciona ao **nome da
campanha no Meta** (comparação sem acento/número, com fuzzy por tokens). A gestora usa
`utm_campaign=atacado_wa_01` / `pl_wa_01` / `branding_01` — garanta que o **nome da campanha no
Gerenciador do Meta** contenha essas palavras-chave (ex.: campanha "Atacado WhatsApp" casa com
`atacado_wa`). Nomes muito diferentes não casam → o gasto entra na conta mas não por linha.

## Atribuição de campanha no CTWA (Click-to-WhatsApp)

Um lead que chega por CTWA **não tem `utm_campaign` nenhum** — o WhatsApp não carrega UTMs.
O que a Meta manda no webhook é `referral.source_id`, que é o **ID do anúncio**. Por isso a
atribuição do Meta funciona em dois passos:

1. o webhook carimba `leads.meta_ad_id` a partir de `referral.source_id`;
2. o sync do Meta Ads popula `meta_ad_campaigns` (anúncio → campanha) via insights `level=ad`.

Sem esses dois, os leads do Meta caem todos em **"(não atribuído)"**. Isso **não** quebra o
investimento nem o ROAS do canal: o gasto é ancorado na campanha, então o subtotal "Meta Ads"
bate com o Gerenciador de qualquer jeito — só a quebra por campanha é que fica pendente.

> Leads anteriores a 21/08/2026 não têm `meta_ad_id` (o webhook descartava o `source_id`), e
> não há como recuperar isso pela API — o `ctwa_clid` não é reversível. A atribuição por
> campanha do Meta passa a valer para os leads novos.

## Diagnóstico rápido

| Sintoma | Causa provável |
|---|---|
| ROAS "—" nas linhas Meta | secrets ausentes, sync não rodou, ou `ad_spend` sem linhas `platform='meta'` |
| Sync Meta volta 0 linhas | token sem `ads_read`, conta errada, ou sem gasto na janela |
| Erro de auth no log | token inválido/revogado, ou o App sem acesso à Marketing API |
| ROAS "—" só em algumas campanhas | `utm_campaign` não casa com o nome da campanha no Meta |
| Todos os leads Meta em "(não atribuído)" | migration `20260821` não aplicada, ou leads antigos sem `meta_ad_id` |
| Subtotal do canal certo, linhas sem lead | esperado enquanto o `meta_ad_id` não acumula (ver seção acima) |
