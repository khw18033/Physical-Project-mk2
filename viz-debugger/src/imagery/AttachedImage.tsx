/**
 * src/imagery/AttachedImage.tsx (260929 신설 — SAR · 3D 복원 뷰 노드)
 *
 * **연결 관리에 붙인 것을 띄운다.** 어느 쪽인지는 노드가 아니라 연결 관리가 정한다 — 가상 맵 노드와 같은 규칙이다.
 *
 *   이미지 주소가 있으면   그 주소 (서비스가 생기면 주소만 넣는다)
 *   없고 파일을 붙였으면  붙인 파일 (`shared/imageStore.ts` — 이 브라우저 안)
 *   둘 다 없으면          「연결 관리에서 이미지를 붙이세요」
 *
 * 카드(접힘)는 한 장을 칸에 맞춰 보이고, 확대는 휠로 키우고 끌어서 옮긴다. 두 번 누르면 원래 크기다.
 */

import { useState, type MouseEvent as ReactMouseEvent, type WheelEvent as ReactWheelEvent } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import { useStoredImage } from '../shared/imageStore.ts';

export type ImageTarget = 'sar' | 'recon-3d';

/** 무엇을 띄울지 — 주소가 파일보다 먼저다. 순수하게 가른다. */
export function imageSourceOf(address: string, file: { url: string; name: string } | null): { src: string; from: 'url' | 'file'; label: string } | null {
  const url = address.trim();
  if (url !== '') return { src: url, from: 'url', label: url };
  if (file !== null) return { src: file.url, from: 'file', label: file.name };
  return null;
}

export function AttachedImage({ target, zoom = false }: { target: ImageTarget; zoom?: boolean }) {
  useLang();
  useConnections();
  const file = useStoredImage(`${target}.image`);
  const source = imageSourceOf(connectionAddress(target, 'base'), file);
  const [broken, setBroken] = useState<string | null>(null);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);

  if (source === null) return <p className="vn-line vn-dim">{t('img.empty')}</p>;
  const caption = source.from === 'url' ? t('img.from.url', { url: source.label }) : t('img.from.file', { name: source.label });
  if (broken === source.src) return <div className="attached-img">
    <p className="vn-line vn-dim">{t('img.broken')}</p>
    <small className="attached-img__caption">{caption}</small>
  </div>;

  if (!zoom) {
    return <figure className="attached-img">
      <img className="attached-img__still" src={source.src} alt={caption} draggable={false} onError={() => setBroken(source.src)} />
      <figcaption className="attached-img__caption">{caption}</figcaption>
    </figure>;
  }

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    setView((prev) => ({ ...prev, scale: Math.max(0.2, Math.min(12, prev.scale * factor)) }));
  };
  const onDown = (event: ReactMouseEvent<HTMLDivElement>) => setDrag({ x: event.clientX - view.x, y: event.clientY - view.y });
  const onMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (drag !== null) setView((prev) => ({ ...prev, x: event.clientX - drag.x, y: event.clientY - drag.y }));
  };
  return <figure className="attached-img attached-img--zoom">
    <div
      className={`attached-img__stage${drag !== null ? ' is-dragging' : ''}`}
      onWheel={onWheel}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={() => setDrag(null)}
      onMouseLeave={() => setDrag(null)}
      onDoubleClick={() => setView({ scale: 1, x: 0, y: 0 })}
    >
      <img
        src={source.src}
        alt={caption}
        draggable={false}
        onError={() => setBroken(source.src)}
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
      />
    </div>
    <figcaption className="attached-img__caption">{caption} · {t('img.zoomHint')}</figcaption>
  </figure>;
}
