import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

// vitest roda com cwd = frontend/ (root do projeto); a suíte inteira depende disso.
const SRC = path.resolve(process.cwd(), "src");

// Itens deliberadamente públicos (sem sessão). Adicionar aqui exige revisão consciente.
const PUBLIC_API_PREFIXES: string[] = [];
const PUBLIC_PAGES: string[] = [];

function matcherEntries(): string[] {
  const source = fs.readFileSync(path.join(SRC, "proxy.ts"), "utf8");
  const block = source.match(/matcher:\s*\[([\s\S]*?)\]/);
  if (!block) throw new Error("config.matcher não encontrado em src/proxy.ts");
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function topLevelDirs(relative: string): string[] {
  return fs
    .readdirSync(path.join(SRC, relative), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
}

function covered(prefix: string, entries: string[]): boolean {
  return entries.some((e) => e === prefix || e.startsWith(`${prefix}/`));
}

describe("cobertura do config.matcher do proxy (gating de auth)", () => {
  const entries = matcherEntries();

  it("toda rota /api/* de 1º nível está no matcher ou é pública explícita", () => {
    const missing = topLevelDirs("app/api")
      .map((dir) => `/api/${dir}`)
      .filter((p) => !covered(p, entries) && !PUBLIC_API_PREFIXES.includes(p));
    expect(missing, `Rotas de API fora do matcher do proxy.ts: ${missing.join(", ")}`).toEqual([]);
  });

  it("toda página autenticada está no matcher ou é pública explícita", () => {
    const missing = topLevelDirs("app/(authenticated)")
      .map((dir) => `/${dir}`)
      .filter((p) => !covered(p, entries) && !PUBLIC_PAGES.includes(p));
    expect(missing, `Páginas fora do matcher do proxy.ts: ${missing.join(", ")}`).toEqual([]);
  });
});
