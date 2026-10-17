// remy — the pass (home) and the cookbook (browse). Loaded before app.js; uses its globals at call time.
// Home: a shelf with the cookbook, an order rail with the three most-read recipes clipped up as
// tickets, and the stove. Clicking the book lifts it to the camera, opens it, flips to the middle,
// and lands on #/book: the open spread with the full list.

const STOVE_SVG = `
<svg class="stove-svg" viewBox="0 0 960 360" aria-hidden="true" focusable="false">
  <defs><pattern id="tile" width="48" height="48" patternUnits="userSpaceOnUse"><rect width="48" height="48" class="f-sunken"/><path d="M0 47.5H48M47.5 0V48" class="s-hair"/></pattern></defs>
  <rect x="0" y="0" width="960" height="150" fill="url(#tile)"/>
  <!-- range top -->
  <rect x="40" y="150" width="880" height="34" rx="6" class="f-raised s-hair"/>
  <ellipse cx="300" cy="167" rx="120" ry="20" class="f-sunken s-slate"/>
  <ellipse cx="300" cy="167" rx="80" ry="13" fill="none" class="s-slate"/>
  <ellipse cx="650" cy="167" rx="120" ry="20" class="f-sunken s-slate"/>
  <ellipse cx="650" cy="167" rx="80" ry="13" fill="none" class="s-slate"/>
  <!-- flames -->
  <g class="flames">
    <path class="flame f-lamp" d="M250 163c6-14 10-20 12-30 4 10 10 16 10 30z"/><path class="flame f-tomato" d="M292 163c5-10 7-15 9-22 3 8 7 12 8 22z"/><path class="flame f-lamp" d="M336 163c6-14 10-20 12-30 4 10 10 16 10 30z"/>
    <path class="flame f-lamp" d="M604 163c6-12 9-18 11-26 4 9 9 14 9 26z"/><path class="flame f-tomato" d="M644 163c5-9 7-14 9-20 3 7 7 11 8 20z"/><path class="flame f-lamp" d="M684 163c6-12 9-18 11-26 4 9 9 14 9 26z"/>
  </g>
  <!-- stock pot -->
  <g class="pot">
    <rect x="215" y="60" width="170" height="104" rx="8" class="f-copper"/>
    <rect x="215" y="60" width="170" height="104" rx="8" fill="none" class="s-copper-dark"/>
    <rect x="207" y="56" width="186" height="12" rx="4" class="f-copper-dark"/>
    <rect x="190" y="92" width="22" height="12" rx="4" class="f-aubergine"/><rect x="388" y="92" width="22" height="12" rx="4" class="f-aubergine"/>
    <ellipse cx="300" cy="56" rx="86" ry="10" class="f-aubergine"/>
    <circle cx="300" cy="46" r="7" class="f-lamp"/>
    <g class="steam">
      <path class="wisp" d="M268 40c-8-10 8-18 0-28s8-18 0-26"/><path class="wisp" d="M300 36c-8-10 8-18 0-28s8-18 0-26"/><path class="wisp" d="M332 40c-8-10 8-18 0-28s8-18 0-26"/>
    </g>
  </g>
  <!-- skillet -->
  <g class="skillet">
    <ellipse cx="650" cy="150" rx="104" ry="20" class="f-copper-dark"/>
    <ellipse cx="650" cy="142" rx="104" ry="20" class="f-copper"/>
    <ellipse cx="650" cy="142" rx="88" ry="14" class="f-aubergine"/>
    <ellipse cx="650" cy="141" rx="70" ry="9" class="f-tomato"/>
    <ellipse cx="628" cy="138" rx="12" ry="4" class="f-lamp"/><ellipse cx="668" cy="143" rx="10" ry="3" class="f-lamp"/>
    <path d="M748 136l120-22a8 8 0 0 1 4 15l-118 24z" class="f-aubergine"/>
    <g class="steam"><path class="wisp" d="M640 120c-8-10 8-18 0-28s8-18 0-26"/><path class="wisp" d="M672 124c-8-10 8-18 0-28s8-18 0-26"/></g>
  </g>
  <!-- oven -->
  <rect x="60" y="188" width="840" height="150" rx="8" class="f-raised s-hair"/>
  <rect x="120" y="206" width="720" height="14" rx="7" class="f-copper"/>
  <rect x="180" y="236" width="600" height="86" rx="6" class="f-aubergine"/>
  <rect x="196" y="250" width="568" height="58" rx="4" class="f-ink glow"/>
  <circle cx="100" cy="300" r="12" class="f-sunken s-slate"/><circle cx="860" cy="300" r="12" class="f-sunken s-slate"/>
  <path d="M100 290v8M860 290v8" class="s-slate"/>
</svg>`;

function ticketHtml(r, i) {
  const tilt = [-2.2, 1.4, -1.1][i] + "deg";
  if (!r) return `<li class="ticket empty" style="--tilt:${tilt}"><span class="clip"></span><span class="slip"><span class="slip-head">ORDER 0${i + 1}</span><span class="slip-title">—</span><span class="slip-meta">${i === 0 ? "star a recipe to hang it here" : ""}</span></span></li>`;
  return `<li class="ticket" style="--tilt:${tilt}"><a href="#/r/${r.id}"><span class="clip"></span><span class="slip">
      <span class="slip-head">ORDER 0${i + 1}<span class="slip-star">★</span></span>
      <span class="slip-title">${esc(r.title)}</span>
      <span class="slip-meta">${r.tags.length ? r.tags.map((t) => "#" + esc(t)).join(" ") : when(r.updatedAt)}</span>
    </span></a></li>`;
}

const bookHtml = () => `
  <div class="book-3d">
    <div class="book-back"></div>
    <div class="book-page p3"></div><div class="book-page p2"></div><div class="book-page p1"></div>
    <div class="book-cover"><span class="cover-title">Anyone<br>Can<br>Cook</span><span class="cover-rule"></span></div>
  </div>`;

async function renderHome() {
  const [starred, recipes] = await Promise.all([api.list({ starred: 1, sort: "starred" }), api.list({})]);
  const top = [starred[0], starred[1], starred[2]];
  view.innerHTML = `
    <section class="pass" aria-label="The pass">
      <div class="shelf-row">
        <div class="shelf"></div>
        <button class="book" id="book" aria-label="Open the cookbook: all recipes">${bookHtml()}</button>
        <a class="shelf-label" href="#/book">All ${recipes.length} recipe${recipes.length === 1 ? "" : "s"}</a>
      </div>
      <div class="rail" aria-label="Starred recipes">
        <div class="rail-bar"></div>
        <ul class="tickets">${top.map(ticketHtml).join("")}</ul>
      </div>
      <div class="stove">${STOVE_SVG}</div>
    </section>`;
  view.querySelector("#book").addEventListener("click", (e) => { e.preventDefault(); openBook(view.querySelector("#book")); });
}

// Lift the book off the shelf, turn it to the camera, open the cover, flip to the middle, then
// show the spread. Done on a fixed clone so the shelf copy never reflows.
function openBook(bookEl) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { location.hash = "#/book"; return; }
  const rect = bookEl.getBoundingClientRect();
  const fly = document.createElement("div");
  fly.className = "book-fly";
  fly.style.cssText = `left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px`;
  fly.innerHTML = bookHtml();
  document.body.appendChild(fly); bookEl.style.visibility = "hidden";
  const stage = (cls, ms) => new Promise((res) => { requestAnimationFrame(() => { fly.classList.add(cls); setTimeout(res, ms); }); });
  (async () => {
    await stage("to-camera", 750);   // position 2: translate + rotate to camera normal
    await stage("opened", 650);      // cover swings
    await stage("flipped", 700);     // pages flip to the middle
    sessionStorage.setItem("remy.bookOpened", "1");
    location.hash = "#/book";
    await stage("gone", 320);
    fly.remove();
  })();
}

// star / unstar; resolves {recipe, demoted}
const toggleStar = (id, on) => api.req(on ? "DELETE" : "POST", `/recipes/${id}/star`);

// ---------- the open book: browse ----------
const browse = { q: "", tag: "", sort: "updated" };
try { Object.assign(browse, JSON.parse(sessionStorage.getItem("remy.browse") || "{}")); } catch {}
const saveBrowse = () => { try { sessionStorage.setItem("remy.browse", JSON.stringify(browse)); } catch {} };

function tocHtml(recipes) {
  if (!recipes.length) return `<p class="empty">${browse.q || browse.tag ? "No matches." : "No recipes yet."}</p>`;
  return `<ol class="toc">${recipes.map((r) => {
    const img = r.blocks.find((b) => b.type === "image");
    return `<li><div class="toc-row"><a href="#/r/${r.id}">
      ${img ? `<img class="toc-thumb" src="/api/assets/${esc(img.asset)}" alt="" loading="lazy">` : `<span class="toc-thumb toc-empty" aria-hidden="true"></span>`}
      <span class="toc-title">${esc(r.title)}</span><span class="toc-dots" aria-hidden="true"></span>
      <span class="toc-num">${when(r.updatedAt)}</span>
    </a><button class="star ${r.starred ? "on" : ""}" data-id="${r.id}" title="${r.starred ? "Take off the pass" : "Hang on the pass (up to 3)"}" aria-label="${r.starred ? "Unstar" : "Star"} ${esc(r.title)}" aria-pressed="${r.starred}">${r.starred ? "★" : "☆"}</button></div>${r.tags.length ? `<span class="toc-tags">${r.tags.map((t) => "#" + esc(t)).join(" ")}</span>` : ""}</li>`; }).join("")}</ol>`;
}

async function renderBook() {
  const [recipes, tags] = await Promise.all([api.list(browse), api.tags()]);
  const justOpened = sessionStorage.getItem("remy.bookOpened") === "1"; sessionStorage.removeItem("remy.bookOpened");
  view.innerHTML = `
    <section class="spread ${justOpened ? "settle" : ""}" aria-label="Cookbook">
      <div class="bpage left">
        <h2 class="display-md">Anyone Can Cook</h2>
        <p class="hint">${recipes.length} recipe${recipes.length === 1 ? "" : "s"}${browse.q || browse.tag ? " matching" : ""}</p>
        <div class="toolbar">
          <input id="q" type="search" placeholder="Search" value="${esc(browse.q)}" aria-label="Search recipes">
          <select id="sort" aria-label="Sort">
            <option value="updated" ${browse.sort === "updated" ? "selected" : ""}>Recently updated</option>
            <option value="created" ${browse.sort === "created" ? "selected" : ""}>Newest</option>
            <option value="title" ${browse.sort === "title" ? "selected" : ""}>Title</option>
            <option value="starred" ${browse.sort === "starred" ? "selected" : ""}>Starred first</option>
          </select>
        </div>
        ${tags.length ? `<div class="tags">${tags.map((t) => `<button class="tag ${browse.tag === t.tag ? "on" : ""}" data-tag="${esc(t.tag)}">${esc(t.tag)} ${t.count}</button>`).join("")}</div>` : ""}
        <p class="hint" id="star-note" hidden></p>
        <a class="btn btn-ghost back-to-pass" href="#/">← Back to the pass</a>
      </div>
      <div class="bpage right" id="list">${tocHtml(recipes)}</div>
    </section>`;
  const q = view.querySelector("#q");
  let timer;
  const refresh = async () => { view.querySelector("#list").innerHTML = tocHtml(await api.list(browse)); };
  view.querySelector("#list").addEventListener("click", async (e) => {
    const b = e.target.closest(".star"); if (!b) return;
    e.preventDefault(); b.disabled = true;
    try {
      const res = await toggleStar(b.dataset.id, b.classList.contains("on"));
      const note = view.querySelector("#star-note");
      note.hidden = !res.demoted; if (res.demoted) note.textContent = `Only three fit on the pass: ${res.demoted.title} came down.`;
      await refresh();
    } catch (ex) { b.disabled = false; }
  });
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { browse.q = q.value; saveBrowse(); refresh(); }, 200); });
  view.querySelector("#sort").addEventListener("change", (e) => { browse.sort = e.target.value; saveBrowse(); refresh(); });
  view.querySelectorAll(".tag").forEach((b) => b.addEventListener("click", () => { browse.tag = browse.tag === b.dataset.tag ? "" : b.dataset.tag; saveBrowse(); renderBook(); }));
}
