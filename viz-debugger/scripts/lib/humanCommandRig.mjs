// scripts/lib/humanCommandRig.mjs (261023 신설 — 사람 명령 액션 층 §4)
//
// **사람이 직접 내는 명령 셋을 실제 길로 낸다** — 수동 제어(키) · SAR 시작 · 비행 시작.
// `verify:human-command-layer` 가 원본과 사본을 같은 이 판으로 몬다.
//
// 가짜 장비는 명령마다 수락을 답한다 — 답이 같은 행에 붙는지 보려면 답이 와야 한다.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function humanCommandKit(root) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  // 수동 제어 설정은 브라우저 저장소를 읽는다 — 흉내를 깐다.
  if (globalThis.localStorage === undefined) {
    const memory = new Map();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key) => (memory.has(key) ? memory.get(key) : null),
        setItem: (key, value) => memory.set(key, String(value)),
        removeItem: (key) => memory.delete(key),
      },
    });
  }
  const scenario = await load('src', 'data', 'scenario.ts');
  const trace = await load('src', 'data', 'trace.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const mc = await load('src', 'physical', 'manualControl.ts');
  const { noteCapability, resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
  const { TELEOP_ACTION, STOP_ACTION } = await load('src', 'physical', 'presets.ts');
  const sarPlan = await load('src', 'sar', 'plan.ts');
  const flightPlan = await load('src', 'physical', 'flightPlan.ts');
  const MISSION = 'MSN-260909-01';
  const column = () => scenario.traceFor(scenario.currentMission());

  /** 명령마다 수락을 답하는 가짜 장비. */
  function answeringDevice(prefix) {
    const listeners = new Set();
    const sent = [];
    return {
      sent,
      address: () => `ws://${prefix}.test:9001`,
      getStatus: () => ({ state: 'open' }),
      onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
      send(action, parameters) {
        const commandId = `${prefix}-${String(sent.length + 1).padStart(4, '0')}`;
        sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
        setTimeout(() => { for (const cb of [...listeners]) cb({ kind: 'acceptance', commandId, accepted: true, code: null, message: null }); }, 3);
        return { sent: true, commandId };
      },
    };
  }

  /**
   * 한 판. 돌려주는 것은 이 판이 열에 더한 사건과, **사람이 낸 명령 목록**(어느 장비에 무엇이 나갔나)이다.
   *
   * @param mods  `{ md, sar, flight }` — 원본 또는 사본 모듈
   */
  async function drive(mods, prefix) {
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.previewMission(MISSION);
    resetDeviceIdentity();
    mc.resetManualControl();
    mods.md.resetManualDispatch();
    const before = new Set(column().map((e) => e.seq));
    const issued = [];

    // ── 수동 제어 — 속도 모드: 누르고(전진) 떼면(0) 두 건 ──
    const go1 = answeringDevice(`${prefix}go1`);
    mods.md.setManualProbes({ client: (id) => (id === 'go1-001' ? go1 : null), typing: () => false, auto: () => false });
    noteCapability('go1-001', ['ping', TELEOP_ACTION, STOP_ACTION], go1.address());
    mc.setManualEnabled('go1-001', true);
    mods.md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
    await sleep(10);
    mods.md.manualKeyUp('KeyW');
    await sleep(20);
    for (const s of go1.sent) issued.push({ ...s, deviceId: 'go1-001' });
    mods.md.resetManualDispatch();

    // ── SAR 시작 ──
    const drone = answeringDevice(`${prefix}sar`);
    const sarParams = sarPlan.toStartParams({ ...sarPlan.defaultDraft(), start: { lat: 37.5665, lon: 126.978 }, end: sarPlan.endFrom({ lat: 37.5665, lon: 126.978 }, 45, 80) });
    await mods.sar.issueSarStart(sarParams, { client: drone, deviceId: 'x500-001', start: 'yes', abort: 'yes', reason: '' });
    for (const s of drone.sent) issued.push({ ...s, deviceId: 'x500-001' });

    // ── 비행 제어 — dry-run 시작 ──
    const pi3 = answeringDevice(`${prefix}fly`);
    await mods.flight.issueFlightStart({ client: pi3, deviceId: 'x500-002', start: 'yes', stop: 'yes', emergency: 'yes', reason: '' },
      flightPlan.FLIGHT_DEFAULTS, { dryRun: true, confirmed: false });
    for (const s of pi3.sent) issued.push({ ...s, deviceId: 'x500-002' });

    await sleep(30);
    const added = column().filter((e) => !before.has(e.seq));
    return { added, issued, view: scenario.currentMission() };
  }

  /** 사람 층 — `appendHuman` 의 대역. */
  const isHumanLayer = (event) => Number(event.seq) >= trace.HUMAN_SEQ_BASE && Number(event.seq) < trace.ACTION_SEQ_BASE;

  return { drive, isHumanLayer, column, scenario, session, MISSION, load };
}
