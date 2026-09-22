/**
 * src/tabs/data/stateRows.ts (260922 신설 — 드론 카드 안을 채운다)
 *
 * **`/state` 본문을 화면이 그릴 줄로 바꾼다.** 표 하나와 함수 하나다.
 *
 * ## 이것이 「어댑터 프로파일」의 자리다 — 그리고 그것이 없다는 표시다
 *
 * 요구사항은 이렇게 적혀 있다.
 *
 * > 대상별로 조회할 상세 항목은 **어댑터 프로파일에서 제공**하며 화면 코드에 기종별
 * > 항목표를 두지 않는다.
 *
 * 그 프로파일이 아직 없다. 계약(`문서/CONTRACT_x500.md` §7-1)은 **필드 이름과 단위를
 * 페이로드에 안 싣는다** — `battery.remaining_pct` 라는 이름만 오고 「배터리 잔량, %」라는
 * 사실은 문서에만 있다. 그래서 표를 우리가 든다. **한 곳이고, 여기다.**
 *
 * 지시서(260921 §원칙 2)가 그 경우를 미리 적어 두었다 — 「계약상 불가능하면 최소한 항목표를
 * 한 곳에 두고 **보고서에 한계로 적는다**」. 보고서에 적었다.
 *
 * ## 기종으로 가르지 않는다
 *
 * `if (드론)` 이 아니다. **필드 이름으로 찾는 사전**이고, 들어온 본문에 있는 것만 줄이 된다.
 * 나중에 Go1 이 `/state` 로 옮겨 와도(지시 — 「Go1 도 나중엔 서버 연결로」) 같은 표를 지나간다.
 * 겹치는 필드는 그대로 그려지고, 없는 필드는 줄이 안 생긴다. 기종을 물어볼 일이 없다.
 *
 * 표에 없는 필드는 **버리지 않고 이름 그대로 적는다**(`extra`). 장비가 새 필드를 보내기
 * 시작했을 때 화면에서 그 사실이 보여야 한다 — 표에 없다고 조용히 사라지면, 값이 오는데도
 * 안 온다고 읽는다.
 *
 * ## 안 온 것은 줄을 안 만든다
 *
 * FC 링크가 없으면 계약상 `battery`·`flight`·`gps`·`attitude`·`altitude` 가 전부 `null` 이다
 * (§7-1 — 마지막 값을 현재값처럼 재사용하지 않는다). 그때 빈 줄 스무 개 대신 **`fc_link ✕`
 * 한 줄이 이유를 말한다.**
 */

import type { TelemetryRow } from '../../shared/deviceTelemetry.ts';

/** 표 한 줄. `path` 는 본문에서 찾아갈 자리다. */
type FieldSpec = {
  /** `battery.remaining_pct` 처럼 점으로 이은 자리. */
  path: string;
  labelKey: string;
  /** 값 뒤에 붙일 것. 단위는 번역하지 않는다 — `V`·`A`·`%`·`m` 은 어느 언어에서도 같다. */
  unit?: string;
  /** 소수 몇 자리로 자를 것인가. 없으면 온 그대로. */
  digits?: number;
  /** 참/거짓이면 낱말이어야 한다 — 그때 쓸 사전 키 둘. */
  bool?: { yes: string; no: string };
  /** 값을 그대로 믿으면 안 되는 줄. 계약이 의심한 값에만 붙인다. */
  noteKey?: string;
  /** 카드 한 줄에도 나오는가. */
  onCard?: boolean;
  /** 이 값의 나이를 어디서 읽는가. 계약이 묶음마다 `age_s` 를 준다. */
  agePath?: string;
};

/**
 * **계약 §7-1 의 필드표.** 차례가 화면의 차례다 — 위에서부터 무대에서 먼저 봐야 하는 것이다.
 *
 * 뺀 것 둘을 적어 둔다. 지어내지 않는 것만큼이나 **안 쓰기로 한 것도 이유가 있어야 한다.**
 *
 *   `flight.system_status`  계약이 「arm 판정에 쓰지 말 것」이라고 못박았다 — pi3 실측에서
 *                           0(UNINIT)으로 온다. 화면에 두면 누군가 그것으로 판정한다.
 *   `flight.custom_mode` ·  원본 정수다. `mode` 문자열이 같은 사실을 사람이 읽을 수 있게
 *   `flight.base_mode`      말한다 — 둘을 같이 두면 어느 쪽이 답인지 흐려진다.
 */
const FIELDS: readonly FieldSpec[] = [
  // ── 링크가 먼저다. 아래 값들이 왜 없는지를 이 셋이 설명한다 ─────────────────
  { path: 'device_status', labelKey: 'dt.deviceStatus' },
  { path: 'link', labelKey: 'dt.link' },
  {
    path: 'fc_link', labelKey: 'dt.fcLink', onCard: true, agePath: 'fc_link_age_s',
    bool: { yes: 'dt.yes', no: 'dt.no' },
  },
  { path: 'router_mode', labelKey: 'dt.routerMode' },

  // ── 배터리 (계약 §7-1 `battery`) ─────────────────────────────────────────────
  { path: 'battery.remaining_pct', labelKey: 'dt.battery', unit: '%', digits: 0, onCard: true, agePath: 'battery.age_s' },
  { path: 'battery.voltage_v', labelKey: 'dt.voltage', unit: 'V', digits: 2, agePath: 'battery.age_s' },
  /**
   * **계약이 스스로 의심한 값이다** — 「참고값. 실측에서 디스암 상태인데 12.2A 로 읽혔다
   * (스케일 의심)」. 빼지 않고 그리되 그 사실을 같이 적는다. 빼면 왜 없는지 모르고,
   * 그냥 그리면 12.2A 를 사실로 읽는다.
   */
  { path: 'battery.current_a', labelKey: 'dt.current', unit: 'A', digits: 1, noteKey: 'dt.note.suspect', agePath: 'battery.age_s' },
  { path: 'battery.consumed_mah', labelKey: 'dt.consumed', unit: 'mAh', digits: 0, agePath: 'battery.age_s' },

  // ── 비행 (계약 §7-1 `flight`) ────────────────────────────────────────────────
  { path: 'flight.armed', labelKey: 'dt.armed', onCard: true, bool: { yes: 'dt.armedYes', no: 'dt.armedNo' }, agePath: 'flight.age_s' },
  { path: 'flight.mode', labelKey: 'dt.flightMode', onCard: true, agePath: 'flight.age_s' },
  { path: 'flight.landed_state', labelKey: 'dt.landedState', agePath: 'flight.age_s' },

  // ── 고도·자세 ────────────────────────────────────────────────────────────────
  { path: 'altitude.relative_m', labelKey: 'dt.altRelative', unit: 'm', digits: 2, agePath: 'altitude.age_s' },
  { path: 'altitude.amsl_m', labelKey: 'dt.altAmsl', unit: 'm', digits: 2, agePath: 'altitude.age_s' },
  { path: 'attitude.yaw_deg', labelKey: 'dt.yaw', unit: '°', digits: 1, agePath: 'attitude.age_s' },
  { path: 'attitude.roll_deg', labelKey: 'dt.roll', unit: '°', digits: 1, agePath: 'attitude.age_s' },
  { path: 'attitude.pitch_deg', labelKey: 'dt.pitch', unit: '°', digits: 1, agePath: 'attitude.age_s' },

  // ── GPS. `lat`·`lon` 은 fix 가 없으면 계약이 null 을 준다 — 그때 줄이 안 생긴다 ──
  { path: 'gps.fix', labelKey: 'dt.gpsFix', agePath: 'gps.age_s' },
  { path: 'gps.satellites', labelKey: 'dt.satellites', digits: 0, agePath: 'gps.age_s' },
  { path: 'gps.eph_m', labelKey: 'dt.eph', unit: 'm', digits: 1, agePath: 'gps.age_s' },
  { path: 'gps.lat', labelKey: 'dt.lat', digits: 6, agePath: 'gps.age_s' },
  { path: 'gps.lon', labelKey: 'dt.lon', digits: 6, agePath: 'gps.age_s' },
];

/** 표가 이미 다루는 자리. `extra` 가 같은 값을 두 번 적지 않게 한다. */
const COVERED = new Set<string>([
  ...FIELDS.map((f) => f.path),
  ...FIELDS.map((f) => f.agePath).filter((p): p is string => p !== undefined),
  // 봉투가 이미 말하는 것들 — 줄로 만들면 같은 사실이 두 번 적힌다.
  'schema_version', 'source_id', 'node_id', 'zone_id', 'timestamp', 'session_id',
  'sequence_id', 'channel', 'reason', 'warnings',
]);

/** 묶음 이름(`battery` 등)도 덮인 것으로 본다 — 그 속은 위에서 이미 훑었다. */
const GROUPS = new Set(
  FIELDS.map((f) => f.path.split('.')).filter((parts) => parts.length > 1).map((parts) => parts[0]!),
);

function dig(body: unknown, path: string): unknown {
  let cursor: unknown = body;
  for (const part of path.split('.')) {
    if (cursor === null || typeof cursor !== 'object') return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return cursor;
}

function ageOf(body: unknown, spec: FieldSpec): number | null {
  if (spec.agePath === undefined) return null;
  const raw = dig(body, spec.agePath);
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

/** 숫자·문자·참거짓만 줄이 된다. 객체와 배열은 여기서 안 편다 — 표가 자리를 지정한다. */
function plain(value: unknown, digits?: number): string | null {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    return digits === undefined ? String(value) : value.toFixed(digits);
  }
  if (typeof value === 'string') return value === '' ? null : value;
  return null;
}

/**
 * 본문 한 건 → 줄들. **없는 값은 줄이 안 된다.**
 *
 * @param body `/state` 봉투의 payload. 모양을 모르는 것이 와도 던지지 않는다 —
 *             여기서 던지면 상태 구독 하나가 화면 전체를 멈춘다.
 */
export function stateRows(body: unknown): TelemetryRow[] {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return [];
  const rows: TelemetryRow[] = [];

  for (const spec of FIELDS) {
    const raw = dig(body, spec.path);
    if (raw === undefined || raw === null) continue;

    if (spec.bool !== undefined) {
      if (typeof raw !== 'boolean') continue;
      rows.push({
        labelKey: spec.labelKey, value: '', valueKey: raw ? spec.bool.yes : spec.bool.no,
        ageS: ageOf(body, spec), ...(spec.noteKey ? { noteKey: spec.noteKey } : {}),
        ...(spec.onCard ? { onCard: true } : {}),
      });
      continue;
    }

    const text = plain(raw, spec.digits);
    if (text === null) continue;
    rows.push({
      labelKey: spec.labelKey,
      value: spec.unit === undefined ? text : `${text} ${spec.unit}`,
      ageS: ageOf(body, spec), ...(spec.noteKey ? { noteKey: spec.noteKey } : {}),
      ...(spec.onCard ? { onCard: true } : {}),
    });
  }

  // ── 경고 (계약 §7-1 `warnings` — FC STATUSTEXT 최근 5줄) ─────────────────────
  //
  // **줄이 몇 개든 그대로 적는다.** 잘라 내면 무대에서 마지막 경고를 못 본다.
  const warnings = dig(body, 'warnings');
  if (Array.isArray(warnings)) {
    for (const item of warnings) {
      if (item === null || typeof item !== 'object') continue;
      const record = item as Record<string, unknown>;
      const text = plain(record.text);
      if (text === null) continue;
      const severity = plain(record.severity);
      rows.push({
        labelKey: 'dt.warning',
        value: severity === null ? text : `${severity} · ${text}`,
        ageS: typeof record.age_s === 'number' ? record.age_s : null,
        onCard: true,
      });
    }
  }

  // ── 표에 없는 최상위 필드 — 이름 그대로 적는다 (위 주석) ─────────────────────
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (COVERED.has(key) || GROUPS.has(key)) continue;
    const text = plain(value);
    if (text === null) continue;
    // 사전에 없는 이름이라 **키가 아니라 글자**다. 화면이 그것을 그대로 적는다 —
    // 번역할 수 없는 것을 번역된 척하지 않는다.
    rows.push({ labelKey: null, rawLabel: key, value: text, ageS: null });
  }

  return rows;
}
