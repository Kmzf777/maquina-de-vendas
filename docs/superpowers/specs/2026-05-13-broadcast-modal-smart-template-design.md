# Broadcast Modal — Smart Template Support Design

**Date:** 2026-05-13  
**Status:** Approved

## Goal

Make the broadcast wizard handle **any Meta template** correctly: positional params (`{{1}}`, `{{2}}`), named params, media headers (IMAGE / VIDEO / DOCUMENT). Variables map via token picker with auto-suggestions. Full validation before advancing to Leads step.

## Problem Statement

The modal breaks silently for templates with positional params because `extractParams` only reads `body_text_named_params`. When `body_text_named_params` is absent (most old templates), params array is empty, no fields are shown, `template_variables` is sent as `{}`, and Meta returns 400.

Additionally, templates with IMAGE/VIDEO/DOCUMENT headers have no UI support at all.

---

## Architecture

### Files Changed

| File | Change |
|------|--------|
| `frontend/src/app/api/channels/[id]/templates/route.ts` | Enhance parser: positional params, header type, footer, paramsType |
| `frontend/src/components/campaigns/template-preview-card.tsx` | Rebuild: media header, token picker per slot, auto-suggest, validation |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Update: canGoToStep3, handleSelectTemplate init, handleCreate storage |
| `backend/app/broadcast/worker.py` | Update `_build_template_components`: positional + media header + new tokens |

No DB migration required — media URL and params type stored inside existing `template_variables` JSONB using `__key__` prefixes.

---

## Section 1 — Template Parsing

### Extended `MetaTemplate` type

```typescript
interface TemplateParam {
  index: number;        // 1-based (1, 2, 3…)
  paramName: string;    // named: "first_name"; positional: "1", "2", "3"
  example: string;      // from Meta's example data
}

interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;        // if TEXT header
  example?: string;     // example URL for media types
}

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
}
```

### Detection logic (in `route.ts`)

**Named params:** `body.example.body_text_named_params` exists and has items.

**Positional params:** `body_text_named_params` is absent or empty, but `body.example.body_text[0]` exists. Param count = `body_text[0].length`. Names = "1", "2", "3", …

**No params:** Neither present. Scan body text for `{{N}}` as fallback. If still none, `paramsType = "none"`.

**Header parsing:**
```typescript
const header = components.find(c => c.type === "HEADER");
if (header) {
  if (header.format === "TEXT") { type: "TEXT", text: header.text }
  if (header.format === "IMAGE") { type: "IMAGE", example: header.example?.header_url?.[0] }
  if (header.format === "VIDEO") { type: "VIDEO", example: header.example?.header_url?.[0] }
  if (header.format === "DOCUMENT") { type: "DOCUMENT", example: header.example?.header_url?.[0] }
}
```

**Footer parsing:** `components.find(c => c.type === "FOOTER")?.text ?? null`

---

## Section 2 — Variable Mapping (Token Picker)

### Available tokens

| Token | Resolves to |
|-------|------------|
| `{{primeiro_nome}}` | Primeira palavra do `lead.name` |
| `{{nome_completo}}` | `lead.name` completo |
| `{{telefone}}` | `lead.phone` |
| `{{empresa}}` | `lead.company` ou `lead.nome_fantasia` |
| `texto_fixo` | Texto estático digitado pelo usuário |

### Auto-suggest from example

```
example is digits/spaces/dashes and len ≥ 8  →  {{telefone}}
example has no spaces                          →  {{primeiro_nome}}
example has 2–3 words                          →  {{nome_completo}}
otherwise                                      →  texto_fixo (empty input)
```

### UI per variable slot

Each `{{N}}` or `{{param_name}}` in the body renders inline as a dropdown:

```
[dropdown ▼]  with options:
  ⚡ Primeiro nome
  ⚡ Nome completo
  ⚡ Telefone
  ⚡ Empresa
  ✏ Texto fixo → reveals text input below
```

Auto-suggest pre-selects the best match on template selection. User can change.

---

## Section 3 — Media Header

When `header.type` is `IMAGE`, `VIDEO`, or `DOCUMENT`:

- Show a media placeholder card above the body in `TemplatePreviewCard`
- Show a URL input: "URL da mídia (imagem/vídeo/documento)"
- This URL is stored as `varValues["__header_url__"]` via `onVarChange("__header_url__", url)`
- Required to advance: if header is media type and `__header_url__` is empty, `canGoToStep3 = false`

Text header (`type: "TEXT"`): displayed as-is, no input needed.

---

## Section 4 — Validation (`canGoToStep3`)

```typescript
const canGoToStep3 =
  selectedTemplate !== null &&
  // All body params must have non-empty values
  selectedTemplate.params.every(p => {
    const v = templateVarValues[p.paramName] ?? "";
    return v !== "" && v !== "texto_fixo";  // "texto_fixo" alone = not filled
  }) &&
  // Media header must have URL
  (
    !selectedTemplate.header ||
    selectedTemplate.header.type === "TEXT" ||
    (templateVarValues["__header_url__"] ?? "").trim() !== ""
  );
```

For "texto fixo" option: `varValues[param]` holds the static string (not the literal "texto_fixo"). See UI detail below.

---

## Section 5 — Storage Format in `template_variables`

All metadata stored in existing `template_variables` JSONB. Reserved keys use `__prefix__`:

```json
{
  "__params_type__": "positional",
  "__header_type__": "IMAGE",
  "__header_url__": "https://cdn.example.com/promo.jpg",
  "1": "{{primeiro_nome}}",
  "2": "{{nome_completo}}",
  "3": "{{telefone}}"
}
```

Named params example:
```json
{
  "__params_type__": "named",
  "first_name": "{{primeiro_nome}}",
  "city": "São Paulo"
}
```

No params, no header: `template_variables = null` (sent as null to API).

---

## Section 6 — Backend `_build_template_components`

Updated function in `backend/app/broadcast/worker.py`:

```python
def _build_template_components(template_variables: dict, lead: dict) -> list | None:
    if not template_variables:
        return None

    params_type = template_variables.get("__params_type__", "named")
    header_type = template_variables.get("__header_type__")
    header_url = template_variables.get("__header_url__")

    # Only non-reserved keys are body variable mappings
    body_vars = {k: v for k, v in template_variables.items() if not k.startswith("__")}

    components = []

    # Header component (media only)
    if header_type in ("IMAGE", "VIDEO", "DOCUMENT") and header_url:
        media_key = header_type.lower()
        components.append({
            "type": "header",
            "parameters": [{"type": media_key, media_key: {"link": header_url}}],
        })

    # Body component
    if params_type == "positional":
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(x[0]) if x[0].isdigit() else 999
        )
        parameters = [{"type": "text", "text": _resolve_value(v, lead)} for _, v in ordered]
    else:
        parameters = [
            {"type": "text", "parameter_name": k, "text": _resolve_value(v, lead)}
            for k, v in body_vars.items()
        ]

    if parameters:
        components.append({"type": "body", "parameters": parameters})

    return components if components else None
```

### New tokens added to `_LEAD_FIELD_TOKENS`

```python
"{{primeiro_nome}}": lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
"{{nome_completo}}": lambda lead: lead.get("name") or "",
"{{telefone}}":      lambda lead: lead.get("phone") or "",
"{{empresa}}":       lambda lead: lead.get("company") or lead.get("nome_fantasia") or "",
```

Existing tokens (`{{first_name}}`, `{{lead_name}}`, `{{phone}}`) kept for backward compat.

---

## Section 7 — Backward Compatibility

Old broadcasts stored without `__params_type__`:
- Worker defaults `params_type = template_variables.get("__params_type__", "named")`
- Processes as named → same behavior as before ✓

Old broadcasts stored without `__header_url__`:
- `header_type` is None → no header component added ✓

---

## What Is NOT in Scope

- Header text variables (TEXT header with `{{1}}`) — rare, skip for now
- Button URL dynamic parameters — not supported by this design
- Scheduling broadcasts — separate feature
- Preview with actual lead data from the database — preview uses example values only
