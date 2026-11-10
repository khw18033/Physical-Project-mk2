/**
 * src/physical/cameraView.ts (260928 신설 — 카메라 노드 · Go1 카메라 직접 보기)
 *
 * **로봇 노드(pi7)의 Go1 카메라 뷰어에서 바로 받는 주소.**
 *
 * 카메라 노드는 백엔드 `/media` 로 영상을 받는다. 그런데 실물 Go1 영상이 그 길로 오려면 누군가 `stream_start` 를
 * 보내고 → 엣지가 받아 → 서버에 올려야 하는데, 그 배선이 백엔드의 Phase 6 이라 **실물 영상이 그 길로 온 적이 없다**
 * (260928 pi7 실측 — 명령·상태는 되는데 카메라만 안 왔다).
 *
 * 그 사이 영상은 pi7 에 이미 있다 — HW 의 `go1-camview`(`bench/go1_cam_view.py`, 8090)가 Go1 안 카메라 5대를
 * 중계하고, `/stream/<번호>` 가 `<img>` 로 바로 받는 MJPEG 다(실측 약 30 fps). 그래서 **장비가 붙어 있는 브로커의
 * 호스트**에서 그 주소를 만든다. 주소를 아는 면은 이 폴더 하나라(`verify:physical-port`) 여기서 만든다.
 *
 * 이 뷰어는 HW 가 「운영 구성요소가 아니다 — 말단에서 영상이 나오는가를 사람이 보는 도구」라고 적은 것이다.
 * `/media` 경로가 열리면 그쪽이 본선이고, 이것은 그때까지의 길이다. 화면은 어느 길로 보는지 적는다.
 */

import { useEffect, useSyncExternalStore } from 'react';
import { clientForDevice } from './robotClient.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';

/** HW `go1-camview.service` 의 포트. 바뀌면 여기 한 곳만 고친다. */
export const GO1_CAMVIEW_PORT = 8090;

/**
 * pi3 **영상 말단**(`drone_rpi` · `drone-agent.service`)의 포트 (260928). 엣지가 당겨 가는 창구이고, 한 번에
 * 메타 + JPEG 한 장을 multipart 로 준다. 브라우저가 그 형식도 CORS 도 못 넘으므로 개발 서버 중계
 * (`scripts/drone-cam-relay.mjs`)를 거친다.
 */
export const DRONE_AGENT_PORT = 8890;

/**
 * 받는 방식. Go1 뷰어는 끝나지 않는 MJPEG(`stream`)이고, 드론 말단은 한 번에 한 장(`frames`)이라 화면이 이어서 당긴다.
 * 모양은 `media/views/DeviceCamera.tsx` 의 `DirectSource` 와 같다 — 그쪽이 이 파일을 import 하지 않게 모양으로만 맞춘다.
 */
export type DirectCameraSource = { url: string; kind: 'stream' | 'frames' };

/** 카메라 위치 → 뷰어의 카메라 번호 (`robot/go1_camera.py` 의 `CAMS`). */
const GO1_CAMERA_INDEX: Readonly<Record<string, number>> = { front: 1, chin: 2, left: 3, right: 4, belly: 5 };

/**
 * 그 장비의 그 카메라를 직접 보는 주소. **못 만들면 null** — 그러면 카메라 노드는 `/media` 로 간다.
 *
 * 어느 길인지는 장비가 밝힌 것으로 가른다 — Go1(`go1_robot`)은 pi7 의 Go1 뷰어, 드론(`drone`)은 pi3 의 영상 말단.
 * 둘 다 아니면 null 이고, 그 장비는 `/media` 로 간다. 주소를 지어 붙이면 「영상이 안 온다」의 원인을 엉뚱한 데서 찾게 된다.
 */
export function directCameraUrl(deviceId: string, position: string): DirectCameraSource | null {
  const client = clientForDevice(deviceId);
  if (client === null) return null;
  const identity = deviceIdentityFor(client.address());
  let host: string;
  try {
    host = new URL(client.address()).hostname;
  } catch {
    return null;
  }
  if (host === '') return null;
  if (identity?.deviceType === 'go1_robot') {
    const index = GO1_CAMERA_INDEX[position];
    return index === undefined ? null : { url: `http://${host}:${GO1_CAMVIEW_PORT}/stream/${index}`, kind: 'stream' };
  }
  /**
   * **드론은 기체에 실린 pi3 의 카메라 모듈이다** (260928 지시 — 「pi3 의 카메라 말단 노드를 활용」). 위치 칸은 뜻이
   * 없다 — 이 함수는 늘 0번을 준다. 카메라가 둘 이상 붙은 것은 `useDirectCameraSources` 가 본다(261019).
   * 말단은 브로커와 같은 호스트에 있다.
   */
  if (identity?.kind === 'drone') return { url: droneFrameUrl(`http://${host}:${DRONE_AGENT_PORT}`, 0), kind: 'frames' };
  return null;
}

function droneFrameUrl(base: string, cam: number): string {
  return `/drone-cam/frame?base=${encodeURIComponent(base)}&cam=${cam}`;
}

/** 드론이면 그 영상 말단의 주소(`http://host:8890`), 아니면 null. */
function droneAgentBase(deviceId: string): string | null {
  const client = clientForDevice(deviceId);
  if (client === null || deviceIdentityFor(client.address())?.kind !== 'drone') return null;
  try {
    const host = new URL(client.address()).hostname;
    return host === '' ? null : `http://${host}:${DRONE_AGENT_PORT}`;
  } catch {
    return null;
  }
}

// ── 드론 카메라 여러 대 (261019) ───────────────────────────────────────────────
//
// 말단은 `config.json` 의 `pi.cameras` 에 적힌 만큼 카메라를 열고, 한 장이라도 낸 번호를 `/api/health` 의 `cameras` 로
// 알린다. cam0 · cam1 이 둘 다 붙어 있으면 `[0, 1]` 이다. 화면은 그 목록대로 칸을 세운다 — 번호를 지어 붙이지 않는다.
// 목록을 아직 모르거나 못 읽으면 0번 한 대로 본다(지금까지의 동작). 그러면 「못 붙었다」가 0번 칸에 그대로 적힌다.

/** 카메라 한 대의 길과, 여럿일 때 칸에 붙일 이름(`cam1`). 한 대면 이름이 없다. */
export type LabeledCameraSource = DirectCameraSource & { label: string | null };

/** 카메라 목록을 다시 읽는 간격. 카메라가 빠지거나 다시 붙는 것을 이 안에 따라간다. */
const DRONE_CAMERA_POLL_MS = 5000;

const droneCameras = new Map<string, number[]>();
const droneWatchers = new Map<string, { count: number; timer: ReturnType<typeof setInterval> }>();
const listeners = new Set<() => void>();
let version = 0;

function sameList(a: readonly number[] | undefined, b: readonly number[]): boolean {
  return a !== undefined && a.length === b.length && a.every((value, index) => value === b[index]);
}

async function readDroneCameras(base: string): Promise<void> {
  try {
    const response = await fetch(`/drone-cam/health?base=${encodeURIComponent(base)}`, { cache: 'no-store' });
    if (!response.ok) return;
    const body = await response.json() as { cameras?: unknown };
    if (!Array.isArray(body.cameras)) return;
    const cams = body.cameras.filter((cam): cam is number => Number.isInteger(cam)).sort((a, b) => a - b);
    if (sameList(droneCameras.get(base), cams)) return;
    droneCameras.set(base, cams);
    version += 1;
    for (const listener of listeners) listener();
  } catch {
    // 말단이 꺼졌다 — 아는 목록을 그대로 둔다. 영상 칸이 실패를 적는다.
  }
}

/** 보는 칸이 하나라도 있는 동안만 목록을 읽는다. 마지막 칸이 닫히면 멈춘다. */
function watchDroneCameras(base: string): () => void {
  const watcher = droneWatchers.get(base);
  if (watcher !== undefined) watcher.count += 1;
  else {
    void readDroneCameras(base);
    droneWatchers.set(base, { count: 1, timer: setInterval(() => { void readDroneCameras(base); }, DRONE_CAMERA_POLL_MS) });
  }
  return () => {
    const current = droneWatchers.get(base);
    if (current === undefined) return;
    current.count -= 1;
    if (current.count > 0) return;
    clearInterval(current.timer);
    droneWatchers.delete(base);
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 그 장비에서 바로 보는 카메라 전부. 드론은 말단이 알린 번호마다 한 칸, 그 밖은 `directCameraUrl` 한 칸(없으면 빈 배열). */
export function directCameraSources(deviceId: string, position: string): LabeledCameraSource[] {
  const one = directCameraUrl(deviceId, position);
  if (one === null) return [];
  const base = droneAgentBase(deviceId);
  const cams = base === null ? [] : droneCameras.get(base) ?? [];
  if (base === null || cams.length === 0) return [{ ...one, label: null }];
  return cams.map((cam) => ({ url: droneFrameUrl(base, cam), kind: 'frames', label: cams.length > 1 ? `cam${cam}` : null }));
}

/**
 * **장비 여럿을 한꺼번에** (261110 — 전체 장치 확인). 영상 칸을 장비가 아니라 영상마다 세려면 장비 전부의 카메라 목록이
 * 한 자리에 있어야 한다. 훅을 장비마다 부를 수 없으니(개수가 바뀐다) 드론 말단 지켜보기를 효과 하나에서 묶어 건다.
 */
export function useDirectCameraSourcesMany(deviceIds: readonly string[], positions: Readonly<Record<string, string>>): Record<string, LabeledCameraSource[]> {
  const bases = [...new Set(deviceIds.map(droneAgentBase).filter((base): base is string => base !== null))].sort();
  const key = bases.join('|');
  useEffect(() => {
    const stops = key === '' ? [] : key.split('|').map(watchDroneCameras);
    return () => { for (const stop of stops) stop(); };
  }, [key]);
  useSyncExternalStore(subscribe, () => version, () => version);
  const out: Record<string, LabeledCameraSource[]> = {};
  for (const id of deviceIds) out[id] = directCameraSources(id, positions[id] ?? 'front');
  return out;
}

/** `directCameraSources` 를 화면에서 — 드론이면 보는 동안 말단의 카메라 목록을 따라간다. */
export function useDirectCameraSources(deviceId: string | null, position: string): LabeledCameraSource[] {
  const base = deviceId === null ? null : droneAgentBase(deviceId);
  useEffect(() => (base === null ? undefined : watchDroneCameras(base)), [base]);
  useSyncExternalStore(subscribe, () => version, () => version);
  return deviceId === null ? [] : directCameraSources(deviceId, position);
}
