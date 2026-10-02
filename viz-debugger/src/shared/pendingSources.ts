/**
 * src/shared/pendingSources.ts
 *
 * **화면이 남에게서 기다리는 것의 목록.** 자리표시 문구를 화면마다 하드코딩하지 않고
 * 여기 표 하나에 모은다 — 상대 요구사항이 또 바뀔 것이기 때문이다.
 * 화면은 `<PendingSource id="…" />` 로 ID만 참조한다.
 *
 * ## 출처
 *
 * 상대 ID는 **`피지컬팀 프로젝트 mk2 요구사항 정의서.xlsx` 김현우 시트의 `연관점` 열**에서
 * 그대로 읽었다(2026-08-31 현행판). 옛 문서에 적힌 ID를 베끼지 않았고, 제목은 상대 시트
 * (조병현=하드웨어 · 이대규=백엔드 · 진나영=AI)에서 가져왔다.
 *
 * **ID를 지어내지 않는다.** 현행 엑셀에 없으면 `missing` 에 사유를 적고 상대를 비운다.
 * **사람 이름을 쓰지 않는다.** 파트 이름으로만 적는다.
 *
 * ## 네 가지가 다 있어야 한다
 *
 *   what   무엇을 기다리는가 — 사람 말로
 *   from   누가 보내는가 — 파트와 상대 ID. 여럿을 거치면 **순서대로**
 *   ours   우리 쪽 자리 (VZ-*) — 이게 있어야 "안 만든 게 아니라 못 받은 것"이 증명된다
 *   plane  어느 평면으로 오는가 — 세 평면을 나눈 이유가 여기서 드러난다 (DF-1b)
 *
 * `verify:placeholder-default` 가 넷이 다 찼는지 검사한다.
 */

/** 어느 평면으로 오는가 (DF-1b). */
export type Plane = 'business' | 'control' | 'observability' | 'media';

/** 평면 넷. **글자는 사전에 있다** — 이 목록은 「무엇이 있는가」만 말한다 (지시서 §2 ②). */
export const PLANES: readonly Plane[] = ['business', 'control', 'observability', 'media'];


export type Sender = {
  /** 파트 이름. **사람 이름을 쓰지 않는다.** */
  part: 'hardware' | 'ai' | 'backend';
  /** 상대 요구사항 ID. 현행 엑셀에 실재하는 것만 쓴다. */
  id: string;
};

export type PendingSourceSpec = {
  id: string;
  /** 누가 보내는가. **거치는 순서대로** 적는다. */
  from: Sender[];
  /** 우리 쪽 자리. */
  ours: string[];
  plane: Plane;
  /**
   * 상대가 아직 없을 때의 사유. 있으면 화면에 「상대 없음 — 회의 안건」이 크게 붙는다.
   * **없는 것을 있는 것처럼 적는 쪽이 훨씬 나쁘다.**
   */
  missing?: string;
};

const HW = (id: string): Sender => ({ part: 'hardware', id });
const AI = (id: string): Sender => ({ part: 'ai', id });
const BE = (id: string): Sender => ({ part: 'backend', id });

export const PENDING_SOURCES: PendingSourceSpec[] = [
  // ── 공유 계층 ──────────────────────────────────────────────────────────────
  {
    id: 'registry',    from: [
      HW('HW-C-04'),
      HW('HW-C-07'),
      BE('BE-C-02'),
      BE('BE-T-04'),
      BE('BE-Q-03'),
    ],
    ours: ['VZ-I-03'],
    plane: 'business',
  },
  {
    id: 'role-scope',    from: [
      BE('BE-Q-04'),
      BE('BE-C-02'),
    ],
    ours: ['VZ-C-01', 'VZ-C-04'],
    plane: 'business',
  },
  {
    id: 'ai-failure-alert',    from: [
      AI('AI-O-02'),
      BE('BE-X-05'),
    ],
    ours: ['VZ-I-10'],
    plane: 'observability',
  },

  // ── 탭② 구역 현황판 ───────────────────────────────────────────────────────
  {
    id: 'zone-summary',    from: [
      HW('HW-R-02'),
      HW('HW-S-05'),
      HW('HW-S-07'),
      HW('HW-C-04'),
      BE('BE-T-04'),
      BE('BE-C-05'),
    ],
    ours: ['VZ-U-01'],
    plane: 'business',
  },
  {
    id: 'device-cards',    from: [
      HW('HW-R-03'),
      HW('HW-S-02'),
      HW('HW-A-01'),
      HW('HW-S-07'),
      BE('BE-C-01'),
      BE('BE-T-03'),
      BE('BE-T-06'),
    ],
    ours: ['VZ-I-01', 'VZ-I-02', 'VZ-U-01'],
    plane: 'business',
  },
  {
    // 대본 재생(260831) 신설 — 탭② 구역 맵 미니뷰. 지금 scenario 모드에서 그리는 커버리지는
    // 대본이 만든 **합성본**이고, 실제로는 아래 백엔드 디지털 트윈이 줄 데이터다(A).
    // 가상 맵 본체는 Unity 트윈(VZ-U-02 · 별도 앱) 몫이며 이 미니뷰는 웹 시연용 축소판이다.
    id: 'zone-map',    from: [
      BE('DT-04'),
      BE('DT-05'),
    ],
    ours: ['VZ-U-01', 'VZ-U-02'],
    plane: 'business',
  },
  {
    id: 'risk-state',    from: [
      HW('HW-S-03'),
      AI('AI-R-02'),
      AI('AI-R-03'),
      BE('BE-A-04'),
    ],
    ours: ['VZ-I-08'],
    plane: 'business',
  },

  // ── 탭③ 제어 패널 ─────────────────────────────────────────────────────────
  {
    id: 'actuator-state',    from: [
      HW('HW-A-01'),
      HW('HW-A-05'),
      HW('HW-S-07'),
      BE('BE-T-04'),
    ],
    ours: ['VZ-O-05', 'VZ-U-01'],
    plane: 'business',
  },
  {
    id: 'command-result',    from: [
      HW('HW-C-06'),
      HW('HW-A-03'),
      HW('HW-A-04'),
      BE('BE-X-01'),
      BE('BE-X-03'),
    ],
    ours: ['VZ-O-01', 'VZ-O-02'],
    plane: 'control',
  },
  {
    id: 'audit-history',    from: [
      HW('HW-C-06'),
      BE('BE-X-02'),
      BE('BE-S-05'),
      BE('BE-Q-02'),
    ],
    ours: ['VZ-I-05'],
    plane: 'business',
  },
  {
    id: 'action-catalog',    from: [
      HW('HW-A-02'),
      HW('HW-R-05'),
      BE('BE-A-01'),
      BE('BE-A-02'),
    ],
    ours: ['VZ-O-01'],
    plane: 'control',
  },

  // ── 탭④ 지표 조회 ─────────────────────────────────────────────────────────
  {
    id: 'metrics-query',    from: [
      HW('HW-C-05'),
      AI('AI-O-01'),
      BE('BE-S-02'),
      BE('BE-S-01'),
      BE('BE-S-03'),
      BE('BE-Q-01'),
      BE('BE-T-05'),
    ],
    ours: ['VZ-I-04', 'VZ-C-03'],
    plane: 'observability',
  },
  {
    id: 'client-metrics-sink',    from: [
      BE('BE-S-02'),
      BE('BE-S-01'),
    ],
    ours: ['VZ-O-04'],
    plane: 'observability',
  },
  {
    id: 'metrics-push',    from: [
      HW('HW-C-05'),
      BE('BE-S-03'),
      BE('BE-S-06'),
    ],
    ours: ['VZ-I-04', 'VZ-C-03'],
    plane: 'observability',
  },

  // ── 탭⑤ 영상 오버레이 ─────────────────────────────────────────────────────
  {
    id: 'video-stream',    from: [
      HW('HW-R-07'),
      HW('HW-S-06'),
      AI('AI-C-08'),
      AI('AI-C-14'),
      BE('BE-T-05'),
    ],
    ours: ['VZ-I-06'],
    plane: 'media',
  },
  {
    id: 'detections',    from: [
      HW('HW-R-04'),
      AI('AI-N-01'),
      AI('AI-E-01'),
      AI('AI-E-04'),
      AI('AI-C-03'),
      BE('BE-C-03'),
    ],
    ours: ['VZ-I-07'],
    plane: 'business',
  },
  {
    id: 'tracking',    from: [
      AI('AI-S-01'),
      AI('AI-S-02'),
      AI('AI-S-03'),
      BE('DT-01'),
      BE('DT-02'),
    ],
    ours: ['VZ-I-09'],
    plane: 'business',
  },

  // 탭⑥(파이프라인 편집기)의 `node-catalog`·`pipeline-runner` 항목은 2026-08-31에 지웠다.
  // 먼저 실행기(유일한 「상대 없음」)를 없앴고, 같은 날 탭 자체를 제거했다 —
  // 노드 에디터의 구현 방향이 탭①로 확정됐기 때문(전회의). 원형은 web-dashboard(기준선)에 있다.

  // ── 임무 이력 ─────────────────────────────────────────────────────────────
  {
    id: 'mission-history',    from: [
      BE('BE-S-01'),
      BE('BE-Q-01'),
    ],
    ours: ['VZ-D-04'],
    plane: 'business',
  },

  // ── 탭① 임무 설계 및 디버깅 — **장비 실측값만** ────────────────────────────
  {
    id: 'robot-status-strip',    from: [
      HW('HW-R-02'),
      HW('HW-R-03'),
      HW('HW-C-04'),
      HW('HW-C-07'),
      BE('BE-T-04'),
    ],
    ours: ['VZ-D-07'],
    plane: 'business',
  },
  {
    id: 'hardware-pool-status',    from: [
      HW('HW-C-04'),
      HW('HW-S-07'),
      HW('HW-A-05'),
      AI('AI-O-04'),
      BE('BE-C-02'),
    ],
    ours: ['VZ-D-07'],
    plane: 'business',
  },
];

const BY_ID = new Map(PENDING_SOURCES.map((spec) => [spec.id, spec]));

export function pendingSource(id: string): PendingSourceSpec {
  const spec = BY_ID.get(id);
  // 화면이 없는 ID를 참조하면 조용히 빈 자리를 그리는 대신 즉시 터뜨린다 —
  // 자리표시가 사라지는 것이 이 작업에서 제일 나쁜 실패다.
  if (!spec) throw new Error(`pendingSources 에 없는 id: ${id}`);
  return spec;
}
