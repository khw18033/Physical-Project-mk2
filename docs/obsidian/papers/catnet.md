# CATNet: Collaborative Alignment and Transformation Network for Cooperative Perception

## 메타데이터
- categories: 비동기 특징 동기화(STSync), Wavelet 기반 다중 노이즈 억제(WTDen), 적응형 유효 특징 선택(AdpSel), V2X 협력 인지
- domain: [[협력 인지]]
- source: Chen, Gong, Zhang, Chaokun, Tang, Tao, Lv, Pengcheng, Li, Feng, Xie, Xin. "CATNet: Collaborative Alignment and Transformation Network for Cooperative Perception." CVPR 2026 (accepted; arXiv comment field explicitly states "Accepted by CVPR26").
- url: https://arxiv.org/abs/2603.05255 (PDF: https://arxiv.org/pdf/2603.05255)
- year: 2026
- authors: Gong Chen¹, Chaokun Zhang²(교신저자), Tao Tang¹, Pengcheng Lv³, Feng Li¹, Xin Xie¹ — ¹School of Computer Science and Technology, Tianjin University; ²School of Cybersecurity, Tianjin University; ³School of Future Technology, Tianjin University
- venue: CVPR 2026 (Denver, Colorado, 2026-06-03~07) — arXiv 메타데이터의 `comment` 필드가 "Accepted by CVPR26"로 명시. 교신저자 Chaokun Zhang의 톈진대 소속 페이지(https://cic.tju.edu.cn/faculty/zhangchaokun/index.html)에도 동일 서지정보로 게재 확인.

## 1. 핵심 요약
- 협력 인지(cooperative perception)는 다중 에이전트 정보를 융합해 단일 에이전트의 시야 제한과 가림(occlusion) 문제를 완화하지만, 실제 환경의 통신 지연(latency)과 다중 소스 노이즈는 기존 연구에서 충분히 다뤄지지 않았다.
- CATNet은 세 모듈을 순차 결합한 적응형 보상 프레임워크다: (1) STSync가 비동기 특징 스트림을 시공간적으로 정렬하고, (2) WTDen이 신호 레벨의 전역·국소 왜곡을 웨이블릿 도메인에서 제거하며, (3) AdpSel이 의미 레벨에서 유효 영역을 선택해 최종 융합을 정제한다.
- OPV2V/V2XSet/DAIR-V2X 세 벤치마크에서 PointPillar 백본 기준 AP@0.5/AP@0.7을 각각 기존 2위 모델 대비 1.2%/0.7%(OPV2V), 4.1%/1.9%(V2XSet), 2.1%/0.6%(DAIR-V2X) 초과 달성했고, 노이즈·지연 조건에서 단일 에이전트 baseline 대비 최대 16.0%/12.7% 개선(V2XSet 기준)을 보고한다.
- 공식 코드 저장소는 확인되지 않는다(GitHub API 검색·PapersWithCode/HuggingFace Papers 색인·저자 소속 페이지 모두에서 링크 없음) — **원문 확인 안 됨** 항목으로 명시.

## 2. 문서 목적
- 해결하려는 문제: 실제 V2X 통신에서 발생하는 시변(time-varying) 지연으로 인한 에이전트 간 특징 시공간 불일치, 그리고 통신·센서·모델 파라미터 편차에서 비롯되는 다중 소스 노이즈가 결합될 때 기존 협력 인지 방법(기하 기반 정합, 고정 임계값 디노이징, 국소 시간 정렬)이 겪는 성능 저하 문제.
- 기술적 목표: 지연 보상(시공간 정렬)과 노이즈 정화(신호 레벨 + 의미 레벨)를 하나의 파이프라인으로 통합해, 비동기·노이즈 조건에서도 강건한 중간 융합(intermediate fusion) 협력 인지를 달성하는 것.
- 다루는 범위: STSync/WTDen/AdpSel 세 모듈의 설계, OPV2V·V2XSet·DAIR-V2X에서의 정량 비교, 인위적 지연·노이즈·패킷 손실 주입 실험을 통한 강건성 분석.

## 3. 핵심 개념 상세

### STSync (Spatio-Temporal Recurrent Synchronization)
- 원문 표현: "we introduce a Spatio-Temporal Recurrent Synchronization (STSync) that aligns asynchronous feature streams via adjacent-frame differential modeling, establishing a temporal-spatially unified representation space." / "It establishes a global temporal context by recurrently propagating the ego-vehicle's features to iteratively align asynchronous data streams."
- 실제 메커니즘(재료 요청 (b) 확인): 다중 에이전트에서 지연 수신된 특징을 max/avg pooling + 3D conv로 병합(`Integration`)한 뒤, ego 차량이 최근 K개의 융합 특징을 저장하는 버퍼를 유지한다. Time-Augmented Recurrent Unit(TARU)이 이 버퍼에 대해 순차적으로 (1) 인접 두 프레임으로 모션 오프셋 예측 → (2) deformable convolution으로 특징 워핑 → (3) Spatio-Temporal Gate(공간·채널 어텐션 병렬)로 이전 hidden state와 워핑된 특징을 적응적 가중합 → (4) hidden state 갱신을 반복한다. 최종 hidden state는 ego의 실시간 특징을 spatial prior로 사용하는 Deformable Cross-Attention으로 다시 한 번 보정되어 "시간적으로 예측되었지만 공간적으로는 ego 현재 상태에 고정된" 특징을 만든다.
- 요약하면 "비동기 특징 동기화"라는 개괄적 설명보다 구체적으로는, 순환(recurrent) 방식의 모션 예측+워핑+게이트 융합을 반복 적용하는 시간 보간/외삽 모듈이다.

### WTDen (Dual-Branch Wavelet Enhanced Denoiser)
- 원문 표현: "we design a Dual-Branch Wavelet Enhanced Denoiser (WTDen) module... corrects global distortions with a Wavelet Mamba and remedies local inconsistencies via Wavelet Convolution."
- 실제 메커니즘: STSync가 산출한 융합 특징을 2D Haar Wavelet Transform으로 4개 서브밴드(LL/LH/HL/HH)로 분해한 뒤, 두 개의 병렬 분기로 처리한다. (1) Wavelet Mamba 분기는 고주파→저주파 순서의 forward 통합 경로와 4개 서브밴드를 모두 스캔하는 interleaved 경로(및 각각의 역방향 경로)를 State Space Model(SSM)로 집계해 전역 공간 관계를 복원하고 Inverse Wavelet Transform으로 되돌린다. (2) Wavelet Convolution 분기는 4개 서브밴드를 concat한 뒤 conv+IWT를 계층적으로 두 번 적용해 국소 특징 왜곡을 보정한다. 두 분기의 출력을 합산해 최종 디노이즈 특징을 얻는다.
- 즉 "다중 소스 노이즈 억제"는 통계적 필터링이 아니라, 웨이블릿 도메인에서 전역 정합(Mamba 기반 장거리 관계 모델링)과 국소 정합(계층적 컨볼루션)을 분리해 각각 처리하는 이중 분기 구조로 구현된다.

### AdpSel (Adaptive Feature Selector)
- 원문 표현: "we construct an Adaptive Feature Selector (AdpSel) that dynamically focuses on critical perceptual features for robust fusion." / "By redefining saliency as a proxy for semantic coherence, AdpSel performs context-aware synthesis to selectively enhance coherent feature regions, thereby filtering out semantic noise."
- 실제 메커니즘: WTDen 출력을 여러 윈도우 스케일(S1..Sn)에 대해 반복 처리한다. 각 스케일에서 (1) 경량 선형 selector가 블록별 중요도 점수를 매겨 top-k%를 선택 블록/나머지를 비선택 블록으로 나누고(Coherence-Aware Block Selection), (2) 미세 스케일에서 버려진 저-중요도 영역의 마스크를 다음 상위 스케일의 마스크 갱신에 재사용하는 계층적 마스크 전파(Hierarchical Mask Refinement)를 수행하며, (3) 선택된 블록은 MLLA 모듈(비전용 선형 어텐션)로 문맥을 강화하고 비선택 블록은 경량 Inverted Bottleneck으로 보조 정보를 복원하는 이중 경로 처리 후 Aggregator로 스케일별 출력을 만들고, 전체 스케일 출력을 SplitAttention으로 최종 융합한다.
- 즉 "유효 특징 선택"은 단순 임계값 마스킹이 아니라, 다중 스케일에 걸친 반복적 top-k 선택 + 교차 스케일 마스크 전파 + 선택/비선택 블록에 대한 비대칭 처리(고비용 MLLA vs 경량 IB)로 구성된 의미 레벨 정화 단계다.

## 4. 구조 및 흐름
1. 각 에이전트(ego 포함)가 센서 데이터를 encoder로 인코딩해 특징 $F_i^t$를 생성한다.
2. 지연 $\tau$ 후 ego에 도착한 타 에이전트 특징은 좌표 변환 $\xi^{t-\tau}_{i\to ego}$을 거쳐 ego 좌표계로 정렬된다.
3. STSync: 정렬된 특징들을 Integration(max/avg pooling + 3D conv)으로 1차 병합 → 버퍼에 누적 → TARU가 모션 예측·워핑·게이트 융합을 반복 → ego 실시간 특징으로 Deformable Cross-Attention 보정 → 시공간 정합 특징 산출.
4. WTDen: STSync 출력을 Haar wavelet으로 분해 → Wavelet Mamba(전역) + Wavelet Convolution(국소) 병렬 처리 → 두 분기 합산으로 디노이즈 특징 산출.
5. AdpSel: 디노이즈 특징을 다중 스케일에서 반복적으로 블록 선택(top-k%) → 계층적 마스크 전파 → 선택 블록은 MLLA, 비선택 블록은 Inverted Bottleneck으로 처리 → Aggregator·SplitAttention으로 최종 특징 $F_{out}$ 산출.
6. Decoder가 최종 특징으로부터 검출 결과(Detecting Head)를 생성하고, PointPillar 백본과 AP@0.5/0.7(IoU 기준)로 평가한다.
7. 평가는 OPV2V(V2V), V2XSet(V2X, 저자 표현으로는 첫 vehicle-to-infrastructure 데이터셋), DAIR-V2X(실세계) 세 데이터셋에서 이뤄지며, heading/위치 노이즈 주입, 지연(0~500ms) 주입, 과거 프레임 패킷 손실(최대 4프레임/600ms) 등 강건성 실험을 포함한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| CATNet은 3개 데이터셋에서 기존 2위 방법 대비 일관되게 우수하다 | Table 1: OPV2V AP@0.5/0.7 = 0.843/0.686 (2위 대비 +1.2%/+0.7%), V2XSet = 0.858/0.643 (+4.1%/+1.9%), DAIR-V2X = 0.723/0.565 (+2.1%/+0.6%); 파라미터 수는 9.95M으로 비교군 중 최소~준최소 수준(DSRC 40.64M, MRCNet 19.71M 대비 경량) |
| STSync가 성능 향상의 주된 기여자다 | Table 3 ablation: baseline(0.595/0.384, OPV2V) 대비 STSync 단독 추가만으로 0.818/0.678로 AP@0.5 +22.3%p 상승(OPV2V), DAIR-V2X에서는 +2.4%p; WTDen·AdpSel 단독 추가는 이보다 작은 개선폭 |
| WTDen은 혼합 위치·헤딩 노이즈 조건에서 노이즈 강건 SOTA(Agent-graph, FeaCo, CoAlign, DSRC)를 능가한다 | Table 6: 노이즈 0.4/0.4 조건에서 CATNet 0.870/0.663 vs DSRC 0.854/0.638, CoAlign 0.848/0.633 |
| AdpSel의 고-중요도 블록 선택이 실제로 검출에 핵심적이다 | Table 5 (OPV2V, block masking): AdpSel 원본 0.897(AP@0.5) → 고-어텐션 영역 마스킹 시 0.364로 급락, 저-어텐션 영역 마스킹 시 0.784로 상대적으로 완만한 하락 |
| 극단적 노이즈·지연 조건에서도 성능 저하가 완만하다 | 노이즈 미보정 시 최대 AP@0.7 저하 7.98%(heading)/10.02%(위치)인 데 반해 CATNet은 0.6%만 저하(OPV2V); 지연 0~500ms 구간에서도 CATNet이 전 구간 1위 유지(Table 2: 0.756/0.624 @ 0-500ms, 2위 ERMVP 0.745/0.600) |

## 6. 한계 및 부족한 점
- **코드 공개 여부**: GitHub API 검색("CATNet cooperative perception", "CATNet STSync", "STSync WTDen AdpSel" 등 복수 쿼리), PapersWithCode(검색 결과가 Hugging Face Papers로 리다이렉트되며 해당 arXiv ID 페이지도 404), 교신저자 Chaokun Zhang의 톈진대 소속 페이지 어디에서도 공식 코드 저장소 링크를 찾지 못했다. **동료가 지적한 "공식 코드 저장소 없음"은 이번 조사에서도 재확인되었다** — 다만 이는 특정 시점 검색 결과이며, 추후 저자가 비공개로 코드를 릴리스했을 가능성을 완전히 배제하지는 못한다.
- **논문 접근 경로**: 사용자가 제시한 CVF openaccess 원본 URL(`openaccess.thecvf.com/.../Chen_CATNet_..._CVPR_2026_paper.html`)은 자동 접근 시 HTTP 403이 반환되어 직접 확인하지 못했다(봇 차단 가능성이 높으며 페이지 부재를 의미하지는 않음). 대신 arXiv 프리프린트(2603.05255, PDF 전체 9페이지)를 직접 읽어 본문 전체를 확인했고, arXiv 메타데이터의 `comment` 필드("Accepted by CVPR26")와 교신저자 소속 페이지의 게재 정보(CVPR 2026, Denver, 2026-06-03~07)로 venue를 교차 확인했다. CVF 페이지 자체의 최종 조판본(camera-ready) 내용이 arXiv v1과 다를 가능성은 남아 있다.
- **저자 소속·이해관계**: 참고문헌 [2],[3]이 동일 제1저자(Gong Chen)의 다른 미검증 프리프린트(CoRA, arXiv:2512.13191; CoopDiff, 2026)를 인용하고 있어, 동일 연구 그룹 내 자기인용 비중이 있다. 이것이 방법론의 타당성을 훼손하지는 않으나 독립적 검증 사례가 아직 외부에서 축적되지 않았음을 시사한다.
- **평가 범위**: 세 데이터셋 모두 차량 중심 LiDAR 포인트클라우드 협력 검출에 한정되며(PointPillar 백본 고정), 카메라 모달리티나 다른 백본에서의 일반화는 논문 범위에서 다뤄지지 않는다.
- **CORE 방법의 DAIR-V2X 결과는 Table 1에서 "–"(미보고)로 표시**되어 있어 해당 조합은 저자들도 측정하지 못했거나 보고하지 않은 것으로 보인다.
- **Ablation 표(Table 3)에 "+WTDen+AdpSel"(STSync 제외) 조합이 없다** — STSync를 제외한 두 정화 모듈만의 조합 효과는 원문에서 확인되지 않는다.

## 7. 원문 기반 핵심 문장
> "Using the V2XSet as an example, results demonstrate that our method achieves an average AP@0.5/AP@0.7 improvement of 5.7%/2.5% compared to the second-best approach, and outperforms the single-vehicle baseline by 16.0%/12.7% under noisy and latency scenarios."

> "This network first aligns asynchronous multi-vehicle features via a temporal recurrent module, then performs a comprehensive purification by first cleaning signal-level distortions and subsequently using semantic coherence to guide the final adaptive fusion."

> (arXiv 메타데이터) `<arxiv:comment>Accepted by CVPR26</arxiv:comment>` — venue 확인의 1차 근거.
