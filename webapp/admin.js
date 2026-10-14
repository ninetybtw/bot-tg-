// Админка «Дозвона». Открывается из бота: кнопкой /panel внутри Telegram (вход по initData)
// или ссылкой с ключом в браузере (#key=…, действует 24 часа). Вне Telegram без ключа — демо.
(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const ss = { get: k => { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* без хранилища */ } } };
  const hashKey = (location.hash.match(/key=([\w.]+)/) || [])[1];
  if (hashKey) { ss.set("dz_admin_key", hashKey); history.replaceState(null, "", location.pathname); }
  const KEY = hashKey || ss.get("dz_admin_key");
  const INIT = (tg && tg.initData) || ss.get("dz_init");
  const MODE = KEY ? "key" : INIT ? "tma" : window.DemoServer ? "demo" : "none";

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const NB = " ";
  const int = n => String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  const rub = c => `${(c || 0) < 0 ? "−" : ""}${int(Math.abs(c || 0) / 100)}${NB}₽`;
  const date = t => t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  const left = t => { const s = Math.max(0, t - Date.now() / 1000), h = Math.floor(s / 3600); return h >= 24 ? `${Math.floor(h / 24)} д ${h % 24} ч` : `${h} ч ${Math.floor(s % 3600 / 60)} мин`; };
  const REASONS = { start: "старт", spin_common: "Обычная", spin_rare: "Редкая", spin_epic: "Эпическая", spin_legendary: "Легендарная", spin_elite: "Мифическая", spin_secret: "Секретная",
    case_phones: "кейс «Телефоны»", sell: "продажа номеров", sell_device: "продажа телефонов", sell_undo: "отмена продажи", wheel_daily: "колесо дня", wheel_weekly: "колесо недели",
    gift: "подарок дня", task: "задания", task_weekly: "задание недели", referral: "рефералы", upgrade: "улучшение", upgrade_parts: "запчасти", market_buy: "рынок: покупки",
    market_sale: "рынок: продажи", market_fee: "комиссия рынка", raffle: "розыгрыш", overflow_sold: "переполнение", admin: "админ", purchase: "покупка ⭐", vip_daily: "VIP", invited: "приглашение", spin: "спин" };

  async function api(path, body = {}) {
    if (MODE === "demo") return window.DemoServer.call("admin/" + path, body);
    const auth = MODE === "key" ? "admin " + KEY : "tma " + INIT;
    let res;
    try { res = await fetch("/api/admin/" + path, { method: "POST", headers: { "Content-Type": "application/json", Authorization: auth }, body: JSON.stringify(body) }); }
    catch (e) { throw { message: "Нет связи с сервером" }; }
    let data = {};
    try { data = await res.json(); } catch (e) { /* пусто */ }
    if (!res.ok) throw data.error || { message: res.status === 403 ? "Нет доступа к админке" : "Ошибка сервера" };
    return data;
  }

  const root = document.getElementById("adm");
  const TABS = [["home", "Сводка"], ["users", "Игроки"], ["ads", "Реклама"], ["luck", "Удача"], ["mail", "Рассылка"]];
  const st = { tab: "home", ov: null, users: null, q: "", user: null, mult: 5 };
  try { const t = localStorage.getItem("adm_tab"); if (TABS.some(x => x[0] === t)) st.tab = t; } catch (e) { /* */ }
  let toastT;
  function toast(text) {
    document.querySelectorAll(".toast").forEach(t => t.remove());
    const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = text;
    document.body.append(t); clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 3200);
  }
  const fail = e => toast((e && e.message) || "Ошибка");
  const tierName = i => { const t = (st.ov && st.ov.tiers || window.DEMO_CONFIG && DEMO_CONFIG.tiers || [])[i]; return t ? `${t.icon} ${t.name}` : `#${i}`; };

  function frame(inner) {
    root.innerHTML = `<div class="head"><h1>ДОЗВ<i>ОН</i> · админка</h1>${MODE === "demo" ? '<span class="demo">демо</span>' : ""}
      <span class="who">${MODE === "key" ? "вход по ключу" : MODE === "tma" ? "вход через Telegram" : MODE === "demo" ? "данные демо-игры" : ""}</span>
      <button class="btn sm" data-act="reload" aria-label="Обновить">↻</button></div>
      <nav class="tabs">${TABS.map(([k, t]) => `<button class="${st.tab === k ? "on" : ""}" data-act="tab" data-v="${k}">${t}</button>`).join("")}</nav>
      <main id="body">${inner}</main>`;
  }
  const loading = () => `<div class="grid"><div class="skel" style="height:90px"></div><div class="skel" style="height:220px"></div></div>`;

  async function render() {
    if (MODE === "none") {
      root.innerHTML = `<div class="card empty"><b>Админка открывается из бота</b><br>Напиши боту <span class="mono">/panel</span> — он пришлёт кнопку и ссылку для браузера.</div>`;
      return;
    }
    frame(loading());
    try {
      if (!st.ov || st.tab === "home") st.ov = await api("overview");
      const body = document.getElementById("body");
      body.innerHTML = ({ home: homeHTML, users: usersHTML, ads: adsHTML, luck: luckHTML, mail: mailHTML })[st.tab]();
      if (st.tab === "users") loadUsers();
    } catch (e) {
      document.getElementById("body").innerHTML = `<div class="card empty"><b>${esc(e.message || "Ошибка")}</b><br>${MODE === "key" ? "Ключ мог устареть — попроси новый командой /panel" : ""}</div>`;
    }
  }

  // ---------- сводка ----------
  function chartSVG(series) {
    const W = 640, H = 200, pl = 34, pb = 26, pt = 14, n = series.length;
    const max = Math.max(1, ...series.map(d => Math.max(d.active, d.new)));
    const nice = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / nice) * nice;
    const y = v => pt + (H - pt - pb) * (1 - v / top), gw = (W - pl) / n, bw = Math.max(3, Math.min(14, gw / 3 - 2));
    let grid = "";
    for (let i = 0; i <= 2; i++) { const v = top * i / 2; grid += `<line x1="${pl}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(140,170,255,.13)"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end" fill="#8794b4" font-size="11" font-family="JetBrains Mono, monospace">${int(v)}</text>`; }
    const bars = series.map((d, i) => {
      const x = pl + i * gw + gw / 2, label = d.day.slice(8) + "." + d.day.slice(5, 7);
      const bar = (v, dx, c) => v ? `<path d="M${x + dx},${y(0)} V${y(v) + 3} q0,-3 3,-3 h${bw - 6} q3,0 3,3 V${y(0)} Z" fill="${c}"/>` : "";
      return `<g><title>${label}: в игре ${d.active}, новых ${d.new}, спинов ${d.spins}${d.stars ? `, ⭐ ${d.stars}` : ""}</title>
        <rect x="${pl + i * gw}" y="${pt}" width="${gw}" height="${H - pt - pb}" fill="transparent"/>
        ${bar(d.active, -bw - 1, "#2a9d63")}${bar(d.new, 1, "#6a6cf0")}
        ${i % 2 === n % 2 ? "" : `<text x="${x}" y="${H - 8}" text-anchor="middle" fill="#8794b4" font-size="11" font-family="JetBrains Mono, monospace">${label}</text>`}</g>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Игроки за 14 дней">${grid}<line x1="${pl}" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(140,170,255,.3)"/>${bars}</svg>`;
  }
  function homeHTML() {
    const s = st.ov.stats, series = st.ov.series;
    const flows = (s.reasons || []).map(r => `<tr><td>${esc(REASONS[r.reason] || r.reason)}</td><td class="r mono ${r.cents > 0 ? "ok" : ""}">${r.cents > 0 ? "+" : ""}${rub(r.cents)}</td></tr>`).join("");
    const drops = (s.drops_by_tier || []).map(r => `<span class="tier">${esc(tierName(r.tier))} · ${r.n}</span>`).join("") || '<span class="muted">сегодня спинов не было</span>';
    const ev = st.ov.luck_event;
    return `<div class="kpis">
        <div class="kpi"><b>${int(s.users)}</b><span>игроков · живых ${int(s.alive)}</span></div>
        <div class="kpi"><b>${int(s.dau)}</b><span>заходили сегодня</span></div>
        <div class="kpi"><b>${int(s.new_today)}</b><span>новых сегодня</span></div>
        <div class="kpi"><b>${int(s.spins_today)}</b><span>спинов сегодня</span></div>
        <div class="kpi"><b>${int(s.stars_month)} ⭐</b><span>за месяц · всего ${int(s.stars_total)}</span></div>
        <div class="kpi"><b>${int(s.referrals)}</b><span>засчитанных друзей</span></div>
      </div>
      <div class="grid two" style="margin-top:12px">
        <div class="card"><h2>Игроки за 14 дней</h2><div class="chart">${chartSVG(series)}</div>
          <div class="legend"><span><i style="background:#2a9d63"></i>крутили в этот день</span><span><i style="background:#6a6cf0"></i>новые игроки</span></div>
          <div class="tbl" style="margin-top:10px"><table><tr><th>День</th><th class="r">В игре</th><th class="r">Новые</th><th class="r">Спины</th><th class="r">⭐</th></tr>
          ${series.slice(-7).reverse().map(d => `<tr><td class="mono">${d.day.slice(8)}.${d.day.slice(5, 7)}</td><td class="r mono">${d.active}</td><td class="r mono">${d.new}</td><td class="r mono">${d.spins}</td><td class="r mono">${d.stars || 0}</td></tr>`).join("")}</table></div></div>
        <div class="grid">
          <div class="card"><h2>Экономика сегодня</h2>
            <div class="kv"><span>Баланс у всех игроков</span><b class="mono">${rub(s.balance_total_cents)}</b></div>
            <div class="kv"><span>Приток на активного</span><b class="mono">${rub(s.inflow_per_active_cents)}</b></div>
            <h3>Движение монет</h3><div class="tbl"><table>${flows || '<tr><td class="muted">пока пусто</td></tr>'}</table></div>
            <h3>Дропы сегодня</h3><div class="tiers">${drops}</div></div>
          <div class="card"><h2>Сейчас в игре</h2>
            <div class="kv"><span>Реклама</span><b>${st.ov.ads.length} из ${st.ov.ads_max}</b></div>
            <div class="kv"><span>Удача для всех</span><b class="${ev && ev.active ? "ok" : "muted"}">${ev && ev.active ? `×${ev.mult} · ещё ${left(ev.until)} · получили ${ev.claims}` : "не идёт"}</b></div>
          </div>
        </div>
      </div>`;
  }

  // ---------- игроки и подкрутка ----------
  function usersHTML() {
    return `<div class="grid two"><div class="card"><h2>Игроки</h2>
        <form class="row" id="ufind"><input class="grow" id="uq" placeholder="ID, @username или имя" value="${esc(st.q)}" aria-label="Поиск игрока"><button class="btn">Найти</button></form>
        <p class="hint">Без запроса — последние заходившие.</p><div class="users" id="ulist"><div class="skel" style="height:52px"></div></div></div>
      <div class="card" id="ucard">${st.user ? userCardHTML(st.user) : '<div class="empty">Выбери игрока слева, чтобы начислить монеты или подкрутить удачу</div>'}</div></div>`;
  }
  async function loadUsers() {
    const box = document.getElementById("ulist");
    try {
      const r = await api("users", { q: st.q });
      st.users = r.users;
      box.innerHTML = r.users.length ? r.users.map(u => `<button class="user ${st.user && st.user.id === u.id ? "on" : ""}" data-act="user" data-id="${u.id}">
          <span class="av">${esc((u.name || "И")[0])}</span><span class="grow"><b>${esc(u.name)}${u.username ? ` <span class="muted">@${esc(u.username)}</span>` : ""}</b>
          <small class="mono">${u.id} · ур. ${u.level} · ${int(u.total_spins)} спинов · ${date(u.last_seen)}</small></span><span class="mono">${rub(u.balance_cents)}</span></button>`).join("")
        : '<div class="empty">Никого не нашли</div>';
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  function userCardHTML(u) {
    const tiers = obj => Object.entries(obj || {}).sort((a, b) => b[0] - a[0]).map(([t, n]) => `<span class="tier">${esc(tierName(+t))} · ${n}</span>`).join("") || '<span class="muted">пусто</span>';
    const boost = u.boost_min_tier;
    return `<h2>${esc(u.name)} ${u.username ? `<span class="muted">@${esc(u.username)}</span>` : ""}</h2>
      <div class="kv"><span>ID</span><b class="mono">${u.id}</b></div>
      <div class="kv"><span>Баланс</span><b class="mono">${rub(u.balance_cents)} · ${u.attempts} попыток</b></div>
      <div class="kv"><span>Уровень · спинов</span><b class="mono">${u.level} · ${int(u.total_spins)}</b></div>
      <div class="kv"><span>Стоимость коллекции</span><b class="mono">${rub(u.value_cents)}</b></div>
      <div class="kv"><span>Удача</span><b class="${u.luck.spins_left ? "ok" : "muted"}">${u.luck.spins_left ? `×${u.luck.mult} · ещё ${u.luck.spins_left} спинов` : "нет"}</b></div>
      <div class="kv"><span>Подкрутка след. дропа</span><b class="${boost != null ? "warn" : "muted"}">${boost != null ? "не ниже " + esc(tierName(boost)) : "нет"}</b></div>
      <div class="kv"><span>Регион номеров</span><b>${esc(u.region)}</b></div>
      <div class="kv"><span>Друзей · ⭐ потратил</span><b class="mono">${u.ref_count} · ${int(u.stars)}</b></div>
      <div class="kv"><span>С нами с · был</span><b>${date(u.created_at)} · ${date(u.last_seen)}</b></div>
      <h3>Номера</h3><div class="tiers">${tiers(u.items)}</div>
      <h3>Телефоны</h3><div class="tiers">${tiers(u.devices)}</div>

      <h3>Начислить</h3>
      <form class="row" id="fgive"><label class="f">Рубли<input id="grub" inputmode="numeric" placeholder="например 5000 или -1000"></label>
        <label class="f">Попытки<input id="gatt" inputmode="numeric" placeholder="0"></label><button class="btn primary" style="align-self:flex-end">Начислить</button></form>

      <h3>Подкрутка: удача</h3>
      <p class="hint" style="margin-top:0">Шансы старших ступеней ×N на Обычной крутке и в кейсе «Телефоны». Применённые шансы сохраняются в истории бросков игрока.</p>
      <form class="row" id="fluck"><label class="f">Множитель<select id="lm">${[1, 1.5, 2, 3, 5, 10].map(m => `<option value="${m}" ${u.luck.mult === m ? "selected" : ""}>×${String(m).replace(".", ",")}</option>`).join("")}</select></label>
        <label class="f">На сколько спинов<input id="ls" inputmode="numeric" value="${u.luck.spins_left || 20}"></label><button class="btn primary" style="align-self:flex-end">Выдать</button></form>

      <h3>Подкрутка: следующий дроп</h3>
      <p class="hint" style="margin-top:0">Первый номер или телефон следующей крутки будет не ниже выбранной ступени. Срабатывает один раз. Если на крутке, которую выберет игрок, такой ступени нет (на Обычной максимум Мифический), выпадет самая высокая из возможных.</p>
      <div class="chips">${[2, 3, 4, 5, 6].map(t => `<button class="chip ${boost === t ? "on" : ""}" data-act="boost" data-v="${t}">${esc(tierName(t))}</button>`).join("")}
        ${boost != null ? '<button class="chip" data-act="boost" data-v="">Снять</button>' : ""}</div>

      <h3>Последние операции</h3><div class="tbl"><table>${(u.ledger || []).map(l => `<tr><td>${esc(REASONS[l.reason] || l.reason)}</td><td class="muted">${date(l.created_at)}</td>
        <td class="r mono ${l.delta > 0 ? "ok" : ""}">${l.delta > 0 ? "+" : ""}${l.currency === "rub" ? rub(l.delta) : l.delta + " поп."}</td></tr>`).join("") || '<tr><td class="muted">пусто</td></tr>'}</table></div>`;
  }
  async function openUser(id) {
    const card = document.getElementById("ucard");
    card.innerHTML = '<div class="skel" style="height:300px"></div>';
    try { st.user = await api("user", { id }); card.innerHTML = userCardHTML(st.user); document.querySelectorAll(".user").forEach(b => b.classList.toggle("on", +b.dataset.id === id)); if (innerWidth < 820) card.scrollIntoView({ behavior: "smooth" }); }
    catch (e) { card.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  async function userAction(path, body, okText) {
    try { st.user = await api(path, { id: st.user.id, ...body }); document.getElementById("ucard").innerHTML = userCardHTML(st.user); toast(okText); loadUsers(); }
    catch (e) { fail(e); }
  }

  // ---------- реклама ----------
  const adPreview = a => `<div class="ad"><span class="ic">${esc(a.icon || "📣")}</span><span class="body"><b>${esc(a.title || "Заголовок")}</b><span>${esc(a.text || "")}</span></span><span class="go">${esc(a.button || "Открыть")}</span></div>`;
  function adsHTML() {
    const ads = st.ov.ads, max = st.ov.ads_max;
    const list = ads.map((x, i) => {
      const a = x.ad, v = x.view, c = x.click, ctr = v.users ? (c.users / v.users * 100).toFixed(1).replace(".", ",") + "%" : "—";
      return `<div class="adrow"><div class="row"><b>№${i + 1}</b><span class="muted grow mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.url)}</span>
          <button class="btn sm" data-act="ad-edit" data-id="${a.id}">Изменить</button><button class="btn sm danger" data-act="ad-del" data-id="${a.id}">Снять</button></div>
        ${adPreview(a)}
        <div class="stat3"><div><b>${int(v.users)}</b><span>увидели · сегодня ${int(v.users_today)}</span></div><div><b>${int(c.users)}</b><span>перешли · сегодня ${int(c.users_today)}</span></div><div><b>${ctr}</b><span>конверсия</span></div></div></div>`;
    }).join("");
    const edit = st.adEdit ? ads.find(x => x.ad.id === st.adEdit) : null;
    const a = edit ? edit.ad : {};
    return `<div class="grid two"><div class="card"><h2>На главном экране · ${ads.length} из ${max}</h2>
        ${list || `<div class="empty">Своей рекламы нет${st.ov.ads_contact ? ` — игроки видят заглушку «Ваша реклама здесь» с контактом @${esc(st.ov.ads_contact)}` : ""}</div>`}
        <p class="hint">Баннеры листаются сами каждые 5 секунд. «Увидели» — уникальные игроки, которым показали баннер.</p></div>
      <div class="card"><h2>${edit ? "Изменить рекламу" : "Новая реклама"}</h2>
        ${!edit && ads.length >= max ? `<div class="empty">Уже ${max} рекламы — сними одну, чтобы поставить новую</div>` : `
        <form id="fad" class="grid" style="gap:10px">
          <div class="row"><label class="f" style="flex:0 0 76px;min-width:0">Значок<input id="ai" maxlength="4" value="${esc(a.icon || "📣")}"></label>
            <label class="f">Заголовок · до 40<input id="at" maxlength="40" required value="${esc(a.title || "")}" placeholder="Канал про красивые номера"></label></div>
          <label class="f">Текст · до 80<input id="ax" maxlength="80" value="${esc(a.text || "")}" placeholder="Каждый день — номер дня"></label>
          <div class="row"><label class="f">Ссылка<input id="au" required value="${esc(a.url || "")}" placeholder="https://t.me/канал"></label>
            <label class="f" style="flex:0 0 130px">Кнопка<input id="ab" maxlength="16" value="${esc(a.button || "Открыть")}"></label></div>
          <h3 style="margin:4px 0 0">Так увидят игроки</h3><div id="apv">${adPreview(a)}</div>
          <div class="row">${edit ? '<button type="button" class="btn" data-act="ad-cancel">Отмена</button>' : ""}<button class="btn primary grow">${edit ? "Сохранить" : "Поставить на главный экран"}</button></div>
        </form>`}</div></div>`;
  }
  function adForm() { return { icon: val("ai"), title: val("at"), text: val("ax"), url: val("au"), button: val("ab") }; }
  const val = id => (document.getElementById(id) || {}).value || "";

  // ---------- удача для всех ----------
  function luckHTML() {
    const ev = st.ov.luck_event, mults = st.ov.luck_mults;
    const cur = ev && ev.active ? `<div class="event"><div class="row"><span class="big">×${ev.mult}</span><span class="grow"><b>${esc(ev.title)}</b><br><span class="muted">${ev.spins} спинов с удачей · осталось ${left(ev.until)}</span></span>
        <button class="btn danger" data-act="luck-stop">Остановить</button></div>
        <div class="stat3" style="margin-top:10px"><div><b>${int(ev.claims)}</b><span>получили удачу</span></div><div><b class="mono" style="font-size:13px">${esc(ev.chat_id)}</b><span>канал</span></div><div><b class="mono" style="font-size:13px">${date(ev.until)}</b><span>до</span></div></div></div>`
      : `<div class="empty">Сейчас акции нет</div>`;
    return `<div class="grid two"><div class="card"><h2>Удача для всех</h2>${cur}
        <p class="hint">Игроки видят баннер «Удача ×N» среди рекламы на главном экране. Нажимают «Подписаться», затем «Проверить» — бот проверяет подписку и включает удачу на N спинов Обычной и кейса «Телефоны».</p>
        <p class="hint warn">Бот должен быть администратором канала, иначе он не видит подписчиков.</p></div>
      <div class="card"><h2>${ev && ev.active ? "Запустить заново" : "Запустить акцию"}</h2>
        <form id="fluckev" class="grid" style="gap:10px">
          <div><div class="hint" style="margin:0 0 6px">Множитель</div><div class="chips">${mults.map(m => `<button type="button" class="chip ${st.mult === m ? "on" : ""}" data-act="mult" data-v="${m}">×${m}</button>`).join("")}</div></div>
          <div class="row"><label class="f">Спинов с удачей<input id="es" inputmode="numeric" value="20"></label><label class="f">Сколько идёт акция, часов<input id="eh" inputmode="numeric" value="24"></label></div>
          <label class="f">Канал для подписки<input id="ec" required placeholder="@my_channel или https://t.me/my_channel"></label>
          <label class="f">Заголовок баннера<input id="et" maxlength="40" placeholder="Удача ×${st.mult} для всех"></label>
          <button class="btn primary">Запустить ×${st.mult}</button>
        </form></div></div>`;
  }

  // ---------- рассылка ----------
  function mailHTML() {
    return `<div class="grid two"><div class="card"><h2>Рассылка всем игрокам</h2>
      <form id="fmail" class="grid" style="gap:10px"><label class="f">Текст сообщения<textarea id="mt" maxlength="3500" placeholder="Сегодня в 20:00 розыгрыш…"></textarea></label>
        <label class="row" style="font-weight:700"><input type="checkbox" id="mb" checked style="width:auto"> Кнопка «Играть» под сообщением</label>
        <button class="btn primary" id="msend">Отправить всем</button></form>
      <p class="hint">Отправка идёт по 25 сообщений в секунду. Когда закончится, бот пришлёт тебе отчёт: сколько доставлено и сколько заблокировали бота.</p></div>
      <div class="card"><h2>Ещё в боте</h2><p class="hint" style="margin-top:0">Картинки и видео в рассылке — командой /broadcast в чате с ботом. Шансы и цены — /config и /setconfig. Возврат звёзд — /refund.</p></div></div>`;
  }

  // ---------- события ----------
  document.addEventListener("click", async e => {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const a = el.dataset.act;
    if (a === "tab") { st.tab = el.dataset.v; st.adEdit = null; try { localStorage.setItem("adm_tab", st.tab); } catch (x) { /* */ } render(); }
    else if (a === "reload") { st.ov = null; render(); }
    else if (a === "user") openUser(+el.dataset.id);
    else if (a === "boost") userAction("boost", { tier: el.dataset.v === "" ? null : +el.dataset.v }, el.dataset.v === "" ? "Подкрутка снята" : "Следующий дроп будет не ниже " + tierName(+el.dataset.v));
    else if (a === "ad-edit") { st.adEdit = +el.dataset.id; document.getElementById("body").innerHTML = adsHTML(); }
    else if (a === "ad-cancel") { st.adEdit = null; document.getElementById("body").innerHTML = adsHTML(); }
    else if (a === "ad-del") {
      if (el.dataset.sure !== "1") { el.dataset.sure = "1"; el.textContent = "Точно снять?"; return; }
      try { const r = await api("ads/remove", { id: +el.dataset.id }); st.ov.ads = r.ads; document.getElementById("body").innerHTML = adsHTML(); toast("Реклама снята"); } catch (x) { fail(x); }
    }
    else if (a === "mult") { st.mult = +el.dataset.v; document.getElementById("body").innerHTML = luckHTML(); }
    else if (a === "luck-stop") {
      if (el.dataset.sure !== "1") { el.dataset.sure = "1"; el.textContent = "Точно остановить?"; return; }
      try { await api("luck_event/stop"); st.ov.luck_event = null; document.getElementById("body").innerHTML = luckHTML(); toast("Акция остановлена"); } catch (x) { fail(x); }
    }
  });
  document.addEventListener("input", e => { if (e.target.closest("#fad")) document.getElementById("apv").innerHTML = adPreview(adForm()); });
  document.addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, btn = f.querySelector("button:not([type=button])");
    if (btn) btn.disabled = true;
    try {
      if (f.id === "ufind") { st.q = val("uq"); await loadUsers(); }
      else if (f.id === "fgive") await userAction("give", { rubles: +(val("grub").replace(/\s/g, "").replace(",", ".") || 0), attempts: +val("gatt") || 0 }, "Начислено");
      else if (f.id === "fluck") await userAction("luck", { mult: +val("lm"), spins: +val("ls") || 0 }, "Удача выдана");
      else if (f.id === "fad") {
        const r = await api("ads/save", { ...adForm(), id: st.adEdit || undefined });
        st.ov.ads = r.ads; const was = st.adEdit; st.adEdit = null;
        document.getElementById("body").innerHTML = adsHTML(); toast(was ? "Реклама обновлена" : "Реклама на главном экране");
      } else if (f.id === "fluckev") {
        const r = await api("luck_event/start", { mult: st.mult, spins: +val("es"), hours: +val("eh"), channel: val("ec"), title: val("et") });
        st.ov.luck_event = r.luck_event; document.getElementById("body").innerHTML = luckHTML();
        toast(r.warning || `Удача ×${st.mult} запущена`);
      } else if (f.id === "fmail") {
        if (btn && btn.dataset.sure !== "1") { btn.dataset.sure = "1"; btn.textContent = "Точно отправить всем?"; btn.disabled = false; return; }
        const r = await api("broadcast", { text: val("mt"), button: document.getElementById("mb").checked });
        toast(`Рассылка пошла: ${int(r.recipients)} игроков`); document.getElementById("body").innerHTML = mailHTML();
      }
    } catch (x) { fail(x); }
    if (btn && document.body.contains(btn)) btn.disabled = false;
  });

  if (tg) { try { tg.ready(); tg.expand(); tg.setHeaderColor && tg.setHeaderColor("#060a14"); tg.setBackgroundColor && tg.setBackgroundColor("#060a14"); } catch (e) { /* */ } }
  render();
})();
