# 2026-08-25 15:06 — STT 모델 비교 실험 하네스 구축

**기준**: `stt-lab_작업프롬프트_260825.md` · `요구사항정의서.md` §2.13 F13
**구현 커밋**: `237baad` · Python 3.9 호환 보완 `6552346`
**범위**: F13 음성 인터페이스를 대시보드에 붙이기 전, 엔진·모델·설정과 신뢰도 임계값을 비교할 독립 실험 도구

## 요청과 경계

STT 엔진을 먼저 정해 대시보드에 결합하지 않고, 같은 오디오를 여러 설정으로 반복 측정해
선정 근거를 만들 수 있는 `stt-lab/`을 구축했다. 이번 결과는 **F13 운영 기능 구현이
아니다.** `web-dashboard/`와 다른 프로세스·포트(8799)에서 실행하며 대시보드 코드와
계약을 변경하지 않는다.

이 경계를 둔 이유는 두 가지다.

1. `REQ-1302`가 특정 STT 엔진에 종속되지 않는 인터페이스를 요구한다.
2. `REQ-1306`의 신뢰도 임계값은 추측으로 정하지 않고 실제 발화의 확률 분포를 보고
   정해야 한다.

## 구현 결과

| 영역 | 결과 |
|---|---|
| 서버 | FastAPI가 API와 단일 정적 HTML 화면을 함께 제공한다. npm·Vite는 추가하지 않았다. |
| 엔진 경계 | `SttEngine` 프로토콜 뒤에 faster-whisper 구현을 두었다. 새 엔진은 파일과 등록 항목을 추가하는 구조다. |
| 모델·장치 | tiny~large-v3-turbo 선택, CUDA/float16 우선, 실패 시 CPU/int8 자동 폴백, 프로세스 수명 모델 캐시를 제공한다. |
| 어휘 | `registry.json` 복사본 없이 원본의 `display_name`·`aliases[]`를 읽어 hotwords 42개를 구성한다. |
| 시험 발화 | zone/node/entity와 별칭을 조합해 정답이 정해진 프리셋 67개를 생성한다. |
| 측정 | 세그먼트 `avg_logprob`·`no_speech_prob`, 단어 확률, 모델 로드 시간, 추론 시간, RTF를 노출한다. |
| 정확도 | 외부 점수 라이브러리 없이 음절 CER·자모 CER·WER를 계산하고 문장부호 제거 여부를 선택할 수 있다. |
| 반복 비교 | 녹음·파일 업로드, 같은 오디오 재실행, 누적 JSONL 기록, UTF-8 BOM CSV 내보내기를 지원한다. |
| 보관 | 비교용 오디오·실행 기록·모델/가상환경은 Git에서 제외한다. |

## 주요 판단

### hotwords와 initial prompt를 분리했다

레지스트리 어휘로 디코딩을 편향시키는 `hotwords`와 문맥·문체를 유도하는
`initial_prompt`는 목적이 다르다. 화면과 API에서 별도 옵션으로 유지하며, 실제 적용된
옵션은 결과에 다시 실어 설정이 무시됐는지 확인할 수 있게 했다.

### 짧은 명령 발화에 맞춘 기본값을 고정했다

1~3초 발화의 반복·무음 환각을 줄이기 위해 `condition_on_previous_text=False`,
한국어 고정, VAD 기본 켬을 적용했다. VAD는 비교를 위해 끌 수 있고, 모델 최초 로드
시간은 RTF에서 분리한다. 같은 모델을 매번 다시 읽으면 모델 성능이 아니라 다운로드와
초기화 시간을 비교하게 되기 때문이다.

### 신뢰도 임계값은 아직 정하지 않았다

Whisper에는 명령 수락 여부를 바로 결정할 단일 confidence가 없다. 따라서
`avg_logprob`, `no_speech_prob`, 단어 확률과 CER을 함께 저장한다. 정답·오답·무음·소음,
hotwords/VAD 조합을 반복 측정한 뒤 정답 오거부율과 오답 통과율을 비교해야
`REQ-1306` 임계값을 확정할 수 있다.

### Python 3.9 실행 경로를 복구했다

초기 구현의 PEP 604 union 표기(`X | None`)는 Python 3.9에서 런타임 타입 평가 중
실패할 수 있었다. `Optional[...]`·`Union[...]` 형태로 바꾸고, 가상환경 활성화가 막힐
때 직접 Python 실행 파일을 사용하는 절차와 PowerShell 실행 정책 안내를 README에
추가했다.

## 산출물

| 파일 | 역할 |
|---|---|
| `stt-lab/server/main.py` | FastAPI 앱, API 라우팅, 정적 화면 제공 |
| `stt-lab/server/engines/base.py` | 엔진 프로토콜과 공통 결과 형식 |
| `stt-lab/server/engines/faster_whisper.py` | faster-whisper 구현, 장치 선택·CPU 폴백·모델 캐시 |
| `stt-lab/server/registry.py` | 원본 레지스트리 어휘 42개와 시험 발화 67개 생성 |
| `stt-lab/server/scoring.py` | 음절 CER·자모 CER·WER 계산 |
| `stt-lab/server/store.py` | 실행 결과 JSONL 적재와 CSV 변환 |
| `stt-lab/web/index.html` | 녹음·업로드·설정·결과·정확도·누적 비교 화면 |
| `stt-lab/README.md` | Windows 실행, GPU/CPU 폴백, 수치 해석, 장애 대응, 엔진 확장 절차 |

## 재검증

2026-08-25 현재 작업 트리에서 다음을 다시 확인했다.

```text
Python 3.9.13
python -m compileall -q stt-lab/server                         통과
registry hotwords                                              42개
registry 기반 시험 발화                                       67개
동일 문장 점수                                                 CER 0.0 / WER 0.0
from server.main import app                                   통과 · route 14개
구현 커밋 237baad·6552346의 web-dashboard 변경                0개
```

FastAPI 앱 로드와 순수 로직은 확인했다. 실제 모델 다운로드·마이크 녹음·CUDA/CPU 추론은
모델 파일과 사용자 장비가 필요한 실험 단계이므로 이 보고서에서 성공으로 간주하지 않는다.
그 결과는 동일 오디오 반복 측정 후 별도 실험 기록으로 남겨야 한다.

## 다음 단계

1. 계획의 Phase 1 문서 정합 잔여물을 완료한다.
2. `web-dashboard` Phase 2의 잔여 표시 4건을 구현한다.
3. 별도 트랙에서 대표 발화·무음·소음 데이터로 STT 모델과 옵션을 비교하고
   `REQ-1306` 임계값의 근거를 만든다.
