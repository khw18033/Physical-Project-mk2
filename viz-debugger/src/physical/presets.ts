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
  /** 접근 거리(m). 경로 산출이 붙으면 그 결과가 들어온다. */
  forwardDistanceM: number;
  /** 값이 어디서 왔는가 — 화면과 보고서가 이 사실을 적는다. */
  source: 'script' | 'path-planner';
};

/** 대본 `params` 에서 읽는다. 없으면 스캔만 돌린다 — 거리를 지어내지 않는다. */
export function missionGeometry(params: Record<string, unknown> | null | undefined): MissionGeometry {
  const steps = typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8;
  const forward = typeof params?.forward_distance_m === 'number' ? params.forward_distance_m : 0;
  return { steps, forwardDistanceM: forward, source: 'script' };
}
