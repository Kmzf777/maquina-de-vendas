/**
 * Telefone utilizável para iniciar conversa no WhatsApp (cartão 70d844a6), ou null.
 * Lead importado do Bling sem celular vem como `bling-<id>`: isso não é telefone.
 * Critério único das telas (/conversas, /trafego) e da rota iniciar-conversa.
 */
export function telefoneWhatsapp(phone: string | null | undefined): string | null {
  if (!phone || /^bling-/i.test(phone.trim())) return null;
  const digitos = phone.replace(/\D/g, "");
  return digitos.length >= 10 && digitos.length <= 13 ? digitos : null;
}
