"""FOMO-style per-class attribute generation, using a local LLM instead of GPT-3.5.

implements: AI-S-04 (research support script, not a shipped provider)

FOMO (Zohar et al., 2023, "Open World Object Detection in the Era of
Foundation Models") asks GPT-3.5 to list class-agnostic visual attributes
(color, texture, material, ...) per known class name, then embeds templated
attribute sentences with a text encoder. This script reproduces that step
against Qwen2.5-7B-Instruct served locally through Ollama (no external API
key — see project decision to avoid a paid/external LLM dependency for a
one-off data-prep step).

This is *not* a deployed capability/provider — it runs once, offline, and its
output (`attributes.json`) is a versioned data artifact consumed by
`perception_framework.perception.unknownness.FomoAttributePolicy`.

Deviation from the paper (documented, not silently substituted):
- LLM: Qwen2.5-7B-Instruct (local, Apache-2.0) instead of GPT-3.5. Attribute
  *quality* is not claimed to be identical — only the generation *procedure*
  (prompt class name, get attribute phrases, template them) is reproduced.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib import request as urlrequest

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b-instruct"

SPLIT_PATH = Path(__file__).resolve().parent / "tao_known_unknown_split.json"
OUTPUT_PATH = Path(__file__).resolve().parent / "attributes.json"

ATTRIBUTES_PER_CLASS = 6

# FOMO paper: attributes are class-agnostic (color/texture/material/shape),
# not category names themselves — the prompt explicitly forbids naming
# other object categories so the model doesn't just paraphrase the label.
PROMPT_TEMPLATE = """List {n} short visual attributes (color, texture, material, shape, size) \
that commonly describe the appearance of a "{class_name}" in a photo.
Rules:
- Each attribute is 1-3 words (e.g. "smooth", "metallic", "bright red").
- Do not name other object categories or the object itself.
- Return ONLY a JSON array of strings, nothing else.
"""

# FOMO's templated attribute sentence, used to embed each attribute phrase
# with the same text encoder used for class-name embedding.
ATTRIBUTE_SENTENCE_TEMPLATE = "an object that is {attribute}"


def _call_ollama(prompt: str) -> str:
    payload = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}).encode()
    req = urlrequest.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return body["response"]


def _parse_attribute_list(raw_response: str) -> list[str]:
    match = re.search(r"\[.*\]", raw_response, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON array found in LLM response: {raw_response!r}")
    attributes = json.loads(match.group(0))
    if not isinstance(attributes, list) or not all(isinstance(a, str) for a in attributes):
        raise ValueError(f"expected a JSON array of strings, got: {attributes!r}")
    return [a.strip() for a in attributes if a.strip()]


def generate_attributes_for_class(class_name: str) -> list[str]:
    prompt = PROMPT_TEMPLATE.format(n=ATTRIBUTES_PER_CLASS, class_name=class_name)
    response = _call_ollama(prompt)
    return _parse_attribute_list(response)


def main() -> None:
    split = json.loads(SPLIT_PATH.read_text())
    known_classes = [entry["natural_name"] for entry in split["known"]]

    per_class: dict[str, list[str]] = {}
    failures: list[str] = []
    for class_name in known_classes:
        try:
            per_class[class_name] = generate_attributes_for_class(class_name)
            print(f"{class_name}: {per_class[class_name]}")
        except Exception as exc:  # noqa: BLE001 — one bad class must not stop the batch
            failures.append(class_name)
            print(f"{class_name}: FAILED ({exc})")

    output = {
        "model": MODEL,
        "sentence_template": ATTRIBUTE_SENTENCE_TEMPLATE,
        "attributes_per_class": per_class,
        "failed_classes": failures,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n{len(per_class)}/{len(known_classes)} classes succeeded -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
