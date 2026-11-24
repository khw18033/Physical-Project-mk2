/**
 * src/detect/scan/ScanDetectViews.tsx (261123 신설 — 스캔 탐지를 data_stream 으로 · S5 · S7)
 *
 * 새 흐름(`scan-detect`) 노드 상세에 붙는 것. 옛 `DetectViews.tsx` 는 그대로 둔다 — 창구도 모양도 다르다.
 *
 *   T-A0      준비 — 창구 주소 · 소스 · 대상 · @ 질의(원문 → 영어) · 상태
 *   T-A3      여덟 각도 한 줄 요약
 *   T-A4-n    그 각도의 대표 그림 — mark 전 빈 칸 · 수집됨(원본) · 결과 뒤 찾음(overlay · 초록) / 아님(원본 · 이유) · 받지 못함(주황)
 *   T-A5·A6   위치(방위 · 거리 · 거리 출처 · 측정 전 하한) · 근거 표 · 이유 · 대상 그림
 *   T-B1·B2   경로(회전 · 직진 · 회전 오차 보정) · 정지 거리 칸(바꾸면 다시 센다 · 261124) · 승인 대기면 「이동」 버튼
 *
 * 그림은 data_stream 창구(`/scan/frame`)에서 받는다 — 로봇 MQTT 프레임에 기대지 않으므로 어느 장치든 같다.
 * 단서 이름은 data_stream 이 영어로 주므로, 사전에 있는 이름만 옮기고 없으면 영어 그대로 둔다.
 */

import { useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { getLang, useLang } from '../../shared/language.ts';
import { currentMission } from '../../data/scenario.ts';
import {
  SCAN_STOP_RANGE, issueScanApproach, scanStopDistance, scanStopEdited, setScanStopDistance, useScanApproach, useScanStopVersion,
} from '../../physical/scanApproachRun.ts';
import { scanClient } from './ScanClient.ts';
import { frameResultAt, useScanRun, type ScanAngle, type ScanRunState } from './scanStore.ts';

const ANGLE_TASK = /^T-A4-(\d+)$/;

/** 단서 이름(영어) → 사전 키. data_stream 계획 §3.1 의 런처 이름이다. 없는 것은 영어 그대로. */
const CUE_KEYS: Record<string, string> = {
  detector: 'sd.cue.detector', class: 'sd.cue.detector', semantic: 'sd.cue.semantic', 'text description': 'sd.cue.semantic',
  dict_features: 'sd.cue.dict', 'feature dictionary': 'sd.cue.dict', match: 'sd.cue.match', 'reference photo': 'sd.cue.match',
  shape: 'sd.cue.shape', colour: 'sd.cue.colour', 'clip colour': 'sd.cue.clipColour', 'clip shape': 'sd.cue.clipShape',
  saturation: 'sd.cue.saturation', hue: 'sd.cue.hue', aspect: 'sd.cue.aspect', 'ovd pair iou': 'sd.cue.ovdPair',
  ground: 'sd.cue.ground', size_veto: 'sd.cue.sizeVeto', 'size veto': 'sd.cue.sizeVeto', lookalike: 'sd.cue.lookalike',
};

function cueName(name: string): string {
  if (getLang() !== 'ko') return name;
  const key = CUE_KEYS[name.trim().toLowerCase()];
  return key === undefined ? name : t(key);
}

function angleImage(run: ScanRunState, angle: ScanAngle): { url: string | null; tone: string; label: string } {
  if (angle.captured === null) return { url: null, tone: 'empty', label: t('sd.angle.empty') };
  if (angle.captured === false) return { url: null, tone: 'missed', label: t('sd.angle.missed') };
  const client = scanClient(run.base);
  const frame = frameResultAt(run, angle.deg);
  if (frame === null) return { url: client.frameUrl(run.scanId, angle.deg, 'original'), tone: 'captured', label: t('sd.angle.captured') };
  if (frame.found) {
    return { url: client.frameUrl(run.scanId, angle.deg, 'overlay'), tone: 'found', label: t('sd.angle.found', { score: frame.score ?? '–' }) };
  }
  return { url: client.frameUrl(run.scanId, angle.deg, 'original'), tone: 'not', label: frame.reason ?? t('sd.angle.notFound') };
}

const fmt = (value: number | null | undefined, digits = 1) => (value === null || value === undefined ? '–' : value.toFixed(digits));

function Prepare({ run }: { run: ScanRunState }) {
  useLang();
  return <dl className="scan-facts">
    <dt>{t('sd.f.base')}</dt><dd><code>{run.base || '–'}</code></dd>
    <dt>{t('sd.f.stream')}</dt><dd>{run.stream ?? '–'}</dd>
    <dt>{t('sd.f.targets')}</dt><dd>{run.targets.length > 0 ? run.targets.join(', ') : run.target}</dd>
    {run.queryKo !== null && <><dt>{t('sd.f.query')}</dt><dd>{run.queryKo} → {run.query ?? '…'}</dd></>}
    <dt>{t('sd.f.state')}</dt><dd>{run.serverState ?? '…'}{run.profileVersion !== null && ` · profile ${run.profileVersion}`}</dd>
  </dl>;
}

function Angle({ run, index }: { run: ScanRunState; index: number }) {
  useLang();
  const angle = run.angles[index];
  if (angle === undefined) return null;
  const view = angleImage(run, angle);
  return <figure className={`scan-angle scan-angle--${view.tone}`}>
    {view.url !== null ? <img src={view.url} alt={t('sd.angle.alt', { deg: angle.deg })} /> : <div className="scan-angle__blank" />}
    <figcaption>{angle.deg}° · {view.label}{angle.frameN !== null && ` · #${angle.frameN}`}</figcaption>
  </figure>;
}

function Sweep({ run }: { run: ScanRunState }) {
  useLang();
  return <div className="scan-sweep">
    {run.angles.map((angle) => <Angle key={angle.index} run={run} index={angle.index} />)}
  </div>;
}

function Evidence({ run }: { run: ScanRunState }) {
  useLang();
  const result = run.result;
  if (result === null) return <p className="scan-facts__wait">{t('sd.waitResult')}</p>;
  const best = result.best;
  const client = scanClient(run.base);
  return <div className="scan-evidence">
    <p>{result.reason}</p>
    {best === null
      ? <p className="scan-facts__bad">{t('sd.notFound')}</p>
      : <dl className="scan-facts">
        <dt>{t('sd.f.bearing')}</dt><dd>{fmt(best.bearing_deg)}° ({t('sd.f.atAngle', { deg: best.rotation_deg })})</dd>
        <dt>{t('sd.f.distance')}</dt><dd>{fmt(best.distance_m, 2)} m · {best.distance_source ?? '–'}{!best.distance_valid && ` · ${t('sd.f.distanceInvalid')}${best.distance_note ? ` (${best.distance_note})` : ''}`}</dd>
        {best.provisional && <><dt>{t('sd.f.threshold')}</dt><dd>{t('sd.f.provisional')}</dd></>}
        {result.score_basis !== null && <><dt>{t('sd.f.basis')}</dt><dd>{t(`sd.f.basis.${result.score_basis}`)}</dd></>}
      </dl>}
    {result.cues.length > 0 && <table className="scan-cues">
      <tbody>{result.cues.map((cue, i) => <tr key={i}><th>{cueName(cue.name)}</th><td>{fmt(cue.value, 2)}</td><td>{cue.note}</td></tr>)}</tbody>
    </table>}
    {best !== null && <img className="scan-evidence__crop" src={client.frameUrl(run.scanId, best.rotation_deg, 'crop')} alt={t('sd.cropAlt')} />}
  </div>;
}

/**
 * **정지 거리 칸** (261124 — 실물 Go1 시험). 대상 앞 몇 m 에서 설지. 결과 전에 바꿔 두면 그 값으로 세고, 결과 뒤(이동 전)에
 * 바꾸면 그 자리에서 다시 센다 — 다시 센 경로는 「이 경로로 이동」을 눌러야 나간다. 이동이 나간 뒤에는 잠근다.
 */
function StopDistanceField({ missionId, locked }: { missionId: string; locked: boolean }) {
  useLang();
  useScanStopVersion();
  const value = scanStopDistance(missionId, (currentMission().params as Record<string, unknown>).stop_distance_max_m);
  const [text, setText] = useState<string | null>(null);
  const [bad, setBad] = useState(false);
  const apply = () => {
    if (text === null) return;
    const meters = Number(text.trim().replace(',', '.'));
    const ok = text.trim() !== '' && setScanStopDistance(missionId, meters);
    setBad(!ok);
    if (ok) setText(null);
  };
  return <div className="scan-stop">
    <label title={locked ? t('sd.stop.locked') : t('sd.stop.title')}>
      <span>{t('sd.stop.label')}</span>
      <input
        type="number" inputMode="decimal" step={0.05} min={SCAN_STOP_RANGE.min} max={SCAN_STOP_RANGE.max} disabled={locked}
        value={text ?? String(value)}
        onChange={(event) => { setText(event.target.value); setBad(false); }}
        onBlur={apply}
        onKeyDown={(event) => { if (event.key === 'Enter') apply(); }}
      /> m
      {scanStopEdited(missionId) && <small>{t('sd.stop.edited')}</small>}
    </label>
    {bad && <p className="scan-facts__bad">{t('sd.stop.bad', { min: SCAN_STOP_RANGE.min, max: SCAN_STOP_RANGE.max })}</p>}
  </div>;
}

function Approach({ missionId }: { missionId: string }) {
  useLang();
  const approach = useScanApproach();
  const field = <StopDistanceField missionId={missionId} locked={approach?.issued === true} />;
  if (approach === null) return <div>{field}<p className="scan-facts__wait">{t('sd.waitPlan')}</p></div>;
  const { plan } = approach;
  if (!plan.ok) return <div>{field}<p className="scan-facts__bad">{t(plan.reason.key, plan.reason.vars)}</p></div>;
  return <div>
    {field}
    <dl className="scan-facts">
      <dt>{t('sd.f.turn')}</dt><dd>{fmt(plan.turnDeg)}° ({t('sd.f.bearing')} {fmt(plan.bearingDeg)}° − {t('sd.f.drift')} {plan.driftDeg === null ? t('sd.f.noDrift') : `${fmt(plan.driftDeg)}°`})</dd>
      <dt>{t('sd.f.forward')}</dt><dd>{fmt(plan.issuedForwardM, 2)} m{plan.issuedForwardM !== plan.plannedForwardM && ` (${t('sd.f.planned')} ${fmt(plan.plannedForwardM, 2)} m)`} · vx {plan.forwardVx}</dd>
    </dl>
    {plan.notes.length > 0 && <ul>{plan.notes.map((note, i) => <li key={i}>{t(note.key, note.vars)}</li>)}</ul>}
    {approach.waitingApproval && !approach.issued && <button type="button" className="scan-approve" onClick={() => { void issueScanApproach(); }}>{t('sd.approve')}</button>}
    {approach.issued && <p>{t('sd.issued')}</p>}
  </div>;
}

export function ScanDetectFacts({ taskId }: { taskId: string }) {
  useLang();
  const run = useScanRun();
  if (run === null) {
    // 판 전에도 정지 거리는 미리 바꿔 둘 수 있다 — 그 값으로 센다.
    if (taskId === 'T-B1' || taskId === 'T-B2') {
      return <section className="scan-detect">
        <h4>{t('sd.title')}</h4>
        <StopDistanceField missionId={currentMission().missionId} locked={false} />
        <p className="scan-facts__wait">{t('sd.notStarted')}</p>
      </section>;
    }
    return <p className="scan-facts__wait">{t('sd.notStarted')}</p>;
  }
  const failure = run.failure === null ? null : <p className="scan-facts__bad">{t('sd.failed', { stage: run.failure.stage, code: run.failure.code, detail: run.failure.detail })}</p>;
  const angle = ANGLE_TASK.exec(taskId);
  let body = null;
  if (taskId === 'T-A0') body = <Prepare run={run} />;
  else if (taskId === 'T-A3') body = <Sweep run={run} />;
  else if (angle !== null) body = <Angle run={run} index={Number(angle[1])} />;
  else if (taskId === 'T-A5' || taskId === 'T-A6') body = <Evidence run={run} />;
  else if (taskId === 'T-B1' || taskId === 'T-B2') body = <Approach missionId={run.missionId} />;
  if (body === null && failure === null) return null;
  return <section className="scan-detect">
    <h4>{t('sd.title')}</h4>
    {failure}
    {body}
  </section>;
}

// ── 팔레트 뷰 노드 (`detect-cam` · `detect-reason` — 새 흐름 편에서) ──────────────────

/** 크게 볼 각도: 고른 것 > 결과의 best > 마지막으로 수집한 각도. */
function focusAngle(run: ScanRunState, picked: number | null): ScanAngle | null {
  if (picked !== null && run.angles[picked] !== undefined) return run.angles[picked];
  const best = run.result?.best ?? null;
  if (best !== null) return run.angles.find((angle) => angle.deg === best.rotation_deg) ?? null;
  const seen = run.angles.filter((angle) => angle.captured !== null);
  return seen.length > 0 ? seen[seen.length - 1] : null;
}

/** 탐지 영상 노드 — 지금 보는(또는 찾은) 각도를 크게, 아래에 여덟 각도. 각도를 누르면 그 각도를 크게, 한 번 더 누르면 원래대로. */
export function ScanSweepNode({ zoom = false }: { zoom?: boolean }) {
  useLang();
  const run = useScanRun();
  const [picked, setPicked] = useState<number | null>(null);
  if (run === null) return <p className="scan-facts__wait">{t('sd.notStarted')}</p>;
  const focus = focusAngle(run, picked);
  return <div className={`scan-node${zoom ? ' scan-node--zoom' : ''}`}>
    {focus === null ? <p className="scan-facts__wait">{t('sd.angle.empty')}</p> : <Angle run={run} index={focus.index} />}
    <div className="scan-strip">
      {run.angles.map((angle) => {
        const view = angleImage(run, angle);
        return <button key={angle.index} type="button" className={`scan-strip__cell scan-angle--${view.tone}${focus?.index === angle.index ? ' is-focus' : ''}`}
          title={`${angle.deg}° · ${view.label}`} onClick={() => setPicked(picked === angle.index ? null : angle.index)}>
          {view.url !== null ? <img src={view.url} alt={t('sd.angle.alt', { deg: angle.deg })} /> : <span>{angle.deg}°</span>}
        </button>;
      })}
    </div>
    {run.failure !== null && <p className="scan-facts__bad">{t('sd.failed', { stage: run.failure.stage, code: run.failure.code, detail: run.failure.detail })}</p>}
  </div>;
}

/** 판단 근거 노드 — 위치 · 단서 표 · 대상 그림. */
export function ScanReasonNode({ zoom = false }: { zoom?: boolean }) {
  useLang();
  const run = useScanRun();
  if (run === null) return <p className="scan-facts__wait">{t('sd.notStarted')}</p>;
  return <div className={`scan-node${zoom ? ' scan-node--zoom' : ''}`}>
    {run.failure !== null && <p className="scan-facts__bad">{t('sd.failed', { stage: run.failure.stage, code: run.failure.code, detail: run.failure.detail })}</p>}
    <Evidence run={run} />
  </div>;
}
