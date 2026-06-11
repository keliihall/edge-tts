const assert = require('node:assert/strict');
const {merge} = require('../static/js/file-selection.js');
const taskView = require('../static/js/task-view-state.js');

const first = {name: 'first.txt', size: 10, lastModified: 1};
const second = {name: 'second.txt', size: 20, lastModified: 2};
const third = {name: 'third.txt', size: 30, lastModified: 3};

const appended = merge([first], [second], 20);
assert.deepEqual(appended.files, [first, second]);

const deduplicated = merge(appended.files, [first, third], 20);
assert.deepEqual(deduplicated.files, [first, second, third]);
assert.equal(deduplicated.duplicateCount, 1);

const limited = merge([first, second], [third], 2);
assert.deepEqual(limited.files, [first, second]);
assert.equal(limited.overflowCount, 1);

const expandedTaskIds = new Set();
assert.equal(taskView.toggle(expandedTaskIds, 'task-1'), true);
assert.equal(expandedTaskIds.has('task-1'), true);

taskView.prune(expandedTaskIds, [{id: 'task-1'}, {id: 'task-2'}]);
assert.equal(expandedTaskIds.has('task-1'), true);

taskView.prune(expandedTaskIds, [{id: 'task-2'}]);
assert.equal(expandedTaskIds.has('task-1'), false);
assert.equal(taskView.toggle(expandedTaskIds, 'task-2'), true);
assert.equal(taskView.toggle(expandedTaskIds, 'task-2'), false);

const finishedTask = {
    id: 'task-audio',
    status: 'finished',
    audio_url: '/jobs/task-audio/audio',
    items: [{id: 'item-1', status: 'done'}]
};
const matchingCard = {
    dataset: {
        taskId: finishedTask.id,
        renderKey: taskView.renderKey(finishedTask)
    }
};
assert.equal(taskView.canReuseCard(matchingCard, finishedTask), true);
assert.equal(taskView.canReuseCard(matchingCard, {...finishedTask, status: 'processing'}), false);
assert.equal(taskView.canReuseCard(matchingCard, {...finishedTask, items: [{id: 'item-1', status: 'failed'}]}), false);

console.log('Frontend state tests passed');
