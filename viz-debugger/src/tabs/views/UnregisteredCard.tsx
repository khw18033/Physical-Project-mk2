/**
 * src/tabs/views/UnregisteredCard.tsx (260921 신설 — 관문 C-a 준비)
 *
 * **값은 왔는데 레지스트리에 없는 개체.** 디버깅 도구라 **보여줄 수 있는 값은 다 보여준다** —
 * 「값이 도착했는데 화면에는 아무것도 없다」를 없애는 것이 이 카드의 전부다.
 *
 * ## 왜 필요해졌나
 *
 * `DataStore.apply` 는 레지스트리에 없는 개체도 **받아 둔다**(*"구성 변경 통지를 놓쳤을 수
 * 있다. 일단 받아 둔다"*). 그런데 화면은 `r.registry?.zone === ZONE_ID` 로 걸러서
 * **레지스트리 밖 개체는 카드가 안 나왔다.** 관문 C-a 에서 백엔드가 보내는 로봇 개체 키는
 * 목 레지스트리에 없으므로 정확히 그 상태가 된다 — 봉투는 쌓이는데 화면은 비어서,
 * 어댑터가 안 붙은 것인지 우리가 안 그리는 것인지 구분이 안 된다.
 *
 * (실제 개체 키는 여기 안 적는다 — 하드웨어 장비 id 를 아는 면은 `src/physical/` 하나다,
 * `verify:physical-port`.)
 *
 * ## 상태를 지어내지 않는다
 *
 * `DeviceCard` 를 재사용하지 않는다. 그 카드는 payload 가 `StateLayers`(3층)인 것을 전제로
 * 층별 배지를 그리는데, 백엔드 어댑터는 **원래 메시지를 통째로** payload 에 넣는다. 없는
 * 층을 그 카드에 태우면 화면이 「미배포」·「정상」 같은 **없는 판정**을 말하게 된다.
 *
 * 그래서 이 카드는 **판정을 하지 않는다.** 적는 것은 네 가지뿐이고 전부 우리가 실제로
 * 아는 사실이다: 개체 키 · 받은 봉투 수 · 채널별 마지막 `ts`·`seq` · payload 원문.
 *
 * 레지스트리 항목을 지어내지도 않는다 — 레지스트리는 남이 줄 데이터다(VZ-I-03).
 */

import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import type { ChannelSlot, EntityRecord } from '../data/store.ts';

/**
 * 카드가 훑는 채널 칸. `EntityRecord` 의 슬롯 이름 그대로다 — 와이어의 `channel` 값과
 * 일대일은 아니지만(예: `videoMeta` ↔ `video_meta`), **화면이 들고 있는 자리**를 적는 것이
 * 목적이라 저장소의 이름을 쓴다.
 */
const SLOTS = [
  'state', 'telemetry', 'heartbeat', 'videoMeta', 'actuator', 'commandResult',
  'controlLock', 'plan', 'planProgress', 'metrics', 'coverage', 'riskState', 'aiFailure',
] as const;

/** 값이 들어 있는 칸만. 빈 칸을 줄줄이 적으면 들어온 것이 안 보인다. */
function filledSlots(record: EntityRecord): readonly { name: string; slot: ChannelSlot }[] {
  const out: { name: string; slot: ChannelSlot }[] = [];
  for (const name of SLOTS) {
    const slot = record[name] as ChannelSlot | null;
    if (slot !== null && slot !== undefined) out.push({ name, slot });
  }
  return out;
}

/**
 * payload 원문 한 줄 요약. **자르는 길이를 짧게 둔다** — 카드가 목록이라 한 건이 길어지면
 * 나머지가 화면 밖으로 밀린다. 전체는 아래 펼침에 있다.
 */
function brief(payload: unknown, limit = 120): string {
  let text: string;
  try {
    text = JSON.stringify(payload);
  } catch {
    // 순환 참조 등 — 여기서 던지면 카드 하나가 판 전체를 깨뜨린다.
    return t('dg.stray.unreadable');
  }
  if (text === undefined) return String(payload);
  return text.length <= limit ? text : text.slice(0, limit) + '…';
}

export function UnregisteredCard({ record }: { record: EntityRecord }) {
  useLang();
  const slots = filledSlots(record);
  const statePayload = record.state?.payload ?? null;

  return <article className="card card--stray">
    <header className="card__head">
      <b className="card__id">{record.id}</b>
      <span className="card__badge card__badge--stray">{t('dg.stray.badge')}</span>
    </header>

    <p className="card__line">{t('dg.stray.envelopes', { n: record.envelopeCount })}</p>

    {slots.length === 0
      ? <p className="card__line card__line--dim">{t('dg.stray.noChannel')}</p>
      : <dl className="card__slots">
        {slots.map(({ name, slot }) => <div key={name}>
          <dt><code>{name}</code></dt>
          <dd><span>{slot.ts}</span><small>seq {slot.seq}</small></dd>
        </div>)}
      </dl>}

    {statePayload !== null && <details className="card__raw">
      <summary>{t('dg.stray.payload')}</summary>
      <pre>{brief(statePayload, 4000)}</pre>
    </details>}
    {statePayload !== null && <p className="card__line card__line--dim">{brief(statePayload)}</p>}
  </article>;
}
