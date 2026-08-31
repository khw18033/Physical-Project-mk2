"""
피지컬팀 mk2 — 엣지 참조 구현 로컬 검증 (AGENDA 10-2·10-7·[G3] 임의 진행분)
=============================================================================
브로커도 실물도 없이 판정·수신 규칙을 검증한다.

가용성 판정기 (availability.py):
  1. birth→online, shutdown→offline_planned(장애 아님), LWT→offline_fault
  2. 하트비트 침묵 → stale (주기는 관측 학습 — 중앙값)
  3. 하트비트 없는 노드(임무 중 로봇)는 침묵 판정 제외, summary 가 생존 신호
  4. Prometheus 텍스트 출력: up / hw_availability_state / 나이
  5. 깨진 payload 는 상태를 바꾸지 못한다

미디어 게이트웨이 (media_gateway.py):
  6. go1_relay 와 루프백 종단: 송신 NAL == 수신 NAL (전 프레임 바이트 일치)
  7. 패킷 유실 주입: 해당 프레임만 폐기, 다음 프레임부터 정상 (반쪽 NAL 없음)

사용:
    python test_edge.py        (edge/ 디렉터리에서, 어느 OS 든)
"""
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi"))

from availability import (ONLINE, OFFLINE_FAULT, OFFLINE_PLANNED, STALE,
                          AvailabilityTracker, serve_metrics)
from media_gateway import START, RtpH264Depacketizer, receive


def hb(zone="zoneA", etype="sensor", eid="s-01"):
    return (f"{zone}/{etype}/{eid}/heartbeat", json.dumps({"channel": "heartbeat"}))


def status(event, zone="zoneA", etype="sensor", eid="s-01", **kw):
    return (f"{zone}/{etype}/{eid}/status",
            json.dumps(dict({"channel": "status", "event": event}, **kw)))


def state_of(tr, key=("zoneA", "sensor", "s-01")):
    return tr.snapshot()[key][0]


# ---------------------------------------------------------------- 가용성
def test_lifecycle():
    tr = AvailabilityTracker()
    t = 1000.0
    tr.on_message(*status("birth"), now=t)
    assert state_of(tr) == ONLINE
    tr.on_message(*status("shutdown", reason="graceful_shutdown"), now=t + 10)
    assert state_of(tr) == OFFLINE_PLANNED, "계획 정지는 장애가 아니다 (VZ-U-01)"
    tr.on_message(*status("rebirth"), now=t + 20)
    assert state_of(tr) == ONLINE
    tr.on_message(*status("death", reason="lwt"), now=t + 30)
    assert state_of(tr) == OFFLINE_FAULT, "LWT 는 장애다"
    print("  1) 생애주기: birth→online, shutdown→planned, LWT→fault ✓")


def test_silence():
    tr = AvailabilityTracker()
    t = 1000.0
    # 2초 주기 하트비트를 학습시킨다 (기본 가정 5초와 다르게)
    for i in range(6):
        tr.on_message(*hb(), now=t + i * 2.0)
    tr.evaluate(now=t + 10 + 2.0 * 4 - 1)      # 학습 주기(2s)×miss(4) 직전
    assert state_of(tr) == ONLINE, "임계 전에 죽이면 안 된다"
    tr.evaluate(now=t + 10 + 2.0 * 4 + 1)      # 직후
    assert state_of(tr) == STALE, "LWT 조차 없는 침묵은 stale"
    tr.on_message(*hb(), now=t + 60)            # 복귀
    assert state_of(tr) == ONLINE
    print("  2) 침묵 판정: 학습 주기(2s)×4 경과 → stale, 하트비트 복귀 → online ✓")


def test_no_heartbeat_node():
    tr = AvailabilityTracker()
    t = 1000.0
    k = ("zoneA", "robot", "rb-01")
    tr.on_message(*status("birth", etype="robot", eid="rb-01"), now=t)
    tr.evaluate(now=t + 3600)                   # 1시간 침묵 — 하트비트가 원래 없다
    assert tr.snapshot()[k][0] == ONLINE, "하트비트 없는 노드를 침묵으로 죽이면 안 된다"
    tr.on_message(*status("summary", etype="robot", eid="rb-01"), now=t + 3600)
    assert tr.snapshot()[k][0] == ONLINE
    print("  3) 무하트비트 노드(임무 중 로봇): 침묵 판정 제외, summary 가 생존 신호 ✓")


def test_prometheus():
    tr = AvailabilityTracker()
    t = 1000.0
    tr.on_message(*hb(), now=t)
    tr.on_message(*status("death", reason="lwt", eid="s-02"), now=t)
    text = tr.prometheus(now=t + 1)
    assert 'up{zone="zoneA",entity_type="sensor",entity_id="s-01"} 1' in text
    assert 'up{zone="zoneA",entity_type="sensor",entity_id="s-02"} 0' in text
    assert 'hw_availability_state{zone="zoneA",entity_type="sensor",entity_id="s-02"} 2' in text
    # HTTP 로도 나가는지 — 기존 Prometheus 가 엣지만 scrape 하면 되는 형태
    srv = serve_metrics(tr, port=0)
    port = srv.server_address[1]
    import urllib.request
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
    srv.shutdown()
    assert "up{" in body and "hw_heartbeat_age_seconds" in body
    print(f"  4) Prometheus 노출: up 1/0·상태 코드·나이, HTTP /metrics ✓")


def test_malformed():
    tr = AvailabilityTracker()
    t = 1000.0
    tr.on_message(*status("birth"), now=t)
    tr.on_message("zoneA/sensor/s-01/status", b"{broken json", now=t + 1)
    tr.on_message("garbage", b"{}", now=t + 1)
    assert state_of(tr) == ONLINE, "깨진 입력이 상태를 바꾸면 안 된다"
    print("  5) 깨진 payload·토픽: 상태 불변 ✓")


# ---------------------------------------------------------------- 미디어
def test_gateway_e2e():
    """go1_relay(송신) ↔ media_gateway(수신) — 양끝을 루프백으로 맞물린다."""
    from bench.go1_relay_test import FakeWssink, make_frames
    from robot.go1_relay import Go1RtpRelaySender, split_annexb

    n_frames = 45
    frames = make_frames(n_frames, seed=11)
    sent_nals = [split_annexb(f) for f in frames]

    got = []
    stop = threading.Event()
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]
    sk.close()                                  # 게이트웨이가 이 포트에 다시 바인드

    def rx():
        receive(port, got.append, stop_check=stop.is_set, bind="127.0.0.1")

    rx_t = threading.Thread(target=rx, daemon=True)
    rx_t.start()
    time.sleep(0.3)

    ws = FakeWssink(frames)
    ws.start()
    sender = Go1RtpRelaySender(cam_id=1, cam_host="127.0.0.1", cam_port=ws.port)
    sender.start("127.0.0.1", port, "sess-edge")
    deadline = time.time() + n_frames / 30.0 + 5
    while time.time() < deadline and len(got) < n_frames:
        time.sleep(0.2)
    sender.stop()
    stop.set()
    rx_t.join(timeout=3)

    assert len(got) == n_frames, f"수신 프레임 {len(got)} != {n_frames}"
    got_nals = [split_annexb(f) for f in got]
    assert got_nals == sent_nals, "송수신 NAL 불일치"
    print(f"  6) 게이트웨이 종단(go1_relay↔수신단): {n_frames}프레임 바이트 일치 ✓")


def test_gateway_loss():
    """유실 주입 — 소켓 없이 depacketizer 에 직접. 두 시나리오:
    (a) 경계 유실: 프레임 하나가 통째로 사라짐 → 이웃 프레임은 건드리지 않는다
    (b) 조립 중 유실: FU-A 조각 하나 소실 → 그 프레임만 폐기, 이후 온전"""
    from robot.go1_relay import MTU_PAYLOAD, RtpH264Packetizer

    # ---- (a) 경계 유실 ----
    pk = RtpH264Packetizer(ssrc=1, seq=0)
    frames_nals = [[bytes([0x41]) + bytes([i]) * 900] for i in range(10)]
    packets, bounds = [], []
    for i, nals in enumerate(frames_nals):
        ps = pk.packetize(nals, timestamp=i * 3000)
        bounds.append((len(packets), len(packets) + len(ps)))
        packets += ps
    fed = packets[:bounds[5][0]] + packets[bounds[5][1]:]   # 5번 프레임 전체 소실

    dp = RtpH264Depacketizer()
    out = [f for p in fed if (f := dp.feed(p)) is not None]
    st = dp.stats()
    assert st["lost"] == 1, st
    assert len(out) == 9, f"완성 프레임 {len(out)} != 9 — 이웃 프레임까지 버렸다"
    survivors = [n for i, n in enumerate(frames_nals) if i != 5]
    got = [f.split(START)[1:] for f in out]
    assert got == survivors, "유실 이후 프레임이 오염됐다"

    # ---- (b) 조립 중 유실 ----
    pk = RtpH264Packetizer(ssrc=1, seq=0)
    big = [[bytes([0x65]) + bytes([i]) * (MTU_PAYLOAD * 3)] for i in range(6)]
    packets, bounds = [], []
    for i, nals in enumerate(big):
        ps = pk.packetize(nals, timestamp=i * 3000)
        bounds.append((len(packets), len(packets) + len(ps)))
        packets += ps
    mid = bounds[2][0] + 1                                  # 2번 프레임의 중간 조각
    fed = packets[:mid] + packets[mid + 1:]

    dp = RtpH264Depacketizer()
    out = [f for p in fed if (f := dp.feed(p)) is not None]
    st = dp.stats()
    assert st["frames_dropped"] == 1 and st["lost"] == 1, st
    assert len(out) == 5, f"완성 프레임 {len(out)} != 5"
    survivors = [n for i, n in enumerate(big) if i != 2]
    got = [f.split(START)[1:] for f in out]
    assert got == survivors, "조립 중 유실 뒤 프레임이 오염됐다"
    print(f"  7) 유실 주입: 경계 유실(이웃 무손상)·FU-A 중간 유실(해당 프레임만 폐기) ✓")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("엣지 참조 구현 검증 (브로커·실물 불필요)")
    test_lifecycle()
    test_silence()
    test_no_heartbeat_node()
    test_prometheus()
    test_malformed()
    test_gateway_e2e()
    test_gateway_loss()
    print("전부 통과")


if __name__ == "__main__":
    main()
