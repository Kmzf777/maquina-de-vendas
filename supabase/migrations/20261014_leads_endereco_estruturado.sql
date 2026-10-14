-- Endereço estruturado do lead (cartão b3788533). Aditiva: nada é apagado.
-- `leads.endereco` (texto livre, legado) continua e passa a ser regravado
-- formatado pelo PATCH /api/leads/[id] quando estes campos mudam.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS cep text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS logradouro text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS numero text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS complemento text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bairro text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS municipio text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS uf text;
NOTIFY pgrst, 'reload schema';
