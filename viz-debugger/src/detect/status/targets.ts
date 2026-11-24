/**
 * src/detect/status/targets.ts (261124 신설 — 객체 탐지 상태판 · 지정 탐지)
 *
 * **지정 클래스 탐지(`targeted`)가 지금 무엇을 찾고 있나.** 순수 함수다.
 *
 * 출처가 넷이고 확실함이 다르다 — 그래서 **출처를 같이 돌려주고 화면이 그것을 적는다** (계획서 §3-4).
 *
 *   mission    이 가시화가 연 스캔 판(`scanStore`) — 임무 · 판 번호 · 각도 · 판 대상
 *   otherScan  스캔 창구가 판을 쥐고 있는데(`/health` 의 `busy_scan_id`) 이 화면의 판이 아니다 — 다른 화면이 열었다
 *   profile    런처 설정 — Redis 마지막 결과의 `targets` · 프로필 이름 · 판
 *   unknown    대상 목록을 못 읽었다 — 마지막 장에 보인 라벨만(있으면)
 *
 * 「보이는 것」(마지막 장의 라벨 수)은 출처와 따로 늘 싣는다 — 찾는 것과 보이는 것은 다른 말이다.
 */

import { SCAN_TERMINAL } from '../scan/types.ts';
import type { ScanRunState } from '../scan/scanStore.ts';
import type { LatestState } from './latestStore.ts';
import { TARGETED, type DetectSourceRow } from './summary.ts';

export type TargetSource = 'mission' | 'otherScan' | 'profile' | 'unknown';

export type TargetInfo = {
  source: TargetSource;
  /** 찾는 대상. 모르면 null. */
  targets: readonly string[] | null;
  /** 마지막 장에 보인 라벨 → 개수. 모르면 null. */
  seen: Readonly<Record<string, number>> | null;
  missionId: string | null;
  scanId: string | null;
  /** 이 화면의 판이면 각도 수집 n/전체. */
  angles: { captured: number; total: number } | null;
  /** 판의 사람 말 대상(@ 편의 한국어 · 영어). */
  query: string | null;
  profileLabel: string | null;
  profileVersion: number | null;
  /** 하한을 아직 안 잰 대상(`provisional`). */
  provisional: readonly string[] | null;
  /** 대상 목록을 못 읽은 사유 — Redis 창구의 오류. */
  why: string | null;
};

/** 이 화면의 스캔 판이 지금 이 포트에서 돌고 있나. 기록에서 연 판 · 끝난 판은 아니다. */
export function liveScanOn(scan: ScanRunState | null, base: string): boolean {
  return scan !== null && scan.recorded === null && scan.base === base && !scan.cancelled && scan.failure === null
    && scan.result === null && !(scan.serverState !== null && SCAN_TERMINAL.includes(scan.serverState));
}

/** 한 포트의 지정 탐지. `targeted` 가 이 포트에서 안 돌면 null. */
export function targetInfo(row: DetectSourceRow, scan: ScanRunState | null, latest: LatestState): TargetInfo | null {
  if (row.state === 'down' || !row.live.some((m) => m.model === TARGETED)) return null;
  const last = latest.latest;
  const base: TargetInfo = {
    source: 'unknown',
    targets: null,
    seen: last?.labels ?? null,
    missionId: null,
    scanId: null,
    angles: null,
    query: null,
    profileLabel: last?.profile?.label ?? null,
    profileVersion: last?.profile?.version ?? null,
    provisional: last?.provisional ?? null,
    why: latest.error ?? (latest.empty ? 'empty' : null),
  };
  if (scan !== null && liveScanOn(scan, row.base)) {
    return {
      ...base,
      source: 'mission',
      targets: scan.targets.length > 0 ? scan.targets : (last?.targets ?? null),
      missionId: scan.missionId,
      scanId: scan.scanId,
      angles: { captured: scan.angles.filter((angle) => angle.captured === true).length, total: scan.angles.length },
      query: scan.queryKo ?? scan.query,
      profileVersion: scan.profileVersion ?? base.profileVersion,
      why: null,
    };
  }
  if (row.busyScanId !== null) {
    // Redis 결과가 그 판의 것이면 대상도 그 판의 것이다.
    const same = last?.profile?.scanId === row.busyScanId;
    return { ...base, source: 'otherScan', scanId: row.busyScanId, targets: same ? (last?.targets ?? null) : null };
  }
  if (last?.targets != null) return { ...base, source: 'profile', targets: last.targets, why: null };
  return base;
}
