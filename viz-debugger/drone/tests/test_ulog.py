"""`.ulg` 받기 — 어느 비행 폴더에 두나 · 가장 최근 로그 고르기."""

from types import SimpleNamespace

from sar_pass.ulog import flight_dir_for, newest


def test_flight_dir_for_picks_the_flight_in_progress(tmp_path):
    for t in (1000, 5000, 9000):
        (tmp_path / f"flight_{t}").mkdir()
    (tmp_path / "flight_x").mkdir()
    assert flight_dir_for(tmp_path, 6000).name == "flight_5000"
    assert flight_dir_for(tmp_path, 9001).name == "flight_9000"
    assert flight_dir_for(tmp_path, 900).name == "ulog"                       # 그 전엔 비행이 없었다
    assert flight_dir_for(tmp_path, 9000 + 4 * 3600).name == "ulog"           # 너무 오래된 비행에 붙이지 않는다


def test_newest_entry():
    E = lambda i, d: SimpleNamespace(id=i, date=d, size_bytes=1)  # noqa: E731
    assert newest([E(1, "2026-10-03T02:04:46Z"), E(3, "2026-10-03T03:19:19Z"), E(2, "2026-10-03T03:13:53Z")]).id == 3
    assert newest([E(1, ""), E(2, "")]).id == 2
    assert newest([]) is None
