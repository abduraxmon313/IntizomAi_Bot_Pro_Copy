/* ═══════════════════════════════════════════════════════════════════════════
   OBSIDIAN (7-chi tema) — dashboard moduli
   ═══════════════════════════════════════════════════════════════════════════
   Bu modul BUTUNLAY qo'shimcha (additive) va faqat `data-theme="obsidian"`
   faol bo'lganda ishlaydi. Boshqa 6 tema uchun barcha funksiyalar no-op
   (hech narsa qilmaydi) va qo'shilgan DOM node'lar olib tashlanadi.

   Nima qiladi:
     • Desktop/planshet uchun professional top navigatsiya
     • Home sahifasiga yetishmayotgan dashboard bloklarini qo'shadi:
         – metrics strip (streak / bugun / daraja / XP)
         – AI insight kartasi (Intizom AI identiteti)
         – tezkor amallar (quick actions)
         – haftalik bajarilish grafigi
         – oxirgi faollik ro'yxati
     • Mavjud render funksiyalarini O'RAB OLADI (wrap) — ularni almashtirmaydi,
       shuning uchun asl mantiq buzilmaydi.

   Muhim qoidalar:
     • Faqat YANGI id'lar ishlatiladi (mavjud id'lar dublikat bo'lmaydi)
     • Mavjud DOM ko'chirilmaydi/o'chirilmaydi
     • Ma'lumot `window.IZ.State` (app.js beradigan ko'prik) orqali o'qiladi
     • Har qanday xato try/catch ichida yutiladi — asosiy app buzilmasin
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var KEY = 'obsidian';
  var HTML = document.documentElement;
  var built = false;

  function isOn() { return HTML.getAttribute('data-theme') === KEY; }
  function bridge() { return window.IZ || {}; }
  function St() { return bridge().State || {}; }

  var UZ_DOW = ['Du', 'Se', 'Cho', 'Pa', 'Ju', 'Sha', 'Ya'];
  var UZ_MON = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'];

  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function byId(id) { return document.getElementById(id); }
  function node(tag, cls, id) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (id) n.id = id;
    return n;
  }
  function clickProxy(sel) {
    var t = document.querySelector(sel);
    if (t) t.click();
  }

  /* ── Ikonalar (feather uslubi, 1.75 stroke) ─────────────────────────── */
  var IC = {
    spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/><path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z"/></svg>',
    flame: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s4.5 4.2 4.5 8.4A4.5 4.5 0 0 1 12 16a4.5 4.5 0 0 1-4.5-4.6C7.5 7.2 12 3 12 3z"/><path d="M12 21a6 6 0 0 0 6-6c0-1.2-.3-2.3-.8-3.3"/><path d="M12 21a6 6 0 0 1-6-6c0-1.2.3-2.3.8-3.3"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 12.5 9.5 18 20 6.5"/></svg>',
    layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 3 21 8 12 13 3 8 12 3"/><polyline points="3 13 12 18 21 13"/></svg>',
    bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 4 14 11 14 10 22 20 9 13 9 13 2"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    repeat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z"/></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-1.5A4.5 4.5 0 0 0 15.5 15h-7A4.5 4.5 0 0 0 4 19.5V21"/><circle cx="12" cy="8" r="4"/></svg>',
    inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 19 3 19 3 8"/><path d="M3 8l2.2-4h13.6L21 8"/><path d="M3 12h5l1 2h6l1-2h5"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="18" y2="12"/><polyline points="13 7 18 12 13 17"/></svg>'
  };

  /* ═════════════════ TOP NAVIGATSIYA (desktop / planshet) ═════════════ */

  var NAV = [
    { k: 'home', label: 'Dashboard' },
    { k: 'goals', label: 'Maqsadlar' },
    { k: 'habits', label: 'Odatlar' },
    { k: 'stats', label: 'Progress' },
    { k: 'ai', label: 'AI' },
    { k: 'friends', label: "Do'stlar" }
  ];

  function buildTopbar() {
    if (byId('obsTopbar')) return;
    var app = document.querySelector('.app');
    if (!app || !app.parentNode) return;

    var bar = node('header', 'obs-topbar obs-node', 'obsTopbar');
    var inner = node('div', 'obs-topbar-inner');

    var brand = node('div', 'obs-brand');
    brand.innerHTML =
      '<span class="obs-brand-mark">' + IC.spark + '</span>' +
      '<span class="obs-brand-name">Intizom<i>AI</i></span>';
    brand.onclick = function () { clickProxy('.nav-item[data-nav="home"]'); };

    var nav = node('nav', 'obs-nav');
    nav.innerHTML = NAV.map(function (n) {
      return '<button type="button" class="obs-nav-link" data-obs-go="' + n.k + '">' + esc(n.label) + '</button>';
    }).join('');

    var right = node('div', 'obs-topbar-right');
    right.innerHTML =
      '<span class="obs-ai-status" id="obsAiStatus"><i class="obs-ai-dot"></i> AI faol</span>' +
      '<button type="button" class="obs-icon-btn" id="obsModeBtn" aria-label="Rejim">' + IC.moon + '</button>' +
      '<button type="button" class="obs-icon-btn" id="obsProfileBtn" aria-label="Profil">' + IC.user + '</button>';

    inner.appendChild(brand);
    inner.appendChild(nav);
    inner.appendChild(right);
    bar.appendChild(inner);
    app.parentNode.insertBefore(bar, app);

    /* Navigatsiya — mavjud tugmalarni "proxy" qilib bosadi, shuning uchun
       Premium gate (premiumGate) mantiqi aynan bir xil ishlaydi. */
    nav.querySelectorAll('[data-obs-go]').forEach(function (b) {
      b.onclick = function () {
        var k = b.dataset.obsGo;
        if (k === 'stats') { clickProxy('#statsBtn'); return; }
        if (k === 'ai') { clickProxy('.nav-ai[data-nav="ai"]'); return; }
        clickProxy('.nav-item[data-nav="' + k + '"]');
      };
    });
    var mb = byId('obsModeBtn');
    if (mb) mb.onclick = function () { clickProxy('#modeBtn'); syncTopbar(); };
    var pb = byId('obsProfileBtn');
    if (pb) pb.onclick = function () { clickProxy('#settingsBtn'); };
  }

  function syncTopbar() {
    var bar = byId('obsTopbar');
    if (!bar) return;
    var active = null;
    var pg = document.querySelector('.page.active');
    if (pg) active = pg.dataset.page;
    bar.querySelectorAll('[data-obs-go]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.obsGo === active);
    });
    var mb = byId('obsModeBtn');
    if (mb) {
      var dark = HTML.getAttribute('data-mode') === 'dark';
      mb.innerHTML = dark ? IC.sun : IC.moon;
      mb.setAttribute('aria-label', dark ? 'Kunduzgi rejim' : 'Tungi rejim');
    }
  }

  /* ═════════════════ HOME DASHBOARD BLOKLARI ═════════════════════════ */

  function buildHome() {
    var home = document.querySelector('.page[data-page="home"]');
    if (!home || byId('obsSide')) return;

    /* ── O'ng panel (desktop) / aralashgan bloklar (mobil) ──────────── */
    var side = node('div', 'obs-node', 'obsSide');

    /* 1. Metrics strip */
    var metrics = node('section', 'obs-metrics obs-node', 'obsMetrics');
    metrics.innerHTML = [
      metricHTML('streak', IC.flame, 'Streak'),
      metricHTML('today', IC.check, 'Bugun'),
      metricHTML('level', IC.layers, 'Daraja'),
      metricHTML('xp', IC.bolt, 'Jami XP')
    ].join('');

    /* 2. AI insight */
    var ai = node('section', 'obs-ai obs-node', 'obsAi');
    ai.innerHTML =
      '<div class="obs-ai-head">' +
        '<span class="obs-ai-mark">' + IC.spark + '</span>' +
        '<span class="obs-ai-label">Intizom AI</span>' +
        '<span class="obs-badge obs-badge--accent" id="obsAiTag">Tahlil</span>' +
      '</div>' +
      '<div id="obsAiBody">' +
        '<div class="obs-skel obs-skel-line" style="width:70%"></div>' +
        '<div class="obs-skel obs-skel-line"></div>' +
        '<div class="obs-skel obs-skel-line"></div>' +
      '</div>' +
      '<div class="obs-ai-foot">' +
        '<span class="obs-eyebrow" id="obsAiMeta">Real vaqtda hisoblanadi</span>' +
        '<button type="button" class="obs-btn obs-btn--ghost" id="obsAiOpen">AI Coach ' + IC.arrow + '</button>' +
      '</div>';

    /* 3. Tezkor amallar */
    var quick = node('section', 'obs-quick obs-node', 'obsQuick');
    quick.innerHTML = [
      quickHTML('plan', IC.plus, "Reja qo'shish"),
      quickHTML('habit', IC.repeat, "Odat qo'shish"),
      quickHTML('ai', IC.spark, 'AI bilan suhbat'),
      quickHTML('stats', IC.chart, 'Statistika')
    ].join('');

    /* 4. Oxirgi faollik */
    var act = node('section', 'obs-card obs-node', 'obsActivity');
    act.innerHTML =
      '<div class="obs-card-head">' +
        '<span class="obs-card-title">Oxirgi faollik</span>' +
        '<span class="obs-badge" id="obsActBadge">—</span>' +
      '</div>' +
      '<div class="obs-act" id="obsActList">' +
        '<div class="obs-skel obs-skel-line"></div>' +
        '<div class="obs-skel obs-skel-line"></div>' +
      '</div>';

    side.appendChild(metrics);
    side.appendChild(ai);
    side.appendChild(quick);
    side.appendChild(act);
    home.appendChild(side);

    /* 5. Haftalik progress (asosiy ustunda, ro'yxatdan keyin) */
    var week = node('section', 'obs-card obs-node', 'obsWeek');
    week.innerHTML =
      '<div class="obs-card-head">' +
        '<span class="obs-card-title">Haftalik bajarilish</span>' +
        '<span class="obs-badge" id="obsWeekBadge">Oxirgi 7 kun</span>' +
      '</div>' +
      '<div class="obs-week-chart" id="obsWeekChart"></div>';
    home.appendChild(week);

    /* Amallarni bog'lash */
    var aiOpen = byId('obsAiOpen');
    if (aiOpen) aiOpen.onclick = function () { clickProxy('.nav-ai[data-nav="ai"]'); };
    quick.querySelectorAll('[data-obs-act]').forEach(function (b) {
      b.onclick = function () {
        var a = b.dataset.obsAct;
        if (a === 'plan') { clickProxy('#addPlanBtn'); return; }
        if (a === 'habit') { clickProxy('#addHabitBtn'); return; }
        if (a === 'ai') { clickProxy('.nav-ai[data-nav="ai"]'); return; }
        if (a === 'stats') { clickProxy('#statsBtn'); return; }
      };
    });
  }

  function metricHTML(k, icon, label) {
    return '<div class="obs-metric" id="obsM_' + k + '">' +
      '<div class="obs-metric-l">' + icon + '<span>' + esc(label) + '</span></div>' +
      '<div class="obs-metric-v" id="obsMv_' + k + '">–</div>' +
      '<div class="obs-metric-s" id="obsMs_' + k + '">&nbsp;</div>' +
      '</div>';
  }

  function quickHTML(act, icon, label) {
    return '<button type="button" class="obs-quick-btn" data-obs-act="' + act + '">' +
      '<span class="obs-quick-ic">' + icon + '</span>' +
      '<span>' + esc(label) + '</span>' +
      '</button>';
  }

  /* ═════════════════ MA'LUMOTNI SINXRONLASH ══════════════════════════ */

  function setHTML(id, html) { var e = byId(id); if (e) e.innerHTML = html; }
  function setTxt(id, t) { var e = byId(id); if (e) e.textContent = t; }

  function syncMetrics() {
    var s = St().snap || {};
    var streak = s.streak || 0;
    var done = s.today_done || 0;
    var total = s.today_total || 0;
    var lvl = s.level || 1;
    var xp = s.xp || 0;

    setTxt('obsMv_streak', streak);
    var ms = byId('obsMs_streak');
    if (ms) {
      if (s.streak_at_risk && streak >= 2) {
        ms.textContent = 'Xavf ostida';
        ms.className = 'obs-metric-s warn';
      } else if (streak > 0) {
        ms.textContent = 'Eng uzuni ' + (s.longest_streak || streak);
        ms.className = 'obs-metric-s';
      } else {
        ms.textContent = 'Bugun boshlanadi';
        ms.className = 'obs-metric-s';
      }
    }

    setHTML('obsMv_today', done + '<small> / ' + total + '</small>');
    var mt = byId('obsMs_today');
    if (mt) {
      var pct = total ? Math.round(done * 100 / total) : 0;
      mt.textContent = total ? pct + '% bajarildi' : 'Reja belgilanmagan';
      mt.className = 'obs-metric-s' + (total && pct >= 100 ? ' up' : '');
    }

    setTxt('obsMv_level', lvl);
    setTxt('obsMs_level', (s.xp_in_level || 0) + ' / ' + (s.xp_needed || 100) + ' XP');

    setTxt('obsMv_xp', formatNum(xp));
    setTxt('obsMs_xp', (s.rank_title ? stripEmoji(s.rank_title) : 'Boshlovchi'));
  }

  function formatNum(n) {
    n = Number(n) || 0;
    return n >= 10000 ? (Math.round(n / 100) / 10) + 'k' : String(n);
  }
  function stripEmoji(s) {
    try { return String(s || '').replace(/^[\s\p{Extended_Pictographic}\uFE0F\u200D]+/u, '').trim(); }
    catch (_) { return String(s || '').trim(); }
  }

  /* ── AI insight: lokal, real ma'lumotga asoslangan tavsiya ────────── */
  function buildInsight() {
    var s = St().snap || {};
    var plans = St().plans || [];
    var habits = St().habits || [];
    var ds = s.discipline_score != null ? s.discipline_score : 50;
    var streak = s.streak || 0;
    var done = s.today_done || 0;
    var total = s.today_total || 0;
    var left = Math.max(0, total - done);
    var pendingHabits = habits.filter(function (h) { return h.due_today && !h.finished && !h.done_today; }).length;

    if (s.streak_at_risk && streak >= 2) {
      return {
        tag: 'Ogohlantirish',
        t: streak + ' kunlik ketma-ketlik xavf ostida',
        d: 'Bugun kamida bitta vazifani yopsang, seriya saqlanadi. Eng qisqasidan boshla — 5 daqiqalik ish ham hisoblanadi.'
      };
    }
    if (total === 0 && pendingHabits === 0) {
      return {
        tag: 'Tavsiya',
        t: 'Bugun uchun aniq reja yo\u2019q',
        d: 'Kunni yozib qo\u2019yilgan maqsad bilan boshlash bajarilish ehtimolini sezilarli oshiradi. Bitta muhim vazifa qo\u2019shing va shundan boshlang.'
      };
    }
    if (total > 0 && done >= total && pendingHabits === 0) {
      return {
        tag: 'Natija',
        t: 'Bugungi reja to\u2019liq yopildi',
        d: 'Discipline score ' + ds + '. Bu barqarorlik belgisi — ertangi kunni bugun rejalashtirsang, momentum saqlanadi.'
      };
    }
    if (ds >= 80) {
      return {
        tag: 'Tahlil',
        t: 'Intizom yuqori zonada',
        d: 'Discipline score ' + ds + ' — foydalanuvchilarning yuqori qatlamidasan. Yuklamani bir pog\u2019ona oshirish uchun qulay payt.'
      };
    }
    if (ds < 45) {
      return {
        tag: 'Tahlil',
        t: 'Tizim sekinlashgan',
        d: 'Discipline score ' + ds + '. Tiklanish katta qadamdan emas, kichik va takrorlanadigan qadamdan boshlanadi: bugun eng oson vazifani yop.'
      };
    }
    if (left > 0) {
      var nextTitle = '';
      var pend = plans.filter(function (p) { return p.status !== 'done'; })
        .sort(function (a, b) { return String(a.scheduled_time || '99:99').localeCompare(String(b.scheduled_time || '99:99')); });
      if (pend.length) nextTitle = pend[0].title || '';
      return {
        tag: 'Fokus',
        t: left + ' vazifa hali yopilmagan',
        d: nextTitle
          ? 'Keyingi qadam: \u201C' + nextTitle + '\u201D. Bitta vazifani oxirigacha yopish ikkitasini yarim qoldirishdan foydaliroq.'
          : 'Bitta vazifani oxirigacha yopish ikkitasini yarim qoldirishdan foydaliroq. Eng muhimidan boshla.'
      };
    }
    if (pendingHabits > 0) {
      return {
        tag: 'Fokus',
        t: pendingHabits + ' odat bugun belgilanmagan',
        d: 'Rejalar yopilgan — odatlar qoldi. Ular streakni ushlab turadigan asosiy mexanizm.'
      };
    }
    return {
      tag: 'Tahlil',
      t: 'Barqaror ritm',
      d: 'Discipline score ' + ds + ', ' + streak + ' kunlik seriya. Hozirgi tempni saqlash — eng samarali strategiya.'
    };
  }

  function syncAi() {
    if (!byId('obsAiBody')) return;
    var i = buildInsight();
    setHTML('obsAiBody',
      '<div class="obs-ai-t">' + esc(i.t) + '</div>' +
      '<div class="obs-ai-d">' + esc(i.d) + '</div>');
    setTxt('obsAiTag', i.tag);
    var s = St().snap || {};
    setTxt('obsAiMeta', 'Discipline ' + (s.discipline_score != null ? s.discipline_score : '—') + ' \u00B7 real vaqtda');
  }

  /* ── Haftalik bajarilish grafigi ──────────────────────────────────── */
  var rangeAsked = false;

  function dayStats(d) {
    var key = ymd(d);
    var range = St().plansRange || [];
    var plans = range.length ? range : (St().plans || []);
    var total = 0, done = 0;
    plans.forEach(function (p) {
      if (String(p.plan_date) !== key) return;
      total++;
      if (p.status === 'done') done++;
    });
    (St().habits || []).forEach(function (h) {
      var due = false;
      try { due = window.habitDueOn ? window.habitDueOn(h, d) : (h.frequency || 'daily') === 'daily'; }
      catch (_) { due = false; }
      if (!due) return;
      total++;
      if (Array.isArray(h.log_dates) && h.log_dates.indexOf(key) !== -1) done++;
    });
    return { total: total, done: done, pct: total ? Math.round(done * 100 / total) : 0 };
  }

  var weekSig = '';

  function syncWeek() {
    var wrap = byId('obsWeekChart');
    if (!wrap) return;
    var today = new Date();
    var html = '';
    var sumDone = 0, sumTotal = 0;
    var sig = '';
    for (var i = 6; i >= 0; i--) {
      var d = addDays(today, -i);
      var st = dayStats(d);
      sumDone += st.done;
      sumTotal += st.total;
      sig += st.done + '/' + st.total + '|';
      /* Ustun balandligi: yorliq (~20%) uchun joy qoldiriladi */
      var h = st.total ? Math.max(6, Math.round(st.pct * 0.78)) : 0;
      var cls = st.total === 0 ? '' : (st.pct >= 100 ? 'full' : 'has');
      html += '<div class="obs-wcol' + (i === 0 ? ' today' : '') + '">' +
        '<div class="obs-wbar ' + cls + '" data-h="' + h + '" title="' +
        d.getDate() + ' ' + UZ_MON[d.getMonth()] + ' \u2014 ' + st.done + '/' + st.total + '"></div>' +
        '<div class="obs-wlb">' + (i === 0 ? 'Bugun' : UZ_DOW[(d.getDay() + 6) % 7]) + '</div>' +
        '</div>';
    }
    /* Bir xil ma'lumotda qayta chizmaymiz (animatsiya "sakramasin") */
    if (sig === weekSig && wrap.children.length) return;
    weekSig = sig;
    wrap.innerHTML = html;
    /* Balandlikni keyingi freymda beramiz — o'sish animatsiyasi ko'rinadi */
    requestAnimationFrame(function () {
      wrap.querySelectorAll('.obs-wbar').forEach(function (b) {
        var h = +b.dataset.h || 0;
        b.style.height = h ? h + '%' : '3px';
      });
    });
    setTxt('obsWeekBadge', sumTotal ? Math.round(sumDone * 100 / sumTotal) + '% \u00B7 7 kun' : 'Oxirgi 7 kun');

    /* 30 kunlik oyna hali yuklanmagan bo'lsa — bir marta yuklab, qayta chizamiz */
    if (!(St().plansRange || []).length && !rangeAsked && typeof window.loadPlansRange === 'function') {
      rangeAsked = true;
      try {
        var pr = window.loadPlansRange();
        if (pr && typeof pr.then === 'function') pr.then(function () { if (isOn()) { syncWeek(); syncActivity(); } });
      } catch (_) { }
    }
  }

  /* ── Oxirgi faollik ───────────────────────────────────────────────── */
  function relDay(key) {
    var today = ymd(new Date());
    if (key === today) return 'Bugun';
    if (key === ymd(addDays(new Date(), -1))) return 'Kecha';
    var diff = Math.round((new Date(today + 'T00:00:00') - new Date(key + 'T00:00:00')) / 86400000);
    if (diff > 1 && diff < 30) return diff + ' kun oldin';
    var d = new Date(key + 'T00:00:00');
    return d.getDate() + ' ' + UZ_MON[d.getMonth()];
  }

  var actSig = null;

  function syncActivity() {
    var list = byId('obsActList');
    if (!list) return;
    var items = [];
    var range = St().plansRange || [];
    var plans = range.length ? range : (St().plans || []);
    plans.forEach(function (p) {
      if (p.status !== 'done') return;
      items.push({ key: String(p.plan_date || ''), t: p.title || '', kind: 'plan', v: '+' + (p.score_value || 0) });
    });
    (St().habits || []).forEach(function (h) {
      var logs = Array.isArray(h.log_dates) ? h.log_dates.slice(-5) : [];
      logs.forEach(function (k) {
        items.push({ key: k, t: (h.icon ? h.icon + ' ' : '') + (h.title || ''), kind: 'habit', v: '+5' });
      });
    });
    items.sort(function (a, b) { return b.key.localeCompare(a.key); });
    items = items.slice(0, 6);

    var sig = items.map(function (x) { return x.key + x.t; }).join('|');
    if (sig === actSig && list.children.length) return;
    actSig = sig;

    if (!items.length) {
      list.innerHTML =
        '<div class="obs-empty">' +
          '<div class="obs-empty-ic">' + IC.inbox + '</div>' +
          '<div class="obs-empty-t">Faollik hali yo\u2019q</div>' +
          '<div class="obs-empty-d">Birinchi vazifani yoping \u2014 u shu yerda tarixga tushadi.</div>' +
        '</div>';
      setTxt('obsActBadge', '0');
      return;
    }
    list.innerHTML = items.map(function (it, i) {
      return '<div class="obs-act-row" style="animation-delay:' + (i * 40) + 'ms">' +
        '<span class="obs-act-ic ' + (it.kind === 'habit' ? 'habit' : '') + '">' + IC.check + '</span>' +
        '<div class="obs-act-b">' +
          '<div class="obs-act-t">' + esc(it.t) + '</div>' +
          '<div class="obs-act-m">' + esc(it.kind === 'habit' ? 'Odat bajarildi' : 'Reja bajarildi') + ' \u00B7 ' + esc(relDay(it.key)) + '</div>' +
        '</div>' +
        '<span class="obs-act-v">' + esc(it.v) + '</span>' +
        '</div>';
    }).join('');
    setTxt('obsActBadge', items.length + (items.length >= 6 ? '+' : ''));
  }

  function syncAll() {
    if (!isOn()) return;
    try { syncTopbar(); } catch (e) { }
    try { syncMetrics(); } catch (e) { }
    try { syncAi(); } catch (e) { }
    try { syncWeek(); } catch (e) { }
    try { syncActivity(); } catch (e) { }
  }

  /* ═════════════ SARLAVHALARDAN BEZAK EMOJI'NI OLISH ═════════════════ */
  /* Obsidian tilida emoji ASOSIY UI elementi emas. Statik sarlavhalar
     ("Odatlar ✅", "🎨 Tema", "📊 Mening") tozalanadi; asl matn
     `data-obs-raw` ichida saqlanadi va tema o'zgarganda tiklanadi.
     Foydalanuvchi ma'lumoti (odat belgisi, kayfiyat) TEGILMAYDI. */
  var CLEAN_SEL = [
    '.page .hdr .hdr-greet h1',
    '.section-title h2',
    '.habit-view-seg .hvs',
    '.friends-actions .btn'
  ].join(',');
  /* Dinamik (JS to'ldiradigan) matnlarga tegmaymiz — ular keyin qayta yoziladi */
  var SKIP_IDS = {
    userName: 1, homePlansTitle: 1,
    friendsGroupName: 1, friendsMemberName: 1
  };

  function stripDeco(txt) {
    var t = String(txt == null ? '' : txt);
    try { t = t.replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, ''); }
    catch (_) { t = t.replace(/[\u2190-\u27BF\uFE0F\u200D\uD800-\uDFFF]/g, ''); }
    return t.replace(/\s{2,}/g, ' ').trim();
  }

  function cleanHeadings() {
    var list;
    try { list = document.querySelectorAll(CLEAN_SEL); } catch (_) { return; }
    Array.prototype.slice.call(list).forEach(function (el) {
      if (el.id && SKIP_IDS[el.id]) return;
      if (el.dataset.obsRaw == null) el.dataset.obsRaw = el.textContent;
      var t = stripDeco(el.dataset.obsRaw);
      if (t) el.textContent = t;
    });
  }

  function restoreHeadings() {
    Array.prototype.slice.call(document.querySelectorAll('[data-obs-raw]')).forEach(function (el) {
      el.textContent = el.dataset.obsRaw;
      delete el.dataset.obsRaw;
    });
  }

  /* ═════════════════ FAOLLASHTIRISH / O'CHIRISH ══════════════════════ */

  function activate() {
    if (!built) {
      try { buildTopbar(); } catch (e) { console.warn('obsidian topbar', e); }
      try { buildHome(); } catch (e) { console.warn('obsidian home', e); }
      /* Qayta qurilgandan keyin keshlangan "signature"lar eskirgan bo'ladi —
         aks holda skeleton holatida qotib qolardi. */
      weekSig = '';
      actSig = null;
      built = true;
    }
    HTML.classList.add('obs-active');
    try { cleanHeadings(); } catch (e) { }
    syncAll();
  }

  function deactivate() {
    HTML.classList.remove('obs-active');
    if (!built) return;
    Array.prototype.slice.call(document.querySelectorAll('.obs-node')).forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
    try { restoreHeadings(); } catch (e) { }
    built = false;
  }

  function applyActive() {
    if (isOn()) activate();
    else deactivate();
  }

  /* ═════════════════ MAVJUD FUNKSIYALARNI O'RASH ═════════════════════ */
  /* app.js'dagi top-level `function` deklaratsiyalari `window` ustida
     yashaydi, shuning uchun ularni almashtirmasdan O'RAB olamiz: asl
     funksiya baribir chaqiriladi, biz faqat keyin sinxronlashtiramiz. */
  function wrap(name, after, always) {
    var orig = window[name];
    if (typeof orig !== 'function') return;
    window[name] = function () {
      var out = orig.apply(this, arguments);
      var run = function () { if (always || isOn()) { try { after(); } catch (e) { } } };
      if (out && typeof out.then === 'function') { try { out.then(run, run); } catch (e) { run(); } }
      else run();
      return out;
    };
  }

  wrap('renderHero', function () { syncMetrics(); syncAi(); });
  wrap('renderPlans', function () { syncAi(); syncActivity(); syncWeek(); });
  wrap('loadSnapshot', function () { syncMetrics(); syncAi(); });
  wrap('switchPage', function () { syncTopbar(); syncAll(); });
  wrap('applyMode', function () { syncTopbar(); });
  /* Tema almashsa (Profil → 🎨 Tema) — darhol yoqamiz/o'chiramiz.
     `always = true`: boshqa temaga o'tganda ham chaqirilishi SHART, aks holda
     teardown (node'larni olib tashlash, sarlavhalarni tiklash) ishlamaydi. */
  wrap('renderThemes', function () { applyActive(); }, true);
  window.addEventListener('obsidian:refresh', syncAll);

  /* Boshlanishi: app.js DOMContentLoaded ichida data-theme ni qo'yadi.
     Bizning `renderThemes` wrapper'i shu paytda applyActive() ni chaqiradi,
     ammo index.html'dagi erta (inline) skript allaqachon data-theme ni
     qo'ygan bo'lishi mumkin — shuning uchun ikki tomonlama kafolat. */
  function boot() {
    applyActive();
    /* Ma'lumot keyin keladi — bir necha marta yumshoq sinxron */
    setTimeout(syncAll, 400);
    setTimeout(syncAll, 1400);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  /* Tashqi dunyo uchun kichik API (debug / kelajakdagi kengaytmalar) */
  window.IZObsidian = { key: KEY, sync: syncAll, apply: applyActive };
})();
