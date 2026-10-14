// Демо-сервер для просмотра мини-приложения вне Telegram. Повторяет API bot/web.py и правила
// bot/game/service.py на клиенте: те же шансы, гарантии, тиражи, продажа с отменой и честный бросок
// (HMAC-SHA256 через WebCrypto). Номера берутся из пула, собранного настоящим генератором
// (scripts/build_demo_config.py). В Telegram с initData не используется.
(() => {
  "use strict";
  const C = window.DEMO_CONFIG, D = window.DEMO_DATA;
  if (!C || !D) return;
  const G = D.game, LAD = C.ladder_cents;
  const EPIC = 3, LEGENDARY = 4, RARE = 2, SECRET = 6;
  const KEY = "dozvon-demo-v16";
  const now = () => Date.now() / 1000;
  const MSK = 3 * 3600;
  const dayKey = ts => new Date((ts + MSK) * 1000).toISOString().slice(0, 10);
  const weekKey = ts => {
    const d = new Date((ts + MSK) * 1000); d.setUTCHours(0, 0, 0, 0);
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const y = d.getUTCFullYear(), w = Math.ceil(((d - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
    return `W${y}-${String(w).padStart(2, "0")}`;
  };
  const err = (message, code = "BAD_REQUEST", extra = {}) => { throw { code, message, ...extra }; };
  const level = key => C.levels.find(l => l.key === key);
  const oddsObj = lv => Object.fromEntries(lv.odds.map(r => [r.tier, r.p]));
  const sumP = (o, f) => Object.entries(o).reduce((a, [t, p]) => a + (f(+t) ? p : 0), 0);
  const COUNTRIES = C.currency.countries;
  function money(cents) {
    const c = COUNTRIES[S.user.country] || COUNTRIES.RU;
    const [a, b] = (cents / 100 * c.rate).toFixed(c.decimals).split(".");
    return `${a.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${b ? "," + b : ""} ${c.symbol}`;
  }

  // ---------- честный бросок ----------
  const subtle = window.crypto && crypto.subtle;
  const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
  const bytes = h => { const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; };
  const randHex = n => { const a = new Uint8Array(n); crypto.getRandomValues(a); return hex(a); };
  async function seedHash(s) { return subtle ? hex(await subtle.digest("SHA-256", bytes(s))) : randHex(32); }
  async function roll(server, client, nonce, i) {
    if (!subtle) return Math.random();
    const k = await subtle.importKey("raw", bytes(server), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = hex(await subtle.sign("HMAC", k, new TextEncoder().encode(`${client}:${nonce}:${i}`)));
    return parseInt(sig.slice(0, 13), 16) / 2 ** 52;
  }
  function pickTier(u, odds) {
    let acc = 0;
    const keys = Object.keys(odds).map(Number).sort((a, b) => a - b);
    for (const t of keys) { acc += odds[t]; if (u < acc) return t; }
    return keys[keys.length - 1];
  }

  // ---------- шансы ----------
  function applyLuck(odds, m) {
    const keys = Object.keys(odds).map(Number);
    if (m <= 1 || keys.length < 3) return { ...odds };
    const top = [...keys].sort((a, b) => odds[b] - odds[a]).slice(0, 2);
    const out = {};
    keys.filter(k => !top.includes(k)).forEach(k => { out[k] = odds[k] * m; });
    const boosted = Object.values(out).reduce((a, b) => a + b, 0);
    if (boosted > 0.9) Object.keys(out).forEach(k => { out[k] *= 0.9 / boosted; }); // как на сервере
    const rest = 1 - Object.values(out).reduce((a, b) => a + b, 0);
    const cs = top.reduce((a, k) => a + odds[k], 0);
    top.forEach(k => { out[k] = odds[k] * rest / cs; });
    return out;
  }
  const groupProb = (base, n, soft, step, hard) => n >= hard ? 1 : n >= soft ? Math.min(1, base + (n - soft + 1) * step) : base;
  function pityChances(odds, pe, pl) {
    const A = C.pity.epic_plus, B = C.pity.legend_plus;
    const qb = groupProb(sumP(odds, t => t >= LEGENDARY), pl + 1, B.soft, B.step_pct / 100, B.hard);
    const qa = Math.max(groupProb(sumP(odds, t => t >= EPIC), pe + 1, A.soft, A.step_pct / 100, A.hard), qb);
    return [qa, qb];
  }
  function withPity(odds, pe, pl) {
    let [pa, pb] = pityChances(odds, pe, pl);
    pb = Math.min(pb, 1); pa = Math.max(Math.min(pa, 1), pb);
    const out = {};
    for (const [f, share] of [[t => t >= LEGENDARY, pb], [t => t >= EPIC && t < LEGENDARY, pa - pb], [t => t < EPIC, 1 - pa]]) {
      const s = sumP(odds, f);
      for (const t in odds) if (f(+t)) out[t] = s ? odds[t] / s * share : 0;
    }
    return out;
  }
  function levelFromXp(xp) {
    let lvl = 1, need = 100;
    while (xp >= need) { xp -= need; lvl++; need = 100 + 50 * (lvl - 1); }
    return [lvl, xp, need];
  }

  // ---------- состояние ----------
  let S = null;
  const OTHERS = [["Алина", true, 10], ["Макс", true, 7], ["Денис", true, 3], ["Катя", false], ["Тимур", false], ["Саша", false], ["Ира", false], ["Артём", false]];
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* без хранилища */ } };
  const counter = (key, inc = 0, day = dayKey(now())) => {
    const k = day + "|" + key;
    if (inc) S.counters[k] = (S.counters[k] || 0) + inc;
    return S.counters[k] || 0;
  };
  const ledger = (currency, delta, reason) => { if (delta) S.ledger.push({ currency, delta, reason, created_at: now() }); };
  const add = (cents, attempts, reason) => { S.user.balance += cents; S.user.attempts += attempts; ledger("rub", cents, reason); ledger("attempts", attempts, reason); };
  async function newPair(client) {
    const server = randHex(32);
    const pair = { id: S.seeds.length + 1, server_seed: server, server_hash: await seedHash(server), client_seed: client || randHex(8), nonce: 0, active: true, revealed_at: null };
    S.seeds.push(pair);
    return pair;
  }
  const pair = () => S.seeds.find(p => p.active);

  async function init() {
    try { S = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { S = null; }
    if (S && S.v === 2) return;
    const t = now();
    S = {
      v: 2, nextId: 1, items: [], editions: {}, drops: [], ledger: [], sales: [], lots: [], counters: {}, seeds: [], payments: [], feed: [], devices: [], ads: [],
      luck_event: { id: 1, mult: 5, spins: 20, until: t + 3 * 86400, url: "https://t.me/telegram", chat_id: "@telegram", title: "Удача ×5 для всех", started_at: t },
      user: {
        id: 1, name: "Гость", created_at: t - 3 * 86400, balance: G.start_cents, attempts: 0, energy: G.energy.max, energy_ts: t, xp: 0,
        total_spins: 0, pity_epic: 0, pity_legend: 0, luck_mult: 1, luck_left: 0, upgrade_bonus: 0, vip_until: null, vip_day: null,
        slots_extra: 0, slots_bought: 0, start_pack: false, starter_used: false, country: "RU", country_confirmed: false,
        country_changed_at: null, settings: {}, showcase: [], badges: [], gift_day: dayKey(t - 86400), gift_streak: 2, ref_count: 2,
        region: null, boost_min_tier: null, username: "guest",
      },
      others: OTHERS.map(([name, friend, spins], i) => ({ id: 100 + i, name, friend, spins: spins || 0, country: ["RU", "KZ", "BY", "UZ", "RU", "KG", "AM", "RU"][i], xp: 300 + ((i * 397) % 2400), extra: 1500000 + ((i * 7919) % 9) * 900000 })),
      raffle: {},
    };
    ledger("rub", G.start_cents, "start");
    await newPair();
    // задания в прошлые дни: колесо недели откроется после первого задания сегодня
    for (let d = 1; d <= 4; d++) S.counters[dayKey(t - d * 86400) + "|claimed:spin3"] = 1;
    // мир: у других игроков есть номера, лоты на рынке и Эпик+ в ленте
    const lotTiers = [0, 1, 1, 2, 2, 3, 3, 4, 5, 2, 0, 3];
    lotTiers.forEach((tier, i) => {
      const o = S.others[i % S.others.length];
      const it = issue(o.id, tier, (i * 0.137 + 0.05) % 1, "spin", "listed");
      it.created_at = t - 86400 * (1 + i % 3);
      const k = [0.8, 1.15, 0.95, 1.3, 0.7, 1.05][i % 6];
      S.lots.push({ id: i + 1, item_id: it.id, seller_id: o.id, price_cents: Math.round(LAD[tier] * k / 100) * 100, created_at: t - 3600 * (i + 1), expires_at: t + 86400 * 2, status: "active" });
    });
    [[0, 4], [1, 3], [3, 5], [4, 3], [2, 3], [5, 4], [6, 6], [7, 3]].forEach(([oi, tier], i) => {
      const o = S.others[oi];
      const it = issue(o.id, tier, (i * 0.311 + 0.2) % 1, "spin", "free");
      S.feed.push({ user_id: o.id, item_id: it.id, created_at: t - 600 * (i + 1) });
    });
    const yd = dayKey(t - 86400), ys = randHex(32);
    S.raffle[yd] = { server_seed: ys, server_hash: await seedHash(ys), drawn: true, winners: [{ name: "Катя", place: 1, prize: "⬢ Эпик номер" }, { name: "Макс", place: 2, prize: "◆ Редкий номер" }, { name: "Ира", place: 3, prize: "◆ Редкий номер" }] };
    save();
  }
  async function raffleRow(day) {
    if (!S.raffle[day]) { const s = randHex(32); S.raffle[day] = { server_seed: s, server_hash: await seedHash(s), drawn: false, winners: [] }; }
    return S.raffle[day];
  }

  // ---------- предметы ----------
  function energy() {
    const u = S.user, mx = G.energy.max, period = G.energy.regen_minutes * 60, t = now();
    if (u.energy >= mx) return [u.energy, t];
    const gained = Math.floor((t - u.energy_ts) / period);
    if (gained <= 0) return [u.energy, u.energy_ts];
    const e = Math.min(mx, u.energy + gained);
    return [e, e >= mx ? t : u.energy_ts + gained * period];
  }
  const vip = () => !!(S.user.vip_until && S.user.vip_until > now());
  const capacity = () => Math.min(C.inventory.slots_max, C.inventory.slots + S.user.slots_extra + (vip() ? G.shop.vip_slots : 0));
  const coinCap = () => Math.min(G.coin_spins.per_day_max, G.coin_spins.per_day_base + G.coin_spins.per_level * (levelFromXp(S.user.xp)[0] - 1));
  const mine = (states = ["free", "listed"]) => S.items.filter(i => i.user_id === 1 && states.includes(i.state));
  function slots() {
    return { used: mine().length, total: capacity(), overflow: mine(["overflow"]).length, overflow_max: C.inventory.overflow_slots };
  }
  function promoteOverflow() {
    let free = capacity() - mine().length;
    for (const i of mine(["overflow"]).sort((a, b) => a.id - b.id)) { if (free <= 0) break; i.state = "free"; i.overflow_until = null; free--; }
  }
  function place(n) {
    const s = slots(), free = Math.max(0, s.total - s.used), over = Math.max(0, s.overflow_max - s.overflow);
    if (n > free + over) err("Нет места: освободи коллекцию — продай лишнее или выставь на рынок", "INVENTORY_FULL");
    return Array.from({ length: n }, (_, i) => i < free ? "free" : "overflow");
  }
  function issue(uid, tier, u1, source, state = "free") {
    // номер — из страны владельца, как на сервере
    const country = uid === 1 ? (S.user.region || S.user.country) : (S.others.find(o => o.id === uid) || {}).country || "RU";
    const pool = (D.pool[country] || D.pool.RU)[tier];
    const size = +(C.editions[String(tier)] || 1);
    const start = Math.floor(u1 * pool.length);
    for (let k = 0; k < pool.length; k++) {
      const [op, sub, rule, hl] = pool[(start + k) % pool.length];
      const key = `${country}:${op}${sub}`;
      const ed = S.editions[key] || (S.editions[key] = { size, issued: size > 1 ? Math.floor(u1 * 7) % size : 0 });
      if (ed.issued >= ed.size) continue;
      ed.issued++;
      const t = now();
      const it = { id: S.nextId++, user_id: uid, country, op, sub, key, tier: tier === 7 ? 7 : tier, rule, hl, source, state, serial_no: ed.issued, edition_size: size, created_at: t, locked: false, favorite: false, is_new: uid === 1, hold_until: null, overflow_until: state === "overflow" ? t + C.inventory.overflow_hours * 3600 : null };
      S.items.push(it);
      return it;
    }
    err("Тираж этой ступени закончился. Попробуй позже", "CONFLICT");
  }
  function formatNumber(country, op, sub) {
    const c = D.countries[country];
    if (c.regroup && c.regroup.length) {
      const digits = op + sub;
      let k = 0;
      const g = c.regroup.map(n => { const x = digits.slice(k, k + n); k += n; return x; });
      return `${c.dial} ${g[0]} ${g.slice(1).join(c.sep)}`;
    }
    let i = 0;
    const parts = c.groups.map(g => { const s = sub.slice(i, i + g); i += g; return s; });
    return `${c.dial} ${op} ${parts.join(c.sep)}`;
  }
  const tierDict = i => C.tiers[i];
  function view(r) {
    const c = D.countries[r.country];
    const common = oddsObj(C.levels[0]);
    return {
      id: r.id, user_id: r.user_id, country: r.country, flag: c.flag, country_name: c.name, dial: c.dial, op: r.op, sub: r.sub,
      number: formatNumber(r.country, r.op, r.sub), tier: tierDict(r.tier), rule: r.rule, rule_name: C.rules[r.rule] || r.rule,
      highlight: r.hl, price_cents: LAD[r.tier], got_price_cents: LAD[r.tier], sell_cents: Math.floor(LAD[r.tier] * C.sell_system_pct / 100),
      one_in: common[r.tier] ? Math.max(1, Math.round(1 / common[r.tier])) : null,
      copy: r.edition_size > 1 ? { no: r.serial_no, of: r.edition_size, in_game: S.editions[r.key].issued } : null,
      state: r.state, locked: r.locked, favorite: r.favorite, is_new: r.is_new, source: r.source, created_at: r.created_at,
      hold_until: r.hold_until && r.hold_until > now() ? r.hold_until : null, overflow_until: r.overflow_until,
    };
  }
  function owned(ids, states = ["free"]) {
    ids = [...new Set(ids.map(Number))];
    if (!ids.length) err("Ничего не выбрано");
    const rows = S.items.filter(i => i.user_id === 1 && ids.includes(i.id) && states.includes(i.state));
    if (rows.length !== ids.length) {
      if (S.items.some(i => i.user_id === 1 && ids.includes(i.id) && i.state === "listed")) err("Номер выставлен на рынке. Сначала сними лот", "ITEM_BUSY");
      err("Часть номеров уже недоступна. Обнови коллекцию", "CONFLICT");
    }
    return rows;
  }
  const collectionValue = uid => S.items.filter(i => i.user_id === uid && i.state !== "gone").reduce((a, i) => a + LAD[i.tier], 0);

  // ---------- задания ----------
  function todayTasks(ts) {
    let h = 0;
    for (const ch of dayKey(ts)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const pool = [...G.tasks];
    for (let i = pool.length - 1; i > 0; i--) { h = (h * 1103515245 + 12345) >>> 0; const j = h % (i + 1); [pool[i], pool[j]] = [pool[j], pool[i]]; }
    return pool.slice(0, G.tasks_per_day);
  }
  function taskEvent(event, n = 1) {
    const t = now();
    todayTasks(t).forEach(x => { if (x.event === event) counter("task:" + x.key, n); });
    G.weekly_tasks.forEach(x => { if (x.event === event) counter("wtask:" + x.key, n, weekKey(t)); });
  }
  function taskDays() {
    const t = now();
    let n = 0;
    for (let i = 0; i < 7; i++) {
      const d = dayKey(t - i * 86400) + "|claimed:";
      if (Object.keys(S.counters).some(k => k.startsWith(d))) n++;
    }
    return n;
  }
  function dailyVip() {
    const today = dayKey(now());
    if (vip() && S.user.vip_day !== today) { S.user.vip_day = today; add(0, G.shop.vip_daily_attempts, "vip_daily"); }
  }

  // ---------- эндпоинты ----------
  const H = {};
  H.config = () => C;
  H.ad = () => ({ ok: true });
  H.me = () => {
    dailyVip(); promoteOverflow();
    const u = S.user, t = now(), [e, ets] = energy(), [lvl, xpIn, need] = levelFromXp(u.xp);
    const today = dayKey(t), yesterday = dayKey(t - 86400), week = weekKey(t);
    const common = oddsObj(C.levels[0]);
    const odds = u.luck_left > 0 ? applyLuck(common, u.luck_mult) : common;
    const [qa, qb] = pityChances(odds, u.pity_epic, u.pity_legend);
    const lastDrop = [...S.drops].reverse().find(d => d.action === "spin" && d.kind !== "device");
    const sale = [...S.sales].reverse().find(s => !s.undone && s.undo_until > t);
    const changeAfter = u.country_changed_at ? u.country_changed_at + C.currency.change_days * 86400 : null;
    const td = taskDays();
    return {
      user: { id: 1, name: u.name, level: lvl, xp: xpIn, xp_need: need, total_spins: u.total_spins, badges: u.badges, vip_until: vip() ? u.vip_until : null, created_at: u.created_at, showcase: u.showcase },
      country: u.country, country_confirmed: u.country_confirmed, country_change_after: changeAfter && changeAfter > t ? changeAfter : null,
      currency: { country: u.country, ...COUNTRIES[u.country], game_label: C.currency.show_game_label },
      balance_cents: u.balance, attempts: u.attempts,
      energy: { now: e, max: G.energy.max, next_in: e >= G.energy.max ? 0 : Math.floor(G.energy.regen_minutes * 60 - (t - ets)) },
      coin_spins_left: Math.max(0, coinCap() - counter("coin_spins")),
      upper_spins_left: Math.max(0, G.upper_levels_per_day - counter("upper_spins")),
      luck: u.luck_left > 0 ? { mult: u.luck_mult, spins_left: u.luck_left } : null,
      pity: { epic_in: C.pity.epic_plus.hard - u.pity_epic, epic_chance: qa, legend_in: C.pity.legend_plus.hard - u.pity_legend, legend_chance: qb },
      slots: slots(), starter: !u.starter_used,
      settings: { fast: false, no_effects: false, no_upgrader: false, ...u.settings },
      today: {
        gift: u.gift_day !== today,
        gift_day: u.gift_day !== today ? (u.gift_day === yesterday ? (u.gift_streak % 7) + 1 : 1) : u.gift_streak,
        wheel_daily: counter("wheel") === 0,
        wheel_weekly: td >= G.wheel_weekly.unlock_days && !counter("wheel_weekly", 0, week),
        wheel_weekly_used: !!counter("wheel_weekly", 0, week),
        task_days: td,
        tasks: todayTasks(t).map(x => ({ key: x.key, title: x.title, target: x.target, cents: x.cents, progress: Math.min(counter("task:" + x.key), x.target), claimed: !!counter("claimed:" + x.key) })),
        weekly_tasks: G.weekly_tasks.map(x => ({ key: x.key, title: x.title, target: x.target, cents: x.cents, badge: x.badge, progress: Math.min(counter("wtask:" + x.key, 0, week), x.target), claimed: !!counter("wclaimed:" + x.key, 0, week) })),
        tickets: counter("tickets"),
      },
      last_drop: lastDrop ? view(S.items.find(i => i.id === lastDrop.item_id)) : null,
      last_sale: sale ? { id: sale.id, amount_cents: sale.amount_cents, undo_until: sale.undo_until, count: sale.item_ids.length } : null,
      stars_enabled: true, ref_link: "https://t.me/твой_бот?start=r1",
      ads: S.ads.length ? S.ads.map(({ id, title, text, url, button, icon }) => ({ id, title, text, url, button, icon }))
        : [{ id: 0, placeholder: true, icon: "📣", title: "Ваша реклама здесь", text: "Её увидит каждый игрок", button: "Связаться", url: "https://t.me/" }],
      region: u.region || u.country, is_admin: true,
      device_free: counter("device_free", 0, "all") ? 0 : 1,
      luck_event: S.luck_event && S.luck_event.until > t ? { id: S.luck_event.id, mult: S.luck_event.mult, spins: S.luck_event.spins, until: S.luck_event.until, url: S.luck_event.url, title: S.luck_event.title, claimed: !!counter("luck_claim:" + S.luck_event.id, 0, "event") } : null,
    };
  };
  H.country = b => {
    const u = S.user, code = String(b.country), t = now();
    if (!COUNTRIES[code]) err("Такой страны нет в списке");
    if (u.country_confirmed && code !== u.country) {
      const after = (u.country_changed_at || 0) + C.currency.change_days * 86400;
      if (after > t) err(`Страну можно менять раз в 30 дней. Следующая смена с ${new Date(after * 1000).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}`, "NOT_ALLOWED_YET");
      u.country_changed_at = t;
    }
    u.country = code; u.country_confirmed = true;
    return { country: code };
  };
  H.settings = b => {
    for (const k of ["fast", "no_effects", "no_upgrader"]) if (k in b) S.user.settings[k] = !!b[k];
    return { fast: false, no_effects: false, no_upgrader: false, ...S.user.settings };
  };
  H.spin = async b => {
    const lv = level(String(b.level || "common"));
    if (!lv) err("Нет такого уровня крутки");
    const count = +b.count || 1;
    if (!C.counts.includes(count)) err("Можно крутить ×1, ×3, ×5 или ×10");
    const common = lv.key === "common", u = S.user, t = now();
    dailyVip(); promoteOverflow();
    const [e, ets] = energy();
    const places = place(count);
    const useE = common ? Math.min(e, count) : 0, useA = common ? Math.min(u.attempts, count - useE) : 0, useC = count - useE - useA;
    if (common) {
      if (useC > coinCap() - counter("coin_spins")) err(`Спины за монеты на сегодня закончились (${coinCap()} в сутки). Бесплатные спины и попытки работают`, "DAILY_LIMIT");
    } else {
      const left = G.upper_levels_per_day - counter("upper_spins");
      if (count > left) err(`Уровни выше Обычной — до ${G.upper_levels_per_day} круток в сутки. Сегодня осталось ${Math.max(left, 0)}`, "LEVEL_LIMIT");
    }
    const cost = useC * lv.price_cents;
    if (cost > u.balance) err(`Не хватает ${money(cost - u.balance)}. Задания и колесо дадут монеты`, "NOT_ENOUGH_COINS", { need_cents: cost - u.balance });
    const starter = common && count === G.starter.count && !u.starter_used;
    if (cost && !b.confirmed && !starter && (cost >= C.confirm_from_cents || cost > u.balance * C.confirm_balance_share)) err(`Подтверди покупку: ${money(cost)}`, "CONFIRM_REQUIRED", { cost_cents: cost });
    const p = pair();
    let luckLeft = u.luck_left, pe = u.pity_epic, pl = u.pity_legend, gotMin = false;
    const drops = [];
    for (let i = 0; i < count; i++) {
      let odds = oddsObj(lv), luck = 1;
      if (common && luckLeft > 0) { luck = u.luck_mult; odds = applyLuck(odds, luck); luckLeft--; }
      if (lv.pity) odds = withPity(odds, pe, pl);
      if (starter && i === count - 1 && !gotMin) {
        const m = G.starter.min_tier, s = sumP(odds, x => x >= m);
        odds = Object.fromEntries(Object.entries(odds).filter(([x]) => +x >= m).map(([x, q]) => [x, q / s]));
      }
      if (u.boost_min_tier != null && i === 0) odds = restrict(odds, u.boost_min_tier);
      const nonce = ++p.nonce;
      const u0 = await roll(p.server_seed, p.client_seed, nonce, 0), u1 = await roll(p.server_seed, p.client_seed, nonce, 1);
      const tier = pickTier(u0, odds);
      gotMin = gotMin || tier >= G.starter.min_tier;
      const it = issue(1, tier, u1, useC || !common ? "spin" : "free", places[i]);
      S.drops.push({ id: S.drops.length + 1, item_id: it.id, action: "spin", level: lv.key, tier, odds, u0, seed_id: p.id, server_hash: p.server_hash, client_seed: p.client_seed, nonce, created_at: t });
      if (tier >= EPIC) S.feed.push({ user_id: 1, item_id: it.id, created_at: t });
      if (lv.pity) { pe = tier >= EPIC ? 0 : pe + 1; pl = tier >= LEGENDARY ? 0 : pl + 1; }
      drops.push({ ...view(it), fair: { server_hash: p.server_hash, client_seed: p.client_seed, nonce } });
    }
    const xpGain = count * Math.max(10, Math.floor(lv.price_cents / 10000));
    const before = levelFromXp(u.xp)[0];
    u.balance -= cost; u.attempts -= useA; u.energy = e - useE; u.energy_ts = ets;
    u.pity_epic = pe; u.pity_legend = pl; u.luck_left = luckLeft; u.xp += xpGain; u.total_spins += count;
    if (starter) u.starter_used = true;
    u.boost_min_tier = null;
    ledger("rub", -cost, "spin_" + lv.key); ledger("attempts", -useA, "spin");
    if (common && useC) counter("coin_spins", useC);
    if (!common) counter("upper_spins", count);
    const spinsToday = counter("spins", count);
    taskEvent("spin", count);
    const after = levelFromXp(u.xp)[0];
    return { drops, level: lv.key, paid: { energy: useE, attempts: useA, cents: cost }, starter, overflow: places.filter(x => x === "overflow").length, level_up: after > before, player_level: after, break_hint: spinsToday - count < G.break_hint_spins && G.break_hint_spins <= spinsToday };
  };
  H.inventory = b => {
    promoteOverflow();
    const minTier = +b.min_tier || 0, digits = String(b.q || "").replace(/\D/g, "");
    let rows = mine(b.overflow ? ["overflow"] : ["free", "listed"]).filter(i => i.tier >= minTier);
    rows.sort(b.sort === "new" ? (x, y) => y.id - x.id : (x, y) => y.tier - x.tier || y.id - x.id);
    rows = rows.filter(r => (!digits || (r.op + r.sub).includes(digits)) && (!b.favorites || r.favorite));
    const all = mine(["free", "listed", "overflow"]), counts = {};
    all.forEach(i => { counts[i.tier] = (counts[i.tier] || 0) + 1; });
    const weekAgo = now() - 7 * 86400;
    return { items: rows.map(view), counts, value_cents: collectionValue(1), week_cents: all.filter(i => i.created_at >= weekAgo).reduce((a, i) => a + LAD[i.tier], 0), slots: slots() };
  };
  const myItem = id => { const it = S.items.find(i => i.id === +id && i.user_id === 1 && i.state !== "gone"); if (!it) err("Номер не найден", "CONFLICT"); return it; };
  H.item = b => view(myItem(b.id));
  H.seen = () => { mine(["free", "listed", "overflow"]).forEach(i => { i.is_new = false; }); return { ok: true }; };
  H.favorite = b => { const it = myItem(b.id); it.favorite = !it.favorite; return { favorite: it.favorite }; };
  const myDev = id => { const d = S.devices.find(x => x.id === +id && x.user_id === 1 && x.state === "free"); if (!d) err("Не найдено", "CONFLICT"); return d; };
  H.lock = b => {
    const it = b.kind === "device" ? myDev(b.id) : myItem(b.id), locked = b.locked !== false;
    if (!locked && it.locked && !b.confirm) err("Снять замок? Его снова можно будет продать", "CONFIRM_REQUIRED");
    it.locked = locked;
    if (locked) taskEvent("lock");
    return { locked };
  };
  H.showcase = b => { const ids = (b.ids || []).map(Number).slice(0, 3); if (ids.length) owned(ids, ["free", "listed"]); S.user.showcase = ids; return { showcase: ids }; };
  const devPrice = d => d.price_cents;
  const sellPrice = (r, kind) => Math.floor((kind === "device" ? devPrice(r) : LAD[r.tier]) * C.sell_system_pct / 100);
  function sellRows(ids, kind) {
    if (kind !== "device") return owned(ids, ["free", "overflow"]);
    ids = [...new Set((ids || []).map(Number))];
    if (!ids.length) err("Ничего не выбрано");
    const rows = S.devices.filter(d => d.user_id === 1 && d.state === "free" && ids.includes(d.id));
    if (rows.length !== ids.length) err("Часть телефонов уже недоступна. Обнови коллекцию", "CONFLICT");
    return rows;
  }
  H.sell = b => {
    const kind = b.kind === "device" ? "device" : "number", items = sellRows(b.ids || [], kind);
    if (items.some(i => i.locked)) err("Под замком не продаётся. Сними замок, чтобы продать", "ITEM_LOCKED");
    const top = Math.max(...items.map(i => i.tier));
    if (top >= EPIC && !b.confirmed) err("Подтверди продажу", "CONFIRM_REQUIRED");
    const total = items.reduce((a, i) => a + sellPrice(i, kind), 0);
    items.forEach(i => { i.state = "gone"; i.gone_reason = "sold"; });
    const t = now(), sale = { id: S.sales.length + 1, kind, item_ids: items.map(i => i.id), amount_cents: total, created_at: t, undo_until: t + G.undo_sell.minutes * 60, undone: false };
    S.sales.push(sale);
    add(total, 0, kind === "device" ? "sell_device" : "sell");
    taskEvent("sell", items.length);
    promoteOverflow();
    return { sale_id: sale.id, cents: total, sold: items.length, undo_until: sale.undo_until };
  };
  H["sales/undo"] = b => {
    const sale = S.sales.find(x => x.id === +b.sale_id);
    if (!sale || sale.undone) err("Эту продажу уже отменили", "CONFLICT");
    if (sale.undo_until < now()) err("Отменить можно только в течение 10 минут", "NOT_ALLOWED_YET");
    if (counter("undo") >= G.undo_sell.per_day) err("Отменять продажу можно 5 раз в сутки", "DAILY_LIMIT");
    if (S.user.balance < sale.amount_cents) err(`Не хватает ${money(sale.amount_cents - S.user.balance)}, чтобы вернуть проданное`, "NOT_ENOUGH_COINS");
    if (sale.kind === "device") sale.item_ids.forEach(id => { const d = S.devices.find(x => x.id === id && x.gone_reason === "sold"); if (d) { d.state = "free"; d.gone_reason = null; } });
    else {
      const places = place(sale.item_ids.length);
      sale.item_ids.forEach((id, k) => {
        const it = S.items.find(i => i.id === id && i.gone_reason === "sold");
        if (it) { it.state = places[k]; it.gone_reason = null; it.overflow_until = places[k] === "overflow" ? now() + C.inventory.overflow_hours * 3600 : null; }
      });
    }
    sale.undone = true;
    add(-sale.amount_cents, 0, "sell_undo");
    counter("undo", 1);
    return { restored: sale.item_ids.length, kind: sale.kind || "number" };
  };
  H["sell/quote"] = b => {
    const kind = b.kind === "device" ? "device" : "number";
    let rows = kind === "device" ? S.devices.filter(d => d.user_id === 1 && d.state === "free" && !d.locked) : mine(["free", "overflow"]).filter(i => !i.locked);
    const price = r => kind === "device" ? devPrice(r) : LAD[r.tier];
    if (!b.mode || b.mode === "below_rare") rows = rows.filter(i => i.tier < RARE);
    else if (b.mode === "cheaper") rows = rows.filter(i => price(i) < +b.max_cents);
    else if (b.mode === "tier") rows = rows.filter(i => i.tier === +b.tier);
    return { ids: rows.map(i => i.id), count: rows.length, cents: rows.reduce((a, i) => a + sellPrice(i, kind), 0), top_tier: rows.length ? Math.max(...rows.map(i => i.tier)) : null };
  };

  // ---------- кейс «Телефоны» ----------
  const MODELS = C.devices, CASES = C.device_cases;
  function devView(d) {
    const m = MODELS.find(x => x.key === d.model), kase = CASES[0], same = MODELS.filter(x => x.tier === m.tier);
    const w = x => x.key === "nokia3310" ? 1 : x.key === "vertu_signature" ? 3 : x.key === "nokia8800" ? 5 : 1;
    const o = (kase.odds.find(x => x.tier === m.tier) || { p: 0 }).p * w(m) / same.reduce((a, x) => a + w(x), 0);
    return { id: d.id, kind: "device", user_id: d.user_id, ...m, tier: C.tiers[d.tier], price_cents: d.price_cents, sell_cents: sellPrice(d, "device"),
      one_in: o ? Math.max(1, Math.round(1 / o)) : null, locked: d.locked, is_new: d.is_new, state: d.state, source: d.source, created_at: d.created_at };
  }
  function pickModel(tier, u) {
    const ms = MODELS.filter(m => m.tier === tier), w = m => m.key === "nokia3310" ? 1 : m.key === "vertu_signature" ? 3 : m.key === "nokia8800" ? 5 : 1;
    let x = u * ms.reduce((a, m) => a + w(m), 0);
    for (const m of ms) { x -= w(m); if (x < 0) return m; }
    return ms[ms.length - 1];
  }
  const restrict = (odds, m) => { const mx = Math.max(...Object.keys(odds).map(Number)); m = Math.min(m, mx); const s = sumP(odds, t => t >= m); return Object.fromEntries(Object.entries(odds).filter(([t]) => +t >= m).map(([t, p]) => [t, p / s])); };
  H["case/spin"] = async b => {
    const kase = CASES.find(c => c.key === (b.case || "phones"));
    if (!kase) err("Нет такого кейса");
    const count = +b.count || 1, u = S.user, t = now();
    if (!C.counts.includes(count)) err("Можно открыть ×1, ×3, ×5 или ×10");
    if (S.devices.filter(d => d.user_id === 1 && d.state === "free").length + count > C.inventory.slots) err("Полка телефонов заполнена: продай лишние", "INVENTORY_FULL");
    const free = count === 1 && kase.free_first && !counter("device_free", 0, "all");
    const cost = free ? 0 : count * kase.price_cents;
    if (cost > u.balance) err(`Не хватает ${money(cost - u.balance)}. Продай номера или выполни задания`, "NOT_ENOUGH_COINS", { need_cents: cost - u.balance });
    if (cost && !b.confirmed && (cost >= C.confirm_from_cents || cost > u.balance * C.confirm_balance_share)) err(`Подтверди покупку: ${money(cost)}`, "CONFIRM_REQUIRED", { cost_cents: cost });
    const p = pair(), drops = [];
    let luckLeft = u.luck_left;
    for (let i = 0; i < count; i++) {
      let odds = Object.fromEntries(kase.odds.map(o => [o.tier, o.p])), luck = 1;
      if (luckLeft > 0) { luck = u.luck_mult; odds = applyLuck(odds, luck); luckLeft--; }
      if (u.boost_min_tier != null && i === 0) odds = restrict(odds, u.boost_min_tier);
      const nonce = ++p.nonce;
      const u0 = await roll(p.server_seed, p.client_seed, nonce, 0), u1 = await roll(p.server_seed, p.client_seed, nonce, 1);
      const tier = pickTier(u0, odds), m = pickModel(tier, u1);
      const d = { id: S.nextId++, user_id: 1, model: m.key, tier, price_cents: m.price_cents, source: free ? "free" : "case", state: "free", locked: false, is_new: true, created_at: t };
      S.devices.push(d);
      S.drops.push({ id: S.drops.length + 1, kind: "device", item_id: d.id, action: "case", level: kase.key, tier, odds, u0, seed_id: p.id, server_hash: p.server_hash, client_seed: p.client_seed, nonce, created_at: t });
      drops.push({ ...devView(d), fair: { server_hash: p.server_hash, client_seed: p.client_seed, nonce } });
    }
    const before = levelFromXp(u.xp)[0], xpGain = count * Math.max(10, Math.floor(kase.price_cents / 10000));
    u.balance -= cost; u.luck_left = luckLeft; u.xp += xpGain; u.total_spins += count; u.boost_min_tier = null;
    ledger("rub", -cost, "case_" + kase.key);
    if (free) counter("device_free", 1, "all");
    counter("spins", count); taskEvent("spin", count);
    return { drops, case: kase.key, paid: { cents: cost, free }, level_up: levelFromXp(u.xp)[0] > before, player_level: levelFromXp(u.xp)[0] };
  };
  H.devices = b => {
    let rows = S.devices.filter(d => d.user_id === 1 && d.state === "free" && d.tier >= (+b.min_tier || 0));
    rows.sort(b.sort === "new" ? (x, y) => y.id - x.id : (x, y) => y.tier - x.tier || y.price_cents - x.price_cents || y.id - x.id);
    const all = S.devices.filter(d => d.user_id === 1 && d.state === "free"), counts = {};
    all.forEach(d => { counts[d.tier] = (counts[d.tier] || 0) + 1; });
    return { items: rows.map(devView), counts, value_cents: all.reduce((a, d) => a + d.price_cents, 0), total: all.length, slots: C.inventory.slots };
  };
  H["devices/seen"] = () => { S.devices.forEach(d => { if (d.user_id === 1) d.is_new = false; }); return { ok: true }; };
  H.region = b => {
    if (!C.regions.includes(String(b.region))) err("Такой страны нет в списке");
    S.user.region = String(b.region);
    return { region: S.user.region };
  };
  H["luck/claim"] = () => {
    const ev = S.luck_event, u = S.user;
    if (!ev || ev.until < now()) err("Акция удачи закончилась", "NOT_ALLOWED_YET");
    if (counter("luck_claim:" + ev.id, 0, "event")) err("Удачу этой акции ты уже получил", "CONFLICT");
    if (u.luck_left > 0 && u.luck_mult > ev.mult) err("У тебя уже действует удача сильнее. Потрать её и возвращайся", "CONFLICT");
    u.luck_left = Math.max(ev.spins, u.luck_mult === ev.mult ? u.luck_left : 0); u.luck_mult = ev.mult;
    counter("luck_claim:" + ev.id, 1, "event");
    return { mult: ev.mult, spins: ev.spins };
  };
  H.contract = async b => {
    const cc = C.contracts, items = owned(b.ids || []);
    if (items.length !== cc.inputs) err(`Нужно ровно ${cc.inputs} номеров одной ступени`);
    if (items.some(i => i.locked)) err("Номера под замком в «5 в 1» не попадают", "ITEM_LOCKED");
    const tiers = new Set(items.map(i => i.tier));
    if (tiers.size !== 1) err("Все 5 номеров должны быть одной ступени");
    const tier = [...tiers][0];
    if (tier > SECRET) err("Эту ступень нельзя улучшить");
    items.forEach(i => { i.state = "gone"; i.gone_reason = "contract"; });
    const p = pair(), nonce = ++p.nonce;
    const u0 = await roll(p.server_seed, p.client_seed, nonce, 0), u1 = await roll(p.server_seed, p.client_seed, nonce, 1);
    const guaranteed = tier <= cc.guaranteed_up_to_tier, success = guaranteed || u0 < cc.success_pct / 100;
    const it = issue(1, success ? tier + 1 : tier, u1, "contract");
    S.drops.push({ id: S.drops.length + 1, item_id: it.id, action: "contract", tier: it.tier, odds: { success: guaranteed ? 1 : cc.success_pct / 100 }, u0, seed_id: p.id, server_hash: p.server_hash, client_seed: p.client_seed, nonce, created_at: now() });
    taskEvent("contract");
    return { success, guaranteed, item: view(it), chance: guaranteed ? 1 : cc.success_pct / 100, roll: u0 };
  };
  function upgradeCalc(b) {
    const up = C.upgrader, u = S.user, ids = (b.ids || []).map(Number);
    if (u.settings.no_upgrader) err("Улучшение выключено в настройках");
    if (ids.length > up.max_items) err(`Не больше ${up.max_items} номеров за раз`);
    const cents = Math.max(0, Math.floor(+b.cents || 0));
    const items = ids.length ? owned(ids) : [];
    if (items.some(i => i.locked)) err("Номера под замком нельзя улучшать", "ITEM_LOCKED");
    if (cents > u.balance) err(`Не хватает ${money(cents - u.balance)}`, "NOT_ENOUGH_COINS", { need_cents: cents - u.balance });
    const stake = items.reduce((a, i) => a + LAD[i.tier], 0) + cents, target = +b.target;
    if (stake <= 0) err("Положи номер или монеты");
    if (!(target >= 0 && target <= SECRET)) err("Такую цель нельзя выбрать");
    if (LAD[target] <= stake) err("Цель должна стоить дороже ставки");
    if (stake > (collectionValue(1) + u.balance) * up.max_share_of_collection) err("За раз можно поставить не больше половины стоимости коллекции");
    const base = stake / LAD[target] * up.k, r4 = x => Math.round(x * 1e4) / 1e4;
    return { items, cents, stake_cents: stake, target, target_cents: LAD[target], chance: r4(Math.min(up.max_chance_pct / 100, base + u.upgrade_bonus)), base_chance: r4(base), bonus: r4(u.upgrade_bonus), left_today: up.per_day - counter("upgrades"), confirm: items.some(i => i.tier >= up.confirm_from_tier) };
  }
  H["upgrade/quote"] = b => { const q = upgradeCalc(b); delete q.items; return q; };
  H.upgrade = async b => {
    const q = upgradeCalc(b), up = C.upgrader;
    if (b.quote_chance != null && Math.abs(+b.quote_chance - q.chance) > 1e-6) err("Шанс изменился, посмотри ещё раз", "CONFIG_CHANGED");
    if (q.left_today <= 0) err("На сегодня улучшения закончились (10 в сутки)", "DAILY_LIMIT");
    counter("upgrades", 1);
    q.items.forEach(i => { i.state = "gone"; i.gone_reason = "upgrade"; });
    add(-q.cents, 0, "upgrade");
    const p = pair(), nonce = ++p.nonce;
    const u0 = await roll(p.server_seed, p.client_seed, nonce, 0), success = u0 < q.chance;
    const res = { success, chance: q.chance, roll: u0 };
    if (success) {
      const it = issue(1, q.target, await roll(p.server_seed, p.client_seed, nonce, 1), "upgrade", place(1)[0]);
      res.item = view(it);
      S.user.upgrade_bonus = 0;
      S.drops.push({ id: S.drops.length + 1, item_id: it.id, action: "upgrade", tier: q.target, odds: { success: q.chance }, u0, seed_id: p.id, server_hash: p.server_hash, client_seed: p.client_seed, nonce, created_at: now() });
    } else {
      const parts = Math.floor(q.stake_cents * up.fail_parts_pct / 100);
      add(parts, 0, "upgrade_parts");
      S.user.upgrade_bonus += up.fail_bonus_pct / 100;
      Object.assign(res, { parts_cents: parts, next_bonus: Math.round((q.bonus + up.fail_bonus_pct / 100) * 1e4) / 1e4 });
    }
    promoteOverflow();
    return res;
  };

  // ---------- рынок ----------
  const nameOf = id => id === 1 ? S.user.name : (S.others.find(o => o.id === id) || {}).name || "Игрок";
  function lotView(l) {
    const it = S.items.find(i => i.id === l.item_id);
    return { ...view(it), lot_id: l.id, lot_cents: l.price_cents, seller_id: l.seller_id, seller: nameOf(l.seller_id), expires_at: l.expires_at, lot_status: l.status, buyer_id: l.buyer_id || null, fee_cents: l.fee_cents || null };
  }
  function expireLots() {
    const t = now();
    S.lots.filter(l => l.status === "active" && l.expires_at < t).forEach(l => { l.status = "expired"; const it = S.items.find(i => i.id === l.item_id); if (it && it.state === "listed") it.state = "free"; });
  }
  H.market = b => {
    expireLots(); taskEvent("market");
    const digits = String(b.q || "").replace(/\D/g, "");
    let lots = S.lots.filter(l => l.status === "active").map(lotView).filter(l => l.tier.idx >= (+b.min_tier || 0) && (!digits || (l.op + l.sub).includes(digits)));
    const sorts = { new: (x, y) => y.lot_id - x.lot_id, cheap: (x, y) => x.lot_cents - y.lot_cents, rare: (x, y) => y.tier.idx - x.tier.idx || y.lot_cents - x.lot_cents };
    lots.sort(sorts[b.sort] || sorts.new);
    return { lots, fee_pct: vip() ? C.market.fee_vip_pct : C.market.fee_pct };
  };
  H["market/mine"] = () => {
    const views = S.lots.filter(l => l.seller_id === 1 || l.buyer_id === 1).sort((a, b) => b.id - a.id).map(l => ({ ...lotView(l), side: l.seller_id === 1 ? "sell" : "buy" }));
    return { active: views.filter(v => v.lot_status === "active" && v.side === "sell"), deals: views.filter(v => v.lot_status === "sold") };
  };
  H["market/list"] = b => {
    const m = C.market, t = now();
    if (t - S.user.created_at < m.new_account_hours * 3600) err(`Торговать можно через ${m.new_account_hours} ч после первого входа`, "NOT_ALLOWED_YET");
    const it = owned([b.id])[0];
    if (it.hold_until && it.hold_until > t) err("Купленный номер можно выставить через 24 часа", "ITEM_BUSY");
    if (S.lots.filter(l => l.seller_id === 1 && l.status === "active").length >= m.lots_max) err(`Не больше ${m.lots_max} лотов одновременно`, "DAILY_LIMIT");
    const ref = LAD[it.tier], lo = Math.floor(ref * m.band_pct[0] / 100), hi = Math.floor(ref * m.band_pct[1] / 100), price = Math.floor(+b.price_cents);
    if (!(price >= lo && price <= hi)) err(`Цена от ${money(lo)} до ${money(hi)}`, "PRICE_OUT_OF_BAND", { min_cents: lo, max_cents: hi });
    it.state = "listed";
    const lot = { id: S.lots.length + 1, item_id: it.id, seller_id: 1, price_cents: price, created_at: t, expires_at: t + m.lot_days * 86400, status: "active" };
    S.lots.push(lot);
    const lotId = lot.id;
    // в демо кто-нибудь купит лот через полминуты, если цена не выше опорной
    if (price <= ref) setTimeout(() => {
      const lot = S.lots.find(l => l.id === lotId), it = lot && S.items.find(i => i.id === lot.item_id);
      if (!lot || lot.status !== "active" || !it) return;
      const fee = Math.floor(price * (vip() ? m.fee_vip_pct : m.fee_pct) / 100), buyer = S.others[(lot.id * 3) % S.others.length];
      add(price, 0, "market_sale"); add(-fee, 0, "market_fee");
      Object.assign(lot, { status: "sold", buyer_id: buyer.id, fee_cents: fee, closed_at: now() });
      Object.assign(it, { user_id: buyer.id, state: "free" });
      save();
    }, 30000);
    return { lot_id: lot.id, you_get_cents: price - Math.floor(price * (vip() ? m.fee_vip_pct : m.fee_pct) / 100) };
  };
  H["market/cancel"] = b => {
    const lot = S.lots.find(l => l.id === +b.lot_id && l.seller_id === 1 && l.status === "active");
    if (!lot) err("Лот уже закрыт", "CONFLICT");
    lot.status = "cancelled";
    S.items.find(i => i.id === lot.item_id).state = "free";
    return { ok: true };
  };
  H["market/buy"] = b => {
    expireLots();
    const m = C.market, t = now(), lot = S.lots.find(l => l.id === +b.lot_id && l.status === "active");
    if (!lot) err("Этот лот уже купили или сняли", "CONFLICT");
    if (lot.seller_id === 1) err("Это твой лот");
    if (S.user.balance < lot.price_cents) err(`Не хватает ${money(lot.price_cents - S.user.balance)}`, "NOT_ENOUGH_COINS", { need_cents: lot.price_cents - S.user.balance });
    const pl = place(1)[0];
    add(-lot.price_cents, 0, "market_buy");
    Object.assign(lot, { status: "sold", buyer_id: 1, fee_cents: Math.floor(lot.price_cents * m.fee_pct / 100), closed_at: t });
    const it = S.items.find(i => i.id === lot.item_id);
    Object.assign(it, { user_id: 1, state: pl, is_new: true, favorite: false, locked: false, hold_until: t + m.hold_hours * 3600, overflow_until: pl === "overflow" ? t + C.inventory.overflow_hours * 3600 : null });
    return { item: view(it) };
  };

  // ---------- колёса, подарок, задания ----------
  function pick(sectors) { let x = Math.random(); for (let i = 0; i < sectors.length; i++) { x -= sectors[i].p; if (x < 0) return i; } return sectors.length - 1; }
  H.wheel = async b => {
    const t = now(), weekly = b.kind === "weekly";
    let sectors;
    if (weekly) {
      if (counter("wheel_weekly", 0, weekKey(t))) err("Недельное колесо уже крутил на этой неделе", "DAILY_LIMIT");
      if (taskDays() < G.wheel_weekly.unlock_days) err("Недельное колесо открывается за задания в 5 днях из 7", "NOT_ALLOWED_YET");
      sectors = G.wheel_weekly.sectors; counter("wheel_weekly", 1, weekKey(t));
    } else {
      if (counter("wheel")) err("Колесо уже крутил сегодня. Следующее завтра", "DAILY_LIMIT");
      sectors = D.wheel_daily; counter("wheel", 1); taskEvent("wheel");
    }
    const idx = pick(sectors), s = sectors[idx];
    const out = { index: idx, label: s.label, cents: s.cents || 0, attempts: s.attempts || 0 };
    add(s.cents || 0, s.attempts || 0, weekly ? "wheel_weekly" : "wheel_daily");
    if (s.item_min_tier != null) {
      const common = oddsObj(C.levels[0]), m = s.item_min_tier, tot = sumP(common, x => x >= m);
      const odds = Object.fromEntries(Object.entries(common).filter(([x]) => +x >= m).map(([x, q]) => [x, q / tot]));
      const p = pair(), nonce = ++p.nonce;
      const tier = pickTier(await roll(p.server_seed, p.client_seed, nonce, 0), odds);
      out.item = view(issue(1, tier, await roll(p.server_seed, p.client_seed, nonce, 1), "wheel_weekly", place(1)[0]));
    }
    if (s.badge && !S.user.badges.includes(s.badge)) { S.user.badges.push(s.badge); out.badge = s.badge; }
    return out;
  };
  H.gift = () => {
    const u = S.user, t = now(), today = dayKey(t), yesterday = dayKey(t - 86400);
    if (u.gift_day === today) err("Подарок уже забран. Возвращайся завтра", "DAILY_LIMIT");
    const streak = u.gift_day === yesterday ? (u.gift_streak % 7) + 1 : 1, r = C.gift[streak - 1];
    const cents = typeof r === "number" ? r : r.cents || 0, attempts = typeof r === "number" ? 0 : r.attempts || 0;
    u.gift_day = today; u.gift_streak = streak;
    add(cents, attempts, "gift");
    return { day: streak, cents, attempts };
  };
  H.task = b => {
    const key = String(b.key), t = now(), w = G.weekly_tasks.find(x => x.key === key);
    if (w) {
      const week = weekKey(t);
      if (counter("wclaimed:" + key, 0, week)) err("Награда уже получена", "CONFLICT");
      if (counter("wtask:" + key, 0, week) < w.target) err("Задание ещё не выполнено");
      counter("wclaimed:" + key, 1, week); add(w.cents, 0, "task_weekly");
      if (w.badge && !S.user.badges.includes(w.badge)) S.user.badges.push(w.badge);
      return { cents: w.cents, badge: w.badge };
    }
    const task = todayTasks(t).find(x => x.key === key);
    if (!task) err("Такого задания сегодня нет");
    if (counter("claimed:" + key)) err("Награда уже получена", "CONFLICT");
    if (counter("task:" + key) < task.target) err("Задание ещё не выполнено");
    counter("claimed:" + key, 1); counter("tickets", G.tickets_per_task); add(task.cents, 0, "task");
    return { cents: task.cents, tickets: G.tickets_per_task };
  };
  H.raffle = async () => {
    const t = now(), today = dayKey(t), row = await raffleRow(today), last = S.raffle[dayKey(t - 86400)];
    return {
      day: today, hour_msk: G.raffle.hour_msk, server_hash: row.server_hash, drawn: row.drawn, my_tickets: counter("tickets"),
      total_tickets: counter("tickets") + 37, prizes: G.raffle.prizes, winners: row.winners,
      last: last ? { day: dayKey(t - 86400), server_seed: last.server_seed, server_hash: last.server_hash, winners: last.winners } : null,
    };
  };

  // ---------- честная игра ----------
  H.fair = () => {
    const p = pair();
    const rolls = [...S.drops].reverse().slice(0, 50).map(d => {
      const s = S.seeds.find(x => x.id === d.seed_id), it = d.kind === "device" ? null : S.items.find(i => i.id === d.item_id);
      const dv = d.kind === "device" ? S.devices.find(x => x.id === d.item_id) : null, dm = dv && MODELS.find(m => m.key === dv.model);
      return { id: d.id, action: d.action, level: d.level || null, tier: d.tier, u0: d.u0, odds: d.odds, server_hash: d.server_hash, client_seed: d.client_seed, nonce: d.nonce, server_seed: s && s.revealed_at ? s.server_seed : null, number: it ? formatNumber(it.country, it.op, it.sub) : dm ? `${dm.brand} ${dm.name}` : null, created_at: d.created_at };
    });
    return { server_hash: p.server_hash, client_seed: p.client_seed, nonce: p.nonce, rolls };
  };
  H["fair/rotate"] = async b => {
    const client = String(b.client_seed || "").trim() || randHex(8);
    if (!/^[A-Za-z0-9_-]{1,32}$/.test(client)) err("Client seed: до 32 латинских букв, цифр, «-» или «_»");
    const old = pair();
    old.active = false; old.revealed_at = now();
    const p = await newPair(client);
    return { revealed: { server_seed: old.server_seed, server_hash: old.server_hash, client_seed: old.client_seed, nonce: old.nonce }, server_hash: p.server_hash, client_seed: p.client_seed, nonce: 0 };
  };

  // ---------- друзья, рейтинг, лента ----------
  H.friends = () => {
    const req = G.referral.required_spins;
    return { count: S.user.ref_count, required_spins: req, friend_attempts: G.referral.friend_attempts, tiers: G.referral.tiers, ref_link: "https://t.me/твой_бот?start=r1",
      friends: S.others.filter(o => o.friend).map(o => ({ name: o.name, spins: Math.min(o.spins, req), qualified: o.spins >= req })) };
  };
  H.rating = b => {
    taskEvent("rating");
    const board = b.board || "collection", scope = b.scope || "friends";
    let rows = [{ id: 1, name: S.user.name }, ...S.others.map(o => ({ id: o.id, name: o.name, friend: o.friend, o }))];
    if (scope === "friends") rows = rows.filter(r => r.id === 1 || r.friend);
    rows.forEach(r => {
      if (board === "level") { r.value = levelFromXp(r.id === 1 ? S.user.xp : r.o.xp)[0]; r.score = r.value; }
      else if (board === "rarest") {
        const best = S.items.filter(i => i.user_id === r.id && i.state !== "gone").sort((x, y) => y.tier - x.tier || y.id - x.id)[0];
        r.item = best; r.score = best ? best.tier * 1e9 + best.id : -1;
      } else { r.value_cents = collectionValue(r.id) + (r.o ? r.o.extra : 0); r.score = r.value_cents; }
    });
    rows = rows.filter(r => r.score >= 0).sort((x, y) => y.score - x.score);
    const out = rows.map((r, i) => {
      const e = { pos: i + 1, id: r.id, name: r.name, me: r.id === 1 };
      if (board === "rarest") e.item = view(r.item); else if (board === "level") e.level = r.value; else e.value_cents = r.value_cents;
      return e;
    });
    return { board, scope, top: out.slice(0, 50), me: out.find(e => e.me) || null };
  };
  H.feed = () => ({
    items: [...S.feed].sort((a, b) => b.created_at - a.created_at).slice(0, 20).map(f => {
      const it = S.items.find(i => i.id === f.item_id), v = view(it), o = S.others.find(x => x.id === f.user_id);
      return { name: nameOf(f.user_id), friend: !!(o && o.friend), me: f.user_id === 1, number: v.number, flag: v.flag, tier: v.tier, at: f.created_at };
    }),
  });
  H.history = () => ({ items: [...S.ledger].reverse().slice(0, 20) });

  // ---------- магазин (в демо без оплаты) ----------
  const monthSpent = () => { const d = new Date((now() + MSK) * 1000); const m0 = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1) / 1000 - MSK; return S.payments.filter(p => p.created_at >= m0).reduce((a, p) => a + p.stars, 0); };
  H.shop = () => {
    const s = G.shop;
    return { enabled: true, products: Object.entries(s.products).filter(([, p]) => !(p.once && S.user.start_pack)).map(([key, p]) => ({ key, ...p })), month_spent: monthSpent(), month_cap: s.monthly_cap_stars, warn_at_pct: s.warn_at_pct, attempts_stock_cap: s.attempts_stock_cap };
  };
  function checkPurchase(key) {
    const s = G.shop, p = s.products[key], u = S.user;
    if (!p) err("Нет такого товара");
    const spent = monthSpent();
    if (spent + p.stars > s.monthly_cap_stars) err(`Месячный лимит покупок ${s.monthly_cap_stars} ⭐, осталось ${s.monthly_cap_stars - spent} ⭐. Повысить можно через /paysupport`, "STARS_MONTH_CAP");
    if (p.once && u.start_pack) err("Набор «Старт» можно купить один раз", "NOT_ALLOWED_YET");
    if (p.attempts) {
      if (u.attempts + p.attempts > s.attempts_stock_cap) err(`Запас попыток не больше ${s.attempts_stock_cap}. Сначала потрать текущие`, "DAILY_LIMIT");
      if (counter("bought_attempts") + p.attempts > s.attempts_daily_cap) err(`За сутки можно купить не больше ${s.attempts_daily_cap} попыток`, "DAILY_LIMIT");
    }
    if (p.luck) {
      if (u.luck_left > 0 && u.luck_mult > p.luck) err("Уже действует более сильная удача", "CONFLICT");
      if (p.luck >= 2 && counter("luck2") >= s.luck2_daily) err(`Удачу ×2 можно купить не больше ${s.luck2_daily} раз в сутки`, "DAILY_LIMIT");
    }
    if (p.slots && u.slots_bought >= s.slots_max_buys) err("Места можно докупить не больше 3 раз", "DAILY_LIMIT");
    return p;
  }
  H["shop/invoice"] = b => { checkPurchase(String(b.key)); return { demo: true }; };
  H["shop/demo_pay"] = b => {
    const key = String(b.key), p = checkPurchase(key), u = S.user, t = now();
    S.payments.push({ product: key, stars: p.stars, created_at: t });
    if (p.attempts) { add(0, p.attempts, "purchase"); counter("bought_attempts", p.attempts); }
    if (p.luck) { u.luck_mult = p.luck; u.luck_left = G.shop.luck_spins; if (p.luck >= 2) counter("luck2", 1); }
    if (p.vip_days) u.vip_until = Math.max(t, u.vip_until || 0) + p.vip_days * 86400;
    if (p.slots) { u.slots_extra += p.slots; u.slots_bought++; }
    if (p.once) u.start_pack = true;
    return { granted: p.title };
  };

  // ---------- админка (демо: данные этой вкладки) ----------
  const adNums = id => {
    const out = {}, today = dayKey(now());
    for (const kind of ["view", "click"]) {
      const ks = Object.keys(S.counters).filter(k => k.endsWith("|ad_" + kind + ":" + id));
      const td = ks.filter(k => k.startsWith(today));
      out[kind] = { total: ks.reduce((a, k) => a + S.counters[k], 0), users: ks.length ? 1 : 0, today: td.reduce((a, k) => a + S.counters[k], 0), users_today: td.length ? 1 : 0 };
    }
    return out;
  };
  const adsStats = () => S.ads.map(a => ({ ad: a, ...adNums(a.id) }));
  const luckStats = () => S.luck_event ? { ...S.luck_event, active: S.luck_event.until > now(), claims: counter("luck_claim:" + S.luck_event.id, 0, "event") ? 1 : 0 } : null;
  const brief = o => o.id === 1
    ? { id: 1, name: S.user.name, username: S.user.username, balance_cents: S.user.balance, level: levelFromXp(S.user.xp)[0], total_spins: S.user.total_spins, created_at: S.user.created_at, last_seen: now(), country: S.user.country, is_blocked: false }
    : { id: o.id, name: o.name, username: null, balance_cents: 250000 + o.id * 13000, level: levelFromXp(o.xp)[0], total_spins: 40 + o.id % 50, created_at: S.user.created_at - 86400 * (o.id % 9), last_seen: now() - 3600 * (o.id % 20), country: o.country, is_blocked: false };
  H["admin/overview"] = () => {
    const t = now(), d0 = dayKey(t), drops = S.drops.filter(d => dayKey(d.created_at) === d0 && (d.action === "spin" || d.action === "case"));
    const byTier = {}; drops.forEach(d => { byTier[d.tier] = (byTier[d.tier] || 0) + 1; });
    const reasons = {}; S.ledger.filter(l => l.currency === "rub" && dayKey(l.created_at) === d0).forEach(l => { reasons[l.reason] = (reasons[l.reason] || 0) + l.delta; });
    const series = Array.from({ length: 14 }, (_, i) => {
      const day = dayKey(t - (13 - i) * 86400), mine = S.drops.filter(d => dayKey(d.created_at) === day).length;
      const k = (i * 7919) % 13;
      return { day, new: 3 + k + (i > 9 ? 6 : 0), active: 9 + k * 2 + i * 2 + (mine ? 1 : 0), spins: 60 + k * 9 + i * 11 + mine, stars: i % 4 === 0 ? 49 : 0 };
    });
    return {
      stats: { users: S.others.length + 1, alive: S.others.length + 1, new_today: series[13].new, dau: series[13].active, spins_today: series[13].spins,
        balance_total_cents: S.user.balance + 9_870_000, reasons: Object.entries(reasons).map(([reason, cents]) => ({ reason, cents })).sort((a, b) => b.cents - a.cents),
        inflow_per_active_cents: 320000, stars_month: S.payments.reduce((a, p) => a + p.stars, 0) + 147, stars_total: 1240, referrals: 2,
        drops_by_tier: Object.entries(byTier).map(([tier, n]) => ({ tier: +tier, n })), editions_low: [] },
      series, ads: adsStats(), ads_max: 3, luck_event: luckStats(), luck_mults: [2, 3, 5, 10], luck_max_spins: 100, ads_contact: "ninety97", tiers: C.tiers,
    };
  };
  H["admin/users"] = b => {
    const q = String(b.q || "").trim().toLowerCase().replace(/^@/, "");
    const all = [{ id: 1 }, ...S.others].map(brief);
    return { users: q ? all.filter(u => String(u.id) === q || (u.name || "").toLowerCase().includes(q) || (u.username || "").includes(q)) : all };
  };
  H["admin/user"] = b => {
    const id = +b.id;
    const o = id === 1 ? { id: 1 } : S.others.find(x => x.id === id);
    if (!o) err("Игрок не найден", "CONFLICT");
    const items = {}, devs = {};
    S.items.filter(i => i.user_id === id && i.state !== "gone").forEach(i => { items[i.tier] = (items[i.tier] || 0) + 1; });
    S.devices.filter(d => d.user_id === id && d.state === "free").forEach(d => { devs[d.tier] = (devs[d.tier] || 0) + 1; });
    const me = id === 1;
    return { ...brief(o), attempts: me ? S.user.attempts : 0, xp: me ? S.user.xp : o.xp, region: me ? (S.user.region || S.user.country) : o.country,
      luck: me ? { mult: S.user.luck_mult, spins_left: S.user.luck_left } : (S.adminLuck && S.adminLuck[id]) || { mult: 1, spins_left: 0 },
      boost_min_tier: me ? S.user.boost_min_tier : (S.adminBoost && S.adminBoost[id] != null ? S.adminBoost[id] : null),
      vip_until: null, ref_count: me ? S.user.ref_count : 0, ref_id: null, items, devices: devs,
      value_cents: collectionValue(id) + S.devices.filter(d => d.user_id === id && d.state === "free").reduce((a, d) => a + d.price_cents, 0) + (me ? 0 : o.extra),
      best: null, stars: me ? S.payments.reduce((a, p) => a + p.stars, 0) : 0, ledger: me ? [...S.ledger].reverse().slice(0, 15) : [] };
  };
  H["admin/give"] = b => {
    const id = +b.id, cents = Math.round(+b.rubles * 100) || 0, att = +b.attempts || 0;
    if (id === 1) { if (S.user.balance + cents < 0 || S.user.attempts + att < 0) err("Баланс не может уйти в минус"); add(cents, att, "admin"); }
    return H["admin/user"]({ id });
  };
  H["admin/luck"] = b => {
    const id = +b.id, mult = +b.mult, spins = +b.spins;
    if (!(mult >= 1 && mult <= 10) || !(spins >= 0 && spins <= 1000)) err("Удача от ×1 до ×10, спинов от 0 до 1000");
    if (id === 1) { S.user.luck_mult = mult; S.user.luck_left = spins; } else { S.adminLuck = S.adminLuck || {}; S.adminLuck[id] = { mult, spins_left: spins }; }
    return H["admin/user"]({ id });
  };
  H["admin/boost"] = b => {
    const id = +b.id, tier = b.tier == null ? null : +b.tier;
    if (id === 1) S.user.boost_min_tier = tier; else { S.adminBoost = S.adminBoost || {}; S.adminBoost[id] = tier; }
    return H["admin/user"]({ id });
  };
  H["admin/ads/save"] = b => {
    const title = String(b.title || "").trim(), text = String(b.text || "").trim(), url = String(b.url || "").trim();
    const button = String(b.button || "").trim() || "Открыть", icon = String(b.icon || "").trim() || "📣";
    if (!title || title.length > 40) err("Заголовок от 1 до 40 символов");
    if (text.length > 80) err("Текст не длиннее 80 символов");
    if (!url.startsWith("https://") || url.includes(" ")) err("Ссылка должна начинаться с https://");
    if (b.id) { const a = S.ads.find(x => x.id === +b.id); if (!a) err("Такой рекламы нет", "CONFLICT"); Object.assign(a, { title, text, url, button, icon }); }
    else { if (S.ads.length >= 3) err("Уже 3 рекламы. Сними одну, чтобы поставить новую"); S.ads.push({ id: Math.max(Math.floor(now()), ...S.ads.map(a => a.id + 1)), title, text, url, button, icon, created_at: now() }); }
    return { ads: adsStats() };
  };
  H["admin/ads/remove"] = b => { S.ads = S.ads.filter(a => a.id !== +b.id); return { ads: adsStats() }; };
  H["admin/luck_event/start"] = b => {
    const mult = +b.mult, spins = +b.spins, hours = +b.hours, ch = String(b.channel || "").trim();
    if (![2, 3, 5, 10].includes(mult)) err("Множитель: ×2, ×3, ×5, ×10");
    if (!(spins >= 1 && spins <= 100)) err("Спинов с удачей от 1 до 100");
    if (!(hours > 0 && hours <= 720)) err("Длительность от 1 часа до 30 дней");
    const m = ch.match(/^(?:https?:\/\/)?t\.me\/([A-Za-z0-9_]{4,32})\/?$/) || ch.match(/^@?([A-Za-z0-9_]{4,32})$/);
    if (!m) err("Канал: @username или ссылка t.me/username");
    const t = now();
    S.luck_event = { id: Math.floor(t), mult, spins, until: t + hours * 3600, chat_id: "@" + m[1], url: "https://t.me/" + m[1], title: String(b.title || "").trim().slice(0, 40) || `Удача ×${mult} для всех`, started_at: t };
    return { luck_event: luckStats(), warning: null };
  };
  H["admin/luck_event/stop"] = () => { S.luck_event = null; return { luck_event: null }; };
  H["admin/broadcast"] = b => { if (!String(b.text || "").trim()) err("Текст рассылки от 1 до 3500 символов"); return { started: true, recipients: S.others.length + 1 }; };

  // ---------- вызов ----------
  const READ = new Set(["admin/overview", "admin/users", "admin/user", "devices", "config", "me", "inventory", "item", "market/mine", "fair", "friends", "feed", "history", "shop", "raffle", "upgrade/quote", "sell/quote"]);
  let ready = null, queue = Promise.resolve();
  const clone = x => JSON.parse(JSON.stringify(x));
  window.DemoServer = {
    call(path, body = {}) {
      ready = ready || init();
      // запросы по очереди, как per-user lock на сервере
      const run = queue.then(() => ready).then(async () => {
        const h = H[path];
        if (!h) err("Нет такого метода", "BAD_REQUEST");
        const snapshot = JSON.stringify(S);
        try {
          const res = await h(clone(body || {}));
          if (!READ.has(path)) save();
          return clone(res);
        } catch (e) {
          S = JSON.parse(snapshot); // транзакция: при ошибке ничего не меняется
          throw e;
        }
      });
      queue = run.catch(() => {});
      // небольшая задержка сети
      return run.then(r => new Promise(res => setTimeout(() => res(r), path === "spin" ? 260 : 90)));
    },
    reset() { try { localStorage.removeItem(KEY); } catch (e) { /* */ } location.reload(); },
  };
})();
