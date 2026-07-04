(function() {
  var TOGGLE, PANEL, MSGS, INPUT, SEND, TYPING, CLEAR, CLOSE, MIC, LISTENING, LISTEN_TEXT;
  var LANG_EN, LANG_UR;
  var HISTORY = [];
  var lang = 'en';
  var voiceEntryActive = false;
  var isRecording = false;
  var currentRecognition = null;
  var micResultCallback = null;

  // Tripsheet state (single handler approach)
  var tripsheet = null;

  var TEXTS = {
    en: {
      welcome: 'Hi! I\'m your ERP assistant. Ask me about your data, or tap <strong>Tripsheet Entry</strong> below.',
      placeholder: 'Ask me anything...',
      placeholder2: 'Speak or type here...',
      tripsheetBtn: '📋 Tripsheet Entry',
      tripsheetStart: '📋 Tripsheet Entry started! I will ask each question aloud.',
      noCustomer: 'Please open a customer profile page first, then start Tripsheet Entry.',
      fieldDate: 'What is the trip date?',
      fieldTimeIn: 'What is the Time In?',
      fieldTimeOut: 'What is the Time Out?',
      fieldMeter: 'How many meter reading?',
      fieldTrips: 'How many trips?',
      fieldGln: 'What is the Tanker GLN?',
      fieldReg: 'What is the tanker registration number?',
      saving: 'Saving data...',
      saved: 'Saved successfully! Tap',
      saved2: 'again for another entry.',
      error: 'Error',
      fail: 'Customer ID not found.',
      skipped: '(skipped)',
      listenHint: ' (press mic or type)',
      listening: 'Listening... speak now',
    },
    ur: {
      welcome: 'ہیلو! میں ERP اسسٹنٹ ہوں۔ ڈیٹا کے بارے میں پوچھیں، یا نیچے <strong>ٹرپ شیٹ انٹری</strong> دبائیں۔',
      placeholder: 'کچھ پوچھیں...',
      placeholder2: 'بولیں یا لکھیں...',
      tripsheetBtn: '📋 ٹرپ شیٹ انٹری',
      tripsheetStart: '📋 ٹرپ شیٹ انٹری شروع! ہر سوال میں اونچی آواز میں پوچھوں گا۔',
      noCustomer: 'پہلے کسی کسٹمر کا پروفائل کھولیں، پھر ٹرپ شیٹ انٹری شروع کریں۔',
      fieldDate: 'تاریخ کیا ہے؟',
      fieldTimeIn: 'ٹائم ان کیا ہے؟',
      fieldTimeOut: 'ٹائم آؤٹ کیا ہے؟',
      fieldMeter: 'میٹر ریڈنگ کتنی ہے؟',
      fieldTrips: 'کتنے ٹرپس ہیں؟',
      fieldGln: 'ٹینکر GLN کیا ہے؟',
      fieldReg: 'ٹینکر رجسٹریشن نمبر کیا ہے؟',
      saving: 'ڈیٹا محفوظ ہو رہا ہے...',
      saved: 'محفوظ ہو گیا! دوبارہ کے لیے',
      saved2: 'دوبارہ دبائیں۔',
      error: 'خرابی',
      fail: 'کسٹمر ID نہیں ملی۔',
      skipped: '(چھوڑ دیا)',
      listenHint: ' (مائک دبائیں یا لکھیں)',
      listening: 'سن رہا ہوں... بولیں',
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
    MIC = document.getElementById('aiChatMic');
    LISTENING = document.getElementById('aiChatListening');
    LISTEN_TEXT = document.getElementById('aiChatListeningText');
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

    setupMic();

    // SINGLE Enter handler for both normal chat and tripsheet
    INPUT.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (voiceEntryActive && tripsheet) {
          handleTripsheetAnswer();
        } else {
          sendMessage();
        }
      }
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
    if (welcome) welcome.innerHTML = '<div>' + t('welcome') + '</div>';
    var actionBtn = document.querySelector('#aiQuickActions button');
    if (actionBtn) actionBtn.textContent = t('tripsheetBtn');
  }

  function showQuickActions() {
    var welcomeMsg = MSGS.querySelector('.ai-chat-msg.assistant');
    if (!welcomeMsg) return;
    if (document.getElementById('aiQuickActions')) return;
    var div = document.createElement('div');
    div.id = 'aiQuickActions';
    div.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 10px;';
    var btn = document.createElement('button');
    btn.textContent = t('tripsheetBtn');
    btn.style.cssText = 'background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;border:none;border-radius:14px;padding:6px 16px;font-size:0.78rem;cursor:pointer;font-weight:500;';
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

  // ─── Text-to-Speech ───
  function speakText(text, cb) {
    if (!window.speechSynthesis) { if (cb) setTimeout(cb,100); return; }
    var u = new SpeechSynthesisUtterance(text);
    u.lang = lang === 'ur' ? 'ur-PK' : 'en-US';
    u.rate = 0.95; u.pitch = 1;
    u.onend = function() { if (cb) setTimeout(cb,200); };
    u.onerror = function() { if (cb) setTimeout(cb,200); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  // ─── Push-to-Talk Mic ───
  function setupMic() {
    if (!MIC) return;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { MIC.style.display = 'none'; return; }

    function onStart() {
      if (isRecording) return;
      isRecording = true;
      MIC.classList.add('is-recording');
      LISTENING.classList.add('is-active');
      if (LISTEN_TEXT) LISTEN_TEXT.textContent = t('listening');
      currentRecognition = new SpeechRecognition();
      currentRecognition.lang = lang === 'ur' ? 'ur-PK' : 'en-US';
      currentRecognition.continuous = true;
      currentRecognition.interimResults = false;
      currentRecognition.onresult = function(e) {
        var last = e.results[e.results.length - 1];
        if (last && last[0]) currentRecognition._latest = last[0].transcript.trim();
      };
      currentRecognition.onerror = function() { onEnd(); };
      try { currentRecognition.start(); } catch(e) { onEnd(); }
    }

    function onEnd() {
      if (!isRecording) return;
      isRecording = false;
      MIC.classList.remove('is-recording');
      LISTENING.classList.remove('is-active');
      var text = '';
      if (currentRecognition) {
        try { currentRecognition.stop(); } catch(e) {}
        text = currentRecognition._latest || '';
        currentRecognition = null;
      }
      if (!text) return;
      INPUT.value = text;
      if (micResultCallback) {
        var cb = micResultCallback;
        micResultCallback = null;
        setTimeout(function() { cb(text); }, 150);
      } else {
        // Normal mode: auto-submit
        setTimeout(function() { handleEnter(); }, 150);
      }
    }

    MIC.addEventListener('mousedown', function(e) { e.preventDefault(); onStart(); });
    MIC.addEventListener('mouseup', function(e) { e.preventDefault(); onEnd(); });
    MIC.addEventListener('mouseleave', function() { if (isRecording) onEnd(); });
    MIC.addEventListener('touchstart', function(e) { e.preventDefault(); onStart(); }, {passive: false});
    MIC.addEventListener('touchend', function(e) { e.preventDefault(); onEnd(); }, {passive: false});
    MIC.addEventListener('touchcancel', function() { if (isRecording) onEnd(); });
  }

  // ─── Single Enter handler ───
  function handleEnter() {
    if (voiceEntryActive && tripsheet) {
      handleTripsheetAnswer();
    } else {
      sendMessage();
    }
  }

  // ─── Tripsheet Entry ───
  function startTripsheetEntry() {
    if (voiceEntryActive) return;
    var cid = getCustomerId();
    if (!cid) {
      addMessage('assistant', t('noCustomer'));
      return;
    }
    voiceEntryActive = true;

    tripsheet = {
      fields: [
        { id: 'entry_date', label: 'fieldDate', parse: parseDate },
        { id: 'time_in', label: 'fieldTimeIn', parse: parseTime },
        { id: 'time_out', label: 'fieldTimeOut', parse: parseTime },
        { id: 'total_reading', label: 'fieldMeter', parse: parseNumber },
        { id: 'trips', label: 'fieldTrips', parse: parseNumber },
        { id: 'tanker_reg', label: 'fieldReg', parse: parseText },
      ],
      // tanker_gln always auto-fills as "10000 GLN" on backend
      data: {},
      idx: 0,
      answered: false,
    };
    micResultCallback = null;

    addMessage('assistant', t('tripsheetStart'));
    INPUT.placeholder = t('placeholder2');
    INPUT.focus();
    setTimeout(askNext, 500);
  }

  function askNext() {
    if (!tripsheet) return;
    if (tripsheet.idx >= tripsheet.fields.length) {
      finishEntry();
      return;
    }
    tripsheet.answered = false;
    var f = tripsheet.fields[tripsheet.idx];

    addMessage('assistant', t(f.label) + t('listenHint'));
    INPUT.focus();
    speakText(t(f.label));

    micResultCallback = function(voiceText) {
      if (tripsheet.answered) return;
      tripsheet.answered = true;
      INPUT.value = '';
      addMessage('user', '🎤 ' + voiceText);
      tripsheet.data[f.id] = f.parse ? f.parse(voiceText) : voiceText;
      tripsheet.idx++;
      setTimeout(askNext, 300);
    };
  }

  function handleTripsheetAnswer() {
    if (!tripsheet || tripsheet.answered) return;
    tripsheet.answered = true;
    micResultCallback = null;
    var f = tripsheet.fields[tripsheet.idx];
    var text = INPUT.value.trim();
    INPUT.value = '';
    if (text) {
      addMessage('user', text);
      tripsheet.data[f.id] = f.parse ? f.parse(text) : text;
    } else {
      addMessage('user', t('skipped'));
    }
    tripsheet.idx++;
    setTimeout(askNext, 300);
  }

  function finishEntry() {
    micResultCallback = null;
    var cid = getCustomerId();
    if (!cid) { addMessage('assistant', '❌ ' + t('fail')); resetTripsheetMode(); return; }
    addMessage('assistant', t('saving'));
    showTyping();
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    var payload = { customer_id: cid, lang: lang };
    tripsheet.fields.forEach(function(f) { payload[f.id] = tripsheet.data[f.id] || ''; });
    console.log('Tripsheet payload:', JSON.stringify(payload));
    fetch('/ai/tripsheet_save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      hideTyping();
      if (data.error) { addMessage('assistant', '❌ ' + t('error') + ': ' + data.error); }
      else { addMessage('assistant', t('saved') + ' "📋 ' + t('tripsheetBtn') + '" ' + t('saved2')); speakText('Entry saved successfully'); }
      resetTripsheetMode();
    })
    .catch(function(err) {
      hideTyping();
      addMessage('assistant', '❌ ' + t('error') + ': ' + err.message);
      resetTripsheetMode();
    });
  }

  function resetTripsheetMode() {
    voiceEntryActive = false;
    tripsheet = null;
    micResultCallback = null;
    INPUT.placeholder = t('placeholder');
    INPUT.focus();
  }

  // ─── Parsers ───
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
  function parseNumber(s) { var n = parseFloat(s); return isNaN(n) ? 0 : n; }
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
      if (data.error) { addMessage('assistant', t('error') + ': ' + data.error); return; }
      addMessage('assistant', data.reply);
      HISTORY.push({role: 'assistant', content: data.reply});
    })
    .catch(function(err) {
      hideTyping();
      addMessage('assistant', t('error') + ': ' + err.message);
    })
    .finally(function() { SEND.disabled = false; INPUT.focus(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
