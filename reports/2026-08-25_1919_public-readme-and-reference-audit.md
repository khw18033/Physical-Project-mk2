# 공개 README 및 참고 저장소·보안 감사

담당: 진나영
일시: 2026-08-25 19:19

## 작업 내용

1. 루트 `README.md`에 프로젝트 목적, 51개 요구사항 요약, 활용 시나리오, 아키텍처,
   구현 상태, 테스트, 저장소 구조, 파트별 통합 절차와 남은 검증을 정리했다.
2. mk1 `fleet_mission-dashboard`의 `main`과 `vision` 브랜치를 확인했다. SDK 독립
   `target/action/params` 명령, 상관 ID 기반 ACK, telemetry/online/event 분리와 실물
   RoboMaster 이동·LED 검증 기록을 mk2 제어 경계의 참고 근거로 삼았다.
3. `come-capstone26-physicalAI`에서 로봇·서버·Unity/VR 3단 구조, 구역 핸드오프와
   디지털 트윈 활용 배경을 확인해 참고 프로젝트로 연결했다.
4. mk1 코드를 복사하거나 Redis·특정 로봇 SDK를 mk2 공통 규격으로 고정하지 않았다.
5. `.gitignore`에 로컬 환경설정, 자격증명·개인키 형식과 runtime 산출물 제외 규칙을
   추가했다.

## 공개 보안 감사

- 저장소 전체에서 API key, access key, password, bearer token, GitHub token, AWS key,
  Slack token과 private-key header 패턴을 검색했다.
- 사용자 홈 경로, 이메일 주소, 사설 IPv4 주소, 장치 SSID 흔적을 검색했다.
- URL·endpoint를 검토했으며 `127.0.0.1`, JSON Schema 공식 URL, 공개 문서 URL,
  `.example` 예약 도메인만 확인했다.
- 대용량·바이너리 파일을 확인했으며 소스·문서 외에 공개를 막아야 할 산출물은 없었다.
- `gitleaks`와 `detect-secrets`는 현재 환경에 설치되어 있지 않아 전용 스캐너 대신 위
  패턴 검사와 staged diff 육안 검토를 사용했다.

## 검증

```bash
cd ai-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
# 293 passed, 19 skipped

cd ..
git diff --check
# exit 0
```

## 결론

현재 변경에는 공개 저장소에 올리면 안 되는 운영 자격증명, 개인키, 사설 endpoint,
실영상·모델 데이터가 없다. 물리 명령의 최종 공통 Schema와 실제 하드웨어 성능값은
각 파트 합의·실측 전까지 미확정 상태로 명시했다.
