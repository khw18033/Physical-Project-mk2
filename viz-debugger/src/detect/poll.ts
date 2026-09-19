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

import { t } from '../i18n/dict.ts';
import {
  fetchFeatures, fetchFrameEvidence, fetchLocalization, fetchPath, fetchSummary, sourceOf,
} from './DetectClient.ts';
import { scanElapsedSec } from '../physical/robotSession.ts';
import { noteIssue } from '../shared/notifications.ts';
import {
  clearStale, detectState, discardRound, markStale, noteDetectError, receiveEvidence,
  receiveFeatures, receiveFrames, receiveLocalization, receivePath, receivePathFailure,
} from './store.ts';
import { angleTask, appendDetectLog, DETECT_TASKS, WHOLE_DETECT_PATH } from './detectLog.ts';
import { chosenFrame, gateWords, indexOfRotation, SCORE_LABEL_KEY } from './parse.ts';
import type { DetectFrame, DetectFrameEvidence, DetectPath } from './types.ts';

/** 스캔이 도는 동안. 한 각도가 4초쯤 걸리니 그보다 짧아야 칸이 제때 바뀐다. */
export const POLL_RUNNING_MS = 1500;
/** 끝난 뒤. 경로 산출이 한 번 더 올 수 있어 아주 끄지는 않는다. */
export const POLL_IDLE_MS = 6000;

let timer: ReturnType<typeof setTimeout> | null = null;
let inFlight = false;

/**
 * **이번 판의 결과만 받는 문** (260914).
 *
 * 실제로 겪은 일: 데스크톱의 탐지 창구에 **지난 판 산출물**(데이터셋 8장을 돌려 본 결과)이
 * 남아 있었다. 「임무 시작」을 누르자 첫 물음에 여덟 각도와 경로가 한꺼번에 왔고, 로봇은
 * 돌지도 않았는데 노드가 판단 완료를 지나 「접근 시작」까지 달려갔다. 그 버튼을 누르면
 * 로봇이 **지난 판의 경로로** 움직인다.
 *
 * 탐지 서비스는 판의 경계를 알려 주지 않는다(연동 스키마 — `command_id` 도 `mission_id` 도
 * 없다). 대신 **새 스캔이 시작될 때 지난 판 산출물을 지운다**(`mqtt_stream_receiver.py` 의
 * `_clear_previous_run`). 그래서 이렇게 가른다.
 *
 *   baseline   폴링을 켠 뒤 첫 물음. 비어 있으면 곧바로 fresh, 뭔가 있으면 stale
 *   stale      지난 판이다. 아무것도 안 받는다 — 각도 수가 **줄어드는 것**(지워짐)을 보면 fresh
 *   fresh      이번 판. 받는다. 도중에 줄면 판이 다시 시작된 것이라 받은 것을 비운다
 *
 * 한 각도가 끝나기까지 수 초가 걸리므로 1.5초 폴링이 「지워진 순간」을 놓칠 일은 없다.
 * 시료(「테스트」)는 박자를 화면이 만들므로 이 문을 지나지 않는다.
 */
type Gate = { phase: 'baseline' } | { phase: 'stale'; count: number } | { phase: 'fresh' };
let gate: Gate = { phase: 'baseline' };

/** 이번 판에서 판정 줄을 이미 적었는가 — 여덟이 다 찬 뒤 폴링마다 같은 줄이 쌓이지 않게. */
let judgedLogged = false;
/** 이번 폴링에서 첫 응답을 적었는가. */
let firstAnswerLogged = false;

/** 문을 처음 자리로 — 폴링을 켤 때마다(시작을 누를 때 · 주소가 바뀔 때) 다시 가른다. */
export function resetDetectGate(): void {
  gate = { phase: 'baseline' };
  judgedLogged = false;
  firstAnswerLogged = false;
  clearStale();
}

/** 이번 물음의 각도 목록을 받아도 되는가. 문의 상태도 여기서 옮긴다. */
function admit(frames: readonly DetectFrame[]): boolean {
  if (gate.phase === 'baseline') {
    if (frames.length === 0) {
      gate = { phase: 'fresh' };
      appendDetectLog({
        lane: 'detect', level: 'info',
        say: { key: 'dpl.1' },
        tasks: WHOLE_DETECT_PATH,
      });
      return true;
    }
    gate = { phase: 'stale', count: frames.length };
    markStale(frames.length);
    const words = t('dpl.staleRound', { n: frames.length });
    noteIssue('detect-stale', 'connection', words);
    appendDetectLog({
      lane: 'screen', level: 'warn',
      say: { key: 'dpl.staleRound', vars: { n: frames.length } },
      sayDetail: { key: 'dpl.staleAngles', vars: { list: frames.map((f) => `${f.rotation_deg}°`).join(' ') } },
      tasks: WHOLE_DETECT_PATH,
    });
    return false;
  }
  if (gate.phase === 'stale') {
    if (frames.length >= gate.count) return false;
    gate = { phase: 'fresh' };
    clearStale();
    noteIssue('detect-stale', 'connection', t('dpl.2'));
    appendDetectLog({
      lane: 'detect', level: 'info', say: { key: 'dpl.2' },
      sayDetail: { key: 'dpl.nowAngles', vars: { n: frames.length } }, tasks: WHOLE_DETECT_PATH,
    });
    return true;
  }
  // fresh — 도중에 줄었으면 판이 다시 시작됐다.
  if (frames.length < detectState().frames.length) {
    discardRound();
    judgedLogged = false;
    appendDetectLog({
      lane: 'detect', level: 'warn',
      say: { key: 'dpl.3' },
      sayDetail: { key: 'dpl.fewerAngles', vars: { from: detectState().frames.length, to: frames.length } },
      tasks: WHOLE_DETECT_PATH,
    });
  }
  return true;
}

/** 새로 온 각도 결과를 한 줄씩. 이미 받은 각도는 다시 안 적는다. */
function logNewFrames(previous: readonly DetectFrame[], next: readonly DetectFrame[], stepDeg: number, count: number): void {
  const seen = new Set(previous.map((frame) => frame.rotation_deg));
  for (const frame of next) {
    if (seen.has(frame.rotation_deg)) continue;
    const index = indexOfRotation(frame.rotation_deg, stepDeg, count);
    appendDetectLog({
      lane: 'detect', level: 'info',
      say: { key: 'dpl.frameResult', vars: { deg: frame.rotation_deg, verdict: { key: frame.found ? 'dpl.doorYes' : 'dpl.doorNo' }, n: next.length, count } },
      // 조각마다 **그 자체로 완결된 말**이라 이을 수 있다 (프레임 id · 점수 · 한 문장).
      sayDetail: [
        frame.frame,
        ...(typeof frame.final_score === 'number'
          ? [{ key: 'dpl.scoreValue', vars: { label: { key: SCORE_LABEL_KEY }, score: frame.final_score.toFixed(3) } }]
          : []),
        { key: 'dpl.4' },
      ],
      tasks: index === null ? [DETECT_TASKS.sweep] : [DETECT_TASKS.sweep, angleTask(index)],
    });
  }
}

/**
 * 한 번 읽어 온다. **던지지 않는다** — 여기서 예외가 새면 폴링이 통째로 죽고,
 * 그러면 화면은 「탐지가 아무 말도 안 한다」가 된다. 사유는 저장소에 남긴다.
 */
export async function pollOnce(expected = 8, stepDeg = 45): Promise<void> {
  if (inFlight) return;          // 느린 응답에 요청이 겹치면 탐지 기계만 바빠진다
  inFlight = true;
  try {
    const source = sourceOf(detectState().testMode);

    // **로봇이 돌기 시작한 뒤 몇 초째인가.** 시료를 한 각도씩 내놓는 박자의 기준이고,
    // 로봇이 같이 돌고 있으면 그 회전과 같은 시계다. 준비 단계는 빠져 있다.
    const summary = await fetchSummary(source, 'door', scanElapsedSec());
    if (!firstAnswerLogged && source.kind === 'sample') {
      firstAnswerLogged = true;
      appendDetectLog({ lane: 'detect', level: 'info', say: { key: 'dpl.5' }, tasks: WHOLE_DETECT_PATH });
    }
    if (detectState().error !== null) {
      appendDetectLog({ lane: 'detect', level: 'info', say: { key: 'dpl.6' }, tasks: WHOLE_DETECT_PATH });
    }

    // **이번 판인지 먼저 가른다** — 자세·근거·경로도 같은 판의 산출물이라 같이 거른다.
    if (source.kind === 'live' && !admit(summary.frames ?? [])) return;

    /**
     * **탐지의 자세 역산.** 실제 탐지 프로그램은 이것을 **여덟 장을 다 받은 뒤에** 계산한다 —
     * 돌기 전에는 없다. `T-A1`·`T-A2` 는 이것을 기다리지 않는다(`physical/prepStage.ts`).
     * 오면 T-A2 액션 아이템에 「탐지가 역산한 도면 기준 자세」로 덧붙는다.
     */
    if (detectState().localization === null) {
      const localization = await fetchLocalization(source);
      receiveLocalization(localization);
      if (localization?.robot_position_cm !== undefined) {
        const [x, y] = localization.robot_position_cm;
        appendDetectLog({
          lane: 'detect', level: 'info',
          say: { key: 'dpl.localized', vars: { deg: localization.current_heading_map_deg ?? '?', x, y } },
          // 전에는 두 키를 `+` 로 이어 붙였다 — 뒤 조각이 ` · 로…` 로 시작하는 **문장의 꼬리**라
          // 영어 어순에서 못 잇는다. 한 문장 한 키로 합치고 앞부분만 값으로 넣는다.
          sayDetail: {
            key: 'dpl.localizedDetail',
            vars: { method: { key: localization.method === 'door_only' ? 'dpl.doorOnly' : 'dpl.fromPodium' } },
          },
          tasks: [DETECT_TASKS.pose, DETECT_TASKS.path],
        });
      }
    }

    const previous = detectState().frames;
    receiveFrames(summary.frames ?? []);
    logNewFrames(previous, summary.frames ?? [], stepDeg, expected);
    const complete = (summary.frames ?? []).length >= expected;

    // 찾은 각도의 근거만 받아 온다 — 못 찾은 각도에는 근거 파일이 없는 것이 정상이다.
    for (const frame of summary.frames ?? []) {
      if (!frame.found) continue;
      if (detectState().evidence[frame.frame] !== undefined) continue;   // 한 번 받은 것은 다시 안 받는다
      const evidence = await fetchFrameEvidence(source, frame.frame);
      if (evidence === null) continue;
      receiveEvidence(frame.frame, evidence);
      const index = indexOfRotation(frame.rotation_deg, stepDeg, expected);
      appendDetectLog({
        lane: 'detect', level: 'info',
        say: { key: 'dpl.evidence', vars: { deg: frame.rotation_deg, gates: gateLine(evidence) } },
        sayDetail: {
          key: 'dpl.evidenceDetail',
          vars: {
            label: { key: SCORE_LABEL_KEY },
            score: evidence.final_score.toFixed(3),
            box: evidence.box_xyxy.map((n) => n.toFixed(1)).join(', '),
          },
        },
        tasks: index === null ? [DETECT_TASKS.evidence] : [angleTask(index), DETECT_TASKS.evidence],
      });
    }

    // **여덟이 다 찼으면 판정을 한 번 적는다.** 판정 자체는 `detectBridge`·`detectTrace` 가 한다 —
    // 여기서는 같은 규칙(`chosenFrame`)으로 무엇이 골라졌는지만 옮긴다.
    if (complete && !judgedLogged) {
      judgedLogged = true;
      const chosen = chosenFrame(detectState().frames, (f) => detectState().evidence[f.frame]?.final_score ?? 0);
      appendDetectLog({
        lane: 'screen', level: chosen === null ? 'warn' : 'info',
        say: chosen === null
          ? { key: 'dpl.noneFound', vars: { expected } }
          : { key: 'dpl.judged', vars: { deg: chosen.rotation_deg } },
        // 값만 있는 줄 — 각도와 점수다. 옮길 글자가 없다.
        detail: detectState().frames.filter((f) => f.found).map((f) => `${f.rotation_deg}° ${(detectState().evidence[f.frame]?.final_score ?? 0).toFixed(3)}`).join(' · '),
        tasks: [DETECT_TASKS.judge],
      });
    }

    if (detectState().features === null) receiveFeatures(await fetchFeatures(source));
    // 경로는 **스캔이 끝나야** 나온다. 없는 동안 null 인 것이 정상이라 사유를 안 남긴다.
    if (detectState().path === null && detectState().pathFailure === null && complete) {
      const { path, failure } = await fetchPath(source, 'door', true);
      if (path !== null) {
        receivePath(path);
        appendDetectLog({
          lane: 'detect', level: path.path_mode === 'door_relative' ? 'warn' : 'info',
          // 탐지 서비스가 준 한국어는 **그릴 때 옮기고**(`foreign`), 옮겨진 경우에만
          // **원문을 상세 줄에 남긴다**(`original`). 한국어 화면에서는 원문 자리가 비어
          // 줄에서 빠지므로 글자가 한 자도 안 달라진다.
          say: [
            { key: 'dpl.pathReceived', vars: { turn: { foreign: path.turn_instruction }, m: (path.forward_distance_cm / 100).toFixed(2) } },
            ...(path.path_mode_words ? [{ foreign: path.path_mode_words }] : []),
          ],
          sayDetail: [
            { foreign: chainWords(path) },
            { key: 'dpl.standoff', vars: { m: (path.standoff_cm / 100).toFixed(2) } },
            { key: path.path_overlay_available === false ? 'dpl.7' : 'dpl.8' },
            // 받은 그대로 — 탐지 파트와는 이 글자로 이야기한다.
            { original: [path.turn_instruction, path.path_mode_words, chainWords(path)].filter((v) => v !== undefined && v !== '').join(' · ') },
          ],
          tasks: [DETECT_TASKS.path],
        });
      } else if (failure !== null) {
        receivePathFailure(failure);
        appendDetectLog({
          lane: 'detect', level: 'error',
          say: { key: 'dpl.pathFailed', vars: { reason: failure.reason === undefined ? { key: 'dpl.noReason' } : { foreign: failure.reason } } },
          sayDetail: [
            { key: 'dpl.willNotMove', vars: { chain: { foreign: chainWords(failure) } } },
            { original: [failure.reason, chainWords(failure)].filter((v) => v !== undefined && v !== '').join(' · ') },
          ],
          tasks: [DETECT_TASKS.path, DETECT_TASKS.approach],
        });
      }
    }
    /**
     * **돌아오면 돌아왔다고 적는다** (260913 지시). 끊겼다는 줄만 남고 복구가 안 남으면,
     * 나중에 로그를 읽는 사람은 그 뒤로 계속 끊겨 있었다고 읽는다.
     */
    if (detectState().error !== null) noteIssue('detect', 'connection', t('dpl.9'));
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    noteDetectError(why);
    // 폴링은 1.5초마다 돈다. 같은 사유는 `noteIssue` 가 삼키므로 한 줄만 남는다.
    noteIssue('detect', 'connection', t('dpl.serviceUnreachable', { why }));
    appendDetectLog({ lane: 'detect', level: 'error', say: { key: 'dpl.endpointUnreachable', vars: { why } }, tasks: WHOLE_DETECT_PATH });
  } finally {
    inFlight = false;
  }
}

/** 대체 경로를 한 줄로 — `A_pedestal ✕ → B_door_only ✓ → path_map ✓`. */
function chainWords(path: DetectPath): string {
  const chain = path.fallback_chain ?? [];
  return chain.length === 0 ? '' : chain.map((step) => `${step.step} ${step.ok ? '✓' : '✕'}`).join(' → ');
}

/** 관문 넷을 한 줄로 — 화면 문장과 같은 함수(`gateWords`)를 쓴다. */
function gateLine(evidence: DetectFrameEvidence): string {
  const gates = Object.entries(evidence.mandatory_gates ?? {});
  if (gates.length === 0) return t('dpl.10');
  return gates.map(([name, gate]) => `${gate.passed ? '✓' : '✕'} ${gateWords(name, gate)}`).join(' · ');
}

/**
 * 폴링을 켠다. 되돌려주는 함수를 부르면 멎는다.
 *
 * `running()` 이 참이면 짧게, 아니면 길게 묻는다. 매번 다시 재는 이유는 스캔이 도는 동안
 * 간격이 바뀌어야 하기 때문이다 — 한 번 정해 두면 끝나고도 계속 1.5초마다 때린다.
 */
export function startDetectPolling(running: () => boolean, expected = 8, stepDeg = 45): () => void {
  let stopped = false;
  // 켤 때마다 이번 판을 새로 가른다 — 앞에서 켰던 폴링이 fresh 로 끝났어도 그건 지난 판이다.
  resetDetectGate();
  const tick = async () => {
    if (stopped) return;
    await pollOnce(expected, stepDeg);
    if (stopped) return;
    timer = setTimeout(() => void tick(), running() ? POLL_RUNNING_MS : POLL_IDLE_MS);
  };
  void tick();
  return () => {
    stopped = true;
    if (timer !== null) { clearTimeout(timer); timer = null; }
  };
}
