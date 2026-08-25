# 파트 간 AI 계약 및 병합 가이드 완료

담당: 진나영
일시: 2026-08-25 19:07

## 작업 범위

다른 파트 브랜치를 직접 병합하거나 연결하지 않고, AI 브랜치에서 독립적으로 완료할 수 있는
연동 경계와 검증 자산을 구현했다. 하드웨어·백엔드·가시화 파트는 동일 JSON Schema와 예시
payload를 기준으로 각자 adapter를 작성할 수 있다.

## 변경 내용

1. `contracts/ai`에 공통 message envelope와 detection, risk, failure, plan, capability,
   model deployment 결과 JSON Schema 및 유효 예시를 추가했다.
2. `ai_framework/integration/wire.py`에 AI 내부 도메인 객체를 공통 wire payload로 변환하고
   기존 `TransportProvider`로 발행하는 adapter를 추가했다.
3. `ModelDeploymentProvider`와 `ModelDeploymentManager`를 추가해 모델 다운로드, 검증,
   활성화, 실패 시 이전 버전 롤백 lifecycle을 구현했다.
4. 스키마, 변환 adapter, 전송 발행, 모델 배포 성공·실패·롤백을 단위 테스트로 검증했다.
5. `docs/integration`에 공통 통합 순서와 하드웨어·백엔드·가시화 파트별 병합 가이드를
   작성했다. Google Sheet의 깨진 AI 요구사항 참조와 의미 불일치도 문서에 표시했다.

## 검증

```bash
cd ai-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
# 293 passed, 19 skipped

cd ..
git diff --check
# exit 0
```

## 인계 상태

- 브랜치 checkout, merge, rebase, cherry-pick은 수행하지 않았다.
- 실제 센서 입력 연결은 `docs/integration/hardware-merge-guide.md`에 남겼다.
- broker/API와 승인 흐름 연결은 `docs/integration/backend-merge-guide.md`에 남겼다.
- TypeScript 타입과 bbox/frame/risk 매핑은 `docs/integration/visualization-merge-guide.md`에
  남겼다.
- AI-B-10의 실물 말단 성능·발열·처리주기 실측은 하드웨어 확보 후에만 완료할 수 있다.
