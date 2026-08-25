/**
 * VZ-U-04 회귀 검증. 목 게이트웨이가 떠 있는 상태에서 실행한다.
 * 화면 클릭만 확인하면 서버 검증·시험 토큰·되돌리기 경계가 빠지므로 API 실물로 검사한다.
 */

const HTTP = process.env.MOCK_HTTP ?? 'http://127.0.0.1:8787';

async function request(path, body) {
  const response = await fetch(HTTP + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  const json = await response.json();
  return { status: response.status, body: json };
}

function graph(version) {
  return {
    id: 'verify-pipeline', version, serializationFormat: 'json',
    nodes: [
      { type: 'prometheus-range', label: 'source', kind: 'source', input: null, output: 'timeseries', executionLocation: 'server', id: 'src', x: 10, y: 10 },
      { type: 'resample', label: 'resample', kind: 'transform', input: 'timeseries', output: 'timeseries', executionLocation: 'server', id: 'step', x: 200, y: 10 },
      { type: 'graph-renderer', label: 'graph', kind: 'sink', input: 'timeseries', output: null, executionLocation: 'client', id: 'out', x: 400, y: 10 },
    ],
    edges: [{ from: 'src', to: 'step' }, { from: 'step', to: 'out' }],
  };
}

const failures = [];
const check = (condition, message) => { if (!condition) failures.push(message); };
const note = (message) => process.stdout.write(message + '\n');

async function main() {
  const catalog = await request('/pipelines/catalog');
  check(catalog.status === 200, '카탈로그 조회 실패');
  check(catalog.body.nodes?.length === 7, '카탈로그가 7종이 아니다');
  note(`■ 카탈로그 ${catalog.body.nodes?.length ?? 0}종`);

  const invalid = graph('0.0.1');
  invalid.edges = [{ from: 'src', to: 'out' }, { from: 'out', to: 'src' }];
  const invalidResult = await request('/pipelines/test', { graph: invalid });
  const invalidCodes = new Set(invalidResult.body.issues?.map((v) => v.code));
  for (const code of ['type_mismatch', 'direction', 'cycle']) check(invalidCodes.has(code), `무효 그래프에서 ${code}를 잡지 못했다`);
  note('■ 타입 불일치·역방향·순환 거부: ' + [...invalidCodes].join(', '));

  const orphan = graph('0.0.2'); orphan.edges = [];
  const orphanResult = await request('/pipelines/test', { graph: orphan });
  const orphanCodes = new Set(orphanResult.body.issues?.map((v) => v.code));
  check(orphanCodes.has('input_required') && orphanCodes.has('output_required'), '고립 노드 입력/출력을 모두 잡지 못했다');
  note('■ 고립 노드 거부: ' + [...orphanCodes].join(', '));

  const first = graph('1.0.0');
  const firstTest = await request('/pipelines/test', { graph: first });
  check(firstTest.body.ok && firstTest.body.outputs?.length === 3, '정상 그래프 시험 실행 실패');
  const wrongToken = await request('/pipelines/commit', { graph: first, token: 'wrong' });
  check(wrongToken.status === 409, '잘못된 시험 토큰이 409로 거부되지 않았다');
  const firstCommit = await request('/pipelines/commit', { graph: first, token: firstTest.body.token });
  check(firstCommit.body.state?.active?.version === '1.0.0', 'v1.0.0 반영 실패');

  const second = graph('1.0.1');
  const secondTest = await request('/pipelines/test', { graph: second });
  // 시험 뒤 초안을 바꾸면 같은 토큰을 쓸 수 없어야 한다.
  const changed = structuredClone(second); changed.version = '1.0.2';
  const changedCommit = await request('/pipelines/commit', { graph: changed, token: secondTest.body.token });
  check(changedCommit.status === 409, '시험 뒤 변경한 초안이 거부되지 않았다');
  const secondCommit = await request('/pipelines/commit', { graph: second, token: secondTest.body.token });
  check(secondCommit.body.state?.active?.version === '1.0.1', 'v1.0.1 반영 실패');
  check(secondCommit.body.state?.previous?.version === '1.0.0', '직전 버전 보존 실패');

  const rollback = await request('/pipelines/rollback', {});
  check(rollback.body.state?.active?.version === '1.0.0', '되돌리기 후 active가 v1.0.0이 아니다');
  check(rollback.body.state?.audit?.slice(-3).map((v) => v.action).join(',') === 'commit,commit,rollback', '감사 순서가 commit,commit,rollback이 아니다');
  note('■ 시험 토큰·변경 후 토큰 무효화·2회 반영·되돌리기·감사 확인');

  if (failures.length) {
    note(`\n❌ 실패 ${failures.length}건`);
    for (const failure of failures) note('   - ' + failure);
    process.exitCode = 1;
    return;
  }
  note('\n✅ 통과 — 그래프 검증, 시험 증명, 반영, 직전 버전 복구, 감사 확인');
}

main().catch((error) => {
  process.stderr.write('실행 실패 — ' + (error?.message ?? String(error)) + '\n');
  process.stderr.write('목 게이트웨이가 떠 있는지 확인할 것: npm run dev:mock\n');
  process.exitCode = 1;
});
