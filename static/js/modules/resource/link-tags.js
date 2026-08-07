(function (global) {
    'use strict';

    const CATEGORY_FALLBACK_TONES = Object.freeze({
        cloud: 'sky',
        offline: 'amber',
        direct: 'slate',
        unknown: 'neutral',
    });
    const TONES = new Set([
        'blue',
        'violet',
        'lime',
        'orange',
        'sky',
        'indigo',
        'amber',
        'emerald',
        'rose',
        'fuchsia',
        'teal',
        'green',
        'cyan',
        'red',
        'yellow',
        'pink',
        'slate',
        'neutral',
    ]);
    const IMPORT_MODES = new Set([
        'none',
        'ed2k-direct',
        'ed2k-page',
    ]);
    const rawDefinitions = [
        {
            type: '115share',
            label: '115网盘',
            category: 'cloud',
            tone: 'blue',
            actionType: '115share',
            patterns: [/(?:https?:\/\/)?(?:115cdn|115|anxia)\.com\/s\/[a-z0-9]+/i],
        },
        {
            type: 'quark',
            label: '夸克网盘',
            category: 'cloud',
            tone: 'violet',
            actionType: 'quark',
            patterns: [/https?:\/\/(?:pan|www)\.quark\.cn\/s\/[a-z0-9]+/i],
        },
        {
            type: 'guangya',
            label: '光鸭网盘',
            category: 'cloud',
            tone: 'lime',
            actionType: 'link',
            patterns: [
                /^https?:\/\/(?:www\.)?guangyapan\.com\/(?:share|s|link|download)\/[a-z0-9_-]+(?:[?#][^\s]*)?$/i,
            ],
        },
        {
            type: 'aliyun',
            label: '阿里云盘',
            category: 'cloud',
            tone: 'orange',
            actionType: 'aliyun',
            patterns: [/https?:\/\/(?:www\.)?(?:aliyundrive|alipan)\.com\/s\/[a-z0-9]+/i],
        },
        {
            type: 'baidu',
            label: '百度网盘',
            category: 'cloud',
            tone: 'sky',
            actionType: 'baidu',
            patterns: [/https?:\/\/(?:pan|yun)\.baidu\.com\/(?:s\/|share\/)/i],
        },
        {
            type: 'xunlei',
            label: '迅雷网盘',
            category: 'cloud',
            tone: 'indigo',
            actionType: 'xunlei',
            patterns: [/https?:\/\/(?:pan|xlpan)\.xunlei\.com\/s\/[a-z0-9]+/i],
        },
        {
            type: 'uc',
            label: 'UC网盘',
            category: 'cloud',
            tone: 'amber',
            actionType: 'uc',
            patterns: [/https?:\/\/drive\.uc\.cn\/s\/[a-z0-9]+/i],
        },
        {
            type: '123pan',
            label: '123云盘',
            category: 'cloud',
            tone: 'emerald',
            actionType: '123pan',
            patterns: [
                /https?:\/\/(?:www\.)?(?:123pan|123684|123865|123912)\.(?:com|cn)\/s\/[a-z0-9_-]+(?:\.html?)?/i,
            ],
        },
        {
            type: 'tianyi',
            label: '天翼云盘',
            category: 'cloud',
            tone: 'rose',
            actionType: 'tianyi',
            patterns: [/https?:\/\/cloud\.189\.cn\/(?:t\/|web\/share)/i],
        },
        {
            type: 'pikpak',
            label: 'PikPak',
            category: 'cloud',
            tone: 'fuchsia',
            actionType: 'pikpak',
            patterns: [/https?:\/\/(?:www\.)?(?:mypikpak|pikpak)\.com\/s\/[a-z0-9]+/i],
        },
        {
            type: 'lanzou',
            label: '蓝奏云',
            category: 'cloud',
            tone: 'teal',
            actionType: 'lanzou',
            patterns: [/https?:\/\/(?:www\.)?lanzou[a-z0-9]*\.[a-z.]+\/[a-z0-9]+/i],
        },
        {
            type: 'google_drive',
            label: 'Google Drive',
            category: 'cloud',
            tone: 'green',
            actionType: 'google_drive',
            patterns: [/https?:\/\/drive\.google\.com\//i],
        },
        {
            type: 'onedrive',
            label: 'OneDrive',
            category: 'cloud',
            tone: 'cyan',
            actionType: 'onedrive',
            patterns: [/https?:\/\/(?:1drv\.ms|onedrive\.live\.com)\//i],
        },
        {
            type: 'mega',
            label: 'MEGA',
            category: 'cloud',
            tone: 'red',
            actionType: 'mega',
            patterns: [/https?:\/\/mega\.nz\//i],
        },
        {
            type: 'magnet',
            label: '磁力',
            category: 'offline',
            tone: 'yellow',
            actionType: 'magnet',
            prefixes: ['magnet:?'],
        },
        {
            type: 'ed2k',
            label: '电驴',
            category: 'offline',
            tone: 'pink',
            actionType: 'ed2k',
            importMode: 'ed2k-direct',
            prefixes: ['ed2k://'],
        },
        {
            type: 'telegra_ed2k',
            label: '电驴',
            category: 'offline',
            tone: 'pink',
            actionType: 'ed2k',
            importMode: 'ed2k-page',
            patterns: [/^https?:\/\/telegra\.ph\/.+/i],
        },
        {
            type: 'link',
            label: '直链',
            category: 'direct',
            tone: 'slate',
            actionType: 'link',
            prefixes: ['http://', 'https://'],
        },
        {
            type: 'unknown',
            label: '待识别',
            category: 'unknown',
            tone: 'neutral',
            actionType: 'unknown',
        },
    ];

    function normalizeType(value) {
        return String(value || '').trim().toLowerCase();
    }

    const definitions = Object.freeze(rawDefinitions.map((raw, order) => {
        const category = CATEGORY_FALLBACK_TONES[raw.category] ? raw.category : 'unknown';
        const tone = TONES.has(raw.tone) ? raw.tone : CATEGORY_FALLBACK_TONES[category];
        return Object.freeze({
            type: normalizeType(raw.type) || 'unknown',
            label: String(raw.label || '待识别').trim() || '待识别',
            category,
            tone,
            actionType: normalizeType(raw.actionType || raw.type) || 'unknown',
            importMode: IMPORT_MODES.has(raw.importMode) ? raw.importMode : 'none',
            patterns: Object.freeze([...(raw.patterns || [])]),
            prefixes: Object.freeze((raw.prefixes || []).map(prefix => String(prefix).toLowerCase())),
            order,
        });
    }));
    const definitionsByType = new Map(definitions.map(definition => [definition.type, definition]));
    const unknownDefinition = definitionsByType.get('unknown');

    function publicMeta(definition) {
        const source = definition || unknownDefinition;
        return Object.freeze({
            type: source.type,
            label: source.label,
            category: source.category,
            tone: source.tone,
            actionType: source.actionType,
            importMode: source.importMode,
            order: source.order,
        });
    }

    function list() {
        return definitions.map(publicMeta);
    }

    function getTagMeta(type) {
        return publicMeta(definitionsByType.get(normalizeType(type)) || unknownDefinition);
    }

    function matchesDefinition(definition, value, lowered) {
        if (definition.prefixes.some(prefix => lowered.startsWith(prefix))) return true;
        return definition.patterns.some(pattern => {
            pattern.lastIndex = 0;
            return pattern.test(value);
        });
    }

    function detect(url) {
        const value = String(url || '').trim();
        if (!value) return 'unknown';
        const lowered = value.toLowerCase();
        for (const definition of definitions) {
            if (definition.type === 'unknown') continue;
            if (matchesDefinition(definition, value, lowered)) return definition.type;
        }
        return 'unknown';
    }

    function normalizeItem(item) {
        if (item && typeof item === 'object' && !Array.isArray(item)) return item;
        return { link_url: String(item || '') };
    }

    function resolveDisplayType(item) {
        const payload = normalizeItem(item);
        const rawType = normalizeType(payload.link_type);
        const detected = detect(payload.link_url);
        if (detected !== 'link' && detected !== 'unknown') return detected;
        if (rawType && rawType !== 'link' && rawType !== 'unknown' && definitionsByType.has(rawType)) {
            return rawType;
        }
        if (detected === 'link') return 'link';
        if (rawType && definitionsByType.has(rawType)) return rawType;
        return 'unknown';
    }

    function resolveActionType(item) {
        return getTagMeta(resolveDisplayType(item)).actionType;
    }

    function getResourceLinkRecords(item) {
        const payload = normalizeItem(item);
        const extra = payload.extra && typeof payload.extra === 'object' && !Array.isArray(payload.extra)
            ? payload.extra
            : {};
        const structuredRecords = Array.isArray(extra.resource_links) ? extra.resource_links : [];
        const legacyRecords = Array.isArray(extra.all_links) ? extra.all_links : [];
        const primaryRecord = payload.link_url
            ? {
                link_url: payload.link_url,
                link_type: payload.link_type,
                receive_code: payload.receive_code || extra.receive_code || '',
            }
            : null;
        const values = structuredRecords.length
            ? [...structuredRecords, primaryRecord].filter(Boolean)
            : [primaryRecord, ...legacyRecords].filter(Boolean);

        const records = [];
        const seen = new Set();
        values.forEach(value => {
            const raw = value && typeof value === 'object' && !Array.isArray(value)
                ? value
                : { link_url: value };
            const linkUrl = String(raw.link_url || raw.url || '').trim();
            if (!linkUrl) return;
            const displayType = resolveDisplayType({ link_url: linkUrl, link_type: raw.link_type });
            if (displayType === 'unknown') return;
            const fingerprint = linkUrl.toLowerCase();
            if (seen.has(fingerprint)) return;
            seen.add(fingerprint);
            records.push(Object.freeze({
                link_url: linkUrl,
                link_type: displayType,
                receive_code: String(raw.receive_code || '').trim(),
            }));
        });
        return records;
    }

    function summarize(items, fallbackProfile = {}) {
        const fallback = fallbackProfile && typeof fallbackProfile === 'object' && !Array.isArray(fallbackProfile)
            ? { ...fallbackProfile }
            : {};
        const sourceItems = Array.isArray(items) ? items : [];
        if (!sourceItems.length) return fallback;

        const counts = {};
        sourceItems.forEach(item => {
            const type = resolveDisplayType(item);
            counts[type] = Number(counts[type] || 0) + 1;
        });
        const sortedTypes = Object.keys(counts).sort((left, right) => {
            const unknownDiff = Number(left === 'unknown') - Number(right === 'unknown');
            if (unknownDiff !== 0) return unknownDiff;
            const countDiff = Number(counts[right] || 0) - Number(counts[left] || 0);
            if (countDiff !== 0) return countDiff;
            return getTagMeta(left).order - getTagMeta(right).order;
        });
        const orderedCounts = {};
        sortedTypes.forEach(type => {
            orderedCounts[type] = counts[type];
        });
        return {
            ...fallback,
            primary_link_type: sortedTypes[0] || 'unknown',
            dominant_link_types: sortedTypes.slice(0, 3),
            link_type_counts: orderedCounts,
        };
    }

    global.ResourceLinkTags = Object.freeze({
        detect,
        getTagMeta,
        getResourceLinkRecords,
        list,
        resolveActionType,
        resolveDisplayType,
        summarize,
    });
})(window);
