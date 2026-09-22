/**
 * src/physical/robotClient.ts (260910 신설 — 화면 연결)
 *
 * **화면이 쓰는 클라이언트 하나.** 여러 화면이 각자 만들면 브로커에 여러 번 붙고,
 * 그중 하나만 정지 명령을 받는 날이 온다.
 *
 * 만들기만 하고 **붙지는 않는다** — 붙는 것은 사람이 「연결 확인」을 누를 때다.
 * 화면을 열자마자 브로커를 찾아 나서면, 브로커가 없는 개발 자리에서 매번 실패 로그가 쌓인다.
 */

import { t } from '../i18n/dict.ts';
import { PhysicalClient, physicalWsUrls } from './PhysicalClient.ts';
import { issuePing, issueScan, shouldIssueScan } from './robotCommands.ts';
import { robotSession, setConnection, subscribeRobot } from './robotSession.ts';
import { currentMission } from '../data/scenario.ts';
import { noteIssue } from '../shared/notifications.ts';
import { deviceState, receiveDeviceMessage } from './deviceState.ts';
import { noteScanFeed } from '../detect/feedLog.ts';
import { indexOfRotation } from '../detect/parse.ts';
import { hardwareTarget } from './encode.ts';
import { awaitDeviceIdentity, deviceIdentityFor } from './deviceIdentity.ts';
import { receiveScanCapture } from './robotBridge.ts';
import { elapsedSec } from './robotSession.ts';
import { initPrepStage } from './prepStage.ts';
import { initScanContinue } from './scanContinue.ts';
import { noteRobotFrame } from '../record/recorder.ts';
import type { PhysicalStatus } from './PhysicalClient.ts';

/**
 * **연결이 바뀌면 알림에 한 줄** (260913 지시 — 「실제로 이슈가 생기면 알림에도 뜨도록」).
 *
 * 머리줄의 표시등은 **지금 상태**만 보여 준다. 끊겼다 다시 붙으면 초록으로 돌아가 있어서
 * 「아까 끊겼었다」는 사실이 사라진다. 시연 도중 한 번 끊겼던 것이 나중에 원인이 되는데,
 * 그때 되짚을 자리가 없었다.
 *
 * `noteIssue` 가 **직전과 같은 문구만** 삼키므로, 끊겼다 붙었다 다시 끊기면 세 줄이 남는다.
 */
function noteConnection(status: PhysicalStatus): void {
  /**
   * **붙는 중과 안 붙음은 안 올린다** (260913 — 실측하고 줄였다).
   *
   * 처음에 넷을 다 올렸더니 「확인」 한 번에 두 줄이 생겼다 — 「붙는 중입니다」와
   * 「끊겼습니다」. 앞의 것은 **이슈가 아니라 지나가는 상태**이고, 그 상태는 머리줄의
   * 표시등이 이미 실시간으로 보여 준다.
   *
   * 남기는 것은 **결말 둘**이다. 끊겼다(이슈)와 다시 붙었다(복구). 복구를 안 남기면
   * 나중에 로그를 읽는 사람이 그 뒤로 계속 끊겨 있었다고 읽는다.
   */
  if (status.state === 'connecting' || status.state === 'idle') return;
  const words = status.state === 'open'
    ? t('rc.1')
    : t('rc.brokerLost', { reason: status.reason || t('rc.noReason') });
  noteIssue('robot-broker', 'connection', words);
}

/**
 * **브로커마다 클라이언트 하나** (260922 — 로봇 N대 동시 연결 1단계).
 *
 * 전에는 싱글턴 하나였다. 로봇이 둘이면 브로커도 둘이고(Go1 은 pi7, 드론은 pi3) 소켓
 * 하나로는 둘을 못 본다 — 주소를 바꾸면 앞엣것이 끊겼다.
 *
 * 주소를 키로 둔다. 연결 관리에서 줄을 지우면 그 클라이언트는 **끊고 버린다** — 안 버리면
 * 지운 주소에 소켓이 남아 카드가 계속 뜬다.
 */
const pool = new Map<string, PhysicalClient>();
/** 마지막으로 스캔을 시도한 조건. 같은 조건이면 다시 안 쏜다 (아래 주석). */
let lastScanAttempt = '';
/** 임무를 모는 배선이 붙어 있는 주소. 첫 줄이 바뀌면 옮겨 단다. */
let drivingUrl: string | null = null;

/**
 * **지금 주소 목록대로 풀을 맞춘다.** 없는 것은 만들고, 사라진 줄은 끊어서 버린다.
 *
 * 부르는 쪽은 화면과 연결 관리다 — 주소가 바뀌는 순간이 그때뿐이라 여기서 맞춘다.
 */
export function syncRobotClients(): readonly PhysicalClient[] {
  const urls = physicalWsUrls();
  for (const [url, client] of pool) {
    if (urls.includes(url)) continue;
    // 줄이 지워졌다 — 소켓을 남겨 두면 없는 설정의 로봇이 카드에 계속 뜬다.
    client.disconnect();
    pool.delete(url);
  }
  for (const url of urls) if (!pool.has(url)) pool.set(url, makeClient(url));
  attachDriver(urls[0] ?? null);
  return urls.map((url) => pool.get(url)!).filter((client) => client !== undefined);
}

/** 지금 있는 클라이언트 전부. 연결 관리와 표시등이 줄마다 상태를 묻는다. */
export function robotClients(): readonly PhysicalClient[] {
  return syncRobotClients();
}

/**
 * **대상을 안 받는 옛 호출이 쓰는 클라이언트** — 목록의 첫 줄이다.
 *
 * 2단계(명령 대상을 명시 인자로)가 이 함수를 걷어낸다. 그때까지는 임무를 모는 로봇이
 * 첫 줄이고, 화면이 그 사실을 적는다. **조용히 한 대를 고르지 않는다** — 로봇이 둘이면
 * `deviceIdentity()` 가 `null` 을 내어 명령 자체가 막힌다(`deviceIdentity.ts`).
 */
export function robotClient(): PhysicalClient {
  const urls = physicalWsUrls();
  const url = urls[0] ?? '';
  syncRobotClients();
  const found = pool.get(url);
  if (found !== undefined) return found;
  // 주소가 하나도 없을 때도 면은 있어야 한다 — 붙지 못할 뿐이다.
  const empty = makeClient(url);
  pool.set(url, empty);
  return empty;
}

/** 브로커 하나에 대한 클라이언트. **중립 배선만** 단다 — 임무는 아래 `attachDriver` 가 단다. */
function makeClient(url: string): PhysicalClient {
  {
    // 붙을 **장비**는 넘기지 않는다 — 붙은 장비가 자기 이름을 댄다 (260921 · `deviceIdentity.ts`).
    const singleton = new PhysicalClient(url);
    // **연결 상태는 만들 때 잇는다** (260910). 화면 부품이 구독하게 두면 그 부품이 안 떠
    // 있는 동안의 변화를 놓치고, 「붙었는데 세션은 모른다」가 된다 — 승인 순간에 그게
    // 나면 대본 타이머가 돌아 로봇보다 화면이 앞서 간다.
    singleton.onStatus((status) => {
      /**
       * **모는 클라이언트의 상태만 세션에 민다** (260922).
       *
       * 세션은 임무 하나를 따라가는 것이다. 로봇이 둘이면 둘의 연결 상태가 번갈아
       * 덮어써서 「붙었다 · 끊겼다」가 이유 없이 반복되고, 대본 타이머가 그것을 보고 돈다.
       *
       * 줄마다의 상태는 **연결 관리가 줄마다 따로** 보여 준다 — 그쪽이 그 물음의 자리다.
       */
      if (url !== drivingUrl) return;
      // 알림을 먼저 적고 세션을 민다 — 순서가 뒤면 화면이 새 상태로 다시 그려진 뒤에
      // 알림이 붙어, 로그를 되짚을 때 한 칸씩 어긋나 보인다.
      noteConnection(status);
      setConnection(status);
    });
    // 장비 상태도 만들 때 잇는다 — 화면 부품이 안 떠 있는 동안의 값을 놓치면
    // 하드웨어 카드가 「모른다」로 남는다.
    singleton.onDevice(receiveDeviceMessage);
    // **임무 배선은 여기 없다.** 아래 `attachDriver` 가 첫 줄 하나에만 단다 —
    // 모든 클라이언트에 달면 드론에도 스캔 명령이 나간다.
    return singleton;
  }
}

/**
 * **임무를 모는 배선.** 스캔 발행·준비 단계·촬영 대기 해제·탐지 흐름이 여기 붙는다.
 *
 * **클라이언트 하나에만 단다.** 전부에 달면 드론에도 `scan_mission` 이 나가고, 드론은
 * 그 action 을 선언한 적이 없다(계약 §4) — 거절당하는 것이 그나마 다행인 실패다.
 *
 * 지금은 **주소 목록의 첫 줄**이 그 자리다. 3단계에서 **배정**이 이 자리를 대신한다 —
 * 「어느 로봇이 이 임무를 모나」는 원래 배정이 답할 물음이고, 첫 줄은 그때까지의 임시값이다.
 *
 * 첫 줄이 바뀌면 옮겨 단다. 옛 자리의 구독은 끊지 않는다 — `subscribeRobot` 이 세션을
 * 보고 돌기 때문에 클라이언트가 바뀌어도 조건이 같으면 같은 답을 낸다. 대신 **누가 몰고
 * 있는지**를 한 곳에 적어 둔다(`drivingUrl`).
 */
function attachDriver(url: string | null): void {
  if (url === null || url === drivingUrl) return;
  const singleton = pool.get(url);
  if (singleton === undefined) return;
  drivingUrl = url;
  {
    /**
     * **로봇 → 탐지 흐름도 만들 때 잇는다** (260914). 탐지 그림이 안 올 때 로봇이 보냈는지를
     * 화면이 스스로 말할 수 있어야 한다. 각도 → 칸은 지금 올라온 임무의 간격·칸 수로 잡는다.
     */
    singleton.onScanFeed((message) => {
      const mission = currentMission();
      const params = mission.params;
      const stepDeg = typeof params?.viewpoint_step_deg === 'number' ? params.viewpoint_step_deg : 45;
      const count = typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8;
      noteScanFeed(message, stepDeg, count);
      // 로봇이 찍은 원본을 임무 기록에 남긴다 (260914) — 탐지 그림과 견줄 수 있게.
      noteRobotFrame(message);
      // **촬영이 그 칸을 켠다** (260914) — 0도 노드는 회전 없이 촬영만 하므로 이것만이 그 칸을 켠다.
      if (message.kind === 'frame') {
        const index = indexOfRotation(message.rotationDeg, stepDeg, count);
        const heading = deviceState(hardwareTarget('robot-01'))?.position?.headingDeg ?? null;
        if (index !== null) receiveScanCapture(mission.missionId, elapsedSec(), index, index === 0 ? heading : null);
      }
    });
    // **준비 단계(T-A1·T-A2)도 여기서 잇는다** — 스캔 발행과 같은 이유다. 그리기에 매이면
    // 두 판째에 안 돈다.
    initPrepStage();
    // **로봇의 촬영 뒤 대기를 푸는 신호도 여기서 잇는다** (260914) — 그 각도 그림이 화면에 뜨면 다음 회전.
    initScanContinue(() => singleton);
    /**
     * **승인이 스캔을 쏘는 자리도 여기다** (260911 — 두 판째에 안 나가던 자리).
     *
     * 전에는 화면의 `useEffect` 가 `session.approved` 가 바뀌는 것을 보고 쐈다. 한 판을
     * 돌린 뒤 같은 임무를 다시 올리면 `approved` 는 **true → false → true** 로 한 틱 안에
     * 오간다(`activateMission` 이 세션을 비우고 곧바로 승인이 다시 걸린다). React 가 그
     * 둘을 한 번의 그리기로 묶으면 **의존값이 안 바뀐 것으로 보여 효과가 안 돈다.**
     * 그러면 승인은 됐는데 로봇에는 아무것도 안 간다.
     *
     * 그래서 그리기와 무관한 자리로 옮겼다 — 세션이 바뀔 때마다 조건을 다시 보고, 참이면
     * 쏜다. 관문(`markScanIssued`)이 한 번만 열리게 스스로 빗장을 건다.
     *
     * 연결 상태·장비 상태를 여기서 잇는 것과 같은 이유이고 같은 자리다.
     */
    subscribeRobot(() => {
      if (!shouldIssueScan()) return;
      /**
       * **같은 조건으로 두 번 시도하지 않는다** (260912 — 브라우저가 멎었다).
       *
       * 발행이 실패하면 `issueScan` 이 관문을 도로 내린다(다시 시도할 수 있게). 그런데 그
       * 내림 자체가 세션 변경이라 이 구독이 다시 불리고, 조건이 그대로니 또 쏘고, 또 실패해
       * **한 틱 안에서 무한히 돈다.** 화면이 통째로 멎는다.
       *
       * 실제로 그렇게 멎었다 — 연결 상태만 `open` 이고 소켓은 안 붙은 상태에서.
       *
       * 그래서 **무엇이 바뀌었을 때만** 시도한다. 승인이나 연결 상태가 그대로면 한 번으로
       * 끝이고, 사유는 화면에 남는다. 다시 하려면 사람이 「처음부터」를 누른다.
       */
      const session = robotSession();
      const attempt = `${session.started}|${session.approved}|${session.connection.state}|${session.startedAtMs ?? 0}`;
      if (attempt === lastScanAttempt) return;
      lastScanAttempt = attempt;
      void issueScan(singleton as PhysicalClient, currentMission().params);
    });
  }
}


/**
 * 연결 관리가 쓰는 얇은 면 (`PhysicalProbe`). **주소·토픽은 여기서도 안 샌다** —
 * 팝업은 「붙어라 · 물어봐라」만 알고 어디에 어떻게 붙는지는 모른다.
 */
export function robotProbe() {
  return probeFor(robotClient());
}

/** 클라이언트 하나에 대한 면. `robotProbe` 와 `robotProbes` 가 같은 것을 쓴다. */
function probeFor(client: PhysicalClient) {
  return {
    connect: () => client.connect(),
    getStatus: () => client.getStatus(),
    ping: () => issuePing(client),
    /**
     * **누구와 말하고 있는가** (260921). 팝업은 장비 이름을 여기서만 받는다 — 주소로
     * 짐작하지 않는다. 아직 아무 말도 못 들었으면 잠깐 기다렸다가 `null` 이다.
     */
    /**
     * **그 브로커의 장비를 본다** (260922). 전역판(`awaitDeviceIdentity`)은 로봇이 둘이면
     * `null` 이고 — 그건 명령을 막으려는 판정이라 맞다 — 여기서 쓰면 줄마다의 확인이
     * 둘 다 「모른다」가 된다. 이 줄이 묻는 것은 **이 주소에 누가 있나**다.
     */
    identity: () => awaitDeviceIdentity().then(() => {
      const found = deviceIdentityFor(client.address());
      return found === null ? null : {
        deviceId: found.deviceId,
        kind: found.kind,
        deviceType: found.deviceType,
      };
    }),
  };
}

/**
 * **주소마다 하나씩, 연결 관리가 쓰는 얇은 면** (260922).
 *
 * 주소·토픽은 여기서도 안 샌다 — 팝업은 「붙어라 · 물어봐라」와 **어느 줄의 것인가**만 안다.
 * 그 주소는 팝업이 이미 화면에 적고 있는 값이라 새로 새는 것이 아니다.
 */
export function robotProbes(): readonly { probe: ReturnType<typeof robotProbe>; address: string }[] {
  return syncRobotClients().map((client) => ({ probe: probeFor(client), address: client.address() }));
}

/**
 * **그 장비에게 닿는 클라이언트** (260922 — 2단계).
 *
 * 「어느 로봇에게 보낼까」는 「어느 소켓으로 보낼까」와 같은 물음이다. 장비가 자기를 밝힌
 * 브로커가 그 답이고, **주소로 짐작하지 않는다** — 장비가 말한 것으로 정한다(§원칙 1).
 *
 * 3단계에서 **배정**이 이 함수의 입구가 된다: 배정이 장비 id 를 주면 여기가 소켓을 찾는다.
 *
 * 못 찾으면 `null` 이다. 그러면 부르는 쪽이 **안 쏜다** — 아무 소켓으로나 물러서면 명령이
 * 엉뚱한 브로커의 토픽으로 떨어져 조용히 사라진다.
 */
export function clientForDevice(deviceId: string): PhysicalClient | null {
  if (deviceId === '') return null;
  for (const client of syncRobotClients()) {
    if (deviceIdentityFor(client.address())?.deviceId === deviceId) return client;
  }
  return null;
}
