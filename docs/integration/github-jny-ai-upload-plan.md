# jny_AI 공개 업로드 계획

## 점검 결론

대상은 공개 저장소 `khw18033/Physical-Project-mk2`의 `jny_AI` 브랜치
(`012580c`)이다. 현재 브랜치에는 과거 `ai-framework/`가 있으므로 새
`perception-framework/`를 추가만 하면 구현이 중복된다.

`perception-framework/`와 `docs/`만 복사한 임시 환경에서 전체 테스트는 수집 단계에서
실패했다. 원인은 다음 저장소 상위 경로 의존성이다.

- `tests/test_external_validation_common.py` → `experiments/external/common.py`
- 계약 테스트 2개 → `contracts/ai/`
- open-vocabulary 테스트 → `models/`, `datasets/`(없으면 정상 skip)
- 시나리오 지표 → 루트 `reports/`(실행 중 생성)

외부 경로 의존 테스트 3개를 제외하면 독립 복사본에서 `462 passed, 27 skipped`였다.
따라서 현재 상태를 “두 디렉터리만으로 전체 정상 동작”이라고 표현하면 부정확하다.

## 공개 범위

업로드 allowlist는 다음으로 제한한다.

```text
perception-framework/
docs/
```

다음 항목은 반드시 제외한다: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`,
`:memory:.ses`, dataset, model weight, 실행 로그와 개인 환경 파일. `docs/obsidian/ideas/
progressive-object-record.pdf`는 5.6 MB이므로 저작권·배포 권한 확인 전 제외한다.

## 업로드 전 수정

1. `contracts/ai` 스키마와 예제를 `perception-framework/contracts/ai/`에 복제하고 테스트
   경로를 독립 배치 기준으로 수정한다.
2. `experiments/external/common.py`의 manifest·checksum 기능을 패키지 내부 모듈로 옮기고
   외부 실험 결과 자체는 공개 대상에서 제외한다.
3. 시나리오 지표 기본 출력 위치를 `perception-framework/reports/` 또는 임시 경로로 바꾼다.
4. README의 `../contracts/ai` 참조와 설치·테스트 명령을 독립 배치 기준으로 갱신한다.
5. Python 3.10과 프로젝트 사용 버전에서 clean install, wheel build, 전체 pytest 및 Docker
   build를 새 임시 clone에서 실행한다.

완료 기준은 제외 테스트 없이 전체 suite가 통과하거나 선택 자산 테스트만 사유와 함께
skip되는 것이다.

## 보안·운영 Gate

- `git diff --cached --name-only`로 두 allowlist 밖 변경이 없는지 검사한다.
- Gitleaks 또는 GitHub secret scanning으로 현재 snapshot과 추가 commit을 검사한다.
- 토큰, `.env`, 인증서, 내부 주소, 사용자 절대 경로 및 민감 영상이 없는지 재검사한다.
- Dependabot, CodeQL(Python), dependency review와 pytest CI를 활성화한다.
- 최소 권한 PAT 또는 SSH deploy key를 사용하고 토큰을 명령행·remote URL에 넣지 않는다.
- `jny_AI` 직접 push 대신 PR, 필수 CI, 1인 review, force-push 금지 규칙을 적용한다.
- 공개 라이선스와 `SECURITY.md`가 원격 루트에 없으므로 저장소 소유자가 공개 배포 전
  라이선스와 취약점 신고 정책을 결정해야 한다.

## 반영 순서

1. 원격 `jny_AI` 최신 commit에서 별도 `jny_AI-perception-sync` 브랜치를 만든다.
2. 위 독립성 수정과 공개 allowlist 정리를 한 개의 준비 commit으로 만든다.
3. 과거 `ai-framework/` 처리 방식을 결정한다. 권장은 검증된 새 폴더로 교체하며, 삭제는
   저장소 소유자 승인 후 별도 commit으로 수행하는 것이다.
4. clean clone에서 pytest·Docker·secret scan 결과를 CI artifact로 남긴다.
5. PR에는 변경 디렉터리, 테스트 결과, skip 사유, 외부 자산 미포함, 데이터·모델 라이선스
   제한과 rollback commit을 기록한다.
6. review와 CI 통과 후 squash merge하고 branch tag를 생성한다. 문제 발생 시 merge
   commit을 revert하며 history rewrite는 하지 않는다.

## 실행 결과

- 2026-09-01: `jny_AI`의 `012580c`를 기준으로 공개 후보를 구성했다.
- 구 `ai-framework/`와 중복 루트 `contracts/`를 삭제하고 계약을
  `perception-framework/contracts/ai/`에 포함했다.
- 독립 복사본: `479 passed, 27 skipped`; Docker: `472 passed, 34 skipped`.
- wheel 빌드 성공, secret 정규식 검사와 staged 경로 allowlist 검사 통과.
- 배포 권한 미확인 PDF, 가상환경, cache, model, dataset과 runtime artifact는 제외했다.
- commit `3dac804`를 `refs/heads/jny_AI`에만 push했다.

브랜치 보호와 저장소 설정은 코드 push 권한과 별개의 관리자 작업이므로 변경하지 않았다.
