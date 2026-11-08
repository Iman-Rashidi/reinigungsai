-- Keep the private ingestion token table protected by RLS.
-- Only the postgres-owned SECURITY DEFINER ingestion function may access it.
ALTER TABLE private.api_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY api_tokens_postgres_definer_only
ON private.api_tokens
FOR ALL
TO postgres
USING (current_user = 'postgres')
WITH CHECK (current_user = 'postgres');
