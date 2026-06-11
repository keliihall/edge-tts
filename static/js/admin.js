document.addEventListener('DOMContentLoaded', () => {
    const $ = selector => document.querySelector(selector);
    const $$ = selector => Array.from(document.querySelectorAll(selector));
    const titles = {overview: '运行概览', tasks: '任务管理', users: '用户管理', settings: '系统设置', diagnostics: '诊断信息'};
    let tasks = [];
    let users = [];
    let passwordUserId = null;

    function notify(message, type = 'info') {
        const toast = $('#toast');
        toast.textContent = message;
        toast.dataset.type = type;
        toast.classList.add('show');
        clearTimeout(notify.timer);
        notify.timer = setTimeout(() => toast.classList.remove('show'), 3200);
    }
    async function api(url, options = {}) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error?.message || '操作失败');
        return data;
    }
    function time(value, empty = '未开始') {
        return value ? new Date(value * 1000).toLocaleString('zh-CN') : empty;
    }
    function duration(value) {
        const seconds = Math.round(value || 0);
        return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    }
    function label(status) {
        return ({
            queued: '排队中', processing: '处理中', finished: '已结束',
            cancelled: '已取消', pending: '等待中', done: '已完成', failed: '失败'
        })[status] || status;
    }
    function switchView(view) {
        $$('.admin-tab').forEach(item => item.classList.toggle('active', item.dataset.view === view));
        $$('.admin-view').forEach(item => item.classList.toggle('active', item.dataset.viewPanel === view));
        $('#admin-view-title').textContent = titles[view];
    }
    function renderOverview() {
        const active = tasks.filter(item => ['queued', 'processing'].includes(item.status)).length;
        const failed = tasks.reduce((total, item) => total + item.failed_count, 0);
        $('#overview-metrics').innerHTML = `
            <article><span>任务总数</span><strong>${tasks.length}</strong><small>当前保留期内</small></article>
            <article><span>队列压力</span><strong>${active}</strong><small>排队与处理中</small></article>
            <article><span>用户数</span><strong>${users.length}</strong><small>${users.filter(item => item.active).length} 个已启用</small></article>
            <article class="${failed ? 'warning' : ''}"><span>失败分项</span><strong>${failed}</strong><small>${failed ? '建议进入任务管理排查' : '运行正常'}</small></article>`;
        renderTaskRows($('#overview-tasks'), tasks.slice(0, 6));
    }
    function renderTaskRows(container, source) {
        container.innerHTML = '';
        container.classList.toggle('empty-state', source.length === 0);
        if (!source.length) {
            container.textContent = '暂无任务';
            return;
        }
        source.forEach(task => {
            const entry = document.createElement('div');
            entry.className = 'admin-task-entry';
            const row = document.createElement('div');
            row.className = 'admin-table-row';
            row.innerHTML = `<div class="table-primary"><strong>${task.kind === 'text' ? '文本' : '批量'} · ${escapeHtml(task.title)}</strong>
                <small>${escapeHtml(task.owner_name || '')} · 创建 ${time(task.created_at)} · 开始 ${time(task.started_at)} · 耗时 ${duration(task.elapsed_seconds)}${task.finished_at ? ` · 结束 ${time(task.finished_at)}` : ''}</small></div>
                <div class="table-progress"><i style="width:${task.total ? Math.round(task.completed / task.total * 100) : 0}%"></i></div>
                <div class="table-count">${task.completed}/${task.total}${task.failed_count ? `<em>${task.failed_count} 失败</em>` : ''}</div>
                <span class="status-badge ${task.status}">${label(task.status)}</span>
                <div class="row-actions">
                    <button class="small-button" data-admin-task="details" data-kind="${task.kind}" data-id="${task.id}">分项</button>
                    ${['queued', 'processing'].includes(task.status) ? `<button class="small-button" data-admin-task="cancel" data-kind="${task.kind}" data-id="${task.id}">取消</button>` : ''}
                    ${!['queued', 'processing'].includes(task.status) ? `<button class="small-button danger-text" data-admin-task="delete" data-kind="${task.kind}" data-id="${task.id}">清理</button>` : ''}
                </div>`;
            const items = document.createElement('div');
            items.className = 'admin-task-items';
            items.hidden = true;
            items.innerHTML = task.items.map(item => {
                const name = task.kind === 'batch' ? item.source_name : `片段 ${item.index}`;
                return `<div><span><strong>${escapeHtml(name)}</strong><small>${item.text_length} 字 · ${time(item.started_at)} 开始 · ${duration(item.elapsed_seconds)}${item.finished_at ? ` · ${time(item.finished_at)} 结束` : ''}</small>${item.error ? `<em>${escapeHtml(item.error)}</em>` : ''}</span><span class="status-badge ${item.status}">${label(item.status)}</span></div>`;
            }).join('');
            entry.append(row, items);
            container.appendChild(entry);
        });
    }
    function escapeHtml(value) {
        const node = document.createElement('span');
        node.textContent = String(value ?? '');
        return node.innerHTML;
    }
    function renderTasks() {
        const kind = $('#admin-task-kind').value;
        const status = $('#admin-task-status').value;
        renderTaskRows($('#admin-task-list'), tasks.filter(item =>
            (!kind || item.kind === kind) && (!status || item.status === status)
        ));
    }
    function renderUsers() {
        const list = $('#users-list');
        list.innerHTML = '';
        users.forEach(user => {
            const row = document.createElement('div');
            row.className = 'admin-table-row user-row';
            row.innerHTML = `<div class="table-primary"><strong>${escapeHtml(user.username)}</strong><small>${user.role === 'admin' ? '管理员' : '普通用户'} · ${user.active ? '已启用' : '已禁用'} · 最后登录 ${time(user.last_login_at, '从未')}</small></div>
                <div class="row-actions">
                    <button class="small-button" data-user-action="role" data-id="${user.id}" data-value="${user.role === 'admin' ? 'user' : 'admin'}">${user.role === 'admin' ? '降为用户' : '设为管理员'}</button>
                    <button class="small-button" data-user-action="active" data-id="${user.id}" data-value="${!user.active}">${user.active ? '禁用' : '启用'}</button>
                    <button class="small-button" data-user-action="password" data-id="${user.id}" data-name="${escapeHtml(user.username)}">重置密码</button>
                </div>`;
            list.appendChild(row);
        });
    }
    async function loadAll() {
        try {
            [tasks, users] = await Promise.all([api('/tasks?limit=200'), api('/admin/users')]);
            renderOverview();
            renderTasks();
            renderUsers();
        } catch (error) {
            notify(error.message, 'error');
        }
    }
    async function loadSettings() {
        try {
            const [settings, voices] = await Promise.all([api('/settings'), api('/voices')]);
            const voiceSelect = $('#settings-default-voice');
            voiceSelect.innerHTML = voices.map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join('');
            voiceSelect.value = settings.default_voice;
            $('#settings-default-rate').value = settings.default_speech_rate;
            $('#settings-default-volume').value = settings.default_volume;
            $('#settings-default-pitch').value = settings.default_pitch;
            $('#settings-proxy').value = settings.proxy_url || '';
            $('#settings-save-dir').value = settings.default_save_dir || '';
            $('#settings-chunk-length').value = settings.chunk_length;
            $('#settings-task-days').value = settings.task_retention_days || 30;
            $('#settings-history-days').value = settings.history_retention_days;
            $('#settings-temp-hours').value = settings.temp_file_ttl_hours;
            $('#settings-auto-open').checked = settings.auto_open_browser !== false;
        } catch (error) {
            notify(error.message, 'error');
        }
    }
    async function loadDiagnostics(force = false) {
        try {
            const data = await api(force ? '/diagnostics?force=1' : '/diagnostics');
            const rows = [
                ['版本', data.version], ['整体网络', data.network_connectivity ? '可用' : '异常'],
                ['Edge TTS', data.edge_tts_available ? '可连接' : '不可连接'],
                ['代理', data.proxy_configured ? (data.proxy_available ? '已配置且可用' : '已配置但不可用') : '未配置'],
                ['设置文件', data.settings_path], ['临时目录', data.temp_dir]
            ];
            $('#diagnostics-panel').innerHTML = rows.map(([name, value]) =>
                `<div><span>${name}</span><strong>${escapeHtml(value)}</strong></div>`
            ).join('');
        } catch (error) {
            notify(error.message, 'error');
        }
    }
    $$('.admin-tab').forEach(button => button.addEventListener('click', () => {
        switchView(button.dataset.view);
        if (button.dataset.view === 'settings') loadSettings();
        if (button.dataset.view === 'diagnostics') loadDiagnostics();
    }));
    $('#admin-refresh').addEventListener('click', () => {
        loadAll();
        if ($('[data-view-panel="diagnostics"]').classList.contains('active')) loadDiagnostics(true);
    });
    $('#admin-task-kind').addEventListener('change', renderTasks);
    $('#admin-task-status').addEventListener('change', renderTasks);
    $('.admin-main').addEventListener('click', async event => {
        const button = event.target.closest('[data-admin-task]');
        if (!button) return;
        const task = tasks.find(item => item.id === button.dataset.id);
        try {
            if (button.dataset.adminTask === 'details') {
                const items = button.closest('.admin-task-entry').querySelector('.admin-task-items');
                items.hidden = !items.hidden;
                button.textContent = items.hidden ? '分项' : '收起';
                return;
            }
            if (button.dataset.adminTask === 'cancel') {
                const url = task.kind === 'text' ? `/jobs/${task.id}/cancel` : `/batch/job/${task.id}/cancel`;
                await api(url, {method: 'POST'});
            } else {
                await api(`/tasks/${task.kind}/${task.id}`, {method: 'DELETE'});
            }
            await loadAll();
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    $('#create-user-form').addEventListener('submit', async event => {
        event.preventDefault();
        try {
            await api('/admin/users', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: $('#new-username').value.trim(), password: $('#new-password').value, role: $('#new-role').value})
            });
            event.target.reset();
            notify('用户已创建', 'success');
            await loadAll();
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    $('#users-list').addEventListener('click', async event => {
        const button = event.target.closest('[data-user-action]');
        if (!button) return;
        if (button.dataset.userAction === 'password') {
            passwordUserId = button.dataset.id;
            $('#password-dialog-title').textContent = `重置 ${button.dataset.name} 的密码`;
            $('#reset-password').value = '';
            $('#password-dialog').showModal();
            return;
        }
        const payload = button.dataset.userAction === 'role'
            ? {role: button.dataset.value}
            : {active: button.dataset.value === 'true'};
        try {
            await api(`/admin/users/${button.dataset.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
            await loadAll();
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    $$('[data-close-password]').forEach(button => button.addEventListener('click', () => $('#password-dialog').close()));
    $('#password-form').addEventListener('submit', async event => {
        event.preventDefault();
        try {
            await api(`/admin/users/${passwordUserId}`, {
                method: 'PATCH', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: $('#reset-password').value})
            });
            $('#password-dialog').close();
            notify('密码已重置', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    $('#settings-form').addEventListener('submit', async event => {
        event.preventDefault();
        try {
            await api('/settings', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    default_voice: $('#settings-default-voice').value,
                    default_speech_rate: $('#settings-default-rate').value,
                    default_volume: $('#settings-default-volume').value,
                    default_pitch: $('#settings-default-pitch').value,
                    proxy_url: $('#settings-proxy').value.trim(),
                    default_save_dir: $('#settings-save-dir').value.trim(),
                    chunk_length: Number($('#settings-chunk-length').value),
                    task_retention_days: Number($('#settings-task-days').value),
                    history_retention_days: Number($('#settings-history-days').value),
                    temp_file_ttl_hours: Number($('#settings-temp-hours').value),
                    auto_open_browser: $('#settings-auto-open').checked
                })
            });
            notify('系统设置已保存', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    loadAll();
});
