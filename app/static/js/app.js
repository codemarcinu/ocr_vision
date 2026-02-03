/* Second Brain - Global JS */

(function() {
    'use strict';

    // ===== Dark Mode =====
    function initDarkMode() {
        const toggle = document.getElementById('dark-mode-toggle');
        if (!toggle) return;

        const saved = localStorage.getItem('sb-theme');
        if (saved) {
            document.documentElement.setAttribute('data-bs-theme', saved);
            updateToggleIcon(toggle, saved);
        }

        toggle.addEventListener('click', function() {
            const current = document.documentElement.getAttribute('data-bs-theme') || 'light';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-bs-theme', next);
            localStorage.setItem('sb-theme', next);
            updateToggleIcon(toggle, next);

            // Dispatch event for charts to update
            document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: next }}));
        });
    }

    function updateToggleIcon(toggle, theme) {
        toggle.innerHTML = theme === 'dark'
            ? '<i class="bi bi-sun"></i>'
            : '<i class="bi bi-moon-stars"></i>';
    }

    // ===== Sidebar Mobile Toggle =====
    function initSidebar() {
        const toggle = document.querySelector('.sidebar-toggle');
        const sidebar = document.querySelector('.sidebar');
        const backdrop = document.querySelector('.sidebar-backdrop');
        if (!toggle || !sidebar) return;

        toggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
            if (backdrop) backdrop.classList.toggle('show');
        });

        if (backdrop) {
            backdrop.addEventListener('click', function() {
                sidebar.classList.remove('show');
                backdrop.classList.remove('show');
            });
        }
    }

    // ===== Active Nav Link =====
    function initActiveNav() {
        const path = window.location.pathname;
        document.querySelectorAll('.sidebar-link').forEach(function(link) {
            const href = link.getAttribute('href');
            if (href && path.startsWith(href) && href !== '/app/') {
                link.classList.add('active');
            } else if (href === '/app/' && path === '/app/') {
                link.classList.add('active');
            }
        });
    }

    // ===== Toast Notifications =====
    window.showToast = function(message, type) {
        type = type || 'info';
        const container = document.getElementById('toast-container');
        if (!container) return;

        const bgClass = {
            'success': 'text-bg-success',
            'error': 'text-bg-danger',
            'warning': 'text-bg-warning',
            'info': 'text-bg-primary'
        }[type] || 'text-bg-primary';

        const id = 'toast-' + Date.now();
        const html = '<div id="' + id + '" class="toast ' + bgClass + '" role="alert">' +
            '<div class="d-flex">' +
            '<div class="toast-body">' + message + '</div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
            '</div></div>';

        container.insertAdjacentHTML('beforeend', html);
        var el = document.getElementById(id);
        var toast = new bootstrap.Toast(el, { delay: 4000 });
        toast.show();
        el.addEventListener('hidden.bs.toast', function() { el.remove(); });
    };

    // ===== HTMX Events =====
    function initHtmx() {
        // Toast from server response
        document.body.addEventListener('showToast', function(evt) {
            if (evt.detail) {
                showToast(evt.detail.message, evt.detail.type);
            }
        });

        // Error handling
        document.body.addEventListener('htmx:responseError', function(evt) {
            var status = evt.detail.xhr ? evt.detail.xhr.status : 0;
            var msg = 'Wystapil blad';
            if (status === 404) msg = 'Nie znaleziono';
            else if (status === 500) msg = 'Blad serwera';
            else if (status === 0) msg = 'Brak polaczenia z serwerem';
            showToast(msg + ' (' + status + ')', 'error');
        });

        // Close modal after successful HTMX request if triggered from modal
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            // Close any open modals after successful form submission
            if (evt.detail.requestConfig &&
                evt.detail.requestConfig.elt &&
                evt.detail.requestConfig.elt.closest('.modal')) {
                var modal = bootstrap.Modal.getInstance(document.getElementById('globalModal'));
                if (modal) modal.hide();
            }
        });
    }

    // ===== Confirm Dialogs =====
    window.confirmAction = function(message, callback) {
        if (confirm(message)) {
            callback();
        }
    };

    // ===== Init =====
    document.addEventListener('DOMContentLoaded', function() {
        initDarkMode();
        initSidebar();
        initActiveNav();
        initHtmx();
    });
})();
