# Rastreamento de leads nas Landing Pages — o que enviar

Contrato do `POST /webhook/landing-page` e o que configurar em cada plataforma para o
/trafego conseguir cruzar lead → campanha → venda.

---

## 1. Payload completo

```jsonc
{
  // --- identificação (já enviados hoje) ---
  "nome": "Maria Silva",
  "whatsapp": "34991461669",
  "email": "maria@exemplo.com",
  "timestamp": "2026-08-21T14:32:00-03:00",
  "origem": "atacado",              // identificador da página — SEMPRE preencher

  // --- rastreio de tráfego pago ---
  "gclid": "",                      // Google auto-tagging
  "fbclid": "",                     // Meta
  "meta_ad_id": "",                 // ID do anúncio do Meta ({{ad.id}})
  "utm_source": "",
  "utm_medium": "",
  "utm_campaign": ""
}
```

Campos ausentes ou vazios são simplesmente ignorados — **nunca apagam** um rastreio já
capturado do lead (o backend faz first-touch na criação e last-touch em cliques novos).
Chaves fora dessa lista são descartadas por whitelist.

> `origem` é o que decide o funil (atacado / terceirização). A página
> `/terceirizacaocafe` historicamente não enviava esse campo — vale conferir.

---

## 2. O campo que faz diferença: `meta_ad_id`

`utm_campaign` casa com a campanha **por nome**. Isso funciona, mas quebra quando alguém
renomeia a campanha no Gerenciador — e obriga o utm a espelhar o nome.

`meta_ad_id` resolve a campanha **pelo ID do anúncio**, via a tabela `meta_ad_campaigns`
que o sync do Meta alimenta. É exato e imune a renomeação. Quando presente, ele **vence**
qualquer casamento por nome.

O equivalente para o Google (`{campaignid}`) ainda não é consumido — lá o casamento é por
tokens do `utm_campaign`, e hoje resolve corretamente todas as campanhas com gasto (os 10
slugs em uso caem nas 3 campanhas certas; só `atacado_grupo2`, com 1 lead, fica de fora).

---

## 3. O que configurar em cada plataforma

### Meta Ads — campo "Parâmetros de URL" do anúncio

```
utm_source=metaads&utm_medium=paid_social&utm_campaign={{campaign.name}}&meta_ad_id={{ad.id}}
```

`{{ad.id}}` e `{{campaign.name}}` são macros que a Meta substitui no clique. O `fbclid` a
própria Meta anexa sozinha.

> **Use `utm_source=metaads`, não `facebook` nem `instagram`.** O /trafego trata
> `instagram`/`facebook` crus como tráfego **orgânico** (link da bio) — taguear assim joga
> o lead pago para fora do canal Meta Ads.

### Google Ads

1. **Auto-tagging ligado** (Configurações da conta → "Marcação automática") → traz o `gclid`.
2. Sufixo de URL final, **por campanha**, com o nome escrito à mão:

```
utm_source=google&utm_medium=cpc&utm_campaign=leads_search_terceirizacao
```

Não existe macro ValueTrack para o *nome* da campanha (`{campaignid}` devolve o ID, e
`{_algo}` exige criar um parâmetro personalizado em cada campanha). O casamento usa tokens,
então o slug não precisa ser idêntico ao nome — basta que suas palavras apareçam nele:
`leads_search_terceirizacao` casa com `Leads-Search | Terceirização | 20.03.24`. Datas,
números e o sufixo `_sitelink_NN` são ignorados no casamento.

> `utm_medium` importa: é ele que desempata quando duas campanhas cabem no mesmo slug
> (`atacado` + `medium=pmax` → "PMAX | Atacado"; `atacado` + `medium=cpc` → a de Search).
> Use `pmax` nas campanhas Performance Max e `cpc` nas de Search.

---

## 4. Captura no JS da LP — o erro clássico

Os parâmetros chegam na **URL de entrada**. Se a pessoa navega para outra página antes de
enviar o formulário, eles somem. Grave no primeiro load e leia na hora do submit:

```js
const CAMPOS = ["gclid", "fbclid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign"];

// No carregamento de QUALQUER página: guarda o primeiro toque e não sobrescreve com vazio.
(function capturaRastreio() {
  const url = new URLSearchParams(location.search);
  CAMPOS.forEach((c) => {
    const v = (url.get(c) || "").trim();
    if (v && !sessionStorage.getItem(c)) sessionStorage.setItem(c, v);
  });
})();

// No submit:
const rastreio = Object.fromEntries(
  CAMPOS.map((c) => [c, sessionStorage.getItem(c) || ""])
);
fetch("https://webhook.canastrainteligencia.com/webhook/landing-page", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ nome, whatsapp, email, timestamp, origem, ...rastreio }),
});
```

---

## 5. O que a LP NÃO resolve: Click-to-WhatsApp

Anúncio CTWA (`PL | WA`, `Atacado | WA`) manda a pessoa direto para o WhatsApp — **não passa
por landing page nenhuma**. Nesse caminho o rastreio vem do webhook da Meta
(`referral.source_id` → `leads.meta_ad_id`), não do formulário. Nada a fazer na LP.

Hoje 100% do tráfego pago do Meta é CTWA (`fbclid` = 0 em 2.503 leads nos últimos 30 dias).
Os campos de Meta acima só passam a valer quando existir campanha de Meta apontando para LP.

---

## 6. Conferindo se funcionou

Abra a LP com os parâmetros na mão e veja o lead entrar rastreado:

```
https://atacado.cafecanastra.com/cafeatacado?utm_source=metaads&utm_medium=paid_social&utm_campaign=Teste&meta_ad_id=120250281981050163
```

| Sintoma no /trafego | Causa provável |
|---|---|
| Lead em "Sem rastreio" | LP não enviou nada — parâmetros perdidos na navegação (ver §4) |
| Lead em "Orgânico" sendo pago | `utm_source=facebook/instagram`, ou `utm_medium` fora da lista paga |
| Linha "(não atribuído)" no Meta | sem `meta_ad_id` (ou é lead de CTWA anterior a 21/08/2026) |
| Linha "(não atribuído)" no Google | `utm_campaign` não casa com nome nenhum de campanha |
