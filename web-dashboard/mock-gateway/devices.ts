/**
 * mock-gateway/devices.ts
 *
 * 가짜 장치들. **각 장치는 요구사항 시트가 정한 실제 주기로 발행한다** —
 * 주기를 실제와 다르게 두면 화면이 "잘 동작하는 것처럼" 보이다가 붙일 때 무너진다.
 * 모든 주기 숫자는 config.ts에서만 온다.
 *
 * 좌표는 **이미 전역 좌표로 변환된 값**을 낸다. 로컬→글로벌 변환과 축 변환은
 * 백엔드 책임이므로(REQ-302) 가시화도, 이 목 서버의 소비자도 변환 로직을 갖지 않는다.
 */

import { INTERVALS } from './config.ts';
import type { Hub } from './hub.ts';
import type { ActuatorState } from './protocol.ts';
import type { CommandEngine } from './commands.ts';

/**
 * 주기가 도중에 바뀔 수 있는 루프. setInterval 대신 재무장 setTimeout을 쓴다.
 *
 * **기동 즉시 1회 발행한다.** 첫 주기를 기다리면 평시 1분 센서는 서버가 뜬 뒤 1분 동안
 * 마지막 값 캐시가 비어 있고, 그 사이에 구독한 화면은 VZ-I-02의 즉시 스냅샷을 받지 못한다.
 * 실제 장치도 부팅하면 곧바로 자기 상태를 보고하므로 이쪽이 현실에도 맞다.
 */
type Loop = {
  stop(): void;
  /**
   * 주기가 바뀌었을 때 **이미 무장된 타이머를 다시 건다.**
   * 이게 없으면 평시 1분으로 무장된 센서가 이벤트 모드로 바뀌어도 다음 발행은
   * 여전히 1분 뒤라, 급변 대응 주기 상향(HW-S-03)이 이름만 남는다.
   */
  rearm(): void;
};

function looping(getDelayMs: () => number, fn: () => void): Loop {
  let timer: ReturnType<typeof setTimeout>;
  const arm = () => {
    timer = setTimeout(() => {
      fn();
      arm();
    }, getDelayMs());
  };
  fn();
  arm();
  return {
    stop: () => clearTimeout(timer),
    rearm: () => {
      clearTimeout(timer);
      arm();
    },
  };
}

function round(n: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

// ─────────────────────────────────────────────────────────────────────────────
// 로봇 (HW-R-02 · HW-R-03)
// ─────────────────────────────────────────────────────────────────────────────

export class RobotDevice {
  /** 임무 중이면 50ms, 대기면 5초. */
  mission: boolean;
  private battery: number;
  private phase = 0;
  private readonly hub: Hub;
  readonly id: string;

  constructor(
    hub: Hub,
    id: string,
    opts: { mission: boolean; battery: number; deviceStatus: 'ok' | 'fault' },
  ) {
    this.hub = hub;
    this.id = id;
    this.mission = opts.mission;
    this.battery = opts.battery;
    const rt = this.hub.runtime.get(id);
    if (rt) rt.deviceStatus = opts.deviceStatus;
    if (opts.deviceStatus === 'fault') {
      const r = this.hub.runtime.get(id);
      if (r) r.note = '구동부 응답 없음 — 기기 자기보고 fault';
    }
  }

  private telemetryDelay = (): number =>
    this.mission ? INTERVALS.ROBOT_MISSION_MS : INTERVALS.ROBOT_IDLE_MS;

  private emitTelemetry(): void {
    const rt = this.hub.runtime.get(this.id);
    const faulted = rt?.deviceStatus === 'fault';
    const moving = this.mission && !faulted;

    if (moving) {
      this.phase += 0.02;
      this.battery = Math.max(0, this.battery - 0.0006);
    }

    // 이미 전역 좌표로 변환된 값 (REQ-302 — 변환은 백엔드 책임).
    const payload = {
      position: {
        x: round(12 + 6 * Math.cos(this.phase), 3),
        y: 0,
        z: round(-4.5 + 6 * Math.sin(this.phase), 3),
        frame: 'site-global',
      },
      battery_pct: round(this.battery, 1),
      velocity: { linear_mps: moving ? round(0.9 + 0.1 * Math.sin(this.phase * 3), 2) : 0, angular_rps: moving ? 0.2 : 0 },
      is_moving: moving,
      mission: this.mission ? { id: 'msn-503-01', segment: 3, segment_total: 7 } : null,
    };

    this.hub.publish(this.id, 'telemetry', payload, {
      quality: faulted ? 'degraded' : 'good',
    });
  }

  /** 대기 중에만 1초 하트비트. 임무 중에는 50ms 상태 발행이 생존 신호를 겸한다. */
  private emitHeartbeat(): void {
    if (this.mission) return;
    this.hub.publish(this.id, 'heartbeat', { uptime_s: Math.round(process.uptime()), rssi_dbm: -58 });
  }

  start(): Loop[] {
    return [
      looping(this.telemetryDelay, () => this.emitTelemetry()),
      looping(() => INTERVALS.ROBOT_HEARTBEAT_IDLE_MS, () => this.emitHeartbeat()),
    ];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 센서 (HW-S-02 · HW-S-03 · HW-S-05)
// ─────────────────────────────────────────────────────────────────────────────

export class SensorDevice {
  private level: number;
  private flow: number;
  /** 이벤트 모드(1초 상향)가 끝나는 서버 시각. 평시에는 0. */
  private eventModeUntilMs = 0;
  /** 시나리오가 연결을 끊은 동안은 아무것도 발행하지 않는다. */
  silent = false;
  private readonly hub: Hub;
  readonly id: string;
  private loop: Loop | null = null;

  constructor(hub: Hub, id: string, opts: { level: number; flow: number }) {
    this.hub = hub;
    this.id = id;
    this.level = opts.level;
    this.flow = opts.flow;
    const rt = this.hub.runtime.get(id);
    if (rt) rt.deviceStatus = 'ok';
  }

  get eventMode(): boolean {
    return Date.now() < this.eventModeUntilMs;
  }

  private delay = (): number =>
    this.eventMode ? INTERVALS.SENSOR_EVENT_MS : INTERVALS.SENSOR_NORMAL_MS;

  private emit(): void {
    if (this.silent) return;
    if (this.eventMode) {
      this.level = round(this.level + (Math.random() - 0.35) * 0.05, 3);
      this.flow = round(Math.max(0, this.flow + (Math.random() - 0.4) * 0.1), 3);
    } else {
      this.level = round(this.level + (Math.random() - 0.5) * 0.01, 3);
      this.flow = round(Math.max(0, this.flow + (Math.random() - 0.5) * 0.02), 3);
    }
    this.publishNow();
  }

  private publishNow(): void {
    this.hub.publish(this.id, 'telemetry', {
      water_level: { value: this.level, unit: 'meter' },
      flow_velocity: { value: this.flow, unit: 'meter_per_second' },
      // 평시 1분 / 이벤트 1초 — 화면이 "왜 이 값이 자주 오는가"를 설명할 수 있어야 한다.
      report_mode: this.eventMode ? 'event' : 'normal',
      report_interval_ms: this.delay(),
    });
  }

  /**
   * 임계 초과·급변 — **주기를 기다리지 않고 즉시 발행**하고 이벤트 모드(1초)로 전환한다 (HW-S-02/03).
   * 평시 1분을 기다렸다면 골든타임 대응 화면이 성립하지 않는다.
   */
  surge(deltaM: number): void {
    this.level = round(this.level + deltaM, 3);
    this.flow = round(this.flow + deltaM * 0.8, 3);
    this.eventModeUntilMs = Date.now() + INTERVALS.SENSOR_EVENT_HOLD_MS;
    this.publishNow();
    // 평시 1분으로 무장된 타이머를 이벤트 주기(1초)로 다시 건다.
    this.loop?.rearm();
  }

  private emitHeartbeat(): void {
    if (this.silent) return;
    this.hub.publish(this.id, 'heartbeat', { uptime_s: Math.round(process.uptime()), rssi_dbm: -71 });
  }

  start(): Loop[] {
    this.loop = looping(this.delay, () => this.emit());
    return [this.loop, looping(() => INTERVALS.SENSOR_HEARTBEAT_MS, () => this.emitHeartbeat())];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 카메라 (HW-S-06) — 15fps 메타데이터만. 영상 스트림은 이번 범위 밖.
// ─────────────────────────────────────────────────────────────────────────────

export class CameraDevice {
  private frame = 0;
  silent = false;
  private readonly hub: Hub;
  readonly id: string;

  constructor(hub: Hub, id: string) {
    this.hub = hub;
    this.id = id;
    const rt = this.hub.runtime.get(id);
    if (rt) rt.deviceStatus = 'ok';
  }

  private emit(): void {
    if (this.silent) return;
    this.frame += 1;
    this.hub.publish(this.id, 'video_meta', {
      frame_seq: this.frame,
      fps: 15,
      resolution: { width: 1920, height: 1080 },
      // 프레임 참조 형식은 미확정(AI↔하드웨어 시트 공백)이므로 값만 흉내 낸다. 정합은 범위 밖.
      frame_ref: this.id + ':' + this.frame,
      encoding: 'h264',
    });
  }

  start(): Loop[] {
    return [looping(() => INTERVALS.CAMERA_META_MS, () => this.emit())];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 액추에이터 (HW-A-01 · HW-A-04) — 표준 3층과 별개인 도메인 어휘
// ─────────────────────────────────────────────────────────────────────────────

export class ActuatorDevice {
  private readonly hub: Hub;
  readonly id: string;
  private engine: CommandEngine | null = null;
  private loop: Loop | null = null;

  constructor(hub: Hub, id: string) {
    this.hub = hub;
    this.id = id;
    const rt = this.hub.runtime.get(id);
    if (rt) rt.deviceStatus = 'ok';
  }

  /**
   * 명령 수행은 CommandEngine이 소유한다. 장치는 **자기 상태를 보고할 뿐**이다.
   * 둘을 한 클래스에 두면 "장치 상태 100ms"와 "명령 진행 200ms"가 섞여
   * 어느 주기가 무엇을 위한 것인지 코드에서 읽히지 않는다.
   */
  attach(engine: CommandEngine): void {
    this.engine = engine;
  }

  private delay = (): number =>
    this.engine?.isBusy(this.id) ? INTERVALS.ACTUATOR_MOVING_MS : INTERVALS.ACTUATOR_IDLE_MS;

  private snapshot(): ActuatorState {
    const engine = this.engine;
    const lock = engine?.getLock(this.id) ?? null;
    const busy = engine?.isBusy(this.id) ?? false;

    // 잠긴 동안은 실제 상태를 확인할 수 없으므로 '확인 불가'다.
    // 도메인 어휘(대기·동작 중·완료·오류·확인 불가)는 표준 3층과 별개다.
    const phase: ActuatorState['phase'] = lock?.locked ? 'unverified' : busy ? 'moving' : 'idle';

    return {
      phase,
      progress_pct: null,
      position_pct: engine ? round(engine.getPositionPct(this.id), 1) : null,
      control_locked: lock?.locked ?? false,
      lock_reason: lock?.reason ?? null,
      command_id: null,
    };
  }

  /**
   * 대기 1초 <-> 동작 중 100ms 전환. 엔진이 명령 시작·종료 시점에 불러 준다.
   * 루프 콜백 안에서 rearm을 부르면 이미 재무장을 예약한 타이머와 겹쳐
   * 매 틱마다 타이머가 배로 늘어난다 — 그래서 밖에서 부른다.
   */
  rearm(): void {
    this.loop?.rearm();
  }

  start(): Loop[] {
    this.loop = looping(this.delay, () => this.hub.publish(this.id, 'actuator_state', this.snapshot()));
    return [this.loop];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 관측 지표 (HW-C-05) — 15초. **집약값**이므로 aggregation 표기가 붙는다.
// ─────────────────────────────────────────────────────────────────────────────

export class ObservabilityEmitter {
  private sent = 0;
  private failed = 0;
  private readonly hub: Hub;
  readonly id: string;

  constructor(hub: Hub, id: string) {
    this.hub = hub;
    this.id = id;
  }

  private emit(): void {
    const batchSent = 900 + Math.floor(Math.random() * 200);
    const batchFailed = Math.floor(Math.random() * 4);
    this.sent += batchSent;
    this.failed += batchFailed;

    this.hub.publish(
      this.id,
      'metrics',
      {
        cpu_pct: { value: round(18 + Math.random() * 22, 1), unit: 'percent' },
        publish_success: { value: batchSent, unit: 'count' },
        publish_failure: { value: batchFailed, unit: 'count' },
        publish_latency_ms: { value: round(8 + Math.random() * 14, 1), unit: 'millisecond' },
        totals: { sent: this.sent, failed: this.failed },
      },
      {
        /**
         * VZ-C-03 — 이 값은 15초 창에서 이미 집약된 값이다.
         * 표기가 없으면 화면이 이 값을 **또 평균 내는** 재집약 사고가 난다.
         */
        aggregation: { mode: 'aggregated', layer: 'edge', method: 'mean', window_ms: INTERVALS.OBSERVABILITY_MS },
      },
    );
  }

  start(): Loop[] {
    return [looping(() => INTERVALS.OBSERVABILITY_MS, () => this.emit())];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 함대 조립
// ─────────────────────────────────────────────────────────────────────────────

export type Fleet = {
  robots: Map<string, RobotDevice>;
  sensors: Map<string, SensorDevice>;
  cameras: Map<string, CameraDevice>;
  actuators: Map<string, ActuatorDevice>;
  stopAll(): void;
};

export function createFleet(hub: Hub): Fleet {
  const loops: Loop[] = [];

  const robots = new Map<string, RobotDevice>();
  const sensors = new Map<string, SensorDevice>();
  const cameras = new Map<string, CameraDevice>();
  const actuators = new Map<string, ActuatorDevice>();

  // robot-01 — 임무 수행 중(50ms). 렌더 병합을 실측하려면 이 대상이 계속 20Hz여야 한다.
  const r1 = new RobotDevice(hub, 'robot-01', { mission: true, battery: 82, deviceStatus: 'ok' });
  robots.set(r1.id, r1);

  // robot-02 — device_status = fault 로 시작. 연결은 살아 있으므로 availability는 online이다.
  const r2 = new RobotDevice(hub, 'robot-02', { mission: false, battery: 64, deviceStatus: 'fault' });
  robots.set(r2.id, r2);

  // robot-03 — 미배포. **아무것도 발행하지 않는다.** 화면은 레지스트리를 근거로만 그린다.
  const r3 = hub.runtime.get('robot-03');
  if (r3) {
    r3.deployment = 'not_deployed';
    r3.note = '배포되지 않아 값이 오지 않음 — 레지스트리 목록에만 존재';
  }

  const s1 = new SensorDevice(hub, 'sensor-01', { level: 1.42, flow: 0.31 });
  const s2 = new SensorDevice(hub, 'sensor-02', { level: 1.18, flow: 0.27 });
  sensors.set(s1.id, s1);
  sensors.set(s2.id, s2);

  // sensor-04 — 기동 시점부터 연결 두절(LWT 감지). 발행하지 않는다.
  const s4 = hub.runtime.get('sensor-04');
  if (s4) {
    s4.forcedOffline = true;
    s4.note = 'LWT로 연결 단절 감지';
  }

  const c2 = new CameraDevice(hub, 'camera-02');
  cameras.set(c2.id, c2);

  const a1 = new ActuatorDevice(hub, 'actuator-01');
  actuators.set(a1.id, a1);

  const obs = new ObservabilityEmitter(hub, 'edge-node-a');

  for (const d of [r1, r2, s1, s2, c2, a1, obs]) loops.push(...d.start());

  // 첫 상태 3층을 즉시 한 번 조합해 캐시에 넣는다 — 첫 구독자가 빈 화면을 보지 않도록.
  // 전이 판정과 사유 문구를 한 곳에서 만들기 위해 publishAllStates가 아니라 sweep으로 낸다.
  hub.sweepAvailability();

  return {
    robots,
    sensors,
    cameras,
    actuators,
    stopAll: () => loops.forEach((l) => l.stop()),
  };
}
