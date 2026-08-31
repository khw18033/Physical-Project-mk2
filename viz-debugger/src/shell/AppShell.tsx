import { useState, type ReactNode } from 'react';
import { useMission } from '../data/scenario.ts';
import { issueCommand } from '../shared/commandEgress.ts';
import { ManualScope } from '../shared/Explain.tsx';
import { useNotifications } from '../shared/notifications.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { exitScenarioRender, useDevTools, useMockRender, useScenarioRender } from '../shared/renderMode.ts';
import { TabView, useTabsDataLayer } from '../tabs/index.tsx';
import { HelpOverlay } from './HelpOverlay.tsx';
import { useMissionBridge } from './missionBridge.ts';
import { ModeSwitch } from './ModeSwitch.tsx';

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
  // 임무 축(plan 제안·trace_event) — 구역 축 구독에 딸려 오지 않아 셸이 따로 잇는다 (260831).
  useMissionBridge();
  // 남이 줄 데이터를 그릴지 말지. **기본은 자리표시**다 (shared/renderMode.ts).
  const mock = useMockRender();
  // 상단 바의 임무 이름 — 한 편이 박혀 있던 자리. 현재 임무 저장소를 본다 (260831).
  const mission = useMission();
  // 대본 띠 — 모드 스위치가 상태를 말해 주므로 **한 줄**이다 (사이트 개선 요구 4).
  const scenario = useScenarioRender();
  const scenarioEnded =
    scenario !== null && scenario.playing && mission.current.missionId === scenario.missionId && !mission.playing;
  const scenarioState = scenario === null ? '' : scenario.playing ? (scenarioEnded ? '재생 끝 — 마지막 상태' : '재생 중') : '정지 미리보기';
  const closeScript = () => {
    // 게이트웨이가 재생을 멈추고 장치를 평시로 되돌린다. 실패해도 화면은 placeholder 로 복귀한다.
    void issueCommand({ action: 'script_close' }).catch(() => undefined);
    exitScenarioRender();
  };
  // 개발 도구(devpanel — 시나리오 재생 버튼·계약 확인·리렌더 카운터)는 목·개발 모드(또는
  // ? 오버레이의 토글)에서만 보인다 (260831 요구 1). CSS 한 규칙으로 여섯 자리를 다 가린다.
  const devTools = useDevTools();
  const select = (tab: AppTab) => { setActiveTab(tab); setPanel(null); };
  return <main className={'app-shell' + (mock ? ' app-shell--mock' : '') + (devTools ? ' app-shell--dev' : '')}>
    {/* 배너 3종은 각각 **한 줄**이다 — 상태는 우상단 모드 스위치가 말한다. 목 배너의 경고만 남긴다. */}
    {mock && <div className="mock-banner" role="status">목 렌더 켜짐 — 남의 데이터 자리가 <b>전부 지어낸 값</b>입니다. 시연 전에 끄세요.</div>}
    {scenario !== null && <div className="scenario-banner" role="status">
      대본 <b>{scenario.missionId}</b> · {scenarioState} · <b>합성 데이터</b> — cast 밖 장비는 자리표시
      <button onClick={closeScript}>대본 닫기</button>
    </div>}
    {scenario === null && mission.activatedBy === 'approval' && mission.current.world === 'legacy' && <div className="legacy-banner" role="status">
      구판 세계 대본(<b>{mission.current.missionId}</b>) — 구역 장비와 연결되지 않아 탭②~⑤는 따라 움직이지 않습니다 (7.8 예외)
    </div>}
    <header className="global-bar">
      <button className="mission-identity" onClick={() => { setActiveTab('debugger'); onDebuggerHome(); }}><b>{mission.current.missionId}</b><span>{mission.current.label}</span><small>통합 가시화 · 탭① 임무 디버거</small></button>
      {/* 안내 문단 2줄은 우상단 `?` 오버레이로 옮겼다 (사이트 개선 요구 1). */}
      <nav>
        <ModeSwitch />
        <HelpOverlay tab={activeTab} />
        <span className={`conn conn--${connection.state}`}>{CONNECTION_LABEL[connection.state] ?? connection.state}{connection.state === 'reconnecting' ? ` (${connection.attempt}회)` : ''}</span>
        <button onClick={() => void issueCommand({ action: 'mission_pause' })}>■ 정지</button><button onClick={() => void issueCommand({ action: 'mission_resume' })}>▶ 재시작</button><button onClick={() => void issueCommand({ action: 'mission_abort' })}>■ 중단</button><button onClick={() => { setPanel('history'); onMissionHistory(); }}>◷ 임무 이력</button><button onClick={() => setPanel('notifications')}>알림 <b>{notifications.length}</b></button>
      </nav>
    </header>
    <nav className="app-tabs" aria-label="통합 앱 탭">{TABS.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => select(tab.id)} title={tab.tag}>{tab.label}</button>)}</nav>
    {panel && <aside className="global-panel"><header><b>{panel === 'history' ? '임무 이력' : '통합 알림'}</b><button onClick={() => setPanel(null)}>닫기</button></header>{panel === 'history' ? <PendingSource id="mission-history" minHeight={110}><ul><li>MSN-260826-01 · 실패 · 현재</li><li>MSN-260826-00 · 완료</li><li>MSN-260825-07 · 완료</li></ul></PendingSource> : <ul>{notifications.map((item) => <li key={item.id}><b>{item.source}</b> {item.source === 'external-ai' ? <PendingSource id="ai-failure-alert" inline>{item.message}</PendingSource> : item.message}</li>)}</ul>}</aside>}
    {/* 탭①은 감추기만 하고 언마운트하지 않는다 — 되감기 시각·배정 같은 화면 상태가 날아가면 안 된다.
        ManualScope 는 탭마다 감싼다 — Explain 문단이 「지금 열려 있는 탭」의 설명서로 등록된다. */}
    <section className={activeTab === 'debugger' ? 'tab-stage' : 'tab-stage is-hidden'} aria-hidden={activeTab !== 'debugger'}>
      <ManualScope.Provider value="debugger">{debuggerView}</ManualScope.Provider>
    </section>
    {activeTab !== 'debugger' && <section className="tab-stage tab-stage--ported">
      <ManualScope.Provider value={activeTab}><TabView tab={activeTab} /></ManualScope.Provider>
    </section>}
  </main>;
}
