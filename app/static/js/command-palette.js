/* Command Palette - Ctrl+K global search */
(function() {
    'use strict';

    var dialog = null;
    var input = null;
    var results = null;
    var activeIndex = -1;
    var debounceTimer = null;

    function init() {
        dialog = document.getElementById('command-palette');
        if (!dialog) return;
        input = dialog.querySelector('.cp-input');
        results = dialog.querySelector('.cp-results');

        // Ctrl+K / Cmd+K to open
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                open();
            }
            if (e.key === 'Escape' && dialog.open) {
                close();
            }
        });

        // Click backdrop to close
        dialog.addEventListener('click', function(e) {
            if (e.target === dialog) close();
        });

        // Input events
        input.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function() { search(input.value); }, 200);
        });

        // Keyboard navigation
        input.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                moveSelection(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                moveSelection(-1);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                activateSelected();
            }
        });

        // Load initial results
        search('');
    }

    function open() {
        if (!dialog) return;
        dialog.showModal();
        input.value = '';
        input.focus();
        activeIndex = -1;
        search('');
    }

    function close() {
        if (!dialog) return;
        dialog.close();
    }

    function search(query) {
        var url = '/app/command-palette?q=' + encodeURIComponent(query);
        fetch(url, { headers: { 'HX-Request': 'true' } })
            .then(function(r) { return r.text(); })
            .then(function(html) {
                results.innerHTML = html;
                activeIndex = -1;
            });
    }

    function getItems() {
        return results.querySelectorAll('[data-cp-item]');
    }

    function moveSelection(delta) {
        var items = getItems();
        if (!items.length) return;

        // Remove current highlight
        if (activeIndex >= 0 && activeIndex < items.length) {
            items[activeIndex].classList.remove('cp-active');
        }

        activeIndex += delta;
        if (activeIndex < 0) activeIndex = items.length - 1;
        if (activeIndex >= items.length) activeIndex = 0;

        items[activeIndex].classList.add('cp-active');
        items[activeIndex].scrollIntoView({ block: 'nearest' });
    }

    function activateSelected() {
        var items = getItems();
        if (activeIndex >= 0 && activeIndex < items.length) {
            var href = items[activeIndex].getAttribute('href');
            if (href) {
                close();
                window.location.href = href;
            }
        } else if (items.length > 0) {
            // If nothing selected, activate first item
            var href = items[0].getAttribute('href');
            if (href) {
                close();
                window.location.href = href;
            }
        }
    }

    // Expose open for topbar button
    window.openCommandPalette = open;

    document.addEventListener('DOMContentLoaded', init);
})();
