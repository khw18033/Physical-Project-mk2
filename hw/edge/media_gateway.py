"""
피지컬팀 mk2 — 엣지 미디어 게이트웨이: H.264 RTP 수신단 (AGENDA 10-7 임의 진행)
=================================================================================
**회신 대기로 멈추지 않기 위해, 하드웨어 권고안(소스별 협상)을 양끝 다 구현해 둔다.**

    말단 go1_relay ──RTP/UDP (RFC 6184)──► 이 수신단 ──Annex-B──► 디코더/저장/AI

10-7 권고 ①"소스별 협상 — 로봇은 H.264, 고정 CCTV 는 JPEG"에서 빠져 있던 조각이
**H.264 수신측**이다. JPEG(RFC 2435) 쪽은 표준이라 기성 도구(ffmpeg 등)가 바로 받지만,
H.264 무변환 중계는 우리가 보내는 쪽이므로 받는 쪽 참조 구현도 우리가 낸다.
백엔드가 다른 코덱 정책을 확정하면 이 구성요소만 바뀐다 — 말단은 그대로다.

## 수신 규칙 (RFC 6184 역방향)

  - Single NAL: payload 그대로 한 NAL
  - FU-A(28): S 조각에서 NAL 헤더 복원 → E 조각까지 이어붙임
  - marker=1 이 액세스 유닛(프레임) 경계
  - **유실 프레임은 버린다.** 시퀀스 결번을 보면 그 프레임 전체를 폐기하고 다음
    프레임부터 다시 붙는다 — 반쪽 NAL 을 디코더에 넣으면 화면 깨짐이 다음 IDR 까지
    전파된다. 버리면 최대 한 프레임(33ms) 손실로 끝난다. IDR 이 0.5초 간격이라
    유실이 IDR 에 걸려도 0.5초 안에 회복된다.

출력은 Annex-B(4바이트 시작 코드) — 파일이든 디코더 stdin 이든 그대로 먹는 형식이다.

## 사용

    python -m media_gateway --port 5004 --out robot.h264
    python -m media_gateway --port 5004 --out - | <디코더>
    (시험: edge/test_edge.py — go1_relay 와 루프백으로 맞물려 검증한다)
"""
import socket
import struct

FU_A = 28
START = b"\x00\x00\x00\x01"


class RtpH264Depacketizer:
    """RTP 패킷 → 완성된 프레임(Annex-B bytes). 소켓을 모른다 — 그래서
    패킷 배열만으로 검증된다(유실 주입 포함)."""

    def __init__(self):
        self.expected_seq = None
        self._nals = []             # 조립 중인 프레임의 완성 NAL 들
        self._fu = None             # 조립 중인 FU-A
        self._ts = None             # 조립 중인 액세스 유닛의 RTP 타임스탬프
        self._drop_until_marker = False
        self.frames_ok = 0
        self.frames_dropped = 0
        self.packets = 0
        self.lost = 0

    def feed(self, pkt):
        """패킷 하나. 프레임이 완성되면 Annex-B bytes, 아니면 None."""
        if len(pkt) < 13 or (pkt[0] >> 6) != 2:
            return None                         # RTP v2 가 아니면 버린다
        _, b2, seq, ts, _ = struct.unpack(">BBHII", pkt[:12])
        marker = bool(b2 & 0x80)
        payload = pkt[12:]
        self.packets += 1

        # ---- 유실 감지 ----
        # 결번이 나면 "조립 중이던" 프레임만 살릴 수 없다. 다음 프레임까지 버리면
        # 유실 1패킷에 2프레임을 잃는다 — 타임스탬프(액세스 유닛 식별자)로 이 패킷이
        # 오염된 유닛의 잔여인지, 새 유닛의 시작인지 가른다.
        if self.expected_seq is not None and seq != self.expected_seq:
            self.lost += (seq - self.expected_seq) & 0xFFFF
            if self._nals or self._fu is not None:
                # 조립 중이던 유닛은 오염 — 버리고, 같은 유닛의 잔여도 마저 버린다
                self.frames_dropped += 1
                self._drop_until_marker = (ts == self._ts)
                self._nals, self._fu, self._ts = [], None, None
            # 경계에서 난 결번이면 통째로 사라진 프레임뿐 — 이 패킷은 새 유닛이므로
            # 그대로 처리한다 (머리 잘린 유닛의 Single NAL 꼬리는 FU 가드가 못 잡지만,
            # 그 경우도 유닛 일부는 온전해 디코더가 스스로 버틴다)
        self.expected_seq = (seq + 1) & 0xFFFF

        if self._drop_until_marker:
            if marker:                          # 오염 유닛의 경계 도달
                self._drop_until_marker = False
            return None

        if self._ts is None:
            self._ts = ts

        # ---- NAL 재조립 ----
        if payload and (payload[0] & 0x1F) == FU_A and len(payload) >= 2:
            s_bit, e_bit = payload[1] & 0x80, payload[1] & 0x40
            if s_bit:
                nal_hdr = (payload[0] & 0xE0) | (payload[1] & 0x1F)
                self._fu = bytearray([nal_hdr])
            if self._fu is None:
                # 시작 없는 조각 — 유실 감지를 비켜 간 손상. 프레임 폐기
                self._nals = []
                self._drop_until_marker = not marker
                if marker:
                    self.frames_dropped += 1
                return None
            self._fu += payload[2:]
            if e_bit:
                self._nals.append(bytes(self._fu))
                self._fu = None
        elif payload:
            self._nals.append(payload)

        # ---- 프레임 경계 ----
        if marker:
            if self._fu is not None:            # E 없이 marker — 반쪽 FU. 폐기
                self._fu = None
                self._nals = []
                self.frames_dropped += 1
                return None
            if not self._nals:
                return None
            frame = START + START.join(self._nals)
            self._nals, self._ts = [], None
            self.frames_ok += 1
            return frame
        return None

    def stats(self):
        return {"packets": self.packets, "lost": self.lost,
                "frames_ok": self.frames_ok, "frames_dropped": self.frames_dropped}


def receive(port, on_frame, stop_check=None, bind="0.0.0.0"):
    """UDP 수신 루프. 프레임이 완성될 때마다 on_frame(bytes) 호출."""
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.bind((bind, port))
    sk.settimeout(0.5)
    dp = RtpH264Depacketizer()
    try:
        while stop_check is None or not stop_check():
            try:
                pkt, _ = sk.recvfrom(65535)
            except socket.timeout:
                continue
            frame = dp.feed(pkt)
            if frame is not None:
                on_frame(frame)
    finally:
        sk.close()
    return dp


def main():
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5004)
    ap.add_argument("--out", default="-", help="Annex-B 출력: 파일 경로 또는 '-'(stdout)")
    args = ap.parse_args()

    out = sys.stdout.buffer if args.out == "-" else open(args.out, "wb")
    print(f"[게이트웨이] RTP/H.264 수신 대기 :{args.port} → {args.out}", file=sys.stderr)

    def on_frame(frame):
        out.write(frame)
        out.flush()

    try:
        receive(args.port, on_frame)
    except KeyboardInterrupt:
        pass
    finally:
        if out is not sys.stdout.buffer:
            out.close()


if __name__ == "__main__":
    main()
