# FOMO / OW-OVD / OWOBJ direction-only validation

implements: AI-S-03, AI-S-04 (research support, not shipped provider code)

Reproduces the unknown-object-likelihood mechanism from three OWOD papers
(see `docs/obsidian/papers/{fomo,ow-ovd,owobj}.md`) against the real
`OwlVitPerceptionProvider` pipeline and the locally downloaded TAO subset —
**mechanism direction**, not the papers' M-OWODB/S-OWODB benchmark numbers
(see decision log below for why).

## Run order

```bash
python research/fomo/build_split.py        # -> tao_known_unknown_split.json
python research/fomo/generate_attributes.py # -> attributes.json (needs local Ollama)
python research/fomo/validate_tao.py        # prints known/unknown p_unknown separation per policy
```

## What each script does

- **`build_split.py`** — reconstructs a known/unknown class split from TAO's
  native LVIS `frequency` label (f/c = known, r = unknown), restricted to
  categories present in the 4178 frames already downloaded under
  `datasets/tao/`. This is a *new* split, not the original 0B/0C experiment's
  (that script was removed from the repo before this session; only two
  numbers — known recall 0.757, unknown recall 0.392 — survive as a comment
  in `perception_framework/perception/open_vocabulary.py`).
- **`generate_attributes.py`** — FOMO's attribute-generation step, run
  against a local LLM instead of GPT-3.5 (see decision log). Talks to
  Ollama's local HTTP API (`localhost:11434`, no API key).
- **`validate_tao.py`** — runs the real OWL-ViT ONNX model twice per frame
  (known vocab, attribute vocab), scores every ground-truth box with all
  three policies (`perception_framework.perception.unknownness`), and
  reports `mean(p_unknown | known GT)` vs `mean(p_unknown | unknown GT)` per
  policy. A positive gap ("separation") is the paper-claimed direction.

## Decisions made this session (why things look the way they do)

- **Local LLM instead of GPT-3.5**: chosen to avoid an external API key/cost
  dependency for a one-off data-prep script. Model: Qwen2.5-7B-Instruct
  (Apache-2.0), served locally via Ollama.
- **Direction-only validation, not full M-OWODB/S-OWODB reproduction**: the
  full benchmarks need COCO+VOC downloads and, for OW-OVD, incremental
  fine-tuning across 4 tasks — multi-day GPU work disproportionate to
  "does this mechanism work" for a framework validation. `validate_tao.py`'s
  docstring states this explicitly on every run's output.
- **OWOBJ is explicitly unverifiable**: OWOBJ's official code/weights are
  not released (`docs/obsidian/papers/owobj.md` §6). `OwobjEnergyPolicy` in
  `perception_framework/perception/unknownness.py` reimplements the paper's
  described energy-margin formula, but there is no official baseline to
  check it against — its docstring says so, and no result from it should be
  reported as "reproduces OWOBJ."
- **Known/unknown split is reconstructed, not the original 0B/0C split**:
  see `build_split.py` docstring. Any numbers from `validate_tao.py` are a
  fresh measurement (AI-B-01: 다른 구성에서 측정한 성능은 자동으로 같다고
  가정하지 않는다), not a like-for-like comparison to the 0.757/0.392
  figures.

## Known environment issue (2026-09-04)

Downloading the ~4.7GB Qwen2.5-7B-Instruct GGUF failed repeatedly through
both Ollama's own registry and a direct HuggingFace download — this sandbox's
outbound network intermittently fails DNS resolution entirely (not specific
to one host) and throttles large transfers to ~40KB/s effective throughput
when it does resolve. A long-running resumable retry loop was left running
in the background (`nohup ... curl -C - ...`, PID tracked in the session that
started it) rather than blocking on it. `generate_attributes.py` cannot run
until that file exists at `~/.ollama/gguf/qwen2.5-7b-instruct-q4_k_m.gguf`
(or an equivalent model is registered with Ollama).
