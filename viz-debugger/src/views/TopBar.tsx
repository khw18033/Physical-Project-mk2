import { recordHuman } from '../data/scenario.ts';

export function TopBar({ onReplay }: { onReplay(): void }) {
  const command = (kind: string) => recordHuman(kind);
  return <header className="topbar">
    <div><b>MSN-260826-01</b><span>415호 → 503호 이동</span><small>목 데이터 · HCI 초안</small></div>
    <p>정지는 하달 중인 액션 아이템까지 마친 뒤 멈춥니다.</p>
    <nav><button onClick={() => command('mission_pause')}>■ 정지</button><button onClick={() => command('mission_resume')}>▶ 재시작</button><button onClick={() => command('mission_abort')}>■ 중단</button><button onClick={onReplay}>◷ 임무 이력</button></nav>
  </header>;
}
