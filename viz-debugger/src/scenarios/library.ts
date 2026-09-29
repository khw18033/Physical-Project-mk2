/**
 * src/scenarios/library.ts
 *
 * **브라우저용** 대본 라이브러리 — 대본 다섯 편과 옛 편 사이드카를 번들에 싣는다.
 *
 * 단독 빌드(게이트웨이 없음)에서도 문장 → 탭① 전환이 동작해야 하므로(지시서 §흐름)
 * 대본이 번들에 들어간다. 번들 크기 전후는 보고서에 기록한다(논문 측정축 D).
 *
 * 게이트웨이는 같은 JSON 파일을 readFileSync 로 읽는다(`gateway/script-engine.ts`) —
 * Node ESM 의 JSON import 제약 때문에 적재 경로만 다르고, **목록은 manifest.ts,
 * 매칭은 matcher.ts 하나**를 같이 쓴다. 아래 기동 검사가 목록과 실물의 어긋남을 잡는다.
 */

import legacySidecar from '../../scenarios/MSN-260826-01.match.json' with { type: 'json' };
import script01 from '../../scenarios/MSN-260831-01.json' with { type: 'json' };
import script02 from '../../scenarios/MSN-260831-02.json' with { type: 'json' };
import script03 from '../../scenarios/MSN-260831-03.json' with { type: 'json' };
import script04 from '../../scenarios/MSN-260909-01.json' with { type: 'json' };
import script05 from '../../scenarios/MSN-260915-01.json' with { type: 'json' };
import script06 from '../../scenarios/MSN-260927-01.json' with { type: 'json' };
import script07 from '../../scenarios/MSN-260929-01.json' with { type: 'json' };
import { LEGACY_ID, SCRIPT_IDS } from './manifest.ts';
import type { ScriptLibraryEntry, ScriptScenario } from './types.ts';

const scripts = [script01, script02, script03, script04, script05, script06, script07] as unknown as ScriptScenario[];

// 목록(manifest)과 실물(import)의 대조 — 대본을 더할 때 한쪽만 늘면 여기서 즉시 죽는다.
{
  const imported = scripts.map((s) => s.missionId).join(',');
  const listed = SCRIPT_IDS.join(',');
  if (imported !== listed) {
    throw new Error('대본 라이브러리 불일치 — manifest [' + listed + '] vs import [' + imported + ']');
  }
  if ((legacySidecar as { missionId: string }).missionId !== LEGACY_ID) {
    throw new Error('옛 편 사이드카의 missionId 가 manifest 와 다르다');
  }
}

export const SCRIPT_LIBRARY: readonly ScriptLibraryEntry[] = [
  ...scripts.map((script) => ({
    missionId: script.missionId,
    world: 'registry' as const,
    match: script.match,
    script,
  })),
  {
    missionId: LEGACY_ID,
    world: 'legacy' as const,
    match: (legacySidecar as { match: ScriptLibraryEntry['match'] }).match,
    // legacy 편의 본문은 기존 경로(src/data/scenario.ts 의 번들 Scenario)가 갖고 있다.
    script: null,
  },
];

export function libraryEntry(missionId: string): ScriptLibraryEntry | null {
  return SCRIPT_LIBRARY.find((entry) => entry.missionId === missionId) ?? null;
}

/**
 * **대본 재생이 모는 registry 편인가** (260915 — 자율주행 편 · `driver: 'script'`).
 *
 * 참이면 그 편은 옛 편처럼 돈다 — 게이트웨이의 합성 진행을 받고 시나리오 모드로 들어가며,
 * **승인이 로봇 관문을 안 연다.** 로봇 경로(준비 · 스캔 · 접근)는 전부 문 찾기 편의 태스크에
 * 묶여 있어서, 관문이 열리면 「임무 시작」 한 번에 `scan_mission` 이 실물 로봇으로 나간다.
 *
 * 선언이 없는 편은 지금까지와 한 줄도 다르지 않다. 옛 편은 이 함수가 아니라 `world` 로 가른다.
 */
export function scriptDriven(missionId: string): boolean {
  return libraryEntry(missionId)?.script?.driver === 'script';
}

/**
 * **라즈베리파이 중계가 모는 편인가** (260915 — 자율주행 편 · `driver: 'relay'`).
 *
 * 로봇은 유니티가 몰고 화면은 pi1 이 본 것을 받아 칠한다. 합성 진행을 안 받는 것은 로봇 편과 같고,
 * **승인이 로봇 관문(pi7 명령)을 안 여는 것**은 대본 편과 같다.
 */
export function relayDriven(missionId: string): boolean {
  return libraryEntry(missionId)?.script?.driver === 'relay';
}

/**
 * **이 화면이 진행을 모는 편인가** (260927 — 장치 두 대 편 · `driver: 'local'`).
 *
 * 문 찾기 편처럼 **일반 모드**로 돈다 — 승인은 판을 걸어만 두고, 「▶ 임무 시작」이 진행을 연다. 진행은 화면 안
 * 진행기가 제 시각으로 민다(`data/scenario.ts` 의 `startLocalRun`). 게이트웨이 합성 진행은 안 받는다 —
 * 두 진행이 같은 노드를 칠하면 무엇이 판의 진행인지 모른다.
 */
export function localDriven(missionId: string): boolean {
  return libraryEntry(missionId)?.script?.driver === 'local';
}

/**
 * **장비를 자리로 두는 편인가** (260927 — 장치 두 대 편 · `slots`).
 *
 * 참이면 하드웨어 카드를 마일스톤에 놓는 것이 **자리 배정**이 되고(`data/slots.ts`), 팔레트에 그 편의
 * 뷰 노드(가상 맵 · 카메라 · 객체 탐지 로그)가 선다. 문 찾기 시연의 노드는 이 편에서 꺼낼 일이 없다.
 */
export function slotDriven(missionId: string): boolean {
  return (libraryEntry(missionId)?.script?.slots?.length ?? 0) > 0;
}

/**
 * **승인이 로봇 관문을 여는 편인가.** 관문 뒤의 경로(준비 · 스캔 · 접근)는 문 찾기 편(pi7)의
 * 것이라, 자기 방식으로 도는 편(`script` · `relay`)에서는 열지 않는다. 선언 없는 편은 그대로 연다.
 */
export function opensRobotGate(missionId: string): boolean {
  return doorScanFlow(missionId);
}

/**
 * **문 찾기 흐름을 쓰는 편인가** (260928). 대본이 `robotFlow: 'door-scan'` 을 선언했을 때만 참이다.
 *
 * 로봇 쪽 문 찾기 부품(관문 · 준비 단계 · 스캔 발행 · 탐지 조회)은 전부 이것을 본다. 전에는 「선언이 없으면 연다」
 * 였고, 그래서 체계 전체가 한 임무에 귀속돼 있었다 — 정량 명령 판에서도 도면을 받으러 갔고, 1~3편을 승인하고
 * 시작을 누르면 실물 로봇이 스캔을 돌 수 있었다. 이제 **선언한 편만** 그 흐름을 탄다.
 */
export function doorScanFlow(missionId: string): boolean {
  return libraryEntry(missionId)?.script?.robotFlow === 'door-scan';
}
