/**
 * src/vision/views/VisionToolStack.tsx (261124 신설 — 영상 위 버튼 묶음 한 자리)
 *
 * **영역 지정 · 재식별 버튼이 서는 자리 하나.** 영상 그림의 오른쪽 위(결과 띠 아래)에 세로로 쌓는다.
 *
 * ## 왜 따로 두나 (261124 — 하드웨어 카드에서 영상이 둘 이상이면 재식별 버튼이 세로로 길게 겹쳤다)
 *
 * 전에는 두 층이 제각기 `left = 그림 오른쪽 끝 − 8px` 에 절대 위치로 서서 `translateX(-100%)` 로 왼쪽으로 밀었다.
 * 절대 위치 상자는 폭을 안 주면 「담는 칸 폭 − left」 안에서만 넓어진다. 영상이 하나면 높이 제한 때문에 좌우에 여백이
 * 남아 괜찮았지만, 둘 이상이면 2열 격자에서 그림이 칸 폭을 꽉 채워 **남는 폭이 8px** 가 됐다 — 버튼 글이 한 글자씩
 * 줄바꿈해 세로로 길어지고, 고정 간격(8 / 40px)으로 선 두 묶음이 서로 겹쳤다.
 *
 * 그래서 자리를 **오른쪽 기준(`right`)** 으로 하나만 세우고, 두 층은 제 버튼 줄을 이 자리에 포털로 넣는다.
 * 한쪽 줄의 높이가 바뀌어도 다른 줄이 그 아래로 밀려날 뿐 겹치지 않는다.
 *
 * 결과 띠 높이(`bandPx`)는 프레임 크기를 아는 층(영역 · 재식별)이 알려 준다. 둘이 같은 프레임을 보므로 같은 값이다.
 */

import { useEffect, useState, type RefObject } from 'react';

/** 그림이 `<img>` 안에서 차지하는 자리(object-fit: contain 여백 포함) — VisionCards · VisionRoi · VisionReid 와 같은 셈. */
function contentBox(img: HTMLImageElement) {
  const w = img.clientWidth;
  const h = img.clientHeight;
  const nw = img.naturalWidth || 1;
  const nh = img.naturalHeight || 1;
  const fit = getComputedStyle(img).objectFit;
  const s = fit === 'contain' ? Math.min(w / nw, h / nh) : w / nw;
  return { left: img.offsetLeft + (w - nw * s) / 2, top: img.offsetTop + (h - nh * s) / 2, width: nw * s };
}

export function VisionToolStack({ imgRef, bandPx, slotRef }: {
  imgRef: RefObject<HTMLImageElement | null>;
  /** 결과 띠 높이(화면 픽셀). 버튼이 띠의 글을 가리지 않게 그 아래에 선다. */
  bandPx: number;
  slotRef: (el: HTMLDivElement | null) => void;
}) {
  const [, setTick] = useState(0);
  useEffect(() => {                                 // 영상 칸 크기가 바뀌면 다시 선다
    const img = imgRef.current;
    if (img === null || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => setTick((v) => v + 1));
    ro.observe(img);
    const onLoad = () => setTick((v) => v + 1);
    img.addEventListener('load', onLoad);
    return () => { ro.disconnect(); img.removeEventListener('load', onLoad); };
  }, [imgRef]);

  const img = imgRef.current;
  const host = img?.offsetParent as HTMLElement | null | undefined;
  // 그림이 아직 없으면 자리만 둔다 — 층이 포털할 곳이 사라지면 버튼이 깜빡인다.
  if (img == null || !img.naturalWidth || host == null) return <div ref={slotRef} className="vtool-stack" hidden />;
  const g = contentBox(img);
  const right = Math.max(0, host.clientWidth - (g.left + g.width)) + 8;
  return <div ref={slotRef} className="vtool-stack" style={{ right, top: g.top + bandPx + 8 }} />;
}
