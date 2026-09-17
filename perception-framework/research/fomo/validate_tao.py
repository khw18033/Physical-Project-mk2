"""Direction-only validation of FOMO/OW-OVD/OWOBJ policies against TAO.

implements: AI-S-03, AI-S-04, AI-B-01 (research support script, not a shipped provider)

What this measures (and does not)
----------------------------------
Per the project decision to validate *mechanism direction*, not reproduce
paper-reported M-OWODB/S-OWODB numbers: for every ground-truth box in the
locally downloaded TAO subset, this finds the OWL-ViT detection box with the
best IoU overlap and records that detection's `p_unknown` under each policy,
split by whether the ground-truth category is `known` or `unknown` (per
`tao_known_unknown_split.json`).

A policy is doing what its paper claims if `mean(p_unknown | unknown GT)` is
clearly higher than `mean(p_unknown | known GT)` — that gap ("separation"
below) is the direction check. This is NOT U-Recall/U-mAP and is not
comparable to the papers' benchmark tables (different backbone, different
dataset, different — reconstructed — known/unknown split; see
`build_split.py`).

Run order: `build_split.py` -> `generate_attributes.py` -> this script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "models" / "openvocab" / "owlvit-base-patch32"
MODEL_PATH = MODEL_DIR / "onnx" / "model_quantized.onnx"
TOKENIZER_PATH = MODEL_DIR / "tokenizer.json"
FRAMES_DIR = REPO_ROOT / "datasets" / "tao" / "frames"
ANNOTATIONS = (
    REPO_ROOT
    / "datasets"
    / "tao"
    / "annotations"
    / "annotations-be63b9c27ebddbd774d4deef7e49f50a6c71e144"
    / "validation.json"
)

RESEARCH_DIR = Path(__file__).resolve().parent
SPLIT_PATH = RESEARCH_DIR / "tao_known_unknown_split.json"
ATTRIBUTES_PATH = RESEARCH_DIR / "attributes.json"

MAX_FRAMES = 300  # lightweight sweep, not a full-dataset benchmark run
IOU_MATCH_THRESHOLD = 0.3


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _load_ground_truth(known_names: set[str], unknown_names: set[str]):
    ann = json.loads(ANNOTATIONS.read_text())
    categories = {c["id"]: c["name"] for c in ann["categories"]}
    images = {im["id"]: im for im in ann["images"]}

    # category names in TAO annotations are the raw LVIS `name` field
    # (e.g. "drumstick"); the split stores the same value as `lvis_name`.
    lvis_to_group = {}
    for e in known_names:
        lvis_to_group[e] = "known"
    for e in unknown_names:
        lvis_to_group[e] = "unknown"

    by_image: dict[int, list[tuple[tuple[float, float, float, float], str]]] = {}
    for a in ann["annotations"]:
        group = lvis_to_group.get(categories.get(a["category_id"]))
        if group is None:
            continue
        x, y, w, h = a["bbox"]
        by_image.setdefault(a["image_id"], []).append(((x, y, x + w, y + h), group))
    return images, by_image


def main(policy_ids: tuple[str, ...] = ("fomo_attribute", "ow_ovd_hauf", "owobj_energy")) -> None:
    if not ATTRIBUTES_PATH.exists():
        print(f"missing {ATTRIBUTES_PATH} — run generate_attributes.py first", file=sys.stderr)
        raise SystemExit(1)
    if not (MODEL_PATH.exists() and TOKENIZER_PATH.exists()):
        print(f"missing OWL-ViT model under {MODEL_DIR}", file=sys.stderr)
        raise SystemExit(1)

    import cv2

    from perception_framework.perception.open_vocabulary import OwlVitPerceptionProvider
    from perception_framework.perception.unknownness import (
        FomoAttributePolicy,
        OwobjEnergyPolicy,
        OwOvdHaufPolicy,
    )

    split = json.loads(SPLIT_PATH.read_text())
    known_lvis_names = {e["lvis_name"] for e in split["known"]}
    unknown_lvis_names = {e["lvis_name"] for e in split["unknown"]}
    known_vocab = [f"a {e['natural_name']}" for e in split["known"]]

    attributes = json.loads(ATTRIBUTES_PATH.read_text())
    template = attributes["sentence_template"]
    all_attributes = sorted({a for attrs in attributes["attributes_per_class"].values() for a in attrs})
    attribute_vocab = [template.format(attribute=a) for a in all_attributes]

    known_provider = OwlVitPerceptionProvider(MODEL_PATH, TOKENIZER_PATH, vocab=known_vocab, score_thr=0.0)
    attribute_provider = OwlVitPerceptionProvider(
        MODEL_PATH, TOKENIZER_PATH, vocab=attribute_vocab, score_thr=0.0
    )

    images, gt_by_image = _load_ground_truth(known_lvis_names, unknown_lvis_names)
    image_ids = [iid for iid, gts in gt_by_image.items() if gts][:MAX_FRAMES]

    policies = {
        "fomo_attribute": FomoAttributePolicy(),
        "ow_ovd_hauf": OwOvdHaufPolicy(),
        "owobj_energy": OwobjEnergyPolicy(known_energy_reference=-2.0, margin=1.0),
    }

    p_unknown = {pid: {"known": [], "unknown": []} for pid in policy_ids}
    frames_used = 0

    for image_id in image_ids:
        frame_path = FRAMES_DIR / images[image_id]["file_name"]
        if not frame_path.exists():
            continue
        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue
        frames_used += 1

        known_raw = known_provider.detect_raw(frame)
        attribute_raw = attribute_provider.detect_raw(frame)

        for pid in policy_ids:
            scores = policies[pid].score(known_raw, attribute_raw)
            for gt_box, group in gt_by_image[image_id]:
                best = max(scores, key=lambda s: _iou(s.box, gt_box))
                if _iou(best.box, gt_box) >= IOU_MATCH_THRESHOLD:
                    p_unknown[pid][group].append(best.p_unknown)

    print(f"frames_used={frames_used} (cap={MAX_FRAMES})")
    print(f"{'policy':<16} {'n_known':>8} {'mean(known)':>12} {'n_unknown':>10} {'mean(unknown)':>14} {'separation':>11}")
    for pid in policy_ids:
        known_scores, unknown_scores = p_unknown[pid]["known"], p_unknown[pid]["unknown"]
        mean_known = sum(known_scores) / len(known_scores) if known_scores else float("nan")
        mean_unknown = sum(unknown_scores) / len(unknown_scores) if unknown_scores else float("nan")
        separation = mean_unknown - mean_known
        print(
            f"{pid:<16} {len(known_scores):>8} {mean_known:>12.3f} "
            f"{len(unknown_scores):>10} {mean_unknown:>14.3f} {separation:>11.3f}"
        )
    print(
        "\nseparation > 0 means the policy assigns higher unknown-likelihood to "
        "held-out (unknown) categories than to known ones — the direction each "
        "paper claims. This is not U-Recall/U-mAP and is not paper-comparable "
        "(see module docstring)."
    )


if __name__ == "__main__":
    main()
