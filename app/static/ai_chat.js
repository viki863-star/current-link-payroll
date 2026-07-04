(function() {
  var TOGGLE, PANEL, MSGS, INPUT, SEND, TYPING, CLEAR, CLOSE, LANG_EN, LANG_UR;
  var HISTORY = [];
  var lang = 'en';
  var voiceEntryActive = false;

  var TEXTS = {
    en: {
      welcome: 'Hi! I\'m your ERP assistant. Ask me about your data, or use the quick actions below.',
      placeholder: 'Ask me anything about your ERP data...',
      placeholder2: 'Speak or type here...',
      tripsheetBtn: '📋 Tripsheet Entry',
      tripsheetStart: '📋 Tripsheet Entry! I will ask questions, you can speak or type.',
      noCustomer: 'Please open a customer profile page first, then start Tripsheet Entry.',
      fieldDate: '📅 What is the date?',
      fieldTimeIn: '⏰ What is the Time In?',
      fieldTimeOut: '⏰ What is the Time Out?',
      fieldMeter: '📊 What is the meter reading?',
      fieldTrips: '🔄 How many trips?',
      fieldGln: '⛽ What is the Tanker GLN?',
      fieldReg: '🚛 What is the tanker registration number?',
      saving: '⏳ Saving data...',
      saved: '✅ Saved! Click',
      saved2: 'again for another entry.',
      error: 'Error',
      fail: 'Customer ID not found.',
      skipped: '(skipped)',
      listenHint: ' (speak or type)',
    },
    ur: {
      welcome: 'ہیلو! میں ERP اسسٹنٹ ہوں۔ ڈیٹا کے بارے میں پوچھیں، یا نیچے دیے گئے بٹن استعمال کریں۔',
      placeholder: 'ERP ڈیٹا کے بارے میں پوچھیں...',
      placeholder2: 'بولیں یا یہاں لکھیں...',
      tripsheetBtn: '📋 ٹرپ شیٹ انٹری',
      tripsheetStart: '📋 ٹرپ شیٹ انٹری! میں سوال پوچھوں گا، آپ بول سکتے ہیں یا ٹائپ کر سکتے ہیں۔',
      noCustomer: 'پہلے کسی کسٹمر کا پروفائل کھولیں، پھر ٹرپ شیٹ انٹری شروع کریں۔',
      fieldDate: '📅 تاریخ کیا ہے؟',
      fieldTimeIn: '⏰ ٹائم ان کیا ہے؟',
      fieldTimeOut: '⏰ ٹائم آؤٹ کیا ہے؟',
      fieldMeter: '📊 میٹر ریڈنگ کتنی ہے؟',
      fieldTrips: '🔄 کتنے ٹرپس ہیں؟',
      fieldGln: '⛽ ٹینکر GLN کیا ہے؟',
      fieldReg: '🚛 ٹینکر رجسٹریشن نمبر کیا ہے؟',
      saving: '⏳ ڈیٹا محفوظ ہو رہا ہے...',
      saved: '✅ محفوظ ہو گیا! دوبارہ انٹری کے لیے',
      saved2: 'دوبارہ دبائیں۔',
      error: 'خرابی',
      fail: 'کسٹمر ID نہیں ملی۔',
      skipped: '(چھوڑ دیا)',
      listenHint: ' (بولیں یا ٹائپ کریں)',
    }
  };

  function t(key) { return TEXTS[lang][key] || TEXTS.en[key]; }

  function init() {
    TOGGLE = document.getElementById('aiChatToggle');
    PANEL = document.getElementById('aiChatPanel');
    MSGS = document.getElementById('aiChatMessages');
    INPUT = document.getElementById('aiChatInput');
    SEND = document.getElementById('aiChatSend');
    TYPING = document.getElementById('aiChatTyping');
    CLEAR = document.getElementById('aiChatClear');
    CLOSE = document.getElementById('aiChatClose');
    LANG_EN = document.getElementById('aiLangEn');
    LANG_UR = document.getElementById('aiLangUr');
    if (!TOGGLE || !PANEL) return;

    lang = localStorage.getItem('aiChatLang') || 'en';
    applyLang();

    TOGGLE.addEventListener('click', togglePanel);
    SEND.addEventListener('click', sendMessage);
    CLEAR.addEventListener('click', clearChat);
    CLOSE.addEventListener('click', closeChat);
    if (LANG_EN) LANG_EN.addEventListener('click', function(){ setLang('en'); });
    if (LANG_UR) LANG_UR.addEventListener('click', function(){ setLang('ur'); });

    INPUT.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    INPUT.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
    });
    updateWelcome();
    showQuickActions();
  }

  function setLang(l) {
    lang = l;
    localStorage.setItem('aiChatLang', l);
    applyLang();
    updateWelcome();
    if (LANG_EN) LANG_EN.classList.toggle('is-active', l === 'en');
    if (LANG_UR) LANG_UR.classList.toggle('is-active', l === 'ur');
  }

  function applyLang() {
    INPUT.placeholder = t('placeholder');
  }

  function updateWelcome() {
    var welcome = MSGS.querySelector('.ai-chat-msg.assistant');
    if (welcome) {
      welcome.innerHTML = '<div>' + t('welcome') + '</div>';
    }
    var actionBtn = document.querySelector('#aiQuickActions button');
    if (actionBtn) actionBtn.textContent = t('tripsheetBtn');
  }

  function showQuickActions() {
    var welcomeMsg = MSGS.querySelector('.ai-chat-msg.assistant');
    if (!welcomeMsg) return;
    var actions = document.getElementById('aiQuickActions');
    if (actions) return;
    var div = document.createElement('div');
    div.id = 'aiQuickActions';
    div.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:0 12px 8px;';
    var btn = document.createElement('button');
    btn.textContent = t('tripsheetBtn');
    btn.style.cssText = 'background:var(--primary);color:#fff;border:none;border-radius:16px;padding:5px 14px;font-size:0.78rem;cursor:pointer;white-space:nowrap;';
    btn.addEventListener('click', function(e) { e.stopPropagation(); startTripsheetEntry(); });
    div.appendChild(btn);
    welcomeMsg.parentNode.insertBefore(div, welcomeMsg.nextSibling);
  }

  function getCustomerId() {
    var m = window.location.pathname.match(/\/customer\/(\d+)/);
    return m ? parseInt(m[1]) : null;
  }

  function addMessage(role, text) {
    var div = document.createElement('div');
    div.className = 'ai-chat-msg ' + role;
    var p = document.createElement('div');
    p.textContent = text;
    div.appendChild(p);
    MSGS.appendChild(div);
    MSGS.scrollTop = MSGS.scrollHeight;
  }

  function showTyping() { TYPING.style.display = 'flex'; MSGS.scrollTop = MSGS.scrollHeight; }
  function hideTyping() { TYPING.style.display = 'none'; }

  // ─── Tripsheet Entry (Voice + Text) ───
  function startTripsheetEntry() {
    if (voiceEntryActive) return;
    var cid = getCustomerId();
    if (!cid) {
      addMessage('assistant', t('noCustomer'));
      return;
    }
    voiceEntryActive = true;
    addMessage('assistant', t('tripsheetStart'));

    var fields = [
      { id: 'entry_date', label: 'fieldDate', parse: parseDate },
      { id: 'time_in', label: 'fieldTimeIn', parse: parseTime },
      { id: 'time_out', label: 'fieldTimeOut', parse: parseTime },
      { id: 'total_reading', label: 'fieldMeter', parse: parseNumber },
      { id: 'trips', label: 'fieldTrips', parse: parseNumber },
      { id: 'tanker_gln', label: 'fieldGln', parse: parseGln },
      { id: 'tanker_reg', label: 'fieldReg', parse: parseText },
    ];
    var entryData = {};
    var idx = 0;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    INPUT.placeholder = t('placeholder2');
    INPUT.focus();

    function askNext() {
      if (idx >= fields.length) {
        finishEntry();
        return;
      }
      var f = fields[idx];
      var answered = false;
      addMessage('assistant', t(f.label) + t('listenHint'));
      INPUT.focus();

      var textHandler = function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (answered) return;
          answered = true;
          INPUT.removeEventListener('keydown', textHandler);
          var text = INPUT.value.trim();
          INPUT.value = '';
          stopListening();
          if (text) {
            addMessage('user', text);
            entryData[f.id] = f.parse ? f.parse(text) : text;
          } else {
            addMessage('user', t('skipped'));
          }
          idx++;
          setTimeout(askNext, 200);
        }
      };
      INPUT.addEventListener('keydown', textHandler);

      var recognition = null;
      function startListening() {
        if (!SpeechRecognition) return;
        try {
          recognition = new SpeechRecognition();
          recognition.lang = lang === 'ur' ? 'ur-PK' : 'en-US';
          recognition.continuous = false;
          recognition.interimResults = false;
          recognition.onresult = function(e) {
            if (answered) return;
            answered = true;
            INPUT.removeEventListener('keydown', textHandler);
            stopListening();
            var text = e.results[0][0].transcript.trim();
            addMessage('user', '🎤 ' + text);
            entryData[f.id] = f.parse ? f.parse(text) : text;
            idx++;
            setTimeout(askNext, 200);
          };
          recognition.onerror = function() {};
          recognition.start();
        } catch(e) {}
      }
      function stopListening() {
        if (recognition) { try { recognition.stop(); } catch(e) {} recognition = null; }
      }
      startListening();
    }

    function finishEntry() {
      var cid = getCustomerId();
      if (!cid) {
        addMessage('assistant', '❌ ' + t('fail'));
        resetVoiceMode();
        return;
      }
      addMessage('assistant', t('saving'));
      showTyping();

      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
      var payload = { customer_id: cid };
      payload = { customer_id: cid, lang: lang };
      fields.forEach(function(f) {
        payload[f.id] = entryData[f.id] || '';
      });

      fetch('/ai/tripsheet_save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify(payload)
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        hideTyping();
        if (data.error) {
          addMessage('assistant', '❌ ' + t('error') + ': ' + data.error);
        } else {
          addMessage('assistant', t('saved') + ' "📋 ' + t('tripsheetBtn') + '" ' + t('saved2'));
        }
        resetVoiceMode();
      })
      .catch(function(err) {
        hideTyping();
        addMessage('assistant', '❌ ' + t('error') + ': ' + err.message);
        resetVoiceMode();
      });
    }

    function resetVoiceMode() {
      voiceEntryActive = false;
      INPUT.placeholder = t('placeholder');
      INPUT.focus();
    }

    idx = 0;
    entryData = {};
    setTimeout(askNext, 500);
  }

  function parseDate(s) {
    if (!s) return '';
    var d = new Date(s);
    if (!isNaN(d)) return d.toISOString().slice(0,10);
    var m = s.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/);
    if (m) { var day=m[1], mon=m[2], yr=m[3]; if(yr.length===2)yr='20'+yr; return yr+'-'+mon.padStart(2,'0')+'-'+day.padStart(2,'0'); }
    return s;
  }
  function parseTime(s) {
    if (!s) return '';
    var tm = s.match(/(\d{1,2})\s*[:\s]\s*(\d{2})\s*(am|pm|AM|PM)?/i);
    if (tm) { var h=parseInt(tm[1]),m=tm[2],ap=(tm[3]||'').toLowerCase(); if(ap==='pm'&&h<12)h+=12; if(ap==='am'&&h===12)h=0; return String(h).padStart(2,'0')+':'+m; }
    if (/^\d{1,2}:\d{2}$/.test(s)) return s;
    return s;
  }
  function parseNumber(s) {
    var n = parseFloat(s); return isNaN(n) ? 0 : n;
  }
  function parseGln(s) {
    if (!s) return '';
    var up = s.toUpperCase();
    return up.includes('GLN') ? up : up + ' GLN';
  }
  function parseText(s) { return (s||'').toUpperCase(); }

  // ─── Chat send ───
  function clearChat() {
    MSGS.innerHTML = '';
    HISTORY = [];
    var welcome = document.createElement('div');
    welcome.className = 'ai-chat-msg assistant';
    welcome.innerHTML = '<div>' + t('welcome') + '</div>';
    MSGS.appendChild(welcome);
    INPUT.value = '';
    INPUT.focus();
    showQuickActions();
  }

  function closeChat() {
    PANEL.classList.remove('is-open');
    TOGGLE.classList.remove('is-open');
  }

  function togglePanel() {
    var open = PANEL.classList.toggle('is-open');
    TOGGLE.classList.toggle('is-open', open);
    if (open) {
      MSGS.scrollTop = MSGS.scrollHeight;
      INPUT.focus();
      showQuickActions();
    }
  }

  function sendMessage() {
    var text = INPUT.value.trim();
    if (!text) return;
    INPUT.value = '';
    addMessage('user', text);
    SEND.disabled = true;
    showTyping();
    HISTORY.push({role: 'user', content: text});

    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    fetch('/ai/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
      body: JSON.stringify({message: text, history: HISTORY, lang: lang})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      hideTyping();
      if (data.error) {
        addMessage('assistant', t('error') + ': ' + data.error);
        return;
      }
      addMessage('assistant', data.reply);
      HISTORY.push({role: 'assistant', content: data.reply});
    })
    .catch(function(err) {
      hideTyping();
      addMessage('assistant', t('error') + ': ' + err.message);
    })
    .finally(function() {
      SEND.disabled = false;
      INPUT.focus();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
