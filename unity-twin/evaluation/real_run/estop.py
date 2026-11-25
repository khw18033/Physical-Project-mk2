# 비상 정지: 로봇 PC 로 PATH_CANCEL 을 직접 보낸다 (Unity 가 멈춰 있어도 동작).  python estop.py [로봇 PC 주소]
# 주소를 주지 않으면 pi7 의 Tailscale 주소와 랩 공유기 주소 양쪽 모두로 보낸다 (한쪽 망이 끊겨도 정지가 닿도록, 2026-11-25).
import socket, sys, time
hosts = [sys.argv[1]] if len(sys.argv) > 1 else ["100.72.109.9", "192.168.50.170"]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for i in range(10):
    for host in hosts:
        try:
            s.sendto(b"PATH_CANCEL", (host, 15110))
        except OSError as e:
            if i == 0:
                print("send failed ->", host, e)
    time.sleep(0.05)
print("PATH_CANCEL x10 ->", ", ".join(hosts))
