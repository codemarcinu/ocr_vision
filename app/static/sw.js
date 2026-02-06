/**
 * Second Brain - Service Worker
 * Handles offline support and caching for PWA
 */

const CACHE_VERSION = 'v2';
const STATIC_CACHE = `static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `dynamic-${CACHE_VERSION}`;

// Assets to precache (app shell)
const STATIC_ASSETS = [
  '/m/',
  '/static/css/mobile.css',
  '/static/js/offline-queue.js',
  '/static/js/mobile.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/offline.html'
];

// CDN assets to cache on first use
const CDN_HOSTS = [
  'cdn.jsdelivr.net',
  'unpkg.com'
];

// Install event - precache static assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        console.log('[SW] Precaching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .catch((err) => {
        console.warn('[SW] Precache failed:', err);
      })
  );
  // Activate immediately
  self.skipWaiting();
});

// Activate event - cleanup old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== DYNAMIC_CACHE)
          .map((key) => {
            console.log('[SW] Deleting old cache:', key);
            return caches.delete(key);
          })
      );
    })
  );
  // Take control of all pages immediately
  self.clients.claim();
});

// Fetch event - cache strategies
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip chrome-extension and other non-http(s) URLs
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // API calls - network first, fallback to cache
  if (url.pathname.startsWith('/chat/') ||
      url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/transcriptions/') ||
      url.pathname.startsWith('/process-receipt')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Mobile UI pages - network first with offline fallback
  if (url.pathname.startsWith('/m/')) {
    event.respondWith(networkFirstWithOffline(request));
    return;
  }

  // Static assets - cache first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // CDN assets - cache first
  if (CDN_HOSTS.some(host => url.host.includes(host))) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Default: network first
  event.respondWith(networkFirst(request));
});

/**
 * Cache-first strategy
 * Best for static assets that don't change often
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    console.warn('[SW] Cache-first fetch failed:', request.url);
    return new Response('Offline', { status: 503 });
  }
}

/**
 * Network-first strategy
 * Best for API calls and dynamic content
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    console.warn('[SW] Network-first falling back to cache:', request.url);
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    return new Response(
      JSON.stringify({ error: 'Offline', detail: 'Brak połączenia z internetem' }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' }
      }
    );
  }
}

/**
 * Network-first with offline page fallback
 * Best for navigation requests
 */
async function networkFirstWithOffline(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    console.warn('[SW] Network failed, trying cache:', request.url);

    // Try cache first
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }

    // Fallback to offline page for navigation requests
    if (request.mode === 'navigate') {
      const offlinePage = await caches.match('/offline.html');
      if (offlinePage) {
        return offlinePage;
      }
    }

    return new Response('Offline', { status: 503 });
  }
}

// Push notification handling
self.addEventListener('push', (event) => {
  const data = event.data?.json() || {
    title: 'Second Brain',
    body: 'Nowe powiadomienie'
  };

  const options = {
    body: data.body,
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-72.png',
    tag: data.tag || 'default',
    data: { url: data.url || '/m/' },
    vibrate: [100, 50, 100],
    actions: [
      { action: 'open', title: 'Otwórz' },
      { action: 'close', title: 'Zamknij' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Notification click handling
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'close') {
    return;
  }

  const url = event.notification.data?.url || '/m/';

  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((clientList) => {
      // Focus existing window if open
      for (const client of clientList) {
        if (client.url.includes('/m/') && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open new window
      return clients.openWindow(url);
    })
  );
});

// Background sync for offline actions (Chrome only)
self.addEventListener('sync', (event) => {
  console.log('[SW] Sync event:', event.tag);

  if (event.tag === 'sync-pending-actions') {
    event.waitUntil(syncPendingActions());
  }
});

async function syncPendingActions() {
  console.log('[SW] Background sync triggered');

  // Notify all clients to process their offline queues
  const allClients = await self.clients.matchAll({ type: 'window' });

  if (allClients.length === 0) {
    console.log('[SW] No clients available for sync');
    return;
  }

  // Send sync message to each client
  const syncPromises = allClients.map(client => {
    return new Promise((resolve) => {
      // Set up a one-time listener for sync completion
      const channel = new MessageChannel();
      channel.port1.onmessage = (event) => {
        console.log('[SW] Sync response from client:', event.data);
        resolve(event.data);
      };

      // Send sync request with response port
      client.postMessage({ type: 'SYNC_PENDING' }, [channel.port2]);

      // Timeout after 30 seconds
      setTimeout(() => resolve({ timeout: true }), 30000);
    });
  });

  const results = await Promise.all(syncPromises);
  console.log('[SW] Sync completed:', results);
}

// Message handler for communication with main thread
self.addEventListener('message', (event) => {
  const { type, data } = event.data || {};

  switch (type) {
    case 'SKIP_WAITING':
      self.skipWaiting();
      break;

    case 'GET_VERSION':
      event.ports[0]?.postMessage({ version: CACHE_VERSION });
      break;

    case 'CLEAR_CACHE':
      caches.keys().then(keys => {
        Promise.all(keys.map(key => caches.delete(key)));
      });
      break;

    default:
      console.log('[SW] Unknown message type:', type);
  }
});

console.log('[SW] Service Worker loaded, version:', CACHE_VERSION);
