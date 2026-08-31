# 엣지노드 구성 절차 (임시: WSL2, 최종: 전용 리눅스 장비)

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-08-31 |
| 목적 | HW-C-03(K3s 컨테이너 배포·제거) 검증을 위한 구역 엣지노드 구성 |
| 현재 구성 | 개발 PC의 WSL2 Ubuntu 26.04 (**임시**) |
| 최종 구성 | 현장 전용 리눅스 장비. 아래 §5 참조 |

---

## 1. 왜 엣지에 두는가

제어평면(K3s server)은 **반드시 엣지노드에** 둔다. 말단에 두면 apiserver + 내장
데이터스토어가 곧 서버형 미들웨어가 되어 AI-B-10(말단 경량 실행 경계)을 위반하고,
etcd 의 쓰기 부하가 마이크로SD를 갉는다. 말단은 **agent(워커)로만** 편입한다.

말단의 안전 루프(계측·임계 판정·자율 주기 전환·하트비트·버퍼링)는 **systemd 로
상주**시키고 k3s 에 넣지 않는다. k3s agent 는 제어평면에 연결되지 못하면 컨테이너를
기동조차 하지 못하므로(k3s-io/k3s#1686), 안전 루프를 거기 넣으면 그 실패 모드를
그대로 상속한다. 자세한 근거는 `docs/SRS.md` §9.1~9.2.

---

## 2. 구성 (현재, WSL2)

### 2-1. 미러 네트워킹

WSL2 기본값은 NAT라 **말단이 엣지에 접근할 수 없다.** 미러 모드로 바꾸면 WSL이
호스트와 같은 LAN 주소를 갖는다.

`%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
firewall=false
```

> **`firewall=false` 가 핵심이다.** 미러 모드에서는 Hyper-V 방화벽이 인바운드를
> 기본 차단(`DefaultInboundAction: Block`)한다. 그 상태에서는 WSL 안의 K3s가 6443을
> 열고 있어도 말단에서 TLS 핸드셰이크가 reset 된다 — **TCP 연결은 되는데 인증서를
> 못 받는 형태로 나타나서 원인을 찾기 어렵다.**
> `New-NetFirewallHyperVRule` 로 포트별 허용 규칙을 넣는 방법도 있으나 **관리자 권한이
> 필요하다.** `.wslconfig` 는 권한 없이 되고 되돌리기도 쉽다.

적용: `wsl --shutdown` 후 재기동. 확인:

```powershell
wsl -d Ubuntu -- bash -lc "ip -4 addr show scope global | grep inet"
# 호스트와 같은 192.168.50.x 가 보이면 성공
```

### 2-2. K3s server 설치

```bash
export INSTALL_K3S_EXEC="server \
 --disable traefik --disable servicelb --disable metrics-server \
 --node-name edge-wsl \
 --node-ip <엣지IP> --advertise-address <엣지IP> --tls-san <엣지IP> \
 --write-kubeconfig-mode 644"
curl -sfL https://get.k3s.io | sh -
```

`traefik`·`servicelb`·`metrics-server`는 이 구간에 필요 없어 끈다 — 켜 두면 엣지 자원만
먹고 파드 목록이 지저분해진다.

### 2-3. 말단을 워커로 편입

`/etc/systemd/system/k3s-agent.service.env`:

```
K3S_URL=https://<엣지IP>:6443
K3S_TOKEN=<엣지의 /var/lib/rancher/k3s/server/node-token>
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart k3s-agent      # ⚠ start 는 이미 active 면 무동작이다
```

> **함정**: 이미 실행 중인 유닛에 `systemctl start` 는 아무 일도 하지 않는다.
> 환경 파일을 바꿨으면 반드시 **restart**. 실제로 이 때문에 옛 서버 주소를 계속
> 바라보며 조인이 안 되는 상태를 한동안 오진했다.

확인:

```bash
kubectl get nodes -o wide
# NAME       STATUS   ROLES           VERSION        INTERNAL-IP
# edge-wsl   Ready    control-plane   v1.36.4+k3s1   192.168.50.244
# pi7        Ready    <none>          v1.35.4+k3s1   192.168.50.172   ← 워커
```

---

## 3. 증강 기능 배포 (HW-C-03)

```bash
kubectl apply  -f pi/deploy/k8s/augment-analyzer.yaml   # 상황 발생
kubectl delete -f pi/deploy/k8s/augment-analyzer.yaml   # 상황 종료
```

`nodeSelector` 로 말단에 고정하고, `requests/limits` 로 폭주 컨테이너가 안전 루프를
굶기지 못하게 막는다. `imagePullPolicy: IfNotPresent` + 사전 pull 로 이벤트 시점의
pull(30~60초)을 피한다.

---

## 4. 검증 결과 (2026-08-31, pi7 실기)

| 항목 | 결과 |
|---|---|
| 말단 워커 편입 | `pi7 Ready <none>` (arm64, containerd 2.2.3) |
| 컨테이너 배포 | pi7 에 스케줄·기동, 파드 IP 10.42.1.2 |
| **셀프힐링** | `crictl stop` → Exit Code 137 → **K3s 자동 재기동(RESTARTS 1)** |
| 컨테이너 제거 | 파드 정리 완료, 노드는 Ready 유지 |
| **MQTT 1883 회귀** | k3s agent 활성 상태에서 계측·하트비트 정상 (1.0 Hz) — **flannel·kube-proxy 가 Debian 13 nftables 위에서 업무 경로에 간섭하지 않음** |
| **층 분리 (HW-S-05)** | 컨테이너가 죽는 동안에도 노드 하트비트는 끊기지 않았다. "컨테이너 장애"와 "노드 장애"가 실제로 구분된다 |

---

## 4-1. WSL 엣지의 알려진 한계 — 파드 간 오버레이가 통하지 않는다

제어평면 기능(스케줄링·배포·제거·셀프힐링)은 정상이지만, **말단 파드에서 엣지 파드로
가는 경로(flannel VXLAN)가 통하지 않는다.** 실측:

```
파이 파드 → 외부 인터넷(8.8.8.8:53)   : 도달 OK
파이 파드 → 엣지 CoreDNS 파드(10.42.0.22:53) : TimeoutError
```

결과적으로 **클러스터 DNS(10.43.0.10)가 말단 파드에서 죽는다.** 증상은 DNS 실패로
나타나므로("pypi.org 이름 해석 실패") 원인을 네트워크가 아니라 이미지·설정 쪽에서
찾기 쉽다.

**영향 범위와 대응**

| 대상 | 영향 |
|---|---|
| 말단 안전 루프(sensor/robot/actuator node) | **없음.** systemd 로 호스트 네트워크에서 돌고 브로커를 IP 로 직접 잡는다 |
| 증강 워크로드 | 클러스터 서비스 탐색 불가. `dnsPolicy: Default` 로 **노드 리졸버**를 쓰게 하면 동작한다 |
| 파드 간 통신이 필요한 워크로드 | 이 구성에서는 불가. 전용 엣지 장비 필요 |

말단의 증강 워크로드는 어차피 서비스 탐색을 쓰지 않고 브로커를 IP 로 잡으므로
`dnsPolicy: Default` 가 이 구성의 우회책이자, 실무적으로도 더 튼튼한 선택이다.
매니페스트에 반영해 두었다.

## 5. 최종 구성으로 넘어갈 때

WSL2 는 **검증용 임시 구성**이다. 현장에서는 다음이 필요하다.

| 항목 | 이유 |
|---|---|
| 전용 리눅스 장비 | 개발 PC 가 꺼지면 구역 전체가 제어평면을 잃는다 |
| SSD 저장 | etcd 는 쓰기 집약적이라 SD·eMMC 가 버티지 못한다 |
| Mosquitto 이전 | 현재 브로커는 Windows 에 있다. 엣지로 옮겨 한 장비에 모은다 |
| OTel Collector(Agent) | 현재는 검증용 최소 수신단. BE-S-02 의 Agent→Gateway 구조 실물 필요 |
| 미디어 게이트웨이 | HW-S-06·R-07 의 브라우저 재생 변환 (VZ-I-06) |
| TLS 인증서 | BE-T-01 의 MQTT 5.0 + TLS |
| 정상 동작하는 파드 오버레이 | §4-1 — WSL 엣지에서는 flannel VXLAN 이 말단까지 닿지 않는다 |

## 6. 되돌리기

```powershell
# WSL 네트워킹 원복
Copy-Item "$env:USERPROFILE\.wslconfig.bak-hw" "$env:USERPROFILE\.wslconfig" -Force
wsl --shutdown
```

```bash
# 엣지 K3s 제거
/usr/local/bin/k3s-uninstall.sh
# 말단 agent 제거 (또는 원래 서버 주소로 복원)
/usr/local/bin/k3s-agent-uninstall.sh
```
