/**
 * src/shell/LangSwitch.tsx (260916 신설 — 영문화 1단계 §3)
 *
 * 우상단 **언어 전환** — `언어 [한국어] [English]`. `ModeSwitch.tsx` 를 본뜬 세그먼트이고
 * **새 디자인을 만들지 않는다** — 클래스도 `modeswitch__*` 를 그대로 쓴다.
 *
 * ## 라벨은 각 언어를 그 언어로 적는다
 *
 * `한국어` · `English` — **번역하지 않는다.** 영문 화면에서 `Korean` 이라고 적으면 한국어를
 * 찾는 사람이 못 찾는다. 그래서 이 파일은 시범 키 다섯 중 아무것도 안 쓴다.
 *
 * ## 주소창을 복사하면 그 언어가 따라간다
 *
 * 전환할 때 `?lang=` 을 **`replaceState`** 로 갱신한다. `pushState` 가 아니다 — 뒤로가기가
 * 언어 전환 이력으로 채워지면 안 된다.
 *
 * `<html lang>` 은 여기서 안 건드린다. 저장소(`shared/language.ts`)가 기동 때와 전환 때
 * 모두 심는다 — 두 곳에서 쓰면 갈라진다.
 *
 * ## 라우터를 넣지 않는다
 *
 * `/ko`·`/en` 경로 분리는 하지 않는다. 의존성은 넷(`react`·`mqtt`·`protobufjs`·`ws`)이고,
 * 라우터 하나 넣자고 그 선을 넘을 일이 아니다. 무엇보다 **`standalone.html` 전달본에서는
 * 경로 분리가 아예 동작하지 않는다** — 서버가 없어 `/en` 을 되돌려 줄 것이 없다.
 *
 * ## 셸 전용 의존이 없다
 *
 * `shared/language.ts` 와 `i18n/dict.ts` 둘만 본다. `ModeSwitch` 가 `scenarios/`·`commandEgress`
 * 를 끌어오는 것과 다르다 — 260916 단독 빌드 정합에서 셸이 단독 전달본에도 들어갔으므로
 * 이 부품은 양쪽에 그대로 실린다(`verify:build-parity`). 사전은 `AppShell` 이 이미 끌어오므로
 * 이 import 로 단독 빌드가 무거워지지 않는다.
 *
 * 260918 에 사전을 하나 들였다 — 세그먼트의 **보조 이름 둘**(`언어` 와 화면 낭독용 이름)이
 * 영문 화면에서 한국어로 남아 있었다. **버튼 이름 「한국어」·「English」는 여전히 사전 밖이다**
 * (위 「라벨은 각 언어를 그 언어로 적는다」).
 */

import { t } from '../i18n/dict.ts';
import { LANGS, setLang, useLang, type Lang } from '../shared/language.ts';

/** 각 언어를 **그 언어로** 적은 이름. 사전을 타지 않는다. */
const ENDONYM: Record<Lang, string> = {
  ko: '한국어',
  en: 'English',
};

export function LangSwitch() {
  const lang = useLang();

  const choose = (next: Lang) => {
    setLang(next);
    // 주소창의 `?lang=` 을 같이 갱신한다 — **복사해 건네면 그 언어로 열려야 한다.**
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('lang', next);
      window.history.replaceState(null, '', url);
    } catch {
      // `file://` 로 연 전달본 등에서 막힐 수 있다. 전환 자체는 이미 끝났으므로 조용히 넘어간다.
    }
  };

  return (
    <div className="modeswitch" role="group" aria-label={t('lang.aria')}>
      {/* 「한국어」·「English」는 각 언어를 그 언어로 적으므로 사전을 안 탄다 (위 주석).
          앞의 이 이름은 그 둘이 무엇인지 말하는 말이라 화면 언어를 따라간다. */}
      <span className="modeswitch__label">{t('lang.label')}</span>
      {LANGS.map((code) => (
        <button
          key={code}
          type="button"
          className={'modeswitch__seg' + (lang === code ? ' modeswitch__seg--on' : '')}
          aria-pressed={lang === code}
          lang={code}
          onClick={() => choose(code)}
        >
          {ENDONYM[code]}
        </button>
      ))}
    </div>
  );
}
