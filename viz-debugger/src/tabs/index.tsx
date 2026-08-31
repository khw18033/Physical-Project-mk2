/**
 * src/tabs/index.tsx
 *
 * 탭②~⑥의 출입구. **통합 셸은 여기서만 import 한다.**
 *
 * 이 파일이 있는 이유는 셸이 이식한 화면 다섯 개를 각각 알 필요가 없기 때문이고,
 * 더 중요하게는 **탭① 단독 빌드가 이 경계 밖에 있다**는 것을 코드로 보이기 위해서다.
 * `verify:standalone` 은 단독 진입점의 의존 그래프에 `tabs/` 가 나타나면 실패한다.
 *
 * 데이터 계층 기동도 여기서 한 번만 한다 — 원본 `web-dashboard/src/App.tsx` 와 같은 이유로
 * **탭을 옮겨도 구독을 끊지 않는다.** 끊으면 돌아왔을 때 화면이 비고, 평시 1분 주기 센서는
 * 최대 1분간 빈 칸이 된다.
 */

import { useEffect } from 'react';
import { useAiFailureNotifications } from './aiFailureBridge.ts';
import { startDataLayer } from './data/index.ts';
import { useConnectionStatus } from './data/hooks.ts';
import { ControlPanel } from './views/ControlPanel.tsx';
import { DeviceGrid } from './views/DeviceGrid.tsx';
import { MetricsView } from './views/MetricsView.tsx';
import { NodeGraphView } from './views/NodeGraphView.tsx';
import { RiskPanel } from './views/RiskPanel.tsx';
import { VideoOverlayView } from './views/VideoOverlayView.tsx';
import './views/styles.css';

export { PlanApproval } from './views/PlanApproval.tsx';

/** 현재 설계 전제는 구역 1개 (VZ-C-05). */
const ZONE_ID = 'zone-503';

/**
 * 데이터 계층 기동. 앱 수명과 같다 — 탭 전환으로 구독을 끊지 않는다.
 * 셸이 최상위에서 한 번 부른다. 두 번 불려도 `startDataLayer` 가 스스로 막는다.
 */
export function useTabsDataLayer() {
  useEffect(() => startDataLayer(ZONE_ID), []);
  // VZ-I-10 — 외부 AI 실패는 탭 하나가 아니라 **상단 공통 알림**으로 올라간다.
  useAiFailureNotifications();
  return useConnectionStatus();
}

/** 셸이 그리는 탭 본문. 탭① 은 여기 없다 — 그건 셸이 프롭으로 받는다. */
export function TabView({ tab }: { tab: 'overview' | 'control' | 'metrics' | 'video' | 'pipeline' }) {
  // 구 「판단·알림」 탭의 위험도·표시 깊이가 탭② 위쪽으로 들어왔다 (VZ-I-08 · VZ-U-03).
  if (tab === 'overview') return <><RiskPanel /><DeviceGrid /></>;
  if (tab === 'control') return <ControlPanel />;
  if (tab === 'metrics') return <MetricsView />;
  // 탭을 떠나면 언마운트되어 프레임 루프가 멈추고 서버 발행도 멈춘다 (VZ-I-06).
  if (tab === 'video') return <VideoOverlayView />;
  return <NodeGraphView />;
}
