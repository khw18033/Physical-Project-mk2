import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MissionDebugger, type DebuggerNavigation } from './main.tsx';
import { AppShell } from './shell/AppShell.tsx';
import './style.css';

function IntegratedApp() {
  const [navigation, setNavigation] = useState<DebuggerNavigation>({ screen: 'milestones', requestId: 0 });
  const request = (screen: DebuggerNavigation['screen']) => setNavigation((current) => ({ screen, requestId: current.requestId + 1 }));
  return <AppShell debuggerView={<MissionDebugger navigation={navigation} />} onDebuggerHome={() => request('milestones')} onMissionHistory={() => request('replay')} />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><IntegratedApp /></StrictMode>);
