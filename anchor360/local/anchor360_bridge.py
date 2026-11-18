"""
anchor360_bridge.py — 서버 JSON → 유니티 UDP 중계기

[왜 필요한가]
  서버(210.110.250.33, 학교망)에서 유니티 PC(192.168.50.244, 사설망)로
  UDP 직송이 안 된다. 서버에 192.168.50.x 경로가 없어서 패킷이 기본
  게이트웨이로 나가 버려진다. (에러 없이 조용히 사라지므로 UDP 송신은
  계속 '성공'으로 찍힌다.)

  반대로 "PC → 서버" 방향은 NAT를 통과해서 잘 된다.
  그래서 방향을 뒤집는다. 이 스크립트가 서버에서 JSON을 당겨와
  로컬 네트워크로 UDP 송출한다.

    [서버] anchor360_live.py → live_out/anchor360_latest.json
                             → GET /anchor360_latest
    [이 PC] ──당겨옴──> 로컬 UDP ──> [유니티] 5010

[어디서 실행하나 — 둘 중 하나]
  (1) 유니티 PC에서 실행  ← 홉이 1개라 더 좋다
      먼저 브라우저로 http://210.110.250.33:7866/pano_health 가 열리는지 확인.
      열리면:  python anchor360_bridge.py --unity-ip 127.0.0.1

  (2) 랩실 PC(Pro2 연결된 PC)에서 실행
      유니티 PC가 서버에 못 닿을 때. 이 PC가 192.168.50.x 에 있어야 한다.
      python anchor360_bridge.py --unity-ip 192.168.50.244

[하트비트 겸용]
  새 JSON이 없어도 마지막 것을 --poll 주기마다 계속 재송출한다.
  유니티 수신기는 스냅샷 방식이라 같은 내용을 다시 받아도 결과가 같고,
  덕분에 유니티를 언제 켜도 몇 초 안에 큐브가 채워진다.
  (사진 1장당 1패킷만 보내던 구조에서는 유니티를 늦게 켜면
   다음 사진이 올 때까지 화면이 비어 있었다.)

[서버 준비]
  pano_receiver.py 에 아래 엔드포인트가 추가되어 있어야 한다.

      from fastapi.responses import FileResponse
      LATEST_JSON = os.path.expanduser(
          "~/capstone-db/docx2026/live_out/anchor360_latest.json")

      @app.get("/anchor360_latest")
      async def anchor360_latest():
          if not os.path.exists(LATEST_JSON):
              return {"status": "empty"}
          return FileResponse(LATEST_JSON, media_type="application/json")

[의존]
  pip install requests

[종료]
  Ctrl+C
"""

import json
import time
import socket
import argparse
import datetime

import requests


DEF_SERVER = "http://210.110.250.33:7866/anchor360_latest"
DEF_UNITY_IP = "192.168.50.244"
DEF_PORT = 5010
DEF_POLL = 2.0


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def main():
    ap = argparse.ArgumentParser(
        description="서버 360° JSON을 당겨와 유니티로 UDP 중계")
    ap.add_argument("--server", default=DEF_SERVER,
                    help="서버 JSON 엔드포인트 URL")
    ap.add_argument("--unity-ip", default=DEF_UNITY_IP,
                    help="유니티 PC IP. 이 스크립트를 유니티 PC에서 돌리면 127.0.0.1")
    ap.add_argument("--port", type=int, default=DEF_PORT)
    ap.add_argument("--poll", type=float, default=DEF_POLL,
                    help="당겨오기/재송출 주기(초)")
    ap.add_argument("--only-new", action="store_true",
                    help="내용이 바뀐 경우에만 송출(하트비트 끄기)")
    ap.add_argument("--quiet", action="store_true",
                    help="새 패킷일 때만 로그 출력")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("=" * 62)
    print("anchor360_bridge — 서버 JSON → 유니티 UDP 중계")
    print(f"  가져올 곳 : {args.server}")
    print(f"  보낼 곳   : UDP {args.unity_ip}:{args.port}")
    print(f"  주기      : {args.poll}s"
          f"{'  (새 내용일 때만 송출)' if args.only_new else '  (하트비트 겸용)'}")
    print("  Ctrl+C 로 종료")
    print("=" * 62)

    last_ts = None
    n_sent = 0
    n_new = 0
    warned = False

    try:
        while True:
            try:
                r = requests.get(args.server, timeout=5)
                data = r.content

                # 서버에 아직 결과가 없을 때
                if len(data) < 50:
                    if not args.quiet:
                        print(f"[{ts()}] 서버에 아직 결과 없음")
                    time.sleep(args.poll)
                    continue

                pkt = json.loads(data)
                cur_ts = pkt.get("timestamp")
                n_det = len(pkt.get("detections", []))
                is_new = (cur_ts != last_ts)

                if args.only_new and not is_new:
                    time.sleep(args.poll)
                    continue

                sock.sendto(data, (args.unity_ip, args.port))
                n_sent += 1
                if is_new:
                    n_new += 1
                last_ts = cur_ts
                warned = False

                if is_new:
                    print(f"[{ts()}] NEW  ts={cur_ts}  검출 {n_det}개  "
                          f"{len(data)}B  → {args.unity_ip}:{args.port}")
                elif not args.quiet:
                    print(f"[{ts()}]      (재송출) 검출 {n_det}개  "
                          f"누적 {n_sent}회 / 신규 {n_new}건", end="\r")

            except requests.exceptions.RequestException as e:
                if not warned:
                    print(f"[{ts()}] 서버 연결 실패: {e}")
                    print("        → 이 PC에서 서버에 닿는지 확인하세요:")
                    print("           브라우저로 http://210.110.250.33:7866/pano_health")
                    warned = True
            except json.JSONDecodeError:
                print(f"[{ts()}] JSON 파싱 실패 — 서버가 쓰는 중일 수 있음, 다음 주기 재시도")
            except Exception as e:
                print(f"[{ts()}] 예외: {e}")

            time.sleep(args.poll)

    except KeyboardInterrupt:
        print(f"\n[{ts()}] 종료. 송출 {n_sent}회 (신규 {n_new}건).")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
