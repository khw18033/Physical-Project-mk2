import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MissionDebugger, type DebuggerNavigation } from './main.tsx';
import { AppShell } from './shell/AppShell.tsx';
import './style.css';

/**
 * src/standalone.tsx — **탭① 단독 빌드의 진입점.**
 *
 * `integrated.tsx` 와 **구조가 같고 주입만 없다.** 그 차이가 두 빌드의 전부이고
 * `verify:build-parity` 가 그 사실을 검사한다.
 *
 * 통합 진입점이 하는 주입 다섯을 **여기서는 하나도 안 한다** — 뷰 노드 렌더러 등록(팔레트가
 * 빈다) · 배경 작업 등록(구역 축 구독이 없다) · 봉투 수신처 등록(봉투가 조용히 지나간다) ·
 * 통합 빌드 표식(관측 보고서가 `standalone` 으로 남는다) · 승인 화면 프롭(승인 카드가 안 뜬다).
 *
 * 다섯 다 `tabs/` 에서 오고, `tabs/` 가 단독 번들에 섞이면 **논문 측정축 D(계측 오버헤드)가
 * 오염된다.** 그것이 이 경계가 서 있는 유일한 이유다.
 *
 * *(이 주석에 그 함수들의 이름을 그대로 적지 않는다 — `verify:view-nodes` 가 단독 진입점
 * 소스에서 등록 호출을 문자열로 찾기 때문에 주석만으로도 걸린다. 거친 검사지만 그 거칢이
 * 「주입이 실제로 한쪽에서만 일어나는가」를 지키는 값이라 검사를 무르게 하지 않는다.)*
 *
 * ## 260916 — 셸이 여기 들어왔다 (단독 빌드 정합)
 *
 * 전에는 이 파일이 `<MissionDebugger />` 하나만 그렸다. `verify:standalone` 이 `shell/` 을
 * 통짜로 금지했기 때문인데, 그 금지는 08-28 에 `shell/` = 「탭 전환 기계」였을 때 그은
 * **대리 지표**였다. 그 뒤 `shell/` 은 상단 바에 붙는 것들의 서랍이 됐고, 아무도 결정한 적
 * 없이 **모드 스위치·연결 관리·도움말·긴급정지가 전달본에서 빠져 있었다.**
 *
 * 지금은 셸이 `tabs/` 를 모른다(주입으로 끊었다). 그래서 양쪽이 같은 셸을 쓰고, 검사는
 * 대리 지표가 아니라 진짜 기준(`tabs/`)을 본다.
 *
 * ## 게이트웨이에 열자마자 붙는다
 *
 * 셸의 `conn` 배지가 `useConnectionStatus()` → `getTransport()` 를 부르고, 그 함수가 첫
 * 호출에 `connect()` 한다. 전에는 명령을 낼 때만 붙었으므로 **붙는 시점이 당겨진 것**이고,
 * 게이트웨이가 없으면 재연결을 쌓는다. 막을지 말지는 보고서의 관측 결과를 보고 정한다.
 */

function StandaloneApp() {
  const [navigation, setNavigation] = useState<DebuggerNavigation>({ screen: 'milestones', requestId: 0 });
  const request = (screen: DebuggerNavigation['screen'], node?: DebuggerNavigation['node']) =>
    setNavigation((current) => ({ screen, node, requestId: current.requestId + 1 }));
  // `planApproval` 을 안 준다 — 승인 화면은 `tabs/views/` 에 있다. `main.tsx` 가 선택 프롭으로
  // 받으므로 안 줘도 화면이 선다.
  return <AppShell
    debuggerView={<MissionDebugger navigation={navigation} />}
    onDebuggerHome={() => request('milestones')}
    onMissionHistory={() => request('replay')}
    onOpenNode={(kind, taskId) => request('node', { kind, taskId })} />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><StandaloneApp /></StrictMode>);
