# Data Annotation Platform

Starter implementation for Step 1 of the Faceted Hyperdimensional RAG pipeline:
archetype definition plus a small OpenNeuro fMRI metadata scrape.

## What This Does Now

- Defines a first `fmri_scan` archetype with the facets from the blueprint:
  `authority_base`, `type`, `modality`, `strictness`, and `tone`.
- Scrapes a small file manifest from OpenNeuro using its documented GraphQL API.
- Defaults to the public BART fMRI dataset, `ds000001`.
- Stores manifest records locally without downloading heavy NIfTI payloads.

## Quick Start

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

## Why Metadata First

OpenNeuro stores large imaging files through git-annex/DataLad. For Step 1, the
platform only needs enough data to classify assets into the correct archetype and
prepare an ingestion plan. The actual payload download belongs in Step 2, where
we can add BIDS validation, DICOM/NIfTI header inspection, and authority scoring.

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
