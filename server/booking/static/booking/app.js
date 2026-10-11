// Shared helpers for the customer site. Motion (window.Motion) is optional and off under reduced motion.
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const motion = () => (!reducedMotion && window.Motion) || null;

// Paise → "₹1,250" or "₹24.75".
function rupees(paise) {
  return "₹" + (Math.round(paise) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

// Roll a number element to a new value.
function rollTo(el, value, format) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = value;
  const m = motion();
  if (!m || from === value) { el.textContent = format(value); return; }
  m.animate(from, value, { duration: 0.35, ease: "easeOut", onUpdate: (v) => { el.textContent = format(v); } });
}

// A quick spring on something the user just tapped.
function pop(el) {
  const m = motion();
  if (m) m.animate(el, { scale: [0.92, 1] }, { type: "spring", stiffness: 500, damping: 18 });
}

// Glitch headlines draw two offset copies of their text (see .glitch in theme.css).
for (const el of document.querySelectorAll(".glitch")) el.dataset.text = el.innerText;

// Decode effect for section titles: random glyphs settle into the real text, left to right.
function scramble(el) {
  const text = el.textContent, glyphs = "#%&*+<>/\[]{}=01ABCDEFX";
  el.setAttribute("aria-label", text);
  let frame = 0;
  const frames = 28;
  const tick = () => {
    const settled = (frame / frames) * text.length;
    el.textContent = [...text].map((c, i) => (c === " " || i < settled ? c : glyphs[(Math.random() * glyphs.length) | 0])).join("");
    if (++frame <= frames) requestAnimationFrame(tick);
    else { el.textContent = text; el.removeAttribute("aria-label"); }
  };
  tick();
}

// Reveal blocks as they scroll into view, once each.
const revealer = "IntersectionObserver" in window && new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    entry.target.classList.add("is-in");
    if (!reducedMotion && entry.target.matches("[data-scramble]")) scramble(entry.target);
    revealer.unobserve(entry.target);
  }
}, { rootMargin: "0px 0px -8% 0px" });
for (const el of document.querySelectorAll("[data-reveal], [data-scramble]")) {
  if (revealer) revealer.observe(el); else el.classList.add("is-in");
}

// Cursor spotlight on .spot cards; delegated so tiles swapped in by fetch still get it.
document.addEventListener("pointermove", (event) => {
  const el = event.target.closest?.(".spot");
  if (!el) return;
  const box = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${event.clientX - box.left}px`);
  el.style.setProperty("--my", `${event.clientY - box.top}px`);
}, { passive: true });
