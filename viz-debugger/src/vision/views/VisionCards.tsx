/**
 * src/vision/views/VisionCards.tsx (261113 신설 — 위험물 근거 카드)
 *
 * **추론 영상 위에 얹는 투명한 층 하나.** 영상(`<img>` MJPEG)과 칸의 모양은 그대로 두고, 그 위에서
 *
 *   물체 위에 마우스  → 그 물체의 근거 카드가 커서 옆에 뜬다
 *   클릭              → 카드가 그 물체 옆에 **고정**된다(물체가 움직이면 `track_id` 로 따라간다)
 *   ✕                 → 고정한 카드를 닫는다
 *
 * 카드의 내용은 서버가 정한다 — 데이터 스트림 `<base>/vision/frame?model=<m>&image=0` 이 주는 검출의
 * `assess`(위험물 클래스마다의 단서 점수 · 의심 클래스 · 하한)를 **그대로** 그린다. 화면이 점수를 다시 셈하지 않는다.
 * `assess` 가 없는 모델(yoloe 등)의 검출에는 카드가 없다 — 층은 아무것도 하지 않는다.
 *
 * 영상 그림에는 서버가 「이름 거리 점수」만 그려 둔다. 근거(단서별 점수)는 그림에 넣지 않는다 — 카드가 검출을 가렸다.
 *
 * **좌표.** 오버레이 그림은 원본 위에 제목 띠를 덧붙인 것이라 `naturalHeight - 결과 height` 만큼 아래로 밀려 있다.
 * `<img>` 는 `object-fit: contain` 일 수 있어 그림이 칸 가운데 들어간다 — 그 여백까지 계산한다.
 * MJPEG 의 장과 검출 JSON 의 장은 따로 오므로 한두 장 어긋날 수 있다(2~3 장/초에서 물체는 거의 안 움직인다).
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { trimBase } from '../visionClient.ts';

type CardRow = [string, number | null, string];
type Assess = {
  scores: Record<string, number | null>;
  suspect: string | null;
  score: number | null;
  min_score: number;
  cards: Record<string, { score: number | null; rows: CardRow[]; source: string }>;
};
type Det = {
  bbox: [number, number, number, number];
  label?: string;
  lead?: string;
  confidence?: number;
  track_id?: number | null;
  dist?: { value: number; space: string } | number | null;
  assess?: Assess;
};
type FrameDets = { seq: number; n?: number; width?: number; height?: number; detections?: Det[] };

const CARD_W = 300;
const GAP = 8;

const keyOf = (d: Det, i: number, seq: number) => (d.track_id != null ? `t${d.track_id}` : `i${i}@${seq}`);
const shown = (cls: string) => t(`vis.card.cls.${cls}`);
const scoreTone = (s: number) => (s >= 60 ? 'hi' : s >= 40 ? 'mid' : 'lo');

function distText(d: Det): string | null {
  const v = d.dist;
  if (v == null) return null;
  if (typeof v === 'number') return `${v.toFixed(1)} m`;
  return v.space === 'metric' ? `${v.value.toFixed(1)} m` : t('vis.card.relative', { v: v.value.toFixed(3) });
}

/** 카드 한 장. `onClose` 가 있으면 고정 카드다. */
function Card({ det, onClose, gone }: { det: Det; onClose?: () => void; gone?: boolean }) {
  useLang();
  const a = det.assess;
  if (a === undefined) return null;
  const names = Object.keys(a.scores);
  const best = a.suspect ?? [...names].sort((p, q) => (a.scores[q] ?? -1) - (a.scores[p] ?? -1))[0];
  const card = a.cards[best] ?? { score: null, rows: [], source: '' };
  const haz = a.suspect !== null;
  const dist = distText(det);
  return <div className={`vcard${haz ? ' vcard--haz' : ''}${gone ? ' vcard--gone' : ''}`}
    onMouseMove={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
    <div className="vcard__head">
      <b>{haz ? shown(best) : (det.lead ?? det.label ?? '?')}</b>
      {card.score !== null && <span className={`vcard__score vcard__score--${scoreTone(card.score)}`}>{Math.round(card.score)}/100</span>}
      {onClose !== undefined && <button type="button" className="vcard__x" title={t('vis.card.close')} onClick={onClose}>✕</button>}
    </div>
    <div className="vcard__cmp">
      {names.map((name) => `${shown(name)} ${a.scores[name] === null ? '—' : (a.scores[name] as number).toFixed(1)}`).join(' · ')}
      {' · '}{t('vis.card.min', { min: a.min_score })}
      {!haz && <> {t('vis.card.notSuspect', { cls: shown(best) })}</>}
    </div>
    {card.rows.map(([key, pct, text]) => (pct === null
      ? <div key={key} className="vcard__kv"><span>{t(`vis.card.cue.${key}`)}</span><span className="vcard__txt">{text}</span></div>
      : <div key={key} className="vcard__row">
          <span>{t(`vis.card.cue.${key}`)}</span>
          <span className="vcard__bar"><i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} /></span>
          <span className="vcard__pct">{Math.round(pct)}%</span>
          <span className="vcard__txt">{text}</span>
        </div>))}
    {dist !== null && !card.rows.some(([key]) => key === 'distance')
      && <div className="vcard__kv"><span>{t('vis.card.cue.distance')}</span><span className="vcard__txt">{dist}</span></div>}
    {card.source !== '' && <div className="vcard__kv"><span>{t('vis.card.source')}</span><span className="vcard__txt">{card.source}</span></div>}
    {gone && <div className="vcard__gone">{t('vis.card.gone')}</div>}
  </div>;
}

/** 서버의 최신 검출 — 새 장이 오면 바뀐다. 못 받으면 마지막 것을 그대로 둔다. */
function useFrameDets(base: string, model: string): FrameDets | null {
  const [frame, setFrame] = useState<FrameDets | null>(null);
  useEffect(() => {
    let alive = true;
    let seq = -1;
    let abort: AbortController | null = null;
    const loop = async () => {
      while (alive) {
        abort = new AbortController();
        try {
          const url = `${trimBase(base)}/vision/frame?model=${encodeURIComponent(model)}&image=0&since=${seq}&wait=5`;
          const response = await fetch(url, { signal: abort.signal, cache: 'no-store' });
          if (response.status === 200) {
            const body = await response.json() as FrameDets;
            seq = body.seq;
            if (alive) setFrame(body);
          } else if (response.status !== 204) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
          }
        } catch {
          if (!alive) return;
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    };
    void loop();
    return () => { alive = false; abort?.abort(); };
  }, [base, model]);
  return frame;
}

/** 그림이 `<img>` 안에서 실제로 차지하는 자리(object-fit: contain 여백 포함)와 배율. */
function contentBox(img: HTMLImageElement) {
  const w = img.clientWidth;
  const h = img.clientHeight;
  const nw = img.naturalWidth || 1;
  const nh = img.naturalHeight || 1;
  const fit = getComputedStyle(img).objectFit;
  const s = fit === 'contain' ? Math.min(w / nw, h / nh) : w / nw;
  return { left: img.offsetLeft + (w - nw * s) / 2, top: img.offsetTop + (h - nh * s) / 2, s, nw, nh };
}

/**
 * **카드 층.** `imgRef` 의 `<img>` 와 같은 부모(`rec-host`, position: relative) 안에 둔다.
 * 검출에 `assess` 가 하나도 없으면 층은 사건을 받지 않는다 — 영상 칸이 예전과 똑같이 움직인다.
 */
export function VisionCards({ base, model, imgRef }: { base: string; model: string; imgRef: RefObject<HTMLImageElement | null> }) {
  useLang();
  const frame = useFrameDets(base, model);
  const [hover, setHover] = useState<{ key: string; x: number; y: number } | null>(null);
  const [pins, setPins] = useState<string[]>([]);
  const lastSeen = useRef(new Map<string, Det>());
  const pinEls = useRef(new Map<string, HTMLDivElement>());
  const [, setTick] = useState(0);

  const dets = frame?.detections ?? [];
  const seq = frame?.seq ?? -1;
  const withCards = dets.some((d) => d.assess !== undefined);
  const now = new Map<string, Det>();
  dets.forEach((d, i) => { if (d.assess !== undefined) now.set(keyOf(d, i, seq), d); });
  now.forEach((d, k) => lastSeen.current.set(k, d));

  // 영상 칸 크기가 바뀌면(확대 · 창 크기) 다시 그린다
  useEffect(() => {
    const img = imgRef.current;
    if (img === null || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => setTick((v) => v + 1));
    ro.observe(img);
    const onLoad = () => setTick((v) => v + 1);
    img.addEventListener('load', onLoad, { once: true });
    return () => { ro.disconnect(); img.removeEventListener('load', onLoad); };
  }, [imgRef]);

  const geom = useCallback(() => {
    const img = imgRef.current;
    if (img === null || !img.naturalWidth || frame?.height == null) return null;
    const box = contentBox(img);
    return { ...box, band: Math.max(0, box.nh - frame.height) };
  }, [imgRef, frame]);

  /** 화면(부모 기준) 좌표 → 원본 그림 좌표에서 가장 작은 검출. */
  const hitAt = (px: number, py: number): string | null => {
    const g = geom();
    if (g === null) return null;
    const x = (px - g.left) / g.s;
    const y = (py - g.top) / g.s - g.band;
    let best: string | null = null;
    let area = Infinity;
    now.forEach((d, k) => {
      const [x1, y1, x2, y2] = d.bbox;
      if (x >= x1 && x <= x2 && y >= y1 && y <= y2 && (x2 - x1) * (y2 - y1) < area) { area = (x2 - x1) * (y2 - y1); best = k; }
    });
    return best;
  };

  const boxPx = (d: Det) => {
    const g = geom();
    if (g === null) return null;
    const [x1, y1, x2, y2] = d.bbox;
    return { x1: g.left + x1 * g.s, y1: g.top + (y1 + g.band) * g.s, x2: g.left + x2 * g.s, y2: g.top + (y2 + g.band) * g.s };
  };

  // 고정 카드 자리: 물체 오른쪽 → 왼쪽 → 아래 → 위, 서로 안 겹치게. 그린 뒤 크기를 재서 놓는다
  useLayoutEffect(() => {
    const img = imgRef.current;
    const host = img?.parentElement;
    if (!host) return;
    const W = host.clientWidth;
    const H = host.clientHeight;
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    const clash = (r: { x: number; y: number; w: number; h: number }) => placed.some((q) => !(r.x + r.w <= q.x || q.x + q.w <= r.x || r.y + r.h <= q.y || q.y + q.h <= r.y));
    for (const k of pins) {
      const el = pinEls.current.get(k);
      const d = now.get(k) ?? lastSeen.current.get(k);
      const b = d === undefined ? null : boxPx(d);
      if (!el || b === null) continue;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const fit = (x: number, y: number) => ({ x: Math.max(0, Math.min(x, W - w)), y: Math.max(0, Math.min(y, H - h)), w, h });
      const cand = [fit(b.x2 + GAP, b.y1), fit(b.x1 - w - GAP, b.y1), fit(b.x1, b.y2 + GAP), fit(b.x1, b.y1 - h - GAP)];
      let pick = cand.find((c) => !clash(c)) ?? cand[0];
      for (let n = 0; n < 40 && clash(pick); n += 1) pick = fit(pick.x, pick.y + 24);
      placed.push(pick);
      el.style.left = `${pick.x}px`;
      el.style.top = `${pick.y}px`;
    }
  });

  if (!withCards && pins.length === 0) return null;
  const g = geom();
  const hovered = hover === null ? undefined : now.get(hover.key);
  const marks = [...new Set([...(hover === null ? [] : [hover.key]), ...pins])];

  const local = (event: MouseEvent) => {
    const host = imgRef.current?.parentElement;
    if (!host) return null;
    const r = host.getBoundingClientRect();
    return { x: event.clientX - r.left, y: event.clientY - r.top };
  };

  return <>
    <div className={`vcard-layer${hovered !== undefined ? ' vcard-layer--hit' : ''}`}
      style={g === null ? { display: 'none' } : { left: g.left, top: g.top, width: g.nw * g.s, height: g.nh * g.s }}
      onMouseMove={(event) => {
        const p = local(event);
        const k = p === null ? null : hitAt(p.x, p.y);
        setHover(k === null ? null : { key: k, x: event.clientX, y: event.clientY });
      }}
      onMouseLeave={() => setHover(null)}
      onClick={(event) => {
        const p = local(event);
        const k = p === null ? null : hitAt(p.x, p.y);
        if (k !== null && !pins.includes(k)) setPins([...pins, k]);
      }}>
      {marks.map((k) => {
        const d = now.get(k);
        const b = d === undefined || g === null ? null : boxPx(d);
        if (b === null || g === null) return null;
        return <div key={k} className={`vcard-mark${pins.includes(k) ? ' vcard-mark--pin' : ''}`}
          style={{ left: b.x1 - g.left, top: b.y1 - g.top, width: b.x2 - b.x1, height: b.y2 - b.y1 }} />;
      })}
    </div>
    {pins.map((k) => {
      const d = now.get(k) ?? lastSeen.current.get(k);
      if (d === undefined) return null;
      return <div key={k} className="vcard-pin" ref={(el) => { if (el) pinEls.current.set(k, el); else pinEls.current.delete(k); }}>
        <Card det={d} gone={!now.has(k)} onClose={() => { setPins(pins.filter((p) => p !== k)); lastSeen.current.delete(k); }} />
      </div>;
    })}
    {hovered !== undefined && hover !== null && !pins.includes(hover.key) && <div className="vcard-tip"
      style={{
        left: Math.min(hover.x + 16, window.innerWidth - CARD_W - 12),
        top: Math.min(hover.y + 16, window.innerHeight - 280),
      }}>
      <Card det={hovered} />
    </div>}
  </>;
}
