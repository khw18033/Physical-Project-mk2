import { scenario } from '../data/scenario.ts';
import type { Hardware } from '../model/types.ts';

/**
 * 모든 탭이 같은 배정 원천을 보도록 하는 레지스트리 경계.
 *
 * **탭①의 원천은 임무 시나리오이고, 탭②~⑥의 원천은 게이트웨이가 내려주는 레지스트리다.**
 * 화면이 `scenario.hardware`를 직접 읽으면 그 사실이 코드에서 보이지 않고, 나중에 둘을
 * 합칠 때 고쳐야 할 곳을 셀 수가 없다. 그래서 탭①의 접근을 이 함수 하나로 모은다.
 *
 * **지금 두 원천은 서로 다른 장비 목록을 담고 있다** — 시나리오는 이동 로봇(`go1-02` 등)이고
 * `registry.json`은 구역 설비(`robot-01`·`sensor-04`·`actuator-01` 등)다. 목 데이터가
 * 다른 세계라서 그렇다. 합치려면 임무 시나리오를 registry.json 위에 다시 쓰거나 그 반대인데,
 * 둘 다 이식의 범위를 넘고 탭①의 HCI 전달본을 바꾸는 일이라 **혼자 정하지 않았다.**
 * 판단 근거는 `reports/2026-08-28_1900_탭이식.md` §레지스트리 원천에 있다.
 */
export function listRegisteredHardware(): readonly Hardware[] {
  return scenario.hardware;
}

/** 이 목록이 어디서 왔는가. 화면이 목임을 감추지 않기 위해 표시한다. */
export function hardwareSourceLabel(): string {
  return `임무 시나리오 ${scenario.missionId} (목)`;
}
