/**
 * src/physical/presets.ts (260910 신설 — 하드웨어 연동 §2 · §3)
 *
 * 브로커 주소 프리셋과, **방향·거리를 정하는 자리.**
 *
 * ## 주소 프리셋
 *
 * 이름(`pi7.local`)이 안 풀릴 때를 대비해 화면에서 고를 수 있게 한다. 발표장에서 mDNS 가
 * 막히는 일은 드물지 않고, 그때 손으로 IP 를 치는 것보다 고르는 편이 빠르다.
 *
 * **발표장 핫스팟 IP 는 아직 없다.** 5GHz 대역·SSID·PW 를 전달했고 정적 IP 가 나오면 채운다.
 * 값을 지어내 넣지 않는다 — 틀린 주소가 들어 있으면 발표장에서 「왜 안 붙지」로 시간을 쓴다.
 * 빈 프리셋으로 두고, 받는 즉시 아래 한 줄만 고치면 되게 해 두었다.
 */

/**
 * **정지 명령의 이름. 상수 한 줄이다.** (`문서/정지명령_규약_260910.md`)
 *
 * 우리가 정의해 하드웨어 쪽에 넘긴 안이고 **받는 쪽이 아직 합의하지 않았다.** 그쪽이 다른
 * 이름을 쓰겠다고 하면 이 줄만 고친다 — 그래서 문자열을 여기 밖에 적지 않는다.
 * 규약의 질문 다섯 중 첫째가 「`abort` 라는 이름으로 괜찮은가」다.
 */
export const STOP_ACTION = 'abort';

/**
 * **일시정지가 쓰는 이름.** `abort` 와 다르다 — 돌던 임무만 접고 다른 쪽(Unity·촬영 도구)이
 * 흘리는 것은 안 건드린다(연동 가이드 §4-2).
 *
 * 규약에 **일시정지도 재개도 없다.** 우리가 할 수 있는 것은 임무를 접는 것뿐이고,
 * 「이어 하기」는 화면이 그 단계를 다시 내는 것으로 흉내 낸다. 이 줄만 고치면 하드웨어가
 * 진짜 일시정지를 주는 날 그리로 갈아탄다.
 */
export const PAUSE_ACTION = 'abort_mission';

/**
 * **구동 브리지 명령의 이름들.** 여기 밖에 문자열을 안 적는 이유는 위와 같다.
 *
 * 브리지(`go1-sdk`)는 평시에 **내려가 있다** — 기동하는 순간 로봇이 일어서기 때문이다
 * (연동 가이드 §4-3). 그래서 「붙어 있다」와 「움직일 수 있다」가 다르고, 그 차이를
 * 화면이 말해야 한다.
 */
export const SDK_ACTIONS = {
  /** 브리지를 띄운다 — **로봇이 일어선다.** 임무 전에 미리 세워 둘 때. */
  start: 'sdk_start',
  /** 브리지를 내린다. 로봇은 **선 채로** 남는다. */
  stop: 'sdk_stop',
  /** 이동 명령이 왔을 때 알아서 띄울지. 끄면 `go1_sdk_not_running` 으로 거절된다. */
  auto: 'sdk_auto',
} as const;

/**
 * 정지 사유 코드. `parameters` 가 `map<string, double>` 이라 문자열을 못 넣어 숫자로 보낸다.
 * **기록용이고 로봇 동작은 값과 무관하게 같아야 한다** — 무엇이든 즉시 멈춘다.
 *
 * **`reason` 말고 다른 파라미터를 더하지 않는다** — 규약 밖으로 나가지 않는다.
 */
export const STOP_REASON = { human: 1, screen: 2, connection: 3 } as const;

export type BrokerPreset = {
  id: string;
  label: string;
  /** 빈 문자열이면 **아직 값이 없다는 뜻**이다. 화면이 고를 수 없게 막는다. */
  url: string;
  why: string;
};

export const BROKER_PRESETS: readonly BrokerPreset[] = [
  { id: 'name', label: '이름', url: 'ws://pi7.local:9001', why: '기본값. mDNS 가 풀리면 이것이 가장 편하다' },
  { id: 'lab', label: '랩 Wi-Fi', url: 'ws://192.168.50.172:9001', why: '고정 IP. 이름이 안 풀릴 때' },
  // ↓ 정적 IP 를 받으면 이 줄의 url 만 채운다.
  { id: 'venue', label: '발표장 핫스팟', url: '', why: '정적 IP 미정 — 받는 즉시 채운다. 지어내 넣지 않는다' },
  { id: 'manual', label: '직접 입력', url: '', why: '사용자가 적는다' },
];

/** 고를 수 있는 프리셋인가. 값이 빈 것은 아직 없는 것이다. */
export function presetReady(preset: BrokerPreset): boolean {
  return preset.id === 'manual' || preset.url.trim() !== '';
}

/**
 * **방향과 거리를 정하는 자리. 여기 하나다.** (§3 「방향과 거리의 출처는 한 곳에」)
 *
 * 지금은 대본의 상수를 내놓는다. 하드웨어 쪽이 `door_turn` 과 `move_forward` 를 우리가
 * 산출한 경로대로 움직이게 바꿀 수 있다고 했고, 그때 **이 함수의 속만 바뀐다.**
 * 명령을 쏘는 코드는 값이 대본에서 왔는지 경로 산출에서 왔는지 몰라야 한다.
 *
 * 2D 맵은 다른 담당이라 이번 범위 밖이다 — 경로 산출이 붙는 자리가 여기라는 것만 남긴다.
 */
export type MissionGeometry = {
  /** 스캔을 몇 등분하는가. 지금은 대본의 여덟. */
  steps: number;
  /** 한 걸음의 각도. **상수로 박지 않는다** — 명령 파라미터이고 로봇도 이 값을 쓴다. */
  stepDeg: number;
  /** 접근 거리(m). 경로 산출이 붙으면 그 결과가 들어온다. */
  forwardDistanceM: number;
  /** 값이 어디서 왔는가 — 화면과 보고서가 이 사실을 적는다. */
  source: 'script' | 'path-planner';
};

/** 대본 `params` 에서 읽는다. 없으면 스캔만 돌린다 — 거리를 지어내지 않는다. */
export function missionGeometry(params: Record<string, unknown> | null | undefined): MissionGeometry {
  const steps = typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8;
  const stepDeg = typeof params?.viewpoint_step_deg === 'number' ? params.viewpoint_step_deg : 360 / steps;
  const forward = typeof params?.forward_distance_m === 'number' ? params.forward_distance_m : 0;
  return { steps, stepDeg, forwardDistanceM: forward, source: 'script' };
}
