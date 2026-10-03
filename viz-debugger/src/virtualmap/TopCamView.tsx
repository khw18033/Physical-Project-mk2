/**
 * src/virtualmap/TopCamView.tsx (261003 신설 — Unity 상공 카메라 연동)
 *
 * **Unity 상공 카메라 서버(`CameraMjpegServer`, 기본 8090)를 틀 대신 직접 그리고, 시점을 조절한다.**
 * 「3D 가상환경」 · 「가상 맵」 칸에 그 서버 주소(`http://<PC>:8090/`)를 넣으면, 노드가 `/status` 로
 * 그 서버인지 알아보고 이 화면으로 바뀐다. 다른 주소면 지금처럼 틀(iframe)을 띄운다 — 판단은 주소가 아니라 응답으로 한다.
 *
 * 서버 쪽 약속 (HW_coupling `Assets/Code/Camera/CameraMjpegServer.cs`)
 *   GET /status                → { cameras:[{name,target,height,yaw,heading,ortho,frames}], clients }
 *   GET /<name>.mjpg           → 끝나지 않는 MJPEG (드론 = drone, GO1 = go1)
 *   GET /cam?name=..&zoom=0.8  → 확대(높이 x0.8) · height= · rotate= · yaw= · heading=0|1 · ortho=0|1
 *   정면 카메라(kind=front, /dronefront.mjpg): 기체 정면 아래 45° 고정 — zoom= 은 화각, tilt= 숙임, fov= 화각
 *
 * 카드에서는 누름을 막는다(끌기가 먼저다). 조작은 확대에서 한다 — 가상 맵의 Unity 틀과 같은 규칙이다.
 * 확대에서는 버튼 말고도 **영상 위 휠 = 확대·축소, 좌우 끌기 = 회전** 이다.
 */

import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as RPointerEvent, WheelEvent as RWheelEvent } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';

export type TopCamInfo = {
  name: string;
  target: string;
  height: number;
  yaw: number;
  heading: boolean;
  ortho: boolean;
  frames: number;
  /** 'top' = 상공 내려다보기, 'front' = 기체 정면 아래 카메라 (옛 서버는 없음 → top) */
  kind?: 'top' | 'front';
  tilt?: number;
  fov?: number;
};
type Probe = { kind: 'unknown' } | { kind: 'other' } | { kind: 'topcam'; cameras: TopCamInfo[]; at: number };

/** 주소 끝의 `/` 와 `index.html` 을 떼어 서버 뿌리로 만든다. */
export function topCamRoot(url: string): string {
  return url.trim().replace(/\/index\.html?$/i, '').replace(/\/+$/, '');
}

/**
 * 그 주소가 상공 카메라 서버인지 `/status` 로 알아본다. 맞으면 1초마다 다시 읽어 높이·프레임을 갱신한다.
 * 한 번도 맞은 적 없는 주소가 응답하지 않으면 `other` — 노드는 원래대로 틀을 띄운다.
 */
export function useTopCamProbe(url: string): Probe {
  const [probe, setProbe] = useState<Probe>({ kind: 'unknown' });
  const seen = useRef(false);
  useEffect(() => {
    seen.current = false;
    setProbe({ kind: 'unknown' });
    const root = topCamRoot(url);
    if (!/^https?:\/\//i.test(root)) { setProbe({ kind: 'other' }); return; }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const ctrl = new AbortController();
      const cut = setTimeout(() => ctrl.abort(), 1500);
      try {
        const res = await fetch(`${root}/status`, { signal: ctrl.signal, cache: 'no-store' });
        const body = res.ok ? await res.json() : null;
        if (!alive) return;
        if (body && Array.isArray(body.cameras)) {
          seen.current = true;
          setProbe({ kind: 'topcam', cameras: body.cameras as TopCamInfo[], at: Date.now() });
        } else if (!seen.current) setProbe({ kind: 'other' });
      } catch {
        // 한 번 맞았던 서버가 잠깐 안 받으면(Unity Play 를 멈춤 등) 화면을 틀로 바꾸지 않고 마지막 모양을 둔다
        if (alive && !seen.current) setProbe({ kind: 'other' });
      } finally {
        clearTimeout(cut);
        if (alive) timer = setTimeout(tick, seen.current ? 1000 : 4000);
      }
    };
    void tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [url]);
  return probe;
}

function send(root: string, name: string, query: string) {
  void fetch(`${root}/cam?name=${encodeURIComponent(name)}&${query}`, { cache: 'no-store' }).catch(() => undefined);
}

function camLabel(name: string): string {
  if (name === 'drone') return t('topcam.drone');
  if (name === 'go1') return t('topcam.go1');
  if (name === 'dronefront') return t('topcam.droneFront');
  return name;
}

/**
 * 숫자로 바로 넣는 칸. Enter 또는 칸을 벗어나면 보낸다. 입력 중에는 서버 값(1초마다 갱신)으로 덮어쓰지 않는다.
 */
function NumField({ label, unit, value, min, max, onSet }: {
  label: string; unit: string; value: number; min: number; max: number; onSet: (v: number) => void;
}) {
  const [text, setText] = useState(String(Math.round(value)));
  const editing = useRef(false);
  useEffect(() => { if (!editing.current) setText(String(Math.round(value))); }, [value]);
  const commit = () => {
    if (!editing.current) return; // Enter 로 이미 보냈으면 칸을 벗어날 때 또 보내지 않는다
    editing.current = false;
    const v = Number(text);
    if (!Number.isFinite(v)) { setText(String(Math.round(value))); return; }
    const c = Math.min(max, Math.max(min, v));
    setText(String(c));
    if (Math.abs(c - value) >= 0.5) onSet(c);
  };
  return <label className="topcam__num">
    {label}
    <input
      type="number" inputMode="decimal" min={min} max={max} step={1} value={text}
      onFocus={() => { editing.current = true; }}
      onChange={(e) => { editing.current = true; setText(e.currentTarget.value); }}
      onKeyDown={(e) => { if (e.key === 'Enter') { commit(); e.currentTarget.blur(); } if (e.key === 'Escape') { editing.current = false; setText(String(Math.round(value))); e.currentTarget.blur(); } }}
      onBlur={commit}
    />
    <span>{unit}</span>
  </label>;
}

/** 영상 한 칸. 확대에서는 휠 = 확대·축소, 좌우 끌기 = 회전. */
function CamPane({ root, cam, zoom, stale }: { root: string; cam: TopCamInfo; zoom: boolean; stale: boolean }) {
  useLang();
  const front = cam.kind === 'front';
  const drag = useRef<{ x: number; acc: number; last: number } | null>(null);
  const wheelAt = useRef(0);
  // 같은 영상을 다시 붙일 때(서버 재시작) 끊긴 MJPEG 를 새로 받게 한다
  const [epoch, setEpoch] = useState(0);
  useEffect(() => { if (stale) return; setEpoch((e) => e + 1); }, [stale]);

  const onWheel = (e: RWheelEvent) => {
    if (!zoom) return;
    const now = performance.now();
    if (now - wheelAt.current < 80) return; // 휠 한 번에 여러 번 오는 것을 묶는다
    wheelAt.current = now;
    send(root, cam.name, `zoom=${e.deltaY > 0 ? 1.15 : 0.87}`);
  };
  const onDown = (e: RPointerEvent) => {
    if (!zoom) return;
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, acc: 0, last: performance.now() };
  };
  const onMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d || front) return;
    d.acc += (e.clientX - d.x) * 0.4; // 픽셀 → 도
    d.x = e.clientX;
    const now = performance.now();
    if (Math.abs(d.acc) >= 3 && now - d.last > 90) {
      send(root, cam.name, `rotate=${(-d.acc).toFixed(1)}`);
      d.acc = 0; d.last = now;
    }
  };
  const onUp = () => {
    const d = drag.current;
    if (d && !front && Math.abs(d.acc) >= 1) send(root, cam.name, `rotate=${(-d.acc).toFixed(1)}`);
    drag.current = null;
  };

  return <figure className="topcam__pane">
    <figcaption className="topcam__cap">
      <b>{camLabel(cam.name)}</b>
      <span className="vn-dim">{front ? t('topcam.metaFront', {
        target: cam.target || '—',
        tilt: Math.round(cam.tilt ?? 45),
        fov: Math.round(cam.fov ?? 80),
      }) : t('topcam.meta', {
        target: cam.target || '—',
        height: Math.round(cam.height),
        yaw: Math.round(cam.yaw),
        up: cam.heading ? t('topcam.upHeading') : t('topcam.upNorth'),
        view: cam.ortho ? t('topcam.viewMap') : t('topcam.viewPersp'),
      })}</span>
    </figcaption>
    <img
      key={epoch}
      className={`topcam__img${zoom ? ' topcam__img--live' : ''}`}
      src={`${root}/${cam.name}.mjpg`}
      alt={camLabel(cam.name)}
      draggable={false}
      onWheel={onWheel}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
    />
    {zoom && front && <div className="topcam__bar">
      <button type="button" onClick={() => send(root, cam.name, 'zoom=0.8')}>{t('topcam.zoomIn')}</button>
      <button type="button" onClick={() => send(root, cam.name, 'zoom=1.25')}>{t('topcam.zoomOut')}</button>
      <button type="button" onClick={() => send(root, cam.name, 'tilt=45&fov=80')}>45° · 80°</button>
      <label className="topcam__height">
        {t('topcam.tilt')}
        <input
          type="range" min={0} max={90} step={1}
          defaultValue={Math.round(cam.tilt ?? 45)}
          key={`t${Math.round(cam.tilt ?? 45)}`}
          onChange={(e) => send(root, cam.name, `tilt=${e.currentTarget.value}`)}
        />
      </label>
      <NumField label="" unit="°" value={cam.tilt ?? 45} min={0} max={90} onSet={(v) => send(root, cam.name, `tilt=${v}`)} />
      <NumField label={t('topcam.fov')} unit="°" value={cam.fov ?? 80} min={15} max={110} onSet={(v) => send(root, cam.name, `fov=${v}`)} />
    </div>}
    {zoom && !front && <div className="topcam__bar">
      <button type="button" onClick={() => send(root, cam.name, 'zoom=0.8')}>{t('topcam.zoomIn')}</button>
      <button type="button" onClick={() => send(root, cam.name, 'zoom=1.25')}>{t('topcam.zoomOut')}</button>
      <button type="button" onClick={() => send(root, cam.name, 'rotate=-45')}>⟲ 45°</button>
      <button type="button" onClick={() => send(root, cam.name, 'rotate=45')}>⟳ 45°</button>
      <button type="button" className={!cam.heading ? 'is-on' : ''} onClick={() => send(root, cam.name, 'yaw=0&heading=0')}>{t('topcam.upNorth')}</button>
      <button type="button" className={cam.heading ? 'is-on' : ''} onClick={() => send(root, cam.name, 'yaw=0&heading=1')}>{t('topcam.upHeading')}</button>
      <button type="button" className={cam.ortho ? 'is-on' : ''} onClick={() => send(root, cam.name, 'ortho=1')}>{t('topcam.viewMap')}</button>
      <button type="button" className={!cam.ortho ? 'is-on' : ''} onClick={() => send(root, cam.name, 'ortho=0')}>{t('topcam.viewPersp')}</button>
      <label className="topcam__height">
        {t('topcam.height')}
        <input
          type="range" min={3} max={500} step={1}
          defaultValue={Math.round(cam.height)}
          key={Math.round(cam.height)}
          onChange={(e) => send(root, cam.name, `height=${e.currentTarget.value}`)}
        />
      </label>
      <NumField label="" unit="m" value={cam.height} min={3} max={500} onSet={(v) => send(root, cam.name, `height=${v}`)} />
      <NumField label={t('topcam.rotation')} unit="°" value={((cam.yaw % 360) + 360) % 360} min={0} max={359} onSet={(v) => send(root, cam.name, `yaw=${v}`)} />
      <NumField label={t('topcam.fov')} unit="°" value={cam.fov ?? 60} min={10} max={100} onSet={(v) => send(root, cam.name, `fov=${v}`)} />
    </div>}
  </figure>;
}

/**
 * 상공 카메라 화면. `cameras` 가 비면 서버는 떠 있지만 카메라가 없는 것(Unity 가 Play 가 아님).
 * 확대에서는 「둘 다 · 드론 · GO1」 을 고를 수 있다.
 */
export function TopCamView({ url, probe, zoom = false }: { url: string; probe: Extract<Probe, { kind: 'topcam' }>; zoom?: boolean }) {
  useLang();
  const root = topCamRoot(url);
  const [only, setOnly] = useState<string>('');
  const stale = Date.now() - probe.at > 3000;
  const cams = probe.cameras.filter((c) => only === '' || c.name === only);
  return <div className={`topcam${zoom ? ' topcam--zoom' : ''}`} style={zoom ? undefined : { pointerEvents: 'none' }}>
    {zoom && <div className="topcam__pick">
      <button type="button" className={only === '' ? 'is-on' : ''} onClick={() => setOnly('')}>{t('topcam.both')}</button>
      {probe.cameras.map((c) => <button key={c.name} type="button" className={only === c.name ? 'is-on' : ''} onClick={() => setOnly(c.name)}>{camLabel(c.name)}</button>)}
      <span className="vn-dim">{t('topcam.hint')}{probe.cameras.some((c) => c.kind === 'front') ? ` · ${t('topcam.hintFront')}` : ''}</span>
    </div>}
    {probe.cameras.length === 0
      ? <p className="vn-line vn-dim">{t('topcam.noCams')}</p>
      : <div className={`topcam__grid topcam__grid--${cams.length}`}>
          {cams.map((c) => <CamPane key={c.name} root={root} cam={c} zoom={zoom} stale={stale} />)}
        </div>}
    <p className="vn-line vn-dim">{t('topcam.line', { url: root })}{stale ? ` · ${t('topcam.stale')}` : ''}{zoom ? '' : ` · ${t('v3d.zoomHint')}`}</p>
  </div>;
}
