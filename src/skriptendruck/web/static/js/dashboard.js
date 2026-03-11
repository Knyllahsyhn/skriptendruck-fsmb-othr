/**
 * Skriptendruck Dashboard – JavaScript
 * FSMB Regensburg e.V.
 */

/* ============================================================
   Dark/Light Mode Toggle
   ============================================================ */
(function initTheme() {
    const saved = localStorage.getItem('fsmb-theme') || 'light';
    applyTheme(saved);

    // Bind toggle buttons once DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        bindThemeToggle('themeToggle', 'themeIcon');
        bindThemeToggle('loginThemeToggle', 'loginThemeIcon');
    });
})();

function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('fsmb-theme', theme);
    updateThemeIcons(theme);
}

function updateThemeIcons(theme) {
    var icons = document.querySelectorAll('#themeIcon, #loginThemeIcon');
    icons.forEach(function (icon) {
        if (!icon) return;
        if (theme === 'dark') {
            icon.classList.remove('bi-moon-fill');
            icon.classList.add('bi-sun-fill');
        } else {
            icon.classList.remove('bi-sun-fill');
            icon.classList.add('bi-moon-fill');
        }
    });
}

function bindThemeToggle(buttonId, iconId) {
    var btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener('click', function () {
        var current = document.documentElement.getAttribute('data-bs-theme') || 'light';
        var next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
    });
}

// Re-apply icons after full load (login page might render later)
document.addEventListener('DOMContentLoaded', function () {
    var theme = localStorage.getItem('fsmb-theme') || 'light';
    updateThemeIcons(theme);
});


/* ============================================================
   Toast Notifications
   ============================================================ */

/**
 * Zeigt eine Toast-Benachrichtigung an.
 * @param {string} message - Nachricht
 * @param {string} type - 'success', 'danger', 'warning', 'info'
 */
function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toastContainer');
    if (!container) return;

    var iconMap = {
        success: 'bi-check-circle-fill',
        danger: 'bi-exclamation-triangle-fill',
        warning: 'bi-exclamation-circle-fill',
        info: 'bi-info-circle-fill',
    };

    var toast = document.createElement('div');
    toast.className = 'toast align-items-center text-bg-' + type + ' border-0';
    toast.setAttribute('role', 'alert');
    toast.innerHTML =
        '<div class="d-flex">' +
        '  <div class="toast-body">' +
        '    <i class="bi ' + (iconMap[type] || iconMap.info) + ' me-2"></i>' +
        '    ' + message +
        '  </div>' +
        '  <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
        '</div>';

    container.appendChild(toast);
    var bsToast = new bootstrap.Toast(toast, { delay: 4000 });
    bsToast.show();

    toast.addEventListener('hidden.bs.toast', function () { toast.remove(); });
}


/* ============================================================
   Order Actions
   ============================================================ */

/**
 * Gibt einen Auftrag frei (POST /api/orders/{id}/start).
 */
async function startOrder(orderId) {
    if (!confirm('Auftrag #' + orderId + ' wirklich freigeben?')) return;

    try {
        var res = await fetch('/api/orders/' + orderId + '/start', { method: 'POST' });
        var data = await res.json();

        if (res.ok && data.success) {
            showToast(data.message, 'success');
            var row = document.getElementById('order-row-' + orderId);
            if (row) {
                var badge = row.querySelector('td:nth-last-child(2) .badge');
                if (badge) {
                    badge.className = 'badge bg-info';
                    badge.textContent = 'Validiert';
                }
            }
        } else {
            showToast(data.error || 'Fehler beim Freigeben', 'danger');
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
    }
}

/**
 * Loescht einen Auftrag (DELETE /api/orders/{id}).
 */
async function deleteOrder(orderId) {
    if (!confirm('Auftrag #' + orderId + ' wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.')) return;

    try {
        var res = await fetch('/api/orders/' + orderId, { method: 'DELETE' });
        var data = await res.json();

        if (res.ok && data.success) {
            showToast(data.message, 'success');
            var row = document.getElementById('order-row-' + orderId);
            if (row) {
                row.style.transition = 'opacity 0.3s';
                row.style.opacity = '0';
                setTimeout(function () { row.remove(); }, 300);
            }
        } else {
            showToast(data.error || 'Fehler beim Löschen', 'danger');
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
    }
}
