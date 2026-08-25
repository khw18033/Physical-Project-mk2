# 2026-08-25 하드웨어·타 파트 없이 구현 가능한 범위 일괄 구현

담당: 진나영

## 배경

이전 세션에서 만든 `docs/ai/01-standalone-implementation-plan.md` 계획에 따라, 실제
카메라·GPU·MQTT 브로커·백엔드가 없어도 fake provider와 합성 데이터로 구현·검증할 수 있는
요구사항을 권장 순서대로 전부 구현했다.

## 진행 순서와 결과

1. **Provider fake 구현체** (AI-C-04/06/07/08/09/12, AI-B-08) — `providers/fakes.py`.
   InMemoryTransportProvider, JsonSerializerProvider, SyntheticMediaSourceProvider,
   StubAIRuntimeProvider, InMemoryObservabilityProvider. 8개 테스트.
2. **서브태스크 생성·검증·재생성** (AI-D-01/02/04) — `decision/`. 생성기는 등록되지 않은
   구역을 절대 추측하지 않고, 검증기는 jsonschema+커스텀 rule로 생성과 분리된 재현 가능한
   검증을 수행하며, 재생성 판단은 "차단성 이벤트"와 "단순 관측 변화"를 구분한다. 13개 테스트.
3. **추적·연계·불확실성·미확인객체·추가정보선택** (AI-S-01~05) — `perception/`. IOU 추적기,
   시간·공간·외형 선택적 연계, 신뢰도-근거충분도 분리, 미확인 상태 보존, 등록된 기능만
   요청하는 추가정보 선택기. 20개 테스트.
4. **위험분석 FSM·점수·출력·수준조정** (AI-R-01~04) — `risk/`. 등록된 이벤트 종류가 없으면
   비활성화만 되는 FSM, 존재하는 입력만 쓰는 규칙기반 점수, Serializer/Transport provider를
   통한 출력, `select_with_degrade` 재사용한 관측수준 요청. 13개 테스트.
5. **실행제어·lifecycle·conformance + 관측** (AI-B-03/05/09, AI-O-01~04) — `execution/`,
   `observability/`. 업무감사 로그와 기술추적 로그 분리, 선택기능 실패가 핵심기능에 전파되지
   않는 lifecycle, 신규 provider가 무관한 capability를 건드리지 않는지 자동 검증하는
   conformance 하네스, 개별 상태(장치 생사)가 metric 집계에 섞이지 않는 관측 저장소.
   22개 테스트.
6. **인지·캘리브레이션·환경설정 적용** (AI-E-01~04, AI-N-02) — `perception/detection.py`,
   `edge/calibration*.py`, `ondevice/config_apply.py`. 캘리브레이션은 알려진 K/dist로
   `cv2.projectPoints`를 역산해 합성 코너를 만들고 `cv2.calibrateCamera`가 원본을 복원하는지
   검증(재투영 오차 RMS 기준 통과/실패 모두 테스트). 인지는 이 환경의 opencv-python 빌드에
   `HOGDescriptor`/`CascadeClassifier`가 없어(objdetect 모듈 미탑재) 대신 threshold+contour
   기반 경량 detector로 교체해 구현. 13개 테스트.

## 검증

```
cd ai-framework && pytest -q
110 passed
```

## 결과

48개 요구사항 중 **40개 완료**(테스트로 동작 보장), 부분 2개(AI-B-02 컨테이너 패키징 제외,
AI-B-04 preferred 가중치 제외), 미착수 6개(AI-B-10, AI-C-01[의도적 보류], AI-C-02, AI-C-03,
AI-C-14, AI-D-03 — 뒤 4개는 Tier A였으나 이번 순서에 미포함). 전체 갱신된 상세는
`docs/ai/requirement-traceability.md` 참고.

## 다음 단계

- 이번에 빠진 Tier A 항목(AI-D-03, AI-C-02/03/14) 마저 구현.
- AI-B-04 preferred 태그 가중치 선택 로직 반영.
- Tier C(실제 MQTT/Kafka/K3s/OTel/백엔드 연동)는 타 파트 산출물이 준비되는 대로 통합.

추가 요구사항 필요 사항 없음.
