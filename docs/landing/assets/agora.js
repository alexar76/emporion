/** EMPORION hero — the trading post at night, drawn as what the service does.
 *
 *  seal       the struck bronze coin in the middle: every answer leaves EMPORION signed
 *  beacons    the seven public sources on a ring around it — VIES, GLEIF, ECB, OFAC, the EU,
 *             the UN and Bitcoin
 *  fact       a pulse of light from a source to the seal: one fetched answer
 *  receipt    the seal flashes and a ring runs out from it, with the evidence it carries — the
 *             list's SHA-256 for a sanctions list, "signed" for a per-call answer
 *  chain      Bitcoin blocks drifting behind; now and then the seal anchors a digest in one
 *
 * LIVE when the running service answers emporion.sources@v1: the beacons of the sanctions lists
 * it holds are lit, their receipts carry the lists' real SHA-256, and the badge names the lists
 * with their entry counts. ILLUSTRATION otherwise — badged as such, with made-up hashes, because a
 * picture of evidence is not evidence.
 */
import * as THREE from "./vendor/three/three.module.min.js";
import { EffectComposer } from "./vendor/three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/three/addons/postprocessing/OutputPass.js";

// On its own domain the page asks itself; the GitHub Pages copy asks the live service (CORS
// allows alexar76.github.io); a local copy asks a local EMPORION.
const HOST = location.hostname;
const API = /^(localhost|127\.0\.0\.1)$/.test(HOST) ? "http://127.0.0.1:9351"
  : HOST === "emporion.modelmarket.dev" ? "" : "https://emporion.modelmarket.dev";

const BRONZE = 0xd9a441;
const SOURCES = [
  { id: "VIES", label: "EU VIES", color: 0x6f9cff },
  { id: "GLEIF", label: "GLEIF", color: 0x4fb8ad },
  { id: "ECB", label: "ECB", color: 0x8fd4ff },
  { id: "OFAC-SDN", label: "OFAC", color: 0xe8b85a, list: true },
  { id: "EU", label: "EU FSF", color: 0x8aa8ff, list: true },
  { id: "UN", label: "UN", color: 0x62c6f0, list: true },
  { id: "BTC", label: "BITCOIN", color: 0xf7931a },
];

// ------------------------------------------------------------------------------------------
// live data
// ------------------------------------------------------------------------------------------
async function fetchLive() {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 6000);
  try {
    const res = await fetch(`${API}/ai-market/v2/invoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capability_id: "emporion.sources@v1", input: {} }),
      signal: ctrl.signal,
    });
    if (!res.ok) return null;
    const body = await res.json();
    const lists = body && body.ok && body.output && body.output.sanctions && body.output.sanctions.lists;
    if (!lists || typeof lists !== "object") return null;
    const held = {};
    for (const [name, meta] of Object.entries(lists)) {
      if (meta && Array.isArray(meta.sha256) && meta.sha256.length) {
        held[name] = { entries: Number(meta.entries) || 0, sha256: String(meta.sha256[0]) };
      }
    }
    return held;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ------------------------------------------------------------------------------------------
// textures drawn on canvases
// ------------------------------------------------------------------------------------------
function canvasTexture(size, draw) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function coinFace() {
  return canvasTexture(1024, (g, s) => {
    const r = s / 2;
    const bg = g.createRadialGradient(r * 0.7, r * 0.6, r * 0.1, r, r, r);
    bg.addColorStop(0, "#f6d58e");
    bg.addColorStop(0.55, "#c08a32");
    bg.addColorStop(1, "#6b4612");
    g.fillStyle = bg;
    g.fillRect(0, 0, s, s);
    g.translate(r, r);
    g.strokeStyle = "rgba(60, 36, 8, 0.75)";
    g.fillStyle = "rgba(60, 36, 8, 0.82)";
    // Rim and inner rings.
    for (const [rad, w] of [[0.965, 10], [0.86, 5], [0.62, 4]]) {
      g.lineWidth = w;
      g.beginPath();
      g.arc(0, 0, r * rad, 0, Math.PI * 2);
      g.stroke();
    }
    // A Greek key (meander) band between the outer rings.
    const steps = 44;
    g.lineWidth = 6;
    for (let i = 0; i < steps; i++) {
      g.save();
      g.rotate((i / steps) * Math.PI * 2);
      const a = r * 0.875, b = r * 0.945, w = (Math.PI * 2 * r * 0.91) / steps;
      g.beginPath();
      g.moveTo(-w / 2, -a);
      g.lineTo(-w / 2, -b);
      g.lineTo(w / 4, -b);
      g.lineTo(w / 4, -a - (b - a) * 0.35);
      g.lineTo(-w / 8, -a - (b - a) * 0.35);
      g.lineTo(-w / 8, -a);
      g.lineTo(w / 2, -a);
      g.stroke();
      g.restore();
    }
    // Lettering round the field: the Greek word and the Latin name.
    const text = "ἘΜΠΌΡΙΟΝ · EMPORION · ";
    g.font = `600 ${Math.round(s * 0.05)}px Syne, Georgia, serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    const chars = [...text];
    for (let i = 0; i < chars.length; i++) {
      g.save();
      g.rotate((i / chars.length) * Math.PI * 2);
      g.fillText(chars[i], 0, -r * 0.74);
      g.restore();
    }
    // The device in the middle: a ship's prow over a balance — trade and its scales.
    g.font = `800 ${Math.round(s * 0.34)}px Syne, Georgia, serif`;
    g.fillText("Ε", 0, -r * 0.02);
    g.lineWidth = 7;
    g.beginPath();
    g.moveTo(-r * 0.34, r * 0.33);
    g.lineTo(r * 0.34, r * 0.33);
    g.stroke();
    for (const x of [-0.28, 0.28]) {
      g.beginPath();
      g.arc(r * x, r * 0.4, r * 0.07, 0, Math.PI);
      g.stroke();
    }
  });
}

function glowDot(color) {
  return canvasTexture(128, (g, s) => {
    const r = s / 2;
    const grd = g.createRadialGradient(r, r, 0, r, r, r);
    const c = new THREE.Color(color);
    const rgb = `${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)}`;
    grd.addColorStop(0, `rgba(255, 255, 255, 1)`);
    grd.addColorStop(0.22, `rgba(${rgb}, 0.9)`);
    grd.addColorStop(1, `rgba(${rgb}, 0)`);
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
  });
}

function textSprite(text, color, height) {
  const pad = 18, fontPx = 56;
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  g.font = `600 ${fontPx}px "DM Sans", system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(text).width) + pad * 2;
  c.width = w;
  c.height = fontPx + pad * 2;
  g.font = `600 ${fontPx}px "DM Sans", system-ui, sans-serif`;
  g.textBaseline = "middle";
  g.fillStyle = color;
  g.fillText(text, pad, c.height / 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set((height * c.width) / c.height, height, 1);
  sprite.userData.dispose = () => { tex.dispose(); mat.dispose(); };
  return sprite;
}

function randomHex(n) {
  let s = "";
  for (let i = 0; i < n; i++) s += "0123456789abcdef"[(Math.random() * 16) | 0];
  return s;
}

// ------------------------------------------------------------------------------------------
// the scene
// ------------------------------------------------------------------------------------------
export function mountAgora(canvas, { reducedMotion = false, onLive = () => {} } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch {
    return null;
  }
  const small = Math.min(window.innerWidth, window.innerHeight) < 700;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0e0b07, 0.028);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200);
  const stage = new THREE.Group();
  scene.add(stage);

  scene.add(new THREE.HemisphereLight(0xffe2b0, 0x1a1206, 0.9));
  const key = new THREE.PointLight(0xffd08a, 60, 40, 1.6);
  key.position.set(-4, 5, 8);
  scene.add(key);
  const rimLight = new THREE.PointLight(0x4fb8ad, 30, 30, 1.8);
  rimLight.position.set(5, -1, -4);
  scene.add(rimLight);

  // ── the seal ──
  const face = coinFace();
  const coinGeo = new THREE.CylinderGeometry(2.1, 2.1, 0.26, 128, 1);
  const rimMat = new THREE.MeshStandardMaterial({ color: 0x9c6b22, metalness: 0.75, roughness: 0.38,
    emissive: 0x3a2508, emissiveIntensity: 0.4 });
  const faceMat = new THREE.MeshStandardMaterial({ map: face, metalness: 0.55, roughness: 0.42,
    emissive: 0xffffff, emissiveMap: face, emissiveIntensity: 0.16 });
  const coin = new THREE.Mesh(coinGeo, [rimMat, faceMat, faceMat]);
  coin.rotation.x = Math.PI / 2;
  const coinPivot = new THREE.Group();
  coinPivot.add(coin);
  coinPivot.position.set(0, 0.35, 0);
  stage.add(coinPivot);

  const halo = new THREE.Mesh(new THREE.TorusGeometry(2.32, 0.035, 12, 160),
    new THREE.MeshBasicMaterial({ color: BRONZE, transparent: true, opacity: 0.9 }));
  coinPivot.add(halo);
  const haloGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowDot(BRONZE), transparent: true,
    opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending }));
  haloGlow.scale.setScalar(9);
  coinPivot.add(haloGlow);

  // ── the agora floor ──
  const floor = new THREE.PolarGridHelper(9, 14, 5, 128, 0x5c4320, 0x2e2210);
  floor.position.y = -2.3;
  floor.material.transparent = true;
  floor.material.opacity = 0.55;
  stage.add(floor);

  // ── the seven sources ──
  const RING = 6.4;
  const beacons = SOURCES.map((src, i) => {
    const a = -Math.PI / 2 + ((i + 0.5) / SOURCES.length) * Math.PI * 2;
    const pos = new THREE.Vector3(Math.cos(a) * RING, -2.3, Math.sin(a) * RING * 0.9);
    const group = new THREE.Group();
    group.position.copy(pos);
    const pillarMat = new THREE.MeshStandardMaterial({ color: src.color, emissive: src.color,
      emissiveIntensity: 0.55, metalness: 0.2, roughness: 0.5, transparent: true });
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.11, 1.5, 12), pillarMat);
    pillar.position.y = 0.75;
    const tip = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowDot(src.color), transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    tip.scale.setScalar(0.9);
    tip.position.y = 1.6;
    const label = textSprite(src.label, "#e9dcc4", 0.42);
    label.position.y = 2.25;
    group.add(pillar, tip, label);
    stage.add(group);
    return { src, group, pillarMat, tip, label, lit: true, hash: null, top: pos.clone().setY(pos.y + 1.6) };
  });

  // ── the Bitcoin chain behind ──
  const chain = new THREE.Group();
  chain.position.set(0, -1.6, -6.5);
  stage.add(chain);
  const blockGeo = new THREE.BoxGeometry(0.62, 0.62, 0.62);
  const blockEdges = new THREE.EdgesGeometry(blockGeo);
  const BLOCKS = 13, GAP = 1.15;
  const blocks = [];
  for (let i = 0; i < BLOCKS; i++) {
    const mat = new THREE.LineBasicMaterial({ color: 0xf7931a, transparent: true, opacity: 0.55 });
    const fillMat = new THREE.MeshBasicMaterial({ color: 0xf7931a, transparent: true, opacity: 0.05 });
    const b = new THREE.Group();
    b.add(new THREE.LineSegments(blockEdges, mat), new THREE.Mesh(blockGeo, fillMat));
    b.position.x = (i - BLOCKS / 2) * GAP;
    b.userData = { mat, fillMat, glow: 0 };
    chain.add(b);
    blocks.push(b);
  }

  // ── embers rising over the agora ──
  const EMBERS = small ? 260 : 520;
  const emberPos = new Float32Array(EMBERS * 3);
  const emberSpeed = new Float32Array(EMBERS);
  for (let i = 0; i < EMBERS; i++) {
    const r = Math.sqrt(Math.random()) * 10, a = Math.random() * Math.PI * 2;
    emberPos.set([Math.cos(a) * r, -2.3 + Math.random() * 8, Math.sin(a) * r], i * 3);
    emberSpeed[i] = 0.12 + Math.random() * 0.35;
  }
  const emberGeo = new THREE.BufferGeometry();
  emberGeo.setAttribute("position", new THREE.BufferAttribute(emberPos, 3));
  const embers = new THREE.Points(emberGeo, new THREE.PointsMaterial({ map: glowDot(0xffc46b), size: 0.16,
    transparent: true, opacity: 0.7, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
  stage.add(embers);

  // ── facts, receipts and anchors ──
  const pulseTex = glowDot(0xffffff);
  const live = { held: null };
  const flights = [];   // light travelling along a curve
  const receipts = [];  // rings and hash labels leaving the seal
  let flash = 0;

  function curveBetween(from, to, lift) {
    const mid = from.clone().lerp(to, 0.5);
    mid.y += lift;
    return new THREE.QuadraticBezierCurve3(from, mid, to);
  }

  function spawnFact() {
    const lit = beacons.filter((b) => b.lit);
    if (!lit.length) return;
    const b = lit[(Math.random() * lit.length) | 0];
    const head = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulseTex, color: b.src.color,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    head.scale.setScalar(0.75);
    stage.add(head);
    const trail = Array.from({ length: 6 }, (_, k) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulseTex, color: b.src.color,
        transparent: true, opacity: 0.5 - k * 0.07, depthWrite: false, blending: THREE.AdditiveBlending }));
      s.scale.setScalar(0.55 - k * 0.06);
      stage.add(s);
      return s;
    });
    flights.push({ kind: "fact", beacon: b, head, trail, t: 0, dur: 1.5 + Math.random() * 0.5,
      curve: curveBetween(b.top, coinPivot.position, 2.6) });
  }

  function spawnAnchor() {
    const target = blocks.reduce((m, x) => (x.position.x > m.position.x ? m : x), blocks[0]);
    const to = new THREE.Vector3().setFromMatrixPosition(target.matrixWorld);
    stage.worldToLocal(to);
    const head = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulseTex, color: 0xf7931a,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    head.scale.setScalar(0.7);
    stage.add(head);
    flights.push({ kind: "anchor", block: target, head, trail: [], t: 0, dur: 1.4,
      curve: curveBetween(coinPivot.position.clone(), to, 1.2) });
  }

  function receipt(beacon) {
    flash = 1;
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.3, 2.42, 128),
      new THREE.MeshBasicMaterial({ color: beacon.src.color, transparent: true, opacity: 0.85,
        side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    ring.position.copy(coinPivot.position);
    stage.add(ring);
    let text;
    if (beacon.src.list) {
      const hex = beacon.hash || randomHex(12);
      text = `${beacon.src.label} · sha256 ${hex.slice(0, 12)}…`;
    } else {
      text = `${beacon.src.label} · signed`;
    }
    const tag = textSprite(text, "#f4ede1", 0.36);
    tag.position.copy(coinPivot.position).add(new THREE.Vector3((Math.random() - 0.5) * 2.2, 2.6, 0.6));
    stage.add(tag);
    receipts.push({ ring, tag, t: 0, dur: 2.6 });
  }

  function dispose3(obj) {
    stage.remove(obj);
    if (obj.userData && obj.userData.dispose) obj.userData.dispose();
    else {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    }
  }

  // ── post-processing: the glow ──
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.72, 0.5, 0.22);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ── framing ──
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  function fit() {
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w / 2, h / 2);
    camera.aspect = w / h;
    // On a wide screen the hero text owns the left half: the agora stands to the right.
    stage.position.x = camera.aspect > 1.15 ? Math.min(5.6, 2.6 * camera.aspect) : 0;
    camera.position.set(0, 2.0, camera.aspect < 0.8 ? 22 : 15.5);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(() => { fit(); if (reducedMotion) frame(0); });
  ro.observe(canvas);
  fit();
  window.addEventListener("pointermove", (e) => {
    pointer.tx = (e.clientX / window.innerWidth - 0.5) * 2;
    pointer.ty = (e.clientY / window.innerHeight - 0.5) * 2;
  }, { passive: true });

  // ── time ──
  let elapsed = 0, nextFact = 0.4, nextAnchor = 3.5;
  const look = new THREE.Vector3();
  function frame(dt) {
    elapsed += dt;
    pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 2);
    pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 2);
    camera.position.x = pointer.x * 1.2;
    camera.position.y = 2.0 - pointer.y * 0.6;
    look.set(0, -0.2, 0); // the camera looks at the middle; the stage stands where fit() put it
    camera.lookAt(look);

    coinPivot.rotation.y = Math.sin(elapsed * 0.35) * 0.55;
    coinPivot.position.y = 0.35 + Math.sin(elapsed * 0.8) * 0.08;
    flash = Math.max(0, flash - dt * 1.8);
    faceMat.emissiveIntensity = 0.16 + flash * 0.5;
    halo.material.opacity = 0.65 + flash * 0.35;
    halo.rotation.z += dt * 0.15;

    for (const b of beacons) {
      const target = b.lit ? 1 : 0.18;
      b.pillarMat.opacity += (target - b.pillarMat.opacity) * Math.min(1, dt * 3);
      b.tip.material.opacity = b.pillarMat.opacity * (0.85 + Math.sin(elapsed * 2 + b.group.position.x) * 0.15);
      b.label.material.opacity = 0.45 + 0.55 * b.pillarMat.opacity;
    }

    for (const blk of blocks) {
      blk.position.x -= dt * 0.22;
      if (blk.position.x < -(BLOCKS / 2) * GAP) blk.position.x += BLOCKS * GAP;
      blk.rotation.y += dt * 0.2;
      blk.userData.glow = Math.max(0, blk.userData.glow - dt * 0.6);
      blk.userData.mat.opacity = 0.45 + blk.userData.glow * 0.55;
      blk.userData.fillMat.opacity = 0.05 + blk.userData.glow * 0.45;
    }

    const p = emberGeo.attributes.position.array;
    for (let i = 0; i < EMBERS; i++) {
      p[i * 3 + 1] += emberSpeed[i] * dt;
      if (p[i * 3 + 1] > 6) p[i * 3 + 1] = -2.3;
    }
    emberGeo.attributes.position.needsUpdate = true;

    if (!reducedMotion) {
      nextFact -= dt;
      if (nextFact <= 0) { spawnFact(); nextFact = 0.9 + Math.random() * 1.1; }
      nextAnchor -= dt;
      if (nextAnchor <= 0) { spawnAnchor(); nextAnchor = 6 + Math.random() * 4; }
    }

    for (let i = flights.length - 1; i >= 0; i--) {
      const f = flights[i];
      f.t += dt / f.dur;
      const u = Math.min(1, f.t);
      f.head.position.copy(f.curve.getPoint(u));
      f.trail.forEach((s, k) => s.position.copy(f.curve.getPoint(Math.max(0, u - (k + 1) * 0.035))));
      if (f.t >= 1) {
        if (f.kind === "fact") receipt(f.beacon);
        else f.block.userData.glow = 1;
        dispose3(f.head);
        f.trail.forEach(dispose3);
        flights.splice(i, 1);
      }
    }
    for (let i = receipts.length - 1; i >= 0; i--) {
      const r = receipts[i];
      r.t += dt / r.dur;
      const s = 1 + r.t * 0.9;
      r.ring.scale.set(s, s, 1);
      r.ring.rotation.y = coinPivot.rotation.y;
      r.ring.material.opacity = 0.85 * (1 - r.t);
      r.tag.position.y += dt * 0.55;
      r.tag.material.opacity = r.t < 0.15 ? r.t / 0.15 : 1 - (r.t - 0.15) / 0.85;
      if (r.t >= 1) {
        dispose3(r.ring);
        dispose3(r.tag);
        receipts.splice(i, 1);
      }
    }
    composer.render(dt);
  }

  // ── the loop: paused off screen and in a background tab ──
  let running = true, visible = true, last = performance.now();
  const io = new IntersectionObserver((items) => { visible = items.some((it) => it.isIntersecting); });
  io.observe(canvas);
  function loop() {
    if (!running) return;
    requestAnimationFrame(loop);
    const now = performance.now();
    const dt = (now - last) / 1000;
    last = now;
    if (!visible || document.hidden) return;
    frame(Math.min(0.05, dt));
  }
  frame(0.016); // one frame now, so the scene exists where requestAnimationFrame is throttled
  if (reducedMotion) {
    // A still picture: a fact in flight and a receipt leaving the seal, frozen.
    spawnFact();
    for (let i = 0; i < 20; i++) frame(0.04);
    receipt(beacons[3]);
    frame(0.3);
  } else {
    loop();
  }

  // ── live data ──
  fetchLive().then((held) => {
    live.held = held;
    if (held) {
      for (const b of beacons) {
        if (!b.src.list) continue;
        b.lit = Boolean(held[b.src.id]);
        b.hash = held[b.src.id] ? held[b.src.id].sha256 : null;
      }
    }
    onLive(held);
    if (reducedMotion) frame(0);
  });

  const handle = {
    /** Advance the scene by hand — for environments where requestAnimationFrame never fires. */
    step(frames = 60, dt = 1 / 60) { for (let i = 0; i < frames; i++) frame(dt); },
    get live() { return live.held; },
    stats() { return { flights: flights.length, receipts: receipts.length, beacons: beacons.filter((b) => b.lit).length }; },
    dispose() {
      running = false;
      ro.disconnect();
      io.disconnect();
      composer.dispose();
      renderer.dispose();
    },
  };
  window.__emporion_agora = handle;
  return handle;
}
