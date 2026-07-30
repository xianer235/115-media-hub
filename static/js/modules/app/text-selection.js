(function (global) {
    'use strict';

    const CJK_TOKEN_REGEX = /^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$/u;
    const TEXT_TOKEN_REGEX = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*/gu;

    function tokenize(value) {
        const source = String(value || '');
        return Array.from(source.matchAll(TEXT_TOKEN_REGEX), match => ({
            text: match[0],
            start: Number(match.index || 0),
            end: Number(match.index || 0) + match[0].length,
            source,
            isCjk: CJK_TOKEN_REGEX.test(match[0]),
        }));
    }

    function applySelectionRange(selectedIndexes, startIndex, endIndex, shouldSelect) {
        const selected = new Set(
            (Array.isArray(selectedIndexes) ? selectedIndexes : [])
                .map(Number)
                .filter(value => Number.isInteger(value) && value >= 0)
        );
        const start = Math.max(0, Math.min(Number(startIndex) || 0, Number(endIndex) || 0));
        const end = Math.max(0, Math.max(Number(startIndex) || 0, Number(endIndex) || 0));
        for (let index = start; index <= end; index += 1) {
            if (shouldSelect) selected.add(index);
            else selected.delete(index);
        }
        return Array.from(selected).sort((left, right) => left - right);
    }

    function compose(tokens, selectedIndexes) {
        const sourceTokens = Array.isArray(tokens) ? tokens : [];
        const selected = new Set(Array.isArray(selectedIndexes) ? selectedIndexes.map(Number) : []);
        const chosen = sourceTokens
            .map((token, index) => ({ token, index }))
            .filter(item => selected.has(item.index));
        let result = '';
        let previous = null;
        for (const item of chosen) {
            const token = item.token || {};
            if (previous) {
                const source = String(token.source || previous.token?.source || '');
                const gap = source.slice(Number(previous.token?.end || 0), Number(token.start || 0));
                const directlyAdjacentCjk = (
                    item.index === previous.index + 1
                    && gap === ''
                    && previous.token?.isCjk
                    && token.isCjk
                );
                if (!directlyAdjacentCjk && result && !result.endsWith(' ')) result += ' ';
            }
            result += String(token.text || '');
            previous = item;
        }
        return result.replace(/\s+/g, ' ').trim();
    }

    global.MediaHubTextSelection = Object.freeze({
        applySelectionRange,
        compose,
        tokenize,
    });
})(window);
