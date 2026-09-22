/**
 * src/physical/StepCommandBar.tsx (260922 신설 — 정량 명령 직접 입력)
 *
 * **사람이 적은 「1m 전진 후 오른쪽 90도 회전」을 그대로 보낸다.**
 *
 * 임무도 탐지도 거치지 않는다. 그래서 대본 없이 명령 경로를 시험할 수 있고, 그것이 이
 * 부품이 있는 이유다 — 로봇이 실제로 얼마나 가는지(`odo_m`)를 재는 자리이기도 하다.
 *
 * ## 자리는 머리줄이다
 *
 * 어느 화면에 있든 보여야 하고, 무엇보다 **정지 버튼이 늘 옆에 있어야 한다.** 로봇을
 * 움직이는 버튼과 세우는 버튼이 떨어져 있으면 무대에서 찾는다.
 *
 * ## 두 박자 — 읽은 결과를 먼저 보여 준다
 *
 *   1. 문장을 적고 **「읽기」**
 *   2. 화면이 읽은 것을 적는다 — `↑ 1.00 m (vx 0.30)` · `→ 90.0°`
 *   3. 사람이 보고 **「보내기」**
 *
 * **승인 전에 바이트가 나가지 않는다**(`VZ-U-07`). 읽은 결과를 눈으로 확인하고 누르는 것이
 * 이 경로의 승인이다 — 문장을 잘못 읽었을 때 로봇이 먼저 움직이면 되돌릴 방법이 없다.
 *
 * 문장을 고치면 읽은 것이 **사라진다.** 안 지우면 고치기 전 문장을 승인한 채로 보내게 된다.
 */

import { useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { issueSteps } from './robotCommands.ts';
import { robotClient } from './robotClient.ts';
import { parseStepScript, type StepScript } from './stepScript.ts';
import { useRobotSession } from './robotSession.ts';

export function StepCommandBar() {
  useLang();
  // 정지 관문이 열리고 닫히는 것을 따라간다 — 정지 뒤에는 보내기가 막혀야 한다.
  useRobotSession();
  const [text, setText] = useState('');
  const [read, setRead] = useState<StepScript | null>(null);
  const [busy, setBusy] = useState(false);
  /** 보낸 결과. 실패 사유이거나, 몇 걸음이 나갔는지. */
  const [outcome, setOutcome] = useState<string | null>(null);

  const ready = read !== null && read.reject === null && read.steps.length > 0;

  return <div className="stepbar">
    <input
      className="stepbar__input"
      value={text}
      placeholder={t('step.placeholder')}
      onChange={(event) => {
        setText(event.target.value);
        // **고치면 승인이 풀린다.** 안 그러면 고치기 전 문장을 승인한 채로 보낸다.
        setRead(null);
        setOutcome(null);
      }}
      onKeyDown={(event) => { if (event.key === 'Enter') setRead(parseStepScript(text)); }} />
    <button type="button" onClick={() => { setOutcome(null); setRead(parseStepScript(text)); }}>
      {t('step.read')}
    </button>
    <button
      type="button"
      className="stepbar__send"
      disabled={!ready || busy}
      onClick={() => {
        if (read === null) return;
        setBusy(true);
        setOutcome(null);
        void issueSteps(robotClient(), read.steps).then((result) => {
          setBusy(false);
          setOutcome(result.sent === true
            ? t('step.sent', { n: read.steps.length })
            : t('step.failed', { reason: result.reason ?? t('step.noReason') }));
        });
      }}
    >{busy ? t('step.sending') : t('step.send')}</button>

    {/* 읽은 결과 · 알림 · 거부 사유. **보내기 전에** 여기 다 적힌다. */}
    {read !== null && <div className="stepbar__read">
      {read.reject !== null && <b className="stepbar__reject">{t(read.reject.key, read.reject.vars)}</b>}
      {read.reads.map((line, index) => <em key={index}>{line}</em>)}
      {read.notes.map((note, index) => <small key={index}>{t(note.key, note.vars)}</small>)}
    </div>}
    {outcome !== null && <span className="stepbar__outcome">{outcome}</span>}
  </div>;
}
