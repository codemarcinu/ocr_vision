/**
 * Second Brain - Offline Actions Queue
 *
 * IndexedDB-based queue for storing actions when offline.
 * Syncs automatically when connection is restored.
 */

class OfflineQueue {
  constructor() {
    this.dbName = 'secondbrain-offline';
    this.dbVersion = 1;
    this.storeName = 'pending-actions';
    this.db = null;
    this.isSyncing = false;
  }

  /**
   * Initialize IndexedDB
   */
  async init() {
    if (this.db) return true;

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.dbVersion);

      request.onerror = () => {
        console.error('IndexedDB error:', request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        this.db = request.result;
        console.log('OfflineQueue: IndexedDB initialized');
        resolve(true);
      };

      request.onupgradeneeded = (event) => {
        const db = event.target.result;

        // Create object store if not exists
        if (!db.objectStoreNames.contains(this.storeName)) {
          const store = db.createObjectStore(this.storeName, {
            keyPath: 'id',
            autoIncrement: true
          });
          // Index by timestamp for ordered retrieval
          store.createIndex('timestamp', 'timestamp', { unique: false });
          // Index by type for filtering
          store.createIndex('type', 'type', { unique: false });
        }
      };
    });
  }

  /**
   * Add action to the queue
   * @param {Object} action - Action to queue
   * @param {string} action.type - Action type (chat, note, receipt, etc.)
   * @param {string} action.url - API endpoint URL
   * @param {string} action.method - HTTP method (POST, PUT, DELETE)
   * @param {Object} action.body - Request body (will be JSON stringified)
   * @param {Object} action.headers - Optional request headers
   * @param {string} action.displayText - Text to show in pending UI
   */
  async add(action) {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readwrite');
    const store = tx.objectStore(this.storeName);

    const item = {
      type: action.type || 'generic',
      url: action.url,
      method: action.method || 'POST',
      body: action.body,
      headers: action.headers || { 'Content-Type': 'application/json' },
      displayText: action.displayText || 'Oczekująca akcja',
      timestamp: Date.now(),
      retries: 0,
      maxRetries: 3
    };

    return new Promise((resolve, reject) => {
      const request = store.add(item);
      request.onsuccess = () => {
        console.log('OfflineQueue: Added action', item.type, request.result);
        this.notifyPendingCount();
        resolve(request.result);
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get all pending actions
   */
  async getAll() {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readonly');
    const store = tx.objectStore(this.storeName);
    const index = store.index('timestamp');

    return new Promise((resolve, reject) => {
      const request = index.getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get pending count
   */
  async getCount() {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readonly');
    const store = tx.objectStore(this.storeName);

    return new Promise((resolve, reject) => {
      const request = store.count();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Remove action from queue
   */
  async remove(id) {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readwrite');
    const store = tx.objectStore(this.storeName);

    return new Promise((resolve, reject) => {
      const request = store.delete(id);
      request.onsuccess = () => {
        this.notifyPendingCount();
        resolve();
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Update action (e.g., increment retries)
   */
  async update(id, updates) {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readwrite');
    const store = tx.objectStore(this.storeName);

    return new Promise((resolve, reject) => {
      const getRequest = store.get(id);
      getRequest.onsuccess = () => {
        const item = getRequest.result;
        if (!item) {
          reject(new Error('Item not found'));
          return;
        }

        const updated = { ...item, ...updates };
        const putRequest = store.put(updated);
        putRequest.onsuccess = () => resolve(updated);
        putRequest.onerror = () => reject(putRequest.error);
      };
      getRequest.onerror = () => reject(getRequest.error);
    });
  }

  /**
   * Clear all pending actions
   */
  async clear() {
    await this.init();

    const tx = this.db.transaction(this.storeName, 'readwrite');
    const store = tx.objectStore(this.storeName);

    return new Promise((resolve, reject) => {
      const request = store.clear();
      request.onsuccess = () => {
        this.notifyPendingCount();
        resolve();
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Process all pending actions
   * Called when coming back online
   */
  async processQueue() {
    if (this.isSyncing) {
      console.log('OfflineQueue: Already syncing');
      return { synced: 0, failed: 0 };
    }

    if (!navigator.onLine) {
      console.log('OfflineQueue: Still offline, skipping sync');
      return { synced: 0, failed: 0 };
    }

    this.isSyncing = true;
    this.notifySyncStart();

    const items = await this.getAll();
    let synced = 0;
    let failed = 0;

    console.log(`OfflineQueue: Processing ${items.length} pending actions`);

    for (const item of items) {
      try {
        const response = await fetch(item.url, {
          method: item.method,
          headers: item.headers,
          body: typeof item.body === 'string' ? item.body : JSON.stringify(item.body)
        });

        if (response.ok) {
          await this.remove(item.id);
          synced++;
          console.log('OfflineQueue: Synced', item.type, item.id);
        } else if (response.status >= 400 && response.status < 500) {
          // Client error - don't retry, remove
          console.warn('OfflineQueue: Client error, removing', item.type, response.status);
          await this.remove(item.id);
          failed++;
        } else {
          // Server error - retry later
          await this.incrementRetry(item);
          failed++;
        }
      } catch (error) {
        console.warn('OfflineQueue: Sync error', item.type, error.message);
        await this.incrementRetry(item);
        failed++;
      }
    }

    this.isSyncing = false;
    this.notifySyncEnd(synced, failed);

    return { synced, failed };
  }

  /**
   * Increment retry count, remove if max exceeded
   */
  async incrementRetry(item) {
    const newRetries = item.retries + 1;

    if (newRetries >= item.maxRetries) {
      console.warn('OfflineQueue: Max retries exceeded, removing', item.type, item.id);
      await this.remove(item.id);
    } else {
      await this.update(item.id, { retries: newRetries });
    }
  }

  /**
   * Notify UI about pending count change
   */
  async notifyPendingCount() {
    const count = await this.getCount();

    // Dispatch custom event
    window.dispatchEvent(new CustomEvent('offlinequeue:count', {
      detail: { count }
    }));

    // Update badge in UI if exists
    const badge = document.getElementById('offline-badge');
    if (badge) {
      if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }
  }

  /**
   * Notify sync started
   */
  notifySyncStart() {
    window.dispatchEvent(new CustomEvent('offlinequeue:syncstart'));
    document.body.classList.add('syncing');
  }

  /**
   * Notify sync ended
   */
  notifySyncEnd(synced, failed) {
    window.dispatchEvent(new CustomEvent('offlinequeue:syncend', {
      detail: { synced, failed }
    }));
    document.body.classList.remove('syncing');
  }

  /**
   * Request Background Sync if available
   */
  async requestBackgroundSync() {
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
      try {
        const registration = await navigator.serviceWorker.ready;
        await registration.sync.register('sync-pending-actions');
        console.log('OfflineQueue: Background sync registered');
      } catch (error) {
        console.log('OfflineQueue: Background sync not available', error.message);
      }
    }
  }
}

// Singleton instance
window.offlineQueue = new OfflineQueue();

// Auto-init when DOM ready
document.addEventListener('DOMContentLoaded', async () => {
  await window.offlineQueue.init();
  await window.offlineQueue.notifyPendingCount();
});
