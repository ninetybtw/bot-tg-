(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const LIVE = !!(tg && tg.initData);
  if (!LIVE) document.body.classList.add("demo");

  // ---------- утилиты ----------
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const NB = " ";
  const group = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  const int = n => group(String(Math.round(n)));
  const pct = (p, d) => (p * 100).toLocaleString("ru-RU", { maximumFractionDigits: d ?? (p < 0.01 ? 2 : 1) }) + "%";
  const hms = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hap = (kind, style) => { try { const h = tg && tg.HapticFeedback; if (!h) return; if (kind === "n") h.notificationOccurred(style); else if (kind === "s") h.selectionChanged(); else h.impactOccurred(style || "light"); } catch (e) { /* старый клиент */ } };

  let CFG = null, ME = null;
  const cur = () => ME.currency;
  function money(cents, opts = {}) {
    const c = cur();
    const v = cents / 100 * c.rate;
    const d = c.decimals;
    const [a, b] = Math.abs(v).toFixed(d).split(".");
    return `${v < 0 ? "−" : ""}${group(a)}${b ? "," + b : ""}${opts.noSym ? "" : NB + c.symbol}`;
  }
  const tierOf = i => CFG.tiers[i];
  const tcls = t => `t${t.idx}`;
  const tierName = (t, cls = "") => `<span class="tcol ${t.idx === 7 ? "rainbow" : ""} ${cls}">${t.icon} ${esc(t.name)}</span>`;

  // ---------- API ----------
  const READ = new Set(["config", "me", "inventory", "item", "market", "market/mine", "fair", "friends", "rating", "feed",
    "history", "shop", "raffle", "upgrade/quote", "sell/quote", "seen", "ad"]);
  async function api(path, body = {}) {
    if (!LIVE) return window.DemoServer.call(path, body);
    const headers = { "Content-Type": "application/json", Authorization: "tma " + tg.initData };
    if (!READ.has(path)) headers["Idempotency-Key"] = uuid();
    let res;
    try { res = await fetch("/api/" + path, { method: "POST", headers, body: JSON.stringify(body) }); }
    catch (e) { throw { code: "NETWORK", message: "Нет связи. Попробуй ещё раз" }; }
    let data = {};
    try { data = await res.json(); } catch (e) { /* пусто */ }
    if (!res.ok) throw Object.assign({ code: "ERROR", message: "Что-то пошло не так. Попробуй ещё раз" }, data.error || {});
    return data;
  }

  // ---------- каркас ----------
  const ICONS = {
    play: '<svg viewBox="0 0 24 24"><rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M10 18.5h4M9 8h6M9 11.5h6"/></svg>',
    collection: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/></svg>',
    market: '<svg viewBox="0 0 24 24"><path d="M4 9.5 5.5 4h13L20 9.5M4 9.5h16M4 9.5a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0 2.7 2.7 0 0 0 5.3 0M5.5 12v8h13v-8"/></svg>',
    friends: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.8a3.4 3.4 0 0 1 0 6.4M18 14.8c2 .7 3.2 2.4 3.5 5.2"/></svg>',
    more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>',
  };
  const TABS = [["play", "Играть"], ["collection", "Коллекция"], ["market", "Рынок"], ["friends", "Друзья"], ["more", "Ещё"]];
  const app = document.getElementById("app");
  app.innerHTML = `<header class="top" id="top"></header><main class="main" id="main"></main>
    <nav class="nav" id="nav">${TABS.map(([k, t]) => `<button data-act="tab" data-tab="${k}" aria-label="${t}">${ICONS[k]}<span>${t}</span></button>`).join("")}</nav>`;
  const $top = document.getElementById("top"), $main = document.getElementById("main"), $nav = document.getElementById("nav");

  const ui = {
    tab: "play", level: "common", count: 1, busy: false, boardItem: null, energyAt: 0, shownBalance: null,
    col: { min: 0, q: "", fav: false, sort: "rare", overflow: false },
    mk: { tab: "showcase", min: 0, sort: "new" },
    contract: { tier: 0, sel: new Set() },
    up: { sel: new Set(), cents: 0, target: null },
    rating: { scope: "friends", board: "collection" },
    oddsLevel: "common", wheelKind: "daily", items: [],
  };
  try { ui.level = localStorage.getItem("level") || "common"; } catch (e) { /* без хранилища */ }

  // ---------- табло: перекидные цифры ----------
  function flapsHTML(it, opts = {}) {
    const number = typeof it === "string" ? it : it.number;
    const hl = new Set((it && it.highlight) || []);
    const color = it && it.tier ? `var(--t${it.tier.idx})` : "#fff";
    const [dial, ...rest] = number.split(" ");
    let j = 0, k = 0, out = "";
    for (const ch of dial) out += `<span class="flap dial">${esc(ch)}</span>`;
    out += `<span class="flap sep"></span>`;
    for (const ch of rest.join(" ")) {
      if (ch === " ") { out += `<span class="flap sep"></span>`; continue; }
      if (!/\d|•/.test(ch)) { out += `<span class="flap sep">${esc(ch)}</span>`; continue; }
      const isHl = !opts.plain && hl.has(j);
      out += `<span class="flap${isHl ? " hl" : ""}" data-j="${j}" style="${isHl ? `--tcolor:${color};--i:${k++}` : ""}">${esc(ch)}</span>`;
      j++;
    }
    return `<div class="flaps" style="--len:${number.length}">${out}</div>`;
  }
  function skyline() {
    let w = "";
    for (let i = 0; i < 16; i++) w += `<i style="left:${4 + i * 6 + (i % 3)}%;bottom:${8 + (i * 37 % 60)}%;--d:${4 + (i % 5)}s;animation-delay:${(i * 0.7) % 5}s"></i>`;
    return `<div class="sky"><svg viewBox="0 0 400 120" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%"><path d="M0 120V70h30V40h28v30h20V20h34v50h16V55h30v65h12V35h40v85h20V60h26v60h18V45h36v75h22V30h30v90h38V65h0" fill="#0b1430" opacity=".9"/></svg>${w}</div>`;
  }
  function boardHTML(it) {
    const lv = CFG.levels.find(l => l.key === ui.level);
    if (!it) {
      return `${skyline()}<div class="meta"><span>Табло</span><span class="tag" style="--tcol:var(--neon)">${esc(lv.name)}</span></div>
        ${flapsHTML((CFG.number_masks || {})[ME.country] || "+7 ••• •••-••-••", { plain: true })}<div class="foot">Жми «Крутить» — номер появится здесь</div>`;
    }
    return `${skyline()}<div class="meta"><span>${it.flag} ${esc(it.country_name)}</span><span class="tag" style="--tcol:var(--t${it.tier.idx})">${it.tier.icon} ${esc(it.tier.name)}</span></div>
      ${flapsHTML(it)}<div class="foot">${esc(it.rule_name)} · игровой номер${it.copy ? ` · ${it.copy.no} из ${it.copy.of}` : ""}</div>`;
  }
  function animateFlaps(board, it) {
    board.className = "board";
    board.style.removeProperty("--tc");
    board.innerHTML = `${skyline()}<div class="meta"><span>${it.flag} ${esc(it.country_name)}</span><button class="skip" data-act="skip">Пропустить</button></div>
      ${flapsHTML(it, { plain: true })}<div class="foot">крутим…</div>`;
    const digits = [...board.querySelectorAll(".flap[data-j]")];
    const finals = digits.map(d => d.textContent);
    digits.forEach(d => { d.classList.add("flip"); d.textContent = Math.floor(Math.random() * 10); });
    return new Promise(resolve => {
      let done = false, timer = null, idx = 0;
      const shuffle = setInterval(() => digits.forEach((d, i) => { if (i >= idx) d.textContent = Math.floor(Math.random() * 10); }), 70);
      const land = i => { const d = digits[i]; d.classList.remove("flip"); d.textContent = finals[i]; d.classList.add("land"); };
      const finish = () => {
        if (done) return; done = true; clearInterval(shuffle); clearTimeout(timer);
        for (let i = idx; i < digits.length; i++) land(i);
        resolve();
      };
      ui.skip = finish;
      const step = () => {
        if (done) return;
        land(idx); hap("s"); idx++;
        if (idx >= digits.length) return finish();
        timer = setTimeout(step, 115);
      };
      timer = setTimeout(step, 520);
    });
  }

  // ---------- шторка, тосты, полёт денег ----------
  let sheetEl = null, shadeEl = null, sheetClose = null;
  function openSheet(html, onClose) {
    closeSheet(true);
    shadeEl = document.createElement("div"); shadeEl.className = "shade"; shadeEl.dataset.act = "close";
    sheetEl = document.createElement("div"); sheetEl.className = "sheet"; sheetEl.setAttribute("role", "dialog");
    sheetEl.innerHTML = `<div class="grab"></div>${html}`;
    app.append(shadeEl, sheetEl);
    sheetClose = onClose || null;
    requestAnimationFrame(() => requestAnimationFrame(() => { shadeEl && shadeEl.classList.add("open"); sheetEl && sheetEl.classList.add("open"); }));
    try { tg && tg.BackButton && tg.BackButton.show(); } catch (e) { /* */ }
    return sheetEl;
  }
  function closeSheet(instant) {
    if (!sheetEl) return;
    const s = sheetEl, d = shadeEl, cb = sheetClose;
    sheetEl = shadeEl = sheetClose = null;
    if (instant) { s.remove(); d.remove(); } else { s.classList.remove("open"); d.classList.remove("open"); setTimeout(() => { s.remove(); d.remove(); }, 380); }
    try { tg && tg.BackButton && tg.BackButton.hide(); } catch (e) { /* */ }
    if (cb) cb();
  }
  try { tg && tg.BackButton && tg.BackButton.onClick(() => closeSheet()); } catch (e) { /* */ }

  let toastTimer = null;
  function toast(html, opts = {}) {
    app.querySelectorAll(".toast").forEach(t => t.remove());
    clearTimeout(toastTimer);
    const ms = opts.ms || 2800;
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status"); t.style.setProperty("--ms", ms + "ms");
    t.innerHTML = `<div class="grow">${html}</div>${opts.action ? `<button class="btn sm">${esc(opts.action)}</button>` : ""}<i class="tbar"></i>`;
    if (opts.action) t.querySelector("button").onclick = () => { t.remove(); opts.onAction && opts.onAction(); };
    app.append(t);
    toastTimer = setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 260); }, ms);
  }
  function fly(text, from) {
    const target = document.getElementById("balance");
    if (!target || reduced) return;
    const a = app.getBoundingClientRect(), tr = target.getBoundingClientRect();
    const fr = from ? from.getBoundingClientRect() : { left: a.left + a.width / 2 - 30, top: a.top + a.height * 0.45, width: 60, height: 20 };
    const f = document.createElement("div");
    f.className = "fly"; f.textContent = text;
    f.style.left = (fr.left - a.left + fr.width / 2 - 20) + "px"; f.style.top = (fr.top - a.top) + "px";
    app.append(f);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      f.style.transform = `translate(${tr.left - fr.left - fr.width / 2 + 30}px, ${tr.top - fr.top}px) scale(.7)`;
      f.style.opacity = "0";
    }));
    setTimeout(() => f.remove(), 900);
  }
  function fail(e) {
    if (e && e.code === "NOT_ENOUGH_COINS") return noCoins(e.need_cents);
    hap("n", "error");
    toast(esc((e && e.message) || "Нет связи. Попробуй ещё раз"));
  }

  // ---------- шапка, баланс ----------
  function animateBalance(to) {
    const el = document.getElementById("balval");
    if (!el) return;
    const from = ui.shownBalance ?? to;
    ui.shownBalance = to;
    if (from === to || reduced) { el.textContent = money(to); return; }
    const pill = document.getElementById("balance");
    pill.classList.remove("bump"); void pill.offsetWidth; pill.classList.add("bump");
    const t0 = performance.now(), dur = 700;
    const stepf = now => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = money(Math.round(from + (to - from) * e));
      if (k < 1) requestAnimationFrame(stepf);
    };
    requestAnimationFrame(stepf);
  }
  function renderTop() {
    const e = ME.energy;
    $top.innerHTML = `<div class="brand"><b><span class="dot"></span>ДОЗВ<i>ОН</i></b>${LIVE ? "" : '<span class="demo-pill">демо</span>'}</div><div class="sp"></div>
      <button class="pill rub" id="balance" data-act="coins" aria-label="Баланс"><span><span class="val" id="balval">${money(ui.shownBalance ?? ME.balance_cents)}</span>${cur().game_label ? '<span class="lbl">игровые</span>' : ""}</span></button>
      <button class="pill" data-act="odds" aria-label="Энергия"><span class="bolt">⚡</span><span class="val">${e.now}/${e.max}</span>${ME.attempts ? `<span class="val muted">+${ME.attempts}</span>` : ""}</button>`;
    animateBalance(ME.balance_cents);
    const t = ME.today;
    const dot = t.gift || t.wheel_daily || t.wheel_weekly || t.tasks.some(x => x.progress >= x.target && !x.claimed);
    $nav.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", b.dataset.tab === ui.tab);
      b.querySelector(".dot")?.remove();
      if (b.dataset.tab === "play" && dot && ui.tab !== "play") b.insertAdjacentHTML("beforeend", '<i class="dot"></i>');
    });
  }
  async function refresh() {
    ME = await api("me");
    ui.energyAt = Date.now() + ME.energy.next_in * 1000;
    document.body.classList.toggle("noeffects", !!ME.settings.no_effects);
    renderTop();
  }
  function setTab(tab) {
    ui.tab = tab;
    $main.scrollTop = 0;
    renderTop();
    ({ play: renderPlay, collection: renderCollection, market: renderMarket, friends: renderFriends, more: renderMore })[tab]();
  }
  function enter() { $main.classList.remove("enter"); void $main.offsetWidth; $main.classList.add("enter"); }

  // ---------- ИГРАТЬ ----------
  const levelColor = key => ({ common: "var(--neon)", rare: "var(--t2)", epic: "var(--t3)", legendary: "var(--t4)", elite: "var(--t6)" })[key];
  function spinPlan() {
    const lv = CFG.levels.find(l => l.key === ui.level), n = ui.count;
    if (lv.key !== "common") return { e: 0, a: 0, c: n, cost: n * lv.price_cents, lv };
    const e = Math.min(ME.energy.now, n), a = Math.min(ME.attempts, n - e), c = n - e - a;
    return { e, a, c, cost: c * lv.price_cents, lv };
  }
  function spinCostLabel() {
    const p = spinPlan();
    const parts = [];
    if (p.e) parts.push(`⚡${p.e}`);
    if (p.a) parts.push(`🎟${p.a}`);
    if (p.c) parts.push(money(p.cost));
    return !p.c && !p.a ? `Бесплатно · ⚡${p.e}` : parts.join(" + ");
  }
  function pityLine() {
    if (ui.level !== "common") {
      const lv = CFG.levels.find(l => l.key === ui.level);
      return `<div class="pity"><span>От ${esc(tierOf(lv.min_tier).name.toLowerCase())}а · ${esc(lv.goal.label)} <b>${pct(lv.goal.p, 2)}</b></span><span class="grow"></span><span>сегодня ещё ${ME.upper_spins_left}</span></div>`;
    }
    if (ME.starter && ui.count === 5) return `<div class="starter">🎁 Первый ×5 — Редкий или выше гарантирован</div>`;
    const p = ME.pity, hard = CFG.pity.epic_plus.hard;
    const prog = 1 - p.epic_in / hard;
    return `<div class="pity ${p.epic_chance > 0.05 ? "hot" : ""}"><span>Шанс Эпика сейчас <b>${pct(p.epic_chance)}</b></span>
      <div class="bar"><i id="pitybar" style="width:0;background:var(--t3)" data-w="${Math.round(prog * 100)}"></i></div>
      ${ME.luck ? `<span class="badge-luck">✨ ×${String(ME.luck.mult).replace(".", ",")} · ${ME.luck.spins_left}</span>` : `<span>гарантия ≤${p.epic_in}</span>`}</div>`;
  }
  function renderPlay() {
    const t = ME.today, last = ME.last_drop && ME.last_drop.country === ME.country ? ME.last_drop : null, it = ui.boardItem || last;
    const claimable = t.tasks.filter(x => x.progress >= x.target && !x.claimed).length;
    const done = t.tasks.filter(x => x.claimed).length;
    $main.className = "main noscroll";
    $main.innerHTML = `
      <div class="today">
        <button data-act="gift" class="${t.gift ? "ready" : ""}"><b>🎁</b>Подарок</button>
        <button data-act="wheel" class="${t.wheel_daily || t.wheel_weekly ? "ready" : ""}"><b>🎡</b>Колесо</button>
        <button data-act="tasks" class="${claimable ? "ready" : ""}"><b>✅</b>${done}/${t.tasks.length}</button>
        <button data-act="raffle"><b>🎟</b>${t.tickets} бил.</button>
      </div>
      ${adHTML()}
      <div class="ticker" id="ticker"><div class="track"><span class="muted">Эпик+ у друзей и в игре появится здесь</span></div></div>
      <div class="board-slot"><div class="board" id="board">${boardHTML(it)}</div></div>
      ${pityLine()}
      <div class="levels" id="levels">${CFG.levels.map(lv => `<button class="lv ${lv.key === ui.level ? "on" : ""}" data-act="level" data-v="${lv.key}" style="--lc:${levelColor(lv.key)}">
        <span class="n">${esc(lv.name)}</span><span class="p">${money(lv.price_cents)}</span>
        <span class="g">${esc(lv.goal.label)}<b>${pct(lv.goal.p, 2)}</b></span></button>`).join("")}</div>
      <div class="seg">${CFG.counts.map(n => `<button class="${ui.count === n ? "on" : ""}" data-act="count" data-v="${n}">×${n}</button>`).join("")}</div>
      <div class="spin-row"><button class="spin-btn ${ui.level !== "common" ? "upper" : ""}" style="--lc:${levelColor(ui.level)}" data-act="spin" id="spinbtn">КРУТИТЬ${ui.count > 1 ? " ×" + ui.count : ""}<small>${spinCostLabel()}</small></button></div>
      <div class="under"><span id="etimer"></span><button class="link" data-act="odds">Шансы</button></div>`;
    if (it) paintBoard(it, false);
    const bar = document.getElementById("pitybar");
    if (bar) requestAnimationFrame(() => { bar.style.width = bar.dataset.w + "%"; });
    const sel = $main.querySelector(".lv.on");
    if (sel) sel.scrollIntoView({ inline: "center", block: "nearest" });
    tick();
    loadFeed();
  }
  // ---------- реклама ----------
  function adHTML() {
    const a = ME.ad;
    if (!a) return "";
    const fresh = ui.adSeen !== a.id; // показ считаем один раз за запуск игры
    if (fresh) { ui.adSeen = a.id; if (!a.placeholder) api("ad", { id: a.id, kind: "view" }).catch(() => {}); }
    return `<button class="ad ${fresh ? "in" : ""}" data-act="ad" aria-label="Реклама: ${esc(a.title)}"><span class="ad-ic">${esc(a.icon)}</span>
      <span class="ad-body"><b>${esc(a.title)}</b>${a.text ? `<span>${esc(a.text)}</span>` : ""}</span><span class="ad-btn">${esc(a.button)}</span><i class="ad-mark">реклама</i></button>`;
  }
  function openAd() {
    const a = ME.ad;
    if (!a) return;
    hap("i", "light");
    if (!a.placeholder) api("ad", { id: a.id, kind: "click" }).catch(() => {});
    if (!LIVE) return toast(a.placeholder ? "Здесь будет реклама, которую ты поставишь командой /ad в боте" : `Откроется ${esc(a.url)}`);
    try {
      if (/^https:\/\/t\.me\//.test(a.url) && tg.openTelegramLink) tg.openTelegramLink(a.url); else tg.openLink(a.url);
    } catch (e) { location.href = a.url; }
  }

  function paintBoard(it, flash) {
    const board = document.getElementById("board");
    if (!board) return;
    board.className = "board";
    board.innerHTML = boardHTML(it);
    board.style.setProperty("--tc", `color-mix(in srgb, var(--t${it.tier.idx}) 65%, transparent)`);
    if (flash && it.tier.idx >= 1) { void board.offsetWidth; board.classList.add("flash"); }
  }
  async function loadFeed() {
    try {
      const f = await api("feed");
      const el = document.getElementById("ticker");
      if (!el || !f.items.length) return;
      const row = f.items.map(x => `<span class="${x.friend ? "fr" : ""}">${esc(x.name)}${x.me ? " (ты)" : ""} · <span class="t${x.tier.idx}"><span class="tcol">${x.tier.icon}</span></span> <b>${esc(x.number)}</b></span>`).join("");
      el.innerHTML = `<div class="track" style="--dur:${Math.max(18, f.items.length * 6)}s">${row}${row}</div>`;
    } catch (e) { /* лента не обязательна */ }
  }
  function tick() {
    const el = document.getElementById("etimer");
    if (!el || !ME) return;
    const e = ME.energy;
    if (e.now >= e.max) { el.textContent = "⚡ Энергия полная"; return; }
    const left = (ui.energyAt - Date.now()) / 1000;
    if (left <= 0) {
      el.textContent = "⚡ Спин готов";
      if (!ui.busy && !ui.refreshing) { ui.refreshing = true; refresh().then(() => ui.tab === "play" && renderPlay()).finally(() => { ui.refreshing = false; }); }
      return;
    }
    el.textContent = `⚡ +1 через ${hms(left)}`;
  }
  setInterval(tick, 1000);

  function rarityFx(it, el) {
    const idx = it.tier.idx;
    if (idx >= 3) hap("n", "success"); else if (idx >= 1) hap("i", idx >= 2 ? "medium" : "light");
    if (idx >= 4) setTimeout(() => hap("n", "success"), 260);
    if (idx >= 5) [520, 780, 1040].forEach(t => setTimeout(() => hap("i", "heavy"), t));
    if (ME.settings.no_effects || idx < 3 || reduced) return;
    const color = idx === 7 ? "#ffd93d" : getComputedStyle(document.body).getPropertyValue("--t" + idx).trim() || "#fff";
    if (idx === 6) {
      const safe = document.createElement("div"); safe.className = "safe"; app.append(safe); setTimeout(() => safe.remove(), 3100);
    }
    const fx = document.createElement("div");
    fx.className = "fx" + (idx === 7 ? " rainbowfx" : idx >= 5 ? " full" : idx === 4 ? " dim" : "");
    fx.style.setProperty("--c", color);
    fx.innerHTML = '<i class="bg"></i>' + (idx >= 4 ? '<i class="wave"></i><i class="wave"></i><i class="wave"></i>' : "");
    const n = { 3: 34, 4: 54, 5: 80, 6: 90, 7: 110 }[idx];
    const palette = idx === 7 ? ["#ff6b6b", "#ffd93d", "#6bff95", "#6bc5ff", "#c56bff"] : [color, "#ffffff", color];
    for (let i = 0; i < n; i++) {
      const p = document.createElement("i");
      p.className = "p";
      const a = Math.random() * Math.PI * 2, r = 110 + Math.random() * 240;
      p.style.cssText = `--x:${Math.cos(a) * r}px;--y:${Math.sin(a) * r}px;--d:${1200 + Math.random() * 1400}ms;--c:${palette[i % palette.length]};animation-delay:${idx === 6 ? 1.6 : 0}s;width:${5 + Math.random() * 6}px;height:${5 + Math.random() * 6}px`;
      fx.append(p);
    }
    app.append(fx);
    setTimeout(() => fx.remove(), 4600);
  }

  async function doSpin(confirmed = false) {
    if (ui.busy) return;
    const plan = spinPlan();
    if (!confirmed && plan.cost && !(ME.starter && plan.lv.key === "common" && ui.count === 5) &&
      (plan.cost >= CFG.confirm_from_cents || plan.cost > ME.balance_cents * CFG.confirm_balance_share) && plan.cost <= ME.balance_cents) {
      return confirmSpin(plan);
    }
    ui.busy = true;
    const btn = document.getElementById("spinbtn");
    if (btn) { btn.classList.add("busy"); btn.innerHTML = "КРУТИМ…<small>результат уже решён сервером</small>"; }
    hap("i", "medium");
    let res;
    try {
      res = await api("spin", { level: ui.level, count: ui.count, confirmed });
    } catch (e) {
      ui.busy = false;
      if (ui.tab === "play") renderPlay();
      if (e.code === "CONFIRM_REQUIRED") return confirmSpin(plan);
      return fail(e);
    }
    const best = res.drops.reduce((a, b) => (b.tier.idx > a.tier.idx || (b.tier.idx === a.tier.idx && b.price_cents > a.price_cents)) ? b : a);
    const board = document.getElementById("board");
    if (board && !ME.settings.fast) await animateFlaps(board, best);
    ui.skip = null;
    ui.boardItem = best;
    if (best.tier.idx >= 5 && !ME.settings.fast && !reduced) await sleep(450); // пауза перед мифическим
    try { await refresh(); } catch (e) { /* баланс обновится позже */ }
    ui.busy = false;
    if (ui.tab === "play") { renderPlay(); paintBoard(best, true); }
    rarityFx(best);
    await sleep(ME.settings.fast ? 80 : best.tier.idx >= 6 ? 1900 : best.tier.idx >= 4 ? 900 : best.tier.idx >= 2 ? 420 : 160);
    showSpinResult(res, best);
    if (res.level_up) setTimeout(() => toast(`🎉 Новый уровень: <b>${res.player_level}</b>. Спинов за монеты в сутки стало больше`), 600);
    if (res.overflow) setTimeout(() => toast(`📦 ${res.overflow} в переполнении — освободи место в коллекции за 48 часов`, { ms: 4500 }), 900);
    if (res.break_hint) setTimeout(() => toast("☕ Уже 50 спинов сегодня. Может, перерыв?", { ms: 5000 }), 2600);
  }

  function confirmSpin(plan) {
    const lv = plan.lv;
    const sh = openSheet(`<h2>Подтверди покупку</h2>
      <div class="card"><div class="kv"><span>Крутка</span><b>${esc(lv.name)} ×${ui.count}</b></div>
        <div class="kv"><span>Спишется</span><b class="price">${money(plan.cost)}</b></div>
        <div class="kv"><span>Останется</span><b class="mono">${money(ME.balance_cents - plan.cost)}</b></div>
        <div class="kv"><span>${esc(lv.goal.label)}</span><b class="mono">${pct(lv.goal.p, 2)} за крутку</b></div></div>
      <p class="small muted">Шансы одинаковы для всех и видны на экране «Шансы». Отменить крутку после результата нельзя.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn primary" id="cgo">Подтвердить</button></div>`);
    sh.querySelector("#cgo").onclick = () => { closeSheet(true); doSpin(true); };
  }

  function callCard(it, opts = {}) {
    return `<div class="call ${tcls(it.tier)}"><div class="rings"><i></i><i></i><i></i></div>
      <div class="who">Входящий · игровой номер</div>
      <div class="flag">${it.flag}</div><div class="small muted">${esc(it.country_name)}</div>
      ${flapsHTML(it)}
      <div class="rule">${esc(it.rule_name)}</div>
      <div class="facts">${it.one_in ? `<span>Шанс <b>1 из ${int(it.one_in)}</b></span>` : ""}${it.copy ? `<span>Экземпляр <b>${it.copy.no} из ${it.copy.of}</b></span>` : ""}<span>Цена <b>${money(it.price_cents)}</b></span></div>
      ${opts.extra || ""}</div>`;
  }
  const tierHead = t => `<div class="tier-head ${tcls(t)}"><span class="tcol ${t.idx === 7 ? "rainbow" : ""}">${[...(t.icon + " " + t.name)].map((ch, i) => `<span style="--i:${i}">${ch === " " ? "&nbsp;" : esc(ch)}</span>`).join("")}</span></div>`;

  function showSpinResult(res, best) {
    if (res.drops.length === 1) {
      openSheet(`${tierHead(best.tier)}${callCard(best)}
        <div class="actions">
          <button class="btn" data-act="close">В коллекцию</button>
          <button class="btn" data-act="sell-one" data-id="${best.id}">Продать <span class="sub">${money(best.sell_cents)}</span></button>
          <button class="btn" data-act="share" data-id="${best.id}">Показать другу</button>
          <button class="btn primary" data-act="again">Крутить ещё</button>
        </div>`);
      sheetEl._items = res.drops;
      return;
    }
    const cheap = res.drops.filter(d => d.tier.idx < 2);
    const cheapSum = cheap.reduce((a, d) => a + d.sell_cents, 0);
    const rest = [...res.drops].filter(d => d !== best).sort((a, b) => b.tier.idx - a.tier.idx || b.price_cents - a.price_cents);
    openSheet(`${tierHead(best.tier)}${callCard(best)}
      <h3>Ещё ${rest.length} ${rest.length === 2 || rest.length === 4 ? "номера" : "номеров"}</h3><div class="grid3">${rest.map((d, i) => tile(d, { act: "item", i: i + 4 })).join("")}</div>
      <div class="actions">
        ${cheap.length ? `<button class="btn wide" data-act="sell-cheap">Продать простые (${cheap.length}) <span class="sub">${money(cheapSum)}</span></button>` : ""}
        <button class="btn" data-act="share" data-id="${best.id}">Показать другу</button>
        <button class="btn" data-act="close">Забрать всё</button>
        <button class="btn primary wide" data-act="again">Крутить ещё ×${ui.count}</button>
      </div>`);
    sheetEl._items = res.drops;
  }

  // ---------- продажа ----------
  function sellFlow(items, after) {
    const total = items.reduce((a, i) => a + i.sell_cents, 0);
    const top = items.reduce((a, i) => Math.max(a, i.tier.idx), 0);
    if (items.some(i => i.locked)) return toast("🔒 Номер под замком. Сними замок, чтобы продать");
    const go = async (confirmed) => {
      try {
        const r = await api("sell", { ids: items.map(i => i.id), confirmed });
        hap("n", "success");
        fly("+" + money(r.cents));
        await refresh();
        ui.boardItem = ui.boardItem && items.some(i => i.id === ui.boardItem.id) ? null : ui.boardItem;
        toast(`Продано за ${money(r.cents)} · отменить можно 10 минут`, { action: "Отменить", ms: 6000, onAction: () => undoSale(r.sale_id) });
        if (after) after();
      } catch (e) { fail(e); }
    };
    if (top < 3) return go(false);
    const it = items.find(i => i.tier.idx === top);
    const sh = openSheet(`${tierHead(it.tier)}<h2 style="text-align:center">Продать системе?</h2>
      <p class="muted" style="text-align:center">${items.length > 1 ? `${items.length} номеров` : esc(it.number)} за <b class="price">${money(total)}</b> (60% цены). Отменить можно в течение 10 минут.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn danger" id="sgo">Продать</button></div>`);
    sh.querySelector("#sgo").onclick = () => { closeSheet(true); go(true); };
  }
  async function undoSale(id) {
    try { const r = await api("sales/undo", { sale_id: id }); hap("n", "success"); toast(`↩️ Вернули ${r.restored} ${r.restored === 1 ? "номер" : "номера"} в коллекцию`); await refresh(); rerender(); }
    catch (e) { fail(e); }
  }
  function rerender() { ({ play: renderPlay, collection: loadCollection, market: renderMarket, friends: renderFriends, more: renderMore })[ui.tab](); }

  function share(it) {
    const text = it ? `Мне выпал ${it.tier.icon} ${it.tier.name} номер ${it.number}${it.one_in ? ` — шанс 1 из ${it.one_in}` : ""}! Крути и ты:` : "Крути красивые номера вместе со мной:";
    const url = `https://t.me/share/url?url=${encodeURIComponent(ME.ref_link)}&text=${encodeURIComponent(text)}`;
    if (LIVE && tg.openTelegramLink) tg.openTelegramLink(url); else toast("В Telegram откроется выбор чата: карточка дропа и твоя ссылка");
  }
  function noCoins(need) {
    hap("n", "warning");
    openSheet(`<h2>Не хватает ${money(need || 0)}</h2><p class="muted">Монеты можно получить бесплатно:</p>
      <div class="list">
        <button class="li" data-act="tasks" style="--i:0"><span class="ic">✅</span><span class="grow"><b>Задания</b><span class="small muted">до ${money(60000)} за каждое и билет в розыгрыш</span></span></button>
        <button class="li" data-act="wheel" style="--i:1"><span class="ic">🎡</span><span class="grow"><b>Колесо дня</b><span class="small muted">до ${money(1000000)}</span></span></button>
        <button class="li" data-act="bulk" style="--i:2"><span class="ic">💱</span><span class="grow"><b>Продать ниже Редкого</b><span class="small muted">простые номера из коллекции</span></span></button>
        ${ME.stars_enabled ? `<button class="li" data-act="shop" style="--i:3"><span class="ic">⭐</span><span class="grow"><b>Попытки за Stars</b><span class="small muted">спины Обычной без монет</span></span></button>` : ""}
      </div>`);
  }

  // ---------- плитка и коллекция ----------
  function tailHTML(it) {
    const hl = new Set(it.highlight || []);
    const parts = it.number.split(" "), rest = parts.slice(2).join(" ");
    let j = parts[1].length, out = ""; // первая группа после кода страны (у части стран — не код оператора)
    for (const ch of rest) {
      if (/\d/.test(ch)) { out += hl.has(j) ? `<em>${ch}</em>` : ch; j++; } else out += ch === " " ? NB : ch;
    }
    return out;
  }
  function tile(it, opts = {}) {
    const flags = [it.locked ? "🔒" : "", it.state === "listed" ? "🏷" : "", it.state === "overflow" ? "📦" : "", it.favorite ? "☆" : ""].join("");
    return `<button class="tile ${tcls(it.tier)} ${opts.sel ? "sel" : ""}" data-act="${opts.act || "item"}" data-id="${it.id}" style="--i:${opts.i || 0}">
      ${it.is_new && !opts.noNew ? '<span class="new" aria-label="новый"></span>' : ""}
      <span class="ti"><b class="${it.tier.idx === 7 ? "rainbow" : ""}">${it.tier.icon}</b><span>${it.flag}</span></span>
      <span class="tn"><span class="tdial">${esc(it.number.split(" ").slice(0, 2).join(" "))}</span>${tailHTML(it)}</span>
      <span class="tp"><span>${it.copy ? `№${it.copy.no}/${it.copy.of}` : money(it.price_cents)}</span><span class="flags">${flags}</span></span>
    </button>`;
  }
  const FILTERS = [[0, "Все"], [2, "◆ Редкий+"], [3, "⬢ Эпик+"], [4, "★ Легенд.+"]];
  async function renderCollection() {
    $main.className = "main";
    $main.innerHTML = `<div class="row between"><h2>Коллекция</h2><button class="btn sm" data-act="bulk">Продать ниже Редкого</button></div>
      <div id="cstats"><div class="stats"><div class="skel" style="height:52px"></div><div class="skel" style="height:52px"></div><div class="skel" style="height:52px"></div></div></div>
      <div id="cbanners" style="margin-top:10px"></div>
      <div class="chips">${FILTERS.map(([v, t]) => `<button class="chip ${!ui.col.fav && !ui.col.overflow && ui.col.min === v ? "on" : ""}" data-act="cfilter" data-v="${v}">${t}</button>`).join("")}
        <button class="chip ${ui.col.fav ? "on" : ""}" data-act="cfav">☆ Избранное</button></div>
      <div class="row" style="margin-top:8px"><input class="search grow" id="csearch" inputmode="numeric" placeholder="Поиск по цифрам, например 777" value="${esc(ui.col.q)}">
        <button class="btn sm" data-act="csort" style="min-height:42px">${ui.col.sort === "new" ? "Новые" : "Редкие"} ⇅</button></div>
      <div id="cgrid" style="margin-top:12px"><div class="grid3">${Array.from({ length: 9 }, () => '<div class="skel" style="height:92px"></div>').join("")}</div></div>`;
    enter();
    const input = document.getElementById("csearch");
    let deb;
    input.oninput = () => { clearTimeout(deb); deb = setTimeout(() => { ui.col.q = input.value; loadCollection(); }, 300); };
    await loadCollection();
    api("seen").catch(() => {});
  }
  async function loadCollection() {
    const grid = document.getElementById("cgrid");
    if (!grid) return;
    try {
      const c = await api("inventory", { min_tier: ui.col.min, q: ui.col.q, favorites: ui.col.fav, sort: ui.col.sort, overflow: ui.col.overflow });
      ui.items = c.items;
      const s = c.slots;
      document.getElementById("cstats").innerHTML = `<div class="stats">
        <div><b class="${s.used >= s.total ? "bad" : ""}">${s.used} / ${s.total}</b><span>мест</span></div>
        <div><b class="price">${money(c.value_cents)}</b><span>стоимость</span></div>
        <div><b class="ok">+${money(c.week_cents)}</b><span>за неделю</span></div></div>`;
      let banners = "";
      if (s.overflow) banners += `<button class="banner" data-act="coverflow" style="width:100%">📦 В переполнении ${s.overflow} из ${s.overflow_max} · через 48 ч продадутся по 60% <span class="grow"></span><b>${ui.col.overflow ? "Скрыть" : "Показать"}</b></button>`;
      if (ME.last_sale) banners += `<div class="banner info">↩️ Продажа на ${money(ME.last_sale.amount_cents)} <span class="grow"></span><span class="mono" id="undotimer"></span><button class="btn sm" data-act="undo" data-id="${ME.last_sale.id}">Отменить</button></div>`;
      document.getElementById("cbanners").innerHTML = banners;
      undoTick();
      const total = Object.values(c.counts).reduce((a, b) => a + b, 0);
      grid.innerHTML = c.items.length ? `<div class="grid3">${c.items.map((i, n) => tile(i, { i: Math.min(n, 18) })).join("")}</div>`
        : total ? `<div class="empty"><span class="em">🔎</span><b>Ничего не нашлось</b>Попробуй другой фильтр или цифры</div>`
          : `<div class="empty"><span class="em">📱</span><b>Пока пусто</b>Крутни первый спин — номер появится здесь<br><br><button class="btn primary" data-act="tab" data-tab="play">Крутить</button></div>`;
    } catch (e) { grid.innerHTML = `<div class="empty"><b>Нет связи</b>Попробуй ещё раз<br><br><button class="btn" data-act="tab" data-tab="collection">Повторить</button></div>`; }
  }
  function undoTick() {
    const el = document.getElementById("undotimer");
    if (!el || !ME.last_sale) return;
    const left = ME.last_sale.undo_until - Date.now() / 1000;
    if (left <= 0) { ME.last_sale = null; document.getElementById("cbanners").innerHTML = ""; return; }
    el.textContent = hms(left);
    setTimeout(undoTick, 1000);
  }
  const SOURCES = { spin: "из спина", free: "из бесплатного спина", contract: "из «5 в 1»", upgrade: "из улучшения", wheel_weekly: "из колеса недели", raffle: "из розыгрыша", test: "из теста", demo: "из демо" };
  function itemSheet(it) {
    const date = new Date(it.created_at * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
    const inShow = (ME.user.showcase || []).includes(it.id);
    const listed = it.state === "listed";
    openSheet(`${tierHead(it.tier)}${callCard(it)}
      <div class="card" style="margin-top:12px;padding:4px 14px">
        <div class="kv"><span>Узор</span><b>${esc(it.rule_name)}</b></div>
        ${it.copy ? `<div class="kv"><span>Тираж</span><b>экземпляр ${it.copy.no} из ${it.copy.of} · у игроков ${it.copy.in_game}</b></div>` : `<div class="kv"><span>Тираж</span><b>единственный в игре</b></div>`}
        <div class="kv"><span>Выпал</span><b>${date} ${SOURCES[it.source] || ""}</b></div>
        <div class="kv"><span>Цена сейчас</span><b class="price">${money(it.price_cents)}</b></div>
        <div class="kv"><span>Быстрая продажа</span><b class="mono">${money(it.sell_cents)} · 60%</b></div>
        ${it.hold_until ? `<div class="kv"><span>Удержание</span><b>на рынок через ${hms(it.hold_until - Date.now() / 1000)}</b></div>` : ""}
        ${it.state === "overflow" ? `<div class="kv"><span>Переполнение</span><b class="bad">продастся через ${hms(it.overflow_until - Date.now() / 1000)}</b></div>` : ""}
      </div>
      <div class="actions">
        ${listed ? `<button class="btn wide" data-act="tab" data-tab="market" data-mk="mine">🏷 На рынке — управлять лотом</button>` : `
        <button class="btn" data-act="sell-one" data-id="${it.id}" ${it.locked ? "disabled" : ""}>Продать <span class="sub">${money(it.sell_cents)}</span></button>
        <button class="btn" data-act="list" data-id="${it.id}" ${it.hold_until || it.state !== "free" ? "disabled" : ""}>На рынок</button>
        <button class="btn" data-act="to-upgrade" data-id="${it.id}" ${it.locked || it.state !== "free" || ME.settings.no_upgrader ? "disabled" : ""}>Улучшить</button>
        <button class="btn" data-act="to-contract" data-id="${it.id}" ${it.locked || it.state !== "free" ? "disabled" : ""}>5 в 1</button>`}
        <button class="btn" data-act="share" data-id="${it.id}">Показать другу</button>
        <button class="btn" data-act="showcase" data-id="${it.id}">${inShow ? "Убрать с витрины" : "На витрину"}</button>
        <button class="btn" data-act="lock" data-id="${it.id}">${it.locked ? "🔓 Снять замок" : "🔒 Замок"}</button>
        <button class="btn" data-act="fav" data-id="${it.id}">${it.favorite ? "☆ В избранном" : "☆ В избранное"}</button>
      </div>`);
    sheetEl._items = [it];
  }
  async function bulkSheet(mode = "below_rare", maxCents = 0) {
    const sh = openSheet(`<h2>Продать пачкой</h2><p class="small muted">Под замком, от Легендарного и выставленные на рынок не продаются. Отменить можно 10 минут.</p>
      <div class="seg" style="margin:10px 0"><button class="${mode === "below_rare" ? "on" : ""}" data-act="bulk" data-v="below_rare">Ниже Редкого</button>
        <button class="${mode === "cheaper" ? "on" : ""}" data-act="bulk" data-v="cheaper" data-max="${maxCents || 400000}">Дешевле ${money(maxCents || 400000)}</button></div>
      <div id="bulkinfo"><div class="skel" style="height:48px"></div></div>`);
    try {
      const q = await api("sell/quote", { mode, max_cents: maxCents || 400000 });
      if (sheetEl !== sh) return;
      sh.querySelector("#bulkinfo").innerHTML = q.count
        ? `<button class="btn primary block" id="bgo">Продать ${q.count} ${q.count === 1 ? "номер" : q.count < 5 ? "номера" : "номеров"} · ${money(q.cents)}</button>`
        : `<div class="card muted">Таких номеров нет.</div>`;
      const b = sh.querySelector("#bgo");
      if (b) b.onclick = async () => {
        b.disabled = true;
        try {
          const r = await api("sell", { ids: q.ids, confirmed: true });
          closeSheet(); hap("n", "success"); fly("+" + money(r.cents), b);
          await refresh();
          toast(`Продано ${r.sold} за ${money(r.cents)}`, { action: "Отменить", ms: 6000, onAction: () => undoSale(r.sale_id) });
          ui.boardItem = null; rerender();
        } catch (e) { fail(e); b.disabled = false; }
      };
    } catch (e) { fail(e); }
  }
  function listSheet(it) {
    const lo = Math.ceil(it.price_cents * CFG.market.band_pct[0] / 100), hi = Math.floor(it.price_cents * CFG.market.band_pct[1] / 100);
    const step = Math.max(100, Math.round(it.price_cents / 100 / 100) * 100);
    const sh = openSheet(`<h2>Выставить на рынок</h2>${callCard(it)}
      <h3>Цена: от ${money(lo)} до ${money(hi)}</h3>
      <input type="range" id="lp" min="${lo}" max="${hi}" step="${step}" value="${it.price_cents}" aria-label="Цена лота">
      <div class="row between" style="margin-top:4px"><span class="price" id="lpv"></span><span class="small muted" id="lpg"></span></div>
      <p class="small muted">Лот висит ${CFG.market.lot_days} дня. Комиссия ${CFG.market.fee_pct}% уходит из игры${ME.user.vip_until ? ", у тебя VIP — 5%" : ""}.</p>
      <button class="btn primary block" id="lpgo">Выставить</button>`);
    const r = sh.querySelector("#lp");
    const fee = ME.user.vip_until ? CFG.market.fee_vip_pct : CFG.market.fee_pct;
    const upd = () => { const v = +r.value; sh.querySelector("#lpv").textContent = money(v); sh.querySelector("#lpg").textContent = `тебе ${money(v - Math.floor(v * fee / 100))}`; };
    r.oninput = upd; upd();
    sh.querySelector("#lpgo").onclick = async () => {
      try { await api("market/list", { id: it.id, price_cents: +r.value }); closeSheet(); hap("n", "success"); toast("🏷 Лот выставлен"); rerender(); }
      catch (e) { fail(e); }
    };
  }

  // ---------- РЫНОК ----------
  async function renderMarket() {
    $main.className = "main";
    const tabs = [["showcase", "Витрина"], ["mine", "Мои лоты"], ["contract", "5 в 1"]];
    if (!ME.settings.no_upgrader) tabs.push(["upgrade", "Улучшить"]);
    if (!tabs.some(t => t[0] === ui.mk.tab)) ui.mk.tab = "showcase";
    $main.innerHTML = `<h2>Рынок</h2><div class="seg">${tabs.map(([k, t]) => `<button class="${ui.mk.tab === k ? "on" : ""}" data-act="mktab" data-v="${k}">${t}</button>`).join("")}</div>
      <div id="mk" style="margin-top:12px"><div class="list">${Array.from({ length: 5 }, () => '<div class="skel" style="height:62px"></div>').join("")}</div></div>`;
    enter();
    const box = document.getElementById("mk");
    try {
      if (ui.mk.tab === "showcase") await renderShowcase(box);
      else if (ui.mk.tab === "mine") await renderMine(box);
      else if (ui.mk.tab === "contract") await renderContract(box);
      else await renderUpgrade(box);
    } catch (e) { box.innerHTML = `<div class="empty"><b>Нет связи</b>${esc(e.message || "Попробуй ещё раз")}</div>`; }
  }
  function lotRow(l, act, i) {
    return `<div class="li ${tcls(l.tier)}" style="--i:${i}"><span class="ic">${l.flag}</span>
      <span class="grow"><b class="mono" style="font-size:14px">${esc(l.number)}</b>
      <span class="small">${tierName(l.tier)} <span class="muted">· ${esc(l.seller)}${l.copy ? ` · №${l.copy.no}/${l.copy.of}` : ""}</span></span></span>
      <span style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:4px"><span class="price">${money(l.lot_cents)}</span>${act}</span></div>`;
  }
  async function renderShowcase(box) {
    const m = await api("market", { min_tier: ui.mk.min, sort: ui.mk.sort });
    ui.lots = m.lots;
    box.innerHTML = `<div class="chips">${FILTERS.map(([v, t]) => `<button class="chip ${ui.mk.min === v ? "on" : ""}" data-act="mkmin" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="chips" style="margin-top:6px">${[["new", "Новые"], ["cheap", "Дешевле"], ["rare", "Редкие"]].map(([v, t]) => `<button class="chip ${ui.mk.sort === v ? "on" : ""}" data-act="mksort" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="list" style="margin-top:10px">${m.lots.length ? m.lots.map((l, i) => lotRow(l, l.seller_id === ME.user.id ? '<span class="tiny muted">твой лот</span>' : `<button class="btn sm primary" data-act="buy" data-lot="${l.lot_id}">Купить</button>`, Math.min(i, 12))).join("")
        : `<div class="empty"><span class="em">🏪</span><b>Витрина пуста</b>Выставь свой номер из коллекции</div>`}</div>
      <p class="tiny muted" style="margin-top:10px">Цена лота — от 50 до 150% опорной. Купленный номер можно перепродать через 24 часа.</p>`;
  }
  async function renderMine(box) {
    const m = await api("market/mine");
    box.innerHTML = `<h3 style="margin-top:0">Активные лоты</h3><div class="list">${m.active.length ? m.active.map((l, i) => lotRow(l, `<button class="btn sm" data-act="unlist" data-lot="${l.lot_id}">Снять</button>`, i)).join("") : `<div class="empty"><span class="em">🏷</span><b>Нет лотов</b>Открой номер в коллекции и нажми «На рынок»</div>`}</div>
      <h3>Сделки</h3><div class="list">${m.deals.length ? m.deals.map((l, i) => lotRow(l, `<span class="tiny ${l.side === "sell" ? "ok" : "muted"}">${l.side === "sell" ? `продал, тебе ${money(l.lot_cents - (l.fee_cents || 0))}` : "купил"}</span>`, i)).join("") : `<div class="empty small">Сделок пока нет</div>`}</div>`;
  }
  async function renderContract(box) {
    const c = await api("inventory", {});
    ui.items = c.items;
    const free = c.items.filter(i => i.state === "free" && !i.locked && i.tier.idx === ui.contract.tier);
    const t = tierOf(ui.contract.tier), next = tierOf(ui.contract.tier + 1);
    const guaranteed = ui.contract.tier <= CFG.contracts.guaranteed_up_to_tier;
    const n = ui.contract.sel.size;
    box.innerHTML = `<div class="card small">5 номеров одной ступени → 1 случайный номер ступенью выше. До Редкого успех 100%, с Эпика ${CFG.contracts.success_pct}%: при неудаче получишь номер той же ступени. Номера под замком не участвуют.</div>
      <div class="chips" style="margin-top:10px">${CFG.tiers.slice(0, 7).map(x => `<button class="chip ${tcls(x)} ${x.idx === ui.contract.tier ? "on" : ""}" data-act="ctier" data-v="${x.idx}"><span class="tcol">${x.icon}</span> ${esc(x.name)} · ${c.counts[x.idx] || 0}</button>`).join("")}</div>
      <div class="row between" style="margin:12px 0 8px">${tierName(t)}<span class="muted">→ ${guaranteed ? "100%" : CFG.contracts.success_pct + "%"} →</span>${tierName(next)}</div>
      ${free.length ? `<div class="grid3">${free.map((i, k) => tile(i, { act: "csel", sel: ui.contract.sel.has(i.id), noNew: true, i: Math.min(k, 15) })).join("")}</div>` : `<div class="empty"><span class="em">🧩</span><b>Нет свободных номеров этой ступени</b>Крути, чтобы собрать пять</div>`}
      ${free.length ? `<button class="btn primary block" style="margin-top:12px;position:sticky;bottom:4px" data-act="contract-go" ${n === 5 ? "" : "disabled"}>Собрать 5 в 1 · ${n}/5</button>` : ""}`;
  }
  let quoteTimer;
  async function renderUpgrade(box) {
    const c = await api("inventory", {});
    ui.items = c.items;
    const own = c.items.filter(i => i.state === "free" && !i.locked).sort((a, b) => a.price_cents - b.price_cents);
    const sel = own.filter(i => ui.up.sel.has(i.id));
    const stake = sel.reduce((a, i) => a + i.price_cents, 0) + ui.up.cents;
    const targets = CFG.tiers.slice(0, 7).filter(t => CFG.ladder_cents[t.idx] > stake);
    if (!targets.some(t => t.idx === ui.up.target)) ui.up.target = targets.length ? targets[0].idx : null;
    const maxCents = Math.max(0, Math.min(ME.balance_cents, 10000000));
    box.innerHTML = `<div class="card small">Положи до 3 номеров и монеты, выбери цель дороже ставки. Шанс = ставка ÷ цена цели × 0,8, не больше 80%. При неудаче ставка сгорает, ты получаешь 10% монетами и +3% к следующему шансу.</div>
      <h3>Ставка · ${sel.length}/3</h3>
      ${own.length ? `<div class="grid3">${own.slice(0, 30).map((i, k) => tile(i, { act: "usel", sel: ui.up.sel.has(i.id), noNew: true, i: Math.min(k, 15) })).join("")}</div>` : `<div class="empty"><b>Коллекция пуста</b>Сначала покрути</div>`}
      <h3>Монеты к ставке</h3>
      <input type="range" id="ucoins" min="0" max="${maxCents}" step="10000" value="${Math.min(ui.up.cents, maxCents)}" aria-label="Монеты к ставке">
      <div class="row between"><span class="price">${money(ui.up.cents)}</span><span class="small muted">ставка ${money(stake)}</span></div>
      <h3>Цель</h3>
      <div class="chips">${targets.length ? targets.map(t => `<button class="chip ${tcls(t)} ${ui.up.target === t.idx ? "on" : ""}" data-act="utarget" data-v="${t.idx}"><span class="tcol">${t.icon}</span> ${esc(t.name)}</button>`).join("") : '<span class="muted small">Ставка уже дороже всех целей</span>'}</div>
      <div id="uquote" style="margin-top:8px"></div>`;
    const r = document.getElementById("ucoins");
    r.oninput = () => { ui.up.cents = +r.value; clearTimeout(quoteTimer); quoteTimer = setTimeout(() => renderMarket(), 250); };
    loadQuote();
  }
  async function loadQuote() {
    const box = document.getElementById("uquote");
    if (!box) return;
    if ((!ui.up.sel.size && !ui.up.cents) || ui.up.target === null) { box.innerHTML = '<p class="muted small" style="text-align:center">Выбери номера или монеты для ставки</p>'; return; }
    try {
      const q = await api("upgrade/quote", { ids: [...ui.up.sel], cents: ui.up.cents, target: ui.up.target });
      ui.quote = q;
      box.innerHTML = `<div class="chance">${pct(q.chance, 2)}</div>
        <div class="formula">${money(q.stake_cents)} ÷ ${money(q.target_cents)} × 0,8 = ${pct(q.base_chance, 2)}${q.bonus ? ` · бонус +${pct(q.bonus, 0)}` : ""}</div>
        <button class="btn primary block" style="margin-top:12px" data-act="upgrade-go" ${q.left_today > 0 ? "" : "disabled"}>Улучшить</button>
        <p class="small muted" style="text-align:center">Осталось сегодня: ${q.left_today} из ${CFG.upgrader.per_day}</p>`;
    } catch (e) { box.innerHTML = `<p class="small bad" style="text-align:center">${esc(e.message)}</p>`; }
  }
  async function upgradeGo() {
    const q = ui.quote;
    const run = async () => {
      let res;
      try { res = await api("upgrade", { ids: [...ui.up.sel], cents: ui.up.cents, target: ui.up.target, quote_chance: q.chance }); }
      catch (e) { return fail(e); }
      ui.up.sel.clear(); ui.up.cents = 0;
      const sh = openSheet(`<h2 style="text-align:center">Улучшение</h2><div class="chance">${pct(res.chance, 2)}</div>
        <div class="gauge" id="ugauge"><div class="win" style="width:${res.chance * 100}%"></div><div class="arrow" id="uarrow"></div></div>
        <div class="row between"><span class="tiny ok">← успех</span><button class="link small" id="uskip">Пропустить</button><span class="tiny muted">неудача →</span></div>
        <div id="uout" style="margin-top:12px;min-height:40px"></div>`);
      const arrow = sh.querySelector("#uarrow"), gauge = sh.querySelector("#ugauge");
      let done = false;
      const finish = () => {
        if (done) return; done = true;
        arrow.style.transition = "none"; arrow.style.left = (res.roll * 100) + "%";
        const out = sh.querySelector("#uout");
        if (res.success) { gauge.classList.add("win-flash"); hap("n", "success"); rarityFx(res.item); out.innerHTML = `${tierHead(res.item.tier)}${callCard(res.item)}<button class="btn primary block" style="margin-top:12px" data-act="close">Готово</button>`; }
        else { gauge.classList.add("lose"); hap("n", "error"); out.innerHTML = `<div class="card" style="text-align:center"><b>Не повезло.</b><br><span class="muted small">Запчасти: +${money(res.parts_cents)}. Следующий шанс выше на 3%.</span></div><button class="btn block" style="margin-top:12px" data-act="close">Готово</button>`; fly("+" + money(res.parts_cents), gauge); }
        refresh().then(() => ui.tab === "market" && renderMarket()).catch(() => {});
      };
      sh.querySelector("#uskip").onclick = finish;
      if (ME.settings.fast || reduced) return finish();
      // стрелка проходит шкалу и замедляется там, где решил сервер
      const t0 = performance.now(), dur = 3400, target = 1 + res.roll;
      const anim = now => {
        if (done) return;
        const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3.2);
        arrow.style.left = ((target * e) % 1) * 100 + "%";
        if (k < 1) requestAnimationFrame(anim); else finish();
      };
      requestAnimationFrame(anim);
    };
    if (!q.confirm) return run();
    const sh = openSheet(`<h2>Точно улучшить?</h2><p class="muted">В ставке номер ступени Эпик или выше. Если не выйдет, он сгорит. Шанс ${pct(q.chance, 2)}.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn danger" id="ugo">Улучшить</button></div>`);
    sh.querySelector("#ugo").onclick = () => { closeSheet(true); run(); };
  }
  async function contractGo() {
    const chosen = (ui.items || []).filter(i => ui.contract.sel.has(i.id));
    let res;
    try { res = await api("contract", { ids: [...ui.contract.sel] }); } catch (e) { return fail(e); }
    ui.contract.sel.clear();
    const pos = [[-110, -50, -12], [110, -50, 12], [-80, 55, -8], [80, 55, 8], [0, -75, 0]];
    const sh = openSheet(`<h2 style="text-align:center">5 в 1</h2><div class="merge" id="merge">${chosen.map((c, i) => `<div class="m ${tcls(c.tier)}" style="--x:${pos[i][0]}px;--y:${pos[i][1]}px;--r:${pos[i][2]}deg;animation-delay:${i * 80}ms">${c.tier.icon}</div>`).join("")}<div class="core ${tcls(res.item.tier)}" style="--tc:var(--t${res.item.tier.idx})"></div></div><div id="mout"></div>`);
    hap("i", "medium");
    await sleep(ME.settings.fast || reduced ? 0 : 1300);
    if (sheetEl !== sh) return;
    sh.querySelector("#merge").remove();
    sh.querySelector("#mout").innerHTML = `${res.success ? "" : `<p class="muted" style="text-align:center">Не повезло с шансом ${pct(res.chance, 0)} — номер той же ступени</p>`}${tierHead(res.item.tier)}${callCard(res.item)}<button class="btn primary block" style="margin-top:12px" data-act="close">Отлично</button>`;
    rarityFx(res.item);
    sheetEl._items = [res.item];
    refresh().then(() => renderMarket()).catch(() => {});
  }

  // ---------- ДРУЗЬЯ ----------
  async function renderFriends() {
    $main.className = "main";
    $main.innerHTML = `<h2>Друзья</h2><div id="fr"><div class="skel" style="height:150px"></div></div><h3>Рейтинг</h3><div id="rt"></div>`;
    enter();
    try {
      const f = await api("friends");
      const word = n => n === 1 ? "друг" : n < 5 ? "друга" : "друзей";
      document.getElementById("fr").innerHTML = `
        <div class="card"><b>Друг сразу получает ${f.friend_attempts} спина.</b> <span class="muted">Ты — награду, когда он сделает ${f.required_spins} спинов.</span>
          <div class="hash" style="margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.ref_link)}</div>
          <div class="actions"><button class="btn" data-act="copy" data-v="${esc(f.ref_link)}">Скопировать</button><button class="btn primary" data-act="share">Отправить</button></div></div>
        <h3>Награды · засчитано ${f.count}</h3>
        <div class="list">${f.tiers.map((t, i) => `<div class="li" style="--i:${i}"><span class="ic">${f.count >= t.count ? "✅" : "🎁"}</span><span class="grow"><b>${t.count} ${word(t.count)}</b><span class="small muted">${esc(t.title)}</span><div class="bar" style="margin-top:6px"><i data-w="${Math.min(100, f.count / t.count * 100)}"></i></div></span><span class="small muted mono">${Math.min(f.count, t.count)}/${t.count}</span></div>`).join("")}</div>
        <h3>Приглашённые</h3>
        <div class="list">${f.friends.length ? f.friends.map((x, i) => `<div class="li" style="--i:${i}"><span class="ic">${x.qualified ? "✅" : "⏳"}</span><span class="grow"><b>${esc(x.name)}</b><div class="bar" style="margin-top:6px"><i data-w="${x.spins / f.required_spins * 100}"></i></div></span><span class="small muted mono">${x.spins}/${f.required_spins}</span></div>`).join("") : `<div class="empty"><span class="em">🤝</span><b>Пока никого</b>Отправь ссылку — друг получит спины сразу</div>`}</div>`;
      fillBars();
    } catch (e) { document.getElementById("fr").innerHTML = `<div class="empty"><b>Нет связи</b>Попробуй ещё раз</div>`; }
    renderRating();
  }
  function fillBars() { requestAnimationFrame(() => document.querySelectorAll(".bar i[data-w]").forEach(b => { b.style.width = b.dataset.w + "%"; })); }
  async function renderRating() {
    const box = document.getElementById("rt");
    if (!box) return;
    box.innerHTML = `<div class="seg">${[["friends", "Друзья"], ["all", "Все"]].map(([v, t]) => `<button class="${ui.rating.scope === v ? "on" : ""}" data-act="rscope" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="chips" style="margin-top:8px">${[["collection", "Коллекция"], ["rarest", "Самый редкий"], ["level", "Уровень"]].map(([v, t]) => `<button class="chip ${ui.rating.board === v ? "on" : ""}" data-act="rboard" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="list" id="rlist" style="margin-top:10px">${Array.from({ length: 4 }, () => '<div class="skel" style="height:56px"></div>').join("")}</div>`;
    try {
      const r = await api("rating", ui.rating);
      const row = (e, i) => `<div class="li ${e.me ? "me" : ""}" style="--i:${i}"><span class="pos p${e.pos}">${e.pos}</span><span class="grow"><b>${esc(e.name)}${e.me ? " · ты" : ""}</b>
        ${e.item ? `<span class="small ${tcls(e.item.tier)}"><span class="tcol">${e.item.tier.icon}</span> <span class="mono">${esc(e.item.number)}</span></span>` : ""}</span>
        ${e.value_cents !== undefined ? `<span class="price">${money(e.value_cents)}</span>` : ""}${e.level !== undefined ? `<span class="mono">Ур. ${e.level}</span>` : ""}</div>`;
      let html = r.top.map(row).join("");
      if (r.me && r.me.pos > r.top.length) html += row(r.me, r.top.length);
      document.getElementById("rlist").innerHTML = html || `<div class="empty"><b>Пока пусто</b>${ui.rating.scope === "friends" ? "Пригласи друзей, чтобы соревноваться" : "Стань первым"}</div>`;
    } catch (e) { document.getElementById("rlist").innerHTML = `<div class="empty"><b>Нет связи</b></div>`; }
  }

  // ---------- ЕЩЁ ----------
  async function renderMore() {
    $main.className = "main";
    const u = ME.user, st = ME.settings, c = ME.currency;
    $main.innerHTML = `<h2>Профиль</h2>
      <div class="card"><div class="row"><div class="avatar">${esc((u.name || "И")[0])}</div><div class="grow"><b style="font-size:17px">${esc(u.name)}</b>
        <div class="small muted">${int(u.total_spins)} спинов · с нами с ${new Date(u.created_at * 1000).toLocaleDateString("ru-RU")}</div></div>
        <span class="tag" style="--tcol:var(--neon)">Ур. ${u.level}</span></div>
        <div class="bar" style="margin-top:12px"><i data-w="${u.xp / u.xp_need * 100}"></i></div><div class="tiny muted" style="margin-top:4px">${u.xp} / ${u.xp_need} опыта до уровня ${u.level + 1}</div>
        ${u.vip_until || u.badges.length ? `<div class="chips wrap" style="margin-top:10px">${u.vip_until ? `<span class="chip on">👑 VIP до ${new Date(u.vip_until * 1000).toLocaleDateString("ru-RU")}</span>` : ""}${u.badges.map(b => `<span class="chip">🏅 ${esc(b)}</span>`).join("")}</div>` : ""}
        <h3>Витрина</h3><div class="grid3" id="showcase"><div class="skel" style="height:92px"></div><div class="skel" style="height:92px"></div><div class="skel" style="height:92px"></div></div></div>
      <h3>Игра</h3><div class="list">
        <button class="li" data-act="fair" style="--i:0"><span class="ic">🛡</span><span class="grow"><b>Честная игра</b><span class="small muted">проверь любой бросок по зерну</span></span></button>
        <button class="li" data-act="raffle" style="--i:1"><span class="ic">🎟</span><span class="grow"><b>Розыгрыш дня</b><span class="small muted">билеты за задания · ${ME.today.tickets} сегодня</span></span></button>
        <button class="li" data-act="odds" style="--i:2"><span class="ic">📊</span><span class="grow"><b>Шансы</b><span class="small muted">все уровни крутки в процентах</span></span></button>
        <button class="li" data-act="shop" style="--i:3"><span class="ic">⭐</span><span class="grow"><b>Магазин</b><span class="small muted">попытки, удача, VIP, места</span></span></button>
        <button class="li" data-act="history" style="--i:4"><span class="ic">🧾</span><span class="grow"><b>История</b><span class="small muted">последние 20 операций</span></span></button>
      </div>
      <h3>Настройки</h3><div class="card" style="padding:4px 14px">
        <button class="toggle" data-act="country"><span class="grow"><b>Страна и валюта</b><span class="small muted" style="display:block">${c.flag} ${esc(c.name)} · ${esc(c.symbol)}</span></span><span class="muted">›</span></button>
        ${[["fast", "Всегда быстро", "без анимации спина"], ["no_effects", "Без эффектов", "без вспышек и частиц"], ["no_upgrader", "Без улучшения", "скрыть вкладку «Улучшить»"]].map(([k, t, d]) => `<button class="toggle" data-act="setting" data-k="${k}"><span class="grow"><b>${t}</b><span class="small muted" style="display:block">${d}</span></span><span class="sw ${st[k] ? "on" : ""}"></span></button>`).join("")}
      </div>
      <h3>Помощь</h3><div class="list">
        <button class="li" data-act="terms" style="--i:0"><span class="ic">📄</span><span class="grow"><b>Условия</b><span class="small muted">что можно и что нельзя</span></span></button>
        <button class="li" data-act="support" style="--i:1"><span class="ic">💬</span><span class="grow"><b>Поддержка</b><span class="small muted">вопросы по оплате: /paysupport</span></span></button>
      </div>`;
    enter(); fillBars();
    try {
      const col = await api("inventory", {});
      ui.items = col.items;
      const pick = (u.showcase || []).map(id => col.items.find(i => i.id === id)).filter(Boolean);
      const show = pick.length ? pick : col.items.slice(0, 3);
      const el = document.getElementById("showcase");
      if (el) el.innerHTML = show.map((i, k) => tile(i, { noNew: true, i: k })).join("") || '<span class="small muted" style="grid-column:span 3">Лучшие номера появятся здесь. Добавить: карточка номера → «На витрину»</span>';
    } catch (e) { /* витрина не обязательна */ }
  }

  // ---------- шторки ----------
  function wheelSheet(kind) {
    kind = kind || (ME.today.wheel_weekly ? "weekly" : "daily");
    ui.wheelKind = kind;
    const sectors = kind === "weekly" ? CFG.wheel_weekly : CFG.wheel_daily;
    const avail = kind === "weekly" ? ME.today.wheel_weekly : ME.today.wheel_daily;
    const n = sectors.length, R = 100;
    const wlabel = (l, short) => /^[\d ]+$/.test(l) ? money(parseInt(l.replace(/\D/g, ""), 10) * 100, { noSym: short }) : l;
    const colors = ["#16224a", "#1e2e62", "#16224a", "#283c80", "#3a2a10"];
    const paths = sectors.map((s, i) => {
      const a0 = (i / n) * 2 * Math.PI - Math.PI / 2, a1 = ((i + 1) / n) * 2 * Math.PI - Math.PI / 2;
      const x0 = R + R * Math.cos(a0), y0 = R + R * Math.sin(a0), x1 = R + R * Math.cos(a1), y1 = R + R * Math.sin(a1);
      const am = (a0 + a1) / 2, tx = R + 64 * Math.cos(am), ty = R + 64 * Math.sin(am);
      return `<path d="M${R},${R} L${x0},${y0} A${R},${R} 0 0 1 ${x1},${y1} Z" fill="${colors[i % colors.length]}" stroke="#3dff8f" stroke-opacity=".35" data-s="${i}"/>
        <text x="${tx}" y="${ty}" fill="${i === n - 1 ? "#ffc94a" : "#eaf0fc"}" font-family="JetBrains Mono, monospace" font-weight="800" font-size="${wlabel(s.label, true).length > 6 ? 10 : 12}" text-anchor="middle" dominant-baseline="middle" transform="rotate(${am * 180 / Math.PI + 90} ${tx} ${ty})">${esc(wlabel(s.label, true))}</text>`;
    }).join("");
    const sh = openSheet(`<h2>${kind === "weekly" ? "Колесо недели" : "Колесо дня"}</h2>
      <div class="seg" style="margin-bottom:8px"><button class="${kind === "daily" ? "on" : ""}" data-act="wheel" data-v="daily">Дня</button><button class="${kind === "weekly" ? "on" : ""}" data-act="wheel" data-v="weekly">Недели ${ME.today.wheel_weekly ? "●" : `· ${ME.today.task_days}/${5}`}</button></div>
      <p class="small muted">${kind === "weekly" ? "Открывается за задания в 5 днях из 7. Раз в неделю." : "Один бесплатный поворот в сутки, пустых секторов нет."}</p>
      <div class="wheel-wrap"><div class="pin" id="wpin"></div><svg viewBox="-4 -4 208 208" id="wsvg"><circle cx="100" cy="100" r="103" fill="#0a1121" stroke="#3dff8f" stroke-opacity=".5" stroke-width="2"/><g id="wrot" style="transform-origin:100px 100px">${paths}</g><circle cx="100" cy="100" r="15" fill="#3dff8f"/><circle cx="100" cy="100" r="6" fill="#03140a"/></svg></div>
      <table class="odds">${sectors.map(s => `<tr><td>${esc(wlabel(s.label))}</td><td class="mono">${pct(s.p, 0)}</td></tr>`).join("")}</table>
      <button class="btn primary block" style="margin-top:12px" id="wgo" ${avail ? "" : "disabled"}>${avail ? "Крутить колесо" : kind === "weekly" ? (ME.today.wheel_weekly_used ? "Уже крутил на этой неделе" : "Выполняй задания 5 дней из 7") : "Следующий поворот завтра"}</button>`);
    sh.querySelector("#wgo").onclick = async e => {
      e.target.disabled = true;
      try {
        const r = await api("wheel", { kind });
        const rot = sh.querySelector("#wrot"), pin = sh.querySelector("#wpin");
        const seg = 360 / n, target = 360 * 6 - (r.index + 0.5) * seg + (Math.random() - 0.5) * seg * 0.5;
        hap("i", "medium");
        if (ME.settings.fast || reduced) rot.style.transform = `rotate(${target}deg)`;
        else await new Promise(done => {
          const t0 = performance.now(), dur = 4300;
          let last = 0;
          const anim = now => {
            const k = Math.min(1, (now - t0) / dur), ang = target * (1 - Math.pow(1 - k, 4));
            rot.style.transform = `rotate(${ang}deg)`;
            const crossed = Math.floor(ang / seg);
            if (crossed !== last) { last = crossed; pin.classList.remove("tick"); void pin.offsetWidth; pin.classList.add("tick"); hap("s"); }
            if (k < 1) requestAnimationFrame(anim); else done();
          };
          requestAnimationFrame(anim);
        });
        const seg0 = sh.querySelector(`path[data-s="${r.index}"]`);
        if (seg0) { seg0.setAttribute("fill", "#3dff8f"); seg0.setAttribute("fill-opacity", ".35"); }
        hap("n", "success");
        if (r.cents) fly("+" + money(r.cents), sh.querySelector(".wheel-wrap"));
        e.target.textContent = r.item ? `Выпал ${r.item.tier.icon} ${r.item.number}` : `Выпало: ${r.cents ? money(r.cents) : r.attempts ? r.attempts + " спин" : r.label}`;
        if (r.item) rarityFx(r.item);
        await refresh();
      } catch (err) { fail(err); }
    };
  }
  function giftSheet() {
    const t = ME.today, curd = t.gift_day;
    const label = r => typeof r === "number" ? money(r) : `${money(r.cents)} + ${r.attempts} 🎟`;
    const sh = openSheet(`<h2>Подарок дня</h2><p class="small muted">Заходи 7 дней подряд — на 7-й большой подарок. Пропуск начинает серию заново.</p>
      <div class="days">${CFG.gift.map((r, i) => `<div class="${(t.gift ? i < curd - 1 : i < curd) ? "done" : ""} ${t.gift && i === curd - 1 ? "cur" : ""}">День ${i + 1}<b>${label(r)}</b></div>`).join("")}</div>
      <button class="btn primary block" style="margin-top:14px" id="ggo" ${t.gift ? "" : "disabled"}>${t.gift ? `Забрать ${label(CFG.gift[curd - 1])}` : `Завтра: ${label(CFG.gift[curd % 7])}`}</button>`);
    sh.querySelector("#ggo").onclick = async e => {
      e.target.disabled = true;
      try { const r = await api("gift"); hap("n", "success"); fly("+" + money(r.cents), e.target); await refresh(); giftSheet(); }
      catch (err) { fail(err); }
    };
  }
  function tasksSheet() {
    const t = ME.today;
    const row = (x, weekly, i) => `<div class="li" style="--i:${i}"><span class="grow"><b>${esc(x.title)}</b><div class="bar" style="margin-top:6px"><i data-w="${x.progress / x.target * 100}"></i></div><span class="small muted">${x.progress}/${x.target} · +${money(x.cents)}${weekly ? (x.badge ? " и значок" : "") : " и 🎟 билет"}</span></span>
      ${x.claimed ? '<span class="small ok">✓ Получено</span>' : `<button class="btn sm ${x.progress >= x.target ? "primary" : ""}" data-act="task" data-k="${x.key}" ${x.progress >= x.target ? "" : "disabled"}>Забрать</button>`}</div>`;
    openSheet(`<h2>Задания</h2><p class="small muted">Новые каждый день в 00:00 по Москве. Задания в 5 днях из 7 открывают колесо недели (сейчас ${t.task_days}/7).</p>
      <h3>Сегодня</h3><div class="list">${t.tasks.map((x, i) => row(x, false, i)).join("")}</div>
      <h3>Неделя</h3><div class="list">${t.weekly_tasks.map((x, i) => row(x, true, i + 3)).join("")}</div>`);
    fillBars();
  }
  async function raffleSheet() {
    const sh = openSheet(`<h2>Розыгрыш дня</h2><div id="rf"><div class="skel" style="height:160px"></div></div>`);
    try {
      const r = await api("raffle");
      if (sheetEl !== sh) return;
      const prize = p => p.item_tier !== undefined ? `${tierOf(p.item_tier).icon} ${tierOf(p.item_tier).name} номер` : money(p.cents);
      sh.querySelector("#rf").innerHTML = `<div class="stats"><div><b>${r.my_tickets}</b><span>мои билеты</span></div><div><b>${r.total_tickets}</b><span>всего</span></div><div><b>${r.hour_msk}:00</b><span>МСК</span></div></div>
        <p class="small muted">Билеты бесплатные — за выполненные задания, купить их нельзя. Хеш зерна опубликован заранее, само зерно раскрывается после розыгрыша: результат можно пересчитать.</p>
        <h3>Призы</h3><div class="list">${r.prizes.map((p, i) => `<div class="li" style="--i:${i}"><span class="pos p${i + 1}">${i + 1}</span><span class="grow"><b>${prize(p)}</b></span></div>`).join("")}</div>
        <h3>Хеш зерна сегодня</h3><div class="hash">${esc(r.server_hash)}</div>
        ${r.last ? `<h3>Итоги ${esc(r.last.day)}</h3><div class="list">${r.last.winners.length ? r.last.winners.map((w, i) => `<div class="li" style="--i:${i}"><span class="pos p${w.place}">${w.place}</span><span class="grow"><b>${esc(w.name)}</b><span class="small muted">${esc(w.prize)}</span></span></div>`).join("") : '<div class="empty small">Билетов не было</div>'}</div><h3>Раскрытое зерно</h3><div class="hash">${esc(r.last.server_seed)}</div>` : ""}`;
    } catch (e) { fail(e); }
  }
  function oddsSheet() {
    const lv = CFG.levels.find(l => l.key === ui.oddsLevel) || CFG.levels[0];
    const luck = lv.key === "common" && ME.luck;
    const lucky = luck ? applyLuck(lv.odds, ME.luck.mult) : null;
    openSheet(`<h2>Шансы</h2>
      <div class="chips">${CFG.levels.map(l => `<button class="chip ${l.key === lv.key ? "on" : ""}" data-act="oddslevel" data-v="${l.key}">${esc(l.name)}</button>`).join("")}</div>
      <div class="card" style="margin-top:10px"><div class="row between"><b>${esc(lv.name)} · ${money(lv.price_cents)}</b><span class="tag" style="--tcol:${levelColor(lv.key)}">${esc(lv.goal.label)} ${pct(lv.goal.p, 2)}</span></div></div>
      <table class="odds" style="margin-top:8px"><tr><th>Ступень</th><th>Шанс</th><th>1 из</th>${luck ? `<th>Удача ×${String(ME.luck.mult).replace(".", ",")}</th>` : ""}</tr>
      ${lv.odds.map(r => `<tr class="${tcls(tierOf(r.tier))}"><td>${tierName(tierOf(r.tier))}</td><td class="mono">${pct(r.p, 2)}</td><td class="mono">${int(1 / r.p)}</td>${luck ? `<td class="mono">${pct(lucky[r.tier], 2)}</td>` : ""}</tr>`).join("")}</table>
      ${lv.key === "common" ? `<div class="card small" style="margin-top:12px">🛡 Мягкая гарантия: шанс Эпика сейчас <b>${pct(ME.pity.epic_chance)}</b>, гарантирован не позже чем через <b>${ME.pity.epic_in}</b> спинов. С ${CFG.pity.epic_plus.soft}-го спина подряд без Эпика шанс растёт на ${CFG.pity.epic_plus.step_pct} п.п. за спин. Легендарный+ — не позже чем через <b>${ME.pity.legend_in}</b>.</div>`
        : `<div class="card small" style="margin-top:12px">Уровни выше Обычной только за монеты, без энергии, попыток, удачи и гарантий. До ${CFG.levels.length && 20} круток в сутки суммарно.</div>`}
      <p class="small muted">Шансы одинаковы для всех и равны серверным. Результат решает сервер до анимации — его можно проверить на экране «Честная игра». «Шанс 1 из N» на карточке всегда по Обычной. Тираж: Легендарный ${CFG.editions["4"]} экземпляра, Мифический ${CFG.editions["5"]}, остальные номера уникальны.</p>
      <p class="small muted">Энергия: 1 бесплатный спин раз в 3 часа, копится до 3. Спинов за монеты на Обычной — до ${ME.coin_spins_left} сегодня.</p>`);
  }
  function applyLuck(rows, m) {
    const odds = Object.fromEntries(rows.map(r => [r.tier, r.p]));
    const keys = Object.keys(odds).map(Number), top = [...keys].sort((a, b) => odds[b] - odds[a]).slice(0, 2);
    const out = {}; let boosted = 0;
    keys.filter(k => !top.includes(k)).forEach(k => { out[k] = odds[k] * m; boosted += out[k]; });
    const cs = top.reduce((a, k) => a + odds[k], 0);
    top.forEach(k => { out[k] = odds[k] * (1 - boosted) / cs; });
    return out;
  }
  function coinsSheet() {
    const c = cur();
    openSheet(`<h2>Баланс · ${money(ME.balance_cents)}</h2><p class="small muted">Игровые рубли${c.code !== "RUB" ? ` (на экране в ${esc(c.symbol)} по курсу 1 ₽ = ${String(c.rate).replace(".", ",")} ${esc(c.symbol)})` : ""}. Их нельзя купить за деньги и нельзя вывести. Реальные деньги в игре — только ⭐ в магазине.</p>
      <h3>Как получить</h3><div class="list">
        <div class="li" style="--i:0"><span class="ic">⚡</span><span class="grow"><b>Бесплатные спины</b><span class="small muted">раз в 3 часа, номер можно продать</span></span></div>
        <button class="li" data-act="tasks" style="--i:1"><span class="ic">✅</span><span class="grow"><b>Задания</b><span class="small muted">3 в день и билеты в розыгрыш</span></span></button>
        <button class="li" data-act="wheel" style="--i:2"><span class="ic">🎡</span><span class="grow"><b>Колесо дня</b><span class="small muted">${money(50000)}–${money(1000000)}</span></span></button>
        <button class="li" data-act="gift" style="--i:3"><span class="ic">🎁</span><span class="grow"><b>Подарок дня</b><span class="small muted">серия 7 дней</span></span></button>
        <button class="li" data-act="tab" data-tab="friends" style="--i:4"><span class="ic">🤝</span><span class="grow"><b>Друзья</b><span class="small muted">спины и монеты за приглашения</span></span></button></div>
      <h3>Куда потратить</h3><div class="list">
        <div class="li" style="--i:5"><span class="ic">📱</span><span class="grow"><b>Крутки</b><span class="small muted">${CFG.levels.map(l => `${l.name} ${money(l.price_cents)}`).join(" · ")}</span></span></div>
        <button class="li" data-act="tab" data-tab="market" style="--i:6"><span class="ic">🏪</span><span class="grow"><b>Рынок и улучшение</b><span class="small muted">номера других игроков</span></span></button></div>`);
  }
  async function historySheet() {
    const sh = openSheet(`<h2>История</h2><div class="list" id="hl"><div class="skel" style="height:56px"></div></div>`);
    const names = { start: "Старт", spin_common: "Обычная", spin_rare: "Редкая", spin_epic: "Эпическая", spin_legendary: "Легендарная", spin_elite: "Элитная", spin: "Спин", sell: "Продажа", sell_undo: "Отмена продажи", wheel_daily: "Колесо дня", wheel_weekly: "Колесо недели", gift: "Подарок дня", task: "Задание", task_weekly: "Задание недели", referral: "Друзья", invited: "Приглашение", upgrade: "Улучшение", upgrade_parts: "Запчасти", market_buy: "Покупка на рынке", market_sale: "Продажа на рынке", market_fee: "Комиссия рынка", purchase: "Покупка ⭐", refund: "Возврат", admin: "Бонус", raffle: "Розыгрыш", overflow_sold: "Переполнение", vip_daily: "VIP" };
    try {
      const h = await api("history");
      if (sheetEl !== sh) return;
      sh.querySelector("#hl").innerHTML = h.items.length ? h.items.map((x, i) => `<div class="li" style="--i:${i}"><span class="grow"><b>${names[x.reason] || esc(x.reason)}</b><span class="small muted">${new Date(x.created_at * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span></span><span class="price" style="color:${x.delta > 0 ? "var(--neon)" : "var(--fg)"}">${x.delta > 0 ? "+" : ""}${x.currency === "rub" ? money(x.delta) : x.delta + " 🎟"}</span></div>`).join("") : '<div class="empty">Пока пусто</div>';
    } catch (e) { fail(e); }
  }
  async function fairSheet() {
    const sh = openSheet(`<h2>Честная игра</h2><div id="fv"><div class="skel" style="height:200px"></div></div>`);
    try {
      const f = await api("fair");
      if (sheetEl !== sh) return;
      sh.querySelector("#fv").innerHTML = `<p class="small muted">Результат решён до того, как ты нажал. Сервер заранее показывает хеш своего зерна, ты задаёшь своё. Каждый бросок: <span class="mono">u = HMAC-SHA256(server_seed, "client:nonce:0")</span>, первые 52 бита ÷ 2^52, ступень по шансам броска. Сменишь пару — старое зерно раскроется, и любой прошлый бросок можно пересчитать прямо здесь.</p>
        <h3>Хеш текущего зерна сервера</h3><div class="hash">${esc(f.server_hash)}</div>
        <h3>Твоё зерно · бросков ${f.nonce}</h3><div class="row"><input class="search grow" id="cseed" maxlength="32" value="${esc(f.client_seed)}" aria-label="Client seed"><button class="btn sm" id="rot" style="min-height:42px">Сменить пару</button></div>
        <h3>Последние броски</h3><div class="list">${f.rolls.length ? f.rolls.slice(0, 30).map((r, i) => `<div class="li" style="--i:${Math.min(i, 10)}"><span class="ic ${tcls(tierOf(r.tier))}"><span class="tcol">${tierOf(r.tier).icon}</span></span><span class="grow"><b class="mono" style="font-size:13px">${esc(r.number || "")}</b><span class="tiny muted">nonce ${r.nonce} · u = ${r.u0.toFixed(6)}</span><span class="tiny" id="v${r.id}"></span></span>${r.server_seed ? `<button class="btn sm" data-act="verify" data-id="${r.id}">Проверить</button>` : '<span class="tiny muted">зерно скрыто</span>'}</div>`).join("") : '<div class="empty small">Бросков пока нет</div>'}</div>`;
      sheetEl._rolls = f.rolls;
      sh.querySelector("#rot").onclick = async () => {
        try { const r = await api("fair/rotate", { client_seed: sh.querySelector("#cseed").value }); hap("n", "success"); toast("🔓 Старое зерно раскрыто — прошлые броски можно проверить"); fairSheet(); }
        catch (e) { fail(e); }
      };
    } catch (e) { fail(e); }
  }
  async function verifyRoll(id) {
    const r = (sheetEl._rolls || []).find(x => x.id === id);
    const out = document.getElementById("v" + id);
    if (!r || !out) return;
    try {
      const u = await hmacRoll(r.server_seed, r.client_seed, r.nonce, 0);
      const hash = await sha256hex(r.server_seed);
      let acc = 0, tier = null;
      const keys = Object.keys(r.odds).map(Number).sort((a, b) => a - b);
      if (keys.length && r.action === "spin") { for (const t of keys) { acc += r.odds[t]; if (u < acc) { tier = t; break; } } if (tier === null) tier = keys[keys.length - 1]; }
      const okHash = hash === r.server_hash, okU = Math.abs(u - r.u0) < 1e-9, okT = r.action !== "spin" || tier === r.tier;
      out.innerHTML = okHash && okU && okT ? `<span class="ok">✓ Совпало: хеш зерна, u = ${u.toFixed(6)}${r.action === "spin" ? ", " + tierOf(tier).name : ""}</span>` : `<span class="bad">✗ Не совпало</span>`;
      hap("n", okHash && okU && okT ? "success" : "error");
    } catch (e) { out.innerHTML = '<span class="bad">Проверка недоступна в этом браузере</span>'; }
  }
  async function hmacRoll(serverHex, client, nonce, i) {
    const key = await crypto.subtle.importKey("raw", hexToBytes(serverHex), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${client}:${nonce}:${i}`)));
    const hex = [...sig].map(b => b.toString(16).padStart(2, "0")).join("");
    return parseInt(hex.slice(0, 13), 16) / 2 ** 52;
  }
  async function sha256hex(hex) { const d = new Uint8Array(await crypto.subtle.digest("SHA-256", hexToBytes(hex))); return [...d].map(b => b.toString(16).padStart(2, "0")).join(""); }
  function hexToBytes(hex) { const a = new Uint8Array(hex.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(hex.substr(i * 2, 2), 16); return a; }
  function countrySheet(first) {
    const all = CFG.currency.countries;
    const sug = ME.country;
    openSheet(`<h2>${first ? "Где ты играешь?" : "Страна и валюта"}</h2><p class="small muted">Номера будут выпадать твоей страны, а цены покажем в твоей валюте по игровому курсу. Шансы и баланс от страны не зависят. Сменить страну можно раз в 30 дней.</p>
      ${first ? `<button class="btn primary block" data-act="setcountry" data-v="${sug}" style="margin:6px 0 14px">Да, ${all[sug].flag} ${esc(all[sug].name)} · ${esc(all[sug].symbol)}</button><h3>Другая страна</h3>` : ""}
      ${!first && ME.country_change_after ? `<div class="banner">Следующая смена с ${new Date(ME.country_change_after * 1000).toLocaleDateString("ru-RU")}</div>` : ""}
      <div class="list">${Object.entries(all).map(([code, c], i) => `<button class="li" data-act="setcountry" data-v="${code}" style="--i:${i}"><span class="ic">${c.flag}</span><span class="grow"><b>${esc(c.name)}</b><span class="small muted">1 000 ₽ = ${group(String((1000 * c.rate).toFixed(c.decimals))).replace(".", ",")} ${esc(c.symbol)}</span></span>${code === ME.country ? '<span class="ok">✓</span>' : ""}</button>`).join("")}</div>`);
  }
  function termsSheet() {
    openSheet(`<h2>Условия</h2><div class="card small" style="line-height:1.6">
      • Баланс — игровые рубли (на экране в валюте твоей страны). Их нельзя купить за деньги и нельзя вывести.<br>
      • Номера сгенерированы игрой и помечены «игровой номер». Это не SIM-карты: их нельзя купить или проверить по базам операторов. Совпадение с реальным номером случайно.<br>
      • Шансы одинаковы для всех и видны на экране «Шансы». Любой бросок можно проверить на экране «Честная игра».<br>
      • За Telegram Stars продаются только попытки, удача, VIP и места: не больше 500 ⭐ в месяц, запас попыток до 100.<br>
      • Продажу системе можно отменить в течение 10 минут, 5 раз в сутки.<br>
      • Уведомления не чаще 2 в сутки и не с 21:00 до 8:00. После 50 спинов в сутки игра предложит перерыв.</div>`);
  }
  async function shopSheet() {
    const sh = openSheet(`<h2>Магазин ⭐</h2><div id="sp"><div class="skel" style="height:200px"></div></div>`);
    try {
      const s = await api("shop");
      if (sheetEl !== sh) return;
      ui.products = s.products;
      if (!s.enabled) { sh.querySelector("#sp").innerHTML = `<div class="empty"><span class="em">⭐</span><b>Магазин откроется позже</b>Всё в игре можно получить бесплатно</div>`; return; }
      const warn = s.month_spent >= s.month_cap * s.warn_at_pct / 100;
      sh.querySelector("#sp").innerHTML = `<div class="card small"><div class="row between"><span class="muted">Потрачено в этом месяце</span><b class="mono">${s.month_spent} / ${s.month_cap} ⭐</b></div><div class="bar" style="margin-top:6px"><i data-w="${Math.min(100, s.month_spent / s.month_cap * 100)}" style="background:var(--gold)"></i></div>${warn ? '<div class="small" style="color:var(--gold);margin-top:6px">Почти достигнут месячный лимит</div>' : ""}</div>
        <div class="list" style="margin-top:8px">${s.products.map((p, i) => `<div class="li" style="--i:${i}"><span class="ic">${p.luck && !p.attempts ? "✨" : p.vip_days ? "👑" : p.slots ? "📦" : "🎟"}</span><span class="grow"><b>${esc(p.title)}</b><span class="small muted">${esc(p.desc)}</span></span><button class="btn sm" data-act="buy-star" data-k="${p.key}">${p.stars} ⭐</button></div>`).join("")}</div>
        <p class="small muted">Монеты и номера за звёзды не продаются. Попытки и удача работают только на Обычной.</p>`;
      fillBars();
    } catch (e) { fail(e); }
  }
  function buyStar(key) {
    const p = (ui.products || []).find(x => x.key === key);
    if (!p) return;
    const common = CFG.levels[0];
    const luckTable = p.luck ? `<table class="odds" style="margin-top:8px"><tr><th>Ступень</th><th>Обычно</th><th>С удачей</th></tr>${common.odds.map(r => `<tr class="${tcls(tierOf(r.tier))}"><td>${tierName(tierOf(r.tier))}</td><td class="mono">${pct(r.p, 2)}</td><td class="mono">${pct(applyLuck(common.odds, p.luck)[r.tier], 2)}</td></tr>`).join("")}</table>` : "";
    const sh = openSheet(`<h2>${esc(p.title)}</h2><p class="muted">${esc(p.desc)}.</p>${luckTable}
      <p class="small muted">Покупка выдаётся сразу после оплаты и окончательна. Условия: /terms.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn primary" id="paygo">Купить за ${p.stars} ⭐</button></div>`);
    sh.querySelector("#paygo").onclick = async () => {
      try {
        const r = await api("shop/invoice", { key });
        if (r.demo) { await api("shop/demo_pay", { key }); closeSheet(); hap("n", "success"); toast(`✅ ${esc(p.title)} — в демо звёзды не списываются`); await refresh(); return; }
        tg.openInvoice(r.link, async status => {
          if (status === "paid") { closeSheet(); hap("n", "success"); toast(`✅ Получено: ${esc(p.title)}`); await sleep(900); await refresh(); rerender(); }
          else if (status === "failed") toast("Оплата не прошла");
        });
      } catch (e) { fail(e); }
    };
  }

  // ---------- действия ----------
  const findItem = id => [...(sheetEl && sheetEl._items || []), ...(ui.items || []), ...(ui.boardItem ? [ui.boardItem] : [])].find(i => i.id === id);
  const actions = {
    tab: el => { closeSheet(true); if (el.dataset.mk) ui.mk.tab = el.dataset.mk; hap("s"); setTab(el.dataset.tab); },
    close: () => closeSheet(),
    skip: () => ui.skip && ui.skip(),
    spin: () => doSpin(),
    again: () => { closeSheet(true); if (ui.tab !== "play") setTab("play"); setTimeout(() => doSpin(), 60); },
    level: el => { ui.level = el.dataset.v; try { localStorage.setItem("level", ui.level); } catch (e) { /* */ } hap("s"); renderPlay(); },
    count: el => { ui.count = +el.dataset.v; hap("s"); renderPlay(); },
    coins: () => coinsSheet(),
    odds: () => { ui.oddsLevel = ui.level; oddsSheet(); },
    oddslevel: el => { ui.oddsLevel = el.dataset.v; oddsSheet(); },
    wheel: el => wheelSheet(el && el.dataset.v),
    gift: () => giftSheet(),
    tasks: () => tasksSheet(),
    raffle: () => raffleSheet(),
    fair: () => fairSheet(),
    verify: el => verifyRoll(+el.dataset.id),
    shop: () => shopSheet(),
    history: () => historySheet(),
    terms: () => termsSheet(),
    country: () => countrySheet(false),
    setcountry: async el => {
      try { await api("country", { country: el.dataset.v }); closeSheet(); await refresh(); ui.shownBalance = ME.balance_cents; renderTop(); rerender(); const c = CFG.currency.countries[el.dataset.v]; ui.boardItem = null; if (ui.tab === "play") renderPlay(); toast(`${c.flag} Номера: ${esc(c.name)} · цены в ${esc(c.symbol)}`); }
      catch (e) { fail(e); }
    },
    task: async el => {
      try { const r = await api("task", { key: el.dataset.k }); hap("n", "success"); fly("+" + money(r.cents), el); await refresh(); tasksSheet(); }
      catch (e) { fail(e); }
    },
    "sell-one": el => { const it = findItem(+el.dataset.id); if (it) { closeSheet(true); sellFlow([it], () => rerender()); } },
    "sell-cheap": () => { const items = (sheetEl._items || []).filter(d => d.tier.idx < 2); closeSheet(true); sellFlow(items, () => rerender()); },
    undo: el => undoSale(+el.dataset.id),
    share: el => share(el.dataset.id ? findItem(+el.dataset.id) : null),
    item: el => { const it = findItem(+el.dataset.id); if (it) itemSheet(it); },
    fav: async el => { try { const r = await api("favorite", { id: +el.dataset.id }); const it = findItem(+el.dataset.id); if (it) { it.favorite = r.favorite; itemSheet(it); } hap("s"); if (ui.tab === "collection") loadCollection(); } catch (e) { fail(e); } },
    lock: async el => {
      const it = findItem(+el.dataset.id); if (!it) return;
      try { const r = await api("lock", { id: it.id, locked: !it.locked, confirm: true }); it.locked = r.locked; hap("i", "medium"); toast(r.locked ? "🔒 Под замком: не продастся случайно" : "🔓 Замок снят"); itemSheet(it); if (ui.tab === "collection") loadCollection(); } catch (e) { fail(e); }
    },
    showcase: async el => {
      const id = +el.dataset.id; let ids = [...(ME.user.showcase || [])];
      ids = ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id].slice(-3);
      try { const r = await api("showcase", { ids }); ME.user.showcase = r.showcase; hap("s"); toast(ids.includes(id) ? "⭐ На витрине профиля" : "Убран с витрины"); const it = findItem(id); if (it) itemSheet(it); } catch (e) { fail(e); }
    },
    list: el => { const it = findItem(+el.dataset.id); if (it) listSheet(it); },
    "to-upgrade": el => { ui.up.sel = new Set([+el.dataset.id]); ui.mk.tab = "upgrade"; closeSheet(true); setTab("market"); },
    "to-contract": el => { const it = findItem(+el.dataset.id); ui.contract.tier = it ? it.tier.idx : 0; ui.contract.sel = new Set([+el.dataset.id]); ui.mk.tab = "contract"; closeSheet(true); setTab("market"); },
    bulk: el => bulkSheet(el && el.dataset.v || "below_rare", el && el.dataset.max ? +el.dataset.max : 0),
    cfilter: el => { ui.col.min = +el.dataset.v; ui.col.fav = false; ui.col.overflow = false; renderCollection(); },
    cfav: () => { ui.col.fav = !ui.col.fav; ui.col.overflow = false; renderCollection(); },
    csort: () => { ui.col.sort = ui.col.sort === "new" ? "rare" : "new"; renderCollection(); },
    coverflow: () => { ui.col.overflow = !ui.col.overflow; renderCollection(); },
    mktab: el => { ui.mk.tab = el.dataset.v; hap("s"); renderMarket(); },
    mkmin: el => { ui.mk.min = +el.dataset.v; renderMarket(); },
    mksort: el => { ui.mk.sort = el.dataset.v; renderMarket(); },
    buy: el => {
      const l = (ui.lots || []).find(x => x.lot_id === +el.dataset.lot);
      if (!l) return;
      const sh = openSheet(`${tierHead(l.tier)}${callCard(l)}<p class="muted small" style="text-align:center">Продавец ${esc(l.seller)} · у тебя ${money(ME.balance_cents)}. Купленный номер можно перепродать через 24 часа.</p>
        <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn primary" id="bgo">Купить <span class="sub">${money(l.lot_cents)}</span></button></div>`);
      sh.querySelector("#bgo").onclick = async () => { try { await api("market/buy", { lot_id: l.lot_id }); closeSheet(); hap("n", "success"); toast("📲 Номер в твоей коллекции"); await refresh(); renderMarket(); } catch (e) { fail(e); } };
    },
    unlist: async el => { try { await api("market/cancel", { lot_id: +el.dataset.lot }); toast("Лот снят"); renderMarket(); } catch (e) { fail(e); } },
    ctier: el => { ui.contract.tier = +el.dataset.v; ui.contract.sel.clear(); renderMarket(); },
    csel: el => { const id = +el.dataset.id, s = ui.contract.sel; if (s.has(id)) s.delete(id); else if (s.size < 5) s.add(id); else return toast("Уже выбрано 5"); hap("s"); renderMarket(); },
    "contract-go": () => contractGo(),
    usel: el => { const id = +el.dataset.id, s = ui.up.sel; if (s.has(id)) s.delete(id); else if (s.size < 3) s.add(id); else return toast("Не больше 3 номеров"); hap("s"); renderMarket(); },
    utarget: el => { ui.up.target = +el.dataset.v; hap("s"); renderMarket(); },
    "upgrade-go": () => upgradeGo(),
    rscope: el => { ui.rating.scope = el.dataset.v; renderRating(); },
    rboard: el => { ui.rating.board = el.dataset.v; renderRating(); },
    copy: async el => { try { await navigator.clipboard.writeText(el.dataset.v); toast("Ссылка скопирована"); } catch (e) { toast("Не получилось скопировать — зажми ссылку"); } },
    setting: async el => { const k = el.dataset.k; try { ME.settings = await api("settings", { [k]: !ME.settings[k] }); document.body.classList.toggle("noeffects", !!ME.settings.no_effects); hap("s"); renderMore(); } catch (e) { fail(e); } },
    ad: () => openAd(),
    support: () => { const bot = (ME.ref_link.match(/t\.me\/([^/?]+)/) || [])[1]; if (LIVE && bot) tg.openTelegramLink(`https://t.me/${bot}`); else toast("Напиши /paysupport в чате с ботом"); },
    "buy-star": el => buyStar(el.dataset.k),
  };
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-act]");
    if (!el || !app.contains(el) || el.disabled) return;
    const fn = actions[el.dataset.act];
    if (fn) fn(el, e);
  });

  // ---------- старт ----------
  (async function boot() {
    if (tg) {
      try {
        tg.ready(); tg.expand();
        tg.setHeaderColor && tg.setHeaderColor("#0a1121");
        tg.setBackgroundColor && tg.setBackgroundColor("#050913");
        tg.disableVerticalSwipes && tg.disableVerticalSwipes();
        const inset = tg.contentSafeAreaInset && tg.contentSafeAreaInset.top;
        if (inset) document.documentElement.style.setProperty("--tg-top", inset + "px");
      } catch (e) { /* старый клиент Telegram */ }
    }
    $main.innerHTML = '<div class="empty"><span class="em">📱</span><b>Набираем номер…</b></div>';
    try {
      CFG = await api("config");
      await refresh();
      if (!CFG.levels.some(l => l.key === ui.level)) ui.level = "common";
      if (ME.starter) ui.count = 5;
      setTab("play");
      if (!ME.country_confirmed) setTimeout(() => countrySheet(true), 400);
    } catch (e) {
      $main.innerHTML = `<div class="empty"><b>Не удалось загрузить</b>${esc(e.message || "")}<br><br><button class="btn primary" onclick="location.reload()">Повторить</button></div>`;
    }
  })();
})();
