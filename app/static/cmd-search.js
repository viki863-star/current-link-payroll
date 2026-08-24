/* ─── Command Palette Search ─── */
(function() {
    const overlay = document.getElementById('cmdOverlay');
    const input = document.getElementById('cmdInput');
    const results = document.getElementById('cmdResults');
    const tabs = document.getElementById('cmdTabs');
    const trigger = document.getElementById('searchTrigger');
    const escBtn = document.getElementById('cmdEsc');
    let activeCategory = 'all';
    let selectedIndex = -1;
    let searchTimeout = null;

    function open() {
        overlay.classList.add('is-open');
        input.value = '';
        input.focus();
        selectedIndex = -1;
        showQuickActions();
    }

    function close() {
        overlay.classList.remove('is-open');
        input.value = '';
        results.innerHTML = '';
    }

    function showQuickActions() {
        results.innerHTML = `
            <div class="cmd-section">Quick Actions</div>
            <div class="cmd-action" data-action="add-driver">
                <div class="cmd-action-icon"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10 5v10M5 10h10"/></svg></div>
                <span class="cmd-action-text">Add new driver</span>
            </div>
            <div class="cmd-action" data-action="add-invoice">
                <div class="cmd-action-icon"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10 5v10M5 10h10"/></svg></div>
                <span class="cmd-action-text">Create invoice</span>
            </div>
            <div class="cmd-action" data-action="salary-report">
                <div class="cmd-action-icon"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10h14M3 6h14M3 14h14"/></svg></div>
                <span class="cmd-action-text">View salary report</span>
            </div>
            <div class="cmd-action" data-action="fuel-report">
                <div class="cmd-action-icon"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10h14M3 6h14M3 14h14"/></svg></div>
                <span class="cmd-action-text">View fuel report</span>
            </div>
            <div class="cmd-action" data-action="purchase-report">
                <div class="cmd-action-icon"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10h14M3 6h14M3 14h14"/></svg></div>
                <span class="cmd-action-text">Purchase report</span>
            </div>
        `;
        bindActions();
    }

    function bindActions() {
        results.querySelectorAll('.cmd-action').forEach(el => {
            el.onclick = function() {
                const action = this.dataset.action;
                const urls = {
                    'add-driver': '/hr/drivers/add',
                    'add-invoice': '/supplier/invoices/new',
                    'salary-report': '/hr/salary-store',
                    'fuel-report': '/fleet/fuel',
                    'purchase-report': '/supplier/purchase-report'
                };
                if (urls[action]) window.location.href = urls[action];
            };
        });
    }

    async function search(query) {
        if (!query || query.length < 2) {
            showQuickActions();
            return;
        }

        try {
            const resp = await fetch('/api/search?q=' + encodeURIComponent(query) + '&cat=' + activeCategory);
            const data = await resp.json();
            renderResults(data, query);
        } catch(e) {
            results.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:0.82rem;">Search error. Please try again.</div>';
        }
    }

    function renderResults(data, query) {
        let html = '';
        const categories = {
            driver: { label: 'Drivers', icon: '🚛', cls: 'driver' },
            supplier: { label: 'Suppliers', icon: '🏪', cls: 'supplier' },
            invoice: { label: 'Invoices', icon: '📄', cls: 'invoice' },
            vehicle: { label: 'Vehicles', icon: '🚗', cls: 'vehicle' },
            customer: { label: 'Customers', icon: '👥', cls: 'customer' }
        };

        for (const [cat, items] of Object.entries(data)) {
            if (!items || items.length === 0) continue;
            const meta = categories[cat] || { label: cat, icon: '📋', cls: 'action' };
            html += `<div class="cmd-section">${meta.label} (${items.length})</div>`;
            items.forEach((item, i) => {
                const badge = item.status ? `<span class="cmd-item-badge ${item.status.toLowerCase()}">${item.status}</span>` : '';
                html += `
                    <div class="cmd-item" data-url="${item.url || '#'}" data-idx="${i}">
                        <div class="cmd-item-icon ${meta.cls}">${meta.icon}</div>
                        <div class="cmd-item-info">
                            <div class="cmd-item-title">${highlightMatch(item.title, query)}</div>
                            ${item.meta ? `<div class="cmd-item-meta">${item.meta}</div>` : ''}
                        </div>
                        ${badge}
                    </div>
                `;
            });
        }

        if (!html) {
            html = '<div style="padding:32px 16px;text-align:center;color:#94a3b8;font-size:0.82rem;">No results found for "' + escapeHtml(query) + '"</div>';
        }

        results.innerHTML = html;
        selectedIndex = -1;

        results.querySelectorAll('.cmd-item').forEach(el => {
            el.onclick = function() {
                const url = this.dataset.url;
                if (url && url !== '#') window.location.href = url;
            };
        });
    }

    function highlightMatch(text, query) {
        if (!query) return text;
        const regex = new RegExp('(' + escapeRegex(query) + ')', 'gi');
        return text.replace(regex, '<strong style="color:var(--primary)">$1</strong>');
    }

    function escapeHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function navigate(direction) {
        const items = results.querySelectorAll('.cmd-item');
        if (items.length === 0) return;

        items.forEach(el => el.classList.remove('is-selected'));
        selectedIndex += direction;
        if (selectedIndex < 0) selectedIndex = items.length - 1;
        if (selectedIndex >= items.length) selectedIndex = 0;
        items[selectedIndex].classList.add('is-selected');
        items[selectedIndex].scrollIntoView({ block: 'nearest' });
    }

    function selectItem() {
        const items = results.querySelectorAll('.cmd-item');
        if (selectedIndex >= 0 && selectedIndex < items.length) {
            const url = items[selectedIndex].dataset.url;
            if (url && url !== '#') window.location.href = url;
        }
    }

    // Event Listeners
    if (trigger) {
        trigger.addEventListener('click', open);
    }

    if (escBtn) {
        escBtn.addEventListener('click', close);
    }

    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) close();
    });

    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            if (overlay.classList.contains('is-open')) close();
            else open();
        }
        if (e.key === 'Escape' && overlay.classList.contains('is-open')) {
            close();
        }
        if (overlay.classList.contains('is-open')) {
            if (e.key === 'ArrowDown') { e.preventDefault(); navigate(1); }
            if (e.key === 'ArrowUp') { e.preventDefault(); navigate(-1); }
            if (e.key === 'Enter') { e.preventDefault(); selectItem(); }
        }
    });

    input.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => search(this.value.trim()), 200);
    });

    // Category tabs
    if (tabs) {
        tabs.querySelectorAll('.cmd-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                tabs.querySelectorAll('.cmd-tab').forEach(t => t.classList.remove('is-active'));
                this.classList.add('is-active');
                activeCategory = this.dataset.cat;
                if (input.value.trim()) search(input.value.trim());
            });
        });
    }
})();
