export async function ensureTabData(context) {
    if (!context.versionInfo?.checked_at) {
        await context.refreshVersionInfo(false);
    }
    context.moduleVisitState.about = true;
}

export function normalizeVersionLabel(rawVersion) {
    const raw = String(rawVersion || 'dev').trim();
    if (!raw) return 'Vdev';
    return raw.startsWith('V') ? raw : `V${raw}`;
}

function getProjectUrl(versionInfo, fallbackProjectUrl) {
    return versionInfo?.latest?.projectUrl || versionInfo?.local?.projectUrl || fallbackProjectUrl;
}

function getChangelogUrl(versionInfo, fallbackProjectUrl, fallbackChangelogUrl) {
    return versionInfo?.latest?.changelogUrl
        || versionInfo?.local?.changelogUrl
        || getProjectUrl(versionInfo, fallbackProjectUrl)
        || fallbackChangelogUrl;
}

function getVersionNotes(versionInfo) {
    const latestNotes = Array.isArray(versionInfo?.latest?.notes) ? versionInfo.latest.notes.filter(Boolean) : [];
    if (latestNotes.length) return latestNotes;
    const localNotes = Array.isArray(versionInfo?.local?.notes) ? versionInfo.local.notes.filter(Boolean) : [];
    return localNotes;
}

export function buildVersionBannerPayload({
    versionInfo,
    latest,
    fallbackProjectUrl,
    fallbackChangelogUrl,
} = {}) {
    const fromVer = normalizeVersionLabel(versionInfo?.local?.version || 'dev');
    const toVer = latest?.version ? normalizeVersionLabel(latest.version) : '';
    const notes = getVersionNotes(versionInfo);
    return {
        text: toVer ? `${fromVer} -> ${toVer} 可更新` : '检测到可用更新',
        note: notes.length ? notes[0] : '建议先在「关于」页查看更新说明，再执行升级。',
        href: getChangelogUrl(versionInfo, fallbackProjectUrl, fallbackChangelogUrl),
    };
}

export function renderVersionInfoPanel({
    versionInfo,
    fallbackProjectUrl,
    fallbackChangelogUrl,
    formatTimeText,
    escapeHtml,
} = {}) {
    const localVersion = normalizeVersionLabel(versionInfo?.local?.version || 'dev');
    const latestRaw = versionInfo?.latest?.version || '';
    const latestVersion = latestRaw ? normalizeVersionLabel(latestRaw) : '--';
    const hasUpdate = !!versionInfo?.has_update;
    const hasChecked = Number(versionInfo?.checked_at || 0) > 0;
    const error = String(versionInfo?.error || '').trim();

    const footerVersion = document.getElementById('version-text');
    if (footerVersion) footerVersion.textContent = localVersion;

    const localEl = document.getElementById('about-local-version');
    if (localEl) localEl.textContent = localVersion;
    const buildEl = document.getElementById('about-build-date');
    if (buildEl) buildEl.textContent = formatTimeText(versionInfo?.local?.buildDate);
    const latestEl = document.getElementById('about-latest-version');
    if (latestEl) latestEl.textContent = latestVersion;
    const checkedEl = document.getElementById('about-checked-at');
    if (checkedEl) checkedEl.textContent = versionInfo?.checked_at ? `约 ${formatTimeText(versionInfo.checked_at * 1000)}` : '--';

    const statusEl = document.getElementById('about-version-status');
    if (statusEl) {
        if (error) {
            statusEl.textContent = '检查失败';
            statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-red-500/20 bg-red-500/10 text-red-300';
        } else if (!hasChecked) {
            statusEl.textContent = '尚未检查更新';
            statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-slate-700 bg-slate-900/80 text-slate-300';
        } else if (hasUpdate) {
            statusEl.textContent = latestRaw ? `有可用更新：${normalizeVersionLabel(latestRaw)}` : '发现可用更新';
            statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-amber-500/25 bg-amber-500/15 text-amber-300';
        } else {
            statusEl.textContent = '当前已是最新版本';
            statusEl.className = 'text-xs px-3 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
        }
    }

    const errorEl = document.getElementById('about-version-error');
    if (errorEl) {
        if (error) {
            errorEl.textContent = `版本检查失败：${error}`;
            errorEl.classList.remove('hidden');
        } else {
            errorEl.classList.add('hidden');
            errorEl.textContent = '';
        }
    }

    const hintEl = document.getElementById('about-version-hint');
    if (hintEl && !error) {
        if (!hasChecked) {
            hintEl.textContent = '提示：进入页面后会自动检查远端版本，也可以手动点击“检查更新”。';
        } else {
            hintEl.textContent = hasUpdate
                ? `检测到新版本 ${latestVersion}，建议先查看更新说明后再升级。`
                : '当前版本已和远端同步，后续会自动定时检查。';
        }
    }

    const notesWrap = document.getElementById('about-version-notes');
    if (notesWrap) {
        const notes = getVersionNotes(versionInfo);
        if (notes.length) {
            notesWrap.innerHTML = `<ul class="list-disc pl-5 space-y-2">${notes.map(note => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
        } else {
            notesWrap.textContent = '暂无更新说明';
        }
    }

    const changelogUrl = getChangelogUrl(versionInfo, fallbackProjectUrl, fallbackChangelogUrl);
    const projectUrl = getProjectUrl(versionInfo, fallbackProjectUrl);
    const starUrl = `${projectUrl.replace(/\/+$/, '')}/stargazers`;
    const changelogLink = document.getElementById('about-changelog-link');
    if (changelogLink) changelogLink.href = changelogUrl;
    const projectLink = document.getElementById('about-project-link');
    if (projectLink) projectLink.href = projectUrl;
    const starLink = document.getElementById('about-star-link');
    if (starLink) starLink.href = starUrl;
}

export function showVersionBanner({
    versionInfo,
    latest,
    fallbackProjectUrl,
    fallbackChangelogUrl,
} = {}) {
    if (!latest) return;
    const banner = document.getElementById('version-banner');
    if (!banner) return;
    const textEl = document.getElementById('version-banner-text');
    const noteEl = document.getElementById('version-banner-notes');
    const linkEl = document.getElementById('version-banner-link');
    const payload = buildVersionBannerPayload({
        versionInfo,
        latest,
        fallbackProjectUrl,
        fallbackChangelogUrl,
    });
    if (textEl) textEl.textContent = payload.text;
    if (noteEl) noteEl.textContent = payload.note;
    if (linkEl) linkEl.href = payload.href;
    banner.classList.remove('hidden');
}

export function hideVersionBanner() {
    const banner = document.getElementById('version-banner');
    if (banner) banner.classList.add('hidden');
}

export function dismissVersionBanner({ setDismissed } = {}) {
    if (typeof setDismissed === 'function') setDismissed(true);
    hideVersionBanner();
}

export async function refreshVersionInfo({
    force = false,
    getVersionInfo,
    setVersionInfo,
    isDismissed,
    setDismissed,
    renderPanel,
    showBanner = showVersionBanner,
    hideBanner = hideVersionBanner,
    fallbackProjectUrl,
    fallbackChangelogUrl,
} = {}) {
    const current = typeof getVersionInfo === 'function' ? (getVersionInfo() || {}) : {};
    try {
        const endpoint = force ? '/version?refresh=1' : '/version';
        const res = await fetch(endpoint);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const nextVersionInfo = {
            ...current,
            ...data,
            error: data?.error || ''
        };
        if (typeof setVersionInfo === 'function') setVersionInfo(nextVersionInfo);
        if (typeof renderPanel === 'function') await renderPanel();

        const dismissed = typeof isDismissed === 'function' ? !!isDismissed() : false;
        if (!dismissed && nextVersionInfo.has_update) {
            await showBanner({
                versionInfo: nextVersionInfo,
                latest: nextVersionInfo.latest || {},
                fallbackProjectUrl,
                fallbackChangelogUrl,
            });
        } else if (!nextVersionInfo.has_update) {
            hideBanner();
            if (typeof setDismissed === 'function') setDismissed(false);
        }
    } catch (err) {
        console.warn('Version refresh failed', err);
        const nextVersionInfo = {
            ...current,
            error: err instanceof Error ? err.message : String(err || 'unknown error')
        };
        if (typeof setVersionInfo === 'function') setVersionInfo(nextVersionInfo);
        if (typeof renderPanel === 'function') await renderPanel();
    }
}

export async function manualVersionCheck({
    refreshVersionInfo,
    getVersionInfo,
} = {}) {
    const btn = document.getElementById('about-check-btn');
    const hintEl = document.getElementById('about-version-hint');
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.classList.add('btn-disabled');
        btn.textContent = '检查中...';
    }
    if (typeof refreshVersionInfo === 'function') {
        await refreshVersionInfo(true);
    }
    const versionInfo = typeof getVersionInfo === 'function' ? (getVersionInfo() || {}) : {};
    if (hintEl) {
        if (versionInfo?.error) {
            hintEl.textContent = `手动检查失败：${versionInfo.error}`;
        } else if (versionInfo?.has_update) {
            const latest = normalizeVersionLabel(versionInfo?.latest?.version || '');
            hintEl.textContent = latest ? `手动检查完成，发现可用更新 ${latest}。` : '手动检查完成，发现可用更新。';
        } else {
            hintEl.textContent = '手动检查完成，当前已是最新版本。';
        }
    }
    if (btn) {
        btn.disabled = false;
        btn.classList.remove('btn-disabled');
        btn.textContent = originalText || '手动检查更新';
    }
}

export async function ensureWorkflowImageLoaded({
    loaded,
    loadingPromise,
    defaultImageUrl,
    setLoaded,
    setLoadingPromise,
} = {}) {
    if (loaded) return true;
    if (loadingPromise) return loadingPromise;

    const modalImage = document.getElementById('about-workflow-modal-image');
    const loadingEl = document.getElementById('about-workflow-modal-loading');
    const errorEl = document.getElementById('about-workflow-modal-error');
    if (!modalImage) return false;

    if (loadingEl) loadingEl.classList.remove('hidden');
    if (errorEl) errorEl.classList.add('hidden');

    const targetSrc = String(modalImage.dataset.src || defaultImageUrl).trim() || defaultImageUrl;
    const nextPromise = new Promise((resolve) => {
        let done = false;
        const finish = (ok) => {
            if (done) return;
            done = true;
            if (ok) {
                if (typeof setLoaded === 'function') setLoaded(true);
                if (loadingEl) loadingEl.classList.add('hidden');
                if (errorEl) errorEl.classList.add('hidden');
                modalImage.classList.remove('hidden');
            } else {
                if (loadingEl) loadingEl.classList.add('hidden');
                if (errorEl) errorEl.classList.remove('hidden');
            }
            if (typeof setLoadingPromise === 'function') setLoadingPromise(null);
            resolve(ok);
        };

        const handleLoad = () => finish(true);
        const handleError = () => finish(false);

        modalImage.addEventListener('load', handleLoad, { once: true });
        modalImage.addEventListener('error', handleError, { once: true });

        if (!modalImage.src) {
            modalImage.src = targetSrc;
        }
        if (modalImage.complete) {
            if (modalImage.naturalWidth > 0) finish(true);
            else finish(false);
        }
    });

    if (typeof setLoadingPromise === 'function') setLoadingPromise(nextPromise);
    return nextPromise;
}
