(function (global) {
    'use strict';

    const FOLDER_CHARACTER_REPLACEMENTS = Object.freeze({
        '*': '＊',
        '?': '？',
        '"': '＂',
        '<': '＜',
        '>': '＞',
        '|': '｜',
    });

    function cleanShowTitle(value, fallback = '未命名影视') {
        const safeFallback = String(fallback || '未命名影视').trim() || '未命名影视';
        let title = String(value || '').trim() || safeFallback;
        title = title.split(/\s*[|｜丨]+\s*/)[0].trim() || title;
        title = title
            .replace(/[._]+/g, ' ')
            .replace(/[\[\【(（][^\]\】)）]{0,90}(?:2160p|1080p|720p|4k|uhd|hdr|web(?:-|\s)?dl|bluray|x26[45]|h\.?26[45]|aac|ddp|atmos|中字|双语|國語|国语|粤语|简繁|完结|全集|更新|s\d{1,2}\s*e?\d{0,4}|第\s*[零〇一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話))[^\]\】)）]*[\]\】)）]/gi, ' ')
            .replace(/[\[\【(（]\s*(?:19|20)\d{2}\s*[\]\】)）]/g, ' ')
            .replace(/\b(19|20)\d{2}\b/g, ' ')
            .replace(/\b(?:S\d{1,2}\s*E?\d{0,4}|E\d{1,4}|EP?\s*\d{1,4})\b/gi, ' ')
            .replace(/第\s*[零〇一二三四五六七八九十两兩0-9]{1,4}\s*(?:季|集|话|話)/g, ' ')
            .replace(/(?:全|共)\s*\d{1,4}\s*(?:集|话|話)/g, ' ')
            .replace(/\d{1,4}\s*(?:集|话|話)\s*(?:全|完|完结|完結)?/g, ' ')
            .replace(/\b(?:2160p|1080p|720p|480p|360p|4k|uhd|hdr(?:10)?|dolby(?:\s*vision)?|atmos|dts(?:-?hd)?(-?ma)?|truehd|blu-?ray|web-?dl|webrip|bdrip|brrip|hdtv|remux|x26[45]|h\.?26[45]|hevc|avc|aac|ac3|ddp5?\.?1)\b/gi, ' ')
            .replace(/(?:\s|^)(?:中字|双语|国语|國語|粤语|粤語|简繁)(?=\s|$)/g, ' ')
            .replace(/\s{2,}/g, ' ')
            .trim();
        return title || safeFallback;
    }

    function extractShowYear(value, knownYear = '') {
        const normalized = String(knownYear || '').trim();
        if (/^(19|20)\d{2}$/.test(normalized)) return normalized;
        const matched = String(value || '').match(/\b(19|20)\d{2}\b/);
        return matched ? String(matched[0]) : '';
    }

    function sanitizeFolderName(value) {
        return String(value || '')
            .replace(/[\u0000-\u001f\u007f]+/gu, '')
            .replace(/[\\/]+/gu, ' ')
            .replace(/[*?"<>|]/gu, character => FOLDER_CHARACTER_REPLACEMENTS[character] || '')
            .replace(/\s+/gu, ' ')
            .trim();
    }

    function recommendFolderName(title, year) {
        const base = sanitizeFolderName(cleanShowTitle(title));
        const normalizedYear = String(year || '').trim();
        const suffix = /^(19|20)\d{2}$/.test(normalizedYear) ? ` (${normalizedYear})` : '';
        const result = `${base}${suffix}`.trim();
        return result || '未命名影视';
    }

    global.MediaHubTitleUtils = Object.freeze({
        cleanShowTitle,
        extractShowYear,
        recommendFolderName,
        sanitizeFolderName,
    });
})(window);
