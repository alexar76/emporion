/** Mounts the agora behind the hero and tells the reader whether it shows the live service. */
import { mountAgora } from "./agora.js";

const canvas = document.getElementById("agora");
const badge = document.getElementById("scene-badge");
const label = badge && badge.querySelector("[data-i18n]");
const detail = document.getElementById("scene-detail");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function onLive(held) {
  if (!badge || !label || !detail) return;
  badge.hidden = false;
  const names = held ? Object.keys(held) : [];
  badge.classList.toggle("live", names.length > 0);
  label.setAttribute("data-i18n", names.length ? "scene_live" : "scene_sim");
  // Entry counts come from the service; inserted as text, never as HTML.
  detail.textContent = names.length
    ? " · " + names.map((n) => `${n} ${held[n].entries.toLocaleString("en-US")}`).join(" · ")
    : "";
  if (typeof window.symmartysApplyLang === "function") window.symmartysApplyLang();
}

// After the page has loaded and painted: creating the WebGL context and compiling the glow's
// shaders takes the main thread for a moment, and the text should never wait for a picture.
// Until then — and for good without WebGL — the CSS coin stands in.
function start() {
  const scene = canvas ? mountAgora(canvas, { reducedMotion, onLive }) : null;
  // No WebGL, no picture: the badge describes the picture, so it stays hidden too.
  if (scene) document.body.classList.add("has-3d");
}
if (document.readyState === "complete") setTimeout(start, 0);
else window.addEventListener("load", () => setTimeout(start, 0), { once: true });
