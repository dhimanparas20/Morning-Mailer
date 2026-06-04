function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const id = 'toast-' + Date.now();
    const icon = type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle';
    const bsType = type === 'error' ? 'danger' : type;
    container.insertAdjacentHTML('beforeend', `
        <div id="${id}" class="toast align-items-center text-bg-${bsType} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body"><i class="bi bi-${icon}"></i> ${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `);
    const el = document.getElementById(id);
    const toast = new bootstrap.Toast(el, { delay: 4000 });
    toast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}

function showJobStarted(taskId) {
    showToast(`Job enqueued (ID: ${taskId.slice(0, 8)}...) — processing in background`, 'info');
}

function showJobFinished(result) {
    if (result && result.error) {
        showToast(`Job failed: ${result.error}`, 'error');
    } else if (result && result.status === 'sent') {
        showToast('Job completed — summary sent!', 'success');
    } else if (result && result.processed !== undefined) {
        showToast(`Job completed — ${result.processed} user(s) processed`, 'success');
    } else {
        showToast('Job completed', 'success');
    }
}

async function postForm(url, formData) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData instanceof FormData ? formData : new URLSearchParams(formData),
            headers: formData instanceof FormData ? {} : { 'Content-Type': 'application/x-www-form-urlencoded' },
        });
        const data = await response.json();
        if (response.ok) {
            if (data.result && data.result.task_id) {
                showJobStarted(data.result.task_id);
                pollTaskStatus(data.result.task_id);
            } else {
                showToast(data.message || data.result?.message || 'Success', 'success');
            }
            return data;
        } else {
            showToast(data.detail || 'Error occurred', 'error');
            return null;
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
        return null;
    }
}

async function apiPost(url) {
    try {
        const response = await fetch(url, { method: 'POST' });
        const data = await response.json();
        if (response.ok) {
            if (data.result && data.result.task_id) {
                showJobStarted(data.result.task_id);
                pollTaskStatus(data.result.task_id);
            } else {
                showToast(data.message || data.result?.message || 'Action completed', 'success');
            }
            return data;
        } else {
            showToast(data.detail || 'Error occurred', 'error');
            return null;
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
        return null;
    }
}

async function pollTaskStatus(taskId, maxAttempts = 30) {
    for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
            const response = await fetch(`/actions/status/${taskId}`);
            const data = await response.json();
            if (data.status === 'finished') {
                showJobFinished(data.result);
                return data;
            } else if (data.status === 'not_found' || data.status === 'error') {
                showToast(`Job ${data.status}`, 'error');
                return data;
            }
        } catch (err) {
            // continue polling
        }
    }
    showToast('Job still processing (timeout)', 'info');
}

document.addEventListener('click', function(e) {
    const btn = e.target.closest('.action-btn, .action-btn-sm');
    if (!btn) return;
    e.preventDefault();
    const action = btn.dataset.action;
    const method = (btn.dataset.method || 'POST').toUpperCase();
    const confirmMsg = btn.dataset.confirm;

    if (confirmMsg && !confirm(confirmMsg)) return;

    if (method === 'POST') {
        apiPost(action);
    }
});
