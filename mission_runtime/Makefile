# Edge box bring-up in one command each. Shell + docker compose + kubectl only —
# no extra tooling (docs/ai/design/hardware-capability-contract-and-bringup-plan.md §4).
#
#   make install   받은 폴더 하나로 설치·점검·시험·기동까지 (docs/guides/deployment.md)
#   make backend   백엔드 **한 줄** — 컨테이너로 세운다(상시 실행). 내리기 backend-stop
#   make serve     백엔드를 세운다 — 조회 30 · 쓰기 20 (127.0.0.1:8899)
#   make open      같은 백엔드를 **다른 기계에서 붙을 수 있게** (0.0.0.0, 안내는 오버레이 주소)
#   make dist      배포 브랜치에 담을 것을 본다 (옮기려면 ARGS=--write)
#   make up        start mosquitto / kafka / otel-collector (dev: loopback; edge: AIF_BIND=<ip>)
#   make label     label this K3s node with its measured hardware tags (+ TAGS="tier.edge")
#   make smoke     probe registered devices, LEVEL=1|2|3 ARGS='--only pi6 --address-override pi6=pi6.example.ts.net'
#   make check     integration + cluster + smoke L1 — the "is this box ready" gate
#   make view      운영 상태 화면 + 가시화 콘솔을 한 명령으로 (127.0.0.1:8770)
#   make view-solo 우리 화면만
#   make preview   서버 없이 열리는 한 장으로 내보내기
#   make ui        옛 기능 상태 패널 (127.0.0.1:8765, CONFIG=... 로 예시 교체)
#   make down      stop the stack
#
# 말단(Raspberry Pi 등)에는 아무것도 설치하지 않는다 — 말단 배포는 `make bootstrap DEVICE=<id>`
# 가 providers/ondevice_bootstrap.py 를 통해 에이전트 스크립트 하나만 놓는다 (AI-B-10).

# venv 는 이 디렉터리나 저장소 루트 중 있는 곳을 쓴다 — 재분류로 자리가 바뀌었다.
PY        ?= $(shell test -x .venv/bin/python && echo "$(CURDIR)/.venv/bin/python" || echo "$(abspath $(CURDIR)/../.venv/bin/python)")
COMPOSE   ?= docker compose -f deploy/integration/docker-compose.yml
KUBECONFIG ?= $(HOME)/.kube/config
CONFIG    ?= config/status_ui.example.json
PORT      ?= 8899
DOMAINS   ?= profiles/domains.example.json
UICONFIG  ?= config/status_ui.fms.example.json
ARGS      ?=
LEVEL     ?= 1
TAGS      ?=
DEVICE    ?=
PYTEST    = PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PY) -m pytest -q -p no:cacheprovider

export KUBECONFIG

.PHONY: install backend backend-stop backend-status serve open dist up down ps label smoke check ui view view-solo preview bootstrap test help

help:
	@sed -n '2,18p' Makefile

# 받은 폴더 하나로 끝까지 — 가상환경·설치·자가점검·시험·기동 확인. 판정은 각 단계가
# 하고 이 목표는 순서만 잡는다(docs/guides/deployment.md).
install:
	bash tools/install_check.sh $(ARGS)

# **받은 기계에서 한 줄.** 도커가 있으면 컨테이너로(기계를 다시 켜도 돈다), 없으면
# 프로세스로 띄우고 그렇다고 말한다. 가시화가 읽는 자리 둘(8899 · 8765)을 함께 세운다.
backend:
	bash tools/backend.sh start

backend-stop:
	bash tools/backend.sh stop

backend-status:
	bash tools/backend.sh status

# 게이트웨이 하나만 앞에서 띄운다(개발용). 선언은 예시 현장이고 자기 현장은 두 깃발을 바꾼다.
serve:
	$(PY) tools/vz_gateway/serve.py --port $(PORT) \
	    --domains $(DOMAINS) --config $(UICONFIG)

# 프론트가 다른 노트북일 때. 듣는 주소는 모든 인터페이스이고 **안내문에 적히는
# 주소는 오버레이가 말하는 이 기계**다 — 0.0.0.0 을 안내하면 붙을 수 없다.
open:
	$(PY) tools/vz_gateway/serve.py --host 0.0.0.0 --port $(PORT) \
	    --domains $(DOMAINS) --config $(UICONFIG)

# 배포 브랜치(jny_opensource-dist)에 담을 것. 기본은 보기만 하고, 옮기려면
# `make dist ARGS=--write` 다. 푸시는 사람이 한다.
dist:
	$(PY) tools/release/make_dist.py $(ARGS)

up:
	mkdir -p deploy/integration/artifacts
	# otelcol-contrib runs as uid 10001 and writes output.json here; a dir created by an
	# earlier root-run docker is unwritable to it -> restart loop. Fix ownership via a
	# throwaway container so no sudo is needed on the host.
	docker run --rm -v "$(CURDIR)/deploy/integration/artifacts:/a" busybox:latest chmod 1777 /a
	$(COMPOSE) up -d
	$(COMPOSE) ps

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

label:
	$(PY) tools/infra/label_node.py $(foreach t,$(TAGS),--tag $(t))

smoke:
	$(PY) tools/hw_smoke/run.py --level $(LEVEL) $(ARGS)

bootstrap:
	@test -n "$(DEVICE)" || (echo "usage: make bootstrap DEVICE=<device_id>" && exit 2)
	$(PY) tools/infra/bootstrap_device.py --device $(DEVICE)

ui:
	$(PY) tools/status_ui/serve.py --config $(CONFIG)

# 운영 상태 화면 — **명령 하나로** 우리 화면과 가시화 콘솔을 함께 띄운다.
# 콘솔은 Node 22.6+ 가 있고 third_party/vz-web-dashboard 에 npm install 이 끝났을 때만
# 뜨고, 없으면 우리 화면만 뜬다(선택 구성요소 결손은 축소다).
view:
	$(PY) tools/snapshot_ui/serve.py --with-console

# 가시화 콘솔 없이 우리 화면만.
view-solo:
	$(PY) tools/snapshot_ui/serve.py

# 서버 없이 열리는 한 장으로 내보낸다(검토를 남에게 보여 줄 때).
preview:
	$(PY) tools/snapshot_ui/serve.py --static ../local/dashboard-preview.html

test:
	$(PYTEST) 2>/dev/null | tail -1

check: up
	$(PYTEST) tests/test_wire_integration.py tests/test_k3s_control.py tests/test_infra_label_node.py 2>/dev/null | tail -1
	-$(PY) tools/hw_smoke/run.py --level 1
