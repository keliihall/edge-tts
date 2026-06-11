document.addEventListener('DOMContentLoaded', () => {
    const text = document.querySelector('#quick-text');
    const generateButton = document.querySelector('#quick-generate-btn');
    const toast = document.querySelector('#home-toast');

    function notify(message, type = 'info') {
        toast.textContent = message;
        toast.dataset.type = type;
        toast.classList.add('show');
        clearTimeout(notify.timer);
        notify.timer = setTimeout(() => toast.classList.remove('show'), 3200);
    }

    async function api(url, options = {}) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data?.error?.message || '操作失败，请稍后重试');
        return data;
    }

    function resizeInput() {
        text.style.height = 'auto';
        text.style.height = `${Math.min(Math.max(text.scrollHeight, 92), 240)}px`;
    }

    function openStudio() {
        const draft = text.value.trim();
        if (draft) sessionStorage.setItem('shengjian-studio-draft', draft);
        window.location.href = '/studio';
    }

    async function createQuickTask(event) {
        event.preventDefault();
        const content = text.value.trim();
        if (!content) return notify('请先输入需要转换的文字', 'error');
        const form = new FormData();
        form.append('text', content);
        try {
            generateButton.disabled = true;
            generateButton.textContent = '正在创建...';
            const task = await api('/convert', {method: 'POST', body: form});
            window.location.href = `/studio?task=${encodeURIComponent(task.id)}#tasks-title`;
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            generateButton.disabled = false;
            generateButton.textContent = '立即生成';
        }
    }

    text.addEventListener('input', resizeInput);
    text.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            document.querySelector('#quick-start-form').requestSubmit();
        }
    });
    document.querySelector('#quick-start-form').addEventListener('submit', createQuickTask);
    document.querySelector('#open-studio-btn').addEventListener('click', openStudio);
    document.querySelector('#home-logout').addEventListener('click', async () => {
        await fetch('/auth/logout', {method: 'POST'});
        window.location.href = '/login';
    });

    resizeInput();
});
