/* Tabula online: draws the live creature from the server's frames and keeps the cards up to date.
   Frames arrive ten times a second (server-sent events); the picture runs a little behind them and
   blends between two frames, so the motion stays smooth at any screen rate. */
(function () {
  'use strict';

  var params = new URLSearchParams(location.search);
  var API = params.get('api') || 'api/';
  var DELAY = 160;               // ms the picture runs behind the newest frame
  var STATE_EVERY = 20000;       // ms between biography refreshes

  var $ = function (id) { return document.getElementById(id); };
  var canvas = $('world');
  var ctx = canvas.getContext('2d');
  var lang = document.documentElement.lang;

  // ---------- words ----------
  var T = {
    en: {
      stages: { babbling: 'babbling', flailing: 'flailing', crawling: 'crawling', walking: 'walking', running: 'running' },
      bodies: { strider: 'a strider', quadruped: 'a quadruped', hopper: 'a hopper' },
      day: 'day', night: 'night', dawn: 'dawn', dusk: 'dusk',
      thrown: 'Thrown! It can smell it now.', wait: 'You can throw again in {s} s.',
      full: 'There is plenty of food lying around already. Try a bit later.',
      offline: 'The creature is asleep right now (the server is restarting). It will be back in a moment.',
      steps: '{n} moments', d: 'd'
    },
    ru: {
      stages: { babbling: 'лепет', flailing: 'барахтается', crawling: 'ползает', walking: 'ходит', running: 'бегает' },
      bodies: { strider: 'ходок', quadruped: 'четвероногое', hopper: 'прыгун' },
      day: 'день', night: 'ночь', dawn: 'рассвет', dusk: 'сумерки',
      thrown: 'Брошено! Теперь оно чувствует запах.', wait: 'Снова бросить можно через {s} с.',
      full: 'Вокруг и так много еды. Попробуйте чуть позже.',
      offline: 'Существо сейчас спит (сервер перезапускается). Скоро вернётся.',
      steps: '{n} моментов', d: 'д'
    }
  };
  var RU_MILESTONES = [
    [/^Born as (.+), a (\w+)$/, function (m) { return 'Родилось: ' + m[1] + ', ' + (T.ru.bodies[m[2]] || m[2]); }],
    [/^Woke up$/, 'Проснулось'],
    [/^Wandered (\d+) m from its birthplace$/, function (m) { return 'Ушло на ' + m[1] + ' м от места рождения'; }],
    [/^Found food for the first time$/, 'Впервые нашло еду'],
    [/^Ate (\d+) meals$/, function (m) { return 'Съело ' + m[1] + ' раз'; }],
    [/^Started (\w+)$/, function (m) { return 'Начало: ' + (T.ru.stages[m[1]] || m[1]); }],
    [/^Lived for an hour$/, 'Прожило час'],
    [/^Lived for a day$/, 'Прожило сутки'],
    [/^Lived for a week$/, 'Прожило неделю'],
    [/^Ran out of energy for the first time$/, 'Впервые выбилось из сил'],
    [/^Ate food from a stranger.*$/, 'Съело еду от незнакомца'],
    [/^Got stuck in a pit and was lifted out$/, 'Застряло в яме, его вытащили']
  ];
  function milestoneText(text) {
    if (lang !== 'ru') return text;
    for (var i = 0; i < RU_MILESTONES.length; i++) {
      var m = text.match(RU_MILESTONES[i][0]);
      if (m) return typeof RU_MILESTONES[i][1] === 'function' ? RU_MILESTONES[i][1](m) : RU_MILESTONES[i][1];
    }
    return text;
  }
  var STAGE_COLORS = { babbling: '#a0a0b4', flailing: '#ec7864', crawling: '#f0be5a', walking: '#8cdc78', running: '#6ec8ff' };

  function fmtAge(s) {
    s = Math.floor(s);
    var d = Math.floor(s / 86400); s %= 86400;
    var h = Math.floor(s / 3600); s %= 3600;
    var m = Math.floor(s / 60); s %= 60;
    var hms = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return d ? d + ' ' + T[lang].d + ' ' + hms : hms;
  }
  function num(n, digits) {
    return Number(n).toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US',
      { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
  }

  // ---------- data from the server ----------
  var state = null;      // /state: body plan, biography
  var frames = [];       // [{t: arrival ms, f: frame}]
  var terrain = {};      // 40 m blocks of ground points, by block index
  var BLOCK = 40;

  function loadState() {
    return fetch(API + 'state', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (s) {
      state = s;
      if (!frames.length && s.frame && s.frame.parts) frames.push({ t: performance.now(), f: s.frame });
      renderCards();
      $('asleep').hidden = true;
    }).catch(function () { showOffline(); });
  }

  function showOffline() {
    $('asleep').hidden = false;
    $('asleep').querySelector('p').textContent = T[lang].offline;
  }

  function block(k) {
    if (terrain[k] !== undefined) return terrain[k];
    terrain[k] = null;   // loading
    fetch(API + 'terrain?x0=' + (k * BLOCK) + '&x1=' + ((k + 1) * BLOCK)).then(function (r) {
      return r.ok ? r.json() : Promise.reject(r.status);
    }).then(function (pts) { terrain[k] = pts; }).catch(function () { delete terrain[k]; });
    return null;
  }

  var source = null;
  function connect() {
    source = new EventSource(API + 'stream');
    source.onmessage = function (e) {
      var f = JSON.parse(e.data);
      frames.push({ t: performance.now(), f: f });
      if (frames.length > 30) frames.splice(0, frames.length - 30);
      $('asleep').hidden = true;
    };
    source.onerror = function () {
      if (source.readyState === EventSource.CLOSED) setTimeout(connect, 5000);
      if (!frames.length || performance.now() - frames[frames.length - 1].t > 5000) showOffline();
    };
  }

  // ---------- blending two frames ----------
  function lerp(a, b, t) { return a + (b - a) * t; }
  function lerpAngle(a, b, t) {
    var d = b - a;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return a + d * t;
  }
  function current() {
    if (!frames.length) return null;
    var at = performance.now() - DELAY;
    var i = frames.length - 1;
    while (i > 0 && frames[i - 1].t > at) i--;
    var b = frames[i], a = frames[i - 1];
    if (!a || at >= b.t) return b.f;
    var t = Math.max(0, Math.min(1, (at - a.t) / (b.t - a.t)));
    var parts = b.f.parts.map(function (p, j) {
      var q = a.f.parts[j] || p;
      return [lerp(q[0], p[0], t), lerp(q[1], p[1], t), lerpAngle(q[2], p[2], t)];
    });
    return Object.assign({}, b.f, { parts: parts, age: lerp(a.f.age, b.f.age, t), light: lerp(a.f.light, b.f.light, t) });
  }

  // ---------- drawing ----------
  var cam = null;
  var W = 0, H = 0, dpr = 1, ppm = 90;
  var stars = [];
  for (var s = 0; s < 70; s++) stars.push([Math.random(), Math.random() * 0.6, 0.5 + Math.random() * 1.2]);

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    var r = canvas.getBoundingClientRect();
    W = Math.round(r.width * dpr);
    H = Math.round(r.height * dpr);
    canvas.width = W;
    canvas.height = H;
    ppm = H / 5.2;
  }
  window.addEventListener('resize', resize);

  function sx(x) { return W / 2 + (x - cam.x) * ppm; }
  function sy(y) { return H * 0.62 - (y - cam.y) * ppm; }

  function mix(c1, c2, t) {
    return 'rgb(' + c1.map(function (v, i) { return Math.round(v + (c2[i] - v) * t); }).join(',') + ')';
  }

  function drawBox(x, y, angle, w, h, fill, stroke) {
    ctx.save();
    ctx.translate(sx(x), sy(y));
    ctx.rotate(-angle);
    ctx.fillStyle = fill;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(-w * ppm / 2, -h * ppm / 2, w * ppm, h * ppm, 2 * dpr);
    else ctx.rect(-w * ppm / 2, -h * ppm / 2, w * ppm, h * ppm);
    ctx.fill();
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 2 * dpr; ctx.stroke(); }
    ctx.restore();
  }

  function local(p, lx, ly) {   // a point on a body, in world coordinates
    var c = Math.cos(p[2]), s = Math.sin(p[2]);
    return [p[0] + lx * c - ly * s, p[1] + lx * s + ly * c];
  }

  function draw(now) {
    requestAnimationFrame(draw);
    var f = current();
    if (!f || !state || !W) return;
    var torso = f.parts[0];
    if (!cam) cam = { x: torso[0], y: torso[1] };
    cam.x += (torso[0] - cam.x) * 0.08;
    cam.y += (torso[1] - cam.y) * 0.05;

    // sky
    var light = f.light;
    var g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, mix([6, 8, 18], [24, 30, 48], light));
    g.addColorStop(1, mix([16, 20, 36], [58, 66, 92], light));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    if (light < 0.9) {
      ctx.fillStyle = 'rgba(255,255,240,' + (0.8 * (1 - light)) + ')';
      stars.forEach(function (st) {
        var x = ((st[0] * W - cam.x * ppm * 0.05) % W + W) % W;
        ctx.fillRect(x, st[1] * H, st[2] * dpr, st[2] * dpr);
      });
    }

    var half = W / 2 / ppm + 2;
    var x0 = cam.x - half, x1 = cam.x + half;

    // distance marks and the birthplace flag
    ctx.font = (11 * dpr) + 'px "IBM Plex Mono", monospace';
    for (var m = Math.ceil(x0 / 5) * 5; m <= x1; m += 5) {
      ctx.strokeStyle = 'rgba(255,255,255,.06)';
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.moveTo(sx(m), 0);
      ctx.lineTo(sx(m), H);
      ctx.stroke();
      ctx.fillStyle = 'rgba(200,205,220,.45)';
      ctx.fillText(m + ' m', sx(m) + 4 * dpr, H - 10 * dpr);
    }

    // ground
    var pts = [];
    for (var k = Math.floor(x0 / BLOCK); k <= Math.floor(x1 / BLOCK); k++) {
      var b = block(k);
      if (b) pts = pts.concat(b);
    }
    pts = pts.filter(function (p) { return p[0] >= x0 - 1 && p[0] <= x1 + 1; });
    if (pts.length > 1) {
      ctx.beginPath();
      ctx.moveTo(sx(pts[0][0]), sy(pts[0][1]));
      pts.forEach(function (p) { ctx.lineTo(sx(p[0]), sy(p[1])); });
      ctx.lineTo(sx(pts[pts.length - 1][0]), H);
      ctx.lineTo(sx(pts[0][0]), H);
      ctx.closePath();
      ctx.fillStyle = mix([22, 26, 22], [46, 52, 44], light);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(sx(pts[0][0]), sy(pts[0][1]));
      pts.forEach(function (p) { ctx.lineTo(sx(p[0]), sy(p[1])); });
      ctx.strokeStyle = mix([70, 84, 60], [120, 140, 96], light);
      ctx.lineWidth = 3 * dpr;
      ctx.stroke();
      if (x0 < 0 && x1 > 0) {
        var gy = sy(groundAt(pts, 0));
        ctx.strokeStyle = '#ffc45c';
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath();
        ctx.moveTo(sx(0), gy);
        ctx.lineTo(sx(0), gy - 60 * dpr);
        ctx.stroke();
        ctx.fillStyle = '#ffc45c';
        ctx.beginPath();
        ctx.moveTo(sx(0), gy - 60 * dpr);
        ctx.lineTo(sx(0) + 20 * dpr, gy - 52 * dpr);
        ctx.lineTo(sx(0), gy - 44 * dpr);
        ctx.fill();
      }
    }

    // food
    var pulse = 0.5 + 0.5 * Math.sin(now / 250);
    f.foods.forEach(function (fd) {
      var col = fd[2] ? '#ff96d2' : '#78e68c';
      var px = sx(fd[0]), py = sy(fd[1]);
      if (px < -20 || px > W + 20) return;
      ctx.fillStyle = fd[2] ? 'rgba(255,150,210,.28)' : 'rgba(120,230,140,.25)';
      ctx.beginPath(); ctx.arc(px, py, (15 + 6 * pulse) * dpr, 0, 7); ctx.fill();
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(px, py, 8 * dpr, 0, 7); ctx.fill();
    });
    var tx = sx(f.target[0]);
    if (tx < 0 || tx > W) {
      var left = tx < 0, ax = left ? 18 * dpr : W - 18 * dpr, ay = Math.max(40 * dpr, Math.min(H - 40 * dpr, sy(f.target[1])));
      var isGift = f.foods.some(function (fd) { return fd[2] && fd[0] === f.target[0]; });
      ctx.fillStyle = isGift ? '#ff96d2' : '#78e68c';
      ctx.beginPath();
      ctx.moveTo(ax + (left ? -10 : 10) * dpr, ay);
      ctx.lineTo(ax + (left ? 8 : -8) * dpr, ay - 10 * dpr);
      ctx.lineTo(ax + (left ? 8 : -8) * dpr, ay + 10 * dpr);
      ctx.fill();
      var label = num(Math.abs(f.target[0] - torso[0]), 1) + ' m';
      ctx.fillText(label, left ? ax - 4 * dpr : ax - ctx.measureText(label).width + 4 * dpr, ay + 24 * dpr);
    }

    drawCreature(f);
    updateLive(f);
  }

  function groundAt(pts, x) {
    for (var i = 1; i < pts.length; i++) {
      if (pts[i][0] >= x) {
        var a = pts[i - 1], b = pts[i];
        return a[1] + (b[1] - a[1]) * (x - a[0]) / ((b[0] - a[0]) || 1);
      }
    }
    return 0;
  }

  function drawCreature(f) {
    var body = state.body, legs = body.legs, n = legs.length;
    var torso = f.parts[0];
    function leg(i, behind) {
      var thigh = f.parts[1 + i], shin = f.parts[1 + n + i];
      var col = behind ? '#965e3c' : '#c4844a';
      drawBox(thigh[0], thigh[1], thigh[2], body.limb, body.thigh, col);
      drawBox(shin[0], shin[1], shin[2], body.limb * 0.8, body.shin, col);
      var foot = local(shin, 0, -body.shin / 2);
      var on = f.contacts[i];
      ctx.fillStyle = on ? (behind ? '#b4a064' : '#fae68c') : (behind ? '#5a3e28' : '#785436');
      ctx.beginPath();
      ctx.arc(sx(foot[0]), sy(foot[1]), Math.max(3 * dpr, body.foot * ppm), 0, 7);
      ctx.fill();
    }
    var behind = legs.map(function (l, i) { return l.far || (n === 2 && i === 0); });
    for (var i = 0; i < n; i++) if (behind[i]) leg(i, true);
    drawBox(torso[0], torso[1], torso[2], body.torso[0], body.torso[1], '#e8b062',
      f.contacts[n] ? '#ec6460' : '#965e3c');
    for (i = 0; i < n; i++) if (!behind[i]) leg(i, false);

    // the eye looks at the food it is after; it droops when exhausted
    var eye = local(torso, body.eye, 0.03);
    var ex = sx(eye[0]), ey = sy(eye[1]), r = 9 * dpr;
    ctx.fillStyle = '#fafaf5';
    ctx.beginPath(); ctx.arc(ex, ey, r, 0, 7); ctx.fill();
    var dx = f.target[0] - eye[0], dy = f.target[1] - eye[1], dn = Math.hypot(dx, dy) || 1;
    ctx.fillStyle = '#1e1e28';
    ctx.beginPath(); ctx.arc(ex + dx / dn * 4 * dpr, ey - dy / dn * 4 * dpr, 4 * dpr, 0, 7); ctx.fill();
    if (f.energy <= 0) {
      ctx.fillStyle = '#e8b062';
      ctx.fillRect(ex - r, ey - r, 2 * r, r + dpr);
    }
  }

  // ---------- the text around the picture ----------
  var lastStage = null;
  function updateLive(f) {
    $('age').textContent = fmtAge(f.age);
    if (f.stage !== lastStage) {
      lastStage = f.stage;
      var chip = $('stage-chip');
      chip.textContent = T[lang].stages[f.stage] || f.stage;
      chip.style.color = STAGE_COLORS[f.stage] || '#fff';
      renderStages();
    }
    var phase = f.light >= 0.999 ? 'day' : f.light <= 0.001 ? 'night' : (f.age % 720) / 720 < 0.3 ? 'dawn' : 'dusk';
    $('light').textContent = T[lang][phase];
    $('energy').textContent = Math.round(f.energy * 100) + '%';
    var bar = $('energy-bar');
    bar.style.width = (f.energy * 100) + '%';
    bar.style.background = f.energy > 0.25 ? 'var(--good)' : 'var(--bad)';
    $('speed').textContent = num(f.speed, 2) + (lang === 'ru' ? ' м/с' : ' m/s');
    $('meals').textContent = num(f.meals);
  }

  function renderStages() {
    if (!state) return;
    var list = $('stages');
    list.innerHTML = '';
    state.stages.forEach(function (st) {
      var li = document.createElement('li');
      li.textContent = T[lang].stages[st] || st;
      var reached = st === 'babbling' || state.achieved.indexOf('stage_' + st) >= 0 || st === lastStage;
      if (reached) { li.className = 'reached'; li.style.setProperty('--stage-color', STAGE_COLORS[st]); }
      if (st === (lastStage || state.stage)) li.className += ' now';
      list.appendChild(li);
    });
  }

  function renderCards() {
    var s = state;
    $('name').textContent = s.name;
    $('kind').textContent = T[lang].bodies[s.body.key] || s.body.title;
    document.title = s.name + ' — Tabula';
    $('gifts').textContent = num(s.gifts);
    $('walked').textContent = num(s.walked) + (lang === 'ru' ? ' м' : ' m');
    $('farthest').textContent = num(s.farthest, 1) + (lang === 'ru' ? ' м' : ' m');
    $('steps').textContent = T[lang].steps.replace('{n}', num(s.steps));
    renderStages();

    var list = $('milestones');
    list.innerHTML = '';
    s.milestones.slice().reverse().forEach(function (m) {
      var li = document.createElement('li');
      var t = document.createElement('time');
      t.textContent = fmtAge(m[0]);
      var span = document.createElement('span');
      span.textContent = milestoneText(m[1]);
      li.appendChild(t);
      li.appendChild(span);
      list.appendChild(li);
    });

    var svg = $('chart');
    var h = s.history;
    if (h.length < 2) { svg.innerHTML = ''; return; }
    var hi = Math.max(0.3, Math.max.apply(null, h.map(function (r) { return r.speed; })));
    var line = h.map(function (r, i) {
      return (i / (h.length - 1) * 400).toFixed(1) + ',' + (116 - r.speed / hi * 104).toFixed(1);
    });
    svg.innerHTML = '<polygon fill="rgba(140,220,120,.18)" points="0,120 ' + line.join(' ') + ' 400,120"/>' +
      '<polyline fill="none" stroke="#8cdc78" stroke-width="2" vector-effect="non-scaling-stroke" points="' +
      line.join(' ') + '"/>';
  }

  // ---------- feeding ----------
  var cooldownUntil = 0;
  function feedStatus(text) { $('feed-status').textContent = text; }
  function tickCooldown() {
    var left = Math.ceil((cooldownUntil - Date.now()) / 1000);
    var buttons = document.querySelectorAll('.feed .btn');
    buttons.forEach(function (b) { b.disabled = left > 0; });
    if (left > 0) {
      feedStatus(T[lang].wait.replace('{s}', left));
      setTimeout(tickCooldown, 1000);
    }
  }
  document.querySelectorAll('.feed .btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (Date.now() < cooldownUntil) return;
      fetch(API + 'feed', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ side: Number(btn.dataset.side) }) })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (res.ok) {
            cooldownUntil = Date.now() + res.wait * 1000;
            feedStatus(T[lang].thrown);
            setTimeout(tickCooldown, 2500);
            loadState();
          } else if (res.reason === 'cooldown') {
            cooldownUntil = Date.now() + res.wait * 1000;
            tickCooldown();
          } else {
            feedStatus(T[lang].full);
          }
        })
        .catch(function () { feedStatus(T[lang].offline); });
    });
  });

  // ---------- language ----------
  $('lang').addEventListener('click', function () {
    lang = lang === 'ru' ? 'en' : 'ru';
    document.documentElement.lang = lang;
    try { localStorage.setItem('ks-lang-picked', lang); } catch (e) {}
    lastStage = null;
    if (state) renderCards();
    if (Date.now() < cooldownUntil) tickCooldown();
  });

  // ---------- go ----------
  resize();
  loadState().then(function () { connect(); });
  setInterval(loadState, STATE_EVERY);
  requestAnimationFrame(draw);
})();
