# Spec: Correções de Design + Bug de Notas — CRM Panel /conversas

**Data:** 2026-05-20  
**Status:** Aprovado

---

## Problemas

### Design
1. **Header muito alto** — avatar 64px centralizado + padding gera ~150px de altura desnecessária
2. **Tab bar texto pequeno** — `text-[11px]` é ilegível em 4 abas comprimidas
3. **Métricas: card "Fonte" transborda** — grid 3 colunas com `text-[20px]` em card ~91px. "whatsapp" não cabe
4. **Perfil: duplicata de stage** — bloco redundante (dot + label) abaixo do `<select>` de stage

### Bug Notas
1. **Sem feedback de erro** — se `res.ok` for false, nada acontece visualmente
2. **Author hardcoded como "Rafael"** — inconsistente e pode causar falha silenciosa de insert; trocar para `"Vendedor"`

---

## Solução

### Header (`contact-detail.tsx`)
Layout inline: avatar 40px à esquerda + nome/telefone/badges à direita. Altura total ~64px.

```
[●40px] Nome do Lead         
        5551996729739  [Canal badge] [Em espera?]
```

### Tab bar (`contact-detail.tsx`)
- `text-[11px]` → `text-[12px]`
- `py-2.5` → `py-2`

### Métricas tab (`crm-metricas-tab.tsx`)
- Grid Engajamento: 3 colunas → 2 colunas (Dias no CRM + Dias no stage)
- "Fonte" (lead.channel): mover para seção Detalhes como linha key-value

### Perfil tab (`crm-perfil-tab.tsx`)
- Remover bloco redundante (linhas 104-109): o dot colorido + label após o select de stage

### Notas tab (`crm-notas-tab.tsx`)
- Adicionar estado `error: string | null`
- No `handleAddNote`: se `!res.ok`, setar `setError("Erro ao salvar nota. Tente novamente.")`
- Se ok: limpar erro
- Mostrar mensagem de erro inline abaixo do input
- Trocar `author: "Rafael"` por `author: "Vendedor"`

---

## Arquivos a modificar
- `frontend/src/components/conversas/contact-detail.tsx`
- `frontend/src/components/conversas/tabs/crm-metricas-tab.tsx`
- `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`
- `frontend/src/components/conversas/tabs/crm-notas-tab.tsx`
