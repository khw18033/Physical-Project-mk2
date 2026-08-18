# 조사 보고 — 그라파나에서 동적 데이터소스 조합·중첩이 가능한가

**조사 일시**: 2026-08-18
**출처**: 260818 회의록 §2 "조사 과제(현우)"
**결론**: **부분적으로 가능하나, 회의에서 요구한 형태는 구조적으로 불가능하다.**

---

## 1. 조사 질문의 분해

회의록의 "동적 데이터소스 조합·중첩"은 실제로 세 가지 서로 다른 요구를 한 문장에
담고 있다. 그라파나는 이 중 첫 번째만 충족한다.

| # | 요구 | 그라파나 |
|---|---|---|
| A | 한 화면에 여러 데이터소스의 데이터를 겹쳐 보기 | **가능** |
| B | 사용자가 런타임에 소스→변환→싱크를 노드로 이어 붙이기 | **불가** |
| C | 영상 등 비-시계열 미디어를 파이프라인 대상으로 다루기 | **불가** |

---

## 2. A — 다중 데이터소스 중첩: 가능

그라파나는 `-- Mixed --`라는 가상 데이터소스를 제공한다. 패널의 데이터소스로
Mixed를 선택하면 쿼리를 추가할 때마다 **쿼리별로 다른 데이터소스**를 지정할 수
있고, 결과를 한 패널에 겹쳐 그린다. 서로 다른 프레임을 하나로 합칠 때는
Transformations 탭의 `merge` / `join` 변환을 사용한다.

즉 "Prometheus의 수위와 다른 백엔드의 강우량을 한 그래프에" 같은 요구는 그라파나로
해결된다. **이 부분은 우리가 다시 만들 이유가 없다.**

### 다만 알려진 제약

| 제약 | 내용 |
|---|---|
| 기존 쿼리 전환 불가 | 이미 만든 쿼리를 Mixed로 바꿀 수 없다. 패널을 다시 만들어야 한다 — 동적 재구성에 불리하다. |
| 시각화별 지원 편차 | 시계열·테이블은 잘 동작하나 Stat 등 단일값 패널은 다중 쿼리 지원이 제한적이다. |
| 다차원 쿼리 결합 | 쿼리가 둘 이상의 시계열을 반환하면 "No Data"가 나오는 경우가 있고, 서로 다른 데이터소스의 쿼리를 하나의 Math 표현식에 넣는 것은 문제가 된다. |
| 프레임 병합 필요 | 다수의 시각화가 여러 데이터 프레임을 "한 번에 하나씩 골라 보기"로만 지원한다. 합치려면 transformation을 명시적으로 걸어야 한다. |

**Stat 패널의 다중 쿼리 제약**은 우리에게 특히 중요하다. 회의록 §2의 "최상위
결심자에게는 빨강/초록 두 색이면 충분"이 정확히 단일값 패널이고, 그 값은 여러
소스를 종합해 산출되어야 하기 때문이다. 그라파나가 가장 약한 지점이 우리
설계의 최상위 계층과 겹친다.

---

## 3. B — 런타임 노드 조합: 불가

여기가 결정적이다. 그라파나에 "노드"라는 이름이 붙은 것이 두 개 있는데 **둘 다
회의에서 말한 노드 에디터가 아니다.**

### 3.1 Node Graph 패널은 에디터가 아니다

Node Graph는 **관계를 그리는 시각화**다. 노드와 엣지를 화면에 표시할 뿐,
노드가 무언가를 실행하지 않는다. 사용자가 노드를 끌어다 연결해도 그것이 데이터
처리 경로가 되지 않는다. DearPyGui 데모의 "카메라 → Canny → 디텍션 → 저장"과는
범주가 다르다.

### 3.2 Transformations는 선형 체인이지 DAG가 아니다

변환은 순서대로 이어 붙이는 **파이프라인**이다. 분기(하나의 소스를 두 갈래로)나
합류(두 갈래를 하나로) 같은 그래프 구조를 만들 수 없다. 우리
`contracts/pipeline.schema.json`은 이미 노드 그래프를 전제하고 있어, 계약 표현력이
그라파나 실행 모델을 넘어선다.

### 3.3 편집 주체가 다르다

그라파나의 조합은 **대시보드 편집 모드에서 관리자가 미리** 구성하는 것이다.
회의에서 요구한 것은 **사용 중인 사용자가 그 자리에서** 조합하는 것이다. 전자는
설정이고 후자는 상호작용이다. 요구사항정의서가 "정적"이라고 진단받은 이유와 정확히
같은 층위의 문제가 그라파나에도 있다.

---

## 4. C — 미디어 파이프라인: 불가

그라파나의 데이터 모델은 DataFrame(시계열/테이블)이다. 영상 스트림은 이 모델
밖에 있고, 실무에서는 Text 패널에 HTML `<img>`/`<video>`를 끼워 넣는 방식으로
우회한다. **이것이 요구사항정의서 1장 "해결하려는 문제" 3번에 이미 적어둔 바로
그 임시방편이다.**

회의록의 참조 사례(카메라 소스 → 컨트라스트·Canny 필터 → 오브젝트 디텍션)는
전 구간이 미디어 파이프라인이므로, 그라파나 위에서는 시작조차 할 수 없다.

---

## 5. 결론 및 설계 반영

### 5.1 그라파나는 경쟁 대상이 아니라 소비 대상이다

조사 결과는 "그라파나를 대체하자"가 아니라 **"그라파나가 잘하는 A는 그대로 쓰고,
못 하는 B·C를 우리가 만든다"**로 정리된다. 이는 회의록 §2의 다음 문장과 일치한다.

> 그라파나처럼 Prometheus에서 데이터를 가져와 가시화하는 것도 당연히 포함하되,
> 그 위에 LLM 가공 계층을 얹는 것이 핵심

기존 설계의 **F7 DataSource 추상화(REQ-701/702)를 유지·강화**하는 것이 옳다.
Prometheus뿐 아니라 **Grafana HTTP API 자체를 하나의 DataSource 구현체로** 두면,
대규 파트가 구축하는 OTel/Grafana 스택을 그대로 흡수하면서 그 위에 우리 계층을
얹을 수 있다.

### 5.2 자체 도구가 필요한 근거는 B와 C다

"그라파나로 안 되니까"가 아니라 **"그라파나의 실행 모델이 노드 그래프도 미디어도
표현하지 못하니까"**가 정확한 근거다. 스택 논쟁(파이썬/닷넷/웹)과 무관하게 성립하는
근거이므로, 회의록 §2의 "스택 자체로는 승부하기 어렵다"는 결론과도 충돌하지 않는다.

### 5.3 신뢰도에 대한 단서

본 조사는 공개 문서·커뮤니티 자료 기반이다. §2의 제약 목록은 그라파나 버전에 따라
완화되었을 수 있으므로, **실제 그라파나 인스턴스에서 Mixed + Stat 패널 조합을 한 번
확인**한 뒤 확정하는 것이 안전하다. 이 확인은 대규 파트가 OTel 스택을 세운 이후에
가능하다.

---

## 출처

- [Data sources | Grafana documentation](https://grafana.com/docs/grafana/latest/datasources/)
- [How to work with multiple data sources in Grafana dashboards | Grafana Labs](https://grafana.com/blog/how-to-work-with-multiple-data-sources-in-grafana-dashboards-best-practices-to-get-started/)
- [Transform data | Grafana documentation](https://grafana.com/docs/grafana/latest/panels-visualizations/query-transform-data/transform-data/)
- [Node graph | Grafana documentation](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/node-graph/)
- [How to Configure Grafana Mixed Data Source Panels](https://oneuptime.com/blog/post/2026-02-02-grafana-mixed-data-sources/view)
- [Can we add two data sources in the same panel — Grafana Community](https://community.grafana.com/t/can-we-add-two-data-sources-in-the-same-panel/71577)
- [Node Graph does not look for renaming transformations · grafana#54844](https://github.com/grafana/grafana/issues/54844)
