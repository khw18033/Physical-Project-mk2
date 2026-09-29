// scripts/lib/runnerRig.mjs (260929 신설 — 임무 실행기 시험대)
//
// **가짜 브로커 둘에 장비를 세우고 판을 끝까지 돌린다.** 장치 두 대 편(`verify:script-two-devices`)과
// @까지 이동 편(`verify:script-at-move`)이 같이 쓴다.
//
// 로봇 응답은 `PhysicalClient.prototype.send` 를 가로채 만든다 — 수락 → 결과(SUCCEEDED). 장비 상태는 실제 수신
// 입구(`receiveDeviceMessage`)로 넣는다: 배터리 · 링크 · 생사가 화면이 받는 길 그대로 들어간다.

import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export async function makeRig(root) {
  const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
  // **robotClient 를 먼저 부른다** — PhysicalClient 가 기본 주소를 import 순간에 적어 둔다.
  const { robotClients } = await load('src', 'physical', 'robotClient.ts');
  const scenario = await load('src', 'data', 'scenario.ts');
  const slots = await load('src', 'data', 'slots.ts');
  const runner = await load('src', 'physical', 'taskRunner.ts');
  const { receiveDeviceMessage, resetDevices } = await load('src', 'physical', 'deviceState.ts');
  const { resetDeviceTelemetry } = await load('src', 'shared', 'deviceTelemetry.ts');
  const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
  const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const original = PhysicalClient.prototype.send;
  runner.startTaskRunner();
  runner.setCameraProbe(async () => ({ ok: true }));

  /**
   * @param {object} o
   * @param {string} o.missionId
   * @param {string} [o.target]          발화에서 잘라 온 @
   * @param {Record<string,string>} o.bindings   자리 → 장비 id (마일스톤에 카드를 놓은 결과)
   * @param {Array<{id:string, type:string, deviceType:string, broker:'pi7'|'pi3', body?:object}>} o.devices
   * @param {number|null} [o.rejectMoveAt]  몇 번째 **이동 명령**(turn · move_forward)을 거절할지
   * @param {(view:object)=>void} [o.tweak] 승인 뒤 판의 params 를 바꾼다(대조군)
   * @param {(ctx:object)=>Promise<void>} [o.during]  판이 도는 중에 한 번 부른다(재시작 시험)
   */
  async function run({ missionId, target = '문', bindings, devices, rejectMoveAt = null, tweak, during, maxTicks = 200 }) {
    const sent = [];
    let n = 0;
    let moves = 0;
    PhysicalClient.prototype.send = function send(action, parameters) {
      n += 1;
      const commandId = `cmd-${n}`;
      const isMove = action === 'turn' || action === 'move_forward';
      if (isMove) moves += 1;
      const moveOrder = moves;
      sent.push({ to: this.address(), action, parameters });
      const emit = (message) => { for (const listener of this.listeners) listener(message); };
      setTimeout(() => {
        if (action === 'abort' || action === 'abort_mission' || action === 'emergency_stop') return;
        if (isMove && moveOrder === rejectMoveAt) { emit({ kind: 'acceptance', commandId, accepted: false, code: 'UNIMPLEMENTED', message: 'no' }); return; }
        emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
        setTimeout(() => emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: action === 'ping' ? { uptime_s: 100 } : {}, code: null, message: null }), isMove ? 120 : 5);
      }, 5);
      return { sent: true, commandId };
    };
    resetDevices();
    resetDeviceTelemetry();
    registerConnectionDefault('physical', 'ws', ['ws://pi7.test:9001', 'ws://pi3.test:9001'].join('\n'));
    const clients = robotClients();
    const clientOf = (broker) => clients.find((client) => client.address().includes(broker));
    const report = (device) => {
      const body = {
        channel: 'status', status: 'online', link: 'ok',
        registration: { entity_id: device.id, entity_type: device.type, device_type: device.deviceType },
        ...(device.body ?? {}),
      };
      receiveDeviceMessage(`zoneA/${device.type}/${device.id}/status`, body, clientOf(device.broker).address());
    };
    for (const device of devices) report(device);

    scenario.proposeMission({ origin: 'script', missionId, title: missionId, keywords: [], planId: null, world: 'registry', target });
    slots.resetSlots();
    slots.holdSlotsFor(missionId);
    for (const [slot, deviceId] of Object.entries(bindings)) slots.dropOnSlots([slot], deviceId);
    scenario.acceptProposal('local');
    const beforeStart = sent.length;
    const current = scenario.getMissionState().current;
    current.params.play_speed = 20;   // 1배속이면 1분 남짓 — 판의 규칙은 그대로다
    tweak?.(current);
    const canWalk = Object.fromEntries(devices.map((device) => [device.id, runner.canWalk(device.id)]));
    scenario.startLocalRun();
    let called = false;
    for (let i = 0; i < maxTicks && scenario.localRunPhase() !== 'done'; i += 1) {
      await sleep(100);
      // 상태는 주기적으로 온다 — 멈춰 있으면 낡아서 「붙어 있지 않다」가 된다.
      if (i % 10 === 0) for (const device of devices) report(device);
      if (scenario.localRunPhase() !== 'stopped') continue;
      // 판이 섰다. 재시작 시험이면 한 번 손을 쓰게 하고(배터리 교체 · 재시작) 이어서 본다. 아니면 여기서 끝이다.
      if (during === undefined || called) break;
      called = true;
      await during({ report, devices, scenario });
    }
    const trace = [...scenario.traceEvents()];
    PhysicalClient.prototype.send = original;
    return { sent, beforeStart, trace, phase: scenario.localRunPhase(), canWalk, view: scenario.getMissionState().current };
  }

  return { run, scenario, runner, slots };
}

/** 기록 열에서 그 태스크의 그 상태 첫 사건. */
export const eventOf = (trace, id, status) => trace.find((e) => e.nodeId === id && e.status === status) ?? null;

/** 「임무 시작」 줄 — 넘긴 태스크가 적힌 판 기록. */
export const startedLine = (trace) => trace.find((e) => e.kind === 'mission_started') ?? null;
