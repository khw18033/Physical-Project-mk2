// 이식: web-dashboard/src/views/InsightView.tsx @ 700ed91 — 해체해서 탭②로
//
// 구 「판단·알림」 탭은 화면 하나로 남기지 않고 **해체했다.**
//   위험도 판단 근거 (VZ-I-08)  → 여기. 탭② 구역 현황판 위쪽
//   표시 깊이 3단 (VZ-U-03)     → 여기. 같은 구독을 유지한 채 깊이만 바꾼다
//   AI 실패 이벤트 (VZ-I-10)    → 상단 공통 알림. tabs/aiFailureBridge.ts 가 잇는다
//   자체 관측 (VZ-O-04)         → 공유 계층. startDataLayer() 가 기동한다
//
// 탭 하나를 통째로 옮기지 않은 이유: 위험도는 "그 구역이 지금 어떤가"이고, 그 질문에
// 답하는 화면은 이미 탭②다. 같은 질문에 답하는 화면이 둘이면 사용자가 어느 쪽을 봐야
// 하는지 알 수 없게 된다 — 탭⑥에서 임무 관제 모드를 지운 것과 같은 이유다.

import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import { useState } from 'react';
import { GATEWAY, type RiskState } from '../../transport/index.ts';
import { deriveDisplayStatus, DISPLAY_STATUS_LABEL, store } from '../data/index.ts';
import { useEntities } from '../data/hooks.ts';
import { PendingSource } from '../../shared/PendingSource.tsx';
import { CURRENT_ZONE_ID } from '../../shared/registry.ts';
import { Explain } from '../../shared/Explain.tsx';

type Level = 'decision' | 'operation' | 'development';

const LEVELS: Array<{ id: Level; label: string; note: string }> = [
  { id: 'decision', label: t('rp.1'), note: t('rp.2') },
  { id: 'operation', label: t('rp.3'), note: t('rp.4') },
  { id: 'development', label: t('rp.5'), note: t('rp.6') },
];

const RISK_LABEL: Record<RiskState['level'], string> = { normal: t('rp.7'), watch: t('rp.8'), alert: t('rp.9'), recovery: t('rp.10') };

export function RiskPanel() {
  const entities = useEntities();
  const [level, setLevel] = useState<Level>('decision');
  const riskSlot = [...entities.values()].map((r) => r.riskState).find(Boolean) ?? null;
  const risk = riskSlot?.payload as RiskState | undefined;
  const records = [...entities.values()].filter((r) => r.registry?.zone === CURRENT_ZONE_ID);

  const trigger = (name: string) => void fetch(GATEWAY.http + '/insight/' + name, { method: 'POST' });

  return (
    <section className="board insight insight--embedded">
      <header className="board__head">
        <div>
          <h2 className="board__title">{t('rp.11')}</h2>
          <Explain id="risk-1" className="board__sub"><Rich id="rp.sub" /></Explain>
        </div>
        <div className="levelbar">
          {LEVELS.map((v) => (
            <button key={v.id} type="button" className={'btn' + (level === v.id ? ' btn--on' : '')} onClick={() => setLevel(v.id)}>
              {v.label}<em>{v.note}</em>
            </button>
          ))}
        </div>
      </header>

      {/* 위험도는 어느 대본도 몰지 않는다 — AI 파트(VZ-I-08)의 몫. 시나리오 모드에서는
          「연결 예정」이 아니라 「이 대본에는 해당 없음」으로 갈린다 (260831 요구 2). */}
      <PendingSource id="risk-state" minHeight={132} axis="risk">
        {risk ? (
          <div className={'riskcard riskcard--' + risk.level}>
            <div><span className="riskcard__label">{RISK_LABEL[risk.level]}</span><strong>{risk.score}</strong><small>/ 100</small></div>
            <p>{risk.recommendation}</p>
            {level !== 'decision' && <ul>{risk.reasons.map((r) => <li key={r.label}><b>{r.label}</b> {r.value} <span>{t('rp.contribution', { pct: Math.round(r.contribution * 100) })}</span></li>)}</ul>}
            {level === 'development' && <pre>{JSON.stringify(riskSlot, null, 2)}</pre>}
          </div>
        ) : (
          <p className="notice">{t('rp.12')}</p>
        )}
      </PendingSource>

      {level !== 'decision' && (
        <PendingSource id="device-cards" minHeight={96}>
        <div className="layergrid">
          {records.map((r) => {
            const status = deriveDisplayStatus(r.state?.payload ?? null);
            return (
              <article className="layercard" key={r.id}>
                <b>{r.registry?.display_name ?? r.id}</b>
                <span className={'badge badge--' + status}>{DISPLAY_STATUS_LABEL[status]}</span>
                {level === 'development' && <pre>{JSON.stringify({ state: r.state, telemetry: r.telemetry }, null, 2)}</pre>}
              </article>
            );
          })}
        </div>
        </PendingSource>
      )}

      <div className="devpanel">
        <h3 className="devpanel__title">{t('rp.replayTransitions')} <small>{t('rp.mockGateway')}</small></h3>
        <div className="devpanel__row">
          {(['normal', 'watch', 'alert', 'recovery'] as const).map((v) => (
            <button className="btn" type="button" key={v} onClick={() => trigger('risk-' + v)}>{t('rp.riskOf', { level: RISK_LABEL[v] })}</button>
          ))}
          <button className="btn" type="button" onClick={() => trigger('ai-failure')}>{t('rp.13')}</button>
        </div>
        <Explain id="risk-2" className="note note--dim">
          <Rich id="rp.note1" vars={{ n: store.getSnapshot().size }} />
          <Rich id="rp.note2" />
        </Explain>
      </div>
    </section>
  );
}
