// Dono único da moeda no dashboard.
//
// O painel mistura valores nativos em USD (custo de token do Gemini) e em BRL
// (valor de venda do CAPI) e precisa exibir os dois. Regra de exibição: o REAL é
// sempre a moeda em destaque, porque é nele que o operador pensa; a moeda nativa
// aparece na linha secundária junto com a taxa usada, para o número nunca ser
// uma caixa-preta.
//
// A conversão parte SEMPRE do valor nativo — nunca de um valor já convertido.

export interface FxRate {
  rate: number;
  date: string;
  /** Cotação viva indisponível: o valor é aproximado e a UI precisa dizer isso. */
  stale: boolean;
  source: string;
}

export interface DualValue {
  /** Moeda em destaque (BRL), ou a nativa quando ainda não há câmbio. */
  primary: string;
  /** Moeda nativa + taxa. Ausente quando não há câmbio ou não há valor. */
  secondary?: string;
}

const DASH = "—";

function isMoney(v: number | null | undefined): v is number {
  return v !== null && v !== undefined && Number.isFinite(v);
}

/**
 * Casas decimais: custo de IA por atendimento vive abaixo de um centavo, e
 * arredondar para 2 casas apagaria o número inteiro (o card viraria "$0.00").
 */
function digits(v: number): number {
  return Math.abs(v) > 0 && Math.abs(v) < 0.01 ? 4 : 2;
}

function fmt(v: number | null | undefined, locale: string, currency: string): string {
  if (!isMoney(v)) return DASH;
  const d = digits(v);
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  }).format(v);
}

/** "$1,234.56" / "$0.0042" — símbolo e pontuação en-US. */
export function fmtUSD(v: number | null | undefined): string {
  return fmt(v, "en-US", "USD");
}

/** "R$ 1.234,56" — símbolo e pontuação pt-BR. */
export function fmtBRL(v: number | null | undefined): string {
  return fmt(v, "pt-BR", "BRL");
}

function validRate(rate: number): boolean {
  return Number.isFinite(rate) && rate > 0;
}

export function usdToBrl(usd: number, rate: number): number | null {
  return validRate(rate) ? usd * rate : null;
}

export function brlToUsd(brl: number, rate: number): number | null {
  return validRate(rate) ? brl / rate : null;
}

/** "câmbio 5,50" — ou "câmbio 5,50 (aprox.)" quando a cotação viva caiu. */
function rateLabel(fx: FxRate): string {
  const r = fx.rate.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `câmbio ${r}${fx.stale ? " (aprox.)" : ""}`;
}

function dual(brl: number | null, usd: number | null, fx: FxRate | null): DualValue {
  // Sem câmbio (ainda carregando, ou bloco em erro): mostra só a moeda nativa.
  // O card nunca fica em branco esperando o câmbio.
  if (!fx || brl === null || usd === null) {
    const native = brl !== null ? fmtBRL(brl) : fmtUSD(usd);
    return { primary: native };
  }
  return { primary: fmtBRL(brl), secondary: `${fmtUSD(usd)} · ${rateLabel(fx)}` };
}

/** Valor nativo em USD (custo de IA) → real em destaque, dólar embaixo. */
export function dualFromUsd(usd: number | null | undefined, fx: FxRate | null): DualValue {
  if (!isMoney(usd)) return { primary: DASH };
  if (!fx) return { primary: fmtUSD(usd) };
  return dual(usdToBrl(usd, fx.rate), usd, fx);
}

/** Valor nativo em BRL (venda) → real em destaque, dólar convertido embaixo. */
export function dualFromBrl(brl: number | null | undefined, fx: FxRate | null): DualValue {
  if (!isMoney(brl)) return { primary: DASH };
  if (!fx) return { primary: fmtBRL(brl) };
  return dual(brl, brlToUsd(brl, fx.rate), fx);
}
