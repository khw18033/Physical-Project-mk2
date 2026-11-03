#!/usr/bin/env python3
"""내려받은 참조영상에서 기종 사전(원형 벡터)을 만든다.

implements: AI-E-01, AI-S-04, AI-L-09
tests: tests/test_appearance_classifier.py

`fetch_references.py` 가 모아 둔 `local/appearance/<class>/*.jpg` 를 실제 CLIP
ONNX 로 임베딩해 `config/device_appearance_classes.*.json` 을 쓴다. 사진 자체는
공개하지 않고 **여기서 나온 벡터만** 공개 트리에 올라간다.

임베딩은 `mission_runtime.edge.clip_dictionary_provider.ClipEngine` 을 그대로
쓴다. 전처리(resize·center crop·CLIP 평균/표준편차)가 1 픽셀이라도 다르면 사전을
만들 때 쓴 공간과 운영에서 crop 을 재는 공간이 달라져, 유사도는 나오지만 그 값이
무엇과 무엇의 거리인지 아무도 보증하지 못하게 된다. 그래서 로더를 새로 쓰지 않는다.

## 원형 하나로 뭉치지 않고 참조영상별 벡터를 함께 남기는 이유

평균 벡터 하나만 남기면 "왜 이 기종인가"에 답할 수 있는 말이 "평균과 가까워서"
뿐이다. 그것은 운영자에게 아무 정보도 아니다. 참조영상별 벡터를 남기면 판정의
근거를 "앞에서 본 사진 2 장과 닮았다"처럼 **볼 수 있는 것**으로 돌려줄 수 있고,
이상한 참조영상 하나가 점수를 만들고 있다는 사실도 드러난다(AI-S-03).

## --self-check 가 임계값을 정한다

유사도 임계값과 모호 판정 마진은 짐작으로 정할 수 없다. 참조영상 한 장을 빼고
나머지로 그 장을 분류하는 leave-one-out 을 돌려 "맞은 경우의 1·2 위 차이"와
"틀린 경우"의 분포를 재고, 그 수치를 사전의 `_meta` 에 그대로 적는다. 적힌 숫자가
없으면 임계값은 근거가 아니라 취향이다(AI-B-01: 미측정 항목은 구분해 남긴다).

사용법:

    python3 tools/appearance/build_dictionary.py \\
        --references ../local/appearance \\
        --sources tools/appearance/reference_sources.json \\
        --model-dir ../local/models/openvocab/clip-vit-base-patch32 \\
        --out config/device_appearance_classes.example.json --self-check
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

#: 벡터 소수 자리. L2 정규화된 512 차원 벡터에서 1e-5 는 코사인 유사도에 1e-4
#: 수준으로만 영향을 주는데, 이 사전의 판정 마진은 그보다 두 자리 크다. 자리수를
#: 더 남기면 설정 파일만 커지고 판정은 달라지지 않는다.
VECTOR_PRECISION = 5
#: 점수에 쓰는 상위 참조영상 수. 1 장이면 유별난 사진 한 장이 그대로 점수가 되고,
#: 전부 평균하면 같은 기종을 다른 각도에서 찍은 사진들이 서로를 깎는다.
DEFAULT_TOP_K = 3
#: 아래 두 값의 근거는 `--self-check` 가 잰 수치다(사전의 `_meta.self_check`).
#: 52 회 leave-one-out 에서 1·2 위 차이가 0.05 를 넘은 판정 중 **틀린 것이 하나도
#: 없었고**, 0.03 에서는 하나 남았다. 대가는 10/52 가 '모호'로 떨어지는 것인데,
#: 모호는 틀린 확답보다 싸다 — 틀린 기종은 그대로 다음 판단의 전제가 된다.
#: (기종이 5 종으로 는 2026-11-03 재측정 결과. 4 종이던 2026-11-02 측정에서도
#: 같은 값에서 같은 결론이었다.)
DEFAULT_AMBIGUITY_MARGIN = 0.05
#: 같은 기종 판정의 최저 점수가 0.6236 이었다. 0.55 는 그 아래라 정상 판정을
#: 깎지 않고, "어느 참조영상과도 닮지 않았다"만 걸러낸다. 이 값으로 기종을 **가를**
#: 수는 없다 — 다른 기종에서 나온 점수가 0.8915 까지 올라가 구간이 겹친다.
DEFAULT_SIMILARITY_FLOOR = 0.55


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _engine(model_dir: Path):
    """운영에서 쓰는 것과 **같은** CLIP 로더. 전처리까지 같아야 의미가 있다."""
    from mission_runtime.edge.clip_dictionary_provider import ClipEngine

    return ClipEngine(
        model_dir / "onnx" / "vision_model_quantized.onnx",
        model_dir / "onnx" / "text_model_quantized.onnx",
        model_dir / "tokenizer.json",
    )


def _class_specs(sources_path: Path) -> dict[str, dict]:
    spec = json.loads(sources_path.read_text(encoding="utf-8"))
    return {entry["class_name"]: entry for entry in spec["classes"]}


#: 참조영상이 어디서 왔는지. 제품 사진으로 시작해 현장 사진으로 보강하는 것이
#: 정해진 순서이고(2026-11-03 사용자 결정), 둘을 한 덩어리로 세면 "아직 제품
#: 사진뿐"인 기종과 "현장에서 확인된" 기종이 같아 보인다.
ORIGIN_WEB = "web_reference"
ORIGIN_FIELD = "field_capture"
#: 현장 사진 자리. `fetch_references.py` 는 이 디렉터리를 지우지 않는다.
FIELD_DIR = "field"
FIELD_SUFFIXES = (".jpg", ".jpeg", ".png")


def _reference_files(class_dir: Path) -> list[tuple[Path, str]]:
    """웹 사진과 현장 사진을 출처 표시와 함께 모은다. 현장 사진이 뒤에 붙는다."""
    web = [(path, ORIGIN_WEB) for path in sorted(class_dir.glob("*.jpg"))]
    field = [(path, ORIGIN_FIELD)
             for path in sorted((class_dir / FIELD_DIR).glob("*"))
             if path.suffix.lower() in FIELD_SUFFIXES]
    return web + field


def _previous_references(out_path: Path) -> dict[str, dict[str, dict]]:
    """이미 만들어 둔 사전에서 참조영상별 기록을 꺼낸다.

    운영자가 "이 참조영상은 틀렸다"고 내린 가중치는 사전을 다시 만들 때마다
    1.0 으로 되돌아가면 안 된다 — 그러면 교정은 매번 사라지고 같은 오판이
    돌아온다(AI-L-03: 사용자가 확인한 정보는 보존한다).
    """
    if not out_path.exists():
        return {}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    return {
        name: {r["file"]: r for r in entry.get("references", [])}
        for name, entry in payload.items() if not name.startswith("_")
    }


def _previous_blocks(out_path: Path, key: str) -> dict:
    """사람이 손으로 적어 넣은 블록을 이어받는다.

    `estimation_profile`(기종이 어떤 action 을 공지하고 어떤 태그를 달고 얼마나
    큰가)은 **측정이 아니라 선언**이라 이 스크립트가 만들어 낼 수 없다. 재빌드가
    그것을 지우면 다중 단서 추정은 사진을 한 장 더할 때마다 눈이 먼다
    (perception/device_class_estimator.py).
    """
    if not out_path.exists():
        return {}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    if key.startswith("_"):
        return payload.get("_meta", {}).get(key[1:], {})
    return {name: entry[key] for name, entry in payload.items()
            if not name.startswith("_") and key in entry}


def build(references_root: Path, sources_path: Path, model_dir: Path,
          *, top_k: int = DEFAULT_TOP_K, previous: dict | None = None,
          reuse_embeddings: bool = False, profiles: dict | None = None) -> dict:
    import cv2
    import numpy as np

    specs = _class_specs(sources_path)
    engine = None
    out: dict = {}
    vectors: dict[str, "np.ndarray"] = {}

    for class_name, spec in specs.items():
        class_dir = references_root / class_name
        files = _reference_files(class_dir) if class_dir.exists() else []
        kept = (previous or {}).get(class_name, {})
        entry: dict = {
            "label": spec.get("label", class_name),
            "identity": spec.get("identity", "confirmed"),
            "identity_note": spec.get("identity_note", ""),
            "built_at": _now(),
        }
        profile = (profiles or {}).get(class_name)
        if profile is not None:
            entry["estimation_profile"] = profile
        if not files:
            # 0 장은 비어 있는 원형이 아니라 **분류할 수 없는 기종**이다. 빈 벡터나
            # 0 벡터를 넣으면 코사인 유사도가 0 으로 나와 "닮지 않았다"는 측정값처럼
            # 보이지만, 사실은 아무것도 재지 않은 것이다(AI-B-01).
            entry["unfit_reason"] = "no_reference_image"
            out[class_name] = entry
            continue

        sources = {}
        sources_json = class_dir / "sources.json"
        if sources_json.exists():
            sources = {r["file_name"]: r
                       for r in json.loads(sources_json.read_text(encoding="utf-8"))["references"]}

        # 이미 임베딩해 둔 사진은 다시 인코딩하지 않는다(--append). 현장 사진이
        # 한 장 늘 때마다 수십 장을 다시 돌릴 이유가 없고, 같은 모델·같은 전처리라
        # 결과도 같다.
        fresh = [(i, path) for i, (path, _) in enumerate(files)
                 if not (reuse_embeddings and "embedding" in kept.get(path.name, {}))]
        if fresh and engine is None:
            # 새로 인코딩할 사진이 하나도 없으면 모델을 읽지 않는다 — 현장 사진
            # 한 장을 더할 때 수백 MB 를 다시 읽을 이유가 없다.
            engine = _engine(model_dir)
        computed = (engine.embed_images([cv2.imread(str(path)) for _, path in fresh])
                    if fresh else None)
        rows: list[list[float]] = []
        references: list[dict] = []
        fresh_index = {i: n for n, (i, _) in enumerate(fresh)}
        for i, (path, origin) in enumerate(files):
            before = kept.get(path.name, {})
            if i in fresh_index:
                vector = [round(float(v), VECTOR_PRECISION)
                          for v in computed[fresh_index[i]]]
            else:
                vector = before["embedding"]
            rows.append(vector)
            references.append({
                "file": path.name,
                "origin": before.get("origin", origin),
                # 운영자 교정용 가중치. 0 이면 점수에서 빠지되 설명에는 남는다 —
                # 조용히 지우면 "왜 저 사진이 더 이상 근거가 아닌가"를 알 수 없다.
                "weight": float(before.get("weight", 1.0)),
                "source_url": sources.get(path.name, {}).get(
                    "source_url", before.get("source_url", "")),
                "page_url": sources.get(path.name, {}).get(
                    "page_url", before.get("page_url", "")),
                "license_note": sources.get(path.name, {}).get(
                    "license_note", before.get("license_note", "")),
                "embedding": vector,
            })
        embeddings = np.array(rows, dtype=np.float32)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        vectors[class_name] = embeddings
        entry["references"] = references
        prototype = embeddings.mean(axis=0)
        prototype = prototype / np.linalg.norm(prototype)
        entry["prototype"] = [round(float(v), VECTOR_PRECISION) for v in prototype]
        entry["prototype_kind"] = "l2_normalised_mean_of_reference_embeddings"
        entry["score_top_k_references"] = min(top_k, len(files))
        entry["reference_origins"] = {
            origin: sum(1 for r in references if r["origin"] == origin)
            for origin in (ORIGIN_WEB, ORIGIN_FIELD)
        }
        # `clip_dictionary_provider` 가 읽는 블록과 같은 이름을 쓴다 — 같은 뜻의
        # 항목이 파일마다 다른 이름으로 적히면 사전이 둘로 갈라진다(AI-C-01).
        entry["reference_image_features"] = {
            "source_image": str((class_dir / files[0][0].name).as_posix()),
            "features": [],
            "unanchored_features": [],
            "note": "이 사전은 텍스트 특징이 아니라 참조영상 임베딩으로 판정한다 — 문구 목록은 측정한 적이 없으므로 빈 채로 둔다(0 이 아니라 '없음').",
        }
        out[class_name] = entry

    return {"classes": out, "_vectors": vectors, "_engine_loaded": engine is not None}


def self_check(classes: dict, vectors: dict, *, top_k: int) -> dict:
    """참조영상 한 장을 빼고 나머지로 그 장을 분류한다(leave-one-out).

    맞은 경우의 1·2 위 차이가 얼마나 벌어지는지, 틀린 경우가 있는지를 재서
    임계값의 근거로 남긴다. 자기 자신을 참조로 두고 재면 유사도는 항상 1.0 이라
    아무것도 검증하지 못한다 — 그래서 반드시 뺀다.
    """
    import numpy as np

    names = sorted(vectors)
    correct = 0
    total = 0
    margins: list[float] = []
    wrong: list[dict] = []
    top_scores: list[float] = []
    cross_scores: list[float] = []

    for truth in names:
        for index in range(len(vectors[truth])):
            probe = vectors[truth][index]
            ranked = []
            for name in names:
                matrix = vectors[name]
                sims = matrix @ probe
                if name == truth:
                    sims = np.delete(sims, index)
                if sims.size == 0:
                    continue
                k = min(top_k, sims.size)
                ranked.append((float(np.sort(sims)[::-1][:k].mean()), name))
            if len(ranked) < 2:
                continue
            ranked.sort(reverse=True)
            total += 1
            top_scores.append(ranked[0][0])
            cross_scores.extend(score for score, name in ranked if name != truth)
            if ranked[0][1] == truth:
                correct += 1
                margins.append(ranked[0][0] - ranked[1][0])
            else:
                wrong.append({"truth": truth, "picked": ranked[0][1],
                              "score": round(ranked[0][0], 4)})

    margins_sorted = sorted(margins)
    return {
        "method": "leave_one_out_over_reference_images",
        "top_k_references": top_k,
        "probes": total,
        "correct": correct,
        "wrong": wrong,
        "correct_margin_min": round(margins_sorted[0], 4) if margins_sorted else None,
        "correct_margin_p05": (round(margins_sorted[max(0, int(0.05 * len(margins_sorted)) - 1)], 4)
                               if margins_sorted else None),
        "correct_margin_median": (round(margins_sorted[len(margins_sorted) // 2], 4)
                                  if margins_sorted else None),
        "own_class_score_min": round(min(top_scores), 4) if top_scores else None,
        "other_class_score_max": round(max(cross_scores), 4) if cross_scores else None,
        "note": "같은 기종끼리의 최저 점수와 다른 기종에서 나온 최고 점수가 겹치면 그 구간은 어떤 임계값으로도 가를 수 없다 — 겹침 자체를 적어 둔다.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--references", required=True, type=Path,
                        help="fetch_references.py 가 만든 기종별 디렉터리의 뿌리")
    parser.add_argument("--sources", required=True, type=Path,
                        help="기종 이름표·식별 상태를 가진 출처 선언 JSON")
    parser.add_argument("--model-dir", required=True, type=Path,
                        help="CLIP ONNX 모델 디렉터리(onnx/*.onnx + tokenizer.json)")
    parser.add_argument("--out", required=True, type=Path, help="쓸 사전 JSON 경로")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--ambiguity-margin", type=float, default=DEFAULT_AMBIGUITY_MARGIN)
    parser.add_argument("--similarity-floor", type=float, default=DEFAULT_SIMILARITY_FLOOR)
    parser.add_argument("--append", action="store_true",
                        help="이미 임베딩한 사진은 그대로 두고 새 사진만 더한다 "
                             "(현장 사진 보강 경로 — 사전을 처음부터 다시 만들지 않는다)")
    parser.add_argument("--self-check", action="store_true",
                        help="leave-one-out 으로 임계값 근거를 재서 _meta 에 남긴다")
    args = parser.parse_args(argv)

    # 가중치는 --append 여부와 무관하게 이어받는다. 운영자 교정이 재빌드마다
    # 사라지면 그것은 교정이 아니다.
    built = build(args.references.resolve(), args.sources, args.model_dir.resolve(),
                  top_k=args.top_k, previous=_previous_references(args.out),
                  reuse_embeddings=args.append,
                  profiles=_previous_blocks(args.out, "estimation_profile"))
    classes = built["classes"]

    meta = {
        "purpose": "이 배치가 가진 장비의 **기종**을 외형으로 가르기 위한 참조영상 임베딩 사전. 기종은 개체가 아니다 — 같은 기종이 두 대면 이 사전은 둘을 영원히 구분하지 못하고, 그것이 설계대로다(perception/device_identity.py).",
        "built_at": _now(),
        "built_by": "tools/appearance/build_dictionary.py",
        "embedding_model": {
            "id": args.model_dir.name,
            "vision_model": "onnx/vision_model_quantized.onnx",
            "preprocess": "mission_runtime.edge.clip_dictionary_provider",
            "embedding_dim": next((len(c["prototype"]) for c in classes.values()
                                   if "prototype" in c), None),
        },
        "vector_precision": VECTOR_PRECISION,
        "thresholds": {
            "ambiguity_margin": args.ambiguity_margin,
            "similarity_floor": args.similarity_floor,
            "top_k_references": args.top_k,
            "rationale": "self_check 의 leave-one-out 수치에서 고른 값이다. 1·2 위 차이가 margin 이하면 고르지 않고 모호로 둔다. floor 는 기종을 가르는 값이 아니라 '어느 참조영상과도 닮지 않았다'만 거르는 값이다(같은 기종 최저 0.6236 vs 다른 기종 최고 0.8915 로 절대점수 구간이 겹친다). 2026-11-03 보강(52→86 장) 전후: 확신 정답 42/52 → 70/86, 확신 오답은 양쪽 모두 0, 모호 10/52 → 16/86 — 사진을 늘려 고쳐진 것은 1 위가 뒤집히던 두 건이고 모호 비율은 거의 그대로다. 하나(어두운 접사 insta360 → 어두운 스튜디오 go1)는 같은 조건의 참조영상이 5 장 늘면서 사라졌고, 다른 하나(go1 → 흰 배경 mt4)는 배경 문제가 아니라 참조영상 자체가 규칙 위반이었다 — 겉면이 아니라 내부 기판이 비쳐 보이는 투시 렌더라 흰 배경 스튜디오 사진과 닮았던 것이다(tools/appearance/reference_sources.json 의 go1 exclude_rationale).",
        },
        "reference_images_are_not_published": "원본 사진은 제조사·언론·판매처의 저작물이라 local/appearance/ 에만 두고 커밋하지 않는다. 출처 URL 과 받은 시각은 그 디렉터리의 sources.json 에 있다.",
    }
    if args.self_check:
        meta["self_check"] = self_check(classes, built["_vectors"], top_k=args.top_k)

    payload = {"_meta": meta}
    payload.update(classes)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    for name, entry in classes.items():
        origins = entry.get("reference_origins", {})
        count = len(entry.get("references", []))
        state = entry.get("unfit_reason", "ok")
        print(f"{name:<20}{count:>4} references "
              f"(web {origins.get(ORIGIN_WEB, 0)}, field {origins.get(ORIGIN_FIELD, 0)})"
              f"   {state}")
    if args.self_check:
        print(json.dumps(meta["self_check"], indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out} ({args.out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
