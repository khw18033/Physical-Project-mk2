# 시연 실행에서 논문 실험 데이터를 얻는 구성

시연(하천·기후·정찰)과 논문 실험을 별개 작업으로 두지 않는다. 시연을 한 번
돌리면 그 실행이 그대로 분석 가능한 run bundle로 남고, 오프라인에서 다른
방법과 동일 조건으로 비교할 수 있게 한다.

## 왜 이 구조인가

시연 현장에서만 발생하는 조건이 있다. 실제 링크 단절, 실제 발열로 인한 모델
축소, 노드 이탈이 그렇다. 합성 시나리오로 만들면 "인위적"이라는 반박을 받는
조건들이라, 시연 자체를 데이터 취득 기회로 쓰는 편이 논문의 설득력에 직접
기여한다.

## 경계

- 캡처는 **선택 기능**이다. `observability.experiment_capture`가 활성 목록에
  없으면 `NullRecorder`가 들어가고 아무 것도 기록하지 않는다. 캡처 실패는
  스스로를 비활성화할 뿐 기록 대상 기능을 멈추지 않는다(AI-C-05, AI-O-01).
- 기록은 **관측 평면**에만 놓인다. 업무 메시지에 섞지 않고, 영상 픽셀은 담지
  않으며 참조만 남긴다(AI-C-14, AI-C-08).
- 장치 생사·치명 오류·capability 전이는 수치 요약에 합산되지 않고 개별 항목으로
  보존된다(AI-O-01, AI-O-02).
- 도메인 분기는 없다. 하천·기후·정찰의 차이는 run header에 기록되는 프로파일
  뿐이다(AI-C-15).

## 채널

| 채널 | 내용 | 집계 |
|---|---|---|
| `evidence` | provider 결과(소스 그룹, 완료시각, 신뢰도, 영역·라벨) | 요약 가능 |
| `record` | 객체 레코드 개정본 | 요약 가능 |
| `resource` | 지연, RSS, CPU, 전력 | 요약 가능 |
| `capability` | ACTIVE/DEGRADED/DISABLED 전이와 사유 | **개별 보존** |
| `liveness` | 노드·장치 생사 | **개별 보존** |
| `fault` | 치명 오류 | **개별 보존** |

`capability` 채널이 논문의 가용성 스케줄 그 자체다. 시연에서 링크가 끊기면 그
전이가 사유와 함께 남고, 오프라인 하네스가 이를 읽어 동일 조건으로 여러 해석
규칙을 재실행한다.

## 시연 → 논문 경로

```text
시연 실행 (하천 / 기후 / 정찰 프로파일)
   ├─ evidence 채널   → 이종 모델 출력 스트림
   ├─ capability 채널 → 실측 가용성 스케줄 (링크 단절·발열 축소·노드 이탈)
   ├─ resource 채널   → RPi5 메모리·전력·지연
   └─ record 채널     → 레코드 개정 이력
                ↓  run bundle (실행 조건·버전 포함)
        승인된 protocol의 오프라인 replay evaluator
                ↓
   동일 evidence + 동일 스케줄 위에서 해석 규칙만 교체 비교
```

한 번의 시연이 네 개 방법의 비교 실험 입력이 된다. 조건이 동일하고 방법만
다르므로, 측정된 차이는 방법 차이만 반영한다.

## 사용

```python
from perception_framework.observability.experiment import ExperimentRecorder, NullRecorder, RunHeader
from perception_framework.contracts.profile_loader import load_profile, is_capability_active

profile = load_profile("profiles/river.json")
recorder = (ExperimentRecorder(RunHeader(run_id=run_id, domain_id=profile.domain_id,
                                         profile_id="river", versions={"rules": profile.rule_set_id}))
            if is_capability_active(profile, "observability.experiment_capture")
            else NullRecorder())

recorder.capture_evidence(evidence)
recorder.capture("capability", kind="perception.segment", state="DISABLED", reason="link_loss")
recorder.capture_resource(latency_ms=elapsed, rss_mib=rss)
recorder.write("reports/runs")
```
