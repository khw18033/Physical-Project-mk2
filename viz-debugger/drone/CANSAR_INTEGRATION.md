# CANSAR-2 연동 — 레이더 팀 코드(2026-10-04)를 드론 쪽에 붙인 것

레이더 팀에게 받은 `cansar_flight.py` · `cansar_quick.py` · README 세 개를 드론 쪽 시스템에 붙였습니다.
받은 파일은 `tests/data/cansar/` 에 그대로 두고 시험에 씁니다(고치지 않았습니다).

## 1. 레이더 팀이 부탁한 것 — 패스마다 quick-look 을 화면에

| 무엇 | 어떻게 |
|---|---|
| 돌리기 | Pi 의 드론 데이터 서버(`sar-data`)가 `passes.csv` 에 새 줄이 생기고 `iq_N.bin` · `meta_N.txt` 가 있으면 `cansar_quick.py --nopull …` 을 실행 (`sar_data/quick.py`) |
| 지킨 것 | `nice -n 19` · `--fine` 안 씀 · **CAP_ON 이 있으면 미룸** · 한 번에 하나 · 패스마다 따로 만든 작업 폴더(flight_img.png 겹침 없음) · 명령 형식과 `quick_N.png` · `quick_N.npz` 이름만 사용 |
| 화면 | SAR 패스 화면에 「레이더 팀 영상 · quick-look」 카드. 영상 · `[판정]` 줄 · `영상 첨두` 줄 · 처리 기록 · npz 받기 (`screenshots/34_레이더팀_quicklook.png`) |
| 노트북 · 서버 | 노트북 미러가 결과(png · npz · 기록)를 받아 가므로 Pi 에 직접 붙지 않아도 보입니다 |
| 실패 | 0 이 아닌 종료면 「실패」 + 마지막 오류 줄 + 처리 기록 링크 |

Pi 설정(`/etc/sar-drone.env`):

```bash
SAR_CANSAR_QUICK=/home/physical/<레이더 팀 폴더>/cansar_quick.py   # cansar_flight.py 와 같은 폴더
SAR_CANSAR_DATA=/home/physical/flight
SAR_CANSAR_LOGS=/home/physical/cansar_logs
SAR_CANSAR_SIDE=right            # 안테나가 보는 쪽 — 비행 전에 레이더 팀이 정한다
```

`sudo systemctl restart sar-data` 뒤 `curl http://<Pi>:8766/api/cansar` 로 목록이 보이면 됩니다.

## 2. 드론 쪽 영상 파이프라인에도 넣었다 — `sar_image/cansar.py`

그쪽 「스윕별 프로파일」 · 「시각」 처리를 그대로 옮긴 어댑터입니다. 이것으로 같은 원시를 **드론 쪽 RTK 궤적 · 레버암 ·
리플렉터 검증 · 패스 비교 · mm 변위**에 넣을 수 있습니다(그쪽 quick-look 은 FC 의 LOCAL_POSITION_NED 를 씁니다).

- Pi 에서 패스마다 거리 압축으로 줄여 둠(`SAR_REDUCE_ADAPTER=sar_image.cansar:cansar_iq`) → 노트북 · 서버는 줄인 것만 받음
- 레이더 설정 예시: `sar_image/example_radar_cansar.json` (λ = c / 5.50 GHz — 그쪽 위상 기준 주파수, 대역 368 MHz)

가짜 CANSAR-2 비행(그쪽 형식 그대로, `cansar.write_fake`)으로 확인한 것:

| | 결과 |
|---|---|
| 그쪽 `cansar_quick.py` 가 우리 가짜 파일에서 그대로 도나 | 됩니다 — 가장 밝은 리플렉터를 제자리(진행 +4.1 m, 옆 24.0 m)에서 찾음 |
| 드론 쪽 파이프라인 | 리플렉터 4/4 제자리(오차 0.0 m) · 진행 방향 해상도 3.3 cm · 옆 15 cm · 첨두 대비 부엽 −32 ~ −35 dB · 시각 어긋남 0 |

## 3. 레이더 팀에 드리는 의견 · 질문

1. **quick 의 `--dec 8` 과 방위 앨리어싱.** 가짜 데이터(PRF 234 Hz, 4 m/s, 빔 30°)에서 `--dec 1` 은 리플렉터 4개가 깨끗하지만
   `--dec 2` 부터 유령 줄무늬, `--dec 8` 은 줄무늬에 묻힙니다(`screenshots/35_cansar_dec_비교.png`).
   진행 방향 표본 간격(= 속도 / (PRF / dec))이 벌어지면 생깁니다. 가짜에서 1.7 cm(dec 1)는 깨끗, 3.4 cm(dec 2)부터 유령 —
   3 dB 빔폭만 보면 5 cm 까지 될 것 같지만 빔 가장자리 · 넓은 영상 구역까지 받으니 λ/4 ≈ 1.4 cm 에 가까울수록 안전합니다.
   **실제 유효 PRF** 를 알려 주시면 그 값에 맞는 dec 를 같이 정하겠습니다(GPU 를 쓰면 dec 를 낮춰도 빠릅니다).
2. **빛의 속도 `c = 3e8`.** 실제 값(299 792 458)과 0.07 % 차이라, 25 m 에서 위상 기준이 수 rad 어긋나고 개구 안에서 0.3 rad 남짓
   흐려집니다. 드론 쪽 어댑터는 실제 값을 씁니다. 바꾸셔도 거리 축 · 위상이 같이 맞습니다.
3. **표시 행(0x5A5A)이 하나 빠지면.** 지금은 부대역마다 k 번째를 같은 스윕으로 짝지어 그 뒤 스윕이 전부 밀립니다.
   드론 쪽 어댑터는 순서(0→7)가 끊긴 곳을 세어 알려 줍니다. 스윕 번호(카운터)를 원시에 같이 적어 주시면 정확히 고칠 수 있습니다.
4. **궤적.** quick 은 FC 의 LOCAL_POSITION_NED(IMU 자리)를 씁니다. 안테나는 IMU 에서 떨어져 있어 기울면 위치가 바뀝니다(레버암).
   드론 쪽은 RTK 궤적 + 레버암으로 계산합니다. 안테나 위치(FC 기준 앞 · 오른쪽 · 아래 m)를 재 주시면 둘 다에 쓰겠습니다.
5. **확인할 것**
   - `roff` 0.4 m 는 장비 내부 지연 실측값인가요? (드론 쪽도 같은 값을 씁니다)
   - CAP_ON 으로 캡처를 켜고 끄나요? CAP_ACK 를 쓰나요? (드론 쪽이 패스 시작 · 끝에 CAP_ON 을 만들고 지웁니다)
   - Pi 에서 `cansar_quick.py` 를 둘 경로(`SAR_CANSAR_QUICK`)
   - 캡처 번호 N 이 시각(HHMMSS)이면 날이 바뀔 때 겹칠 수 있습니다 — 드론 쪽은 `passes.csv` 의 t0 로 줄 세웁니다
