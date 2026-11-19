/**
 * scripts/history-server-mock.mjs (261119 신설 — 임무 이력 서버 DB 연동 준비)
 *
 * **임무 이력 서버의 가짜.** 서버 담당이 만들 서버(`documents/협의/임무이력서버_요청_VZ_261119.md`)와
 * **같은 창구**를 낸다. 진짜 서버가 오기 전까지 가시화 쪽 연결 · 양쪽 저장 · 목록 합치기를 이것으로 시험한다.
 * DB 대신 폴더에 쓴다 — 본체는 개발 서버의 기록 창구(`mission-records.mjs`)이고 경로만 `/api/v1` 로 바꾼다.
 *
 *   npm run history:mock                       → http://0.0.0.0:8790 · 폴더는 OS 임시 폴더 아래
 *   npm run history:mock -- --port 9000 --dir D:/history-test
 *
 * 규약 문서가 요구하는 것 중 여기서 내는 것:
 *   GET  /api/v1/health                        서버 확인 (service = "mission-history")
 *   GET  /api/v1/runs                          판 목록
 *   PUT  /api/v1/runs/<날짜>/<판>/<mission|progress>.json
 *   POST /api/v1/runs/<날짜>/<판>/images/<detect|robot>/<이름>
 *   GET  /api/v1/files/<날짜>/<판>/<경로>
 *   CORS (사전 요청 OPTIONS 포함) · Private Network Access 허용 머리
 */

import { createServer } from 'node:http';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { listRuns, missionRecordsMiddleware } from './mission-records.mjs';

export const HISTORY_API = '/api/v1';
export const HISTORY_SERVICE = 'mission-history';

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, PUT, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  res.setHeader('Access-Control-Max-Age', '600');
}

/** 요청 처리기. 검사 스크립트가 임의 포트로 띄울 수 있게 서버와 갈라 둔다. */
export function historyServerHandler(dir, { label = 'mock' } = {}) {
  mkdirSync(dir, { recursive: true });
  const records = missionRecordsMiddleware(dir, { runs: `${HISTORY_API}/runs`, files: `${HISTORY_API}/files`, dir: label });
  return (req, res) => {
    cors(res);
    if (req.method === 'OPTIONS') { res.statusCode = 204; res.end(); return; }
    const url = (req.url ?? '').split('?')[0];
    if (url === `${HISTORY_API}/health` && req.method === 'GET') {
      res.statusCode = 200;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Cache-Control', 'no-store');
      res.end(JSON.stringify({ ok: true, service: HISTORY_SERVICE, apiVersion: 1, serverTime: new Date().toISOString(), runCount: listRuns(dir).length, label }));
      return;
    }
    void records(req, res, () => {
      res.statusCode = 404;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({ error: '없는 창구입니다' }));
    });
  };
}

export function startHistoryServer({ dir, port = 8790, host = '0.0.0.0', label } = {}) {
  const server = createServer(historyServerHandler(dir, { label }));
  return new Promise((done) => server.listen(port, host, () => done(server)));
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = (name, fallback) => {
    const at = process.argv.indexOf(`--${name}`);
    return at >= 0 && process.argv[at + 1] !== undefined ? process.argv[at + 1] : fallback;
  };
  const dir = resolve(arg('dir', join(tmpdir(), 'viz-history-mock')));
  const port = Number(arg('port', '8790'));
  const server = await startHistoryServer({ dir, port, host: arg('host', '0.0.0.0'), label: `mock:${dir}` });
  const at = server.address();
  console.log(`임무 이력 가짜 서버 — http://${at.address === '0.0.0.0' ? 'localhost' : at.address}:${at.port}  (폴더 ${dir})`);
  console.log('임무 이력 탭 맨 위 서버 칸에 이 주소를 넣으면 붙습니다. 끄려면 Ctrl+C');
}
