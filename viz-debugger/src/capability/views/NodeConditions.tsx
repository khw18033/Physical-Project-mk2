/**
 * src/capability/views/NodeConditions.tsx (260921 신설 — What-if · 계층별 노드)
 *
 * **조건을 거는 자리.** 전달본의 노드 카드(태그 핀 · 예산 · provider 제외)를 계층 섹션
 * 안으로 옮긴 것이다. 여기서 체크 하나를 누르면 `POST /api/functions/whatif` 가 한 번 돈다.
 *
 * ## 목록은 **기준선**에서 뽑는다
 *
 * `after` 에서 뽑으면 방금 제외한 provider 가 목록에서 사라져 **되돌릴 수가 없다** —
 * 서버가 제외된 provider 를 레지스트리에서 통째로 빼고 계산하기 때문이다
 * (`_registry_without`). 그래서 이 부품이 받는 `baseline` 은 언제나 조건이 안 걸린 한 벌이다.
 *
 * ## 전체(`'*'`)는 provider 제외만 연다
 *
 * 태그와 예산은 **노드마다 다른 값**이다(pi6 의 `sensor.camera.imx708`, edge-gpu 의 30 CU).
 * 전체에 태그를 걸면 모든 노드의 센서 태그가 한 벌로 덮여 「고정 카메라가 갑자기 Go1
 * 카메라를 가진」 판이 된다 — 가정해 보려던 것과 다른 것이 나온다. provider 제외는
 * 노드와 무관한 값이라 전체로 걸어도 그 사고가 없고, 전달본의 확인 순서 3번이 바로 그것이다.
 *
 * ## 계산 중에도 잠그지 않는다 (260921)
 *
 * 체크를 누르면 `overrides` 가 **즉시** 바뀌므로 눌린 자리는 바로 켜진다. 서버 왕복만
 * 뒤로 묶인다(`WHATIF_DEBOUNCE_MS`). 계산 중이라고 칸을 잠그면 연달아 누르는 일이 애초에
 * 안 되고, 그러면 묶을 것도 없다 — 늦게 온 답은 저장소가 버린다(`whatifSerial`).
 */

import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import {
  budgetPatch, effectiveOverride, excludePatch, isNodeBaseline, providerUniverse, tagUniverse,
  tagsPatch, toggled,
} from '../options.ts';
import { setCapabilityOverride, useCapability } from '../store.ts';
import { OVERRIDE_ALL, type CapNode, type CapSnapshot } from '../types.ts';

/** 숫자 칸 하나를 읽는다. 비었거나 숫자가 아니면 `null` — 0 으로 읽으면 없는 한도가 생긴다. */
function numberOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

export function NodeConditions({ node, baseline }: { node: CapNode; baseline: CapSnapshot }) {
  useLang();
  const cap = useCapability();
  const eff = effectiveOverride(cap.overrides, node);
  const tags = tagUniverse(baseline);
  const providers = providerUniverse(baseline);
  const fromAll = cap.overrides[OVERRIDE_ALL]?.excludeProviders ?? null;

  return <div className="cap-cond">
    <div className="cap-cond__col">
      <h4>{t('cap.cond.tags')}</h4>
      <div className="cap-pins">
        {tags.map((tag) => {
          const on = eff.tags.includes(tag);
          return <label key={tag} className={`cap-pin${on ? ' is-on' : ''}`}>
            <input
              type="checkbox"
              checked={on}
              onChange={(event) => void setCapabilityOverride(
                node.nodeId, tagsPatch(node, toggled(eff.tags, tag, event.target.checked)),
              )}
            />
            {tag}
          </label>;
        })}
      </div>
      <p className="cap-note cap-note--flush">{t('cap.cond.tagsNote')}</p>
    </div>

    <div className="cap-cond__col">
      <h4>{t('cap.cond.budget')}</h4>
      <div className="cap-fields">
        {/* **커밋은 포커스가 빠질 때다.** 글자마다 보내면 「3」 을 치는 동안 30 → 3 → 30 으로
            세 번 계산이 돈다. `key` 가 확정값이라, 값이 실제로 바뀌면 칸이 다시 선다. */}
        <label>
          {t('cap.cond.computeUnits')}
          <input
            key={`cu:${eff.budget.computeUnits ?? ''}`}
            type="number" step="0.5" min="0" inputMode="decimal"
            defaultValue={eff.budget.computeUnits ?? ''}
            onBlur={(event) => void setCapabilityOverride(node.nodeId, budgetPatch(node, {
              computeUnits: numberOrNull(event.target.value), memoryMb: eff.budget.memoryMb,
            }))}
          />
        </label>
        <label>
          {t('cap.cond.memoryMb')}
          <input
            key={`mb:${eff.budget.memoryMb ?? ''}`}
            type="number" step="64" min="0" inputMode="numeric"
            defaultValue={eff.budget.memoryMb ?? ''}
            onBlur={(event) => void setCapabilityOverride(node.nodeId, budgetPatch(node, {
              computeUnits: eff.budget.computeUnits, memoryMb: numberOrNull(event.target.value),
            }))}
          />
        </label>
      </div>

      <h4>{t('cap.cond.exclude')}</h4>
      <div className="cap-checks">
        {providers.map((providerId) => {
          const on = eff.excludeProviders.includes(providerId);
          return <label key={providerId}>
            <input
              type="checkbox"
              checked={on}
              onChange={(event) => void setCapabilityOverride(
                node.nodeId, excludePatch(node, toggled(eff.excludeProviders, providerId, event.target.checked)),
              )}
            />
            <code>{providerId}</code>
            {/* 전체에서 온 제외인지 적는다 — 여기서 끄면 **이 노드만** 풀린다. */}
            {fromAll !== null && fromAll.includes(providerId)
              && <em className="cap-chip cap-chip--whatif">{t('cap.cond.fromAll')}</em>}
          </label>;
        })}
      </div>
    </div>
  </div>;
}

/** 전체 노드의 기본값. **provider 제외만** — 위 주석의 이유다. */
export function GlobalConditions({ baseline }: { baseline: CapSnapshot }) {
  useLang();
  const cap = useCapability();
  const excluded = cap.overrides[OVERRIDE_ALL]?.excludeProviders ?? [];
  const providers = providerUniverse(baseline);

  return <div className="cap-cond cap-cond--global">
    <div className="cap-cond__col">
      <h4>{t('cap.cond.globalTitle')}</h4>
      <p className="cap-note cap-note--flush">{t('cap.cond.globalNote')}</p>
    </div>
    <div className="cap-cond__col">
      <h4>{t('cap.cond.exclude')}</h4>
      <div className="cap-checks">
        {providers.map((providerId) => {
          const on = excluded.includes(providerId);
          return <label key={providerId}>
            <input
              type="checkbox"
              checked={on}
              onChange={(event) => {
                const next = toggled(excluded, providerId, event.target.checked);
                // 빈 목록은 **없던 일**이다 — `null` 로 돌려놔야 조건 수가 실제와 맞는다.
                void setCapabilityOverride(OVERRIDE_ALL, { excludeProviders: next.length > 0 ? next : null });
              }}
            />
            <code>{providerId}</code>
          </label>;
        })}
      </div>
    </div>
  </div>;
}

/** 이 노드에 조건이 걸려 있는가 — 줄에 표시를 달지 결정한다. */
export function nodeChanged(overrides: Parameters<typeof isNodeBaseline>[0], node: CapNode): boolean {
  return !isNodeBaseline(overrides, node);
}
