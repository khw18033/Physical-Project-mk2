/**
 * src/physical/robotFacts.ts (260910 신설)
 *
 * **장비 상태 → 연결 관리가 읽는 몇 줄.**
 *
 * `connectionCheck.ts` 는 토픽도 장비 id 도 모른다(`verify:physical-port`). 그쪽이 쓰는
 * 모양으로 바꿔 주는 자리가 여기다 — 경계 안이다.
 */

import { deviceState, isStale } from './deviceState.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';
import { hardwareTarget } from './encode.ts';
import type { RobotFacts } from '../shared/connectionCheck.ts';

/**
 * 우리 로봇의 지금. 아무것도 안 왔으면 null — 지어내지 않는다.
 *
 * **브로커 주소를 주면 그 브로커의 장비다** (261117). 브로커가 여럿이면 연결 관리가 줄마다 이것을 부른다 — 전에는
 * 주소를 안 받아 모든 브로커의 로봇 줄이 같은 한 대(기본 `go1-001`)로 칠해졌다. 그 브로커에서 자기를 밝힌 장비가
 * 없으면 `null`(모른다)이다.
 */
export function robotFacts(address?: string): RobotFacts | null {
  const id = address === undefined ? hardwareTarget('robot-01') : deviceIdentityFor(address)?.deviceId ?? null;
  if (id === null) return null;
  const device = deviceState(id);
  if (device === null) return null;
  const stale = isStale(device);
  return {
    online: device.online,
    link: device.link,
    health: device.health,
    batteryPct: device.batteryPct,
    stale,
    staleSec: Math.round((Date.now() - device.lastSeenMs) / 1000),
  };
}
