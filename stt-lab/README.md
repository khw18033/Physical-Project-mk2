# stt-lab

F13 음성 인터페이스를 구현하기 전에 STT 엔진·모델·설정을 같은 오디오로 비교하는
로컬 실험 하네스다. `web-dashboard/`와 별도 프로세스로 실행하며, 대시보드 코드는
수정하지 않는다. 화면은 FastAPI가 정적 HTML을 직접 서빙하므로 npm, Vite,
`node_modules`가 필요 없다.

## Windows에서 실행

Python 3.10 이상을 권장한다. 저장소 루트에서 다음 명령을 실행한다.

```powershell
cd stt-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m server.main
```

브라우저에서 <http://localhost:8799>를 연다. 기본 포트는 기존 대시보드의
5173, 8787~8788과 겹치지 않는 8799다. 바꾸려면 실행 전에
`$env:STT_LAB_PORT = "8800"`처럼 지정한다.

처음 모델을 선택해 전사하면 Hugging Face에서 모델을 내려받기 때문에 오래 걸릴 수
있다. 같은 프로세스에서 같은 모델을 다시 쓰면 메모리 캐시를 사용하며, 화면에는 모델
로드 시간과 실제 추론 시간이 분리되어 표시된다. 기본 모델은 `large-v3-turbo`다.

## GPU와 모델 캐시

faster-whisper는 PyTorch가 아니라 CTranslate2 기반이므로 `torch`를 별도로 설치하지
않는다. CUDA 장치가 보이면 `cuda/float16`, 아니면 `cpu/int8`을 자동 선택한다.
Windows에서 GPU를 쓰려면 NVIDIA 드라이버와 CTranslate2가 요구하는 CUDA 12 및
cuDNN 9 런타임 DLL이 실행 환경에서 보여야 한다.

CUDA 장치가 탐지됐더라도 cuBLAS/cuDNN DLL 누락 등으로 모델 로드나 첫 추론이
실패하면 서버는 CPU/int8로 한 번 자동 재시도한다. 이때 폴백 사유가 화면 상단에
표시된다. CPU로 폴백한 사실을 확인하지 않고 GPU RTF로 해석하면 안 된다.

캐시는 기본 Hugging Face 위치(`HF_HOME` 포함)를 사용한다. 전용 위치가 필요하면:

```powershell
$env:STT_LAB_MODEL_DIR = "D:\stt-models"
python -m server.main
```

## 실험 방법

1. registry에서 자동 생성된 시험 발화를 골라 정답 텍스트를 채운다.
2. 문장을 읽어 녹음하거나 기존 오디오 파일을 올려 전사한다.
3. 누적 비교표의 행을 클릭해 같은 오디오를 선택한다.
4. 모델, hotwords, VAD, initial prompt, beam size 중 비교할 설정만 바꾸고
   **같은 오디오 재실행**을 누른다.
5. CER과 RTF뿐 아니라 세그먼트·단어 확률 분포를 함께 보고 CSV로 내보낸다.

오디오는 `samples/`, 실행 기록은 `results/runs.jsonl`에 남는다. 두 폴더에는 음성과
발화 원문이 들어갈 수 있고 장비별 측정값도 섞이므로 Git에는 올리지 않는다.

registry는 복사하지 않고 실행할 때마다
`../web-dashboard/mock-gateway/registry.json`을 읽는다. 다른 파일을 쓰려면 절대 경로로
지정한다.

```powershell
$env:STT_LAB_REGISTRY = "D:\experiment\registry.json"
```

## 수치 해석과 REQ-1306 임계값

- `avg_logprob`: 세그먼트 토큰의 평균 로그 확률이다. 0에 가까울수록 모델이 더
  확신한 결과지만, 이것만으로 명령의 정오를 판정할 수 없다.
- `no_speech_prob`: 해당 세그먼트가 무음일 확률이다. 높을수록 무음 환각 후보지만
  VAD와 엔진의 `no_speech_threshold` 영향을 함께 받는다.
- 단어 `probability`: 단어 타임스탬프 생성 과정의 단어별 확률이다. 낮은 단어를
  화면에서 강조해 오인식 위치를 찾는다.
- `CER`: 공백을 제외한 한글 음절 단위 편집거리 비율이다. 명령 인식의 주 지표다.
  자모 CER은 종성 하나의 오류와 음절 전체 오류를 구분하는 참고치다.
- `WER`: 어절 단위 참고치다. 한국어는 조사 차이도 단어 전체 오류가 되어 CER보다
  과하게 나쁠 수 있다.
- `RTF`: 추론 시간 / 오디오 길이다. 1 미만이면 오디오 재생 시간보다 빠르다. 모델
  최초 로드 시간은 포함하지 않는다.

REQ-1306의 임계값은 한두 발화나 화면의 기본 강조값으로 정하지 않는다. 정답/오답,
짧은 명령/무음/소음, hotwords 및 VAD on/off를 같은 오디오로 반복 측정한 뒤 CSV에서
`min_avg_logprob`, `max_no_speech_prob`, `min_word_prob` 분포를 비교한다. 오답을
얼마나 거르는지뿐 아니라 정답을 잘못 거부하는 비율도 함께 보고 임계값을 확정해야 한다.

## 알려진 실패와 확인 순서

- 짧은 발화 반복·환각: `condition_on_previous_text=False`로 고정돼 있다. 그래도
  반복되면 VAD on/off와 무음 구간 길이를 비교한다.
- 무음 구간 환각: VAD를 켠 결과와 끈 결과의 `duration_after_vad`,
  `no_speech_prob`를 비교한다.
- 모델 다운로드 실패: 인터넷 연결, Hugging Face 캐시 쓰기 권한,
  `STT_LAB_MODEL_DIR` 경로를 확인한다.
- CUDA DLL 오류: 화면의 CPU 폴백 사유를 확인하고 CUDA 12/cuDNN 9 설치 및 PATH를
  점검한다. CPU에서도 실험은 계속할 수 있지만 RTF는 GPU 결과와 섞지 않는다.
- 오디오 디코딩 실패: wav, mp3, m4a, webm/opus 파일인지 확인한다.
- 포트 충돌: `STT_LAB_PORT`를 비어 있는 포트로 바꾼다.
- registry 없음: 저장소 배치가 달라졌다면 `STT_LAB_REGISTRY`를 지정한다.

## 다른 STT 엔진 붙이기 (REQ-1302)

1. `server/engines/`에 `SttEngine` 프로토콜을 구현한 파일 하나를 추가한다.
2. 구현 인스턴스를 `register_engine(...)`으로 등록한다.
3. `server/engines/__init__.py`의 `_ENGINE_MODULES`에 모듈 경로 한 줄을 추가한다.

라우터와 UI에는 엔진별 분기문을 추가하지 않는다. 지원하는 모델과 런타임 정보는
프로토콜을 통해 `/api/models`에 자동 노출되고, 지원하지 않는 옵션은 결과의
`applied_options`에서 제외해 실제 적용 여부가 드러나게 한다.

## API 요약

- `GET /api/models`: 엔진별 모델 목록, device/compute type, 폴백 상태
- `GET /api/vocab`: registry의 `display_name`과 `aliases[]`에서 만든 hotwords
- `GET /api/presets`: registry 조합 시험 발화
- `POST /api/transcribe`: 오디오 전사와 세그먼트·단어 확률, RTF
- `POST /api/score`: 음절 CER, 자모 CER, WER
- `GET /api/runs`: 누적 JSON 기록
- `GET /api/runs.csv`: Excel용 UTF-8 BOM CSV
