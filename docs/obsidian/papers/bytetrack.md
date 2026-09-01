# ByteTrack: Multi-Object Tracking by Associating Every Detection Box

## 메타데이터
- categories: [[BYTE 연관 알고리즘]], [[ByteTrack 파이프라인]], [[Low-score Detection Box 복구]], [[Kalman Filter 기반 모션 예측]]
- domain: [[Multi-Object Tracking]], [[Computer Vision]]
- source: Zhang, Yifu, Sun, Peize, Jiang, Yi, Yu, Dongdong, Weng, Fucheng, Yuan, Zehuan, Luo, Ping, Liu, Wenyu, Wang, Xinggang. "ByteTrack: Multi-Object Tracking by Associating Every Detection Box." Proceedings of the European Conference on Computer Vision (ECCV), 2022.
- url: https://arxiv.org/abs/2110.06864
- year: 2022
- authors: Zhang et al.
- venue: European Conference on Computer Vision (ECCV)

## 1. 핵심 요약
- 대부분의 Multi-Object Tracking(MOT) 방법은 threshold보다 점수가 높은 detection box만 사용해 identity를 연관시키고, occlusion 등으로 점수가 낮은 detection box는 그냥 버려서 true object missing과 fragmented trajectory를 유발한다.
- 이 논문은 거의 모든 detection box를 연관에 활용하는 간단하고 효과적이며 범용적인 연관 방법인 BYTE를 제안한다. 낮은 점수의 detection box는 tracklet과의 유사도를 이용해 실제 객체를 복구하고 배경 detection은 걸러낸다.
- BYTE를 9개의 서로 다른 state-of-the-art tracker에 적용했을 때 IDF1 score가 1점에서 10점까지 일관되게 향상되었다.
- BYTE와 YOLOX 검출기를 결합한 강력한 tracker인 ByteTrack을 설계했으며, MOT17 test set에서 단일 V100 GPU 기준 30 FPS로 80.3 MOTA, 77.3 IDF1, 63.1 HOTA를 달성했다. MOT20, HiEve, BDD100K 트래킹 벤치마크에서도 state-of-the-art 성능을 보였다.

## 2. 문서 목적
- 해결하려는 문제: 기존 MOT 방법이 낮은 confidence score의 detection box(occluded object, motion blur 등)를 threshold로 걸러내면서 true object가 소실되고 trajectory가 끊기는 문제.
- 기술적 목표: 특정 tracker 구조에 종속되지 않는 범용 연관(association) 방법을 제안해, 높은 점수와 낮은 점수의 detection box를 모두 활용함으로써 tracking 정확도와 identity 일관성을 높이는 것.
- 다루는 범위: BYTE 연관 알고리즘 자체의 설계, 9개 기존 tracker에 대한 plug-in 적용 실험, YOLOX 기반 ByteTrack tracker 설계, MOT17/MOT20/HiEve/BDD100K 벤치마크 평가.

## 3. 핵심 개념 상세
### BYTE 연관 알고리즘
- 원문 표현: "we present a simple, effective and generic association method, tracking by associating almost every detection box instead of only the high score ones."
- 정의: detection box를 점수에 따라 high score와 low score로 나눈 뒤, 먼저 high score box를 tracklet과 매칭하고, 매칭되지 않은 tracklet을 다시 low score box와 매칭하는 2단계 연관 방법.
- 역할: 특정 tracker의 핵심 로직을 바꾸지 않고도 기존 tracker에 삽입 가능한 범용 모듈로서, occlusion·motion blur로 점수가 낮아진 실제 객체를 배경 detection과 구분해 복구한다.

### ByteTrack 파이프라인
- 원문 표현: "we design a simple and strong tracker, named ByteTrack."
- 정의: YOLOX detector로 얻은 detection box에 BYTE 연관 알고리즘을 적용한 tracker.
- 역할: MOT17 test set에서 30 FPS(단일 V100 GPU)로 80.3 MOTA, 77.3 IDF1, 63.1 HOTA를 달성하며, MOT20·HiEve·BDD100K에서도 state-of-the-art 성능을 보이는 실제 구현체 역할을 한다.

### Low-score Detection Box 복구
- 원문 표현: "For the low score detection boxes, we utilize their similarities with tracklets to recover true objects and filter out the background detections."
- 정의: 낮은 confidence score를 가진 detection box를 즉시 폐기하지 않고, unmatched tracklet과의 유사도를 계산해 실제 객체 여부를 판단하는 절차.
- 역할: occluded object처럼 detection score가 낮아진 true object의 fragmented trajectory와 missing을 줄이면서, 동시에 유사도가 낮은 background detection은 걸러낸다.

### Kalman Filter 기반 모션 예측
- 원문 표현: "adopt Kalman filter to predict the location of the tracklets in the new frame"
- 정의: 이전 프레임까지의 tracklet 상태를 이용해 다음 프레임에서의 위치를 예측하는 모션 모델.
- 역할: 예측된 위치와 실제 detection box 간의 motion similarity를 계산해 high score/low score 매칭 단계 모두에서 연관 기준으로 사용된다. 특히 low score box와의 2차 매칭에서는 severe occlusion·motion blur 상황 때문에 IoU 기반 similarity가 중요하다고 명시되어 있다.

## 4. 구조 및 흐름
1. 매 프레임마다 detector(예: YOLOX)로 detection box를 얻고, 이를 threshold τ 기준으로 high score box와 low score box로 분리한다.
2. Kalman filter로 기존 tracklet의 다음 프레임 위치를 예측한다.
3. 1차 매칭: high score detection box를 모든 tracklet과 motion similarity 또는 appearance similarity 기반으로 매칭한다(Hungarian Algorithm 사용).
4. 2차 매칭: 1차에서 매칭되지 않은 tracklet을 low score detection box와 IoU 기반 similarity로 매칭해, occlusion 등으로 점수가 낮아진 실제 객체를 복구한다.
5. 최종적으로 두 단계 매칭에도 남은 unmatched tracklet과 unmatched detection box를 각각 처리하여 tracklet 종료 또는 새 tracklet 생성에 활용한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| low score detection box를 버리지 않고 활용하면 tracking 성능이 향상된다 | BYTE를 9개의 서로 다른 state-of-the-art tracker에 적용한 결과 IDF1 score가 1~10점 일관되게 향상됨 |
| BYTE와 YOLOX를 결합한 ByteTrack이 강력한 성능을 낸다 | MOT17 test set에서 30 FPS로 80.3 MOTA, 77.3 IDF1, 63.1 HOTA 달성(단일 V100 GPU), MOT20/HiEve/BDD100K에서도 state-of-the-art 성능 |
| low score box와의 2차 매칭에는 Re-ID 기반 appearance similarity보다 IoU 기반 similarity가 더 중요하다 | "it is important to utilize IoU as Similarity#2 in the second association on both datasets because the low score detection boxes usually contains severe occlusion or motion blur" |

## 6. 한계 및 부족한 점
- ar5iv 전문 확인 결과, 논문 본문은 occlusion, motion blur, size changing과 같은 실패 상황을 언급하지만 이에 대한 상세한 failure case 분석은 제한적으로만 제공한다.
- low score detection box와의 2차 매칭에서 Re-ID 기반 appearance feature가 occluded object에 대해 신뢰도가 떨어져 IoU 기반 매칭만 사용해야 하는 제약이 있다.
- 확인한 범위(arXiv abstract, ar5iv 본문 일부, GitHub README) 내에서는 future work나 미해결 문제에 대한 별도의 명시적 논의는 확인되지 않음.

## 7. 원문 기반 핵심 문장
> "Most methods obtain identities by associating detection boxes whose scores are higher than a threshold. The objects with low detection scores, e.g. occluded objects, are simply thrown away, which brings non-negligible true object missing and fragmented trajectories."
