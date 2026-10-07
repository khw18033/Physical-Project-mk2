/**
 * src/record/screenRecord.ts (261007 신설 — 실시간 화면 녹화)
 *
 * **지금 눈으로 보고 있는 영상 칸을 그대로 녹화한다.** 목적은 「실시간으로 본 것을 나중에 다시 확인」이다(261007 지시).
 *
 * ## 왜 영상 요소를 바로 녹화하지 않나
 *
 * 카메라 · 추론 · Unity 상공 카메라는 다른 주소의 MJPEG 를 `<img>` 로 띄운다. 그런 그림을 캔버스에 옮기면 브라우저가
 * 그 캔버스의 녹화를 막는다(다른 출처). 3D 가상환경은 틀(iframe)이라 아예 꺼낼 수 없다. 그래서 **탭 화면을 찍고**
 * (`getDisplayMedia` · 이 탭) 그중 영상 칸만 남긴다 — 눈에 보이는 픽셀 그대로이고, 영상을 한 번 더 받지 않으므로 원본
 * 장비와 망에는 부담이 없다.
 *
 *   남기는 법   `restrictTo`(요소 캡처) 가 있으면 그것 — 그 요소만 찍혀 위에 얹힌 녹화 버튼 · 알림이 안 찍힌다.
 *               없으면 `cropTo`(영역 캡처) — 그 칸의 네모만큼 자른다. 위에 얹힌 것도 같이 찍힌다.
 *   확인 창     Chrome 이 「이 탭 공유」를 묻는다. 웹 페이지가 끌 수 없다 — 그대로 띄운다(261007 결정).
 *               공유는 녹화가 하나라도 도는 동안 한 벌을 같이 쓰고, 다 멈추면 놓는다(공유 중 표시줄이 사라진다).
 *               그래서 동시에 여럿을 녹화하면 확인은 처음 한 번이다.
 *   저장        1초 조각을 개발 서버 창구로 보내 저장소 루트 `video/` 에 이어 쓴다(`scripts/video-records.mjs`).
 *   닫으면      녹화 버튼이 내려가면(창을 닫음) 그 녹화를 멈추고 저장한다(261007 결정). Chrome 의 「공유 중지」를
 *               누르면 도는 녹화가 전부 멈추고 저장된다.
 *
 * Chrome 전용이다(사용자 환경 · 261007). 요소 캡처 · 영역 캡처가 둘 다 없는 브라우저면 버튼이 사유를 적는다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';

const SAVE_URL = '/video-records';
const SLICE_MS = 1000;
const BITS_PER_SECOND = 4_000_000;
/** 끝난 녹화를 알림에 남겨 두는 시간 — 저장된 경로를 읽을 틈. 실패는 사람이 닫을 때까지 둔다. */
const SAVED_SHOWN_MS = 8000;

export type RecordingPhase = 'starting' | 'recording' | 'saving' | 'saved' | 'failed';

export type Recording = {
  id: string;
  label: string;
  phase: RecordingPhase;
  startedAtMs: number;
  bytes: number;
  /** 저장소 루트 기준 경로(`video/…`). 저장이 끝나야 생긴다. */
  path: string | null;
  error: string | null;
};

type Live = {
  recorder: MediaRecorder | null;
  track: MediaStreamTrack | null;
  saveId: string | null;
  chain: Promise<void>;
};

let recordings: readonly Recording[] = [];
const live = new Map<string, Live>();
const listeners = new Set<() => void>();
let serial = 0;

function emit(): void {
  for (const listener of listeners) listener();
}

function patch(id: string, change: Partial<Recording>): void {
  recordings = recordings.map((item) => (item.id === id ? { ...item, ...change } : item));
  emit();
}

function drop(id: string): void {
  recordings = recordings.filter((item) => item.id !== id);
  emit();
}

export function subscribeRecordings(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

const snapshot = () => recordings;

export function useRecordings(): readonly Recording[] {
  return useSyncExternalStore(subscribeRecordings, snapshot, snapshot);
}

/** 지금 도는(멈추는 중 포함) 녹화인가. */
export function isActive(item: Recording): boolean {
  return item.phase === 'starting' || item.phase === 'recording' || item.phase === 'saving';
}

export function dismissRecording(id: string): void {
  if (!live.has(id)) drop(id);
}

// ── 브라우저가 해 주는 것 ──────────────────────────────────────────────

type ElementTarget = { fromElement(element: Element): Promise<unknown> };
type TrackWith = MediaStreamTrack & { restrictTo?(target: unknown): Promise<void>; cropTo?(target: unknown): Promise<void> };

function targetApi(): { kind: 'restrict' | 'crop'; api: ElementTarget } | null {
  const scope = globalThis as unknown as { RestrictionTarget?: ElementTarget; CropTarget?: ElementTarget };
  if (scope.RestrictionTarget !== undefined) return { kind: 'restrict', api: scope.RestrictionTarget };
  if (scope.CropTarget !== undefined) return { kind: 'crop', api: scope.CropTarget };
  return null;
}

/** 이 브라우저에서 녹화가 안 되면 그 사유(사전 키), 되면 null. */
export function unsupportedReason(): string | null {
  if (typeof navigator === 'undefined' || navigator.mediaDevices?.getDisplayMedia === undefined) return 'rec.noCapture';
  if (typeof MediaRecorder === 'undefined') return 'rec.noRecorder';
  if (targetApi() === null) return 'rec.noElementCapture';
  return null;
}

/** 크롬이 되는 것부터 고른다. mp4(H.264) 가 되면 mp4, 아니면 webm. */
function pickFormat(): { mimeType: string; ext: 'mp4' | 'webm' } {
  const candidates: Array<[string, 'mp4' | 'webm']> = [
    ['video/mp4;codecs=avc1.42E01F', 'mp4'],
    ['video/mp4;codecs=avc1', 'mp4'],
    ['video/mp4', 'mp4'],
    ['video/webm;codecs=vp9', 'webm'],
    ['video/webm;codecs=vp8', 'webm'],
    ['video/webm', 'webm'],
  ];
  for (const [mimeType, ext] of candidates) if (MediaRecorder.isTypeSupported(mimeType)) return { mimeType, ext };
  return { mimeType: '', ext: 'webm' };
}

/**
 * **탭 공유 한 벌.** 녹화가 여럿이어도 공유는 하나다 — 녹화마다 이것을 복제(`clone`)해 각자 다른 칸으로 남긴다.
 * 확인 창이 떠 있는 동안 버튼을 또 누르면 같은 약속을 기다린다(창이 둘 뜨지 않게).
 */
let shared: MediaStream | null = null;
let asking: Promise<MediaStream> | null = null;

function shareTab(): Promise<MediaStream> {
  if (shared !== null && shared.getVideoTracks().some((track) => track.readyState === 'live')) return Promise.resolve(shared);
  if (asking !== null) return asking;
  const options = {
    video: { frameRate: 30, displaySurface: 'browser' },
    audio: false,
    // 이 탭을 먼저 내민다 — 다른 탭 · 창을 고르면 칸을 잘라낼 수 없다.
    preferCurrentTab: true,
    selfBrowserSurface: 'include',
    surfaceSwitching: 'exclude',
    monitorTypeSurfaces: 'exclude',
  } as unknown as DisplayMediaStreamOptions;
  asking = navigator.mediaDevices.getDisplayMedia(options).then((stream) => {
    shared = stream;
    // Chrome 의 「공유 중지」 — 도는 녹화를 전부 멈추고 저장한다.
    stream.getVideoTracks()[0]?.addEventListener('ended', () => {
      shared = null;
      for (const id of [...live.keys()]) void stopRecording(id);
    });
    return stream;
  }).finally(() => { asking = null; });
  return asking;
}

/** 도는 녹화가 없으면 공유를 놓는다 — 공유 중 표시줄이 남아 있으면 「아직 찍고 있나」로 읽힌다. */
function releaseIfIdle(): void {
  if (live.size > 0 || shared === null) return;
  for (const track of shared.getTracks()) track.stop();
  shared = null;
}

async function post(path: string, body?: BodyInit, json = false): Promise<Record<string, unknown>> {
  const response = await fetch(`${SAVE_URL}/${path}`, {
    method: 'POST',
    body,
    headers: json ? { 'Content-Type': 'application/json' } : { 'Content-Type': 'application/octet-stream' },
  });
  const data = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : `HTTP ${response.status}`);
  return data;
}

/** 저장 창구가 있는가 — 단독 빌드 · 정적 서버에는 없다. 한 번만 묻는다. */
let saverCheck: Promise<boolean> | null = null;
export function saverAvailable(): Promise<boolean> {
  saverCheck ??= fetch(`${SAVE_URL}/ping`, { cache: 'no-store' })
    .then(async (response) => response.ok && (await response.json().catch(() => null))?.ok === true)
    .catch(() => false);
  return saverCheck;
}

function errorText(error: unknown): string {
  if (error instanceof DOMException && error.name === 'NotAllowedError') return t('rec.denied');
  return error instanceof Error ? error.message : String(error);
}

/**
 * 그 요소를 녹화하기 시작한다. **버튼 누름 안에서 곧바로 불러야 한다** — 확인 창은 사람이 누른 직후에만 뜬다.
 * 돌려주는 id 로 멈춘다.
 */
export function startRecording(element: Element, label: string): string {
  serial += 1;
  const id = `rec-${Date.now().toString(36)}-${serial}`;
  recordings = [...recordings, { id, label, phase: 'starting', startedAtMs: Date.now(), bytes: 0, path: null, error: null }];
  const state: Live = { recorder: null, track: null, saveId: null, chain: Promise.resolve() };
  live.set(id, state);
  emit();

  const fail = (error: unknown) => {
    state.track?.stop();
    live.delete(id);
    patch(id, { phase: 'failed', error: errorText(error) });
    releaseIfIdle();
  };

  const target = targetApi();
  if (target === null) { fail(new Error(t('rec.noElementCapture'))); return id; }
  // 확인 창을 먼저 띄운다 — 누름 직후여야 뜬다. 저장 창구 확인 · 요소 표지는 그 뒤에 한다.
  const sharing = shareTab();
  void (async () => {
    try {
      const marker = await target.api.fromElement(element);
      const stream = await sharing;
      // 확인 창을 기다리는 사이에 창을 닫았다 — 방금 받은 공유를 쓸 녹화가 없으면 놓는다(공유 중 표시줄이 남지 않게).
      if (!live.has(id)) { releaseIfIdle(); return; }
      const base = stream.getVideoTracks()[0];
      if (base === undefined) throw new Error(t('rec.noTrack'));
      const surface = (base.getSettings() as { displaySurface?: string }).displaySurface;
      if (surface !== undefined && surface !== 'browser') throw new Error(t('rec.notThisTab'));
      const track = base.clone() as TrackWith;
      state.track = track;
      try {
        if (target.kind === 'restrict') await track.restrictTo!(marker);
        else await track.cropTo!(marker);
      } catch {
        // 다른 탭을 골랐으면 여기서 거절된다 — 잘라낼 칸이 그 탭에 없다.
        throw new Error(t('rec.notThisTab'));
      }
      const opened = await post('open', JSON.stringify({ label, ext: pickFormat().ext }), true);
      state.saveId = String(opened.id);
      if (!live.has(id)) { track.stop(); await post(`close?id=${encodeURIComponent(state.saveId)}`); drop(id); releaseIfIdle(); return; }
      const format = pickFormat();
      const recorder = new MediaRecorder(new MediaStream([track]), {
        ...(format.mimeType === '' ? {} : { mimeType: format.mimeType }),
        videoBitsPerSecond: BITS_PER_SECOND,
      });
      state.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size === 0 || state.saveId === null) return;
        const saveId = state.saveId;
        // 조각은 **차례대로** 붙여야 한다 — 앞 조각이 끝난 뒤에 다음을 보낸다.
        state.chain = state.chain.then(async () => {
          const result = await post(`append?id=${encodeURIComponent(saveId)}`, event.data);
          patch(id, { bytes: Number(result.bytes) || 0 });
        }).catch((error) => { patch(id, { error: errorText(error) }); });
      };
      // 칸이 사라져 트랙이 끝나면(요소가 지워짐) 저장으로 넘어간다.
      track.addEventListener('ended', () => { void stopRecording(id); });
      recorder.start(SLICE_MS);
      patch(id, { phase: 'recording', startedAtMs: Date.now(), path: String(opened.path ?? '') || null });
    } catch (error) {
      fail(error);
    }
  })();
  return id;
}

/** 멈추고 저장한다. 이미 멈췄거나 없는 녹화면 아무것도 안 한다. */
export async function stopRecording(id: string): Promise<void> {
  const state = live.get(id);
  if (state === undefined) return;
  live.delete(id);
  const recorder = state.recorder;
  if (recorder === null) {
    // 아직 확인 창 · 준비 중이었다 — 찍은 것이 없다.
    state.track?.stop();
    drop(id);
    releaseIfIdle();
    return;
  }
  patch(id, { phase: 'saving' });
  if (recorder.state !== 'inactive') {
    await new Promise<void>((resolve) => {
      recorder.addEventListener('stop', () => resolve(), { once: true });
      recorder.stop();
    });
  }
  state.track?.stop();
  releaseIfIdle();
  try {
    await state.chain;
    const closed = await post(`close?id=${encodeURIComponent(state.saveId ?? '')}`);
    if (closed.path === null) throw new Error(t('rec.empty'));
    patch(id, { phase: 'saved', path: String(closed.path), bytes: Number(closed.bytes) || 0 });
    setTimeout(() => drop(id), SAVED_SHOWN_MS);
  } catch (error) {
    patch(id, { phase: 'failed', error: errorText(error) });
  }
}
