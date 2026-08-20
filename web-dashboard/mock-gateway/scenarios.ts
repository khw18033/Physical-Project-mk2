/**
 * mock-gateway/scenarios.ts
 *
 * 상태 전이 재생 스크립트. 화면이 "정상일 때 잘 보인다"만으로는 검증이 안 되고,
 * **전이하는 순간**이 맞는지를 봐야 하므로 전이를 손으로 재생할 수 있어야 한다.
 *
 * 실행: `npm run scenario -- camera-silence`  또는  WS로 { type: 'scenario', name: ... }
 */

import { INTERVALS, SCENARIO_TIMING, THRESHOLDS } from './config.ts';
import type { Fleet } from './devices.ts';
import type { Hub } from './hub.ts';

export type Scenario = {
  name: string;
  title: string;
  /** 사람이 화면에서 무엇을 봐야 하는가. */
  expect: string;
  run(ctx: { hub: Hub; fleet: Fleet }): string;
};

const seconds = (ms: number) => Math.round(ms / 1000);

export const SCENARIOS: Scenario[] = [
  {
    name: 'camera-silence',
    title: 'camera-02 침묵 → stale 전이',
    expect:
      'camera-02 카드가 ' + seconds(THRESHOLDS.STALE_MS) + '초 뒤 "판단 불가"로 바뀐다. ' +
      'availability만 stale이 되고 device_status는 마지막 자기보고(ok)가 그대로 남아 있어야 한다 — ' +
      '두 층이 각각 다른 주체의 말이라는 근거.',
    run({ fleet }) {
      const cam = fleet.cameras.get('camera-02');
      if (!cam) return 'camera-02 없음';
      cam.silent = true;
      return (
        'camera-02 발행 중지. 서버가 ' + seconds(INTERVALS.AVAILABILITY_SWEEP_MS) +
        '초마다 재판정하므로 약 ' + seconds(THRESHOLDS.STALE_MS) + '초 뒤 stale 전이가 푸시된다. ' +
        '되돌리려면 scenario camera-resume.'
      );
    },
  },
  {
    name: 'camera-resume',
    title: 'camera-02 발행 재개',
    expect: 'camera-02가 다시 15fps로 발행하며 다음 재판정에서 online으로 돌아온다.',
    run({ fleet }) {
      const cam = fleet.cameras.get('camera-02');
      if (!cam) return 'camera-02 없음';
      cam.silent = false;
      return 'camera-02 발행 재개.';
    },
  },
  {
    name: 'sensor-offline',
    title: 'sensor-02 연결 끊김 → offline 후 복구',
    expect:
      'sensor-02가 즉시 "장애"로 바뀌고(오프라인 감지는 5초 정기 발행을 기다리지 않는다), ' +
      seconds(SCENARIO_TIMING.SENSOR_OFFLINE_RECOVER_MS) + '초 뒤 "정상"으로 복구된다.',
    run({ hub, fleet }) {
      const sensor = fleet.sensors.get('sensor-02');
      const rt = hub.runtime.get('sensor-02');
      if (!sensor || !rt) return 'sensor-02 없음';

      sensor.silent = true;
      rt.forcedOffline = true;
      rt.note = 'LWT로 연결 단절 감지';
      hub.sweepAvailability(); // 전이를 즉시 밀어낸다.

      setTimeout(() => {
        sensor.silent = false;
        rt.forcedOffline = false;
        rt.note = null;
        // 복구 직후에는 last_seen이 오래되어 stale로 보일 수 있으므로 실제 값 하나를 먼저 낸다.
        sensor.surge(0);
        hub.sweepAvailability();
      }, SCENARIO_TIMING.SENSOR_OFFLINE_RECOVER_MS);

      return (
        'sensor-02 연결 두절 주입. ' +
        seconds(SCENARIO_TIMING.SENSOR_OFFLINE_RECOVER_MS) + '초 뒤 자동 복구.'
      );
    },
  },
  {
    name: 'sensor-surge',
    title: 'sensor-01 급변 → 즉시 발행 + 이벤트 모드(1초)',
    expect:
      '평시 1분 주기를 기다리지 않고 수위가 즉시 뛴다. 이후 ' +
      seconds(INTERVALS.SENSOR_EVENT_HOLD_MS) + '초 동안 1초 주기로 갱신되고 report_mode가 event로 표시된다.',
    run({ fleet }) {
      const sensor = fleet.sensors.get('sensor-01');
      if (!sensor) return 'sensor-01 없음';
      sensor.surge(0.62);
      return (
        'sensor-01 수위 +0.62m 급변, 즉시 발행. 이벤트 모드 ' +
        seconds(INTERVALS.SENSOR_EVENT_HOLD_MS) + '초(' +
        INTERVALS.SENSOR_EVENT_MS + 'ms 주기) 유지.'
      );
    },
  },
  {
    name: 'actuator-command',
    title: 'actuator-01 명령 → ACK → 동작 중 → 완료',
    expect:
      '수문 카드가 대기 → (ACK) → 동작 중(' + INTERVALS.ACTUATOR_MOVING_MS +
      'ms 주기로 진행률) → 완료 로 바뀐다. 표준 3층과 별개인 도메인 어휘다.',
    run({ fleet }) {
      const act = fleet.actuators.get('actuator-01');
      if (!act) return 'actuator-01 없음';
      const commandId = act.command(70);
      return (
        '수문 개도 70% 명령 왕복 시작 (command_id=' + commandId + '). ' +
        '명령은 목 서버 안에서만 왕복하며 실제 제어 발행 경로는 만들지 않는다.'
      );
    },
  },
  {
    name: 'robot-idle',
    title: 'robot-01 임무 종료 → 대기(5초 주기)',
    expect: 'robot-01 갱신이 50ms에서 5초로 떨어지고 1초 하트비트가 시작된다.',
    run({ fleet }) {
      const robot = fleet.robots.get('robot-01');
      if (!robot) return 'robot-01 없음';
      robot.mission = false;
      return 'robot-01 대기 모드. 상태 ' + INTERVALS.ROBOT_IDLE_MS + 'ms / 하트비트 ' + INTERVALS.ROBOT_HEARTBEAT_IDLE_MS + 'ms.';
    },
  },
  {
    name: 'robot-mission',
    title: 'robot-01 임무 시작 → 50ms(20Hz)',
    expect: 'robot-01이 다시 20Hz로 올라온다. 화면 리렌더는 초당 10회를 넘지 않아야 한다.',
    run({ fleet }) {
      const robot = fleet.robots.get('robot-01');
      if (!robot) return 'robot-01 없음';
      robot.mission = true;
      return 'robot-01 임무 모드. 상태 ' + INTERVALS.ROBOT_MISSION_MS + 'ms.';
    },
  },
];

export function runScenario(name: string, ctx: { hub: Hub; fleet: Fleet }): { ok: boolean; message: string } {
  const s = SCENARIOS.find((x) => x.name === name);
  if (!s) {
    return { ok: false, message: '알 수 없는 시나리오: ' + name + ' (사용 가능: ' + SCENARIOS.map((x) => x.name).join(', ') + ')' };
  }
  return { ok: true, message: s.run(ctx) };
}
