(function() {
  var TOGGLE, PANEL, MSGS, INPUT, SEND, TYPING, CLEAR, CLOSE;
  var HISTORY = [];
  var WELCOME = 'Hi! I\'m your ERP assistant. Ask me about data, or use the quick actions below.';
  var voiceEntryActive = false;

  function init() {
    TOGGLE = document.getElementById('aiChatToggle');
    PANEL = document.getElementById('aiChatPanel');
    MSGS = document.getElementById('aiChatMessages');
    INPUT = document.getElementById('aiChatInput');
    SEND = document.getElementById('aiChatSend');
    TYPING = document.getElementById('aiChatTyping');
    CLEAR = document.getElementById('aiChatClear');
    CLOSE = document.getElementById('aiChatClose');
    if (!TOGGLE || !PANEL) return;

    TOGGLE.addEventListener('click', togglePanel);
    SEND.addEventListener('click', sendMessage);
    CLEAR.addEventListener('click', clearChat);
    CLOSE.addEventListener('click', closeChat);
    INPUT.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    INPUT.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
    });
    showQuickActions();
  }

  function showQuickActions() {
    var welcomeMsg = MSGS.querySelector('.ai-chat-msg.assistant');
    if (!welcomeMsg) return;
    var actions = document.getElementById('aiQuickActions');
    if (actions) return;
    var div = document.createElement('div');
    div.id = 'aiQuickActions';
    div.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:0 12px 8px;';
    var btns = [
      { label: '📋 Tripsheet Entry', action: startVoiceEntry },
    ];
    btns.forEach(function(b) {
      var btn = document.createElement('button');
      btn.textContent = b.label;
      btn.style.cssText = 'background:var(--primary);color:#fff;border:none;border-radius:16px;padding:5px 14px;font-size:0.78rem;cursor:pointer;white-space:nowrap;';
      btn.addEventListener('click', function(e) { e.stopPropagation(); b.action(); });
      div.appendChild(btn);
    });
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

  // ─── Voice / Text Entry for Tripsheet ───
  function startVoiceEntry() {
    if (voiceEntryActive) return;
    var cid = getCustomerId();
    if (!cid) {
      addMessage('assistant', 'Pehle kisi customer ka profile page kholen, phir Tripsheet Entry start karein.');
      return;
    }
    voiceEntryActive = true;
    addMessage('assistant', '📋 Tripsheet Entry start! Main sawaal puchhoonga, aap jawab boliye (ya text mein likhiye).');

    var fields = [
      { id: 'entry_date', label: 'Date kya hai?', parse: parseDate },
      { id: 'time_in', label: 'Time In kya hai?', parse: parseTime },
      { id: 'time_out', label: 'Time Out kya hai?', parse: parseTime },
      { id: 'total_reading', label: 'Kitna meter reading hai?', parse: parseNumber },
      { id: 'trips', label: 'Kitne trips hain?', parse: parseNumber },
      { id: 'tanker_gln', label: 'Tanker GLN kya hai?', parse: parseGln },
      { id: 'tanker_reg', label: 'Tanker registration number kya hai?', parse: parseText },
    ];
    var entryData = {};
    var idx = 0;
    var synth = window.speechSynthesis;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    // Disable normal input temporarily
    INPUT.disabled = true;
    SEND.disabled = true;
    INPUT.placeholder = 'Voice entry mode...';

    function speak(text, cb) {
      addMessage('assistant', '🤖 ' + text);
      if (!synth || !SpeechRecognition) { if (cb) setTimeout(cb, 100); return; }
      var u = new SpeechSynthesisUtterance(text);
      u.lang = 'ur-PK'; u.rate = 0.9;
      u.onend = function() { if (cb) setTimeout(cb, 300); };
      u.onerror = function() { if (cb) setTimeout(cb, 300); };
      synth.cancel(); synth.speak(u);
    }

    function listen(cb) {
      addMessage('assistant', '🎤 Sun raha hoon... boliye');
      if (!SpeechRecognition) { cb(null); return; }
      var r = new SpeechRecognition();
      r.lang = 'ur-PK'; r.continuous = false; r.interimResults = false;
      r.onresult = function(e) {
        var text = e.results[0][0].transcript.trim();
        addMessage('user', '🎤 ' + text);
        cb(text);
      };
      r.onerror = function() {
        addMessage('assistant', '❌ Samajh nahi aaya, text mein likhiye.');
        // fallback to text input for this field
        enableTextFallback(cb);
      };
      r.start();
    }

    function enableTextFallback(cb) {
      INPUT.disabled = false;
      INPUT.placeholder = 'Type answer here...';
      INPUT.focus();
      var handler = function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          INPUT.removeEventListener('keydown', handler);
          var text = INPUT.value.trim();
          INPUT.value = '';
          INPUT.disabled = true;
          INPUT.placeholder = 'Voice entry mode...';
          if (text) {
            addMessage('user', text);
            cb(text);
          } else {
            cb(null);
          }
        }
      };
      INPUT.addEventListener('keydown', handler);
    }

    function askNext() {
      if (idx >= fields.length) {
        finishEntry();
        return;
      }
      var f = fields[idx];
      speak(f.label, function() {
        listen(function(answer) {
          if (answer) {
            entryData[f.id] = f.parse ? f.parse(answer) : answer.trim();
          }
          idx++;
          setTimeout(askNext, 200);
        });
      });
    }

    function finishEntry() {
      var cid = getCustomerId();
      if (!cid) {
        addMessage('assistant', '❌ Customer ID nahi mila.');
        resetVoiceMode();
        return;
      }
      addMessage('assistant', '⏳ Data save ho raha hai...');
      showTyping();

      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
      var payload = { customer_id: cid };
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
          addMessage('assistant', '❌ Error: ' + data.error);
        } else {
          addMessage('assistant', '✅ ' + data.message + '! Agar aur entries chahiye to dobara Tripsheet Entry click karein.');
          // Optional: prompt to add another
          idx = 0;
          entryData = {};
          speak('Entry save ho gayi. Agar aur chahiye to dobara Tripsheet Entry button dabayein.');
        }
        resetVoiceMode();
      })
      .catch(function(err) {
        hideTyping();
        addMessage('assistant', '❌ Network error: ' + err.message);
        resetVoiceMode();
      });
    }

    function resetVoiceMode() {
      voiceEntryActive = false;
      INPUT.disabled = false;
      SEND.disabled = false;
      INPUT.placeholder = 'Ask me anything about your ERP data...';
      INPUT.focus();
    }

    // Start the flow
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
    // try "HH:MM" directly
    if (/^\d{1,2}:\d{2}$/.test(s)) return s;
    return s;
  }
  function parseNumber(s) {
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
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
    welcome.innerHTML = '<div>' + WELCOME + '</div>';
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
      body: JSON.stringify({message: text, history: HISTORY})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      hideTyping();
      if (data.error) {
        addMessage('assistant', 'Error: ' + data.error);
        return;
      }
      addMessage('assistant', data.reply);
      HISTORY.push({role: 'assistant', content: data.reply});
    })
    .catch(function(err) {
      hideTyping();
      addMessage('assistant', 'Network error: ' + err.message);
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
