# CANSAR-2 레이더 영상 처리 — 웹 연동용 안내

웹 화면에서 패스가 끝날 때마다 레이더 quick-look 영상을 띄우기 위한 안내입니다.
처리 코드는 **명령 한 줄로 실행 → PNG 를 만들어 주는 구조**라서, 서버는 이 명령을 부르고 결과 PNG 를 띄우기만 하면 됩니다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `cansar_quick.py` | 진입점. 패스 번호로 데이터·로그 폴더를 찾고, 시각을 자동 매칭해 `cansar_flight.py` 를 실행 |
| `cansar_flight.py` | 실제 영상 처리(역투영). torch + CUDA 가 있으면 GPU, 없으면 numpy(CPU) |

두 파일을 같은 폴더에 둡니다. 필요한 패키지: `numpy` (선택: `torch` CUDA 판 — GPU 가속).

## 입력 데이터 (Pi 기준 위치)

| 데이터 | 위치 |
| --- | --- |
| 레이더 원시 데이터 | `/home/physical/flight/iq_N.bin`, `meta_N.txt` (패스 끝나고 수 초 안에 자동 복사됨) |
| 로그 폴더 | `/home/physical/cansar_logs/<날짜_시각>/` 안의 `mav.csv`, `events.csv`, `passes.csv` |

`passes.csv` 에 패스 번호 `n` 과 판정(`verdict`)이 한 줄씩 추가됩니다. 새 줄이 생기면 그 패스를 처리하면 됩니다.

## 실행

작업 폴더(처리 결과가 쌓일 곳)에서:

```bash
# 서버가 Pi 가 아닐 때: Pi 에서 받아와서 처리 (ssh 키 등록 필요)
python3 cansar_quick.py --pi physical@<Pi IP> --n <N> --side <right|left> --noopen

# 서버가 Pi 자신이거나, 파일을 이미 작업 폴더에 복사해 둔 경우
python3 cansar_quick.py --nopull --n <N> --side <right|left> --noopen
```

- `--nopull` 은 기본으로 작업 폴더의 `iq_N.bin`, `meta_N.txt`, `cansar_logs/` 를 찾습니다. **Pi 에서 바로 돌릴 때는** 경로를 지정합니다:
  ```bash
  python3 /경로/cansar_quick.py --nopull --data-dir /home/physical/flight --logs-root /home/physical/cansar_logs --n <N> --side <right|left> --noopen
  ```
  결과(`quick_N.png`, `quick_N.npz`)는 실행한 작업 폴더에 생깁니다. `cansar_flight.py` 는 `cansar_quick.py` 와 같은 폴더에 두면 자동으로 찾습니다.
- `--side` 는 레이더 안테나가 보는 쪽(진행 방향 기준). 비행 전에 레이더 팀이 알려 줍니다.
- `--n` 을 빼면 가장 최신 패스를 처리합니다.

## 출력

| 파일 | 내용 |
| --- | --- |
| `quick_N.png` | **화면에 띄울 영상.** 가로 = 진행 방향(m), 세로 = 옆 거리(m, 위가 먼 쪽), 밝기 0 ~ −30 dB |
| `quick_N.npz` | 복소 영상 원본(레이더 팀 후처리용). 지우지 말 것 |

표준 출력의 `[판정]` 줄(속도·헤딩·RTK fix·OK/재비행?)과 `영상 첨두 … dB @ 진행 …m, 옆 …m` 줄도 화면에 같이 보여 주면 좋습니다.
실패하면 0 이 아닌 종료 코드를 돌려줍니다.

## 주의

1. **quick-look 입니다.** 빠른 확인용 설정(`--dec 8 --res 0.5`)이라 최종 영상보다 거칩니다. 화면에 "quick-look" 이라고 표시해 주세요. 최종 영상은 착륙 후 레이더 팀이 정밀 처리합니다.
2. **Pi 에서 돌릴 경우:** 비행 제어와 같은 기기이므로 **패스가 끝난 뒤에만, 낮은 우선순위로** 실행해 주세요.
   ```bash
   nice -n 19 python3 cansar_quick.py --nopull --data-dir /home/physical/flight --logs-root /home/physical/cansar_logs --n <N> --side <right|left> --noopen
   ```
   `--fine` (정밀 처리)은 Pi 에서 실행하지 마세요.
3. **캡처 중에는 실행하지 않기:** 다음 패스가 진행 중(CAP_ON 있음)일 때는 처리를 미뤄 주세요.
4. **코드는 계속 바뀝니다.** 명령 형식과 출력 파일 이름(`quick_N.png`, `quick_N.npz`)은 유지할 테니, 서버는 이 인터페이스만 사용해 주세요.
5. 한 번에 한 패스씩 처리해 주세요(같은 작업 폴더에서 동시에 두 개 돌리면 `flight_img.png` 가 겹칩니다).
