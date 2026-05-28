# Integração Webhook LP → CRM Canastra

Este documento descreve as alterações necessárias nas landing pages para substituir o n8n pelo endpoint nativo do CRM.

---

## Mudança necessária

Cada formulário/chat das LPs dispara dois webhooks em paralelo. O endpoint do **n8n deve ser substituído** pelo endpoint do CRM abaixo.

### Endpoint antigo (n8n — REMOVER)
```
https://n8n.canastrainteligencia.com/webhook-test/landing-page
```

### Endpoint novo (CRM — ADICIONAR)
```
https://crm.canastrainteligencia.com/webhook/landing-page
```

> O endpoint de produção existente (`https://webhook.canastrainteligencia.com/webhook/landing-page`) pode continuar ou ser removido — confirme com o time do CRM.

---

## Payload esperado

```json
{
  "nome": "João Silva",
  "whatsapp": "5534999999999",
  "email": "joao@email.com",
  "timestamp": "2026-05-28T10:00:00.000Z",
  "origem": "graocafeteria"
}
```

### Campos

| Campo       | Tipo   | Obrigatório | Descrição                                                  |
|-------------|--------|-------------|------------------------------------------------------------|
| `nome`      | string | Sim         | Nome completo do lead                                      |
| `whatsapp`  | string | Sim         | Telefone WhatsApp. Pode vir com ou sem `+`, com ou sem `55`. O CRM normaliza automaticamente. |
| `email`     | string | Não         | E-mail do lead. Pode ser string vazia `""`.               |
| `timestamp` | string | Não         | ISO 8601. Se ausente, o CRM usa o horário do recebimento. |
| `origem`    | string | Recomendado | Identifica a página/formulário de origem (ver tabela abaixo). |

### Valores de `origem` por página

| Página / Componente                    | `origem` recomendado  |
|----------------------------------------|-----------------------|
| Formulário `/graocafeteria`            | `"graocafeteria"`     |
| Chat WhatsApp em `/cafeatacado`        | `"atacado"`           |
| Chat WhatsApp em `/terceirizacaocafe`  | `"terceirizacao"`     |
| Formulário `/terceirizacaocafe`        | `"terceirizacao"`     |
| Chat WhatsApp em outras páginas        | `"Chat WhatsApp"`     |

> **Ação pendente:** O formulário de `/terceirizacaocafe` não envia o campo `origem`. Adicionar `origem: "terceirizacao"` ao payload.

---

## Resposta do endpoint

O endpoint sempre retorna HTTP 200 para não interromper o fluxo de redirecionamento da LP.

**Sucesso:**
```json
{ "ok": true, "lead_id": "uuid", "conversation_id": "uuid" }
```

**Erro (ex: telefone inválido):**
```json
{ "ok": false, "error": "Telefone inválido" }
```

---

## Exemplo de implementação (código das LPs)

### Antes (n8n)
```typescript
const WEBHOOK_URLS = [
  "https://n8n.canastrainteligencia.com/webhook-test/landing-page",
  "https://webhook.canastrainteligencia.com/webhook/landing-page",
];
```

### Depois (CRM)
```typescript
const WEBHOOK_URLS = [
  "https://crm.canastrainteligencia.com/webhook/landing-page",
  // remover ou manter o segundo endpoint conforme necessidade
];
```

### Payload completo (exemplo)
```typescript
const payload = {
  nome: formData.nome,
  whatsapp: formData.whatsapp,
  email: formData.email || "",
  timestamp: new Date().toISOString(),
  origem: "graocafeteria", // ajustar por página
};

await Promise.all(
  WEBHOOK_URLS.map((url) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => null) // falha silenciosa, não bloqueia redirect
  )
);
```

---

## O que o CRM faz com o lead recebido

1. Normaliza o telefone para E.164 (ex: `5534999999999`)
2. Cria ou atualiza o lead no banco (sem duplicação por telefone)
3. Salva `email` e `origem` no cadastro do lead
4. Cria uma conversa na inbox da Valéria
5. Após o delay configurado (padrão: 15 min), dispara automaticamente um template WhatsApp para o lead

---

## Configuração do template e delay

O template e o delay são configuráveis pelo CRM em **Configurações → Webhook de Landing Pages**. Não há necessidade de alterar código das LPs para mudar o template ou o tempo de espera.
