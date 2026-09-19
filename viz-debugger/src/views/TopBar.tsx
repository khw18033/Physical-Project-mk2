/**
 * **지금 이 부품은 어느 화면도 그리지 않는다 — 그래도 지우지 않는다** (260919 · 4단계).
 *
 * `src/` 안에 이것을 `import` 하는 곳이 하나도 없다. `<TopBar` 가 있던 커밋은 초창기
 * 둘(`d33a9cc` · `c79bdaf`)뿐이고, 머리줄은 `shell/AppShell.tsx` 로 옮겨 갔다.
 *
 * ## 그런데 검사 넷이 이 파일을 본다
 *
 *   verify:emergency-stop      `<StopButton />` 이 있어야 한다 · 옛 중단 명령이 없어야 한다
 *                              (그 명령 이름을 여기 적으면 그 검사가 이 주석을 잡는다 —
 *                               실제로 260919 에 한 번 잡혔다. 검사는 주석을 안 지운다)
 *   〃                         `mission_pause/resume` 를 쏘면 안 된다
 *   verify:mission-prep        `<ApproachButton />` 이 있어야 한다
 *   verify:one-broker-address  `<StopButton />` 이 사라지면 안 된다
 *
 * 넷 다 `AppShell` 과 **나란히** 「어느 화면에 있든 보여야 한다」는 이유로 검사한다.
 * 지우면 그 검사들이 지키던 「머리줄 둘 다 정지 버튼이 있다」가 절반으로 준다 —
 * 안전 기능을 지키는 규칙이라 함부로 걷어낼 것이 아니다.
 *
 * ## 그래서 한글 셋은 영문화 대상이 아니다
 *
 * 화면에 안 뜨므로 사전에 넣어도 아무도 못 본다. `verify:no-raw-korean` 의 예외
 * 목록에 이 파일이 있고, 그 목록이 이 주석을 가리킨다. 머리줄을 되살리는 날
 * 그때 함께 옮긴다.
 */
import { useMission } from '../data/scenario.ts';
import { ApproachButton, PauseButton, ResumeButton, StopButton } from '../physical/StopButton.tsx';
import { ResetButton, RestartButton } from './ResetButton.tsx';

export function TopBar({ onHome, onReplay }: { onHome(): void; onReplay(): void }) {
  const { current } = useMission();
  // 임무 조작 셋은 **한 부품**에서 온다 (260910). 전에는 여기서 게이트웨이로
  // `mission_pause` 를 쏘다가 「지원하지 않는 action」으로 거절됐다 — 두 상단 바가 각자
  // 손으로 적으면 한쪽만 고쳐진다.
  return <header className="topbar">
    <button className="mission-home" onClick={onHome}><b>{current.missionId}</b><span>{current.label}</span><small>목 데이터 · HCI 초안 · 클릭하면 마일스톤으로</small></button>
    <p>정지는 로봇을 즉시 멈추고 임무를 끝냅니다. 진행상황을 남기려면 일시정지를 쓰세요.</p>
    <nav><StopButton /><PauseButton /><ResumeButton /><ApproachButton /><button onClick={onReplay}>◷ 임무 이력</button><RestartButton /><ResetButton /></nav>
  </header>;
}
