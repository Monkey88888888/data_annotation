# Data Annotation Platform

Starter implementation for the first two stages of the Faceted Hyperdimensional
RAG pipeline: archetype definition, small OpenNeuro fMRI metadata scrape, and
context-aware ingestion heuristics.

## Product Direction

This platform is an annotation and qualification system for enterprise data. It
does not treat every file as a generic embedding. Each asset is assigned an
archetype, evaluated with a domain-specific rubric, converted into reproducible
hypervector inputs, and emitted as a faceted matrix record. Later retrieval and
generation systems can then filter by evidence-backed structure instead of raw
semantic similarity alone.

For fMRI, annotation means validating BIDS/NIfTI evidence and scoring source
authority before the asset is allowed into a trusted retrieval or generation
context.

## What This Does Now

- Runs an end-to-end local fMRI annotation POC with:
  - request intake and agent-style project proposals
  - editable/approvable task specs
  - seeded OpenNeuro annotation assignments
  - AI pre-labels with evidence-backed rationales
  - human annotation and reviewer adjudication
  - live quality metrics
  - faceted HDC retrieval with terminal routes for pure retrieval, clean-room text, and image-context manifests
  - JSONL/CSV export with provenance
- Defines a first `fmri_scan` archetype with the facets from the blueprint:
  `authority_base`, `type`, `modality`, `strictness`, and `tone`.
- Scrapes a small file manifest from OpenNeuro using its documented GraphQL API.
- Defaults to the public BART fMRI dataset, `ds000001`.
- Stores manifest records locally without downloading heavy NIfTI payloads.
- Runs Step 2 ingestion over the manifest:
  - creates deterministic raw hypervector seeds for each asset
  - selects the fMRI/OpenNeuro/BIDS metadata authority rubric
  - computes an authority score
  - generates the per-asset authority vector
  - emits the faceted matrix with the authority axis swapped in
- Runs Steps 3-6 locally:
  - binds raw asset vectors against the faceted matrix
  - projects each facet into a block-separated manifold index
  - searches with user-controlled facet weights
  - emits a pure retrieval package for verified fMRI assets

## Quick Start

Run the browser POC:

```bash
PYTHONPATH=src python3 -m data_annotation.demo_server --reset
```

Open `http://127.0.0.1:8787`.

The server writes mutable demo state and exports under `data/`, which is
gitignored. The demo starts with OpenNeuro `ds000001` assignments already
queued, so an operator can approve/edit the rubric, annotate scans, adjudicate
review items, run faceted retrieval, and export rows without external services.

The POC intentionally uses the standard library HTTP server and static assets so
it can run in a plain checkout. It preserves the recommended product shape from
the prototype document while keeping the scientific HDC pipeline as executable
backend logic.

```bash
python3 -m data_annotation.openneuro_scraper \
  --dataset-id ds000001 \
  --tag 1.0.0 \
  --limit 8 \
  --output manifests/openneuro_ds000001_fmri.jsonl
```

Set `PYTHONPATH=src` if you run from a plain checkout:

```bash
PYTHONPATH=src python3 -m data_annotation.openneuro_scraper --limit 8
```

Run Step 2 ingestion:

```bash
PYTHONPATH=src python3 -m data_annotation.ingestion \
  --manifest manifests/openneuro_ds000001_fmri.jsonl \
  --output manifests/openneuro_ds000001_ingested.jsonl
```

Run Step 2 with local payload evidence after downloading selected OpenNeuro
files:

```bash
PYTHONPATH=src python3 -m data_annotation.ingestion \
  --manifest manifests/openneuro_ds000001_fmri.jsonl \
  --output manifests/openneuro_ds000001_ingested.jsonl \
  --dataset-root data/openneuro/ds000001
```

Run Steps 3-6 end to end:

```bash
PYTHONPATH=src python3 -m data_annotation.pipeline run \
  --ingested manifests/openneuro_ds000001_ingested.jsonl \
  --index manifests/openneuro_ds000001_manifold.jsonl \
  --results manifests/openneuro_ds000001_search.jsonl \
  --retrieval-package manifests/openneuro_ds000001_retrieval_package.json \
  --dataset-root data/openneuro/ds000001 \
  --prompt "high authority fMRI balloon risk task" \
  --top-k 3 \
  --authority-weight 1 \
  --type-weight 1 \
  --modality-weight 1 \
  --strictness-weight 1 \
  --tone-weight 0.2
```

## Pipeline Artifacts

- `manifests/openneuro_ds000001_fmri.jsonl`: Step 1 scraped source manifest.
- `manifests/openneuro_ds000001_ingested.jsonl`: Step 2 authority-scored faceted records.
- `manifests/openneuro_ds000001_manifold.jsonl`: Steps 3-4 trusted vectors projected into block-separated manifold sectors.
- `manifests/openneuro_ds000001_search.jsonl`: Step 5 weighted search results.
- `manifests/openneuro_ds000001_retrieval_package.json`: Step 6 terminal retrieval package.

The local downloaded payloads live under `data/`, which is gitignored.

## Why Metadata First

OpenNeuro stores large imaging files through git-annex/DataLad. For the initial
version, the platform can classify assets into the correct archetype and prepare
an ingestion plan from metadata alone. When a local dataset root is provided,
Step 2 also inspects downloaded `.nii`/`.nii.gz` payload headers and matching
BIDS JSON sidecars. The authority rubric then includes payload presence, valid
NIfTI header, 4D imaging shape, sidecar presence, and `RepetitionTime`.

OpenNeuro download path for later:

```bash
openneuro download ds000001 data/openneuro/ds000001
cd data/openneuro/ds000001
git-annex get sub-01/func
```

## Local Checks

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall src tests
```
