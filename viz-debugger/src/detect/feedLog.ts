/**
 * src/detect/feedLog.ts (260914 신설)
 *
 * **로봇 → 탐지 흐름을 로그 줄로.** 브로커에서 들은 `/frame` · `/scan` 한 건이 한 줄이다.
 *
 * 줄만 적는 것이 아니라 **뒤따라와야 할 것이 왔는지도 본다.** 로봇이 프레임을 보냈으면 몇 초
 * 뒤 탐지 창구에 그 각도의 결과가 있어야 한다. 없으면 그 사실을 적는다 — 260914 에 수신기가
 * 한 장도 못 받았는데 화면은 조용했고, 원인이 로봇인지 탐지인지 화면인지 한참 못 갈랐다.
 */

import { t } from '../i18n/dict.ts';
import type { ScanFeedMessage } from '../physical/scanFeed.ts';
import { appendDetectLog, angleTask, DETECT_TASKS, WHOLE_DETECT_PATH } from './detectLog.ts';
import { indexOfRotation } from './parse.ts';
import { detectState } from './store.ts';

/**
 * 프레임을 보낸 뒤 탐지 결과를 기다리는 시간. 탐지는 한 장에 2초 안팎(모델 넷)이고 폴링이
 * 1.5초라, 이만큼 지나도 없으면 흐름이 끊긴 것이다.
 */
export const RESULT_EXPECTED_WITHIN_MS = 20000;

const kb = (bytes: number | null) => (bytes === null ? t('flg.sizeUnknown') : `${(bytes / 1024).toFixed(1)} KB`);

/** 한 건을 줄로 옮긴다. 각도는 대본의 간격·칸 수로 칸 번호를 잡는다. */
export function noteScanFeed(message: ScanFeedMessage, stepDeg = 45, count = 8): void {
  if (message.kind === 'scan') {
    if (message.event === 'scan_start') {
      appendDetectLog({
        lane: 'robot', level: 'info',
        say: { key: 'flg.runStarted', vars: { n: message.expectedFrames ?? '?' } },
        sayDetail: { key: 'flg.runStartedDetail', vars: { id: message.missionId ?? { key: 'flg.none' } } },
        tasks: [DETECT_TASKS.sweep],
      });
      return;
    }
    const short = message.framesSent !== null && message.expectedFrames !== null && message.framesSent < message.expectedFrames;
    const failed = message.outcome !== null && message.outcome !== 'SUCCEEDED';
    appendDetectLog({
      lane: 'robot', level: short || failed ? 'warn' : 'info',
      // **한 문장 한 키.** 꼬리를 따로 두면 ` — ` 이음매까지 사전에 들어가고, 영어
      // 어순에서 그 둘을 다시 이을 수 없다 (1단계부터의 규칙).
      say: {
        key: short || failed ? 'flg.runEndedShort' : 'flg.runEnded',
        vars: { outcome: message.outcome ?? { key: 'flg.noOutcome' }, sent: message.framesSent ?? '?', expected: message.expectedFrames ?? '?' },
      },
      sayDetail: { key: 'flg.missionId', vars: { id: message.missionId ?? { key: 'flg.none' } } },
      tasks: [DETECT_TASKS.sweep, ...WHOLE_DETECT_PATH.slice(1)],
    });
    return;
  }

  const index = indexOfRotation(message.rotationDeg, stepDeg, count);
  const tasks = index === null ? [DETECT_TASKS.sweep] : [DETECT_TASKS.sweep, angleTask(index)];
  appendDetectLog({
    lane: 'robot',
    level: message.duplicateOfPrev ? 'warn' : 'info',
    say: {
      key: message.duplicateOfPrev ? 'flg.frameSentDup' : 'flg.frameSent',
      vars: { deg: message.rotationDeg, nth: (message.seq ?? 0) + 1 },
    },
    sayDetail: [
      ...(message.width !== null && message.height !== null ? [`${message.width}×${message.height}`] : []),
      kb(message.bytes),
      ...(message.sha1 === null ? [] : [`sha1 ${message.sha1}`]),
      ...(message.missionId === null ? [] : [`mission_id ${message.missionId}`]),
    ],
    tasks,
  });

  // **뒤따라와야 할 것이 왔는가.** 탐지 창구에 그 각도의 결과가 생겨야 한다.
  const rotation = message.rotationDeg;
  const timer = setTimeout(() => {
    const state = detectState();
    if (state.testMode) return;                         // 시료를 보고 있으면 실제 흐름과 무관하다
    if (state.frames.some((frame) => frame.rotation_deg === rotation)) return;
    appendDetectLog({
      lane: 'screen', level: 'warn',
      say: { key: 'flg.noResultYet', vars: { deg: rotation, sec: RESULT_EXPECTED_WITHIN_MS / 1000 } },
      sayDetail: state.staleFrames !== null
        ? { key: 'flg.stillStale', vars: { n: state.staleFrames } }
        : state.error !== null
          ? { key: 'flg.endpointUnreachable', vars: { why: state.error } }
          : { key: 'flg.3' },
      tasks,
    });
  }, RESULT_EXPECTED_WITHIN_MS);
  // 로그를 기다리느라 프로세스를 붙잡지 않는다(Node 검사) — 브라우저에는 없는 메서드다.
  (timer as { unref?: () => void }).unref?.();
}
