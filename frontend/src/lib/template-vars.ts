import type { TemplateHeader, TemplateParam } from "@/lib/template-parser";

/**
 * Monta o mapa de variaveis de um template Meta para envio ao backend.
 *
 * Fonte unica para TODOS os modais de disparo. Antes cada modal montava esse
 * mapa por conta propria, e o Disparo Rapido — a unica copia que esquecia as
 * chaves reservadas — gerava payload invalido: sem `__params_type__`, o worker
 * cai no default "named" (backend/app/broadcast/worker.py:278) e monta
 * `parameter_name: "1"` para template posicional, que a Meta rejeita.
 *
 * Chaves com prefixo `__` sao de controle: o worker as separa das variaveis do
 * corpo antes de montar os parametros.
 */

/** Formato minimo de template aceito aqui. `MetaTemplate` satisfaz por estrutura. */
export interface TemplateVarSource {
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
}

/**
 * Sugere um token de lead a partir do exemplo que a Meta guarda para a variavel.
 * Telefone vira `{{telefone}}`, palavra unica vira `{{primeiro_nome}}`, ate tres
 * palavras vira `{{nome_completo}}`. Texto livre nao vira token — fica vazio
 * para o operador escrever.
 */
export function autoSuggestToken(example: string): string {
  if (!example) return "";
  if (/^[\d\s\-()+]+$/.test(example) && example.replace(/\D/g, "").length >= 8) {
    return "{{telefone}}";
  }
  if (!example.includes(" ")) return "{{primeiro_nome}}";
  if (example.trim().split(/\s+/).length <= 3) return "{{nome_completo}}";
  return "";
}

export function buildTemplateVarDefaults(
  tpl: TemplateVarSource
): Record<string, string> {
  const defaults: Record<string, string> = {};
  if (tpl.paramsType !== "none") defaults["__params_type__"] = tpl.paramsType;
  if (tpl.header) defaults["__header_type__"] = tpl.header.type;
  tpl.params.forEach((p) => {
    defaults[p.paramName] = autoSuggestToken(p.example);
  });
  return defaults;
}
