"""
datastream_front_reader.py — 데이터 스트림 서버(Redis)의 Go1 정면 탐지 결과를 Tailscale 로 받아 Unity 로 넘긴다

[흐름]
  pi7 정면 카메라 → 서버 노트북(WSL)의 데이터 스트림이 탐지·깊이 추정
  → Redis 스트림 vision_stream:<소스>:<모델> (Tailscale 100.125.104.23:6380)
  → 이 프로그램이 최신 한 건을 읽어 로봇 기준 거리로 바꿈
  → UDP JSON(Unity 5012). go1_front_guard.py 와 같은 형식이라 Go1FrontGuardReceiver 가 그대로 받는다.
  ※ 이 PC 에서는 탐지를 돌리지 않는다. 로봇에 아무것도 보내지 않는다.

[거리 계산]
  unidepth : 물체마다 depth_m(m), uv(화면 좌표), 서버가 추정한 intrinsics 가 있다.
             앞 = depth_m, 오른쪽 = (u - cx) / fx * depth_m  (depth_m 를 앞 방향 거리로 보고 계산. 실측 확인 안 함)
  targeted : 사람·의자만. dist.value(m) 와 bbox 가운데로 같은 계산. intrinsics 가 없어 --fx/--cx 를 쓴다.

[오래된 데이터]
  Redis 에는 서버가 멈춘 뒤에도 마지막 결과가 남는다. 마지막 건이 --max-age 초보다 오래됐으면
  탐지를 싣지 않고 level 을 "no_video" 로 보낸다. (--replay 는 확인용으로 나이를 무시한다)

[실행]
  python datastream_front_reader.py                    # targeted (사람·의자)
  python datastream_front_reader.py --model unidepth   # 모든 탐지 (배경 오탐이 섞인다)
"""
import json
import math
import time
import socket
import argparse


class Redis:
    """읽기 명령만 쓰는 최소 Redis 접속 (별도 패키지 없이)."""

    def __init__(self, host, port, timeout=5.0):
        self.addr, self.timeout, self.s, self.f = (host, port), timeout, None, None

    def _open(self):
        self.s = socket.create_connection(self.addr, self.timeout)
        self.s.settimeout(self.timeout)
        self.f = self.s.makefile("rb")

    def close(self):
        try:
            if self.s is not None:
                self.s.close()
        except OSError:
            pass
        self.s = self.f = None

    def _read(self):
        line = self.f.readline()
        if not line:
            raise ConnectionError("연결이 끊겼다")
        t, v = line[:1], line[1:].rstrip(b"\r\n")
        if t == b"+":
            return v.decode("utf-8", "replace")
        if t == b"-":
            raise RuntimeError(v.decode("utf-8", "replace"))
        if t == b":":
            return int(v)
        if t == b"$":
            n = int(v)
            if n < 0:
                return None
            return self.f.read(n + 2)[:-2]          # 바이트 그대로 (영상·깊이가 섞여 있다)
        if t == b"*":
            return [self._read() for _ in range(int(v))]
        raise RuntimeError("알 수 없는 응답 %r" % line[:20])

    def cmd(self, *args):
        if self.s is None:
            self._open()
        parts = [a if isinstance(a, bytes) else str(a).encode("utf-8") for a in args]
        self.s.sendall(b"*%d\r\n" % len(parts) + b"".join(b"$%d\r\n%s\r\n" % (len(p), p) for p in parts))
        return self._read()

    def latest(self, key):
        """스트림의 마지막 한 건 → (id_ms, {칸: 바이트}) 또는 None."""
        r = self.cmd("XREVRANGE", key, "+", "-", "COUNT", "1")
        if not r:
            return None
        eid, flat = r[0]
        fields = {flat[i].decode("utf-8", "replace"): flat[i + 1] for i in range(0, len(flat), 2)}
        return eid.decode(), int(eid.split(b"-")[0]), fields


def to_items(res, model, args):
    """서버 결과 한 건 → go1_front_guard 형식의 탐지 목록."""
    K = res.get("intrinsics")
    fx = K[0][0] if K else args.fx
    cx = K[0][2] if K else args.cx
    items = []
    for d in res.get("detections") or []:
        bb = d.get("bbox") or [0, 0, 0, 0]
        if model == "targeted":
            dist = (d.get("dist") or {}).get("value")
            u = (bb[0] + bb[2]) / 2.0
        else:
            dist = d.get("depth_m")
            u = (d.get("uv") or [(bb[0] + bb[2]) / 2.0])[0]
        if dist is None or not (dist > 0) or math.isnan(dist):
            continue                               # 거리를 모르는 것은 보내지 않는다
        conf = float(d.get("confidence") or 0.0)
        if conf < args.min_conf:
            continue
        fwd = float(dist)
        right = (u - cx) / fx * fwd
        items.append({"name": str(d.get("label", "?")), "conf": round(conf, 2),
                      "bbox": [round(v) for v in bb],
                      "right_m": round(right, 2), "forward_m": round(fwd, 2),
                      "dist_m": round(math.hypot(right, fwd), 2), "in_path": bool(abs(right) <= args.corridor)})
    return items


def main():
    ap = argparse.ArgumentParser(description="데이터 스트림(Redis) Go1 정면 탐지 → Unity")
    ap.add_argument("--redis", default="100.125.104.23", help="서버 노트북 Tailscale 주소")
    ap.add_argument("--redis-port", type=int, default=6380)
    ap.add_argument("--source", default="robot1", help="소스 이름 (robot1 = pi7 Go1 정면)")
    # 기본은 targeted: unidepth 쪽은 이름 제한 없는 탐지라 화면 전체를 덮는 배경("night sky" 등)이 0.3 m 로 잡혀 stop 이 뜬다
    ap.add_argument("--model", default="targeted", choices=["unidepth", "targeted"])
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--max-age", type=float, default=3.0, help="마지막 결과가 이보다 오래됐으면(초) 탐지를 싣지 않는다")
    ap.add_argument("--replay", action="store_true", help="확인용: 나이를 무시하고 남아 있는 마지막 결과를 보낸다")
    ap.add_argument("--min-conf", type=float, default=0.25)
    ap.add_argument("--fx", type=float, default=174.0, help="targeted 용 초점(px). unidepth 는 서버 값을 쓴다")
    ap.add_argument("--cx", type=float, default=232.0)
    ap.add_argument("--corridor", type=float, default=0.35, help="진행 통로 반폭(m)")
    ap.add_argument("--warn", type=float, default=1.0)
    ap.add_argument("--stop", type=float, default=0.6)
    ap.add_argument("--unity-ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5012)
    ap.add_argument("--seconds", type=float, default=0)
    args = ap.parse_args()

    key = "vision_stream:%s:%s" % (args.source, args.model)
    rd = Redis(args.redis, args.redis_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print("[ds-front] %s:%d %s → UDP %s:%d" % (args.redis, args.redis_port, key, args.unity_ip, args.port))

    t_start, period, last_level, last_id, n_new = time.time(), 1.0 / args.fps, None, None, 0
    while args.seconds <= 0 or time.time() - t_start < args.seconds:
        t0 = time.time()
        level, items, nearest, age, note = "no_video", [], None, -1.0, ""
        try:
            got = rd.latest(key)
            if got is None:
                note = "키가 비어 있다"
            else:
                eid, id_ms, fields = got
                age = t0 - id_ms / 1000.0             # 서버 시계 기준이라 두 PC 시계 차이만큼 틀릴 수 있다
                if eid != last_id:
                    last_id, n_new = eid, n_new + 1
                if args.replay or age <= args.max_age:
                    res = json.loads(fields["result"].decode("utf-8", "replace"))
                    items = to_items(res, args.model, args)
                    inpath = [i for i in items if i["in_path"]]
                    nearest = min(inpath, key=lambda i: i["forward_m"]) if inpath else None
                    level = "clear"
                    if nearest is not None:
                        f = nearest["forward_m"]
                        level = "stop" if f <= args.stop else "warn" if f <= args.warn else "clear"
                else:
                    note = "마지막 결과가 %.0f 초 전 것" % age
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            rd.close()
            note = "읽기 실패: %s" % e

        pkt = {"type": "go1_front_guard", "timestamp": "%.3f" % time.time(), "level": level,
               "nearest_name": "" if nearest is None else nearest["name"],
               "nearest_forward_m": -1.0 if nearest is None else nearest["forward_m"],
               "video_age_s": round(age, 2) if age >= 0 else -1.0,
               "warn_m": args.warn, "stop_m": args.stop, "detections": items,
               "via": "datastream:%s" % key}
        sock.sendto(json.dumps(pkt, ensure_ascii=False).encode("utf-8"), (args.unity_ip, args.port))

        if level != last_level:
            print("[ds-front] %s → %s  탐지 %d개%s%s" % (
                last_level, level, len(items),
                "" if nearest is None else "  (%s 앞 %.2f m, 좌우 %+.2f m)" % (nearest["name"], nearest["forward_m"], nearest["right_m"]),
                "  [%s]" % note if note else ""))
            last_level = level

        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)
    print("[ds-front] 끝. 새 결과 %d건" % n_new)


if __name__ == "__main__":
    main()
