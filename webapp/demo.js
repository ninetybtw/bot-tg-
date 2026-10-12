/* Демо-сервер: работает, только когда приложение открыто вне Telegram.
   Повторяет API игрового сервера (bot/game/service.py) в памяти вкладки,
   чтобы игру можно было потрогать без бота. В Telegram не используется. */
(() => {
  "use strict";
  const PRICES = [10, 30, 100, 400, 2000, 10000, 50000, 250000];
  const TIERS = [
    ["common", "Обычный", "○", "#9aa4b2"], ["uncommon", "Необычный", "◇", "#4cc38a"], ["rare", "Редкий", "◆", "#4c8dff"],
    ["epic", "Эпик", "⬢", "#a06bff"], ["legendary", "Легендарный", "★", "#ff5fb4"], ["mythic", "Мифический", "✹", "#ff4d4d"],
    ["secret", "Секретный", "♛", "#f5c542"], ["divine", "Божественный", "✺", "rainbow"], ["exclusive", "Эксклюзив", "◈", "#111111"],
  ].map(([key, name, icon, color], idx) => ({ idx, key, name, icon, color }));
  const SCALES = {
    phone: { title: "Обычный спин", price: 100, odds: { 0: .62, 1: .24, 2: .09, 3: .035, 4: .012, 5: .003 } },
    premium: { title: "Премиум-спин", price: 500, odds: { 2: .70, 3: .22, 4: .067, 5: .012, 6: .001 } },
  };
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => String(a + i));
  const COUNTRIES = {
    RU: { code: "RU", name: "Россия", flag: "🇷🇺", dial: "+7", ops: range(900, 999), groups: [3, 2, 2], sep: "-" },
    KZ: { code: "KZ", name: "Казахстан", flag: "🇰🇿", dial: "+7", ops: ["700", "701", "702", "705", "707", "708", "747", "750", "751", "760", "771", "775", "776", "777", "778"], groups: [3, 2, 2], sep: "-" },
    BY: { code: "BY", name: "Беларусь", flag: "🇧🇾", dial: "+375", ops: ["25", "29", "33", "44"], groups: [3, 2, 2], sep: "-" },
    AE: { code: "AE", name: "ОАЭ", flag: "🇦🇪", dial: "+971", ops: ["50", "52", "54", "55", "56", "58"], groups: [3, 4], sep: " " },
  };
  const DIVINE = [["RU", "900", "0000000"], ["KZ", "700", "0000000"], ["BY", "25", "0000000"], ["AE", "50", "0000000"]];
  const BLACKLIST = ["1488", "228", "420", "69"];
  const D = "0123456789";
  const rnd = n => Math.floor(Math.random() * n);
  const pick = a => a[rnd(a.length)];
  const rand = n => Array.from({ length: n }, () => pick(D)).join("");
  const DAY = 86400e3;

  // ---------- классификатор (порт bot/game/phones.py) ----------
  const maxRun = s => { let b = 1, c = 1; for (let i = 1; i < s.length; i++) { c = s[i] === s[i - 1] ? c + 1 : 1; b = Math.max(b, c); } return b; };
  const maxLadder = s => { let b = 1; for (const st of [1, -1]) { let c = 1; for (let i = 1; i < s.length; i++) { c = (+s[i] - +s[i - 1] === st) ? c + 1 : 1; b = Math.max(b, c); } } return b; };
  const ladderEnd = (s, n) => { const t = s.slice(-n); return [1, -1].some(st => [...t].every((ch, i) => i === 0 || +ch - +t[i - 1] === st)); };
  const pal = s => s === [...s].reverse().join("");
  function classify(cc, op, sub) {
    const full = op + sub;
    if (DIVINE.some(d => d[0] === cc && d[1] === op && d[2] === sub)) return 7;
    const same = new Set(full).size === 1;
    if (pal(full) && !same) return 6;
    if (same || (full.length >= 9 && maxLadder(full) === full.length)) return 5;
    const s = sub;
    if (maxRun(s) >= 6) return 4;
    if (new Set(s.slice(-4)).size === 1 || maxLadder(s) >= 4 || (s[3] === s[4] && s[5] === s[6]) || pal(s.slice(-6))) return 3;
    if (maxRun(s) >= 3 || pal(s.slice(-4)) || ladderEnd(s, 3)) return 2;
    if (s[6] === s[5]) return 1;
    return 0;
  }
  function ladder(n) { const st = pick([1, -1]), a = rnd(10), o = []; for (let i = 0; i < n; i++) o.push(a + i * st); return o.every(d => d >= 0 && d <= 9) ? o.join("") : null; }
  function build(tier, c) {
    const op = pick(c.ops), s = rand(7), d = pick(D);
    if (tier === 0) return [op, s];
    if (tier === 1) return [op, s.slice(0, 5) + (Math.random() < .8 ? d + d : "00")];
    if (tier === 2) { const k = rnd(3); if (k === 0) { const p = rnd(5); return [op, s.slice(0, p) + d.repeat(3) + s.slice(p + 3)]; } if (k === 1) { const a = pick(D), b = pick(D); return [op, s.slice(0, 3) + a + b + b + a]; } const l = ladder(3); return l ? [op, s.slice(0, 4) + l] : null; }
    if (tier === 3) { const k = rnd(4); if (k === 0) return [op, s.slice(0, 3) + d.repeat(4)]; if (k === 1) { const n = pick([4, 4, 5]), l = ladder(n); if (!l) return null; const p = rnd(8 - n); return [op, s.slice(0, p) + l + s.slice(p + n)]; } if (k === 2) { let a = pick(D), b = pick(D); if (a === b) return null; return [op, s.slice(0, 3) + a + a + b + b]; } const h = rand(3); return [op, s.slice(0, 1) + h + [...h].reverse().join("")]; }
    if (tier === 4) { const n = pick([6, 6, 7]), p = rnd(8 - n); return [op, s.slice(0, p) + d.repeat(n) + s.slice(p + n)]; }
    if (tier === 5) { const o = []; for (const x of c.ops) { if (new Set(x).size === 1) o.push([x, x[0].repeat(7)]); for (const l of ["0123456789", "9876543210", "123456789", "987654321"]) if (l.length === x.length + 7 && l.startsWith(x)) o.push([x, l.slice(x.length)]); } return o.length ? pick(o) : null; }
    if (tier === 6) { const total = op.length + 7, hl = Math.ceil(total / 2), head = op + rand(hl - op.length), full = head + [...head.slice(0, Math.floor(total / 2))].reverse().join(""); return [op, full.slice(op.length)]; }
    if (tier === 7) { const own = DIVINE.filter(x => x[0] === c.code); return own.length ? [own[0][1], own[0][2]] : null; }
    return null;
  }
  function generate(tier, country) {
    for (const cc of [country, ...Object.keys(COUNTRIES).filter(x => x !== country)]) {
      const c = COUNTRIES[cc];
      for (let i = 0; i < 2000; i++) {
        const b = build(tier, c);
        if (!b || b[1].length !== 7) continue;
        if (tier !== 7 && BLACKLIST.some(x => (b[0] + b[1]).includes(x))) continue;
        if (classify(cc, b[0], b[1]) === tier) return [cc, b[0], b[1]];
      }
    }
    throw new Error("generate");
  }
  const fmtNum = (cc, op, sub) => { const c = COUNTRIES[cc]; let i = 0; const parts = c.groups.map(g => { const p = sub.slice(i, i + g); i += g; return p; }); return `${c.dial} ${op} ${parts.join(c.sep)}`; };
  const chanceFor = t => { for (const k of ["phone", "premium"]) { const p = SCALES[k].odds[t]; if (p) return Math.max(1, Math.round(1 / p)); } return null; };
  function applyLuck(odds, m) {
    if (m <= 1) return { ...odds };
    const keys = Object.keys(odds).map(Number), top = [...keys].sort((a, b) => odds[b] - odds[a]).slice(0, 2);
    const out = {}; let boosted = 0;
    keys.filter(k => !top.includes(k)).forEach(k => { out[k] = odds[k] * m; boosted += out[k]; });
    const cs = top.reduce((a, k) => a + odds[k], 0);
    top.forEach(k => { out[k] = odds[k] * (1 - boosted) / cs; });
    return out;
  }
  const levelFromXp = xp => { let l = 1, need = 100; while (xp >= need) { xp -= need; l++; need = 100 + 50 * (l - 1); } return [l, xp, need]; };
  const dayKey = ts => new Date(ts + 3 * 3600e3).toISOString().slice(0, 10);

  // ---------- мир демо ----------
  let nextId = 1, nextLot = 1;
  const now = () => Date.now();
  const items = [], lots = [], ledger = [], counters = {};
  const ME = 1;
  const users = {
    [ME]: { id: ME, first_name: "Ты", coins: 2000, spins: 5, energy: 3, energy_ts: now(), xp: 0, total_spins: 0, pity_epic: 0, pity_legendary: 0,
      luck_mult: 1, luck_left: 0, upgrade_bonus: 0, gift_day: null, gift_streak: 0, country: "RU", settings: { fast: false, no_effects: false, no_upgrader: false },
      badges: [], created_at: now() - 3 * DAY, ref_count: 2 },
  };
  const NAMES = ["Аня", "Миша", "Лера", "Тимур", "Даня", "Соня", "Артём"];
  const cnt = (k, inc = 0, uid = ME) => { const key = `${uid}|${dayKey(now())}|${k}`; counters[key] = (counters[key] || 0) + inc; return counters[key]; };
  const log = (currency, delta, reason, uid = ME) => { if (delta && uid === ME) ledger.unshift({ currency, delta, reason, created_at: now() / 1000 }); };
  function newItem(uid, tier, country, source) {
    const [cc, op, sub] = generate(tier, country);
    const it = { id: nextId++, user_id: uid, country: cc, op, sub, tier, price: PRICES[tier], status: "owned", is_new: uid === ME, favorite: false, created_at: now() / 1000, source };
    items.push(it);
    return it;
  }
  function view(it) {
    const c = COUNTRIES[it.country];
    return { id: it.id, country: it.country, flag: c.flag, country_name: c.name, dial: c.dial, op: it.op, sub: it.sub, number: fmtNum(it.country, it.op, it.sub),
      tier: TIERS[it.tier], price: it.price, chance: chanceFor(it.tier), status: it.status, is_new: it.is_new, favorite: it.favorite, created_at: it.created_at };
  }
  // стартовая коллекция и соседи по рынку
  [0, 0, 0, 0, 0, 0, 1, 1, 1, 2].forEach(t => newItem(ME, t, pick(["RU", "RU", "KZ", "BY", "AE"]), "demo"));
  ledger.unshift({ currency: "coins", delta: 2000, reason: "start", created_at: now() / 1000 });
  NAMES.forEach((name, i) => {
    const uid = 100 + i;
    users[uid] = { id: uid, first_name: name, coins: 0, created_at: now() - 30 * DAY, total_spins: 10 + rnd(300) };
    const n = 6 + rnd(10);
    for (let k = 0; k < n; k++) { const r = Math.random(); newItem(uid, r < .5 ? 0 : r < .75 ? 1 : r < .9 ? 2 : r < .97 ? 3 : r < .995 ? 4 : 5, pick(Object.keys(COUNTRIES)), "spin"); }
  });
  items.filter(i => i.user_id !== ME && i.tier >= 1).slice(0, 14).forEach(it => {
    it.status = "listed";
    lots.push({ id: nextLot++, item_id: it.id, seller_id: it.user_id, price: Math.round(it.price * (0.8 + Math.random() * 0.6)), status: "active", created_at: now(), expires_at: now() + 3 * DAY });
  });

  const TASKS = [
    { key: "spin3", title: "Сделай 3 спина", event: "spin", target: 3, coins: 40 },
    { key: "sell1", title: "Продай 1 номер", event: "sell", target: 1, coins: 30 },
    { key: "wheel1", title: "Крутни колесо", event: "wheel", target: 1, coins: 30 },
  ];
  const WHEEL = [{ label: "50", coins: 50, p: .55 }, { label: "100", coins: 100, p: .25 }, { label: "250", coins: 250, p: .12 }, { label: "1 спин", spins: 1, p: .06 }, { label: "1 000", coins: 1000, p: .02 }];
  const GIFT = [50, 75, 100, 150, 200, 300, { coins: 500, spins: 3 }];
  const PRODUCTS = {
    spins5: { title: "Попытки ×5", desc: "5 дополнительных спинов", stars: 25, spins: 5 },
    spins20: { title: "Попытки ×20", desc: "20 дополнительных спинов", stars: 89, spins: 20 },
    spins50: { title: "Попытки ×50", desc: "50 дополнительных спинов", stars: 199, spins: 50 },
    luck15: { title: "Удача ×1,5", desc: "Шансы старших ступеней ×1,5 на 10 спинов", stars: 29, luck: 1.5 },
    luck2: { title: "Удача ×2", desc: "Шансы старших ступеней ×2 на 10 спинов", stars: 49, luck: 2 },
  };
  let starsSpent = 0;
  const err = (message, code = "error", extra = {}) => { throw Object.assign({ message, code }, extra); };
  const task = (ev, n = 1) => TASKS.filter(t => t.event === ev).forEach(t => cnt("task:" + t.key, n));
  const PERIOD = 3 * 3600e3;
  function energy(u) {
    if (u.energy >= 3) { u.energy_ts = now(); return; }
    const g = Math.floor((now() - u.energy_ts) / PERIOD);
    if (g > 0) { u.energy = Math.min(3, u.energy + g); u.energy_ts = u.energy >= 3 ? now() : u.energy_ts + g * PERIOD; }
  }
  const owned = ids => { const out = ids.map(id => items.find(i => i.id === id && i.user_id === ME && i.status === "owned")); if (!ids.length) err("Ничего не выбрано"); if (out.some(x => !x)) err("Часть номеров уже недоступна. Обнови коллекцию"); return out; };
  const colValue = uid => items.filter(i => i.user_id === uid && i.status !== "gone").reduce((a, i) => a + i.price, 0);
  const coinCap = u => Math.min(60, 30 + levelFromXp(u.xp)[0] - 1);

  const H = {
    state() {
      const u = users[ME]; energy(u);
      const [level, xp, need] = levelFromXp(u.xp);
      const today = dayKey(now()), yesterday = dayKey(now() - DAY);
      const last = [...items].reverse().find(i => i.user_id === ME && i.source !== "demo" && i.source !== "market");
      const luck = u.luck_left > 0 ? u.luck_mult : 1;
      const odds = {};
      for (const [k, sc] of Object.entries(SCALES)) { const b = applyLuck(sc.odds, luck); odds[k] = { title: sc.title, price: sc.price, rows: Object.keys(sc.odds).map(Number).sort((a, b) => a - b).map(t => ({ tier: TIERS[t], p: sc.odds[t], p_luck: b[t] })) }; }
      return {
        user: { id: ME, name: u.first_name, username: null, coins: u.coins, spins: u.spins, energy: u.energy, energy_max: 3,
          next_energy_in: u.energy >= 3 ? 0 : Math.round((PERIOD - (now() - u.energy_ts)) / 1000), level, xp, xp_need: need, total_spins: u.total_spins,
          luck, luck_left: u.luck_left, country: u.country, settings: { ...u.settings }, badges: u.badges, coin_spins_left: coinCap(u) - cnt("coin_spins"),
          pity_epic_left: 40 - u.pity_epic, pity_legendary_left: 200 - u.pity_legendary, created_at: u.created_at / 1000 },
        today: { wheel: cnt("wheel") === 0, gift: u.gift_day !== today, gift_day: u.gift_day !== today ? (u.gift_day === yesterday ? (u.gift_streak % 7) + 1 : 1) : u.gift_streak,
          gift_rewards: GIFT, tasks: TASKS.map(t => ({ key: t.key, title: t.title, target: t.target, progress: Math.min(t.target, cnt("task:" + t.key)), coins: t.coins, claimed: !!cnt("claimed:" + t.key) })) },
        wheel: WHEEL.map(w => ({ label: w.label, p: w.p })), odds,
        countries: Object.values(COUNTRIES).map(c => ({ code: c.code, name: c.name, flag: c.flag, dial: c.dial })),
        tiers: TIERS, last_drop: last ? view(last) : null, stars_enabled: true, ref_link: "https://t.me/твой_бот?start=r1",
      };
    },
    spin({ count = 1, scale = "phone" }) {
      if (![1, 5, 10].includes(count)) err("Можно крутить ×1, ×5 или ×10");
      const u = users[ME]; energy(u);
      const price = SCALES[scale].price, coinLeft = coinCap(u) - cnt("coin_spins");
      const plan = [];
      let e = u.energy, s = u.spins, c = u.coins;
      for (let i = 0; i < count; i++) {
        if (scale === "phone" && e > 0) { e--; plan.push("e"); }
        else if (scale === "phone" && s > 0) { s--; plan.push("s"); }
        else if (c >= price && plan.filter(x => x === "c").length < coinLeft) { c -= price; plan.push("c"); }
        else break;
      }
      if (plan.length < count) { if (plan.filter(x => x === "c").length >= coinLeft) err(`Спины за монеты на сегодня закончились (${coinCap(u)} в сутки)`, "limit"); err(`Не хватает ${price * (count - plan.length) - c}`, "no_coins", { need: price * (count - plan.length) - c }); }
      const ue = plan.filter(x => x === "e").length, us = plan.filter(x => x === "s").length, uc = plan.filter(x => x === "c").length;
      u.energy = e; u.spins = s; u.coins = c;
      log("coins", -uc * price, "spin"); log("spins", -us, "spin");
      cnt("coin_spins", uc);
      const drops = [];
      for (let i = 0; i < count; i++) {
        let odds = { ...SCALES[scale].odds };
        const luck = u.luck_left > 0 ? u.luck_mult : 1;
        if (luck > 1) { odds = applyLuck(odds, luck); u.luck_left--; }
        const floor = u.pity_legendary + 1 >= 200 ? 4 : u.pity_epic + 1 >= 40 ? 3 : null;
        if (floor !== null) { const f = {}; let t = 0; for (const k in odds) if (+k >= floor) { f[k] = odds[k]; t += odds[k]; } for (const k in f) f[k] /= t; odds = f; }
        const keys = Object.keys(odds).map(Number).sort((a, b) => a - b);
        let r = Math.random(), tier = keys[keys.length - 1];
        for (const k of keys) { r -= odds[k]; if (r < 0) { tier = k; break; } }
        u.pity_epic = tier >= 3 ? 0 : u.pity_epic + 1;
        u.pity_legendary = tier >= 4 ? 0 : u.pity_legendary + 1;
        drops.push(view(newItem(ME, tier, u.country, "spin")));
      }
      const before = levelFromXp(u.xp)[0];
      u.xp += count * (scale === "premium" ? 50 : 10);
      u.total_spins += count;
      const today = cnt("spins", count);
      task("spin", count);
      return { drops, paid: { energy: ue, spins: us, coins: uc * price }, level_up: levelFromXp(u.xp)[0] > before, level: levelFromXp(u.xp)[0], break_hint: today - count < 50 && today >= 50 };
    },
    country({ code }) { users[ME].country = code; return { ok: true }; },
    settings(v) { Object.keys(users[ME].settings).forEach(k => { if (k in v) users[ME].settings[k] = !!v[k]; }); return { ...users[ME].settings }; },
    collection({ min_tier = 0, q = "", favorites = false }) {
      const digits = String(q).replace(/\D/g, "");
      const mine = items.filter(i => i.user_id === ME && i.status !== "gone");
      const list = mine.filter(i => i.tier >= min_tier && (!digits || (i.op + i.sub).includes(digits)) && (!favorites || i.favorite)).sort((a, b) => b.tier - a.tier || b.price - a.price || b.id - a.id);
      const counts = {}; mine.forEach(i => { counts[i.tier] = (counts[i.tier] || 0) + 1; });
      return { items: list.map(view), counts, value: colValue(ME) };
    },
    seen() { items.forEach(i => { if (i.user_id === ME) i.is_new = false; }); return { ok: true }; },
    favorite({ id }) { const it = items.find(i => i.id === id && i.user_id === ME); if (!it) err("Номер не найден"); it.favorite = !it.favorite; return { favorite: it.favorite }; },
    sell({ ids }) { const list = owned(ids); const total = list.reduce((a, i) => a + i.price, 0); list.forEach(i => { i.status = "gone"; }); users[ME].coins += total; log("coins", total, "sell"); task("sell", list.length); return { coins: total, sold: list.length }; },
    bulk_preview({ max_tier }) { const m = Math.min(max_tier, 2); const l = items.filter(i => i.user_id === ME && i.status === "owned" && !i.favorite && i.tier <= m); return { count: l.length, coins: l.reduce((a, i) => a + i.price, 0), max_tier: m }; },
    bulk_sell({ max_tier }) { const m = Math.min(max_tier, 2); const l = items.filter(i => i.user_id === ME && i.status === "owned" && !i.favorite && i.tier <= m); if (!l.length) err("Нечего продавать: избранное не продаётся пачкой"); return H.sell({ ids: l.map(i => i.id) }); },
    contract({ ids }) {
      const list = owned(ids);
      if (list.length !== 5) err("Нужно ровно 5 номеров одной ступени");
      if (new Set(list.map(i => i.tier)).size !== 1) err("Все 5 номеров должны быть одной ступени");
      if (list[0].tier > 6) err("Эту ступень нельзя улучшить");
      list.forEach(i => { i.status = "gone"; });
      return { item: view(newItem(ME, list[0].tier + 1, pick(list).country, "contract")) };
    },
    "upgrade/quote"({ ids = [], coins = 0, target }) {
      const u = users[ME];
      if (u.settings.no_upgrader) err("Апгрейдер выключен в настройках");
      if (ids.length > 3) err("Не больше 3 номеров за раз");
      const list = ids.length ? owned(ids) : [];
      if (coins > u.coins) err("Не хватает монет");
      const stake = list.reduce((a, i) => a + i.price, 0) + coins;
      if (stake <= 0) err("Положи номер или монеты");
      if (PRICES[target] <= stake) err("Цель должна стоить дороже ставки");
      if (stake > (colValue(ME) + u.coins) / 2) err("За раз можно поставить не больше половины стоимости коллекции");
      const base = stake / PRICES[target] * 0.85;
      return { coins, stake, target, target_price: PRICES[target], chance: Math.min(0.9, base + u.upgrade_bonus), base_chance: base, bonus: u.upgrade_bonus, left_today: 10 - cnt("upgrades") };
    },
    upgrade(b) {
      const q = H["upgrade/quote"](b), u = users[ME];
      if (q.left_today <= 0) err("На сегодня апгрейды закончились (10 в сутки)");
      cnt("upgrades", 1);
      const list = (b.ids || []).map(id => items.find(i => i.id === id));
      list.forEach(i => { i.status = "gone"; });
      u.coins -= q.coins; log("coins", -q.coins, "upgrade");
      const roll = Math.random(), success = roll < q.chance;
      const res = { success, chance: q.chance, roll };
      if (success) { res.item = view(newItem(ME, b.target, list.length ? pick(list).country : "RU", "upgrade")); u.upgrade_bonus = 0; }
      else { const parts = Math.floor(q.stake * 0.1); u.coins += parts; log("coins", parts, "upgrade_parts"); u.upgrade_bonus += 0.03; res.parts = parts; res.next_bonus = u.upgrade_bonus; }
      return res;
    },
    market({ min_tier = 0, sort = "new" }) {
      const l = lots.filter(x => x.status === "active").map(x => ({ x, it: items.find(i => i.id === x.item_id) })).filter(o => o.it.tier >= min_tier);
      l.sort(sort === "cheap" ? (a, b) => a.x.price - b.x.price : sort === "rare" ? (a, b) => b.it.tier - a.it.tier || b.x.price - a.x.price : (a, b) => b.x.id - a.x.id);
      return { lots: l.map(lotView), fee: 0.1 };
    },
    "market/mine"() {
      const mine = lots.filter(x => x.seller_id === ME || x.buyer_id === ME).sort((a, b) => b.id - a.id).map(x => ({ ...lotView({ x, it: items.find(i => i.id === x.item_id) }), lot_status: x.status, side: x.seller_id === ME ? "sell" : "buy" }));
      return { active: mine.filter(l => l.lot_status === "active" && l.side === "sell"), deals: mine.filter(l => l.lot_status === "sold") };
    },
    "market/list"({ id, price }) {
      const it = owned([id])[0];
      if (price < Math.floor(it.price * .5) || price > Math.floor(it.price * 1.5)) err("Цена вне вилки 50–150%");
      it.status = "listed";
      const lot = { id: nextLot++, item_id: it.id, seller_id: ME, price, status: "active", created_at: now(), expires_at: now() + 3 * DAY };
      lots.push(lot);
      // в демо кто-то из соседей купит лот через 20 секунд, чтобы было видно, как приходит сделка
      setTimeout(() => { if (lot.status === "active") { lot.status = "sold"; lot.buyer_id = 100 + rnd(7); it.user_id = lot.buyer_id; it.status = "owned"; const get = price - Math.floor(price * .1); users[ME].coins += get; log("coins", get, "market_sell"); } }, 20000);
      return { lot_id: lot.id, you_get: price - Math.floor(price * .1) };
    },
    "market/cancel"({ lot_id }) { const l = lots.find(x => x.id === lot_id && x.seller_id === ME && x.status === "active"); if (!l) err("Лот уже закрыт"); l.status = "cancelled"; items.find(i => i.id === l.item_id).status = "owned"; return { ok: true }; },
    "market/buy"({ lot_id }) {
      const l = lots.find(x => x.id === lot_id && x.status === "active"), u = users[ME];
      if (!l) err("Этот лот уже купили или сняли");
      if (l.seller_id === ME) err("Нельзя купить свой лот");
      if (u.coins < l.price) err(`Не хватает ${l.price - u.coins}`, "no_coins", { need: l.price - u.coins });
      u.coins -= l.price; log("coins", -l.price, "market_buy");
      l.status = "sold"; l.buyer_id = ME;
      const it = items.find(i => i.id === l.item_id); it.user_id = ME; it.status = "owned"; it.is_new = true; it.favorite = false; it.source = "market";
      return { item: view(it) };
    },
    wheel() {
      if (cnt("wheel")) err("Колесо уже крутил сегодня. Следующее завтра", "used");
      let r = Math.random(), idx = WHEEL.length - 1;
      for (let i = 0; i < WHEEL.length; i++) { r -= WHEEL[i].p; if (r < 0) { idx = i; break; } }
      const s = WHEEL[idx], u = users[ME];
      cnt("wheel", 1); u.coins += s.coins || 0; u.spins += s.spins || 0; log("coins", s.coins || 0, "wheel"); log("spins", s.spins || 0, "wheel"); task("wheel");
      return { index: idx, label: s.label, coins: s.coins || 0, spins: s.spins || 0 };
    },
    gift() {
      const u = users[ME], today = dayKey(now()), yesterday = dayKey(now() - DAY);
      if (u.gift_day === today) err("Подарок уже забран. Возвращайся завтра", "used");
      const streak = u.gift_day === yesterday ? (u.gift_streak % 7) + 1 : 1, r = GIFT[streak - 1];
      const coins = typeof r === "number" ? r : r.coins, spins = typeof r === "number" ? 0 : r.spins;
      u.gift_day = today; u.gift_streak = streak; u.coins += coins; u.spins += spins; log("coins", coins, "gift"); log("spins", spins, "gift");
      return { day: streak, coins, spins };
    },
    task({ key }) {
      const t = TASKS.find(x => x.key === key);
      if (!t) err("Такого задания сегодня нет");
      if (cnt("claimed:" + key)) err("Награда уже получена");
      if (cnt("task:" + key) < t.target) err("Задание ещё не выполнено");
      cnt("claimed:" + key, 1); users[ME].coins += t.coins; log("coins", t.coins, "task");
      return { coins: t.coins };
    },
    friends() {
      return { count: 2, required_spins: 10, friend_spins: 3, ref_link: "https://t.me/твой_бот?start=r1",
        tiers: [{ count: 1, title: "3 спина" }, { count: 5, title: "300 монет и рамка профиля" }, { count: 10, title: "1 000 монет и эффект анимации" }, { count: 25, title: "Значок «Амбассадор»" }],
        friends: [{ name: "Аня", spins: 10, qualified: true }, { name: "Миша", spins: 10, qualified: true }, { name: "Лера", spins: 4, qualified: false }] };
    },
    rating({ kind = "value", scope = "all" }) {
      let ids = Object.keys(users).map(Number);
      if (scope === "friends") ids = [ME, 100, 101, 102];
      let rows = ids.map(id => {
        const mine = items.filter(i => i.user_id === id && i.status !== "gone");
        if (!mine.length) return null;
        const best = mine.reduce((a, i) => (i.tier > a.tier || (i.tier === a.tier && i.price > a.price)) ? i : a);
        return { id, name: users[id].first_name, score: kind === "best" ? best.tier * 1e9 + best.price : colValue(id), best };
      }).filter(Boolean).sort((a, b) => b.score - a.score);
      const out = rows.map((r, i) => ({ pos: i + 1, id: r.id, name: r.name, me: r.id === ME, ...(kind === "best" ? { item: view(r.best) } : { value: r.score }) }));
      return { top: out.slice(0, 50), me: out.find(x => x.me) || null };
    },
    history() { return { items: ledger.slice(0, 20) }; },
    shop() { return { enabled: true, products: Object.entries(PRODUCTS).map(([key, p]) => ({ key, ...p })), month_spent: starsSpent, month_cap: 500, spins_stock_cap: 100 }; },
    "shop/invoice"({ key }) {
      const p = PRODUCTS[key], u = users[ME];
      if (!p) err("Нет такого товара");
      if (starsSpent + p.stars > 500) err(`Месячный лимит покупок 500 ⭐. Осталось ${500 - starsSpent} ⭐`, "cap");
      if (p.spins && u.spins + p.spins > 100) err("Запас попыток не больше 100. Сначала потрать текущие", "stock");
      if (p.luck && u.luck_left > 0 && u.luck_mult > p.luck) err("Уже действует более сильная удача", "luck_active");
      return { demo: true };
    },
    "shop/demo_pay"({ key }) {
      const p = PRODUCTS[key], u = users[ME];
      starsSpent += p.stars;
      if (p.spins) { u.spins += p.spins; log("spins", p.spins, "purchase"); }
      if (p.luck) { u.luck_mult = p.luck; u.luck_left = 10; }
      return { granted: p.title };
    },
  };
  function lotView({ x, it }) { return { ...view(it), lot_id: x.id, lot_price: x.price, seller_id: x.seller_id, seller: users[x.seller_id].first_name, expires_at: x.expires_at / 1000 }; }

  window.DemoServer = {
    async call(path, body) {
      await new Promise(r => setTimeout(r, 60));
      const fn = H[path];
      if (!fn) throw { message: "Нет такого метода", code: "error" };
      try { return JSON.parse(JSON.stringify(fn(body || {}))); }
      catch (e) { if (e && e.message && e.code) throw e; console.error(e); throw { message: "Ошибка демо", code: "error" }; }
    },
  };
})();
