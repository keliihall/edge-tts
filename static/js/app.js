document.addEventListener('DOMContentLoaded', () => {
    const config = window.EDGE_TTS_CONFIG;
    const $ = selector => document.querySelector(selector);
    const $$ = selector => Array.from(document.querySelectorAll(selector));
    const state = {
        voices: [],
        favorites: [],
        selectedFiles: [],
        tasks: [],
        autoDownload: 'off',
        pollTimer: null
    };

    const elements = {
        voice: $('#voice-select'),
        voiceSearch: $('#voice-search'),
        voiceDescription: $('#voice-description'),
        rate: $('#speech-rate-select'),
        volume: $('#volume-select'),
        pitch: $('#pitch-select'),
        text: $('#text-input'),
        textCounter: $('#text-counter'),
        previewAudio: $('#preview-audio'),
        files: $('#batch-files'),
        fileList: $('#batch-file-list'),
        fileSummary: $('#batch-file-summary'),
        taskList: $('#task-list'),
        taskSummary: $('#task-summary'),
        taskFilter: $('#task-filter'),
        favoriteSelect: $('#favorite-select'),
        favoriteDialog: $('#favorite-dialog'),
        favoritePreview: $('#favorite-preview'),
        autoDownload: $('#auto-download-select'),
        toast: $('#toast')
    };
    const settingsDisclosure = $('.settings-disclosure');
    const compactSettingsMedia = window.matchMedia('(max-width: 680px)');
    if (settingsDisclosure) {
        if (compactSettingsMedia.matches) settingsDisclosure.open = false;
        compactSettingsMedia.addEventListener('change', event => {
            if (!event.matches) settingsDisclosure.open = true;
        });
    }

    function notify(message, type = 'info') {
        elements.toast.textContent = message;
        elements.toast.dataset.type = type;
        elements.toast.classList.add('show');
        clearTimeout(notify.timer);
        notify.timer = setTimeout(() => elements.toast.classList.remove('show'), 3200);
    }

    async function api(url, options = {}) {
        const response = await fetch(url, options);
        const contentType = response.headers.get('content-type') || '';
        const data = contentType.includes('application/json') ? await response.json() : null;
        if (!response.ok) throw new Error(data?.error?.message || '操作失败，请稍后重试');
        return data;
    }

    function formatDuration(value) {
        if (value === null || value === undefined) return '估算中';
        const seconds = Math.max(0, Math.round(value));
        if (seconds < 60) return `${seconds} 秒`;
        return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    }

    function formatTime(value, empty = '尚未开始') {
        if (!value) return empty;
        return new Date(value * 1000).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    }

    function formatBytes(value) {
        if (!value) return '0 B';
        if (value < 1024) return `${value} B`;
        return `${(value / 1024).toFixed(1)} KB`;
    }

    function statusLabel(status) {
        return ({
            queued: '排队中', processing: '处理中', finished: '已结束',
            cancelled: '已取消', pending: '等待中', done: '已完成', failed: '失败'
        })[status] || status;
    }

    function currentVoice() {
        return state.voices.find(item => item.id === elements.voice.value);
    }

    function configLabel(values = {}) {
        const voice = state.voices.find(item => item.id === (values.voice || elements.voice.value));
        const rate = values.speech_rate || elements.rate.value;
        const volume = values.volume || elements.volume.value;
        const pitch = values.pitch ?? elements.pitch.value;
        const pitchLabel = pitch === '0' ? '标准音高' : `${Number(pitch) > 0 ? '+' : ''}${pitch}Hz`;
        return `${voice?.name || '未选音色'} · ${rate}x · ${Math.round(Number(volume) * 100)}% · ${pitchLabel}`;
    }

    function renderVoices() {
        const query = elements.voiceSearch.value.trim().toLowerCase();
        const previous = elements.voice.value || config.settings.default_voice;
        const filtered = state.voices.filter(item =>
            [item.name, item.id, item.style, item.locale].join(' ').toLowerCase().includes(query)
        );
        elements.voice.replaceChildren(...filtered.map(item => {
            const option = document.createElement('option');
            option.value = item.id;
            option.textContent = `${item.name} · ${item.gender}`;
            return option;
        }));
        if (filtered.some(item => item.id === previous)) elements.voice.value = previous;
        updateVoiceDescription();
    }

    function updateVoiceDescription() {
        const voice = currentVoice();
        elements.voiceDescription.textContent = voice
            ? `${voice.gender}声 · ${voice.style || voice.locale || '通用'}`
            : '没有匹配的音色';
        updateActiveConfig();
    }

    function updateActiveConfig() {
        $$('.active-config-summary').forEach(element => {
            element.textContent = configLabel();
        });
        $$('.compact-config-summary').forEach(element => {
            element.textContent = configLabel();
        });
    }

    function renderFavorites() {
        const current = elements.favoriteSelect.value;
        elements.favoriteSelect.innerHTML = '<option value="">选择收藏配置</option>';
        state.favorites.forEach(item => {
            const option = document.createElement('option');
            option.value = item.id;
            option.textContent = item.name;
            elements.favoriteSelect.appendChild(option);
        });
        if (state.favorites.some(item => item.id === current)) elements.favoriteSelect.value = current;
        $('#delete-favorite-btn').disabled = !elements.favoriteSelect.value;
    }

    function applyFavorite(favorite) {
        if (!favorite) return;
        elements.voiceSearch.value = '';
        renderVoices();
        elements.voice.value = favorite.voice;
        elements.rate.value = favorite.speech_rate;
        elements.volume.value = favorite.volume;
        elements.pitch.value = favorite.pitch;
        updateVoiceDescription();
        notify(`已应用“${favorite.name}”`, 'success');
    }

    function renderFiles() {
        elements.fileList.innerHTML = '';
        elements.fileList.classList.toggle('empty', state.selectedFiles.length === 0);
        elements.fileSummary.textContent = state.selectedFiles.length
            ? `已添加 ${state.selectedFiles.length} 个文件`
            : '尚未添加文件';
        if (!state.selectedFiles.length) {
            elements.fileList.textContent = '文件会在这里按选择顺序排列';
            return;
        }
        state.selectedFiles.forEach((file, index) => {
            const row = document.createElement('div');
            row.className = 'file-row';
            row.innerHTML = `<div><strong>${escapeHtml(file.name)}</strong><small>${formatBytes(file.size)}</small></div>
                <button class="icon-button" type="button" data-remove-file="${index}" aria-label="移除 ${escapeHtml(file.name)}">×</button>`;
            elements.fileList.appendChild(row);
        });
    }

    function escapeHtml(value) {
        const node = document.createElement('span');
        node.textContent = String(value ?? '');
        return node.innerHTML;
    }

    function taskActionUrl(task, action, itemId = '') {
        if (task.kind === 'text') {
            if (action === 'status') return `/jobs/${task.id}`;
            if (action === 'cancel') return `/jobs/${task.id}/cancel`;
            if (action === 'retry') return `/jobs/${task.id}/items/${itemId}/retry`;
            if (action === 'download') return `/jobs/${task.id}/download`;
            if (action === 'audio') return task.audio_url;
        }
        if (action === 'status') return `/batch/status/${task.id}`;
        if (action === 'cancel') return `/batch/job/${task.id}/cancel`;
        if (action === 'retry') return `/batch/job/${task.id}/items/${itemId}/retry`;
        if (action === 'download') return `/batch/download/${task.id}`;
        return '';
    }

    function renderTaskSummary(tasks) {
        const active = tasks.filter(item => ['queued', 'processing'].includes(item.status)).length;
        const completed = tasks.filter(item => item.status === 'finished').length;
        const failed = tasks.reduce((sum, item) => sum + item.failed_count, 0);
        elements.taskSummary.innerHTML = `
            <span><strong>${tasks.length}</strong> 总任务</span>
            <span><strong>${active}</strong> 进行中</span>
            <span><strong>${completed}</strong> 已结束</span>
            ${failed ? `<span class="danger"><strong>${failed}</strong> 失败项</span>` : ''}`;
    }

    function taskTimeline(task) {
        const eta = task.status === 'queued'
            ? `队列第 ${task.queue_position || 1} 位`
            : task.status === 'processing'
                ? `预计剩余 ${formatDuration(task.estimated_remaining_seconds)}`
                : `结束于 ${formatTime(task.finished_at, '未记录')}`;
        return `
            <div><span>创建</span><strong>${formatTime(task.created_at)}</strong></div>
            <div><span>开始</span><strong>${formatTime(task.started_at)}</strong></div>
            <div><span>已耗时</span><strong>${formatDuration(task.elapsed_seconds || 0)}</strong></div>
            <div><span>${task.status === 'finished' || task.status === 'cancelled' ? '结束' : '预期'}</span><strong>${eta}</strong></div>`;
    }

    function taskItemRow(task, item) {
        const name = task.kind === 'batch' ? item.source_name : (task.total > 1 ? `片段 ${item.index}` : '完整文本');
        const error = item.error ? `<p class="item-error">${escapeHtml(item.error)}</p>` : '';
        const retry = ['failed', 'cancelled'].includes(item.status) && !['queued', 'processing'].includes(task.status)
            ? `<button class="small-button" data-task-action="retry" data-task="${task.id}" data-item="${item.id}">重试</button>`
            : '';
        const download = task.kind === 'batch' && item.status === 'done'
            ? `<a class="small-button" href="/batch/download/${task.id}/${item.id}">下载</a>`
            : '';
        const timing = item.started_at
            ? ` · ${formatTime(item.started_at)} 开始${item.finished_at ? ` · ${formatTime(item.finished_at)} 结束` : ''}`
            : ' · 尚未开始';
        const remaining = ['pending', 'processing'].includes(item.status)
            ? ` · 预计剩余 ${formatDuration(item.estimated_remaining_seconds)}`
            : '';
        return `<div class="task-item ${item.status}">
            <div><strong>${escapeHtml(name)}</strong><small>${item.text_length} 字 · 尝试 ${item.attempts || 0} 次${item.elapsed_seconds != null ? ` · 耗时 ${formatDuration(item.elapsed_seconds)}` : ''}${remaining}${timing}</small>${error}</div>
            <div class="item-actions"><span class="status-badge ${item.status}">${statusLabel(item.status)}</span>${retry}${download}</div>
        </div>`;
    }

    function renderTasks() {
        const filter = elements.taskFilter.value;
        const tasks = filter ? state.tasks.filter(item => item.status === filter) : state.tasks;
        renderTaskSummary(state.tasks);
        elements.taskList.innerHTML = '';
        elements.taskList.classList.toggle('empty-state', tasks.length === 0);
        if (!tasks.length) {
            elements.taskList.textContent = filter ? '当前筛选下没有任务' : '暂无任务';
            return;
        }
        tasks.forEach(task => {
            const progress = task.total ? Math.round(task.completed / task.total * 100) : 0;
            const failure = task.failed_count ? `<span class="metric danger">${task.failed_count} 失败</span>` : '';
            const canDownload = task.success_count > 0 && !['queued', 'processing'].includes(task.status);
            const card = document.createElement('article');
            card.className = `task-card ${task.status}`;
            card.innerHTML = `
                <div class="task-card-head">
                    <div><span class="task-kind">${task.kind === 'text' ? '文本' : '批量'}</span><h3>${escapeHtml(task.title)}</h3><p>${configLabel(task)}</p></div>
                    <span class="status-badge ${task.status}">${statusLabel(task.status)}</span>
                </div>
                <div class="progress-line"><i style="width:${progress}%"></i></div>
                <div class="task-metrics">
                    <span class="metric"><strong>${task.completed}/${task.total}</strong> 已处理</span>
                    <span class="metric">${task.success_count} 完成</span>${failure}
                </div>
                <div class="task-timeline">${taskTimeline(task)}</div>
                <div class="task-actions">
                    ${['queued', 'processing'].includes(task.status) ? `<button class="secondary-button" data-task-action="cancel" data-task="${task.id}">取消任务</button>` : ''}
                    ${canDownload ? `<a class="primary-button" href="${taskActionUrl(task, 'download')}">${task.kind === 'batch' ? '下载 ZIP' : '下载 MP3'}</a>` : ''}
                    ${task.kind === 'text' && task.audio_url ? `<button class="secondary-button" data-task-action="play" data-task="${task.id}">播放</button>` : ''}
                    <button class="quiet-button details-toggle" data-task-action="details" data-task="${task.id}">查看 ${task.total} 个分项</button>
                    ${!['queued', 'processing'].includes(task.status) ? `<button class="quiet-button danger-text" data-task-action="delete" data-task="${task.id}">删除</button>` : ''}
                </div>
                <audio class="task-audio" controls hidden></audio>
                <div class="task-items" hidden>${task.items.map(item => taskItemRow(task, item)).join('')}</div>`;
            elements.taskList.appendChild(card);
        });
    }

    function maybeAutoDownload(task) {
        if (!['finished'].includes(task.status) || task.success_count === 0) return;
        if (state.autoDownload === 'off' || (state.autoDownload === 'single' && task.kind !== 'text')) return;
        const key = `edge-tts-downloaded-${task.kind}-${task.id}`;
        if (localStorage.getItem(key)) return;
        localStorage.setItem(key, '1');
        const link = document.createElement('a');
        link.href = taskActionUrl(task, 'download');
        link.download = '';
        document.body.appendChild(link);
        link.click();
        link.remove();
        notify(`“${task.title}”已完成并开始下载`, 'success');
    }

    async function loadTasks({quiet = false} = {}) {
        try {
            state.tasks = await api('/tasks?limit=100');
            state.tasks.forEach(maybeAutoDownload);
            renderTasks();
            const active = state.tasks.some(item => ['queued', 'processing'].includes(item.status));
            clearTimeout(state.pollTimer);
            state.pollTimer = setTimeout(() => loadTasks({quiet: true}), active ? 1200 : 5000);
        } catch (error) {
            if (!quiet) notify(error.message, 'error');
            clearTimeout(state.pollTimer);
            state.pollTimer = setTimeout(() => loadTasks({quiet: true}), 5000);
        }
    }

    async function createTextTask() {
        const text = elements.text.value.trim();
        if (!text) return notify('请先输入文本', 'error');
        const form = new FormData();
        form.append('text', text);
        appendVoiceConfig(form);
        try {
            $('#convert-btn').disabled = true;
            const task = await api('/convert', {method: 'POST', body: form});
            notify('文本任务已加入队列', 'success');
            elements.text.value = '';
            updateCounter();
            await loadTasks();
            document.querySelector('.task-center').scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            $('#convert-btn').disabled = false;
        }
    }

    function appendVoiceConfig(form) {
        form.append('voice', elements.voice.value);
        form.append('speech_rate', elements.rate.value);
        form.append('volume', elements.volume.value);
        form.append('pitch', elements.pitch.value);
    }

    async function createBatchTask() {
        if (!state.selectedFiles.length) return notify('请先添加 TXT 文件', 'error');
        const form = new FormData();
        appendVoiceConfig(form);
        state.selectedFiles.forEach(file => form.append('files', file));
        try {
            $('#batch-convert-btn').disabled = true;
            await api('/batch/convert', {method: 'POST', body: form});
            state.selectedFiles = [];
            elements.files.value = '';
            renderFiles();
            notify('批量任务已加入队列', 'success');
            await loadTasks();
            document.querySelector('.task-center').scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            $('#batch-convert-btn').disabled = false;
        }
    }

    async function taskAction(button) {
        const task = state.tasks.find(item => item.id === button.dataset.task);
        if (!task) return;
        const action = button.dataset.taskAction;
        try {
            if (action === 'details') {
                const card = button.closest('.task-card');
                const items = card.querySelector('.task-items');
                items.hidden = !items.hidden;
                button.textContent = items.hidden ? `查看 ${task.total} 个分项` : '收起分项';
                return;
            }
            if (action === 'play') {
                const audio = button.closest('.task-card').querySelector('.task-audio');
                audio.src = task.audio_url;
                audio.hidden = false;
                await audio.play().catch(() => {});
                return;
            }
            if (action === 'cancel') await api(taskActionUrl(task, 'cancel'), {method: 'POST'});
            if (action === 'retry') await api(taskActionUrl(task, 'retry', button.dataset.item), {method: 'POST'});
            if (action === 'delete') await api(`/tasks/${task.kind}/${task.id}`, {method: 'DELETE'});
            await loadTasks();
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    function updateCounter() {
        elements.textCounter.textContent = `${elements.text.value.length} / ${config.maxTextLength}`;
    }

    $$('.mode-tab').forEach(button => button.addEventListener('click', () => {
        $$('.mode-tab').forEach(item => item.classList.toggle('active', item === button));
        $$('.mode-panel').forEach(panel => panel.classList.toggle('active', panel.id === `${button.dataset.mode}-panel`));
    }));
    elements.voiceSearch.addEventListener('input', renderVoices);
    elements.voice.addEventListener('change', updateVoiceDescription);
    [elements.rate, elements.volume, elements.pitch].forEach(element =>
        element.addEventListener('change', updateActiveConfig)
    );
    elements.text.addEventListener('input', updateCounter);
    $('#convert-btn').addEventListener('click', createTextTask);
    $('#batch-convert-btn').addEventListener('click', createBatchTask);
    $('#preview-btn').addEventListener('click', async () => {
        if (!elements.text.value.trim()) return notify('请先输入试听文本', 'error');
        const form = new FormData();
        form.append('text', elements.text.value.trim());
        appendVoiceConfig(form);
        try {
            $('#preview-btn').disabled = true;
            const result = await api('/preview', {method: 'POST', body: form});
            elements.previewAudio.src = result.audio_url;
            elements.previewAudio.hidden = false;
            await elements.previewAudio.play().catch(() => {});
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            $('#preview-btn').disabled = false;
        }
    });
    elements.files.addEventListener('change', () => {
        const incoming = Array.from(elements.files.files).filter(file => file.name.toLowerCase().endsWith('.txt'));
        const result = window.EdgeTtsFiles.merge(state.selectedFiles, incoming, config.maxBatchFiles);
        state.selectedFiles = result.files;
        elements.files.value = '';
        if (result.duplicateCount) notify(`已忽略 ${result.duplicateCount} 个重复文件`);
        if (result.overflowCount) notify(`最多添加 ${config.maxBatchFiles} 个文件`, 'error');
        renderFiles();
    });
    elements.fileList.addEventListener('click', event => {
        const index = event.target.dataset.removeFile;
        if (index === undefined) return;
        state.selectedFiles.splice(Number(index), 1);
        renderFiles();
    });
    $('#batch-clear-btn').addEventListener('click', () => {
        state.selectedFiles = [];
        elements.files.value = '';
        renderFiles();
    });
    elements.favoriteSelect.addEventListener('change', () => {
        applyFavorite(state.favorites.find(item => item.id === elements.favoriteSelect.value));
        $('#delete-favorite-btn').disabled = !elements.favoriteSelect.value;
    });
    $('#save-favorite-btn').addEventListener('click', () => {
        elements.favoritePreview.textContent = configLabel();
        $('#favorite-name').value = '';
        elements.favoriteDialog.showModal();
    });
    $$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => elements.favoriteDialog.close()));
    $('#favorite-form').addEventListener('submit', async event => {
        event.preventDefault();
        try {
            const favorite = await api('/config-favorites', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: $('#favorite-name').value.trim(),
                    voice: elements.voice.value,
                    speech_rate: elements.rate.value,
                    volume: elements.volume.value,
                    pitch: elements.pitch.value
                })
            });
            state.favorites = [favorite, ...state.favorites.filter(item => item.name !== favorite.name)];
            renderFavorites();
            elements.favoriteSelect.value = favorite.id;
            $('#delete-favorite-btn').disabled = false;
            elements.favoriteDialog.close();
            notify('配置已加入收藏夹', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    $('#delete-favorite-btn').addEventListener('click', async () => {
        const id = elements.favoriteSelect.value;
        if (!id) return;
        try {
            await api(`/config-favorites/${id}`, {method: 'DELETE'});
            state.favorites = state.favorites.filter(item => item.id !== id);
            renderFavorites();
            notify('收藏已删除', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    elements.autoDownload.addEventListener('change', async () => {
        try {
            const result = await api('/preferences/workspace', {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({auto_download: elements.autoDownload.value})
            });
            state.autoDownload = result.auto_download;
            notify('自动下载偏好已保存', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    });
    elements.taskFilter.addEventListener('change', renderTasks);
    $('#refresh-tasks-btn').addEventListener('click', () => loadTasks());
    elements.taskList.addEventListener('click', event => {
        const target = event.target.closest('[data-task-action]');
        if (target) taskAction(target);
    });
    $('#logout-btn').addEventListener('click', async () => {
        await fetch('/auth/logout', {method: 'POST'});
        window.location.href = '/login';
    });

    Promise.all([
        api('/voices'),
        api('/preferences'),
        api('/config-favorites')
    ]).then(([voices, preferences, favorites]) => {
        state.voices = voices;
        state.favorites = favorites;
        state.autoDownload = preferences.auto_download || 'off';
        elements.autoDownload.value = state.autoDownload;
        renderVoices();
        elements.rate.value = config.settings.default_speech_rate || '1.0';
        elements.volume.value = config.settings.default_volume || '1.0';
        elements.pitch.value = config.settings.default_pitch || '0';
        renderFavorites();
        updateActiveConfig();
    }).catch(error => notify(error.message, 'error'));
    api('/health').then(data => {
        $('#network-status').classList.toggle('offline', !data.network_connectivity);
        $('#status-text').textContent = data.network_connectivity ? '服务可用' : '网络异常';
    }).catch(() => {
        $('#network-status').classList.add('offline');
        $('#status-text').textContent = '服务检查失败';
    });
    updateCounter();
    renderFiles();
    loadTasks();
});
