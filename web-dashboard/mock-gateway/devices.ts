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

import { INTERVALS, SCENARIO_TIMING } from './config.ts';
import type { Hub } from './hub.ts';
import type { ActuatorState } from './protocol.ts';

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
  private phase: ActuatorState['phase'] = 'idle';
  private positionPct = 0;
  private targetPct = 0;
  private progressPct: number | null = null;
  private commandId: string | null = null;
  private travelStartedMs = 0;
  private startPct = 0;
  private readonly hub: Hub;
  readonly id: string;
  private loop: Loop | null = null;

  constructor(hub: Hub, id: string) {
    this.hub = hub;
    this.id = id;
    const rt = this.hub.runtime.get(id);
    if (rt) rt.deviceStatus = 'ok';
  }

  private delay = (): number =>
    this.phase === 'moving' ? INTERVALS.ACTUATOR_MOVING_MS : INTERVALS.ACTUATOR_IDLE_MS;

  private snapshot(): ActuatorState {
    const rt = this.hub.runtime.get(this.id);
    const locked = rt?.forcedOffline === true;
    return {
      phase: locked ? 'unverified' : this.phase,
      progress_pct: this.phase === 'moving' ? this.progressPct : null,
      position_pct: round(this.positionPct, 1),
      // VZ-O-05 — 통신 두절 시 제어를 잠그고 사유를 함께 보여 준다.
      control_locked: locked,
      lock_reason: locked ? '통신 두절 — 실제 상태 재확인 전까지 잠금 유지' : null,
      command_id: this.commandId,
    };
  }

  private emit(): void {
    if (this.phase === 'moving') {
      const elapsed = Date.now() - this.travelStartedMs;
      const ratio = Math.min(1, elapsed / SCENARIO_TIMING.ACTUATOR_TRAVEL_MS);
      this.progressPct = round(ratio * 100, 1);
      this.positionPct = round(this.startPct + (this.targetPct - this.startPct) * ratio, 1);

      if (ratio >= 1) {
        this.phase = 'completed';
        this.progressPct = 100;
        this.positionPct = this.targetPct;
        this.loop?.rearm(); // 동작 중 100ms → 대기 1초
        this.hub.publish(this.id, 'actuator_state', this.snapshot());
        // REQ-903 — 확정 판정은 백엔드가 디바이스 ack를 command.result로 승격해 내려 준다.
        this.hub.publish(this.id, 'command_result', {
          command_id: this.commandId,
          status: 'completed',
          stage: 'physical_state_changed',
          detail: '개도율 ' + this.targetPct + '% 도달',
        });
        setTimeout(() => {
          if (this.phase === 'completed') {
            this.phase = 'idle';
            this.progressPct = null;
            this.hub.publish(this.id, 'actuator_state', this.snapshot());
          }
        }, 3000);
        return;
      }
    }
    this.hub.publish(this.id, 'actuator_state', this.snapshot());
  }

  /**
   * 명령 왕복. **목 서버 안에서만 왕복시킨다** — 실제 제어 명령 발행 경로는 만들지 않는다.
   * ACK → 동작 중(100ms 진행) → 완료 4단계를 REQ-903의 3상태 표시로 접어 내려 준다.
   */
  command(targetPct: number): string {
    const commandId = 'cmd-' + Date.now().toString(36);
    this.commandId = commandId;

    // REQ-909 — command_id(전 파트 단일 상관 키)와 expires_at(만료 후 실행 금지).
    const expiresAt = new Date(Date.now() + 30_000).toISOString();

    // 1단계 — 수신 확인(ACK).
    setTimeout(() => {
      this.hub.publish(this.id, 'command_result', {
        command_id: commandId,
        status: 'accepted',
        stage: 'ack',
        expires_at: expiresAt,
        detail: '수신 확인',
      });
    }, SCENARIO_TIMING.ACTUATOR_ACK_MS);

    // 2단계 — 수행 중. ACK와 **시간상 분리**한다. 같은 순간에 내면 마지막 값만 남는
    // 저장 방식에서는 ACK 단계가 화면에 한 번도 보이지 않는다.
    setTimeout(() => {
      this.startPct = this.positionPct;
      this.targetPct = targetPct;
      this.travelStartedMs = Date.now();
      this.progressPct = 0;
      this.phase = 'moving';
      this.loop?.rearm(); // 대기 1초 → 동작 중 100ms
      this.hub.publish(this.id, 'actuator_state', this.snapshot());
      this.hub.publish(this.id, 'command_result', {
        command_id: commandId,
        status: 'accepted',
        stage: 'executing',
        expires_at: expiresAt,
        detail: '수행 중',
      });
    }, SCENARIO_TIMING.ACTUATOR_ACK_MS + SCENARIO_TIMING.ACTUATOR_EXEC_GAP_MS);

    return commandId;
  }

  start(): Loop[] {
    this.loop = looping(this.delay, () => this.emit());
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
