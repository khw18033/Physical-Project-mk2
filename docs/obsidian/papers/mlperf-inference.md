# MLPerf Inference

## 메타데이터
- categories: Inference Benchmark, Latency, Throughput
- domain: [[엣지 실행·자원]]
- source: MLCommons. "MLPerf Inference Benchmark Suite."
- url: https://mlcommons.org/working-groups/benchmarks/inference/
- year: 2026
- authors: MLCommons Inference Working Group
- venue: Industry Benchmark Suite

## 1. 핵심 요약
- ML hardware·software system을 architecture-neutral하고 representative하며 reproducible하게 비교하기 위한 benchmark suite다.
- system type을 Datacenter와 Edge 등으로 나누고 workload별 scenario와 metric을 정의한다.
- 공통 LoadGen이 query 생성·scheduling·logging·latency tracking·accuracy validation·metric 계산을 담당한다.

## 2. 문서 목적
다양한 model, accelerator, framework 조합을 공정하게 비교할 산업 공통 inference benchmark와 평가 기준을 제공한다.

## 3. 핵심 개념 상세
- **Scenario:** Edge는 SingleStream, MultiStream, Offline을 사용하며 Datacenter는 Server·Offline 등의 요청 pattern을 사용한다.
- **Quality target:** 성능 결과가 유효하려면 benchmark별 accuracy 기준을 충족해야 한다.
- **Closed/Open division:** 동일 조건 비교와 혁신적 변형 제출을 구분한다.
- **System description:** processor, accelerator, software와 측정 구성을 결과에 연결한다.

## 4. 구조 및 흐름
system·division·scenario를 정하고 표준 dataset/model과 LoadGen으로 performance를 측정한다. accuracy checker와 compliance 절차를 거친 결과가 system metadata와 함께 제출된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| latency와 throughput은 workload scenario에 종속된다 | scenario마다 요청 pattern과 metric이 별도로 정의됨 |
| 성능만 높아서는 유효 결과가 아니다 | benchmark별 quality target과 accuracy validation을 요구 |

## 6. 한계 및 부족한 점
- 지원 benchmark와 scenario 밖의 workload 성능을 보장하지 않는다.
- 결과는 해당 system·software·model·scenario 조합에 연결되며 다른 조건으로 일반화할 수 없다.
- capability 의미나 runtime health를 정의하는 계약은 아니다.

## 7. 원문 기반 핵심 문장
> “Create a set of fair and representative inference benchmarks.”
