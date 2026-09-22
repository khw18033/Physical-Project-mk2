/**
 * src/physical/deviceIdentity.ts (260921 신설 — 드론 연결 §원칙 1 · 3)
 *
 * **붙은 장비가 누구인가. 주소가 아니라 장비가 말한 것으로 정한다.**
 *
 * 전에는 `encode.ts` 의 표 한 줄(`robot-01 → go1-001`)이 그 답이었다. 주소를 pi3 로 바꿔도
 * 그 표가 그대로라 발행 대상과 구독 토픽이 Go1 에 남는다 — 「붙었다」고 말하면서 아무것도
 * 못 받는 그 모양이다.
 *
 * **주소로 판정하지 않는 이유**는 주소가 바뀌기 때문이다. 같은 드론이 `pi3.local` 이었다가
 * 연구실 IP 였다가 Tailscale IP 가 된다. 주소 문자열로 종류를 가르면 그때마다 깨지고,
 * 깨진 줄도 모른다 — 화면은 여전히 초록이다.
 *
 * ## 원천 셋. 전부 **장비가 발행한 것**이다 (계약 §8)
 *
 *   capability     규약 uplink 의 `capability{device_id, actions[]}`  — 가장 세다
 *   registration   `status.registration{entity_id, entity_type, device_type}`
 *   topic          상태 토픽의 `{zone}/{entity_type}/{entity_id}/{channel}` 두·세 번째 칸
 *
 * ## `Capability` 만으로는 안 된다 (계약 §4 · §11-4)
 *
 * **retained 가 아니다.** 노드가 브로커에 붙는 순간 한 번 발행하고 끝이라, 나중에 붙은 웹은
 * 영영 못 받는다. 그것 하나만 관문으로 두면 **Go1 도 드론도 `ping` 조차 못 낸다** — 그리고
 * `ping` 은 계약이 「Capability 를 못 받았으면 이것으로 확인하라」고 지정한 바로 그 수단이다.
 *
 * 메우는 것이 `status` 다. 이쪽은 **retained** 라 구독하는 즉시 한 건이 오고, 그 안의
 * `registration` 에 `entity_id` 와 `entity_type` 이 들어 있다. 늦게 붙어도 장비가 누구인지
 * 알 수 있는 길이 이것이다.
 *
 * ## 종류는 규약에 자리가 없다 (계약 §8 · REPORT §7)
 *
 * `Capability` 는 `device_id` 와 `actions[]` 뿐이다. `.proto` 를 고치지 않기로 했으므로
 * **종류는 JSON 쪽에서 읽는다.** 드론 쪽도 같은 판단을 적어 보냈다.
 *
 * 종류 문자열을 **우리가 목록으로 정하지 않는다.** 장비가 `drone` 이라고 하면 `drone` 이다.
 * `'robot' | 'drone'` 같은 합집합을 여기 적으면 세 번째 기종이 붙는 날 이 파일을 고쳐야 하고,
 * 그것이 「기종별 표를 코드에 두지 않는다」가 막으려던 바로 그것이다.
 *
 * ## 모르면 모른다고 한다
 *
 * 후보가 둘이면 `null` 이다. 하나를 골라 두면 엉뚱한 장비로 명령이 나간다 — 그것이 이 파일이
 * 막으려는 단 하나의 사고다. 화면 조회는 `encode.ts` 의 옛 표로 물러설 수 있지만
 * (`hardwareTarget`), **발행은 물러서지 않는다** (`commandTarget`).
 */

/** 붙은 장비 하나. 값은 전부 장비가 준 것이고, 안 온 칸은 `null` 이다. */
export type DeviceIdentity = {
  /** 하드웨어가 부르는 이름. 발행 대상과 구독 토픽이 이 값으로 정해진다. */
  deviceId: string;
  /** 장비 종류 — **장비가 보낸 문자열 그대로.** `robot` · `drone` … 우리가 고르지 않는다. */
  kind: string | null;
  /** 더 구체적인 기종 (`x500_drone`). 계약 §8 이 「가장 구체적」이라고 적은 칸이다. */
  deviceType: string | null;
  /**
   * Capability 가 선언한 action 목록.
   *
   * **`null` 은 「못 받았다」이고 `[]` 는 「하나도 없다」이다.** 둘을 뭉치면 정지 버튼이
   * 「이 장비는 정지를 지원하지 않는다」를 못 받은 것만으로 단언하게 된다 — retained 가
   * 아니라서 못 받는 것이 정상인데도.
   */
  actions: readonly string[] | null;
  /** 무엇으로 알았나. 화면과 보고서가 이 사실을 적는다 — 「짐작했다」와 구별하려고. */
  source: 'capability' | 'registration' | 'topic';
  atMs: number;
};

/**
 * 한 장비에 대해 지금까지 모은 것. 원천이 섞여 들어오므로 칸마다 따로 찬다.
 *
 * **260922 — `origin`(어느 브로커에서 봤나)이 생겼다.** 로봇이 여럿이면 브로커도 여럿이고,
 * 한 브로커가 끊길 때 **그 브로커의 장비만** 지워야 한다. 전역으로 비우면 pi3 를 다시 붙일
 * 때마다 pi7 의 Go1 이 사라진다.
 *
 * `origin` 은 주소 문자열이지만 **판정에 쓰지 않는다** — 장비가 누구인지는 여전히 장비가
 * 말한 것으로 정한다(§원칙 1). 여기서는 「어느 소켓이 물어 왔나」라는 살림살이일 뿐이다.
 */
type Candidate = {
  deviceId: string;
  /** 이 장비를 본 브로커. 그 브로커가 끊기면 이 후보만 사라진다. */
  origin: string;
  kind: string | null;
  deviceType: string | null;
  actions: readonly string[] | null;
  /** 가장 센 원천. capability > registration > topic. */
  source: 'capability' | 'registration' | 'topic';
  atMs: number;
};

const RANK: Record<Candidate['source'], number> = { topic: 0, registration: 1, capability: 2 };

let candidates: Record<string, Candidate> = {};
const listeners = new Set<() => void>();
/** 기다리는 쪽을 깨우는 손잡이. 값이 생기면 부른다. */
const waiters = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
  for (const wake of waiters) wake();
}

/**
 * 지금 붙어 있다고 말할 수 있는 장비. **애매하면 `null`.**
 *
 * **260922 — 로봇이 여럿이면 여기는 `null` 이다.** 그것이 맞다: 대상을 안 받는 명령은
 * 로봇이 둘일 때 갈 곳이 정해지지 않는다. 고르는 것은 **배정**의 일이고(3단계), 그때
 * 명령은 대상을 인자로 받는다(2단계). 그 전까지 둘을 붙이면 명령이 막히고, 화면이
 * 그 사실을 적는다 — 조용히 한 대를 골라 쏘는 것보다 낫다.
 *
 * Capability 가 왔으면 그것이다 — 규약 평면에서 자기 이름을 댄 장비이므로 다툼이 없다.
 * 안 왔으면 자기소개(`registration`)를 한 장비가 **정확히 하나**일 때만 그것으로 본다.
 * 그마저 없으면 상태를 보낸 장비가 **정확히 하나**일 때만.
 */
export function deviceIdentity(): DeviceIdentity | null {
  return resolve(Object.values(candidates));
}

/**
 * 후보 묶음에서 **하나를 고르거나 고르지 않는다.** 전역판과 브로커별판이 같은 규칙을 쓴다 —
 * 두 벌로 적으면 한쪽만 고쳐지는 날 명령이 엉뚱한 장비로 나간다.
 */
function resolve(all: readonly Candidate[]): DeviceIdentity | null {
  if (all.length === 0) return null;
  const byCapability = all.filter((c) => c.source === 'capability');
  if (byCapability.length === 1) return byCapability[0];
  // Capability 가 둘이면 장비가 둘이다 — 고르지 않는다.
  if (byCapability.length > 1) return null;
  const introduced = all.filter((c) => c.source === 'registration');
  if (introduced.length === 1) return introduced[0];
  if (introduced.length > 1) return null;
  return all.length === 1 ? all[0] : null;
}

/** 지금 보이는 장비 전부. 화면이 「둘이 보인다」를 말할 수 있게. */
export function deviceCandidates(): readonly DeviceIdentity[] {
  return Object.values(candidates);
}

/**
 * **발행 대상.** 장비가 밝힌 id 가 없으면 `null` 이고, 그러면 명령은 나가지 않는다.
 *
 * 옛 표(`go1-001`)로 물러서지 않는다 — 물러서는 순간 드론에 붙은 채로 Go1 의 토픽에
 * 발행하게 되고, 그것이 이 작업이 없애려던 실패다.
 */
export function commandTarget(): string | null {
  return deviceIdentity()?.deviceId ?? null;
}

/** 이 장비가 그 action 을 할 수 있는가. **`null` 은 모른다** — 안 된다가 아니다. */
export function supportsAction(action: string): boolean | null {
  const actions = deviceIdentity()?.actions ?? null;
  if (actions === null) return null;
  return actions.includes(action);
}

function upsert(next: Candidate): void {
  const previous = candidates[next.deviceId];
  if (previous !== undefined) {
    // 센 원천이 이긴다. 같은 원천이면 새 값이 이긴다 — 장비가 고쳐 말한 것이다.
    const keepSource = RANK[previous.source] > RANK[next.source] ? previous.source : next.source;
    candidates = {
      ...candidates,
      [next.deviceId]: {
        deviceId: next.deviceId,
        // **브로커는 마지막으로 본 쪽이다.** 같은 장비가 두 소켓에 보이면 그건 같은
        // 장비이고, 그 장비에 닿는 길로는 최근 것을 쓴다(`connectedDevices` 와 같은 규칙).
        origin: next.origin || previous.origin,
        // **한 번 안 값을 `null` 로 지우지 않는다.** `state` 는 `registration` 을 안 싣는다.
        kind: next.kind ?? previous.kind,
        deviceType: next.deviceType ?? previous.deviceType,
        actions: next.actions ?? previous.actions,
        source: keepSource,
        atMs: next.atMs,
      },
    };
  } else {
    candidates = { ...candidates, [next.deviceId]: next };
  }
  notify();
}

/**
 * 규약 uplink 의 `capability` 를 받았다 (계약 §4).
 *
 * 이것이 오면 장비 종류는 몰라도 **누구인지와 무엇을 할 수 있는지**는 확실하다.
 */
export function noteCapability(
  deviceId: string,
  actions: readonly string[],
  origin = '',
  nowMs = Date.now(),
): void {
  if (deviceId === '') return;
  upsert({ deviceId, origin, kind: null, deviceType: null, actions: [...actions], source: 'capability', atMs: nowMs });
}

/**
 * 상태 한 건을 받았다. 토픽에서 id·종류를, 본문의 `registration` 에서 더 구체적인 것을 읽는다.
 *
 * `registration` 은 `status` 채널에만 실린다. 계약 §3-1 이 이 채널을 **retained** 로 두었기
 * 때문에 늦게 붙은 웹도 구독 즉시 한 건을 받는다 — 그것이 Capability 공백을 메우는 자리다.
 */
export function noteDeviceReport(
  entityId: string,
  entityType: string,
  body: Record<string, unknown>,
  origin = '',
  nowMs = Date.now(),
): void {
  if (entityId === '') return;
  const registration = body.registration as Record<string, unknown> | undefined;
  const registeredId = str(registration?.entity_id);
  const registeredKind = str(registration?.entity_type);
  const deviceType = str(registration?.device_type);
  // 자기소개가 있으면 그쪽 id 가 맞다 — 토픽은 발행자가 실수할 수 있고 본문은 노드가 짓는다.
  const deviceId = registeredId ?? entityId;
  const introduced = registration !== undefined && (registeredId !== null || registeredKind !== null);
  upsert({
    deviceId,
    origin,
    kind: registeredKind ?? (entityType === '' ? null : entityType),
    deviceType,
    actions: null,
    source: introduced ? 'registration' : 'topic',
    atMs: nowMs,
  });
}

/**
 * **그 브로커에서 본 장비를 비운다.** 붙을 때와 끊을 때 부른다.
 *
 * 주소를 바꿔 다른 브로커에 붙으면 거기 있는 장비는 다른 장비다. 안 비우면 pi7 에서 본
 * `go1-001` 이 pi3 에 붙은 뒤에도 남아 「장비가 둘」이 되고, 그러면 애매해져서 명령이
 * 통째로 막힌다.
 *
 * **260922 — 브로커 하나만 비운다.** 로봇이 여럿이면 소켓도 여럿이고, 그중 하나가 다시
 * 붙을 때마다 전부 비우면 나머지 로봇이 화면에서 사라진다. `origin` 을 안 주면 전부
 * 비우던 옛 동작이다 — 검사와 화면 전환이 그렇게 쓴다.
 */
export function resetDeviceIdentity(origin?: string): void {
  const keys = Object.keys(candidates);
  if (keys.length === 0) return;
  if (origin === undefined) {
    candidates = {};
    notify();
    return;
  }
  const next: Record<string, Candidate> = {};
  for (const [id, candidate] of Object.entries(candidates)) {
    if (candidate.origin !== origin) next[id] = candidate;
  }
  if (Object.keys(next).length === keys.length) return;
  candidates = next;
  notify();
}

/**
 * **그 브로커에서 본 장비 하나.** 2단계(명령 대상을 명시로)가 이 함수를 쓴다 — 명령이
 * 「어느 소켓으로 나가는가」와 「어느 장비에게 가는가」가 같은 답을 내야 하기 때문이다.
 *
 * 애매하면 `null` 인 것은 전역판과 같다 — 한 브로커에 장비가 둘이면 고르지 않는다.
 */
export function deviceIdentityFor(origin: string): DeviceIdentity | null {
  return resolve(Object.values(candidates).filter((c) => c.origin === origin));
}

export function subscribeDeviceIdentity(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/**
 * 장비가 자기를 밝힐 때까지 **잠깐** 기다린다.
 *
 * 붙자마자 확인을 누르면 아직 한 건도 안 와 있다. 그때 「모른다」로 끝내면 발표 직전 점검에서
 * 늘 한 번 더 눌러야 한다 — `waitForRobot` 이 같은 이유로 같은 일을 한다.
 *
 * retained `status` 는 구독 직후에 오므로 보통 한 바퀴 안에 끝난다. 기다려도 안 오면 그대로
 * `null` 이다 — 지어내지 않는다.
 *
 * **기본이 6초인 이유는 Go1 이다.** 드론의 `status` 는 retained 라 즉시 오지만(계약 §3-1),
 * Go1 쪽은 retained 라는 확인이 없고 주기가 5초다. 4초로 두면 **retained 가 아닐 때 첫
 * `ping` 이 거절되고**, 발표 직전 점검에서 한 번 더 눌러야 한다. `waitForRobot` 이 같은
 * 이유로 같은 6초를 쓴다 — 두 기다림의 근거가 같으므로 숫자도 같이 둔다.
 */
export async function awaitDeviceIdentity(timeoutMs = 6000): Promise<DeviceIdentity | null> {
  const found = deviceIdentity();
  if (found !== null) return found;
  return await new Promise<DeviceIdentity | null>((resolve) => {
    let done = false;
    const finish = (value: DeviceIdentity | null) => {
      if (done) return;
      done = true;
      waiters.delete(wake);
      clearTimeout(timer);
      resolve(value);
    };
    const wake = () => {
      const now = deviceIdentity();
      if (now !== null) finish(now);
    };
    const timer = setTimeout(() => finish(deviceIdentity()), timeoutMs);
    waiters.add(wake);
  });
}

const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
