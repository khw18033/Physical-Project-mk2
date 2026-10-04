# 레이더 브리지(cansar_pi.py) — 드론 쪽 제안 (2026-10-04)

레이더 팀의 `cansar_pi.py` v3 · `cansar.service` 에 드론 쪽이 바라는 것만 더한 판입니다. 바뀐 줄은 모두 `# [드론 쪽 제안 10/4]`
표시가 있고, 차이만 보려면 `cansar_pi.diff` 를 보면 됩니다. **기존 동작(명령줄 · 파일 이름 · events/passes 열)은 그대로**이고
열을 지우거나 순서를 바꾸지 않았습니다(passes.csv 끝에 두 칸만 더함).

| | 무엇 | 왜 |
|---|---|---|
| ① | `--ack` (기본 `/home/physical/CAP_ACK`): SDR 캡처를 실제로 켠 직후 그 시각, 끈 직후 지움 | 드론이 레이더 지연을 재 다음 패스부터 그만큼 미리 켠다 |
| ② | events.csv `pi_epoch` 를 SSH **응답 시각**으로(요청 시각은 note 의 `req=`, 왕복 `rtt=`). 캡처 중 `--clock` 초마다 `clock` 행 | 요청 시각은 SSH 접속(수백 ms) 전이라 SDR 이 uptime 을 읽은 순간과 그만큼 어긋난다. 시계 행 여러 개로 직선을 맞추면 0.01 s 눈금 · 흐름까지 잡힌다 |
| ③ | SSH ControlMaster(연결 한 번 열어 두고 다시 씀) | 명령마다 접속하던 지연 · 들쭉날쭉이 수십 ms 안으로 |
| ④ | passes.csv 끝에 `pass` · `flight` — 드론 비행 프로그램이 CAP_ON 안에 적은 JSON 에서 | 드론 패스와 캡처를 시각 짐작 없이 짝짓는다 |
| ⑤ | `cansar.service` 에 `--rtcm-port 0` | RTK 보정 중계가 드론 쪽 `sar-rtk` 와 겹친다(같은 UDP 14660). 하나만 — 아래 |

## RTK 중계는 하나만

**지금(레이더 팀이 실험 데이터를 받는 동안)은 이 브리지의 RTK 중계를 그대로 씁니다.** 드론 쪽 `sar-rtk` 는 기본값
`SAR_RTK_RELAY=auto` 라서 이 브리지가 중계 중이면 포트도 안 잡고 비켜 있습니다(상태판 텔레메트리만). 통합 비행 때 합의하고
실험 사이에 바꿉니다: 이 서비스에 `--rtcm-port 0`, 드론 쪽 `SAR_RTK_RELAY=on`, 땅에서 RTK Fixed 확인.


이 브리지도 UDP 14660 으로 받은 RTCM 을 FC 에 넣고, 드론 쪽 `sar-rtk`(rtk_relay)도 같은 일을 합니다. 둘 다 켜면 포트를 다투거나
보정이 두 번 들어갑니다. 드론 쪽을 권합니다 — 화면(RTK 상태)에 보정 수신 · 주입 상태가 나오고 시험이 있습니다. 브리지 쪽을 쓰기로 하면
`--rtcm-port 0` 을 빼고 드론 쪽 `sudo systemctl disable --now sar-rtk`. 드론 쪽 `install.sh --status` 가 겹치면 알려 줍니다.

## 시험

SDR 보드 없이 가짜 SDR(`tests/fake_sdr/sshpass`)로 원본 · 제안 둘 다 돌려 봅니다(`tests/test_cansar_pi.py`): CAP_ON 으로 켜고 끄면
events start · stop, passes.csv, ~/flight 복사 — 제안은 여기에 CAP_ACK · clock 행 · pass/flight 칸까지 확인합니다.
드론 쪽 영상 처리(`sar_image/cansar.py`)는 clock 행이 있으면 그것으로 시각을 맞추고, 없으면 지금처럼 start 행 하나로 합니다.
