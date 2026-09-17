import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { registerViewNodes } from './canvas/registry.ts';
import { MissionDebugger, type DebuggerNavigation } from './main.tsx';
import { AppShell } from './shell/AppShell.tsx';
import { registerAppService } from './shared/appServices.ts';
import { registerEnvelopeSink } from './shared/envelopeSink.ts';
import { markIntegratedBuild } from './shared/observability.ts';
import { PlanApproval, VIEW_NODE_RENDERERS, startTabsServices } from './tabs/index.tsx';
import { store } from './tabs/data/index.ts';
import './style.css';

/**
 * **`tabs/` 의 실물은 이 파일만 가져간다.** 단독 빌드(`standalone.tsx`)는 셸까지는 같이 쓰고
 * 아래 주입 넷만 안 한다 — 그것이 두 빌드의 유일한 차이다
 * (`verify:standalone` · `verify:build-parity` · 논문 측정축 D).
 *
 * ## 260916 — 경계가 `shell/` 에서 `tabs/` 로 좁혀졌다 (단독 빌드 정합)
 *
 * 전에는 단독 빌드가 `shell/` 을 통째로 못 가져갔다. 그래서 모드 스위치·연결 관리·도움말·
 * **긴급정지**가 전달본에서 19일간 빠져 있었다 — 결정한 적 없이, `shell/` 이 금지 폴더였기
 * 때문에 생긴 일이다. 지금은 셸이 `tabs/` 를 모르고(주입으로 끊었다) 양쪽 빌드가 같은 셸을 쓴다.
 *
 * 주입은 **명시적 호출**이다 — import 부작용으로 등록하면 어느 파일이 등록했는지가 코드에서
 * 안 보이고 트리 셰이킹에 따라 조용히 빠진다(`canvas/registry.ts` 의 같은 주석).
 * **렌더 전에** 부른다. 늦으면 이번 세션에는 안 돈다.
 */

/** ① 뷰 노드 렌더러 4종 (260903 — 노드 캔버스 1단계). 단독은 팔레트가 빈다. */
registerViewNodes(VIEW_NODE_RENDERERS);

/**
 * ② 구역 축 구독과 외부 AI 실패 알림. **이것이 「대시보드 데이터 계층」이고 측정축 D 가
 * 섞이면 안 된다고 말하는 바로 그 부하다.** 이름 있는 함수를 그대로 넘긴다 — 익명 화살표로
 * 감싸면 HMR 중복 등록 방어가 무력해진다(`shared/appServices.ts`).
 */
registerAppService(startTabsServices);

/** ③ 임무 다리가 받은 봉투를 대시보드 저장소에도 넣는다. 단독은 그 저장소가 없다. */
registerEnvelopeSink(store.apply);

/**
 * ④ 관측 보고서의 `build` 표식. **셸이 아니라 여기서 찍는다** (260916).
 * 뜻이 「셸이 붙었는가」가 아니라 **「위 ②가 실렸는가」**이기 때문이다 — 셸은 이제 양쪽에 있다.
 */
markIntegratedBuild();

function IntegratedApp() {
  const [navigation, setNavigation] = useState<DebuggerNavigation>({ screen: 'milestones', requestId: 0 });
  const request = (screen: DebuggerNavigation['screen'], node?: DebuggerNavigation['node']) =>
    setNavigation((current) => ({ screen, node, requestId: current.requestId + 1 }));
  return <AppShell
    // VZ-U-07 승인·거부는 **탭① 안에서** 동작한다. 구 「임무 승인·진행」 탭이 통폐합된 자리다.
    // 프롭으로 주입하는 이유는 main.tsx 의 주석에 있다 (단독 빌드 오염 방지).
    debuggerView={<MissionDebugger navigation={navigation} planApproval={<PlanApproval />} />}
    onDebuggerHome={() => request('milestones')}
    onMissionHistory={() => request('replay')}
    // 대본 띠의 「○○ 노드로」 (260903 3단계). 셸은 캔버스 안을 모른 채 요청만 넣고,
    // 캔버스가 그 태스크의 마일스톤으로 옮겨 가 노드를 만들거나 하이라이트한다.
    onOpenNode={(kind, taskId) => request('node', { kind, taskId })} />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><IntegratedApp /></StrictMode>);
