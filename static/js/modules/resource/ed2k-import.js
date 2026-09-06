(function (global) {
    'use strict';

    const textSelection = global.MediaHubTextSelection;
    if (!textSelection) throw new Error('MediaHubTextSelection 尚未加载');
    const FOLDER_CHARACTER_REPLACEMENTS = Object.freeze({
        '*': '＊',
        '?': '？',
        '"': '＂',
        '<': '＜',
        '>': '＞',
        '|': '｜',
    });

    function normalizeRelativePath(value) {
        return String(value || '')
            .split(/[\\/]+/)
            .map(part => part.trim())
            .filter(Boolean)
            .join('/');
    }

    function tokenizeTitle(value) {
        return textSelection.tokenize(value);
    }

    function applySelectionRange(selectedIndexes, startIndex, endIndex, shouldSelect) {
        return textSelection.applySelectionRange(selectedIndexes, startIndex, endIndex, shouldSelect);
    }

    function composeFolderName(tokens, selectedIndexes) {
        return textSelection.compose(tokens, selectedIndexes);
    }

    function cleanFolderName(value) {
        return String(value || '')
            .replace(/[\u0000-\u001f\u007f]+/gu, '')
            .replace(/[\\/]+/gu, ' ')
            .replace(/[*?"<>|]/gu, character => FOLDER_CHARACTER_REPLACEMENTS[character] || '')
            .replace(/\s+/gu, ' ')
            .trim();
    }

    function normalizeFolderName(value, fallback = '') {
        let cleaned = cleanFolderName(value);
        if (!cleaned || cleaned === '.' || cleaned === '..') cleaned = cleanFolderName(fallback);
        if (!cleaned || cleaned === '.' || cleaned === '..') return '';
        return Array.from(cleaned).slice(0, 120).join('');
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

    function collectDirectEd2kItems(resource) {
        const allLinks = Array.isArray(resource?.extra?.all_links) ? resource.extra.all_links : [];
        const values = [...allLinks, resource?.link_url];
        const seenIds = new Set();
        const items = [];
        for (const value of values) {
            try {
                const item = parseEd2kLink(value);
                if (seenIds.has(item.id)) continue;
                seenIds.add(item.id);
                items.push(item);
            } catch (error) {
                // 同帖中的其他资源链接和格式错误的 ED2K 链接不应阻断可保存文件。
            }
        }
        return items;
    }

    const GENERIC_TITLE_PATTERN = /^(ed2k任务|磁力任务|未命名资源|资源任务|链接任务|115分享任务|夸克分享任务)(?:\s*#\d+)?$/i;
    const LINK_LIKE_TITLE_PATTERN = /^(ed2k:\/\/|magnet:\?|https?:\/\/|tg:\/\/)/i;

    function isGenericResourceTitle(value) {
        const text = String(value || '').trim();
        if (!text) return true;
        if (LINK_LIKE_TITLE_PATTERN.test(text)) return true;
        return GENERIC_TITLE_PATTERN.test(text);
    }

    function resolveFolderTitleSource(item, items) {
        const recordTitle = String(item?.title || '').trim();
        if (!isGenericResourceTitle(recordTitle)) return recordTitle;
        const firstItem = (Array.isArray(items) ? items : []).find(
            entry => entry && String(entry.filename || entry.title || '').trim()
        );
        return firstItem
            ? String(firstItem.filename || firstItem.title || '').trim()
            : '';
    }

    global.ResourceEd2kImport = Object.freeze({
        applySelectionRange,
        buildTargetSavepath,
        collectDirectEd2kItems,
        composeFolderName,
        isGenericResourceTitle,
        normalizeFolderName,
        normalizeRelativePath,
        parseEd2kLink,
        resolveFolderTitleSource,
        shouldShowTitleSelector,
        tokenizeTitle,
    });
})(window);
