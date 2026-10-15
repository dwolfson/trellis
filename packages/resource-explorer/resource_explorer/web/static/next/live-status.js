/** One way to keep a status on screen current: read, show, wait, read again, until the server says it is over.
 *  Backoff: every `fastMs` for the first `fastForMs`, then every `slowMs`. A failed read is not a status, so it is
 *  tried again at the same pace; it never ends the watch. The watch ends only on a terminal answer, on `alive()`
 *  turning false (the pane went away), or on stop(). Time is counted from the delays waited, not a wall clock. */
export const POLL = { fastMs: 2000, fastForMs: 60000, slowMs: 10000 };

export function followUntil({ read, isDone, onUpdate = () => {}, alive = () => true, cfg = POLL, fixedMs = null }) {
  let stopped = false; let timer = null; let waited = 0;
  const step = () => (fixedMs != null ? fixedMs : (waited < cfg.fastForMs ? cfg.fastMs : cfg.slowMs));
  const arm = () => {
    if (stopped) return;
    const ms = step();
    timer = globalThis.setTimeout(async () => {
      timer = null;
      waited += ms;
      if (stopped || !alive()) return;
      let res; let ok = true;
      try { res = await read(); } catch (_) { ok = false; }
      if (stopped || !alive()) return;
      if (ok) { onUpdate(res); if (isDone(res)) { stopped = true; return; } }
      arm();
    }, ms);
  };
  arm();
  return { stop() { stopped = true; if (timer != null) globalThis.clearTimeout(timer); timer = null; } };
}

/** The activity-entry statuses that mean "still going". Anything else is the end. */
export const ACTIVITY_LIVE = new Set(['running', 'queued', 'pending', 'claimed', 'submitted']);
