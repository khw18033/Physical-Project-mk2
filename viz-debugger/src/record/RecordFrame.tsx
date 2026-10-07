/**
 * src/record/RecordFrame.tsx (261007 신설 — 실시간 화면 녹화 버튼)
 *
 * **실시간 영상 한 칸을 감싸고, 그 위 왼쪽 위에 녹화 시작 · 정지 버튼을 얹는다.** 녹화되는 것은 감싼 칸의 **첫 요소**
 * (`<img>` · `<canvas>` · `<iframe>`)다 — 버튼은 그 형제라 요소 캡처(`restrictTo`)에서는 안 찍힌다(`screenRecord.ts`).
 *
 * **이 칸이 내려가면(창을 닫음 · 탭을 옮김) 녹화를 멈추고 저장한다** (261007 결정). 보고 있는 것을 찍는 방식이라 칸이
 * 사라지면 찍을 것이 없다.
 *
 * 저장 창구가 없는 서버(단독 빌드 · 정적 서버)면 버튼을 그리지 않는다 — 눌러도 저장할 곳이 없다.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { isActive, saverAvailable, startRecording, stopRecording, unsupportedReason, useRecordings } from './screenRecord.ts';

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** 저장 창구가 있는가 — 모든 버튼이 같은 답을 쓴다. */
function useSaver(): boolean | null {
  const [available, setAvailable] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    void saverAvailable().then((value) => { if (alive) setAvailable(value); });
    return () => { alive = false; };
  }, []);
  return available;
}

export function RecordFrame({ label, children, className }: {
  /** 파일 이름에 들어갈 이름 — 장치 · 영상 종류. 예: `go1-001_카메라`. */
  label: string;
  children: ReactNode;
  className?: string;
}) {
  useLang();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [mine, setMine] = useState<string | null>(null);
  const mineRef = useRef<string | null>(null);
  mineRef.current = mine;
  const saver = useSaver();
  const all = useRecordings();
  const current = mine === null ? undefined : all.find((item) => item.id === mine);
  const running = current !== undefined && isActive(current);
  const [, setTick] = useState(0);
  // 경과 시간을 1초마다 다시 그린다 — 도는 동안만.
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setTick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [running]);
  // 칸이 내려가면 멈추고 저장한다.
  useEffect(() => () => { if (mineRef.current !== null) void stopRecording(mineRef.current); }, []);

  const reason = unsupportedReason();
  const onClick = () => {
    if (running && mine !== null) { void stopRecording(mine); return; }
    const target = hostRef.current?.firstElementChild;
    if (target == null) return;
    setMine(startRecording(target, label));
  };

  return <div ref={hostRef} className={`rec-host${className === undefined ? '' : ` ${className}`}`}>
    {children}
    {saver === true && <button
      type="button"
      className={`rec-btn${running ? ' rec-btn--on' : ''}`}
      disabled={reason !== null || current?.phase === 'saving' || current?.phase === 'starting'}
      title={reason !== null ? t(reason) : running ? t('rec.stopTitle') : t('rec.startTitle', { label })}
      // 카드 · 노드 위에서 누를 때 끌기 · 더블클릭(확대)로 번지지 않게 한다.
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onClick={(event) => { event.stopPropagation(); onClick(); }}
    >
      <i aria-hidden="true" />
      {current?.phase === 'starting' ? t('rec.starting')
        : current?.phase === 'saving' ? t('rec.saving')
        : running ? t('rec.stop', { elapsed: formatElapsed(Date.now() - current!.startedAtMs) })
        : t('rec.start')}
    </button>}
  </div>;
}
