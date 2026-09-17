# Tailscale

## 메타데이터
- categories: Mesh VPN, WireGuard 기반 암호화, NAT Traversal, Zero Trust Access Control
- domain: [[관측·보안]], [[전송·프로토콜]]
- source: Tailscale Inc. "Tailscale Docs" 및 "WireGuard concepts." Tailscale Documentation, 2026(access).
- url: https://tailscale.com/docs ; https://tailscale.com/docs/concepts/wireguard
- year: 확인 필요(문서 페이지에 개정 연도 명시 없음)
- authors: Tailscale Inc.
- venue: Tailscale 공식 문서 (tailscale.com/docs)

## 1. 핵심 요약
- Tailscale은 스스로를 "Zero Trust identity-based connectivity platform"으로 정의하며, 기존 VPN/SASE/PAM을 대체해 원격 팀, 멀티클라우드, CI/CD, Edge & IoT 장치, AI workload를 연결한다고 설명한다.
- Tailscale은 디바이스들 사이에 peer-to-peer mesh network("tailnet")를 구성하며, 중앙 게이트웨이를 거치지 않고 direct 연결을 지향한다.
- 연결 자체는 오픈소스 WireGuard 프로토콜 기반의 암호화된 point-to-point 연결을 사용하며(`wireguard-go`의 자체 fork를 클라이언트에 포함), 여기에 NAT traversal, TCP transport, access control policy를 추가로 구축한 것이 Tailscale이라고 설명한다.
- WireGuard 자체는 "open source network tunneling protocol"로, OpenVPN·IPsec 같은 기존 VPN 프로토콜을 대체하기 위한 더 단순하고 가벼운 대안으로 설계되었으며 독립 암호학자들의 프로토콜 리뷰와 보안 감사자들의 구현 코드 검토를 받았다고 명시한다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 네트워크(방화벽·NAT 뒤)에 있는 장치들을 공개 인터넷에 직접 노출하지 않으면서 안전하게 상호 연결해야 하는 문제, 그리고 기존 VPN/SASE/PAM 구성의 복잡성.
- 기술적 목표: WireGuard 기반의 암호화된 연결 위에 mesh 토폴로지, NAT traversal, 인증·접근 제어(access control policy)를 결합한 connectivity platform을 제공하는 것.
- 다루는 범위: Tailscale의 개요와 개념 소개, tailnet(mesh network) 구조, WireGuard와의 관계 및 차별점, subnet router·exit node 등 네트워크 확장 기능, access control(ACL) 정책.

## 3. 핵심 개념 상세
### Zero Trust Identity-based Connectivity Platform
- 원문 표현: "Tailscale is a Zero Trust identity-based connectivity platform that replaces your legacy VPN, SASE, and PAM and connects remote teams, multi-cloud environments, CI/CD pipelines, Edge & IoT devices, and AI workloads."
- 정의: 네트워크 위치가 아니라 장치·사용자의 identity를 신뢰의 기준으로 삼는(Zero Trust) 연결 플랫폼.
- 역할: 서로 다른 위치의 노드들이 네트워크 경로(사설망/공인망 여부)가 아니라 각자의 identity로 인증된 상태에서만 연결되도록 하며, 공인 IP·포트를 공개 인터넷에 노출하지 않고도 노드 간 신뢰 연결을 구성할 수 있게 하는 근거가 된다.

### Mesh Network(Tailnet)
- 원문 표현: "Tailscale creates a peer-to-peer mesh network (known as a tailnet)."
- 정의: 참여 장치들이 중앙 게이트웨이를 거치지 않고 서로 직접(peer-to-peer) 연결되는 네트워크 토폴로지.
- 역할: 지리적으로 분산된 노드들을 중앙 게이트웨이 병목 없이 하나의 사설 오버레이 네트워크로 묶는 데 사용되며, 상위 애플리케이션은 구체적인 mesh 구현을 알 필요 없이 "연결 가능한 사설망"이라는 추상 수준에서만 이를 소비할 수 있다.

### WireGuard 기반 암호화
- 원문 표현: "It enables encrypted point-to-point connections using the open source WireGuard protocol, which means only devices on your private network can communicate with each other." / "Tailscale maintains a fork of the open source `wireguard-go` package, which comes with Tailscale clients."
- 정의: 장치 간 실제 데이터 전송 채널을 오픈소스 WireGuard 프로토콜로 암호화하는 방식이며, Tailscale은 `wireguard-go`의 자체 fork를 클라이언트에 내장해 사용한다.
- 역할: 분산된 노드 간 통신 구간이 공개 인터넷을 경유하더라도 암호화된 채널로만 통신하도록 보장하는 실제 암호화 계층이다.

### NAT Traversal
- 원문 표현: "Connections between tailnet devices work seamlessly across firewalls and Network Address Translation (NAT) without requiring port forwarding or complex firewall rules."
- 정의: 방화벽이나 NAT 뒤에 있는 장치들끼리도 포트포워딩이나 복잡한 방화벽 규칙 없이 연결이 성립하도록 하는 기능.
- 역할: NAT나 방화벽 뒤에 있는 노드가 공인 IP나 별도 포트 개방 없이도 다른 노드와 연결될 수 있게 하는 근거로, 폐쇄망·사내망 환경에서도 안전한 노드 간 연결이 가능함을 뒷받침한다.

### Access Control (Identity/Access Control)
- 원문 표현: "a zero-trust architecture" featuring "access control policies"(WebFetch 요약 기준; 정확한 원문 문장은 페이지 축약 결과로만 확인되어 별도 직접 인용은 하지 않음)
- 정의: 장치·사용자의 identity를 기준으로 어떤 피어가 어떤 리소스에 접근할 수 있는지를 정책으로 제어하는 기능.
- 역할: 노드 간 연결이 성립하더라도 임의의 서비스·포트에 무제한 접근하지 않도록, 애플리케이션 계층의 인증·인가(예: 메시지 브로커 ACL, 클러스터 RBAC)와는 별도로 네트워크 계층에서 1차 접근 제어를 제공한다.

### WireGuard 프로토콜 자체의 설계 목표
- 원문 표현: "An open source network tunneling protocol for creating encrypted communication channels." / WireGuard aims to "replace other VPN protocols, such as OpenVPN and IPsec, as a simpler and lighter-weight alternative." / "maintains concurrent connections with minimal overhead per session." / "Independent cryptographers have reviewed the WireGuard protocol, and security auditors have examined the code implementation."
- 정의: 암호화된 통신 채널을 만들기 위한 오픈소스 터널링 프로토콜로, 기존 VPN 프로토콜보다 단순하고 가벼운 것을 목표로 설계되었으며 독립적인 암호학적 검토와 코드 감사를 받았다.
- 역할: Tailscale이 왜 WireGuard를 기반으로 선택했는지에 대한 근거(단순성, 낮은 오버헤드, 검증된 보안성)이며, 특정 제품을 오버레이 네트워크 provider로 채택하더라도 그 밑바탕 암호화 프로토콜 자체의 신뢰성을 평가하는 기준이 된다.

## 4. 구조 및 흐름
1. 각 장치에 Tailscale 클라이언트를 설치하고 identity 기반으로 tailnet에 등록(인증)한다.
2. Tailscale 클라이언트는 내장된 `wireguard-go` fork를 이용해 다른 tailnet 장치와 암호화된 WireGuard 연결을 시도한다.
3. 장치가 NAT/방화벽 뒤에 있어도 NAT traversal 메커니즘을 통해 포트포워딩 없이 연결을 수립한다(직접 연결이 불가능한 경우 relay를 경유할 수 있음 — 이 relay 동작의 세부는 이번 페치 범위에서 확인하지 못함, "원문 확인 안 됨").
4. 연결이 수립된 뒤에도 access control policy(ACL)가 어떤 장치가 어떤 리소스·포트에 접근 가능한지를 강제한다.
5. 상위 애플리케이션은 이 tailnet 위의 사설 IP/도메인으로만 통신하며, 공개 인터넷에는 노출되지 않는다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Tailscale은 identity 기반의 Zero Trust connectivity platform이다 | "Tailscale is a Zero Trust identity-based connectivity platform that replaces your legacy VPN, SASE, and PAM..." |
| Tailscale은 WireGuard 기반의 암호화된 연결을 mesh 형태로 제공한다 | "Tailscale creates a peer-to-peer mesh network (known as a tailnet)." + "It enables encrypted point-to-point connections using the open source WireGuard protocol..." |
| Tailscale은 포트포워딩·복잡한 방화벽 설정 없이 NAT/방화벽을 넘어 연결을 성립시킨다 | "Connections between tailnet devices work seamlessly across firewalls and Network Address Translation (NAT) without requiring port forwarding or complex firewall rules." |
| WireGuard는 기존 VPN 프로토콜보다 단순하고 검증된 보안성을 갖는다 | "replace other VPN protocols, such as OpenVPN and IPsec, as a simpler and lighter-weight alternative." + "Independent cryptographers have reviewed the WireGuard protocol, and security auditors have examined the code implementation." |

## 6. 한계 및 부족한 점
- 이번 WebFetch 범위에서는 Tailscale이 실제로 다른 WireGuard 기반 VPN과 동시 실행될 때 충돌 가능성을 스스로 인정한다: "Tailscale has received reports of technical conflicts when running concurrent with other WireGuard-based VPNs," 그 원인은 "how each implementation handles network interfaces and routing tables"라고 설명한다. 즉 동일 노드에 다른 WireGuard 기반 VPN을 동시에 설치하면 충돌 위험이 있다는 점을 문서가 스스로 경고한다.
- Access control 항목의 정확한 원문 문장은 이번 WebFetch 요약 결과에서 패러프레이즈로만 확인되었고, 직접 인용 가능한 원문 문장은 확보하지 못했다 — "원문 확인 안 됨"으로 표시했다.
- NAT traversal이 실패했을 때의 relay(DERP 등) 동작 방식, 대역폭·지연 영향, 그리고 대규모(수백~수천 노드) tailnet에서의 성능 한계는 이번 페치 범위에서 확인하지 못했다.

## 7. 원문 기반 핵심 문장
> "Tailscale is a Zero Trust identity-based connectivity platform that replaces your legacy VPN, SASE, and PAM and connects remote teams, multi-cloud environments, CI/CD pipelines, Edge & IoT devices, and AI workloads."
