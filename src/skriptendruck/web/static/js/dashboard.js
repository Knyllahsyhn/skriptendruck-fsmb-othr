/**
 * Skriptendruck Dashboard – JavaScript
 * FSMB Regensburg e.V.
 */

/* ============================================================
   Dark/Light Mode Toggle
   ============================================================ */
(function initTheme() {
    var saved = localStorage.getItem('fsmb-theme') || 'light';
    applyTheme(saved);

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

document.addEventListener('DOMContentLoaded', function () {
    var theme = localStorage.getItem('fsmb-theme') || 'light';
    updateThemeIcons(theme);

    // ---- Printing Toggle ----
    initPrintingToggle();
});


/* ============================================================
   Printing Toggle (localStorage)
   ============================================================ */
function initPrintingToggle() {
    var toggle = document.getElementById('printingToggle');
    if (!toggle) return;

    // Load saved state (default: false = off)
    var saved = localStorage.getItem('fsmb-printing-enabled');
    toggle.checked = saved === 'true';

    toggle.addEventListener('change', function () {
        localStorage.setItem('fsmb-printing-enabled', toggle.checked ? 'true' : 'false');
        showToast(
            toggle.checked ? 'Drucken aktiviert' : 'Drucken deaktiviert',
            toggle.checked ? 'success' : 'info'
        );
    });
}

function isPrintingEnabled() {
    return localStorage.getItem('fsmb-printing-enabled') === 'true';
}


/* ============================================================
   Toast Notifications
   ============================================================ */

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
    var bsToast = new bootstrap.Toast(toast, { delay: 5000 });
    bsToast.show();

    toast.addEventListener('hidden.bs.toast', function () { toast.remove(); });
}


/* ============================================================
   Helper: Button → Spinner → Result
   ============================================================ */

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.disabled = true;
        btn._origHTML = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Verarbeite…';
    } else {
        btn.disabled = false;
        if (btn._origHTML) btn.innerHTML = btn._origHTML;
    }
}

function setButtonSuccess(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn.classList.remove('btn-success', 'btn-outline-success', 'btn-warning');
    btn.classList.add('btn-outline-secondary');
    btn.innerHTML = '<i class="bi bi-check-lg"></i> Erledigt';
}

function setButtonError(btn) {
    if (!btn) return;
    btn.disabled = false;
    if (btn._origHTML) btn.innerHTML = btn._origHTML;
    btn.classList.add('btn-outline-danger');
}


/* ============================================================
   Order Actions (NO confirm popups)
   ============================================================ */

/**
 * Startet einen einzelnen Auftrag – OHNE Bestätigungs-Popup.
 * Zeigt Spinner während der Verarbeitung, dann Erfolg/Fehler-Toast.
 */
async function startOrder(orderId, btn) {
    setButtonLoading(btn, true);

    try {
        var res = await fetch('/api/orders/' + orderId + '/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable_printing: isPrintingEnabled() }),
        });
        var data = await res.json();

        if (res.ok && data.success) {
            showToast(data.message || 'Auftrag #' + orderId + ' erfolgreich verarbeitet', 'success');

            // Update row status badge
            var row = document.getElementById('order-row-' + orderId);
            if (row) {
                var badge = row.querySelector('.order-status-badge');
                if (badge) {
                    badge.className = 'badge bg-success order-status-badge';
                    badge.textContent = 'Verarbeitet';
                }
                // Fade out from pending table after a moment
                setTimeout(function () {
                    row.style.transition = 'opacity 0.4s';
                    row.style.opacity = '0';
                    setTimeout(function () { row.remove(); updatePendingCount(); }, 400);
                }, 1200);
            }
            setButtonSuccess(btn);
        } else {
            showToast(data.error || 'Fehler beim Verarbeiten', 'danger');
            // Update badge to error
            var row = document.getElementById('order-row-' + orderId);
            if (row) {
                var badge = row.querySelector('.order-status-badge');
                if (badge) {
                    badge.className = 'badge bg-danger order-status-badge';
                    badge.textContent = 'Fehler';
                    badge.title = data.error || '';
                }
            }
            setButtonError(btn);
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
        setButtonLoading(btn, false);
    }
}

/**
 * Löscht einen Auftrag (DELETE). Bestätigung beibehalten da destruktiv.
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
                setTimeout(function () { row.remove(); updatePendingCount(); }, 300);
            }
        } else {
            showToast(data.error || 'Fehler beim Löschen', 'danger');
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
    }
}


/* ============================================================
   Bulk Action: Start All Pending Orders
   ============================================================ */

async function startAllOrders(btn) {
    setButtonLoading(btn, true);
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Verarbeite alle…';

    // Disable all individual start buttons
    var startBtns = document.querySelectorAll('.btn-start-order');
    startBtns.forEach(function (b) { b.disabled = true; });

    try {
        var res = await fetch('/api/orders/start-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable_printing: isPrintingEnabled() }),
        });
        var data = await res.json();

        if (res.ok && data.success) {
            showToast(data.message, data.fail_count > 0 ? 'warning' : 'success');

            // Update individual rows based on results
            if (data.results) {
                data.results.forEach(function (r) {
                    var row = document.getElementById('order-row-' + r.order_id);
                    if (row) {
                        var badge = row.querySelector('.order-status-badge');
                        if (badge) {
                            if (r.success) {
                                badge.className = 'badge bg-success order-status-badge';
                                badge.textContent = 'Verarbeitet';
                            } else {
                                badge.className = 'badge bg-danger order-status-badge';
                                badge.textContent = 'Fehler';
                                badge.title = r.message || '';
                            }
                        }
                    }
                });
            }

            // Reload after short delay to refresh everything
            setTimeout(function () { location.reload(); }, 2500);
        } else {
            showToast(data.error || 'Fehler bei der Bulk-Verarbeitung', 'danger');
            setButtonLoading(btn, false);
            startBtns.forEach(function (b) { b.disabled = false; });
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
        setButtonLoading(btn, false);
        startBtns.forEach(function (b) { b.disabled = false; });
    }
}


/* ============================================================
   Trigger Manual Scan
   ============================================================ */

async function triggerScan(btn) {
    setButtonLoading(btn, true);
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Scanne…';

    try {
        var res = await fetch('/api/scan', { method: 'POST' });
        var data = await res.json();

        if (res.ok && data.success) {
            // Erfolgreicher Scan
            var toastType = data.new_orders > 0 ? 'success' : 'info';
            showToast(data.message || 'Scan abgeschlossen', toastType);
            
            // Debug-Info in Console loggen
            console.log('Scan-Ergebnis:', data);
            
            if (data.new_orders > 0) {
                setTimeout(function () { location.reload(); }, 1000);
            }
        } else {
            // Fehler beim Scan - detaillierte Infos anzeigen
            var errorMsg = data.message || data.error || 'Unbekannter Fehler';
            showToast(errorMsg, 'danger');
            
            // Detaillierte Debug-Infos in Console und als Alert
            console.error('Scan-Fehler:', data);
            if (data.orders_dir) {
                console.log('Auftragsordner:', data.orders_dir);
                console.log('Existiert:', data.dir_exists);
                console.log('Lesbar:', data.dir_readable);
            }
            
            // Bei Pfad-Problemen detailliertes Modal anzeigen
            if (data.error && !data.dir_exists) {
                showScanDebugModal(data);
            }
        }
    } catch (err) {
        showToast('Netzwerkfehler: ' + err.message, 'danger');
        console.error('Scan Netzwerkfehler:', err);
    } finally {
        setButtonLoading(btn, false);
        btn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i> Ordner scannen';
    }
}

/**
 * Zeigt ein Debug-Modal mit detaillierten Scan-Informationen an
 */
function showScanDebugModal(data) {
    // Prüfen ob Modal schon existiert, sonst erstellen
    var modal = document.getElementById('scanDebugModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = 'scanDebugModal';
        modal.tabIndex = -1;
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-warning">
                        <h5 class="modal-title"><i class="bi bi-bug me-2"></i>Scan Debug-Info</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body" id="scanDebugContent">
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Schließen</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }
    
    // Content aktualisieren
    var content = document.getElementById('scanDebugContent');
    var statusIcon = data.dir_exists ? '✓' : '✗';
    var readableIcon = data.dir_readable ? '✓' : '✗';
    
    content.innerHTML = `
        <div class="alert ${data.error ? 'alert-danger' : 'alert-info'}">
            <strong>Fehler:</strong> ${data.error || 'Kein Fehler'}
        </div>
        <table class="table table-sm">
            <tr><th>BASE_PATH</th><td><code>${data.base_path || 'nicht gesetzt'}</code></td></tr>
            <tr><th>Auftragsordner</th><td><code>${data.orders_dir || 'nicht ermittelt'}</code></td></tr>
            <tr><th>Verzeichnis existiert</th><td>${statusIcon} ${data.dir_exists ? 'Ja' : 'Nein'}</td></tr>
            <tr><th>Verzeichnis lesbar</th><td>${readableIcon} ${data.dir_readable ? 'Ja' : 'Nein'}</td></tr>
            <tr><th>Dateien gesamt</th><td>${data.total_files || 0}</td></tr>
            <tr><th>PDF-Dateien</th><td>${data.pdf_files || 0}</td></tr>
            <tr><th>Neue Aufträge</th><td>${data.new_orders || 0}</td></tr>
        </table>
        ${data.pdf_list && data.pdf_list.length > 0 ? `
            <h6>Gefundene PDFs:</h6>
            <ul class="small">${data.pdf_list.map(f => '<li>' + f + '</li>').join('')}</ul>
        ` : ''}
        <hr>
        <h6>Troubleshooting:</h6>
        <ol class="small">
            <li>Prüfen Sie <code>BASE_PATH</code> in der <code>.env</code> Datei</li>
            <li>Stellen Sie sicher, dass der Ordner <code>01_Auftraege</code> existiert</li>
            <li>Prüfen Sie die Netzlaufwerk-Verbindung</li>
            <li>Prüfen Sie die Berechtigungen des Service-Accounts</li>
        </ol>
    `;
    
    // Modal anzeigen
    var bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}


/* ============================================================
   Helpers
   ============================================================ */

function updatePendingCount() {
    var table = document.getElementById('pendingOrdersTable');
    if (!table) return;
    var rows = table.querySelectorAll('tbody tr');
    var count = rows.length;

    // Update badge in header
    var badge = table.closest('.card').querySelector('.card-header .badge.bg-warning');
    if (badge) {
        badge.textContent = count;
        if (count === 0) badge.style.display = 'none';
    }

    // Update bulk button
    var bulkBtn = document.getElementById('btnStartAll');
    if (bulkBtn && count === 0) {
        bulkBtn.style.display = 'none';
    }
}
