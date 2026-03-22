/* KI Status Panels für scanservjs — zeigt letzten Scan-Titel + Tags */
(function () {
  'use strict';

  var STATUS_URL = '/ki-status.json';
  var POLL_MS    = 30000;

  function fmt(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
        + ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ''; }
  }

  function createPanels() {
    if (document.getElementById('ki-panels')) return;
    var wrap = document.createElement('div');
    wrap.id = 'ki-panels';
    wrap.innerHTML =
      '<div class="ki-panel" id="ki-p1">' +
        '<div class="ki-ph"><span class="ki-dot"></span>Bezug / Dateiname</div>' +
        '<div class="ki-pc" id="ki-title">–</div>' +
        '<div class="ki-pt" id="ki-time"></div>' +
      '</div>' +
      '<div class="ki-panel" id="ki-p2">' +
        '<div class="ki-ph"><span class="ki-dot"></span>Tags</div>' +
        '<div class="ki-tags" id="ki-tags"><span class="ki-tag">–</span></div>' +
      '</div>' +
      '<div class="ki-panel" id="ki-p3">' +
        '<div class="ki-ph"><span class="ki-dot"></span>Kategorie / Konfidenz</div>' +
        '<div class="ki-pmeta" id="ki-meta">–</div>' +
      '</div>';
    document.body.appendChild(wrap);
  }

  function update(data) {
    var t  = document.getElementById('ki-title');
    var tm = document.getElementById('ki-time');
    var tg = document.getElementById('ki-tags');
    var tm2 = document.getElementById('ki-meta');
    if (!t) return;
    if (data && data.last_doc) {
      var doc = data.last_doc;
      t.textContent  = doc.title || '–';
      if (tm) tm.textContent = fmt(data.updated);
      if (tg) {
        var tags = doc.tags || [];
        tg.innerHTML = tags.length
          ? tags.map(function(s){ return '<span class="ki-tag">'+s+'</span>'; }).join('')
          : '<span class="ki-tag">–</span>';
      }
      if (tm2) {
        var cat = doc.kategorie || '–';
        var conf = doc.konfidenz || 0;
        var confPercent = Math.round(conf * 100);
        tm2.textContent = cat + ' (' + confPercent + '%)';
      }
    }
  }

  function poll() {
    fetch(STATUS_URL + '?_=' + Date.now())
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){ if (d) update(d); })
      .catch(function(){});
  }

  function init() {
    createPanels();
    poll();
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function(){ setTimeout(init, 600); });
  } else {
    setTimeout(init, 600);
  }
})();
