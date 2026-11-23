/**
 * src/vision/views/VisionRoi.tsx (261123 신설 — 탐지 영역)
 *
 * **추론 영상 위의 영역 층.** 카드 층(VisionCards)처럼 영상과 칸 모양은 그대로 두고 그 위에 얹는다.
 *
 *   「영역 지정」 → 버튼이 켜진다 → 영상 위를 끌면 색으로 영역이 그려지고 데이터 스트림에 보낸다
 *   영역마다 ✕      → 그 영역만 지운다
 *   「영역 취소」 → 영역을 모두 지운다
 *
 * 영역의 주인은 데이터 스트림이다 — `<base>/control/roi` (GET 지금 영역 · POST 바꾸기 · DELETE 지우기,
 * 좌표는 프레임 대비 0~1). 비전(vision_infer.py)이 그 영역 안만 탐지하고, 탐지 개수도 그 안에서만 세어
 * 영상 왼쪽 위에 그린다. 그래서 이 층은 **지정과 표시만** 한다 — 같은 영역을 다른 화면(/vision/view)에서
 * 바꿔도 2초 안에 여기에도 보인다.
 *
 * 비전 오버레이 설정에서 「탐지 영역」을 끈 모델(`overlay_prefs.roi === false`)에는 층을 세우지 않는다.
 * 영역 지정 모드가 아닐 때 층은 마우스를 받지 않는다 — 카드 층의 마우스 · 클릭이 그대로 움직인다.
 */

import { useCallback, useEffect, useRef, useState, type MouseEvent, type RefObject } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { trimBase } from '../visionClient.ts';

type Rect = [number, number, number, number];
type Roi = { version: number; rects: Rect[]; model?: string | null } | null;
type FrameInfo = { width?: number; height?: number; overlay_prefs?: { roi?: boolean } };

/** 그림이 `<img>` 안에서 차지하는 자리(object-fit: contain 여백 포함) — VisionCards 와 같은 셈. */
function contentBox(img: HTMLImageElement) {
  const w = img.clientWidth;
  const h = img.clientHeight;
  const nw = img.naturalWidth || 1;
  const nh = img.naturalHeight || 1;
  const fit = getComputedStyle(img).objectFit;
  const s = fit === 'contain' ? Math.min(w / nw, h / nh) : w / nw;
  return { left: img.offsetLeft + (w - nw * s) / 2, top: img.offsetTop + (h - nh * s) / 2, s, nw, nh };
}

/** 2초마다: 지금 영역 + 결과의 크기 · 설정(띠 높이를 알려면 결과 height 가 필요하다). */
function useRoiState(base: string, model: string) {
  const [roi, setRoi] = useState<Roi>(null);
  const [info, setInfo] = useState<FrameInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${trimBase(base)}/control/roi`, { cache: 'no-store' });
      if (r.ok) { setRoi(((await r.json()) as { roi: Roi }).roi); setError(null); }
    } catch { /* 서버가 잠시 없으면 마지막 것을 둔다 */ }
  }, [base]);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      await refresh();
      try {
        const r = await fetch(`${trimBase(base)}/vision/frame?model=${encodeURIComponent(model)}&image=0&wait=0`, { cache: 'no-store' });
        if (r.status === 200 && alive) setInfo(await r.json() as FrameInfo);
      } catch { /* 위와 같다 */ }
    };
    void tick();
    const id = setInterval(() => { void tick(); }, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [base, model, refresh]);
  return { roi, setRoi, info, error, setError, refresh };
}

export function VisionRoi({ base, model, imgRef }: { base: string; model: string; imgRef: RefObject<HTMLImageElement | null> }) {
  useLang();
  const { roi, setRoi, info, error, setError } = useRoiState(base, model);
  const [mode, setMode] = useState(false);
  const [drag, setDrag] = useState<{ a: [number, number]; b: [number, number] } | null>(null);
  const [, setTick] = useState(0);
  const layer = useRef<HTMLDivElement | null>(null);

  useEffect(() => {                                 // 영상 칸 크기가 바뀌면 다시 그린다
    const img = imgRef.current;
    if (img === null || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => setTick((v) => v + 1));
    ro.observe(img);
    const onLoad = () => setTick((v) => v + 1);
    img.addEventListener('load', onLoad);
    return () => { ro.disconnect(); img.removeEventListener('load', onLoad); };
  }, [imgRef]);

  const img = imgRef.current;
  if (img === null || !img.naturalWidth || info?.height == null || info.width == null) return null;
  if (info.overlay_prefs?.roi === false) return null;
  const g = contentBox(img);
  const band = Math.max(0, g.nh - info.height);
  const fw = info.width;
  const fh = info.height;
  const rects = roi?.rects ?? [];

  /** 프레임 비율(0~1) → 층 안 픽셀 */
  const px = (r: Rect) => ({ left: r[0] * fw * g.s, top: (band + r[1] * fh) * g.s,
    width: (r[2] - r[0]) * fw * g.s, height: (r[3] - r[1]) * fh * g.s });
  /** 마우스 → 프레임 비율 */
  const frac = (event: MouseEvent): [number, number] | null => {
    const el = layer.current;
    if (el === null) return null;
    const r = el.getBoundingClientRect();
    const x = (event.clientX - r.left) / g.s / fw;
    const y = ((event.clientY - r.top) / g.s - band) / fh;
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
  };

  const send = async (next: Rect[]) => {
    try {
      const r = next.length === 0
        ? await fetch(`${trimBase(base)}/control/roi`, { method: 'DELETE' })
        : await fetch(`${trimBase(base)}/control/roi`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rects: next, model: null }),
          });
      const body = await r.json() as { roi?: Roi; detail?: string };
      if (!r.ok) { setError(body.detail ?? `HTTP ${r.status}`); return; }
      setRoi(body.roi ?? null);
      setError(null);
    } catch (e) {
      setError(t('vis.roi.failed', { why: e instanceof Error ? e.message : String(e) }));
    }
  };

  const box = { left: g.left, top: g.top, width: g.nw * g.s, height: g.nh * g.s };
  const live = drag === null ? null : ([Math.min(drag.a[0], drag.b[0]), Math.min(drag.a[1], drag.b[1]),
    Math.max(drag.a[0], drag.b[0]), Math.max(drag.a[1], drag.b[1])] as Rect);

  return <>
    <div ref={layer} className={`vroi-layer${mode ? ' vroi-layer--on' : ''}`} style={box}
      onMouseDown={(event) => {
        if (!mode || event.button !== 0) return;
        const p = frac(event);
        if (p !== null) { event.preventDefault(); setDrag({ a: p, b: p }); }
      }}
      onMouseMove={(event) => {
        if (drag === null) return;
        const p = frac(event);
        if (p !== null) setDrag({ ...drag, b: p });
      }}
      onMouseUp={() => {
        if (drag === null || live === null) return;
        setDrag(null);
        if (live[2] - live[0] < 0.01 || live[3] - live[1] < 0.01) return;
        setMode(false);
        void send([...rects, live]);
      }}
      onMouseLeave={() => setDrag(null)}>
      {rects.map((r, i) => <div key={`${roi?.version ?? 0}-${i}`} className="vroi-rect" style={px(r)}>
        <button type="button" className="vroi-rect__x" title={t('vis.roi.remove')}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); void send(rects.filter((_, j) => j !== i)); }}>✕</button>
      </div>)}
      {live !== null && <div className="vroi-rect vroi-rect--live" style={px(live)} />}
    </div>
    <div className="vroi-bar" style={{ left: g.left + g.nw * g.s - 8, top: g.top + band * g.s + 8 }}>
      <button type="button" className={mode ? 'is-on' : ''} onClick={() => setMode(!mode)}>{t('vis.roi.set')}</button>
      {rects.length > 0 && <button type="button" onClick={() => { setMode(false); void send([]); }}>{t('vis.roi.clear')}</button>}
      {error !== null && <small className="vroi-bar__err">{error}</small>}
    </div>
  </>;
}
