"""chrony SOCK refclock 형식 — chrony 의 struct sock_sample 과 같은 바이트."""

import socket

from sar_pass.chrony_fc import SAMPLE, SOCK_MAGIC, ChronySock, pack_sample


def test_sample_layout_and_send(tmp_path):
    assert SAMPLE.size == 40                      # chrony: 16(timeval) + 8(double) + 4×4
    sec, usec, off, pulse, leap, _pad, magic = SAMPLE.unpack(pack_sample(1790000000.9999996, -0.0123))
    assert (sec, usec) == (1790000001, 0) and abs(off + 0.0123) < 1e-12 and magic == SOCK_MAGIC and pulse == leap == 0
    path = str(tmp_path / "c.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    assert ChronySock(path).send(1790000000.25, 0.004)
    got = SAMPLE.unpack(srv.recv(64))
    assert got[0] == 1790000000 and got[1] == 250000 and abs(got[2] - 0.004) < 1e-12
    assert not ChronySock(str(tmp_path / "none.sock")).send(1.0, 0.0)   # chrony 없으면 조용히 실패
