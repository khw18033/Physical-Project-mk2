/**
 * scripts/video-records.mjs (261007 신설 — 실시간 화면 녹화 저장 · 3D 가상환경 PC 이름)
 *
 * **브라우저가 녹화한 영상을 파일로 받는 창구.** 녹화는 화면이 한다(`src/record/screenRecord.ts` — 지금 보고 있는
 * 탭을 찍어 영상 칸만 잘라낸다). 브라우저는 아무 폴더에나 쓸 수 없으므로 조각을 여기로 보내고, 여기서 저장소 루트
 * `video/<날짜>/<시각>_<이름>.<mp4|webm>` 에 이어 쓴다. 폴더가 없으면 만든다. 루트 `.gitignore` 가 화이트리스트라
 * `video/` 는 저절로 안 올라간다.
 *
 *   POST /video-records/open    { label, ext }  → { id, path }   이름만 잡는다. 파일은 첫 조각이 올 때 생긴다
 *   POST /video-records/append?id=<id>          → 본문(조각) 그대로 파일 끝에 붙인다
 *   POST /video-records/close?id=<id>           → { path, bytes } 한 조각도 안 왔으면 파일이 없다(bytes 0)
 *   GET  /video-records/ping                    → { ok, dir } 화면이 「저장 창구가 있다」를 안다(단독 빌드에는 없다)
 *
 * 조각을 1초마다 보내므로, 녹화 중에 브라우저가 죽어도 거기까지는 파일에 남는다.
 *
 * ## 3D 가상환경 PC 이름 (`/video-records/host-name`)
 *
 * 하드웨어 카드에 3D 가상환경을 띄울 때 카드 이름은 **그 화면을 내보내는 PC 의 이름**이다(261007 지시 — 방법 (나)).
 * 브라우저는 상대 PC 이름을 알 길이 없어서, 이 PC 의 `tailscale status --json` 에서 그 주소의 기기 이름을 찾는다.
 *
 *   GET /video-records/host-name?host=<IP 또는 이름>  → { name } 못 찾으면 { name: null }
 *
 * 녹화와는 다른 일이지만, 개발 서버에 붙는 작은 창구를 하나 더 늘리지 않으려고 여기 둔다.
 */

import { execFile } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, statSync } from 'node:fs';
import { hostname } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const VIDEO_URL = '/video-records';
const DEFAULT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'video');
/** 조각 하나의 상한. 1초 조각은 비트레이트 4Mbps 기준 0.5MB 안팎이다. */
const MAX_CHUNK = 64 * 1024 * 1024;
const EXT = /^(mp4|webm)$/;
const TAILSCALE_TIMEOUT_MS = 4000;
const TAILSCALE_CACHE_MS = 60_000;

export function videoDir() {
  return process.env.VIDEO_RECORDS_DIR ? resolve(process.env.VIDEO_RECORDS_DIR) : DEFAULT_DIR;
}

const pad = (value) => String(value).padStart(2, '0');

/** 이 PC 시각으로 `YYMMDD` · `HHMMSS` — `mission-history/` 의 날짜 폴더와 같은 모양이다. */
export function stamp(date = new Date()) {
  return {
    day: `${pad(date.getFullYear() % 100)}${pad(date.getMonth() + 1)}${pad(date.getDate())}`,
    time: `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`,
  };
}

/**
 * 파일 이름에 넣을 수 있게 다듬는다. 장치 이름 · 모델 이름은 한국어일 수 있어서 글자는 남기고, Windows 가 막는 글자
 * (`\ / : * ? " < > |`) · 공백 · 제어 문자만 `-` 로 바꾼다. 비면 `video`.
 */
export function safeLabel(label) {
  const cleaned = String(label ?? '')
    // eslint-disable-next-line no-control-regex
    .replace(/[\\/:*?"<>|\s\u0000-\u001f]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
    .slice(0, 80);
  return cleaned === '' ? 'video' : cleaned;
}

/** 같은 초에 같은 이름이 또 오면(동시 녹화) 뒤에 `-2`, `-3` 을 붙인다. 잡아 둔 이름(`taken`)도 피한다. */
export function freeName(dir, base, ext, taken = new Set()) {
  for (let n = 1; n < 1000; n += 1) {
    const name = n === 1 ? `${base}.${ext}` : `${base}-${n}.${ext}`;
    if (!taken.has(join(dir, name)) && !existsSync(join(dir, name))) return name;
  }
  throw new Error('같은 이름의 녹화가 너무 많습니다');
}

/**
 * `tailscale status --json` 에서 그 주소(IP · 기기 이름 · DNS 이름)의 기기 이름을 찾는다. **순수 함수**라 검사가 그대로 부른다.
 * 자기 자신(`Self`)도 본다 — 3D 가상환경을 이 PC 에서 띄웠을 수 있다.
 */
export function tailscaleNameOf(status, host) {
  const want = String(host ?? '').trim().toLowerCase().replace(/\.$/, '');
  if (want === '' || status === null || typeof status !== 'object') return null;
  const nodes = [status.Self, ...Object.values(status.Peer ?? {})].filter((node) => node && typeof node === 'object');
  for (const node of nodes) {
    const ips = Array.isArray(node.TailscaleIPs) ? node.TailscaleIPs : [];
    const dns = String(node.DNSName ?? '').toLowerCase().replace(/\.$/, '');
    const name = String(node.HostName ?? '');
    if (ips.includes(want) || (dns !== '' && (dns === want || dns.split('.')[0] === want)) || name.toLowerCase() === want) {
      return name === '' ? null : name;
    }
  }
  return null;
}

let tailscaleCache = { at: 0, status: null };

function readTailscale() {
  if (Date.now() - tailscaleCache.at < TAILSCALE_CACHE_MS && tailscaleCache.status !== null) return Promise.resolve(tailscaleCache.status);
  return new Promise((resolveStatus) => {
    execFile('tailscale', ['status', '--json'], { timeout: TAILSCALE_TIMEOUT_MS, windowsHide: true, maxBuffer: 8 * 1024 * 1024 }, (error, stdout) => {
      if (error) { resolveStatus(null); return; }
      try {
        const status = JSON.parse(stdout);
        tailscaleCache = { at: Date.now(), status };
        resolveStatus(status);
      } catch {
        resolveStatus(null);
      }
    });
  });
}

/** 그 주소의 PC 이름. 이 PC 자신(`localhost` · `127.0.0.1`)이면 OS 이름을 쓴다. */
export async function hostNameOf(host, read = readTailscale) {
  const want = String(host ?? '').trim().toLowerCase();
  if (want === 'localhost' || want === '127.0.0.1' || want === '::1') return hostname();
  return tailscaleNameOf(await read(), want);
}

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

function readBody(req, limit) {
  return new Promise((resolveBody, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) { reject(new Error('본문이 너무 큽니다')); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on('end', () => resolveBody(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/** 미들웨어 본체. 내 주소가 아니면 `next()`. `root` 는 검사가 임시 폴더로 바꾼다. */
export function videoRecordsMiddleware(root = videoDir(), lookup = hostNameOf) {
  /** 열린 녹화 — id → 파일. 개발 서버가 다시 뜨면 비지만, 그때는 화면의 녹화도 이어 쓸 곳을 잃는다(닫기가 실패로 적힌다). */
  const open = new Map();
  let serial = 0;
  return async (req, res, next) => {
    const [path, query = ''] = (req.url ?? '').split('?');
    if (!path.startsWith(`${VIDEO_URL}/`)) return next();
    const params = new URLSearchParams(query);
    const action = path.slice(VIDEO_URL.length + 1);
    try {
      if (action === 'ping' && req.method === 'GET') return send(res, 200, { ok: true, dir: root });
      if (action === 'host-name' && req.method === 'GET') return send(res, 200, { name: await lookup(params.get('host') ?? '') });
      if (action === 'open' && req.method === 'POST') {
        const body = JSON.parse((await readBody(req, 64 * 1024)).toString('utf8') || '{}');
        const ext = EXT.test(body.ext ?? '') ? body.ext : 'webm';
        const { day, time } = stamp();
        const dir = join(root, day);
        const taken = new Set([...open.values()].map((item) => item.file));
        const name = freeName(dir, `${time}_${safeLabel(body.label)}`, ext, taken);
        serial += 1;
        const id = `${Date.now().toString(36)}-${serial}`;
        open.set(id, { dir, file: join(dir, name), rel: `video/${day}/${name}`, bytes: 0 });
        return send(res, 200, { id, path: `video/${day}/${name}` });
      }
      const item = open.get(params.get('id') ?? '');
      if ((action === 'append' || action === 'close') && req.method === 'POST' && item === undefined) {
        return send(res, 404, { error: '열린 녹화가 아닙니다 — 개발 서버가 다시 떴을 수 있습니다' });
      }
      if (action === 'append' && req.method === 'POST') {
        const chunk = await readBody(req, MAX_CHUNK);
        if (chunk.length > 0) {
          mkdirSync(item.dir, { recursive: true });
          appendFileSync(item.file, chunk);
          item.bytes += chunk.length;
        }
        return send(res, 200, { ok: true, bytes: item.bytes });
      }
      if (action === 'close' && req.method === 'POST') {
        open.delete(params.get('id'));
        const bytes = existsSync(item.file) ? statSync(item.file).size : 0;
        return send(res, 200, { path: bytes > 0 ? item.rel : null, bytes });
      }
      return send(res, 404, { error: '없는 창구입니다' });
    } catch (error) {
      return send(res, 500, { error: error instanceof Error ? error.message : String(error) });
    }
  };
}

/** Vite 플러그인 — 개발 서버와 미리보기 서버에 같은 미들웨어를 붙인다. */
export function videoRecords() {
  return {
    name: 'video-records',
    configureServer(server) { server.middlewares.use(videoRecordsMiddleware()); },
    configurePreviewServer(server) { server.middlewares.use(videoRecordsMiddleware()); },
  };
}
