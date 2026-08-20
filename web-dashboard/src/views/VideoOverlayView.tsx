/**
 * src/views/VideoOverlayView.tsx
 *
 * VZ-I-06 영상 · VZ-I-07 탐지 오버레이 정합 · VZ-I-09 추적·궤적.
 *
 * **이 화면의 목적은 그림이 아니라 실측이다.**
 * 정합 on/off를 토글하면 박스가 대상에서 얼마나 뒤처지는지가 눈으로 보이고,
 * 그 거리가 화면에 픽셀 숫자로 뜬다. "프레임 참조가 없으면 어긋난다"를
 * 그림으로 주장하던 것을 여기서 숫자로 바꾼다.
 *
 * **영상은 렌더 예산의 예외다.** 상태 병합(100ms)과 별개로 requestAnimationFrame 루프를
 * 돌리되, 그 루프는 canvas만 건드리고 React 상태를 매 프레임 바꾸지 않는다 —
 * 매 프레임 setState 하면 결국 15Hz 리렌더가 되어 병합의 의미가 사라진다.
 */

import { useEffect, useRef, useState } from 'react';
import {
  CONFIDENCE_THRESHOLD,
  FrameBuffer,
  playScenario,
  resolveAlignment,
  subscribeVision,
  type AlignmentReport,
  type VideoFrame,
} from '../data/index.ts';

const CAMERA = 'camera-02';

/** 계측 표시 갱신 주기. 매 프레임 setState 하지 않기 위한 창. */
const METRICS_REFRESH_MS = 200;

export function VideoOverlayView() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const bufferRef = useRef(new FrameBuffer());
  /** 토글을 ref로도 들고 있다 — 프레임 루프가 매번 최신 값을 읽어야 하는데
   *  루프를 재생성하면 프레임이 끊기기 때문이다. */
  const alignedRef = useRef(true);

  const [aligned, setAligned] = useState(true);
  const [report, setReport] = useState<AlignmentReport | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [frameCount, setFrameCount] = useState(0);

  useEffect(() => {
    alignedRef.current = aligned;
  }, [aligned]);

  // 구독 + 패널 열기. 닫으면 서버가 프레임 발행을 멈춘다 (VZ-I-06).
  useEffect(() => {
    if (!panelOpen) return;
    const buffer = bufferRef.current;
    return subscribeVision(CAMERA, buffer);
  }, [panelOpen]);

  // 프레임 루프. 상태 병합과 **별개**로 돈다.
  useEffect(() => {
    if (!panelOpen) return;

    let raf = 0;
    let lastMetricsAt = 0;
    let drawn = 0;

    const draw = (now: number) => {
      const canvas = canvasRef.current;
      const buffer = bufferRef.current;
      const frame = buffer.latestFrame;

      if (canvas !== null && frame !== null) {
        const ctx = canvas.getContext('2d');
        if (ctx !== null) {
          const alignment = resolveAlignment(buffer, alignedRef.current, frame);
          drawScene(ctx, frame, alignment, alignedRef.current);
          drawn += 1;

          // 계측 표시는 200ms 창으로 묶는다 — 매 프레임 setState 하면 15Hz 리렌더가 된다.
          if (now - lastMetricsAt > METRICS_REFRESH_MS) {
            lastMetricsAt = now;
            setReport(alignment);
            setFrameCount(drawn);
          }
        }
      }
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [panelOpen]);

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">탐지 결과 오버레이 정합</h1>
          <p className="board__sub">
            각 탐지에 되돌아온 <strong>프레임 참조값</strong>으로 해당 프레임에 정합시켜야 박스가 대상 위에 놓인다
          </p>
        </div>
        <div className="board__meta">
          <span>VZ-I-06 · VZ-I-07 · VZ-I-09</span>
        </div>
      </header>

      <div className="videobar">
        <label className="toggle">
          <input type="checkbox" checked={aligned} onChange={(e) => setAligned(e.target.checked)} />
          <span>
            프레임 참조 정합 <strong>{aligned ? 'ON' : 'OFF'}</strong>
          </span>
        </label>

        <button type="button" className="btn" onClick={() => setPanelOpen((v) => !v)}>
          {panelOpen ? '패널 닫기 (프레임 루프 정지)' : '패널 열기'}
        </button>

        {report !== null && (
          <span className={'lagbadge' + (report.maxLagPx > 8 ? ' lagbadge--bad' : '')}>
            뒤처짐 최대 <strong>{report.maxLagPx.toFixed(1)} px</strong> · 평균{' '}
            {report.avgLagPx.toFixed(1)} px · {report.frameLag}프레임
          </span>
        )}
      </div>

      {!panelOpen ? (
        <p className="notice">
          패널이 닫혀 있다. 프레임 루프가 멈췄고 서버도 프레임을 발행하지 않는다 — 열린 패널만 받는다(VZ-I-06).
        </p>
      ) : (
        <>
          <div className="videoframe">
            <canvas ref={canvasRef} width={960} height={540} className="videocanvas" />
          </div>

          {report !== null && (
            <div className="cols cols--3">
              <section className="panel">
                <header className="panel__head">
                  <h2 className="panel__title">정합 계측</h2>
                  <span className="panel__tag">VZ-I-07</span>
                </header>
                <dl className="kv">
                  <dt>표시 프레임</dt>
                  <dd>
                    <code>#{report.displayFrame}</code>
                  </dd>
                  <dt>탐지 frame_ref</dt>
                  <dd>
                    <code>#{report.detectionFrame}</code>
                  </dd>
                  <dt>프레임 차</dt>
                  <dd>
                    <strong>{report.frameLag}프레임</strong> <span className="muted">(추론 {report.inferenceDelayMs}ms ÷ 67ms)</span>
                  </dd>
                  <dt>뒤처짐 최대</dt>
                  <dd>
                    <strong>{report.maxLagPx.toFixed(1)} px</strong>
                  </dd>
                  <dt>뒤처짐 평균</dt>
                  <dd>{report.avgLagPx.toFixed(1)} px</dd>
                  <dt>그린 프레임</dt>
                  <dd className="muted">{frameCount}장</dd>
                </dl>
                <p className="note">
                  {aligned
                    ? 'frame_ref가 가리키는 프레임에 맞춰 그린다. 뒤처짐이 0에 가깝다.'
                    : '도착 순서대로 현재 프레임에 그린다. 박스가 대상이 지나간 자리에 남는다.'}
                </p>
              </section>

              <section className="panel">
                <header className="panel__head">
                  <h2 className="panel__title">bbox 좌표계 환산</h2>
                  <span className="panel__tag">VZ-I-07</span>
                </header>
                <dl className="kv">
                  <dt>형식</dt>
                  <dd>
                    <code>{report.bboxFormat}</code>
                  </dd>
                  <dt>환산 배율</dt>
                  <dd>
                    x {report.scale.x.toFixed(3)} · y {report.scale.y.toFixed(3)}
                  </dd>
                </dl>
                <p className="note">
                  정규화 여부·원점·기준 해상도가 <strong>계약에 선언되어야</strong> 무엇을 곱할지 정할 수 있다.
                  추론 해상도와 표시 해상도가 다를 때 이게 환산 기준이 된다.
                </p>
              </section>

              <section className="panel">
                <header className="panel__head">
                  <h2 className="panel__title">추적 대상</h2>
                  <span className="panel__tag">VZ-I-09</span>
                </header>
                <ul className="tracklist">
                  {report.boxes.map((b) => (
                    <li key={b.trackId} className={'tracklist__item' + (b.uncertain ? ' tracklist__item--uncertain' : '')}>
                      <code>{b.trackId}</code>
                      <strong>{b.label}</strong>
                      <span>{b.confidence.toFixed(2)}</span>
                      <span className="muted">{b.uncertain ? '불확실' : '확실'}</span>
                      <span className="muted">{b.lagPx.toFixed(1)} px</span>
                    </li>
                  ))}
                </ul>
                <p className="note">
                  신뢰도 {CONFIDENCE_THRESHOLD} 미만은 <strong>점선 + 물음표</strong>로 그린다. 확실한 것과 애매한 것이
                  똑같이 보이면 안 된다. 카메라 간 연결과 단기 예측은 이번 범위 밖.
                </p>
              </section>
            </div>
          )}
        </>
      )}

      <section className="devpanel">
        <h2 className="devpanel__title">시나리오 재생 — 숫자가 바뀌는지 확인</h2>
        <div className="devpanel__row">
          <button type="button" className="btn" onClick={() => playScenario('vision-delay-200')}>
            추론 지연 200ms
          </button>
          <button type="button" className="btn" onClick={() => playScenario('vision-delay-500')}>
            추론 지연 500ms
          </button>
          <button type="button" className="btn" onClick={() => playScenario('vision-bbox-absolute')}>
            bbox 픽셀 절대
          </button>
          <button type="button" className="btn" onClick={() => playScenario('vision-bbox-normalized')}>
            bbox 정규화(0~1)
          </button>
          <button type="button" className="btn" onClick={() => playScenario('vision-inference-320')}>
            추론 해상도 320×180
          </button>
          <button type="button" className="btn" onClick={() => playScenario('vision-inference-640')}>
            추론 해상도 640×360
          </button>
        </div>
      </section>
    </main>
  );
}

// ── canvas 합성 ──────────────────────────────────────────────────────────────

/**
 * 합성 영상과 오버레이를 그린다.
 * 실제 스트림 변환 지점이 미정이라 목 서버가 준 도형을 직접 그린다 —
 * 이 검증에 필요한 것은 화질이 아니라 "몇 번째 프레임인가"이기 때문이다.
 */
function drawScene(
  ctx: CanvasRenderingContext2D,
  frame: VideoFrame,
  alignment: AlignmentReport | null,
  aligned: boolean,
): void {
  const { width, height } = ctx.canvas;

  // 배경
  ctx.fillStyle = '#1e2227';
  ctx.fillRect(0, 0, width, height);

  // 대상 도형 — 프레임이 선언한 기준 해상도로 표시 해상도에 환산해 그린다.
  const objScaleX = width / frame.reference.width;
  const objScaleY = height / frame.reference.height;

  ctx.fillStyle = '#5b6672';
  for (const o of frame.objects) {
    const cx = o.cx * objScaleX;
    const cy = o.cy * objScaleY;
    const w = o.w * objScaleX;
    const h = o.h * objScaleY;

    if (o.shape === 'person') {
      // 머리 + 몸통
      ctx.beginPath();
      ctx.arc(cx, cy - h * 0.32, w * 0.42, 0, Math.PI * 2);
      ctx.fill();
      roundRect(ctx, cx - w / 2, cy - h * 0.12, w, h * 0.62, 8);
      ctx.fill();
    } else {
      roundRect(ctx, cx - w / 2, cy - h / 2, w, h, 6);
      ctx.fill();
    }
  }

  // 오버레이 박스
  if (alignment !== null) {
    for (const b of alignment.boxes) {
      const color = aligned ? '#3ddc84' : '#ff6b6b';
      ctx.strokeStyle = color;
      ctx.lineWidth = b.uncertain ? 2 : 3;
      // 신뢰도가 낮으면 점선 — 확실한 것과 애매한 것이 똑같이 보이면 안 된다.
      ctx.setLineDash(b.uncertain ? [7, 5] : []);
      ctx.strokeRect(b.x, b.y, b.w, b.h);
      ctx.setLineDash([]);

      // 궤적
      if (b.trail.length > 1) {
        ctx.strokeStyle = color + '88';
        ctx.lineWidth = 2;
        ctx.beginPath();
        b.trail.forEach(([tx, ty], i) => {
          if (i === 0) ctx.moveTo(tx, ty);
          else ctx.lineTo(tx, ty);
        });
        ctx.stroke();
      }

      // 라벨
      const label =
        b.label + ' ' + b.confidence.toFixed(2) + (b.uncertain ? ' ?' : '') +
        (aligned ? '' : ' — ' + (alignment.frameLag) + '프레임 뒤');
      ctx.font = '600 13px "Malgun Gothic", sans-serif';
      const tw = ctx.measureText(label).width + 12;
      ctx.fillStyle = color;
      ctx.fillRect(b.x, b.y - 20, tw, 19);
      ctx.fillStyle = aligned ? '#0b2016' : '#3a0d0d';
      ctx.fillText(label, b.x + 6, b.y - 6);
    }
  }

  // 헤더/푸터 텍스트
  ctx.font = '600 13px "Malgun Gothic", sans-serif';
  ctx.fillStyle = '#e6e9ec';
  ctx.fillText(CAMERA + ' · 합성 영상 · ' + frame.fps + ' fps', 14, 26);

  ctx.font = '12px Consolas, monospace';
  ctx.fillStyle = '#aab2ba';
  const headRight = 'frame #' + frame.frame_seq;
  ctx.fillText(headRight, width - ctx.measureText(headRight).width - 14, 26);

  if (alignment !== null) {
    ctx.fillStyle = aligned ? '#8fe7b4' : '#ff9d9d';
    const foot = aligned
      ? 'detections.frame_ref = #' + alignment.detectionFrame + ' → 표시 프레임 #' + alignment.displayFrame + '  일치'
      : 'frame_ref 무시 → 표시 프레임 #' + alignment.displayFrame + '에 #' + alignment.detectionFrame + ' 결과를 그림  (' + alignment.maxLagPx.toFixed(0) + 'px 어긋남)';
    ctx.fillText(foot, 14, height - 16);
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
