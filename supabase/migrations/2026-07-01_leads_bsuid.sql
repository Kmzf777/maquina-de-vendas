-- BSUID (Business-Scoped User ID) resilience: store the Meta BSUID so leads whose
-- phone is omitted (username adopters) can still be identified and messaged.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bsuid text;
CREATE UNIQUE INDEX IF NOT EXISTS leads_bsuid_key ON leads (bsuid) WHERE bsuid IS NOT NULL;
