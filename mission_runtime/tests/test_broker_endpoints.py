"""주소는 선언이고, **닿는가는 자리마다 다른 관측이다.**

implements: AI-C-18, AI-C-10, AI-C-15, AI-O-06
tests: declaration carries scope, loopback refused in declaration, candidates
       exclude non-browser transports and order overlay first, gateway vantage
       never speaks for the viewer, unprobed is not failed, the real config loads
"""
from __future__ import annotations

import json
import pathlib

import pytest

from integration.broker_endpoints import (
    PROBE_FAILED,
    PROBE_MQTT_ACCEPTED,
    REASON_NOT_PROBED,
    SCOPE_LAN,
    SCOPE_LOOPBACK,
    SCOPE_OVERLAY,
    TRANSPORT_MQTT_TCP,
    TRANSPORT_MQTT_WS,
    VANTAGE_GATEWAY,
    VANTAGE_VIEWER,
    BrokerEndpoint,
    BrokerEndpointDirectory,
    EndpointObservation,
    UnknownScope,
    UnknownTransport,
    load_broker_endpoints,
)

_CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config" / "status_ui.json"


def _directory() -> BrokerEndpointDirectory:
    return BrokerEndpointDirectory(endpoints=(
        BrokerEndpoint("pi7", "ws://pi7.ts.net:9001/mqtt", SCOPE_OVERLAY,
                       serves=("go1-001",)),
        BrokerEndpoint("pi7", "mqtt://100.0.0.1:1883", SCOPE_OVERLAY,
                       transport=TRANSPORT_MQTT_TCP, serves=("go1-001",)),
        BrokerEndpoint("pi7", "ws://192.168.50.172:9001/mqtt", SCOPE_LAN,
                       serves=("go1-001",)),
    ))


def test_declaration_says_where_the_address_resolves():
    row = BrokerEndpoint("pi7", "ws://pi7.ts.net:9001/mqtt",
                         SCOPE_OVERLAY).as_declaration()
    assert row["scope"] == SCOPE_OVERLAY
    # 브라우저가 쓸 수 있는가는 전송에서 **유도된다** — 따로 적지 않는다.
    assert row["browser_usable"] is True
    # serves 를 비우면 그 노드 자신이다. 빈 목록으로 내보내지 않는다.
    assert row["serves"] == ["pi7"]


def test_plain_tcp_is_declared_but_not_browser_usable():
    row = BrokerEndpoint("pi7", "mqtt://10.0.0.1:1883", SCOPE_OVERLAY,
                         transport=TRANSPORT_MQTT_TCP).as_declaration()
    assert row["browser_usable"] is False


def test_an_unknown_scope_is_refused_not_guessed():
    with pytest.raises(UnknownScope):
        load_broker_endpoints({"broker_endpoints": [
            {"node_id": "pi7", "url": "ws://x:9001/mqtt", "scope": "somewhere"}]})


def test_an_unknown_transport_is_refused():
    with pytest.raises(UnknownTransport):
        load_broker_endpoints({"broker_endpoints": [
            {"node_id": "pi7", "url": "ws://x:9001/mqtt",
             "scope": SCOPE_OVERLAY, "transport": "carrier-pigeon"}]})


def test_a_loopback_address_cannot_be_declared():
    """기계마다 다른 것을 선언에 담으면 다른 현장에서 거짓이 된다."""
    with pytest.raises(UnknownScope, match="loopback"):
        load_broker_endpoints({"broker_endpoints": [
            {"node_id": "bridge", "url": "ws://127.0.0.1:9001/mqtt",
             "scope": SCOPE_LOOPBACK}]})


def test_no_declaration_is_a_normal_deployment():
    assert load_broker_endpoints({}) == ()
    assert load_broker_endpoints(None) == ()


def test_candidates_drop_transports_the_browser_cannot_use():
    rows = _directory().candidates_for("go1-001")
    urls = [e.url for e in rows]
    assert all(e.transport == TRANSPORT_MQTT_WS for e in rows)
    assert "mqtt://100.0.0.1:1883" not in urls


def test_candidates_put_the_real_topology_before_the_dev_bridge():
    directory = _directory()
    directory.add_viewer_bridge("ws://127.0.0.1:9001/mqtt", serves=("go1-001",))
    scopes = [e.scope for e in directory.candidates_for("go1-001")]
    # 오버레이 → 랜 → 다리. 오버레이 안에 있는 기계가 다리를 거쳐 돌아가면 안 된다.
    assert scopes == [SCOPE_OVERLAY, SCOPE_LAN, SCOPE_LOOPBACK]


def test_the_dev_bridge_carries_the_fact_that_it_is_one():
    directory = BrokerEndpointDirectory()
    endpoint = directory.add_viewer_bridge("ws://127.0.0.1:9001/mqtt")
    assert endpoint.scope == SCOPE_LOOPBACK
    assert "오버레이를 설치" in (endpoint.note or ""), \
        "다리가 해결책처럼 보이면 같은 문제가 조용히 남는다"
    assert "개발 편의" in (endpoint.label or "")


def test_a_device_not_served_gets_no_candidates():
    assert _directory().candidates_for("drone-001") == ()


def test_unprobed_is_not_failed():
    snap = _directory().snapshot()
    for row in snap["endpoints"]:
        assert row["observed"] is None
        # 묻지 않은 것은 실패가 아니다(미측정 ≠ 0 ≠ 미달).
        assert row["observed_reason"] == REASON_NOT_PROBED


def test_the_gateway_vantage_never_speaks_for_the_viewer():
    """이것이 이 모듈이 생긴 이유다 — 둘이 같은 칸에 있었다."""
    directory = _directory()
    url = "ws://pi7.ts.net:9001/mqtt"
    directory.observe(url, EndpointObservation(
        vantage=VANTAGE_GATEWAY, probe=PROBE_MQTT_ACCEPTED, at=1.0))
    row = next(r for r in directory.snapshot()["endpoints"] if r["url"] == url)

    vantages = [o["vantage"] for o in row["observed"]]
    assert vantages == [VANTAGE_GATEWAY]
    # **브라우저 자리는 비어 있다.** 우리 관측이 그 자리를 채우지 않는다.
    assert VANTAGE_VIEWER not in vantages
    assert "브라우저가 닿는지는" in directory.snapshot()["note"]


def test_the_two_vantages_can_disagree_and_both_survive():
    directory = _directory()
    url = "ws://pi7.ts.net:9001/mqtt"
    directory.observe(url, EndpointObservation(VANTAGE_GATEWAY,
                                               PROBE_MQTT_ACCEPTED, at=1.0))
    directory.observe(url, EndpointObservation(VANTAGE_VIEWER, PROBE_FAILED,
                                               reason="경로가 없다", at=2.0))
    row = next(r for r in directory.snapshot()["endpoints"] if r["url"] == url)
    seen = {o["vantage"]: o["probe"] for o in row["observed"]}
    # 실제로 일어난 일이다: 우리는 닿았고 브라우저는 못 닿았다.
    assert seen == {VANTAGE_GATEWAY: PROBE_MQTT_ACCEPTED,
                    VANTAGE_VIEWER: PROBE_FAILED}


def test_a_newer_observation_from_the_same_vantage_replaces_the_old_one():
    directory = _directory()
    url = "ws://pi7.ts.net:9001/mqtt"
    directory.observe(url, EndpointObservation(VANTAGE_GATEWAY, PROBE_FAILED, at=1.0))
    directory.observe(url, EndpointObservation(VANTAGE_GATEWAY,
                                               PROBE_MQTT_ACCEPTED, at=2.0))
    row = next(r for r in directory.snapshot()["endpoints"] if r["url"] == url)
    assert len(row["observed"]) == 1
    assert row["observed"][0]["probe"] == PROBE_MQTT_ACCEPTED


def test_the_real_deployment_config_declares_the_live_broker():
    """선언이 실제 현장과 맞는지. 가시화 코드에 박힌 주소를 여기로 옮긴 자리다."""
    with open(_CONFIG, encoding="utf-8") as handle:
        endpoints = load_broker_endpoints(json.load(handle))
    assert endpoints, "브로커 주소가 선언되지 않았다 — 가시화가 다시 박아야 한다"
    urls = {e.url for e in endpoints}
    assert "ws://pi7.tailcb6bfb.ts.net:9001/mqtt" in urls
    assert all(e.scope != SCOPE_LOOPBACK for e in endpoints)

    directory = BrokerEndpointDirectory(endpoints=endpoints)
    candidates = directory.candidates_for("go1-001")
    assert candidates, "go1-001 을 받는 브라우저용 주소가 선언에 없다"
    assert all(e.transport == TRANSPORT_MQTT_WS for e in candidates)


def test_matching_is_not_a_substring_search():
    """부분문자열로 찾으면 엉뚱한 주소에 우리 관측이 붙는다."""
    directory = BrokerEndpointDirectory(endpoints=(
        BrokerEndpoint("a", "mqtt://10.0.0.1:1883", SCOPE_OVERLAY,
                       transport=TRANSPORT_MQTT_TCP),
        BrokerEndpoint("b", "mqtt://110.0.0.1:1883", SCOPE_OVERLAY,
                       transport=TRANSPORT_MQTT_TCP),
    ))
    hits = directory.matching("10.0.0.1", 1883)
    assert [e.node_id for e in hits] == ["a"]


def test_authority_refuses_what_it_cannot_read():
    from integration.broker_endpoints import authority_of
    assert authority_of("ws://pi7.ts.net:9001/mqtt") == ("pi7.ts.net", 9001)
    assert authority_of("mqtt://10.0.0.1:1883") == ("10.0.0.1", 1883)
    # 포트가 없으면 짝짓기에 쓸 수 없다 — 기본값을 지어내지 않는다.
    assert authority_of("ws://pi7.ts.net/mqtt") is None
    assert authority_of("pi7.ts.net:9001") is None
    assert authority_of("ws://pi7.ts.net:nope/mqtt") is None


def test_order_within_a_scope_follows_the_declaration_not_the_alphabet():
    """이름을 먼저 적은 것은 적은 사람의 판단이다 — 글자로 다시 정렬하면 사라진다."""
    directory = BrokerEndpointDirectory(endpoints=(
        BrokerEndpoint("pi7", "ws://pi7.ts.net:9001/mqtt", SCOPE_OVERLAY,
                       serves=("go1-001",)),
        BrokerEndpoint("pi7", "ws://100.0.0.1:9001/mqtt", SCOPE_OVERLAY,
                       serves=("go1-001",)),
    ))
    urls = [e.url for e in directory.candidates_for("go1-001")]
    assert urls == ["ws://pi7.ts.net:9001/mqtt", "ws://100.0.0.1:9001/mqtt"]
    # 스냅샷도 같은 순서여야 한다 — 화면과 도구가 다른 순서를 보면 안 된다.
    assert [r["url"] for r in directory.snapshot()["endpoints"]] == urls


def test_the_real_config_offers_the_name_before_the_ip():
    with open(_CONFIG, encoding="utf-8") as handle:
        endpoints = load_broker_endpoints(json.load(handle))
    urls = [e.url for e in
            BrokerEndpointDirectory(endpoints=endpoints).candidates_for("go1-001")]
    assert urls[0] == "ws://pi7.tailcb6bfb.ts.net:9001/mqtt", (
        "이름이 먼저여야 한다 — IP 는 MagicDNS 가 안 풀릴 때의 대안이고, "
        f"이름은 IP 가 바뀌어도 같다. 지금 순서: {urls}")
