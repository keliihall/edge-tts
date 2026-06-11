(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.EdgeTtsTaskView = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    function toggle(expandedTaskIds, taskId) {
        if (expandedTaskIds.has(taskId)) {
            expandedTaskIds.delete(taskId);
            return false;
        }
        expandedTaskIds.add(taskId);
        return true;
    }

    function prune(expandedTaskIds, tasks) {
        const activeIds = new Set(tasks.map(task => task.id));
        for (const taskId of expandedTaskIds) {
            if (!activeIds.has(taskId)) expandedTaskIds.delete(taskId);
        }
        return expandedTaskIds;
    }

    function renderKey(task) {
        return JSON.stringify(task);
    }

    function canReuseCard(card, task) {
        return Boolean(
            card
            && card.dataset.taskId === String(task.id)
            && card.dataset.renderKey === renderKey(task)
        );
    }

    return {toggle, prune, renderKey, canReuseCard};
}));
