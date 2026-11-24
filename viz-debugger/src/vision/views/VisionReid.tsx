/**
 * src/vision/views/VisionReid.tsx (261123 신설 — 객체 재식별)
 *
 * **추론 영상 위의 재식별 층.** 카드 · 영역 층처럼 영상과 칸 모양은 그대로 두고 그 위에 얹는다.
 *
 *   「재식별 선택」 → 버튼이 켜진다 → 물체 상자를 누르면 그 물체를 재식별 대상으로 데이터 스트림에 보낸다
 *   「재식별 취소」 → 고른 물체를 모두 지운다
 *
 * 따라가기 · 다시 찾기 · 다른 카메라 연결은 데이터 스트림 비전(vision/reid.py)이 한다 — 이 층은 **고르기만** 한다.
 * 찾은 물체는 서버가 영상에 자홍색 상자 'REID <번호>' 로 그리므로 여기서 다시 그리지 않는다.
 * 창구: `<base>/control/reid` (GET 고른 물체와 마지막으로 본 곳 · POST 고르기 · DELETE 취소).
 * 비전 기능 선택에서 「객체 재식별」을 끄면(`overlay_prefs.reid` 가 거짓) 층을 세우지 않는다.
 */

import { useEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { trimBase } from '../visionClient.ts';

type Det = { bbox: [number, number, number, number]; label?: string; track_id?: number | null };
type Frame = { n?: number; width?: number; height?: number; model?: string; overlay_prefs?: { reid?: boolean }; detections?: Det[] };
type Item = { id: number; label?: string; device?: string; seen?: { device?: string; how?: string; trail?: { device: string }[] } | null };

function contentBox(img: HTMLImageElement) {
  const w = img.clientWidth;
  const h = img.clientHeight;
  const nw = img.naturalWidth || 1;
  const nh = img.naturalHeight || 1;
  const fit = getComputedStyle(img).objectFit;
  const s = fit === 'contain' ? Math.min(w / nw, h / nh) : w / nw;
  return { left: img.offsetLeft + (w - nw * s) / 2, top: img.offsetTop + (h - nh * s) / 2, s, nw, nh };
}

export function VisionReid({ base, model, imgRef, slot, onBand }: {
  base: string;
  model: string;
  imgRef: RefObject<HTMLImageElement | null>;
  /** 버튼 줄이 설 자리(`VisionToolStack`) — 영역 지정 줄 아래에 쌓인다. 아직 없으면 버튼을 안 그린다. */
  slot: HTMLElement | null;
  /** 결과 띠 높이(화면 픽셀)를 버튼 자리에 알린다 — 영역 층을 끈 모델에서도 띠 아래에 서도록. */
  onBand: (px: number) => void;
}) {
  useLang();
  const [frame, setFrame] = useState<Frame | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [mode, setMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const layer = useRef<HTMLDivElement | null>(null);

  useEffect(() => {                                 // 1초마다: 검출(누를 상자) · 고른 물체
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${trimBase(base)}/vision/frame?model=${encodeURIComponent(model)}&image=0&wait=0`, { cache: 'no-store' });
        if (r.status === 200 && alive) setFrame(await r.json() as Frame);
        const q = await fetch(`${trimBase(base)}/control/reid`, { cache: 'no-store' });
        if (q.ok && alive) setItems(((await q.json()) as { items?: Item[] }).items ?? []);
      } catch { /* 서버가 잠시 없으면 마지막 것을 둔다 */ }
    };
    void tick();
    const id = setInterval(() => { void tick(); }, 1000);
    return () => { alive = false; clearInterval(id); };
  }, [base, model]);

  useEffect(() => {
    const img = imgRef.current;
    if (img === null || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => setTick((v) => v + 1));
    ro.observe(img);
    return () => ro.disconnect();
  }, [imgRef]);

  const img = imgRef.current;
  // 결과 띠 높이 — 훅이라 아래의 이른 return 보다 앞에 둔다.
  const box0 = img !== null && img.naturalWidth > 0 ? contentBox(img) : null;
  const bandPx = box0 !== null && frame?.height != null && frame.overlay_prefs?.reid ? Math.max(0, box0.nh - frame.height) * box0.s : null;
  useEffect(() => { if (bandPx !== null) onBand(bandPx); }, [bandPx, onBand]);

  if (img === null || !img.naturalWidth || frame?.height == null) return null;
  if (!frame.overlay_prefs?.reid) return null;
  const g = contentBox(img);
  const band = Math.max(0, g.nh - frame.height);

  const pick = async (px: number, py: number) => {
    const x = px / g.s;
    const y = py / g.s - band;
    let best: Det | null = null;
    let area = Infinity;
    for (const d of frame.detections ?? []) {
      const [x1, y1, x2, y2] = d.bbox;
      if (x >= x1 && x <= x2 && y >= y1 && y <= y2 && (x2 - x1) * (y2 - y1) < area) { area = (x2 - x1) * (y2 - y1); best = d; }
    }
    if (best === null) return;
    setMode(false);
    try {
      const r = await fetch(`${trimBase(base)}/control/reid`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: frame.model ?? model, bbox: best.bbox, track_id: best.track_id ?? null, n: frame.n, label: best.label }),
      });
      if (!r.ok) setError(((await r.json()) as { detail?: string }).detail ?? `HTTP ${r.status}`);
      else setError(null);
    } catch (e) {
      setError(t('vis.reid.failed', { why: e instanceof Error ? e.message : String(e) }));
    }
  };

  const clear = async () => {
    setMode(false);
    try { await fetch(`${trimBase(base)}/control/reid`, { method: 'DELETE' }); setItems([]); } catch { /* 다음 tick 에 다시 본다 */ }
  };

  const where = (it: Item) => {
    const trail = (it.seen?.trail ?? []).map((s) => s.device).join(' → ');
    return `REID ${it.id}${it.label ? ` ${it.label}` : ''}${trail ? ` · ${trail}` : ''}`;
  };

  return <>
    {mode && <div ref={layer} className="vreid-layer" style={{ left: g.left, top: g.top, width: g.nw * g.s, height: g.nh * g.s }}
      onClick={(event) => {
        const r = layer.current?.getBoundingClientRect();
        if (r) void pick(event.clientX - r.left, event.clientY - r.top);
      }} />}
    {/* 261124 — 버튼 줄은 칸의 버튼 자리(`VisionToolStack`)에 영역 지정 줄 아래로 선다. 전에는 고정 간격(+40px)에 따로 서서,
        좁은 칸에서 세로로 길어진 영역 줄과 겹쳤다. 항목 글은 한 줄로 자르고 전체는 title 로 둔다 */}
    {slot !== null && createPortal(<div className="vreid-bar">
      <button type="button" className={mode ? 'is-on' : ''} onClick={() => setMode(!mode)}>{t('vis.reid.set')}</button>
      {items.length > 0 && <button type="button" onClick={() => { void clear(); }}>{t('vis.reid.clear')}</button>}
      {items.map((it) => <small key={it.id} className="vreid-bar__item" title={where(it)}>{where(it)}</small>)}
      {error !== null && <small className="vreid-bar__err" title={error}>{error}</small>}
    </div>, slot)}
  </>;
}
