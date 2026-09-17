# YOLOE: Real-Time Seeing Anything

## 메타데이터
- categories: RepRTA Region-Text Alignment, SAVPE Visual Prompt Encoder, LRPC Prompt-free Retrieval, 통합 Detection-Segmentation 모델
- domain: [[객체 탐지·분할]]
- source: Wang, Ao, Liu, Lihao, Chen, Hui, Lin, Zijia, Han, Jungong, Ding, Guiguang. "YOLOE: Real-Time Seeing Anything." Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2025.
- url: https://openaccess.thecvf.com/content/ICCV2025/html/Wang_YOLOE_Real-Time_Seeing_Anything_ICCV_2025_paper.html
- year: 2025
- authors: Wang et al.
- venue: IEEE/CVF International Conference on Computer Vision (ICCV)

## 1. 핵심 요약
- 기존 YOLO 계열은 사전에 정의된 카테고리에 제한되어 open scenario 적응력이 떨어지고, 이를 해결하려는 text prompt·visual prompt·prompt-free 방식들은 높은 연산 비용이나 배포 복잡도 때문에 성능과 효율 사이에서 타협해야 했다.
- YOLOE는 text prompt, visual prompt, prompt-free 세 가지 open prompt 방식을 detection·segmentation과 함께 하나의 효율적인 모델로 통합해 real-time "seeing anything"을 달성한다.
- 텍스트 프롬프트에는 RepRTA(Re-parameterizable Region-Text Alignment), 비주얼 프롬프트에는 SAVPE(Semantic-Activated Visual Prompt Encoder), prompt-free 시나리오에는 LRPC(Lazy Region-Prompt Contrast)를 사용한다.
- LVIS zero-shot에서 YOLOE-v8-S가 YOLO-Worldv2-S 대비 3.5 AP 높으면서 학습 비용은 3배 적고, T4/iPhone12에서 각각 1.4배/1.3배 빠르다.
- COCO에서는 closed-set YOLOv8-L 대비 AP^b +0.6, AP^m +0.4를 얻으면서 학습 시간은 약 4배 적게 든다.

## 2. 문서 목적
- 해결하려는 문제: 폐쇄형(predefined) 카테고리에 갇힌 YOLO 계열의 한계와, 이를 극복하려는 open-set 방법들이 성능과 효율(연산 비용·배포 복잡도) 사이에서 타협해야 하는 문제.
- 기술적 목표: text/visual/prompt-free라는 서로 다른 open prompt 메커니즘을 단일 모델에서 detection·segmentation과 함께 실시간으로 지원하는 것.
- 다루는 범위: RepRTA, SAVPE, LRPC 세 모듈의 설계, LVIS/COCO 등에서의 zero-shot·closed-set 성능과 학습·추론 효율 비교.

## 3. 핵심 개념 상세
### 통합 Detection-Segmentation 모델
- 원문 표현: "YOLOE, which integrates detection and segmentation across diverse open prompt mechanisms within a single highly efficient model, achieving real-time seeing anything."
- 정의: 서로 다른 open prompt 메커니즘(텍스트/비주얼/프롬프트 없음)에서 모두 동작하는 detection과 segmentation을 하나의 모델로 통합한 구조.
- 역할: 대상 카테고리를 텍스트로 알 수 있는지, 예시 이미지만 있는지, 아무 사전 정보도 없는지에 따라 별도 모델을 두지 않고 하나의 효율적인 모델로 대응할 수 있게 한다.

### RepRTA (Re-parameterizable Region-Text Alignment)
- 원문 표현: "It refines pretrained textual embeddings via a re-parameterizable lightweight auxiliary network and enhances visual-textual alignment with zero inference and transferring overhead."
- 정의: 사전학습된 텍스트 임베딩을 re-parameterizable한 경량 auxiliary network로 정제해 visual-textual alignment를 향상시키는 텍스트 프롬프트 처리 모듈.
- 역할: 학습 시에는 auxiliary network로 텍스트 임베딩 품질을 높이면서, 추론·전이 시에는 re-parameterization을 통해 추가 연산 오버헤드 없이 정렬된 임베딩을 사용할 수 있게 한다.

### SAVPE (Semantic-Activated Visual Prompt Encoder)
- 원문 표현: "It employs decoupled semantic and activation branches to bring improved visual embedding and accuracy with minimal complexity."
- 정의: 의미(semantic) 정보를 다루는 branch와 활성화(activation) 정보를 다루는 branch를 분리해 시각적 예시(visual prompt)로부터 임베딩을 얻는 인코더.
- 역할: 예시 이미지의 영역만으로 대상을 지정해야 하는 visual prompt 상황에서, 최소한의 추가 복잡도로 정확한 visual embedding을 제공한다.

### LRPC (Lazy Region-Prompt Contrast)
- 원문 표현: "Lazy Region-Prompt Contrast (LRPC) strategy. It lazily retrieves category names from a built-in large vocabulary for anchor points with objects in the cost-effective way."
- 정의: 텍스트나 예시 프롬프트가 전혀 주어지지 않는 prompt-free 상황을 retrieval 문제로 재정의해("we reformulate such setting as a retrieval problem"), 내장된 대규모 vocabulary에서 물체가 있는 anchor point에 대해서만 카테고리 이름을 지연 검색(lazy retrieve)하는 전략.
- 역할: 비용이 큰 언어모델 의존("costly language model dependency") 없이 이미지 내 모든 객체에 이름을 붙이는 prompt-free 탐지를 가능하게 한다.

## 4. 구조 및 흐름
1. 입력 이미지가 YOLO 계열 backbone/neck을 통과해 region feature를 추출한다.
2. Text prompt가 주어지면 RepRTA가 사전학습 텍스트 임베딩을 정제해 region feature와의 alignment를 높인다.
3. Visual prompt(예시 박스)가 주어지면 SAVPE가 semantic/activation branch를 통해 예시로부터 visual embedding을 인코딩한다.
4. 프롬프트가 전혀 없으면 LRPC가 내장 vocabulary를 이용해 anchor point별로 카테고리 이름을 지연 검색한다.
5. 세 경로 중 어느 경로로 얻은 임베딩이든 공통 detection+segmentation head에서 box·mask·클래스를 함께 예측한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 세 가지 open prompt 방식을 하나의 효율적 모델로 통합할 수 있다 | "YOLOE excels in detection and segmentation across diverse open prompt mechanisms within one model, enjoying high inference efficiency and low training cost." |
| LVIS zero-shot에서 기존 open-vocabulary detector보다 우수하다 | "YOLOE-v8-S significantly outperforms YOLO-Worldv2-S by 3.5 AP on LVIS, with 1.4× and 1.3× inference speedups on T4 and iPhone 12" — 학습 비용은 3배 적음 |
| closed-set YOLO 대비 학습 효율이 뛰어나다 | YOLOE-v8-L이 closed-set YOLOv8-L 대비 AP^b +0.6, AP^m +0.4를 약 4배 적은 학습 시간으로 달성 |
| LRPC가 비용이 큰 언어모델 의존 없이 prompt-free 탐지를 가능하게 한다 | prompt-free 상황을 retrieval 문제로 재정의하고 "avoiding costly language model dependency" |

## 6. 한계 및 부족한 점
- ICCV 2025 공식 페이지(openaccess.thecvf.com)는 접근이 차단되어(HTTP 403) arXiv/ar5iv 렌더링본을 기준으로 확인했다.
- 확인한 범위(ar5iv 본문)에서는 명시적인 "Limitations" 절이 별도로 존재하지 않으며, "For rare category which is challenging, our YOLOE-v8-S and YOLOE-v8-L obtains significant improvements"처럼 개선을 강조하는 문장 정도로만 어려움이 언급되어, 실패 사례에 대한 구체적 분석은 확인되지 않는다.
- Ultralytics 공식 문서 기준으로는 대규모 프롬프트 집합을 쓸 때 지연시간이 약 19~89% 증가할 수 있고, "damaged", "left-most"처럼 관계에 의존하는 프롬프트는 매칭이 불안정하다는 한계가 별도로 보고된다.

## 7. 원문 기반 핵심 문장
> "In this work, we introduce YOLOE, which integrates detection and segmentation across diverse open prompt mechanisms within a single highly efficient model, achieving real-time seeing anything."
