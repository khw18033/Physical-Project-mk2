import { scenario } from '../data/scenario.ts';
import type { Hardware } from '../model/types.ts';

/** 모든 탭이 같은 배정 원천을 보도록 하는 레지스트리 경계. */
export function listRegisteredHardware(): readonly Hardware[] {
  return scenario.hardware;
}
