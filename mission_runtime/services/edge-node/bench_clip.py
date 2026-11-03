"""엣지 CLIP 이미지 타워 후보 벤치 — GPU에서 실제로 빠른 것을 고른다.

implements: AI-B-01, AI-B-08, AI-B-09, AI-O-01

동기(2026-09-21): 엣지 stage2가 crop 60장에 800~1000 ms를 써서 비동기 큐가 6:1로
밀렸다. 지금까지 시도한 두 대책이 **둘 다 실패**했고 이유가 같다:

  * 배치 쪼개기 → 900→950 ms. 이전 코드가 이미 한 번에 넣고 있었다.
  * quantized ONNX를 CUDA EP로 → 986 ms. quantized 연산이 CUDA에 없어 그래프에
    memcpy 노드 174개가 끼고 CPU↔GPU를 오간다.

즉 **quantized ONNX는 GPU로 갈 수 없는 형식**이다. 이 벤치는 그 전제를 바꿔
fp32/fp16 그래프와 torch CUDA 경로를 같은 crop·같은 배치로 잰다.

정확도도 같이 본다 — 지연만 보고 고르면 근거 품질이 조용히 바뀐다. 기준선
(quantized CPU) 임베딩과의 코사인 유사도를 함께 출력하므로, 빠른 후보가 기준선과
다른 것을 보고 있는지 판단할 수 있다(AI-B-01: 다른 구성의 성능을 자동으로 같다고
가정하지 않는다).

주의: 이 venv의 onnxruntime은 CUDA EP를 목록에 올리지만 `libcublasLt.so.13`이 없어
실제 생성에 실패하고 **조용히 CPU로 내려간다**. torch가 가진 `nvidia/*/lib`를
LD_LIBRARY_PATH에 넣어야 올라간다 — 실행 방법은 README 참고.
"""

from __future__ import annotations

import glob
import json
import time

import cv2
import numpy as np

CROPS = sorted(glob.glob("store/unknown_crops/*.jpg"))
N_REPEAT = 3
# CLIP 전처리 상수(OpenAI). MobileCLIP 계열도 open_clip 기본 전처리가 같은 값을 쓴다.
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


def load_batch(size: int, n: int) -> np.ndarray:
    imgs = [cv2.imread(f) for f in CROPS[:n]]
    imgs = [i for i in imgs if i is not None]
    while len(imgs) < n:                      # 항상 같은 배치 크기로 비교한다
        imgs += imgs[: n - len(imgs)]
    out = []
    for c in imgs[:n]:
        r = cv2.resize(c, (size, size))
        x = cv2.cvtColor(r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        out.append(((x - MEAN) / STD).transpose(2, 0, 1))
    return np.ascontiguousarray(np.stack(out))


def l2(a: np.ndarray) -> np.ndarray:
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def timeit(fn, n_repeat: int = N_REPEAT) -> tuple[float, float, np.ndarray]:
    out = fn()                                 # warmup (그래프 빌드·커널 선택 제외)
    ts = []
    for _ in range(n_repeat):
        t = time.perf_counter()
        out = fn()
        ts.append((time.perf_counter() - t) * 1000.0)
    return float(np.median(ts)), float(min(ts)), out


# --------------------------------------------------------------------------
def bench_onnx(path: str, size: int, batch: int, providers: list[str]):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    sess = ort.InferenceSession(path, so, providers=providers)
    name = sess.get_inputs()[0].name
    x = load_batch(size, batch)
    med, mn, out = timeit(lambda: sess.run(None, {name: x})[0])
    return med, mn, l2(np.asarray(out, np.float32)), sess.get_providers()[0]


def bench_torch(builder, size: int, batch: int, half: bool):
    import torch

    model, dev = builder()
    model = model.to(dev).eval()
    if half:
        model = model.half()
    x = torch.from_numpy(load_batch(size, batch)).to(dev)
    if half:
        x = x.half()

    def run():
        with torch.inference_mode():
            f = model(x)
            if hasattr(f, "image_embeds"):
                f = f.image_embeds
            elif hasattr(f, "pooler_output"):
                f = f.pooler_output
        torch.cuda.synchronize() if dev == "cuda" else None
        return f.float().cpu().numpy()

    med, mn, out = timeit(run)
    return med, mn, l2(np.asarray(out, np.float32)), f"torch/{dev}{'/fp16' if half else '/fp32'}"


# --------------------------------------------------------------------------
def main() -> None:
    import torch

    batch = 60
    rows, baseline = [], None
    print(f"crop {len(CROPS)}장 중 {batch}장 배치, 반복 {N_REPEAT}회\n")

    def add(tag, size, fn):
        nonlocal baseline
        try:
            med, mn, emb, ep = fn()
            cos = None
            if baseline is None:
                baseline = emb
            elif emb.shape == baseline.shape:
                cos = float((emb * baseline).sum(-1).mean())
            rows.append({"model": tag, "input": size, "ep": ep,
                         "p50_ms": round(med, 1), "min_ms": round(mn, 1),
                         "ms_per_crop": round(med / batch, 2),
                         "cos_vs_baseline": round(cos, 4) if cos is not None else None})
            print(f"{tag:<34} {size:>4}  {ep:<22} {med:8.1f} ms  "
                  f"{med/batch:6.2f} ms/crop  cos={cos if cos is None else round(cos,4)}")
        except Exception as exc:
            print(f"{tag:<34} 실패: {repr(exc)[:120]}")

    # 기준선 — 지금 운영 중인 구성
    add("CLIP B/32 int8 ONNX (기준선)", 224, lambda: bench_onnx(
        "../models/openvocab/clip-vit-base-patch32/onnx/vision_model_quantized.onnx",
        224, batch, ["CPUExecutionProvider"]))

    # quantized를 GPU로 — 실패 예상. 그 실패를 수치로 남긴다.
    add("CLIP B/32 int8 ONNX → CUDA", 224, lambda: bench_onnx(
        "../models/openvocab/clip-vit-base-patch32/onnx/vision_model_quantized.onnx",
        224, batch, ["CUDAExecutionProvider", "CPUExecutionProvider"]))

    # fp32 ONNX — quantize 노드가 없으니 CUDA가 그래프를 통째로 가져갈 수 있다
    add("CLIP B/32 fp32 ONNX → CUDA", 224, lambda: bench_onnx(
        "../models/openvocab/clip-vit-base-patch32/onnx/clip_vision_fp32.onnx",
        224, batch, ["CUDAExecutionProvider", "CPUExecutionProvider"]))

    if torch.cuda.is_available():
        def hf_clip():
            from transformers import CLIPVisionModelWithProjection
            return (CLIPVisionModelWithProjection.from_pretrained(
                "openai/clip-vit-base-patch32"), "cuda")
        add("CLIP B/32 torch fp32", 224, lambda: bench_torch(hf_clip, 224, batch, False))
        add("CLIP B/32 torch fp16", 224, lambda: bench_torch(hf_clip, 224, batch, True))

        def oc(name):
            def build():
                import open_clip
                m, _, _ = open_clip.create_model_and_transforms(f"hf-hub:{name}")
                return m.visual, "cuda"
            return build
        add("MobileCLIP2-S0 torch fp16", 256,
            lambda: bench_torch(oc("timm/MobileCLIP2-S0-OpenCLIP"), 256, batch, True))
        add("MobileCLIP-S1 torch fp16", 256,
            lambda: bench_torch(oc("apple/MobileCLIP-S1-OpenCLIP"), 256, batch, True))

    print()
    with open("bench_clip_results.json", "w", encoding="utf-8") as f:
        json.dump({"batch": batch, "n_crops": len(CROPS), "rows": rows,
                   "note": ("cos_vs_baseline은 quantized CPU 임베딩과의 코사인 유사도다. "
                            "낮으면 빠르지만 다른 것을 보고 있다는 뜻이라 근거 품질이 바뀐다."),
                   "at": time.time()}, f, ensure_ascii=False, indent=1)
    print("→ bench_clip_results.json")


if __name__ == "__main__":
    main()
