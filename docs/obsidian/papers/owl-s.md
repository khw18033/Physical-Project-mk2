# OWL-S 1.1

## 메타데이터
- categories: Semantic Web Service, Service Composition, IOPE
- domain: [[디지털트윈·상호운용]]
- source: W3C Member Submission. "OWL-S: Semantic Markup for Web Services."
- url: https://www.w3.org/submissions/OWL-S/
- year: 2004
- authors: David Martin et al.
- venue: W3C Member Submission

## 1. 핵심 요약
- Web service의 속성과 기능을 ontology로 기술하기 위한 OWL vocabulary다.
- Service Profile, Service Model, Service Grounding을 분리한다.
- 자동 discovery, invocation, composition, interoperation, execution monitoring 지원을 목표로 한다.

## 2. 문서 목적
software agent가 Web service를 발견하고 실행하며 여러 service를 조합할 수 있도록 machine-interpretable description을 제공한다.

## 3. 핵심 개념 상세
- **Service Profile:** service가 무엇을 제공하는지 광고·발견에 필요한 정보를 기술한다.
- **Service Model:** service의 동작 과정과 input, output, precondition, result를 표현한다.
- **Service Grounding:** 추상적 service description을 구체 message 및 protocol에 연결한다.
- **Process:** atomic, simple, composite process로 동작과 조합을 표현한다.

## 4. 구조 및 흐름
service가 Profile로 기능을 공개하고 Model로 실행 과정을 설명하며 Grounding으로 실제 호출 방식에 연결된다. composite process는 여러 process의 control flow를 표현한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 의미 설명과 통신 binding은 분리된다 | 상위 ontology가 Profile/Model/Grounding을 별도 class로 둠 |
| 자동 composition이 명시적 목표다 | 제출 문서의 motivating tasks에 automatic composition and interoperation 포함 |

## 6. 한계 및 부족한 점
- W3C Recommendation이 아니라 2004년 Member Submission이다.
- 현대 cloud-native 배포, hardware resource, AI model metadata, 물리 안전을 규정하지 않는다.

## 7. 원문 기반 핵심 문장
> “OWL-S is an ontology ... for describing Web services.”
