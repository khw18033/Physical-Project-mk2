/**
 * src/physical/ApproachApproval.tsx (261103 신설)
 *
 * **「산출된 경로에 따라 이동」 노드 상세의 승인 체크.** 기본은 꺼짐 — 경로가 나오면 승인 없이 곧바로 간다
 * (`approachAuto.ts`). 켜면 그 편은 머리줄의 「▶ 경로대로 이동」을 사람이 눌러야 출발한다.
 *
 * 임무 실행 전에 정해 둔다. 이동이 이미 나갔으면 바꿔도 이번 판에는 소용이 없어 잠근다.
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { setApproachNeedsApproval, useApproachNeedsApproval } from './approachAuto.ts';
import { useRobotSession } from './robotSession.ts';

export function ApproachApprovalToggle({ missionId }: { missionId: string }) {
  useLang();
  const session = useRobotSession();
  const needsApproval = useApproachNeedsApproval(missionId);
  const locked = session.approachIssued;
  return <section className="prep-facts approach-approval">
    <label title={locked ? t('approval.lockedTitle') : undefined}>
      <input
        type="checkbox"
        checked={needsApproval}
        disabled={locked}
        onChange={(event) => setApproachNeedsApproval(missionId, event.target.checked)}
      />
      <b>{t('approval.label')}</b>
    </label>
    <small>{needsApproval ? t('approval.onNote') : t('approval.offNote')}</small>
  </section>;
}
