// scripts/lib/droneFixtures.mjs (260921 신설 — 드론 연결 1단계)
//
// **드론 흉내는 검사 코드 안에만 있다.**
//
// 목 게이트웨이(`gateway/`)에도, `src/` 에도 드론 목을 넣지 않는다. 상태는 백엔드 `/state`
// 로 오는 것이고 목 게이트웨이는 그 경로를 흉내 내는 물건이 아니다 — 거기에 드론을 심으면
// 「목에서는 보이는데 실제로는 안 보이는」 상태를 만들고, 그 차이를 무대에서 발견한다.
//
// ## 값은 전부 계약 문서에서 그대로 옮겼다
//
// hex 는 pi3 가 **실제 브로커에서 캡처한 것**이다(계약 §4·§5·§6). 우리가 만든 바이트가
// 아니라 장비가 보낸 바이트라, 이걸로 통과하면 실물에서도 통과한다. 지어낸 값이 하나라도
// 섞이면 그 검사는 우리 상상을 확인하는 것이 된다.

/** 계약 §4 — `capability{device_id:"x500-001", actions:["ping"]}` (18B). */
export const CAPABILITY_HEX = '3a100a08783530302d303031120470696e67';

/** 계약 §5 — `ping` 응답 넷. 순서 그대로다. */
export const PING_REPLY_HEX = [
  // acceptance{command_id:"live-ping-1", accepted:true}
  '1a0f0a0b6c6976652d70696e672d311001',
  // status{state:"EXECUTING"}
  '22180a0b6c6976652d70696e672d311209455845435554494e47',
  // status{state:"EXECUTING", detail:"executing"}
  '22230a0b6c6976652d70696e672d311209455845435554494e471a09657865637574696e67',
  // result{SUCCEEDED, uptime_s:3.8, fc_link:0}  ← FC 링크 없음
  '2a380a0b6c6976652d70696e672d3110011a130a08757074696d655f73116666666666660e401a120a0766635f6c696e6b110000000000000000',
];

/** 계약 §6 — 미선언 `arm` 은 `acceptance` 하나로 거부되고 `result` 가 없다. */
export const REJECT_ARM_HEX =
  '1a330a0a6c6976652d61726d2d311a250a0d554e494d504c454d454e5445441214616374696f6e206e6f7420737570706f72746564';

export function bytes(hex) {
  return Uint8Array.from(hex.match(/../g).map((pair) => parseInt(pair, 16)));
}

/** 계약 §2 — 식별자. 코드가 이 값을 상수로 갖지 않는다는 것을 검사가 본다. */
export const DRONE = {
  entityId: 'x500-001',
  nodeId: 'pi3',
  zoneId: 'zoneA',
  entityType: 'drone',
  deviceType: 'x500_drone',
};

/**
 * 계약 §7-2 — retained `status` 1건. **늦게 붙은 웹이 구독 즉시 받는 것**이고,
 * `Capability` 를 놓쳤을 때 장비 id·종류를 알려 주는 유일한 길이다.
 */
export function statusBody(over = {}) {
  return {
    schema_version: '1.1', source_id: DRONE.entityId, node_id: DRONE.nodeId, zone_id: DRONE.zoneId,
    timestamp: '2026-09-21T20:43:48.225+09:00', session_id: '3e276e814c9b', channel: 'status',
    event: 'summary', status: 'online', device_status: 'degraded',
    registration: {
      entity_id: DRONE.entityId, node_id: DRONE.nodeId, zone_id: DRONE.zoneId,
      entity_type: DRONE.entityType, device_type: DRONE.deviceType,
      fw_version: '0.3.0', mac: '2c:cf:67:e7:cf:67', ip: '127.0.0.1',
    },
    uptime_s: 40.0, fc_link: false, fc_link_age_s: null, router_mode: 'none',
    link: 'degraded', udp_port: 14543, tx_bytes: 0, state_interval_s: 1.0,
    battery: null, flight: null,
    ...over,
  };
}

/**
 * 계약 §13-5 — 실제로 발행된 `state` 1건(원문 그대로). FC 분리 상태라 값이 전부 `null` 이다.
 *
 * **이것은 MQTT 로 안 받는다.** 백엔드 브릿지가 받아 `/state` 로 넘기고, 화면은 계약 봉투로
 * 만난다(`droneStateEnvelope`). 원문을 여기 두는 이유는 그 봉투의 `payload` 가 이것이기
 * 때문이다 — 백엔드가 모양을 바꾸지 않는다는 것이 §13 의 약속이다.
 */
export function stateBody(over = {}) {
  return {
    schema_version: '1.1', source_id: DRONE.entityId, node_id: DRONE.nodeId, zone_id: DRONE.zoneId,
    timestamp: '2026-09-21T21:06:50.795+09:00', session_id: 'a93f81192e02', sequence_id: 173,
    channel: 'state', reason: 'periodic', device_status: 'degraded', link: 'degraded',
    fc_link: false, fc_link_age_s: null, router_mode: 'none',
    battery: null, flight: null, gps: null, attitude: null, altitude: null, warnings: [],
    ...over,
  };
}

/** FC 가 붙었을 때 — 계약 §9 가 적어 둔 0단계 실측값(전압 15.75V·74%·AUTO.LOITER·DISARMED). */
export function liveStateBody(over = {}) {
  return stateBody({
    reason: 'fc_link_up', device_status: 'ok', link: 'ok', fc_link: true, fc_link_age_s: 0.2,
    router_mode: 'drone',
    battery: { voltage_v: 15.75, current_a: 12.2, remaining_pct: 74.0, consumed_mah: 891, source: 'SYS_STATUS', age_s: 0.2 },
    flight: { armed: false, mode: 'AUTO.LOITER', custom_mode: 50593792, base_mode: 81, system_status: 0, landed_state: 'ON_GROUND', age_s: 0.1 },
    gps: { fix_type: 0, fix: 'NO_GPS', satellites: 0, lat: null, lon: null, eph_m: null, age_s: 0.3 },
    attitude: { roll_deg: -0.29, pitch_deg: 1.46, yaw_deg: 108.5, age_s: 0.01 },
    ...over,
  });
}

/**
 * **백엔드 `/state` 가 넘겨 주는 모양** — 계약 봉투다.
 *
 * 드론은 `zoneA/drone/x500-001/state` 로 발행하고, 백엔드 브릿지가 Kafka 를 거쳐 이 봉투로
 * 바꿔 웹에 흘린다. 화면이 만나는 것은 **이쪽뿐**이고 토픽 문자열은 여기 없다 —
 * `entity`·`node`·`channel` 세 축만 있다.
 */
export function droneStateEnvelope(over = {}) {
  return {
    zone: DRONE.zoneId, node: DRONE.nodeId, entity: DRONE.entityId, channel: 'state',
    ts: '2026-09-21T21:06:50.795+09:00', seq: 173,
    payload: stateBody(),
    quality: 'good', aggregation: 'raw', scope: 'all', coordinate_frame: null,
    ...over,
  };
}
