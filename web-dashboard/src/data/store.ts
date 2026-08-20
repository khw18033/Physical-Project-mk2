/**
 * src/data/store.ts
 *
 * 구독 결과를 화면이 쓰는 형태로 보관한다.
 *
 * 지키는 규칙 넷.
 *  1. **상태를 단일 값으로 뭉쳐 저장하지 않는다** (REQ-205). 3층 원본을 그대로 들고 있고
 *     표시값은 읽는 쪽에서 파생시킨다. 뭉쳐 넣는 순간 원천이 섞여 되돌릴 수 없다.
 *  2. 채널별 마지막 봉투를 통째로 보관한다. payload만 꺼내 두면 ts·seq·quality·aggregation이
 *     사라져서 나중에 "이 값이 언제 것인지 / 집약값인지"를 물을 수 없다.
 *  3. 쓰기는 매 수신마다, 알림은 병합 창으로 (MergeScheduler).
 *  4. 레지스트리에만 있고 값이 한 번도 안 온 대상도 **레코드가 존재한다.** 미배포 카드의 근거.
 */

import type { ActuatorState, CommandResult, Envelope, StateLayers } from '../transport/index.ts';
import { normalizeAggregation, type Aggregation } from './aggregation.ts';
import { MergeScheduler } from './mergeScheduler.ts';
import { IMMEDIATE_AVAILABILITY } from './constants.ts';
import type { Registry, RegistryEntity } from './registry.ts';

/** 채널 하나의 마지막 수신 결과. 봉투 메타를 잃지 않는다. */
export type ChannelSlot<T = unknown> = {
  payload: T;
  /** 서버 시각. 화면의 경과 시간 계산은 이 값과 payload의 last_seen으로만 한다. */
  ts: string;
  seq: number;
  quality: Envelope['quality'];
  aggregation: Aggregation;
  scope: Envelope['scope'];
};

export type EntityRecord = {
  id: string;
  /** 레지스트리에서 온 정적 구성. 값이 없어도 이것만으로 카드를 그린다. */
  registry: RegistryEntity | null;
  /** 상태 3층 원본 (REQ-205). 뭉치지 않는다. */
  state: ChannelSlot<StateLayers> | null;
  telemetry: ChannelSlot | null;
  heartbeat: ChannelSlot | null;
  videoMeta: ChannelSlot | null;
  /** 표준 3층과 별개인 액추에이터 도메인 어휘 (VZ-U-01). */
  actuator: ChannelSlot<ActuatorState> | null;
  commandResult: ChannelSlot<CommandResult> | null;
  metrics: ChannelSlot | null;
  /** 이 대상에서 받은 총 봉투 수. 계측·디버깅용. */
  envelopeCount: number;
};

function emptyRecord(id: string, registry: RegistryEntity | null): EntityRecord {
  return {
    id,
    registry,
    state: null,
    telemetry: null,
    heartbeat: null,
    videoMeta: null,
    actuator: null,
    commandResult: null,
    metrics: null,
    envelopeCount: 0,
  };
}

function toSlot<T>(env: Envelope): ChannelSlot<T> {
  return {
    payload: env.payload as T,
    ts: env.ts,
    seq: env.seq,
    quality: env.quality,
    // VZ-C-03 — 여기서 정규화해 두면 아래 코드가 축약형/객체형을 신경 쓰지 않는다.
    aggregation: normalizeAggregation(env.aggregation),
    scope: env.scope,
  };
}

export class DataStore {
  readonly merge = new MergeScheduler();

  private records = new Map<string, EntityRecord>();
  /** useSyncExternalStore가 참조 비교로 변화를 감지하도록 스냅샷을 갈아 끼운다. */
  private snapshot: ReadonlyMap<string, EntityRecord> = this.records;
  private version = 0;
  private dirty = false;

  private registry: Registry | null = null;
  private registryError: string | null = null;

  constructor() {
    // 병합 창이 닫힐 때 스냅샷을 새로 만들어 구독자에게 넘긴다.
    this.merge.subscribe(() => this.commit());
  }

  // ── 레지스트리 ─────────────────────────────────────────────────────────────

  /**
   * 존재해야 할 목록을 먼저 심는다. 값이 한 번도 안 오는 대상(robot-03)도
   * 여기서 레코드가 생기므로 화면에 카드가 나타난다.
   */
  setRegistry(registry: Registry, error: string | null): void {
    this.registry = registry;
    this.registryError = error;
    for (const e of registry.entities) {
      const existing = this.records.get(e.id);
      if (existing) existing.registry = e;
      else this.records.set(e.id, emptyRecord(e.id, e));
    }
    this.dirty = true;
    this.merge.flushNow();
  }

  getRegistry(): Registry | null {
    return this.registry;
  }

  getRegistryError(): string | null {
    return this.registryError;
  }

  // ── 수신 ───────────────────────────────────────────────────────────────────

  /** 봉투 1건 반영. **매 수신마다 호출되며 하나도 버리지 않는다.** */
  apply(env: Envelope): void {
    let rec = this.records.get(env.entity);
    if (!rec) {
      // 레지스트리에 없는데 값이 오는 경우 — 구성 변경 통지를 놓쳤을 수 있다. 일단 받아 둔다.
      rec = emptyRecord(env.entity, null);
      this.records.set(env.entity, rec);
    }
    rec.envelopeCount += 1;

    let immediate = false;

    switch (env.channel) {
      case 'state': {
        const prev = rec.state?.payload.availability ?? null;
        const next = toSlot<StateLayers>(env);
        rec.state = next;
        // 오프라인·판단불가 **전이**는 병합 창을 기다리지 않는다 (VZ-U-01 "오프라인 감지는 즉시").
        const nextAvail = next.payload.availability;
        immediate = nextAvail !== prev && nextAvail !== null && IMMEDIATE_AVAILABILITY.has(nextAvail);
        break;
      }
      case 'telemetry':
        rec.telemetry = toSlot(env);
        break;
      case 'heartbeat':
        rec.heartbeat = toSlot(env);
        break;
      case 'video_meta':
        rec.videoMeta = toSlot(env);
        break;
      case 'actuator_state':
        rec.actuator = toSlot<ActuatorState>(env);
        break;
      case 'command_result':
        rec.commandResult = toSlot<CommandResult>(env);
        break;
      case 'metrics':
        rec.metrics = toSlot(env);
        break;
      default:
        break;
    }

    this.dirty = true;
    if (immediate) this.merge.flushNow();
    else this.merge.mark();
  }

  // ── 읽기 ───────────────────────────────────────────────────────────────────

  private commit(): void {
    if (!this.dirty) return;
    this.dirty = false;
    this.version += 1;
    // 레코드는 제자리에서 갱신하고 Map만 새로 만든다 —
    // 대상 20개 규모에서 매 창마다 전체를 깊은 복사할 이유가 없다.
    this.snapshot = new Map(this.records);
    for (const l of this.listeners) l();
  }

  private readonly listeners = new Set<() => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): ReadonlyMap<string, EntityRecord> => this.snapshot;

  getVersion = (): number => this.version;

  get(id: string): EntityRecord | null {
    return this.snapshot.get(id) ?? null;
  }
}
