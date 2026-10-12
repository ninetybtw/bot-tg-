(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const LIVE = !!(tg && tg.initData);
  if (!LIVE) document.body.classList.add("demo");

  // ---------- утилиты ----------
  const fmt = n => Number(n || 0).toLocaleString("ru-RU");
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const COIN = '<span class="coin" aria-hidden="true"></span>';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pct = p => (p * 100).toLocaleString("ru-RU", { maximumFractionDigits: p < 0.01 ? 2 : 1 }) + "%";
  const hms = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`; };
  const hap = (type, style) => { try { if (!tg || !tg.HapticFeedback) return; if (type === "n") tg.HapticFeedback.notificationOccurred(style); else if (type === "s") tg.HapticFeedback.selectionChanged(); else tg.HapticFeedback.impactOccurred(style || "light"); } catch (e) { /* старый клиент */ } };

  async function api(path, body = {}) {
    if (!LIVE) return window.DemoServer.call(path, body);
    let res;
    try {
      res = await fetch("/api/" + path, { method: "POST", headers: { "Content-Type": "application/json", Authorization: "tma " + tg.initData }, body: JSON.stringify(body) });
    } catch (e) {
      throw { message: "Нет связи. Попробуй ещё раз", code: "network" };
    }
    let data = {};
    try { data = await res.json(); } catch (e) { /* пустой ответ */ }
    if (!res.ok) throw Object.assign({ message: data.error || "Что-то пошло не так. Попробуй ещё раз" }, data);
    return data;
  }

  // ---------- состояние ----------
  let S = null;
  const ui = {
    tab: "play", scale: "phone", mult: 1, busy: false, boardItem: null, energyAt: 0,
    col: { min: 0, q: "", fav: false },
    mk: { tab: "showcase", min: 0, sort: "new" },
    contract: { tier: 0, sel: new Set() },
    up: { sel: new Set(), coins: 0, target: null },
    rating: { scope: "friends", kind: "value" },
    oddsScale: "phone",
  };

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

  // ---------- фрагменты разметки ----------
  const numBlock = (number, inner) => `<div class="num" style="--len:${number.length}">${inner || numHTML(number)}</div>`;
  function numHTML(number) {
    const [dial, op, ...rest] = number.split(" ");
    return `<span class="dial">${esc(dial)}</span> <span class="op">${esc(op)}</span> ${esc(rest.join(" "))}`;
  }
  const tierName = t => `<span class="tcol">${t.icon} ${esc(t.name)}</span>`;
  function tile(it, opts = {}) {
    const short = it.number.split(" ").slice(2).join(" ");
    return `<button class="tile t${it.tier.idx} ${opts.sel ? "sel" : ""}" data-act="${opts.act || "item"}" data-id="${it.id}">
      ${it.is_new && !opts.noNew ? '<span class="new" aria-label="новый"></span>' : ""}
      <span class="ti"><b>${it.tier.icon}</b><span>${it.flag}${it.favorite ? " ★" : ""}</span></span>
      <span class="tn"><span class="tdial">${esc(it.dial)} ${esc(it.op)}</span>${esc(short)}</span>
      <span class="tp">${it.status === "listed" ? '<span class="badge">на рынке</span>' : `${COIN}${fmt(it.price)}`}</span>
    </button>`;
  }
  function callCard(it, cls = "") {
    return `<div class="call t${it.tier.idx} ${cls}"><div class="rings"></div>
      <div class="who">Входящий · игровой номер</div>
      <div class="flag">${it.flag}</div><div class="small muted">${esc(it.country_name)}</div>
      ${numBlock(it.number)}
      <div class="facts">${it.chance ? `<span>Шанс <b>1 из ${fmt(it.chance)}</b></span>` : ""}<span>Цена <b>${fmt(it.price)}</b> ${COIN}</span></div>
    </div>`;
  }
  const tierHead = it => `<div class="tier-head t${it.tier.idx}">${tierName(it.tier)}</div>`;
  const empty = (title, text) => `<div class="empty"><b>${title}</b>${text}</div>`;

  // ---------- шторка, тосты ----------
  let sheetEl = null, shadeEl = null, sheetClose = null;
  function openSheet(html, onClose) {
    closeSheet(true);
    shadeEl = document.createElement("div"); shadeEl.className = "shade"; shadeEl.dataset.act = "close";
    sheetEl = document.createElement("div"); sheetEl.className = "sheet"; sheetEl.setAttribute("role", "dialog");
    sheetEl.innerHTML = `<div class="grab"></div>${html}`;
    app.append(shadeEl, sheetEl);
    sheetClose = onClose || null;
    requestAnimationFrame(() => { shadeEl.classList.add("open"); sheetEl.classList.add("open"); });
    if (tg && tg.BackButton) tg.BackButton.show();
    return sheetEl;
  }
  function closeSheet(instant) {
    if (!sheetEl) return;
    const s = sheetEl, d = shadeEl, cb = sheetClose;
    sheetEl = shadeEl = sheetClose = null;
    if (instant) { s.remove(); d.remove(); } else { s.classList.remove("open"); d.classList.remove("open"); setTimeout(() => { s.remove(); d.remove(); }, 260); }
    if (tg && tg.BackButton) tg.BackButton.hide();
    if (cb) cb();
  }
  if (tg && tg.BackButton) tg.BackButton.onClick(() => closeSheet());

  let toastTimer = null;
  function toast(html, opts = {}) {
    app.querySelectorAll(".toast").forEach(t => t.remove());
    clearTimeout(toastTimer);
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status");
    t.innerHTML = `<div class="grow">${html}</div>${opts.action ? `<button class="btn sm">${esc(opts.action)}</button>` : ""}`;
    if (opts.action) t.querySelector("button").onclick = () => { t.remove(); opts.onAction && opts.onAction(); };
    app.append(t);
    toastTimer = setTimeout(() => t.remove(), opts.ms || 2600);
  }
  function fly(text) {
    const anchor = document.getElementById("coins");
    if (!anchor) return;
    const r = anchor.getBoundingClientRect(), a = app.getBoundingClientRect();
    const f = document.createElement("div");
    f.className = "fly"; f.textContent = text;
    f.style.left = (r.left - a.left + 8) + "px"; f.style.top = (r.bottom - a.top + 2) + "px";
    app.append(f); setTimeout(() => f.remove(), 1000);
  }
  function fail(e) {
    if (e && e.code === "no_coins") return noCoins(e.need);
    hap("n", "error");
    toast(esc((e && e.message) || "Нет связи. Попробуй ещё раз"));
  }

  // ---------- шапка и меню ----------
  function renderTop() {
    const u = S.user;
    $top.innerHTML = `<div class="brand"><span>ДОЗВ<i>ОН</i></span>${LIVE ? "" : '<span class="demo-pill">демо</span>'}</div><div class="sp"></div>
      <button class="stat" id="coins" data-act="coins">${COIN}${fmt(u.coins)}</button>
      <button class="stat energy" data-act="odds"><span class="bolt">⚡</span>${u.energy}/${u.energy_max}${u.spins ? ` <span class="muted">+${u.spins}</span>` : ""}</button>`;
    const dot = S.today.gift || S.today.wheel || S.today.tasks.some(t => t.progress >= t.target && !t.claimed);
    $nav.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", b.dataset.tab === ui.tab);
      b.querySelector(".dot")?.remove();
      if (b.dataset.tab === "play" && dot && ui.tab !== "play") b.insertAdjacentHTML("beforeend", '<i class="dot"></i>');
    });
  }
  function setTab(tab) {
    ui.tab = tab;
    $main.scrollTop = 0;
    renderTop();
    ({ play: renderPlay, collection: renderCollection, market: renderMarket, friends: renderFriends, more: renderMore })[tab]();
  }
  async function refresh() {
    S = await api("state");
    ui.energyAt = Date.now() + S.user.next_energy_in * 1000;
    document.body.classList.toggle("noeffects", !!S.user.settings.no_effects);
    renderTop();
    if (ui.tab === "play" && !ui.busy) renderPlay();
  }

  // ---------- ИГРАТЬ ----------
  function spinCost() {
    const u = S.user, n = ui.mult;
    if (ui.scale === "premium") return `${fmt(500 * n)} ${COIN}`;
    let e = u.energy, s = u.spins, c = 0, ue = 0, us = 0;
    for (let i = 0; i < n; i++) { if (e > 0) { e--; ue++; } else if (s > 0) { s--; us++; } else c++; }
    const parts = [];
    if (ue) parts.push(`⚡${ue}`);
    if (us) parts.push(`🎟${us}`);
    if (c) parts.push(`${fmt(c * 100)} ${COIN}`);
    return c === 0 && us === 0 ? `Бесплатно · ⚡${ue}` : parts.join(" + ");
  }
  function boardHTML(it) {
    if (!it) {
      const c = S.countries.find(x => x.code === S.user.country);
      return `<div class="meta"><span>${c.flag} ${esc(c.name)}</span><span class="tier-name">Готов к спину</span></div>
        ${numBlock(c.dial + " ••• •••-••-••", `<span class="dial">${esc(c.dial)}</span> ••• •••-••-••`)}<div class="label">Жми «Крутить» — номер появится здесь</div>`;
    }
    return `<div class="meta"><span>${it.flag} ${esc(it.country_name)}</span><span class="tier-name" style="--tcol:var(--t${it.tier.idx})">${it.tier.icon} ${esc(it.tier.name)}</span></div>
      ${numBlock(it.number)}<div class="label">игровой номер · ${fmt(it.price)} монет</div>`;
  }
  function renderPlay() {
    const u = S.user, t = S.today;
    const done = t.tasks.filter(x => x.claimed).length;
    const claimable = t.tasks.some(x => x.progress >= x.target && !x.claimed);
    const it = ui.boardItem || S.last_drop;
    $main.className = "main noscroll";
    $main.innerHTML = `
      <div class="today">
        <button data-act="gift" class="${t.gift ? "ready" : ""}"><b>🎁</b>Подарок</button>
        <button data-act="wheel" class="${t.wheel ? "ready" : ""}"><b>🎡</b>Колесо</button>
        <button data-act="tasks" class="${claimable ? "ready" : ""}"><b>✅</b>Задания ${done}/${t.tasks.length}</button>
      </div>
      <div class="chips" style="margin-top:10px">${S.countries.map(c => `<button class="chip ${c.code === u.country ? "on" : ""}" data-act="country" data-code="${c.code}">${c.flag} ${esc(c.name)}</button>`).join("")}</div>
      <div class="board-slot"><div class="board ${it ? "t" + it.tier.idx : ""}" id="board" style="${it ? "--tc:color-mix(in srgb, var(--t" + it.tier.idx + ") 60%, transparent)" : ""}">${boardHTML(it)}</div>
      ${u.luck > 1 ? `<div class="luck">✨ Удача ×${String(u.luck).replace(".", ",")} · ещё ${u.luck_left} спинов</div>` : ""}</div>
      <div class="spin-area">
        <div class="row">
          <div class="seg grow">
            <button class="${ui.scale === "phone" ? "on" : ""}" data-act="scale" data-v="phone">Обычный<small>100</small></button>
            <button class="${ui.scale === "premium" ? "on" : ""}" data-act="scale" data-v="premium">Премиум<small>500</small></button>
          </div>
          <div class="seg grow">${[1, 5, 10].map(n => `<button class="${ui.mult === n ? "on" : ""}" data-act="mult" data-v="${n}">×${n}</button>`).join("")}</div>
        </div>
        <button class="spin-btn ${ui.scale === "premium" ? "premium" : ""}" data-act="spin" id="spinbtn">КРУТИТЬ${ui.mult > 1 ? " ×" + ui.mult : ""}<small>${spinCost()}</small></button>
        <div class="under"><span id="etimer"></span><button class="link" data-act="odds">Шансы</button></div>
      </div>`;
    tick();
  }
  function tick() {
    const el = document.getElementById("etimer");
    if (!el || !S) return;
    const u = S.user;
    if (u.energy >= u.energy_max) { el.textContent = "⚡ Энергия полная"; return; }
    const left = (ui.energyAt - Date.now()) / 1000;
    if (left <= 0) { el.textContent = "⚡ Спин готов"; if (!ui.busy && !ui.refreshing) { ui.refreshing = true; refresh().finally(() => { ui.refreshing = false; }); } return; }
    el.textContent = `⚡ +1 через ${hms(left)}`;
  }
  setInterval(tick, 1000);

  function animateBoard(it) {
    const board = document.getElementById("board");
    if (!board) return Promise.resolve();
    board.className = "board"; board.style.cssText = "";
    const chars = [...it.number.replace(/^\S+\s/, "")];
    let reelIdx = 0;
    const html = chars.map(ch => {
      if (!/\d/.test(ch)) return `<span class="reel">${ch === " " ? "&nbsp;" : esc(ch)}</span>`;
      const strip = Array.from({ length: 10 }, () => Math.floor(Math.random() * 10)).concat([ch]);
      return `<span class="reel"><span class="strip" data-i="${reelIdx++}">${strip.map(d => `<span>${d}</span>`).join("")}</span></span>`;
    }).join("");
    const dial = it.number.split(" ")[0];
    board.innerHTML = `<div class="meta"><span>${it.flag} ${esc(it.country_name)}</span><button class="link small" data-act="skip">Пропустить</button></div>
      ${numBlock(it.number, `<span class="dial">${esc(dial)}</span><span class="reel">&nbsp;</span>${html}`)}<div class="label">крутим…</div>`;
    const strips = [...board.querySelectorAll(".strip")];
    const total = 700 + strips.length * 130;
    return new Promise(resolve => {
      let done = false;
      const finish = () => { if (done) return; done = true; strips.forEach(s => { s.style.transition = "none"; s.style.transform = "translateY(calc(-10 * 1.2em))"; }); resolve(); };
      ui.skip = finish;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        strips.forEach((s, i) => {
          const d = 700 + i * 130;
          s.style.transition = `transform ${d}ms cubic-bezier(.12,.8,.2,1.03)`;
          s.style.transform = "translateY(calc(-10 * 1.2em))";
          setTimeout(() => { if (!done) hap("s"); }, d);
        });
      }));
      setTimeout(finish, total + 120);
    });
  }

  function rarityFx(it) {
    const idx = it.tier.idx;
    if (idx >= 3) hap("n", "success"); else hap("i", idx >= 1 ? "medium" : "light");
    if (idx >= 4) setTimeout(() => hap("n", "success"), 250);
    const board = document.getElementById("board");
    if (board && idx >= 1) { board.classList.add("flash"); }
    if (S.user.settings.no_effects || idx < 3) return;
    const color = getComputedStyle(document.body).getPropertyValue("--t" + idx).trim() || "#fff";
    const fx = document.createElement("div");
    fx.className = "fx" + (idx >= 5 ? " full" : idx === 4 ? " dim" : "");
    fx.style.setProperty("--c", color);
    const n = [0, 0, 0, 30, 50, 70, 90, 90][idx];
    const palette = idx === 7 ? ["#ff6b6b", "#ffd93d", "#6bff95", "#6bc5ff", "#c56bff"] : [color, "#ffffff", color];
    for (let i = 0; i < n; i++) {
      const p = document.createElement("i");
      p.className = "p";
      const a = Math.random() * Math.PI * 2, r = 120 + Math.random() * 220;
      p.style.cssText = `--x:${Math.cos(a) * r}px;--y:${Math.sin(a) * r}px;--d:${900 + Math.random() * 900}ms;--c:${palette[i % palette.length]}`;
      fx.append(p);
    }
    app.append(fx);
    setTimeout(() => fx.remove(), 2800);
  }

  async function doSpin() {
    if (ui.busy) return;
    ui.busy = true;
    hap("i", "medium");
    const btn = document.getElementById("spinbtn");
    if (btn) btn.disabled = true;
    let res;
    try {
      res = await api("spin", { count: ui.mult, scale: ui.scale });
    } catch (e) {
      ui.busy = false;
      if (btn) btn.disabled = false;
      return fail(e);
    }
    const best = res.drops.reduce((a, b) => (b.tier.idx > a.tier.idx || (b.tier.idx === a.tier.idx && b.price > a.price)) ? b : a);
    if (!S.user.settings.fast) await animateBoard(best);
    ui.skip = null;
    ui.boardItem = best;
    ui.busy = false;
    await refresh().catch(() => {});
    rarityFx(best);
    await sleep(best.tier.idx >= 4 ? 900 : best.tier.idx >= 2 ? 450 : 200);
    showSpinResult(res, best);
    if (res.level_up) toast(`🎉 Новый уровень: <b>${res.level}</b>. Спинов за монеты в сутки стало больше`);
    if (res.break_hint) setTimeout(() => toast("☕ Уже 50 спинов сегодня. Может, перерыв?", { ms: 4500 }), 2800);
  }

  function showSpinResult(res, best) {
    const fx = best.tier.idx >= 4 ? "glow ring" : best.tier.idx >= 2 ? "glow" : "";
    if (res.drops.length === 1) {
      openSheet(`${tierHead(best)}${callCard(best, fx)}
        <div class="actions">
          <button class="btn" data-act="close">В коллекцию</button>
          <button class="btn" data-act="sell-one" data-id="${best.id}">Продать ${fmt(best.price)} ${COIN}</button>
          <button class="btn" data-act="share" data-id="${best.id}">Показать другу</button>
          <button class="btn primary" data-act="again">Крутить ещё</button>
        </div>`);
      sheetEl._items = res.drops;
      return;
    }
    const cheap = res.drops.filter(d => d.tier.idx <= 1);
    const cheapSum = cheap.reduce((a, d) => a + d.price, 0);
    const sorted = [...res.drops].sort((a, b) => b.tier.idx - a.tier.idx || b.price - a.price);
    openSheet(`<h2>×${res.drops.length}: лучший — <span class="t${best.tier.idx}"><span class="tcol">${esc(best.tier.name)}</span></span></h2>
      ${callCard(best, fx)}
      <h3>Все номера</h3><div class="grid3">${sorted.map(d => tile(d, { act: "noop", noNew: true })).join("")}</div>
      <div class="actions">
        ${cheap.length ? `<button class="btn" data-act="sell-cheap">Продать ${cheap.length} простых · ${fmt(cheapSum)} ${COIN}</button>` : `<button class="btn" data-act="share" data-id="${best.id}">Показать другу</button>`}
        <button class="btn" data-act="close">Забрать всё</button>
      </div>
      <button class="btn primary block" style="margin-top:8px" data-act="again">Крутить ещё ×${ui.mult}</button>`);
    sheetEl._items = res.drops;
  }

  // ---------- продажа ----------
  function sellFlow(items, after) {
    const total = items.reduce((a, i) => a + i.price, 0);
    const top = items.reduce((a, i) => Math.max(a, i.tier.idx), 0);
    const go = () => commitSell(items.map(i => i.id), total, top >= 4, after);
    if (top < 3) return go();
    const it = items.find(i => i.tier.idx === top);
    const sh = openSheet(`${tierHead(it)}<h2 style="text-align:center">Точно продать?</h2>
      <p class="muted" style="text-align:center">${items.length > 1 ? `${items.length} номеров` : esc(it.number)} за <b class="price">${fmt(total)} ${COIN}</b>. Вернуть номер после продажи нельзя.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn danger" id="confirmSell" ${top >= 5 ? "disabled" : ""}>${top >= 5 ? "Подожди 3 с" : "Продать"}</button></div>`);
    const b = sh.querySelector("#confirmSell");
    b.onclick = () => { closeSheet(); go(); };
    if (top >= 5) { let n = 3; const iv = setInterval(() => { n--; if (n <= 0) { clearInterval(iv); b.disabled = false; b.textContent = "Продать"; } else b.textContent = `Подожди ${n} с`; }, 1000); }
  }
  function commitSell(ids, total, undo, after) {
    const run = async () => {
      try {
        const r = await api("sell", { ids });
        hap("n", "success"); fly("+" + fmt(r.coins));
        toast(`Продано за ${fmt(r.coins)} ${COIN}`);
        ui.boardItem = null;
        await refresh();
        if (after) after();
      } catch (e) { fail(e); }
    };
    if (!undo) return run();
    let cancelled = false;
    toast(`Продаём за ${fmt(total)} ${COIN}…`, { action: "Отменить", ms: 5000, onAction: () => { cancelled = true; toast("Продажа отменена"); } });
    setTimeout(() => { if (!cancelled) run(); }, 5000);
  }

  function share(it) {
    const text = it ? `Мне выпал ${it.tier.icon} ${it.tier.name} номер ${it.number} (шанс 1 из ${fmt(it.chance || 1)})! Крути и ты:` : "Крути красивые номера вместе со мной:";
    const url = `https://t.me/share/url?url=${encodeURIComponent(S.ref_link)}&text=${encodeURIComponent(text)}`;
    if (LIVE && tg.openTelegramLink) tg.openTelegramLink(url); else toast("В Telegram откроется выбор чата: карточка дропа и твоя ссылка");
  }

  function noCoins(need) {
    hap("n", "warning");
    openSheet(`<h2>Не хватает ${fmt(need || 0)} ${COIN}</h2>
      <p class="muted">Монеты можно получить бесплатно:</p>
      <div class="list">
        <button class="li" data-act="tasks"><span class="ic">✅</span><span class="grow"><b>Задания</b><span class="small muted">30–60 монет за каждое</span></span></button>
        <button class="li" data-act="wheel"><span class="ic">🎡</span><span class="grow"><b>Колесо дня</b><span class="small muted">до 1 000 монет</span></span></button>
        <button class="li" data-act="bulk"><span class="ic">💱</span><span class="grow"><b>Продать дубли</b><span class="small muted">простые номера из коллекции</span></span></button>
        ${S.stars_enabled ? `<button class="li" data-act="tab" data-tab="more"><span class="ic">⭐</span><span class="grow"><b>Попытки за Stars</b><span class="small muted">спины без монет</span></span></button>` : ""}
      </div>`);
  }

  // ---------- КОЛЛЕКЦИЯ ----------
  const FILTERS = [[0, "Все"], [2, "◆ Редкий+"], [3, "⬢ Эпик+"], [4, "★ Легенд.+"]];
  async function renderCollection() {
    $main.className = "main";
    $main.innerHTML = `<div class="row"><h2 class="grow">Коллекция</h2><button class="btn sm" data-act="bulk">Продать пачкой</button></div>
      <div class="chips">${FILTERS.map(([v, t]) => `<button class="chip ${!ui.col.fav && ui.col.min === v ? "on" : ""}" data-act="cfilter" data-v="${v}">${t}</button>`).join("")}
        <button class="chip ${ui.col.fav ? "on" : ""}" data-act="cfav">★ Избранное</button></div>
      <input class="search" id="csearch" style="margin-top:10px" inputmode="numeric" placeholder="Поиск по узору, например 777" value="${esc(ui.col.q)}">
      <div id="cgrid" style="margin-top:12px"><div class="empty">Загружаем…</div></div>`;
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
      const c = await api("collection", { min_tier: ui.col.min, q: ui.col.q, favorites: ui.col.fav });
      ui.items = c.items;
      const total = Object.values(c.counts).reduce((a, b) => a + b, 0);
      grid.innerHTML = `<div class="small muted" style="margin-bottom:8px">${fmt(total)} номеров · стоимость <span class="price">${fmt(c.value)} ${COIN}</span></div>` +
        (c.items.length ? `<div class="grid3">${c.items.map(i => tile(i)).join("")}</div>` :
          total ? empty("Ничего не нашлось", "Попробуй другой фильтр или узор") : empty("Пока пусто", "Нажми «Крутить» — первый номер появится здесь"));
    } catch (e) { grid.innerHTML = empty("Нет связи", "Попробуй ещё раз"); }
  }
  function itemSheet(it) {
    const listed = it.status === "listed";
    openSheet(`${tierHead(it)}${callCard(it)}
      <div class="actions">
        <button class="btn" data-act="fav" data-id="${it.id}">${it.favorite ? "★ В избранном" : "☆ В избранное"}</button>
        <button class="btn" data-act="share" data-id="${it.id}">Показать другу</button>
        ${listed ? `<button class="btn" data-act="tab" data-tab="market" data-mk="mine" style="grid-column:span 2">На рынке · управлять лотом</button>` :
          `<button class="btn" data-act="sell-one" data-id="${it.id}">Продать ${fmt(it.price)} ${COIN}</button>
           <button class="btn" data-act="list" data-id="${it.id}">На рынок</button>`}
      </div>`);
    sheetEl._items = [it];
  }
  async function bulkSheet(max = 0) {
    const sh = openSheet(`<h2>Продать пачкой</h2><p class="muted small">Избранное (★) и номера на рынке не продаются.</p>
      <div class="seg" style="margin:10px 0">${[[0, "Обычные"], [1, "+ Необычные"], [2, "+ Редкие"]].map(([v, t]) => `<button class="${v === max ? "on" : ""}" data-act="bulk" data-v="${v}">${t}</button>`).join("")}</div>
      <div id="bulkinfo" class="card">Считаем…</div>`);
    try {
      const p = await api("bulk_preview", { max_tier: max });
      if (!sheetEl || sheetEl !== sh) return;
      sh.querySelector("#bulkinfo").outerHTML = p.count
        ? `<button class="btn primary block" data-act="bulk-go" data-v="${max}">Продать ${fmt(p.count)} номеров · ${fmt(p.coins)} ${COIN}</button>`
        : `<div class="card muted">Таких номеров нет.</div>`;
    } catch (e) { fail(e); }
  }
  function listSheet(it) {
    const lo = Math.floor(it.price * 0.5), hi = Math.floor(it.price * 1.5);
    const sh = openSheet(`<h2>Выставить на рынок</h2>${callCard(it)}
      <h3>Цена: от ${fmt(lo)} до ${fmt(hi)}</h3>
      <input type="range" id="lp" min="${lo}" max="${hi}" step="${Math.max(1, Math.round(it.price / 100))}" value="${it.price}" aria-label="Цена лота">
      <div class="row" style="justify-content:space-between;margin-top:6px"><span class="price" id="lpv"></span><span class="small muted" id="lpg"></span></div>
      <p class="small muted">Лот висит 3 дня. Комиссия рынка 10% уходит из игры.</p>
      <button class="btn primary block" id="lpgo">Выставить</button>`);
    const r = sh.querySelector("#lp");
    const upd = () => { const v = +r.value; sh.querySelector("#lpv").innerHTML = `${fmt(v)} ${COIN}`; sh.querySelector("#lpg").textContent = `тебе ${fmt(v - Math.floor(v * 0.1))}`; };
    r.oninput = upd; upd();
    sh.querySelector("#lpgo").onclick = async () => {
      try { await api("market/list", { id: it.id, price: +r.value }); closeSheet(); toast("Лот выставлен на 3 дня"); if (ui.tab === "collection") loadCollection(); }
      catch (e) { fail(e); }
    };
  }

  // ---------- РЫНОК ----------
  async function renderMarket() {
    $main.className = "main";
    const tabs = [["showcase", "Витрина"], ["mine", "Мои лоты"], ["contract", "5 в 1"]];
    if (!S.user.settings.no_upgrader) tabs.push(["upgrade", "Апгрейд"]);
    if (!tabs.some(t => t[0] === ui.mk.tab)) ui.mk.tab = "showcase";
    $main.innerHTML = `<h2>Рынок</h2><div class="seg">${tabs.map(([k, t]) => `<button class="${ui.mk.tab === k ? "on" : ""}" data-act="mktab" data-v="${k}">${t}</button>`).join("")}</div>
      <div id="mk" style="margin-top:12px"><div class="empty">Загружаем…</div></div>`;
    const box = document.getElementById("mk");
    try {
      if (ui.mk.tab === "showcase") await renderShowcase(box);
      else if (ui.mk.tab === "mine") await renderMine(box);
      else if (ui.mk.tab === "contract") await renderContract(box);
      else await renderUpgrade(box);
    } catch (e) { box.innerHTML = empty("Нет связи", esc(e.message || "Попробуй ещё раз")); }
  }
  function lotRow(l, act) {
    return `<div class="li t${l.tier.idx}"><span class="ic">${l.flag}</span>
      <span class="grow"><b style="font-family:var(--mono)">${esc(l.number)}</b>
      <span class="small"><span class="tcol">${l.tier.icon} ${esc(l.tier.name)}</span> <span class="muted">· ${esc(l.seller)}</span></span></span>
      <span style="text-align:right"><span class="price">${fmt(l.lot_price)} ${COIN}</span><br>${act}</span></div>`;
  }
  async function renderShowcase(box) {
    const m = await api("market", { min_tier: ui.mk.min, sort: ui.mk.sort });
    ui.lots = m.lots;
    box.innerHTML = `<div class="chips">${FILTERS.map(([v, t]) => `<button class="chip ${ui.mk.min === v ? "on" : ""}" data-act="mkmin" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="chips" style="margin-top:6px">${[["new", "Новые"], ["cheap", "Дешевле"], ["rare", "Редкие"]].map(([v, t]) => `<button class="chip ${ui.mk.sort === v ? "on" : ""}" data-act="mksort" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="list" style="margin-top:10px">${m.lots.length ? m.lots.map(l => lotRow(l, l.seller_id === S.user.id ? '<span class="small muted">твой лот</span>' : `<button class="btn sm primary" data-act="buy" data-lot="${l.lot_id}">Купить</button>`)).join("") : empty("Витрина пуста", "Выстави свой номер из коллекции")}</div>`;
  }
  async function renderMine(box) {
    const m = await api("market/mine");
    box.innerHTML = `<h3>Активные лоты</h3><div class="list">${m.active.length ? m.active.map(l => lotRow(l, `<button class="btn sm" data-act="unlist" data-lot="${l.lot_id}">Снять</button>`)).join("") : empty("Нет лотов", "Открой номер в коллекции и нажми «На рынок»")}</div>
      <h3>Сделки</h3><div class="list">${m.deals.length ? m.deals.map(l => lotRow(l, `<span class="small ${l.side === "sell" ? "tcol" : "muted"}" style="--tc:var(--neon)">${l.side === "sell" ? "продал" : "купил"}</span>`)).join("") : empty("Сделок пока нет", "")}</div>`;
  }
  async function renderContract(box) {
    const c = await api("collection", {});
    const counts = c.counts;
    const items = c.items.filter(i => i.status === "owned" && i.tier.idx === ui.contract.tier);
    ui.items = c.items;
    const t = S.tiers[ui.contract.tier], next = S.tiers[ui.contract.tier + 1];
    const n = ui.contract.sel.size;
    box.innerHTML = `<div class="card small">5 номеров одной ступени превращаются в 1 случайный номер ступенью выше. Избранное тоже можно класть.</div>
      <div class="chips" style="margin-top:10px">${S.tiers.slice(0, 7).map(x => `<button class="chip t${x.idx} ${x.idx === ui.contract.tier ? "on" : ""}" data-act="ctier" data-v="${x.idx}"><span class="tcol">${x.icon}</span> ${esc(x.name)} · ${counts[x.idx] || 0}</button>`).join("")}</div>
      <div class="row" style="justify-content:space-between;margin:12px 0 8px"><span class="t${t.idx}"><span class="tcol">${t.icon} ${esc(t.name)}</span></span> <span class="muted">→</span> <span class="t${next.idx}"><span class="tcol">${next.icon} ${esc(next.name)}</span></span></div>
      ${items.length ? `<div class="grid3">${items.map(i => tile(i, { act: "csel", sel: ui.contract.sel.has(i.id), noNew: true })).join("")}</div>` : empty("Нет номеров этой ступени", "Крути, чтобы собрать пять")}
      <button class="btn primary block" style="margin-top:12px" data-act="contract-go" ${n === 5 ? "" : "disabled"}>Собрать 5 в 1 · ${n}/5</button>`;
  }
  let quoteTimer;
  async function renderUpgrade(box) {
    const c = await api("collection", {});
    ui.items = c.items;
    const own = c.items.filter(i => i.status === "owned").sort((a, b) => a.price - b.price);
    const sel = own.filter(i => ui.up.sel.has(i.id));
    const stake = sel.reduce((a, i) => a + i.price, 0) + ui.up.coins;
    const targets = S.tiers.slice(0, 7).filter(t => [10, 30, 100, 400, 2000, 10000, 50000][t.idx] > stake);
    if (!targets.some(t => t.idx === ui.up.target)) ui.up.target = targets.length ? targets[0].idx : null;
    const maxCoins = Math.min(S.user.coins, 10000);
    box.innerHTML = `<div class="card small">Положи до 3 номеров и монеты, выбери цель дороже ставки. Шанс = ставка ÷ цена цели × 0,85. При неудаче ставка сгорает, а ты получаешь 10% монетами и +3% к следующему шансу.</div>
      <h3>Ставка · ${sel.length}/3</h3>
      ${own.length ? `<div class="grid3">${own.slice(0, 30).map(i => tile(i, { act: "usel", sel: ui.up.sel.has(i.id), noNew: true })).join("")}</div>` : empty("Коллекция пуста", "Сначала покрути")}
      <h3>Монеты к ставке</h3>
      <input type="range" id="ucoins" min="0" max="${maxCoins}" step="10" value="${Math.min(ui.up.coins, maxCoins)}" aria-label="Монеты к ставке">
      <div class="row" style="justify-content:space-between"><span class="price">${fmt(ui.up.coins)} ${COIN}</span><span class="small muted">ставка ${fmt(stake)}</span></div>
      <h3>Цель</h3>
      <div class="chips">${targets.length ? targets.map(t => `<button class="chip t${t.idx} ${ui.up.target === t.idx ? "on" : ""}" data-act="utarget" data-v="${t.idx}"><span class="tcol">${t.icon}</span> ${esc(t.name)}</button>`).join("") : '<span class="muted small">Ставка уже дороже всех целей</span>'}</div>
      <div id="uquote" style="margin-top:6px"></div>`;
    const r = document.getElementById("ucoins");
    r.oninput = () => { ui.up.coins = +r.value; clearTimeout(quoteTimer); quoteTimer = setTimeout(() => renderMarket(), 250); };
    loadQuote();
  }
  async function loadQuote() {
    const box = document.getElementById("uquote");
    if (!box) return;
    if ((!ui.up.sel.size && !ui.up.coins) || ui.up.target === null) { box.innerHTML = '<p class="muted small" style="text-align:center">Выбери номера или монеты для ставки</p>'; return; }
    try {
      const q = await api("upgrade/quote", { ids: [...ui.up.sel], coins: ui.up.coins, target: ui.up.target });
      box.innerHTML = `<div class="chance">${pct(q.chance)}</div>
        <div class="formula">${fmt(q.stake)} ÷ ${fmt(q.target_price)} × 0,85 = ${pct(q.base_chance)}${q.bonus ? ` · бонус +${pct(q.bonus)}` : ""}</div>
        <button class="btn primary block" style="margin-top:12px" data-act="upgrade-go" ${q.left_today > 0 ? "" : "disabled"}>Апгрейд</button>
        <p class="small muted" style="text-align:center">Осталось сегодня: ${q.left_today} из 10</p>`;
    } catch (e) { box.innerHTML = `<p class="small" style="text-align:center;color:#ff9aa4">${esc(e.message)}</p>`; }
  }
  async function upgradeGo() {
    const items = (ui.items || []).filter(i => ui.up.sel.has(i.id));
    const top = items.reduce((a, i) => Math.max(a, i.tier.idx), -1);
    const run = async () => {
      let res;
      try { res = await api("upgrade", { ids: [...ui.up.sel], coins: ui.up.coins, target: ui.up.target }); }
      catch (e) { return fail(e); }
      ui.up.sel.clear(); ui.up.coins = 0;
      const sh = openSheet(`<h2 style="text-align:center">Апгрейд</h2><div class="chance" id="ures">${pct(res.chance)}</div>
        <div class="gauge"><div class="win" style="width:${res.chance * 100}%"></div><div class="arrow" id="uarrow"></div></div>
        <div class="row" style="justify-content:space-between" class="small muted"><span class="small muted">успех</span><button class="link small" id="uskip">Пропустить</button></div>
        <div id="uout" style="margin-top:12px"></div>`);
      const arrow = sh.querySelector("#uarrow");
      const finish = () => {
        arrow.style.transition = "none"; arrow.style.left = (res.roll * 100) + "%";
        const out = sh.querySelector("#uout");
        if (!out || out.dataset.done) return;
        out.dataset.done = 1;
        if (res.success) { hap("n", "success"); rarityFx(res.item); out.innerHTML = `${tierHead(res.item)}${callCard(res.item, "glow")}<button class="btn primary block" style="margin-top:12px" data-act="close">Готово</button>`; }
        else { hap("n", "error"); out.innerHTML = `<div class="card" style="text-align:center"><b>Не повезло.</b><br><span class="muted small">Запчасти: +${fmt(res.parts)} ${COIN}. Следующий шанс выше на 3%.</span></div><button class="btn block" style="margin-top:12px" data-act="close">Готово</button>`; }
        refresh().catch(() => {});
        if (ui.tab === "market") renderMarket();
      };
      sh.querySelector("#uskip").onclick = finish;
      if (S.user.settings.fast) return finish();
      requestAnimationFrame(() => requestAnimationFrame(() => { arrow.style.transition = "left 3.2s cubic-bezier(.15,.75,.2,1)"; arrow.style.left = (res.roll * 100) + "%"; }));
      setTimeout(finish, 3300);
    };
    if (top < 3) return run();
    const sh = openSheet(`<h2>Точно?</h2><p class="muted">В ставке есть номер ступени Эпик или выше. Если апгрейд не выйдет, он сгорит.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn danger" id="ugo" disabled>Подожди 3 с</button></div>`);
    const b = sh.querySelector("#ugo");
    let n = 3; const iv = setInterval(() => { n--; if (n <= 0) { clearInterval(iv); b.disabled = false; b.textContent = "Апгрейд"; } else b.textContent = `Подожди ${n} с`; }, 1000);
    b.onclick = () => { closeSheet(true); run(); };
  }

  // ---------- ДРУЗЬЯ ----------
  async function renderFriends() {
    $main.className = "main";
    $main.innerHTML = `<h2>Друзья</h2><div id="fr"><div class="empty">Загружаем…</div></div><h3>Рейтинг</h3><div id="rt"></div>`;
    try {
      const f = await api("friends");
      document.getElementById("fr").innerHTML = `
        <div class="card"><b>Друг получает ${f.friend_spins} спина сразу.</b> Ты — награду, когда он сделает ${f.required_spins} спинов.
          <div class="search" style="display:flex;align-items:center;margin-top:10px;overflow:hidden;white-space:nowrap;font-size:12px">${esc(f.ref_link)}</div>
          <div class="actions"><button class="btn" data-act="copy" data-v="${esc(f.ref_link)}">Скопировать</button><button class="btn primary" data-act="share">Отправить</button></div></div>
        <h3>Награды · засчитано ${f.count}</h3>
        <div class="list">${f.tiers.map(t => `<div class="li"><span class="ic">${f.count >= t.count ? "✅" : "🎁"}</span><span class="grow"><b>${t.count} ${t.count === 1 ? "друг" : t.count < 5 ? "друга" : "друзей"}</b><span class="small muted">${esc(t.title)}</span></span><span class="small muted" style="font-family:var(--mono)">${Math.min(f.count, t.count)}/${t.count}</span></div>`).join("")}</div>
        <h3>Приглашённые</h3>
        <div class="list">${f.friends.length ? f.friends.map(x => `<div class="li"><span class="ic">${x.qualified ? "✅" : "⏳"}</span><span class="grow"><b>${esc(x.name)}</b><div class="bar" style="margin-top:6px"><i style="width:${x.spins / f.required_spins * 100}%"></i></div></span><span class="small muted" style="font-family:var(--mono)">${x.spins}/${f.required_spins}</span></div>`).join("") : empty("Пока никого", "Отправь ссылку другу — оба получите спины")}</div>`;
    } catch (e) { document.getElementById("fr").innerHTML = empty("Нет связи", "Попробуй ещё раз"); }
    renderRating();
  }
  async function renderRating() {
    const box = document.getElementById("rt");
    if (!box) return;
    box.innerHTML = `<div class="row"><div class="seg grow">${[["friends", "Друзья"], ["all", "Все"]].map(([v, t]) => `<button class="${ui.rating.scope === v ? "on" : ""}" data-act="rscope" data-v="${v}">${t}</button>`).join("")}</div>
      <div class="seg grow">${[["value", "Коллекция"], ["best", "Лучший"]].map(([v, t]) => `<button class="${ui.rating.kind === v ? "on" : ""}" data-act="rkind" data-v="${v}">${t}</button>`).join("")}</div></div>
      <div class="list" id="rlist" style="margin-top:10px"><div class="empty">Загружаем…</div></div>`;
    try {
      const r = await api("rating", ui.rating);
      const row = e => `<div class="li ${e.me ? "me" : ""}"><span class="pos">${e.pos}</span><span class="grow"><b>${esc(e.name)}${e.me ? " · ты" : ""}</b>
        ${e.item ? `<span class="small t${e.item.tier.idx}"><span class="tcol">${e.item.tier.icon}</span> <span style="font-family:var(--mono)">${esc(e.item.number)}</span></span>` : ""}</span>
        ${e.value !== undefined ? `<span class="price">${fmt(e.value)} ${COIN}</span>` : ""}</div>`;
      let html = r.top.map(row).join("");
      if (r.me && r.me.pos > r.top.length) html += row(r.me);
      document.getElementById("rlist").innerHTML = html || empty("Пока пусто", ui.rating.scope === "friends" ? "Пригласи друзей, чтобы соревноваться" : "Стань первым");
    } catch (e) { document.getElementById("rlist").innerHTML = empty("Нет связи", ""); }
  }

  // ---------- ЕЩЁ ----------
  async function renderMore() {
    $main.className = "main";
    const u = S.user, st = u.settings;
    $main.innerHTML = `<h2>Профиль</h2>
      <div class="card"><div class="row"><div class="grow"><b style="font-size:17px">${esc(u.name)}</b><div class="small muted">${fmt(u.total_spins)} спинов · с нами с ${new Date(u.created_at * 1000).toLocaleDateString("ru-RU")}</div></div><span class="lvl">Ур. ${u.level}</span></div>
        <div class="bar" style="margin-top:10px"><i style="width:${u.xp / u.xp_need * 100}%"></i></div><div class="small muted" style="margin-top:4px">${u.xp} / ${u.xp_need} опыта до уровня ${u.level + 1}</div>
        ${u.badges.length ? `<div class="chips wrap" style="margin-top:10px">${u.badges.map(b => `<span class="chip on">🏅 ${esc(b)}</span>`).join("")}</div>` : ""}
        <h3>Витрина</h3><div class="grid3" id="showcase"></div></div>
      <h3>Магазин ⭐</h3><div id="shop"></div>
      <h3>Настройки</h3><div class="card" style="padding:4px 14px">
        ${[["fast", "Всегда быстро", "без анимации спина"], ["no_effects", "Без эффектов", "без вспышек и частиц"], ["no_upgrader", "Без апгрейдера", "скрыть вкладку апгрейда"]].map(([k, t, d]) => `<button class="toggle" style="width:100%;text-align:left" data-act="setting" data-k="${k}"><span class="grow"><b>${t}</b><span class="small muted" style="display:block">${d}</span></span><span class="sw ${st[k] ? "on" : ""}"></span></button>`).join("")}</div>
      <h3>Ещё</h3><div class="list">
        <button class="li" data-act="odds"><span class="ic">📊</span><span class="grow"><b>Шансы</b><span class="small muted">все ступени в процентах</span></span></button>
        <button class="li" data-act="history"><span class="ic">🧾</span><span class="grow"><b>История</b><span class="small muted">последние 20 операций</span></span></button>
        <button class="li" data-act="terms"><span class="ic">📄</span><span class="grow"><b>Условия</b><span class="small muted">что можно и что нельзя</span></span></button>
        <button class="li" data-act="support"><span class="ic">💬</span><span class="grow"><b>Поддержка</b><span class="small muted">вопросы по оплате: /paysupport</span></span></button>
      </div>`;
    api("collection", {}).then(c => { const el = document.getElementById("showcase"); if (el) el.innerHTML = c.items.slice(0, 3).map(i => tile(i, { noNew: true })).join("") || '<span class="small muted" style="grid-column:span 3">Три лучших номера появятся здесь</span>'; ui.items = c.items; }).catch(() => {});
    renderShop();
  }
  async function renderShop() {
    const box = document.getElementById("shop");
    try {
      const s = await api("shop");
      if (!s.enabled) { box.innerHTML = `<div class="card muted small">Магазин за Telegram Stars откроется позже. Всё в игре можно получить бесплатно.</div>`; return; }
      box.innerHTML = `<div class="card small"><div class="row" style="justify-content:space-between"><span class="muted">Потрачено в этом месяце</span><b style="font-family:var(--mono)">${s.month_spent} / ${s.month_cap} ⭐</b></div><div class="bar" style="margin-top:6px"><i style="width:${Math.min(100, s.month_spent / s.month_cap * 100)}%;background:var(--gold)"></i></div></div>
        <div class="list" style="margin-top:8px">${s.products.map(p => `<div class="li"><span class="ic">${p.luck ? "✨" : "🎟"}</span><span class="grow"><b>${esc(p.title)}</b><span class="small muted">${esc(p.desc)}</span></span><button class="btn sm" data-act="buy-star" data-k="${p.key}">${p.stars} ⭐</button></div>`).join("")}</div>
        <p class="small muted">Только попытки и удача, без монет и кейсов. Лимит ${s.month_cap} ⭐ в месяц, запас попыток до ${s.spins_stock_cap}.</p>`;
      ui.products = s.products;
    } catch (e) { box.innerHTML = `<div class="card muted small">Магазин недоступен. Попробуй позже.</div>`; }
  }
  function buyStar(key) {
    const p = (ui.products || []).find(x => x.key === key);
    if (!p) return;
    const odds = p.luck ? `<table class="odds" style="margin-top:8px"><tr><th>Ступень</th><th>Обычно</th><th>С удачей</th></tr>${luckRows(p.luck)}</table>` : "";
    const sh = openSheet(`<h2>${esc(p.title)}</h2><p class="muted">${esc(p.desc)}.${p.luck ? " Действует одно усиление, сильнейшее." : ""}</p>${odds}
      <p class="small muted">Покупка выдаётся сразу после оплаты и окончательна. Условия: /terms.</p>
      <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn primary" id="paygo">Купить за ${p.stars} ⭐</button></div>`);
    sh.querySelector("#paygo").onclick = async () => {
      try {
        const r = await api("shop/invoice", { key });
        if (r.demo) { await api("shop/demo_pay", { key }); closeSheet(); toast(`✅ ${esc(p.title)} — в демо звёзды не списываются`); await refresh(); renderMore(); return; }
        tg.openInvoice(r.link, async status => {
          if (status === "paid") { closeSheet(); hap("n", "success"); toast(`✅ Получено: ${esc(p.title)}`); await sleep(800); await refresh(); if (ui.tab === "more") renderMore(); }
          else if (status === "failed") toast("Оплата не прошла");
        });
      } catch (e) { fail(e); }
    };
  }
  function luckRows(m) {
    const rows = S.odds.phone.rows;
    const top2 = [...rows].sort((a, b) => b.p - a.p).slice(0, 2).map(r => r.tier.idx);
    const boosted = rows.filter(r => !top2.includes(r.tier.idx)).reduce((a, r) => a + r.p * m, 0);
    const cSum = rows.filter(r => top2.includes(r.tier.idx)).reduce((a, r) => a + r.p, 0);
    return rows.map(r => { const p2 = top2.includes(r.tier.idx) ? r.p * (1 - boosted) / cSum : r.p * m; return `<tr class="t${r.tier.idx}"><td><span class="tcol">${r.tier.icon} ${esc(r.tier.name)}</span></td><td class="mono">${pct(r.p)}</td><td class="mono">${pct(p2)}</td></tr>`; }).join("");
  }

  // ---------- шторки «Сегодня» ----------
  function wheelSheet() {
    const sectors = S.wheel, n = sectors.length, avail = S.today.wheel;
    const colors = ["#1b2a52", "#22346a", "#1b2a52", "#2c3f80", "#3a2a10"];
    const R = 100, paths = sectors.map((s, i) => {
      const a0 = (i / n) * 2 * Math.PI - Math.PI / 2, a1 = ((i + 1) / n) * 2 * Math.PI - Math.PI / 2;
      const x0 = R + R * Math.cos(a0), y0 = R + R * Math.sin(a0), x1 = R + R * Math.cos(a1), y1 = R + R * Math.sin(a1);
      const am = (a0 + a1) / 2, tx = R + 62 * Math.cos(am), ty = R + 62 * Math.sin(am);
      return `<path d="M${R},${R} L${x0},${y0} A${R},${R} 0 0 1 ${x1},${y1} Z" fill="${colors[i % colors.length]}" stroke="#3dff8f" stroke-opacity=".35"/>
        <text x="${tx}" y="${ty}" fill="${i === n - 1 ? "#ffc94a" : "#e9eefb"}" font-family="JetBrains Mono, monospace" font-weight="800" font-size="13" text-anchor="middle" dominant-baseline="middle">${esc(s.label)}</text>`;
    }).join("");
    const sh = openSheet(`<h2>Колесо дня</h2><p class="muted small">Один бесплатный поворот в сутки, пустых секторов нет.</p>
      <div class="wheel-wrap"><div class="pin"></div><svg viewBox="0 0 200 200" id="wsvg"><circle cx="100" cy="100" r="100" fill="#0b1222"/>${paths}<circle cx="100" cy="100" r="16" fill="#3dff8f"/></svg></div>
      <table class="odds">${sectors.map(s => `<tr><td>${esc(s.label)}${/спин/.test(s.label) ? "" : " монет"}</td><td class="mono">${pct(s.p)}</td></tr>`).join("")}</table>
      <button class="btn primary block" style="margin-top:12px" id="wgo" ${avail ? "" : "disabled"}>${avail ? "Крутить колесо" : "Следующий поворот завтра"}</button>`);
    sh.querySelector("#wgo").onclick = async e => {
      e.target.disabled = true;
      try {
        const r = await api("wheel");
        const svg = sh.querySelector("#wsvg");
        const target = 360 * 6 - (r.index + 0.5) * (360 / n);
        svg.style.transform = `rotate(${target}deg)`;
        hap("i", "medium");
        await sleep(S.user.settings.fast ? 0 : 4100);
        hap("n", "success");
        fly(r.coins ? "+" + fmt(r.coins) : "+" + r.spins + " 🎟");
        e.target.textContent = `Выпало: ${r.label}${r.spins ? "" : " монет"}`;
        await refresh();
      } catch (err) { fail(err); }
    };
  }
  function giftSheet() {
    const t = S.today, cur = t.gift_day;
    const label = r => typeof r === "number" ? fmt(r) : `${fmt(r.coins)}+${r.spins}🎟`;
    const sh = openSheet(`<h2>Подарок дня</h2><p class="muted small">Заходи 7 дней подряд — на 7-й день большой подарок. Пропуск сбрасывает серию.</p>
      <div class="days">${t.gift_rewards.map((r, i) => `<div class="${(t.gift ? i < cur - 1 : i < cur) ? "done" : ""} ${t.gift && i === cur - 1 ? "cur" : ""}">День ${i + 1}<b>${label(r)}</b></div>`).join("")}</div>
      <button class="btn primary block" style="margin-top:14px" id="ggo" ${t.gift ? "" : "disabled"}>${t.gift ? `Забрать ${label(t.gift_rewards[cur - 1])}` : `Завтра: ${label(t.gift_rewards[cur % 7])}`}</button>`);
    sh.querySelector("#ggo").onclick = async e => {
      e.target.disabled = true;
      try { const r = await api("gift"); hap("n", "success"); fly("+" + fmt(r.coins)); toast(`🎁 День ${r.day}: +${fmt(r.coins)} ${COIN}${r.spins ? ` и ${r.spins} попытки` : ""}`); await refresh(); giftSheet(); }
      catch (err) { fail(err); }
    };
  }
  function tasksSheet() {
    openSheet(`<h2>Задания на сегодня</h2><p class="muted small">Новые задания каждый день в 00:00 по Москве.</p>
      <div class="list">${S.today.tasks.map(t => `<div class="li"><span class="grow"><b>${esc(t.title)}</b><div class="bar" style="margin-top:6px"><i style="width:${t.progress / t.target * 100}%"></i></div><span class="small muted">${t.progress}/${t.target} · +${t.coins} монет</span></span>
        ${t.claimed ? '<span class="small muted">✓ Получено</span>' : `<button class="btn sm ${t.progress >= t.target ? "primary" : ""}" data-act="task" data-k="${t.key}" ${t.progress >= t.target ? "" : "disabled"}>Забрать</button>`}</div>`).join("")}</div>`);
  }
  function oddsSheet() {
    const sc = S.odds[ui.oddsScale], u = S.user, luck = u.luck > 1;
    openSheet(`<h2>Шансы</h2>
      <div class="seg">${Object.entries(S.odds).map(([k, v]) => `<button class="${k === ui.oddsScale ? "on" : ""}" data-act="oddsscale" data-v="${k}">${esc(v.title)}<small>${v.price} монет</small></button>`).join("")}</div>
      <table class="odds" style="margin-top:10px"><tr><th>Ступень</th><th>Шанс</th><th>1 из</th>${luck ? `<th>Удача ×${String(u.luck).replace(".", ",")}</th>` : ""}</tr>
      ${sc.rows.map(r => `<tr class="t${r.tier.idx}"><td><span class="tcol">${r.tier.icon} ${esc(r.tier.name)}</span></td><td class="mono">${pct(r.p)}</td><td class="mono">${fmt(Math.round(1 / r.p))}</td>${luck ? `<td class="mono">${pct(r.p_luck)}</td>` : ""}</tr>`).join("")}</table>
      <div class="card small" style="margin-top:12px">🛡 Гарантия: Эпик или выше — не позже чем через <b>${u.pity_epic_left}</b> спинов, Легендарный или выше — через <b>${u.pity_legendary_left}</b>.</div>
      <p class="small muted">Результат решает сервер и записывает его до анимации. Барабаны останавливаются там, где решил сервер, — без подставных «почти выпало». Энергия: 1 бесплатный спин раз в 3 часа, копится до 3. Спинов за монеты — до ${u.coin_spins_left} сегодня.</p>`);
  }
  function coinsSheet() {
    openSheet(`<h2>${COIN} Монеты</h2><p class="muted small">Монеты игровые: их нельзя купить за деньги и нельзя вывести.</p>
      <h3>Как получить</h3><div class="list">
        <div class="li"><span class="ic">⚡</span><span class="grow"><b>Бесплатные спины</b><span class="small muted">раз в 3 часа, номер можно продать</span></span></div>
        <button class="li" data-act="tasks"><span class="ic">✅</span><span class="grow"><b>Задания</b><span class="small muted">3 в день, 30–60 монет</span></span></button>
        <button class="li" data-act="wheel"><span class="ic">🎡</span><span class="grow"><b>Колесо дня</b><span class="small muted">50–1 000 монет</span></span></button>
        <button class="li" data-act="gift"><span class="ic">🎁</span><span class="grow"><b>Подарок дня</b><span class="small muted">серия 7 дней</span></span></button>
        <button class="li" data-act="tab" data-tab="friends"><span class="ic">🤝</span><span class="grow"><b>Друзья</b><span class="small muted">спины и монеты за приглашения</span></span></button></div>
      <h3>Куда потратить</h3><div class="list">
        <div class="li"><span class="ic">📱</span><span class="grow"><b>Спин 100 · Премиум 500</b><span class="small muted">премиум — сразу от Редкого</span></span></div>
        <button class="li" data-act="tab" data-tab="market"><span class="ic">🏪</span><span class="grow"><b>Рынок и апгрейдер</b><span class="small muted">купить номер у игрока</span></span></button></div>`);
  }
  async function historySheet() {
    const sh = openSheet(`<h2>История</h2><div class="list" id="hl"><div class="empty">Загружаем…</div></div>`);
    const names = { start: "Старт", spin: "Спин", sell: "Продажа", wheel: "Колесо", gift: "Подарок дня", task: "Задание", referral: "Друзья", invited: "Приглашение", upgrade: "Апгрейд", upgrade_parts: "Запчасти", market_buy: "Покупка на рынке", market_sell: "Продажа на рынке", purchase: "Покупка ⭐", refund: "Возврат", admin: "Бонус" };
    try {
      const h = await api("history");
      sh.querySelector("#hl").innerHTML = h.items.length ? h.items.map(x => `<div class="li"><span class="grow"><b>${names[x.reason] || esc(x.reason)}</b><span class="small muted">${new Date(x.created_at * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span></span><span class="price" style="color:${x.delta > 0 ? "var(--neon)" : "var(--fg)"}">${x.delta > 0 ? "+" : ""}${fmt(x.delta)} ${x.currency === "coins" ? COIN : "🎟"}</span></div>`).join("") : empty("Пока пусто", "");
    } catch (e) { fail(e); }
  }
  function termsSheet() {
    openSheet(`<h2>Условия</h2><div class="card small" style="line-height:1.55">
      • Монеты, номера и попытки — игровые. Монеты нельзя купить за деньги и нельзя вывести.<br>
      • Номера сгенерированы игрой и помечены «игровой номер». Это не SIM-карты: их нельзя купить или проверить по базам операторов. Совпадение с реальным номером случайно.<br>
      • За Telegram Stars продаются только попытки и удача: не больше 500 ⭐ в месяц, запас попыток до 100.<br>
      • Покупка выдаётся сразу после оплаты. Проблемы с оплатой — /paysupport в чате с ботом.<br>
      • Уведомления не чаще 2 в сутки и не ночью.</div>`);
  }

  // ---------- обработчики ----------
  const findItem = id => [...(sheetEl && sheetEl._items || []), ...(ui.items || []), ...(ui.boardItem ? [ui.boardItem] : [])].find(i => i.id === id);
  const actions = {
    tab: el => { closeSheet(true); if (el.dataset.mk) ui.mk.tab = el.dataset.mk; setTab(el.dataset.tab); },
    close: () => closeSheet(),
    noop: () => {},
    skip: () => ui.skip && ui.skip(),
    spin: () => doSpin(),
    again: () => { closeSheet(true); if (ui.tab !== "play") setTab("play"); doSpin(); },
    scale: el => { ui.scale = el.dataset.v; hap("s"); renderPlay(); },
    mult: el => { ui.mult = +el.dataset.v; hap("s"); renderPlay(); },
    country: async el => { try { await api("country", { code: el.dataset.code }); S.user.country = el.dataset.code; ui.boardItem = null; hap("s"); renderPlay(); } catch (e) { fail(e); } },
    coins: () => coinsSheet(),
    odds: () => oddsSheet(),
    oddsscale: el => { ui.oddsScale = el.dataset.v; oddsSheet(); },
    wheel: () => wheelSheet(),
    gift: () => giftSheet(),
    tasks: () => tasksSheet(),
    task: async el => { try { const r = await api("task", { key: el.dataset.k }); hap("n", "success"); fly("+" + r.coins); await refresh(); tasksSheet(); } catch (e) { fail(e); } },
    "sell-one": el => { const it = findItem(+el.dataset.id); if (it) { closeSheet(true); sellFlow([it], () => ui.tab === "collection" && loadCollection()); } },
    "sell-cheap": () => { const items = (sheetEl._items || []).filter(d => d.tier.idx <= 1); closeSheet(true); sellFlow(items); },
    share: el => share(el.dataset.id ? findItem(+el.dataset.id) : null),
    item: el => { const it = findItem(+el.dataset.id); if (it) itemSheet(it); },
    fav: async el => { try { const r = await api("favorite", { id: +el.dataset.id }); const it = findItem(+el.dataset.id); if (it) it.favorite = r.favorite; hap("s"); if (it) itemSheet(it); if (ui.tab === "collection") loadCollection(); } catch (e) { fail(e); } },
    list: el => { const it = findItem(+el.dataset.id); if (it) listSheet(it); },
    bulk: el => bulkSheet(el.dataset.v ? +el.dataset.v : 0),
    "bulk-go": async el => { try { const r = await api("bulk_sell", { max_tier: +el.dataset.v }); closeSheet(); hap("n", "success"); fly("+" + fmt(r.coins)); toast(`Продано ${r.sold} номеров за ${fmt(r.coins)} ${COIN}`); ui.boardItem = null; await refresh(); if (ui.tab === "collection") loadCollection(); } catch (e) { fail(e); } },
    cfilter: el => { ui.col.min = +el.dataset.v; ui.col.fav = false; renderCollection(); },
    cfav: () => { ui.col.fav = !ui.col.fav; renderCollection(); },
    mktab: el => { ui.mk.tab = el.dataset.v; renderMarket(); },
    mkmin: el => { ui.mk.min = +el.dataset.v; renderMarket(); },
    mksort: el => { ui.mk.sort = el.dataset.v; renderMarket(); },
    buy: el => {
      const l = (ui.lots || []).find(x => x.lot_id === +el.dataset.lot);
      if (!l) return;
      const sh = openSheet(`${tierHead(l)}${callCard(l)}<p class="muted small" style="text-align:center">Продавец: ${esc(l.seller)} · у тебя ${fmt(S.user.coins)} ${COIN}</p>
        <div class="actions"><button class="btn" data-act="close">Отмена</button><button class="btn primary" id="bgo">Купить · ${fmt(l.lot_price)} ${COIN}</button></div>`);
      sh.querySelector("#bgo").onclick = async () => { try { await api("market/buy", { lot_id: l.lot_id }); closeSheet(); hap("n", "success"); toast("Номер в твоей коллекции"); await refresh(); renderMarket(); } catch (e) { fail(e); } };
    },
    unlist: async el => { try { await api("market/cancel", { lot_id: +el.dataset.lot }); toast("Лот снят"); renderMarket(); } catch (e) { fail(e); } },
    ctier: el => { ui.contract.tier = +el.dataset.v; ui.contract.sel.clear(); renderMarket(); },
    csel: el => { const id = +el.dataset.id, s = ui.contract.sel; if (s.has(id)) s.delete(id); else if (s.size < 5) s.add(id); else return toast("Уже выбрано 5"); hap("s"); renderMarket(); },
    "contract-go": async () => {
      try {
        const r = await api("contract", { ids: [...ui.contract.sel] });
        ui.contract.sel.clear();
        rarityFx(r.item);
        openSheet(`<h2 style="text-align:center">5 в 1</h2>${tierHead(r.item)}${callCard(r.item, "glow")}<button class="btn primary block" style="margin-top:12px" data-act="close">Отлично</button>`);
        sheetEl._items = [r.item];
        await refresh(); renderMarket();
      } catch (e) { fail(e); }
    },
    usel: el => { const id = +el.dataset.id, s = ui.up.sel; if (s.has(id)) s.delete(id); else if (s.size < 3) s.add(id); else return toast("Не больше 3 номеров"); hap("s"); renderMarket(); },
    utarget: el => { ui.up.target = +el.dataset.v; hap("s"); renderMarket(); },
    "upgrade-go": () => upgradeGo(),
    rscope: el => { ui.rating.scope = el.dataset.v; renderRating(); },
    rkind: el => { ui.rating.kind = el.dataset.v; renderRating(); },
    copy: async el => { try { await navigator.clipboard.writeText(el.dataset.v); toast("Ссылка скопирована"); } catch (e) { toast("Не получилось скопировать — зажми ссылку"); } },
    setting: async el => { const k = el.dataset.k; try { S.user.settings = await api("settings", { [k]: !S.user.settings[k] }); document.body.classList.toggle("noeffects", !!S.user.settings.no_effects); hap("s"); renderMore(); } catch (e) { fail(e); } },
    history: () => historySheet(),
    terms: () => termsSheet(),
    support: () => { const bot = (S.ref_link.match(/t\.me\/([^/?]+)/) || [])[1]; if (LIVE && bot) tg.openTelegramLink(`https://t.me/${bot}?start=support`); else toast("Напиши /paysupport в чате с ботом"); },
    "buy-star": el => buyStar(el.dataset.k),
  };
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-act]");
    if (!el || !app.contains(el)) return;
    const fn = actions[el.dataset.act];
    if (fn) fn(el, e);
  });

  // ---------- старт ----------
  (async function boot() {
    if (tg) {
      try {
        tg.ready(); tg.expand();
        tg.setHeaderColor && tg.setHeaderColor("#0b1222");
        tg.setBackgroundColor && tg.setBackgroundColor("#060a14");
        tg.disableVerticalSwipes && tg.disableVerticalSwipes();
        const inset = tg.contentSafeAreaInset && tg.contentSafeAreaInset.top;
        if (inset) document.documentElement.style.setProperty("--tg-top", inset + "px");
      } catch (e) { /* старый клиент Telegram */ }
    }
    $main.innerHTML = '<div class="empty">Загружаем…</div>';
    try {
      await refresh();
      setTab("play");
    } catch (e) {
      $main.innerHTML = `<div class="empty"><b>Не удалось загрузить</b>${esc(e.message || "")}<br><br><button class="btn primary" onclick="location.reload()">Повторить</button></div>`;
    }
  })();
})();
