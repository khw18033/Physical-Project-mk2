/**
 * src/fixedcam/fixedCamera.ts (261002 신설 — 고정 카메라 · 360 카메라 연결 준비)
 *
 * **고정 카메라를 아는 유일한 면.** 연결 관리의 「고정 카메라」 목록 칸(`fixed-camera.url`)에 적힌 주소마다 카메라
 * 한 대다. 지금 360 카메라는 **서버 링크 주소로 이미지만** 준다 — 배터리 같은 장비 정보는 아직 없다.
 *
 * ## 「연결됨」은 이미지가 받아지는 것이다
 *
 * 로봇처럼 브로커 — 단말 구조가 아니다. 붙을 소켓도, 물어볼 `ping` 도 없다. 그래서 **그 주소에서 이미지 한 장이
 * 받아지면 연결된 것**으로 본다. 받아질 때마다 연결 장비 저장소에 `camera` 길로 적고(`noteConnectedEntity`),
 * 하드웨어 카드는 그 저장소만 읽는다 — 로봇과 같은 길이다. 안 받아지면 적지 않고, 창(30초)이 지나면 카드가 내려간다.
 *
 * 주기 감시(`startFixedCameraWatch`)가 10초마다 한 장씩 받아 본다. 창이 30초라 두 번 놓쳐도 카드가 안 깜빡인다.
 *
 * ## 장비 id
 *
 * 주소가 아니라 **줄 순서**로 짓는다 — `fixed-cam-1`, `fixed-cam-2` …. 주소를 그대로 id 로 쓰면 카드 · 배정 · 추론
 * 포트 고름이 모두 긴 URL 을 들고 다니고, 주소의 토큰 같은 것이 화면 여기저기에 찍힌다. 줄을 지우면 뒤 줄의 번호가
 * 당겨진다는 대가가 있다 — 카메라가 한두 대인 지금은 그쪽이 싸다.
 *
 * ## 받는 방식
 *
 * 링크가 한 장짜리 JPEG 인지 끝나지 않는 MJPEG 인지 주소만으로는 모른다. 받아 보는 쪽(`<img>`)은 둘 다 첫 장이
 * 그려지면 크기가 생기므로 **연결 판정은 둘을 가르지 않는다.** 보여 줄 때만 가른다 — 주소가 스트림처럼 생겼으면
 * 그대로 띄우고, 아니면 한 장씩 다시 청한다(`feedKindOf`). 상세에서 사람이 바꿀 수 있다.
 */

import { t } from '../i18n/dict.ts';
import { connectionAddress, splitAddressList, subscribeConnections } from '../shared/connections.ts';
import { noteConnectedEntity } from '../shared/connectedDevices.ts';
import { line, type HealthLine } from '../shared/connectionHealth.ts';

export const FIXED_CAMERA_ID_PREFIX = 'fixed-cam-';

/** 감시가 한 장을 받아 보는 주기. 연결 창(30초)의 1/3 이다. */
export const FIXED_CAMERA_WATCH_MS = 10_000;
/** 한 장을 기다리는 한도. 넘기면 「안 받아진다」다. */
export const FIXED_CAMERA_PROBE_TIMEOUT_MS = 6_000;

export type FixedCamera = { entityId: string; url: string };

/** 연결 관리에 적힌 고정 카메라 전부 — 줄 순서대로. */
export function fixedCameras(): readonly FixedCamera[] {
  return splitAddressList(connectionAddress('fixed-camera', 'url'))
    .map((url, index) => ({ entityId: `${FIXED_CAMERA_ID_PREFIX}${index + 1}`, url }));
}

export function isFixedCamera(entityId: string): boolean {
  return entityId.startsWith(FIXED_CAMERA_ID_PREFIX);
}

/** 그 카메라의 이미지 주소. 고정 카메라가 아니거나 줄이 없으면 null. */
export function fixedCameraUrl(entityId: string): string | null {
  return fixedCameras().find((camera) => camera.entityId === entityId)?.url ?? null;
}

/** 주소의 호스트 — 추론 소스 맞추기의 재료(`vision/binding.ts`). 주소가 아니면 null. */
export function fixedCameraHost(entityId: string): string | null {
  const url = fixedCameraUrl(entityId);
  if (url === null) return null;
  try {
    const host = new URL(url).hostname;
    return host === '' ? null : host;
  } catch {
    return null;
  }
}

/** 주소의 `스킴://호스트:포트` — 추론 서버의 한 포트와 **같은 주소**인지 맞대 보는 데 쓴다. 주소가 아니면 null. */
export function fixedCameraOrigin(entityId: string): string | null {
  const url = fixedCameraUrl(entityId);
  if (url === null) return null;
  try {
    const parsed = new URL(url);
    return parsed.hostname === '' ? null : `${parsed.protocol}//${parsed.host}`;
  } catch {
    return null;
  }
}

export type FeedKind = 'stream' | 'frames';

/**
 * 보여 줄 때의 기본 방식. 경로가 스트림처럼 생겼으면(`/stream` · `mjpeg` · `mjpg` · `video`) 끝나지 않는 MJPEG 로 보고
 * 그대로 띄운다. 아니면 한 장짜리로 보고 한 장씩 다시 청한다 — 한 장짜리를 그대로 띄우면 첫 장에서 멈춘다.
 */
export function feedKindOf(url: string): FeedKind {
  let path = url;
  try { path = new URL(url).pathname; } catch { /* 주소가 아니면 글자 그대로 본다 */ }
  return /stream|mjpe?g|video/i.test(path) ? 'stream' : 'frames';
}

/** 같은 주소를 캐시로 받지 않게 차례 번호를 붙인다 — 캐시된 한 장으로 「연결됨」이라고 하면 꺼진 카메라가 살아 보인다. */
export function withNonce(url: string, nonce: number | string): string {
  return `${url}${url.includes('?') ? '&' : '?'}n=${nonce}`;
}

export type ImageProbeResult = { ok: true; ms: number; width: number; height: number } | { ok: false; reason: string };
export type ImageProbe = (url: string, timeoutMs: number) => Promise<ImageProbeResult>;

/**
 * **한 장을 받아 본다** — `<img>` 로. 다른 출처여도 그리는 것은 되므로 CORS 가 필요 없다.
 *
 * MJPEG 면 `load` 가 안 올 수 있어 크기(`naturalWidth`)를 주기로 본다. 받으면 곧바로 주소를 비워 연결을 닫는다 —
 * 그때 브라우저가 `error` 를 내므로 귀를 먼저 뗀다(`DirectCamera` 와 같은 사정).
 */
export const probeImage: ImageProbe = (url, timeoutMs) => new Promise((resolve) => {
  if (typeof Image === 'undefined') { resolve({ ok: false, reason: t('fcam.noBrowser') }); return; }
  const image = new Image();
  const startedAt = Date.now();
  let done = false;
  const finish = (result: ImageProbeResult) => {
    if (done) return;
    done = true;
    clearInterval(timer);
    image.onerror = null;
    image.onload = null;
    image.src = '';
    resolve(result);
  };
  const painted = () => {
    if (image.naturalWidth > 0) finish({ ok: true, ms: Date.now() - startedAt, width: image.naturalWidth, height: image.naturalHeight });
  };
  const timer = setInterval(() => {
    painted();
    if (Date.now() - startedAt > timeoutMs) finish({ ok: false, reason: t('fcam.timeout', { sec: timeoutMs / 1000 }) });
  }, 200);
  image.onload = painted;
  image.onerror = () => finish({ ok: false, reason: t('fcam.notImage') });
  image.src = withNonce(url, Date.now());
});

/** 카메라 하나를 받아 보고, 받아지면 연결 장비로 적는다. */
async function probeOne(camera: FixedCamera, probe: ImageProbe): Promise<ImageProbeResult> {
  const result = await probe(camera.url, FIXED_CAMERA_PROBE_TIMEOUT_MS);
  if (result.ok) noteConnectedEntity(camera.entityId, 'camera');
  return result;
}

/**
 * 연결 관리의 「확인」. **카메라마다 한 줄** — 하나가 안 받아져도 나머지는 그대로 보인다.
 * 주소가 없으면 「모른다」다. 빨갛게 칠하면 「카메라가 죽었다」가 되는데, 아직 주소를 안 넣은 것뿐이다.
 */
export async function checkFixedCameras(probe: ImageProbe = probeImage): Promise<readonly HealthLine[]> {
  const cameras = fixedCameras();
  if (cameras.length === 0) return [line('image', 'check.line.image', null, { reason: t('fcam.noAddress') })];
  const out: HealthLine[] = [];
  for (const camera of cameras) {
    const result = await probeOne(camera, probe);
    const row = result.ok
      ? line('image', 'check.line.image', true, { roundTripMs: result.ms, reason: t('fcam.imageOk', { id: camera.entityId, w: result.width, h: result.height }) })
      : line('image', 'check.line.image', false, { reason: result.reason });
    out.push(cameras.length > 1 ? { ...row, id: `image@${camera.url}`, scope: camera.entityId } : row);
  }
  return out;
}

/**
 * **주기 감시.** 적힌 카메라를 10초마다 한 장씩 받아 본다. 주소가 바뀌면 곧바로 한 번 더 받는다 — 연결 관리에서
 * 주소를 넣고 닫은 뒤 10초를 기다리게 하지 않는다. 같은 주소의 앞 요청이 아직 안 끝났으면 거른다(쌓이지 않게).
 */
export function startFixedCameraWatch(probe: ImageProbe = probeImage, intervalMs = FIXED_CAMERA_WATCH_MS): () => void {
  const inFlight = new Set<string>();
  const tick = () => {
    for (const camera of fixedCameras()) {
      const key = `${camera.entityId}|${camera.url}`;
      if (inFlight.has(key)) continue;
      inFlight.add(key);
      void probeOne(camera, probe).finally(() => inFlight.delete(key));
    }
  };
  let lastUrls = connectionAddress('fixed-camera', 'url');
  const unsubscribe = subscribeConnections(() => {
    const now = connectionAddress('fixed-camera', 'url');
    if (now === lastUrls) return;
    lastUrls = now;
    tick();
  });
  tick();
  const timer = setInterval(tick, intervalMs);
  return () => { clearInterval(timer); unsubscribe(); };
}
