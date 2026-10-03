/**
 * src/dronedash/SatMap.tsx (261002 신설 — 드론 파트 · 위성 지도)
 *
 * **MicoConfigurator 처럼 실제 위성 사진 위에 드론 · 궤적 · SAR 선 · 홈 · 베이스를 그리는 지도.**
 *   - 드래그로 옮기고 휠로 확대/축소, 「전부 보기」 · 「드론 따라가기」
 *   - 배경: 위성 / 지도 / 없음 (타일 주소는 연결 관리 「드론 지도 타일」 — 오프라인 타일 서버로 바꿀 수 있다)
 *   - 궤적에 마우스를 올리면 그 순간의 시각 · 고도 · 속도 · RTK 를 보여 준다
 *   - `onPick` 을 주면 지도를 눌러 점을 고른다(SAR 선 정하기)
 * 외부 지도 라이브러리를 쓰지 않는다 — 웹 메르카토르 타일을 직접 깐다(번들이 커지지 않게).
 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import './dronedash.css';

export type LatLon = { lat: number; lon: number };
export type TrackPoint = LatLon & { t: number; alt?: number | null; speed?: number | null; fix?: string | null; capture?: boolean };
export type Marker = LatLon & { kind: 'home' | 'base' | 'reflector' | 'pick'; label?: string; tone?: 'good' | 'bad'; lit?: boolean };
/** 지도에 깔 면 — 안테나 관측 띠 등. */
export type Area = { points: readonly LatLon[]; kind: 'swath' | 'beam' };
/** 지도에 겹칠 그림(SAR 영상). 꼭짓점 순서: 그림의 왼쪽 위 · 오른쪽 위 · 오른쪽 아래 · 왼쪽 아래. */
export type Overlay = { url: string; corners: readonly [LatLon, LatLon, LatLon, LatLon]; opacity?: number };

type Layer = 'satellite' | 'street' | 'none';
const TILE = 256;
const LAYER_KEY = 'viz.dash.layer.v1';

function world(lat: number, lon: number, z: number): { x: number; y: number } {
  const s = TILE * 2 ** z;
  const sin = Math.min(0.9999, Math.max(-0.9999, Math.sin((lat * Math.PI) / 180)));
  return { x: ((lon + 180) / 360) * s, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s };
}
function unworld(x: number, y: number, z: number): LatLon {
  const s = TILE * 2 ** z;
  const lon = (x / s) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / s;
  return { lat: (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))), lon };
}
function mpp(lat: number, z: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** z;
}
function tileUrl(template: string, z: number, x: number, y: number): string {
  return template.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y));
}

export function SatMap({
  track = [], drone, droneYaw, sarLine, capturing, markers = [], areas = [], overlays = [], onPick, pickHint, height = 380,
}: {
  track?: readonly TrackPoint[];
  drone?: LatLon | null;
  droneYaw?: number | null;
  sarLine?: { start: LatLon; end: LatLon; leadIn?: LatLon | null } | null;
  capturing?: boolean;
  markers?: readonly Marker[];
  areas?: readonly Area[];
  overlays?: readonly Overlay[];
  onPick?: (p: LatLon) => void;
  pickHint?: string;
  height?: number;
}) {
  useLang();
  useConnections();
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  const [layer, setLayer] = useState<Layer>(() => {
    try { return (localStorage.getItem(LAYER_KEY) as Layer) || 'satellite'; } catch { return 'satellite'; }
  });
  const [view, setView] = useState<{ center: LatLon; z: number } | null>(null);
  const [follow, setFollow] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; p: TrackPoint } | null>(null);
  const drag = useRef<{ x: number; y: number; c: { x: number; y: number }; moved: boolean } | null>(null);
  const H = height;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(200, el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const everything = useMemo(() => [
    ...track, ...markers, ...(drone ? [drone] : []),
    ...(sarLine ? [sarLine.start, sarLine.end, ...(sarLine.leadIn ? [sarLine.leadIn] : [])] : []),
    ...overlays.flatMap((o) => o.corners),
  ], [track, markers, drone, sarLine, overlays]);

  function fit(): { center: LatLon; z: number } | null {
    if (everything.length === 0) return null;
    const lat = (Math.min(...everything.map((p) => p.lat)) + Math.max(...everything.map((p) => p.lat))) / 2;
    const lon = (Math.min(...everything.map((p) => p.lon)) + Math.max(...everything.map((p) => p.lon))) / 2;
    let z = 20;
    for (; z > 3; z--) {
      const ps = everything.map((p) => world(p.lat, p.lon, z));
      const w = Math.max(...ps.map((p) => p.x)) - Math.min(...ps.map((p) => p.x));
      const h = Math.max(...ps.map((p) => p.y)) - Math.min(...ps.map((p) => p.y));
      if (w < W * 0.75 && h < H * 0.75 && mpp(lat, z) * W >= 60) break;
    }
    return { center: { lat, lon }, z };
  }

  // 처음 · 자료가 처음 생겼을 때 맞춘다. 사람이 옮긴 뒤에는 건드리지 않는다.
  useEffect(() => { if (view === null) { const f = fit(); if (f) setView(f); } }, [everything.length > 0, W]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (follow && drone && view) setView({ center: drone, z: view.z }); }, [follow, drone?.lat, drone?.lon]); // eslint-disable-line react-hooks/exhaustive-deps

  const satTpl = connectionAddress('drone-map', 'satellite');
  const streetTpl = connectionAddress('drone-map', 'street');

  if (view === null) {
    return <div ref={box} className="satmap satmap--empty" style={{ height: H }}>
      {onPick ? <p>{t('map.noDataPick')}</p> : <p>{t('map.noData')}</p>}
    </div>;
  }
  const z = view.z;
  const zi = Math.floor(z);
  const scale = 2 ** (z - zi);
  const c = world(view.center.lat, view.center.lon, z);
  const ox = c.x - W / 2;
  const oy = c.y - H / 2;
  const P = (p: LatLon) => { const w = world(p.lat, p.lon, z); return { x: w.x - ox, y: w.y - oy }; };

  const tiles: { key: string; src: string; x: number; y: number; size: number }[] = [];
  const tpl = layer === 'satellite' ? satTpl : layer === 'street' ? streetTpl : '';
  if (tpl) {
    const size = TILE * scale;
    const cz = world(view.center.lat, view.center.lon, zi);
    const ox0 = cz.x * scale - W / 2;
    const oy0 = cz.y * scale - H / 2;
    const n = 2 ** zi;
    for (let tx = Math.floor(ox0 / size); tx <= Math.floor((ox0 + W) / size); tx++) {
      for (let ty = Math.floor(oy0 / size); ty <= Math.floor((oy0 + H) / size); ty++) {
        if (ty < 0 || ty >= n) continue;
        const wx = ((tx % n) + n) % n;
        tiles.push({ key: `${zi}/${tx}/${ty}`, src: tileUrl(tpl, zi, wx, ty), x: tx * size - ox0, y: ty * size - oy0, size });
      }
    }
  }

  const m = mpp(view.center.lat, z);
  const scaleM = [2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000].find((s) => s / m > 70) ?? 2000;

  function setZoom(nz: number, ax = W / 2, ay = H / 2) {
    nz = Math.max(3, Math.min(21, nz));
    const before = unworld(ox + ax, oy + ay, z);
    const after = world(before.lat, before.lon, nz);
    const center = unworld(after.x - ax + W / 2, after.y - ay + H / 2, nz);
    setView({ center, z: nz });
  }
  function onDown(e: RPointerEvent<HTMLDivElement>) {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, c, moved: false };
  }
  function onMove(e: RPointerEvent<HTMLDivElement>) {
    const r = box.current!.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    if (drag.current) {
      const dx = e.clientX - drag.current.x;
      const dy = e.clientY - drag.current.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
      if (drag.current.moved) {
        setFollow(false);
        setView({ center: unworld(drag.current.c.x - dx, drag.current.c.y - dy, z), z });
      }
      return;
    }
    let best: { d: number; p: TrackPoint } | null = null;
    for (let i = 0; i < track.length; i += Math.max(1, Math.floor(track.length / 600))) {
      const q = P(track[i]!);
      const d = Math.hypot(q.x - mx, q.y - my);
      if (d < 12 && (best === null || d < best.d)) best = { d, p: track[i]! };
    }
    setHover(best ? { x: mx, y: my, p: best.p } : null);
  }
  function onUp(e: RPointerEvent<HTMLDivElement>) {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved && onPick) {
      const r = box.current!.getBoundingClientRect();
      onPick(unworld(ox + (e.clientX - r.left), oy + (e.clientY - r.top), z));
    }
  }

  const trackSegs: { pts: string; capture: boolean }[] = [];
  let cur: { pts: string[]; capture: boolean } | null = null;
  for (let i = 0; i < track.length; i += Math.max(1, Math.floor(track.length / 1500))) {
    const p = track[i]!;
    const q = P(p);
    const cap = p.capture === true;
    if (cur === null || cur.capture !== cap) {
      if (cur) trackSegs.push({ pts: cur.pts.join(' '), capture: cur.capture });
      cur = { pts: cur ? [cur.pts.at(-1)!] : [], capture: cap };
    }
    cur.pts.push(`${q.x.toFixed(1)},${q.y.toFixed(1)}`);
  }
  if (cur) trackSegs.push({ pts: cur.pts.join(' '), capture: cur.capture });

  return <div className="satmap-wrap">
    <div className="satmap-tools">
      <div className="satmap-seg" role="group" aria-label={t('map.layer')}>
        {(['satellite', 'street', 'none'] as const).map((l) => <button key={l} type="button" className={layer === l ? 'on' : ''}
          onClick={() => { setLayer(l); try { localStorage.setItem(LAYER_KEY, l); } catch { /* */ } }}>{t(`map.layer.${l}`)}</button>)}
      </div>
      <button type="button" onClick={() => setZoom(z + 1)} aria-label={t('map.zoomIn')}>＋</button>
      <button type="button" onClick={() => setZoom(z - 1)} aria-label={t('map.zoomOut')}>－</button>
      <button type="button" onClick={() => { const f = fit(); if (f) { setView(f); setFollow(false); } }}>{t('map.fit')}</button>
      {drone && <label className="sar-check"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />{t('map.follow')}</label>}
      {onPick && <span className="satmap-pick">{pickHint ?? t('map.pickHint')}</span>}
    </div>
    <div ref={box} className={`satmap${onPick ? ' satmap--pick' : ''}`} style={{ height: H }}
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => { setHover(null); drag.current = null; }}
      onWheel={(e) => { e.preventDefault(); const r = box.current!.getBoundingClientRect(); setFollow(false); setZoom(z + (e.deltaY < 0 ? 0.5 : -0.5), e.clientX - r.left, e.clientY - r.top); }}>
      <div className="satmap-tiles">
        {tiles.map((tl) => <img key={tl.key} src={tl.src} alt="" draggable={false} style={{ left: tl.x, top: tl.y, width: tl.size, height: tl.size }} />)}
      </div>
      <svg width={W} height={H} className="satmap-svg">
        {overlays.map((o, i) => {
          // 단위 정사각형 그림을 세 꼭짓점으로 펴는 아핀 변환 — 수백 m 안에서는 메르카토르도 평면과 같다
          const p0 = P(o.corners[0]);
          const p1 = P(o.corners[1]);
          const p3 = P(o.corners[3]);
          return <image key={`ov${i}`} href={o.url} x={0} y={0} width={1} height={1} preserveAspectRatio="none" className="satmap-overlay"
            opacity={o.opacity ?? 0.9} transform={`matrix(${p1.x - p0.x} ${p1.y - p0.y} ${p3.x - p0.x} ${p3.y - p0.y} ${p0.x} ${p0.y})`} />;
        })}
        {areas.map((ar, i) => <polygon key={i} className={`satmap-area satmap-area--${ar.kind}`}
          points={ar.points.map((p) => { const q = P(p); return `${q.x.toFixed(1)},${q.y.toFixed(1)}`; }).join(' ')} />)}
        {sarLine && <>
          {sarLine.leadIn && <line x1={P(sarLine.leadIn).x} y1={P(sarLine.leadIn).y} x2={P(sarLine.start).x} y2={P(sarLine.start).y} className="satmap-lead" />}
          <line x1={P(sarLine.start).x} y1={P(sarLine.start).y} x2={P(sarLine.end).x} y2={P(sarLine.end).y} className={`satmap-sar${capturing ? ' is-on' : ''}`} />
          <circle cx={P(sarLine.start).x} cy={P(sarLine.start).y} r={6} className="satmap-sar-pt" />
          <circle cx={P(sarLine.end).x} cy={P(sarLine.end).y} r={6} className="satmap-sar-pt satmap-sar-pt--end" />
          <text x={P(sarLine.start).x + 9} y={P(sarLine.start).y - 8} className="satmap-label">{t('map.capStart')}</text>
          <text x={P(sarLine.end).x + 9} y={P(sarLine.end).y - 8} className="satmap-label">{t('map.capEnd')}</text>
        </>}
        {trackSegs.map((s, i) => <polyline key={i} points={s.pts} className={`satmap-track${s.capture ? ' is-capture' : ''}`} />)}
        {markers.map((mk, i) => { const q = P(mk); return <g key={i} transform={`translate(${q.x} ${q.y})`} className={`satmap-mk satmap-mk--${mk.kind}${mk.tone ? ` is-${mk.tone}` : ''}${mk.lit ? ' is-lit' : ''}`}>
          {mk.lit && <circle r={17} className="satmap-lit" />}
          {mk.kind === 'reflector' ? <polygon points="0,-8 7,6 -7,6" /> : <circle r={9} />}
          <text y={mk.kind === 'reflector' ? 4 : 4} textAnchor="middle">{mk.kind === 'home' ? 'H' : mk.kind === 'base' ? 'B' : mk.kind === 'pick' ? '•' : ''}</text>
          {mk.label && <text x={12} y={4} className="satmap-label">{mk.label}</text>}
        </g>; })}
        {drone && (() => { const q = P(drone); return <g transform={`translate(${q.x} ${q.y}) rotate(${droneYaw ?? 0})`}>
          <circle r={14} className="satmap-drone-halo" /><polygon points="0,-13 9,10 0,5 -9,10" className="satmap-drone" /></g>; })()}
        {hover && <circle cx={P(hover.p).x} cy={P(hover.p).y} r={5} className="satmap-hover" />}
        <g transform={`translate(${W - 24},26)`}><polygon points="0,-12 5,4 0,0 -5,4" className="satmap-north" /><text x={-4} y={16} className="satmap-label">N</text></g>
        <g transform={`translate(12,${H - 14})`}><rect x={-4} y={-18} width={scaleM / m + 8} height={24} rx={4} className="satmap-scale-bg" />
          <line x1={0} y1={0} x2={scaleM / m} y2={0} className="satmap-scale" /><text x={0} y={-5} className="satmap-label">{scaleM} m</text></g>
      </svg>
      {hover && <div className="satmap-tip" style={{ left: Math.min(hover.x + 12, W - 190), top: Math.max(hover.y - 70, 4) }}>
        <b>{new Date(hover.p.t).toLocaleTimeString(undefined, { hour12: false })}</b>
        <span>{t('map.tip', { alt: hover.p.alt == null ? '—' : hover.p.alt.toFixed(1), spd: hover.p.speed == null ? '—' : hover.p.speed.toFixed(2), fix: hover.p.fix ?? '—' })}</span>
        <small>{hover.p.lat.toFixed(7)}, {hover.p.lon.toFixed(7)}</small>
      </div>}
      {layer === 'satellite' && <small className="satmap-attr">{t('map.attrSat')}</small>}
      {layer === 'street' && <small className="satmap-attr">© OpenStreetMap</small>}
    </div>
  </div>;
}
