/**
 * Second Brain - Mobile PWA Core
 * Chat-centric interface for mobile devices
 */

class MobileApp {
  constructor() {
    this.input = document.getElementById('chat-input');
    this.sendBtn = document.getElementById('send-btn');
    this.chatContainer = document.querySelector('.chat-container');

    // Read session ID from data attribute (no inline script), fallback to sessionStorage
    const configEl = document.getElementById('chat-config');
    const serverSessionId = configEl ? configEl.dataset.sessionId : '';
    this.sessionId = serverSessionId || sessionStorage.getItem('chat_session_id') || null;
    this.isProcessing = false;
    this.abortController = null;

    // Media recorder for voice
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.recordingStartTime = null;
    this.recordingTimerInterval = null;
    this.audioContext = null;
    this.analyser = null;
    this.waveformFrame = null;

    // Configure marked for safe rendering
    if (typeof marked !== 'undefined') {
      marked.setOptions({ breaks: true, gfm: true });
    }

    this.init();
  }

  init() {
    this.setupInput();
    this.setupQuickActions();
    this.setupSettings();
    this.setupHistoryDrawer();
    this.setupSwipeGestures();
    this.setupOnlineStatus();
    this.setupSuggestions();
    this.createToastContainer();
    this.lockScreen = new LockScreen(this);
    this._setupLockSettings();

    // Render markdown in server-rendered messages (data-raw attribute)
    this.renderAllMarkdown();

    // Cache current messages for offline viewing, or restore from cache if offline
    this._cacheCurrentMessages();
    this._restoreCachedMessages();

    // Scroll to bottom if there are messages
    if (this.chatContainer && !document.querySelector('.empty-state')) {
      this.scrollToBottom();
    }
  }

  // === INPUT HANDLING ===
  setupInput() {
    if (!this.input) return;

    // Auto-resize textarea
    this.input.addEventListener('input', () => {
      this.input.style.height = 'auto';
      this.input.style.height = Math.min(this.input.scrollHeight, 120) + 'px';
      this.detectUrl(this.input.value);
    });

    // Detect URL on paste
    this.input.addEventListener('paste', () => {
      setTimeout(() => this.detectUrl(this.input.value), 50);
    });

    // Enter to send (without shift)
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Send button
    if (this.sendBtn) {
      this.sendBtn.addEventListener('click', () => this.sendMessage());
    }
  }

  detectUrl(text) {
    const urlRegex = /https?:\/\/[^\s]+/i;
    const match = text.match(urlRegex);
    let bar = document.getElementById('url-action-bar');

    if (match) {
      const url = match[0];
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'url-action-bar';
        bar.className = 'url-action-bar';
        const quickActions = document.getElementById('quick-actions');
        if (quickActions) quickActions.parentNode.insertBefore(bar, quickActions);
      }
      const domain = url.replace(/https?:\/\//, '').split('/')[0].substring(0, 30);
      bar.innerHTML = `
        <span class="url-detected-label">🔗 ${this.escapeHtml(domain)}</span>
        <div class="url-detected-actions">
          <button class="url-action-chip" data-url-action="summarize">📖 Streść</button>
          <button class="url-action-chip" data-url-action="bookmark">🔖 Zakładka</button>
        </div>
      `;
      bar.classList.remove('hidden');

      bar.querySelectorAll('.url-action-chip').forEach(chip => {
        chip.addEventListener('click', () => {
          const action = chip.dataset.urlAction;
          if (action === 'summarize') {
            this.input.value = `Streść: ${url}`;
          } else if (action === 'bookmark') {
            this.input.value = `Zapisz zakładkę: ${url}`;
          }
          bar.classList.add('hidden');
          this.sendMessage();
        });
      });
    } else if (bar) {
      bar.classList.add('hidden');
    }
  }

  async sendMessage() {
    const text = this.input.value.trim();
    if (!text && !this.isProcessing) return;

    // If already processing, cancel the request
    if (this.isProcessing) {
      this.cancelRequest();
      return;
    }

    this.isProcessing = true;
    this.setSendButtonState('stop');

    // Clear input and URL bar
    this.input.value = '';
    this.input.style.height = 'auto';
    const urlBar = document.getElementById('url-action-bar');
    if (urlBar) urlBar.classList.add('hidden');

    // Hide empty state
    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();

    // Add user message
    this.addMessage(text, 'user');

    // If offline, queue the message
    if (!navigator.onLine) {
      await this.handleOfflineMessage(text);
      this.isProcessing = false;
      this.setSendButtonState('send');
      return;
    }

    // Show typing indicator
    const typingId = this.showTyping();

    try {
      this.abortController = new AbortController();
      await this.callChatStream(text, typingId, this.abortController.signal);

    } catch (error) {
      this.hideTyping(typingId);

      if (error.name === 'AbortError') {
        this.addMessage('⏹️ *Anulowano*', 'assistant');
      } else if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
        await this.handleOfflineMessage(text);
      } else {
        console.error('Chat error:', error);
        // Fallback to non-streaming
        try {
          const response = await this.callChat(text, this.abortController?.signal);
          this.addMessage(response.answer, 'assistant', response.sources || []);
          if (response.session_id) {
            this.sessionId = response.session_id;
            sessionStorage.setItem('chat_session_id', this.sessionId);
          }
        } catch (fallbackErr) {
          if (fallbackErr.name !== 'AbortError') {
            this.addMessage('Przepraszam, wystąpił błąd. Spróbuj ponownie.', 'assistant');
            this.showToast('Błąd połączenia z serwerem', 'error');
          }
        }
      }
    } finally {
      this.isProcessing = false;
      this.abortController = null;
      this.setSendButtonState('send');
    }
  }

  cancelRequest() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  setSendButtonState(state) {
    if (!this.sendBtn) return;
    const icon = this.sendBtn.querySelector('span');
    if (state === 'stop') {
      this.sendBtn.classList.add('stop-mode');
      this.sendBtn.disabled = false;
      if (icon) icon.textContent = '⏹';
      this.sendBtn.title = 'Zatrzymaj';
    } else {
      this.sendBtn.classList.remove('stop-mode');
      this.sendBtn.disabled = false;
      if (icon) icon.textContent = '➤';
      this.sendBtn.title = 'Wyślij';
    }
  }

  /**
   * Handle message when offline - queue and show placeholder with pending indicator
   */
  async handleOfflineMessage(text) {
    const queued = await this.queueOfflineAction({
      type: 'chat',
      url: '/chat/message',
      method: 'POST',
      body: {
        message: text,
        session_id: this.sessionId
      },
      displayText: text.substring(0, 50) + (text.length > 50 ? '...' : '')
    });

    if (queued) {
      // Mark the last user message as pending with queue ID
      const userMessages = this.chatContainer?.querySelectorAll('.message.user');
      const lastUserMsg = userMessages?.[userMessages.length - 1];
      if (lastUserMsg) {
        lastUserMsg.classList.add('pending');
        lastUserMsg.dataset.queueId = queued;
        const badge = document.createElement('div');
        badge.className = 'message-pending-badge';
        badge.innerHTML = '<span class="pending-dot"></span> Oczekuje na połączenie';
        lastUserMsg.appendChild(badge);
      }

      this.addMessage(
        '📡 *Wiadomość zapisana offline*\n\nOdpowiedź pojawi się po połączeniu z internetem.',
        'assistant'
      );
      this.showToast('Wiadomość zapisana - wyślę gdy będzie połączenie', 'info');

      // Cache message for offline viewing
      this._cacheMessage(text, 'user');
    } else {
      this.addMessage('❌ Nie udało się zapisać wiadomości.', 'assistant');
    }
  }

  async callChatStream(text, typingId, signal) {
    const payload = { message: text };
    if (this.sessionId) payload.session_id = this.sessionId;

    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let msgEl = null;
    let contentDiv = null;
    let tokens = [];
    let lastRenderTime = 0;
    let renderTimer = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7);
        } else if (line.startsWith('data: ') && eventType) {
          let data;
          try { data = JSON.parse(line.slice(6)); } catch (e) { console.warn('SSE parse error:', e); eventType = ''; continue; }

          if (eventType === 'session') {
            this.sessionId = data.session_id;
            sessionStorage.setItem('chat_session_id', this.sessionId);
          } else if (eventType === 'status') {
            // Update typing indicator with phase info
            const typingEl = document.getElementById(typingId);
            if (typingEl) {
              const phases = { classifying: 'Analizuję...', searching: 'Szukam...', generating: 'Generuję...', agent: 'Agent...' };
              const statusText = phases[data.phase] || '';
              typingEl.textContent = '';
              const span = document.createElement('span');
              span.className = 'status-text';
              span.textContent = statusText;
              typingEl.appendChild(span);
              for (let i = 0; i < 3; i++) typingEl.appendChild(document.createElement('span'));
            }
          } else if (eventType === 'tool_result') {
            // Agent tool executed - render as action card
            this.hideTyping(typingId);
            const card = this.renderActionCard(data.tool, data.metadata);
            if (card) {
              msgEl = document.createElement('div');
              msgEl.className = 'message assistant';
              msgEl.appendChild(card);
              this.addMessageActions(msgEl, data.text);
              const time = document.createElement('div');
              time.className = 'message-time';
              time.textContent = new Date().toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' });
              msgEl.appendChild(time);
              this.chatContainer.appendChild(msgEl);
              this.scrollToBottom();
            }
          } else if (eventType === 'token') {
            // First token - create message bubble, hide typing
            if (!msgEl) {
              this.hideTyping(typingId);
              msgEl = document.createElement('div');
              msgEl.className = 'message assistant';
              contentDiv = document.createElement('div');
              contentDiv.className = 'message-content';
              msgEl.appendChild(contentDiv);
              this.chatContainer.appendChild(msgEl);
            }
            tokens.push(data.text);
            // Debounced markdown render + throttled scroll (avoid O(n²) on fast streams)
            const now = Date.now();
            if (now - lastRenderTime > 80) {
              lastRenderTime = now;
              contentDiv.innerHTML = this.renderMarkdown(tokens.join(''));
              this.scrollToBottom();
            } else if (!renderTimer) {
              renderTimer = setTimeout(() => {
                renderTimer = null;
                lastRenderTime = Date.now();
                contentDiv.innerHTML = this.renderMarkdown(tokens.join(''));
                this.scrollToBottom();
              }, 80);
            }
          } else if (eventType === 'done') {
            if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
            this.hideTyping(typingId);

            // Skip if tool_result already rendered the card
            if (data.tool_result && msgEl && !contentDiv) {
              // Card already rendered by tool_result event - nothing more to do
            } else if (msgEl && contentDiv) {
              // Final render with complete text
              contentDiv.innerHTML = this.renderMarkdown(data.answer);
              // Add action bar
              this.addMessageActions(msgEl, data.answer);
              // Add sources
              if (data.sources && data.sources.length > 0) {
                const sourcesDiv = document.createElement('div');
                sourcesDiv.className = 'message-sources';
                sourcesDiv.innerHTML = '<small class="sources-label">Źródła:</small>';
                data.sources.slice(0, 3).forEach(source => {
                  const link = document.createElement('a');
                  link.className = 'source-link';
                  link.href = source.url || '#';
                  link.target = '_blank';
                  link.rel = 'noopener noreferrer';
                  link.textContent = (source.title || 'Link').substring(0, 30);
                  if ((source.title || '').length > 30) link.textContent += '...';
                  sourcesDiv.appendChild(link);
                });
                msgEl.appendChild(sourcesDiv);
              }
              // Add time
              const time = document.createElement('div');
              time.className = 'message-time';
              time.textContent = new Date().toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' });
              msgEl.appendChild(time);
            } else {
              // No tokens received (empty response)
              this.addMessage(data.answer || 'Brak odpowiedzi.', 'assistant', data.sources || []);
            }

            // Cache streamed response for offline viewing
            if (data.answer) {
              this._cacheMessage(data.answer, 'assistant', data.sources || []);
            }
          }
          eventType = '';
        }
      }
    }
  }

  async callChat(message, signal) {
    const payload = {
      message: message,
    };
    if (this.sessionId) {
      payload.session_id = this.sessionId;
    }

    const fetchOptions = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    };
    if (signal) fetchOptions.signal = signal;

    const response = await fetch('/chat/message', fetchOptions);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  addMessage(content, role, sources = []) {
    if (!this.chatContainer) return;
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    // Content
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = this.renderMarkdown(content);
    msg.appendChild(contentDiv);

    // Copy/share actions for assistant messages
    if (role === 'assistant') {
      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'message-action-bar';
      actionsDiv.innerHTML = `
        <button class="msg-action-btn" data-action="copy" title="Kopiuj">📋</button>
        ${navigator.share ? '<button class="msg-action-btn" data-action="share" title="Udostępnij">📤</button>' : ''}
      `;
      actionsDiv.querySelector('[data-action="copy"]').addEventListener('click', () => {
        navigator.clipboard.writeText(content).then(() => {
          this.showToast('Skopiowano do schowka', 'success');
        }).catch(() => {
          this.showToast('Nie udało się skopiować', 'error');
        });
      });
      const shareBtn = actionsDiv.querySelector('[data-action="share"]');
      if (shareBtn) {
        shareBtn.addEventListener('click', () => {
          navigator.share({ text: content }).catch(() => {});
        });
      }
      msg.appendChild(actionsDiv);
    }

    // Sources for assistant messages
    if (role === 'assistant' && sources && sources.length > 0) {
      const sourcesDiv = document.createElement('div');
      sourcesDiv.className = 'message-sources';
      sourcesDiv.innerHTML = '<small class="sources-label">Źródła:</small>';

      sources.slice(0, 3).forEach(source => {
        const link = document.createElement('a');
        link.className = 'source-link';
        link.href = source.url || '#';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = (source.title || 'Link').substring(0, 30);
        if ((source.title || '').length > 30) link.textContent += '...';
        sourcesDiv.appendChild(link);
      });

      msg.appendChild(sourcesDiv);
    }

    // Time
    const time = document.createElement('div');
    time.className = 'message-time';
    time.textContent = new Date().toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' });
    msg.appendChild(time);

    this.chatContainer.appendChild(msg);
    this.scrollToBottom();

    // Cache for offline viewing
    this._cacheMessage(content, role, sources);
  }

  addActionCardMessage(cardEl) {
    if (!this.chatContainer) return;
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.appendChild(cardEl);
    const time = document.createElement('div');
    time.className = 'message-time';
    time.textContent = new Date().toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' });
    msg.appendChild(time);
    this.chatContainer.appendChild(msg);
    this.scrollToBottom();
  }

  renderMarkdown(text) {
    // Use marked + DOMPurify for safe markdown rendering
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      const html = marked.parse(text);
      return DOMPurify.sanitize(html, {
        ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'code', 'pre', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
        ALLOWED_ATTR: ['href', 'target', 'rel'],
        ADD_ATTR: ['target'],
      });
    }
    // Fallback: escape HTML and do basic formatting
    const escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    return escaped
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }

  /**
   * Render markdown in all server-rendered messages that have data-raw attribute.
   * Matches desktop pattern from chat/index.html.
   */
  renderAllMarkdown() {
    document.querySelectorAll('.message-content[data-raw]').forEach(el => {
      const raw = el.dataset.raw;
      if (raw) {
        el.innerHTML = this.renderMarkdown(raw);
        el.removeAttribute('data-raw');

        // Add copy/share bar to assistant messages
        const msg = el.closest('.message.assistant');
        if (msg && !msg.querySelector('.message-action-bar')) {
          this.addMessageActions(msg, raw);
        }
      }
    });
  }

  renderActionCard(tool, metadata) {
    if (!metadata || !metadata.card_type) return null;

    const card = document.createElement('div');
    const ct = metadata.card_type;

    if (ct === 'note_created') {
      card.className = 'action-card note';
      card.innerHTML = `
        <div class="action-card-header">
          <span class="action-card-icon">\u2705</span>
          <span class="action-card-title">Notatka utworzona</span>
        </div>
        <div class="action-card-body">${this.escapeHtml(metadata.title || '')}</div>
        ${metadata.content_preview ? `<div class="action-card-subtitle">${this.escapeHtml(metadata.content_preview)}</div>` : ''}
        <div class="action-card-actions">
          ${metadata.id ? `<a class="action-card-btn" href="/m/notatki/${metadata.id}">\ud83d\udcdd Edytuj</a>` : ''}
          <a class="action-card-btn" href="/m/notatki">\ud83d\udccb Notatki</a>
        </div>
      `;
    } else if (ct === 'bookmark_created' || ct === 'bookmark_exists') {
      card.className = 'action-card bookmark';
      const icon = ct === 'bookmark_exists' ? '\u2139\ufe0f' : '\ud83d\udd16';
      const label = ct === 'bookmark_exists' ? 'Zak\u0142adka istnieje' : 'Zak\u0142adka zapisana';
      card.innerHTML = `
        <div class="action-card-header">
          <span class="action-card-icon">${icon}</span>
          <span class="action-card-title">${label}</span>
        </div>
        <div class="action-card-body">${this.escapeHtml(metadata.title || metadata.url || '')}</div>
        <div class="action-card-actions">
          ${metadata.url ? `<a class="action-card-btn" href="${this.escapeHtml(metadata.url)}" target="_blank" rel="noopener noreferrer">\ud83d\udd17 Otw\u00f3rz</a>` : ''}
          <a class="action-card-btn" href="/m/wiedza">\ud83d\udcda Zak\u0142adki</a>
        </div>
      `;
    } else if (ct === 'receipt_processed') {
      card.className = 'action-card receipt';
      card.innerHTML = `
        <div class="action-card-header">
          <span class="action-card-icon">\ud83e\uddfe</span>
          <span class="action-card-title">${this.escapeHtml(metadata.store || 'Sklep')} \u2022 ${this.escapeHtml(metadata.date || '')}</span>
        </div>
        <div class="card-stats">
          <span>${metadata.items_count || 0} pozycji</span>
          <span>${(metadata.total || 0).toFixed(2)} PLN</span>
        </div>
        ${metadata.needs_review ? '<div class="action-card-subtitle">\u26a0\ufe0f Wymaga weryfikacji</div>' : ''}
        <div class="action-card-actions">
          ${metadata.id ? `<a class="action-card-btn" href="/m/paragony/${metadata.id}">\ud83d\udc41\ufe0f Szczeg\u00f3\u0142y</a>` : ''}
          <a class="action-card-btn" href="/m/paragony">\ud83e\uddfe Paragony</a>
        </div>
      `;
    } else {
      return null;
    }

    return card;
  }

  addMessageActions(msgEl, rawText) {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-action-bar';
    actionsDiv.innerHTML = `
      <button class="msg-action-btn" data-action="copy" title="Kopiuj">📋</button>
      ${navigator.share ? '<button class="msg-action-btn" data-action="share" title="Udostępnij">📤</button>' : ''}
    `;
    actionsDiv.querySelector('[data-action="copy"]').addEventListener('click', () => {
      navigator.clipboard.writeText(rawText).then(() => {
        this.showToast('Skopiowano do schowka', 'success');
      }).catch(() => {
        this.showToast('Nie udało się skopiować', 'error');
      });
    });
    const shareBtn = actionsDiv.querySelector('[data-action="share"]');
    if (shareBtn) {
      shareBtn.addEventListener('click', () => {
        navigator.share({ text: rawText }).catch(() => {});
      });
    }
    // Insert before time element
    const timeEl = msgEl.querySelector('.message-time');
    if (timeEl) {
      msgEl.insertBefore(actionsDiv, timeEl);
    } else {
      msgEl.appendChild(actionsDiv);
    }
  }

  showTyping() {
    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    this.chatContainer.appendChild(div);
    this.scrollToBottom();
    return id;
  }

  hideTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  scrollToBottom() {
    const main = document.querySelector('.app-main');
    if (main) {
      setTimeout(() => main.scrollTop = main.scrollHeight, 50);
    }
  }

  // === QUICK ACTIONS ===
  setupQuickActions() {
    // Camera button - tap: camera, long press: context menu (camera/gallery)
    const cameraBtn = document.querySelector('[data-action="camera"]');
    if (cameraBtn) {
      let camTimer = null, camLongPress = false;

      cameraBtn.addEventListener('touchstart', (e) => {
        e.preventDefault();
        camLongPress = false;
        camTimer = setTimeout(() => {
          camLongPress = true;
          this._showContextMenu(cameraBtn, [
            { icon: '📷', label: 'Aparat', action: () => this.openCamera() },
            { icon: '🖼️', label: 'Galeria', action: () => this.openGallery() },
          ]);
        }, 400);
      }, { passive: false });

      cameraBtn.addEventListener('touchend', () => {
        clearTimeout(camTimer);
        if (!camLongPress) this.openCamera();
      });
      cameraBtn.addEventListener('touchcancel', () => clearTimeout(camTimer));

      cameraBtn.addEventListener('click', (e) => {
        if (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return;
        this.openCamera();
      });
    }

    // Voice button - tap to toggle OR push-to-talk (long press)
    const voiceBtn = document.querySelector('[data-action="voice"]');
    if (voiceBtn) {
      let pressTimer = null;
      let isPushToTalk = false;

      voiceBtn.addEventListener('touchstart', (e) => {
        e.preventDefault();
        pressTimer = setTimeout(() => {
          isPushToTalk = true;
          this.startRecording();
        }, 400);
      }, { passive: false });

      voiceBtn.addEventListener('touchend', () => {
        clearTimeout(pressTimer);
        if (isPushToTalk) {
          isPushToTalk = false;
          this.stopRecording(false);
        } else {
          this.toggleVoice();
        }
      });

      voiceBtn.addEventListener('touchcancel', () => {
        clearTimeout(pressTimer);
        if (isPushToTalk) {
          isPushToTalk = false;
          this.stopRecording(true);
        }
      });

      voiceBtn.addEventListener('click', (e) => {
        if (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return;
        this.toggleVoice();
      });
    }

    // Attachment button → bottom sheet
    const attachBtn = document.querySelector('[data-action="attach"]');
    const attachSheet = document.getElementById('attach-sheet');
    const attachBackdrop = document.getElementById('attach-backdrop');
    if (attachBtn && attachSheet) {
      attachBtn.addEventListener('click', () => {
        attachSheet.classList.add('open');
        if (attachBackdrop) attachBackdrop.classList.add('open');
      });
      if (attachBackdrop) {
        attachBackdrop.addEventListener('click', () => {
          attachSheet.classList.remove('open');
          attachBackdrop.classList.remove('open');
        });
      }
      // Attachment options
      document.getElementById('attach-camera')?.addEventListener('click', () => {
        this._closeAttachSheet();
        this.openCamera();
      });
      document.getElementById('attach-gallery')?.addEventListener('click', () => {
        this._closeAttachSheet();
        this.openGallery();
      });
      document.getElementById('attach-pdf')?.addEventListener('click', () => {
        this._closeAttachSheet();
        this.openFilePicker('application/pdf');
      });
      document.getElementById('attach-link')?.addEventListener('click', () => {
        this._closeAttachSheet();
        if (this.input) {
          this.input.focus();
          this.input.placeholder = 'Wklej link...';
          setTimeout(() => { this.input.placeholder = 'Napisz...'; }, 5000);
        }
      });
    }

    // Cancel recording button
    const cancelBtn = document.getElementById('recording-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => this.stopRecording(true));
    }
  }

  _closeAttachSheet() {
    document.getElementById('attach-sheet')?.classList.remove('open');
    document.getElementById('attach-backdrop')?.classList.remove('open');
  }

  _showContextMenu(anchor, items) {
    // Remove existing menu
    document.querySelector('.context-menu')?.remove();

    const menu = document.createElement('div');
    menu.className = 'context-menu';
    items.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'context-menu-item';
      const iconSpan = document.createElement('span');
      iconSpan.textContent = item.icon;
      btn.appendChild(iconSpan);
      btn.appendChild(document.createTextNode(' ' + item.label));
      btn.addEventListener('click', () => {
        menu.remove();
        item.action();
      });
      menu.appendChild(btn);
    });

    document.body.appendChild(menu);

    // Position near anchor
    const rect = anchor.getBoundingClientRect();
    menu.style.left = rect.left + 'px';
    menu.style.bottom = (window.innerHeight - rect.top + 8) + 'px';

    // Haptic
    if (navigator.vibrate) navigator.vibrate(30);

    // Close on outside tap
    const close = (e) => {
      if (!menu.contains(e.target)) {
        menu.remove();
        document.removeEventListener('touchstart', close);
        document.removeEventListener('click', close);
      }
    };
    setTimeout(() => {
      document.addEventListener('touchstart', close, { passive: true });
      document.addEventListener('click', close);
    }, 100);
  }

  openGallery() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = (e) => {
      if (e.target.files[0]) this.showFilePreview(e.target.files[0]);
      input.remove();
    };
    input.click();
  }

  openFilePicker(accept) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = (e) => {
      if (e.target.files[0]) this.showFilePreview(e.target.files[0]);
      input.remove();
    };
    input.click();
  }

  openCamera() {
    const input = document.getElementById('file-input') || document.createElement('input');
    if (!document.getElementById('file-input')) {
      input.type = 'file';
      input.id = 'file-input';
      input.accept = 'image/*,.pdf';
      input.capture = 'environment';
      input.style.display = 'none';
      document.body.appendChild(input);
    }

    input.value = ''; // Reset so same file triggers change
    input.onchange = (e) => {
      if (e.target.files[0]) {
        this.showFilePreview(e.target.files[0]);
      }
    };
    input.click();
  }

  showFilePreview(file) {
    const overlay = document.getElementById('file-preview');
    const img = document.getElementById('file-preview-img');
    const name = document.getElementById('file-preview-name');
    const sendBtn = document.getElementById('file-preview-send');
    const cancelBtn = document.getElementById('file-preview-cancel');
    const actions = document.getElementById('file-preview-actions');
    const progress = document.getElementById('file-preview-progress');
    const bar = document.getElementById('file-preview-bar');

    if (!overlay) {
      this.handleFileUpload(file);
      return;
    }

    // Show preview
    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = (e) => { img.src = e.target.result; };
      reader.readAsDataURL(file);
    } else {
      img.src = '';
      img.alt = file.name;
    }
    name.textContent = `${file.name} (${(file.size / 1024).toFixed(0)} KB)`;
    progress.classList.add('hidden');
    bar.style.width = '0%';
    actions.classList.remove('hidden');
    overlay.classList.remove('hidden');

    // Send button
    const handleSend = () => {
      cleanup();
      this.handleFileUploadWithProgress(file);
    };
    // Cancel button
    const handleCancel = () => {
      cleanup();
      overlay.classList.add('hidden');
    };
    const cleanup = () => {
      sendBtn.removeEventListener('click', handleSend);
      cancelBtn.removeEventListener('click', handleCancel);
    };
    sendBtn.addEventListener('click', handleSend);
    cancelBtn.addEventListener('click', handleCancel);
  }

  async handleFileUploadWithProgress(file) {
    const overlay = document.getElementById('file-preview');
    const progress = document.getElementById('file-preview-progress');
    const bar = document.getElementById('file-preview-bar');
    const actions = document.getElementById('file-preview-actions');

    // Show progress, hide buttons
    if (actions) actions.classList.add('hidden');
    if (progress) progress.classList.remove('hidden');

    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();
    this.addMessage(`📷 Przesyłam: ${file.name}...`, 'user');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const result = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable && bar) {
            bar.style.width = Math.round((e.loaded / e.total) * 100) + '%';
          }
        });
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText));
          } else {
            reject(new Error(`HTTP ${xhr.status}`));
          }
        });
        xhr.addEventListener('error', () => reject(new Error('Upload failed')));
        xhr.open('POST', '/process-receipt');
        xhr.send(formData);
      });

      if (overlay) overlay.classList.add('hidden');

      if (result.success) {
        const receipt = result.receipt || {};
        const store = receipt.sklep || 'Nieznany';
        const total = receipt.suma || 0;
        const itemsCount = receipt.products?.length || 0;

        // Render as action card
        const card = this.renderActionCard('receipt', {
          card_type: 'receipt_processed',
          store: store,
          date: receipt.data || '',
          total: total,
          items_count: itemsCount,
          needs_review: result.needs_review,
          id: result.receipt_id || null,
        });
        if (card) {
          this.addActionCardMessage(card);
        } else {
          this.addMessage(
            `\u2705 **Paragon przetworzony!**\n\n**${store}** - ${total.toFixed(2)} PLN\nPozycji: ${itemsCount}` +
            (result.needs_review ? '\n\n\u26a0\ufe0f Wymaga weryfikacji' : ''),
            'assistant'
          );
        }
        this.showToast('Paragon przetworzony', 'success');
      } else {
        throw new Error(result.error || 'Processing failed');
      }
    } catch (error) {
      console.error('Upload error:', error);
      if (overlay) overlay.classList.add('hidden');
      this.addMessage('\u274c Nie uda\u0142o si\u0119 przetworzy\u0107 paragonu: ' + (error.message || 'Nieznany b\u0142\u0105d'), 'assistant');
      this.showToast('B\u0142\u0105d przetwarzania', 'error');
    }
  }

  async handleFileUpload(file) {
    if (!file) return;

    // Check if offline - files can't be queued easily
    if (!navigator.onLine) {
      this.showToast('Brak po\u0142\u0105czenia - zdj\u0119cia wymagaj\u0105 internetu', 'warning');
      this.addMessage(
        '\ud83d\udce1 *Brak po\u0142\u0105czenia*\n\nZdj\u0119cia paragon\u00f3w wymagaj\u0105 po\u0142\u0105czenia z internetem. Spr\u00f3buj ponownie gdy b\u0119dziesz online.',
        'assistant'
      );
      return;
    }

    // Show uploading message
    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();

    this.addMessage(`\ud83d\udcf7 Przesy\u0142am: ${file.name}...`, 'user');
    const typingId = this.showTyping();

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('/process-receipt', {
        method: 'POST',
        body: formData
      });

      this.hideTyping(typingId);

      if (response.ok) {
        const result = await response.json();

        if (result.success) {
          const receipt = result.receipt || {};
          const store = receipt.sklep || 'Nieznany';
          const total = receipt.suma || 0;
          const itemsCount = receipt.products?.length || 0;

          // Render as action card
          const card = this.renderActionCard('receipt', {
            card_type: 'receipt_processed',
            store: store,
            date: receipt.data || '',
            total: total,
            items_count: itemsCount,
            needs_review: result.needs_review,
            id: result.receipt_id || null,
          });
          if (card) {
            this.addActionCardMessage(card);
          } else {
            this.addMessage(
              `\u2705 **Paragon przetworzony!**\n\n` +
              `**${store}** - ${total.toFixed(2)} PLN\n` +
              `Pozycji: ${itemsCount}` +
              (result.needs_review ? '\n\n\u26a0\ufe0f Wymaga weryfikacji' : ''),
              'assistant'
            );
          }
          this.showToast('Paragon przetworzony', 'success');
        } else {
          throw new Error(result.error || 'Processing failed');
        }
      } else {
        throw new Error('Upload failed');
      }
    } catch (error) {
      console.error('Upload error:', error);
      this.hideTyping(typingId);
      this.addMessage('\u274c Nie uda\u0142o si\u0119 przetworzy\u0107 paragonu: ' + (error.message || 'Nieznany b\u0142\u0105d'), 'assistant');
      this.showToast('B\u0142\u0105d przetwarzania', 'error');
    }
  }

  // === VOICE RECORDING ===
  toggleVoice() {
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.stopRecording(false);
    } else {
      this.startRecording();
    }
  }

  async startRecording() {
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') return;

    const quickActions = document.getElementById('quick-actions');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        this.audioChunks.push(e.data);
      };

      this.mediaRecorder.onstop = () => {
        // Clean up waveform and timer
        this._stopRecordingUI();
        stream.getTracks().forEach(track => track.stop());
      };

      this.mediaRecorder.start();
      quickActions?.classList.add('recording');

      // Haptic feedback
      if (navigator.vibrate) navigator.vibrate(50);

      // Start timer
      this.recordingStartTime = Date.now();
      this._updateRecordingTimer();
      this.recordingTimerInterval = setInterval(() => this._updateRecordingTimer(), 1000);

      // Start waveform visualizer
      this._startWaveform(stream);

    } catch (error) {
      console.error('Microphone access denied:', error);
      this.showToast('Brak dostepu do mikrofonu', 'error');
    }
  }

  stopRecording(cancel = false) {
    if (!this.mediaRecorder || this.mediaRecorder.state !== 'recording') return;

    // Haptic feedback
    if (navigator.vibrate) navigator.vibrate([30, 30, 30]);

    if (cancel) {
      // Cancel: stop without sending
      this.mediaRecorder.onstop = () => {
        this._stopRecordingUI();
        this.mediaRecorder.stream?.getTracks().forEach(t => t.stop());
      };
      this.mediaRecorder.stop();
      this.showToast('Nagrywanie anulowane', 'info');
    } else {
      // Save onstop handler to send
      const stream = this.mediaRecorder.stream;
      this.mediaRecorder.onstop = async () => {
        this._stopRecordingUI();
        stream?.getTracks().forEach(t => t.stop());
        const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
        await this.sendVoiceMessage(blob);
      };
      this.mediaRecorder.stop();
    }
  }

  _stopRecordingUI() {
    const quickActions = document.getElementById('quick-actions');
    quickActions?.classList.remove('recording');
    clearInterval(this.recordingTimerInterval);
    this.recordingTimerInterval = null;
    if (this.waveformFrame) {
      cancelAnimationFrame(this.waveformFrame);
      this.waveformFrame = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    // Reset timer display
    const timerEl = document.getElementById('recording-timer');
    if (timerEl) timerEl.textContent = '0:00';
  }

  _updateRecordingTimer() {
    const timerEl = document.getElementById('recording-timer');
    if (!timerEl || !this.recordingStartTime) return;
    const elapsed = Math.floor((Date.now() - this.recordingStartTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    timerEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  _startWaveform(stream) {
    const canvas = document.getElementById('waveform-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    try {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = this.audioContext.createMediaStreamSource(stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 128;
      source.connect(this.analyser);

      const bufferLength = this.analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const draw = () => {
        this.waveformFrame = requestAnimationFrame(draw);
        this.analyser.getByteFrequencyData(dataArray);

        // Resize canvas to actual pixel size (setTransform resets accumulated scale)
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        ctx.clearRect(0, 0, rect.width, rect.height);

        const barCount = Math.min(bufferLength, 32);
        const barWidth = rect.width / barCount - 1;
        const centerY = rect.height / 2;

        for (let i = 0; i < barCount; i++) {
          const value = dataArray[i] / 255;
          const barHeight = Math.max(2, value * centerY);
          const x = i * (barWidth + 1);
          ctx.fillStyle = value > 0.5 ? '#dc3545' : 'rgba(220, 53, 69, 0.5)';
          ctx.fillRect(x, centerY - barHeight, barWidth, barHeight * 2);
        }
      };
      draw();
    } catch (e) {
      console.warn('Waveform not available:', e);
    }
  }

  async sendVoiceMessage(audioBlob) {
    try {
      const formData = new FormData();
      formData.append('audio', audioBlob, 'voice.webm');

      const response = await fetch('/transcription/quick', {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        this.showToast('Notatka g\u0142osowa dodana do kolejki', 'success');
      } else {
        throw new Error('Queue failed');
      }
    } catch (error) {
      console.error('Voice error:', error);
      this.showToast('Nie uda\u0142o si\u0119 wys\u0142a\u0107 nagrania', 'error');
    }
  }

  // === SETTINGS ===
  setupSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsSheet = document.getElementById('settings-sheet');
    const settingsBackdrop = document.getElementById('settings-backdrop');
    const toggleNav = document.getElementById('toggle-nav');
    const newSessionBtn = document.getElementById('new-session-btn');

    if (settingsBtn && settingsSheet && settingsBackdrop) {
      settingsBtn.addEventListener('click', () => {
        settingsSheet.classList.add('open');
        settingsBackdrop.classList.add('open');
      });

      settingsBackdrop.addEventListener('click', () => {
        settingsSheet.classList.remove('open');
        settingsBackdrop.classList.remove('open');
      });
    }

    // Theme picker (auto / dark / light)
    const themePicker = document.getElementById('theme-picker');
    if (themePicker) {
      const currentTheme = localStorage.getItem('theme_pref') || 'auto';
      themePicker.querySelectorAll('.theme-opt').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.theme === currentTheme);
        btn.addEventListener('click', () => {
          const theme = btn.dataset.theme;
          localStorage.setItem('theme_pref', theme);
          document.documentElement.dataset.theme = theme;
          themePicker.querySelectorAll('.theme-opt').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          // Update meta theme-color
          const meta = document.querySelector('meta[name="theme-color"]');
          if (meta) {
            const isLight = theme === 'light' ||
              (theme === 'auto' && window.matchMedia('(prefers-color-scheme: light)').matches);
            meta.content = isLight ? '#f8f9fa' : '#212529';
          }
        });
      });
    }

    // Bottom nav toggle (default: visible; checkbox ON = hidden)
    if (toggleNav) {
      const bottomNav = document.getElementById('bottom-nav');
      const navHidden = localStorage.getItem('nav_hidden') === 'true';

      toggleNav.checked = navHidden;
      if (navHidden && bottomNav) {
        bottomNav.classList.add('hidden');
      } else if (bottomNav) {
        document.body.classList.add('nav-visible');
      }

      toggleNav.addEventListener('change', () => {
        if (bottomNav) {
          bottomNav.classList.toggle('hidden', toggleNav.checked);
          document.body.classList.toggle('nav-visible', !toggleNav.checked);
          localStorage.setItem('nav_hidden', toggleNav.checked);
        }
      });
    } else {
      // No toggle (non-settings page) - ensure nav visible by default
      document.body.classList.add('nav-visible');
    }

    // New session button
    if (newSessionBtn) {
      newSessionBtn.addEventListener('click', () => {
        this.sessionId = null;
        sessionStorage.removeItem('chat_session_id');

        // Clear chat
        if (this.chatContainer) {
          this.chatContainer.innerHTML = this._createEmptyStateHTML();
          this.setupSuggestions();
        }

        // Close settings
        const settingsSheet = document.getElementById('settings-sheet');
        const settingsBackdrop = document.getElementById('settings-backdrop');
        if (settingsSheet) settingsSheet.classList.remove('open');
        if (settingsBackdrop) settingsBackdrop.classList.remove('open');

        this.showToast('Nowa sesja czatu', 'success');
      });
    }
  }

  // === HISTORY DRAWER ===
  setupHistoryDrawer() {
    const historyBtn = document.getElementById('history-btn');
    const navHistoryBtn = document.getElementById('nav-history');
    const drawer = document.getElementById('history-drawer');
    const backdrop = document.getElementById('history-backdrop');
    const newChatBtn = document.getElementById('new-chat-btn');

    if (!drawer) return;

    const openDrawer = () => {
      drawer.classList.add('open');
      if (backdrop) backdrop.classList.add('open');
      this.loadSessionHistory();
    };
    const closeDrawer = () => {
      drawer.classList.remove('open');
      if (backdrop) backdrop.classList.remove('open');
    };

    if (historyBtn) historyBtn.addEventListener('click', openDrawer);
    if (navHistoryBtn) navHistoryBtn.addEventListener('click', openDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);

    // "More" sheet (subpage shortcuts)
    const navMore = document.getElementById('nav-more');
    const moreSheet = document.getElementById('more-sheet');
    const moreBackdrop = document.getElementById('more-backdrop');
    if (navMore && moreSheet) {
      navMore.addEventListener('click', () => {
        moreSheet.classList.add('open');
        if (moreBackdrop) moreBackdrop.classList.add('open');
      });
      if (moreBackdrop) {
        moreBackdrop.addEventListener('click', () => {
          moreSheet.classList.remove('open');
          moreBackdrop.classList.remove('open');
        });
      }
    }

    if (newChatBtn) {
      newChatBtn.addEventListener('click', () => {
        this.sessionId = null;
        sessionStorage.removeItem('chat_session_id');
        if (this.chatContainer) {
          this.chatContainer.innerHTML = this._createEmptyStateHTML();
          this.setupSuggestions();
        }
        closeDrawer();
        this.showToast('Nowa sesja czatu', 'success');
      });
    }
  }

  async loadSessionHistory() {
    const list = document.getElementById('history-list');
    if (!list) return;

    // Show skeleton while loading
    this.showSkeleton(list, 'cards', 4);

    try {
      const response = await fetch('/chat/sessions?limit=20');
      this.hideSkeleton();
      if (!response.ok) throw new Error('Failed to load sessions');

      const sessions = await response.json();

      if (sessions.length === 0) {
        list.innerHTML = `
          <div class="mobile-empty" style="min-height: auto; padding: 2rem 1rem;">
            <div class="mobile-empty-icon">💬</div>
            <div class="mobile-empty-text">Brak zapisanych rozmów</div>
          </div>`;
        return;
      }

      list.innerHTML = sessions.map(s => {
        const date = new Date(s.updated_at).toLocaleDateString('pl', {
          day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
        });
        const title = s.title || 'Rozmowa bez tytułu';
        return `
          <div class="swipe-item">
            <div class="swipe-item-actions">
              <button class="swipe-delete-btn" data-delete-id="${s.id}" title="Usuń">🗑️</button>
            </div>
            <div class="session-item swipe-item-content" data-session-id="${s.id}">
              <div class="session-title">${this.escapeHtml(title)}</div>
              <div class="session-meta">
                <span>${date}</span>
                <span>${s.message_count} wiad.</span>
              </div>
            </div>
          </div>`;
      }).join('');

      // Enable swipe-to-reveal delete
      this.initSwipeToReveal(list);

      // Click handlers for navigation (skip if swipe just happened)
      list.querySelectorAll('.session-item').forEach(item => {
        item.addEventListener('click', (e) => {
          if (item._swipeJustDone) return;
          const sid = item.dataset.sessionId;
          window.location.href = `/m/?session_id=${sid}`;
        });
      });

      // Delete buttons (revealed by swipe)
      list.querySelectorAll('.swipe-delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sid = btn.dataset.deleteId;
          try {
            const resp = await fetch(`/chat/sessions/${sid}`, { method: 'DELETE' });
            if (resp.ok) {
              const swipeItem = btn.closest('.swipe-item');
              swipeItem.style.maxHeight = swipeItem.offsetHeight + 'px';
              swipeItem.style.transition = 'max-height 0.3s, opacity 0.3s, padding 0.3s';
              requestAnimationFrame(() => {
                swipeItem.style.maxHeight = '0';
                swipeItem.style.opacity = '0';
                swipeItem.style.overflow = 'hidden';
              });
              setTimeout(() => swipeItem.remove(), 300);
              if (this.sessionId === sid) {
                this.sessionId = null;
                sessionStorage.removeItem('chat_session_id');
              }
              this.showToast('Sesja usunięta', 'success');
            }
          } catch (err) {
            this.showToast('Nie udało się usunąć sesji', 'error');
          }
        });
      });

    } catch (error) {
      this.hideSkeleton();
      console.error('Failed to load sessions:', error);
      list.innerHTML = `
        <div class="mobile-empty" style="min-height: auto; padding: 2rem 1rem;">
          <div class="mobile-empty-text">Nie udało się załadować historii</div>
        </div>`;
    }
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  _createEmptyStateHTML() {
    return `
      <div class="empty-state" id="empty-state">
        <div class="icon">💬</div>
        <h2>Cześć!</h2>
        <p>Jestem Twoim asystentem. Pytaj o wydatki, twórz notatki, lub po prostu rozmawiaj.</p>
        <div class="suggestions"></div>
      </div>`;
  }

  // === SWIPE GESTURES ===
  setupSwipeGestures() {
    this._setupEdgeSwipe();
    this._setupPullToRefresh();
  }

  /**
   * Swipe from left edge → open history drawer
   */
  _setupEdgeSwipe() {
    const main = document.querySelector('.app-main');
    if (!main) return;

    let startX = 0, startY = 0, tracking = false;

    main.addEventListener('touchstart', (e) => {
      const touch = e.touches[0];
      if (touch.clientX < 25) {
        startX = touch.clientX;
        startY = touch.clientY;
        tracking = true;
      }
    }, { passive: true });

    main.addEventListener('touchmove', (e) => {
      if (!tracking) return;
      const touch = e.touches[0];
      const dy = Math.abs(touch.clientY - startY);
      const dx = touch.clientX - startX;
      // Cancel if vertical scroll or swipe left
      if (dy > Math.abs(dx) || dx < 0) { tracking = false; }
    }, { passive: true });

    main.addEventListener('touchend', (e) => {
      if (!tracking) return;
      tracking = false;
      const dx = e.changedTouches[0].clientX - startX;
      if (dx > 80) {
        const drawer = document.getElementById('history-drawer');
        const backdrop = document.getElementById('history-backdrop');
        if (drawer) {
          drawer.classList.add('open');
          if (backdrop) backdrop.classList.add('open');
          this.loadSessionHistory();
        }
      }
    }, { passive: true });
  }

  /**
   * Pull-to-refresh on any page (chat, notes, receipts, knowledge)
   */
  _setupPullToRefresh() {
    const scrollable = document.querySelector('.app-main');
    if (!scrollable) return;

    const ptr = document.createElement('div');
    ptr.className = 'ptr-indicator';
    ptr.innerHTML = '<div class="ptr-spinner"></div><span class="ptr-text">Pociągnij aby odświeżyć</span>';
    scrollable.insertBefore(ptr, scrollable.firstChild);

    let startY = 0, pulling = false, threshold = false;

    scrollable.addEventListener('touchstart', (e) => {
      if (scrollable.scrollTop <= 0) {
        startY = e.touches[0].clientY;
        pulling = true;
        threshold = false;
      }
    }, { passive: true });

    scrollable.addEventListener('touchmove', (e) => {
      if (!pulling) return;
      const dy = e.touches[0].clientY - startY;
      if (dy > 10 && scrollable.scrollTop <= 0) {
        ptr.classList.add('visible');
        if (dy > 70) {
          threshold = true;
          ptr.classList.add('threshold');
          ptr.querySelector('.ptr-text').textContent = 'Puść aby odświeżyć';
        } else {
          threshold = false;
          ptr.classList.remove('threshold');
          ptr.querySelector('.ptr-text').textContent = 'Pociągnij aby odświeżyć';
        }
      } else if (dy < 0) {
        pulling = false;
        ptr.classList.remove('visible', 'threshold');
      }
    }, { passive: true });

    scrollable.addEventListener('touchend', () => {
      if (!pulling) return;
      pulling = false;

      if (threshold) {
        ptr.classList.add('refreshing');
        ptr.classList.remove('threshold');
        ptr.querySelector('.ptr-text').textContent = 'Odświeżam...';
        setTimeout(() => window.location.reload(), 400);
      } else {
        ptr.classList.remove('visible', 'threshold');
      }
    }, { passive: true });
  }

  /**
   * Initialize swipe-to-reveal on items within a container.
   * Items must use .swipe-item > .swipe-item-actions + .swipe-item-content structure.
   */
  initSwipeToReveal(container) {
    if (!container) return;

    let activeSwipe = null;

    const resetSwipe = () => {
      if (activeSwipe) {
        activeSwipe.style.transform = '';
        activeSwipe.classList.remove('swiping');
        activeSwipe = null;
      }
    };

    container.addEventListener('touchstart', (e) => {
      const item = e.target.closest('.swipe-item-content');
      if (!item) return;

      if (activeSwipe && activeSwipe !== item) resetSwipe();

      item._swStartX = e.touches[0].clientX;
      item._swStartY = e.touches[0].clientY;
      item._swMoving = false;
    }, { passive: true });

    container.addEventListener('touchmove', (e) => {
      const item = e.target.closest('.swipe-item-content');
      if (!item || item._swStartX === undefined) return;

      const dx = e.touches[0].clientX - item._swStartX;
      const dy = Math.abs(e.touches[0].clientY - item._swStartY);

      // Determine horizontal swipe
      if (!item._swMoving && Math.abs(dx) > 10 && Math.abs(dx) > dy) {
        item._swMoving = true;
        item.classList.add('swiping');
      }

      if (item._swMoving && dx < 0) {
        item.style.transform = `translateX(${Math.max(-80, dx)}px)`;
        e.preventDefault();
      }
    }, { passive: false });

    container.addEventListener('touchend', (e) => {
      const item = e.target.closest('.swipe-item-content');
      if (!item) return;

      if (item._swMoving) {
        item._swipeJustDone = true;
        setTimeout(() => { item._swipeJustDone = false; }, 300);
      }

      item.classList.remove('swiping');
      const dx = e.changedTouches[0].clientX - (item._swStartX || 0);

      if (item._swMoving && dx < -40) {
        item.style.transform = 'translateX(-80px)';
        activeSwipe = item;
      } else {
        item.style.transform = '';
      }

      delete item._swStartX;
      delete item._swStartY;
      item._swMoving = false;
    }, { passive: true });

    // Reset swipe when tapping elsewhere
    document.addEventListener('touchstart', (e) => {
      if (activeSwipe && !e.target.closest('.swipe-item')) {
        resetSwipe();
      }
    }, { passive: true });
  }

  // === SUGGESTIONS ===
  setupSuggestions() {
    if (!this.input) return;

    // Bind click handlers for existing/static chips
    this._bindSuggestionChips();

    // Fetch dynamic suggestions if empty state is visible
    const emptyState = document.querySelector('.empty-state .suggestions');
    if (emptyState) {
      this.loadDynamicSuggestions(emptyState);
    }
  }

  _bindSuggestionChips() {
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
      if (chip.dataset.bound) return;
      chip.dataset.bound = '1';
      chip.addEventListener('click', () => {
        const text = chip.dataset.text || chip.textContent.trim();
        this.input.value = text;
        this.sendMessage();
      });
    });
  }

  async loadDynamicSuggestions(container) {
    // Check sessionStorage cache (refresh every 30 min)
    const cacheKey = 'chat_suggestions';
    const cacheTimeKey = 'chat_suggestions_time';
    const cached = sessionStorage.getItem(cacheKey);
    const cachedTime = parseInt(sessionStorage.getItem(cacheTimeKey) || '0', 10);

    if (cached && (Date.now() - cachedTime) < 30 * 60 * 1000) {
      try {
        this._renderSuggestions(container, JSON.parse(cached));
        return;
      } catch (e) { /* ignore invalid cache */ }
    }

    try {
      const response = await fetch('/chat/suggestions');
      if (!response.ok) return;
      const suggestions = await response.json();

      sessionStorage.setItem(cacheKey, JSON.stringify(suggestions));
      sessionStorage.setItem(cacheTimeKey, String(Date.now()));

      this._renderSuggestions(container, suggestions);
    } catch (e) {
      console.warn('Failed to load suggestions:', e);
    }
  }

  _renderSuggestions(container, suggestions) {
    if (!container || !suggestions || suggestions.length === 0) return;
    container.innerHTML = '';
    suggestions.forEach(s => {
      const chip = document.createElement('button');
      chip.className = 'suggestion-chip';
      chip.dataset.text = s.text;
      chip.textContent = `${s.icon || ''} ${s.text}`.trim();
      container.appendChild(chip);
    });
    this._bindSuggestionChips();
  }

  // === SKELETON LOADING ===
  showSkeleton(container, type = 'messages', count = 3) {
    if (!container) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'skeleton-wrapper';
    wrapper.id = 'skeleton-loading';

    if (type === 'messages') {
      for (let i = 0; i < count; i++) {
        const role = i % 2 === 0 ? 'user' : 'assistant';
        const msg = document.createElement('div');
        msg.className = `skeleton-message ${role}`;
        const widths = role === 'user' ? ['medium'] : ['long', 'medium', 'short'];
        widths.forEach(w => {
          const line = document.createElement('div');
          line.className = `skeleton skeleton-line ${w}`;
          msg.appendChild(line);
        });
        wrapper.appendChild(msg);
      }
    } else if (type === 'cards') {
      for (let i = 0; i < count; i++) {
        const card = document.createElement('div');
        card.className = 'skeleton skeleton-card';
        wrapper.appendChild(card);
      }
    }

    container.appendChild(wrapper);
    return wrapper;
  }

  hideSkeleton() {
    const el = document.getElementById('skeleton-loading');
    if (el) el.remove();
  }

  // === ONLINE STATUS ===
  setupOnlineStatus() {
    const updateStatus = () => {
      document.body.classList.toggle('offline', !navigator.onLine);
      if (!navigator.onLine) {
        this.showToast('Brak połączenia - wiadomości zostaną wysłane później', 'warning');
      }
    };

    window.addEventListener('online', async () => {
      updateStatus();
      this.showToast('Połączono - synchronizacja...', 'info');
      await this.syncOfflineActions();
    });
    window.addEventListener('offline', updateStatus);
    updateStatus();

    // Listen for offline queue events
    window.addEventListener('offlinequeue:syncstart', () => {
      document.body.classList.add('syncing');
    });

    window.addEventListener('offlinequeue:syncend', (e) => {
      document.body.classList.remove('syncing');
      const { synced, failed } = e.detail;
      if (synced > 0) {
        this.showToast(`Zsynchronizowano ${synced} wiadomości`, 'success');
      }
      if (failed > 0) {
        this.showToast(`${failed} wiadomości nie udało się wysłać`, 'warning');
      }
    });

    // Update pending badges when individual items sync
    window.addEventListener('offlinequeue:itemsynced', (e) => {
      const { id } = e.detail;
      const pendingMsg = this.chatContainer?.querySelector(`.message.pending[data-queue-id="${id}"]`);
      if (pendingMsg) {
        pendingMsg.classList.remove('pending');
        pendingMsg.classList.add('synced');
        const badge = pendingMsg.querySelector('.message-pending-badge');
        if (badge) badge.innerHTML = '<span class="pending-dot"></span> Wysłano';
        // Remove badge after 3s
        setTimeout(() => badge?.remove(), 3000);
      }
    });
  }

  /**
   * Sync offline actions when back online
   */
  async syncOfflineActions() {
    if (!window.offlineQueue) return;

    try {
      const { synced, failed } = await window.offlineQueue.processQueue();
      console.log(`Synced: ${synced}, Failed: ${failed}`);
    } catch (error) {
      console.error('Sync error:', error);
      this.showToast('Błąd synchronizacji', 'error');
    }
  }

  /**
   * Queue action for offline sending. Returns queue item ID or false on failure.
   */
  async queueOfflineAction(action) {
    if (!window.offlineQueue) {
      console.warn('OfflineQueue not available');
      return false;
    }

    try {
      const id = await window.offlineQueue.add(action);
      // Request background sync if available
      await window.offlineQueue.requestBackgroundSync();
      return id;
    } catch (error) {
      console.error('Failed to queue action:', error);
      return false;
    }
  }

  // === MESSAGE CACHE (offline viewing) ===

  static MESSAGE_CACHE_KEY = 'secondbrain_msg_cache';
  static MESSAGE_CACHE_MAX = 50;

  /**
   * Cache a message for offline viewing
   */
  _cacheMessage(content, role, sources = []) {
    try {
      const cache = JSON.parse(localStorage.getItem(MobileApp.MESSAGE_CACHE_KEY) || '[]');
      cache.push({
        content,
        role,
        sources,
        time: new Date().toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' }),
        ts: Date.now()
      });
      // Keep only the last N messages
      while (cache.length > MobileApp.MESSAGE_CACHE_MAX) cache.shift();
      localStorage.setItem(MobileApp.MESSAGE_CACHE_KEY, JSON.stringify(cache));
    } catch (e) {
      console.warn('Message cache write failed:', e);
    }
  }

  /**
   * Cache server-rendered messages on page load (for future offline views)
   */
  _cacheCurrentMessages() {
    if (!this.chatContainer) return;
    const messages = this.chatContainer.querySelectorAll('.message');
    if (messages.length === 0) return;

    const cache = [];
    messages.forEach(msg => {
      const role = msg.classList.contains('user') ? 'user' : 'assistant';
      const contentEl = msg.querySelector('.message-content');
      const raw = contentEl?.dataset?.raw || contentEl?.textContent || '';
      const timeEl = msg.querySelector('.message-time');
      cache.push({
        content: raw,
        role,
        sources: [],
        time: timeEl?.textContent || '',
        ts: Date.now()
      });
    });

    if (cache.length > 0) {
      const trimmed = cache.slice(-MobileApp.MESSAGE_CACHE_MAX);
      localStorage.setItem(MobileApp.MESSAGE_CACHE_KEY, JSON.stringify(trimmed));
    }
  }

  /**
   * Restore cached messages when offline and no server-rendered messages exist
   */
  _restoreCachedMessages() {
    if (!this.chatContainer) return;
    // Only restore if we have no server-rendered messages and we're offline
    if (this.chatContainer.querySelectorAll('.message').length > 0) return;
    if (navigator.onLine) return;

    try {
      const cache = JSON.parse(localStorage.getItem(MobileApp.MESSAGE_CACHE_KEY) || '[]');
      if (cache.length === 0) return;

      // Remove empty state
      const empty = document.querySelector('.empty-state');
      if (empty) empty.remove();

      cache.forEach(msg => {
        const el = document.createElement('div');
        el.className = `message ${msg.role} cached`;
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = this.renderMarkdown(msg.content);
        el.appendChild(contentDiv);
        const time = document.createElement('div');
        time.className = 'message-time';
        time.textContent = msg.time || '';
        el.appendChild(time);
        this.chatContainer.appendChild(el);
      });

      this.showToast('Wyświetlono ostatnie wiadomości z cache', 'info');
      this.scrollToBottom();
    } catch (e) {
      console.warn('Message cache restore failed:', e);
    }
  }

  // === LOCK SETTINGS ===
  _setupLockSettings() {
    const toggleLock = document.getElementById('toggle-lock');
    const lockOptions = document.getElementById('lock-options');
    const changePinBtn = document.getElementById('change-pin-btn');
    const toggleBiometric = document.getElementById('toggle-biometric');

    if (!toggleLock) return;

    toggleLock.checked = this.lockScreen.enabled;
    if (this.lockScreen.enabled && lockOptions) lockOptions.classList.remove('hidden');
    if (toggleBiometric) toggleBiometric.checked = this.lockScreen.biometricEnabled;

    toggleLock.addEventListener('change', () => {
      if (toggleLock.checked) {
        this.lockScreen.setupPin((success) => {
          if (!success) {
            toggleLock.checked = false;
          } else if (lockOptions) {
            lockOptions.classList.remove('hidden');
          }
        });
      } else {
        this.lockScreen.disable();
        if (lockOptions) lockOptions.classList.add('hidden');
        this.showToast('Blokada wyłączona', 'info');
      }
    });

    if (changePinBtn) {
      changePinBtn.addEventListener('click', () => {
        this.lockScreen.changePin(() => {});
      });
    }

    if (toggleBiometric) {
      toggleBiometric.addEventListener('change', async () => {
        if (toggleBiometric.checked) {
          const ok = await this.lockScreen.enableBiometric();
          if (!ok) toggleBiometric.checked = false;
        } else {
          this.lockScreen.disableBiometric();
        }
      });
    }
  }

  // === TOAST NOTIFICATIONS ===
  createToastContainer() {
    if (!document.querySelector('.toast-container')) {
      const container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
  }

  showToast(message, type = 'info', duration = 3000) {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const msgSpan = document.createElement('span');
    msgSpan.textContent = message;
    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', () => toast.remove());
    toast.appendChild(msgSpan);
    toast.appendChild(closeBtn);

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'slideDown 0.3s ease-out reverse';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }
}

/**
 * Lock Screen - PIN + optional biometric (WebAuthn) lock
 * Auto-locks after 5 min in background. Toggle in Settings.
 */
class LockScreen {
  constructor(app) {
    this.app = app;
    this.enabled = localStorage.getItem('lock_enabled') === 'true';
    this.biometricEnabled = localStorage.getItem('lock_biometric') === 'true';
    this.biometricAvailable = false;
    this.lastActivity = Date.now();
    this.lockTimeout = 5 * 60 * 1000;
    this.failedAttempts = 0;
    this.lockoutUntil = 0;
    this.digits = [];
    this.mode = null;
    this.tempPin = '';
    this.isLocked = false;
    this.onComplete = null;

    this._createDOM();
    this._checkBiometric();
    this._setupVisibility();

    if (this.enabled && this._hasPin()) {
      // Check if already unlocked in this session (survives page navigation)
      const unlockedAt = parseInt(sessionStorage.getItem('lock_unlocked_at') || '0', 10);
      const elapsed = Date.now() - unlockedAt;
      if (unlockedAt && elapsed < this.lockTimeout) {
        // Still within timeout - don't lock
        this.lastActivity = unlockedAt;
      } else {
        this.lock();
      }
    }
  }

  _hasPin() { return !!localStorage.getItem('lock_pin_hash'); }

  async _hashPin(pin) {
    const data = new TextEncoder().encode(pin + '_2brain_lock');
    const hash = await crypto.subtle.digest('SHA-256', data);
    return btoa(String.fromCharCode(...new Uint8Array(hash)));
  }

  async _checkBiometric() {
    if (window.PublicKeyCredential &&
        PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) {
      try {
        this.biometricAvailable =
          await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
      } catch (e) { /* not available */ }
    }
    const opt = document.getElementById('biometric-option');
    if (opt && this.biometricAvailable) opt.classList.remove('hidden');
  }

  _setupVisibility() {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.lastActivity = Date.now();
        sessionStorage.setItem('lock_unlocked_at', String(Date.now()));
      } else if (this.enabled && this._hasPin() && !this.isLocked) {
        const elapsed = Date.now() - this.lastActivity;
        if (elapsed > this.lockTimeout) {
          sessionStorage.removeItem('lock_unlocked_at');
          this.lock();
        }
      }
    });
    ['touchstart', 'click', 'keydown'].forEach(evt => {
      document.addEventListener(evt, () => {
        if (!this.isLocked) this.lastActivity = Date.now();
      }, { passive: true });
    });
  }

  _createDOM() {
    const el = document.createElement('div');
    el.id = 'lock-screen';
    el.className = 'lock-screen hidden';
    el.innerHTML = `
      <div class="lock-content">
        <div class="lock-icon">🧠</div>
        <div class="lock-title" id="lock-title">Podaj PIN</div>
        <div class="lock-dots" id="lock-dots">
          <span class="lock-dot"></span><span class="lock-dot"></span>
          <span class="lock-dot"></span><span class="lock-dot"></span>
        </div>
        <div class="lock-error hidden" id="lock-error"></div>
        <div class="lock-pad">
          <button class="lock-key" data-key="1">1</button>
          <button class="lock-key" data-key="2">2</button>
          <button class="lock-key" data-key="3">3</button>
          <button class="lock-key" data-key="4">4</button>
          <button class="lock-key" data-key="5">5</button>
          <button class="lock-key" data-key="6">6</button>
          <button class="lock-key" data-key="7">7</button>
          <button class="lock-key" data-key="8">8</button>
          <button class="lock-key" data-key="9">9</button>
          <button class="lock-key lock-key-bio" id="lock-bio-btn" data-key="bio">👆</button>
          <button class="lock-key" data-key="0">0</button>
          <button class="lock-key lock-key-del" data-key="del">⌫</button>
        </div>
        <button class="lock-cancel hidden" id="lock-cancel">Anuluj</button>
      </div>`;
    document.body.appendChild(el);

    el.querySelectorAll('.lock-key').forEach(key => {
      key.addEventListener('click', () => this._onKey(key.dataset.key));
    });
    document.getElementById('lock-cancel').addEventListener('click', () => {
      if (this.mode !== 'unlock') {
        this._hide();
        if (this.onComplete) this.onComplete(false);
      }
    });
  }

  _show(title, mode, showCancel = false) {
    this.mode = mode;
    this.digits = [];
    this._updateDots();
    document.getElementById('lock-title').textContent = title;
    document.getElementById('lock-error').classList.add('hidden');
    document.getElementById('lock-cancel').classList.toggle('hidden', !showCancel);

    const bioBtn = document.getElementById('lock-bio-btn');
    if (bioBtn) {
      bioBtn.style.visibility =
        (mode === 'unlock' && this.biometricEnabled && this.biometricAvailable)
          ? 'visible' : 'hidden';
    }

    document.getElementById('lock-screen').classList.remove('hidden');
    this.isLocked = (mode === 'unlock');
  }

  _hide() {
    document.getElementById('lock-screen').classList.add('hidden');
    this.isLocked = false;
    this.mode = null;
    this.digits = [];
  }

  _updateDots() {
    document.querySelectorAll('#lock-dots .lock-dot').forEach((dot, i) => {
      dot.classList.toggle('filled', i < this.digits.length);
    });
  }

  _showError(msg) {
    const err = document.getElementById('lock-error');
    err.textContent = msg;
    err.classList.remove('hidden');
    const dots = document.getElementById('lock-dots');
    dots.classList.add('shake');
    setTimeout(() => dots.classList.remove('shake'), 500);
  }

  async _onKey(key) {
    if (key === 'bio') { await this._tryBiometric(); return; }
    if (key === 'del') { this.digits.pop(); this._updateDots(); return; }

    if (this.lockoutUntil > Date.now()) {
      this._showError(`Zaczekaj ${Math.ceil((this.lockoutUntil - Date.now()) / 1000)}s`);
      return;
    }

    this.digits.push(key);
    this._updateDots();
    if (navigator.vibrate) navigator.vibrate(10);

    if (this.digits.length < 4) return;
    const pin = this.digits.join('');

    if (this.mode === 'unlock') {
      await this._verifyPin(pin);
    } else if (this.mode === 'setup' || this.mode === 'change') {
      this.tempPin = pin;
      this.digits = [];
      this._updateDots();
      this.mode = this.mode === 'change' ? 'change-confirm' : 'confirm';
      document.getElementById('lock-title').textContent = 'Potwierdź PIN';
      document.getElementById('lock-error').classList.add('hidden');
    } else if (this.mode === 'confirm' || this.mode === 'change-confirm') {
      if (pin === this.tempPin) {
        const hash = await this._hashPin(pin);
        localStorage.setItem('lock_pin_hash', hash);
        localStorage.setItem('lock_enabled', 'true');
        this.enabled = true;
        this._hide();
        this.app.showToast('PIN ustawiony', 'success');
        if (this.onComplete) this.onComplete(true);
      } else {
        this.digits = [];
        this._updateDots();
        this._showError('PIN nie pasuje, spróbuj ponownie');
        this.mode = this.mode === 'change-confirm' ? 'change' : 'setup';
        document.getElementById('lock-title').textContent =
          this.mode === 'change' ? 'Nowy PIN' : 'Ustaw PIN';
        this.tempPin = '';
      }
    }
  }

  async _verifyPin(pin) {
    const hash = await this._hashPin(pin);
    if (hash === localStorage.getItem('lock_pin_hash')) {
      this.failedAttempts = 0;
      this._hide();
      this.lastActivity = Date.now();
      sessionStorage.setItem('lock_unlocked_at', String(Date.now()));
    } else {
      this.failedAttempts++;
      this.digits = [];
      this._updateDots();
      if (this.failedAttempts >= 5) {
        this.lockoutUntil = Date.now() + 30000;
        this._showError('Zbyt wiele prób. Zaczekaj 30s');
      } else {
        this._showError(`Zły PIN (${5 - this.failedAttempts} prób)`);
      }
    }
  }

  lock() {
    this._show('Podaj PIN', 'unlock');
    if (this.biometricEnabled && this.biometricAvailable) {
      setTimeout(() => this._tryBiometric(), 300);
    }
  }

  async _tryBiometric() {
    const credIdB64 = localStorage.getItem('lock_credential_id');
    if (!credIdB64) return;
    try {
      const credId = Uint8Array.from(atob(credIdB64), c => c.charCodeAt(0));
      await navigator.credentials.get({
        publicKey: {
          challenge: crypto.getRandomValues(new Uint8Array(32)),
          allowCredentials: [{ id: credId, type: 'public-key', transports: ['internal'] }],
          userVerification: 'required',
          timeout: 60000,
        }
      });
      this.failedAttempts = 0;
      this._hide();
      this.lastActivity = Date.now();
      sessionStorage.setItem('lock_unlocked_at', String(Date.now()));
    } catch (e) {
      console.log('Biometric cancelled or failed');
    }
  }

  setupPin(callback) {
    this.onComplete = callback;
    this._show('Ustaw PIN', 'setup', true);
  }

  changePin(callback) {
    this.onComplete = callback;
    this._show('Nowy PIN', 'change', true);
  }

  disable() {
    localStorage.removeItem('lock_pin_hash');
    localStorage.removeItem('lock_enabled');
    localStorage.removeItem('lock_biometric');
    localStorage.removeItem('lock_credential_id');
    sessionStorage.removeItem('lock_unlocked_at');
    this.enabled = false;
    this.biometricEnabled = false;
  }

  async enableBiometric() {
    try {
      const credential = await navigator.credentials.create({
        publicKey: {
          challenge: crypto.getRandomValues(new Uint8Array(32)),
          rp: { name: 'Second Brain', id: window.location.hostname },
          user: {
            id: crypto.getRandomValues(new Uint8Array(16)),
            name: 'user@secondbrain',
            displayName: 'Second Brain',
          },
          pubKeyCredParams: [
            { alg: -7, type: 'public-key' },
            { alg: -257, type: 'public-key' },
          ],
          authenticatorSelection: {
            authenticatorAttachment: 'platform',
            userVerification: 'required',
            residentKey: 'preferred',
          },
          timeout: 60000,
        }
      });
      localStorage.setItem('lock_credential_id',
        btoa(String.fromCharCode(...new Uint8Array(credential.rawId))));
      localStorage.setItem('lock_biometric', 'true');
      this.biometricEnabled = true;
      this.app.showToast('Biometria włączona', 'success');
      return true;
    } catch (e) {
      console.error('Biometric setup failed:', e);
      this.app.showToast('Nie udało się włączyć biometrii', 'error');
      return false;
    }
  }

  disableBiometric() {
    localStorage.removeItem('lock_credential_id');
    localStorage.removeItem('lock_biometric');
    this.biometricEnabled = false;
  }
}

/**
 * Push Notifications Manager
 * Handles Web Push subscription and notification permissions
 */
class PushManager {
  constructor() {
    this.registration = null;
    this.subscription = null;
    this.btn = document.getElementById('push-toggle');
  }

  async init() {
    if (!('PushManager' in window)) {
      console.log('Push not supported in this browser');
      this.updateUI(false, true);
      return false;
    }

    if (!('serviceWorker' in navigator)) {
      console.log('Service Worker not supported');
      this.updateUI(false, true);
      return false;
    }

    try {
      this.registration = await navigator.serviceWorker.ready;
      this.subscription = await this.registration.pushManager.getSubscription();
      this.updateUI(!!this.subscription);
      this.setupButton();
      return true;
    } catch (error) {
      console.error('Push init error:', error);
      this.updateUI(false, true);
      return false;
    }
  }

  setupButton() {
    if (!this.btn) return;

    this.btn.addEventListener('click', async () => {
      if (this.subscription) {
        await this.unsubscribe();
      } else {
        await this.subscribe();
      }
    });
  }

  async subscribe() {
    try {
      // Get VAPID public key from server
      const response = await fetch('/api/push/vapid-key');
      if (!response.ok) {
        if (response.status === 503) {
          window.app?.showToast('Powiadomienia push nie są skonfigurowane', 'warning');
        }
        return false;
      }

      const { publicKey } = await response.json();

      // Request notification permission
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        window.app?.showToast('Brak zgody na powiadomienia', 'warning');
        return false;
      }

      // Subscribe to push
      this.subscription = await this.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.urlBase64ToUint8Array(publicKey)
      });

      // Send subscription to server
      const subResponse = await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.subscription.toJSON())
      });

      if (subResponse.ok) {
        this.updateUI(true);
        window.app?.showToast('Powiadomienia włączone', 'success');
        return true;
      } else {
        throw new Error('Subscription save failed');
      }
    } catch (error) {
      console.error('Subscribe error:', error);
      window.app?.showToast('Nie udało się włączyć powiadomień', 'error');
      return false;
    }
  }

  async unsubscribe() {
    if (!this.subscription) return false;

    try {
      // Unsubscribe from push
      await this.subscription.unsubscribe();

      // Remove from server
      await fetch('/api/push/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: this.subscription.endpoint })
      });

      this.subscription = null;
      this.updateUI(false);
      window.app?.showToast('Powiadomienia wyłączone', 'info');
      return true;
    } catch (error) {
      console.error('Unsubscribe error:', error);
      window.app?.showToast('Nie udało się wyłączyć powiadomień', 'error');
      return false;
    }
  }

  isSubscribed() {
    return !!this.subscription;
  }

  updateUI(subscribed, disabled = false) {
    if (!this.btn) return;

    const icon = this.btn.querySelector('span');
    if (disabled) {
      this.btn.disabled = true;
      this.btn.style.opacity = '0.5';
      if (icon) icon.textContent = '🔕';
    } else if (subscribed) {
      this.btn.classList.add('active');
      if (icon) icon.textContent = '🔔';
      this.btn.title = 'Wyłącz powiadomienia';
    } else {
      this.btn.classList.remove('active');
      if (icon) icon.textContent = '🔕';
      this.btn.title = 'Włącz powiadomienia';
    }
  }

  // Helper: Convert VAPID public key from base64 to Uint8Array
  urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, '+')
      .replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
  window.app = new MobileApp();

  // Initialize push manager after service worker is ready
  window.pushManager = new PushManager();
  window.pushManager.init();
});

// Service Worker registration (for PWA)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const registration = await navigator.serviceWorker.register('/sw.js', {
        scope: '/'
      });
      console.log('SW registered:', registration.scope);

      // Listen for messages from Service Worker
      navigator.serviceWorker.addEventListener('message', async (event) => {
        const { type } = event.data || {};

        if (type === 'SYNC_PENDING') {
          console.log('Background sync triggered by SW');

          // Process offline queue
          if (window.offlineQueue) {
            const result = await window.offlineQueue.processQueue();

            // Send response back to SW if port available
            if (event.ports && event.ports[0]) {
              event.ports[0].postMessage({
                success: true,
                synced: result.synced,
                failed: result.failed
              });
            }
          }
        }
      });
    } catch (error) {
      console.log('SW registration skipped (not available yet):', error.message);
    }
  });
}
