/**
 * src/sar/cansarQuick.tsx (261004 — 드론 파트 · 레이더 팀 quick-look)
 *
 * 레이더 팀(CANSAR-2)의 quick-look 을 패스마다 보여 준다. 드론 쪽 데이터 서버가 그쪽 `cansar_quick.py` 를
 * 패스마다 돌리고(sar_data/quick.py) 결과를 `/api/cansar` 로 내준다. 이 카드는 그것을 읽어 띄우기만 한다.
 *
 * 레이더 팀 부탁: 「quick-look」이라고 표시할 것(빠른 확인용이라 거칠다 — 최종은 착륙 뒤 그쪽이 정밀 처리),
 * 판정 줄 · 첨두 줄을 같이 보일 것.
 */

import { useEffect, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';

type QuickItem = {
  n: number; state: 'queued' | 'waiting_capture' | 'running' | 'done' | 'failed'; t0: number | null;
  verdict: string | null; verdict_line: string | null; time_match_s: number | null; warnings?: readonly string[];
  peak: { db: number; along_m: number; side_m: number; background_db: number } | null;
  error?: string | null; duration_s?: number; finished_unix?: number; side?: string;
};
type QuickList = { runner: boolean; missing?: readonly string[]; items: readonly QuickItem[] };

const POLL_MS = 5_000;

function useQuick(base: string): QuickList | null {
  const [list, setList] = useState<QuickList | null>(null);
  useEffect(() => {
    if (base === '') return;
    let alive = true;
    const pull = async () => {
      try {
        const r = await fetch(`${base}/api/cansar`);
        if (!r.ok) { if (alive) setList(null); return; }
        const j = await r.json() as QuickList;
        if (alive) setList({ runner: j.runner === true, missing: j.missing ?? [], items: Array.isArray(j.items) ? j.items : [] });
      } catch { if (alive) setList(null); }
    };
    void pull();
    const id = setInterval(() => void pull(), POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [base]);
  return list;
}

/** 패스마다 레이더 팀 quick-look — 결과가 하나도 없고 설정도 없으면 아무것도 안 그린다. */
export function CansarQuickCard({ base }: { base: string }) {
  useLang();
  const list = useQuick(base);
  const [pick, setPick] = useState<number | null>(null);
  if (list === null) return null;
  if (list.items.length === 0) {
    if (list.runner && (list.missing ?? []).length > 0) {
      return <div className="sar-cq"><b>{t('cq.title')}</b><small className="sar-warn">{t('cq.missing', { what: (list.missing ?? []).join(' · ') })}</small></div>;
    }
    return null;
  }
  const it = list.items.find((x) => x.n === pick) ?? list.items[0]!;
  const dir = `${base}/api/cansar/${it.n}`;
  const okVerdict = it.verdict !== null && /^OK/i.test(it.verdict);
  return <div className="sar-cq">
    <div className="sar-cq-head">
      <b>{t('cq.title')}</b>
      <span className="sar-cq-badge">quick-look</span>
      <label>{t('cq.capture')} <select value={it.n} onChange={(e) => setPick(Number(e.target.value))}>
        {list.items.map((x) => <option key={x.n} value={x.n}>#{x.n} · {t(`cq.state.${x.state}`)}{x.verdict ? ` · ${x.verdict}` : ''}</option>)}
      </select></label>
    </div>
    {it.state !== 'done' && it.state !== 'failed' && <small className="sar-hint">{t(`cq.state.${it.state}`)}</small>}
    {it.state === 'failed' && <small className="sar-bad">{t('cq.failed', { why: it.error ?? '?' })}</small>}
    {it.verdict_line !== null && <div className={okVerdict ? 'sar-ok' : 'sar-warn'}><small>{t('cq.verdict')}</small> {it.verdict_line}</div>}
    {it.peak !== null && <div><small>{t('cq.peak')}</small> {t('cq.peakText', { db: it.peak.db.toFixed(1), a: it.peak.along_m.toFixed(1),
      s: it.peak.side_m.toFixed(1), bg: it.peak.background_db.toFixed(1) })}</div>}
    {it.time_match_s !== null && it.time_match_s > 1 && <small className="sar-warn">{t('cq.timeOff', { s: it.time_match_s.toFixed(2) })}</small>}
    {(it.warnings ?? []).map((w) => <small key={w} className="sar-warn">{w}</small>)}
    {it.state === 'done' && <>
      <a href={`${dir}/quick.png`} target="_blank" rel="noreferrer">
        <img className="sar-cq-img" src={`${dir}/quick.png?v=${it.finished_unix ?? 0}`} alt={t('cq.title')} />
      </a>
      <small className="sar-hint">{t('cq.axes')}</small>
    </>}
    <small className="sar-hint">{t('cq.note')} · <a href={`${dir}/log.txt`} target="_blank" rel="noreferrer">{t('cq.log')}</a>
      {it.state === 'done' && <> · <a href={`${dir}/quick.npz`}>{t('cq.npz')}</a></>}</small>
  </div>;
}
