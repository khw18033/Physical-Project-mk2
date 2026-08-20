/**
 * src/data/audit.ts
 *
 * 감사 이력 조회 (VZ-I-05).
 *
 * **패널을 열 때만 조회한다. 주기 폴링을 만들지 않는다.**
 * 감사는 확정된 과거 기록이라 폴링해도 새 값이 나오지 않고, 진행 중인 명령의 상태 변화는
 * command_result 푸시로 이미 도달하므로 주기 조회는 그냥 중복이다.
 *
 * 이 파일에는 감사 **필드 이름이 없다.** 이름 해석은 auditFieldMap 한 곳에서만 한다.
 */

import { GATEWAY } from '../transport/index.ts';
import { toAuditEntry, type AuditEntry } from './auditFieldMap.ts';

export type AuditQueryResult = {
  entries: AuditEntry[];
  error: string | null;
  /** 서버가 센 누적 조회 횟수. 주기 폴링이 없다는 것을 숫자로 확인하는 계측값. */
  serverQueryCount: number | null;
};

export async function fetchAuditTrail(entity: string, limit = 10): Promise<AuditQueryResult> {
  try {
    const res = await fetch(
      GATEWAY.http + '/audit?entity=' + encodeURIComponent(entity) + '&limit=' + String(limit),
    );
    if (!res.ok) {
      return { entries: [], error: '감사 조회 응답 ' + res.status, serverQueryCount: null };
    }
    const body = (await res.json()) as { records?: unknown[]; _query_count?: number };
    return {
      entries: (body.records ?? []).map(toAuditEntry),
      error: null,
      serverQueryCount: body._query_count ?? null,
    };
  } catch (e) {
    // 감사 저장소에 닿지 못해도 제어 화면 자체는 살아 있어야 한다 (VZ-C-02).
    return { entries: [], error: '감사 조회 실패 — ' + String(e), serverQueryCount: null };
  }
}
