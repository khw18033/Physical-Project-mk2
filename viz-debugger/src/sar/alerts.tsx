/**
 * src/sar/alerts.tsx (261004 — 드론 파트 · 알림)
 *
 * 화면을 계속 보고 있지 않아도 알 수 있게 — 일이 생기면 **짧은 소리 + 오른쪽 아래 알림**.
 *   캡처 시작 · 끝 / 패스 무효 / 임무 끝(완료 · 중단 · 실패) / 레이더 끊김 · 오류 / 배터리 낮음 / 드론 보고 끊김 · 다시 붙음 / 새 SAR 영상
 *
 * 어느 화면(상태판 · SAR 패스)에 몇 개가 떠 있어도 한 번만 울린다 — 알림은 모듈 하나가 모은다.
 * 소리는 끌 수 있다(브라우저에 저장). 브라우저는 사람이 한 번 누르기 전에는 소리를 막으므로 첫 클릭부터 난다.
 */

import { useEffect, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { isSarStale, useSarReports, type SarReport } from '../shared/sarStatus.ts';
import { radarLevel, useRadarReports, type RadarReport } from '../shared/radarStatus.ts';
import { useFcxReports } from '../shared/fcxStatus.ts';
import { useTick } from './useTick.ts';

import { detectEvents, type AlertEvent, type AlertLevel, type Snapshot } from './alertEvents.ts';

export { detectEvents };
export type { AlertEvent, AlertLevel, Snapshot };

// ── 모듈 하나에 모은다 ───────────────────────────────────────────────────────

type Shown = AlertEvent & { atMs: number; id: number };
let shown: readonly Shown[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const lastSnap = new Map<string, Snapshot>();
const SOUND_KEY = 'viz.sar.alertSound.v1';

function emit(): void { for (const l of listeners) l(); }

export function soundOn(): boolean {
  try { return localStorage.getItem(SOUND_KEY) !== '0'; } catch { return true; }
}
export function setSoundOn(v: boolean): void {
  try { localStorage.setItem(SOUND_KEY, v ? '1' : '0'); } catch { /* */ }
  emit();
}

let audio: AudioContext | null = null;
function beep(level: AlertLevel): void {
  if (!soundOn()) return;
  try {
    const W = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
    const Ctor = W.AudioContext ?? W.webkitAudioContext;
    if (!Ctor) return;
    audio = audio ?? new Ctor();
    // 높이로 뜻을 가른다: 좋음 = 올라가는 두 음, 정보 = 한 음, 주의 = 두 번, 나쁨 = 낮게 세 번
    const plan: Record<AlertLevel, [number, number][]> = {
      good: [[660, 0], [880, 0.12]], info: [[740, 0]], warn: [[520, 0], [520, 0.18]], bad: [[330, 0], [330, 0.2], [330, 0.4]],
    };
    const t0 = audio.currentTime;
    for (const [f, dt] of plan[level]) {
      const o = audio.createOscillator(); const g = audio.createGain();
      o.frequency.value = f; o.type = 'sine';
      g.gain.setValueAtTime(0.0001, t0 + dt); g.gain.exponentialRampToValueAtTime(0.18, t0 + dt + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.15);
      o.connect(g).connect(audio.destination); o.start(t0 + dt); o.stop(t0 + dt + 0.16);
    }
  } catch { /* 소리가 막혀도 알림은 뜬다 */ }
}

const seenKeys = new Map<string, number>();
export function pushAlerts(events: readonly AlertEvent[], nowMs = Date.now()): void {
  const fresh = events.filter((e) => nowMs - (seenKeys.get(e.key) ?? 0) > 3000);   // 같은 일은 3 초 안에 한 번만
  if (fresh.length === 0) return;
  for (const e of fresh) seenKeys.set(e.key, nowMs);
  shown = [...shown, ...fresh.map((e) => ({ ...e, atMs: nowMs, id: ++seq }))].slice(-6);
  const worst = fresh.some((e) => e.level === 'bad') ? 'bad' : fresh.some((e) => e.level === 'warn') ? 'warn' : fresh.some((e) => e.level === 'good') ? 'good' : 'info';
  beep(worst);
  emit();
}

export function dismissAlert(id: number): void { shown = shown.filter((s) => s.id !== id); emit(); }

function useShown(): readonly Shown[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, () => shown, () => shown);
}

/** 보고를 지켜보다 일이 생기면 알림을 낸다. 화면마다 하나씩 붙여도 모듈이 한 번만 울린다. */
// 영상 수는 데이터 서버를 읽는 SAR 화면만 안다 — 다른 화면은 마지막 값을 그대로 쓴다. 처음 읽은 수는 기준일 뿐 「새 영상」이 아니다
let imagesKnown: number | null = null;

export function SarAlerts({ prfHz, imagesDone }: { prfHz: number | null; imagesDone?: number }) {
  useLang();
  const now = useTick(1000);
  const sar = useSarReports();
  const radar = useRadarReports();
  const fcx = useFcxReports();
  useEffect(() => {
    if (imagesDone !== undefined) {
      if (imagesKnown === null) for (const s of lastSnap.values()) s.imagesDone = imagesDone;
      imagesKnown = imagesDone;
    }
    const ids = new Set([...Object.keys(sar), ...Object.keys(radar), ...Object.keys(fcx)]);
    const events: AlertEvent[] = [];
    for (const id of ids) {
      const r: SarReport | undefined = sar[id];
      const rr: RadarReport | undefined = radar[id];
      const snap: Snapshot = {
        state: r?.state ?? null, capturing: r?.capturing === true, stale: r ? isSarStale(r, now) && !['idle', 'done', 'incomplete', 'aborted', 'failed'].includes(r.state) : false,
        passes: (r?.passes ?? []).map((p) => ({ passNo: p.passNo, valid: p.valid })),
        radar: rr ? radarLevel(rr, prfHz, now).level : null, batteryPct: fcx[id]?.battery?.remainingPct ?? null, imagesDone: imagesKnown ?? 0,
      };
      events.push(...detectEvents(id, lastSnap.get(id), snap));
      lastSnap.set(id, snap);
    }
    if (events.length) pushAlerts(events, now);
  }, [now, sar, radar, fcx, prfHz, imagesDone]);
  return <AlertStack />;
}

function AlertStack() {
  useLang();
  const list = useShown();
  const now = useTick(1000);
  const live = list.filter((a) => now - a.atMs < (a.level === 'bad' ? 20_000 : 8_000));
  const on = soundOn();
  if (live.length === 0) return null;
  return <div className="sar-alerts" role="status" aria-live="polite">
    {live.map((a) => <div key={a.id} className={`sar-alert is-${a.level}`}>
      <span>{t(a.textKey, a.vars)}</span>
      <button type="button" aria-label={t('alert.close')} onClick={() => dismissAlert(a.id)}>×</button>
    </div>)}
    <button type="button" className="sar-alert-sound" onClick={() => setSoundOn(!on)}>{on ? t('alert.soundOff') : t('alert.soundOn')}</button>
  </div>;
}

/** 드론 보고가 끊겼을 때 크게 — 화면이 멈춘 건지 드론이 멈춘 건지 헷갈리지 않게. */
export function LinkBanner({ report }: { report: SarReport | null | undefined }) {
  useLang();
  const now = useTick(1000);
  if (!report || !isSarStale(report, now)) return null;
  const finished = ['idle', 'done', 'incomplete', 'aborted', 'failed'].includes(report.state);
  const ago = Math.round((now - report.receivedAtMs) / 1000);
  return <div className={`sar-linkbanner${finished ? ' is-calm' : ''}`} role="alert">
    <b>{t('link.lost', { s: ago })}</b>
    <span>{finished ? t('link.lostIdle') : t('link.lostFlying', { state: t(`sar.state.${report.state}`) })}</span>
    <small>{t('link.lostFix')}</small>
  </div>;
}
