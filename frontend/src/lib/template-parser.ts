export interface TemplateParam {
  index: number;
  paramName: string;
  example: string;
}

export interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface ParsedTemplateComponents {
  body: string;
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
}

interface MetaApiParam {
  param_name: string;
  example: string;
}

interface MetaApiComponent {
  type: string;
  text?: string;
  format?: string;
  example?: {
    body_text?: string[][];
    body_text_named_params?: MetaApiParam[];
    header_url?: string[];
  };
  buttons?: Array<{ type: string; text: string }>;
}

export function parseTemplateComponents(
  components: unknown[]
): ParsedTemplateComponents {
  const comps = components as MetaApiComponent[];

  return {
    body: parseBody(comps),
    header: parseHeader(comps),
    footer: parseFooter(comps),
    buttons: parseButtons(comps),
    ...parseParamsAndType(comps),
  };
}

function parseParamsAndType(components: MetaApiComponent[]): {
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
} {
  const body = components.find((c) => c.type === "BODY");
  if (!body) return { params: [], paramsType: "none" };

  if (body.example?.body_text_named_params?.length) {
    return {
      params: body.example.body_text_named_params.map((p, i) => ({
        index: i + 1,
        paramName: p.param_name,
        example: p.example,
      })),
      paramsType: "named",
    };
  }

  if (body.example?.body_text?.[0]?.length) {
    return {
      params: body.example.body_text[0].map((ex, i) => ({
        index: i + 1,
        paramName: String(i + 1),
        example: ex,
      })),
      paramsType: "positional",
    };
  }

  const matches = [...(body.text ?? "").matchAll(/\{\{([\w]+)\}\}/g)];
  if (matches.length) {
    const unique = [...new Map(matches.map((m) => [m[1], m])).values()];
    const allNumeric = unique.every((m) => /^\d+$/.test(m[1]));
    return {
      params: unique.map((m, i) => ({
        index: i + 1,
        paramName: m[1],
        example: "",
      })),
      paramsType: allNumeric ? "positional" : "named",
    };
  }

  return { params: [], paramsType: "none" };
}

function parseHeader(components: MetaApiComponent[]): TemplateHeader | null {
  const header = components.find((c) => c.type === "HEADER");
  if (!header) return null;
  const fmt = header.format?.toUpperCase();
  if (fmt === "TEXT") return { type: "TEXT", text: header.text ?? "" };
  if (fmt === "IMAGE") return { type: "IMAGE", example: header.example?.header_url?.[0] };
  if (fmt === "VIDEO") return { type: "VIDEO", example: header.example?.header_url?.[0] };
  if (fmt === "DOCUMENT") return { type: "DOCUMENT", example: header.example?.header_url?.[0] };
  return null;
}

function parseBody(components: MetaApiComponent[]): string {
  return components.find((c) => c.type === "BODY")?.text ?? "";
}

function parseFooter(components: MetaApiComponent[]): string | null {
  return components.find((c) => c.type === "FOOTER")?.text ?? null;
}

function parseButtons(components: MetaApiComponent[]): { type: string; text: string }[] {
  return components.find((c) => c.type === "BUTTONS")?.buttons ?? [];
}
