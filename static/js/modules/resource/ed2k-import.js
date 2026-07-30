(function (global) {
    'use strict';

    const CJK_TOKEN_REGEX = /^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$/u;
    const TITLE_TOKEN_REGEX = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*/gu;

    function normalizeRelativePath(value) {
        return String(value || '')
            .split(/[\\/]+/)
            .map(part => part.trim())
            .filter(Boolean)
            .join('/');
    }

    function tokenizeTitle(value) {
        const source = String(value || '');
        const tokens = [];
        for (const match of source.matchAll(TITLE_TOKEN_REGEX)) {
            tokens.push({
                text: match[0],
                start: Number(match.index || 0),
                end: Number(match.index || 0) + match[0].length,
                source,
                isCjk: CJK_TOKEN_REGEX.test(match[0]),
            });
        }
        return tokens;
    }

    function applySelectionRange(selectedIndexes, startIndex, endIndex, shouldSelect) {
        const selected = new Set(
            (Array.isArray(selectedIndexes) ? selectedIndexes : [])
                .map(value => Number(value))
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

    function composeFolderName(tokens, selectedIndexes) {
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

    function buildTargetSavepath(parentSavepath, folderName, createFolder = true) {
        const parent = normalizeRelativePath(parentSavepath);
        if (!createFolder) return parent;
        const child = normalizeRelativePath(folderName);
        return [parent, child].filter(Boolean).join('/');
    }

    function shouldShowTitleSelector(active, ready, createFolder) {
        return !!active && !!ready && createFolder !== false;
    }

    function parseEd2kLink(value) {
        const linkUrl = String(value || '').trim();
        const parts = linkUrl.split('|');
        if (
            parts.length < 6
            || parts[0].toLowerCase() !== 'ed2k://'
            || parts[1].toLowerCase() !== 'file'
            || parts[parts.length - 1] !== '/'
        ) {
            throw new Error('不是有效的 ED2K 文件链接');
        }
        let filename = String(parts[2] || '').trim();
        try {
            filename = decodeURIComponent(filename);
        } catch (error) {
            // 保留未编码文件名，后端仍会执行最终校验。
        }
        const sizeBytes = Number(parts[3]);
        const fileHash = String(parts[4] || '').trim().toLowerCase();
        if (!filename || !Number.isSafeInteger(sizeBytes) || sizeBytes <= 0 || !/^[a-f0-9]{32}$/.test(fileHash)) {
            throw new Error('ED2K 文件信息无效');
        }
        return {
            id: `${fileHash}:${sizeBytes}`,
            filename,
            title: filename,
            size_bytes: sizeBytes,
            file_hash: fileHash,
            link_url: linkUrl,
            link_type: 'ed2k',
        };
    }

    global.ResourceEd2kImport = Object.freeze({
        applySelectionRange,
        buildTargetSavepath,
        composeFolderName,
        normalizeRelativePath,
        parseEd2kLink,
        shouldShowTitleSelector,
        tokenizeTitle,
    });
})(window);
