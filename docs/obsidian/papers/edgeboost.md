# EdgeBoost: Confidence Boosting for Resource Constrained Inference via Selective Offloading

## 메타데이터
- categories: Temperature Scaling 기반 확률 보정, Confidence Margin 기반 오프로딩 결정, Edge-Cloud Collaborative Inference, Abstaining Classifier
- domain: [[엣지 실행·자원]]
- source: Said, Naina, Landsiedel, Olaf. "EdgeBoost: Confidence boosting for resource constrained inference via selective offloading." Computer Networks, vol. 269, 2025, Article 111437.
- url: https://doi.org/10.1016/j.comnet.2025.111437 (원 지시 URL: https://www.sciencedirect.com/science/article/pii/S1389128625004049)
- year: 2025
- authors: Naina Said, Olaf Landsiedel (Kiel University, Germany — Distributed Systems 연구그룹, GitHub organization `ds-kiel`)
- venue: Computer Networks (Elsevier), vol. 269, Article 111437, 2025 (Open Access, CC-BY, Unpaywall 기준 `oa_status: hybrid` 확인)

## 1. 핵심 요약
- **이 문서는 논문 PDF 원문을 직접 읽지 못한 상태에서 작성되었다.** ScienceDirect 페이지는 Cloudflare 봇 차단(직접 fetch 시 403, PDF 직접 요청 시 CAPTCHA 페이지 반환)으로 본문 전체에 접근하지 못했다. 대신 (a) 리더 프록시(r.jina.ai)를 통해 렌더링된 ScienceDirect 논문 페이지의 초록·highlights 수준 텍스트, (b) 저자들이 공개한 공식 GitHub 저장소(`ds-kiel/EdgeBoost`)의 README와 실제 실행 코드(`train.py`, `calibrate.py`, `offload.py`)를 raw text로 직접 확인해 이 문서를 작성했다. 아래 2~5절 중 코드로 직접 확인한 부분과 초록 수준에서만 확인한 부분을 구분해서 표기한다.
- EdgeBoost는 엣지 장치에 경량 모델을, 클라우드에 대형 모델을 배치하고, 엣지 모델의 예측 신뢰도가 낮은 입력만 선택적으로 클라우드에 오프로딩하는 collaborative edge-cloud inference 시스템이다. 공식 저장소 README 원문: "EdgeBoost trains and calibrates a lightweight model for deployment on the edge and, in addition, deploys a large, complex model on the cloud. During inference, the edge model makes initial predictions for input samples, and if the confidence of the prediction is low, the sample is sent to the cloud model for further processing otherwise, we accept the local prediction."
- 공식 코드로 직접 확인한 모델 조합은 **엣지: MobileNetV3-Small, 클라우드: EfficientNetV2-L**이며, 코드에 포함된 데이터셋은 **CIFAR-100**이다. ScienceDirect 초록/highlights 수준에서는 CIFAR-100 외에 **ImageNet-1k, Stanford Cars**에서도 평가했다고 언급되지만, 이 두 데이터셋에도 동일한 모델 조합을 썼는지는 논문 본문 없이는 확정할 수 없다(README는 "세 데이터셋에 대한 사전학습 모델을 제공한다"고만 언급).
- 오프로딩 판단에 쓰이는 "confidence"는 공식 코드(`offload.py`)를 그대로 읽으면 **단순 softmax 최댓값이 아니라, temperature scaling으로 보정(calibrate)된 softmax 확률의 top-1과 top-2 값의 차이(margin)** 이다(`diff = np.max(y_pred_cal) - np.sort(y_pred_cal)[-2]`). 이 margin이 threshold 이상이면 엣지(MobileNet) 예측을 채택하고, 미만이면 클라우드(EfficientNet) 예측으로 대체한다.
- ScienceDirect 초록/highlights 수준에서 확인한 정량적 주장: cloud-only 대비 통신량을 CIFAR-100 55%, ImageNet-1k 27%, Stanford Cars 20% 절감하면서도 유사한 정확도를 유지했고("achieving on par classification accuracy"), 보정(calibration)으로 인해 비보정 모델 대비 최대 8%p 정확도 향상, abstaining classifier로 사용 시 비보정 모델 대비 최대 9%p 정확도 향상을 얻었다고 명시한다.

## 2. 문서 목적
- 해결하려는 문제: 연산 자원이 제한된 엣지 장치에서 대형 모델 수준의 정확도를 유지하려면 결국 클라우드로 입력을 오프로딩해야 하는데, 모든 입력을 무조건 클라우드로 보내면(cloud-only) 통신 비용·지연이 크고, 반대로 엣지 모델만 쓰면 정확도가 떨어진다는 트레이드오프. (초록 수준에서 확인)
- 기술적 목표: 엣지 모델의 예측 신뢰도를 판단 기준으로 삼아, 확신이 낮은 입력만 선별적으로 클라우드에 보내는 selective offloading으로 cloud-only에 준하는 정확도를 더 적은 통신량으로 달성하는 것. 이때 신뢰도 판단 자체의 신뢰성을 높이기 위해 엣지 모델을 사후 보정(post-hoc calibration)한다는 것이 이 논문의 핵심 기여로 보인다. (초록 수준 + 코드로 교차 확인)
- 다루는 범위: 원문 확인 안 됨(Introduction/Related Work 전체를 읽지 못함). 코드 저장소 기준으로 확인되는 범위는 (i) 모델 학습(`train.py`), (ii) 비보정 모델 평가 및 확률 저장(`evaluate.py`), (iii) temperature scaling 기반 보정 및 ECE 산출(`calibrate.py`), (iv) 다중 threshold에서의 오프로딩 시뮬레이션 및 정확도·오프로딩 비율 산출(`offload.py`)이다.

## 3. 핵심 개념 상세

### Selective Offloading (선택적 오프로딩)
- 원문 표현(공식 README, verbatim): "During inference, the edge model makes initial predictions for input samples, and if the confidence of the prediction is low, the sample is sent to the cloud model for further processing otherwise, we accept the local prediction."
- 정의: 모든 입력을 무조건 클라우드로 보내는 cloud-only 방식이나 모든 입력을 엣지에서만 처리하는 edge-only 방식과 달리, 엣지 모델의 예측을 신뢰도 기준으로 걸러 일부 입력만 클라우드로 전달하는 라우팅 전략.
- 역할: 통신량(오프로딩되는 샘플 비율)과 정확도 사이의 트레이드오프를 threshold 하나로 조절할 수 있게 한다. 코드(`offload.py`)에서는 `T = [0.04, 0.087, 0.298, 0.59, 0.72, 0.83, 0.93]` 7개 threshold를 스윕하며 이 트레이드오프 곡선을 만든다.

### Temperature Scaling 기반 확률 보정
- 코드 근거(공식 저장소 `calibrate.py`, verbatim): `scaler = TemperatureScaler(); scaler = scaler.fit(model=model, calibration_set=cal_dataset); cal_model = torch.nn.Sequential(model, scaler)` — `torch_uncertainty.post_processing.TemperatureScaler`를 사용해 test set의 일부(코드 기준 1000장)를 calibration set으로 떼어내 온도 파라미터를 학습한다.
- 정의: 학습이 끝난 분류기의 logit을 스칼라 온도(T)로 나눈 뒤 softmax를 적용해, 모델이 과신(overconfident)하는 정도를 사후에 교정하는 대표적인 post-hoc calibration 기법.
- 역할: 신뢰도 값 자체(그리고 그로부터 파생되는 top1-top2 margin)의 신뢰성을 높여, 오프로딩 여부를 가르는 판단 기준이 "모델이 실제로 확신하는 정도"에 더 가깝게 만든다. 코드는 보정 전/후 Expected Calibration Error(ECE, `torchmetrics.CalibrationError`)를 함께 산출해 보정 품질을 정량화한다.

### Confidence Margin 기반 오프로딩 결정 규칙
- 코드 근거(공식 저장소 `offload.py`, verbatim): `diff = np.max(y_pred_cal) - np.sort(y_pred_cal)[-2]; if diff >= threshold: (엣지 예측 채택) else: (EfficientNet 예측으로 대체)`.
- 정의: 보정된 softmax 확률 벡터에서 1등 클래스 확률과 2등 클래스 확률의 차이(margin)를 신뢰도 지표로 사용하는 규칙. 이는 "단순 softmax 최댓값(raw max-probability)"도 아니고 "보정된 확률값 자체를 그대로 threshold와 비교"하는 것도 아니며, **보정된 확률에서 top-1/top-2 차이(margin)를 threshold와 비교**하는 방식이다.
- 역할: margin이 작다는 것은 모델이 상위 두 클래스 사이에서 헷갈리고 있다는 뜻이므로, 단일 최댓값보다 결정 경계 근처의 불확실성을 더 직접적으로 포착하려는 의도로 해석된다. (이 해석은 코드 구조로부터의 합리적 추론이며, 논문 본문에서 이렇게 설명하는지는 원문 확인 안 됨.)

### Abstaining Classifier 모드
- 근거: ScienceDirect 초록/highlights 수준에서 "EdgeBoost, when used as an abstaining classifier, can improve accuracy by up to 9 percent points over an uncalibrated model"라는 취지의 서술을 확인했다(리더 프록시로 렌더링된 요약이며, 원문 문장을 그대로 인용한 것은 아니다).
- 정의: 원문 확인 안 됨. 일반적으로 abstaining classifier는 신뢰도가 낮은 입력에 대해 클라우드로 보내는 대신 아예 예측을 보류(reject)하는 방식을 가리키는데, EdgeBoost가 이를 오프로딩과 어떻게 별도로 구분해 평가했는지 구체적 절차는 확인하지 못했다.
- 역할: 원문 확인 안 됨.

## 4. 구조 및 흐름
아래 흐름은 논문 본문 서술이 아니라 **공식 저장소 코드(`train.py` → `evaluate.py` → `calibrate.py` → `offload.py`)를 순서대로 읽고 재구성한 파이프라인**이다. 실제 논문이 이와 동일한 순서로 기술되어 있는지는 원문 확인 안 됨.
1. 엣지 모델(MobileNetV3-Small)과 클라우드 모델(EfficientNetV2-L)을 CIFAR-100에서 각각 독립적으로 학습한다(`train.py`, `--model_name mobilenet_v3 | efficientnet_v2_l`).
2. 학습된 엣지 모델을 test set에서 평가해 정확도·ECE를 산출하고, 비보정(uncalibrated) softmax 확률을 `.npy`로 저장한다(`evaluate.py`).
3. test set의 일부(코드 기준 1000장)를 calibration set으로 분리해 `TemperatureScaler`로 엣지 모델을 보정하고, 보정 후 ECE와 보정된 softmax 확률을 저장한다(`calibrate.py`).
4. 보정된 엣지 모델 확률, 비보정 확률, 클라우드 모델(EfficientNet) 확률, 정답 레이블을 입력으로 받아 여러 confidence threshold에서 오프로딩을 시뮬레이션한다: threshold 이상이면 엣지 예측을 채택, 미만이면 클라우드 예측으로 대체하고, 각 threshold별로 combined accuracy·오프로딩된 샘플 비율(`perc_model_2_samples`)·엣지 단독 정확도(`model1_accuracy`)를 계산한다(`offload.py`).
5. (초록/highlights 수준) 이렇게 얻은 정확도-통신량 트레이드오프 곡선을 cloud-only, Early Exit, Entropy thresholding, 그리고 "SOTA routing 기반 방법"과 비교한다. 비교 실험의 구체적 설정(모델 종류, threshold 선정 방식 등)은 원문 확인 안 됨.

## 5. 핵심 주장과 근거

| 주장 | 근거 | 확인 수준 |
|------|------|------|
| 오프로딩 결정에는 보정된 확률의 top1-top2 margin을 쓰며, 단순 raw softmax 최댓값이 아니다 | `offload.py`의 `diff = np.max(y_pred_cal) - np.sort(y_pred_cal)[-2]` 코드 라인 | 코드로 직접 확인 |
| 보정 방법은 temperature scaling이다 | `calibrate.py`의 `TemperatureScaler().fit(model=model, calibration_set=cal_dataset)` 코드 라인 | 코드로 직접 확인 |
| cloud-only 대비 통신량을 CIFAR-100 55%, ImageNet-1k 27%, Stanford Cars 20% 절감하면서 유사한 정확도("on par classification accuracy")를 유지했다 | ScienceDirect 논문 페이지 초록/highlights (리더 프록시 렌더링) | 초록 수준 확인, 원문 표·수치 대조는 안 됨 |
| 보정을 통해 비보정 모델 대비 최대 8%p 정확도 향상, abstaining classifier로는 최대 9%p 향상을 얻었다 | 위와 동일 | 초록 수준 확인 |
| Early Exit·Entropy thresholding 베이스라인을 능가하고, 엣지에 라우터를 둘 필요 없이 SOTA routing 기반 방법과 대등한 정확도를 낸다 | 위와 동일 | 초록/highlights 수준 확인, 구체 수치·베이스라인 설정은 원문 확인 안 됨 |
| 추론 지연을 148ms에서 123.84ms로 줄였다 | 위와 동일 | 초록 수준 확인. 단, 같은 저자·제목의 2024 IEEE DCOSS-IoT 학회판을 다룬 검색 스니펫에서는 298ms→233.3ms라는 다른 수치가 발견되어, 두 수치가 서로 다른 버전/측정 설정을 가리킬 가능성이 있다(원문 대조 안 됨) |

## 6. 한계 및 부족한 점
- **논문 PDF/HTML 본문을 직접 읽지 못했다.** ScienceDirect는 오픈 액세스(CC-BY, Unpaywall `is_oa: true`, `oa_status: hybrid` 확인)임에도 불구하고 자동화된 요청에 Cloudflare 봇 차단을 적용한다: `curl`로 직접 요청하면 실제 렌더링 없이 JS 앱 셸만 반환되고, PDF 직접 URL(`/pdfft`)은 CAPTCHA("Are you a robot?") 페이지를 반환했다. 리더 프록시(r.jina.ai)를 통해서만 초록/highlights 수준 텍스트를 확인할 수 있었고, 같은 프록시로 재시도해도 Introduction·Related Work·상세 실험 설계 문단·전체 결과 표는 노출되지 않았다(요약 수준에서 그침).
- 이 문서에서 가장 확신 있게 서술한 부분(temperature scaling 보정, top1-top2 margin 기반 오프로딩 규칙)은 **논문 본문이 아니라 공식 GitHub 저장소(`ds-kiel/EdgeBoost`)의 실제 코드**에서 얻었다. 저장소가 "이 논문을 위한 공식 저장소(official repository for the paper)"로 소개되어 있어 신뢰도가 높다고 판단했지만, 논문 원문의 수식·표기(예: margin을 논문에서 어떤 기호로 정의하는지)와 100% 동일한지는 대조하지 못했다.
- 코드 저장소에는 CIFAR-100 관련 아티팩트(`mobilenet_v3_cifar100.pth`, `cifar_test_labels.npy`, `efficientnetv2_predictions.npy` 등)만 포함되어 있다. README는 "논문에 사용된 세 데이터셋(three datasets used in our paper)"에 대한 사전학습 모델을 Google Drive로 제공한다고 언급하지만, ImageNet-1k·Stanford Cars에서도 정확히 동일한 모델 조합(MobileNetV3-Small/EfficientNetV2-L)과 동일한 margin-threshold 방식을 썼는지는 코드로 직접 확인하지 못했다.
- 같은 제목·저자의 IEEE DCOSS-IoT 2024 학회 논문(`ieeexplore.ieee.org/document/10621456`, computer.org CSDL에도 등재)이 별도로 존재한다. 검색 결과 요약에는 이 학회판이 "Best Paper Award"를 받았다는 언급이 있었으나, 이는 WebSearch 엔진이 생성한 요약 문장에서만 발견되었고 실제 페이지를 직접 읽어 확인한 것이 아니므로 신뢰도가 낮다. Computer Networks 2025 저널판이 이 학회판의 확장판(extended version)인지 여부도 원문에서 명시적으로 확인하지 못했다.
- "이종 모델 결과의 점진적 통합"이나 "capability 기반 provider 선택" 같은 이 프로젝트의 다른 요구사항(AI-S-06, AI-E-04)과 직접 연결되는 세부 설계 논의(예: 오프로딩 실패·통신 두절 시 fallback 동작)는 원문에서 확인하지 못해 이 문서에 포함하지 않았다.

## 7. 원문 기반 핵심 문장
> "EdgeBoost trains and calibrates a lightweight model for deployment on the edge and, in addition, deploys a large, complex model on the cloud. During inference, the edge model makes initial predictions for input samples, and if the confidence of the prediction is low, the sample is sent to the cloud model for further processing otherwise, we accept the local prediction."
> (출처: 공식 GitHub 저장소 `ds-kiel/EdgeBoost` README.md, 논문 PDF 원문이 아님 — raw 텍스트를 직접 확인)

> ```python
> diff = np.max(y_pred_cal) - np.sort(y_pred_cal)[-2]
> if diff >= threshold:
>     # 엣지(MobileNetV3-Small) 예측 채택
> else:
>     # 클라우드(EfficientNetV2-L) 예측으로 대체
> ```
> (출처: 공식 GitHub 저장소 `ds-kiel/EdgeBoost`의 `offload.py`, raw 코드를 직접 확인)
