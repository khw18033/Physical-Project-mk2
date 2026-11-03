/* 지도 아래에 깔리는 **실측 도면** — 뒤처리 한 겹.

   렌더러 안을 고치지 않는다. `Map3D.drawZone`·`drawDomain` 이 그린 `<svg>` 를
   받아 그림을 맨 아래에 끼우고 보이는 범위만 넓힌다. 그리는 순서가 하나 더
   생길 뿐이고, 좌표를 다시 계산하지 않는다 — 계수는 서버가 이미 냈다.

   왜 뒤처리인가: 도면이 없는 배치가 **기본값**이기 때문이다. 렌더러 안에서
   갈라 두면 "도면 있는 길" 과 "없는 길" 두 벌이 생기고 둘 중 하나만 고쳐지는
   날이 온다. 지금 모양은 길이 하나이고 그림은 그 위에 얹힌다(AI-C-05).

   픽셀은 상태 계약으로 오지 않는다 — 선언은 `/api/background`, 그림 바이트는
   `/api/media?kind=map` 이다(AI-C-08).

   implements: AI-C-02, AI-C-05, AI-C-08, AI-C-16
*/
const MapBackground = (() => {
  const NS = "http://www.w3.org/2000/svg";
  /* 같은 도메인·층을 여러 화면이 함께 그리므로 선언은 한 번만 받아 둔다.
     그림 **바이트**는 브라우저가 캐시하므로 여기서 들고 있지 않는다. */
  const asked = new Map();

  /* 도메인을 적지 않으면 **현장** 그림을 묻는 것이다 — 메인 맵이 그 위에
     그려진다. 현장 그림의 앵커는 현장 로컬 좌표(원점 = datum)이고 도메인 로컬
     좌표가 아니라, 같은 그림을 두 프레임에 깔면 한쪽이 조용히 틀어진다(AI-C-02). */
  async function declaration(domainId, levelId, zoneId){
    const key = (domainId || "") + "/" + (levelId || "") + "/" + (zoneId || "");
    if (!asked.has(key)){
      const query = new URLSearchParams();
      if (domainId) query.set("domain", domainId);
      if (levelId) query.set("level", levelId);
      if (zoneId) query.set("zone", zoneId);
      asked.set(key, fetch("/api/background?" + query.toString())
        .then(r => r.ok ? r.json() : null)
        .then(body => (body && body.declared && body.image
                       && body.image.available) ? body.image : null)
        .catch(() => null));
    }
    return asked.get(key);
  }

  /* 로컬 좌표계에서 그림이 차지하는 자리. 서버가 준 계수의 역이다 —
     `px = local * scale + offset` 이므로 `local = (px - offset) / scale`. */
  function extent(image){
    const sx = image.scale.x, sy = image.scale.y;
    return {
      x: -image.offset.x / sx,
      y: -image.offset.y / sy,
      w: image.width_px / sx,
      h: image.height_px / sy,
    };
  }

  /* 보이는 범위를 그림까지 넓힌다. 구역 네모에 맞춰 둔 채로 그림을 깔면 치수선이
     잘려 나가고, 도면에서 치수선은 장식이 아니라 **근거**다. */
  function widen(svg, box){
    const view = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    if (view.length !== 4 || view.some(Number.isNaN)) return;
    const [vx, vy, vw, vh] = view;
    const x0 = Math.min(vx, box.x), y0 = Math.min(vy, box.y);
    const x1 = Math.max(vx + vw, box.x + box.w);
    const y1 = Math.max(vy + vh, box.y + box.h);
    svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
  }

  /** 그려 둔 지도 위에 도면을 깐다. 선언이 없으면 아무것도 하지 않는다. */
  async function apply(host, {domain, level, zone} = {}){
    const image = await declaration(domain, level, zone);
    if (!image || !host) return null;
    const svg = host.querySelector("svg.stage");
    if (!svg || svg.querySelector("image[data-plan]")) return image;

    const box = extent(image);
    const node = document.createElementNS(NS, "image");
    node.setAttribute("data-plan", image.layer_id);
    node.setAttribute("href",
      `/api/media?kind=map&file=${encodeURIComponent(image.media.file)}`);
    node.setAttribute("x", box.x);
    node.setAttribute("y", box.y);
    node.setAttribute("width", box.w);
    node.setAttribute("height", box.h);
    /* 도면은 늘여 맞추지 않는다. 앵커가 정한 자리에 **잰 크기 그대로** 놓이고,
       늘이는 순간 그림 위의 치수와 화면의 좌표가 서로 다른 말을 한다. */
    node.setAttribute("preserveAspectRatio", "none");
    node.setAttribute("opacity", "0.92");
    /* 그림은 **눌리지 않는다.** 깔아 둔 그림이 포인터를 받으면 그 위의 맵
       포인트가 눌리지 않는다 — 핀 묶음의 빈 자리를 누를 때 그림이 먼저 잡혀서
       드릴이 통째로 막힌다. 배경은 장식이고 잡을 것은 그 위에 있다. */
    node.setAttribute("pointer-events", "none");

    /* 맨 아래에 깐다 — 구역 네모·장치·경로가 그 위에 남아야 한다. 첫 `<g>` 가
       구역 좌표로 옮겨 놓는 묶음이라 그 안의 맨 앞에 넣는다. */
    const layer = svg.querySelector("g") || svg;
    layer.insertBefore(node, layer.firstChild);
    /* 도면을 맨 아래에 깔았는데 그 위에 **흰 바닥**이 있으면 그림이 통째로
       가려진다. 도면이 없을 때 흰 바닥은 도면 노릇을 하지만, 있을 때는 그것이
       곧 가리개다. 바닥 네모만 투명으로 바꾼다 — 벽 선(stroke)은 남는다. */
    const base = layer.querySelector("rect");
    if (base && base.getAttribute("fill") === "#ffffff")
      base.setAttribute("fill", "transparent");
    widen(svg, box);
    return image;
  }

  return {apply, declaration};
})();
