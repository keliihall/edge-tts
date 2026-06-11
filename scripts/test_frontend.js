const assert = require('node:assert/strict');
const {merge} = require('../static/js/file-selection.js');

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

console.log('Frontend state tests passed');
