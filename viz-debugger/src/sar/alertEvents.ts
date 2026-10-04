/**
 * src/sar/alertEvents.ts (261004 — 드론 파트 · 알림) — 이전 · 지금 보고를 견줘 「생긴 일」을 뽑는다. 그리는 쪽은 `alerts.tsx`.
 * JSX 없는 순수 함수라 verify:sar 가 node 로 바로 시험한다.
 */

export type AlertLevel = 'info' | 'good' | 'warn' | 'bad';
export type AlertEvent = { key: string; level: AlertLevel; textKey: string; vars?: Record<string, string | number> };

/** 이전 · 지금 보고를 견줘 생긴 일. 순수 함수 — verify:sar 가 시험한다. */
export type Snapshot = {
  state: string | null; capturing: boolean; stale: boolean; passes: { passNo: number; valid: boolean | null }[];
  radar: 'good' | 'warn' | 'bad' | null; batteryPct: number | null; imagesDone: number;
};

export function detectEvents(device: string, prev: Snapshot | undefined, cur: Snapshot): AlertEvent[] {
  if (prev === undefined) return [];
  const out: AlertEvent[] = [];
  const k = (s: string) => `${device}:${s}`;
  if (!prev.stale && cur.stale) out.push({ key: k('stale'), level: 'bad', textKey: 'alert.stale', vars: { id: device } });
  if (prev.stale && !cur.stale) out.push({ key: k('back'), level: 'good', textKey: 'alert.back', vars: { id: device } });
  if (!prev.capturing && cur.capturing) out.push({ key: k('capOn'), level: 'info', textKey: 'alert.capOn' });
  if (prev.capturing && !cur.capturing) out.push({ key: k('capOff'), level: 'info', textKey: 'alert.capOff' });
  for (const p of cur.passes) {
    const before = prev.passes.find((x) => x.passNo === p.passNo);
    if (p.valid === false && before?.valid !== false) out.push({ key: k(`bad${p.passNo}`), level: 'warn', textKey: 'alert.passBad', vars: { n: p.passNo } });
    if (p.valid === true && before?.valid !== true) out.push({ key: k(`ok${p.passNo}`), level: 'good', textKey: 'alert.passOk', vars: { n: p.passNo } });
  }
  if (cur.state !== prev.state && (cur.state === 'done' || cur.state === 'incomplete' || cur.state === 'aborted' || cur.state === 'failed')) {
    out.push({ key: k(`end-${cur.state}`), level: cur.state === 'done' ? 'good' : cur.state === 'incomplete' ? 'warn' : 'bad', textKey: `alert.end.${cur.state}` });
  }
  if (cur.radar === 'bad' && prev.radar !== 'bad') out.push({ key: k('radarBad'), level: 'bad', textKey: 'alert.radarBad' });
  const low = (v: number | null, th: number) => v !== null && v < th;
  if (low(cur.batteryPct, 20) && !low(prev.batteryPct, 20)) out.push({ key: k('bat20'), level: 'bad', textKey: 'alert.battery', vars: { pct: Math.round(cur.batteryPct!) } });
  else if (low(cur.batteryPct, 30) && !low(prev.batteryPct, 30)) out.push({ key: k('bat30'), level: 'warn', textKey: 'alert.battery', vars: { pct: Math.round(cur.batteryPct!) } });
  if (cur.imagesDone > prev.imagesDone) out.push({ key: k(`img${cur.imagesDone}`), level: 'good', textKey: 'alert.image' });
  return out;
}

