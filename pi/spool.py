"""
피지컬팀 mk2 — 통신 두절 시 버퍼링·재전송 (HW-R-09)
====================================================
브로커가 끊긴 동안의 발행분을 디스크에 줄 단위(JSON Lines)로 쌓아두고, 재연결이
확인되면 쌓인 순서 그대로 다시 보낸다.

설계 근거
  - 디스크에 쓰는 이유: 메모리 큐는 정전·재부팅에서 통째로 사라진다. 재난 구간의
    업무 데이터는 지속 학습 재료로 장기 보존 대상(BE-S-04)이라 유실이 곧 손실이다.
  - 기록 순서 = 시간 순서: 발행 시각 순으로 append 하므로 파일 순서대로 재전송하면
    HW-R-09가 요구하는 "타임스탬프 순서 복원"이 그대로 성립한다. 재정렬 로직 불필요.
  - 상한을 두는 이유: 저사양 말단에서 두절이 길어지면 디스크가 먼저 고갈된다.
    그래서 디스크 여유 공간이 관측 metric 5종(HW-C-05)에 들어가 있다.
  - 재전송분에 `replayed` 표식: 소비자(BE-S-01)가 "지금 값"과 "밀린 값"을 구분해야
    대시보드가 과거 값을 현재로 오인하지 않는다.
"""
import json
import os


class Spool:
    def __init__(self, path, max_records, batch):
        self.path = path
        self.max_records = max_records
        self.batch = batch
        self.dropped = 0          # 상한 초과로 버린 건수 (degraded 판정 근거)
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.count = self._count_lines()

    def _count_lines(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def append(self, topic, payload, qos):
        """발행 실패분을 적재. payload는 dict 그대로 — 재전송 시 표식을 넣어야 한다."""
        rec = {"topic": topic, "qos": qos, "payload": payload}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.count += 1
        if self.count > self.max_records:
            self._trim()

    def _trim(self):
        """상한 초과 시 오래된 것부터 버린다. 매번 재작성하지 않도록 10%씩 잘라낸다."""
        keep = int(self.max_records * 0.9)
        lines = self._read_lines()
        drop = len(lines) - keep
        if drop <= 0:
            return
        self._write_lines(lines[drop:])
        self.dropped += drop
        self.count = keep

    def _read_lines(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            return []

    def _write_lines(self, lines):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")
        os.replace(tmp, self.path)   # 재작성 도중 정전에도 파일이 깨지지 않도록 원자 교체

    def replay(self, publish_fn):
        """재연결 시 호출. batch 만큼만 밀어넣고 남은 건 다음 호출로 미룬다
        (한 번에 쏟아부으면 복구 직후 브로커·자신의 큐를 다시 막는다).
        publish_fn(topic, payload, qos) -> bool 로 성공 여부를 돌려받는다.
        보낸 개수를 반환."""
        lines = self._read_lines()
        if not lines:
            self.count = 0
            return 0
        sent = 0
        for ln in lines[: self.batch]:
            try:
                rec = json.loads(ln)
            except ValueError:
                sent += 1        # 깨진 줄은 버린다 (되살릴 방법이 없다)
                continue
            payload = rec["payload"]
            payload["replayed"] = True
            if not publish_fn(rec["topic"], payload, rec["qos"]):
                break            # 또 끊겼다 — 여기서 멈추고 순서를 지킨다
            sent += 1
        if sent:
            self._write_lines(lines[sent:])
            self.count = len(lines) - sent
        return sent

    @property
    def pending(self):
        return self.count
