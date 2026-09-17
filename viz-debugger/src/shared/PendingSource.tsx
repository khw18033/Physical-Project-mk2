/**
 * src/shared/PendingSource.tsx
 *
 * 남이 줄 데이터가 있어야 할 자리에 **무엇을 · 누구에게서 기다리는지**를 그린다.
 *
 * 빈칸으로 두는 것이 아니다. 빈칸은 "우리가 안 만들었다"로 읽히고, 자리표시는
 * **"못 받았다 · 누가 주면 된다"**로 읽힌다. 그 차이가 이 작업의 전부다.
 *
 * ## 크기를 부모에서 받는다
 *
 * 나중에 진짜 데이터가 오면 **이 자리에 그대로 들어가야** 하므로 원래 자리의 크기를 유지한다.
 * 화면이 텅 비어 보이면 실패다. 그래서 높이를 스스로 정하지 않고 `minHeight`/`fill` 로 받는다.
 *
 * ## 목 렌더 모드
 *
 * `renderMode` 가 `'mock'` 이면 `children`(원래의 목 화면)을 그린다. 이때 **지워지지 않는
 * 목 배지**가 그 자리에 함께 뜬다 — 토글을 켠 것을 잊고 시연하면 원래 문제로 되돌아간다.
 * 배지를 끄는 경로는 만들지 않는다.
 */

import type { ReactNode } from 'react';
import { AXIS_LABEL, type ScenarioAxis } from '../scenarios/axes.ts';
import { scriptsWithAxis } from '../scenarios/scriptScope.ts';
import { pendingSource } from './pendingSources.ts';
import { t } from '../i18n/dict.ts';
import { useLang } from './language.ts';
import { useMockRender, useScenarioAxis, useScenarioCast } from './renderMode.ts';

type Props = {
  /** `pendingSources.ts` 의 id. */
  id: string;
  /** 원래 자리의 최소 높이(px). 자리를 유지하려면 준다. */
  minHeight?: number;
  /** 부모 높이를 꽉 채운다. */
  fill?: boolean;
  /** 한 줄짜리 좁은 자리(카드 안 한 행 등). 네 가지는 툴팁으로 간다. */
  inline?: boolean;
  /**
   * 이 자리가 담는 **장비 ID** (260831 — scenario 모드).
   * 대본 재생 중 그 장비가 대본의 cast 에 있으면 값을 그린다 — 대본이 몰아 주는
   * 합성값이라는 배지와 함께. cast 밖이거나 entity 가 없으면 여전히 자리표시다.
   * 「이 값은 대본이 준 것」과 「이 자리는 아직 아무도 안 준 것」이 그렇게 갈린다.
   */
  entity?: string;
  /**
   * 이 자리가 담는 **축** (260831 — 사이트 개선 요구 2).
   *
   * 시나리오 모드에서 이 축을 현재 대본이 몰지 않으면 「연결 예정」이 아니라
   * **「이 대본에는 해당 없음」**을 그린다. 1편의 수문 자리, 3편의 영상 자리가 그렇다 —
   * 그 자리는 못 받은 것이 아니라 이 대본의 이야기에 없는 것이고, 다른 편에서는 실제로 온다.
   * 그 구분이 없으면 시연에서 "왜 여긴 비었냐"에 답할 수 없다.
   */
  axis?: ScenarioAxis;
  /** 목 렌더·scenario 모드에서 그릴 원래 화면. */
  children?: ReactNode;
};

function senderLines(spec: ReturnType<typeof pendingSource>) {
  return spec.from.map((sender) => `${t('part.' + sender.part)} ${sender.id} ${t('req.' + sender.id)}`);
}

/** 좁은 자리에서 툴팁으로 쓰는 한 덩어리 문구. 네 가지가 다 들어간다. */
function summaryText(spec: ReturnType<typeof pendingSource>): string {
  const from = spec.from.length === 0
    ? t('pending.summary.fromNone', { reason: spec.missing ?? t('pending.agenda') })
    : t('pending.summary.from', { value: senderLines(spec).join(' → ') });
  return [
    t(`pending.${spec.id}.title`),
    t('pending.summary.what', { value: t(`pending.${spec.id}.what`) }),
    from,
    t('pending.summary.ours', { value: spec.ours.join(' · ') }),
    // 시범 키 ④ 열거형 라벨 (영문화 1단계 §4). `PLANE_LABEL` 은 모듈 최상위 상수라
    // 거기서 `t()` 를 부르면 로드 시점에 굳는다 — **읽는 자리에서 부른다.**
    t('pending.summary.path', { label: t('plane.' + spec.plane), note: t(`plane.${spec.plane}.note`) }),
  ].join('\n');
}

export function PendingSource({ id, minHeight, fill, inline, entity, axis, children }: Props) {
  const spec = pendingSource(id);
  // 언어가 바뀌면 다시 그린다 — `t()` 는 값을 줄 뿐 리렌더를 일으키지 않는다 (§4).
  useLang();
  const mock = useMockRender();
  const scenarioCast = useScenarioCast();
  const axisCovered = useScenarioAxis(axis);

  if (mock) {
    return (
      <div className={inline ? 'mockwrap mockwrap--inline' : 'mockwrap'} data-pending={id}>
        {/* 지워지지 않는다. 목 렌더 중이라는 사실이 화면에서 사라지면 안 된다. */}
        <span className="mockwrap__badge" title={summaryText(spec)}>{t('pending.badge.mock')}</span>
        {children}
      </div>
    );
  }

  // 시나리오 모드 · 이 축을 대본이 몰지 않는다 — **「연결 예정」이 아니다** (요구 2의 넷째 상태).
  // 못 받은 것이 아니라 이 대본의 이야기에 없는 것이고, 어느 편에서 보이는지까지 적는다.
  if (axisCovered === false && axis !== undefined) {
    const elsewhere = scriptsWithAxis(axis);
    if (inline) {
      return (
        <span className="notinscript notinscript--inline" data-pending={id} title={summaryText(spec)}>
          <b>{t('pending.notInScript')}</b> <em>{AXIS_LABEL[axis]}</em>
        </span>
      );
    }
    return (
      <section className="notinscript" data-pending={id} style={minHeight === undefined ? undefined : { minHeight }}>
        <header>
          <span className="notinscript__mark">{t('pending.notInScript')}</span>
          <h3>{AXIS_LABEL[axis]} · {t(`pending.${spec.id}.title`)}</h3>
        </header>
        <p>
          {elsewhere.length === 0
            ? <>{t('pending.noScriptDrives', { parts: spec.from.map((sender) => t('part.' + sender.part)).join('·') || t('pending.partsUndecided') })}</>
            : <>{t('pending.seenIn', { scripts: elsewhere.map((script) => script.missionId).join(' · ') })}</>}
        </p>
        <p className="notinscript__why">{t('pending.sizeKept')}</p>
      </section>
    );
  }

  // scenario 모드 — 대본 등장 장비에 한해 합성값을 그린다. 배지는 지워지지 않는다.
  // A/B 분류는 바뀌지 않는다 — 이 자리는 여전히 남이 줄 데이터이고, 지금 값은 대본의 합성본이다.
  if (scenarioCast !== null && entity !== undefined && scenarioCast.has(entity)) {
    return (
      <div className={inline ? 'scenariowrap scenariowrap--inline' : 'scenariowrap'} data-pending={id}>
        <span className="scenariowrap__badge" title={summaryText(spec)}>{t('pending.badge.script')}</span>
        {children}
      </div>
    );
  }

  const noCounterpart = spec.from.length === 0;

  if (inline) {
    return (
      <span className="pending pending--inline" data-pending={id} title={summaryText(spec)}>
        <b>{t(`pending.${spec.id}.title`)}</b>
        <em>{spec.ours.join(' · ')}</em>
        {noCounterpart && <strong className="pending__missing">{t('pending.noCounterpart')}</strong>}
      </span>
    );
  }

  return (
    <section
      className={fill ? 'pending pending--fill' : 'pending'}
      data-pending={id}
      style={minHeight === undefined ? undefined : { minHeight }}
    >
      <header className="pending__head">
        <span className="pending__mark">{t('pending.mark')}</span>
        <h3 className="pending__title">{t(`pending.${spec.id}.title`)}</h3>
      </header>

      <dl className="pending__rows">
        <dt>{t('pending.what')}</dt>
        <dd>{t(`pending.${spec.id}.what`)}</dd>

        <dt>{t('pending.from')}</dt>
        <dd>
          {noCounterpart ? (
            <>
              <strong className="pending__missing">{t('pending.noCounterpart')}</strong>
              <span className="pending__why">{spec.missing}</span>
            </>
          ) : (
            <ol className="pending__from">
              {spec.from.map((sender) => (
                <li key={sender.id}>
                  <span className={`pending__part pending__part--${sender.part}`}>{t('part.' + sender.part)}</span>
                  <code>{sender.id}</code> {t('req.' + sender.id)}
                </li>
              ))}
            </ol>
          )}
        </dd>

        <dt>{t('pending.ours')}</dt>
        <dd>
          {spec.ours.map((our) => <code key={our}>{our}</code>)}
          <span className="pending__why">{t('pending.oursWhy')}</span>
        </dd>

        <dt>{t('pending.path')}</dt>
        <dd>
          {/* 시범 키 ④ — 읽는 자리에서 부른다 (위 `summaryText` 주석과 같은 이유). */}
          <b>{t('plane.' + spec.plane)}</b>
          <span className="pending__why">{t(`plane.${spec.plane}.note`)}</span>
        </dd>
      </dl>
    </section>
  );
}
