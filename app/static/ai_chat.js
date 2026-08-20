(function() {
  var TOGGLE, PANEL, MSGS, INPUT, SEND, TYPING, CLEAR, CLOSE, MIC, LISTENING, LISTEN_TEXT;
  var LANG_EN, LANG_UR;
  var HISTORY = [];
  var lang = 'en';
  var voiceEntryActive = false;
  var isRecording = false;
  var currentRecognition = null;
  var micResultCallback = null;
  var tripsheetTimer = null;

  // Tripsheet state (single handler approach)
  var tripsheet = null;

  var TEXTS = {
    en: {
      welcome: '👋 Hi! I\'m <strong>VIKI</strong> — your ERP AI assistant. Ask me <strong>anything</strong>!',
      placeholder: 'Ask me anything...',
      error: 'Error',
      listening: 'Listening... speak now',
    },
    ur: {
      welcome: '👋 السلام علیکم! میں <strong>VIKI</strong> ہوں — آپ کا ERP اسسٹنٹ۔ کچھ بھی پوچھیں!',
      placeholder: 'کچھ بھی پوچھیں...',
      error: 'خرابی',
      listening: 'سن رہا ہوں... بولیں',
    }
  };

  // Smart ERP suggestion chips
  var SUGGESTIONS = [
    { icon: '👥', text: 'How many active drivers?' },
    { icon: '💰', text: 'Show this month payroll total' },
    { icon: '🚛', text: 'How many vehicles are active?' },
    { icon: '📄', text: 'Show recent customer invoices' },
    { icon: '⛽', text: 'Total fuel cost this month' },
    { icon: '⚠️', text: 'Any expired documents?' },
    { icon: '🏢', text: 'Show top suppliers by amount' },
    { icon: '📊', text: 'Give me a business summary' },
  ];

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
    SEND.addEventListener('click', function() { if (voiceEntryActive) return; sendMessage(); });
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
  }

  function showQuickActions() {
    if (MSGS.querySelector('.ai-chat-quick-actions')) return;
    var div = document.createElement('div');
    div.className = 'ai-chat-quick-actions';
    div.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:6px 14px 10px;';
    SUGGESTIONS.forEach(function(s) {
      var btn = document.createElement('button');
      btn.innerHTML = s.icon + ' ' + s.text;
      btn.style.cssText = 'background:#f1f5f9;color:#0f172a;border:1px solid #e2e8f0;border-radius:20px;padding:5px 12px;font-size:0.72rem;cursor:pointer;font-weight:500;transition:all 0.15s;white-space:nowrap;font-family:inherit;';
      btn.addEventListener('mouseenter', function() { this.style.background='#0f172a'; this.style.color='#fff'; this.style.borderColor='#0f172a'; });
      btn.addEventListener('mouseleave', function() { this.style.background='#f1f5f9'; this.style.color='#0f172a'; this.style.borderColor='#e2e8f0'; });
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        INPUT.value = s.text;
        div.remove();
        sendMessage();
      });
      div.appendChild(btn);
    });
    MSGS.appendChild(div);
    MSGS.scrollTop = MSGS.scrollHeight;
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
    var releaseTimer = null, pendingText = '';

    function onStart() {
      if (isRecording) return;
      if (releaseTimer) { clearTimeout(releaseTimer); releaseTimer = null; }
      isRecording = true; pendingText = '';
      MIC.classList.add('is-recording');
      LISTENING.classList.add('is-active');
      if (LISTEN_TEXT) LISTEN_TEXT.textContent = t('listening');
      var r = new SpeechRecognition();
      r.lang = lang === 'ur' ? 'ur-PK' : 'en-US';
      r.continuous = true;
      r.interimResults = false;
      r.onresult = function(e) {
        for (var i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) pendingText = e.results[i][0].transcript.trim();
        }
      };
      r.onerror = function() { forceFinish(); };
      r.onend = function() { if (isRecording) forceFinish(); };
      currentRecognition = r;
      try { r.start(); } catch(e) { forceFinish(); }
    }

    function forceFinish() {
      if (releaseTimer) { clearTimeout(releaseTimer); releaseTimer = null; }
      if (!isRecording) return;
      isRecording = false;
      if (currentRecognition) { try { currentRecognition.stop(); } catch(e) {} currentRecognition = null; }
      MIC.classList.remove('is-recording');
      LISTENING.classList.remove('is-active');
      var text = pendingText || '';
      pendingText = '';
      if (!text) return;
      INPUT.value = text;
      if (micResultCallback) {
        var cb = micResultCallback;
        micResultCallback = null;
        setTimeout(function() { cb(text); }, 80);
      } else {
        setTimeout(function() { handleEnter(); }, 80);
      }
    }

    function userRelease() {
      if (!isRecording) return;
      // Wait briefly for speech to finish processing, then force-stop
      if (releaseTimer) clearTimeout(releaseTimer);
      releaseTimer = setTimeout(function() {
        releaseTimer = null;
        forceFinish();
      }, 600);
    }

    MIC.addEventListener('mousedown', function(e) { e.preventDefault(); onStart(); });
    MIC.addEventListener('mouseup', function(e) { e.preventDefault(); userRelease(); });
    MIC.addEventListener('mouseleave', function() { if (isRecording) userRelease(); });
    MIC.addEventListener('touchstart', function(e) { e.preventDefault(); onStart(); }, {passive: false});
    MIC.addEventListener('touchend', function(e) { e.preventDefault(); userRelease(); }, {passive: false});
    MIC.addEventListener('touchcancel', function() { if (isRecording) userRelease(); });
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
        { id: 'tanker_reg', label: 'fieldReg', parse: parseText },
      ],
      // tanker_gln = "10000 GLN", trips = 1 (auto-filled on backend)
      data: {},
      idx: 0,
      answered: false,
    };
    micResultCallback = null;

    addMessage('assistant', t('tripsheetStart'));
    INPUT.placeholder = t('placeholder2');
    INPUT.focus();
    scheduleAskNext(500);
  }

  function scheduleAskNext(ms) {
    if (tripsheetTimer) { clearTimeout(tripsheetTimer); tripsheetTimer = null; }
    tripsheetTimer = setTimeout(function() {
      tripsheetTimer = null;
      askNext();
    }, ms);
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
      scheduleAskNext(300);
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
    scheduleAskNext(300);
  }

  function finishEntry() {
    micResultCallback = null;
    var cid = getCustomerId();
    if (!cid) { addMessage('assistant', '❌ ' + t('fail')); resetTripsheetMode(); return; }
    addMessage('assistant', t('saving'));
    showTyping();
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    var payload = { customer_id: cid, lang: lang, tanker_gln: '10000 GLN', trips: 1 };
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
      if (data.error) { addMessage('assistant', '❌ ' + t('error') + ': ' + data.error); resetTripsheetMode(); return; }
      var info = '✅ Saved (customer #' + data.customer_id + ', date: ' + data.date + ')';
      addMessage('assistant', info);
      var msg = t('saved') + ' "📋 ' + t('tripsheetBtn') + '" ' + t('saved2');
      addMessage('assistant', msg);
      speakText('Entry saved successfully');
      // Add inline New Entry button
      var btnDiv = document.createElement('div');
      btnDiv.style.cssText = 'display:flex;gap:6px;padding:2px 16px 10px;';
      var newBtn = document.createElement('button');
      newBtn.textContent = '🆕 New Entry';
      newBtn.style.cssText = 'background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;border:none;border-radius:14px;padding:6px 16px;font-size:0.78rem;cursor:pointer;font-weight:500;';
      newBtn.addEventListener('click', function(e) { e.stopPropagation(); startTripsheetEntry(); });
      btnDiv.appendChild(newBtn);
      MSGS.appendChild(btnDiv);
      MSGS.scrollTop = MSGS.scrollHeight;
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
    if (tripsheetTimer) { clearTimeout(tripsheetTimer); tripsheetTimer = null; }
    INPUT.placeholder = t('placeholder');
    INPUT.focus();
  }

  // ─── Parsers ───
  function parseDate(s) {
    if (!s) return '';
    // YYYY-MM-DD already
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    // Try standard date parsing
    var d = new Date(s);
    if (!isNaN(d) && d.getFullYear() > 2000) return d.toISOString().slice(0,10);
    // d/m/y or d-m-y
    var m = s.match(/^(\d{1,2})\s*[\/\-\.]\s*(\d{1,2})\s*[\/\-\.]\s*(\d{2,4})$/);
    if (m) { var day=m[1], mon=m[2], yr=m[3]; if(yr.length===2)yr='20'+yr; return yr+'-'+mon.padStart(2,'0')+'-'+day.padStart(2,'0'); }
    // d m y (space separated)
    var m2 = s.match(/^(\d{1,2})\s+(\d{1,2})\s+(\d{2,4})$/);
    if (m2) { var day2=m2[1], mon2=m2[2], yr2=m2[3]; if(yr2.length===2)yr2='20'+yr2; return yr2+'-'+mon2.padStart(2,'0')+'-'+day2.padStart(2,'0'); }
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
    welcome.innerHTML = '<div>👋 Hi! I\'m <strong>VIKI</strong> — your ERP AI assistant. Ask me <strong>anything</strong>!</div>';
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
