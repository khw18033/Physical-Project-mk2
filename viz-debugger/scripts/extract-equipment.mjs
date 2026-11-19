/**
 * scripts/extract-equipment.mjs — 마일스톤 분리 7단계 (6단계 §5 「다음에 할 것」 1번)
 *
 * **장소에 들은 처방을 장비에 그대로 준다.**
 *
 * 260906 실측에서 장소 어휘 위반은 세 모델 모두 0건이고 장비 어휘 위반은 22~48% 였다.
 * 같은 모델·같은 프롬프트·같은 디코딩·같은 응답 안에서 갈린 것이 하나뿐이다 —
 * **장소는 목록을 줬고 장비는 안 줬다.** 그래서 장비에도 목록을 준다.
 *
 *   places/places.json      ← Unity 씬에서 뽑아 둔 것 (뽑던 extract-places.mjs 는 261021 Unity_Map 과 함께 지웠다)
 *   equipment/equipment.json ← 이 스크립트          (레지스트리 + 정답셋)
 *
 * ## 원천이 둘인 이유 — 정답셋만 쓰면 축이 자기 자신을 채점한다
 *
 * 채점기(`score-generation.mjs` 축 2d)의 어휘는 **정답셋 4편의 `assigned_targets`
 * 합집합 8건**이다. 그것만 프롬프트에 실으면 「목록에서 고를 줄 아는가」가 아니라
 * 「준 8개를 옮겨 적는가」를 재게 된다 — **오답 선택지가 없는 시험**이다.
 *
 * 그래서 목 게이트웨이 레지스트리의 장비를 합집합으로 넣는다. 레지스트리에만 있는
 * 장비(`robot-02`·`sensor-04` …)가 곧 오답 선택지다. 프롬프트 목록이 채점 어휘보다
 * **넓어야** 이 축이 살아 있고, 같아지는 순간 죽는다 — `verify:no-leak` 이 검사한다.
 *
 * ## 레지스트리를 복사하지 않는다
 *
 * `gateway/hub.ts` 와 `stt/vocab.py` 가 같은 파일을 읽는다. 복사본을 두면 화면의 장치
 * 목록·음성 인식 어휘·생성 어휘가 조용히 갈라진다. 경로는 `VIZ_REGISTRY_DIR` 로 바꾼다.
 *
 * ## 이름을 지어내지 않는다
 *
 * 지금 정답셋 3편의 장비는 전부 레지스트리에 있어서 이 자리가 비어 있다. 그런데 `e2c3f0f`
 * 가 들어낸 415 편이 4층을 재고 돌아오면 `go1-02`·`arm-03`·`cam-4f`·`cam-5f` 가 함께
 * 돌아오고, 그 넷은 레지스트리에 없다. 옛 대본의 `hardware[]` 에 이름이 있지만 그 값은
 * **기종**이다(「Unitree Go1」) — 프롬프트 규칙 4가 금지하는 바로 그것이라 실으면 모델에게
 * 금지어를 쥐여 주는 꼴이다.
 *
 * 그래서 그때도 **식별자만 싣고 label·kind 는 null 로 둔다.** 없는 것은 없는 대로 둔다 —
 * `places.json` 의 자리표시와 같은 원칙이고, 그 자리는 지금 비어 있어도 열어 둔다.
 *
 * ## 동작 어휘 — 생성기가 액션 아이템에 쓸 이름 (261023 · 생성기 3단계)
 *
 * 장비마다 **임무가 낼 수 있는 명령 이름**을 `actions` 표로 싣는다. 7단계에 장비 목록을
 * 주자 지어낸 장비가 20건 → 0건이 됐다 — 같은 처방을 동작에 준다.
 *
 * **9월 판단과 어긋나지 않는다.** 그때 「장비 종류를 우리가 목록으로 정하지 않는다, 장비가
 * 밝힌다」고 한 것은 **발행 시점**의 이야기다. 여기 싣는 것은 **생성 어휘**다 — 생성기는 이
 * 목록을 보고 쓰고, 발행은 장비가 밝힌 `Capability` 로 다시 확인해 모르는 명령을 거부한다
 * (그 거부 경로는 이미 있다). 이 표가 틀려도 장비에 엉뚱한 명령이 나가지 않는다.
 *
 * 원천은 둘이고 **둘 다 우리가 이미 내고 있는 이름**이다. 새로 짓지 않는다.
 *   - 수문 — `gateway/commands.ts` 의 `ACTION_CATALOG` 를 그대로 읽는다(장비 id 별)
 *   - 로봇 — `src/physical/encode.ts` 의 `PhysicalAction` 중 **임무가 로봇을 움직이는 넷**.
 *     정지 이름은 `presets.ts` 의 `STOP_ACTION` 에서 끌어온다. 빼는 것은 정비 명령
 *     (`ping`·`diag`·`sdk_*`)과 화면 쪽 신호(`scan_continue`) · 장비가 선언해야만 쓰는 것
 *     (`teleop`·`move_relative`·드론 SAR) — 임무 생성이 고를 명령이 아니거나, 장비가
 *     밝혔는지 생성 시점에 모른다
 *   - 센서·카메라·엣지 노드 — **싣지 않는다.** 켜 두면 값이 오는 서비스라 지정할 행동이 없다
 *
 * 장비 계약(`equipment.schema.json`)은 항목에 `additionalProperties: false` 라 항목 안에
 * 넣지 않고 파일 최상위에 id → 이름 표로 둔다. **계약은 안 바꾼다.**
 */
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { loadContracts, validate } from './lib/json-schema.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const registryDir = process.env.VIZ_REGISTRY_DIR ?? join(repoRoot, 'web-dashboard', 'mock-gateway');
const registryRel = 'web-dashboard/mock-gateway/registry.json';
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');
const outDir = join(repoRoot, 'equipment');

// ── 원천 1: 목 게이트웨이 레지스트리 ─────────────────────────────────────────
//
// `entities[]` 를 통째로 옮긴다. **손으로 고르지 않는다** — 「이건 임무 대상이 아닌 것
// 같다」로 빼기 시작하면 추출이 사람의 판단에 기대게 되고, 그때부터 목록이 흔들린다.
// (`extract-places.mjs` 가 문을 좌표로 가르고 이름으로 안 가른 것과 같은 이유다.)
const registry = JSON.parse(readFileSync(join(registryDir, 'registry.json'), 'utf8'));
const fromRegistry = new Map();
for (const entity of registry.entities ?? []) {
  fromRegistry.set(entity.id, {
    equipment_id: entity.id,
    label: entity.display_name ?? null,
    // 260918 — 영어를 **실어 나르기만** 한다 (영문화 3단계). 원천은 레지스트리 하나다.
    // 레지스트리에 `_en` 이 없으면 null 로 둔다: 여기서 이름을 지어내지 않는다.
    label_en: entity.display_name_en ?? null,
    aliases: [...new Set((entity.aliases ?? []).filter(Boolean))].sort(),
    aliases_en: [...new Set((entity.aliases_en ?? []).filter(Boolean))].sort(),
    kind: entity.entity_type ?? null,
    zone_id: entity.zone ?? null,
  });
}

// ── 원천 2: 정답셋의 assigned_targets ────────────────────────────────────────
//
// 채점 어휘와 **같은 것을 같은 방법으로** 센다(`score-generation.mjs` 의
// `targetVocabulary`). 이 8건이 목록에 다 있어야 정답을 낼 길이 열린다 — 빠지면
// 「정답의 장비를 쓰지 말라」고 말한 셈이 되고, 그것도 `verify:no-leak` 이 잡는다.
const goldTargets = new Set();
for (const name of readdirSync(goldDir).filter((file) => file.endsWith('.json'))) {
  const mission = JSON.parse(readFileSync(join(goldDir, name), 'utf8'));
  for (const milestone of mission.milestones ?? []) {
    for (const target of milestone.assigned_targets ?? []) goldTargets.add(target);
  }
}

// ── 합집합 ───────────────────────────────────────────────────────────────────
const equipment = [];
for (const id of [...new Set([...fromRegistry.keys(), ...goldTargets])].sort()) {
  equipment.push(fromRegistry.get(id) ?? {
    // 레지스트리에 없다 — 이름도 종류도 모른다. **지어내지 않는다.**
    equipment_id: id, label: null, label_en: null, aliases: [], aliases_en: [], kind: null, zone_id: null,
  });
}

// ── 동작 어휘 (261023) ───────────────────────────────────────────────────────
//
// 머리말의 「동작 어휘」. **id 별로** 싣는다 — 같은 종류라도 장비마다 밝히는 명령이 다를 수
// 있고, 수문의 원천(`ACTION_CATALOG`)이 이미 id 별이다.
const { ACTION_CATALOG } = await import(pathToFileURL(join(vizRoot, 'gateway', 'commands.ts')).href);
const { STOP_ACTION } = await import(pathToFileURL(join(vizRoot, 'src', 'physical', 'presets.ts')).href);
const ROBOT_MISSION_ACTIONS = ['scan_mission', 'turn', 'move_forward', STOP_ACTION];
const actions = {};
for (const entry of equipment) {
  const fromCatalog = ACTION_CATALOG[entry.equipment_id];
  if (fromCatalog !== undefined) actions[entry.equipment_id] = fromCatalog.map((spec) => spec.action);
  else if (entry.kind === 'robot') actions[entry.equipment_id] = [...ROBOT_MISSION_ACTIONS];
}

// ── 계약 ─────────────────────────────────────────────────────────────────────
//
// 쓰기 전에 검사한다. 계약을 어긴 파일을 남기면 그것을 읽는 쪽이 먼저 깨지고,
// 그때는 원인이 추출기인지 읽는 쪽인지 가릴 수 없다.
const contracts = loadContracts(join(repoRoot, 'contracts'));
const schema = contracts.get('equipment.schema.json');
const contractErrors = equipment.flatMap((entry) => validate(entry, schema, contracts, `$[${entry.equipment_id}]`).errors ?? []);
if (contractErrors.length) {
  console.error(`❌ equipment.schema.json 위반 ${contractErrors.length}건\n- ${contractErrors.join('\n- ')}`);
  process.exit(1);
}

const registryOnly = equipment.filter((entry) => !goldTargets.has(entry.equipment_id));
const goldOnly = equipment.filter((entry) => entry.label === null);

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'equipment.json'), JSON.stringify({
  schema: 'contracts/equipment.schema.json',
  extracted_from: {
    registry: registryRel,
    goldset: 'gen-lab/goldset/missions/*.json 의 assigned_targets',
    script: 'scripts/extract-equipment.mjs',
    actions_actuator: 'viz-debugger/gateway/commands.ts 의 ACTION_CATALOG',
    actions_robot: 'viz-debugger/src/physical/encode.ts 의 PhysicalAction 중 임무가 로봇을 움직이는 넷 (정지 이름은 presets.ts 의 STOP_ACTION)',
  },
  note: '손으로 고치지 마라 — 원천은 레지스트리와 정답셋이고 `npm run extract:equipment` 로 다시 뽑는다. 레지스트리에 없는 식별자는 label·kind 가 null 이다: 이름을 지어내지 않는다.',
  vocabulary_note: `프롬프트에 싣는 목록은 채점 어휘(정답셋 assigned_targets 합집합 ${goldTargets.size}건)보다 **넓어야 한다.** 같아지면 오답 선택지가 없는 시험이 되어 이 축이 자기 자신을 채점한다. verify:no-leak 이 검사한다.`,
  actions_note: '생성 어휘다 — 생성기가 액션 아이템의 params.action 에 쓸 이름. **발행 시점의 확인과는 다른 자리다**: 9월에 「장비 종류·명령은 장비가 밝힌다」고 한 것은 발행의 이야기이고, 발행은 여전히 장비가 밝힌 Capability 로 확인해 모르는 명령을 거부한다. 여기 없는 장비(센서·카메라·엣지 노드)는 켜 두면 도는 서비스라 지정할 행동이 없다. 장비 계약이 항목에 additionalProperties:false 라 항목 밖 표로 둔다.',
  counts: { total: equipment.length, registry: fromRegistry.size, goldset_targets: goldTargets.size, wider_by: equipment.length - goldTargets.size },
  equipment,
  actions,
}, null, 2) + '\n', 'utf8');

const kinds = [...new Set(equipment.map((entry) => entry.kind).filter(Boolean))].sort();
console.log(`장비 ${equipment.length}건 — 레지스트리 ${fromRegistry.size} · 정답셋 ${goldTargets.size} (겹침 ${fromRegistry.size + goldTargets.size - equipment.length})`);
console.log(`채점 어휘보다 ${equipment.length - goldTargets.size}건 넓다 — 오답 선택지: ${registryOnly.map((entry) => entry.equipment_id).join(' · ') || '없다(축이 죽는다)'}`);
console.log(`이름을 모르는 식별자 ${goldOnly.length}건 (label·kind = null): ${goldOnly.map((entry) => entry.equipment_id).join(' · ') || '없다'}`);
console.log(`종류 ${kinds.length}종 — ${kinds.join(' · ')}  (레지스트리의 entity_type 을 그대로 옮긴다)`);
console.log(`동작 어휘 ${Object.keys(actions).length}대 — ${Object.entries(actions).map(([id, names]) => `${id}: ${names.join('·')}`).join(' / ')}`);
