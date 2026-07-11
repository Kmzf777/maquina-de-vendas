// Renderiza o BODY real de um template Meta com as variáveis configuradas no nó.
// Função pura — usada pela prévia "Texto real do template" do Inspector.
// {{1}}/{{2}}… (posicional) e {{nome_do_param}} (nomeado) são substituídos pelos
// valores de template_variables; placeholder sem valor configurado permanece visível
// (o operador vê exatamente o que falta preencher).

export function renderTemplateBody(
  body: string,
  variables: Record<string, string> | undefined,
): string {
  if (!body) return "";
  const vars = variables ?? {};
  return body.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (placeholder, key: string) => {
    const value = vars[key];
    return value != null && String(value).trim() !== "" ? String(value) : placeholder;
  });
}
