(function exposeFileSelection(root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    } else {
        root.EdgeTtsFiles = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : window, function createFileSelection() {
    function signature(file) {
        return `${file.name}:${file.size}:${file.lastModified || 0}`;
    }

    function merge(existing, incoming, maximum) {
        const merged = existing.slice();
        const known = new Set(merged.map(signature));
        let duplicateCount = 0;
        let overflowCount = 0;

        incoming.forEach(file => {
            const key = signature(file);
            if (known.has(key)) {
                duplicateCount += 1;
                return;
            }
            if (merged.length >= maximum) {
                overflowCount += 1;
                return;
            }
            merged.push(file);
            known.add(key);
        });

        return {files: merged, duplicateCount, overflowCount};
    }

    return {merge, signature};
}));
