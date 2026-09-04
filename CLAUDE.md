# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

이 파일은 **백엔드(BE) 파트를 구현하는 Claude Code를 위한 상시 규칙집**이다. 설계는 별도
채팅방에서 하고, 그 결과(작업 지시서 + 이 규칙)를 근거로 VS Code에서 구현한다. 매 세션 이 파일을
먼저 읽고 아래 규약을 따른다.

---

## 0. 코드베이스 작업 가이드

### 프로젝트 개요

국가 인프라 전제의 엣지-클라우드 관측 백엔드 + 디지털 트윈(담당: 이대규). 센서·이동체·엣지·AI가
발행하는 데이터를 성격(업무·관측·영상)에 따라 저장·중계·번역하고, 구역 트윈을 종합한다.
MQTT·Kafka·OpenTelemetry·K3s·Tailscale은 **어댑터 뒤의 현재 배포 선택**이지 핵심에 하드코딩된
필수가 아니다.

- 아키텍처 정본: [`docs/be/00-architecture.md`](docs/be/00-architecture.md) (5구간 구조·결정 근거)
- 미디어 경로: [`docs/be/02-media-path.md`](docs/be/02-media-path.md)
- 구현 순서·Tier 분류: [`docs/be/01-standalone-implementation-plan.md`](docs/be/01-standalone-implementation-plan.md)
- 요구사항 상태: [`docs/be/requirement-traceability.md`](docs/be/requirement-traceability.md)
- 파트 간 계약: [`contracts/common/`](contracts/common/) (봉투·frame_ref, 백엔드 소유)

### 명령

> 코드 착수 전이라 아래는 예정 구조다. Phase 0(인프라)·Phase 1(파이프라인) 구현 시 실제 명령으로
> 확정한다.

```bash
# 인프라 스택 (Phase 0) — infra/ 아래 compose
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml ps        # 헬스 확인

# 파이썬 백엔드 (Phase 1~)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 테스트 (Phase 1부터 pytest)
pytest -q
pytest -q tests/test_xxx.py::test_name               # 단일 테스트
```

- **Phase 0(인프라 기동)은 헬스체크로 검증**하고 pytest를 쓰지 않는다.
- **Phase 1 이후는 pytest**로 "가짜 발행자 → 파이프라인 → 예상 저장/중계" 회귀를 검증한다.

### 구조와 흐름

데이터가 성격에 따라 갈라져 흐르는 것이 핵심이다. 상위 로직은 특정 브로커·저장 제품 API를 직접
호출하지 않는다.

```
backend/
  ingest/        MQTT 구독 → Kafka produce (엣지 소비자, 브릿지)
  storage/       TSDB writer(계측) + MySQL writer(감사·레지스트리) — 2축
  availability/  가용성 판정기 (업무 평면 MQTT 세션 우선 + 관측 평면 통합)
  gateway/       WS 게이트웨이 — Kafka 소비자이면서 WebSocket 서버 (서버 내부 컴포넌트)
  twin/          디지털 트윈 (위치·클래스 융합, 커버리지·사각지대, 시의성, 로봇 투입)
contracts/common/  파트 경계 계약 (JSON Schema). 이것이 정본이지 파이썬 타입이 아니다.
infra/             docker-compose · Collector · Grafana 등 배포 자산
```

**흐름 요약(구간별):**
1. **말단↔엣지** = 업무 MQTT / 관측 OTLP / 명령 하달 MQTT / 생사 LWT+하트비트.
2. **엣지 내부** = Mosquitto + MQTT→Kafka 브릿지 + Collector(Agent) + 엣지 Prometheus + K3s.
3. **엣지↔서버** = 업무 Kafka / 관측 페더레이션 요약 / log·trace 원본 / 명령 Kafka. 전부 단일
   Tailscale 터널 공유.
4. **서버 내부** = Kafka 다중 소비자 팬아웃 → AI·TSDB·트윈. 감사·레지스트리 MySQL. 가용성 통합
   단일 지점(업무 평면 우선). Collector(Gateway)→Loki·Tempo.
5. **서버↔사용자** = WS 게이트웨이(Kafka 소비자+WebSocket 서버)로 실시간 push, 조회 프록시로
   pull, 백엔드 캐시로 재접속 스냅샷, 미디어는 별도 WS 중계.

### 서버 배포 워크플로 — git pull 배포가 아니다

인프라·서버 설정 작업은 아래 방식으로 흐른다. **서버에 저장소를 clone해서 `git pull`로
배포하지 않는다.**

- **편집은 컴퓨터(이 저장소), 실제 실행은 서버(sysai-server2).** 깃허브는 코드·문서 동기화용
  이지 서버 배포 통로가 아니다.
- 서버에는 이미 도는 compose가 있다(`~/capstone-db/docker-compose.yml`). **그 서버 파일을
  수정**하는 것이 실제 배포다. `infra/docker-compose.yml`은 그 서버 파일의 **작업본(청사진)**
  이며, 평문 비밀번호·내부망 주소를 담고 있어 **커밋하지 않는다**(`.gitignore`).
- 흐름: 컴퓨터 `infra/`에서 편집 → **사람이** 서버에 복사·적용 → 결과·에러를 컴퓨터로 회수 →
  수정. Claude Code는 서버 파일을 직접 수정하지 않고, 서버에 적용할 내용을 만들어 사람에게 준다.
- **서버 상태가 필요하면 먼저 확인 명령을 제시하고 결과를 받은 뒤** 착수한다. 서버 상태 조회
  결과·설정 사본은 `_serverinfo/`(gitignore)에 두고 참고한다 — 서버 포트·방화벽·내부 IP가
  노출되면 안 되므로 커밋 금지.
- 이미 서버에서 도는 서비스는 **지웠다 다시 깔지 않는다.** `docker compose up -d`에 반드시
  서비스 이름을 명시한다(이름 없이 실행하면 `:latest` 서비스가 재생성될 수 있다).

### 코드 작성 규약

- **모든 모듈·테스트 docstring 상단에 `implements: BE-X-NN` 형식으로 요구사항 ID를 남긴다.**
  구현 후 [`docs/be/requirement-traceability.md`](docs/be/requirement-traceability.md)의 해당
  행(상태·구현 위치·테스트)을 함께 갱신한다.
  ```python
  """MQTT 구독 → Kafka produce 브릿지.

  implements: BE-T-01, BE-T-02
  tests: 봉투 검증 격리, 브릿지 왕복
  """
  ```
- **변수·필드 이름은 [`contracts/common/`](contracts/common/)의 공통 봉투를 정본으로 통일한다.**
  봉투 필드(`source_id`·`entity_id`·`node_id`·`zone_id`·`timestamp`·`sequence_id`·
  `correlation_id`·`origin_kind`)는 이 이름 그대로 쓴다. 새 이름이 필요하면 먼저 계약에 의미를
  정의한다.
- **작업 단위별 보고서는 `reports/YYYY-MM-DD_HHMM_주제.md` 형식으로 남긴다** — 배경 / 한 일 /
  검증 / 다음. 이 보고서가 다음 설계 세션의 입력이 된다.
- 주석·docstring은 한국어를 기본으로 하고, 요구사항 인용은 원문을 섞어 쓴다.
- 파일 인코딩은 UTF-8, 줄바꿈은 LF(`.gitattributes`가 강제). 배포 대상이 리눅스라 CRLF 금지.

---

## 1. 절대 준수 원칙

아키텍처 정본에서 도출한 불변 원칙이다. 구현이 이를 어기면 재작업이다.

1. **특정 기술을 핵심에 하드코딩하지 않는다.** MQTT·Kafka·OpenTelemetry·K3s·Tailscale·저장
   제품(TSDB/MySQL)은 어댑터 뒤의 현재 배포 구현이다. 상위 로직은 목적 수준 인터페이스만 쓴다
   (BE-C-05·AI-C-12 정합).
2. **데이터 성격이 채널을 결정한다.** 업무=MQTT(말단)/Kafka(백본), 관측=OpenTelemetry, 영상=별개
   미디어 경로, 브라우저=WebSocket. 개발자가 채널을 임의 선택하지 않는다(돌발 채널 금지).
3. **영상 픽셀을 업무·관측 메시지에 싣지 않는다.** MQTT/Kafka/OTLP에 JPEG를 넣지 않는다. 영상은
   별도 미디어 경로(RTP/UDP → WS 방식 B → WSS)로만 흐른다.
4. **성격별 저장 모델을 분리한다.** 계측 시계열=TSDB, 감사·레지스트리=MySQL(테이블 분리), 관측=
   Prometheus/Loki/Tempo. **RBAC·MongoDB는 채택하지 않는다.** 트윈·명령 진행·가용성은 저장하지
   않고 WS push한다.
5. **감사는 요약하지 않는다.** 명령·조작의 책임 기록은 요약·필터 없이 전량 MySQL로 직행한다.
   actor는 토큰에서, 시각은 서버 시각으로 백엔드가 주입한다(위조 불가). 명령 이력(감사)과 기술
   추적(Tempo)은 다른 목적이라 섞지 않는다.
6. **관측 metric만 요약하고 log·trace는 원본을 유지한다.** metric은 엣지 raw 보관 + 페더레이션
   요약(부하 구역 수 비례). 장치 생사·치명 오류는 요약에 섞지 않고 개별 신호로 유지한다.
7. **장치 최종 가용성은 백엔드가 단일 지점에서 판정한다.** 두 평면(MQTT 세션 / 관측 up·absent)을
   통합하되 **충돌 시 업무 평면 우선**(MQTT 세션 online이면 가용, offline이면 up=1이어도 불가용).
   AI가 이를 중복 판정하지 않는다.
8. **명령은 전달만으로 완료되지 않는다.** 수신 확인(ACK) → 수행 중 → 물리 상태 변화 → 완료/실패
   4단계로 승격한다. 되돌리기 어려운 명령(수문·펌프·모터)은 ACK가 아니라 실제 수행 결과로 확정
   표시한다. 전 파트 단일 상관키(command_id)는 백엔드가 발급한다.
9. **파트 경계의 기준은 JSON Schema다.** `contracts/common/`이 정본이며 파이썬 타입을 다른 파트에
   노출·강제하지 않는다. 봉투 필수 5필드(`schema_version`·`source_id`·`node_id`·`zone_id`·
   `timestamp`)를 지킨다.
10. **frame_ref는 엣지에서 한 번 부여하고 전파한다.** 백엔드·AI는 새 번호를 재생성하지 않는다.
    영상과 탐지가 뷰어에서 F==F로 합류해야 오버레이가 정합한다.
11. **Kafka는 장기 저장소가 아니다.** 다중 소비자 독립 읽기·단기 버퍼·단기 replay 용도다. 재난
    데이터 장기 보존은 TSDB 보존 사안이지 Kafka retention이 아니다. "재학습 위해 Kafka"라고
    표현하지 않는다.
12. **엣지↔서버는 사설망이라 터널이 강제다.** 업무·관측·영상이 단일 Tailscale 터널을 공유하되
    논리 채널은 분리된다. Tailscale은 교체 가능한 현재 배포 구현이다.
13. **WS 게이트웨이는 서버 내부 컴포넌트다.** Kafka 소비자이면서 WebSocket 서버. 브라우저는
    Kafka·MQTT에 직접 붙지 않고 이 게이트웨이만 통한다. 이는 단순 프로토콜 변환(브릿지)과 달리
    구독·인증·캐시·명령 번역까지 하는 백엔드 로직이다.
14. **부하를 구역 수에 비례하게 유지한다.** 엣지가 브로커·수집기·관측 raw를 1차 수용한다. 중앙에
    모든 raw를 몰지 않는다.
15. **국가 인프라급으로 설계하고 캡스톤은 특수 사례로 포함한다.** 각 결정을 "추상 요구 + 현재
    배포 프로파일"로 서술한다. 캡스톤 규모로 축소해 설계하지 않는다.

---

## 1-A. 구현 규율 — 어떻게 일하는가

원칙(§1)이 "무엇을 지키나"라면, 이건 "어떻게 진행하나"다. Phase 0에서 이 규율이 없어 작업이
반복해서 헛돌았다. 매 구현 세션에서 지킨다.

1. **시작 전에 CLAUDE.md와 작업 지시서를 처음부터 끝까지 정독한다.** 일부만 읽고 착수하지
   않는다. 지시서의 "이번에 하지 않는 것"과 "완료 판정"을 먼저 확인한다.
2. **사실을 다 받기 전에 해법을 제시하지 않는다.** 서버 상태·설정 원문 등 필요한 사실은 먼저
   확인 명령으로 받고, 그 뒤에 판단한다.
3. **지시서와 현실이 다르면, 차이를 먼저 보고하고 결정을 받는다.** 혼자 절충안을 만들지 않는다.
4. **사용자가 결정을 말하면 그대로 한다.** 우려는 한 문장으로만, 반복하지 않는다. (예: 사용자가
   "UFW 열겠다"고 하면 연다. 되묻지 않는다.)
5. **지시서에 없는 것은 꺼내지 않는다.** 필요해 보이면 한 줄로 묻고 넘어간다. 범위를 임의로
   넓히지 않는다(예: Phase 0에서 DB 스키마·인증·포트 정책을 임의로 만들지 않는다).
6. **설정값에 선택지가 있으면 임의로 정하지 않고 표로 제시하고 결정을 받는다.** 특히 계약·채널·
   저장 모델·가용성 규칙·포트/주소/인증처럼 뒤 Phase나 다른 파트에 영향 주는 것.
7. **막히거나 결정이 필요하면 `reports/`에 남기고 멈춘다.** 추측으로 진행하지 않는다.
8. **작업 중 발견한 gap·이월사항은 반드시 두 곳에 흘려보낸다:** (a) 관련 요구사항 행을
   `requirement-traceability.md`에 gap과 함께 기록, (b) **그 조치가 이뤄질 Phase가 있으면
   `docs/be/01-standalone-implementation-plan.md`의 그 Phase 항목에 이월사항으로 적는다.**
   보고서에만 적고 끝내지 않는다 — 보고서는 직전 세션만 읽으므로, 몇 Phase 뒤에 쓰일 발견은
   plan·traceability에 적어야 그 시점에 살아난다.

## 2. 구현 시 금지 사항

- 인지·저장·중계 코드 안에서 특정 protocol client(MQTT/Kafka 등)를 직접 생성하지 않는다 —
  어댑터/provider 경계 뒤에 둔다.
- 영상 픽셀을 MQTT/Kafka/OTLP 메시지에 직접 싣지 않는다.
- 감사·치명 오류·장치 생사를 일반 metric 요약에 섞어 개별 의미를 잃게 하지 않는다.
- 장치 최종 availability를 백엔드 밖(또는 AI)에서 독자 재판정하지 않는다.
- Kafka를 장기 데이터베이스처럼 쓰지 않는다.
- RBAC·MongoDB를 도입하지 않는다(정본 결정).
- 봉투 필드명을 계약과 다르게 임의로 짓지 않는다 — 먼저 `contracts/common/`에 정의한다.
- 실제 `.env`·토큰·키·인증서·내부망 endpoint를 커밋하지 않는다(Public 저장소).

---

## 3. 요구사항 추적 규칙

각 구현 단위와 테스트에 관련 요구사항 ID를 남긴다.

```text
implements: BE-T-02, BE-C-01
tests: 봉투 검증 격리, MQTT→Kafka 브릿지 왕복
```

- 코드를 추가하면 [`docs/be/requirement-traceability.md`](docs/be/requirement-traceability.md)의
  해당 행 상태·구현 위치·테스트를 갱신한다.
- 상태를 **완료**로 올릴 때는 반드시 동작·경계를 검증하는 테스트를 함께 명시한다(테스트 없는 완료
  금지). 검증이 무력하지 않은지(무효 입력을 실제로 거부하는지) 음성 대조도 포함한다.
- 완료 판정은 특정 모델 정확도나 특정 기술 사용 여부가 아니라 **해당 요구사항이 정의한 동작과
  경계가 실제로 보장되는지**로 한다.

---

## 4. 작업 방식 (설계 → 구현 루프)

- **이 CLAUDE.md는 설계방·구현방 둘 다 읽는다.** 구현방(VS Code Claude Code)은 저장소를 열면
  자동으로, 설계방은 고정 세트로 전달받아 읽는다. 따라서 §1-A 구현 규율은 설계방이 지시서를
  만들 때도, 구현방이 코드를 짤 때도 같은 기준이다.
- **채팅방 진입 규칙 (부트스트랩):** 새 설계방을 열 때는 설계방이 지켜야 할 규칙 문서
  `docs/be/설계_규칙.md`와 `docs/be/작업지시_템플릿.md`를 이 CLAUDE.md와 **함께 올린다.**
  이 둘에 "설계방이 지시서를 어떻게 만드는가"(골격·규율 반영·이월)가 있어, 빠지면 새 방이 규칙을
  모른 채 시작한다. 무엇을 올릴지 전체 목록은 `docs/be/설계방_진입가이드.md` §1(고정 세트 11개
  + Phase별 추가)에 있다 — 단 그 진입가이드 자체는 **사람용 운영 절차**라 설계방에 올리지 않는다
  (AI가 읽으면 절차를 자기 행동으로 오해한다). **규칙이 문서에만 있고 방에 전달되지 않으면 없는
  것과 같다.**
- **설계는 별도 채팅방에서** 하고, 그 결과를 작업 지시서로 굳혀 이 저장소에 넣는다. 작업
  지시서는 `docs/be/작업지시_템플릿.md`의 골격을 따른다.
- **구현은 이 저장소에서** 하며 이 CLAUDE.md와 해당 작업 지시서를 읽고 진행한다. 계획이 이미
  문서로 나와 있으므로 새로 설계하지 말고 지시서 범위대로 구현한다.
- **막히면 임의로 정하지 말고** `reports/`에 남기고 멈춘다. 특히 계약 변경·채널 추가·저장 모델
  변경·가용성 판정 규칙은 프로젝트 전체가 걸린 결정이라 혼자 바꾸지 않는다.
- 한 작업 단위가 끝나면 `reports/YYYY-MM-DD_HHMM_주제.md`(배경/한 일/검증/다음)를 남긴다 — 이
  보고서가 다음 설계 세션으로 돌아간다.
