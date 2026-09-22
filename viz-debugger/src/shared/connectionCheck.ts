/**
 * src/shared/connectionCheck.ts (260910 신설 — 연결 관리 통합 §2 · §3)
 *
 * **눌러서 실제로 왕복시키는 자리.** 대상마다 확인 방법이 다르고, 그 다름이 여기 한 곳에 있다.
 *
 * | 대상 | 확인 |
 * |---|---|
 * | `physical` | 브로커 연결 + `ping` 왕복 — **두 줄로 나눈다** |
 * | `detect` | `GET /health` — 2단계-B 에서 잇는다. 지금은 자리만 |
 * | `stt` | `SttClient.probe()` — 기존 |
 * | `generate` | `LlmClient.probe()` — 기존 |
 *
 * `stt`·`generate` 는 **기존 동작을 바꾸지 않는다**(§7). 이미 있는 `probe()` 를 부르기만 한다.
 */

import { probe as generateProbe } from '../generate/LlmClient.ts';
import { probe as sttProbe } from '../stt/SttClient.ts';
import { t } from '../i18n/dict.ts';
import type { ConnectionTargetId } from './connections.ts';
import { line, setChecking, setHealth, type HealthLine } from './connectionHealth.ts';
import { probeDetect, sourceOf } from '../detect/DetectClient.ts';
import { detectState } from '../detect/store.ts';
import { fetchObstacleJson, probeStill, type FetchLike } from '../autodrive/aiClient.ts';
import { parseObstacle } from '../autodrive/obstacle.ts';
// `sourceOf` 라는 이름이 탐지에도 있다 — 두 경계가 같은 모양의 함수를 각자 갖는 것이
// 맞고(섞이면 안 된다), 여기서만 이름을 가른다.
import { probeCapability, sourceOf as capabilitySourceOf, type FetchLike as CapabilityFetchLike } from '../capability/CapabilityClient.ts';
import { capabilityState } from '../capability/store.ts';

/**
 * `physical` 을 확인할 때 쓸 것. 로봇 경계를 이 파일이 직접 열지 않는다 —
 * 주소·토픽을 아는 면은 `src/physical/` 하나여야 한다(`verify:physical-port`).
 * 화면이 클라이언트를 넘긴다.
 */
export type PhysicalProbe = {
  connect(): Promise<{ state: string; reason?: string }>;
  getStatus(): { state: string; reason?: string };
  /**
   * `ping` 왕복. `fcLink` 는 **드론이 답에 실어 주는 값**이고(계약 §5) Go1 은 안 싣는다 —
   * 그래서 없을 수 있고, 없으면 모름이다. 0 으로 읽으면 「FC 가 끊겼다」는 없는 사실이 된다.
   */
  ping(): Promise<{
    ok: boolean; roundTripMs: number | null; message: string;
    fcLink?: boolean | null; fcLinkAgeSec?: number | null;
  }>;
  /**
   * **붙은 장비가 누구인가.** 주소가 아니라 장비가 밝힌 것이다 — 이 판은 어디에 어떻게
   * 붙는지 모르는 채로 「누구와 말하고 있는지」만 받아 적는다.
   *
   * 없을 수 있다(`undefined`) — 옛 목이 이 면을 안 갖고 있어도 확인은 돌아야 한다.
   */
  identity?(): Promise<{ deviceId: string; kind: string | null; deviceType: string | null } | null>;
};

async function timed<T>(run: () => Promise<T>): Promise<{ value: T; ms: number }> {
  const startedAt = Date.now();
  const value = await run();
  return { value, ms: Date.now() - startedAt };
}

/**
 * **`physical` 은 줄이 셋이다** (260910 — 재 보고 하나 늘렸다).
 *
 * 처음에 둘로 나눴다: 브로커와 로봇. 그런데 로봇을 꺼 놓고 눌렀는데 「로봇 ✓」가 떴다.
 * 실제로 uplink 를 떠 보니 **답한 것은 라즈베리파이의 단말 에이전트**였다 —
 * `ping` 의 결과가 `{ uptime_s }` 이고 그건 단말의 가동 시간이다.
 *
 *   브로커  WebSocket 이 서 있는가        실패 → 주소·포트·망
 *   단말    ping 왕복이 도는가            실패 → 라즈베리파이 전원·에이전트
 *   로봇    **ping 으로는 못 본다**       → 「모른다」. 빨강도 초록도 아니다
 *
 * 로봇 줄을 초록으로 칠하면 「로봇이 살아 있다」는 거짓말이고, 빨갛게 칠하면 「로봇이
 * 죽었다」는 없는 사실이다. 둘 다 틀렸으므로 **모른다고 말한다.**
 *
 * 로봇을 증명하려면 로봇을 움직이는 명령을 보내야 하는데, 그건 연결 확인이 할 일이 아니다.
 * 단말이 로봇 상태를 실어 주면 그때 이 줄이 채워진다 — 하드웨어 쪽에 물어볼 것이다.
 */
/** 로봇 줄이 읽는 것. 장비 상태에서 온 값만 담는다 — 이 파일은 토픽을 모른다. */
export type RobotFacts = {
  online: boolean | null;
  link: string | null;
  health: string | null;
  batteryPct: number | null;
  stale: boolean;
  staleSec: number;
};

/**
 * 장비 상태를 **잠깐 기다린다.** 붙자마자 누르면 아직 한 건도 안 와 있는데, 그때 「모른다」로
 * 끝내면 발표 직전 점검에서 늘 한 번 더 눌러야 한다. 상태는 5초 주기라 그만큼만 기다린다.
 *
 * 기다려도 안 오면 그대로 「모른다」다 — 없는 것을 지어내지 않는다.
 */
async function waitForRobot(get: (() => RobotFacts | null) | null, timeoutMs = 6000): Promise<RobotFacts | null> {
  if (get === null) return null;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const facts = get();
    if (facts !== null) return facts;
    if (Date.now() >= deadline) return null;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

/**
 * **브로커마다 줄 셋** (260922 — 로봇 N대 동시 연결 1단계).
 *
 * 로봇이 여럿이면 소켓도 여럿이고, 「어느 주소가 안 붙었나」를 줄이 말해야 한다. 그래서
 * 줄 id 에 주소를 붙이고(`broker@<주소>`) `scope` 에 그 주소를 적는다 — 화면이 줄 앞에 단다.
 *
 * 주소를 `reason` 에 섞지 않는다. 그 칸은 **실패 사유**이고, 성공한 줄에도 주소는 붙어야 한다.
 */
export async function checkPhysicalAll(
  clients: readonly { probe: PhysicalProbe; address: string }[],
  robotSource: RobotFacts | (() => RobotFacts | null) | null = null,
): Promise<readonly HealthLine[]> {
  if (clients.length === 0) return checkPhysical(null, robotSource);
  const out: HealthLine[] = [];
  for (const { probe, address } of clients) {
    // **한 줄로 합치지 않는다.** 하나가 죽어도 나머지 주소의 결과는 그대로 보여야 한다.
    const lines = await checkPhysical(probe, robotSource);
    for (const row of lines) {
      out.push(clients.length === 1 ? row : { ...row, id: `${row.id}@${address}`, scope: address });
    }
  }
  return out;
}

export async function checkPhysical(
  client: PhysicalProbe | null,
  robotSource: RobotFacts | (() => RobotFacts | null) | null = null,
): Promise<readonly HealthLine[]> {
  if (client === null) {
    return [line('broker', 'check.line.broker', false, { reason: t('check.reason.noClient') })];
  }
  const status = client.getStatus().state === 'open'
    ? client.getStatus()
    : (await timed(() => client.connect())).value;

  const broker = status.state === 'open'
    ? line('broker', 'check.line.broker', true)
    : line('broker', 'check.line.broker', false, { reason: status.reason ?? status.state });

  // 브로커가 안 붙었으면 아래 둘은 **확인할 수 없다** — 실패가 아니라 못 물어본 것이다.
  if (broker.ok !== true) {
    return [
      broker,
      line('agent', 'check.line.agent', null, { reason: t('check.reason.noBroker') }),
      line('robot', 'check.line.robot', null, { reason: t('check.reason.noBroker') }),
    ];
  }

  /**
   * **누구와 말하는지 먼저 묻는다** (260921). `ping` 은 장비 id 로 주소를 만들어 나가므로,
   * 장비가 자기를 밝히기 전에 쏘면 나갈 곳이 없다. 붙자마자 오는 retained `status` 가
   * 보통 한 바퀴 안에 답을 준다.
   */
  const who = client.identity === undefined ? null : await client.identity();

  const { value: ping, ms } = await timed(() => client.ping());
  const agent = ping.ok
    // **무엇과 말했는지 적는다.** 「단말 ✓ 12ms」만으로는 pi7 에 붙은 건지 pi3 에 붙은 건지
    // 알 수 없다 — 주소를 바꿔 놓고 안 바뀐 줄 알았던 적이 실제로 있다.
    ? line('agent', 'check.line.agent', true, { roundTripMs: ping.roundTripMs ?? ms, reason: deviceWords(who) })
    : line('agent', 'check.line.agent', false, { reason: ping.message });

  /**
   * **FC 링크를 답에 실어 준 장비면 거기서 끝난다.** 장비 상태를 기다리지 않는다 —
   * 그 장비의 상태는 MQTT 가 아니라 백엔드 `/state` 로 오고, 여기서 6초를 기다려 봐야
   * 영영 안 온다. 실제로 기다리면 확인 한 번에 6초가 그냥 날아간다.
   */
  const fcLink = fcLinkLine(agent, ping);
  if (fcLink !== null) return [broker, agent, fcLink];

  // **붙은 뒤에 기다린다.** 붙기 전에 기다리면 구독이 없어 아무것도 안 오고, 그 시간만
  // 버린 채 「모른다」로 끝난다 — 실제로 그랬다.
  const robot = typeof robotSource === 'function' ? await waitForRobot(robotSource) : robotSource;
  return [broker, agent, robotLine(agent, robot)];
}

/** 장비 줄에 적을 말 — 종류와 이름. 장비가 안 밝혔으면 아무 말도 안 한다. */
function deviceWords(who: { deviceId: string; kind: string | null } | null): string | null {
  if (who === null) return null;
  return who.kind === null ? who.deviceId : `${who.kind} ${who.deviceId}`;
}

/**
 * **셋째 줄 — FC 링크** (260921 · 드론 계약 §5).
 *
 * 줄을 넷으로 늘리지 않는다. 셋째 줄은 원래부터 「단말 너머의 그 장비 자신이 붙어 있는가」
 * 였고(Go1 은 `status.link`), 드론에서 그 자리에 해당하는 것이 FC 링크다. 같은 물음이라
 * 같은 줄에 두고 **이름만 장비에 맞춘다.**
 *
 * **기종으로 가르지 않는다.** `fc_link` 를 실어 보낸 장비면 이 줄이고, 안 실었으면 옛
 * 로봇 줄이다 — 판정 근거가 주소도 기종 목록도 아니라 장비가 보낸 키 하나다.
 *
 * 링크가 없으면 빨갛다. 「라즈베리파이는 켜졌는데 FC 와 안 붙었다」가 정확히 이 모양이고,
 * 무대 전에 이것만 빨간 것을 봐야 한다.
 */
function fcLinkLine(
  agent: HealthLine,
  ping: { fcLink?: boolean | null; fcLinkAgeSec?: number | null },
): HealthLine | null {
  const fcLink = ping.fcLink ?? null;
  if (fcLink === null) return null;
  // 단말이 안 답했으면 그 답에 실려 온 값도 없다 — 앞 줄이 이미 그 사실을 말한다.
  if (agent.ok !== true) return line('robot', 'check.line.fcLink', null, { reason: t('check.reason.agentSilent') });
  const age = ping.fcLinkAgeSec ?? null;
  // 나이는 **있을 때만** 덧붙인다. 한 번도 못 받았으면 키가 없고, 0 으로 적으면 방금 받은 것이 된다.
  const suffix = age === null ? null : t('check.fcLink.age', { sec: age.toFixed(1) });
  return fcLink
    ? line('robot', 'check.line.fcLink', true, { reason: suffix })
    : line('robot', 'check.line.fcLink', false, { reason: t('check.fcLink.down') });
}

/**
 * 로봇 줄 — **`ping` 이 아니라 장비 상태가 채운다** (260910).
 *
 * `ping` 은 단말까지만 증명한다. 로봇 자신이 붙어 있는지는 `zoneA/.../status` 의 `link`
 * (로봇 ↔ 파이 내부 링크)가 말한다. 그 값이 안 왔으면 여전히 「모른다」다 —
 * 안 온 것을 초록으로도 빨강으로도 칠하지 않는다.
 */
function robotLine(agent: HealthLine, robot: RobotFacts | null): HealthLine {
  if (agent.ok !== true) return line('robot', 'check.line.robot', null, { reason: t('check.reason.agentSilent') });
  if (robot === null) return line('robot', 'check.line.robot', null, { reason: t('check.reason.noDeviceStatus') });
  // 시범 키 ② 치환 (영문화 1단계 §4). **영어는 어순이 반대다** — ko 는 숫자가 앞이고
  // en 은 'No signal for {sec}s' 로 뒤다. 조각을 이어붙였다면 옮길 방법이 없었다.
  if (robot.stale) return line('robot', 'check.line.robot', null, { reason: t('check.robot.stale', { sec: robot.staleSec }) });
  if (robot.online === false) return line('robot', 'check.line.robot', false, { reason: t('check.reason.piOffline') });
  if (robot.link !== null && robot.link !== 'ok') return line('robot', 'check.line.robot', false, { reason: t('check.reason.innerLink', { link: robot.link }) });
  if (robot.link === null) return line('robot', 'check.line.robot', null, { reason: t('check.reason.innerLinkMissing') });
  const extra = robot.batteryPct === null ? '' : t('check.reason.batterySuffix', { pct: robot.batteryPct });
  return line('robot', 'check.line.robot', true, { reason: robot.health === 'ok' ? null : `${robot.health}${extra}` });
}

/**
 * `detect` — **자리만 만든다** (§7 「detect 의 실제 확인 로직 — 2단계-B에서 잇는다」).
 *
 * 여기서 `GET /health` 를 지금 부르면, 붙을 곳이 없는 주소에 매번 실패 로그가 쌓이고
 * 「빨간 줄」이 늘 하나 켜져 있게 된다. 그러면 발표 직전 점검에서 「넷 다 초록」이
 * 애초에 불가능해진다. **못 물어봤다고 말한다.**
 */
/**
 * 탐지 확인 (260912 — 자리만이던 것을 실제로 이었다).
 *
 * **「테스트」가 켜져 있으면 시료를 실제로 한 번 읽어 본다.** 「켰는데 파일이 없다」를
 * 그때 잡는다 — 무대에서 체크만 하고 아무것도 안 오면 원인을 못 찾는다.
 */
export async function checkDetect(): Promise<readonly HealthLine[]> {
  const source = sourceOf(detectState().testMode);
  if (source.kind === 'sample') {
    const { value, ms } = await timed(() => probeDetect(source));
    return [value.alive
      ? line('sample', 'check.line.sample', true, { roundTripMs: ms, reason: value.reason })
      : line('sample', 'check.line.sample', false, { reason: value.reason })];
  }
  if (source.base.trim() === '') {
    return [line('health', 'check.line.health', null, { reason: t('check.reason.detectNoAddress') })];
  }
  const { value, ms } = await timed(() => probeDetect(source));
  return [value.alive
    ? line('health', 'check.line.health', true, { roundTripMs: ms })
    : line('health', 'check.line.health', false, { reason: value.reason })];
}

/**
 * `autodrive` 를 확인할 때 쓸 것 (260915 — pi1 중계). 로봇 경계를 이 파일이 직접 열지 않는다 —
 * `physical` 과 같은 이유다. 화면이 넘긴다.
 */
export type NavProbe = {
  connect(): Promise<{ state: string; reason?: string }>;
  getStatus(): { state: string; reason?: string };
  /** 마지막으로 받은 중계 값. 한 건도 안 왔으면 null. */
  latest(): {
    receivedAtMs: number; nodeId: string; entityId: string;
    batteryPct: number | null; yawDeg: number | null; yawSource: string | null;
  } | null;
};

/**
 * **`autodrive` 는 줄이 둘이다** — 브로커 · 중계.
 *
 * 로봇에 물어볼 방법이 없다(명령을 안 보낸다). 대신 pi1 의 중계가 0.5초마다 상태를 내므로,
 * 붙은 **뒤에** 새로 온 한 건이 있으면 중계가 살아 있는 것이다. 6초 안에 안 오면 빨갛다 —
 * 브로커는 붙었는데 중계가 안 돈다는 사실이고, 고칠 곳이 pi1 의 서비스라는 뜻이다.
 */
export async function checkAutodrive(probe: NavProbe | null, waitMs = 6000): Promise<readonly HealthLine[]> {
  if (probe === null) return [line('broker', 'check.line.broker', false, { reason: t('check.reason.noClient') })];
  const askedAt = Date.now();
  const status = probe.getStatus().state === 'open' ? probe.getStatus() : (await timed(() => probe.connect())).value;
  if (status.state !== 'open') {
    return [
      line('broker', 'check.line.broker', false, { reason: status.reason ?? status.state }),
      line('feed', 'check.line.feed', null, { reason: t('check.reason.noBroker') }),
    ];
  }
  const broker = line('broker', 'check.line.broker', true);
  const deadline = Date.now() + waitMs;
  for (;;) {
    const latest = probe.latest();
    if (latest !== null && latest.receivedAtMs >= askedAt) {
      const words = [
        [latest.nodeId, latest.entityId].filter((v) => v !== '').join(' · '),
        latest.batteryPct === null ? t('check.feed.batteryUnknown') : t('check.feed.battery', { pct: latest.batteryPct }),
        latest.yawDeg === null ? t('check.feed.yawUnknown') : // `yawSource` 는 null 일 수 있다. 옛 템플릿이 `${…}` 로 찍어 「null」이 그대로 보였고,
        // 한국어 화면이 한 글자도 달라지면 안 되므로 그 모양을 그대로 둔다.
        t('check.feed.yaw', { deg: latest.yawDeg.toFixed(1), source: String(latest.yawSource) }),
      ].filter((v) => v !== '').join(' · ');
      return [broker, line('feed', 'check.line.feed', true, { roundTripMs: latest.receivedAtMs - askedAt, reason: words })];
    }
    if (Date.now() >= deadline) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return [broker, line('feed', 'check.line.feed', false, { reason: t('check.reason.feedTimeout', { sec: waitMs / 1000 }) })];
}

/**
 * `autodrive-ai` — **장애물 JSON · 영상 한 장** 두 줄 (260915). 둘은 경로가 달라 따로 죽는다 —
 * JSON 은 오는데 스트림만 멎는 일이 실제로 있었다(같은 날 실측).
 */
export async function checkAutodriveAi(fetcher?: FetchLike): Promise<readonly HealthLine[]> {
  const { value: json, ms } = await timed(() => fetchObstacleJson(fetcher));
  const snap = json.ok ? parseObstacle(json.body) : null;
  const control = !json.ok
    ? line('control', 'check.line.control', false, { reason: json.reason })
    : snap === null
      ? line('control', 'check.line.control', false, { reason: t('check.reason.obstacleShape') })
      : line('control', 'check.line.control', true, {
          roundTripMs: ms,
          reason: t('check.reason.obstacleOk', { n: snap.detections.length, near: String(snap.hasNearObstacle) })
            + (json.via === 'direct' ? t('check.reason.viaDirect') : ''),
        });
  const still = await probeStill();
  const stream = line('stream', 'check.line.stream', still.ok, { roundTripMs: still.ms, reason: still.reason });
  return [control, stream];
}

/**
 * 기능 상태 확인 (260920). 탐지와 같은 모양이다 — **「테스트」가 켜져 있으면 받아 둔 자료를
 * 실제로 한 번 읽어 본다.** 「켰는데 아무것도 안 뜬다」를 그때 잡는다.
 *
 * 주소가 비어 있으면 **모른다(null)** 로 둔다. 빨갛게 칠하면 「서비스가 죽었다」는 없는
 * 사실이 되고, 아직 주소를 안 넣은 것뿐이다.
 */
export async function checkCapability(fetcher?: CapabilityFetchLike): Promise<readonly HealthLine[]> {
  const source = capabilitySourceOf(capabilityState().testMode);
  if (source.kind === 'sample') {
    const { value, ms } = await timed(() => probeCapability(source, fetcher));
    return [line('sample', 'check.line.sample', value.alive, { roundTripMs: value.alive ? ms : null, reason: value.reason })];
  }
  if (source.base.trim() === '') {
    return [line('health', 'check.line.health', null, { reason: t('check.reason.capabilityNoAddress') })];
  }
  const { value, ms } = await timed(() => probeCapability(source, fetcher));
  return [value.alive
    ? line('health', 'check.line.health', true, { roundTripMs: ms, reason: value.reason })
    : line('health', 'check.line.health', false, { reason: value.reason })];
}

export async function checkStt(): Promise<readonly HealthLine[]> {
  const { value, ms } = await timed(() => sttProbe());
  return [value.alive
    ? line('probe', 'check.line.probe', true, { roundTripMs: ms })
    : line('probe', 'check.line.probe', false, { reason: value.reason })];
}

export async function checkGenerate(): Promise<readonly HealthLine[]> {
  const { value, ms } = await timed(() => generateProbe());
  return [value.alive
    ? line('probe', 'check.line.probe', true, { roundTripMs: ms })
    : line('probe', 'check.line.probe', false, { reason: value.reason })];
}

/**
 * 대상 하나를 확인한다. **던지지 않는다** — 여기서 예외가 새면 팝업이 통째로 날아간다.
 * 예외도 결과이고, 그 사유가 화면에 남아야 한다.
 */
export async function checkTarget(
  target: ConnectionTargetId,
  physical: PhysicalProbe | null,
  robot: RobotFacts | (() => RobotFacts | null) | null = null,
  nav: NavProbe | null = null,
  /**
   * **주소가 여럿일 때의 상대들** (260922). 주면 이쪽이 이긴다 — `physical` 인자는 상대가
   * 하나뿐이던 시절의 자리이고, 검사들이 그 모양으로 재고 있어 그대로 둔다.
   */
  physicalAll: readonly { probe: PhysicalProbe; address: string }[] | null = null,
): Promise<void> {
  setChecking(target, true);
  try {
    if (target === 'physical') {
      setHealth(target, physicalAll === null
        ? await checkPhysical(physical, robot)
        : await checkPhysicalAll(physicalAll, robot));
    }
    else if (target === 'autodrive') setHealth(target, await checkAutodrive(nav));
    else if (target === 'autodrive-ai') setHealth(target, await checkAutodriveAi());
    else if (target === 'detect') setHealth(target, await checkDetect());
    else if (target === 'capability') setHealth(target, await checkCapability());
    else if (target === 'stt') setHealth(target, await checkStt());
    else if (target === 'generate') setHealth(target, await checkGenerate());
    else setHealth(target, [line('none', 'check.line.none', false, { reason: t('check.reason.noMethod') })]);
  } catch (error) {
    setHealth(target, [line('error', 'check.line.error', false, {
      reason: error instanceof Error ? error.message : String(error),
    })]);
  }
}
