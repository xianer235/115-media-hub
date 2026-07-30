(function (global) {
    'use strict';

    const textSelection = global.MediaHubTextSelection;
    if (!textSelection) throw new Error('MediaHubTextSelection 尚未加载');

    function normalizePath(value) {
        return String(value || '')
            .split(/[\\/]+/)
            .map(part => part.trim())
            .filter(Boolean)
            .join('/');
    }

    function getEntryParentPath(entry, fallbackPath) {
        const item = entry && typeof entry === 'object' ? entry : {};
        if (Object.prototype.hasOwnProperty.call(item, 'parent_path')) {
            return normalizePath(item.parent_path);
        }
        const path = normalizePath(item.path);
        if (!path) return normalizePath(fallbackPath);
        const parts = path.split('/');
        parts.pop();
        return parts.join('/');
    }

    function getCommonPath(paths) {
        const splitPaths = (Array.isArray(paths) ? paths : [])
            .map(path => normalizePath(path).split('/').filter(Boolean));
        if (!splitPaths.length || splitPaths.some(parts => !parts.length)) return '';
        const first = splitPaths[0];
        let sharedLength = first.length;
        for (const parts of splitPaths.slice(1)) {
            sharedLength = Math.min(sharedLength, parts.length);
            let index = 0;
            while (index < sharedLength && parts[index] === first[index]) index += 1;
            sharedLength = index;
            if (!sharedLength) break;
        }
        return first.slice(0, sharedLength).join('/');
    }

    function resolveSourcePath(entries, currentParentPath) {
        const items = (Array.isArray(entries) ? entries : [])
            .filter(item => item && typeof item === 'object');
        const fallbackPath = normalizePath(currentParentPath);
        if (!items.length) return fallbackPath;
        if (items.length === 1 && items[0].is_dir) {
            const item = items[0];
            return normalizePath(item.path || [item.parent_path, item.name].filter(Boolean).join('/'));
        }
        return getCommonPath(items.map(item => getEntryParentPath(item, fallbackPath)));
    }

    function createSelection(entries, currentParentPath) {
        const source = resolveSourcePath(entries, currentParentPath);
        return {
            source,
            tokens: textSelection.tokenize(source),
            selectedIndexes: [],
            expanded: true,
        };
    }

    function composeQuery(selection) {
        const value = selection && typeof selection === 'object' ? selection : {};
        return textSelection.compose(value.tokens, value.selectedIndexes);
    }

    global.ScraperPathSelection = Object.freeze({
        composeQuery,
        createSelection,
        resolveSourcePath,
    });
})(window);
