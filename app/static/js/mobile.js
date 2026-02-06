/**
 * Second Brain - Mobile PWA Core
 * Chat-centric interface for mobile devices
 */

class MobileApp {
  constructor() {
    this.input = document.getElementById('chat-input');
    this.sendBtn = document.getElementById('send-btn');
    this.chatContainer = document.querySelector('.chat-container');
    this.sessionId = window.initialSessionId || localStorage.getItem('chat_session_id') || null;
    this.isProcessing = false;

    // Media recorder for voice
    this.mediaRecorder = null;
    this.audioChunks = [];

    this.init();
  }

  init() {
    this.setupInput();
    this.setupQuickActions();
    this.setupSettings();
    this.setupOnlineStatus();
    this.setupSuggestions();
    this.createToastContainer();

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

  async sendMessage() {
    const text = this.input.value.trim();
    if (!text || this.isProcessing) return;

    this.isProcessing = true;
    this.sendBtn.disabled = true;

    // Clear input
    this.input.value = '';
    this.input.style.height = 'auto';

    // Hide empty state
    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();

    // Add user message
    this.addMessage(text, 'user');

    // If offline, queue the message
    if (!navigator.onLine) {
      await this.handleOfflineMessage(text);
      this.isProcessing = false;
      this.sendBtn.disabled = false;
      return;
    }

    // Show typing indicator
    const typingId = this.showTyping();

    try {
      const response = await this.callChat(text);
      this.hideTyping(typingId);

      // Add assistant response
      this.addMessage(response.answer, 'assistant', response.sources || []);

      // Update session ID
      if (response.session_id) {
        this.sessionId = response.session_id;
        localStorage.setItem('chat_session_id', this.sessionId);
      }

    } catch (error) {
      console.error('Chat error:', error);
      this.hideTyping(typingId);

      // If network error, queue for later
      if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
        await this.handleOfflineMessage(text);
      } else {
        this.addMessage('Przepraszam, wystąpił błąd. Spróbuj ponownie.', 'assistant');
        this.showToast('Błąd połączenia z serwerem', 'error');
      }
    } finally {
      this.isProcessing = false;
      this.sendBtn.disabled = false;
    }
  }

  /**
   * Handle message when offline - queue and show placeholder
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
      this.addMessage(
        '📡 *Wiadomość zapisana offline*\n\nOdpowiedź pojawi się po połączeniu z internetem.',
        'assistant'
      );
      this.showToast('Wiadomość zapisana - wyślę gdy będzie połączenie', 'info');
    } else {
      this.addMessage('❌ Nie udało się zapisać wiadomości.', 'assistant');
    }
  }

  async callChat(message) {
    const payload = {
      message: message,
    };
    if (this.sessionId) {
      payload.session_id = this.sessionId;
    }

    const response = await fetch('/chat/message', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  addMessage(content, role, sources = []) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    // Content
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = this.renderMarkdown(content);
    msg.appendChild(contentDiv);

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
  }

  renderMarkdown(text) {
    // Basic markdown rendering
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank">$1</a>')
      .replace(/\n/g, '<br>');
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
    // Camera button
    const cameraBtn = document.querySelector('[data-action="camera"]');
    if (cameraBtn) {
      cameraBtn.addEventListener('click', () => this.openCamera());
    }

    // Voice button
    const voiceBtn = document.querySelector('[data-action="voice"]');
    if (voiceBtn) {
      voiceBtn.addEventListener('click', () => this.toggleVoice());
    }
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

    input.onchange = (e) => {
      if (e.target.files[0]) {
        this.handleFileUpload(e.target.files[0]);
      }
    };
    input.click();
  }

  async handleFileUpload(file) {
    if (!file) return;

    // Check if offline - files can't be queued easily
    if (!navigator.onLine) {
      this.showToast('Brak połączenia - zdjęcia wymagają internetu', 'warning');
      this.addMessage(
        '📡 *Brak połączenia*\n\nZdjęcia paragonów wymagają połączenia z internetem. Spróbuj ponownie gdy będziesz online.',
        'assistant'
      );
      return;
    }

    // Show uploading message
    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();

    this.addMessage(`📷 Przesyłam: ${file.name}...`, 'user');
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

          this.addMessage(
            `✅ **Paragon przetworzony!**\n\n` +
            `**${store}** - ${total.toFixed(2)} PLN\n` +
            `Pozycji: ${itemsCount}` +
            (result.needs_review ? '\n\n⚠️ Wymaga weryfikacji' : ''),
            'assistant'
          );
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
      this.addMessage('❌ Nie udało się przetworzyć paragonu: ' + (error.message || 'Nieznany błąd'), 'assistant');
      this.showToast('Błąd przetwarzania', 'error');
    }
  }

  // === VOICE RECORDING ===
  async toggleVoice() {
    const btn = document.querySelector('[data-action="voice"]');
    const quickActions = document.getElementById('quick-actions');

    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      // Stop recording
      this.mediaRecorder.stop();
      quickActions?.classList.remove('recording');
    } else {
      // Start recording
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.mediaRecorder = new MediaRecorder(stream);
        this.audioChunks = [];

        this.mediaRecorder.ondataavailable = (e) => {
          this.audioChunks.push(e.data);
        };

        this.mediaRecorder.onstop = async () => {
          const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
          stream.getTracks().forEach(track => track.stop());
          await this.sendVoiceMessage(blob);
        };

        this.mediaRecorder.start();
        quickActions?.classList.add('recording');
        this.showToast('Nagrywanie... Kliknij ponownie aby zakończyć', 'info');
      } catch (error) {
        console.error('Microphone access denied:', error);
        this.showToast('Brak dostępu do mikrofonu', 'error');
      }
    }
  }

  async sendVoiceMessage(audioBlob) {
    const empty = document.querySelector('.empty-state');
    if (empty) empty.remove();

    this.addMessage('🎤 Przetwarzam nagranie...', 'user');
    const typingId = this.showTyping();

    try {
      const formData = new FormData();
      formData.append('audio', audioBlob, 'voice.webm');

      const response = await fetch('/transcriptions/quick', {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        const text = result.text || result.transcription;

        if (text) {
          // Update the "processing" message with actual transcription
          const messages = this.chatContainer.querySelectorAll('.message.user');
          const lastUserMsg = messages[messages.length - 1];
          if (lastUserMsg) {
            lastUserMsg.querySelector('.message-content').innerHTML = this.renderMarkdown(text);
          }

          this.hideTyping(typingId);

          // Now send as chat message
          this.input.value = text;
          await this.sendMessage();
        } else {
          throw new Error('No transcription');
        }
      } else {
        throw new Error('Transcription failed');
      }
    } catch (error) {
      console.error('Voice error:', error);
      this.hideTyping(typingId);
      this.showToast('Nie udało się przetworzyć nagrania', 'error');
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

    // Bottom nav toggle
    if (toggleNav) {
      const bottomNav = document.getElementById('bottom-nav');
      const navVisible = localStorage.getItem('nav_visible') === 'true';

      toggleNav.checked = navVisible;
      if (navVisible && bottomNav) {
        bottomNav.classList.remove('hidden');
        document.body.classList.add('nav-visible');
      }

      toggleNav.addEventListener('change', () => {
        if (bottomNav) {
          bottomNav.classList.toggle('hidden', !toggleNav.checked);
          document.body.classList.toggle('nav-visible', toggleNav.checked);
          localStorage.setItem('nav_visible', toggleNav.checked);
        }
      });
    }

    // New session button
    if (newSessionBtn) {
      newSessionBtn.addEventListener('click', () => {
        this.sessionId = null;
        localStorage.removeItem('chat_session_id');

        // Clear chat
        if (this.chatContainer) {
          this.chatContainer.innerHTML = `
            <div class="empty-state" id="empty-state">
              <div class="icon">💬</div>
              <h2>Cześć!</h2>
              <p>Jestem Twoim asystentem. Pytaj o wydatki, twórz notatki, lub po prostu rozmawiaj.</p>
              <div class="suggestions">
                <button class="suggestion-chip" data-text="Ile wydałem w tym miesiącu?">Ile wydałem w tym miesiącu?</button>
                <button class="suggestion-chip" data-text="Zanotuj: kupić mleko">Zanotuj: kupić mleko</button>
                <button class="suggestion-chip" data-text="Podsumuj ostatnie artykuły">Podsumuj ostatnie artykuły</button>
                <button class="suggestion-chip" data-text="Co nowego w AI?">Co nowego w AI?</button>
              </div>
            </div>
          `;
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

  // === SUGGESTIONS ===
  setupSuggestions() {
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const text = chip.dataset.text || chip.textContent;
        this.input.value = text;
        this.sendMessage();
      });
    });
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
   * Queue action for offline sending
   */
  async queueOfflineAction(action) {
    if (!window.offlineQueue) {
      console.warn('OfflineQueue not available');
      return false;
    }

    try {
      await window.offlineQueue.add(action);
      // Request background sync if available
      await window.offlineQueue.requestBackgroundSync();
      return true;
    } catch (error) {
      console.error('Failed to queue action:', error);
      return false;
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
    toast.innerHTML = `
      <span>${message}</span>
      <button class="toast-close">×</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.remove();
    });

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'slideDown 0.3s ease-out reverse';
      setTimeout(() => toast.remove(), 300);
    }, duration);
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
