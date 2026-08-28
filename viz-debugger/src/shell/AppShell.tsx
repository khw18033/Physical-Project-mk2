import { useState, type ReactNode } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { useNotifications } from '../shared/notifications.ts';

export type AppTab = 'overview' | 'control' | 'metrics' | 'video' | 'pipeline' | 'debugger';

const TABS: Array<{ id: AppTab; label: string }> = [
  { id: 'debugger', label: '① 임무 설계 및 디버깅' },
  { id: 'overview', label: '② 구역 현황판' },
  { id: 'control', label: '③ 제어 패널' },
  { id: 'metrics', label: '④ 지표 조회' },
  { id: 'video', label: '⑤ 영상 오버레이' },
  { id: 'pipeline', label: '⑥ 파이프라인 편집기' },
];

function Placeholder({ tab }: { tab: (typeof TABS)[number] }) {
  return <section className="tab-placeholder"><span>{tab.label.slice(0, 1)}</span><h1>{tab.label.slice(2)}</h1><strong>이식 예정 — 기존 프로토타입에서 동작 중</strong><p>원본 `web-dashboard`는 유지되며, 10월 이식 단계에서 이 영역에 연결됩니다.</p></section>;
}

export function AppShell({ debuggerView, onDebuggerHome, onMissionHistory }: { debuggerView: ReactNode; onDebuggerHome(): void; onMissionHistory(): void }) {
  const [activeTab, setActiveTab] = useState<AppTab>('debugger');
  const [panel, setPanel] = useState<'history' | 'notifications' | null>(null);
  const notifications = useNotifications();
  const select = (tab: AppTab) => { setActiveTab(tab); setPanel(null); };
  return <main className="app-shell">
    <header className="global-bar">
      <button className="mission-identity" onClick={() => { setActiveTab('debugger'); onDebuggerHome(); }}><b>MSN-260826-01</b><span>415동 → 503동 이동</span><small>통합 가시화 · 탭① 임무 디버거</small></button>
      <p>공통 명령은 현재 탭과 무관하게 단일 명령 출구로 발행됩니다.</p>
      <nav><button onClick={() => void issueCommand({ action: 'mission_pause' })}>■ 정지</button><button onClick={() => void issueCommand({ action: 'mission_resume' })}>▶ 재시작</button><button onClick={() => void issueCommand({ action: 'mission_abort' })}>■ 중단</button><button onClick={() => { setPanel('history'); onMissionHistory(); }}>◷ 임무 이력</button><button onClick={() => setPanel('notifications')}>알림 <b>{notifications.length}</b></button></nav>
    </header>
    <nav className="app-tabs" aria-label="통합 앱 탭">{TABS.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => select(tab.id)}>{tab.label}</button>)}</nav>
    {panel && <aside className="global-panel"><header><b>{panel === 'history' ? '임무 이력' : '통합 알림'}</b><button onClick={() => setPanel(null)}>닫기</button></header>{panel === 'history' ? <ul><li>MSN-260826-01 · 실패 · 현재</li><li>MSN-260826-00 · 완료</li><li>MSN-260825-07 · 완료</li></ul> : <ul>{notifications.map((item) => <li key={item.id}><b>{item.source}</b> {item.message}</li>)}</ul>}</aside>}
    <section className={activeTab === 'debugger' ? 'tab-stage' : 'tab-stage is-hidden'} aria-hidden={activeTab !== 'debugger'}>{debuggerView}</section>
    {TABS.filter((tab) => tab.id !== 'debugger').map((tab) => activeTab === tab.id && <Placeholder key={tab.id} tab={tab} />)}
  </main>;
}
