# Parameterized Prompt for Incremental Object Detection

## 메타데이터
- categories: Prompts Pool Confusion, Parameterized Prompt Structure, Parameterized Prompt Fusion
- domain: [[지속학습]], [[객체 탐지·분할]]
- source: An, Zijia, Diao, Boyu, Liu, Ruiqi, Huang, Libo, Yang, Chuanguang, Wang, Fei, An, Zhulin, Xu, Yongjun, "Parameterized Prompt for Incremental Object Detection", CVPR, 2026.
- url: https://openaccess.thecvf.com/content/CVPR2026/html/An_Parameterized_Prompt_for_Incremental_Object_Detection_CVPR_2026_paper.html
- year: 2026
- authors: Zijia An, Boyu Diao, Ruiqi Liu, Libo Huang, Chuanguang Yang, Fei Wang, Zhulin An, Yongjun Xu (Institute of Computing Technology, Chinese Academy of Sciences / University of Chinese Academy of Sciences)
- venue: CVPR 2026 (accepted; also on arXiv as 2510.27316, first submitted 2025-10-31, latest v4 2026-03-13)

## 1. 핵심 요약
- Incremental object detection(IOD)에 프롬프트 풀(prompts pool) 기반 continual learning 기법을 그대로 적용하면, 탐지 데이터 특유의 co-occurrence 현상(신규 task 이미지 안에 이전 task의 미분류 객체가 라벨 없이 함께 등장하는 것) 때문에 "prompts pool confusion"이라는 고유 문제가 생긴다는 점을 지적한다.
- 저자들은 프롬프트 풀을 아예 없애고, 파라미터화된 신경망(MLP bottleneck)을 프롬프트 구조 자체로 사용하는 Parameterized Prompts for Incremental Object Detection(P²IOD)을 제안하며, task 간 파라미터를 크기(magnitude)·부호(sign) 기준으로 선택적으로 보존·평균화하는 parameterized prompt fusion으로 catastrophic forgetting을 억제한다.
- Deformable-DETR(MS COCO 사전학습)과 Co-DETR(Objects365 사전학습)이라는 서로 다른 프레임워크에 각각 방법을 이식해 PASCAL VOC2007과 MS COCO의 단일/다단계 class-incremental 설정에서 검증했고, 공식 GitHub 저장소(EMLS-ICTCAS/P2IOD)도 이 두 프레임워크에 대응하는 두 개의 독립된 코드베이스(P2IOD-MSCOCO-pretrained, P2IOD-objects365-pretrained)로 구성되어 있다.

## 2. 문서 목적
- 해결하려는 문제: L2P·DualPrompt류의 프롬프트 풀 기반 continual learning 방법은 incremental task마다 배타적인(disjoint) 클래스 집합을 가정하지만, object detection에서는 새 task 이미지 안에 이전 task의 객체가 라벨 없이 함께 나타나는 co-occurrence가 상시적으로 발생한다. 이 상황에서 프롬프트 풀은 (i) 한 객체가 여러 task-specific 프롬프트와 모두 높은 유사도를 보여 가장 적합한 프롬프트를 고르지 못하는 matching confusion과, (ii) 특정 task용 프롬프트가 다른 task의 잠재 지식까지 흡수해 표현이 흐려지는 task confusion을 동시에 겪는다.
- 기술적 목표: 프롬프트 지식을 task별로 격리 보존하는 대신, task를 거치며 지식을 전체적으로(holistically) 통합하면서도 갱신을 제약해 confusion과 forgetting을 동시에 막는 프롬프트 구조(파라미터화된 MLP)와 그 갱신 규칙(parameterized prompt fusion)을 설계하는 것.
- 다루는 범위: Deformable-DETR와 Co-DETR의 decoder multi-head attention에 프롬프트를 통합하는 구조, MD-DETR[2](Gaurav et al., prompts-pool 기반 선행연구)과 동일한 pseudo-labeling 기법을 이용한 co-occurring 객체 마이닝, PASCAL VOC2007(19+1/15+5/10+10 단일단계, 10+5+5/5+5+5+5 다단계)과 MS COCO(40+20+20, 40+10+10+10+10 다단계) class-incremental 벤치마크에서의 평가.

## 3. 핵심 개념 상세
### Prompts Pool Confusion (Matching / Task Confusion)
- 원문 표현: "In co-occurring scenarios, unlabeled objects from previous tasks may appear in current task images, leading to confusion in prompts pool." / "since the object appears across all tasks, they exhibit high similarity with all task-specific prompts, making it impractical to match the most relevant prompt." / "The unlabeled previous objects in co-occurring scenarios provide latent knowledge, causing the prompts learned for the current task to incorporate knowledge from all previous tasks, which undermines the clarity of the prompt's representation."
- 정의: 프롬프트 풀 방식(예: L2P, DualPrompt, MD-DETR)이 task마다 독립적인 프롬프트를 학습·매칭하는 것을 전제로 하는데, 탐지 이미지 특유의 co-occurrence 때문에 (1) 동일 객체가 여러 task 프롬프트와 모두 높은 유사도를 가져 최적 프롬프트 선택이 무너지는 matching confusion과, (2) 특정 task 프롬프트가 다른 task 지식까지 학습해 표현이 흐려지는 task confusion이 함께 발생하는 현상. 논문은 이 둘을 묶어 "prompts pool confusion"이라 명명한다.
- 역할: 이 논문이 최초로 정식화한 문제로(저자들 스스로 "the first work to investigate the prompts pool confusion caused by the co-occurrence phenomenon"라고 명시), 이후 제안하는 구조 설계 전체의 동기가 된다. arXiv v1 제목이 "Overcoming Prompts Pool Confusion via Parameterized Prompt for Incremental Object Detection"이었던 데서도 이 문제가 핵심 기여임을 확인할 수 있다.

### Parameterized Prompt Structure
- 원문 표현: "P²IOD redesigns the prompts pool as a parameterized prompt, so as to leverage the adaptive consolidation property inherent in neural networks, which naturally update learned knowledge in response to losses from co-occurring objects."
- 정의: 프롬프트 풀 대신, 동결된 사전학습 탐지기로부터 얻은 proposal(객체+배경 정보 모두 포함, 기존 MD-DETR은 객체 proposal만 사용)을 평균한 뒤 두 개의 FFN으로 구성된 MLP bottleneck에 통과시켜 인스턴스별 프롬프트 `p = ReLU(Q(x,θ*)·W⁽¹⁾)·W⁽²⁾`를 생성하는 구조. decoder의 각 층 self-attention에 독립적인 파라미터화된 프롬프트를 concat 방식으로 삽입한다.
- 역할: task별 프롬프트를 별도 슬롯에 격리 저장하지 않고 하나의 신경망 파라미터 공간에 지식을 인코딩함으로써, 새 task의 손실 신호에 따라 지식이 자연스럽게(task-isolated가 아니라 holistic하게) 갱신되도록 한다. 배경 proposal까지 압축에 포함시킨 것이 foreground/background 구분에 도움이 된다고 보고한다(반대로 MD-DETR은 배경 query를 추가하면 성능이 떨어짐을 원 논문이 보였다고 인용).

### Parameterized Prompt Fusion
- 원문 표현: "For Tt (t≥2), the parameterized prompt used for testing is θ_t^f, which is obtained by fusing θ_t and θ_{t-1}^f ... We fuse θt and θ_{t-1}^f based on the degree of parameter variation ... we decompose the task vector vt into a magnitude vector μt and a sign vector γt."
- 정의: 매 incremental task 학습 후 현재 파라미터 θt와 이전 융합 결과 θ_{t-1}^f의 차이(task vector) vt = θt − θ_{t-1}^f 를 크기 μt = |vt|와 부호 γt = sgn(vt)로 분해한 뒤, (i) μ_{t-1}^f 상위 top-l%와 μt 상위 top-k% 인덱스의 파라미터는 우선 보존, (ii) 부호가 이전과 일치하는 나머지 파라미터는 두 값을 평균, (iii) 그 외는 이전 값을 유지하는 4단계 규칙(수식 (8))으로 파라미터를 통합하는 전략. 여기에 파라미터 중요도를 소수 부분집합에 집중시키는 L1 sparse loss(λΣ|θj|)를 추가로 결합한다.
- 역할: 프롬프트 구조가 신경망이기 때문에 발생할 수 있는 catastrophic forgetting(파라미터화 구조만 도입했을 때 VOC 5+5+5+5 설정에서 구 클래스 AP50이 73.3→70.7로 하락함을 ablation에서 확인)을 억제하고, 중요·일관 파라미터만 선택적으로 보존·병합해 안정성(stability)과 가소성(plasticity)의 균형을 맞춘다.

## 4. 구조 및 흐름
1. 매 incremental task Tt의 이미지가 들어오면, 동결된 사전학습 탐지기(Deformable-DETR 또는 Co-DETR)가 만든 proposal을 평균해 쿼리 Q(x,θ*)를 얻고, 파라미터화된 MLP bottleneck이 이를 인스턴스별 프롬프트 p로 변환해 decoder self-attention에 주입한다.
2. 동시에 이전 task(T1…T_{t-1})로 학습된 탐지기가 현재 task 이미지의 배경에 있는 미분류 객체를 pseudo-label로 마이닝해(MD-DETR과 동일한 방식) 학습 신호에 포함시킴으로써 co-occurring 객체의 잠재 지식을 명시적으로 활용한다.
3. Task 학습이 끝나면 parameterized prompt fusion이 현재 파라미터 θt와 이전 융합 결과 θ_{t-1}^f 사이의 task vector를 크기·부호로 분해해 중요 파라미터를 보존하고 일관된 파라미터를 평균해 θ_t^f를 산출하며, 이 과정에 sparse loss로 파라미터 중요도를 특정 부분집합에 집중시킨다.
4. 이렇게 융합된 θ_t^f가 다음 task T_{t+1}의 시작점이 되어 1~3을 반복하고, 최종적으로 PASCAL VOC2007(단일/다단계)과 MS COCO(다단계) class-incremental 벤치마크에서 클래스 그룹별 AP50으로 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| P²IOD가 co-occurrence가 심해질수록(19+1→15+5→10+10) 프롬프트 풀 기반 MD-DETR 대비 우위가 커진다 | PASCAL VOC 단일단계(Table 1, AP50): Deformable-DETR(MS COCO) 기준 19+1 76.1→77.7(+1.6), 15+5 76.9→79.2(+2.3), 10+10 73.2→81.2(+8.0); Co-DETR(Objects365) 기준에서도 19+1/15+5/10+10 전 구간에서 P²IOD가 MD-DETR을 상회 |
| 다단계(multi-step) incremental에서 task 수가 늘어도 MD-DETR처럼 급격히 성능이 떨어지지 않는다 | VOC 10+5+5/5+5+5+5(Table 4, Co-DETR)에서 MD-DETR 89.1/86.4 대비 P²IOD 89.1/87.1(1-20 AP50); MS COCO 40+20+20/40+10+10+10+10(Table 2, Co-DETR)에서 마지막 task 기준 MD-DETR 60.3/49.4 대비 P²IOD 68.8/64.8 |
| 파라미터화 구조 단독으로는 가소성은 늘지만 forgetting이 여전히 존재하고, model fusion이 이를 완화한다 | VOC 5+5+5+5 ablation(Table 3): pseudo-labeling만 있을 때 구클래스(1-5) AP50 73.3 → parameterized prompt structure 추가 시 70.7로 하락(가소성은 6-20에서 64.6→76.6로 상승); model fusion 추가 시 구클래스가 73.1로 회복 |
| 전체 구성요소(pseudo-labeling+구조+fusion+sparse loss)를 모두 결합하면 stability와 plasticity를 함께 개선한다 | 동일 ablation에서 전체 결합 시 1-5/6-20/1-20 = 74.0/77.2/76.4로, pseudo-labeling만 사용한 baseline(73.3/64.6/66.8) 대비 전체 정확도 9.0%p 상승 |
| Confusion 완화가 정성적으로도 관찰된다 | Fig.5의 MMD 기반 A-MMD 지표에서 P²IOD의 프롬프트 다양성이 decoder 층이 깊어질수록 증가하고 MD-DETR보다 최종층에서 유의하게 높음; Fig.3 시각화에서 MD-DETR은 task가 진행될수록 confidence가 급락하고 false positive가 늘어나는 반면 P²IOD는 confidence가 거의 유지됨 |

## 6. 한계 및 부족한 점
- pypdf로 arXiv v3/v4 전문(15페이지 PDF)과 CVF openaccess 페이지(HTTP 200 확인)를 직접 확인했다. arXiv 메타데이터는 여전히 "arXiv preprint, 2025"로 표기되어 있지만, 논문 1페이지 각주에 "Accepted in Conference on Computer Vision and Pattern Recognition, 2026 (CVPR'26)"이라고 명시되어 있고 CVF openaccess의 CVPR2026 논문 목록에도 An_Parameterized_Prompt_for_Incremental_Object_Detection_CVPR_2026_paper.{html,pdf}와 supplemental 자료가 실제로 존재함을 확인했으므로, CVPR 2026 정식 채택·게재는 사실로 확인된다.
- "Deformable-DETR 기반 구현과 Co-DETR 기반 구현 두 개"라는 주장은 정확하다. 공식 저장소 README가 "Since the training frameworks of these two models differ, we implement our method separately in two distinct codebases"라고 명시하며, 실제로 P2IOD-MSCOCO-pretrained(Deformable-DETR, MS COCO 사전학습)와 P2IOD-objects365-pretrained(Co-DETR, Objects365 사전학습) 두 디렉터리로 구성되어 있음을 GitHub API로 직접 확인했다. 다만 이는 별도 브랜치가 아니라 같은 main 브랜치 안의 두 하위 폴더(각자 자체 README 포함) 형태다.
- 이 프로젝트가 참고하는 DGS([[dgs]])와는 catastrophic forgetting을 다루는 초점이 다르다. DGS는 GroundingDINO 기반 cross-domain/task-incremental(CDIOD, ODinW-13, COCO 클래스 증분)에서 adapter 그룹화·통합으로 forgetting을 억제하는 반면, P²IOD는 Deformable-DETR/Co-DETR 기반 class-incremental(VOC, COCO)에서 프롬프트 구조 자체의 confusion을 원인으로 지목한다. 벤치마크 분할과 backbone이 서로 달라(GroundingDINO vs Deformable-DETR/Co-DETR, 사전학습 데이터도 상이) 두 논문의 AP·forgetting 수치를 직접 비교할 근거는 없으며, 원문에도 DGS 또는 유사 adapter-consolidation 계열 방법과의 직접 비교표는 없다.
- 논문은 "forgetting"을 별도의 단일 수치 지표(예: average forgetting)로 정의해 보고하지 않고, 구/신 클래스 그룹별 AP50(예: VOC의 "1-19" vs "20", "1-5" vs "6-20")의 상대적 변화로 stability/plasticity를 간접적으로만 나타낸다. 또한 19+1/15+5/10+10 표에는 "과대추정(overestimated)" 가능성이 있는 수치에 `*` 표시를 별도로 달아두었는데, 그 구체적 산정 사유는 §5.1 본문에서 "전체 test set 검증 대신 task별 test subset 검증을 쓰면 더 높은 정밀도가 나온다"는 일반적 설명만 확인되고 각 `*` 수치별 정량적 보정값은 명시되어 있지 않다.
- MS COCO에서의 단일단계(40+40, 70+10) 결과는 본문 Table에는 없고 "Appendix B.1"에 있다고 본문이 언급하나, 이번 확인 범위(arXiv 본문 1~9페이지)에서는 부록 원문을 직접 읽지 못해 그 수치는 확인하지 못했다.

## 7. 원문 기반 핵심 문장
> "We observe that the prompts pool exhibits confusion when incorporating the knowledge of the static object distribution in co-occurring scenarios, leading to a negative impact on performance... We refer to the matching and task confusion introduced by the prompts pool in IOD as prompts pool confusion, which negatively affects IOD's performance."
