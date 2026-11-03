# 상태 스냅샷 검토 페이지

오늘의 핵심 계약 — 통합 상태 스냅샷(구역 B~I) · 계층별 자원 실측 · 임계 감시 ·
서브태스크 산출의 capability 접지 · 상황 기반 임무 추천 — 을 **한 장**에서 확인한다.

```bash
python tools/snapshot_ui/serve.py                      # http://127.0.0.1:8770
python tools/snapshot_ui/serve.py --static out.html    # 서버 없이 열리는 사본
```

## 운영 UI 가 아니다

운영 화면은 가시화 파트가 만든다(AI-C-19). 이 페이지는 "방금 만든 계약이 화면에
올라가는 모양인가"를 확인하는 자리까지이고, 그래서 두 가지를 일부러 한다.

- **조회 전용.** GET 만 받고 쓰기는 405 + 사유 토큰이다. 상태 뷰 경로로 실행을 바꿀
  수단을 주지 않는다(기능정의서 §1.1).
- **실측과 예시를 섞지 않는다.** 응답의 `live_sections` 가 이 기계에서 실제로 읽은
  묶음을 말하고 화면이 배지를 붙인다. 섞어 보여 주면 데모가 실제보다 잘 도는 것처럼
  보인다.

## 무엇이 실측인가

| 묶음 | 출처 |
|---|---|
| `accelerators` · `board` | `observability/host_resources.py` — psutil · nvidia-smi |
| `events`(RESOURCE) · `verdicts[].resource` | `observability/resource_watch.py` — 같은 판정에서 둘이 나온다 |
| `services` | 예시 서비스를 실측 가속기에 다시 얹은 것 |
| 그 밖 | 커밋된 예시 장면(`schemas/ai/examples/status-snapshot.json`, 생산 코드가 만든 것) |

작업 그래프를 실측으로 채울 수 없는 이유는 그래프가 미션이 들어와야 생기고 그 생성이
가시화 파트의 계약이기 때문이다 — 우리는 소비한다(AI-B-12).

## 엔드포인트

| 경로 | 무엇 |
|---|---|
| `/` | 페이지 |
| `/api/snapshot` | `{message, live_sections, read_at}` — `message` 는 계약 그대로의 와이어 메시지 |
| `/api/proposal?goal=…` | 접지된 단계 · 거부 사유 · 외부 개발 요청 후보 |
| `/api/recommendation` | 임무 후보 — 막힌 것과 그 사유까지 |

외부 자원(CDN·폰트)을 전혀 불러오지 않는다. 폐쇄망에서도 뜬다.
