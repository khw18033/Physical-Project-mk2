// SAR 영상 — 데이터 서버(노트북 미러)가 만든 패스별 영상을 보여 준다. drone/sar_data/imaging.py · sar_image/pipeline.py
//
// 「영상 만들기」 → GET …/image?pass=N&cr=… (202 줄 섰다) → image.json 을 2 초마다 다시 읽어
// 리플렉터 둘레(먼저) → 선 전체(뒤) 순으로 나오는 대로 그린다. 위성 지도에 겹쳐 볼 수 있다.

import { useEffect, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { SatMap, type LatLon, type Marker, type Overlay } from '../dronedash/SatMap.tsx';

export type ImageSummary = { state: string | null; error: string | null; reflectors: number; found: number; full: boolean };
export type Imaging = { ready: boolean; missing: string[] } | null;
export type MirrorState = { source: string; last_ok_unix: number | null; last_error: string | null; fetched_passes: number } | null;

type CrResult = {
  name: string; lat: number; lon: number; found: boolean; contrast_db: number; offset_m: number;
  res_along_m: number; res_cross_m: number; in_beam_s: number | null; png: string; scr_db?: number | null; pslr_db?: number | null;
};
type Offset = { dt_s: number; focus_gain_db: number; name: string };
type Quicklook = { png: string; time_offset: { per_reflector: Offset[]; combined: { dt_s: number; spread_s: number; reflectors: number; consistent: boolean | null } | null; applied_s: number } };
type ImageJson = {
  state: 'queued' | 'running' | 'done' | 'failed'; error?: string; pulses?: number; lever_frd_m?: number[]; tilt_motion_mm?: number;
  notes?: string[]; reflectors: CrResult[]; autofocus?: { method: string; reflectors?: number; fallbacks?: string[] } | null;
  full: { png: string; map_png: string; corners: LatLon[]; kmz?: string } | null; timings_s?: Record<string, number>; finished_unix?: number;
  quicklook?: Quicklook;
};

const n1 = (v: number | null | undefined, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—');

/** 요청 주소 — 화면에 놓은 리플렉터를 같이 보낸다(없으면 서버의 reflectors.csv). */
export function imageRequestUrl(base: string, flight: string, pass: number, reflectors: readonly LatLon[], force: boolean): string {
  const cr = reflectors.map((p) => `${p.lat.toFixed(9)},${p.lon.toFixed(9)}`).join(';');
  return `${base}/api/flights/${encodeURIComponent(flight)}/image?pass=${pass}${cr ? `&cr=${encodeURIComponent(cr)}` : ''}${force ? '&force=1' : ''}`;
}

export function ImageButton({ base, flight, pass, summary, imaging, hasRaw, reflectors, onOpen }: {
  base: string; flight: string; pass: number; summary: ImageSummary | null; imaging: Imaging; hasRaw: boolean;
  reflectors: readonly LatLon[]; onOpen: () => void;
}) {
  useLang();
  const [err, setErr] = useState<string | null>(null);
  const can = imaging?.ready === true && hasRaw;
  const make = async () => {
    setErr(null);
    try {
      const r = await fetch(imageRequestUrl(base, flight, pass, reflectors, summary !== null));
      if (!r.ok && r.status !== 202) {
        const b = await r.json().catch(() => ({})) as { error?: string };
        setErr(b.error ?? String(r.status));
        return;
      }
      onOpen();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  return <span className="sar-img-btn">
    {summary !== null && <button type="button" className={`sar-img-chip is-${summary.state ?? 'none'}`} onClick={onOpen}>
      {summary.state === 'done' ? t('img.view') : t(`img.state.${summary.state ?? 'queued'}`)}{summary.reflectors > 0 && ` · ${t('img.found', { f: summary.found, n: summary.reflectors })}`}
    </button>}
    <button type="button" className={`sar-act${summary === null ? ' is-primary' : ''}`} disabled={!can} title={!hasRaw ? t('img.noRaw') : undefined}
      onClick={() => void make()}>{summary === null ? t('img.make') : t('img.remake')}</button>
    {err !== null && <small className="sar-bad">{t('img.reqFail', { why: err })}</small>}
  </span>;
}

export function SarImageView({ base, flight, pass }: { base: string; flight: string; pass: number }) {
  useLang();
  const dir = `${base}/api/flights/${encodeURIComponent(flight)}/images/pass${String(pass).padStart(2, '0')}`;
  const [img, setImg] = useState<ImageJson | null>(null);
  const [fail, setFail] = useState<string | null>(null);
  const [onMap, setOnMap] = useState(true);
  const [opacity, setOpacity] = useState(0.9);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const pull = async () => {
      try {
        const r = await fetch(`${dir}/image.json`, { cache: 'no-store' });
        const b = r.ok ? await r.json() as ImageJson : null;
        if (!alive) return;
        setImg(b);
        setFail(r.ok ? null : String(r.status));
        if (b === null || b.state === 'queued' || b.state === 'running') timer = setTimeout(() => void pull(), 2000);
      } catch (e) {
        if (alive) { setFail(e instanceof Error ? e.message : String(e)); timer = setTimeout(() => void pull(), 4000); }
      }
    };
    void pull();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [dir]);

  if (img === null) return <p className="sar-hint">{fail === null ? t('sar.data.loading') : t('img.reqFail', { why: fail })}</p>;
  const v = `?v=${img.finished_unix ?? img.reflectors.length}`;
  const markers: Marker[] = img.reflectors.map((r) => ({ lat: r.lat, lon: r.lon, kind: 'reflector', label: r.name, tone: r.found ? 'good' : 'bad' }));
  const overlays: Overlay[] = img.full && onMap
    ? [{ url: `${dir}/${img.full.map_png}${v}`, corners: img.full.corners as unknown as Overlay['corners'], opacity }] : [];
  const af = img.autofocus;
  return <div className="sar-img">
    <div className="sar-img-head">
      <b className={`sar-img-chip is-${img.state}`}>{t(`img.state.${img.state}`)}</b>
      {img.pulses !== undefined && <span>{t('img.meta', {
        p: img.pulses, lev: (img.lever_frd_m ?? []).map((x) => x.toFixed(2)).join(', '), tilt: n1(img.tilt_motion_mm),
        sec: n1(img.timings_s?.total ?? null, 0) })}</span>}
      {af !== undefined && <span>{t('img.af', { m: af === null ? t('img.af.off') : t(`img.af.${af.method}`, { n: af.reflectors ?? 0 }) })}</span>}
    </div>
    {img.state === 'failed' && <p className="sar-bad">{img.error}</p>}
    {img.quicklook && <QuickLook dir={dir} v={v} q={img.quicklook} />}
    {(img.notes ?? []).map((nt, i) => <p key={i} className="sar-hint">{nt}</p>)}
    {img.reflectors.length > 0 && <table className="sar-table">
      <thead><tr><th>{t('img.cr.name')}</th><th>{t('img.cr.found')}</th><th>{t('img.cr.contrast')}</th><th>{t('img.cr.offset')}</th>
        <th>{t('img.cr.res')}</th><th>{t('img.cr.scr')}</th><th>{t('img.cr.inBeam')}</th><th /></tr></thead>
      <tbody>{img.reflectors.map((r) => <tr key={r.name} className={r.found ? '' : 'is-missed'}>
        <td>{r.name}</td>
        <td>{r.found ? <span className="sar-ok">{t('img.cr.yes')}</span> : <span className="sar-bad">{t('img.cr.no')}</span>}</td>
        <td>{n1(r.contrast_db, 0)} dB</td>
        <td>{n1(r.offset_m * 100, 1)} cm</td>
        <td>{n1(r.res_along_m * 100, 1)} cm</td>
        <td>{n1(r.scr_db ?? null, 0)} dB</td>
        <td>{n1(r.in_beam_s, 1)} s</td>
        <td><a href={`${dir}/${r.png}${v}`} target="_blank" rel="noreferrer"><img className="sar-img-thumb" src={`${dir}/${r.png}${v}`} alt={r.name} /></a></td>
      </tr>)}</tbody>
    </table>}
    {img.full !== null && <>
      <div className="sar-img-tools">
        <b>{t('img.full')}</b>
        <label className="sar-check"><input type="checkbox" checked={onMap} onChange={(e) => setOnMap(e.target.checked)} />{t('img.map')}</label>
        <label className="sar-check">{t('img.opacity')}<input type="range" min={0.2} max={1} step={0.05} value={opacity}
          onChange={(e) => setOpacity(Number(e.target.value))} /></label>
        <a className="sar-btn" href={`${dir}/${img.full.png}${v}`} target="_blank" rel="noreferrer">{t('img.openPng')}</a>
        {img.full.kmz && <a className="sar-btn" href={`${dir}/${img.full.kmz}${v}`} download title={t('img.kmzHint')}>{t('img.kmz')}</a>}
      </div>
      <SatMap markers={markers} overlays={overlays} height={340} />
      <a href={`${dir}/${img.full.png}${v}`} target="_blank" rel="noreferrer"><img className="sar-img-full" src={`${dir}/${img.full.png}${v}`} alt={t('img.full')} /></a>
    </>}
    {(img.state === 'queued' || img.state === 'running') && <p className="sar-hint">{t('img.wait')}</p>}
  </div>;
}

/** 빠른 확인 — 거리-시간 그림 위 예상 곡선, 리플렉터로 잰 레이더 시각 오프셋. */
function QuickLook({ dir, v, q }: { dir: string; v: string; q: Quicklook }) {
  useLang();
  const c = q.time_offset.combined;
  const ms = (s: number) => (Math.abs(s) < 5e-5 ? 0 : s * 1000).toFixed(1);
  return <div className="sar-quick">
    <div className="sar-img-tools"><b>{t('img.quick')}</b><small>{t('img.quickHint')}</small></div>
    <a href={`${dir}/${q.png}${v}`} target="_blank" rel="noreferrer"><img className="sar-img-full" src={`${dir}/${q.png}${v}`} alt={t('img.quick')} /></a>
    <p className={c === null ? 'sar-hint' : c.consistent === false ? 'sar-warn' : 'sar-ok'}>
      {c === null ? t('img.dt.none')
        : t('img.dt.result', { dt: ms(c.dt_s), n: c.reflectors, spread: ms(c.spread_s) })}
      {' '}{q.time_offset.applied_s !== 0 ? t('img.dt.applied', { dt: ms(q.time_offset.applied_s) })
        : c !== null && Math.abs(c.dt_s) > 0.0015 ? t('img.dt.notApplied') : ''}
    </p>
    {q.time_offset.per_reflector.length > 0 && <small className="sar-hint">
      {q.time_offset.per_reflector.map((p) => t('img.dt.one', { n: p.name, dt: ms(p.dt_s), g: n1(p.focus_gain_db, 1) })).join(' · ')}
    </small>}
  </div>;
}

/** 같은 선 두 패스 비교 — 기준선 · 일치도 · 밝기 변화. */
export function ComparePanel({ base, flight, passes }: { base: string; flight: string; passes: readonly number[] }) {
  useLang();
  const [a, setA] = useState(passes[0] ?? 0);
  const [b, setB] = useState(passes[1] ?? 0);
  const [res, setRes] = useState<{ png: string; dir: string; coherence_bright_median: number; coherence_all_median: number;
    baseline: { cross_mean_m: number; cross_std_m: number; height_mean_m: number; height_std_m: number } } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (passes.length < 2) return null;
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`${base}/api/flights/${encodeURIComponent(flight)}/compare?a=${a}&b=${b}`);
      const j = await r.json();
      if (!r.ok) setErr(j.error ?? String(r.status)); else setRes(j);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return <div className="sar-compare">
    <div className="sar-img-tools">
      <b>{t('img.cmp.title')}</b>
      <label>A <select value={a} onChange={(e) => setA(Number(e.target.value))}>{passes.map((p) => <option key={p} value={p}>{t('sar.data.pass', { n: p })}</option>)}</select></label>
      <label>B <select value={b} onChange={(e) => setB(Number(e.target.value))}>{passes.map((p) => <option key={p} value={p}>{t('sar.data.pass', { n: p })}</option>)}</select></label>
      <button type="button" disabled={busy || a === b} onClick={() => void run()}>{busy ? t('img.state.running') : t('img.cmp.run')}</button>
      {err !== null && <small className="sar-bad">{err}</small>}
    </div>
    {res !== null && <>
      <div className="sar-kpis">
        <div><small>{t('img.cmp.cohBright')}</small><b>{res.coherence_bright_median.toFixed(2)}</b></div>
        <div><small>{t('img.cmp.cohAll')}</small><b>{res.coherence_all_median.toFixed(2)}</b></div>
        <div><small>{t('img.cmp.baseCross')}</small><b>{res.baseline.cross_mean_m.toFixed(2)} ± {res.baseline.cross_std_m.toFixed(2)} m</b></div>
        <div><small>{t('img.cmp.baseH')}</small><b>{res.baseline.height_mean_m.toFixed(2)} ± {res.baseline.height_std_m.toFixed(2)} m</b></div>
      </div>
      <img className="sar-img-full" src={`${base}/api/flights/${encodeURIComponent(flight)}/images/${res.dir}/${res.png}?v=${a}${b}${Date.now() % 1e6}`} alt={t('img.cmp.title')} />
      <small className="sar-hint">{t('img.cmp.hint')}</small>
    </>}
  </div>;
}

/** 데이터 서버가 영상을 만들 수 있나 — 아래쪽 안내 한 줄. */
export function ImagingStatus({ imaging, mirror }: { imaging: Imaging; mirror: MirrorState }) {
  useLang();
  if (imaging === null || !imaging.ready) {
    return <div className="sar-image-next">
      <b>{t('sar.data.image')}</b>
      <small>{imaging === null ? t('img.notConfigured') : t('img.notReady', { missing: imaging.missing.join(' · ') })}</small>
      <small>{t('img.howTo')}</small>
    </div>;
  }
  return <div className="sar-image-next is-ready">
    <b>{t('sar.data.image')}</b>
    <small>{mirror === null ? t('img.readyLocal') : t('img.ready', { src: mirror.source, n: mirror.fetched_passes })}</small>
    {mirror !== null && mirror.last_error !== null && <small className="sar-bad">{t('img.mirrorErr', { why: mirror.last_error })}</small>}
  </div>;
}
