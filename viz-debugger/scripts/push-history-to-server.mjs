#!/usr/bin/env node
/**
 * scripts/push-history-to-server.mjs (261119 신설 — 임무 이력 서버 DB 연동)
 *
 * **이 PC 의 `mission-history/` 를 임무 이력 서버로 올린다.** 서버가 붙기 전에 쌓인 판, 서버가 끊긴 동안
 * 이 PC 에만 쓰인 판(임무 이력 탭에 「이 PC만」 딱지)을 서버에 채운다. 화면의 줄은 탭을 닫으면 사라지지만
 * 파일은 남으므로 이것으로 메운다.
 *
 *   npm run history:push -- http://<서버>:<포트>            서버에 없는 판만
 *   npm run history:push -- http://<서버>:<포트> --dry      무엇을 올릴지만 적는다
 *   npm run history:push -- http://<서버>:<포트> --force    서버에 있어도 다시 덮는다
 *   (--dir <폴더> 로 다른 기록 폴더를 고를 수 있다. 기본은 저장소 루트 mission-history/)
 *
 * **이 PC 파일은 건드리지 않는다** — 읽기만 한다. 서버에도 지우는 창구가 없다.
 * 판 하나는 progress.json → 그림 → mission.json 순서로 올린다. 목록은 mission.json 이 있는 판만 보이므로,
 * 도중에 끊겨도 반쯤 올라간 판이 목록에 안 뜬다.
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { recordsDir } from './mission-records.mjs';

// DB 가 문자열 속 `\u0000` 을 못 받는다(HTTP 400) — 브라우저 올리기와 같은 함수로 뺀다(`src/record/jsonText.ts`).
const { stripJsonNul } = await import(pathToFileURL(join(import.meta.dirname, '..', 'src', 'record', 'jsonText.ts')).href);
const readJson = (file) => stripJsonNul(readFileSync(file, 'utf8'));

const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const option = (name) => { const at = args.indexOf(`--${name}`); return at >= 0 ? args[at + 1] : undefined; };
const server = (args.find((arg) => /^https?:\/\//.test(arg)) ?? process.env.HISTORY_SERVER ?? '').replace(/\/+$/, '').replace(/\/api\/v1$/, '');
if (server === '') {
  console.error('사용법: npm run history:push -- http://<서버>:<포트> [--dry] [--force] [--dir <폴더>]');
  process.exit(2);
}
const API = `${server}/api/v1`;
const root = option('dir') ?? recordsDir();
const dry = flag('dry');
const force = flag('force');

const DATE = /^\d{6}$/;
const RUN = /^\d{6}_[A-Za-z0-9_.-]{1,80}$/;
const IMAGE_NAME = /^[A-Za-z0-9_.-]{1,120}\.(jpg|jpeg|png)$/;

const health = await fetch(`${API}/health`).then((r) => r.json()).catch((error) => ({ error: String(error) }));
if (health?.service !== 'mission-history') {
  console.error(`임무 이력 서버가 아닙니다 (${API}/health): ${JSON.stringify(health)}`);
  process.exit(1);
}
const listed = await fetch(`${API}/runs`).then((r) => r.json());
const onServer = new Set((listed.runs ?? []).map((r) => `${r.date}/${r.run}`));

const local = [];
if (existsSync(root)) {
  for (const date of readdirSync(root).sort()) {
    if (!DATE.test(date) || !statSync(join(root, date)).isDirectory()) continue;
    for (const run of readdirSync(join(root, date)).sort()) {
      if (RUN.test(run) && existsSync(join(root, date, run, 'mission.json'))) local.push({ date, run });
    }
  }
}
const todo = local.filter(({ date, run }) => force || !onServer.has(`${date}/${run}`));
console.log(`이 PC ${local.length}판 (${root}) · 서버 ${onServer.size}판 · 올릴 판 ${todo.length}${dry ? ' — 시험(--dry), 안 올림' : ''}`);

let sent = 0;
let bytes = 0;
const failed = [];
for (const { date, run } of todo) {
  const dir = join(root, date, run);
  const base = `${API}/runs/${date}/${encodeURIComponent(run)}`;
  const images = [];
  for (const kind of ['detect', 'robot']) {
    const folder = join(dir, 'images', kind);
    if (!existsSync(folder)) continue;
    for (const name of readdirSync(folder)) if (IMAGE_NAME.test(name)) images.push({ kind, name });
  }
  if (dry) { console.log(`  ${date}/${run} · 그림 ${images.length}장`); continue; }
  try {
    const put = async (url, body, type, method = 'PUT') => {
      const response = await fetch(url, { method, body, headers: { 'Content-Type': type } });
      if (!response.ok) throw new Error(`${method} ${url.slice(API.length)} → HTTP ${response.status} ${await response.text().catch(() => '')}`);
      bytes += typeof body === 'string' ? Buffer.byteLength(body) : body.length;
    };
    if (existsSync(join(dir, 'progress.json'))) await put(`${base}/progress.json`, readJson(join(dir, 'progress.json')), 'application/json');
    for (const { kind, name } of images) {
      const body = readFileSync(join(dir, 'images', kind, name));
      if (body.length === 0) continue;
      await put(`${base}/images/${kind}/${encodeURIComponent(name)}`, body, name.endsWith('.png') ? 'image/png' : 'image/jpeg', 'POST');
    }
    await put(`${base}/mission.json`, readJson(join(dir, 'mission.json')), 'application/json');
    sent += 1;
    console.log(`  ok ${date}/${run} · 그림 ${images.length}장`);
  } catch (error) {
    failed.push(`${date}/${run}: ${error instanceof Error ? error.message : String(error)}`);
    console.log(`  FAIL ${date}/${run}`);
  }
}
if (!dry) console.log(`\n올림 ${sent}/${todo.length}판 · ${(bytes / 1024 / 1024).toFixed(1)}MB${failed.length > 0 ? `\n실패:\n  ${failed.join('\n  ')}` : ''}`);
process.exit(failed.length > 0 ? 1 : 0);
