"""GPS 간섭 판정 — 꺼짐 대비 켜짐."""

from sar_pass.emi import summarize, verdict


def S(sats, acc, fix, n=20):
    return [{"sats": sats, "h_acc_m": acc, "fix": fix} for _ in range(n)]


def test_clean_and_suspect():
    off = summarize(S(24, 0.014, "RTK_FIXED"))
    same = summarize(S(23, 0.015, "RTK_FIXED"))
    assert verdict(off, same)["suspect"] is False
    jam = summarize(S(19, 0.030, "RTK_FIXED", 10) + S(19, 0.5, "RTK_FLOAT", 10))
    v = verdict(off, jam)
    assert v["suspect"] and len(v["reasons"]) == 3
    assert verdict(off, None)["suspect"] is None and summarize([]) is None
