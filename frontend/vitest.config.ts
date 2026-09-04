import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    // `node` continua sendo o default: os 49 testes .test.ts existentes são de lógica
    // pura e nunca tocam DOM. Testes de componente optam por jsdom com o docblock
    // `@vitest-environment jsdom` no topo do arquivo — assim nenhum teste antigo muda
    // de ambiente (e de custo) por causa de um teste de UI novo.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  // tsconfig.json usa `"jsx": "react-jsx"`, mas o esbuild do vitest não lê o tsconfig
  // do Next; sem isto, um .test.tsx falha com "Unexpected token <".
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
