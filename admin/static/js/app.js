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
    const toast = new bootstrap.Toast(el, { delay: 5000 });
    toast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}

function showTaskQueued(taskId) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const id = 'toast-' + Date.now();
    container.insertAdjacentHTML('beforeend', `
        <div id="${id}" class="toast align-items-center text-bg-info border-0" role="alert" style="min-width:320px">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi bi-info-circle"></i> Task queued<br>
                    <code class="small" style="word-break:break-all">${taskId}</code>
                </div>
                <button class="btn btn-sm btn-outline-light me-1 m-auto" onclick="navigator.clipboard.writeText('${taskId}');showToast('Copied!','success')" title="Copy Job ID">
                    <i class="bi bi-clipboard"></i>
                </button>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `);
    const el = document.getElementById(id);
    const toast = new bootstrap.Toast(el, { delay: 8000 });
    toast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
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
                showTaskQueued(data.result.task_id);
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

async function apiPost(url, extraHeaders = {}) {
    try {
        const response = await fetch(url, { method: 'POST', headers: extraHeaders });
        const data = await response.json();
        if (response.ok) {
            if (data.result && data.result.task_id) {
                showTaskQueued(data.result.task_id);
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

async function apiPostWithBody(url, body = {}, extraHeaders = {}) {
    try {
        const formData = new URLSearchParams(body);
        const headers = { ...extraHeaders };
        const response = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: formData,
        });
        const data = await response.json();
        if (response.ok) {
            if (data.result && data.result.task_id) {
                showTaskQueued(data.result.task_id);
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

async function checkJobStatus() {
    const input = document.getElementById('jobIdInput');
    const resultDiv = document.getElementById('jobStatusResult');
    if (!input || !resultDiv) return;
    const taskId = input.value.trim();
    if (!taskId) {
        showToast('Enter a job ID', 'error');
        return;
    }
    resultDiv.innerHTML = '<span class="text-muted"><i class="bi bi-hourglass-split"></i> Checking...</span>';
    try {
        const response = await fetch(`/actions/status/${taskId}`);
        const data = await response.json();
        if (data.status === 'finished') {
            const r = data.result;
            let detail = '';
            if (r && r.error) detail = `<span class="text-danger">${r.error}</span>`;
            else if (r && r.status === 'sent') detail = '<span class="text-success">Summary sent</span>';
            else if (r && r.processed !== undefined) detail = `<span class="text-success">${r.processed} user(s) processed</span>`;
            else detail = '<span class="text-success">Completed</span>';
            resultDiv.innerHTML = `<span class="badge bg-success me-2">Finished</span> ${detail}`;
        } else if (data.status === 'pending') {
            resultDiv.innerHTML = '<span class="badge bg-warning text-dark">Pending</span> <span class="text-muted">Task is still in queue</span>';
        } else if (data.status === 'not_found') {
            resultDiv.innerHTML = '<span class="badge bg-secondary">Not Found</span> <span class="text-muted">No task with this ID</span>';
        } else if (data.status === 'error') {
            resultDiv.innerHTML = `<span class="badge bg-danger">Error</span> <span class="text-danger">${data.error || 'Unknown error'}</span>`;
        } else {
            resultDiv.innerHTML = `<span class="badge bg-secondary">${data.status}</span>`;
        }
    } catch (err) {
        resultDiv.innerHTML = `<span class="text-danger">Network error: ${err.message}</span>`;
    }
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
        const headers = {};
        const csrf = btn.dataset.csrf;
        const body = {};
        if (csrf) {
            headers['X-CSRF-Token'] = csrf;
            body['csrf_token'] = csrf;
        }
        apiPostWithBody(action, body, headers);
    }
});
