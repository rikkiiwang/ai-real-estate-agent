-- Runs once when the data volume is first initialized.
-- POSTGRES_DB (set via fly secrets) creates the RAG database; this script adds
-- the Rails production database and enables pgvector where the brain needs it.

-- The brain's RAG store lives in the default POSTGRES_DB (realestate); enable
-- the vector extension there.
CREATE EXTENSION IF NOT EXISTS vector;

-- The Rails domain uses a separate database on the same instance.
CREATE DATABASE domain_production;
