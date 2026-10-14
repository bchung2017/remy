// remy — notebook-style recipe pages. Hash-routed, no build step.
// #/ browse · #/r/:id one notebook page (edited in place, autosaved)
const view = document.getElementById("view");

const api = {
  async req(method, path, body, isForm) {
    const r = await fetch("/api" + path, {
      method,
      headers: body && !isForm ? { "content-type": "application/json" } : undefined,
      body: isForm ? body : body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 204) return null;
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  },
  list: (params) => api.req("GET", "/recipes?" + new URLSearchParams(params)),
  tags: () => api.req("GET", "/tags"),
  get: (id) => api.req("GET", "/recipes/" + id),
  create: (b) => api.req("POST", "/recipes", b),
  update: (id, b) => api.req("PUT", "/recipes/" + id, b),
  remove: (id) => api.req("DELETE", "/recipes/" + id),
  upload: (id, file) => { const fd = new FormData(); fd.append("file", file, file.name || "image.jpg"); return api.req("POST", `/recipes/${id}/assets`, fd, true); },
  draft: (b) => api.req("POST", "/recipes/draft", b),
};
const health = api.req("GET", "/health").catch(() => ({}));
// ---------- on-device speech-to-text (Whisper via transformers.js, in a Worker) ----------
// No key, no Google. The model (about 77 MB) downloads once into Cache Storage. Audio is
// captured as raw PCM, cut into chunks at pauses, and each chunk is transcribed while you
// keep talking, so by Done only the tail is pending.
const WHISPER_CDN = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1/dist/transformers.min.js";
const WHISPER_MODELS = { base: "onnx-community/whisper-base.en", tiny: "onnx-community/whisper-tiny.en" };
const whisperPref = () => { try { return localStorage.getItem("remy.whisper") || "base"; } catch { return "base"; } };
const whisper = { worker: null, ready: null, model: null, device: null, listeners: new Set() };

function whisperWorker() {
  const src = `
    import { pipeline, env } from "${WHISPER_CDN}";
    env.allowLocalModels = false;
    let asr = null;
    self.onmessage = async (e) => {
      const m = e.data;
      try {
        if (m.type === "load") {
          asr = await pipeline("automatic-speech-recognition", m.model, { device: m.device, dtype: "q8", progress_callback: (p) => postMessage({ type: "progress", p }) });
          postMessage({ type: "loaded" });
        } else if (m.type === "transcribe") {
          const r = await asr(m.audio, { chunk_length_s: 30, return_timestamps: false });
          postMessage({ type: "result", seq: m.seq, text: r.text || "" });
        }
      } catch (err) { postMessage({ type: "error", seq: m.seq, message: String(err?.message || err) }); }
    };`;
  const w = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })), { type: "module" });
  w.onmessage = (e) => whisper.listeners.forEach((fn) => fn(e.data));
  return w;
}

// Load (or reuse) the model. onProgress(fraction, label) reports the download; resolves when ready.
function whisperLoad(onProgress) {
  const model = WHISPER_MODELS[whisperPref()] || WHISPER_MODELS.base;
  if (whisper.ready && whisper.model === model) return whisper.ready;
  whisper.worker?.terminate(); whisper.listeners.clear();
  whisper.worker = whisperWorker(); whisper.model = model;
  whisper.ready = (async () => {
    let device = "wasm";
    try { if (navigator.gpu && await navigator.gpu.requestAdapter()) device = "webgpu"; } catch {}
    const attempt = (dev) => new Promise((resolve, reject) => {
      const files = {};
      const on = (m) => {
        if (m.type === "progress" && m.p.file) {
          if (m.p.status === "progress") files[m.p.file] = [m.p.loaded, m.p.total || m.p.loaded];
          if (m.p.status === "done") files[m.p.file] = [1, 1];
          const [l, t] = Object.values(files).reduce((a, [x, y]) => [a[0] + x, a[1] + y], [0, 0]);
          onProgress?.(t ? l / t : 0, m.p.file);
        } else if (m.type === "loaded") { whisper.listeners.delete(on); resolve(); }
        else if (m.type === "error" && m.seq === undefined) { whisper.listeners.delete(on); reject(new Error(m.message)); }
      };
      whisper.listeners.add(on);
      whisper.worker.postMessage({ type: "load", model, device: dev });
    });
    try { await attempt(device); whisper.device = device; }
    catch (e) {
      if (device !== "wasm") { whisper.worker.terminate(); whisper.worker = whisperWorker(); await attempt("wasm"); whisper.device = "wasm"; }
      else throw e;
    }
  })();
  whisper.ready.catch(() => { whisper.ready = null; });
  return whisper.ready;
}

// Warm the worker at app open if the model is already cached (no unsolicited 77 MB download).
(async () => {
  try {
    const h = await health; if (!h.draft || !window.caches) return;
    const c = await caches.open("transformers-cache");
    if ((await c.keys()).some((k) => k.url.includes(WHISPER_MODELS[whisperPref()]))) whisperLoad();
  } catch {}
})();

function resample16k(pcm, from) {
  if (from === 16000) return pcm;
  const ratio = from / 16000, out = new Float32Array(Math.floor(pcm.length / ratio));
  for (let i = 0; i < out.length; i++) { const x = i * ratio, j = Math.floor(x), f = x - j; out[i] = pcm[j] * (1 - f) + (pcm[Math.min(j + 1, pcm.length - 1)] || 0) * f; }
  return out;
}

// Full-screen recording panel: pulsing dot, mic level, timer, the words as chunks come back,
// one big Done. onText(text) per transcribed chunk; onDone(ok).
function startDictation({ onText, onDone }) {
  const panel = document.createElement("div");
  panel.className = "rec"; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Recording");
  panel.innerHTML = `
    <div class="rec-top"><span class="rec-dot" aria-hidden="true"></span><span class="rec-label">Listening</span><span class="rec-time">0:00</span></div>
    <canvas class="rec-meter" width="600" height="80" aria-hidden="true"></canvas>
    <div class="rec-text" aria-live="polite"><span class="rec-final"></span><span class="rec-interim"></span></div>
    <p class="rec-hint">Say the recipe the way you'd tell a friend. Pause whenever you like. Words appear a few seconds behind you.</p>
    <div class="rec-model"><label><input type="radio" name="wm" value="base" ${whisperPref() === "base" ? "checked" : ""}> Accurate (base)</label><label><input type="radio" name="wm" value="tiny" ${whisperPref() === "tiny" ? "checked" : ""}> Fast (tiny)</label><span class="hint">applies next time</span></div>
    <div class="rec-actions"><button class="btn btn-ghost rec-cancel">Cancel</button><button class="btn btn-primary rec-done">Done</button></div>`;
  document.body.appendChild(panel); document.body.classList.add("rec-open");
  const $ = (c) => panel.querySelector(c);
  const label = $(".rec-label"), finalEl = $(".rec-final"), interimEl = $(".rec-interim"), timeEl = $(".rec-time"), done = $(".rec-done");
  panel.querySelectorAll("input[name=wm]").forEach((r) => r.addEventListener("change", () => { try { localStorage.setItem("remy.whisper", r.value); } catch {} }));

  const t0 = Date.now();
  const tick = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); timeEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }, 500);

  // --- model: load in the background; capture starts regardless so nothing said is lost ---
  let modelReady = false, closed = false;
  const pending = new Map();   // seq -> true while a chunk is in the worker
  let nextSeq = 0, doneSeq = 0, results = {};
  const status = () => {
    if (closed) return;
    const n = pending.size;
    if (!modelReady) return;
    interimEl.textContent = n ? ` …` : "";
    label.textContent = n ? `Listening · ${n} chunk${n > 1 ? "s" : ""} transcribing` : "Listening";
  };
  whisperLoad((frac, file) => { if (!modelReady && !closed) label.textContent = frac < 1 ? `Loading speech model… ${Math.round(frac * 100)}%` : "Starting speech model…"; })
    .then(() => { modelReady = true; status(); })
    .catch((e) => { label.textContent = "Speech model failed: " + e.message; panel.classList.add("rec-error"); });

  const onResult = (m) => {
    if (m.type === "result" && pending.has(m.seq)) {
      pending.delete(m.seq); results[m.seq] = (m.text || "").trim();
      // emit in order
      while (results[doneSeq] !== undefined) { const t = results[doneSeq]; delete results[doneSeq]; doneSeq++; if (t) { finalEl.textContent = (finalEl.textContent + " " + t).trim(); onText(t); } }
      panel.scrollTop = panel.scrollHeight; status(); if (finishing) maybeFinish();
    } else if (m.type === "error" && pending.has(m.seq)) { pending.delete(m.seq); results[m.seq] = ""; status(); if (finishing) maybeFinish(); }
  };
  whisper.listeners.add(onResult);

  // --- capture: raw PCM, level meter, chunking at pauses ---
  const canvas = $(".rec-meter"), g = canvas.getContext("2d");
  const fill = getComputedStyle(document.documentElement).getPropertyValue("--copper").trim() || "#9e4e1c";
  const bars = new Array(48).fill(0);
  let stream = null, ac = null, proc = null, src = null, rate = 48000;
  let chunk = [], chunkSamples = 0, silence = 0, peakInChunk = 0;
  const MIN_CUT = 8, MAX_CUT = 12, PAUSE = 0.5, QUIET = 0.01;
  const postChunk = () => {
    if (!chunkSamples) return;
    const n = chunkSamples, pcm = new Float32Array(n); let o = 0; for (const c of chunk) { pcm.set(c, o); o += c.length; }
    const hadSpeech = peakInChunk >= QUIET && n / rate >= 0.6;
    chunk = []; chunkSamples = 0; silence = 0; peakInChunk = 0;
    if (!hadSpeech) return;
    const audio = resample16k(pcm, rate), seq = nextSeq++;
    pending.set(seq, true); status();
    whisper.ready?.then(() => { if (!closed || finishing) whisper.worker.postMessage({ type: "transcribe", seq, audio }, [audio.buffer]); });
  };
  navigator.mediaDevices.getUserMedia({ audio: true }).then(async (st) => {
    if (closed) { st.getTracks().forEach((t) => t.stop()); return; }
    stream = st; ac = new (window.AudioContext || window.webkitAudioContext)(); await ac.resume().catch(() => {}); rate = ac.sampleRate;
    src = ac.createMediaStreamSource(st); proc = ac.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => {
      const buf = e.inputBuffer.getChannelData(0);
      let sum = 0, peak = 0; for (const v of buf) { sum += v * v; peak = Math.max(peak, Math.abs(v)); }
      const rms = Math.sqrt(sum / buf.length);
      bars.push(Math.min(1, rms * 4)); bars.shift();
      chunk.push(new Float32Array(buf)); chunkSamples += buf.length; peakInChunk = Math.max(peakInChunk, peak);
      silence = rms < QUIET ? silence + buf.length / rate : 0;
      const dur = chunkSamples / rate;
      if ((dur >= MIN_CUT && silence >= PAUSE) || dur >= MAX_CUT) postChunk();
    };
    src.connect(proc); proc.connect(ac.destination);
    const draw = () => {
      if (closed) return;
      g.clearRect(0, 0, canvas.width, canvas.height); g.fillStyle = fill;
      const w = canvas.width / bars.length;
      bars.forEach((b, i) => { const h = Math.max(3, b * canvas.height); g.fillRect(i * w + 1, (canvas.height - h) / 2, w - 2, h); });
      requestAnimationFrame(draw);
    };
    draw();
  }).catch((e) => { label.textContent = e.name === "NotAllowedError" ? "Microphone blocked. Allow it in the site settings, then try again." : "Microphone: " + e.message; panel.classList.add("rec-error"); });

  // --- finish / cancel ---
  let finishing = false, ok = false;
  const stopCapture = () => { try { proc?.disconnect(); src?.disconnect(); } catch {} stream?.getTracks().forEach((t) => t.stop()); ac?.close().catch(() => {}); };
  const teardown = () => { closed = true; clearInterval(tick); whisper.listeners.delete(onResult); panel.remove(); document.body.classList.remove("rec-open"); onDone(ok); };
  const maybeFinish = () => { if (pending.size === 0) teardown(); else label.textContent = `Finishing · ${pending.size} chunk${pending.size > 1 ? "s" : ""} left`; };
  done.addEventListener("click", () => {
    if (finishing) return;
    finishing = true; ok = true; done.disabled = true; done.textContent = "Finishing…";
    stopCapture(); postChunk(); panel.classList.add("rec-finishing");
    if (!modelReady) { label.textContent = "Finishing · waiting for the speech model"; whisper.ready?.then(maybeFinish).catch(teardown); }
    else maybeFinish();
  });
  $(".rec-cancel").addEventListener("click", () => { ok = false; stopCapture(); pending.clear(); teardown(); });
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") { ok = false; stopCapture(); pending.clear(); teardown(); } });
  done.focus();
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");
const uid = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Date.now().toString(36) + Math.random().toString(36).slice(2));

// ---------- browse ----------
const browse = { q: "", tag: "", sort: "updated" };
try { Object.assign(browse, JSON.parse(sessionStorage.getItem("remy.browse") || "{}")); } catch {}
const saveBrowse = () => { try { sessionStorage.setItem("remy.browse", JSON.stringify(browse)); } catch {} };

function listHtml(recipes) {
  if (!recipes.length) return `<p class="empty">${browse.q || browse.tag ? "No matches." : "No recipes yet."}</p>`;
  return `<ul class="list">${recipes.map((r) => {
    const img = r.blocks.find((b) => b.type === "image");
    return `<li><a class="card" href="#/r/${r.id}">
      ${img ? `<img class="thumb" src="/api/assets/${esc(img.asset)}" alt="">` : ""}
      <div class="card-text">
        <h3>${esc(r.title)}</h3>
        ${r.body ? `<p>${esc(r.body.slice(0, 240))}</p>` : ""}
        <div class="meta"><span>${when(r.updatedAt)}</span>${r.tags.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>
      </div></a></li>`; }).join("")}</ul>`;
}

async function renderBrowse() {
  const [recipes, tags] = await Promise.all([api.list(browse), api.tags()]);
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" type="search" placeholder="Search" value="${esc(browse.q)}" aria-label="Search recipes">
      <select id="sort" aria-label="Sort">
        <option value="updated" ${browse.sort === "updated" ? "selected" : ""}>Recently updated</option>
        <option value="created" ${browse.sort === "created" ? "selected" : ""}>Newest</option>
        <option value="title" ${browse.sort === "title" ? "selected" : ""}>Title</option>
      </select>
    </div>
    ${tags.length ? `<div class="tags">${tags.map((t) =>
      `<button class="tag ${browse.tag === t.tag ? "on" : ""}" data-tag="${esc(t.tag)}">${esc(t.tag)} ${t.count}</button>`).join("")}</div>` : ""}
    <div id="list">${listHtml(recipes)}</div>`;
  const q = view.querySelector("#q");
  let timer;
  const refresh = async () => { view.querySelector("#list").innerHTML = listHtml(await api.list(browse)); };
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { browse.q = q.value; saveBrowse(); refresh(); }, 200); });
  view.querySelector("#sort").addEventListener("change", (e) => { browse.sort = e.target.value; saveBrowse(); refresh(); });
  view.querySelectorAll(".tag").forEach((b) => b.addEventListener("click", () => {
    browse.tag = browse.tag === b.dataset.tag ? "" : b.dataset.tag; saveBrowse(); renderBrowse();
  }));
}

// Pick a text-to-speech voice: a local one in the user's language, else any in that language,
// else the browser default. Resolves null when the device has no voices at all.
async function pickVoice() {
  if (!("speechSynthesis" in window)) return null;
  let voices = speechSynthesis.getVoices();
  if (!voices.length) {
    await new Promise((res) => { const t = setTimeout(res, 1500); speechSynthesis.addEventListener("voiceschanged", () => { clearTimeout(t); res(); }, { once: true }); });
    voices = speechSynthesis.getVoices();
  }
  if (!voices.length) return null;
  const lang = (navigator.language || "en-US").toLowerCase(), base = lang.split("-")[0];
  const match = (v, exact) => (exact ? v.lang.toLowerCase() === lang : v.lang.toLowerCase().startsWith(base));
  return voices.find((v) => v.localService && match(v, true)) || voices.find((v) => v.localService && match(v, false))
    || voices.find((v) => match(v, true)) || voices.find((v) => match(v, false)) || voices.find((v) => v.default) || voices[0];
}

// ---------- notebook page (Jupyter-style cells) ----------
const TYPE_LABEL = { text: "Text", image: "Image", ai: "AI" };

function cellHtml(b, n) {
  const gutter = `<div class="gutter"><span class="kind">${TYPE_LABEL[b.type] || "AI"}</span><span class="num">[${n}]</span></div>`;
  const tools = `<div class="cell-tools">
      <button data-act="up" title="Move up" aria-label="Move up">↑</button>
      <button data-act="down" title="Move down" aria-label="Move down">↓</button>
      <button data-act="del" title="Delete cell" aria-label="Delete cell">×</button>
    </div>`;
  let body;
  if (b.type === "image") body = `
    <div class="cell-in">
      <img src="/api/assets/${esc(b.asset)}" alt="${esc(b.caption)}">
      <input class="caption" placeholder="Caption" value="${esc(b.caption)}" aria-label="Caption">
    </div>`;
  else if (b.type === "ai" && b.draft) body = `
    <div class="cell-in ai-in">
      <div class="ai-row">
        <button class="btn btn-sm dictate">● Dictate</button>
        <span class="hint ai-note"></span>
        <button class="btn btn-sm btn-primary run" disabled>▶ Run</button>
      </div>
      <textarea class="transcript" rows="1" placeholder="Say the recipe the way you'd tell a friend. Edit here before running." aria-label="Transcript"></textarea>
    </div>
    <div class="cell-out hint" hidden></div>`;
  else if (b.type === "ai") body = `
    <div class="cell-in ai-in"><details class="transcript-view"><summary class="hint">Transcript</summary><p>${esc(b.transcript)}</p></details></div>
    <div class="cell-out"><textarea class="text" rows="1" aria-label="Formatted recipe">${esc(b.text)}</textarea></div>`;
  else body = `
    <div class="cell-in"><textarea class="text" rows="1" placeholder="Write here" aria-label="Text">${esc(b.text)}</textarea></div>`;
  return `<section class="cell cell-${b.type} ${b.draft ? "draft" : ""}" data-id="${esc(b.id)}" data-type="${b.type}" tabindex="-1">${gutter}<div class="cell-body">${body}</div>${tools}</section>`;
}

const grow = (ta) => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };

// shrink camera photos before upload: max 1600px edge, JPEG
async function shrinkImage(file) {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  const bmp = await createImageBitmap(file).catch(() => null);
  if (!bmp) return file;
  const max = 1600, scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 1.5e6) return file;
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
  return blob ? new File([blob], (file.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
}

async function renderRecipe(id) {
  let r;
  try { r = await api.get(id); } catch { view.innerHTML = `<p class="empty">Not found. <a href="#/">Back</a></p>`; return; }
  const h = await health;
  let saveTimer, saving = Promise.resolve();

  view.innerHTML = `
    <article class="nb">
      <header class="nb-head">
        <input class="title display-lg" id="title" value="${esc(r.title)}" placeholder="Untitled" aria-label="Title">
        <div class="nb-meta">
          <input class="tagsin" id="tags" value="${esc(r.tags.join(", "))}" placeholder="tags, comma separated" aria-label="Tags">
          <span class="status" id="status">${when(r.updatedAt)}</span>
        </div>
      </header>
      <div class="nb-toolbar" role="toolbar" aria-label="Cells">
        <button class="btn btn-sm" data-add="text">+ Text</button>
        <label class="btn btn-sm" for="add-image">+ Image</label>
        <input id="add-image" type="file" accept="image/*" hidden>
        ${h.draft ? `<button class="btn btn-sm" data-add="ai">+ AI</button>` : `<button class="btn btn-sm" disabled title="Set ANTHROPIC_API_KEY to enable">+ AI</button>`}
        <span class="sep"></span>
        <button class="btn btn-sm btn-ghost" id="t-up" title="Move cell up">↑</button>
        <button class="btn btn-sm btn-ghost" id="t-down" title="Move cell down">↓</button>
        <button class="btn btn-sm btn-ghost" id="t-del" title="Delete cell">× cell</button>
        <span class="sep"></span>
        <button class="btn btn-sm" id="t-read" title="Read the recipe aloud">▶ Read aloud</button>
      </div>
      <div class="cells" id="cells">${r.blocks.map((b, i) => cellHtml(b, i + 1)).join("")}</div>
      <p class="empty" id="nocells" ${r.blocks.length ? "hidden" : ""}>Empty notebook. Add a cell above.</p>
      <p class="error" id="err" hidden></p>
      <footer class="nb-foot">
        <button class="btn btn-danger" id="del">Delete recipe</button>
        <a class="btn btn-ghost" href="#/">Back</a>
      </footer>
    </article>`;

  const cellsEl = view.querySelector("#cells");
  const status = view.querySelector("#status");
  const err = (msg) => { const el = view.querySelector("#err"); el.textContent = msg; el.hidden = !msg; };
  const transcripts = Object.fromEntries(r.blocks.filter((b) => b.type === "ai").map((b) => [b.id, b.transcript || ""]));

  // --- state lives in the DOM; blocks are read back in order on save (draft AI cells are skipped) ---
  const readBlocks = () => [...cellsEl.querySelectorAll(".cell:not(.draft)")].map((el) => {
    const id = el.dataset.id, type = el.dataset.type;
    if (type === "image") return { id, type, asset: el.querySelector("img").getAttribute("src").split("/").pop(), caption: el.querySelector(".caption").value };
    if (type === "ai") return { id, type, text: el.querySelector(".text").value, transcript: transcripts[id] || "" };
    return { id, type, text: el.querySelector(".text").value };
  });
  const renumber = () => {
    const cells = cellsEl.querySelectorAll(".cell");
    cells.forEach((el, i) => { el.querySelector(".num").textContent = `[${i + 1}]`; });
    view.querySelector("#nocells").hidden = cells.length > 0;
  };
  const save = () => {
    clearTimeout(saveTimer);
    status.textContent = "Saving…";
    saving = saving.then(async () => {
      try {
        r = await api.update(id, { title: view.querySelector("#title").value, tags: view.querySelector("#tags").value, blocks: readBlocks() });
        status.textContent = "Saved"; err("");
      } catch (e) { status.textContent = "Not saved"; err(e.message); }
    });
    return saving;
  };
  const saveSoon = () => { clearTimeout(saveTimer); status.textContent = "Editing"; saveTimer = setTimeout(save, 700); };

  // --- selection ---
  let selected = null;
  const select = (el) => { selected?.classList.remove("selected"); selected = el; el?.classList.add("selected"); };
  cellsEl.addEventListener("focusin", (e) => { const c = e.target.closest(".cell"); if (c) select(c); });
  cellsEl.addEventListener("mousedown", (e) => { const c = e.target.closest(".cell"); if (c) select(c); });

  const move = (el, dir) => {
    if (!el) return;
    const sib = dir < 0 ? el.previousElementSibling : el.nextElementSibling;
    if (!sib) return;
    dir < 0 ? sib.before(el) : sib.after(el);
    renumber(); el.focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" }); save();
  };
  const remove = (el) => {
    if (!el) return;
    const next = el.nextElementSibling || el.previousElementSibling;
    el.remove(); renumber(); select(next); next?.focus({ preventScroll: true });
    if (!el.classList.contains("draft")) save();
  };

  // --- wiring per cell ---
  const wire = (el) => {
    el.querySelectorAll("textarea").forEach((ta) => { grow(ta); ta.addEventListener("input", () => { grow(ta); saveSoon(); }); ta.addEventListener("blur", save); });
    el.querySelectorAll("input.caption").forEach((i) => { i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });
    el.querySelectorAll(".cell-tools button").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const act = b.dataset.act;
      if (act === "up") move(el, -1); else if (act === "down") move(el, 1); else remove(el);
    }));
    const run = el.querySelector(".run");
    if (run) {
      const ta = el.querySelector(".transcript"), out = el.querySelector(".cell-out"), mic = el.querySelector(".dictate"), note = el.querySelector(".ai-note");
      const refresh = () => { run.disabled = !ta.value.trim(); grow(ta); };
      ta.addEventListener("input", refresh);
      if (mic) mic.addEventListener("click", () => {
        const before = ta.value; err(""); note.textContent = "";
        mic.disabled = true;
        startDictation({
          onText: (t) => { ta.value = (ta.value.trimEnd() + " " + t).trim(); refresh(); },
          onDone: (ok) => { mic.disabled = false; if (!ok) ta.value = before; refresh(); if (ok && ta.value.trim()) note.textContent = "Edit if needed, then Run."; (ok ? run : ta).focus(); },
        });
      });
      run.addEventListener("click", async () => {
        const transcript = ta.value.trim(); if (!transcript) return;
        run.disabled = true; run.textContent = "Running…"; out.hidden = false; out.textContent = "Formatting with Claude…"; err("");
        const title = view.querySelector("#title").value.trim();
        try {
          const d = await api.draft({ transcript, title: title === "Untitled" ? "" : title });
          const blk = { id: uid(), type: "ai", text: d.body, transcript };
          transcripts[blk.id] = transcript;
          el.insertAdjacentHTML("afterend", cellHtml(blk, 0));
          const real = el.nextElementSibling; wire(real); el.remove(); renumber(); select(real);
          if (!title || title === "Untitled") view.querySelector("#title").value = d.title;
          if (!view.querySelector("#tags").value.trim()) view.querySelector("#tags").value = d.tags.join(", ");
          await save();
        } catch (ex) {
          err(ex.message); out.textContent = "Failed: " + ex.message; run.disabled = false; run.textContent = "▶ Run";
        }
      });
    }
  };
  cellsEl.querySelectorAll(".cell").forEach(wire);
  ["#title", "#tags"].forEach((sel) => { const i = view.querySelector(sel); i.addEventListener("input", saveSoon); i.addEventListener("blur", save); });

  // insert after the selected cell, else at the end
  const insert = (b) => {
    const html = cellHtml(b, 0);
    if (selected && selected.parentElement === cellsEl) selected.insertAdjacentHTML("afterend", html);
    else cellsEl.insertAdjacentHTML("beforeend", html);
    const el = selected?.parentElement === cellsEl ? selected.nextElementSibling : cellsEl.lastElementChild;
    wire(el); renumber(); select(el);
    (el.querySelector("textarea.text, textarea.transcript") || el).focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" });
    return el;
  };
  view.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.add === "text") { insert({ id: uid(), type: "text", text: "" }); save(); }
    else insert({ id: "draft-" + uid(), type: "ai", draft: true });
  }));
  view.querySelector("#add-image").addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    status.textContent = "Uploading…"; err("");
    try {
      const a = await api.upload(id, await shrinkImage(file));
      insert({ id: uid(), type: "image", asset: a.id, caption: "" });
      await save();
    } catch (ex) { status.textContent = "Not saved"; err(ex.message); }
  });
  view.querySelector("#t-up").addEventListener("click", () => move(selected, -1));
  view.querySelector("#t-down").addEventListener("click", () => move(selected, 1));
  view.querySelector("#t-del").addEventListener("click", () => remove(selected));

  // keyboard: with a cell selected and no field focused, j/k or arrows move selection, shift+arrows move the cell, d deletes
  view.querySelector(".nb").addEventListener("keydown", (e) => {
    const inField = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName);
    if (e.key === "Escape" && inField) { document.activeElement.blur(); selected?.focus(); return; }
    if (inField || !selected) return;
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); e.shiftKey ? move(selected, -1) : (selected.previousElementSibling && (select(selected.previousElementSibling), selected.focus())); }
    else if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); e.shiftKey ? move(selected, 1) : (selected.nextElementSibling && (select(selected.nextElementSibling), selected.focus())); }
    else if (e.key === "Enter") { e.preventDefault(); (selected.querySelector("textarea, input.caption") || selected).focus(); }
    else if (e.key === "d" || e.key === "Delete") { e.preventDefault(); remove(selected); }
  });

  // --- read aloud: browser text-to-speech, one utterance per line so iOS/Chrome never
  // cut a long one off; the cell being read is highlighted ---
  const readBtn = view.querySelector("#t-read");
  if (!("speechSynthesis" in window)) readBtn.hidden = true;
  let reading = false;
  const stopReading = () => {
    reading = false; try { speechSynthesis.cancel(); } catch {}
    cellsEl.querySelectorAll(".reading").forEach((e) => e.classList.remove("reading"));
    readBtn.textContent = "▶ Read aloud";
  };
  readBtn.addEventListener("click", async () => {
    if (reading) return stopReading();
    const voice = await pickVoice();
    if (voice === null) { err("No text-to-speech voices on this device. On Android, install or enable a speech engine in Settings → Accessibility → Text-to-speech."); return; }
    const items = [];
    const title = view.querySelector("#title").value.trim(); if (title) items.push({ text: title, el: null });
    cellsEl.querySelectorAll(".cell:not(.draft)").forEach((el) => {
      const ta = el.querySelector("textarea.text"); if (!ta) return;
      ta.value.split(/\n+/).map((l) => l.trim()).filter(Boolean).forEach((line) => items.push({ text: line, el }));
    });
    if (!items.length) { err("Nothing to read yet."); return; }
    err(""); reading = true; readBtn.textContent = "■ Stop";
    let i = 0;
    const next = () => {
      if (!reading || i >= items.length) return stopReading();
      const { text, el } = items[i++];
      cellsEl.querySelectorAll(".reading").forEach((e) => e.classList.remove("reading"));
      el?.classList.add("reading"); el?.scrollIntoView({ block: "nearest" });
      const u = new SpeechSynthesisUtterance(text);
      if (voice) u.voice = voice; u.lang = voice?.lang || navigator.language || "en-US"; u.rate = 0.95;
      u.onend = next;
      u.onerror = (e) => { if (e.error === "interrupted" || e.error === "canceled") return; err("Speech failed: " + e.error); stopReading(); };
      speechSynthesis.speak(u);
    };
    try { speechSynthesis.cancel(); } catch {}
    next();
  });
  window.addEventListener("hashchange", stopReading, { once: true });
  window.addEventListener("pagehide", stopReading, { once: true });

  const del = view.querySelector("#del");
  del.addEventListener("click", () => {
    del.outerHTML = `<span class="confirm">Delete this recipe? <button class="btn btn-danger" id="yes">Delete</button><button class="btn btn-ghost" id="no">Keep</button></span>`;
    view.querySelector("#yes").addEventListener("click", async () => { await api.remove(id); location.hash = "#/"; });
    view.querySelector("#no").addEventListener("click", () => renderRecipe(id));
  });

  if (r.title === "Untitled" && !r.blocks.length) view.querySelector("#title").select();
}

async function newRecipe() {
  const r = await api.create({});
  location.replace("#/r/" + r.id);
}

function route() {
  const h = location.hash || "#/";
  let m;
  if (h === "#/" || h === "#") return renderBrowse();
  if (h === "#/new") return newRecipe();
  if ((m = h.match(/^#\/r\/(\d+)$/))) return renderRecipe(m[1]);
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
route();
