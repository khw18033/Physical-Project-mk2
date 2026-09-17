"""Reconstruct a known/unknown class split from the locally available TAO subset.

implements: AI-S-04 (research support script, not a shipped provider)

Context
-------
The project's earlier "0B/0C" OWL-ViT experiment (documented only as two numbers
in `perception_framework/perception/open_vocabulary.py` — known recall 0.757,
unknown recall 0.392) used a known/unknown class split whose exact definition
was lost when the original experiment scripts were removed from the repo.

This script reconstructs a *new*, principled, reproducible split instead of
guessing at the old one:

- TAO annotations carry LVIS's native `frequency` label per category
  ('f' frequent, 'c' common, 'r' rare) — this is the same frequent/rare split
  convention the OW-OVD paper's RWD/OWODB benchmarks use (top ~50% frequent =
  known, rest = unknown).
- We restrict to categories that actually have instances in the 4178 frames
  already downloaded under `datasets/tao/` (selected via
  `datasets/tao/manifests/val-yfcc100m-annotated.json`), so the split is usable
  without downloading more data.
- known = frequency in {f, c}; unknown (held out) = frequency == r.

This is a *different* split from the removed 0B/0C script, on a different (but
overlapping) frame subset. Any recall/precision numbers measured against it are
therefore a fresh, independently-reproducible measurement — not a like-for-like
comparison to the 0.757/0.392 figures (AI-B-01: 다른 구성에서 측정한 성능은
자동으로 같다고 가정하지 않는다).

Output: research/fomo/tao_known_unknown_split.json
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TAO_ANNOTATIONS = (
    REPO_ROOT
    / "datasets"
    / "tao"
    / "annotations"
    / "annotations-be63b9c27ebddbd774d4deef7e49f50a6c71e144"
    / "validation.json"
)
TAO_MANIFEST = REPO_ROOT / "datasets" / "tao" / "manifests" / "val-yfcc100m-annotated.json"
OUTPUT = Path(__file__).resolve().parent / "tao_known_unknown_split.json"

MIN_INSTANCES = 10  # drop categories too rare in this subset to evaluate meaningfully


def _file_key(image: dict) -> str:
    return "/".join(image["file_name"].split("/")[-2:])


def _natural_name(lvis_name: str) -> str:
    """`car_(automobile)` -> `car`; `drum_(musical_instrument)` -> `drum`."""
    name = re.sub(r"_\([^)]*\)", "", lvis_name)
    return name.replace("_", " ").strip()


def build_split() -> dict:
    annotations = json.loads(TAO_ANNOTATIONS.read_text())
    manifest = json.loads(TAO_MANIFEST.read_text())
    selected_files = set(manifest["files"])

    categories_by_id = {c["id"]: c for c in annotations["categories"]}
    selected_image_ids = {
        image["id"] for image in annotations["images"] if _file_key(image) in selected_files
    }

    instance_count: Counter[int] = Counter()
    for ann in annotations["annotations"]:
        if ann["image_id"] in selected_image_ids:
            instance_count[ann["category_id"]] += 1

    known, unknown = [], []
    for category_id, count in instance_count.items():
        if count < MIN_INSTANCES:
            continue
        category = categories_by_id[category_id]
        entry = {
            "lvis_name": category["name"],
            "natural_name": _natural_name(category["name"]),
            "frequency": category["frequency"],
            "instance_count": count,
        }
        (known if category["frequency"] in ("f", "c") else unknown).append(entry)

    known.sort(key=lambda e: -e["instance_count"])
    unknown.sort(key=lambda e: -e["instance_count"])

    return {
        "methodology": (
            "LVIS/TAO native frequency label ('f'/'c' -> known, 'r' -> unknown), "
            "restricted to categories with >= {} instances in the locally "
            "downloaded 4178-frame TAO validation subset. Reconstructed split, "
            "not the original (lost) 0B/0C split."
        ).format(MIN_INSTANCES),
        "source_frame_count": len(selected_image_ids),
        "known": known,
        "unknown": unknown,
    }


if __name__ == "__main__":
    split = build_split()
    OUTPUT.write_text(json.dumps(split, indent=2, ensure_ascii=False))
    print(f"known={len(split['known'])} unknown={len(split['unknown'])} -> {OUTPUT}")
