// VAMP Offline App - Frontend Logic

// Global state
let appState = {
    contractLoaded: false,
    taImported: false,
    paSkeleton: false,
    enriched: false,
};

// API base URL
const API_BASE = '/api';

// ===== Status Updates =====
async function updateStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const status = await response.json();

        // Update badges
        updateBadge('contractStatus', status.contract_loaded, 'Contract');
        updateBadge('taStatus', status.ta_imported, 'TA');
        updateBadge('paStatus', status.pa_skeleton_ready, 'PA');
        updateBadge('enrichStatus', status.pa_ai_ready, 'Enrich');

        // Update logs
        updateLogs(status.logs);

        // Enable/disable scan button
        document.getElementById('scanBtn').disabled = !status.contract_loaded || !status.ta_imported;

        appState.contractLoaded = status.contract_loaded;
        appState.taImported = status.ta_imported;
        appState.paSkeleton = status.pa_skeleton_ready;
        appState.enriched = status.pa_ai_ready;
    } catch (error) {
        console.error('Error updating status:', error);
    }
}

function updateBadge(elementId, active, text) {
    const badge = document.getElementById(elementId);
    if (badge) {
        if (active) {
            badge.textContent = `${text}: ✅`;
            badge.classList.remove('badge-red');
            badge.classList.add('active');
        } else {
            badge.textContent = `${text}: ❌`;
            badge.classList.add('badge-red');
            badge.classList.remove('active');
        }
    }
}

function updateLogs(logs) {
    const logContainer = document.getElementById('activityLog');
    if (!logContainer) return;

    // Only update if there are new logs
    const currentLines = logContainer.querySelectorAll('.log-line').length;
    if (currentLines === logs.length) return;

    logContainer.innerHTML = logs.map(log => {
        let className = 'log-line';
        if (log.includes('✗') || log.includes('error') || log.includes('Error')) {
            className += ' error';
        } else if (log.includes('⚠️') || log.includes('warn')) {
            className += ' warn';
        } else if (log.includes('✓') || log.includes('success')) {
            className += ' success';
        }
        return `<div class="${className}">${escapeHtml(log)}</div>`;
    }).join('');

    // Scroll to bottom
    logContainer.scrollTop = logContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== File Uploads =====
async function uploadContract() {
    const file = document.getElementById('contractFile').files[0];
    if (!file) {
        alert('Please select a contract file');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload/contract`, {
            method: 'POST',
            body: formData,
        });

        if (response.ok) {
            await updateStatus();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Upload failed: ${error.message}`);
    }
}

async function uploadTA() {
    const file = document.getElementById('taFile').files[0];
    if (!file) {
        alert('Please select a task agreement file');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload/task-agreement`, {
            method: 'POST',
            body: formData,
        });

        if (response.ok) {
            await updateStatus();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Upload failed: ${error.message}`);
    }
}

async function uploadPASkeleton() {
    const file = document.getElementById('paSkeleton').files[0];
    if (!file) {
        alert('Please select a PA skeleton file');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload/pa-skeleton`, {
            method: 'POST',
            body: formData,
        });

        if (response.ok) {
            await updateStatus();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Upload failed: ${error.message}`);
    }
}

async function uploadEvidence() {
    const files = document.getElementById('evidenceFile').files;
    if (files.length === 0) {
        alert('Please select evidence files');
        return;
    }

    for (let file of files) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            await fetch(`${API_BASE}/upload/evidence`, {
                method: 'POST',
                body: formData,
            });
        } catch (error) {
            console.error(`Failed to upload ${file.name}:`, error);
        }
    }

    await updateStatus();
}

// ===== Scanning & Processing =====
async function scanEvidence() {
    if (!appState.contractLoaded || !appState.taImported) {
        alert('Please load contract and task agreement first');
        return;
    }

    const scanBtn = document.getElementById('scanBtn');
    scanBtn.disabled = true;
    scanBtn.textContent = '⏳ Scanning...';

    try {
        const response = await fetch(`${API_BASE}/scan-evidence`, {
            method: 'POST',
        });

        if (response.ok) {
            const result = await response.json();
            populateEvidenceTable(result.rows);
            await updateStatus();
        } else {
            const error = await response.json();
            alert(`Scan failed: ${error.error}`);
        }
    } catch (error) {
        alert(`Scan error: ${error.message}`);
    } finally {
        scanBtn.disabled = false;
        scanBtn.textContent = '🔍 Scan Evidence';
    }
}

function populateEvidenceTable(rows) {
    const tbody = document.getElementById('evidenceTableBody');
    
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No evidence scanned</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(row => `
        <tr>
            <td>${escapeHtml(row.filename)}</td>
            <td>
                <span class="status-badge status-${getStatusClass(row.status)}">
                    ${row.status}
                </span>
            </td>
            <td>${escapeHtml(row.kpa || 'N/A')}</td>
            <td>${row.confidence ? Math.round(row.confidence * 100) + '%' : 'N/A'}</td>
            <td>${escapeHtml((row.impact || row.error || '').substring(0, 60))}</td>
        </tr>
    `).join('');
}

function getStatusClass(status) {
    if (status === 'SCORED') return 'scored';
    if (status === 'NEEDS_REVIEW') return 'review';
    return 'failed';
}

// ===== PA Enrichment =====
async function enrichPA() {
    if (!appState.paSkeleton) {
        alert('Please load PA skeleton first');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/enrich-pa`, {
            method: 'POST',
        });

        if (response.ok) {
            await updateStatus();
            alert('PA enrichment completed successfully');
        } else {
            const error = await response.json();
            alert(`Enrichment failed: ${error.error}`);
        }
    } catch (error) {
        alert(`Enrichment error: ${error.message}`);
    }
}

// ===== Export & Utilities =====
async function exportResults() {
    try {
        const response = await fetch(`${API_BASE}/export-results`);
        
        if (response.ok) {
            // Trigger download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'vamp-results.csv';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } else {
            const error = await response.json();
            alert(`Export failed: ${error.error}`);
        }
    } catch (error) {
        alert(`Export error: ${error.message}`);
    }
}

async function clearLogs() {
    try {
        await fetch(`${API_BASE}/clear-logs`, {
            method: 'POST',
        });
        document.getElementById('activityLog').innerHTML = '';
    } catch (error) {
        console.error('Error clearing logs:', error);
    }
}

// ===== Initialization =====
document.addEventListener('DOMContentLoaded', async () => {
    // Initial status update
    await updateStatus();

    // Poll for status updates every 2 seconds
    setInterval(updateStatus, 2000);

    // Add keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + S: Scan evidence
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            scanEvidence();
        }
        // Ctrl/Cmd + E: Export
        if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
            e.preventDefault();
            exportResults();
        }
    });

    console.log('VAMP Offline App initialized');
});
