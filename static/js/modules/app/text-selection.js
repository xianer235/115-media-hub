(function (global) {
    'use strict';

    const CJK_TOKEN_REGEX = /^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$/u;
    const ASCII_WORD_CHAR_REGEX = /^[A-Za-z0-9]$/u;
    const PUNCTUATION_REGEX = /^[\p{P}\p{S}]$/u;
    const EMOJI_REGEX = /^\p{Extended_Pictographic}$/u;
    const EXCLUDED_SYMBOLS = new Set(['/', '\\', '*', '?', '"', '<', '>', '|']);

    function isSelectableSymbol(value) {
        const character = String(value || '');
        return !!character
            && !/\s/u.test(character)
            && !EXCLUDED_SYMBOLS.has(character)
            && PUNCTUATION_REGEX.test(character)
            && !EMOJI_REGEX.test(character);
    }

    function pushToken(tokens, source, start, end) {
        const text = source.slice(start, end);
        if (!text) return;
        tokens.push({
            text,
            start,
            end,
            source,
            isCjk: CJK_TOKEN_REGEX.test(text),
        });
    }

    function tokenize(value) {
        const source = String(value || '');
        const tokens = [];
        let index = 0;
        while (index < source.length) {
            const codePoint = source.codePointAt(index);
            const character = String.fromCodePoint(codePoint);
            const width = character.length;
            if (CJK_TOKEN_REGEX.test(character) || ASCII_WORD_CHAR_REGEX.test(character)) {
                const start = index;
                index += width;
                if (ASCII_WORD_CHAR_REGEX.test(character)) {
                    while (index < source.length && ASCII_WORD_CHAR_REGEX.test(source[index])) index += 1;
                }
                pushToken(tokens, source, start, index);
                continue;
            }
            if (isSelectableSymbol(character)) pushToken(tokens, source, index, index + width);
            index += width;
        }
        return tokens;
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

    function normalizeComposedText(value) {
        return String(value || '')
            .replace(/[\\/]+/gu, ' ')
            .replace(/\s+/gu, ' ')
            .trim();
    }

    function compose(tokens, selectedIndexes) {
        const sourceTokens = Array.isArray(tokens) ? tokens : [];
        const selected = Array.from(new Set(
            (Array.isArray(selectedIndexes) ? selectedIndexes : [])
                .map(Number)
                .filter(index => Number.isInteger(index) && index >= 0 && index < sourceTokens.length)
        )).sort((left, right) => left - right);
        if (!selected.length) return '';

        const ranges = [];
        for (const index of selected) {
            const previous = ranges[ranges.length - 1];
            if (previous && index === previous.endIndex + 1) previous.endIndex = index;
            else ranges.push({ startIndex: index, endIndex: index });
        }

        const parts = ranges.map(range => {
            let part = '';
            let previous = null;
            for (let index = range.startIndex; index <= range.endIndex; index += 1) {
                const token = sourceTokens[index] || {};
                const text = String(token.text || '');
                if (!text) continue;
                if (previous) {
                    const sameSource = token.source && previous.source && token.source === previous.source;
                    const gap = sameSource
                        ? String(token.source).slice(Number(previous.end || 0), Number(token.start || 0))
                        : ' ';
                    if (/[\s\\/]/u.test(gap) && part && !part.endsWith(' ')) part += ' ';
                }
                part += text;
                previous = token;
            }
            return normalizeComposedText(part);
        }).filter(Boolean);
        return normalizeComposedText(parts.join(' '));
    }

    global.MediaHubTextSelection = Object.freeze({
        applySelectionRange,
        compose,
        tokenize,
    });
})(window);
