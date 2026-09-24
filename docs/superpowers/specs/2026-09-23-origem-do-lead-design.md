# Origem do lead detalhada em /leads e /conversas — design

Data: 23/09/2026 · Status: aprovado pelo usuário

## Problema

- `/conversas` (aba Perfil do painel do lead, `crm-perfil-tab.tsx:213-231`) só mostra o badge
  "Pago · utm_source" / "Orgânico · utm_source" — nunca a campanha.
- `/leads` (modal `lead-detail-modal.tsx`, aba "Dados Gerais") não mostra origem nenhuma.
- O banco já guarda muito mais: `meta_ad_id` (→ `meta_ad_campaigns.campaign_name`), `gclid`,
  `fbclid`, `ctwa_clid`, UTMs completas, `metadata.origem` (funil de LP / importação),
  `metadata.lote`, `channel`.

## Decisões do usuário

- Nível de detalhe: **canal + campanha** (sem nome do anúncio — não é guardado; sem UTMs cruas).
- Sub-origens orgânicas: WhatsApp direto · Landing page (label do funil) · Instagram/Facebook
  orgânico (via UTM) · Bling · Reativação Bling · Cadastro manual / importação · Sem rastreio.
  (`metadata.referral`, gravado no lead que indicou — não no indicado —, não é usado como sinal
  de origem; ver "Regras" abaixo.)

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
   (campanha / label do funil / lote) + linha "Funil: X" quando pago e veio de um funil de LP.
5. Integração: substitui os dois badges em `crm-perfil-tab.tsx`; entra no topo da aba
   "Dados Gerais" do `lead-detail-modal.tsx`.

Sem migration, sem mudança no backend Python, sem aumentar `LEAD_FIELDS` das conversas.

## Contrato

```ts
type LeadOriginKind = "pago" | "organico" | "importado" | "sem_rastreio";
interface LeadOrigin {
  kind: LeadOriginKind;
  channel: string;        // "Meta Ads", "Google Ads", "WhatsApp direto", "Landing page", ...
  detail: string | null;  // campanha, nome da página, "Lote 3"
  funnel: string | null;  // funil (metadata.origem) que o lead passou, quando o lead é pago
}
```

## Regras (primeira que casar vence; espelham `derive_channel` de `traffic_report.py`)

| # | Sinal | kind · channel | detail |
|---|---|---|---|
| 1 | `gclid`, ou utm_source ∈ fontes Google e utm_medium ∈ meios pagos | pago · Google Ads | campanha resolvida ?? utm_campaign ?? "Campanha não identificada" |
| 2 | `fbclid`/`ctwa_clid`/`meta_ad_id`, ou utm_source ∈ fontes Meta | pago · Meta Ads | idem |
| 3 | `traffic_type='paid'` sem casar acima | pago · utm_source capitalizado ou "Anúncio" | utm_campaign ?? "Campanha não identificada" |
| 4 | `metadata.origem='reativacao_bling'` | importado · Reativação Bling | "Lote {lote}" ou null |
| 5 | `channel='bling'` ou `metadata.origem='bling_webhook'` | importado · Bling | null |
| 6 | utm_source instagram/facebook | organico · Instagram / Facebook | utm_campaign ?? utm_medium ?? null |
| 7 | outro utm_source (não pago) | organico · utm_source capitalizado | utm_campaign ?? null |
| 8 | `metadata.origem` string (LP/funil) | organico · Landing page | label de `LP_ORIGINS` ou o próprio valor |
| 9 | `channel='manual'` | importado · Cadastro manual | null |
| 10 | `channel='campaign'` | importado · Importação de campanha | null |
| 11 | `channel='whatsapp'` (exato — `evolution` não conta: é o default legado do schema, inclusive de disparos em massa, não evidência de contato inbound) | organico · WhatsApp direto | null |
| 12 | nada | sem_rastreio · Sem rastreio | null |

`metadata.referral` (gravado por `registrar_indicacao`) fica no lead que FEZ a indicação, não no
indicado — não é sinal de origem e é ignorado por `describeLeadOrigin`.

`funnel` = label de LP/funil de `metadata.origem` nos casos 1-3 (quando existir e não for origem
de importação), senão null. Para 6/7 com funil, `funnel` também é preenchido. CTWA e outros
anúncios também gravam `metadata.origem` ("atacado"/"terceirizacao"): é o funil que o lead passou,
não necessariamente uma landing page — daí o campo se chamar `funnel`, e a UI mostrar
"Funil: {funnel}" em vez de "via página {page}".

A detecção de plataforma (regras 1-2) usa `paidPlatform(lead)`, exportado de `lead-origin.ts`, e a
rota consulta `meta_ad_campaigns`/`ad_spend` apenas quando essa plataforma bate — nunca os dois,
mesmo quando o lead tem `fbclid` E `utm_campaign` que também caça um nome em `ad_spend` (evita
"Meta Ads / <nome de campanha Google>").

## Erros

- Rota: 401 sem sessão, 404 lead inexistente, 500 só se a leitura do lead falhar.
- UI: carregando → "Carregando origem…"; fetch falhou → bloco oculta a linha de detalhe e
  mostra "Origem indisponível". Nunca quebra o painel.

## Testes

- `lead-origin.test.ts`: cada linha da tabela + precedências (gclid vence meta_ad_id; referral no
  metadata é ignorado; campanha resolvida vence utm_campaign; funnel em lead pago via LP;
  `channel='evolution'` não é WhatsApp direto) + `paidPlatform` (mesma ordem, isolado) +
  `resolveGoogleCampaignName` (idêntico, subconjunto único, empate → null, vazio → null).
- `route.test.ts`: 401 sem sessão; 404; Meta resolve nome; falha em `meta_ad_campaigns` → 200
  com "Campanha não identificada"; Meta com utm_campaign que bateria no Google não credita a
  campanha Google (nem consulta `ad_spend`); lead orgânico com utm_campaign não consulta
  `ad_spend`.
