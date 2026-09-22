"""
relay_loop.py — obstacles_360.json 을 유니티로 반복 UDP 송출 (정렬 조정용).
Unity에서 yawOffsetDeg/invertX/distanceScale 을 돌리면 큐브가 실시간으로 따라 갱신됨.
사용:  python relay_loop.py [json파일] [유니티IP] [포트] [주기초]
기본:  python relay_loop.py obstacles_360.json 192.168.50.246 5010 1.0
멈춤:  Ctrl+C
"""
import socket, sys, time

json_path = sys.argv[1] if len(sys.argv) > 1 else "obstacles_360.json"
unity_ip  = sys.argv[2] if len(sys.argv) > 2 else "192.168.50.246"
port      = int(sys.argv[3])   if len(sys.argv) > 3 else 5010
period    = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

data = open(json_path, "rb").read()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"반복 송출 시작: {json_path} -> {unity_ip}:{port}  (매 {period}s, Ctrl+C로 종료)")
try:
    n = 0
    while True:
        s.sendto(data, (unity_ip, port))
        n += 1
        print(f"  [{n}] 송출", end="\r")
        time.sleep(period)
except KeyboardInterrupt:
    print("\n종료")
finally:
    s.close()