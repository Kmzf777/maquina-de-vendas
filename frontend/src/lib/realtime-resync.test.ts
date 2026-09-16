import { describe, expect, it } from "vitest";
import { onResubscribe } from "./realtime-resync";

describe("onResubscribe", () => {
  it("não re-sincroniza na primeira inscrição", () => {
    let vezes = 0;
    const aoStatus = onResubscribe(() => vezes++);

    aoStatus("SUBSCRIBED");

    // A busca de montagem do próprio hook já trouxe dados frescos; refazer aqui
    // dobraria o tráfego de toda carga de página.
    expect(vezes).toBe(0);
  });

  it("re-sincroniza quando o canal volta depois de uma queda", () => {
    let vezes = 0;
    const aoStatus = onResubscribe(() => vezes++);

    aoStatus("SUBSCRIBED");
    aoStatus("CHANNEL_ERROR");
    aoStatus("SUBSCRIBED");

    expect(vezes).toBe(1);
  });

  it("re-sincroniza a cada nova volta", () => {
    let vezes = 0;
    const aoStatus = onResubscribe(() => vezes++);

    aoStatus("SUBSCRIBED");
    aoStatus("SUBSCRIBED");
    aoStatus("SUBSCRIBED");
    aoStatus("SUBSCRIBED");

    expect(vezes).toBe(3);
  });

  it("não re-sincroniza em status de canal degradado", () => {
    let vezes = 0;
    const aoStatus = onResubscribe(() => vezes++);

    aoStatus("CHANNEL_ERROR");
    aoStatus("TIMED_OUT");
    aoStatus("CLOSED");

    // Sem canal não há o que buscar; a re-sincronização espera a volta.
    expect(vezes).toBe(0);
  });

  it("conta cada canal separadamente", () => {
    let a = 0;
    let b = 0;
    const canalA = onResubscribe(() => a++);
    const canalB = onResubscribe(() => b++);

    canalA("SUBSCRIBED");
    canalA("SUBSCRIBED");
    canalB("SUBSCRIBED");

    expect(a).toBe(1);
    expect(b).toBe(0);
  });
});
