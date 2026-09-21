/**
 * src/media/store.ts (260921 신설 — `/media` 수신 경로)
 *
 * **영상 소켓 한 벌의 상태.** `src/capability/store.ts` 와 같은 자리·같은 모양이다.
 *
 * ## 픽셀은 여기 없다
 *
 * 들고 있는 것은 **세어야 하는 것과 적어야 하는 것**뿐이다 — 받은 수·버린 수·마지막 헤더·
 * 끊김 사유. 디코드된 그림은 `decode.ts` 가 들고 있고 화면이 rAF 로 가져간다.
 * 그림을 이 저장소에 넣으면 프레임마다 구독자가 깨어나고, 그러면 30Hz 리렌더가 된다.
 *
 * ## 버린 것을 전부 센다
 *
 * 이 경로의 가장 나쁜 실패는 **「연결됨인데 영상만 안 옴」**이다. 그 상태에서 화면에
 * 아무 숫자도 없으면 어디가 막혔는지 알 수가 없다. 그래서 갈래마다 센다:
 *
 *   received      소켓이 받은 바이너리 메시지
 *   parsed        `[4B][JSON][payload]` 를 뜯은 것
 *   parseErrors   못 뜯은 것 — 사유별로
 *   textMessages  `/media` 에 원래 없는 문자열 메시지
 *   그리고 디코드 쪽 수는 `decode.ts` 가 따로 센다
 */

import { useSyncExternalStore } from 'react';
import type { MediaHeader, MediaParseError } from './parse.ts';

export type MediaPhase = 'idle' | 'connecting' | 'open' | 'closed' | 'failed';

export type MediaState = {
  phase: MediaPhase;
  /** 소켓이 받은 바이너리 메시지 수. */
  received: number;
  /** 뜯는 데 성공한 수. `received` 와 벌어지면 형식이 안 맞는 것이다. */
  parsed: number;
  /** 못 뜯은 것 — 사유별. 조용히 버리지 않는다. */
  parseErrors: Readonly<Record<MediaParseError, number>>;
  /** `/media` 에 원래 없는 문자열 메시지. 오면 그 사실을 적는다. */
  textMessages: number;
  /** 마지막으로 뜯은 헤더. 해상도·코덱·순번이 여기 있다. */
  lastHeader: MediaHeader | null;
  /** 마지막 프레임이 **도착한** 시각(ms). staleness 는 `capture_timestamp` 가 아니라 이것으로 잰다. */
  lastFrameAtMs: number;
  /** 세션이 몇 번 새로 시작했는가 — 순번 역전으로 감지한 수. */
  sessions: number;
  /** 마지막 끊김 코드. 4401·4404·4400 은 다시 안 붙는다. */
  closeCode: number | null;
  /** 못 붙었거나 끊긴 사유. 조용히 비워 두지 않는다. */
  error: string | null;
};

const NO_ERRORS: Record<MediaParseError, number> = {
  too_short: 0, bad_header_length: 0, header_not_json: 0, header_shape: 0,
};

const EMPTY: MediaState = {
  phase: 'idle',
  received: 0,
  parsed: 0,
  parseErrors: NO_ERRORS,
  textMessages: 0,
  lastHeader: null,
  lastFrameAtMs: 0,
  sessions: 0,
  closeCode: null,
  error: null,
};

let state: MediaState = EMPTY;
const listeners = new Set<() => void>();

function commit(next: MediaState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function mediaState(): MediaState {
  return state;
}

export function subscribeMedia(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useMedia(): MediaState {
  return useSyncExternalStore(subscribeMedia, mediaState, mediaState);
}

export function mediaConnecting(): void {
  commit({ ...state, phase: 'connecting', error: null, closeCode: null });
}

export function mediaOpened(): void {
  commit({ ...state, phase: 'open', error: null, closeCode: null });
}

/**
 * 프레임 한 건을 뜯었다. **그림은 안 들고 온다** — 헤더와 수만 남는다.
 *
 * `newSession` 은 순번 역전으로 판정한 것이다(`parse.isNewSession`). 여기서 다시 계산하지
 * 않는다 — 판정하는 자리는 하나여야 한다.
 */
export function mediaFrame(header: MediaHeader, newSession: boolean): void {
  commit({
    ...state,
    received: state.received + 1,
    parsed: state.parsed + 1,
    lastHeader: header,
    lastFrameAtMs: Date.now(),
    sessions: newSession ? state.sessions + 1 : state.sessions,
  });
}

export function mediaParseError(reason: MediaParseError): void {
  commit({
    ...state,
    received: state.received + 1,
    parseErrors: { ...state.parseErrors, [reason]: state.parseErrors[reason] + 1 },
  });
}

export function mediaTextMessage(): void {
  commit({ ...state, received: state.received + 1, textMessages: state.textMessages + 1 });
}

export function mediaClosed(code: number, retrying: boolean): void {
  commit({ ...state, phase: retrying ? 'connecting' : 'failed', closeCode: code });
}

export function mediaError(reason: string): void {
  commit({ ...state, phase: 'failed', error: reason });
}

/** 주소가 바뀌었거나 판을 닫았다 — 수를 통째로 비운다. 옛 주소의 수가 남으면 거짓이다. */
export function resetMedia(): void {
  commit(EMPTY);
}
