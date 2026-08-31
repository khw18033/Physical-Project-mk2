import { useState, type ReactNode } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { useNotifications } from '../shared/notifications.ts';
import { TabView, useTabsDataLayer } from '../tabs/index.tsx';

export type AppTab = 'overview' | 'control' | 'metrics' | 'video' | 'pipeline' | 'debugger';

const TABS: Array<{ id: AppTab; label: string; tag: string }> = [
  { id: 'debugger', label: '① 임무 설계 및 디버깅', tag: 'VZ-D · VZ-L · VZ-U-07' },
  { id: 'overview', label: '② 구역 현황판', tag: 'VZ-U-01 · I-03' },
  { id: 'control', label: '③ 제어 패널', tag: 'VZ-O-01·02·05 · I-05' },
  { id: 'metrics', label: '④ 지표 조회', tag: 'VZ-I-04 · C-03' },
  { id: 'video', label: '⑤ 영상 오버레이', tag: 'VZ-I-06·07·09' },
  { id: 'pipeline', label: '⑥ 파이프라인 편집기', tag: 'VZ-U-04 · 동결' },
];

const CONNECTION_LABEL: Record<string, string> = {
  open: '게이트웨이 연결됨',
  reconnecting: '재연결 중',
  connecting: '연결 중',
  closed: '연결 종료',
};

export function AppShell({ debuggerView, onDebuggerHome, onMissionHistory }: { debuggerView: ReactNode; onDebuggerHome(): void; onMissionHistory(): void }) {
  const [activeTab, setActiveTab] = useState<AppTab>('debugger');
  const [panel, setPanel] = useState<'history' | 'notifications' | null>(null);
  const notifications = useNotifications();
  // 데이터 계층은 앱 수명과 같다. **탭을 옮겨도 구독을 끊지 않는다** — 여기서 한 번만 기동한다.
  const connection = useTabsDataLayer();
  const select = (tab: AppTab) => { setActiveTab(tab); setPanel(null); };
  return <main className="app-shell">
    <header className="global-bar">
      <button className="mission-identity" onClick={() => { setActiveTab('debugger'); onDebuggerHome(); }}><b>MSN-260826-01</b><span>415동 → 503동 이동</span><small>통합 가시화 · 탭① 임무 디버거</small></button>
      <p>공통 명령은 현재 탭과 무관하게 단일 명령 출구로 발행됩니다. 게이트웨이도 하나입니다 — 목 게이트웨이(8790).</p>
      <nav>
        <span className={`conn conn--${connection.state}`}>{CONNECTION_LABEL[connection.state] ?? connection.state}{connection.state === 'reconnecting' ? ` (${connection.attempt}회)` : ''}</span>
        <button onClick={() => void issueCommand({ action: 'mission_pause' })}>■ 정지</button><button onClick={() => void issueCommand({ action: 'mission_resume' })}>▶ 재시작</button><button onClick={() => void issueCommand({ action: 'mission_abort' })}>■ 중단</button><button onClick={() => { setPanel('history'); onMissionHistory(); }}>◷ 임무 이력</button><button onClick={() => setPanel('notifications')}>알림 <b>{notifications.length}</b></button>
      </nav>
    </header>
    <nav className="app-tabs" aria-label="통합 앱 탭">{TABS.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => select(tab.id)} title={tab.tag}>{tab.label}</button>)}</nav>
    {panel && <aside className="global-panel"><header><b>{panel === 'history' ? '임무 이력' : '통합 알림'}</b><button onClick={() => setPanel(null)}>닫기</button></header>{panel === 'history' ? <ul><li>MSN-260826-01 · 실패 · 현재</li><li>MSN-260826-00 · 완료</li><li>MSN-260825-07 · 완료</li></ul> : <ul>{notifications.map((item) => <li key={item.id}><b>{item.source}</b> {item.message}</li>)}</ul>}</aside>}
    {/* 탭①은 감추기만 하고 언마운트하지 않는다 — 되감기 시각·배정 같은 화면 상태가 날아가면 안 된다. */}
    <section className={activeTab === 'debugger' ? 'tab-stage' : 'tab-stage is-hidden'} aria-hidden={activeTab !== 'debugger'}>{debuggerView}</section>
    {activeTab !== 'debugger' && <section className="tab-stage tab-stage--ported"><TabView tab={activeTab} /></section>}
  </main>;
}
