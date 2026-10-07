# server_stream_multi_source.py — 받은 시각을 넣기 전(원본)의 모습

2026-10-07

- 대상: `data_stream/server_stream_multi_source.py` 원본 (1,450줄 · md5 `53c2540d8ba25328028f9acb8432fff0`)
  - `360camera_work/` · `261002 임시모음집/data_stream/` 에 있는 같은 이름 파일도 이 원본과 같다 (md5 같음).
- 같이 둔 파일: `apply_received_at.py` — 이 원본에 받은 시각 칸(`edge_received_at`)을 넣는 스크립트 (§6)
- 행 번호는 전부 원본 기준이다.

---

## 0. 요약

- 원본은 **이 파일이 데이터를 받은 시각을 어디에도 적지 않는다.** 시각은 보내는 쪽이 붙여 보낸 것을 그대로 옮길 뿐이다 (영상은 `sender` 안, state는 `payload` 안).
- 이 파일이 스스로 붙이는 것은 저장 번호 `n` · 저장 경로 `file` · 들어온 길 `via` · 받은 기기 이름 `host` 뿐이다. 머리말에도 그렇게 적혀 있다 (12~13행: "시각·번호 같은 정보는 보내는 쪽이 붙인 것을 그대로 옮기고 … 이 파일이 붙이는 것은 저장 번호뿐이다").
- 받은 시각에 가까운 값은 Redis 항목 번호에만 남는다. 그것도 최근 약 300개뿐이고 파일에는 남지 않는다 (§3).
- 끊겼을 때의 동작(§4)은 패치와 상관없이 원본 그대로다.

---

## 1. 원본이 남기는 기록

### 1-1. `frames.jsonl` — 사진 한 장 = 한 줄

10-02 서버2 기록 (cam360 첫 줄 그대로):

```json
{"source": "cam360", "n": 1, "file": "cam360/20261002_040640/frames/000000001.jpg",
 "via": "upload:/upload_pano", "host": "sysai-server2",
 "sender": {"capture_id": "LIVE_STREAM", "camera_id": "pro2_anchor", "seq": "1",
            "timestamp": "1790918106.071032",
            "_file": {"field": "file", "filename": "equirect.jpg", "content_type": "image/jpeg"}}}
```

| 칸 | 누가 붙이나 | 뜻 |
|---|---|---|
| `source` | 이 파일 | 포트 이름 (`cam360` · `drone` · `robot1` · `robot2`) |
| `n` | 이 파일 | 이 실행에서의 저장 번호, 1부터 |
| `file` | 이 파일 | 저장한 jpg 경로. 저장에 실패하면 `null` |
| `via` | 이 파일 | 들어온 길: `upload:/upload_pano` · `pull:<주소>` · `push` |
| `host` | 이 파일 | 받은 기기 이름 |
| `sender` | 보낸 쪽 | 보낸 쪽이 준 정보 그대로 |
| `edge` | 이 파일 (`/push` 로 받았을 때만) | 넘겨준 기기 쪽의 `n` · `file` · `via` · `host` |

**받은 시각 칸은 없다.** 시각은 `sender` 안에만 있고, 소스마다 이름도 시계도 다르다.

| 소스 | `sender` 안의 시각 | 누구 시계 · 무슨 시각 |
|---|---|---|
| cam360 | `timestamp` (epoch 초, 글자) | 360 노트북 — 카메라 실시간 스트림에서 그 장을 받은 시각 (`stream_to_server.py` 458행) |
| drone | `ts` · `captured_at` · `observed_at` (epoch 초) | pi3 — 찍은 시각. 10-02 기록에서 세 값이 같다 |
| robot1 · robot2 | `X-Timestamp` (epoch 밀리초) · `X-Timestamp-Iso` | pi7 · pi1 — pi가 그 장을 내보낸 시각 |

근거: `261006_jsonl_이름통일안.md` "2번 작업으로 넘길 사실".

### 1-2. `states.jsonl` — state 한 건 = 한 줄

10-02 서버2 기록 (robot1 첫 줄, `payload` 는 줄임, 주소는 가림):

```json
{"n": 1, "topic": "zoneA/robot/go1-001/status", "qos": 1, "retain": true,
 "via": "pull:mqtt://<pi7>:1883", "host": "sysai-server2",
 "payload": "{\"schema_version\": \"1.1\", \"source_id\": \"go1-001\", … \"timestamp\": \"2026-10-02T14:10:33.073+09:00\", …}",
 "enc": "utf8"}
```

- 시각은 `payload` 안에 보낸 쪽이 넣은 `timestamp` 뿐이다. `payload` 는 받은 바이트를 글자로 그대로 둔 것이라, 꺼내려면 JSON 을 한 번 더 풀어야 한다.
- **받은 시각 칸은 없다.**
- `retain: true` 는 브로커가 들고 있던 마지막 값이 구독할 때 온 것이다. 받은 때보다 한참 전 값일 수 있는데, 원본 기록으로는 구분할 수 없다.
  - 예: 10-02 드론 `states.jsonl` 첫 줄의 `timestamp` 는 13:06:35이고, 그 실행이 시작된 것은 13:06:40이다 (실행 폴더 `20261002_040640` 은 UTC).

### 1-3. Redis

| 스트림 | 칸 |
|---|---|
| `camera_stream:<소스>` | `image` (jpg 바이트) · `header` (`frames.jsonl` 한 줄과 같은 JSON) · `sender` 안의 칸을 하나씩 펼친 것 |
| `state_stream:<소스>` | `topic` · `payload` (받은 바이트) · `header` (`states.jsonl` 한 줄에서 `payload` · `enc` 를 빼고 `source` 를 더한 JSON) |

- 항목 번호 `<밀리초>-<순번>` 의 앞부분은 **Redis 에 넣은 순간의 Redis 시계**다. Redis 는 기본으로 같은 기기(`127.0.0.1:6380`)에 있다.
- 원본에서 "받은 시각"에 가장 가까운 값이 이것이다 (한계는 §3).

### 1-4. `/push` 로 넘겨받은 기록 (엣지 → 서버)

- 서버는 넘겨받은 머리에서 정해진 칸만 `edge` 로 옮긴다.
  - 영상: `n` · `file` · `via` · `host` (930행)
  - state: `n` · `via` · `host` (937행)
- 서버 쪽 `n` · `file` · `via`(`"push"`) · `host` 는 서버가 새로 붙인다.
- 엣지가 받은 시각은 원본에서 애초에 없으므로 넘어갈 것도 없다.

```json
{"source": "cam360", "n": 1, "file": "cam360/<서버 실행>/frames/000000001.jpg",
 "via": "push", "host": "<서버>",
 "sender": { 엣지가 받은 그대로 },
 "edge": {"n": 1, "file": "cam360/<엣지 실행>/frames/000000001.jpg",
          "via": "upload:/upload_pano", "host": "<엣지>"}}
```

---

## 2. 원본 코드 — 패치가 손대는 다섯 곳

### 2-1. import (121~135행)

`datetime` 이 없다. 시각은 `time` 모듈로 로그 앞의 `[HH:MM:SS]` 와 실행 폴더 이름에만 쓴다.

```python
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
```

→ 패치 후: `from collections import deque`(132행) 다음에 `from datetime import datetime, timedelta, timezone`

### 2-2. 고정값 (167~168행)

```python
HOSTNAME = socket.gethostname()
STOP = threading.Event()
```

받은 시각을 만드는 함수가 없다.

→ 패치 후: 168행 다음에 `KST`(+09:00 고정)와 `received_now()`

### 2-3. `add_frame` (643~651행)

```python
    def add_frame(self, image, sender, via, edge=None):
        with self.lock:
            fh, fname, err = self._open_new()
            n = self.n_frame
            header = {"source": self.name, "n": n,
                      "file": self.rel + "/frames/" + fname,
                      "via": via, "host": HOSTNAME, "sender": sender}
            if edge:
                header["edge"] = edge
```

- 모든 영상이 이 함수를 지난다 (360 업로드 · 드론 당겨 오기 · GO1 MJPEG · `/push`).
- 머리(`header`)에 시각이 없다. 이 머리가 `frames.jsonl` 한 줄, Redis `header`, 넘기기 묶음에 똑같이 들어간다.

→ 패치 후: 첫 줄에서 `received_at = received_now()` (잠금 전), 머리의 `file` 다음에 `"edge_received_at"`

### 2-4. `add_state` (703~708행)

```python
    def add_state(self, topic, payload, qos, retain, via, edge=None):
        with self.lock:
            self.n_state += 1
            rec = {"n": self.n_state, "topic": topic, "qos": qos, "retain": retain, "via": via, "host": HOSTNAME}
            if edge:
                rec["edge"] = edge
```

- 모든 state(MQTT · `/push`)가 이 함수를 지난다. `rec` 이 `states.jsonl` 한 줄, Redis `header`, 넘기기 묶음이 된다.

→ 패치 후: 첫 줄에서 `received_at = received_now()`, `rec` 의 `topic` 다음에 `"edge_received_at"`

### 2-5. `/push` 받는 곳 (928~940행 중)

```python
                            if kind == b"F":
                                header, image = unpack_frame(data)
                                edge = dict((k, header.get(k)) for k in ("n", "file", "via", "host"))
```

```python
                            elif kind == b"S":
                                rec = json.loads(data.decode("utf-8"))
                                raw = rec.get("payload") or ""
                                payload = base64.b64decode(raw) if rec.get("enc") == "base64" else raw.encode("utf-8")
                                edge = dict((k, rec.get(k)) for k in ("n", "via", "host"))
```

→ 패치 후: 두 목록에 `"edge_received_at"` 을 더해, 넘겨준 쪽이 받은 시각을 `edge` 안에 남긴다.

### 2-6. 패치가 고치지 않는 곳 — 머리말 설명

- 12~13행 "이 파일이 붙이는 것은 저장 번호뿐이다"와 86~90행 헤더 예시.
- 패치 후에는 받은 시각도 붙이므로 설명과 코드가 어긋난다. 문서를 고칠 때 같이 고칠 거리다.

---

## 3. 원본에서 "받은 시각"을 알 수 있는 곳과 한계

| 어디 | 무엇 | 한계 |
|---|---|---|
| Redis 항목 번호 | Redis 에 넣은 순간의 Redis 시계 (밀리초) | 최근 약 300개만 남는다 (`--maxlen`). 메모리 한도를 넘으면 오래 안 쓴 키부터 지워진다. Redis 가 안 되면 아예 없다. 파일에 안 남는다 |
| 비전 결과 `recv_ms` | 위 항목 번호를 옮긴 값 | 비전 live 가 처리한 장만 있다 (최신 장만 처리하고 사이 장은 건너뜀). state 는 없다. 10-02: 360 4,796/4,816장 · 드론 1,025/1,293장 · state 0건 (`261006_jsonl_이름통일안.md` §7) |
| `frames/*.jpg` 파일 수정 시각 | 받은 직후에 쓰므로 사실상 받은 시각 | 기록이 아니라 파일 속성이다. 복사·압축 방법에 따라 바뀌거나 초 아래가 사라진다. state 는 해당 없음 |
| 실행 폴더 이름 | 실행을 시작한 시각 (기기 시간대) | 실행에 하나뿐. 서버2는 UTC라 `20261002_040640` 은 한국 13:06:40 |
| 화면 로그 `[HH:MM:SS]` | 연결 · 끊김 · 10초 보고 | 장마다가 아니고 파일도 아니다 |

이 때문에 원본으로는 다음을 할 수 없다.

- **state 의 말단 → DS 지연을 잴 수 없다.** Redis 항목 번호 말고는 받은 시각이 없고, 그것도 300건이 지나면 사라진다 (`261006_하천시나리오_데이터_전수분석.md` §2-3).
- retain 으로 온 오래된 state 를 받은 시각으로 가려낼 수 없다 (§1-2).
- 넘기기로 밀렸다가 들어온 사진은 서버 Redis 번호가 한꺼번에 몰린다. 엣지가 실제로 받은 시각은 어디에도 없다 (§4 실험 1).
- Pi 시계와 이 기기 시계의 차이를 실행 내내 따라갈 재료가 없다 (`261006_세카메라_같은시각_판별_점검.md` §4-5).

---

## 4. 끊겼을 때 — 원본 동작 (패치와 상관없이 그대로)

- **밀린 것을 다시 보내는 구간은 엣지 → 서버 넘기기 하나뿐이다.**
- 기기(파이 · 360 노트북) → 이 파일 구간은 다시 붙은 시점의 최신 장부터 받는다. 끊긴 동안의 장은 오지 않는다.
- 어느 구간이든 반쯤 받은 것은 저장하지 않는다.

| 구간 | 코드 | 끊기면 | 끊긴 동안의 데이터 |
|---|---|---|---|
| GO1 영상 (MJPEG 당겨 오기) | `robot_video_loop` 1014행~ | 다시 붙는다. 쉬는 시간은 0.5초 × 연속 실패 수, 최대 5초. 연결이 멈춰 있으면 10초(1022행) 뒤에 끊김으로 본다 | 안 온다. MJPEG 는 지금 장만 흘린다 |
| 드론 영상 (롱폴) | `drone_video_loop` 1055행~ | 연결을 새로 열어 다시 묻는다 (쉬는 시간은 위와 같음) | 안 온다. 드론 쪽이 최신 1장을 준다 (10-02 분석 문서 기준. 드론 쪽 코드는 이 폴더에 없어 직접 보지 못함) |
| 360 영상 (업로드) | `do_POST` 905~908행 | 본문을 끝까지 못 받으면 저장하지 않고 연결을 닫는다 | 안 온다. `stream_to_server.py` 는 실패해도 다시 보내지 않고 다음 최신 장을 보낸다 (469~478행). 360 노트북에 따로 저장하지도 않으므로 **영구 손실**이다. `seq` 는 실패해도 올라가므로 빠진 번호로 보인다 |
| state (MQTT) | `start_mqtt` 1132 · 1134 · 1163행 | 1~10초 간격으로 자동 재접속 | 안 온다 (`clean_session=True` — 브로커가 쌓아 두지 않음). retain 값만 다시 와서 한 번 더 저장된다 |
| 엣지 → 서버 넘기기 | `Forwarder` 516행~ | 보내던 묶음을 대기열 맨 앞에 되돌리고(585행) 다시 보낸다 | **다시 간다**, 순서대로. 단 아래 조건이 붙는다 |

넘기기의 조건

- 대기열은 소스마다 **300건**(163행)이고, 영상과 state 를 합쳐 센다. 넘치면 오래된 것부터 버린다 (엣지 디스크에는 남아 있다). GO1 처럼 state 가 많은 소스는 몇 초 분량이다.
- 대기열은 메모리에만 있다. 엣지 쪽 DS 를 끄면 남은 대기는 사라진다 (이것도 엣지 디스크에는 남아 있다).
- **같은 장이 두 번 갈 수 있다.** 서버가 저장을 마쳤는데 응답이 돌아오지 못하면(끊김, 15초 timeout 569행) 엣지는 실패로 보고 다시 보낸다. 서버에는 같은 장이 다른 `n` 으로 두 번 저장된다. 영상은 `edge.file` 로 거르면 된다 (엣지 실행 폴더 + 번호라 겹치지 않는다).
- 서버 쪽 DS 를 다시 켜면 실행 폴더가 새로 생기고, 밀린 장은 새 폴더로 들어간다.
- 서버의 `n` 과 Redis 번호는 서버에 들어온 순서와 시각이다. 밀린 장은 한꺼번에 들어오므로 시각이 몰린다.

실험 (10-07, 사본을 이 PC의 격리된 환경에서 띄움 — 360 업로드 흉내 · 가짜 서버 · 가짜 로봇 카메라)

| # | 한 일 | 결과 |
|---|---|---|
| 1 | 서버를 끈 채 엣지에 5장 → 서버 켬 | 5장 다 도착 (엣지 `n` 1~5). 패치본으로 해서 두 시각이 보였다: 서버가 받은 시각은 5장이 5ms 안에 몰렸고, 엣지가 받은 시각은 그보다 약 3초 앞이다. 원본이면 엣지 쪽 시각은 남지 않는다 |
| 2 | 서버를 끈 채 320장 → 서버 켬 | 300장 도착 (엣지 `n` 26~325). 6~25번 20장은 넘기기에서 버려짐 (`/health` 의 `dropped` 20). 엣지 디스크에는 325장이 다 있다 |
| 3 | 가짜 서버가 첫 묶음을 끝까지 받고 응답 없이 끊음 | 엣지가 1번 장을 다시 보냈다 (두 번째 묶음 = 1 · 2번). 진짜 서버였다면 1번이 두 번 저장된다 |
| 4 | 360 업로드 도중 끊음 (본문 길이를 100,000바이트로 알리고 일부만 보냄) | 아무것도 저장되지 않음 |
| 5 | 가짜 로봇 카메라가 1 · 2 · 3번을 보내고 4번 절반에서 끊음, 1초 뒤 다시 붙자 10 · 11번 | 저장된 것은 1 · 2 · 3 · 10 · 11번 (`n` 1~5). 4번 조각은 없고, 4~9번은 오지 않음 |

---

## 5. 패치 전후 비교

| | 원본 | 패치 후 |
|---|---|---|
| `frames.jsonl` | 받은 시각 없음 | `file` 다음에 `edge_received_at` |
| `states.jsonl` | 받은 시각 없음 | `topic` 다음에 `edge_received_at` |
| Redis `header` JSON | 받은 시각 없음 | 같은 칸. Redis 에 펼친 칸은 그대로 |
| `/push` 의 `edge` | 영상 `n` · `file` · `via` · `host` / state `n` · `via` · `host` | 둘 다 `edge_received_at` 추가 |
| 값 | — | 이 파일이 도는 기기의 시계. `+09:00` 고정, ISO 밀리초 (예 `2026-10-07T13:27:56.356+09:00`). 데이터를 다 받은 직후, 잠금 · 디스크 쓰기 전에 잰다 |
| 비전 결과 · `geo.py` | — | 그대로 (정해진 칸만 읽는다) |
| 끊김 동작 · 번호 · 저장 위치 | — | 그대로 |

- 이름은 `edge_received_at` 이지만 엣지 전용이 아니다. 서버에서 돌면 서버가 받은 시각이 들어간다 (이름사전 T-3: "엣지 · 데이터 스트림 서버가 받은 시각").
- 섞어서 띄웠을 때 (10-07 실험, 둘 다 에러 없음)
  - 엣지만 패치: 엣지가 받은 시각이 서버로 넘어가지 않는다 (엣지 디스크에만 남음).
  - 서버만 패치: `edge.edge_received_at` 이 `null`.
  - → **엣지 노트북과 서버 둘 다 적용해야** 엣지가 받은 시각이 서버까지 간다.

---

## 6. 같이 둔 스크립트 — `apply_received_at.py`

- 행 번호 대신 기준 줄의 글자로 8곳을 찾아 넣는다. 원본에 돌린 결과는 `261006_received_at.patch` 를 적용한 결과와 바이트까지 같다 (md5 `5783112ebe8c5b8aa1226cfeb213fe75`).
- 이미 들어간 곳은 건너뛴다. 한 곳이라도 못 찾으면 아무것도 쓰지 않는다.
- 쓰기 전에 같은 폴더에 `<파일>.bak_<YYMMDD_HHMMSS>` 로 백업하고, 문법 검사를 통과해야 바꿔 넣는다.
- 파이썬 3.6 이상, 추가 패키지 없음.

```
python apply_received_at.py --check "C:\Users\asdfa\physical mk2\data_stream"     ← 고칠 곳만 본다 (쓰지 않음)
python apply_received_at.py "C:\Users\asdfa\physical mk2\data_stream"             ← 적용
python3 apply_received_at.py <서버의 data_stream 폴더>                              ← 서버
```

- 되돌리기: 백업 파일을 원래 이름으로 복사한다.
- 돌고 있는 DS 는 껐다 켜야 적용된다.
- 10-07 확인: 지금의 `data_stream` 과 `360camera_work` 원본에 `--check` 를 돌리면 8곳 모두 넣을 수 있고, 결과 md5 가 패치본과 같다 (아무것도 쓰지 않음).
