/**
 * src/physical/fakeDevice.ts (261014 신설 — 연결 관리 「가짜 Go1 · 가짜 드론」)
 *
 * **실물 없이 하드웨어 카드 · 상세창을 보려고 만든 가짜 브로커.** 연결 관리의 물리 장비 칸에 `fake:go1` ·
 * `fake:drone` 을 넣으면 `PhysicalClient` 가 mqtt.js 대신 이것에 붙는다. 이것은 mqtt.js 클라이언트와 **같은 면**
 * (`on` · `subscribe` · `publish` · `end`)을 가진 흉내라, 그 뒤의 모든 것 — 장비 정체성 · 토픽 분기 · 카드 등록 ·
 * 명령 인코딩 · 응답 디코딩 — 은 실물과 **같은 코드**를 지난다. 가짜가 끼어드는 자리는 `PhysicalClient.connect` 한 줄뿐이다.
 *
 * ## 무엇을 흉내 내나
 *
 *   가짜 Go1 (`go1-fake`)   status · state(1 Hz) · heartbeat, Capability(ping · abort · teleop · move_forward · turn ·
 *                           move_relative). 이동 명령을 받으면 위치 · 기수가 실제로 바뀐다.
 *   가짜 드론 (`x500-fake`)  status · state · fcx(5 Hz), Capability(ping · rtk_test_start · rtk_test_stop ·
 *                           rtk_test_emergency). 비행 실행기(`261014_드론비행실행기_요청_VZ.md`)를 흉내 내
 *                           `test_sar_rtk.py` 와 같은 모양의 출력을 `flight_run` 으로 내고, 그동안 fcx 의 고도 · 위치 ·
 *                           모드가 실제로 이륙 → 왕복 → 착륙을 그린다. RTK 대기는 3초로 줄였다.
 *                           복합 이동 미션(261113 · `MISSION_SEQ_요청_VZ.md`)도 — `seq_mission_start` · `seq_mission_stop` 을
 *                           선언하고 `mission_seq.py` 와 같은 모양의 출력 · `[계획]` 을 `mission_run` 으로 낸다.
 *
 * ## 가짜임을 숨기지 않는다
 *
 * 상태 본문에 `simulated: true` 를 싣는다 — 카드에 「목」 배지가 뜬다(`HardwareLink`). 장비 id 도 실물과 겹치지 않는다.
 * 카메라 · 탐지 칸은 주소에 호스트가 없어(`fake:` 뒤에 `//` 가 없다) 비어 있다 — 깨진 영상을 띄우지 않는다.
 *
 * 출력 문구(`[연결]` · `[미션] 진행 #n` …)는 화면 글자가 아니라 **장비가 보내는 데이터**다 — 스크립트가 찍는 원문을
 * 흉내 낸다. 그래서 사전에 넣지 않는다(`verify:no-raw-korean` 의 예외 목록에 사유를 적었다).
 */

import { physical } from './protocol.js';
import type { MqttLike } from './PhysicalClient.ts';
import { bodyToNe, missionKey, previewOf, seqProblems, STEP_KINDS, stepClass, type SeqMission, type SeqStep } from './seqPlan.ts';

export const FAKE_PREFIX = 'fake:';
export const FAKE_GO1 = 'fake:go1';
export const FAKE_DRONE = 'fake:drone';

export function isFakeAddress(url: string): boolean {
  return url.trim().startsWith(FAKE_PREFIX);
}

const ZONE = 'zoneA';
type Kind = 'go1' | 'drone';
type Handler = (...args: never[]) => void;
type Params = Record<string, number>;

/** 주소 → 가짜 클라이언트. 모르는 이름이면 곧바로 `error` 를 낸다(연결 관리에 사유가 뜬다). */
export function fakeMqtt(url: string): MqttLike {
  const name = url.trim().slice(FAKE_PREFIX.length).toLowerCase();
  const kind: Kind | null = name === 'go1' || name === 'robot' ? 'go1' : name === 'drone' || name === 'x500' ? 'drone' : null;
  return new FakeBroker(kind, url);
}

// ── 바이트 ──────────────────────────────────────────────────────────────

function encode(body: Record<string, unknown>): Uint8Array {
  return physical.PhysicalCommandEnvelope.encode(physical.PhysicalCommandEnvelope.create(body)).finish();
}

const capabilityBytes = (deviceId: string, actions: readonly string[]) => encode({ capability: { deviceId, actions } });
const acceptBytes = (commandId: string) => encode({ acceptance: { commandId, accepted: true } });
const rejectBytes = (commandId: string, code: string, message: string) =>
  encode({ acceptance: { commandId, accepted: false, rejection: { code, message } } });
const statusBytes = (commandId: string, detail: string) => encode({ status: { commandId, state: 'EXECUTING', detail } });
const resultBytes = (commandId: string, result: Params, failed: string | null = null) => encode({
  result: {
    commandId,
    status: physical.TerminalStatus[failed === null ? 'SUCCEEDED' : 'ABORTED'],
    result,
    ...(failed === null ? {} : { failure: { code: 'ABORTED', message: failed } }),
  },
});

const json = (body: unknown) => new TextEncoder().encode(JSON.stringify(body));

// ── 가짜 브로커 ─────────────────────────────────────────────────────────

class FakeBroker implements MqttLike {
  private handlers = new Map<string, Set<Handler>>();
  private timers: ReturnType<typeof setInterval>[] = [];
  private closed = false;
  private device: FakeGo1 | FakeDrone | null = null;

  private readonly kind: Kind | null;
  private readonly url: string;

  constructor(kind: Kind | null, url: string) {
    this.kind = kind;
    this.url = url;
    setTimeout(() => {
      if (this.closed) return;
      if (this.kind === null) {
        this.emit('error', new Error(`unknown fake device "${this.url}" — use ${FAKE_GO1} or ${FAKE_DRONE}`));
        return;
      }
      this.emit('connect');
    }, 30);
  }

  on(event: string, handler: Handler): void {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
  }

  private emit(event: string, ...args: unknown[]): void {
    for (const handler of this.handlers.get(event) ?? []) (handler as (...a: unknown[]) => void)(...args);
  }

  /** 받는 쪽 → 화면. 토픽 필터를 따로 보지 않는다 — 가짜는 화면이 구독하는 것만 낸다. */
  deliver(topic: string, payload: Uint8Array): void {
    if (this.closed) return;
    this.emit('message', topic, payload);
  }

  every(ms: number, fn: () => void): void {
    this.timers.push(setInterval(() => { if (!this.closed) fn(); }, ms));
  }

  subscribe(topic: string, _opts: { qos: number }, done?: () => void): void {
    setTimeout(() => {
      if (this.closed) return;
      done?.();
      // 명령 응답 귀가 서면 장비가 깨어난다 — 실물도 그 뒤에 Capability 를 낸다.
      if (topic.startsWith('terminal/') && this.device === null && this.kind !== null) {
        this.device = this.kind === 'go1' ? new FakeGo1(this) : new FakeDrone(this);
      }
    }, 10);
  }

  publish(topic: string, payload: Uint8Array): void {
    if (this.closed || this.device === null || !topic.endsWith('/downlink')) return;
    let command;
    try {
      command = physical.PhysicalCommandEnvelope.decode(payload).command;
    } catch {
      return;
    }
    if (!command?.commandId || !command.action) return;
    const params: Params = {};
    for (const [key, value] of Object.entries(command.parameters ?? {})) if (typeof value === 'number') params[key] = value;
    const device = this.device;
    setTimeout(() => device.command(command.commandId as string, command.action as string, params), 40);
  }

  end(): void {
    if (this.closed) return;
    this.closed = true;
    for (const timer of this.timers) clearInterval(timer);
    this.device?.stop();
    this.emit('close');
  }
}

abstract class FakeDevice {
  abstract readonly id: string;
  abstract readonly type: string;
  abstract readonly deviceType: string;
  abstract readonly actions: readonly string[];
  protected readonly bornMs = Date.now();
  protected seq = 0;
  stopped = false;

  protected readonly broker: FakeBroker;

  constructor(broker: FakeBroker) {
    this.broker = broker;
  }

  protected start(): void {
    this.uplink(capabilityBytes(this.id, this.actions));
    this.publishStatus();
    this.publishState();
    this.broker.every(5000, () => { this.publishStatus(); this.publishJson('heartbeat', { ...this.head('heartbeat') }); });
    this.broker.every(1000, () => this.publishState());
  }

  stop(): void {
    this.stopped = true;
  }

  protected head(channel: string): Record<string, unknown> {
    this.seq += 1;
    return {
      schema_version: '2.0', source_id: this.id, node_id: 'fake', zone_id: ZONE,
      timestamp: new Date().toISOString(), sequence_id: this.seq, channel, simulated: true,
    };
  }

  protected publishJson(channel: string, body: unknown): void {
    this.broker.deliver(`${ZONE}/${this.type}/${this.id}/${channel}`, json(body));
  }

  protected uplink(bytes: Uint8Array): void {
    this.broker.deliver(`terminal/${this.id}/uplink`, bytes);
  }

  protected registration() {
    return {
      entity_id: this.id, node_id: 'fake', zone_id: ZONE, entity_type: this.type, device_type: this.deviceType,
      fw_version: 'fake-0.1', mac: '00:00:00:00:00:00', ip: '127.0.0.1',
    };
  }

  protected abstract publishStatus(): void;
  protected abstract publishState(): void;
  protected abstract handle(commandId: string, action: string, params: Params): void;

  command(commandId: string, action: string, params: Params): void {
    if (this.stopped) return;
    if (!this.actions.includes(action)) {
      this.uplink(rejectBytes(commandId, 'UNIMPLEMENTED', 'action not supported'));
      return;
    }
    if (action === 'ping') {
      this.uplink(acceptBytes(commandId));
      this.uplink(resultBytes(commandId, { uptime_s: (Date.now() - this.bornMs) / 1000, fc_link: 1, fc_link_age_s: 0.1 }));
      return;
    }
    this.handle(commandId, action, params);
  }
}

// ── 가짜 Go1 ────────────────────────────────────────────────────────────

type Move = { commandId: string; kind: 'line'; dx: number; dy: number; left: number; speed: number }
  | { commandId: string; kind: 'turn'; leftDeg: number; rate: number };

class FakeGo1 extends FakeDevice {
  readonly id = 'go1-fake';
  readonly type = 'robot';
  readonly deviceType = 'go1_robot';
  readonly actions = ['ping', 'abort', 'teleop', 'move_forward', 'turn', 'move_relative'] as const;
  private x = 0;
  private y = 0;
  /** 반시계 + (도). */
  private heading = 0;
  private battery = 95;
  private teleop = { vx: 0, vy: 0, vyaw: 0, untilMs: 0 };
  private move: Move | null = null;

  constructor(broker: FakeBroker) {
    super(broker);
    this.start();
    let last = Date.now();
    broker.every(100, () => {
      const now = Date.now();
      this.tick((now - last) / 1000, now);
      last = now;
    });
  }

  private moving(): boolean {
    return this.move !== null || Date.now() < this.teleop.untilMs;
  }

  private tick(dt: number, now: number): void {
    this.battery = Math.max(5, this.battery - dt * (this.moving() ? 0.02 : 0.003));
    const h = (this.heading * Math.PI) / 180;
    if (now < this.teleop.untilMs) {
      const { vx, vy, vyaw } = this.teleop;
      this.x += (vx * Math.cos(h) - vy * Math.sin(h)) * dt;
      this.y += (vx * Math.sin(h) + vy * Math.cos(h)) * dt;
      this.heading += (vyaw * 180 / Math.PI) * dt;
    }
    const move = this.move;
    if (move === null) return;
    if (move.kind === 'line') {
      const step = Math.min(move.left, move.speed * dt);
      const norm = Math.hypot(move.dx, move.dy) || 1;
      const fx = move.dx / norm;
      const fy = move.dy / norm;
      this.x += (fx * Math.cos(h) - fy * Math.sin(h)) * step;
      this.y += (fx * Math.sin(h) + fy * Math.cos(h)) * step;
      move.left -= step;
      if (move.left <= 1e-3) this.finish(move.commandId);
    } else {
      const step = Math.sign(move.leftDeg) * Math.min(Math.abs(move.leftDeg), move.rate * dt);
      this.heading += step;
      move.leftDeg -= step;
      if (Math.abs(move.leftDeg) <= 1e-3) this.finish(move.commandId);
    }
  }

  private finish(commandId: string): void {
    this.move = null;
    this.uplink(resultBytes(commandId, { x: this.x, y: this.y, heading_deg: this.heading }));
  }

  protected handle(commandId: string, action: string, params: Params): void {
    if (action === 'abort') {
      const was = this.move;
      this.move = null;
      this.teleop.untilMs = 0;
      this.uplink(acceptBytes(commandId));
      if (was !== null) this.uplink(resultBytes(was.commandId, {}, 'aborted'));
      this.uplink(resultBytes(commandId, {}));
      return;
    }
    if (action === 'teleop') {
      if (this.move !== null) { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'mission_in_progress')); return; }
      this.teleop = { vx: params.vx ?? 0, vy: params.vy ?? 0, vyaw: params.vyaw ?? 0, untilMs: Date.now() + (params.hold_ms ?? 500) };
      this.uplink(acceptBytes(commandId));
      this.uplink(resultBytes(commandId, {}));
      return;
    }
    if (this.move !== null) { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'mission_in_progress')); return; }
    this.uplink(acceptBytes(commandId));
    this.uplink(statusBytes(commandId, 'executing'));
    if (action === 'move_forward') {
      const d = params.distance_m ?? params.forward_distance_m ?? 0.5;
      this.move = { commandId, kind: 'line', dx: Math.sign(d) || 1, dy: 0, left: Math.abs(d), speed: Math.abs(params.vx ?? 0.3) || 0.3 };
    } else if (action === 'move_relative') {
      const dx = params.dx_m ?? 0;
      const dy = params.dy_m ?? 0;
      this.move = { commandId, kind: 'line', dx, dy, left: Math.hypot(dx, dy), speed: Math.abs(params.v_mps ?? 0.3) || 0.3 };
    } else {
      // turn: deg + 는 오른쪽(시계) — 수동 제어의 회전 키와 같은 뜻이다.
      this.move = { commandId, kind: 'turn', leftDeg: -(params.deg ?? params.angle_deg ?? 45), rate: 45 };
    }
    if (this.move.kind === 'line' && this.move.left <= 1e-3) this.finish(commandId);
  }

  protected publishStatus(): void {
    this.publishJson('status', {
      ...this.head('status'), event: 'summary', status: 'online', device_status: 'ok', link: 'ok',
      robot_mode: this.moving() ? 'walking' : 'idle', in_mission: this.move !== null, battery_pct: Math.round(this.battery),
      sdk: { ready: true, autostart: true }, registration: this.registration(),
    });
  }

  protected publishState(): void {
    const speed = this.move?.kind === 'line' ? this.move.speed : Date.now() < this.teleop.untilMs ? Math.hypot(this.teleop.vx, this.teleop.vy) : 0;
    this.publishJson('state', {
      ...this.head('state'), reason: 'periodic', battery_pct: Math.round(this.battery * 10) / 10,
      position: { x: round(this.x, 3), y: round(this.y, 3), heading_deg: round(((this.heading + 180) % 360 + 360) % 360 - 180, 1) },
      speed_mps: round(speed, 2), robot_mode: this.moving() ? 'walking' : 'idle', device_status: 'ok', link: 'ok',
      attitude: { roll_deg: 0, pitch_deg: -1 }, body_height_m: 0.29, sdk: { ready: true, autostart: true },
    });
  }
}

// ── 가짜 드론 ───────────────────────────────────────────────────────────

const EARTH_R = 6378137.0;
const HOME = { lat: 36.3504, lon: 127.2985 };

function offset(lat: number, lon: number, dist: number, bearingDeg: number): [number, number] {
  const b = (bearingDeg * Math.PI) / 180;
  const dlat = (dist * Math.cos(b)) / EARTH_R;
  const dlon = (dist * Math.sin(b)) / (EARTH_R * Math.cos((lat * Math.PI) / 180));
  return [lat + (dlat * 180) / Math.PI, lon + (dlon * 180) / Math.PI];
}

function ne(lat0: number, lon0: number, lat: number, lon: number): [number, number] {
  const n = (((lat - lat0) * Math.PI) / 180) * EARTH_R;
  const e = (((lon - lon0) * Math.PI) / 180) * EARTH_R * Math.cos((((lat0 + lat) / 2) * Math.PI) / 180);
  return [n, e];
}

const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;
const wrap = (deg: number) => ((deg % 360) + 360) % 360;
const yawDiff = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180);

class Cancelled extends Error {}

type Proc = {
  runId: string; commandId: string | null; state: 'running' | 'exited'; dryRun: boolean | null; argv: string[];
  startedAt: number; endedAt: number | null; exitCode: number | null; outPath: string; mode?: string;
  lines: { seq: number; text: string }[];
};

/** 드론이 하는 일 — 이동 목표를 받고 100 ms 마다 다가간다. 스크립트 흉내는 이 위에서 돈다. */
class FakeDrone extends FakeDevice {
  readonly id = 'x500-fake';
  readonly type = 'drone';
  readonly deviceType = 'x500_drone';
  readonly actions = ['ping', 'rtk_test_start', 'rtk_test_stop', 'rtk_test_emergency', 'seq_mission_start', 'seq_mission_stop'] as const;
  private lat = HOME.lat;
  private lon = HOME.lon;
  private alt = 0;
  private heading = 118;
  private armed = false;
  private mode = 'HOLD';
  private battery = 92;
  private vn = 0;
  private ve = 0;
  private climb = 0;
  private target: { lat: number; lon: number; alt: number; speed: number; yaw: number | null } | null = null;
  private yawRate = 30;
  private run: Proc | null = null;
  private emergency: Proc | null = null;
  /** 복합 미션 실행 (261113). 왕복 시험(`run`)과 서로 배제된다. */
  private seqRun: SeqProc | null = null;
  private cancel: { reason: 'stop' | 'mode'; mode?: string } | null = null;
  private capturing = false;
  private dirty = false;

  constructor(broker: FakeBroker) {
    super(broker);
    this.start();
    broker.every(200, () => this.publishFcx());
    let last = Date.now();
    broker.every(100, () => {
      const now = Date.now();
      this.tick((now - last) / 1000);
      last = now;
    });
    broker.every(500, () => { if (this.dirty) this.publishRun(); });
    broker.every(5000, () => this.publishRun());
    this.publishRun();
  }

  private inAir(): boolean {
    return this.alt > 0.05;
  }

  private tick(dt: number): void {
    this.battery = Math.max(5, this.battery - dt * (this.inAir() ? 0.08 : 0.002));
    const target = this.target;
    if (target === null) { this.vn = 0; this.ve = 0; this.climb = 0; return; }
    const [dn, de] = ne(this.lat, this.lon, target.lat, target.lon);
    const dist = Math.hypot(dn, de);
    const step = Math.min(dist, target.speed * dt);
    if (dist > 1e-3) {
      const [lat, lon] = offset(this.lat, this.lon, step, (Math.atan2(de, dn) * 180) / Math.PI);
      this.lat = lat;
      this.lon = lon;
      this.vn = (dn / dist) * (step / dt);
      this.ve = (de / dist) * (step / dt);
    } else { this.vn = 0; this.ve = 0; }
    const dz = target.alt - this.alt;
    const rate = dz > 0 ? 1.0 : 0.7;
    const zstep = Math.sign(dz) * Math.min(Math.abs(dz), rate * dt);
    this.alt = Math.max(0, this.alt + zstep);
    this.climb = zstep / dt;
    if (target.yaw !== null) {
      const diff = ((target.yaw - this.heading + 540) % 360) - 180;
      this.heading = wrap(this.heading + Math.sign(diff) * Math.min(Math.abs(diff), this.yawRate * dt));
    }
  }

  private arrived(): boolean {
    const target = this.target;
    if (target === null) return true;
    const [dn, de] = ne(this.lat, this.lon, target.lat, target.lon);
    return Math.hypot(dn, de) < 0.05 && Math.abs(target.alt - this.alt) < 0.05
      && (target.yaw === null || yawDiff(this.heading, target.yaw) < 0.5);
  }

  // ── 출력 ──

  private say(process: Proc, text: string, stamp = true): void {
    process.lines.push({ seq: (process.lines.at(-1)?.seq ?? 0) + 1, text: stamp ? `[${(Date.now() / 1000).toFixed(3)}] ${text}` : text });
    this.dirty = true;
  }

  private wire(process: Proc | null) {
    if (process === null) return null;
    return {
      run_id: process.runId, command_id: process.commandId, state: process.state, dry_run: process.dryRun, argv: process.argv,
      started_at: process.startedAt, ended_at: process.endedAt, exit_code: process.exitCode, out_path: process.outPath,
      // 비상 명령이 아니면 실물 실행기(261022)처럼 띄운 스크립트와 그때 본 보정 여부를 싣는다. 가짜는 늘 보정이 있다.
      ...(process.mode !== undefined ? { mode: process.mode } : { script: 'test_sar_rtk.py', rtk: true }),
      lines: process.lines.slice(-200),
    };
  }

  private publishRun(): void {
    this.dirty = false;
    this.publishJson('flight_run', { schema_version: '1', source_id: this.id, timestamp: new Date().toISOString(), simulated: true,
      run: this.wire(this.run), emergency: this.wire(this.emergency) });
    const seq = this.seqRun;
    this.publishJson('mission_run', { schema_version: '1', source_id: this.id, timestamp: new Date().toISOString(), simulated: true,
      runner: 'mission_seq',
      run: seq === null ? null : {
        ...this.wire(seq), script: 'mission_seq.py', rtk: true,
        steps: seq.steps, plan: seq.plan, mission_key: seq.plan?.key ?? null, mission_hash: seq.plan?.hash ?? null,
      } });
  }

  protected publishStatus(): void {
    this.publishJson('status', {
      ...this.head('status'), event: 'summary', status: 'online', device_status: 'ok', link: 'ok',
      uptime_s: (Date.now() - this.bornMs) / 1000, fc_link: true, fc_link_age_s: 0.1, router_mode: 'drone',
      registration: this.registration(),
    });
  }

  private landedState(): string {
    if (!this.inAir()) return 'ON_GROUND';
    if (this.target !== null && this.target.alt === 0) return 'LANDING';
    if (this.climb > 0.2) return 'TAKEOFF';
    return 'IN_AIR';
  }

  protected publishState(): void {
    this.publishJson('state', {
      ...this.head('state'), reason: 'periodic', device_status: 'ok', link: 'ok', fc_link: true, fc_link_age_s: 0.1,
      router_mode: 'drone',
      battery: { voltage_v: round(14.8 + this.battery * 0.017, 2), current_a: this.inAir() ? 14.5 : 0.8, remaining_pct: Math.round(this.battery), consumed_mah: Math.round((92 - this.battery) * 50), source: 'SYS_STATUS', age_s: 0.2 },
      flight: { armed: this.armed, mode: this.mode, landed_state: this.landedState(), age_s: 0.1 },
      gps: { fix_type: 6, fix: 'RTK_FIXED', satellites: 22, lat: round(this.lat, 7), lon: round(this.lon, 7), eph_m: 0.02, age_s: 0.1 },
      rtk: { corrections: true, rtcm_age_s: 0.4, rtcm_msgs_per_s: 3, rtcm_bytes_per_s: 1100, rtcm_source: 'fake', fix: 'RTK_FIXED' },
      attitude: { roll_deg: 0.3, pitch_deg: Math.hypot(this.vn, this.ve) > 0.1 ? -3 : 0.8, yaw_deg: round(this.heading, 1), age_s: 0.01 },
      altitude: { relative_m: round(this.alt, 2) }, warnings: [],
    });
  }

  private publishFcx(): void {
    const gs = Math.hypot(this.vn, this.ve);
    this.publishJson('fcx', {
      source_id: this.id, simulated: true, time: Date.now() / 1000,
      link: { heartbeat_age_s: 0.1, msgs_per_s: 180, fc_sysid: 1 },
      armed: this.armed, mode: this.mode, landed_state: this.landedState(),
      attitude: { roll_deg: 0.3, pitch_deg: gs > 0.1 ? -3 : 0.8, yaw_deg: round(this.heading, 1) },
      hud: { groundspeed: round(gs, 2), airspeed: round(gs, 2), climb: round(this.climb, 2), heading: Math.round(this.heading), throttle: this.inAir() ? 48 : 0 },
      position: { lat: round(this.lat, 7), lon: round(this.lon, 7), alt_rel_m: round(this.alt, 2), alt_msl_m: round(62 + this.alt, 2),
        vn: round(this.vn, 2), ve: round(this.ve, 2), vd: round(-this.climb, 2) },
      home: { lat: HOME.lat, lon: HOME.lon, alt_msl_m: 62 },
      gps: { fix_type: 6, fix: 'RTK_FIXED', satellites: 22, hdop: 0.6, vdop: 0.9, h_acc_m: 0.02, v_acc_m: 0.03 },
      rtk: { baseline_m: 41.2, accuracy_mm: 14, iar_hypotheses: 1, rtk_rate: 1, nsats: 18 },
      battery: { voltage_v: round(14.8 + this.battery * 0.017, 2), current_a: this.inAir() ? 14.5 : 0.8, remaining_pct: Math.round(this.battery),
        cells_v: [4.05, 4.05, 4.04, 4.05].map((v) => round(v - (92 - this.battery) * 0.004, 2)), temperature_c: 31, consumed_mah: Math.round((92 - this.battery) * 50) },
      sensors: [{ name: 'gyro', enabled: true, healthy: true }, { name: 'accel', enabled: true, healthy: true }, { name: 'mag', enabled: true, healthy: true }, { name: 'gps', enabled: true, healthy: true }],
      load_pct: 41, drop_rate_pct: 0,
      ekf: { vel: 0.05, pos: 0.04, ver: 0.03, mag: 0.02, ter: 0, gps_glitch: false, accel_error: false },
      vibration: { x: 6.1, y: 5.8, z: 9.4, clipping: [0, 0, 0] },
      rc: { rssi: 96, channels: 16 },
      wind: { speed_mps: 1.4, from_deg: 250, var_h: 0.1 },
      clock_offset_s: 0.002,
      console: [],
    });
  }

  // ── 명령 ──

  protected handle(commandId: string, action: string, params: Params): void {
    if (action === 'seq_mission_start' || action === 'seq_mission_stop') { this.handleSeq(commandId, action, params); return; }
    if (action === 'rtk_test_start') {
      if (this.run?.state === 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'already_running')); return; }
      if (this.seqRun?.state === 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'other_flight_running')); return; }
      const dryRun = params.dry_run === 1;
      if (!dryRun && params.confirmed !== 1) { this.uplink(rejectBytes(commandId, 'INVALID_ARGUMENT', 'not_confirmed')); return; }
      this.uplink(acceptBytes(commandId));
      this.uplink(resultBytes(commandId, { launched: 1 }));
      void this.script(commandId, params, dryRun);
      return;
    }
    if (action === 'rtk_test_stop') {
      if (this.run?.state !== 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'not_running')); return; }
      this.uplink(acceptBytes(commandId));
      this.uplink(resultBytes(commandId, {}));
      this.cancel = { reason: 'stop' };
      return;
    }
    // rtk_test_emergency
    if (this.emergency?.state === 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'already_running')); return; }
    this.uplink(acceptBytes(commandId));
    this.uplink(resultBytes(commandId, { launched: 1 }));
    const mode = params.mode === 1 ? 'rtl' : params.mode === 2 ? 'hold' : 'land';
    void this.emergencyRun(commandId, mode);
  }

  private newProc(commandId: string | null, dryRun: boolean | null, argv: string[], mode?: string): Proc {
    const runId = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    return { runId, commandId, state: 'running', dryRun, argv, startedAt: Date.now() / 1000, endedAt: null, exitCode: null,
      outPath: `/home/physical/cansar_logs/runner/${runId}.out`, mode, lines: [] };
  }

  private exit(process: Proc, code: number): void {
    process.state = 'exited';
    process.exitCode = code;
    process.endedAt = Date.now() / 1000;
    this.dirty = true;
  }

  /** 함수로 읽는다 — 기다리는 사이에 바뀌는 값이라 타입 좁히기가 옛 값을 믿게 두면 안 된다. */
  private cancelReason(): 'stop' | 'mode' | null {
    return this.cancel?.reason ?? null;
  }

  private cancelMode(): string {
    return this.cancel?.mode ?? '?';
  }

  /** 기다리기 — 그동안 중단 · 모드 이탈이 오면 던진다. */
  private async wait(ms: number, check = true): Promise<void> {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (this.stopped) throw new Cancelled();
      if (check && this.cancel !== null) throw new Cancelled();
      await new Promise((resolve) => setTimeout(resolve, Math.min(100, end - Date.now())));
    }
  }

  private async goTo(lat: number, lon: number, alt: number, speed: number, yaw: number | null, onTick?: () => void): Promise<void> {
    this.target = { lat, lon, alt, speed, yaw };
    while (!this.arrived()) {
      onTick?.();
      await this.wait(100);
    }
  }

  private async script(commandId: string, p: Params, dryRun: boolean): Promise<void> {
    const pattern = p.pattern === 1 ? 'lr' : p.pattern === 2 ? 'rotate' : 'fb';
    const side = (['forward', 'back', 'right', 'left'] as const)[p.side ?? (pattern === 'lr' ? 2 : 0)] ?? 'forward';
    const sideDeg = { forward: 0, back: 180, right: 90, left: 270 }[side];
    const alt = p.altitude_m ?? 5;
    const length = p.length_m ?? 5;
    const speed = p.speed_mps ?? 1;
    const passes = p.passes ?? 2;
    const gap = p.gap_s ?? 10;
    const settle = p.settle_s ?? 2;
    const alignHold = p.align_hold_s ?? 3;
    const acc = p.accept_radius_m ?? 0.5;
    const rtkMin = p.rtk_min_s ?? 30;
    const abort = p.abort === 1 ? 'hold' : p.abort === 2 ? 'land' : 'rtl';
    const argv = ['--yes', '--pattern', pattern, ...(pattern === 'rotate' ? [] : ['--side', side]), '--altitude', String(alt),
      ...(pattern === 'rotate' ? [] : ['--length', String(length), '--speed', String(speed)]), '--passes', String(passes),
      ...(dryRun ? ['--dry-run'] : [])];
    const run = this.newProc(commandId, dryRun, argv);
    this.run = run;
    this.cancel = null;
    const say = (text: string) => this.say(run, text);
    let phase: 'pre' | 'air' = 'pre';
    try {
      say(`[로그] /home/physical/cansar_logs/test_sar_rtk_${run.runId}.log`);
      say(`[설정] {'pattern': '${pattern}', 'side': '${side}', 'altitude': ${alt}, 'length': ${length}, 'speed': ${speed}, 'passes': ${passes}, 'dry_run': ${dryRun ? 'True' : 'False'}, 'fake': True}`);
      say('[연결] udpin://0.0.0.0:14540 ...');
      await this.wait(700);
      say('[연결] 완료');
      if (this.armed) { say('[중단] 이미 ARM 상태다. 사람이 먼저 안전을 확인할 것.'); throw new Exit(1); }
      say('[확인] 위치 추정 대기 (최대 60.0초)...');
      await this.wait(400);
      say('[확인] 위치 추정 정상 ✔');
      if (!dryRun && rtkMin > 0) {
        say(`[RTK] 이륙 전: Fixed ${rtkMin}초 연속 유지 대기 (최대 ${p.rtk_timeout_s ?? 120}초) — 현재 fix RTK_FIXED 위성 22, Fixed 0초 (가짜: 3초로 줄임)`);
        await this.wait(3000);
        say(`[RTK] 이륙 전: Fixed ${rtkMin}초 유지 ✔`);
      }
      const yaw = p.heading_deg ?? this.heading;
      const bearing = wrap(yaw + (pattern === 'rotate' ? 0 : sideDeg));
      const L: [number, number] = [this.lat, this.lon];
      const X = offset(L[0], L[1], length, bearing);
      const sideName = { forward: '앞', back: '뒤', right: '오른쪽', left: '왼쪽' }[side];
      const patternName = { fb: '전후', lr: '좌우', rotate: '회전' }[pattern];
      say(`[경로] 이동 방향 ${patternName}, 헤딩(고정) ${yaw.toFixed(1)}°${pattern === 'rotate' ? '' : `, ${sideName} 먼저, 이동선 ${bearing.toFixed(1)}°`}, ${passes}회`);
      say(`[경로] L  ${L[0].toFixed(7)}, ${L[1].toFixed(7)}  (0m)`);
      if (pattern !== 'rotate') say(`[경로] X  ${X[0].toFixed(7)}, ${X[1].toFixed(7)}  (${length.toFixed(0)}m)`);
      say(`[경로] 고도 ${alt}m (home 기준 — PX4 가 arm 할 때 home 을 이 자리로 다시 잡는다), 지면 AMSL 62.0m`);
      // 미션 항목 — build_plan 과 같은 순서
      type Item = { kind: string; n: number; text: string };
      const items: Item[] = [];
      const pos = (lat: number, lon: number, z: number, y: number) => `${lat.toFixed(7)}, ${lon.toFixed(7)}  고도 ${z}m  헤딩 ${y.toFixed(1)}°`;
      const add = (kind: string, n: number, name: string, tag: string, rest: string) =>
        items.push({ kind, n, text: `#${String(items.length).padEnd(2)} ${name.padEnd(8)} ${tag.padEnd(14)} ${rest}` });
      add('takeoff', 0, 'TAKEOFF', '이륙', pos(L[0], L[1], alt, yaw));
      add('align', 0, 'WAYPOINT', 'yaw 정렬', `${pos(L[0], L[1], alt, yaw)}  대기 ${alignHold}s  반경 ${acc}m`);
      add('speed', 0, 'SPEED', '속도', `${speed}m/s`);
      add('hold', 0, 'WAYPOINT', 'L 대기', `${pos(L[0], L[1], alt, yaw)}  대기 ${settle}s  반경 ${acc}m`);
      for (let n = 1; n <= passes; n += 1) {
        const rest = n === passes ? settle : Math.max(settle, gap);
        if (pattern === 'rotate') {
          for (let k = 1; k <= 4; k += 1) add('rot', n, 'WAYPOINT', `패스 ${n} 회전`, `${pos(L[0], L[1], alt, wrap(yaw + 90 * k))}  대기 0s  반경 ${acc}m`);
        } else {
          add('speed', 0, 'SPEED', '속도', `${speed}m/s`);
          add('pass', n, 'WAYPOINT', `패스 ${n} L→X`, `${pos(X[0], X[1], alt, yaw)}  대기 ${settle}s  반경 ${acc}m`);
          add('speed', 0, 'SPEED', '속도', `${speed}m/s`);
        }
        add('hold', n, 'WAYPOINT', `L 대기(패스 ${n} 뒤)`, `${pos(L[0], L[1], alt, yaw)}  대기 ${rest}s  반경 ${acc}m`);
      }
      add('land', 0, 'LAND', '착륙', pos(L[0], L[1], 0, yaw));
      for (const item of items) say(`[미션] ${item.text}`);
      say('[미션] 업로드 (' + items.length + '개 항목)...');
      await this.wait(800);
      say('[미션] FC 수락 ✔ — 내려받아 대조...');
      await this.wait(500);
      say(`[미션] 대조 일치 ✔ (${items.length}개 항목 모두 같다)`);
      if (dryRun) {
        say('[미션] FC 의 미션을 지웠다');
        say('[dry-run] 여기서 끝낸다. arm 하지 않았다.');
        throw new Exit(0);
      }
      say(`[정렬] 이륙 직전 yaw ${this.heading.toFixed(1)}° 기억 (미션 헤딩 ${yaw.toFixed(1)}°, 차이 ${yawDiff(this.heading, yaw).toFixed(1)}°, L 에서 0.00m)`);
      say('[명령] arm');
      this.armed = true;
      await this.wait(500);
      say('[명령] 미션 시작 — 이제부터 FC 가 이륙·왕복·착륙을 스스로 진행한다');
      this.mode = 'MISSION';
      phase = 'air';
      let lastLive = 0;
      const live = (i: number) => {
        if (Date.now() - lastLive < 2000) return;
        lastLive = Date.now();
        const [dn, de] = ne(L[0], L[1], this.lat, this.lon);
        const h = (bearing * Math.PI) / 180;
        const along = dn * Math.cos(h) + de * Math.sin(h);
        say(`       #${i} 진행 ${along.toFixed(1).padStart(5)}m  속도 ${Math.hypot(this.vn, this.ve).toFixed(1).padStart(4)}m/s  고도 ${this.alt.toFixed(1).padStart(5)}m  헤딩 ${this.heading.toFixed(1).padStart(5)}°  ${this.capturing ? 'CAP' : ''}`);
      };
      for (let i = 0; i < items.length; i += 1) {
        const item = items[i];
        say(`[미션] 진행 ${item.text}`);
        const tick = () => live(i);
        if (item.kind === 'takeoff') await this.goTo(L[0], L[1], alt, 0, null, tick);
        else if (item.kind === 'align') {
          await this.goTo(L[0], L[1], alt, speed, yaw, tick);
          say(`[정렬] 이륙 yaw ${yaw.toFixed(1)}° 로 정렬 ✔ (현재 ${this.heading.toFixed(1)}°, 오차 ${yawDiff(this.heading, yaw).toFixed(1)}°)`);
          await this.wait(alignHold * 1000);
        } else if (item.kind === 'hold') {
          await this.goTo(L[0], L[1], alt, speed, yaw, tick);
          if (item.n > 0 && this.capturing) { this.capturing = false; say(`PASS ${item.n} END   t=${(Date.now() / 1000).toFixed(3)} 헤딩 ${this.heading.toFixed(1)}°`); say(`PASS ${item.n} SUMMARY (360° 회전) rtk=OK`); }
          if (item.n < passes && rtkMin > 0) say(`[RTK] 패스 ${item.n + 1} 전: Fixed ${rtkMin}초 유지 ✔`);
          const rest = item.n === 0 || item.n === passes ? settle : Math.max(settle, gap);
          await this.wait(rest * 1000);
        } else if (item.kind === 'pass') {
          this.capturing = true;
          const t0 = Date.now() / 1000;
          say(`PASS ${item.n} START t=${t0.toFixed(3)} 속도 ${Math.hypot(this.vn, this.ve).toFixed(2)}m/s 고도 ${this.alt.toFixed(1)}m`);
          await this.goTo(X[0], X[1], alt, speed, yaw, tick);
          this.capturing = false;
          const t1 = Date.now() / 1000;
          say(`PASS ${item.n} END   t=${t1.toFixed(3)} 속도 ${Math.hypot(this.vn, this.ve).toFixed(2)}m/s 고도 ${this.alt.toFixed(1)}m`);
          say(`PASS ${item.n} SUMMARY start=${t0.toFixed(3)} end=${t1.toFixed(3)} dur=${(t1 - t0).toFixed(2)}s alt min/max=${alt.toFixed(1)}/${alt.toFixed(1)}m speed min/mean/max=0.10/${(speed * 0.85).toFixed(2)}/${speed.toFixed(2)}m/s cross-track max=0.1m yaw-err max=0.8° rtk=OK`);
          await this.wait(settle * 1000);
        } else if (item.kind === 'rot') {
          if (!this.capturing) { this.capturing = true; say(`PASS ${item.n} START t=${(Date.now() / 1000).toFixed(3)} 헤딩 ${this.heading.toFixed(1)}°`); }
          await this.goTo(L[0], L[1], alt, speed, wrap(yaw + 90 * ((i - items.findIndex((x) => x.kind === 'rot' && x.n === item.n)) + 1)), tick);
        } else if (item.kind === 'land') {
          this.mode = 'LAND';
          await this.goTo(L[0], L[1], 0, speed, null, tick);
          this.armed = false;
          this.mode = 'HOLD';
          this.target = null;
          say('[확인] 착륙 완료 ✔');
        }
      }
      this.target = null;
      say('[미션] FC 의 미션을 지웠다');
      say('[비행 후] QGC 에서 .ulg 로그를 받을 것 (Analyze Tools → Log Download)');
      throw new Exit(0);
    } catch (error) {
      this.capturing = false;
      let code = 1;
      if (error instanceof Exit) code = error.code;
      else if (error instanceof Cancelled && this.cancelReason() === 'mode') {
        say(`[중단] 비행 모드가 ${this.cancelMode()} 로 바뀌었다 — 캡처 OFF. 조종기/FC 가 제어 중이므로 더 명령하지 않는다.`);
      } else if (error instanceof Cancelled && !this.stopped) {
        say('[중단] 사용자 중단 (Ctrl+C/SIGTERM) — 캡처 OFF');
        if (phase === 'air') {
          say(`[중단] ${abort} 명령을 보낸다 — ★ 필요하면 즉시 조종기로 개입할 것 ★`);
          void this.abortTo(abort, run.runId);
        }
      }
      for (let n = 1; n <= passes && phase === 'air'; n += 1) if (code !== 0) say(`PASS ${n} start=None end=None`);
      say('[종료]');
      if (code !== 0 && error instanceof Cancelled && this.cancelReason() === 'stop') this.say(run, '중단됨 — ★ 기체가 공중에 있다면 즉시 조종기로 개입할 것 ★', false);
      this.exit(run, code);
      this.cancel = null;
    }
  }

  // ── 복합 이동 미션 (261113) ──

  private handleSeq(commandId: string, action: string, params: Params): void {
    if (action === 'seq_mission_stop') {
      if (this.seqRun?.state !== 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'not_running')); return; }
      this.uplink(acceptBytes(commandId));
      this.uplink(resultBytes(commandId, {}));
      this.cancel = { reason: 'stop' };
      return;
    }
    if (this.seqRun?.state === 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'already_running')); return; }
    if (this.run?.state === 'running') { this.uplink(rejectBytes(commandId, 'FAILED_PRECONDITION', 'other_flight_running')); return; }
    const shape = seqShapeError(params);
    if (shape !== null) { this.uplink(rejectBytes(commandId, 'INVALID_ARGUMENT', shape)); return; }
    const dryRun = params.dry_run === 1;
    if (!dryRun && params.confirmed !== 1) { this.uplink(rejectBytes(commandId, 'INVALID_ARGUMENT', 'not_confirmed')); return; }
    this.uplink(acceptBytes(commandId));
    this.uplink(resultBytes(commandId, { launched: 1 }));
    void this.seqScript(commandId, params, dryRun);
  }

  /** `mission_seq.py` 흉내. 출력 문구는 요청 문서 §5 의 예를 따른다. */
  private async seqScript(commandId: string, p: Params, dryRun: boolean): Promise<void> {
    const mission = seqFromParams(p);
    const steps = mission.steps;
    const stepTexts = steps.map((step) => stepWire(step));
    const argv = ['--yes', '--altitude', String(mission.altitudeM), ...stepTexts.flatMap((text) => ['--step', text]),
      '--land', mission.land, ...(dryRun ? ['--dry-run'] : [])];
    const run: SeqProc = { ...this.newProc(commandId, dryRun, argv), steps: stepTexts, plan: null };
    this.seqRun = run;
    this.cancel = null;
    const say = (text: string) => this.say(run, text);
    let phase: 'pre' | 'air' = 'pre';
    const n = steps.length;
    try {
      say(`[로그] /home/physical/cansar_logs/mission_seq_${run.runId}.log`);
      const problem = seqProblems(mission)[0];
      if (problem !== undefined) {
        this.say(run, `mission_seq.py: error: ${JSON.stringify(problem)}`, false);
        throw new Exit(2);
      }
      say('[연결] udpin://0.0.0.0:14540 ...');
      await this.wait(600);
      say('[연결] 완료');
      if (this.armed) { say('[중단] 이미 ARM 상태다. 사람이 먼저 안전을 확인할 것.'); throw new Exit(1); }
      say('[확인] 위치 추정 대기 (최대 60.0초)...');
      await this.wait(300);
      say('[확인] 위치 추정 정상 ✔');
      const h0 = round(this.heading, 1);
      const L: [number, number] = [round(this.lat, 7), round(this.lon, 7)];
      const preview = previewOf(mission);
      const at = (point: { fwd: number; right: number }) => {
        const { n: dn, e: de } = bodyToNe(h0, point);
        const [lat, lon] = offset(L[0], L[1], Math.hypot(dn, de), (Math.atan2(de, dn) * 180) / Math.PI);
        return { n: round(dn, 3), e: round(de, 3), fwd: round(point.fwd, 3), right: round(point.right, 3), lat: round(lat, 7), lon: round(lon, 7) };
      };
      // 미션 항목 — 역할(seq 별)
      // 미션 항목 역할 — 드론 `seq_plan.build` 와 같은 구성(회전 ≤90° 조각 · 캡처 사이 rest · home 복귀 앞 speed).
      const roles: [string, number][] = [['takeoff', 0], ['align', 0]];
      const capKs = steps.flatMap((step, index) => (step.capture ? [index + 1] : []));
      const planSteps = steps.map((step, index) => {
        const k = index + 1;
        const first = roles.length;
        const cls = stepClass(step.kind);
        if (cls === 'move') roles.push(['speed', k], ['move', k]);
        else if (cls === 'rot') for (let piece = 0; piece < Math.max(1, Math.ceil(step.value / 90 - 1e-9)); piece += 1) roles.push(['rot', k]);
        else roles.push(['hover', k]);
        const last = roles.length - 1;
        if (step.capture && capKs.some((c) => c > k)) roles.push(['rest', k]);
        const prev = index === 0 ? { fwd: 0, right: 0, yaw: 0 } : preview.ends[index - 1]!;
        const end = preview.ends[index]!;
        return {
          k, kind: step.kind, value: step.value, speed: step.speedMps, cap: step.capture, label: fakeLabel(step), text: stepWire(step),
          seq: [first, last], yaw: round(wrap(h0 + end.yaw), 2), from: at(prev), to: at(end),
        };
      });
      if (mission.land === 'home') roles.push(['speed', 0], ['return', 0]);
      roles.push(['land', 0]);
      const key = missionKey(mission);
      const estS = Math.round(mission.altitudeM + 6 + 3 + preview.pathM / mission.speedMps
        + steps.reduce((sum, step) => sum + (stepClass(step.kind) === 'rot' ? step.value / 30 : stepClass(step.kind) === 'hover' ? step.value : 4), 0)
        + mission.altitudeM / 0.7 + 10);
      const plan = {
        v: 1, key, hash: await sha16(key), L, h0, alt: mission.altitudeM, speed: mission.speedMps, land: mission.land,
        est_s: estS, timeout_s: estS * 2 + 60, max_r: round(preview.maxR, 2), path_m: round(preview.pathM, 2), n_items: roles.length,
        roles, steps: planSteps, land_pt: at(preview.land),
      };
      run.plan = plan;
      say(`[계획] ${JSON.stringify(plan)}`);
      const items = roles.map(([role, k], i) => {
        const step = k >= 1 ? planSteps[k - 1]! : null;
        const name = role === 'takeoff' ? 'TAKEOFF' : role === 'land' ? 'LAND' : role === 'speed' ? 'SPEED' : 'WAYPOINT';
        const tag = role === 'rest' ? `캡처 간격(단계 ${k} 뒤)` : role === 'speed' ? (k ? `속도(단계 ${k})` : '속도(복귀)')
          : step !== null ? `단계 ${k} ${step.label}` : { takeoff: '이륙', align: 'yaw 정렬', return: 'L 복귀', land: '착륙' }[role] ?? role;
        return `#${String(i).padEnd(2)} ${name.padEnd(8)} ${tag}`;
      });
      for (const item of items) say(`[미션] ${item}`);
      say(`[미션] 업로드 (${items.length}개 항목)...`);
      await this.wait(600);
      say('[미션] FC 수락 ✔ — 내려받아 대조...');
      await this.wait(400);
      say(`[미션] 대조 일치 ✔ (${items.length}개 항목 모두 같다)`);
      if (dryRun) {
        say('[미션] FC 의 미션을 지웠다');
        say('[dry-run] 여기서 끝낸다. arm 하지 않았다.');
        throw new Exit(0);
      }
      say('[명령] arm');
      this.armed = true;
      await this.wait(400);
      say('[명령] 미션 시작 — 이제부터 FC 가 이륙·단계·착륙을 스스로 진행한다');
      this.mode = 'MISSION';
      phase = 'air';
      const alt = mission.altitudeM;
      const results: string[] = [];
      for (let i = 0; i < roles.length; i += 1) {
        const [role, k] = roles[i]!;
        say(`[미션] 진행 ${items[i]}`);
        let lastRole = 0;
        const roleLive = () => {
          if (Date.now() - lastRole < 2000) return;
          lastRole = Date.now();
          say(`       #${i} ${role}  속도 ${Math.hypot(this.vn, this.ve).toFixed(1).padStart(4)}m/s  고도 ${this.alt.toFixed(1).padStart(5)}m  헤딩 ${this.heading.toFixed(1).padStart(5)}°  `);
        };
        if (role === 'takeoff') { await this.goTo(L[0], L[1], alt, 0, null, roleLive); continue; }
        if (role === 'align') { await this.goTo(L[0], L[1], alt, mission.speedMps, h0, roleLive); continue; }
        if (role === 'speed') continue;
        if (role === 'rest') { await this.wait(1000); continue; }              // 실물은 max(settle, gap) — 가짜는 1초로 줄임
        if (role === 'rot' && planSteps[k - 1]!.seq[0] !== i) continue;     // 회전은 첫 조각에서 끝까지 돈다
        if (role === 'return') { await this.goTo(L[0], L[1], alt, mission.speedMps, null, roleLive); continue; }
        if (role === 'land') {
          this.mode = 'LAND';
          const land = planSteps.at(-1) !== undefined && mission.land === 'here' ? planSteps.at(-1)!.to : at({ fwd: 0, right: 0 });
          await this.goTo(land.lat, land.lon, 0, mission.speedMps, null, roleLive);
          this.armed = false;
          this.mode = 'HOLD';
          this.target = null;
          say('[확인] 착륙 완료 ✔');
          continue;
        }
        const step = planSteps[k - 1]!;
        const source = steps[k - 1]!;
        const t0 = Date.now() / 1000;
        say(`STEP ${k}/${n} START t=${t0.toFixed(3)} ${step.label} 고도 ${this.alt.toFixed(1)}m 헤딩 ${this.heading.toFixed(1)}°`);
        if (source.capture) { this.capturing = true; say(`CAP ${k} START t=${t0.toFixed(3)}`); }
        let last = 0;
        const total = role === 'move' ? source.value : role === 'rot' ? source.value : source.value;
        const live = () => {
          if (Date.now() - last < 2000) return;
          last = Date.now();
          const [dn, de] = ne(step.from!.lat, step.from!.lon, this.lat, this.lon);
          const doneNow = role === 'move' ? Math.hypot(dn, de) : role === 'rot' ? yawDiff(this.heading, wrap(h0 + (preview.ends[k - 2]?.yaw ?? 0))) : (Date.now() / 1000 - t0);
          const unit = role === 'move' ? 'm' : role === 'rot' ? '°' : 's';
          say(`       #${i} 단계 ${k}/${n} ${step.label} 진행 ${doneNow.toFixed(1).padStart(4)}/${total.toFixed(1)}${unit}  속도 ${Math.hypot(this.vn, this.ve).toFixed(1).padStart(4)}m/s  고도 ${this.alt.toFixed(1).padStart(5)}m  헤딩 ${this.heading.toFixed(1).padStart(5)}°${this.capturing ? '  CAP' : ''}`);
        };
        if (role === 'move') await this.goTo(step.to!.lat, step.to!.lon, alt, source.speedMps ?? mission.speedMps, step.yaw, live);
        else if (role === 'rot') await this.goTo(step.to!.lat, step.to!.lon, alt, mission.speedMps, step.yaw, live);
        else { const end = Date.now() + source.value * 1000; while (Date.now() < end) { live(); await this.wait(100); } }
        const t1 = Date.now() / 1000;
        if (source.capture) {
          this.capturing = false;
          say(`CAP ${k} END t=${t1.toFixed(3)}`);
          say(`CAP ${k} SUMMARY start=${t0.toFixed(3)} end=${t1.toFixed(3)} dur=${(t1 - t0).toFixed(2)}s alt min/max=${alt.toFixed(1)}/${alt.toFixed(1)}m speed mean=${(source.speedMps ?? mission.speedMps).toFixed(2)}m/s cross-track max=0.1m rtk=OK`);
        }
        const [en, ee] = ne(step.to!.lat, step.to!.lon, this.lat, this.lon);
        const posErr = Math.hypot(en, ee) + 0.12;
        const yawErr = yawDiff(this.heading, step.yaw ?? this.heading) + 0.3;
        say(`STEP ${k}/${n} END   t=${t1.toFixed(3)} dur=${(t1 - t0).toFixed(1)}s 목표 오차 ${posErr.toFixed(2)}m 헤딩 ${this.heading.toFixed(1)}°(목표 ${(step.yaw ?? 0).toFixed(1)}°, 오차 ${yawErr.toFixed(1)}°) 고도 ${this.alt.toFixed(1)}m`);
        results.push(`[결과] 단계 ${k} ${step.label}: 목표 오차 ${posErr.toFixed(2)}m · 기수 오차 ${yawErr.toFixed(1)}°`);
      }
      this.target = null;
      for (const line of results) say(line);
      say('[미션] FC 의 미션을 지웠다');
      throw new Exit(0);
    } catch (error) {
      this.capturing = false;
      let code = 1;
      if (error instanceof Exit) code = error.code;
      else if (error instanceof Cancelled && this.cancelReason() === 'mode') {
        say(`[중단] 비행 모드가 ${this.cancelMode()} 로 바뀌었다 — 캡처 OFF. 조종기/FC 가 제어 중이므로 더 명령하지 않는다.`);
      } else if (error instanceof Cancelled && !this.stopped) {
        say('[중단] 사용자 중단 (Ctrl+C/SIGTERM) — 캡처 OFF');
        if (phase === 'air') {
          const how = mission.abort;
          say(`[중단] ${how} 명령을 보낸다 — ★ 필요하면 즉시 조종기로 개입할 것 ★`);
          void this.abortTo(how, run.runId);
        }
      }
      say('[종료]');
      this.exit(run, code);
      this.cancel = null;
    }
  }

  /** 스크립트가 끝난 뒤에도 기체는 abort 동작을 마저 한다(FC 가 하는 일이다). */
  private async abortTo(how: 'rtl' | 'hold' | 'land', _runId: string): Promise<void> {
    if (how === 'hold') { this.mode = 'HOLD'; this.target = { lat: this.lat, lon: this.lon, alt: this.alt, speed: 0, yaw: null }; return; }
    if (how === 'rtl') {
      this.mode = 'RTL';
      this.target = { lat: this.lat, lon: this.lon, alt: Math.max(this.alt, 30), speed: 3, yaw: null };
      while (!this.arrived()) { if (this.stopped) return; await new Promise((r) => setTimeout(r, 100)); }
      this.target = { lat: HOME.lat, lon: HOME.lon, alt: this.alt, speed: 5, yaw: null };
      while (!this.arrived()) { if (this.stopped) return; await new Promise((r) => setTimeout(r, 100)); }
    } else this.mode = 'LAND';
    this.target = { lat: this.lat, lon: this.lon, alt: 0, speed: 0, yaw: null };
    while (!this.arrived()) { if (this.stopped) return; await new Promise((r) => setTimeout(r, 100)); }
    this.armed = false;
    this.mode = 'HOLD';
    this.target = null;
  }

  private async emergencyRun(commandId: string, how: 'land' | 'rtl' | 'hold'): Promise<void> {
    const proc = this.newProc(commandId, null, how === 'land' ? [] : [`--${how}`], how);
    this.emergency = proc;
    const say = (text: string) => this.say(proc, text);
    const name = { land: 'LAND(그 자리 착륙)', rtl: 'RTL(귀환 후 착륙)', hold: 'HOLD(그 자리 정지)' }[how];
    say('[연결] tcpout://127.0.0.1:5760 (컴포넌트 191) ...');
    await new Promise((r) => setTimeout(r, 400));
    say(`[상태] arm=${this.armed} 공중=${this.inAir()} 모드=${this.mode} 고도=${this.alt.toFixed(1)}m`);
    if (!this.armed && !this.inAir()) {
      say('[확인] 이미 지상·disarm 이다 — 명령을 보내지 않는다');
      say('[종료]');
      this.exit(proc, 0);
      return;
    }
    say(`[명령] ${name} 전송 ✔`);
    if (this.run?.state === 'running' || this.seqRun?.state === 'running') this.cancel = { reason: 'mode', mode: how.toUpperCase() };
    say('[미션] FC 의 미션을 지웠다');
    say('[캡처] CAP 파일 삭제');
    this.capturing = false;
    const done = this.abortTo(how, proc.runId);
    if (how === 'hold') { await done; say('[확인] HOLD — 그 자리에 떠 있다. 조종기로 이어받을 것'); say('[종료]'); this.exit(proc, 0); return; }
    let last = 0;
    while (this.armed && !this.stopped) {
      if (Date.now() - last > 1000) { last = Date.now(); say(`       모드 ${this.mode}  고도 ${this.alt.toFixed(1)}m  공중 ${this.inAir()}`); }
      await new Promise((r) => setTimeout(r, 100));
    }
    say('[확인] 착륙 · disarm ✔');
    say('[종료]');
    this.exit(proc, 0);
  }
}

// ── 복합 미션 흉내의 도움 (261113) ──

type SeqProc = Proc & { steps: string[]; plan: Record<string, unknown> & { key: string; hash: string } | null };

const SEQ_KNOWN = new Set(['dry_run', 'confirmed', 'altitude_m', 'step_count', 'land', 'speed_mps', 'max_radius_m', 'abort',
  'heading_deg', 'accept_radius_m', 'align_hold_s', 'settle_s', 'gap_s', 'rtk_min_s', 'rtk_timeout_s']);

/** 실행기의 모양 검사(§3) — 빠진 키 · 모르는 키 · 정수여야 하는 값 · `step_count` 를 넘는 `s{k}_*`. 범위는 스크립트 몫. */
function seqShapeError(p: Params): string | null {
  for (const key of ['dry_run', 'altitude_m', 'step_count']) if (!(key in p)) return `missing ${key}`;
  const count = p.step_count!;
  if (!Number.isInteger(count) || count < 1) return 'step_count must be an integer';
  for (const key of Object.keys(p)) {
    const match = key.match(/^s(\d+)_(kind|value|speed_mps|capture)$/);
    if (match !== null) { if (Number(match[1]) < 1 || Number(match[1]) > count) return `${key} beyond step_count`; continue; }
    if (!SEQ_KNOWN.has(key)) return `unknown ${key}`;
  }
  for (let k = 1; k <= count; k += 1) {
    if (!(`s${k}_kind` in p) || !(`s${k}_value` in p)) return `missing s${k}_kind/value`;
    if (!Number.isInteger(p[`s${k}_kind`])) return `s${k}_kind must be an integer`;
  }
  return null;
}

function seqFromParams(p: Params): SeqMission {
  const steps: SeqStep[] = [];
  for (let k = 1; k <= (p.step_count ?? 0); k += 1) {
    steps.push({
      kind: STEP_KINDS[p[`s${k}_kind`] ?? 0] ?? 'forward',
      value: p[`s${k}_value`] ?? 0,
      speedMps: p[`s${k}_speed_mps`] ?? null,
      capture: p[`s${k}_capture`] === 1,
    });
  }
  return {
    altitudeM: p.altitude_m ?? 5, speedMps: p.speed_mps ?? 1, land: p.land === 1 ? 'home' : 'here',
    abort: p.abort === 1 ? 'hold' : p.abort === 2 ? 'land' : 'rtl', maxRadiusM: p.max_radius_m ?? 30, steps,
  };
}

function stepWire(step: SeqStep): string {
  return missionKey({ altitudeM: 0, speedMps: 0, land: 'here', steps: [step] }).split('|').at(-1)!;
}

const KIND_KO: Readonly<Record<string, string>> = { forward: '앞', back: '뒤', right: '오른쪽', left: '왼쪽', cw: '시계', ccw: '반시계', hover: '대기' };

/** 드론 `Step.label()` 과 같은 모양 — `오른쪽 3m` · `앞 2m @0.5m/s +캡처` · `대기 5초`. */
function fakeLabel(step: SeqStep): string {
  const unit = { move: 'm', rot: '°', hover: '초' }[stepClass(step.kind)];
  const f = (x: number) => String(Number(x.toFixed(3)));
  return `${KIND_KO[step.kind]} ${f(step.value)}${unit}${step.speedMps !== null ? ` @${f(step.speedMps)}m/s` : ''}${step.capture ? ' +캡처' : ''}`;
}

async function sha16(text: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

class Exit extends Error {
  readonly code: number;

  constructor(code: number) {
    super(`exit ${code}`);
    this.code = code;
  }
}
