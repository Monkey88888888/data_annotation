from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data_annotation.archetypes import Archetype, default_archetype_path


OPENNEURO_GRAPHQL_URL = "https://openneuro.org/crn/graphql"


SNAPSHOT_FILES_QUERY = """
query SnapshotFiles($datasetId: ID!, $tag: String!) {
  snapshot(datasetId: $datasetId, tag: $tag) {
    id
    tag
    description {
      Name
      DatasetDOI
      License
      Authors
      BIDSVersion
    }
    files(recursive: true) {
      id
      filename
      size
      directory
      annexed
    }
  }
}
"""


@dataclass(frozen=True)
class OpenNeuroAsset:
    dataset_id: str
    snapshot_tag: str
    dataset_name: str | None
    dataset_doi: str | None
    license: str | None
    archetype_id: str
    path: str
    file_id: str
    size: int
    annexed: bool
    modality: str
    source: str = "OpenNeuro"


def post_graphql(url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "data-annotation-step1/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenNeuro API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach OpenNeuro API: {exc.reason}") from exc


def scrape_fmri_assets(
    dataset_id: str,
    tag: str,
    limit: int,
    graphql_url: str = OPENNEURO_GRAPHQL_URL,
) -> list[OpenNeuroAsset]:
    if limit <= 0:
        return []

    response = post_graphql(
        graphql_url,
        SNAPSHOT_FILES_QUERY,
        {"datasetId": dataset_id, "tag": tag},
    )
    if response.get("errors"):
        raise RuntimeError(json.dumps(response["errors"], indent=2))

    snapshot = response["data"]["snapshot"]
    description = snapshot.get("description") or {}
    files = snapshot.get("files") or []

    assets: list[OpenNeuroAsset] = []
    for item in files:
        path = item["filename"]
        if item["directory"]:
            continue
        if not is_functional_nifti(path):
            continue
        assets.append(
            OpenNeuroAsset(
                dataset_id=dataset_id,
                snapshot_tag=snapshot["tag"],
                dataset_name=description.get("Name"),
                dataset_doi=description.get("DatasetDOI"),
                license=description.get("License"),
                archetype_id="fmri_scan",
                path=path,
                file_id=item["id"],
                size=int(item["size"] or 0),
                annexed=bool(item["annexed"]),
                modality="fMRI_NIfTI_BIDS",
            )
        )
        if len(assets) >= limit:
            break
    return assets


def is_functional_nifti(path: str) -> bool:
    return "/func/" in path and (path.endswith(".nii") or path.endswith(".nii.gz"))


def write_jsonl(path: Path, records: list[OpenNeuroAsset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape a small fMRI asset manifest from OpenNeuro.")
    parser.add_argument("--dataset-id", default="ds000001")
    parser.add_argument("--tag", default="1.0.0")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("manifests/openneuro_ds000001_fmri.jsonl"))
    parser.add_argument("--archetype", type=Path, default=default_archetype_path("fmri_scan"))
    parser.add_argument("--matrix-preview", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    archetype = Archetype.from_file(args.archetype)

    if args.matrix_preview:
        print(json.dumps(archetype.master_matrix_preview(), indent=2, sort_keys=True))

    records = scrape_fmri_assets(args.dataset_id, args.tag, args.limit)
    write_jsonl(args.output, records)
    print(f"wrote {len(records)} {archetype.id} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
