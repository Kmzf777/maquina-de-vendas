import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      realtime: {
        // Heartbeat num Web Worker, fora do alcance do throttling de timers que
        // o Chrome aplica a abas em segundo plano. No default (`worker: false`)
        // tanto o heartbeat de 25s quanto o timer de reconexão são `setTimeout`
        // da thread principal: numa aba oculta eles atrasam, o servidor derruba
        // o socket por heartbeat perdido e a reconexão também chega tarde — ou
        // seja, o realtime morria exatamente quando o operador estava em outra
        // aba. O worker padrão é um blob inline, sem busca de URL externa.
        worker: true,
      },
    },
  );
}
