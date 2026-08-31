import { useState, type ReactNode } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { useNotifications } from '../shared/notifications.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { toggleRenderMode, useMockRender } from '../shared/renderMode.ts';
import { TabView, useTabsDataLayer } from '../tabs/index.tsx';

export type AppTab = 'overview' | 'control' | 'metrics' | 'video' | 'debugger';

const TABS: Array<{ id: AppTab; label: string; tag: string }> = [
  { id: 'debugger', label: '① 임무 설계 및 디버깅', tag: 'VZ-D · VZ-L · VZ-U-07' },
  { id: 'overview', label: '② 구역 현황판', tag: 'VZ-U-01 · I-03' },
  { id: 'control', label: '③ 제어 패널', tag: 'VZ-O-01·02·05 · I-05' },
  { id: 'metrics', label: '④ 지표 조회', tag: 'VZ-I-04 · C-03' },
  { id: 'video', label: '⑤ 영상 오버레이', tag: 'VZ-I-06·07·09' },
  // 탭⑥(파이프라인 편집기)은 2026-08-31에 제거했다 — 노드 에디터의 구현 방향이
  // 탭①로 확정됐다(전회의). 원형은 web-dashboard(기준선)에 그대로 있다.
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
  // 남이 줄 데이터를 그릴지 말지. **기본은 자리표시**다 (shared/renderMode.ts).
  const mock = useMockRender();
  const select = (tab: AppTab) => { setActiveTab(tab); setPanel(null); };
  return <main className={mock ? 'app-shell app-shell--mock' : 'app-shell'}>
    {/* 지워지지 않는다. 토글을 켠 것을 잊고 시연하면 원래 문제로 되돌아간다. */}
    {mock && <div className="mock-banner" role="status">목 렌더 켜짐 — 화면의 남의 데이터는 <b>전부 지어낸 값</b>입니다. 시연 전에 끄세요.</div>}
    <header className="global-bar">
      <button className="mission-identity" onClick={() => { setActiveTab('debugger'); onDebuggerHome(); }}><b>MSN-260826-01</b><span>415동 → 503동 이동</span><small>통합 가시화 · 탭① 임무 디버거</small></button>
      <p>공통 명령은 현재 탭과 무관하게 단일 명령 출구로 발행됩니다. 게이트웨이도 하나입니다 — 목 게이트웨이(8790).<br /><small>남이 줄 데이터 자리는 <b>무엇을 · 누구에게서 기다리는지</b>를 표시합니다. 목 게이트웨이는 계속 발행하고 있고, 그리는 층만 바뀝니다.</small></p>
      <nav>
        <button className={mock ? 'mock-toggle mock-toggle--on' : 'mock-toggle'} onClick={toggleRenderMode}
          title="켜면 남이 줄 데이터 자리에 목을 그립니다. 시연 중에는 켜지 마세요 — 진짜처럼 보입니다.">
          목 렌더 <b>{mock ? '켬' : '끔'}</b>
        </button>
        <span className={`conn conn--${connection.state}`}>{CONNECTION_LABEL[connection.state] ?? connection.state}{connection.state === 'reconnecting' ? ` (${connection.attempt}회)` : ''}</span>
        <button onClick={() => void issueCommand({ action: 'mission_pause' })}>■ 정지</button><button onClick={() => void issueCommand({ action: 'mission_resume' })}>▶ 재시작</button><button onClick={() => void issueCommand({ action: 'mission_abort' })}>■ 중단</button><button onClick={() => { setPanel('history'); onMissionHistory(); }}>◷ 임무 이력</button><button onClick={() => setPanel('notifications')}>알림 <b>{notifications.length}</b></button>
      </nav>
    </header>
    <nav className="app-tabs" aria-label="통합 앱 탭">{TABS.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => select(tab.id)} title={tab.tag}>{tab.label}</button>)}</nav>
    {panel && <aside className="global-panel"><header><b>{panel === 'history' ? '임무 이력' : '통합 알림'}</b><button onClick={() => setPanel(null)}>닫기</button></header>{panel === 'history' ? <PendingSource id="mission-history" minHeight={110}><ul><li>MSN-260826-01 · 실패 · 현재</li><li>MSN-260826-00 · 완료</li><li>MSN-260825-07 · 완료</li></ul></PendingSource> : <ul>{notifications.map((item) => <li key={item.id}><b>{item.source}</b> {item.source === 'external-ai' ? <PendingSource id="ai-failure-alert" inline>{item.message}</PendingSource> : item.message}</li>)}</ul>}</aside>}
    {/* 탭①은 감추기만 하고 언마운트하지 않는다 — 되감기 시각·배정 같은 화면 상태가 날아가면 안 된다. */}
    <section className={activeTab === 'debugger' ? 'tab-stage' : 'tab-stage is-hidden'} aria-hidden={activeTab !== 'debugger'}>{debuggerView}</section>
    {activeTab !== 'debugger' && <section className="tab-stage tab-stage--ported"><TabView tab={activeTab} /></section>}
  </main>;
}
