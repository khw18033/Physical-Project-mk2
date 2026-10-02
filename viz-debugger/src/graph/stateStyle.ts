import type { TaskStatus } from '../model/types.ts';
import { t } from '../i18n/dict.ts';

/**
 * 태스크 상태 8종의 **모양**. 글자는 여기 없다 (260917 — 영문화 2단계).
 *
 * 전에는 `label` 이 이 표 안에 있었다. 그런데 **모듈 최상위 상수라 `t()` 를 여기서 부르면
 * 로드 시점에 굳어** 언어를 바꿔도 영원히 안 바뀐다(지시서 §2 ②). 그래서 아이콘·클래스만
 * 남기고 글자는 `stateLabel()` 이 읽는 자리에서 묻는다.
 *
 * **장치 상태 4종과 다른 것이다** (용어집 §2 ◆). 이쪽 키는 `task.state.*` 이고
 * 장치 쪽은 `device.status.*` 다 — 한 단어로 뭉치면 탭①과 탭②가 같은 말을 쓰게 된다.
 */
export const STATE_STYLE: Record<TaskStatus, { icon: string; className: string }> = {
  pending: { icon: '·', className: 'state-pending' },
  running: { icon: '▶', className: 'state-running' },
  done: { icon: '✓', className: 'state-done' },
  failed: { icon: '×', className: 'state-failed' },
  skipped: { icon: '↷', className: 'state-skipped' },
  awaiting_evaluation: { icon: '◌', className: 'state-awaiting' },
  not_executed: { icon: '—', className: 'state-not-executed' },
  rerunning: { icon: '↻', className: 'state-rerunning' },
};

/**
 * 상태 이름. **부르는 자리가 `useLang()` 을 갖고 있어야** 언어 전환에 따라 다시 그려진다
 * (지시서 §2 ①) — 이 함수는 값을 줄 뿐 리렌더를 일으키지 않는다.
 */
export function stateLabel(status: TaskStatus): string {
  return t(`task.state.${status}`);
}
