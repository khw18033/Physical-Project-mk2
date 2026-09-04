# gen-lab — 생성 서비스 (지금은 스텁)

발화에서 임무 객체를 만드는 서비스다 (`VZ-G-01` 마일스톤 분리 · `VZ-G-02` 태스크 DAG).
`stt-lab`·`viz-debugger/stt` 와 **같은 패턴**이다 — 모델은 브라우저에 들어가지 않는다.

| | STT | 생성 |
|---|---|---|
| 프로세스 | `viz-debugger/stt` FastAPI · 8801 | **`gen-lab` FastAPI · 8802** |
| 경계 파일 | `viz-debugger/src/stt/SttClient.ts` | **`viz-debugger/src/generate/LlmClient.ts`** |
| 주소 | 연결 관리(`VZ-C-07`) + 환경변수 기본값 | 동일 — `CONNECTION_TARGETS` 의 `generate` |
| 꺼져 있으면 | 음성만 꺼짐 (`verify:no-stt`) | **생성만 꺼짐 (`verify:no-llm`)** |

## 지금은 스텁이다 — 엔진이 없다

**모델이 아직 정해지지 않았다.** 지시서 §4 가 「모델 후보를 둘 이상 같은 정답셋으로
잰다」고 적었고 그 비교가 아직 없다.

엔진 없이 먼저 세운 이유는 그 앞의 것들이 **엔진과 무관하게 정해져야 하기 때문**이다 —
경계(어디까지가 서비스인가) · 계약(무엇을 주고받는가) · 꺼짐(없으면 무엇이 꺼지는가).
엔진을 먼저 붙이면 그 셋이 엔진 모양에 맞춰 굳는다.

**스텁이 실제로 하는 일은 계약 검증 하나다.** 받은 문법 지문을 기록하고, 고정 응답을
`contracts/mission.schema.json` 으로 검증해 결과를 그대로 돌려준다.

고정 응답은 **정답셋을 베껴 오지 않는다.** 정답을 그대로 돌려주면 채점기가 만점을 내고,
그 만점이 「스텁이라서」인지 「모델이 잘해서」인지 구별되지 않는다. 계약만 만족하는
최소 임무 하나를 돌려준다 — 스키마 축은 통과하고 나머지 축은 낮게 나오는 것이 정직한 모습이다.

**목임을 감추지 않는다.** `/generate/health` 가 `engine: "stub"` 을 돌려주고 응답의
`extra.stub` 이 `true` 다.

## 실행

Python 3.10 이상. 저장소 루트에서:

```powershell
cd gen-lab
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m server.main
```

`http://127.0.0.1:8802/generate/health` 를 열면 무엇이 떠 있는지 나온다.
포트를 바꾸려면 `$env:VIZ_GENERATE_PORT = "8803"` 처럼 지정하고, 화면 쪽은
상단 바의 **「연결 관리」** 에서 주소를 바꾼다 (다시 빌드하지 않는다 · `VZ-C-07`).

**띄우지 않아도 된다.** 화면은 그대로 뜨고 생성 경로만 꺼진다 —
그것을 `verify:no-llm` 이 검사한다.

## 면 둘

```
GET  /generate/health    무엇이 떠 있는가 (엔진·모델·읽은 계약 목록)
POST /generate/mission   발화 하나 → 임무 객체 + 계약 검증 결과
```

`SttClient` 는 전용 헬스 경로를 두지 않고 같은 경로에 GET 을 던져 405 를 살아 있음의
신호로 쓴다. 생성은 **「무엇이 떠 있는가」(스텁인가 엔진인가)를 화면이 적어야** 하므로
405 로는 부족해서 경로를 하나 두었다.

## 문법은 계약에서 뽑는다 — 손으로 쓴 문법 파일이 없다

`contracts/mission.schema.json` → GBNF 변환은 `viz-debugger/src/generate/gbnf.ts` 가 한다.
클라이언트가 뽑아 요청에 실어 보내므로 **부르는 쪽이 계약 밖 출력을 요구할 수 없다.**

`verify:gen-port` 가 검사하는 것 둘 — 손으로 쓴 문법 파일(`*.gbnf` 등)이 없는가,
계약을 고치면 문법이 따라 바뀌는가.

**엔진이 붙으면 서비스도 같은 계약에서 다시 뽑아 클라이언트가 보낸 지문과 대조해야 한다.**
지금은 스텁이라 받은 지문을 되돌려 주기만 한다 — 그때의 숙제로 남겨 둔 자리다.

## 계약을 베껴 두지 않는다

`server/main.py` 는 저장소 루트의 `contracts/` 를 직접 읽는다. gen-lab 안에 사본을 두면
저장소가 계속 피해 온 「두 벌이 조용히 갈라진다」가 그대로 난다.

검증기도 `jsonschema` 패키지를 끌어오지 않고 `contracts/` 가 실제로 쓰는 문법만 다루는
최소 구현을 안에 두었다 (`viz-debugger/scripts/lib/json-schema.mjs` 와 같은 범위).
못 다루는 키워드는 조용히 넘기지 않고 오류 목록에 적는다.

## 정답셋

`goldset/` — 대본 4편에서 뽑은 (발화 → 마일스톤 → 태스크) 쌍과 손으로 적은 발화 변형 16개.
만드는 것은 `viz-debugger/scripts/extract-goldset.mjs` 이고 **대본은 읽기만 한다.**
채점은 `npm run score:generation` (네 축을 따로 낸다).

## 엔진을 붙일 때

`server/engines/` 에 파일 하나를 더하고 `server/main.py` 가 그것을 고르게 한다.
**서버 파일에 엔진 이름이 나오면 안 된다** (`stt-lab/server/main.py` 와 같은 규칙 · REQ-1302).

`stt/engines/*.py` 처럼 원본에서 이식하는 것이 아니라 여기서 새로 쓴다 —
그래서 `verify:stt-port` 같은 바이트 동일성 검사가 이 폴더에는 없다.
