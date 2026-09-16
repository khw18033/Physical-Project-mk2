# pi1 가시화 중계 — §4.4 실제 유니티 경로 시험 보고

- 대상: pi1 `viz-nav-feed` (경로 사건 원천 = journal)
- 시험 시각: 2026-09-15 **12:20:49 ~ 12:24:33 KST** (기록 구간)
- 브리지: `go1-sdk` (12:02:13 기동, 11:58:19 빌드). 시험 직전에 로그 문구 세 개가 실행 바이너리에 있음을 `strings` 로 확인
- 앞선 문서: [§0 조사](viz-nav-feed-s0-report.md) · [구현 보고](viz-nav-feed-report.md)

## 요약

| # | 확인 항목 | 결과 |
|---|---|---|
| 1 | 짧은 경로 → `path_received` → 도착 → `path_done` 각 한 건 | **됨.** journal 줄 1건마다 사건 1건 |
| 2 | 경로 변경 → `path_cancel` → `path_received`, 새 id | **순서는 됨. 새 id 는 아님** — 유니티가 매 경로 `path_id=1` 을 보낸다. 게다가 **PATH_CANCEL 이 한 번에 2~3개씩** 오고, 그때마다 **15100 estop=1** 도 함께 온다 |
| 3 | CHUNK 로 쪼개지는 긴 경로 → `path_received` 한 건 | **확인 못 함.** 시험 동안 CHUNK 패킷이 0개였다. 긴 경로(1472 B 넘는 JSON)도 유니티가 CHUNK 없이 한 데이터그램으로 보냈고(IP 단편화), 그 경로들도 `path_received` 는 각 한 건이었다 |
| 4 | journal 시각과 `nav_event.ts_ms` 나란히 | `ts_ms` = journal 줄 시각 (**31건 모두 일치**). 발행은 로그 시각보다 **1~481 ms (평균 190 ms)** 늦다 — journald 가 줄을 묶어 내보내기 때문 |

- 기록 구간 사건 수: `path_received` 6 · `path_cancel` 12 · `path_done` 1 · `estop` 12. journal 줄 수(activated 6 · PATH_CANCEL 12 · done 1)와 **정확히 같다.**
- 15110 으로 온 PATH_CANCEL 패킷 12개 = journal PATH_CANCEL 줄 12개 = `path_cancel` 12건. 빠진 것도, 겹친 것도 없다.
- 중계 오류·경고 로그 0건. 중계는 보기만 했고 설정은 바꾸지 않았다.

---

## 1. 짧은 경로 한 건 — 도착까지

```
12:22:54.813 UDP15110 192.168.50.244->192.168.50.243 871B JSON type=go1_path path_id=1 points=3
12:22:54.931 JOURNAL jts=1789442574815 [PATH] activated id=1 waypoints=2 anchor_yaw=16.30deg
12:22:54.932 NAV_EVENT {"seq": 16, "ts_ms": 1789442574815, "event": "path_received", "path_id": 1, "point_count": 2, "source": "journal", "note": ""}
12:23:00.119 JOURNAL jts=1789442580119 [PATH] reached wp[0/2]
12:23:06.681 JOURNAL jts=1789442586367 [PATH] reached wp[1/2]
12:23:06.681 JOURNAL jts=1789442586367 [PATH] finished.
12:23:06.681 JOURNAL jts=1789442586367 [PATH] done notify sent (mode=99)
12:23:06.681 NAV_EVENT {"seq": 17, "ts_ms": 1789442586367, "event": "path_done", "path_id": 1, "point_count": null, "source": "journal", "note": ""}
```

- `path_received` 1건, `path_done` 1건.
- `point_count` 2 는 브리지 waypoint 수다. 유니티 JSON 의 points 는 3개였다(구현 보고 §6-7 대로).
- 기록 구간에서 도착까지 간 경로는 이 한 건뿐이다. 12:24:26 에 받은 15-waypoint 경로는 기록을 멈출 때 진행 중이었다(`reached wp[0/15]`).

## 2. 이동 중 경로 변경

### 2.1 관찰 (12:22:15 ~ 12:22:23)

```
12:22:16.181 JOURNAL jts=1789442535929 [PATH] activated id=1 waypoints=7 anchor_yaw=-0.01deg
12:22:16.182 NAV_EVENT {"seq": 2, "ts_ms": 1789442535929, "event": "path_received", "path_id": 1, "point_count": 7, "source": "journal"}
12:22:17.697 UDP15110 ... 14B PATH_CANCEL
12:22:17.698 NAV_EVENT {"seq": 3, "ts_ms": 1789442537697, "event": "estop", "path_id": 1, "source": "udp15100_estop"}
12:22:17.793 UDP15110 ... 14B PATH_CANCEL
12:22:17.793 NAV_EVENT {"seq": 4, "ts_ms": 1789442537793, "event": "estop", "path_id": 1, "source": "udp15100_estop"}
12:22:17.905 UDP15110 ... 14B PATH_CANCEL
12:22:17.905 NAV_EVENT {"seq": 5, "ts_ms": 1789442537905, "event": "estop", "path_id": 1, "source": "udp15100_estop"}
12:22:18.178 JOURNAL jts=1789442537697 [PATH] PATH_CANCEL received from Unity dynamic obstacle replan
12:22:18.178 JOURNAL jts=1789442537793 [PATH] PATH_CANCEL received from Unity dynamic obstacle replan
12:22:18.178 JOURNAL jts=1789442537905 [PATH] PATH_CANCEL received from Unity dynamic obstacle replan
12:22:18.178 NAV_EVENT {"seq": 6, "ts_ms": 1789442537697, "event": "path_cancel", "path_id": 1, "source": "journal", "note": "path_active_before=false"}
12:22:18.179 NAV_EVENT {"seq": 7, "ts_ms": 1789442537793, "event": "path_cancel", "path_id": 1, "source": "journal", "note": "path_active_before=false"}
12:22:18.179 NAV_EVENT {"seq": 8, "ts_ms": 1789442537905, "event": "path_cancel", "path_id": 1, "source": "journal", "note": "path_active_before=false"}
12:22:23.840 UDP15110 ... 1392B JSON type=go1_path path_id=1 points=6
12:22:23.845 JOURNAL jts=1789442543843 [PATH] activated id=1 waypoints=5 anchor_yaw=-13.64deg
12:22:23.846 NAV_EVENT {"seq": 9, "ts_ms": 1789442543843, "event": "path_received", "path_id": 1, "point_count": 5, "source": "journal"}
```

같은 모양이 12:22:50(취소 3 → 12:22:54 새 경로), 12:24:00(경로 → 140 ms 뒤 취소 3 → 12:24:07 새 경로), 12:24:17(취소 3 → 12:24:26 새 경로)에 반복됐다.

### 2.2 확인된 것과 다른 것

| 항목 | 결과 |
|---|---|
| 순서 `path_cancel` → `path_received` | **맞다** (`ts_ms` 기준) |
| 새 경로의 id | **다르지 않다.** 기록된 6개 경로가 모두 `path_id=1` — 유니티가 id 를 올리지 않는다. 가시화는 id 로 회차를 가를 수 없고 `path_received` 순서(`seq`)로 세야 한다 |
| 취소 한 번에 PATH_CANCEL 수 | **2~3개**, 약 0.1초 간격. 브리지가 받은 그대로 journal 에 줄마다 찍으므로 `path_cancel` 도 2~3건 나간다. 계약대로의 동작이지만, 가시화가 「재탐색 시작」을 건마다 세면 한 번의 재탐색이 2~3회로 보인다 |
| 함께 오는 `estop` | 유니티가 **PATH_CANCEL 과 같은 ms 에 15100 으로 `0.000 0.000 0.000 1`** 을 보내고 15~35 ms 뒤 `0` 으로 돌린다. 계약 정의(15100 0→1)대로 **`estop` 이 PATH_CANCEL 마다 1건씩** 나간다 (아래 원본) |
| `path_active_before` | 대부분 `false`. 캡처로 먼저 온 `estop` 이 `path_active` 를 끄고, journal 의 `path_cancel` 은 그 뒤에 처리되기 때문 |

15100 원본 (값이 바뀐 순간만, 12:24 구간):

```
12:24:00.978 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:00.978
12:24:01.007 192.168.50.244 '0.000 0.000 0.000 0'
12:24:01.089 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:01.089
12:24:01.123 192.168.50.244 '0.000 0.000 0.000 0'
12:24:01.187 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:01.187
12:24:01.204 192.168.50.244 '0.000 0.000 0.000 0'
12:24:17.790 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:17.790
12:24:17.825 192.168.50.244 '0.000 0.000 0.000 0'
12:24:17.909 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:17.909
12:24:17.930 192.168.50.244 '0.000 0.000 0.000 0'
12:24:18.029 192.168.50.244 '0.000 0.000 0.000 1'   ← PATH_CANCEL 12:24:18.029
12:24:18.044 192.168.50.244 '0.000 0.000 0.000 0'
```

(12:22 구간 취소는 이 기록기를 켜기 전이라 원본이 없다. 다만 중계 코드상 `udp15100_estop` 은 목적지 15100 이고 4번째 필드가 1 인 데이터그램에서만 나오고, 시각 짝도 12:24 구간과 같은 모양이다.)

### 2.3 발행 순서가 사건 순서와 다를 수 있다

12:24:00 구간:

| seq | event | source | ts_ms | 발행 시각 |
|---|---|---|---|---|
| 18 | estop | udp15100_estop | …640978 | 12:24:00.978 |
| 19 | estop | udp15100_estop | …641089 | 12:24:01.089 |
| 20 | path_received | journal | **…640839** | 12:24:01.091 |
| 21 | path_cancel | journal | …640979 | 12:24:01.093 |
| 22 | path_cancel | journal | …641089 | 12:24:01.093 |

- 캡처 원천(`estop`)은 즉시 나가고, journal 원천은 최대 약 0.5초 늦게 나간다.
- 그래서 **`seq`(발행 순서)와 `ts_ms`(일어난 순서)가 어긋날 수 있다.** 여기서는 `path_received`(ts …839)가 그보다 늦게 일어난 `estop`(ts …978) 뒤에 발행됐다.
- 가시화가 순서를 따지려면 `ts_ms` 로 정렬해야 한다.

## 3. CHUNK 긴 경로

**확인 못 함.** 기록 구간에 15110 CHUNK 패킷은 0개였다.

긴 경로는 CHUNK 없이 한 데이터그램으로 왔다.

| 시각 | 첫 조각 크기 | 결과 |
|---|---|---|
| 12:22:15.925 | 1472 B (= MTU 1500 − 28, IP 단편화된 첫 조각) | `activated id=1 waypoints=7` → `path_received` 1건 |
| 12:24:00.833 | 1472 B | `waypoints=8` → `path_received` 1건 |
| 12:24:07.659 | 1472 B | `waypoints=7` → `path_received` 1건 |
| 12:24:26.579 | 1472 B | `waypoints=15` → `path_received` 1건 |

- 브리지는 커널이 재조립한 데이터그램을 받아 정상 활성화했다.
- 중계는 journal 원천이라 단편화와 무관하다.
- 참고로 capture 대안 원천이었다면 단편화된 경로는 해석하지 않으므로(구현 보고 §6-8) `path_received` 가 **안 나왔을 것이다.** journal 원천을 쓴 판단이 여기서도 맞았다.
- CHUNK 재조립은 §4.2 흉내 패킷 시험(capture 원천)에서만 확인됐다. 실제 CHUNK 를 보려면 유니티 쪽에서 CHUNK 전송이 켜진 설정으로 다시 해야 한다.

## 4. journal 시각 · `nav_event.ts_ms` · 받은 시각

`받음` = 기록기가 로컬 브로커에서 `nav_event` 를 받은 pi1 시각. journal 원천 사건은 `ts_ms` = journal 줄 시각(`__REALTIME_TIMESTAMP`)이고, 기록 구간 31건 모두 일치했다.

| 받은 시각 | seq | event | path_id | point_count | source | ts_ms | 받음 − ts_ms (ms) | note |
|---|---|---|---|---|---|---|---|---|
| 12:22:16.182 | 2 | path_received | 1 | 7 | journal | 1789442535929 | 253 |  |
| 12:22:17.698 | 3 | estop | 1 | null | udp15100_estop | 1789442537697 | 1 |  |
| 12:22:17.793 | 4 | estop | 1 | null | udp15100_estop | 1789442537793 | 0 |  |
| 12:22:17.905 | 5 | estop | 1 | null | udp15100_estop | 1789442537905 | 0 |  |
| 12:22:18.178 | 6 | path_cancel | 1 | null | journal | 1789442537697 | 481 | path_active_before=false |
| 12:22:18.179 | 7 | path_cancel | 1 | null | journal | 1789442537793 | 386 | path_active_before=false |
| 12:22:18.179 | 8 | path_cancel | 1 | null | journal | 1789442537905 | 274 | path_active_before=false |
| 12:22:23.846 | 9 | path_received | 1 | 5 | journal | 1789442543843 | 3 |  |
| 12:22:50.122 | 10 | estop | 1 | null | udp15100_estop | 1789442570122 | 0 |  |
| 12:22:50.181 | 11 | path_cancel | 1 | null | journal | 1789442570123 | 58 | path_active_before=false |
| 12:22:50.228 | 12 | estop | 1 | null | udp15100_estop | 1789442570228 | 0 |  |
| 12:22:50.353 | 13 | estop | 1 | null | udp15100_estop | 1789442570338 | 15 |  |
| 12:22:50.626 | 14 | path_cancel | 1 | null | journal | 1789442570229 | 397 | path_active_before=false |
| 12:22:50.628 | 15 | path_cancel | 1 | null | journal | 1789442570339 | 289 | path_active_before=false |
| 12:22:54.932 | 16 | path_received | 1 | 2 | journal | 1789442574815 | 117 |  |
| 12:23:06.681 | 17 | path_done | 1 | null | journal | 1789442586367 | 314 |  |
| 12:24:00.978 | 18 | estop | 1 | null | udp15100_estop | 1789442640978 | 0 |  |
| 12:24:01.089 | 19 | estop | 1 | null | udp15100_estop | 1789442641089 | 0 |  |
| 12:24:01.091 | 20 | path_received | 1 | 8 | journal | 1789442640839 | 252 |  |
| 12:24:01.093 | 21 | path_cancel | 1 | null | journal | 1789442640979 | 114 | path_active_before=true |
| 12:24:01.093 | 22 | path_cancel | 1 | null | journal | 1789442641089 | 4 | path_active_before=false |
| 12:24:01.188 | 23 | estop | 1 | null | udp15100_estop | 1789442641187 | 1 |  |
| 12:24:01.431 | 24 | path_cancel | 1 | null | journal | 1789442641189 | 242 | path_active_before=false |
| 12:24:07.664 | 25 | path_received | 1 | 7 | journal | 1789442647663 | 1 |  |
| 12:24:17.790 | 26 | estop | 1 | null | udp15100_estop | 1789442657790 | 0 |  |
| 12:24:17.910 | 27 | estop | 1 | null | udp15100_estop | 1789442657909 | 1 |  |
| 12:24:17.932 | 28 | path_cancel | 1 | null | journal | 1789442657791 | 141 | path_active_before=false |
| 12:24:17.932 | 29 | path_cancel | 1 | null | journal | 1789442657911 | 21 | path_active_before=false |
| 12:24:18.029 | 30 | estop | 1 | null | udp15100_estop | 1789442658029 | 0 |  |
| 12:24:18.294 | 31 | path_cancel | 1 | null | journal | 1789442658029 | 265 | path_active_before=false |
| 12:24:26.583 | 32 | path_received | 1 | 15 | journal | 1789442666581 | 2 |  |

- journal 원천 발행 지연: **최소 1 ms · 최대 481 ms · 평균 190 ms**
- 캡처 원천(`estop`) 발행 지연: 0~15 ms
- 가시화 PC 는 pi1 보다 약 2.25초 늦으므로(pi1 은 NTP 오차 0.08 ms), 가시화가 잰 「받음 − ts_ms」에는 이 값에 −2.25초가 더해져 보일 것이다

---

## 5. 가시화 쪽에 알릴 것 · 결정할 것

1. **`path_id` 로 경로를 가를 수 없다.** 유니티가 늘 `1` 을 보낸다. 회차는 `path_received` 건수(`ts_ms` 순)로 센다. id 를 올리게 하려면 유니티 쪽 수정이 필요하다.
2. **재탐색 한 번 = `path_cancel` 2~3건 + `estop` 2~3건.**
   - 가시화가 「재탐색 시작」을 건마다 세지 않도록, 짧은 간격(예: 0.5초 안)으로 이어지는 `path_cancel` 은 한 번으로 묶기를 권한다.
   - PATH_CANCEL 과 같은 순간(수십 ms 안)에 온 `estop` 은 **비상정지가 아니라 유니티의 취소용 정지 명령**이다. 가시화가 `estop` 을 경보로 보인다면 이 짝은 거르기를 권한다.
   - 중계에서 거르려면 계약 변경이다(`estop` 정의). 결정해 주면 중계를 고친다. 지금은 계약 그대로 둔다.
3. **순서는 `ts_ms` 로 정렬해야 한다.** 원천별 발행 지연이 달라(journal 최대 약 0.5초) `seq` 와 사건 순서가 어긋날 수 있다(2.3).
4. **CHUNK 는 실측 못 했다.** 현재 유니티 설정은 긴 경로도 CHUNK 없이 보낸다. CHUNK 를 켠 설정으로 볼 필요가 있으면 다시 시간을 잡는다.

## 6. 시험 방법 (재현용)

- 모두 **수동**이다. bind 한 포트 없음, 유니티·브리지·로봇으로 보낸 것 없음, 중계·브리지 설정 변경 없음.
- 기록기(스크래치패드, sudo):
  - `journalctl -u go1-sdk -f -n 0 -o json` 의 `[PATH]` 줄
  - `mosquitto_sub -t '+/robot/+/nav_event'`
  - `AF_PACKET` 으로 15110 목적지 패킷 요약
  - 15100 값이 바뀐 순간 (12:23:07 부터)
- 기록 끝난 뒤 기록기 두 개는 모두 멈췄다. 중계(`viz-nav-feed`)는 그대로 가동 중이다.
- 원본 로그: `rec44.log` · `tele15100.log` (세션 스크래치패드 — 세션이 끝나면 지워진다. 필요하면 보관 위치를 알려 달라)
