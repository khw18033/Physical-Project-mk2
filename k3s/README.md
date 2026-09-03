# 쿠버네티스(K3s) 현황 · 복구 정보 — 피지컬팀 mk2

> 갱신: 2026-09-03 · 담당: HW 파트 · 브랜치: `HW`
> 목적: SD 재구축된 pi1 의 K3s 편입이 왜 실패하고, 무엇이 있으면 복구되는지 한곳에 정리.

이 폴더는 **쿠버네티스 관련 정리 전용**이다. 실제 매니페스트·이미지는 `pi/deploy/k8s/`,
`pi/augment/` 에 있고, 설계 근거는 `docs/SDD.md §7`·`docs/EDGE_SETUP.md` 에 있다.

---

## 1. 한 줄 결론

쿠버네티스는 **설계 1급 요소로 반영**되어 있고 이전에 검증(로드맵 5단계 ✅)까지 됐다.
그러나 **SD 재구축 후 pi1 의 클러스터 재편입은 미완**이다 — 원인은 네트워크가 아니라
**조인 토큰(CA 해시) 불일치**. 엣지 server 의 현재 node-token 만 있으면 복구된다.

---

## 2. 설계에 어떻게 반영돼 있나 (2계층)

`docs/SDD.md §7`, `docs/EDGE_SETUP.md` 기준. 원칙 P1: *안전 루프는 브로커·엣지·오케스트레이터가
전부 죽어도 동작해야 한다.*

| 계층 | 실행 형태 | 담당 | 원칙 |
|---|---|---|---|
| **systemd** (상시·안전) | `sensor/robot/actuator -node.service` | 계측·임계판정·자율전환·하트비트·LWT·버퍼링 | **절대 k3s 에 넣지 않는다** |
| **K3s** (증강·일시) | 엣지 server + 말단 agent, Deployment/Job | 온디바이스 AI 추론, 영상 분석, 모델 배포(HW-C-03) | 없어도 안전 루프 무사 |

- 제어평면(k3s server)은 **엣지노드에만** 둔다(말단에 두면 apiserver 부담·실패모드 상속).
- 말단은 **agent** 만 편입한다. agent 는 제어평면에 못 붙으면 컨테이너를 기동조차 못 하므로
  (k3s-io/k3s#1686), 안전 루프를 여기 넣으면 그 실패 모드를 물려받는다 → 그래서 분리.
- 자원 격리: 모든 파드 requests/limits, `*-node.service` 에 `OOMScoreAdjust=-500`.
- 네트워크 회귀: flannel·kube-proxy 가 MQTT 1883 에 간섭하지 않는지 **k3s 활성화 직후 검증 필수**.

구현물:
```
pi/deploy/k8s/augment-analyzer.yaml       증강 워크로드(운영: 이미지 digest 고정)
pi/deploy/k8s/augment-analyzer-dev.yaml   증강 워크로드(개발: python:3.13-slim + 코드 마운트)
pi/augment/analyzer.py                     증강 분석 예시(수위 추세·임계 도달 예측)
pi/augment/Dockerfile, build.sh            arm64 이미지 빌드(레지스트리 없으면 ctr import)
```

---

## 3. 현재 pi1 상태 (실측 2026-09-03)

| 항목 | 상태 |
|---|---|
| `k3s` / `kubectl` 바이너리 | `/usr/local/bin/k3s`, `/usr/local/bin/kubectl` **있음** |
| `k3s-agent.service` | 로드됨, `activating`(편입 실패로 Ready 못 됨) |
| `/etc/rancher`, `/var/lib/rancher` | **있음** (재구축 때 복원됨) |
| agent 대상 server | `K3S_URL=https://210.110.250.33:6443` |
| server 도달성 | **도달됨**(TLS 핸드셰이크·CA 비교까지 진행) |
| 편입 결과 | **실패 — 토큰 CA 해시 불일치** |

### 실패 로그 (원인 확정)
```
k3s-agent: Failed to validate connection to cluster at https://210.110.250.33:6443:
  token CA hash does not match the Cluster CA certificate hash:
  1f526b0c3b2d558faaa261356f96ffca0474ac91dc0c7a0bc1ed84750a11dfe3   (pi1 이 가진 토큰의 CA 해시)
  != f3afef4c29cb20a8390dbf17e4ebb2d9b81607af73946116d8c571d8a9d09926 (server 의 현재 CA 해시)
```
→ **네트워크·방화벽 문제 아님.** 엣지 server 가 재설치되며 CA 가 바뀌었는데 pi1 의
`K3S_TOKEN` 은 옛 CA 해시를 물고 있어 조인 인증에서 거부된다.

토큰 저장 위치(pi1): `/etc/systemd/system/k3s-agent.service.env` (`K3S_TOKEN`, `K3S_URL`).

---

## 4. 복구에 필요한 정보 (⬅ 지금 막힌 지점)

**엣지 server(210.110.250.33)의 현재 node-token 1개**가 필요하다. HW 가 pi1 에서 꺼낼 수
없는 값이다 — 엣지/백엔드 팀이 server 에서 아래로 확인해 전달해야 한다.

```bash
# 엣지 K3s server 에서 (엣지/백엔드 팀)
sudo cat /var/lib/rancher/k3s/server/node-token
# 형식 예: K10<CA해시>::server:<비밀>
```

확인 요청 항목:
1. **현재 node-token** (위 명령 출력) — 필수.
2. server 주소가 여전히 `210.110.250.33:6443` 인지(바뀌었으면 새 주소).
3. 엣지 server 가 지금 **떠 있는지**(`sudo systemctl is-active k3s`).

---

## 5. 복구 절차 (토큰 받으면 HW 가 수행)

```bash
# 1) pi1: 토큰 갱신
sudo sed -i "s#^K3S_TOKEN=.*#K3S_TOKEN='<받은-node-token>'#" /etc/systemd/system/k3s-agent.service.env
#    server 주소가 바뀌었으면 K3S_URL 도 함께 수정

# 2) agent 재기동
sudo systemctl daemon-reload
sudo systemctl restart k3s-agent

# 3) 편입 확인 (엣지 server 또는 kubeconfig 있는 곳에서)
kubectl get nodes -o wide        # pi1 이 Ready 로 떠야 함
```

편입 성공 후:

```bash
# 4) 매니페스트 nodeSelector 갱신 — 현재 pi7 로 박혀 있어 pi1 에 스케줄 안 됨(§6)
#    pi/deploy/k8s/augment-analyzer.yaml, augment-analyzer-dev.yaml
#    kubernetes.io/hostname: pi7  →  pi1

# 5) 증강 이미지 사전 배치(레지스트리 없으면 import)
pi/augment/build.sh <registry>/hw-augment:<tag> import
sudo k3s ctr images import /tmp/hw-augment.tar    # 각 말단

# 6) HW-C-03 재검증: 배포 → 셀프힐 → 제거, 그리고 MQTT 1883 회귀
kubectl apply  -f pi/deploy/k8s/augment-analyzer.yaml
kubectl get pods -o wide -w                       # Running 확인
kubectl delete pod -l app=augment-analyzer        # 셀프힐(재생성) 확인
kubectl delete -f pi/deploy/k8s/augment-analyzer.yaml
# 회귀: 배포 중 sensor-node 하트비트·수위 보고·규약 명령이 계속되는지(P1) 관찰
```

---

## 6. 미결 이슈

| # | 내용 | 조치 |
|---|---|---|
| 1 | **조인 토큰 CA 불일치** — pi1 재편입 불가 | 엣지 server 의 현재 node-token 필요(§4) |
| 2 | 매니페스트 `nodeSelector: hostname: pi7` — 재구축으로 호스트는 **pi1** | 편입 후 `pi7→pi1` 수정(§5-4) |
| 3 | 증강 이미지 digest 미고정(운영 yaml 이 `REPLACE_WITH_DIGEST`) | `build.sh` 로 빌드 후 digest 고정 |
| 4 | k3s 활성화 후 **MQTT 1883 회귀 검증** 재수행 필요 | flannel/kube-proxy 간섭 여부 확인(§5-6) |

---

## 7. 참고 문서

- `docs/SDD.md §7` — K3s 설계(제어평면 배치, systemd vs k3s 분담, 자원 격리, 실패 모드)
- `docs/EDGE_SETUP.md` — 엣지노드(K3s server) 구성 절차
- `HW-interface/README.md` — 명령 통신 규약(systemd 층 명령 경로) 정리
