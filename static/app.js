/* Lifeboat UI — vanilla JS, no build step. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- helpers
  async function api(path, opts = {}) {
    const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
    if (init.method !== "GET") { init.headers["X-Lifeboat"] = "1"; init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body || {}); }
    const r = await fetch(path, init);
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json() : await r.text();
    if (!r.ok && !(opts.allow || []).includes(r.status)) throw new Error((data && data.error) || `HTTP ${r.status}`);
    return data;
  }
  const B = (n) => {
    if (n == null || isNaN(n)) return "—";
    const u = ["B", "KB", "MB", "GB", "TB", "PB"]; let i = 0; n = Number(n);
    while (Math.abs(n) >= 1000 && i < u.length - 1) { n /= 1000; i++; }
    return i ? `${n.toFixed(n < 10 ? 2 : n < 100 ? 1 : 0)} ${u[i]}` : `${n} B`;
  };
  const N = (n) => (n == null ? "—" : Number(n).toLocaleString());
  const dur = (s) => {
    if (s == null || isNaN(s)) return "—";
    s = Math.max(0, Math.round(s));
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
    return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  };
  const toDate = (t) => (t == null ? null : typeof t === "number" ? new Date(t * 1000) : new Date(t));
  const rel = (t) => {
    const d = toDate(t); if (!d) return "never";
    const s = (Date.now() - d.getTime()) / 1000, a = Math.abs(s), fut = s < 0;
    const f = a < 60 ? "just now" : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
    return f === "just now" ? f : fut ? `in ${f}` : `${f} ago`;
  };
  const abs = (t, opts) => { const d = toDate(t); return d ? d.toLocaleString(undefined, opts || { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—"; };
  const day = (t) => { const d = toDate(t); return d ? d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "—"; };
  const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const KIND = { backup: "Backup", forget: "Retention", prune: "Prune", check: "Integrity check", verify: "Verification", restore: "Restore" };
  const RSTAT = { success: ["s-ok", "Success"], warning: ["s-warn", "Warnings"], failed: ["s-bad", "Failed"], cancelled: ["s-idle", "Cancelled"], running: ["s-run", "Running"] };
  const VSTAT = {
    verified: ["s-ok", "Verified", "In B2, decrypts, matches the run that created it."],
    retired: ["s-idle", "Retired", "Removed by your retention policy, as logged."],
    acknowledged: ["s-info", "Acknowledged", "Made outside this Lifeboat; you marked it as expected."],
    b2_only: ["s-warn", "Not in local log", "In B2 but no local run created it (another machine, or the log was reset)."],
    should_be_removed: ["s-warn", "Should be gone", "Retention removed it, yet it's still visible in B2."],
    mismatch: ["s-bad", "Mismatch", "In B2, but a cross-check against the local log failed."],
    missing: ["s-bad", "Missing", "A logged backup whose snapshot is absent from B2."],
    deleted: ["s-bad", "Deleted", "Hidden in B2 without a retention run; the old version is still held by B2 lifecycle."],
    identity_changed: ["s-bad", "Replaced", "The B2 object changed after it was first recorded."],
    unreadable: ["s-bad", "Unreadable", "In B2 but restic can't decrypt or parse it."],
    local_only: ["s-idle", "Local only", "Known locally, never seen in B2."],
    unknown: ["s-idle", "Unknown", "B2 couldn't be reached."],
  };
  const mark = (k) => `<span class="s-${k}" aria-hidden="true">${{ ok: "✓", warn: "!", bad: "✗" }[k]}</span>`;
  const pill = (cls, label) => `<span class="pill ${cls}">${esc(label)}</span>`;
  const ICON = {
    play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
    stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 4v12M6 11l6 6 6-6M5 20h14"/></svg>',
    folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    chev: '<svg class="vchev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
    right: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
    restore: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.7L20 8M20 3v5h-5"/></svg>',
  };

  let toastT;
  function toast(msg, bad) {
    const t = $("#toast"); t.textContent = msg; t.classList.toggle("bad", !!bad); t.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 4200);
  }
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("busy"); btn.disabled = true; }
    try { return await fn(); } catch (e) { toast(e.message, true); } finally { if (btn) { btn.classList.remove("busy"); btn.disabled = false; } }
  }
  function dialog(html, onOk, okLabel = "Confirm", danger = false) {
    const d = $("#dlg");
    d.innerHTML = `<form method="dialog">${html}<div class="actions"><button class="btn ghost" value="cancel">Cancel</button><button class="btn ${danger ? "danger" : "primary"}" value="ok">${esc(okLabel)}</button></div></form>`;
    d.showModal();
    d.onclose = () => { if (d.returnValue === "ok") onOk(d); };
  }

  // ---------------------------------------------------------------- state
  const S = { ov: null, live: null, versions: null, filter: "all", runs: null, runFilter: "", openRun: null, storage: null, verifs: null, folders: {}, sel: null, view: null };

  // ---------------------------------------------------------------- router
  const VIEWS = ["overview", "versions", "activity", "verify", "settings"];
  function route() {
    const v = (location.hash.slice(1) || "overview").split("/")[0];
    const view = VIEWS.includes(v) ? v : "overview";
    S.view = view;
    $$(".nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.view === view ? "page" : "false"));
    $$(".view").forEach((el) => el.classList.toggle("active", el.id === `view-${view}`));
    ({ overview: loadOverview, versions: loadVersions, activity: loadActivity, verify: loadVerify, settings: loadSettings })[view]();
    window.scrollTo({ top: 0, behavior: RM ? "auto" : "smooth" });
  }
  addEventListener("hashchange", route);

  // ---------------------------------------------------------------- live (SSE)
  // Live updates. A browser EventSource gives up for good when it gets an HTTP error (e.g. a 502 from Caddy or
  // Tailscale while the container restarts), so we watch it ourselves and reconnect; the server pings every 15 s.
  let es, lastJob = null, lastBeat = 0, retryT = 0;
  function onState(st) {
    S.live = st;
    const job = st.job;
    $("#liveDot").classList.add("live");
    $("#liveText").textContent = job ? `${KIND[job.kind] || job.kind}: ${job.phase || "running"}` : st.queue && st.queue.length ? "Starting…" : "Idle · connected";
    if (S.view === "overview") {
      if (!!job !== !!lastJob) loadOverview();   // a job started or ended: redraw hero, buttons and cards
      else renderLive();
    }
    if (lastJob && !job) { // a job just finished: refresh what it may have changed
      setTimeout(() => { if (S.view === "versions") loadVersions(true); if (S.view === "activity") loadActivity(); if (S.view === "verify") loadVerify(); }, 400);
    }
    if (job && S.view === "activity" && (!lastJob || lastJob.run_id !== job.run_id)) loadActivity();
    lastJob = job;
  }
  function connectLive() {
    clearTimeout(retryT);
    if (es) es.close();
    es = new EventSource("/api/events");
    lastBeat = Date.now();
    es.onmessage = (e) => { lastBeat = Date.now(); onState(JSON.parse(e.data)); };
    es.addEventListener("ping", () => { lastBeat = Date.now(); });
    es.onopen = () => { lastBeat = Date.now(); };
    es.onerror = () => {
      $("#liveDot").classList.remove("live"); $("#liveText").textContent = "reconnecting…";
      if (es.readyState === EventSource.CLOSED) retryT = setTimeout(connectLive, 3000);
    };
  }
  setInterval(() => { if (Date.now() - lastBeat > 40000) connectLive(); }, 10000);   // silent stream: reconnect
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - lastBeat > 20000) connectLive(); });

  // After a button press, don't depend on the stream alone: poll briefly until the job shows up.
  async function pollState(tries = 8) {
    for (let i = 0; i < tries; i++) {
      await new Promise((r) => setTimeout(r, i ? 1000 : 300));
      try { const o = await api("/api/overview"); if (o.state.job || i === tries - 1) { onState(o.state); return; } } catch { /* ignore */ }
    }
  }

  async function startJob(kind, extra = {}, btn) {
    await busy(btn, async () => {
      const r = await api("/api/jobs", { body: { kind, ...extra }, allow: [409] });
      toast(r.queued ? `${KIND[kind]} started` : r.error || `${KIND[kind]} is already queued or running`, !r.queued);
      pollState();
    });
  }

  // ---------------------------------------------------------------- overview
  async function loadOverview() {
    try {
      S.ov = await api("/api/overview");
      S.live = S.ov.state;
      renderOverview();
      if (S.ov.configured) api("/api/storage").then((m) => { S.storage = m; renderStorage(); }).catch(() => {});
    } catch (e) { $("#view-overview").innerHTML = `<div class="empty"><h3>Can't reach Lifeboat</h3><p>${esc(e.message)}</p></div>`; }
  }

  function heroCopy() {
    const o = S.ov, v = o.verification, lb = o.last_backup, job = S.live && S.live.job;
    if (!o.configured) return ["Not aboard <em class=\"idle\">yet.</em>", "Connect your Backblaze bucket, set an encryption password and pick folders. Nothing leaves the NAS until you do."];
    if (job && job.kind === "backup") return ["Rowing <em class=\"idle\">out.</em>", "A backup is running right now. Progress, upload speed and the files in flight are below."];
    if (lb && lb.status === "failed") return ["Last backup <em class=\"bad\">failed.</em>", lb.error || "Open Activity for the log."];
    if (v && !v.ok) return ["Something's <em class=\"bad\">off.</em>", (v.issues.find((i) => i.level === "error") || v.issues[0] || {}).text || "The last verification found a problem."];
    if (!o.last_good_backup) return ["Ready to <em class=\"idle\">launch.</em>", "The repository is connected. Run the first backup now or wait for the schedule."];
    if (v && v.issues.length) return ["Aboard, with <em class=\"warn\">notes.</em>", v.issues[0].text];
    return ["Everything's <em>aboard.</em>", `Every version Backblaze holds was listed through its API, decrypted, and matched against the local log.`];
  }

  function renderOverview() {
    const o = S.ov, s = o.settings, el = $("#view-overview");
    $("#hostline").textContent = `${o.host} → B2${s.b2_bucket ? " · " + s.b2_bucket : ""}`;
    $("#resticVer").textContent = (o.restic || "").split(" compiled")[0];
    const issues = o.verification ? o.verification.issues.filter((i) => i.level === "error").length : 0;
    const badge = $("#issueBadge"); badge.hidden = !issues; badge.textContent = issues;
    const [title, lede] = heroCopy();
    const lg = o.last_good_backup, job = S.live && S.live.job;
    el.innerHTML = `
      <div class="hero rv" style="--i:0" id="hero">
        <div class="hero-grid">
          <div>
            <p class="eyebrow">Offsite backup · ${esc(o.host)} → Backblaze B2</p>
            <h1 class="display" id="h-overview">${title}</h1>
            <p class="lede">${esc(lede)}</p>
            <div class="hero-actions">
              ${o.configured ? `<button class="btn primary magnetic" id="btnBackup" ${job || (S.live && S.live.queue && S.live.queue.length) ? "disabled" : ""}>${ICON.play}Back up now</button>
              <button class="btn ghost" id="btnVerify">${ICON.shield}Verify against B2</button>
              ${job ? `<button class="btn ghost danger" id="btnCancel">${ICON.stop}Cancel ${esc(KIND[job.kind] || "job")}</button>` : ""}`
              : `<a class="btn primary magnetic" href="#settings">Set up Lifeboat</a>`}
            </div>
          </div>
          <div class="hero-side">
            <div class="stamp"><span>Last good backup</span><b>${lg ? `${esc(rel(lg.finished_at))} · ${esc(abs(lg.finished_at))}` : "none yet"}</b></div>
            <div class="stamp"><span>Next scheduled</span><b>${o.next_run ? `${esc(day(o.next_run))}, ${esc(abs(o.next_run, { hour: "numeric", minute: "2-digit" }))}` : s.schedule_enabled ? "after setup" : "schedule off"}</b></div>
            <div class="stamp"><span>Last verified</span><b>${o.verification ? `${esc(rel(o.verification.at))} · ${o.verification.ok ? "clean" : "problems found"}` : "never"}</b></div>
          </div>
        </div>
        <div class="waves" aria-hidden="true">
          <svg class="wl" data-depth="10" viewBox="0 0 1200 150" preserveAspectRatio="none"><path class="w1" d="M0 70 C150 40 300 100 450 70 S750 40 900 70 S1150 100 1200 70 V150 H0Z"/></svg>
          <svg class="wl" data-depth="22" viewBox="0 0 1200 150" preserveAspectRatio="none"><path class="w2" d="M0 95 C200 70 350 120 600 95 S950 70 1200 95 V150 H0Z"/></svg>
          <svg class="wl" data-depth="36" viewBox="0 0 1200 150" preserveAspectRatio="none"><path class="w3" d="M0 120 C250 100 400 140 650 118 S1000 104 1200 122 V150 H0Z"/></svg>
        </div>
        <div class="waterline" id="waterline" aria-hidden="true"></div>
      </div>

      <div class="card rv" style="--i:1; margin-bottom: var(--s4)" id="liveCard" aria-live="off"></div>

      <div class="bento">
        <div class="card lift span-2 half rv" style="--i:2" id="cStorage"><span class="k">Stored in B2</span><span class="v">…</span><span class="foot">Measured by the B2 API</span></div>
        <div class="card lift span-2 half rv" style="--i:3"><span class="k">Versions</span>
          <span class="v">${o.verification ? N(o.verification.counts.verified || 0) : "—"}<small> verified</small></span>
          <span class="foot">${o.verification ? Object.entries(o.verification.counts).filter(([k]) => k !== "verified").map(([k, n]) => `${n} ${esc((VSTAT[k] || [0, k])[1].toLowerCase())}`).join(" · ") || "no exceptions" : "verify to populate"} · <a href="#versions">open</a></span></div>
        <div class="card lift span-2 rv" style="--i:4"><span class="k">Protected folders</span>
          <span class="v">${N(s.sources.length)}</span>
          <span class="foot mono">${s.sources.length ? s.sources.map((p) => esc(p.replace(/^\/source\//, ""))).join(" · ") : `<a href="#settings">choose folders</a>`}</span></div>
        ${lastRunCard(o.last_backup)}
      </div>`;
    $("#btnBackup")?.addEventListener("click", (e) => startJob("backup", {}, e.currentTarget));
    $("#btnVerify")?.addEventListener("click", (e) => startJob("verify", {}, e.currentTarget));
    $("#btnCancel")?.addEventListener("click", (e) => busy(e.currentTarget, async () => { await api("/api/cancel", { body: {} }); toast("Cancel requested"); }));
    renderLive(); renderStorage(); waves.bind(); magnet.bind();
  }

  function lastRunCard(r) {
    if (!r) return `<div class="card span-6 rv" style="--i:5"><span class="k">Last backup run</span><span class="foot">No backups yet.</span></div>`;
    const sm = r.summary || {}, [cls, lbl] = RSTAT[r.status] || ["s-idle", r.status];
    return `<div class="card span-6 rv" style="--i:5"><div class="inline" style="justify-content:space-between"><span class="k">Last backup run · #${r.id}</span>${pill(cls, lbl)}</div>
      <div class="live-stats">
        <div><span>Started</span><b>${esc(abs(r.started_at))}</b></div>
        <div><span>Duration</span><b>${esc(dur((r.finished_at || Date.now() / 1000) - r.started_at))}</b></div>
        <div><span>Uploaded (packed)</span><b>${B(sm.data_added_packed)}</b></div>
        <div><span>New · changed files</span><b>${N(sm.files_new)} · ${N(sm.files_changed)}</b></div>
      </div>${r.error ? `<p class="foot s-warn">${esc(r.error)}</p>` : ""}</div>`;
  }

  function renderStorage() {
    const el = $("#cStorage"); if (!el) return;
    const m = S.storage;
    if (!m) return;
    el.innerHTML = `<span class="k">Stored in B2</span><span class="v">${B(m.bytes)}</span>
      <span class="foot">${N(m.objects)} objects${m.hidden_bytes ? ` · ${B(m.hidden_bytes)} in deleted versions` : ""} · ≈ $${(m.monthly_cost ?? 0).toFixed(2)}/mo</span>`;
  }

  function renderLive() {
    const el = $("#liveCard"); if (!el || !S.ov) return;
    const job = S.live && S.live.job, q = (S.live && S.live.queue) || [];
    const wl = $("#waterline");
    if (!job) {
      if (wl) wl.style.setProperty("--p", 0);
      const nx = S.ov.next_run;
      el.innerHTML = `<div class="inline" style="justify-content:space-between"><span class="k">Upload monitor</span>${pill("s-idle", "Idle")}</div>
        <p class="idle-note" style="margin:0">Nothing in flight. ${nx ? `Next backup ${esc(day(nx))} at ${esc(abs(nx, { hour: "numeric", minute: "2-digit" }))}.` : ""} ${q.length ? `Queued: ${q.map((j) => esc(KIND[j.kind])).join(", ")}.` : ""}</p>`;
      return;
    }
    const p = job.progress || {}, pct = Math.min(100, (p.percent_done || 0) * 100);
    if (wl) wl.style.setProperty("--p", job.kind === "backup" ? pct.toFixed(1) : 0);
    const C = 2 * Math.PI * 64, done = p.bytes_done ?? p.bytes_restored, files = p.files_done ?? p.files_restored;
    if (!el.querySelector(".live")) {
      el.innerHTML = `<div class="inline" style="justify-content:space-between"><span class="k" id="liveTitle"></span><span id="livePill"></span></div>
        <div class="live">
          <div class="ring" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-label="Job progress" id="ring">
            <svg viewBox="0 0 148 148" aria-hidden="true"><circle class="track" cx="74" cy="74" r="64" fill="none" stroke-width="8"/><circle class="bar" cx="74" cy="74" r="64" fill="none" stroke-width="8" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
            <b id="ringPct">0<small>%</small></b>
          </div>
          <div style="display:grid; gap: var(--s4); min-width:0">
            <div class="live-stats" id="liveStats"></div>
            <canvas class="spark" id="spark" aria-hidden="true"></canvas>
            <ul class="current-files" id="curFiles"></ul>
          </div>
        </div>`;
    }
    $("#liveTitle").textContent = `${job.title || KIND[job.kind]} · ${job.phase || ""}`;
    $("#livePill").innerHTML = pill("s-run", `Run #${job.run_id}`);
    $("#ring").setAttribute("aria-valuenow", Math.round(pct));
    $("#ring .bar").style.strokeDashoffset = C * (1 - pct / 100);
    $("#ringPct").innerHTML = `${p.percent_done == null ? "—" : Math.floor(pct)}<small>%</small>`;
    $("#liveStats").innerHTML = `
      <div><span>Upload rate (network)</span><b>${B(job.tx_rate)}/s</b></div>
      <div><span>${job.kind === "restore" ? "Restored" : "Processed"}</span><b>${B(done)} / ${B(p.total_bytes)}</b></div>
      <div><span>Files</span><b>${N(files)} / ${N(p.total_files)}</b></div>
      <div><span>${p.seconds_remaining ? "Time left" : "Elapsed"}</span><b>${p.seconds_remaining ? dur(p.seconds_remaining) : dur(Date.now() / 1000 - job.started_at)}</b></div>`;
    $("#curFiles").innerHTML = (p.current_files || []).slice(0, 2).map((f) => `<li title="${esc(f)}">↑ ${esc(f)}</li>`).join("");
    drawSpark($("#spark"), job.tx_hist || []);
  }

  function drawSpark(cv, data) {
    if (!cv) return;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
    const pts = data.slice(-120), max = Math.max(1, ...pts);
    if (pts.length < 2) return;
    const x = (i) => (i / (pts.length - 1)) * w, y = (v) => h - 4 - (v / max) * (h - 12);
    const grad = g.createLinearGradient(0, 0, 0, h); grad.addColorStop(0, "rgba(255,122,69,.35)"); grad.addColorStop(1, "rgba(255,122,69,0)");
    g.beginPath(); g.moveTo(0, h); pts.forEach((v, i) => g.lineTo(x(i), y(v))); g.lineTo(w, h); g.closePath(); g.fillStyle = grad; g.fill();
    g.beginPath(); pts.forEach((v, i) => (i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)))); g.strokeStyle = "#ff7a45"; g.lineWidth = 1.5; g.stroke();
    g.fillStyle = "#9bb1b6"; g.font = "11px 'IBM Plex Mono', monospace"; g.fillText(`peak ${B(max)}/s`, 4, 12);
  }

  // ambient + pointer parallax for the hero waves (decorative)
  const waves = {
    px: 0, raf: 0, t0: performance.now(),
    bind() {
      if (RM) return;
      const hero = $("#hero"); if (!hero) return;
      hero.onpointermove = (e) => { const r = hero.getBoundingClientRect(); this.px = (e.clientX - r.left) / r.width - 0.5; };
      hero.onpointerleave = () => { this.px = 0; };
      if (!this.raf) this.loop();
    },
    loop() {
      this.raf = requestAnimationFrame(() => {
        this.raf = 0;
        const layers = $$(".waves .wl"); if (!layers.length || document.hidden) { if (layers.length) setTimeout(() => this.loop(), 500); return; }
        const t = (performance.now() - this.t0) / 1000;
        layers.forEach((l, i) => {
          const d = +l.dataset.depth, drift = Math.sin(t * (0.25 + i * 0.07) + i) * d * 0.6;
          l.style.transform = `translate3d(${-40 + drift - this.px * d}px, 0, 0)`;
        });
        this.loop();
      });
    },
  };

  // magnetic pull on primary buttons
  const magnet = {
    bind() {
      if (RM || matchMedia("(pointer: coarse)").matches) return;
      $$(".magnetic").forEach((b) => {
        let raf = 0, mx = 0, my = 0;
        b.onpointermove = (e) => {
          const r = b.getBoundingClientRect();
          mx = (e.clientX - r.left - r.width / 2) * 0.18; my = (e.clientY - r.top - r.height / 2) * 0.28;
          if (!raf) raf = requestAnimationFrame(() => { raf = 0; b.style.setProperty("--mx", `${mx}px`); b.style.setProperty("--my", `${my}px`); });
        };
        b.onpointerleave = () => { b.style.setProperty("--mx", "0px"); b.style.setProperty("--my", "0px"); };
      });
    },
  };

  // ---------------------------------------------------------------- versions
  async function loadVersions(refresh) {
    const el = $("#view-versions");
    if (!S.versions) el.innerHTML = `<div class="section-head"><div><p class="eyebrow">Source: Backblaze B2 API</p><h2 id="h-versions">Versions</h2></div></div><div class="empty">Listing the bucket…</div>`;
    try {
      S.ov = S.ov || (await api("/api/overview"));
      if (!S.ov.configured) { el.innerHTML = notReady("versions"); return; }
      S.versions = await api(`/api/versions${refresh ? "?refresh=1" : ""}`);
      renderVersions();
    } catch (e) { el.innerHTML = `<div class="empty"><h3>Couldn't list versions</h3><p>${esc(e.message)}</p></div>`; }
  }
  const notReady = (what) => `<div class="empty rv" style="--i:0"><h3>Lifeboat isn't connected yet</h3><p>Finish the setup steps before ${what} can be listed.</p><p><a class="btn primary" href="#settings">Open settings</a></p></div>`;

  function vGroup(st) { return st === "verified" || st === "acknowledged" ? "ok" : st === "retired" ? "retired" : "attn"; }

  function renderVersions() {
    const d = S.versions, el = $("#view-versions");
    const rows = d.snapshots.filter((r) => S.filter === "all" || vGroup(r.status) === S.filter);
    const cnt = (g) => d.snapshots.filter((r) => vGroup(r.status) === g).length;
    el.innerHTML = `
      <div class="section-head rv" style="--i:0">
        <div><p class="eyebrow">Source: Backblaze B2 API · cross-checked with the local log</p>
          <h2 id="h-versions">Versions</h2>
          <p class="lede">Each row is a snapshot object found in the bucket (deleted ones included while B2 still holds them), decrypted by restic, then compared with the run that created it.</p></div>
        <button class="btn ghost" id="vRefresh">${ICON.refresh}Re-list from B2</button>
      </div>
      <div class="filters rv" style="--i:1; margin-bottom: var(--s5)" role="group" aria-label="Filter versions">
        ${[["all", `All ${d.snapshots.length}`], ["ok", `Verified ${cnt("ok")}`], ["attn", `Needs attention ${cnt("attn")}`], ["retired", `Retired ${cnt("retired")}`]]
          .map(([k, l]) => `<button class="chip" data-f="${k}" aria-pressed="${S.filter === k}">${esc(l)}</button>`).join("")}
      </div>
      <div class="vlist">${rows.length ? rows.map((r, i) => vRow(r, i)).join("") : `<div class="empty"><h3>No versions here</h3><p>${d.snapshots.length ? "Try another filter." : "Run the first backup to create one."}</p></div>`}</div>
      <p class="faint mono rv" style="--i:3; margin-top: var(--s5); font-size:12px">Listed ${esc(abs(d.at))} · ${d.b2_calls ?? "?"} B2 API calls this session</p>`;
    $("#vRefresh").onclick = (e) => busy(e.currentTarget, () => loadVersions(true));
    $$(".chip[data-f]", el).forEach((b) => (b.onclick = () => { S.filter = b.dataset.f; renderVersions(); }));
    $$(".vrow", el).forEach(bindVRow);
  }

  function vRow(r, i) {
    const [cls, lbl] = VSTAT[r.status] || ["s-idle", r.status], sm = r.summary || {};
    const t = r.time || (r.b2 && r.b2.upload_ts && r.b2.upload_ts / 1000);
    return `<article class="vrow rv" style="--i:${Math.min(i + 2, 12)}" data-id="${esc(r.id)}">
      <button class="vhead" aria-expanded="false" aria-controls="vb-${esc(r.short)}">
        <span class="vdate"><b>${esc(day(t))}</b><span>${esc(abs(t, { hour: "numeric", minute: "2-digit" }))} · ${esc(r.short)}</span></span>
        <span class="vmeta">${sm.total_bytes_processed != null ? `${B(sm.total_bytes_processed)} protected · ${B(sm.data_added_packed)} new` : "metadata unavailable"}${r.hostname ? ` · ${esc(r.hostname)}` : ""}
          <span class="paths">${esc((r.paths || []).join("  "))}</span></span>
        <span class="vstat">${pill(cls, lbl)}</span>
        ${ICON.chev}
      </button>
      <div class="vbody" id="vb-${esc(r.short)}"><div></div></div>
    </article>`;
  }

  function vDetail(r) {
    const sm = r.summary || {}, b = r.b2, run = r.run, [, , explain] = VSTAT[r.status] || [];
    const live = b && b.visible && !["unreadable", "identity_changed"].includes(r.status);
    return `<div class="vinner">
      <div>
        <p class="muted" style="margin-top:0">${esc(explain || "")}</p>
        <ul class="checks">${r.checks.map((c) => `<li><span class="ic ${c.ok ? "ok" : "no"}" aria-hidden="true">${c.ok ? "✓" : "!"}</span><span>${esc(c.name)}<span class="sr-only">: ${c.ok ? "passed" : "failed"}</span>${c.detail ? `<small>${esc(c.detail)}</small>` : ""}</span></li>`).join("")}</ul>
        <div class="actions">
          ${live ? `<button class="btn small primary" data-act="browse">${ICON.folder}Browse &amp; download</button>
          <a class="btn small" href="/api/download?snapshot=${esc(r.id)}&path=/&type=tar" data-act="tar">${ICON.down}Whole version (.tar)</a>
          ${S.ov && S.ov.restore_root ? `<button class="btn small" data-act="restore">${ICON.restore}Restore to NAS…</button>` : ""}` : ""}
          ${r.status === "b2_only" ? `<button class="btn small" data-act="ack">Mark as expected</button>` : ""}
        </div>
      </div>
      <dl class="kv">
        <dt>Snapshot</dt><dd>${esc(r.id)}</dd>
        <dt>Backup window</dt><dd>${sm.backup_start ? `${esc(abs(sm.backup_start, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }))} → ${esc(abs(sm.backup_end, { hour: "numeric", minute: "2-digit", second: "2-digit" }))}` : "—"}</dd>
        <dt>Files</dt><dd>${N(sm.total_files_processed)} total · ${N(sm.files_new)} new · ${N(sm.files_changed)} changed</dd>
        <dt>Data</dt><dd>${B(sm.total_bytes_processed)} protected · ${B(sm.data_added_packed)} uploaded</dd>
        <dt>B2 object</dt><dd>${b ? `${b.visible ? "visible" : "hidden (deleted)"} · ${B(b.size)}` : "not in bucket"}</dd>
        ${b ? `<dt>B2 uploaded</dt><dd>${esc(abs(b.upload_ts / 1000, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }))}</dd>
        <dt>B2 file id</dt><dd>…${esc((b.file_id || "").slice(-24))}</dd><dt>B2 sha1</dt><dd>${esc(b.sha1 || "—")}</dd>` : ""}
        <dt>Local log</dt><dd>${run ? `run #${run.id} · ${esc(run.trigger)} · ${esc(abs(run.started_at))} → ${esc(abs(run.finished_at, { hour: "numeric", minute: "2-digit" }))}` : r.ledger ? `first seen in B2 ${esc(abs(r.ledger.first_seen))}` : "no record"}</dd>
        ${r.ledger && r.ledger.removed_at ? `<dt>Retired</dt><dd>${esc(abs(r.ledger.removed_at))} by run #${r.ledger.removed_by_run}</dd>` : ""}
        <dt>Tree</dt><dd>${esc((r.tree || "—").slice(0, 16))}…</dd>
      </dl>
    </div>`;
  }

  function bindVRow(row) {
    const head = $(".vhead", row), r = S.versions.snapshots.find((x) => x.id === row.dataset.id);
    head.onclick = () => {
      const open = !row.classList.contains("open");
      if (open && !row.dataset.filled) { $(".vbody > div", row).innerHTML = vDetail(r); row.dataset.filled = 1; bindDetail(row, r); }
      row.classList.toggle("open", open); head.setAttribute("aria-expanded", open);
    };
  }
  function bindDetail(row, r) {
    $('[data-act="browse"]', row)?.addEventListener("click", () => browser.open(r));
    $('[data-act="restore"]', row)?.addEventListener("click", () => restoreDialog(r, (r.paths || []).slice()));
    $('[data-act="ack"]', row)?.addEventListener("click", (e) => busy(e.currentTarget, async () => { await api("/api/ack", { body: { snapshot: r.id } }); toast("Marked as expected"); loadVersions(true); }));
    $('[data-act="tar"]', row)?.addEventListener("click", (e) => {
      e.preventDefault();
      const size = (r.summary || {}).total_bytes_processed;
      dialog(`<h3>Download the whole version?</h3><p class="muted">This streams ${B(size)} from B2 through the NAS to this device as one .tar file. B2 includes free downloads up to 3× your stored data each month. For large restores, <b>Restore to NAS</b> is faster and safer.</p>`,
        () => (location.href = e.currentTarget.href), "Download .tar");
    });
  }

  function restoreDialog(r, paths) {
    if (!S.ov.restore_root) return toast("No restore folder is mounted", true);
    const name = `Lifeboat restore ${new Date().toISOString().slice(0, 10)} ${r.short}`;
    dialog(`<h3>Restore to the NAS</h3>
      <p class="muted">Files are written into a new folder under <code>${esc(S.ov.restore_root)}</code>. Nothing existing is overwritten.</p>
      <div class="field"><label for="rName">Folder name</label><input id="rName" value="${esc(name)}"></div>
      <p class="mono faint" style="font-size:12px">${paths.length ? paths.map(esc).join("<br>") : "Entire version"}</p>`,
      (d) => startJob("restore", { snapshot: r.id, paths, target_name: $("#rName", d).value }), "Start restore");
  }

  // ---------------------------------------------------------------- browse drawer
  const browser = {
    snap: null, path: "/", lastFocus: null,
    open(r) {
      this.snap = r; this.lastFocus = document.activeElement;
      $("#drawerTitle").textContent = `${day(r.time)} · ${abs(r.time, { hour: "numeric", minute: "2-digit" })}`;
      $("#drawerEyebrow").textContent = `Browse version ${r.short}`;
      $("#drawer").classList.add("open"); $("#scrim").classList.add("open"); $("#drawer").focus();
      const roots = r.paths || [];
      this.go(roots.length === 1 ? roots[0] : commonDir(roots));
    },
    close() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); this.lastFocus?.focus(); },
    async go(path) {
      this.path = path || "/";
      const parts = this.path.split("/").filter(Boolean);
      $("#crumbs").innerHTML = `<button data-p="/">/</button>` + parts.map((p, i) => `<span>›</span><button data-p="/${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("");
      $$("#crumbs button").forEach((b) => (b.onclick = () => this.go(b.dataset.p)));
      const dl = `/api/download?snapshot=${encodeURIComponent(this.snap.id)}&path=${encodeURIComponent(this.path)}`;
      $("#drawerActions").innerHTML = `<a class="btn small primary" href="${dl}&type=zip">${ICON.down}Download folder (.zip)</a>
        ${S.ov && S.ov.restore_root ? `<button class="btn small" id="dRestore">${ICON.restore}Restore folder to NAS…</button>` : ""}`;
      $("#dRestore")?.addEventListener("click", () => restoreDialog(this.snap, [this.path]));
      const body = $("#drawerBody");
      body.innerHTML = `<p class="muted">Reading the folder from B2…</p>`;
      try {
        const items = await api(`/api/browse?snapshot=${encodeURIComponent(this.snap.id)}&path=${encodeURIComponent(this.path)}`);
        body.innerHTML = items.length ? `<ul class="entries">${items.map((it) => `<li class="entry">
            ${it.type === "dir" ? ICON.folder : ICON.file}
            ${it.type === "dir" ? `<button class="nm" data-p="${esc(it.path)}">${esc(it.name)}</button>` : `<span class="nm" title="${esc(it.name)}">${esc(it.name)}</span>`}
            <span class="sz">${it.type === "dir" ? "" : B(it.size)} ${esc(it.mtime ? abs(it.mtime, { year: "numeric", month: "short", day: "numeric" }) : "")}</span>
            <a class="iconbtn" href="/api/download?snapshot=${encodeURIComponent(this.snap.id)}&path=${encodeURIComponent(it.path)}${it.type === "dir" ? "&type=zip" : ""}" aria-label="Download ${esc(it.name)}${it.type === "dir" ? " as zip" : ""}">${ICON.down}</a>
          </li>`).join("")}</ul>` : `<div class="empty">Empty folder</div>`;
        $$(".nm[data-p]", body).forEach((b) => (b.onclick = () => this.go(b.dataset.p)));
      } catch (e) { body.innerHTML = `<div class="empty"><h3>Couldn't read folder</h3><p>${esc(e.message)}</p></div>`; }
    },
  };
  function commonDir(paths) {
    if (!paths.length) return "/";
    const split = paths.map((p) => p.split("/").filter(Boolean));
    const out = [];
    for (let i = 0; i < split[0].length; i++) { if (split.every((s) => s[i] === split[0][i])) out.push(split[0][i]); else break; }
    return "/" + out.join("/");
  }
  $("#drawerClose").onclick = () => browser.close();
  $("#scrim").onclick = () => browser.close();
  addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#drawer").classList.contains("open")) browser.close(); });

  // ---------------------------------------------------------------- activity
  async function loadActivity() {
    try {
      S.runs = await api(`/api/runs?limit=150${S.runFilter ? `&kind=${S.runFilter}` : ""}`);
      renderActivity();
      if (S.openRun) openRun(S.openRun, true);
    } catch (e) { $("#view-activity").innerHTML = `<div class="empty"><h3>Couldn't load the log</h3><p>${esc(e.message)}</p></div>`; }
  }
  function runResult(r) {
    const sm = r.summary || {};
    if (r.kind === "backup" && r.snapshot_id) return `${B(sm.data_added_packed)} uploaded · ${N(sm.files_new)} new / ${N(sm.files_changed)} changed · <span class="mono">${esc(r.snapshot_id.slice(0, 8))}</span>`;
    if (r.kind === "forget" && r.detail) return `${(r.detail.removed || []).length} version(s) retired`;
    if (r.kind === "check" && r.detail) return `${r.detail.subset_pct}% of data read back`;
    if (r.kind === "restore" && r.detail) return `→ ${esc(r.detail.target || "")}`;
    if (r.kind === "verify" && r.status !== "running") return esc(r.error || (r.status === "success" ? "B2 and the local log agree" : "see log"));
    if (r.kind === "prune" && r.b2_before && r.b2_after) return `B2 ${B(r.b2_before.bytes)} → ${B(r.b2_after.bytes)}`;
    return esc(r.error || "");
  }
  function renderActivity() {
    const el = $("#view-activity");
    el.innerHTML = `
      <div class="section-head rv" style="--i:0"><div><p class="eyebrow">Local log · stored on the NAS</p><h2 id="h-activity">Activity</h2>
        <p class="lede">Every job Lifeboat ran: when it started and finished, what it did, and its full restic output.</p></div></div>
      <div class="filters rv" style="--i:1; margin-bottom: var(--s5)" role="group" aria-label="Filter jobs">
        ${[["", "All"], ["backup", "Backups"], ["forget", "Retention"], ["prune", "Prune"], ["check", "Checks"], ["verify", "Verifications"], ["restore", "Restores"]]
          .map(([k, l]) => `<button class="chip" data-k="${k}" aria-pressed="${S.runFilter === k}">${l}</button>`).join("")}
      </div>
      <div class="rv" style="--i:2; overflow-x:auto">
      ${S.runs.length ? `<table class="runs"><thead><tr><th>Started</th><th>Job</th><th class="hide-sm">Trigger</th><th>Status</th><th class="hide-sm">Duration</th><th class="hide-sm">Result</th></tr></thead><tbody>
        ${S.runs.map((r) => { const [cls, lbl] = RSTAT[r.status] || ["s-idle", r.status]; return `<tr class="run" tabindex="0" data-id="${r.id}" aria-expanded="${S.openRun === r.id}">
          <td class="num">${esc(abs(r.started_at))}</td><td>${esc(KIND[r.kind] || r.kind)} <span class="faint mono">#${r.id}</span></td>
          <td class="hide-sm muted">${esc(r.trigger)}</td><td>${pill(cls, lbl)}</td>
          <td class="num hide-sm">${r.finished_at ? dur(r.finished_at - r.started_at) : "…"}</td><td class="hide-sm muted">${runResult(r)}</td></tr>`; }).join("")}
        </tbody></table>` : `<div class="empty"><h3>No jobs yet</h3><p>Backups, checks and verifications will be logged here.</p></div>`}
      </div>`;
    $$(".chip[data-k]", el).forEach((b) => (b.onclick = () => { S.runFilter = b.dataset.k; S.openRun = null; loadActivity(); }));
    $$("tr.run", el).forEach((tr) => {
      const go = () => openRun(+tr.dataset.id);
      tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
    });
  }
  async function openRun(id, keep) {
    const tr = $(`tr.run[data-id="${id}"]`); if (!tr) return;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("logrow")) { next.remove(); if (!keep) { S.openRun = null; tr.setAttribute("aria-expanded", "false"); return; } }
    $$("tr.logrow").forEach((x) => x.remove());
    S.openRun = id; tr.setAttribute("aria-expanded", "true");
    const r = await api(`/api/runs/${id}`);
    const sm = r.summary || {};
    const row = document.createElement("tr"); row.className = "logrow";
    row.innerHTML = `<td colspan="6"><div style="display:grid; gap: var(--s4); padding: var(--s2) 0 var(--s4)">
      <dl class="kv"><dt>Started</dt><dd>${esc(abs(r.started_at, { dateStyle: "medium", timeStyle: "medium" }))}</dd>
        <dt>Finished</dt><dd>${r.finished_at ? esc(abs(r.finished_at, { dateStyle: "medium", timeStyle: "medium" })) : "running"}</dd>
        ${r.snapshot_id ? `<dt>Snapshot</dt><dd>${esc(r.snapshot_id)}</dd>` : ""}
        ${r.b2_before && r.b2_after ? `<dt>B2 (API)</dt><dd>${N(r.b2_before.objects)} → ${N(r.b2_after.objects)} objects · ${B(r.b2_before.bytes)} → ${B(r.b2_after.bytes)} (${r.b2_after.bytes >= r.b2_before.bytes ? "+" : ""}${B(r.b2_after.bytes - r.b2_before.bytes)})</dd>` : ""}
        ${sm.data_added_packed != null ? `<dt>restic says</dt><dd>${B(sm.data_added_packed)} uploaded · ${B(sm.total_bytes_processed)} scanned in ${dur(sm.total_duration)}</dd>` : ""}
        ${r.error ? `<dt>Note</dt><dd class="s-warn">${esc(r.error)}</dd>` : ""}</dl>
      <pre class="log">${(r.log || []).map((l) => `<span class="l-${esc(l.level)}"><time>${esc(new Date(l.ts * 1000).toLocaleTimeString())}</time>${esc(l.line)}</span>`).join("\n") || "No output recorded."}</pre></div></td>`;
    tr.after(row);
  }

  // ---------------------------------------------------------------- verify
  async function loadVerify() {
    const el = $("#view-verify");
    try {
      S.ov = await api("/api/overview");
      if (!S.ov.configured) { el.innerHTML = notReady("verification"); return; }
      const [v, hist] = await Promise.all([api("/api/versions"), api("/api/verifications")]);
      S.versions = v; S.verifs = hist; renderVerify();
    } catch (e) { el.innerHTML = `<div class="empty"><h3>Couldn't verify</h3><p>${esc(e.message)}</p></div>`; }
  }
  function renderVerify() {
    const v = S.versions, el = $("#view-verify"), s = S.ov.settings;
    const errs = v.issues.filter((i) => i.level === "error"), warns = v.issues.filter((i) => i.level !== "error");
    const title = errs.length ? `${errs.length} <em class="bad">problem${errs.length > 1 ? "s" : ""}.</em>` : warns.length ? `Sound, with <em class="warn">notes.</em>` : `B2 and the log <em>agree.</em>`;
    const hist = (S.verifs || []).slice().reverse();
    el.innerHTML = `
      <div class="verdict">
        <div class="rv" style="--i:0"><p class="eyebrow">Primary: B2 API · secondary: local log</p><h2 class="display" id="h-verify" style="font-size:clamp(36px,5vw,72px)">${title}</h2>
          <p class="lede">${N(v.counts.verified || 0)} version(s) fully verified out of ${N(v.snapshots.length)} known. Checked ${esc(rel(v.at))}.</p>
          <div class="hero-actions">
            <button class="btn primary magnetic" id="vNow">${ICON.shield}Verify now</button>
            <button class="btn ghost" id="cNow">Integrity check (${esc(s.check_subset_pct)}% read)</button>
            <button class="btn ghost" id="cFull">Full read-back…</button>
          </div></div>
        <div class="rv" style="--i:1"><p class="eyebrow">Last ${hist.length} verifications</p>
          <div class="history" aria-label="${hist.filter((h) => h.ok).length} of ${hist.length} clean">${hist.map((h, i) => `<i style="--i:${i}; height:${h.ok ? 100 : 60}%" class="${h.ok ? "" : "bad"}" title="${esc(abs(h.at))}: ${h.ok ? "clean" : h.issues + " issue(s)"}"></i>`).join("")}</div></div>
      </div>
      ${v.issues.length ? `<h3 class="rv" style="--i:2; margin-bottom: var(--s3)">Issues</h3><ul class="issues rv" style="--i:3; margin-bottom: var(--s6)">${v.issues.map((i) => `<li><span>${pill(i.level === "error" ? "s-bad" : "s-warn", i.level)} ${esc(i.text)}</span>${i.snapshot ? `<a href="#versions" class="linkbtn">view</a>` : ""}</li>`).join("")}</ul>` : ""}
      <h3 class="rv" style="--i:4; margin-bottom: var(--s3)">Repository checks</h3>
      <div class="rchecks rv" style="--i:5; margin-bottom: var(--s6)">${v.repo_checks.map((c) => `<div class="rcheck"><span class="ic ${c.ok ? "ok" : "no"}" aria-hidden="true">${c.info ? "i" : c.ok ? "✓" : "!"}</span><div><b>${esc(c.label)}</b><span class="sr-only">: ${c.ok ? "ok" : "attention"}</span><p>${esc(c.detail || "")}</p></div></div>`).join("")}</div>
      ${v.uploads.length ? `<h3 class="rv" style="--i:6; margin-bottom: var(--s3)">Upload accounting</h3>
        <p class="muted rv" style="--i:6">B2's own byte count before and after each backup, compared with what restic reported uploading.</p>
        <div class="rv" style="--i:7; overflow-x:auto; margin-bottom: var(--s6)"><table class="runs"><thead><tr><th>Run</th><th>B2 grew by</th><th>restic uploaded</th><th>New objects</th><th>Match</th></tr></thead><tbody>
        ${v.uploads.map((u) => `<tr><td class="num">#${u.run}</td><td class="num">${B(u.b2_growth)}</td><td class="num">${B(u.restic_added)}</td><td class="num">${N(u.new_objects)}</td><td>${u.ok ? pill("s-ok", "match") : pill("s-warn", "differs")}</td></tr>`).join("")}</tbody></table></div>` : ""}
      <h3 class="rv" style="--i:8; margin-bottom: var(--s3)">What each status means</h3>
      <div class="legend rv" style="--i:9">${Object.values(VSTAT).map(([c, l, d]) => `<div>${pill(c, l)}<br>${esc(d)}</div>`).join("")}</div>`;
    $("#vNow").onclick = (e) => startJob("verify", {}, e.currentTarget);
    $("#cNow").onclick = (e) => startJob("check", { subset: s.check_subset_pct }, e.currentTarget);
    $("#cFull").onclick = () => dialog(`<h3>Read back everything?</h3><p class="muted">restic downloads and decrypts every pack in the repository to prove it's intact. That's ${S.storage ? B(S.storage.bytes) : "your whole backup"} of B2 downloads (free up to 3× stored data per month) and can take hours.</p>`,
      () => startJob("check", { subset: 100 }), "Start full check");
    magnet.bind();
  }

  // ---------------------------------------------------------------- settings
  async function loadSettings() {
    S.ov = await api("/api/overview");
    renderSettings();
  }
  function renderSettings() {
    const o = S.ov, s = o.settings, sec = s.secrets, el = $("#view-settings");
    if (!S.sel) S.sel = new Set(s.sources);
    const r = s.retention || {};
    const b2done = sec.b2_key_id && sec.b2_app_key && s.b2_bucket;
    el.innerHTML = `
      <div class="section-head rv" style="--i:0"><div><p class="eyebrow">Setup</p><h2 id="h-settings">Settings</h2>
        <p class="lede">Secrets are stored only in Lifeboat's data folder on the NAS and are never sent back to the browser.</p></div></div>
      <div class="steps">
        <section class="step rv ${b2done ? "done" : ""}" style="--i:1" aria-labelledby="st1"><span class="step-n">${b2done ? "✓" : "1"}</span><div>
          <h3 id="st1">Backblaze B2</h3>
          <p class="help">Create a <b>private</b> bucket, set its lifecycle to <i>Keep prior versions for 30 days</i>, then create an application key restricted to that bucket with read and write access.</p>
          <div class="fields">
            <div class="field"><label for="kId">Application key ID</label><input id="kId" autocomplete="off" spellcheck="false" placeholder="${sec.b2_key_id ? "saved (" + esc(s.b2_key_id_hint) + ")" : "004…"}"></div>
            <div class="field"><label for="kKey">Application key</label><input id="kKey" type="password" autocomplete="new-password" placeholder="${sec.b2_app_key ? "saved, leave blank to keep" : "K004…"}"></div>
            <div class="field"><label for="bkt">Bucket name</label><input id="bkt" value="${esc(s.b2_bucket)}" spellcheck="false"></div>
            <div class="field"><label for="pfx">Folder inside the bucket</label><input id="pfx" value="${esc(s.b2_prefix)}" spellcheck="false"><span class="hint">Keep it the same forever; it's part of the repository address.</span></div>
          </div>
          <div class="actions"><button class="btn primary" id="saveB2">Save &amp; test connection</button></div>
          <div id="b2res"></div>
        </div></section>

        <section class="step rv ${o.configured ? "done" : ""}" style="--i:2" aria-labelledby="st2"><span class="step-n">${o.configured ? "✓" : "2"}</span><div>
          <h3 id="st2">Encryption password</h3>
          <p class="help">restic encrypts everything on the NAS before upload. Backblaze never sees your files or this password, and <b>no one can recover the backup without it</b>.</p>
          ${o.configured ? `<p>${pill("s-ok", "Connected")} <span class="muted">Repository is ready.</span></p>
            <div class="actions"><a class="btn" href="/api/recovery-kit">${ICON.down}Download recovery kit</a><button class="btn ghost" id="chgRepo">Use a different password…</button></div>`
          : `<div class="fields"><div class="field full"><label for="rpw">Repository password</label><input id="rpw" type="password" autocomplete="new-password" placeholder="${sec.repo_password ? "saved, leave blank to keep" : "Long and random"}"></div></div>
            <div id="genBox"></div>
            <div class="actions"><button class="btn" id="genPw">Generate one</button><button class="btn" id="conRepo">Connect to existing</button><button class="btn primary" id="newRepo">Create new repository</button></div>`}
          <div id="repoRes"></div>
        </div></section>

        <section class="step rv ${s.sources.length ? "done" : ""}" style="--i:3" aria-labelledby="st3"><span class="step-n">${s.sources.length ? "✓" : "3"}</span><div>
          <h3 id="st3">Folders to protect</h3>
          <p class="help">Shares are mounted read-only. Tick folders to include; a ticked folder includes everything inside it.</p>
          <ul class="tree" id="tree" role="tree" aria-label="NAS folders"></ul>
          <div class="selected-list" id="selList"></div>
          <div class="actions"><button class="btn primary" id="saveSrc">Save folders</button><button class="btn ghost" id="sizeSrc">Measure selected sizes</button></div>
        </div></section>

        <section class="step rv" style="--i:4" aria-labelledby="st4"><span class="step-n">4</span><div>
          <h3 id="st4">Schedule &amp; retention</h3>
          <div class="fields">
            <div class="field"><span class="lbl">Nightly backup</span><label class="inline"><input type="checkbox" id="schOn" ${s.schedule_enabled ? "checked" : ""} style="width:20px;min-height:20px;accent-color:var(--accent)"> enabled at <input id="schT" type="time" value="${esc(s.schedule_time)}" style="width:auto"></label></div>
            <div class="field"><label for="lim">Upload limit (KiB/s, 0 = none)</label><input id="lim" type="number" min="0" value="${esc(s.limit_upload_kib)}"></div>
            <div class="field full"><span class="lbl">Keep versions</span><div class="ret">
              ${["daily", "weekly", "monthly", "yearly"].map((k) => `<label class="field"><span class="hint">${k}</span><input type="number" min="0" data-ret="${k}" value="${esc(r[k] ?? 0)}"></label>`).join("")}</div>
              <span class="hint">Applied after each scheduled backup. Retired versions stay recoverable in B2 for the bucket's lifecycle window.</span></div>
            <div class="field"><label for="prD">Prune unreferenced data on</label><select id="prD">${WEEKDAYS.map((d, i) => `<option value="${i}" ${+s.prune_weekday === i ? "selected" : ""}>${d}</option>`).join("")}</select></div>
            <div class="field"><label for="ckD">Integrity check on</label><select id="ckD">${WEEKDAYS.map((d, i) => `<option value="${i}" ${+s.check_weekday === i ? "selected" : ""}>${d}</option>`).join("")}</select></div>
            <div class="field"><label for="ckP">Check reads back this % of data</label><input id="ckP" type="number" min="0" max="100" value="${esc(s.check_subset_pct)}"></div>
            <div class="field"><label for="ppt">B2 price per TB / month ($)</label><input id="ppt" type="number" step="0.01" min="0" value="${esc(s.price_per_tb)}"></div>
            <div class="field full"><label for="exc">Exclude patterns (one per line)</label><textarea id="exc" spellcheck="false">${esc((s.excludes || []).join("\n"))}</textarea></div>
          </div>
          <div class="actions"><button class="btn primary" id="saveSch">Save schedule</button></div>
        </div></section>

        <section class="step rv ${sec.discord_webhook ? "done" : ""}" style="--i:5" aria-labelledby="st5"><span class="step-n">${sec.discord_webhook ? "✓" : "5"}</span><div>
          <h3 id="st5">Alerts</h3>
          <p class="help">Failures and verification problems are posted to a Discord channel webhook.</p>
          <div class="fields"><div class="field full"><label for="dwh">Discord webhook URL</label><input id="dwh" type="password" autocomplete="off" placeholder="${sec.discord_webhook ? "saved, leave blank to keep" : "https://discord.com/api/webhooks/…"}"></div>
            <label class="inline field full"><input type="checkbox" id="nOk" ${s.notify_success ? "checked" : ""} style="width:20px;min-height:20px;accent-color:var(--accent)"> Also post a short note after every successful backup</label></div>
          <div class="actions"><button class="btn primary" id="saveN">Save alerts</button><button class="btn ghost" id="testN">Send test</button></div>
        </div></section>
      </div>`;

    $("#saveB2").onclick = (e) => busy(e.currentTarget, async () => {
      const sec2 = {}; if ($("#kId").value.trim()) sec2.b2_key_id = $("#kId").value.trim(); if ($("#kKey").value.trim()) sec2.b2_app_key = $("#kKey").value.trim();
      if (Object.keys(sec2).length) await api("/api/secrets", { body: sec2 });
      await api("/api/settings", { body: { b2_bucket: $("#bkt").value.trim(), b2_prefix: $("#pfx").value.trim().replace(/^\/+|\/+$/g, "") } });
      const box = $("#b2res");
      try {
        const t = await api("/api/b2/test", { body: {} });
        const need = ["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"];
        const missing = need.filter((c) => !t.key.capabilities.includes(c));
        const lc = (t.bucket && t.bucket.lifecycle) || [];
        const rule = lc.find((x) => !x.fileNamePrefix || s.b2_prefix.startsWith(x.fileNamePrefix));
        const days = rule ? rule.daysFromHidingToDeleting : null;
        const lock = !t.bucket ? "" : t.bucket.object_lock == null ? "unknown (key can't read it)" : t.bucket.object_lock ? "on" : "off";
        box.innerHTML = `<div class="result ${t.warnings.length ? "" : "ok"}"><b>${t.warnings.length ? "Connected, with warnings" : "Connected"}</b>
          <span>${missing.length ? `${mark("bad")} Key is missing ${esc(missing.join(", "))}` : `${mark("ok")} Key has every permission Lifeboat needs`}${t.key.buckets.length ? `, restricted to <b>${esc(t.key.buckets.join(", "))}</b>` : ", and can see all buckets"}</span>
          ${t.bucket ? `<span>${mark(t.bucket.type === "allPrivate" ? "ok" : "bad")} Bucket is ${t.bucket.type === "allPrivate" ? "private" : esc(t.bucket.type)}</span>
          <span>${mark(days ? "ok" : "warn")} ${days ? `Deleted versions are kept ${esc(days)} day${days === 1 ? "" : "s"}, then purged` : "Lifecycle keeps every old version forever"}</span>
          <span class="faint">Object Lock: ${esc(lock)}${t.bucket.encryption && t.bucket.encryption.mode ? ` · Backblaze-side encryption: ${esc(t.bucket.encryption.mode)}` : ""}</span>` : ""}
          ${t.warnings.filter((w) => !/capabilities|Lifecycle|not private/.test(w)).map((w) => `<span class="s-warn">⚠ ${esc(w)}</span>`).join("")}
          <details><summary>All ${t.key.capabilities.length} key permissions</summary><p>${esc(t.key.capabilities.slice().sort().join(", "))}</p></details></div>`;
        S.ov = await api("/api/overview");
      } catch (err) { box.innerHTML = `<div class="result bad"><b>Couldn't connect</b><span>${esc(err.message)}</span></div>`; }
    });
    const connect = (create) => async (e) => busy(e.currentTarget, async () => {
      const pw = $("#rpw")?.value.trim();
      const res = await api("/api/repo/connect", { body: { password: pw || undefined, create } });
      if (res.connected) { toast(res.created ? "Repository created. Download the recovery kit now." : `Connected: ${res.snapshots} existing version(s)`); S.ov = await api("/api/overview"); renderSettings(); }
      else $("#repoRes").innerHTML = `<div class="result"><b>No repository at that address yet.</b><span class="muted">Use <i>Create new repository</i> to start one.</span></div>`;
    });
    $("#conRepo")?.addEventListener("click", connect(false));
    $("#newRepo")?.addEventListener("click", (e) => { const b = e.currentTarget; dialog(`<h3>Create a new repository?</h3><p class="muted">Make sure the password is saved in your password manager first. Without it, this backup can never be decrypted.</p>`, () => connect(true)({ currentTarget: b }), "I've saved it, create"); });
    $("#genPw")?.addEventListener("click", async () => { const { password } = await api("/api/password/generate", { body: {} }); $("#rpw").value = password; $("#rpw").type = "text"; $("#genBox").innerHTML = `<p class="help" style="margin-top:var(--s3)">Save this now:</p><div class="secret-box">${esc(password)}</div>`; });
    $("#chgRepo")?.addEventListener("click", () => dialog(`<h3>Disconnect the repository?</h3><p class="muted">Lifeboat will ask for the password again. Existing backups in B2 aren't touched.</p>`, async () => { await api("/api/secrets", { body: { repo_password: "" } }); S.ov = await api("/api/overview"); renderSettings(); }, "Disconnect", true));

    // folder tree
    renderTree(o.settings.sources);
    $("#saveSrc").onclick = (e) => busy(e.currentTarget, async () => { await api("/api/settings", { body: { sources: [...S.sel] } }); toast(`${S.sel.size} folder(s) saved`); S.ov = await api("/api/overview"); });
    $("#sizeSrc").onclick = async () => { for (const p of S.sel) await api("/api/folders/size", { body: { path: p } }); toast("Measuring in the background; sizes appear as they finish"); setTimeout(() => refreshTree(), 4000); };

    $("#saveSch").onclick = (e) => busy(e.currentTarget, async () => {
      const ret = {}; $$("[data-ret]").forEach((i) => (ret[i.dataset.ret] = +i.value || 0));
      if (!Object.values(ret).some((n) => n > 0)) throw new Error("Keep at least one version");
      await api("/api/settings", { body: { schedule_enabled: $("#schOn").checked, schedule_time: $("#schT").value || "02:30", retention: ret, prune_weekday: +$("#prD").value, check_weekday: +$("#ckD").value,
        check_subset_pct: Math.max(0, Math.min(100, +$("#ckP").value || 0)), limit_upload_kib: Math.max(0, +$("#lim").value || 0), price_per_tb: +$("#ppt").value || 0,
        excludes: $("#exc").value.split("\n").map((x) => x.trim()).filter(Boolean) } });
      toast("Schedule saved");
    });
    $("#saveN").onclick = (e) => busy(e.currentTarget, async () => {
      if ($("#dwh").value.trim()) await api("/api/secrets", { body: { discord_webhook: $("#dwh").value.trim() } });
      await api("/api/settings", { body: { notify_success: $("#nOk").checked } }); toast("Alerts saved");
    });
    $("#testN").onclick = (e) => busy(e.currentTarget, async () => { await api("/api/notify/test", { body: {} }); toast("Test sent (if a webhook is saved)"); });
  }

  async function fetchFolders(path) {
    const key = path || "";
    if (!S.folders[key]) S.folders[key] = (await api(`/api/folders${path ? `?path=${encodeURIComponent(path)}` : ""}`)).folders;
    return S.folders[key];
  }
  async function renderTree() {
    const tree = $("#tree"); if (!tree) return;
    try {
      const top = await fetchFolders("");
      tree.innerHTML = top.map((f) => treeItem(f)).join("") || `<li class="muted">No shares mounted under /source.</li>`;
      bindTree(tree);
      // auto-expand ancestors of selected folders so selections are visible
      for (const p of S.sel) for (const btn of $$(".twisty", tree)) if (p.startsWith(btn.dataset.p + "/") && btn.getAttribute("aria-expanded") === "false") await expand(btn);
    } catch (e) { tree.innerHTML = `<li class="s-bad">${esc(e.message)}</li>`; }
    renderSel();
  }
  async function refreshTree() { S.folders = {}; await renderTree(); }
  const treeItem = (f) => `<li role="treeitem" aria-expanded="false"><div class="trow">
      <button class="twisty" data-p="${esc(f.path)}" aria-expanded="false" aria-label="Expand ${esc(f.name)}">${ICON.right}</button>
      <input type="checkbox" data-p="${esc(f.path)}" ${S.sel.has(f.path) ? "checked" : ""} aria-label="Back up ${esc(f.name)}">
      <span class="tname">${esc(f.name)}</span><span class="tsize">${f.size && f.size.bytes != null ? B(f.size.bytes) : ""}</span></div></li>`;
  function bindTree(root) {
    $$(".twisty", root).forEach((b) => { if (!b.dataset.bound) { b.dataset.bound = 1; b.onclick = () => expand(b); } });
    $$("input[type=checkbox]", root).forEach((c) => {
      if (c.dataset.bound) return; c.dataset.bound = 1;
      const anc = [...S.sel].some((p) => c.dataset.p.startsWith(p + "/"));
      if (anc) { c.checked = true; c.disabled = true; }
      c.onchange = () => { c.checked ? S.sel.add(c.dataset.p) : S.sel.delete(c.dataset.p); for (const p of [...S.sel]) if (p.startsWith(c.dataset.p + "/")) S.sel.delete(p); renderSel(); refreshChecks(); };
    });
  }
  function refreshChecks() {
    $$("#tree input[type=checkbox]").forEach((c) => { const anc = [...S.sel].some((p) => c.dataset.p.startsWith(p + "/")); c.disabled = anc; c.checked = anc || S.sel.has(c.dataset.p); });
  }
  async function expand(btn) {
    const li = btn.closest("li"), open = btn.getAttribute("aria-expanded") === "true";
    if (open) { li.querySelector("ul")?.remove(); btn.setAttribute("aria-expanded", "false"); li.setAttribute("aria-expanded", "false"); return; }
    const kids = await fetchFolders(btn.dataset.p);
    const ul = document.createElement("ul"); ul.setAttribute("role", "group");
    ul.innerHTML = kids.map((f) => treeItem(f)).join("") || `<li class="faint" style="padding:4px 8px">no subfolders</li>`;
    li.appendChild(ul); btn.setAttribute("aria-expanded", "true"); li.setAttribute("aria-expanded", "true"); bindTree(ul); refreshChecks();
  }
  function renderSel() {
    const el = $("#selList"); if (!el) return;
    el.innerHTML = S.sel.size ? [...S.sel].sort().map((p) => `<span class="chip">${esc(p.replace(/^\/source\//, ""))}</span>`).join("") : `<span class="muted">Nothing selected</span>`;
  }

  // ---------------------------------------------------------------- boot
  route();
  connectLive();
  setInterval(() => { if (S.view === "overview" && S.ov && !(S.live && S.live.job)) loadOverview(); }, 60000);
})();
