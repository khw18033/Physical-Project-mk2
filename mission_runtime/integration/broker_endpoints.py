"""브로커 주소는 **선언**이고, 닿는가는 **보는 자리마다 다른 관측**이다.

implements: AI-C-18, AI-C-10, AI-C-15, AI-O-06
tests: tests/test_broker_endpoints.py

## 왜 생겼나 (2026-11-05 실측)

가시화 화면의 로봇 브로커 프리셋은 주소 한 줄이었다 —
`ws://pi7.tailcb6bfb.ts.net:9001/mqtt`. 그 한 줄이 **두 사실을 한 칸에** 담고 있었다.

    브로커가 어디 있는가              pi7 · 오버레이 안 · 9001 웹소켓
    이 브라우저가 어디에 닿는가       **보는 자리마다 다르다**

둘째를 첫째에 접어 넣은 결과가 이번 증상이다. 우리는 WSL 에서 그 주소로 CONNACK
Success 까지 갔고, 브라우저(Windows, 오버레이 없음)는 같은 주소로 "연결이
닫혔습니다" 를 봤다. **우리가 닿았다는 것은 브라우저에 대해 아무것도 말해 주지
않는다.** 그런데 화면에는 "브로커 ✕" 하나만 떴고, 그것은 브로커가 죽었다는 말로
읽힌다 — 브로커는 멀쩡했다.

그리고 주소가 가시화 코드에 박혀 있어서 **로봇을 한 대 늘리면 코드를 고쳐야**
했다. 「장치 추가는 코드 변경이 아니다」가 거기서 깨진다(AI-C-15, 원칙 #7).

## 어떻게 고쳤나

주소를 선언으로 옮기고, **닿는가를 관측으로 분리한다.**

- 선언(`broker_endpoints`): 어느 노드의 브로커이고 어느 장치를 받는가, 어떤 전송
  이고 주소가 무엇이며 **어느 범위에서 풀리는 주소인가**(`scope`).
- 관측: 자리마다 하나씩. 게이트웨이가 본 것은 `vantage="gateway"` 이고 브라우저가
  본 것은 `vantage="viewer"` 다. 한 칸에 합치지 않는다.

`scope` 가 핵심이다. `overlay` 주소는 **오버레이 안에서만** 풀린다(원칙 #10) —
밖에서 안 풀리는 것은 고장이 아니라 그 주소의 성질이다. 그 사실이 데이터에 있으면
화면은 "경로가 없다" 와 "브로커가 죽었다" 를 가려서 말할 수 있다.

## 재지 않은 것을 재었다고 하지 않는다

게이트웨이는 `--broker` 로 **받은 하나**에만 실제로 붙는다. 나머지 주소는 묻지
않았으므로 `observed=None`(미측정)이고 사유는 `not_probed` 다. 쓰지도 않을 주소를
매 요청마다 찔러 보는 것은 자원 최소화에 어긋나고(AI-C-13), 무엇보다 **브라우저가
닿는지는 우리가 재 줄 수 없다** — 그 자리는 브라우저가 재야 한다.

`tcp_open` 과 `mqtt_accepted` 도 다른 사실이다. TCP 가 열린 것이 MQTT 가 수락한
것은 아니다 — 그래서 관측에 **무엇을 쟀는지**가 함께 남는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ── scope: 그 주소가 **어디서** 풀리는가 ────────────────────────────────────

#: 보안 오버레이 안에서만 풀린다(원칙 #10 — 구간은 오버레이 위에서만). 밖에서
#: 안 풀리는 것은 **고장이 아니라 그 주소의 성질이다.**
SCOPE_OVERLAY = "overlay"
#: 같은 로컬 망에서 풀린다. 현장 랜·발표장 등.
SCOPE_LAN = "lan"
#: **보는 사람의 기계 안**(`127.0.0.1`). 개발 편의로 세운 다리 같은 것이고,
#: 다른 기계에서는 참이 아니다 — 그래서 선언에 섞여 들어오면 안 되고 런타임에만
#: 붙는다(`tools/vz_gateway/serve.py --viewer-bridge`).
SCOPE_LOOPBACK = "loopback"

SCOPES = (SCOPE_OVERLAY, SCOPE_LAN, SCOPE_LOOPBACK)

#: 선언이 주소 대신 쓸 수 있는 이름. "**지금 가시화가 붙어 있는 그 기계**" 다.
#:
#: 왜 필요한가: 로봇 SDK 를 들고 있는 기계가 가시화 노트북이다. 그 기계의 주소를
#: 선언에 박으면 노트북을 바꿀 때마다 선언을 고쳐야 하고, 고치는 것을 잊으면
#: 운영자는 "명령이 안 간다" 만 본다. 붙어 있는 쪽의 주소는 **우리가 이미 안다** —
#: 그 연결이 어디서 왔는지가 소켓에 적혀 있다. 그래서 이름으로 적고 런타임에 푼다.
HOST_VIEWER = "viewer"

#: 오버레이 주소의 범위. Tailscale 이 쓰는 CGNAT 대역(100.64.0.0/10)과 그 DNS 이름.
#: 벤더 열거형이 아니라 **그 제품이 공표한 대역**이고, 다른 오버레이를 쓰면 이
#: 판정식이 아니라 선언(`scope`)이 답한다.
OVERLAY_V4_PREFIX_BITS = 10
OVERLAY_V4_NETWORK = (100, 64, 0, 0)
OVERLAY_DNS_SUFFIX = ".ts.net"

#: 가시화 주소를 받지 못한 이유. 문구가 아니라 토큰이다.
REASON_VIEWER_UNKNOWN = "viewer_address_unknown"
REASON_VIEWER_NOT_OVERLAY = "viewer_address_not_on_overlay"


def scope_of_address(host: str) -> str:
    """그 주소가 **어디서 풀리는가**를 주소 모양으로 가른다.

    선언이 적어 주는 `scope` 가 있을 때는 그것이 정본이다. 이 함수는 선언이 없는
    주소(런타임에 알게 된 것 — 붙어 온 가시화의 주소)를 가를 때만 쓴다.
    """
    name = (host or "").strip().strip("[]").lower()
    if not name:
        return SCOPE_LOOPBACK
    if name.endswith(OVERLAY_DNS_SUFFIX):
        return SCOPE_OVERLAY
    if name in ("localhost", "::1") or name.startswith("127."):
        return SCOPE_LOOPBACK
    parts = name.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        octets = tuple(int(part) for part in parts)
        if octets[0] == OVERLAY_V4_NETWORK[0] and 64 <= octets[1] <= 127:
            return SCOPE_OVERLAY
        return SCOPE_LAN
    return SCOPE_LAN

#: 고를 때의 **순서**. 실제 지형(오버레이·랜)을 먼저 보고, 개발 편의는 맨 뒤다 —
#: 오버레이 안에 있는 기계가 다리를 거쳐 돌아가는 일이 없어야 한다.
SCOPE_ORDER = {SCOPE_OVERLAY: 0, SCOPE_LAN: 1, SCOPE_LOOPBACK: 2}

# ── 전송 ────────────────────────────────────────────────────────────────────

#: 브라우저가 쓸 수 있는 유일한 쪽. 웹소켓 위의 MQTT.
TRANSPORT_MQTT_WS = "mqtt-ws"
#: 서버·엣지 쪽 평문 TCP MQTT. 브라우저는 못 쓴다.
TRANSPORT_MQTT_TCP = "mqtt-tcp"

TRANSPORTS = (TRANSPORT_MQTT_WS, TRANSPORT_MQTT_TCP)

# ── 관측: 자리마다 하나 ─────────────────────────────────────────────────────

#: 게이트웨이(서버·엣지 쪽)에서 본 것. **브라우저에 대해 아무 말도 하지 않는다.**
VANTAGE_GATEWAY = "gateway"
#: 화면(브라우저)에서 본 것. 그 자리는 브라우저만 잴 수 있다.
VANTAGE_VIEWER = "viewer"

#: MQTT 가 **수락**했다. 가장 강한 관측이다.
PROBE_MQTT_ACCEPTED = "mqtt_accepted"
#: TCP 만 열렸다. **수락과 다르다** — 브로커가 거절할 수도 있다.
PROBE_TCP_OPEN = "tcp_open"
#: 붙지 못했다.
PROBE_FAILED = "failed"
#: **묻지 않았다.** 거짓이 아니고 미달도 아니다(미측정 ≠ 0 ≠ 미달).
REASON_NOT_PROBED = "not_probed"


def split_host_port(spec: str, default_port: int) -> tuple[str, int] | None:
    """`host`·`host:port`·`[::1]`·`[::1]:port` 를 가른다. 모양이 아니면 `None`.

    **`partition(":")` 하나로 하면 IPv6 에서 깨진다** — `"::1:1884".partition(":")`
    는 host 를 빈 문자열로, port 를 `":1:1884"` 로 만든다. 실제로 그랬고 시험이
    잡았다. 괄호 없는 IPv6 에는 포트를 붙일 자리가 없으므로 전체를 host 로 읽는다.
    """
    spec = spec.strip()
    if not spec:
        return None
    if spec.startswith("["):                       # [::1] 또는 [::1]:1884
        host, closing, rest = spec[1:].partition("]")
        if not closing or not host:
            return None
        if not rest:
            return host, default_port
        if not rest.startswith(":"):
            return None
        try:
            return host, int(rest[1:])
        except ValueError:
            return None
    if spec.count(":") > 1:                        # 괄호 없는 IPv6 — 포트 자리가 없다
        return spec, default_port
    host, _, port = spec.partition(":")
    if not host:
        return None
    try:
        return host, int(port or default_port)
    except ValueError:
        return None


def authority_of(url: str) -> tuple[str, int] | None:
    """`scheme://host:port/path` 에서 host·port 만. 모양이 다르면 `None`.

    짝짓기를 **부분문자열로 하지 않기 위해** 있다 — `10.0.0.1:1883` 이
    `110.0.0.1:1883` 에도 걸리면 엉뚱한 주소에 우리 관측이 붙는다.
    """
    if "://" not in url:
        return None
    rest = url.split("://", 1)[1].split("/", 1)[0]
    if ":" not in rest.rsplit("]", 1)[-1] and not rest.startswith("["):
        # 포트가 없으면 짝짓기에 쓸 수 없다 — 기본값을 지어내지 않는다.
        return None
    return split_host_port(rest, 0) or None


@dataclass(frozen=True)
class BrokerEndpoint:
    """브로커 하나의 **선언**. 닿는가는 여기 없다."""

    node_id: str
    url: str
    scope: str
    transport: str = TRANSPORT_MQTT_WS
    #: 이 브로커를 거쳐 말하는 장치들. 비면 "그 노드만" 이다.
    serves: tuple[str, ...] = ()
    #: 사람이 고를 때 읽는 이름. 없으면 화면이 `node_id` 로 적는다.
    label: str | None = None
    #: 왜 이 주소가 있는가. 개발 편의라면 **그렇게 적힌다.**
    note: str | None = None

    def as_declaration(self) -> dict:
        out = {
            "node_id": self.node_id,
            "url": self.url,
            "scope": self.scope,
            "transport": self.transport,
            # 브라우저가 쓸 수 있는가는 **전송에서 유도되는** 값이다. 따로 정하지
            # 않는다 — 한 사실에 주인은 하나다.
            "browser_usable": self.transport == TRANSPORT_MQTT_WS,
            "serves": list(self.serves) or [self.node_id],
        }
        if self.label is not None:
            out["label"] = self.label
        if self.note is not None:
            out["note"] = self.note
        return out


class UnknownScope(ValueError):
    """선언에 없는 범위. **고르지 않고 거절한다**(AI-S-03 과 같은 축)."""


class UnknownTransport(ValueError):
    pass


def load_broker_endpoints(config: Any) -> tuple[BrokerEndpoint, ...]:
    """선언 파일에서 읽는다. 없으면 **빈 묶음** — 정상 배치다.

    주소를 선언하지 않은 현장은 있을 수 있고(화면이 직접 입력으로 쓴다), 그때
    프레임워크가 주소를 지어내서는 안 된다.
    """
    rows = (config or {}).get("broker_endpoints") or []
    out = []
    for row in rows:
        scope = row.get("scope")
        if scope not in SCOPES:
            raise UnknownScope(
                f"선언되지 않은 범위 {scope!r} — {SCOPES} 중 하나여야 한다. "
                "범위를 모르면 화면은 '밖에서 안 풀린다' 와 '브로커가 죽었다' 를 "
                "가릴 수 없다")
        if scope == SCOPE_LOOPBACK:
            raise UnknownScope(
                f"{row.get('url')!r}: loopback 주소는 **선언에 담지 않는다** — "
                "기계마다 다르므로 다른 현장에서 거짓이 된다. 런타임에 "
                "`--viewer-bridge` 로 붙인다")
        transport = row.get("transport", TRANSPORT_MQTT_WS)
        if transport not in TRANSPORTS:
            raise UnknownTransport(
                f"선언되지 않은 전송 {transport!r} — {TRANSPORTS} 중 하나여야 한다")
        out.append(BrokerEndpoint(
            node_id=row["node_id"], url=row["url"], scope=scope,
            transport=transport, serves=tuple(row.get("serves") or ()),
            label=row.get("label"), note=row.get("note")))
    return tuple(out)


@dataclass
class EndpointObservation:
    """**어느 자리에서** 무엇을 쟀는가. 자리를 빼면 의미가 없다."""

    vantage: str
    #: `PROBE_*` 중 하나, 또는 `None` = 재지 않았다.
    probe: str | None = None
    reason: str | None = None
    at: float | None = None

    def as_dict(self) -> dict:
        return {"vantage": self.vantage, "probe": self.probe,
                "reason": self.reason, "at": self.at}


@dataclass
class BrokerEndpointDirectory:
    """선언된 주소들 + **자리별** 관측. 화면이 읽는 한 칸을 만든다."""

    endpoints: tuple[BrokerEndpoint, ...] = ()
    #: url → 관측 목록. 자리마다 하나씩 쌓인다.
    observations: dict[str, list[EndpointObservation]] = field(default_factory=dict)
    #: **지금 붙어 있는 가시화의 주소.** 관측이고 선언이 아니다 — 그 연결이 어디서
    #: 왔는지가 소켓에 적혀 있고, 그것 말고 이 사실을 아는 길이 없다.
    viewer_host: str | None = field(default=None)
    #: 그 주소를 쓰지 않는 이유(오버레이 밖이었다 등). 비면 쓸 수 있다는 뜻이다.
    viewer_reason: str | None = field(default=REASON_VIEWER_UNKNOWN)

    def note_viewer(self, host: str | None) -> str | None:
        """가시화가 붙어 온 주소를 적는다. **오버레이 밖이면 쓰지 않는다.**

        쓰지 않는 이유: 구역 엣지와 서버 사이는 공개 인터넷을 경유하지 않고 보안
        오버레이 위에서만 연결한다(원칙 #10). 랜 주소를 받아 로봇 주소로 쓰면 그
        경계가 조용히 깨지고, 깨진 뒤에는 "왜 저 주소로 갔지" 를 되짚을 수 없다.
        거절도 **사유를 남긴다** — 조용히 무시하면 운영자는 자기 노트북이 왜 안
        잡히는지 알 수 없다.
        """
        if not host:
            self.viewer_host, self.viewer_reason = None, REASON_VIEWER_UNKNOWN
            return self.viewer_reason
        if scope_of_address(host) is not SCOPE_OVERLAY:
            self.viewer_host = None
            self.viewer_reason = f"{REASON_VIEWER_NOT_OVERLAY}:{host}"
            return self.viewer_reason
        self.viewer_host, self.viewer_reason = host, None
        return None

    def resolve(self, url: str) -> tuple[str | None, str | None]:
        """선언의 `viewer` 를 지금 붙어 있는 주소로 바꾼다.

        돌려주는 둘째 값은 **바꾸지 못한 이유**다. 주소를 지어내지 않는다 — 모르면
        `None` 이고, 그 사실이 화면에 그대로 간다.
        """
        if HOST_VIEWER not in url:
            return url, None
        if self.viewer_host is None:
            return None, self.viewer_reason or REASON_VIEWER_UNKNOWN
        return url.replace(HOST_VIEWER, self.viewer_host), None

    def observe(self, url: str, observation: EndpointObservation) -> None:
        """같은 자리의 관측은 **갈아 끼운다** — 자리마다 최신 하나다."""
        rows = self.observations.setdefault(url, [])
        for index, existing in enumerate(rows):
            if existing.vantage == observation.vantage:
                rows[index] = observation
                return
        rows.append(observation)

    def add_viewer_bridge(self, url: str, *, serves: Iterable[str] = (),
                          label: str | None = None) -> BrokerEndpoint:
        """보는 사람의 기계에 세운 다리를 **런타임에** 붙인다.

        선언에 담지 않는 이유는 `SCOPE_LOOPBACK` 에 적어 두었다. 붙일 때마다
        **개발 편의라는 사실이 함께 나간다** — 화면이 그 사실을 지우지 못한다.
        """
        endpoint = BrokerEndpoint(
            node_id="viewer-bridge", url=url, scope=SCOPE_LOOPBACK,
            transport=TRANSPORT_MQTT_WS,
            serves=tuple(serves) or tuple(sorted(
                {d for e in self.endpoints for d in (e.serves or (e.node_id,))})),
            label=label or "다리 (개발 편의)",
            note=("보는 사람의 기계에서만 참이다. 제대로 된 해결은 그 기계에 "
                  "오버레이를 설치하는 것이고, 이 주소는 그것을 대신하지 않는다"))
        self.endpoints = self.endpoints + (endpoint,)
        return endpoint

    def matching(self, host: str, port: int) -> tuple[BrokerEndpoint, ...]:
        """그 host·port 를 가리키는 선언들. **부분문자열로 찾지 않는다.**"""
        return tuple(e for e in self.endpoints
                     if authority_of(e.url) == (host, port))

    def candidate_declarations(self, device_id: str) -> tuple[dict, ...]:
        """그 장치를 받는 주소들을 **해소해서** 낸다.

        `viewer` 를 풀지 못한 선언도 **목록에서 빠지지 않는다** — 빠지면 선언한 적
        없는 것과 같아 보이고, 운영자는 "주소가 왜 없지" 가 아니라 "선언을 안 했나"
        를 의심한다. 못 푼 줄은 `url` 이 `null` 이고 사유가 붙는다.
        """
        rows: list[dict] = []
        for endpoint in self.candidates_for(device_id):
            declared = endpoint.as_declaration()
            resolved, reason = self.resolve(endpoint.url)
            declared["url"] = resolved
            if reason is not None:
                declared["unresolved"] = reason
            rows.append(declared)
        return tuple(rows)

    def candidates_for(self, device_id: str) -> tuple[BrokerEndpoint, ...]:
        """그 장치를 받는 주소들, **고를 순서대로**.

        브라우저가 쓸 수 없는 전송(평문 TCP)은 섞지 않는다 — 고를 수 없는 것을
        목록에 넣으면 사람이 고르고 나서 실패한다.
        """
        rows = [e for e in self.endpoints
                if e.transport == TRANSPORT_MQTT_WS
                and (device_id in (e.serves or (e.node_id,)))]
        # **scope 로만 정렬한다.** 같은 scope 안의 순서는 선언에 적힌 순서를 그대로
        # 둔다 — 이름을 먼저 적고 IP 를 뒤에 적은 것은 적은 사람의 판단이고(이름은
        # IP 가 바뀌어도 같다), 글자로 다시 정렬하면 그 판단이 사라진다.
        return tuple(sorted(rows, key=lambda e: SCOPE_ORDER.get(e.scope, 9)))

    def snapshot(self) -> dict:
        """화면이 **아무 때나** 물을 수 있는 칸."""
        rows = []
        for endpoint in sorted(self.endpoints,
                               key=lambda e: SCOPE_ORDER.get(e.scope, 9)):
            row = endpoint.as_declaration()
            observed = self.observations.get(endpoint.url, [])
            row["observed"] = [o.as_dict() for o in observed] or None
            if not observed:
                # 재지 않은 것을 재었다고 하지 않는다.
                row["observed_reason"] = REASON_NOT_PROBED
            rows.append(row)
        return {
            "endpoints": rows,
            # **이 문장이 이 모듈의 존재 이유다.** 화면이 이것을 읽고 자기 관측을
            # 더해야 한다 — 우리 관측을 자기 것으로 쓰면 같은 버그가 돌아온다.
            "note": ("주소는 선언이고 닿는가는 **보는 자리마다 다른 관측**이다. "
                     "여기 있는 관측은 게이트웨이 자리의 것이고 브라우저가 닿는지는 "
                     "말해 주지 않는다 — 화면이 직접 걸어 보고 그 결과를 자기 "
                     "자리의 관측으로 더해야 한다. `scope: overlay` 주소가 밖에서 "
                     "안 풀리는 것은 고장이 아니라 그 주소의 성질이다(원칙 #10)."),
        }
