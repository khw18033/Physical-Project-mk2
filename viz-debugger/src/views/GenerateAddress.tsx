/**
 * src/views/GenerateAddress.tsx (261123 신설)
 *
 * **생성 서비스(gen-lab) 주소 칸.** 발화 판의 생성 칸 바로 위에 선다.
 *
 * 연결 관리에도 같은 칸(`generate.base`)이 있지만, GPU 가 작은 노트북에서는 생성이 10분을 넘겨 쓸 수 없어서
 * (261123 실측 — MX450 2 GB) **GPU 가 큰 PC 의 gen-lab 으로 바꾸는 일이 잦다.** 그래서 쓰는 자리 옆에 둔다.
 * 값은 연결 관리와 **같은 칸**에 저장한다 — 두 곳이 따로 들면 화면마다 다른 서비스를 부른다.
 *
 * 큰 PC 쪽에서는 gen-lab 을 `GEN_LAB_HOST=<그 PC 의 Tailscale 주소>` 로 띄워야 닿는다(`gen-lab/README.md`).
 */

import { useEffect, useState } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { connectionAddress, connectionKey, connectionOverrides, saveConnections, useConnections } from '../shared/connections.ts';

/** 고르기 쉬운 주소 둘. 이름표는 사전 키다. */
const PRESETS: readonly { labelKey: string; url: string }[] = [
  { labelKey: 'gen.address.local', url: 'http://127.0.0.1:8802' },
  { labelKey: 'gen.address.gpuPc', url: 'http://100.125.71.51:8802' },
];

const KEY = connectionKey('generate', 'base');

/** http(s) 주소만 받는다. 끝의 `/` 는 뗀다. 못 읽으면 null. */
function normalize(value: string): string | null {
  const trimmed = value.trim().replace(/\/+$/, '');
  try {
    const url = new URL(trimmed);
    return url.protocol === 'http:' || url.protocol === 'https:' ? trimmed : null;
  } catch {
    return null;
  }
}

/** 생성 칸만 바꾼다 — 다른 연결 칸은 그대로 둔다(`saveConnections` 는 바꾼 칸 전체를 갈아 끼운다). */
function applyAddress(url: string): void {
  saveConnections({ ...connectionOverrides(), [KEY]: url });
}

export function GenerateAddress({ disabled }: { disabled: boolean }) {
  useLang();
  useConnections();
  const current = connectionAddress('generate', 'base');
  const [draft, setDraft] = useState(current);
  // 연결 관리에서 바꿔도 칸이 따라온다.
  useEffect(() => { setDraft(current); }, [current]);
  const normalized = normalize(draft);
  return <p className="gen-address">
    <label htmlFor="gen-address-input">{t('gen.address')}</label>
    <input id="gen-address-input" type="text" inputMode="url" spellCheck={false} autoComplete="off"
      aria-invalid={normalized === null} value={draft} disabled={disabled}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => { if (event.key === 'Enter' && normalized !== null) applyAddress(normalized); }} />
    <button type="button" disabled={disabled || normalized === null || normalized === current} onClick={() => { if (normalized !== null) applyAddress(normalized); }}>
      {t('gen.address.apply')}
    </button>
    {PRESETS.map((preset) => (
      <button key={preset.url} type="button" disabled={disabled || preset.url === current} onClick={() => applyAddress(preset.url)}>
        {t(preset.labelKey)}
      </button>
    ))}
    {normalized === null && <small className="gen-address__bad">{t('gen.address.invalid')}</small>}
  </p>;
}
