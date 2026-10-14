"use client";

/**
 * Endereço estruturado na ficha do lead (cartão b3788533). É o que vai para o
 * contato no Bling quando a ficha é salva com o endereço completo.
 *
 * O CEP com 8 dígitos consulta o ViaCEP (`buscarCep`, mesmo helper do cadastro
 * de contato no Bling) e preenche só os campos vazios — o que o vendedor
 * digitou continua dele. Falha na consulta não bloqueia nada.
 */
import { useEffect, useRef, useState } from "react";
import { cepDigits } from "@/lib/bling-contact-form";
import { buscarCep } from "@/lib/cep";
import { ADDRESS_FIELDS, mergeViaCep, type AddressField, type LeadAddress } from "@/lib/lead-address";

interface LeadAddressFieldsProps {
  value: LeadAddress;
  /** Texto livre antigo (`leads.endereco`), mostrado enquanto não há campos. */
  legado?: string | null;
  onChange: (patch: LeadAddress) => void;
}

const LABEL = "block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1";
const INPUT =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full";

export function LeadAddressFields({ value, legado, onChange }: LeadAddressFieldsProps) {
  const [buscando, setBuscando] = useState(false);
  // CEP da última consulta: resposta atrasada de um CEP já trocado é ignorada.
  const cepConsultado = useRef<string | null>(null);
  // `value` mais recente, para a resposta do ViaCEP não pisar no que foi
  // digitado enquanto a consulta viajava.
  const atual = useRef(value);
  useEffect(() => {
    atual.current = value;
  });

  async function consultarCep(cep: string) {
    cepConsultado.current = cep;
    setBuscando(true);
    const achado = await buscarCep(cep);
    if (cepConsultado.current !== cep) return;
    setBuscando(false);
    if (!achado || cepDigits(atual.current.cep) !== cep) return;
    const novo = mergeViaCep(atual.current, achado);
    const patch: LeadAddress = {};
    for (const k of ADDRESS_FIELDS) if (novo[k] !== atual.current[k]) patch[k] = novo[k];
    if (Object.keys(patch).length) onChange(patch);
  }

  function campo(chave: AddressField, texto: string) {
    onChange({ [chave]: texto });
    if (chave === "cep") {
      const cep = cepDigits(texto);
      if (cep.length === 8 && cep !== cepConsultado.current) void consultarCep(cep);
      else if (cep.length !== 8) {
        cepConsultado.current = null;
        setBuscando(false);
      }
    }
  }

  const input = (chave: AddressField, rotulo: string, extra: Partial<React.InputHTMLAttributes<HTMLInputElement>> = {}) => (
    <div>
      <label htmlFor={`lead-endereco-${chave}`} className={LABEL}>{rotulo}</label>
      <input
        id={`lead-endereco-${chave}`}
        value={value[chave] ?? ""}
        onChange={(e) => campo(chave, e.target.value)}
        className={INPUT}
        {...extra}
      />
    </div>
  );

  const semCampos = ADDRESS_FIELDS.every((k) => !(value[k] ?? "").trim());

  return (
    <div data-testid="lead-address-block">
      <div className="flex items-center gap-2 mb-3">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Endereço</p>
        {buscando && <span className="text-[11px] text-[#7b7b78]">Buscando…</span>}
      </div>
      <div className="grid grid-cols-[140px_minmax(0,1fr)_100px] gap-3">
        {input("cep", "CEP", { inputMode: "numeric", placeholder: "00000-000" })}
        {input("logradouro", "Rua")}
        {input("numero", "Número")}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_64px] gap-3 mt-3">
        {input("complemento", "Complemento")}
        {input("bairro", "Bairro")}
        {input("municipio", "Cidade")}
        {input("uf", "UF", { maxLength: 2, className: `${INPUT} uppercase` })}
      </div>
      {semCampos && legado?.trim() && (
        <p className="mt-2 text-[12px] text-[#7b7b78]">Endereço antigo: {legado}</p>
      )}
    </div>
  );
}
