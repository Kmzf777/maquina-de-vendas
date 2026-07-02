# Handoff — Atribuição de origem nas Landing Pages (organic vs paid + UTMs)

> **Para quem é este doc:** as IAs/desenvolvedores que trabalham **nos repositórios das Landing Pages** (Next.js — ex.: `app/graocafeteria`, `app/cafeatacado`, `app/terceirizacaocafe`, `components/whatsapp-chat.tsx`). **Não é código deste CRM.**
>
> **Objetivo:** fazer a LP **capturar** os identificadores de origem (cliques pagos + UTMs) e **enviá-los** no webhook que já existe, para o CRM distinguir **tráfego pago × orgânico** e atribuir conversões no Google/Meta Ads.
>
> Supersede o endpoint citado na spec `2026-07-02-ad-conversion-attribution-design.md` §9.1 — **use o endpoint real abaixo**, não `api.canastrainteligencia.com`.

---

## 1. Como o sistema decide "orgânico" vs "pago"

A distinção vem dos parâmetros da URL de entrada:

| Sinal presente na URL | Classificação |
|---|---|
| `gclid` (Google Ads) | **pago** |
| `fbclid` (Meta/site) ou `ctwa_clid` (Click-to-WhatsApp) | **pago** |
| `utm_medium` ∈ `cpc, ppc, paid, paid_social, paidsocial, paid_search, display, cpm` | **pago** |
| `utm_medium` ∈ `organic, social, bio, referral, email, qr, sms` | **orgânico** |
| nenhum parâmetro (acesso direto / digitado) | **orgânico (direto)** |

**Regra de ouro:** o **pago se identifica sozinho** pelos click-ids (`gclid`/`fbclid`/`ctwa_clid`) — Google e Meta injetam isso automaticamente. O **orgânico só é distinguível se você marcar os links com UTM** (é aí que entra a Seção 2). Sem UTM, um clique da bio do Instagram é indistinguível de acesso direto.

---

## 2. Taxonomia de UTM — como gerar os links (bio, stories, etc.)

Padronize **todos** os links orgânicos que você distribui manualmente. Formato:
`https://SEU-DOMINIO/PAGINA?utm_source=<origem>&utm_medium=<meio>&utm_campaign=<campanha>`

| Onde você vai colar o link | `utm_source` | `utm_medium` | `utm_campaign` (exemplo) |
|---|---|---|---|
| Bio do Instagram | `instagram` | `bio` | `link_bio` |
| Bio do TikTok | `tiktok` | `bio` | `link_bio` |
| Linktree / link-in-bio | `linktree` | `bio` | `botao_atacado` |
| Stories orgânico (Instagram) | `instagram` | `organic` | `stories_2026_07` |
| Post/Reels orgânico | `instagram` | `organic` | `reels_cafe_especial` |
| Status do WhatsApp | `whatsapp` | `status` | `oferta_julho` |
| Assinatura de e-mail / newsletter | `newsletter` | `email` | `boas_vindas` |
| Descrição do YouTube | `youtube` | `organic` | `video_torra` |
| QR code impresso (embalagem/feira) | `qrcode` | `qr` | `feira_sp_2026` |
| Google Ads | *(não marcar à mão)* | `cpc` | *(auto-tagging + gclid resolvem)* |
| Meta Ads (feed/stories) | `facebook` / `instagram` | `paid_social` | *(fbclid/ctwa resolvem)* |

**Regras:**
- Sempre minúsculas, sem espaços (use `_`), sem acento.
- `utm_source` = **de onde** vem; `utm_medium` = **o tipo** de tráfego (é ele que classifica organic/paid); `utm_campaign` = **qual ação/campanha**.
- Em **anúncios pagos** confie nos click-ids; UTM é opcional lá. Em **orgânico** o UTM é obrigatório para não virar "direto".

### Links de bio prontos (troque `SEU-DOMINIO` e a página)
```
https://SEU-DOMINIO/cafeatacado?utm_source=instagram&utm_medium=bio&utm_campaign=link_bio
https://SEU-DOMINIO/graocafeteria?utm_source=tiktok&utm_medium=bio&utm_campaign=link_bio
https://SEU-DOMINIO/terceirizacaocafe?utm_source=linktree&utm_medium=bio&utm_campaign=botao_private_label
```
> Dica: gere e encurte esses links com um encurtador que **preserve os parâmetros** (o encurtador não pode dropar a query string).

---

## 3. PROMPT para colar no repositório de cada Landing Page

Copie o bloco abaixo inteiro e entregue ao Claude que trabalha no repo da LP.

````text
CONTEXTO
Esta é uma landing page Next.js/React que gera leads. Os formulários já disparam 2 webhooks
em paralelo (Promise.all) com o payload:
  { nome, whatsapp, email, timestamp, origem }
para:
  1) https://n8n.canastrainteligencia.com/webhook-test/landing-page   (n8n)
  2) https://webhook.canastrainteligencia.com/webhook/landing-page    (produção — CRM)

O CRM precisa distinguir tráfego PAGO x ORGÂNICO e atribuir conversões no Google/Meta Ads.
Para isso, a LP deve CAPTURAR os identificadores de origem da URL e ENVIÁ-LOS no MESMO webhook.

TAREFA
1) Crie um utilitário de captura de atribuição (client-side), ex. `lib/attribution.ts`:
   - Ao carregar QUALQUER página, leia da URL (query string) estes parâmetros, se presentes:
     gclid, fbclid, utm_source, utm_medium, utm_campaign, utm_content, utm_term
   - Persista em localStorage sob a chave "cc_attribution" com um timestamp, VÁLIDO POR 90 DIAS.
   - Regra de gravação (last-touch de visita marcada): se a URL atual tiver QUALQUER um desses
     parâmetros, SOBRESCREVA o armazenado; se a URL não tiver nenhum, MANTENHA o que já estava
     (não apague). Assim um clique pago posterior atualiza a atribuição, mas navegar entre
     páginas sem parâmetros não zera nada.
   - Exponha:
       getAttribution(): { gclid, fbclid, utm_source, utm_medium, utm_campaign, utm_content, utm_term }
       getTrafficType(): "paid" | "organic"
     Regra de getTrafficType:
       "paid" se: gclid OU fbclid presentes, OU utm_medium ∈
                  {cpc, ppc, paid, paid_social, paidsocial, paid_search, display, cpm};
       senão "organic".
   - Fallback de origem orgânica: se NÃO houver utm_source e houver document.referrer de um
     domínio externo conhecido (instagram, facebook, google, tiktok, youtube, bing),
     preencha utm_source=<esse domínio> e utm_medium="referral" (não sobrescreve UTM real).
   - Código defensivo: try/catch em torno de localStorage (modo privado pode lançar); nunca
     quebre a página nem o submit por causa disso.

2) No SUBMIT de TODOS os formulários/chats que disparam o webhook (inclui
   components/whatsapp-chat.tsx e as páginas app/*/page.tsx), MONTE o payload assim:
     const attr = getAttribution();
     const payload = {
       nome, whatsapp, email, timestamp, origem,   // <- campos que já existem, NÃO remover
       gclid: attr.gclid ?? "",
       fbclid: attr.fbclid ?? "",
       utm_source: attr.utm_source ?? "",
       utm_medium: attr.utm_medium ?? "",
       utm_campaign: attr.utm_campaign ?? "",
       traffic_type: getTrafficType(),             // "paid" | "organic"
     };
   Envie ESSE payload nos DOIS webhooks (o mesmo objeto no Promise.all). Campo ausente => "".

3) NÃO altere as URLs dos webhooks, não remova campos existentes, não mude o fluxo de
   redirecionamento das páginas de "obrigado". A mudança é ADITIVA.

4) Preencha o campo `origem` também na página /terceirizacaocafe (hoje ele vai vazio):
   use origem="terceirizacao".

REGRAS DE CONTRATO (não renomear — o CRM depende destes nomes exatos)
- Nomes de campo: gclid, fbclid, utm_source, utm_medium, utm_campaign, traffic_type.
- whatsapp: só dígitos com DDI (ex. 5534999999999).
- O endpoint de produção sempre responde HTTP 200; não trate a resposta como validação.
- Campos que não existirem devem ir como string vazia "", nunca omitidos.

ENTREGÁVEL
- lib/attribution.ts (ou equivalente) + a captura chamada no layout/_app para rodar em toda página.
- Todos os pontos de submit atualizados para incluir os novos campos nos dois webhooks.
- Teste manual: acesse a página com
  ?gclid=TESTE123&utm_source=google&utm_medium=cpc  -> submeta -> confirme no payload
  gclid=TESTE123, utm_source=google, utm_medium=cpc, traffic_type="paid".
  E com ?utm_source=instagram&utm_medium=bio -> traffic_type="organic".
````

---

## 4. Como o CRM usa isso (contexto — não é tarefa da LP)

- `gclid` → conversões do Google Ads (o CRM gera um CSV para importação manual).
- `fbclid`/`ctwa_clid` → Meta CAPI (automático).
- `utm_source/medium/campaign` → gravados no lead (first-touch na criação + last-touch depois).
- `traffic_type` (paid/organic) → hoje **derivável no CRM** a partir de `utm_medium`/`gclid`/`fbclid`
  já gravados; enviar o campo pronto pela LP é conveniência. **Para o CRM armazenar/exibir
  explicitamente `traffic_type`, é preciso uma pequena mudança no CRM** (coluna + persistência
  no `lp_webhook`) — ainda NÃO feita. Peça se quiser.

**Dependência do lado CRM:** a migration `20260618_leads_traffic_tracking.sql` (colunas
`leads.gclid/fbclid/utm_*`) precisa estar aplicada no Supabase para os campos persistirem.
