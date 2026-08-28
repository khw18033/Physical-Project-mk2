/**
 * src/stt/SttClient.ts
 *
 * **가시화 코드가 STT 서비스를 보는 유일한 면이다.** 이 파일 밖에서 `fetch` 로
 * STT를 부르지 않는다. 서비스가 프로세스가 아니라 워커나 WASM으로 바뀌어도
 * 갈아끼우는 곳이 여기 하나가 되게 하기 위한 제약이다.
 *
 * 서비스가 꺼져 있어도 화면은 떠야 한다 (VZ-C-02 / VZ-G-01). 그래서 이 모듈은
 * 실패를 **던지기만 하고 잡지 않는다** — 무엇을 비활성화할지는 화면이 정한다.
 */

import { SttUnavailableError, type SttResult } from './types.ts';

const meta = import.meta as unknown as { env?: { VITE_STT_URL?: string } };

/** 목 게이트웨이(8790)·대시보드(5173/8787~8788)·stt-lab(8799)과 겹치지 않는 포트. */
export const STT_BASE_URL: string = meta.env?.VITE_STT_URL ?? 'http://127.0.0.1:8801';

const TRANSCRIBE_URL = `${STT_BASE_URL}/stt/transcribe`;

export type TranscribeOptions = {
  /** 켬/끔만 보낸다. **어휘 문자열은 보내지 않는다** — 서비스가 registry 원본에서 매번 새로 뽑는다 (REQ-305). */
  useHotwords?: boolean;
  vadFilter?: boolean;
  model?: string;
  signal?: AbortSignal;
};

async function post(body: FormData, signal?: AbortSignal): Promise<SttResult> {
  let response: Response;
  try {
    response = await fetch(TRANSCRIBE_URL, { method: 'POST', body, signal });
  } catch (error) {
    // 서비스가 안 떠 있는 흔한 경우가 여기로 온다. 화면은 이 문장을 그대로 보여주고
    // 음성 기능만 끈다.
    throw new SttUnavailableError('offline', `STT 서비스에 닿지 않습니다 (${STT_BASE_URL})`, String(error));
  }
  const text = await response.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new SttUnavailableError('service', `STT 응답을 해석할 수 없습니다 (HTTP ${response.status})`, text.slice(0, 400));
  }
  if (!response.ok) {
    const detail = parsed as { error?: string; traceback?: string };
    throw new SttUnavailableError('service', detail.error ?? `STT 실패 (HTTP ${response.status})`, detail.traceback);
  }
  return parsed as SttResult;
}

/** 오디오 한 건 → 인식 결과. 이 함수가 STT의 전부다. */
export async function transcribe(blob: Blob, options: TranscribeOptions = {}): Promise<SttResult> {
  const body = new FormData();
  const suffix = blob.type.includes('wav') ? 'wav' : 'webm';
  body.append('audio', blob, `utterance.${suffix}`);
  body.append('use_hotwords', String(options.useHotwords ?? true));
  body.append('vad_filter', String(options.vadFilter ?? true));
  if (options.model) body.append('model', options.model);
  return post(body, options.signal);
}

/**
 * 서비스가 살아 있는가.
 *
 * **전용 헬스 엔드포인트를 두지 않는다.** 이 서비스의 면은 `POST /stt/transcribe`
 * 하나뿐이고, 살아 있는지 알려고 라우팅을 늘리면 stt-lab 이 실험용 라우팅 8개로
 * 불어난 길을 그대로 밟게 된다. 대신 같은 경로에 GET 을 던진다 —
 * **응답이 오면(405 Method Not Allowed) 프로세스가 살아 있다는 뜻**이고,
 * 네트워크 자체가 실패하면 꺼져 있다는 뜻이다.
 */
export async function probe(signal?: AbortSignal): Promise<boolean> {
  try {
    await fetch(TRANSCRIBE_URL, { method: 'GET', signal });
    return true;
  } catch {
    return false;
  }
}
