# Origem do lead detalhada em /leads e /conversas — design

Data: 23/09/2026 · Status: aprovado pelo usuário

## Problema

- `/conversas` (aba Perfil do painel do lead, `crm-perfil-tab.tsx:213-231`) só mostra o badge
  "Pago · utm_source" / "Orgânico · utm_source" — nunca a campanha.
- `/leads` (modal `lead-detail-modal.tsx`, aba "Dados Gerais") não mostra origem nenhuma.
- O banco já guarda muito mais: `meta_ad_id` (→ `meta_ad_campaigns.campaign_name`), `gclid`,
  `fbclid`, `ctwa_clid`, UTMs completas, `metadata.origem` (página de LP / importação),
  `metadata.referral` (indicação), `metadata.lote`, `channel`.

## Decisões do usuário

- Nível de detalhe: **canal + campanha** (sem nome do anúncio — não é guardado; sem UTMs cruas).
- Sub-origens orgânicas: WhatsApp direto · Landing page (nome da página) · Instagram/Facebook
  orgânico (via UTM) · Indicação de <nome> · Bling · Reativação Bling · Cadastro manual /
  importação · Sem rastreio.

## Arquitetura (abordagem A)

1. **`frontend/src/lib/lead-origin.ts`** — lógica pura, sem I/O:
   - `describeLeadOrigin(lead: LeadOriginInput, campaignName: string | null): LeadOrigin`
   - `resolveGoogleCampaignName(utmCampaign, utmMedium, campaignNames: string[]): string | null`
     (porte simplificado de `resolve_campaign_id` do backend: nome idêntico normalizado, senão
     candidato único por subconjunto de tokens, senão desempate por utm_medium; sem chute → null).
2. **`GET /api/leads/[id]/origin`** — exige usuário autenticado (`getCurrentUser`, 401 sem sessão;
   qualquer papel, pois o vendedor usa /conversas). Lê as colunas de origem do lead com o service
   client; resolve o nome da campanha:
   - Meta: `meta_ad_campaigns.campaign_name` onde `ad_id = meta_ad_id`;
   - Google: nomes distintos de `ad_spend` com `platform='google'` → `resolveGoogleCampaignName`.
   Falha na busca de campanha **não** derruba a resposta: segue com `campaignName=null`.
   404 se o lead não existe. Resposta: `LeadOrigin`.
3. **`useLeadOrigin(leadId)`** — hook no padrão de `use-lead-quotes.ts` (fetch + loading).
4. **`<LeadOriginBlock leadId />`** — bloco "Origem": badge (tipo · canal) + linha de detalhe
   (campanha / página / indicador / lote) + linha "via página X" quando pago e veio de LP.
5. Integração: substitui os dois badges em `crm-perfil-tab.tsx`; entra no topo da aba
   "Dados Gerais" do `lead-detail-modal.tsx`.

Sem migration, sem mudança no backend Python, sem aumentar `LEAD_FIELDS` das conversas.

## Contrato

```ts
type LeadOriginKind = "pago" | "organico" | "importado" | "sem_rastreio";
interface LeadOrigin {
  kind: LeadOriginKind;
  channel: string;        // "Meta Ads", "Google Ads", "WhatsApp direto", "Landing page", ...
  detail: string | null;  // campanha, nome da página, "de Fulano", "Lote 3"
  page: string | null;    // página de LP quando o lead é pago e passou por LP
}
```

## Regras (primeira que casar vence; espelham `derive_channel` de `traffic_report.py`)

| # | Sinal | kind · channel | detail |
|---|---|---|---|
| 1 | `gclid`, ou utm_source ∈ fontes Google e utm_medium ∈ meios pagos | pago · Google Ads | campanha resolvida ?? utm_campaign ?? "Campanha não identificada" |
| 2 | `fbclid`/`ctwa_clid`/`meta_ad_id`, ou utm_source ∈ fontes Meta | pago · Meta Ads | idem |
| 3 | `traffic_type='paid'` sem casar acima | pago · utm_source capitalizado ou "Anúncio" | utm_campaign ?? "Campanha não identificada" |
| 4 | `metadata.referral.nome` | organico · Indicação | "de {nome}" |
| 5 | `metadata.origem='reativacao_bling'` | importado · Reativação Bling | "Lote {lote}" ou null |
| 6 | `channel='bling'` ou `metadata.origem='bling_webhook'` | importado · Bling | null |
| 7 | utm_source instagram/facebook | organico · Instagram / Facebook | utm_campaign ?? utm_medium ?? null |
| 8 | outro utm_source (não pago) | organico · utm_source capitalizado | utm_campaign ?? null |
| 9 | `metadata.origem` string (LP) | organico · Landing page | label de `LP_ORIGINS` ou o próprio valor |
| 10 | `channel='manual'` | importado · Cadastro manual | null |
| 11 | `channel='campaign'` | importado · Importação de campanha | null |
| 12 | `channel` whatsapp/evolution | organico · WhatsApp direto | null |
| 13 | nada | sem_rastreio · Sem rastreio | null |

`page` = label de LP de `metadata.origem` nos casos 1-3 (quando existir e não for origem de
importação), senão null. Para 7/8 com LP, `page` também é preenchido.

## Erros

- Rota: 401 sem sessão, 404 lead inexistente, 500 só se a leitura do lead falhar.
- UI: carregando → "Carregando origem…"; fetch falhou → bloco oculta a linha de detalhe e
  mostra "Origem indisponível". Nunca quebra o painel.

## Testes

- `lead-origin.test.ts`: cada linha da tabela + precedências (gclid vence meta_ad_id; referral
  vence LP; campanha resolvida vence utm_campaign; page em lead pago via LP) +
  `resolveGoogleCampaignName` (idêntico, subconjunto único, empate → null, vazio → null).
- `route.test.ts`: 401 sem sessão; 404; Meta resolve nome; falha em `meta_ad_campaigns` → 200
  com "Campanha não identificada".
