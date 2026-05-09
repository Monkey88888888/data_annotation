# Tier 1 + Tier 2 Setup Runbook

This walks through provisioning the relational store (Supabase) and the
vector store (Pinecone) for the Faceted HDC RAG pipeline. Follow it once
per environment (dev / staging / prod). Total time: ~15 minutes.

## 0. Prerequisites

- Python 3.11+
- A Git Bash window open in `C:\Users\Owner\Documents\data_annotation`
- `pip install -r requirements.txt`
- `cp .env.example .env`

---

## 1. Supabase (Tier 1 — relational store)

### 1.1 Create the project

1. Go to <https://supabase.com> → **New project**.
2. Name it `hdc-rag-mvp` (any name). Pick the closest region. Save the
   database password to your password manager — Supabase will not show
   it again.
3. Wait ~2 min for provisioning.

### 1.2 Apply the schema

1. In the Supabase dashboard sidebar, open **SQL Editor → New query**.
2. Paste the entire contents of `db/schema.sql`.
3. Click **Run**. You should see `Success. No rows returned.` and a new
   `documents_raw` table under **Table Editor**.

### 1.3 Grab credentials

In the dashboard: **Project Settings → API**.

| Field in `.env`           | Where to copy from              |
|---------------------------|---------------------------------|
| `SUPABASE_URL`            | "Project URL"                   |
| `SUPABASE_ANON_KEY`       | "anon public" key               |
| `SUPABASE_SERVICE_KEY`    | "service_role" key (keep secret)|

The service-role key bypasses RLS — only use it server-side, never in a
browser bundle.

### 1.4 Verify the round-trip

```bash
PYTHONPATH=src python -m unittest tests.test_supabase_client
```

Expected: one test passes (`test_insert_fetch_mark_processed`). The test
inserts a row, asserts it shows up in the unprocessed feed, marks it
processed, then deletes it.

If credentials are missing the test will skip rather than fail, so the
default `python -m unittest discover -s tests` stays green for anyone
who clones the repo without a Supabase project.

---

## 2. Pinecone (Tier 2 — vector store, 256D)

### 2.1 Create the index

1. Sign in at <https://app.pinecone.io>.
2. **Create index**:
   - **Name:** `annotation`
   - **Dimensions:** `256` (matches `pipeline.py`'s `manifold_dimension` default)
   - **Metric:** `cosine`
   - **Capacity mode:** Serverless (cheapest for MVP)
   - **Cloud / region:** AWS · us-east-1 (matches the free tier)
3. Wait until status is `Ready`.

### 2.2 Grab credentials

In the dashboard: **API Keys → Default**. Copy the key into
`PINECONE_API_KEY` in `.env`. The index name, cloud, and region are
already set in `.env.example`; adjust if you chose differently.

### 2.3 Smoke test (deferred)

The Pinecone client is wired up in the next step (Python ingestion
script). You can confirm the index is reachable now with:

```python
from pinecone import Pinecone
pc = Pinecone(api_key="...")
print(pc.describe_index("hdc-rag-1536"))
```

---

## 3. Hand-off to the data-annotation operator

Your data person can now log into Supabase, click **Table Editor →
documents_raw**, and start filling rows by hand:

- Sales copy: paste the text into `content_payload`, flip `type_text`
  and the appropriate `modality_*` boolean, set the tone/strictness
  floats. Leave fMRI fields at default.
- fMRI scan: paste the S3/HTTPS URI into `content_payload`, flip
  `type_timeseries` + `modality_fmri_bold` (or `_t1`), set
  `auth_institution`. Leave tone fields at default.
- Always leave `is_processed` = FALSE — the ingestion worker flips it.

---

## 4. Next step

The Python ingestion script (Postgres → Jordan blocks → LLM lift →
Pinecone) plugs into `SupabaseClient.fetch_unprocessed()` and
`mark_processed()`. That is the next module to build.
