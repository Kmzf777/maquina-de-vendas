"use client";

import { useState, useRef } from "react";
import Papa from "papaparse";

const LEAD_FIELDS = [
  { key: "", label: "Pular coluna" },
  { key: "phone", label: "Telefone" },
  { key: "name", label: "Nome" },
  { key: "email", label: "Email" },
  { key: "instagram", label: "Instagram" },
  { key: "company", label: "Empresa" },
  { key: "cnpj", label: "CNPJ" },
  { key: "razao_social", label: "Razao Social" },
  { key: "nome_fantasia", label: "Nome Fantasia" },
  { key: "endereco", label: "Endereco" },
  { key: "telefone_comercial", label: "Telefone Comercial" },
  { key: "stage", label: "Stage" },
];

const AUTO_MAP: Record<string, string> = {
  telefone: "phone", phone: "phone", celular: "phone", whatsapp: "phone",
  nome: "name", name: "name",
  email: "email", "e-mail": "email",
  instagram: "instagram",
  empresa: "company", company: "company",
  cnpj: "cnpj",
  "razao social": "razao_social", razao_social: "razao_social",
  "nome fantasia": "nome_fantasia", nome_fantasia: "nome_fantasia",
  endereco: "endereco", address: "endereco",
  "telefone comercial": "telefone_comercial",
  stage: "stage", etapa: "stage",
};

interface LeadImportModalProps {
  onClose: () => void;
  onImportDone: () => void;
}

type Step = "upload" | "mapping" | "confirm";

export function LeadImportModal({ onClose, onImportDone }: LeadImportModalProps) {
  const [step, setStep] = useState<Step>("upload");
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{ inserted: number; updated: number; skipped: number } | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    Papa.parse(file, {
      skipEmptyLines: true,
      complete: (results) => {
        const data = results.data as string[][];
        if (data.length < 2) return;
        const headers = data[0];
        setCsvHeaders(headers);
        setCsvRows(data.slice(1));

        const autoMapping: Record<number, string> = {};
        headers.forEach((h, i) => {
          const normalized = h.toLowerCase().trim();
          if (AUTO_MAP[normalized]) {
            autoMapping[i] = AUTO_MAP[normalized];
          }
        });
        setMapping(autoMapping);
        setStep("mapping");
      },
    });
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".csv")) handleFile(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  async function handleImport() {
    setImporting(true);

    const leads = csvRows.map((row) => {
      const lead: Record<string, string> = {};
      Object.entries(mapping).forEach(([colIdx, field]) => {
        if (field) {
          lead[field] = row[Number(colIdx)] || "";
        }
      });
      return lead;
    }).filter((l) => l.phone);

    const res = await fetch("/api/leads/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leads, skipDuplicates }),
    });
    const data = await res.json();
    setResult(data);
    setImporting(false);
    onImportDone();
  }

  const phoneColumnMapped = Object.values(mapping).includes("phone");

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[640px] max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#dedbd6] flex justify-between items-center">
          <h3
            className="text-[24px] font-normal text-[#111111]"
            style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
          >
            Importar Leads (CSV)
          </h3>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-[4px] border border-[#dedbd6] flex items-center justify-center text-[#7b7b78] hover:text-[#111111] hover:border-[#111111] transition-colors"
          >
            ×
          </button>
        </div>

        {/* Steps indicator */}
        <div className="px-6 py-3 flex items-center gap-2 text-[12px] border-b border-[#dedbd6]">
          {(["Upload", "Mapeamento", "Confirmacao"] as const).map((label, i) => {
            const stepKeys: Step[] = ["upload", "mapping", "confirm"];
            const isActive = stepKeys.indexOf(step) >= i;
            return (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && <span className="text-[#dedbd6]">&rarr;</span>}
                <span className={`px-2.5 py-0.5 rounded-[4px] text-[12px] ${isActive ? "bg-[#111111] text-white" : "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78]"}`}>
                  {i + 1}. {label}
                </span>
              </div>
            );
          })}
        </div>

        <div className="p-6 max-h-[450px] overflow-y-auto">

          {/* Step 1: Upload */}
          {step === "upload" && (
            <div
              className={`border-2 border-dashed rounded-[8px] p-10 text-center transition-colors ${
                dragActive ? "border-[#111111] bg-[#faf9f6]" : "border-[#dedbd6]"
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
            >
              <p className="text-[14px] text-[#7b7b78] mb-2">Arraste um arquivo CSV aqui</p>
              <p className="text-[12px] text-[#7b7b78] mb-4">ou</p>
              <button
                onClick={() => fileRef.current?.click()}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
              >
                Selecionar arquivo
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                onChange={handleFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Step 2: Mapping */}
          {step === "mapping" && (
            <div>
              <p className="text-[13px] text-[#7b7b78] mb-4">
                {csvRows.length} linhas encontradas. Mapeie as colunas do CSV para os campos do lead:
              </p>
              <div className="space-y-2 mb-4">
                {csvHeaders.map((header, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-[13px] text-[#111111] w-40 truncate font-medium">{header}</span>
                    <span className="text-[#7b7b78]">&rarr;</span>
                    <select
                      value={mapping[i] || ""}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [i]: e.target.value }))}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none flex-1"
                    >
                      {LEAD_FIELDS.map((f) => (
                        <option key={f.key} value={f.key}>{f.label}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Preview (5 primeiras linhas)</p>
              <div className="overflow-x-auto border border-[#dedbd6] rounded-[8px]">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[#faf9f6]">
                      {csvHeaders.map((h, i) => (
                        <th key={i} className="px-2 py-1.5 text-left text-[#7b7b78] font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvRows.slice(0, 5).map((row, i) => (
                      <tr key={i} className="border-t border-[#dedbd6]">
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1 text-[#7b7b78] truncate max-w-[120px]">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-end mt-4">
                <button
                  onClick={() => setStep("confirm")}
                  disabled={!phoneColumnMapped}
                  className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
                >
                  Proximo
                </button>
              </div>
              {!phoneColumnMapped && (
                <p className="text-[12px] text-[#c41c1c] mt-2 text-right">Mapeie pelo menos a coluna de telefone.</p>
              )}
            </div>
          )}

          {/* Step 3: Confirm */}
          {step === "confirm" && !result && (
            <div>
              <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5 mb-4">
                <p className="text-[14px] font-medium text-[#111111] mb-2">Resumo da importacao</p>
                <p className="text-[13px] text-[#7b7b78]">{csvRows.length} leads serao processados</p>
                <p className="text-[13px] text-[#7b7b78]">
                  Campos mapeados: {Object.values(mapping).filter(Boolean).join(", ")}
                </p>
              </div>

              <label className="flex items-center gap-2 mb-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipDuplicates}
                  onChange={(e) => setSkipDuplicates(e.target.checked)}
                  className="rounded accent-[#111111]"
                />
                <span className="text-[13px] text-[#7b7b78]">
                  Pular leads duplicados (mesmo telefone). Desmarque para atualizar dados existentes.
                </span>
              </label>

              <div className="flex justify-between">
                <button
                  onClick={() => setStep("mapping")}
                  className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                >
                  Voltar
                </button>
                <button
                  onClick={handleImport}
                  disabled={importing}
                  className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
                >
                  {importing ? "Importando..." : "Importar"}
                </button>
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="text-center py-6">
              <p
                className="text-[24px] font-normal text-[#111111] mb-3"
                style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
              >
                Importacao concluida!
              </p>
              <div className="flex justify-center gap-6 mb-5">
                <div>
                  <p className="text-[24px] font-semibold text-[#0bdf50]">{result.inserted}</p>
                  <p className="text-[12px] text-[#7b7b78]">Inseridos</p>
                </div>
                <div>
                  <p className="text-[24px] font-semibold text-[#111111]">{result.updated}</p>
                  <p className="text-[12px] text-[#7b7b78]">Atualizados</p>
                </div>
                <div>
                  <p className="text-[24px] font-semibold text-[#7b7b78]">{result.skipped}</p>
                  <p className="text-[12px] text-[#7b7b78]">Pulados</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
              >
                Fechar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
