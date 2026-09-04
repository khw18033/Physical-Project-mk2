import { useMission } from '../data/scenario.ts';
import { issueCommand } from '../shared/commandEgress.ts';

export function TopBar({ onHome, onReplay }: { onHome(): void; onReplay(): void }) {
  const { current } = useMission();
  // 셸의 상단 바와 **같은 길**로 낸다 (260904). 기록은 출구 본체가 한다 — 여기서 따로
  // 적으면 「기록은 됐는데 나가지는 않은」 조작이 열에 남는다.
  const command = (kind: string) => void issueCommand({ action: kind });
  return <header className="topbar">
    <button className="mission-home" onClick={onHome}><b>{current.missionId}</b><span>{current.label}</span><small>목 데이터 · HCI 초안 · 클릭하면 마일스톤으로</small></button>
    <p>정지는 하달 중인 액션 아이템까지 마친 뒤 멈춥니다.</p>
    <nav><button onClick={() => command('mission_pause')}>■ 정지</button><button onClick={() => command('mission_resume')}>▶ 재시작</button><button onClick={() => command('mission_abort')}>■ 중단</button><button onClick={onReplay}>◷ 임무 이력</button></nav>
  </header>;
}
