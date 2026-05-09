-- Faceted Hyperdimensional RAG -- Tier 1 relational store.
-- Apply this in the Supabase SQL Editor on a fresh project.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS documents_raw (
    -- 0. Metadata & payload
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    source_name     VARCHAR(255),
    content_payload TEXT,                 -- raw text OR an s3:// / https:// URI for binary assets

    -- Routing for the annotator runner. 'text_document' | 'image_asset' |
    -- 'fmri_scan' (the last is handled by ingestion.py, not the annotator).
    archetype_id    VARCHAR(64),

    -- Pipeline status
    is_processed    BOOLEAN DEFAULT FALSE,

    -- BLOCK 1: AUTHORITY (continuous 0.0..1.0)
    auth_domain         FLOAT DEFAULT 0.0,
    auth_author         FLOAT DEFAULT 0.0,
    auth_institution    FLOAT DEFAULT 0.0,

    -- BLOCK 2: TYPE (boolean)
    type_text           BOOLEAN DEFAULT FALSE,
    type_image          BOOLEAN DEFAULT FALSE,
    type_timeseries     BOOLEAN DEFAULT FALSE,

    -- BLOCK 3: MODALITY (boolean)
    modality_b2b_email      BOOLEAN DEFAULT FALSE,
    modality_landing_page   BOOLEAN DEFAULT FALSE,
    modality_fmri_t1        BOOLEAN DEFAULT FALSE,
    modality_fmri_bold      BOOLEAN DEFAULT FALSE,

    -- BLOCK 4: STRICTNESS (continuous 0.0..1.0)
    strict_regulatory   FLOAT DEFAULT 0.0,
    strict_technicality FLOAT DEFAULT 0.0,

    -- BLOCK 5: TONE (continuous 0.0..1.0)
    tone_formality      FLOAT DEFAULT 0.0,
    tone_aggressiveness FLOAT DEFAULT 0.0,
    tone_creativity     FLOAT DEFAULT 0.0
);

-- Idempotent: lets old projects pick up the column without dropping the table.
ALTER TABLE documents_raw ADD COLUMN IF NOT EXISTS archetype_id VARCHAR(64);

-- Partial index: ingestion worker fetches un-processed rows in O(log n).
CREATE INDEX IF NOT EXISTS idx_unprocessed_documents
    ON documents_raw (is_processed)
    WHERE is_processed = FALSE;
