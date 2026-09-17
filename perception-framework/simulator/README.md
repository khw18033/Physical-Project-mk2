# simulator

하드웨어 없이 프레임워크의 성질(선택 기능 축소, provider 교체, 도메인 전환, 장애 격리,
물리 명령 lifecycle 등)을 확인하는 단일 실행 도구다. **pyjevsim**(DEVS — Discrete Event
System Specification 엔진, `pip install -e ".[sim]"`) 위에서 돈다 — 시나리오는 평평한
이벤트 목록이 아니라 실제 시뮬레이션 시간 축을 가진 노드 토폴로지다.

```bash
pip install -e ".[sim]"                                                    # 최초 1회
PYTHONPATH=. python3 simulator/simulation.py                               # 시나리오 경로를 키보드로 입력
PYTHONPATH=. python3 simulator/simulation.py simulator/scenarios/s03-resource-shedding.json
```

같은 JSON 시나리오 파일이 `tests/test_scenarios.py`에서 pytest 자동 검증 입력으로도 쓰인다 —
시나리오 하나를 작성하면 사람이 보는 데모와 회귀 검증을 동시에 얻는다
(`pytest tests/test_scenarios.py`).

## 구조

```text
simulator/
  runner.py       # 시나리오 JSON -> SysExecutor 토폴로지 구성 -> 시간축 재생 -> 기대값 검증
  simulation.py   # 사람이 실행하는 진입점 (narrate)
  devs/           # pyjevsim atomic model 구현 (registry_node.py, physical_command_device.py)
                  # + README.md: pyjevsim을 직접 써보며 발견한 타이밍 함정 3가지
  scenarios/*.json
```

## 시나리오 JSON 스키마

```json
{
  "id": "고유 식별자",
  "description": "무엇을 확인하는 시나리오인지, 관련 요구사항 ID",
  "nodes": [
    {
      "id": "registry", "type": "registry_node",
      "profile": {"domain_id": "...", "active_capability_kinds": ["..."], "node_tags": ["cpu"]},
      "capabilities": [
        {"kind": "perception.detect", "core": true},
        {"kind": "service.optional", "rank": 1, "requires": ["perception.depth"]}
      ],
      "providers": [
        {"kind": "perception.detect", "provider_id": "cam-1", "priority": 50,
         "compute": 1.0, "memory": 64.0, "hw_tags": ["cpu"], "preferred_hw_tags": [],
         "health_ref": "cam-1-health"}
      ],
      "budget": {"compute_units": 30.0, "memory_mb": 4096.0}
    },
    {
      "id": "robot1", "type": "physical_command_device",
      "capabilities": [{"name": "navigate.relative"}],
      "accept_delay": 0.5, "exec_time": 2.0, "stop_delay": 0.2
    }
  ],
  "couplings": [
    {"from": ["nodeA", "portX"], "to": ["nodeB", "portY"]}
  ],
  "stimuli": [
    {"at": 0.0, "port": "control", "target": "registry", "label": "hotplug",
     "msg": {"op": "register_provider", "kind": "...", "provider_id": "..."}},
    {"at": 3.0, "port": "downlink", "target": "robot1", "label": "command_sent",
     "msg": {"message_type": "command", "payload": {"command_id": "c-1", "target": "robot1",
                                                      "action": "navigate.relative", "parameters": {}}}}
  ],
  "run_until": 10.0,
  "expectations": [
    {"type": "capability_state", "node": "registry", "after": "hotplug", "state": {"perception.detect": "ACTIVE"}},
    {"type": "provider_id", "node": "registry", "after": "hotplug", "provider": {"perception.detect": "cam-1"}},
    {"type": "reason", "node": "registry", "after": "hotplug", "reason": {"perception.detect": "selected"}},
    {"type": "core_kinds_running", "node": "registry", "value": true},
    {"type": "degradation_count_at_least", "node": "registry", "value": 1},
    {"type": "recovery_count_at_least", "node": "registry", "value": 1},
    {"type": "event_logged", "node": "registry", "name": "capability_state_changed", "severity": "error",
     "payload_contains": {"capability_kind": "perception.detect"}},
    {"type": "conformance", "node": "registry", "provider": {"kind": "...", "provider_id": "..."}, "must_pass": true},
    {"type": "source_scan", "forbidden_tokens": ["vendor_name"], "dirs": ["perception", "risk"]},
    {"type": "trace_contains", "node": "robot1", "port": "uplink", "message_type": "result",
     "payload_contains": {"command_id": "c-1", "status": "SUCCEEDED"}, "at_or_before": 5.0}
  ]
}
```

- **`nodes`**: 이 시나리오가 만드는 DEVS atomic model들. `type`이 `simulator/devs/`의 어떤
  클래스로 만들지 정한다(등록표는 `devs/README.md`). `id`/`type` 외의 키는 그대로 해당
  클래스의 생성자 키워드 인자로 전달된다.
- **`couplings`**: 두 노드의 포트를 잇는다(`SysExecutor.coupling_relation`). 지금 시나리오는
  전부 노드 하나짜리라 비어 있다 — 예를 들어 물리 명령 gateway 노드가 추가되면
  `[{"from": ["gateway", "downlink"], "to": ["robot1", "downlink"]}, ...]`처럼 쓰게 된다.
- **`stimuli`**: 시뮬레이션 시간 축 위에서 특정 노드의 특정 포트로 주입하는 외부 이벤트.
  `at`이 절대 시뮬레이션 시각, `target`+`port`가 목적지, `msg`가 페이로드(노드 타입마다
  형식이 다르다 — `registry_node`는 `{"op": ...}`, `physical_command_device`는
  `{"message_type": ..., "payload": {...}}`, interface-spec의 실제 봉투 형식과 동일).
  `label`을 붙이면 `expectations`의 `"after"`에서 그 시각을 이름으로 참조할 수 있다.
- **`run_until`**: 시뮬레이션이 끝까지 도달해야 하는 시각. 이 시각까지 아무 stimulus가
  없어도 checkpoint 하나가 이 시각에 찍힌다.
- **`expectations`**: `after`(checkpoint 시각 또는 label, 생략하면 마지막 checkpoint)를
  기준으로 그 노드의 상태/trace를 검사한다. `core_kinds_running`/`degradation_count_at_least`/
  `recovery_count_at_least`는 항상 **마지막** checkpoint 기준이다(해당 노드가 자기
  누적 카운터·직전 resolve 결과만 들고 있기 때문 — 중간 시점을 확인하려면
  `capability_state`/`trace_contains`를 쓴다). `trace_contains`의 `at_or_before`는
  checkpoint 단위 해상도다(정확한 시각이 아니라 "이 checkpoint까지는 나타났다") — 여러
  개의 개별 stimulus 시각을 그대로 checkpoint로 쓰면 원하는 만큼 세밀하게 나눌 수 있다.

## 이 시스템이 다루는 범위

registry/profile/자원재구성 계열(`registry_node`)과 `terminal/<device-id>/{downlink,uplink}`
물리 명령 lifecycle(`physical_command_device`, 실제 시뮬레이션 시간 지연·취소 경쟁까지)을
다룬다. 실 MQTT/Kafka 브로커, 카메라 보정 파일, 명령 supervisor의 SQLite 상태처럼 진짜
외부 인프라가 필요한 검증은 `tests/` 아래 별도 pytest 파일로 남아 있다 — 문서화는
`docs/ai/validation/framework-property-scenarios.md` 참고. 개별 모듈 단위의 세밀한 검증은
`tests/test_integration_functional_check.py` 하나로 통합했다.

## 새 시나리오 추가

1. `scenarios/`에 JSON 파일 하나를 추가한다.
2. `PYTHONPATH=. python3 simulator/simulation.py simulator/scenarios/<파일>`로 직접 실행해
   기대한 로그가 나오는지 확인한다.
3. `pytest tests/test_scenarios.py`가 자동으로 새 파일을 주워 검증한다.
4. 기존 두 노드 타입(`registry_node`, `physical_command_device`)으로 표현할 수 없는 새로운
   종류의 시나리오가 필요하면 `simulator/devs/`에 새 `BehaviorModel` 서브클래스를 추가하고
   `runner.py`의 `_NODE_TYPES`에 등록한다 — **`devs/README.md`의 타이밍 함정 3가지를 먼저
   읽는다**, 특히 `update_state()`가 `_cur_state`를 옮기지 않는다는 점.
