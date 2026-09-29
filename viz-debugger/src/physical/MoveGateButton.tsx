/**
 * src/physical/MoveGateButton.tsx (260929 신설 — 이상 탐지 편 · Go1 출발 승인)
 *
 * **다음 장치가 출발하기 전에 사람이 본다.** 실행기가 승인 대기를 걸면(`taskRunner.ts` 의 `confirm`) 머리줄에
 * 이 버튼이 뜬다 — 어느 화면(마일스톤 · 노드 캔버스 · 확대)에 있어도 보여야 해서 머리줄이다.
 *
 * 버튼에는 **출발할 장치의 산출 경로**를 적는다(「왼쪽 45° 회전 → 2.00 m 전진」). 앞 장치의 이동이 끝난 것을
 * 눈으로 확인하고, 그 경로를 보고 누른다. 누르기 전까지 앞 장치의 이동 노드는 진행 중으로 남는다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useLocalRun } from '../data/scenario.ts';
import { approveMoveGate, moveGate, subscribeMoveGate } from './taskRunner.ts';

export function MoveGateButton() {
  useLang();
  const phase = useLocalRun();
  const gate = useSyncExternalStore(subscribeMoveGate, moveGate, moveGate);
  if (gate === null) return null;
  const paused = phase !== 'running';
  return <button
    type="button"
    className="move-gate"
    disabled={paused}
    title={paused ? t('gate.paused') : t('gate.title', { device: gate.deviceId ?? gate.slot })}
    onClick={() => { approveMoveGate(); }}
  >
    <b>{t('gate.approve', { device: gate.deviceId ?? gate.slot })}</b>
    {gate.route !== '' && <small> · {gate.route}</small>}
  </button>;
}
