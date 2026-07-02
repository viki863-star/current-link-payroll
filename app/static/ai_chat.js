(function() {
  var TOGGLE, PANEL, MSGS, INPUT, SEND, TYPING, CLEAR, CLOSE;
  var HISTORY = [];
  var WELCOME = 'Hi! I\'m your ERP assistant. Ask me anything about your data — employees, drivers, vehicles, salaries, suppliers, invoices, and more. Try asking in Urdu or English!';

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
  }

  function clearChat() {
    MSGS.innerHTML = '';
    HISTORY = [];
    var welcome = document.createElement('div');
    welcome.className = 'ai-chat-msg assistant';
    welcome.innerHTML = '<div>' + WELCOME + '</div>';
    MSGS.appendChild(welcome);
    INPUT.value = '';
    INPUT.focus();
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
    }
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
