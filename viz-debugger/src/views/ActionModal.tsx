import { useState } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import type { MissionView } from '../data/scenario.ts';
import type { Hardware, Task } from '../model/types.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { STATE_STYLE } from '../graph/stateStyle.ts';

export function ActionModal({ task, view, device, failure, onClose }: { task: Task; view: MissionView; device?: Hardware; failure?: boolean; onClose(): void }) {
  const [speed, setSpeed] = useState('0.35'); const [clearance, setClearance] = useState('0.18');
  const action = (kind: string) => void issueCommand({ action: kind, entity: task.id, params: { speed, clearance } });
  // 대본(registry 세계)의 평가는 대본 파일에서 읽는다 — 기준은 task.evaluation, 근거값은
  // 기록 열의 payload (예: MS-E 의 distance_m: 2.7). 옛 편은 전달본의 목 문구 그대로다.
  const evidence = view.world === 'registry'
    ? view.events.filter((e) => e.nodeId === task.id && e.payload && Object.keys(e.payload).length > 0).at(-1)?.payload ?? null
    : null;
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className={`modal ${failure ? 'failure-modal' : ''}`}>
    <header><div><h2>{failure ? '× ' : ''}{task.id} · {task.title}{failure ? ' — 실패' : ''}</h2><small>액션 아이템 {task.actionItems.length}건 · target {task.target ?? '없음'} · attempt {failure ? 1 : 2}</small></div><button onClick={onClose}>닫기</button></header>
    {failure ? <div className="failure-reason"><b>실패 사유</b><p>진입 중 측면 클리어런스 0.06 m &lt; 최소 0.12 m — 진입 속도가 과다했습니다. 로봇 상태는 정상이었습니다.</p></div> : device && <PendingSource id="robot-status-strip" minHeight={104}><div className="device-strip"><b>{device.id}<small>{device.kind} · {device.connection}</small></b><span>배터리<strong>{device.battery}%</strong></span><span>네트워크<strong>{device.rssi} dBm · {device.latency} ms</strong></span><span>IP<strong>{device.ip}</strong></span><span>펌웨어<strong>{device.firmware}</strong></span><span>관절 온도<strong>{device.temperature} °C</strong></span><span>하트비트<strong>{device.heartbeat}</strong></span></div></PendingSource>}
    {failure ? <div className="parameter-form"><label>진입 속도<input value={speed} onChange={(event) => setSpeed(event.target.value)} /> m/s</label><label>최소 클리어런스<input value={clearance} onChange={(event) => setClearance(event.target.value)} /> m</label></div> : <div className="modal-grid"><table><thead><tr><th>#</th><th>액션 아이템</th><th>파라미터</th><th>상태</th></tr></thead><tbody>{task.actionItems.map((item, index) => <tr key={item.id}><td>{index + 1}</td><td><b>{item.label}</b><small>{item.id}</small></td><td><code>{Object.entries(item.params).map(([key, value]) => `${key}: ${value}`).join(' · ') || '없음'}</code></td><td>{STATE_STYLE[item.status].label}</td></tr>)}</tbody></table><aside>{view.world === 'registry'
      ? <><h3>평가 · Evaluation</h3>{task.evaluation
          ? task.evaluation.criteria.map((criterion) => <p key={criterion}>✓ {criterion} <small>판정 {task.evaluation!.judgedBy}</small></p>)
          : <p>평가 기준 없는 태스크 — 평가로 끝나는 태스크가 아닙니다</p>}
        <h3>근거값 · TraceEvent payload</h3>
        {evidence
          ? <code>{Object.entries(evidence).map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join('\n')}</code>
          : <p>아직 근거가 도달하지 않았습니다 — 근거 없이 통과로 승격하지 않습니다 (REQ-1505)</p>}</>
      : <><h3>평가 · Evaluation</h3><p>✓ 도착 오차 ≤ 0.20 m</p><p>✓ 헤딩 오차 ≤ 5.0°</p><p>◌ 장애물 미접촉 판정 중</p><h3>TraceEvent · 메모리</h3><code>dispatched ai<br />acked backend<br />started backend<br />evaluated backend</code></>}</aside></div>}
    <footer><span>모든 조작은 produced_by=human으로 기록됩니다.</span><button onClick={() => action('counterfactual_run')}>반사실 재실행</button><button onClick={() => action(failure ? 'derived_rerun' : 'single_action_run')}>{failure ? '수정 후 재실행' : '단독 재실행'}</button></footer>
  </section></div>;
}
