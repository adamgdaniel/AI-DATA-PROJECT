/* AgroMonitor — Chat flotante con el agente IA
 * Componente único, se monta automáticamente cuando el partial
 * `_chat_widget.html` está presente en la página.
 */
(function () {
  'use strict';

  var fab     = document.getElementById('agro-chat-fab');
  var panel   = document.getElementById('agro-chat-panel');
  var btnX    = document.getElementById('agro-chat-close');
  var msgs    = document.getElementById('agro-chat-messages');
  var input   = document.getElementById('agro-chat-input');
  var sendBtn = document.getElementById('agro-chat-send');

  if (!fab || !panel || !msgs || !input || !sendBtn) return;

  var welcomeShown = false;

  function showWelcome() {
    if (welcomeShown) return;
    welcomeShown = true;
    var div = document.createElement('div');
    div.className = 'agro-chat-welcome';
    div.innerHTML = '<strong>¡Hola! Soy tu asistente agrónomo 🌱</strong>' +
      'Pregúntame cuándo regar, qué abono usar o cómo tratar una plaga. ' +
      'Estoy aquí para ayudarte con tus cultivos.';
    msgs.appendChild(div);
  }

  function openPanel() {
    panel.classList.add('is-open');
    fab.classList.add('is-open');
    fab.setAttribute('aria-expanded', 'true');
    showWelcome();
    setTimeout(function () { input.focus(); }, 300);
  }

  function closePanel() {
    panel.classList.remove('is-open');
    fab.classList.remove('is-open');
    fab.setAttribute('aria-expanded', 'false');
  }

  function togglePanel() {
    if (panel.classList.contains('is-open')) closePanel();
    else openPanel();
  }

  function appendMsg(text, role) {
    var div = document.createElement('div');
    div.className = 'agro-msg is-' + role;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function appendTyping() {
    var div = document.createElement('div');
    div.className = 'agro-typing';
    div.id = 'agro-typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function removeTyping() {
    var t = document.getElementById('agro-typing-indicator');
    if (t) t.remove();
  }

  function autoresize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  }

  function getParcelaContext() {
    // Si la página actual conoce la parcela seleccionada, la enviamos.
    if (typeof window.currentParcela !== 'undefined' &&
        window.currentParcela && window.currentParcela.parcela_id) {
      return window.currentParcela.parcela_id;
    }
    // Si la URL es /parcela/<id>, lo extraemos.
    var m = window.location.pathname.match(/^\/parcela\/([^\/]+)/);
    if (m) return decodeURIComponent(m[1]);
    return null;
  }

  function enviarMensaje() {
    var texto = input.value.trim();
    if (!texto) return;

    appendMsg(texto, 'user');
    input.value = '';
    autoresize();
    sendBtn.disabled = true;
    appendTyping();

    var body = { mensaje: texto };
    var parcelaId = getParcelaContext();
    if (parcelaId) body.parcela_id = parcelaId;

    fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) {
        return r.json().then(function (data) { return { status: r.status, data: data }; });
      })
      .then(function (res) {
        removeTyping();
        if (res.status === 401) {
          appendMsg('Inicia sesión para hablar con el asistente.', 'error');
          return;
        }
        var data = res.data || {};
        if (data.respuesta) {
          appendMsg(data.respuesta, 'agent');
        } else if (data.error) {
          appendMsg(data.error, 'error');
        } else {
          appendMsg('No he podido generar una respuesta. Inténtalo de nuevo.', 'error');
        }
      })
      .catch(function () {
        removeTyping();
        appendMsg('No hay conexión con el asistente. Revisa tu red e inténtalo de nuevo.', 'error');
      })
      .finally(function () {
        sendBtn.disabled = false;
        input.focus();
      });
  }

  fab.addEventListener('click', togglePanel);
  btnX.addEventListener('click', closePanel);
  sendBtn.addEventListener('click', enviarMensaje);

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      enviarMensaje();
    }
  });
  input.addEventListener('input', autoresize);

  // Cierre con tecla Escape para mejorar accesibilidad.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && panel.classList.contains('is-open')) closePanel();
  });
})();
