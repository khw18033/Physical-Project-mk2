# Edge box bring-up in one command each. Shell + docker compose + kubectl only —
# no extra tooling (docs/ai/design/hardware-capability-contract-and-bringup-plan.md §4).
#
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
LEVEL     ?= 1
TAGS      ?=
DEVICE    ?=
PYTEST    = PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PY) -m pytest -q -p no:cacheprovider

export KUBECONFIG

.PHONY: up down ps label smoke check ui view view-solo preview bootstrap test help

help:
	@sed -n '2,12p' Makefile

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
