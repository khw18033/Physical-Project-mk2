/**
 * src/detect/scan/scanAddress.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S1)
 *
 * **이 장치의 스캔 창구는 어디인가.** 창구는 data_stream 소스 서버에 붙으므로(결정 12) 그 장치의
 * **추론 스트림 포트**가 곧 창구다. 장치 → 포트는 이미 있다 — 연결 관리 「추론 스트림」의 IP 칸 + 포트 줄과,
 * 하드웨어 카드 상세에서 고르는 포트 묶음(`vision/binding.ts`). 표를 하나 더 두면 둘이 갈라진다.
 *
 * 못 정하면(묶음 없음 · 둘 이상) null — 아무 포트나 붙이면 다른 로봇의 영상으로 스캔한다.
 */

import { deviceBrokerHost, deviceDirectBase, resolveVisionBinding, visionBindingChoice, type VisionBinding } from '../../vision/binding.ts';
import { visionBases } from '../../vision/visionClient.ts';
import { visionSources } from '../../vision/store.ts';

export function scanBindingFor(entityId: string): VisionBinding {
  return resolveVisionBinding(visionBindingChoice(entityId), deviceBrokerHost(entityId), visionSources(), visionBases(), deviceDirectBase(entityId));
}

/** 그 장치의 창구 주소. 못 정하면 null. */
export function scanBaseFor(entityId: string): string | null {
  return scanBindingFor(entityId).base;
}
