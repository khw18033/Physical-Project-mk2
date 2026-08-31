import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MissionDebugger, type DebuggerNavigation } from './main.tsx';
import { AppShell } from './shell/AppShell.tsx';
import { PlanApproval } from './tabs/index.tsx';
import './style.css';

function IntegratedApp() {
  const [navigation, setNavigation] = useState<DebuggerNavigation>({ screen: 'milestones', requestId: 0 });
  const request = (screen: DebuggerNavigation['screen']) => setNavigation((current) => ({ screen, requestId: current.requestId + 1 }));
  return <AppShell
    // VZ-U-07 승인·거부는 **탭① 안에서** 동작한다. 구 「임무 승인·진행」 탭이 통폐합된 자리다.
    // 프롭으로 주입하는 이유는 main.tsx 의 주석에 있다 (단독 빌드 오염 방지).
    debuggerView={<MissionDebugger navigation={navigation} planApproval={<PlanApproval />} />}
    onDebuggerHome={() => request('milestones')}
    onMissionHistory={() => request('replay')} />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><IntegratedApp /></StrictMode>);
