-- Annotation cache for the LLM annotator stage.
-- Apply after schema.sql in the same Supabase project.

CREATE TABLE IF NOT EXISTS annotations (
    -- Cache key: SHA-256 of the asset payload + annotator version.
    -- Re-running the pipeline against the same payload + same annotator version
    -- is a cache hit — no second LLM call.
    asset_hash          VARCHAR(64) NOT NULL,
    annotator_version   VARCHAR(64) NOT NULL,

    -- Which document this annotation belongs to (nullable: an annotation can
    -- exist before its documents_raw row is created, e.g. dry-run mode).
    document_id         UUID REFERENCES documents_raw(id) ON DELETE SET NULL,

    -- Provenance
    archetype_id        VARCHAR(64) NOT NULL,
    annotator_kind      VARCHAR(32) NOT NULL,    -- 'text' | 'image'
    model               VARCHAR(64) NOT NULL,    -- e.g. 'claude-haiku-4-5-20251001'
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Annotation payload: facet values produced by the LLM.
    -- JSONB lets us index into individual facets and evolve the shape without
    -- a migration each time we add a facet column to documents_raw.
    facets              JSONB NOT NULL,

    -- Raw model response (tool_use input). Kept for replay + auditing.
    raw_response        JSONB,

    PRIMARY KEY (asset_hash, annotator_version)
);

-- Lookup by document_id when merging annotations into documents_raw.
CREATE INDEX IF NOT EXISTS idx_annotations_document
    ON annotations (document_id)
    WHERE document_id IS NOT NULL;
