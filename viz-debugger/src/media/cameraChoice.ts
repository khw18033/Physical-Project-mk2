/**
 * src/media/cameraChoice.ts (260927 신설 — 카메라 뷰 노드)
 *
 * **카메라 노드 한 장이 고른 장치와 카메라 위치.** 노드마다 따로다 — 「첫 번째 장치 카메라」와
 * 「두 번째 장치 카메라」는 같은 종류의 노드 두 장이고, 다른 것은 이 고름뿐이다.
 *
 * 캔버스 구성(`canvas/persist.ts`)에 넣지 않는 이유: 그 형식은 캔버스 계약이고 판(`version`)이 걸려
 * 있다. 칸 하나 때문에 판을 올리면 사람이 짜 둔 배치가 전부 버려진다. 노드 id 로 따로 들고, 노드를
 * 지우면 이 줄은 그냥 안 읽힌다.
 *
 * 카메라 키는 `<장치 id>_<위치>` 다(`vz-media-interface.md` §12 — 예 `go1-001_front`). 위치 어휘는
 * HW `capture_upload.py` 의 것을 그대로 쓴다. 장치 목록이 레지스트리로 오기 전까지는 이 규약으로 짓는다.
 */

import { useSyncExternalStore } from 'react';

export const CAMERA_POSITIONS = ['front', 'chin', 'left', 'right', 'belly'] as const;
export type CameraPosition = (typeof CAMERA_POSITIONS)[number];

export type CameraChoice = { deviceId: string | null; position: CameraPosition };

const STORAGE_KEY = 'viz.cameraChoice.v1';
const DEFAULT: CameraChoice = { deviceId: null, position: 'front' };

function read(): Record<string, CameraChoice> {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, CameraChoice> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      const v = value as Partial<CameraChoice> | null;
      if (v === null || typeof v !== 'object') continue;
      const position = CAMERA_POSITIONS.includes(v.position as CameraPosition) ? v.position as CameraPosition : 'front';
      out[id] = { deviceId: typeof v.deviceId === 'string' && v.deviceId !== '' ? v.deviceId : null, position };
    }
    return out;
  } catch {
    // 저장소가 막혔거나 깨졌다 — 고르지 않은 것으로 진행한다. 여기서 던지면 캔버스가 멎는다.
    return {};
  }
}

let choices: Record<string, CameraChoice> = read();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function cameraChoice(nodeId: string): CameraChoice {
  return choices[nodeId] ?? DEFAULT;
}

export function useCameraChoice(nodeId: string): CameraChoice {
  return useSyncExternalStore(subscribe, () => cameraChoice(nodeId), () => cameraChoice(nodeId));
}

export function setCameraChoice(nodeId: string, next: Partial<CameraChoice>): void {
  choices = { ...choices, [nodeId]: { ...cameraChoice(nodeId), ...next } };
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(choices));
  } catch {
    // 이번 세션에만 남는다. 캔버스 저장이 막혔을 때와 같은 규칙이다.
  }
  for (const listener of listeners) listener();
}

/** 카메라 키. 장치가 없으면 null — 지어 붙일 대상이 없다. */
export function cameraKeyOf(choice: CameraChoice, fallbackDevice: string | null): string | null {
  const device = choice.deviceId ?? fallbackDevice;
  return device === null ? null : `${device}_${choice.position}`;
}
