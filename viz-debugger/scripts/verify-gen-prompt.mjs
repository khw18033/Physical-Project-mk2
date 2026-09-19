// verify:gen-prompt (260919 신설 — 영문화 5단계 L3)
//
// **영어 프롬프트가 한국어 판 옆에 나란히 서 있고, 한국어 판은 한 글자도 안 달라졌다.**
//
// 6~10단계의 베이스라인 숫자(`score:generation`)는 그 한국어 프롬프트로 나온 것이다.
// 문장이 한 자라도 바뀌면 앞으로 잴 숫자를 그 표에 못 놓는다 — 그때는 다시 재는 수밖에
// 없고, 모델을 다시 돌리는 일이다. 그래서 「안 바꿨다」가 주장이 아니라 **대조**여야 한다.
//
// 보는 것 넷.
//  1. **한국어 프롬프트가 떠 둔 것과 글자까지 같다** (`gen-lab/goldset/prompt-ko.golden.json`)
//  2. **영어 판에 한글이 없다** — 규칙·절 이름·장소·장비 목록 전부
//  3. **두 판의 규칙이 1:1** — 문장 수와 차례가 같아야 「언어만 다르다」가 참이 된다
//  4. **한국어 판은 영어가 섞여도 된다** — `assigned_targets` 같은 계약 이름은 그대로다
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');           // 저장소 뿌리 (gen-lab 은 viz-debugger 밖이다)
const genLab = join(root, 'gen-lab');

const failures = [];
const controls = [];

/**
 * 파이썬을 실제로 부른다 — 문자열 검사로는 「프롬프트가 실제로 어떻게 나오는가」를 못 본다.
 *
 * **바이트코드 캐시를 안 남긴다.** 260919 에 낡은 `__pycache__` 때문에 이 검사가 **고친
 * 뒤의 소스가 아니라 옛 컴파일본**을 재고 있었다 — 되돌림 시험에서 복원했는데도 계속
 * 빨갰다. 캐시 무효화는 (수정시각, 크기)로 하는데 글자 수가 같으면 스치듯 지나간다.
 */
function python(code) {
  const run = spawnSync('python', ['-B', '-c', code], {
    cwd: root, encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' },
  });
  if (run.error !== undefined || run.status === null) {
    return { ok: false, out: `파이썬을 못 돌렸다 — ${run.error?.message ?? '종료 코드가 없다'}` };
  }
  if (run.status !== 0) return { ok: false, out: `${run.stdout ?? ''}${run.stderr ?? ''}`.trim() };
  return { ok: true, out: (run.stdout ?? '').trim() };
}

// ── 1. 한국어 프롬프트가 떠 둔 것과 글자까지 같다 ───────────────────────────
{
  if (!existsSync(join(genLab, 'goldset', 'prompt-ko.golden.json'))) {
    failures.push('떠 둔 한국어 프롬프트가 없다 — `python gen-lab/goldset/prompt_golden.py --write`');
  } else {
    const run = spawnSync('python', ['-B', join(genLab, 'goldset', 'prompt_golden.py')], {
      cwd: root, encoding: 'utf8',
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' },
    });
    if (run.status !== 0) {
      failures.push(`${(run.stdout ?? '').trim()}${(run.stderr ?? '').trim()}`.slice(0, 400));
    } else {
      console.log('✅ 한국어 프롬프트가 떠 둔 것과 **글자까지 같다** — 베이스라인 숫자가 그대로 유효하다');
    }
  }
}

// ── 2·3·4 — 영어 판을 실제로 만들어 본다 ────────────────────────────────────
{
  const code = [
    'import sys, json, pathlib',
    'sys.path.insert(0, "gen-lab")',
    'from server import prompt',
    'places = json.loads(pathlib.Path("places/places.json").read_text(encoding="utf-8"))',
    'eq = json.loads(pathlib.Path("equipment/equipment.json").read_text(encoding="utf-8"))',
    'out = {}',
    'for name, flags in [("base", {}), ("all", {"equipment": True, "node_kinds": True, "tasks": True, "branch": True})]:',
    '    for lang in ("ko", "en"):',
    '        out[name + ":" + lang] = prompt.build(',
    '            utterance="go", mission_id="M", places=places,',
    '            equipment=eq if flags.get("equipment") else None,',
    '            node_kinds=flags.get("node_kinds", False), tasks=flags.get("tasks", False),',
    '            branch=flags.get("branch", False), lang=lang)',
    'out["rules:ko"] = prompt.rules_for(eq, True, True, True, "ko")',
    'out["rules:en"] = prompt.rules_for(eq, True, True, True, "en")',
    'print(json.dumps(out, ensure_ascii=False))',
  ].join('\n');

  const got = python(code);
  if (!got.ok) {
    failures.push(`영어 프롬프트를 못 만들었다 — ${got.out.slice(0, 300)}`);
  } else {
    const built = JSON.parse(got.out);

    // 2 — 영어 판에 한글이 없다.
    for (const name of ['base:en', 'all:en']) {
      const text = `${built[name].system}\n${built[name].user}`;
      const lines = text.split('\n').filter((l) => /[가-힣]/.test(l));
      for (const line of lines.slice(0, 5)) failures.push(`${name}: 한글이 남았다 — 「${line.trim().slice(0, 80)}」`);
      if (lines.length > 5) failures.push(`${name}: 그 밖 ${lines.length - 5}줄`);
    }
    console.log('✅ 영어 판에 한글 0줄 — 규칙 · 절 이름 · 장소 · 장비 목록 전부');

    // 3 — 두 판의 규칙이 1:1.
    const ko = built['rules:ko'];
    const en = built['rules:en'];
    if (ko.length !== en.length) {
      failures.push(`규칙 수가 다르다 — ko ${ko.length} · en ${en.length}. 「언어만 다르다」가 깨진다`);
    } else {
      console.log(`✅ 규칙이 1:1 — 두 판 모두 ${ko.length}줄 (모든 판을 켠 상태)`);
    }
    // 한국어 규칙에 한글이 있고 영어 규칙에는 없다 — 자리가 안 섞였다는 뜻이다.
    if (!ko.every((r) => /[가-힣]/.test(r))) failures.push('한국어 규칙에 한글이 없는 줄이 있다 — 영어가 섞였나');
    if (en.some((r) => /[가-힣]/.test(r))) failures.push('영어 규칙에 한글이 섞였다');

    // 4 — 한국어 판은 그대로 한국어다 (골든과 별개로 한 번 더).
    if (!/[가-힣]/.test(built['base:ko'].system)) failures.push('한국어 판의 system 에 한글이 없다');
    controls.push('한국어 판은 한국어, 영어 판은 영어로 갈린다');
  }
}

// ── 5. 대조군 ───────────────────────────────────────────────────────────────
{
  // 모르는 언어는 **한국어로 떨어진다** — 화면 사전과 같은 규칙이다.
  const got = python([
    'import sys, json',
    'sys.path.insert(0, "gen-lab")',
    'from server import prompt',
    'print(json.dumps({"zz": prompt.build(utterance="x", mission_id="M", lang="zz")["system"],',
    '                  "ko": prompt.build(utterance="x", mission_id="M")["system"]}, ensure_ascii=False))',
  ].join('\n'));
  if (!got.ok) failures.push(`대조군을 못 돌렸다 — ${got.out.slice(0, 200)}`);
  else {
    const out = JSON.parse(got.out);
    if (out.zz !== out.ko) failures.push('모르는 언어가 한국어로 안 떨어진다 — 빈 프롬프트로 모델을 돌리게 된다');
    else controls.push('모르는 언어는 한국어로 떨어진다');
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:gen-prompt\n- ${failures.join('\n- ')}`);
  console.error('\n   한국어 프롬프트를 **일부러** 바꿨다면 베이스라인을 다시 재야 한다 —');
  console.error('   그 결정을 하고 나서 `python gen-lab/goldset/prompt_golden.py --write` 로 다시 떠라.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
