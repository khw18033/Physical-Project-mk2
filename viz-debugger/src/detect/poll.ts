/**
 * src/detect/poll.ts (260912 신설)
 *
 * **우리가 받아 간다.** 관제 웹은 브라우저 페이지라 남이 보내는 요청을 못 받는다 —
 * 탐지 쪽에 「밀어 주지 말고 열어만 달라」고 했고, 그 약속의 우리 쪽 절반이 여기다
 * (`문서/탐지_명령규약_260910.md` §2).
 *
 * ## 한 각도가 끝날 때마다 늘어난다 (260912 확인)
 *
 * 결과는 스캔이 다 끝나야 나오는 것이 아니라 **한 각도 스캔이 끝나면 그림과 함께** 나온다.
 * 그래서 짧게 물어야 칸이 제때 바뀐다. 스캔이 도는 동안만 짧고, 끝나면 길게 — 시연 내내
 * 1초마다 때리면 탐지 기계가 그만큼 느려진다.
 *
 * **WebSocket 이나 SSE 를 새로 깔지 않는다**(지시서 §6). 붙을 시간이 없고, 지금 필요한
 * 것은 여덟 번의 갱신이다.
 */

import {
  fetchFeatures, fetchFrameEvidence, fetchLocalization, fetchPath, fetchSummary, sourceOf,
} from './DetectClient.ts';
import { scanElapsedSec } from '../physical/robotSession.ts';
import { noteIssue } from '../shared/notifications.ts';
import {
  detectState, noteDetectError, receiveEvidence, receiveFeatures, receiveFrames,
  receiveLocalization, receivePath,
} from './store.ts';

/** 스캔이 도는 동안. 한 각도가 4초쯤 걸리니 그보다 짧아야 칸이 제때 바뀐다. */
export const POLL_RUNNING_MS = 1500;
/** 끝난 뒤. 경로 산출이 한 번 더 올 수 있어 아주 끄지는 않는다. */
export const POLL_IDLE_MS = 6000;

let timer: ReturnType<typeof setTimeout> | null = null;
let inFlight = false;

/**
 * 한 번 읽어 온다. **던지지 않는다** — 여기서 예외가 새면 폴링이 통째로 죽고,
 * 그러면 화면은 「탐지가 아무 말도 안 한다」가 된다. 사유는 저장소에 남긴다.
 */
export async function pollOnce(expected = 8): Promise<void> {
  if (inFlight) return;          // 느린 응답에 요청이 겹치면 탐지 기계만 바빠진다
  inFlight = true;
  try {
    const source = sourceOf(detectState().testMode);

    /**
     * **자세를 먼저 받는다.** 도는 것보다 앞이다 — 도면상 문의 자리(`T-A1`)와 로봇
     * 자신의 자리·방위(`T-A2`)가 여기서 나오고, 그 둘이 끝나야 로봇이 돈다.
     *
     * 각도별 결과와 달리 **박자에 걸리지 않는다.** 준비 단계에 있는 값이라 첫 물음에
     * 바로 온다.
     */
    if (detectState().localization === null) receiveLocalization(await fetchLocalization(source));

    // **로봇이 돌기 시작한 뒤 몇 초째인가.** 시료를 한 각도씩 내놓는 박자의 기준이고,
    // 로봇이 같이 돌고 있으면 그 회전과 같은 시계다. 준비 단계는 빠져 있다.
    const summary = await fetchSummary(source, 'door', scanElapsedSec());
    receiveFrames(summary.frames ?? []);
    const complete = (summary.frames ?? []).length >= expected;

    // 찾은 각도의 근거만 받아 온다 — 못 찾은 각도에는 근거 파일이 없는 것이 정상이다.
    for (const frame of summary.frames ?? []) {
      if (!frame.found) continue;
      if (detectState().evidence[frame.frame] !== undefined) continue;   // 한 번 받은 것은 다시 안 받는다
      const evidence = await fetchFrameEvidence(source, frame.frame);
      if (evidence !== null) receiveEvidence(frame.frame, evidence);
    }

    if (detectState().features === null) receiveFeatures(await fetchFeatures(source));
    // 경로는 **스캔이 끝나야** 나온다. 없는 동안 null 인 것이 정상이라 사유를 안 남긴다.
    if (detectState().path === null && complete) receivePath(await fetchPath(source, 'door', true));
    /**
     * **돌아오면 돌아왔다고 적는다** (260913 지시). 끊겼다는 줄만 남고 복구가 안 남으면,
     * 나중에 로그를 읽는 사람은 그 뒤로 계속 끊겨 있었다고 읽는다.
     */
    if (detectState().error !== null) noteIssue('detect', 'connection', '탐지 서비스에서 다시 받고 있습니다');
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    noteDetectError(why);
    // 폴링은 1.5초마다 돈다. 같은 사유는 `noteIssue` 가 삼키므로 한 줄만 남는다.
    noteIssue('detect', 'connection', `탐지 서비스에 못 닿습니다 — ${why}`);
  } finally {
    inFlight = false;
  }
}

/**
 * 폴링을 켠다. 되돌려주는 함수를 부르면 멎는다.
 *
 * `running()` 이 참이면 짧게, 아니면 길게 묻는다. 매번 다시 재는 이유는 스캔이 도는 동안
 * 간격이 바뀌어야 하기 때문이다 — 한 번 정해 두면 끝나고도 계속 1.5초마다 때린다.
 */
export function startDetectPolling(running: () => boolean, expected = 8): () => void {
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    await pollOnce(expected);
    if (stopped) return;
    timer = setTimeout(() => void tick(), running() ? POLL_RUNNING_MS : POLL_IDLE_MS);
  };
  void tick();
  return () => {
    stopped = true;
    if (timer !== null) { clearTimeout(timer); timer = null; }
  };
}
