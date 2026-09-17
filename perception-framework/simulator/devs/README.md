# simulator/devs — pyjevsim atomic models

DEVS(Discrete Event System Specification) 엔진 [pyjevsim](https://github.com/eventsim/pyjevsim)
(`pyproject.toml`의 `sim` extra) 위에 구현한 atomic model들이다. `simulator/runner.py`가
시나리오 JSON의 `"nodes"`/`"type"`을 여기 클래스로 매핑한다.

| type | 클래스 | 무엇을 흉내내는가 |
|---|---|---|
| `registry_node` | `registry_node.py::RegistryNode` | `CapabilityRegistry`+`ZoneApplication`+`ResourceAdaptiveReconfigurer` — registry/profile/자원재구성 계열 |
| `physical_command_device` | `physical_command_device.py::PhysicalCommandDeviceNode` | `terminal/<device-id>/{downlink,uplink}` 반대편 장치(interface-spec) |

## pyjevsim을 직접 clone해서 확인하며 얻은, 문서에 없는 함정 3가지

이 세 가지를 모르면 새 atomic model이 조용히 잘못 동작한다(assert가 통과하는 게 아니라
**아무 것도 안 하는데 에러도 안 나는** 형태로 망가진다 — 실제로 이 프로젝트의
`PhysicalCommandDeviceNode` 초안이 정확히 이렇게 망가졌었다).

### 1. `update_state(name, deadline)`는 상태를 "전이"하지 않는다

```python
self.update_state("EXECUTING", 3.0)  # _cur_state는 그대로 "IDLE"!
```

`BehaviorExecutor.time_advance()`는 `behavior_model._states[behavior_model._cur_state]`를
읽는다 — 즉 `_cur_state`가 실제로 바뀌어야 다음 deadline이 반영된다. `update_state()`는
deadline **표**의 항목 하나만 고칠 뿐 `_cur_state`를 옮기지 않는다(`pyjevsim/
behavior_model.py`의 `update_state` 정의 자체가 `self._states[name] = float(deadline)`
한 줄이다). `examples/banksim/model/model_user_gen.py`를 보면 항상
`self._cur_state = "GEN"`을 **직접 대입**한 뒤에만 `update_state`를 호출한다.

**해야 하는 것**: 상태를 실제로 옮기고 싶으면 `self._cur_state = name`을 직접 하거나,
이 저장소의 두 모델처럼 그 둘을 합친 헬퍼(`_goto`/`RegistryNode`는 상태가 하나뿐이라
불필요)를 쓴다.

### 2. `ext_trans`/`output`/`int_trans` 안에서 `self.global_time`은 믿을 수 없다

`BehaviorExecutor.set_req_time(global_time)`이 `bm.global_time = global_time`을 갱신하는데,
`schedule()`의 Phase C(전이 실행)는 이 갱신(Phase D)보다 **먼저** 일어난다. 즉 모델
자신의 전이 메서드 안에서 읽는 `self.global_time`은 "지금"이 아니라 "내가 마지막으로
스케줄된 그 시점"이다 — 첫 참여라면 생성자 시점 값(보통 0)이 그대로 보인다. 실측:

```python
def ext_trans(self, port, msg):
    print(self.global_time)  # scheduled_time=3으로 넣은 이벤트인데 0이 찍힌다
```

**해야 하는 것**: 모델 내부에서 "지금이 몇 시인지" 계산에 `self.global_time`을 쓰지
않는다. `runner.py`는 이 문제를 아예 피하려고 `SysExecutor.get_global_time()`(엔진 자신의
값 — 이건 정확하다)만 신뢰하고, 매 checkpoint 시각마다 `simulate()`를 나눠 호출한 뒤
그 시점에 새로 생긴 trace만 그 checkpoint 시각으로 표시한다.

### 3. `simulate(_time)`은 정확히 그 순간에 예정된 이벤트를 놓칠 수 있다

`schedule()`은 매번 `handle_external_input_event()`(큐의 `scheduled_time <= global_time`인
것만 배달)로 시작하는데, `simulate()`의 루프 조건이 `while global_time < target_time`이라
**global_time이 target_time에 정확히 도달하는 바로 그 라운드**에서는 아직
`handle_external_input_event()`를 다시 부르지 않은 채 루프가 끝난다 — `scheduled_time`이
정확히 그 target과 같은 이벤트는 배달되지 않고 큐에 남는다. 실측(3개 이벤트를 각각
1.0/2.0/3.0에 예약하고 매 정수 시각마다 `simulate()`를 나눠 부른 결과, 항상 한 틱씩
밀려서 도착):

```text
after target 1.0 global_time= 1.0 calls so far: []
after target 2.0 global_time= 2.0 calls so far: [이벤트 'a']
after target 3.0 global_time= 3.0 calls so far: [이벤트 'a', 이벤트 'b']
```

**해야 하는 것**: `runner.py`는 각 checkpoint로 이동할 때 정확히 그 시각이 아니라
`checkpoint_time + 1e-6`만큼 진행한다(`_FLUSH_EPS`) — 이러면 그 순간 예정된 이벤트를
처리하는 한 라운드가 더 돌고, 그 뒤에 상태를 읽는다. `Checkpoint.time`에는 이 보정값이
아니라 원래 의도한 `checkpoint_time`을 그대로 저장하므로 시나리오 JSON의 `"at"`/`"after"`
값과 어긋나지 않는다.

## 새 atomic model을 추가할 때

1. `pyjevsim.behavior_model.BehaviorModel`을 상속한다.
2. 생성자에서 `insert_input_port`/`insert_output_port`, `init_state`로 시작 상태를 정하고
   그 상태의 deadline을 `update_state`(또는 위 1번 문제를 감안해 직접 `_states[name]=...`)로
   등록한다.
3. `ext_trans(port, msg)`는 `msg.retrieve()`로 들어온 값 리스트를 순회한다.
4. 상태를 옮길 때마다 `self._cur_state = name`을 직접 하는 것을 잊지 않는다(위 1번).
5. `output(md)`는 `self._cur_state`를 보고 무엇을 내보낼지 결정한다 — `self.global_time`이
   아니라(위 2번). `SysMessage(self.get_name(), port_name)`을 만들고
   `md.insert_message(msg)`로 넘긴다.
6. 이 저장소의 관례상 각 모델은 `self.trace: list[dict]`에 `{"direction": "in"|"out",
   "port": ..., "payload": ...}` 형태로 자기 입출력을 남긴다 — `runner.py`가 이 리스트를
   읽어 checkpoint별로 `ScenarioResult.trace`에 모은다(모델마다 다른 키를 쓰면 `simulation.py`의
   narration이 깨진다 — 반드시 `"payload"` 키를 쓴다).
7. `simulator/runner.py`의 `_NODE_TYPES` 딕셔너리에 새 `"type"` 문자열을 등록한다.
