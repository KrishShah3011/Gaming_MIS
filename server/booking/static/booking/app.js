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
