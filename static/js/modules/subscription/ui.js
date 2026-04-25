        function buildSubscriptionRenderKey(state) {
            return JSON.stringify({
                running: !!state?.running,
                current_task: state?.current_task || '',
                queued: Array.isArray(state?.queued) ? state.queued : [],
                next_runs: state?.next_runs || {},
                tasks: Array.isArray(state?.tasks) ? state.tasks : []
            });
        }

        function getSubscriptionStatusLabel(status) {
            const normalized = String(status || 'idle').trim().toLowerCase();
            const map = {
                idle: '待命',
                running: '运行中',
                waiting: '等待资源',
                completed: '已完成',
                failed: '失败',
                cancelled: '已中断'
            };
            return map[normalized] || (normalized || '待命');
        }

        function buildSubscriptionStatusBadge(status) {
            const normalized = String(status || 'idle').trim().toLowerCase();
            const map = {
                idle: 'bg-slate-700 text-slate-300',
                running: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20',
                waiting: 'bg-amber-500/15 text-amber-300 border border-amber-500/20',
                completed: 'bg-sky-500/15 text-sky-300 border border-sky-500/20',
                failed: 'bg-red-500/10 text-red-300 border border-red-500/20',
                cancelled: 'bg-violet-500/15 text-violet-300 border border-violet-500/20'
            };
            const cls = map[normalized] || map.idle;
            return `<span class="text-[10px] px-3 py-1 rounded-full ${cls}">${escapeHtml(getSubscriptionStatusLabel(normalized))}</span>`;
        }

        function applySubscriptionState(data, { forceRender = false } = {}) {
            const subscriptionModule = tabRuntimeState.tabModuleCache.subscription;
            if (subscriptionModule?.applySubscriptionState) {
                subscriptionModule.applySubscriptionState(data, {
                    forceRender,
                    getSubscriptionState: () => subscriptionState,
                    setSubscriptionState: (nextValue) => {
                        subscriptionState = { ...nextValue };
                    },
                    getIntroExpanded: () => subscriptionTaskIntroExpanded,
                    setIntroExpanded: (nextValue) => {
                        subscriptionTaskIntroExpanded = { ...(nextValue || {}) };
                    },
                    pruneTaskIntroExpanded,
                    buildSubscriptionRenderKey,
                    getLastSubscriptionRenderKey: () => lastSubscriptionRenderKey,
                    setLastSubscriptionRenderKey: (nextValue) => {
                        lastSubscriptionRenderKey = String(nextValue || '');
                    },
                    renderSubscriptionTasks,
                    renderSubscriptionLogs,
                });
                return;
            }
            if (!data) return;
            subscriptionState = {
                ...subscriptionState,
                ...data,
                tasks: Array.isArray(data.tasks) ? data.tasks : (subscriptionState.tasks || []),
                logs: Array.isArray(data.logs) ? data.logs : (subscriptionState.logs || []),
                queued: Array.isArray(data.queued) ? data.queued : (subscriptionState.queued || []),
                next_runs: data.next_runs || subscriptionState.next_runs || {},
                summary: data.summary || subscriptionState.summary || { step: '空闲', detail: '等待订阅任务' }
            };
            subscriptionTaskIntroExpanded = pruneTaskIntroExpanded(subscriptionTaskIntroExpanded, subscriptionState.tasks);

            const stepEl = document.getElementById('subscription-summary-step');
            const detailEl = document.getElementById('subscription-summary-detail');
            if (stepEl) stepEl.innerText = subscriptionState.summary?.step || '空闲';
            if (detailEl) detailEl.innerText = subscriptionState.summary?.detail || '等待订阅任务';

            const renderKey = buildSubscriptionRenderKey(subscriptionState);
            if (forceRender || renderKey !== lastSubscriptionRenderKey) {
                renderSubscriptionTasks();
                lastSubscriptionRenderKey = renderKey;
            }
            renderSubscriptionLogs();
        }

        function buildSubscriptionTaskIntro(task, {
            status = 'idle',
            queued = false,
            nextRun = '',
            isTv = false,
            episodeText = '',
            multiSeasonMode = false,
        } = {}) {
            const statusText = queued ? '已排队' : getSubscriptionStatusLabel(status);
            const enabledText = task?.enabled === false ? '已停用' : '已启用';
            const mediaText = isTv ? '电视剧' : '电影';
            const provider = normalizeSubscriptionProvider(task?.provider || '115', '115');
            const providerText = provider === 'quark' ? '夸克' : '115';
            const titleText = String(task?.title || task?.name || '').trim() || '未命名影视';
            const savepath = String(task?.savepath || '').trim() || '--';
            const fixedShareLink = String(task?.share_link_url || '').trim();
            const fixedLinkChannelSearch = !!task?.fixed_link_channel_search;
            const shareSubdir = normalizeRelativePathInput(task?.share_subdir || '');
            const shareSubdirCid = normalizeShareCidInput(task?.share_subdir_cid || '');
            const scheduleWeekdays = normalizeSubscriptionWeekdays(task?.schedule_weekdays || []);
            const scheduleStartTime = normalizeSubscriptionScheduleTime(task?.schedule_start_time || '00:00', '00:00');
            const scheduleEndTime = normalizeSubscriptionScheduleTime(task?.schedule_end_time || '23:59', '23:59');
            const scheduleIntervalMinutes = Math.max(
                1,
                Number(task?.schedule_interval_minutes || task?.cron_minutes || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES)
                    || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            const weekdayText = formatSubscriptionWeekdayText(scheduleWeekdays);
            const isCrossDayWindow = scheduleStartTime > scheduleEndTime;
            const windowText = isCrossDayWindow
                ? `${scheduleStartTime} - 次日 ${scheduleEndTime}`
                : `${scheduleStartTime} - ${scheduleEndTime}`;
            let scheduleText = '';
            if (task?.enabled === false) {
                scheduleText = '自动查询已停用，仅支持手动运行';
            } else if (!scheduleWeekdays.length) {
                scheduleText = '未选择查询星期，仅支持手动运行';
            } else {
                scheduleText = `${weekdayText} ${windowText} 每 ${scheduleIntervalMinutes} 分钟查询一次，下次执行 ${String(nextRun || '计算中')}`;
            }
            const latestMatched = String(task?.matched_resource_title || '').trim();
            const latestText = latestMatched ? `最近命中：${latestMatched}` : '最近尚未命中资源';
            const modeText = isTv ? (multiSeasonMode ? '多季合一追更' : '单季追更') : '命中资源后即执行';
            const fixedShareText = provider === '115' && fixedShareLink
                ? `，固定分享链接模式${fixedLinkChannelSearch ? '（频道补搜兜底）' : ''}`
                : '';
            const shareScopeText = provider === '115' && shareSubdir
                ? `，分享子目录 ${shareSubdir}${shareSubdirCid ? `（CID ${shareSubdirCid}）` : ''}`
                : (provider === '115' && shareSubdirCid ? `，分享子目录 CID ${shareSubdirCid}` : '');
            const providerRuleText = provider === 'quark' ? '，仅频道自动匹配（不使用固定分享链接）' : '';
            return `状态：${statusText}（${enabledText}）。${providerText} · ${mediaText}《${titleText}》保存到 ${savepath}${fixedShareText}${shareScopeText}${providerRuleText}，${modeText}，${episodeText}；${scheduleText}；${latestText}。`;
        }

        function buildSubscriptionTaskProgressBar({ progress = 0, detail = '' } = {}) {
            const progressValue = Math.max(0, Math.min(100, Number(progress || 0) || 0));
            const progressWidth = progressValue <= 0 ? 2 : progressValue;
            const detailText = String(detail || '').trim();
            const detailLine = detailText ? `<div class="mt-1 text-[11px] text-slate-300 break-all">${escapeHtml(detailText)}</div>` : '';
            return `
                <div class="mt-2 rounded-xl border border-sky-500/25 bg-sky-500/10 px-3 py-2">
                    <div class="flex items-center justify-between text-[11px] text-sky-200">
                        <span>运行进度</span>
                        <span class="font-bold">${progressValue}%</span>
                    </div>
                    <div class="mt-1.5 h-2 rounded-full bg-slate-800/80 overflow-hidden">
                        <div class="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-400 transition-width prog-glow" style="width: ${progressWidth}%"></div>
                    </div>
                    ${detailLine}
                </div>
            `;
        }

        function toggleSubscriptionTaskIntro(taskName) {
            subscriptionTaskIntroExpanded = toggleTaskIntroExpanded(subscriptionTaskIntroExpanded, taskName);
            renderSubscriptionTasks();
        }

        function renderSubscriptionLogs() {
            const box = document.getElementById('subscription-log-box');
            if (!box) return;
            const logs = subscriptionState.logs || [];
            const logSignature = buildLogSignature(logs, (item) => `${item?.level || 'info'}:${item?.text || ''}`);
            if (logSignature === lastSubscriptionLogSignature) return;
            box.innerHTML = logs.map(item => `<div class="${getLogEntryClass(item)}">${formatMonitorLogHtml(item)}</div>`).join('');
            box.scrollTop = box.scrollHeight;
            lastSubscriptionLogSignature = logSignature;
        }

        function normalizeSubscriptionMediaType(value) {
            const normalized = String(value || 'movie').trim().toLowerCase();
            return normalized === 'tv' ? 'tv' : 'movie';
        }

        function normalizeSubscriptionProvider(value, fallback = '115') {
            const normalized = String(value || '').trim().toLowerCase();
            if (normalized === '115' || normalized === 'quark') return normalized;
            const fallbackNormalized = String(fallback || '115').trim().toLowerCase();
            return fallbackNormalized === 'quark' ? 'quark' : '115';
        }

        function getSubscriptionProviderLabel(provider) {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'Quark' : '115';
        }

        function getSubscriptionProviderBadgeLabel(provider) {
            return normalizeSubscriptionProvider(provider, '115') === 'quark' ? 'Quark' : '115';
        }

        function buildSubscriptionProviderBadge(provider) {
            const normalized = normalizeSubscriptionProvider(provider, '115');
            const label = getSubscriptionProviderBadgeLabel(normalized);
            const className = normalized === 'quark'
                ? 'resource-card-type-badge resource-card-type-badge-quark'
                : 'resource-card-type-badge resource-card-type-badge-115share';
            return `<span class="${className}">${escapeHtml(label)}</span>`;
        }

        function getCurrentSubscriptionProvider() {
            return normalizeSubscriptionProvider(document.getElementById('subscription_provider')?.value || '115', '115');
        }

        function normalizeSubscriptionQualityPriority(value) {
            const normalized = String(value || 'balanced').trim().toLowerCase();
            if (['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(normalized)) return normalized;
            return 'balanced';
        }

        function normalizeSubscriptionWeekdays(values) {
            let payload = values;
            if (typeof payload === 'string') {
                payload = payload.split(/[\s,，|/]+/).map((item) => item.trim()).filter(Boolean);
            }
            const source = Array.isArray(payload) ? payload : [];
            const seen = new Set();
            const normalized = [];
            source.forEach((item) => {
                const weekday = parseInt(item || '0', 10) || 0;
                if (weekday < 1 || weekday > 7 || seen.has(weekday)) return;
                seen.add(weekday);
                normalized.push(weekday);
            });
            normalized.sort((a, b) => a - b);
            return normalized;
        }

        function normalizeSubscriptionScheduleTime(value, fallback = '00:00') {
            const raw = String(value || '').trim() || String(fallback || '00:00').trim();
            const matched = raw.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
            if (!matched) {
                const fallbackMatched = String(fallback || '00:00').trim().match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
                if (!fallbackMatched) return '00:00';
                return `${String(parseInt(fallbackMatched[1], 10)).padStart(2, '0')}:${String(parseInt(fallbackMatched[2], 10)).padStart(2, '0')}`;
            }
            return `${String(parseInt(matched[1], 10)).padStart(2, '0')}:${String(parseInt(matched[2], 10)).padStart(2, '0')}`;
        }

        function formatSubscriptionWeekdayText(values) {
            const weekdays = normalizeSubscriptionWeekdays(values);
            if (!weekdays.length) return '未选择更新日';
            return weekdays.map((weekday) => SUBSCRIPTION_WEEKDAY_LABELS[weekday] || `周${weekday}`).join('、');
        }

        function setSubscriptionWeekdaysToForm(values) {
            const weekdays = new Set(normalizeSubscriptionWeekdays(values));
            const checkboxList = document.querySelectorAll('[data-subscription-weekday]');
            checkboxList.forEach((checkbox) => {
                const weekday = parseInt(checkbox?.dataset?.subscriptionWeekday || '0', 10) || 0;
                checkbox.checked = weekdays.has(weekday);
            });
        }

        function getSubscriptionWeekdaysFromForm() {
            const selected = [];
            const checkboxList = document.querySelectorAll('[data-subscription-weekday]');
            checkboxList.forEach((checkbox) => {
                const weekday = parseInt(checkbox?.dataset?.subscriptionWeekday || '0', 10) || 0;
                if (weekday <= 0 || weekday > 7 || !checkbox.checked) return;
                selected.push(weekday);
            });
            return normalizeSubscriptionWeekdays(selected);
        }

        function getSubscriptionQualityPriorityLabel(value) {
            const normalized = normalizeSubscriptionQualityPriority(value);
            const map = {
                balanced: '均衡',
                ultra: '超清优先',
                fhd: '高清优先',
                hd: '流畅优先',
                sd: '小体积优先'
            };
            return map[normalized] || '均衡';
        }

        function normalizeTmdbMediaType(value, fallback = '') {
            const normalized = String(value || '').trim().toLowerCase();
            if (normalized === 'movie' || normalized === 'tv') return normalized;
            const fallbackNormalized = String(fallback || '').trim().toLowerCase();
            if (fallbackNormalized === 'movie' || fallbackNormalized === 'tv') return fallbackNormalized;
            return '';
        }

        function normalizeTmdbEpisodeMode(value) {
            const normalized = String(value || '').trim().toLowerCase();
            return normalized === 'absolute' ? 'absolute' : 'seasonal';
        }

        function normalizeTmdbSeasonEpisodeMap(value) {
            const result = {};
            const assign = (seasonValue, episodeValue) => {
                const seasonNo = parseInt(seasonValue || '0', 10) || 0;
                const episodeCount = parseInt(episodeValue || '0', 10) || 0;
                if (seasonNo <= 0 || episodeCount <= 0) return;
                result[String(seasonNo)] = episodeCount;
            };
            let payload = value;
            if (typeof payload === 'string') {
                const text = payload.trim();
                if (!text) payload = {};
                else {
                    try {
                        payload = JSON.parse(text);
                    } catch (_) {
                        payload = {};
                    }
                }
            }
            if (Array.isArray(payload)) {
                payload.forEach((item) => {
                    if (!item || typeof item !== 'object') return;
                    assign(item.season_number ?? item.season ?? item.number, item.episode_count ?? item.episodes ?? item.total_episodes);
                });
                return result;
            }
            if (!payload || typeof payload !== 'object') return result;
            Object.entries(payload).forEach(([seasonKey, episodeValue]) => {
                assign(seasonKey, episodeValue);
            });
            return result;
        }

        function getTmdbSeasonEpisodeTotal(seasonMap, season) {
            const normalizedMap = normalizeTmdbSeasonEpisodeMap(seasonMap);
            const targetSeason = Math.max(1, parseInt(season || '1', 10) || 1);
            return Math.max(0, parseInt(normalizedMap[String(targetSeason)] || '0', 10) || 0);
        }

        function resolveTaskMultiSeasonMode(task) {
            return !!(task?.multi_season_mode ?? task?.anime_mode);
        }

        function normalizeTmdbYear(value) {
            const normalized = String(value || '').trim();
            return /^(19|20)\d{2}$/.test(normalized) ? normalized : '';
        }

        function parseSmallCjkNumber(value, fallback = 0) {
            const raw = String(value || '').trim();
            if (!raw) return fallback;
            if (/^\d{1,4}$/.test(raw)) {
                const parsed = parseInt(raw, 10);
                return Number.isFinite(parsed) ? parsed : fallback;
            }
            if (!/^[零〇一二三四五六七八九十两兩]+$/.test(raw)) return fallback;
            const digits = {
                '零': 0,
                '〇': 0,
                '一': 1,
                '二': 2,
                '三': 3,
                '四': 4,
                '五': 5,
                '六': 6,
                '七': 7,
                '八': 8,
                '九': 9,
                '两': 2,
                '兩': 2,
            };
            if (raw === '十') return 10;
            if (raw.includes('十')) {
                const [head, tail] = raw.split('十');
                const tens = head ? (digits[head] ?? -1) : 1;
                const ones = tail ? (digits[tail] ?? -1) : 0;
                if (tens < 0 || ones < 0) return fallback;
                return tens * 10 + ones;
            }
            const single = digits[raw];
            return Number.isFinite(single) ? single : fallback;
        }

        function extractYearFromResourceText(item) {
            const knownYear = normalizeTmdbYear(item?.year || '');
            if (knownYear) return knownYear;
            const text = `${String(item?.title || '')} ${String(item?.raw_text || '')}`;
            const matched = text.match(/\b(19|20)\d{2}\b/);
            return normalizeTmdbYear(matched?.[0] || '');
        }

        function buildSubscriptionTitleFromResource(item) {
            const fallback = String(item?.title || item?.normalized_title || '未命名资源').trim() || '未命名资源';
            let title = String(item?.title || '').trim() || fallback;

            title = title.split(/\s*[|｜丨]+\s*/)[0].trim() || title;
            title = title
                .replace(/[._]+/g, ' ')
                .replace(/[\[\【(（][^\]\】)）]{0,90}(?:2160p|1080p|720p|4k|uhd|hdr|web(?:-|\s)?dl|bluray|x26[45]|h\.?26[45]|aac|ddp|atmos|中字|双语|國語|国语|粤语|简繁|完结|全集|更新|s\d{1,2}\s*e?\d{0,4}|第\s*[零〇一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話))[^\]\】)）]*[\]\】)）]/gi, ' ')
                .replace(/\b(19|20)\d{2}\b/g, ' ')
                .replace(/\b(?:S\d{1,2}\s*E?\d{0,4}|E\d{1,4}|EP?\s*\d{1,4})\b/gi, ' ')
                .replace(/第\s*[零〇一二三四五六七八九十两兩0-9]{1,4}\s*(?:季|集|话|話)/g, ' ')
                .replace(/(?:全|共)\s*\d{1,4}\s*(?:集|话|話)/g, ' ')
                .replace(/\d{1,4}\s*(?:集|话|話)\s*(?:全|完|完结|完結)?/g, ' ')
                .replace(/\s{2,}/g, ' ')
                .trim();
            return title || fallback;
        }

        function inferSubscriptionDraftFromResource(item) {
            const payload = item && typeof item === 'object' ? item : {};
            const text = `${String(payload?.title || '')} ${String(payload?.raw_text || '')}`;
            const seasonMatch = text.match(/\bS(?:eason)?\s*0?(\d{1,2})\b/i);
            const seasonCnMatch = text.match(/第\s*([零〇一二三四五六七八九十两兩0-9]{1,3})\s*季/i);
            const rangeMatch = text.match(/(?:EP?|E)?\s*(\d{1,4})\s*[-~～—–至到]+\s*(?:EP?|E)?\s*(\d{1,4})/i)
                || text.match(/第?\s*(\d{1,4})\s*[-~～—–至到]+\s*(\d{1,4})\s*(?:集|话|話)/i);
            const totalMatch = text.match(/(?:全|共)\s*(\d{1,4})\s*(?:集|话|話)/i)
                || text.match(/(\d{1,4})\s*(?:集|话|話)\s*(?:全|完|完结|完結)/i);
            const episodeMatch = text.match(/\bS\d{1,2}\s*E(?:P)?\s*0?(\d{1,4})\b/i)
                || text.match(/\bEP?\s*0?(\d{1,4})\b/i)
                || text.match(/第\s*(\d{1,4})\s*(?:集|话|話)/i);

            let season = Math.max(0, parseInt(seasonMatch?.[1] || '0', 10) || 0);
            if (season <= 0 && seasonCnMatch) season = Math.max(0, parseSmallCjkNumber(seasonCnMatch[1], 0));
            let episode = Math.max(0, parseInt(episodeMatch?.[1] || '0', 10) || 0);
            let totalEpisodes = Math.max(0, parseInt(totalMatch?.[1] || '0', 10) || 0);
            let rangeStart = Math.max(0, parseInt(rangeMatch?.[1] || '0', 10) || 0);
            let rangeEnd = Math.max(0, parseInt(rangeMatch?.[2] || '0', 10) || 0);
            if (rangeEnd > 0 && rangeStart > rangeEnd) [rangeStart, rangeEnd] = [rangeEnd, rangeStart];
            if (rangeEnd > 0) {
                episode = Math.max(episode, rangeEnd);
                if (totalEpisodes <= 0 && rangeStart <= 1) totalEpisodes = rangeEnd;
            }
            if (totalEpisodes <= 0 && episode > 0 && /(?:完结|完結|全集|全\d{1,4}集)/i.test(text)) {
                totalEpisodes = episode;
            }

            const hasEpisodeMeta = season > 0 || episode > 0 || totalEpisodes > 0 || rangeEnd > 0;
            const tvHint = /(电视剧|剧集|番剧|动漫|第\s*[零〇一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話)|season\s*\d+|s\d{1,2}\s*e?\d{0,4}|ep\s*\d{1,4}|更新至\s*\d+\s*(?:集|话|話)|全\s*\d+\s*(?:集|话|話)|完结|完結)/i.test(text);
            const movieHint = /(电影|movie|film|剧场版|電影)/i.test(text);
            const animeMode = /(番剧|动漫|新番|动画|動畫|anime)/i.test(text);
            const mediaType = (hasEpisodeMeta || tvHint) && !movieHint ? 'tv' : 'movie';
            const provider = normalizeSubscriptionProvider(
                getEffectiveResourceLinkType(payload) === 'quark' ? 'quark' : '115',
                '115'
            );

            return {
                provider,
                media_type: mediaType,
                title: buildSubscriptionTitleFromResource(payload),
                year: extractYearFromResourceText(payload),
                season: mediaType === 'tv' ? Math.max(1, season || 1) : 1,
                total_episodes: mediaType === 'tv' ? Math.max(0, totalEpisodes || 0) : 0,
                anime_mode: mediaType === 'tv' ? animeMode : false,
                multi_season_mode: mediaType === 'tv' ? animeMode : false,
            };
        }

        function applySubscriptionPrefill(prefill = {}) {
            const payload = prefill && typeof prefill === 'object' ? prefill : {};
            const mediaType = normalizeSubscriptionMediaType(payload.media_type || 'movie');
            const provider = normalizeSubscriptionProvider(payload.provider || '115', '115');
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = provider;
            document.getElementById('subscription_media_type').value = mediaType;
            document.getElementById('subscription_title').value = String(payload.title || '').trim();
            document.getElementById('subscription_year').value = normalizeTmdbYear(payload.year || '');
            document.getElementById('subscription_season').value = Math.max(1, parseInt(payload.season || '1', 10) || 1);
            document.getElementById('subscription_total_episodes').value = Math.max(0, parseInt(payload.total_episodes || '0', 10) || 0);
            document.getElementById('subscription_anime_mode').checked = mediaType === 'tv'
                ? !!(payload.multi_season_mode ?? payload.anime_mode)
                : false;
            const tmdbKeywordInput = document.getElementById('subscription_tmdb_search_keyword');
            if (tmdbKeywordInput) tmdbKeywordInput.value = String(payload.title || '').trim();
            syncSubscriptionProviderUI();
            syncSubscriptionTypeUI();
        }

        function parseSubscriptionAliases(value) {
            return uniquePreserveOrder(String(value || '')
                .split(/[,\n，|/]+/)
                .map(item => item.trim())
                .filter(Boolean));
        }

        function getSubscriptionTmdbBindingFromForm() {
            const tmdbId = parseInt(document.getElementById('subscription_tmdb_id')?.value || '0', 10) || 0;
            const tmdbMediaType = normalizeTmdbMediaType(document.getElementById('subscription_tmdb_media_type')?.value || '');
            const tmdbAliases = parseSubscriptionAliases(document.getElementById('subscription_tmdb_aliases')?.value || '');
            return {
                tmdb_id: Math.max(0, tmdbId),
                tmdb_media_type: tmdbMediaType,
                tmdb_title: String(document.getElementById('subscription_tmdb_title')?.value || '').trim(),
                tmdb_original_title: String(document.getElementById('subscription_tmdb_original_title')?.value || '').trim(),
                tmdb_year: normalizeTmdbYear(document.getElementById('subscription_tmdb_year')?.value || ''),
                tmdb_aliases: tmdbAliases,
                tmdb_total_episodes: Math.max(0, parseInt(document.getElementById('subscription_tmdb_total_episodes')?.value || '0', 10) || 0),
                tmdb_total_seasons: Math.max(0, parseInt(document.getElementById('subscription_tmdb_total_seasons')?.value || '0', 10) || 0),
                tmdb_season_episode_map: normalizeTmdbSeasonEpisodeMap(document.getElementById('subscription_tmdb_season_episode_map')?.value || ''),
                tmdb_episode_mode: normalizeTmdbEpisodeMode(document.getElementById('subscription_tmdb_episode_mode')?.value || 'seasonal'),
            };
        }

        function setSubscriptionTmdbBinding(binding = {}) {
            const normalized = {
                tmdb_id: Math.max(0, parseInt(binding.tmdb_id || binding.id || '0', 10) || 0),
                tmdb_media_type: normalizeTmdbMediaType(
                    binding.tmdb_media_type || binding.media_type || '',
                    normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie')
                ),
                tmdb_title: String(binding.tmdb_title || binding.title || '').trim(),
                tmdb_original_title: String(binding.tmdb_original_title || binding.original_title || '').trim(),
                tmdb_year: normalizeTmdbYear(binding.tmdb_year || binding.year || ''),
                tmdb_aliases: parseSubscriptionAliases(Array.isArray(binding.tmdb_aliases) ? binding.tmdb_aliases.join(',') : (binding.tmdb_aliases || binding.aliases || '')),
                tmdb_total_episodes: Math.max(0, parseInt(binding.tmdb_total_episodes || binding.total_episodes || '0', 10) || 0),
                tmdb_total_seasons: Math.max(0, parseInt(binding.tmdb_total_seasons || binding.total_seasons || '0', 10) || 0),
                tmdb_season_episode_map: normalizeTmdbSeasonEpisodeMap(binding.tmdb_season_episode_map || binding.season_episode_map || {}),
                tmdb_episode_mode: normalizeTmdbEpisodeMode(binding.tmdb_episode_mode || binding.episode_mode || 'seasonal'),
            };
            const useBinding = normalized.tmdb_id > 0;
            document.getElementById('subscription_tmdb_id').value = useBinding ? String(normalized.tmdb_id) : '0';
            document.getElementById('subscription_tmdb_media_type').value = useBinding ? normalized.tmdb_media_type : '';
            document.getElementById('subscription_tmdb_title').value = useBinding ? normalized.tmdb_title : '';
            document.getElementById('subscription_tmdb_original_title').value = useBinding ? normalized.tmdb_original_title : '';
            document.getElementById('subscription_tmdb_year').value = useBinding ? normalized.tmdb_year : '';
            document.getElementById('subscription_tmdb_aliases').value = useBinding ? normalized.tmdb_aliases.join(', ') : '';
            document.getElementById('subscription_tmdb_total_episodes').value = useBinding ? String(normalized.tmdb_total_episodes) : '0';
            document.getElementById('subscription_tmdb_total_seasons').value = useBinding ? String(normalized.tmdb_total_seasons) : '0';
            document.getElementById('subscription_tmdb_season_episode_map').value = useBinding ? JSON.stringify(normalized.tmdb_season_episode_map) : '';
            document.getElementById('subscription_tmdb_episode_mode').value = useBinding ? normalized.tmdb_episode_mode : 'seasonal';
            renderSubscriptionTmdbBinding();
        }

        function clearSubscriptionTmdbBinding({ silent = false } = {}) {
            setSubscriptionTmdbBinding({});
            if (!silent) showToast('已清除 TMDB 绑定', { tone: 'info', duration: 2200, placement: 'top-center' });
        }

        function renderSubscriptionTmdbBinding() {
            const summaryEl = document.getElementById('subscription_tmdb_summary');
            if (!summaryEl) return;
            const binding = getSubscriptionTmdbBindingFromForm();
            if (binding.tmdb_id <= 0) {
                summaryEl.innerHTML = '未绑定 TMDB。绑定后会自动补充别名/年份/总集数并增强匹配稳定性。';
                return;
            }
            const mediaLabel = binding.tmdb_media_type === 'tv' ? '电视剧' : '电影';
            const yearSuffix = binding.tmdb_year ? ` (${escapeHtml(binding.tmdb_year)})` : '';
            const aliasText = binding.tmdb_aliases.length > 0 ? `别名 ${escapeHtml(String(binding.tmdb_aliases.length))} 个` : '无别名';
            const episodeModeText = binding.tmdb_episode_mode === 'absolute' ? '绝对集序' : '按季集序';
            const selectedSeason = Math.max(1, parseInt(document.getElementById('subscription_season')?.value || '1', 10) || 1);
            const seasonEpisodeTotal = getTmdbSeasonEpisodeTotal(binding.tmdb_season_episode_map, selectedSeason);
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            const totalText = binding.tmdb_media_type === 'tv'
                ? `总集数 ${escapeHtml(String(binding.tmdb_total_episodes || 0))} / 季数 ${escapeHtml(String(binding.tmdb_total_seasons || 0))} / S${escapeHtml(String(selectedSeason))}集数 ${escapeHtml(String(seasonEpisodeTotal || 0))} / ${episodeModeText}`
                : '电影元数据';
            const totalHint = binding.tmdb_media_type === 'tv'
                ? (multiSeasonMode ? '当前模式：多季合一（默认采用 TMDB 总集数）' : '当前模式：单季订阅（优先采用所选季集数）')
                : '';
            const subscriptionMediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const mismatch = binding.tmdb_media_type && binding.tmdb_media_type !== subscriptionMediaType;
            summaryEl.innerHTML = `
                <div>已绑定 <span class="text-sky-300">${mediaLabel} #${escapeHtml(String(binding.tmdb_id))}</span>：${escapeHtml(binding.tmdb_title || '--')}${yearSuffix}</div>
                <div class="text-[11px] mt-1">${escapeHtml(aliasText)} / ${escapeHtml(totalText)}</div>
                ${totalHint ? `<div class="text-[11px] mt-1">${escapeHtml(totalHint)}</div>` : ''}
                ${mismatch ? '<div class="text-[11px] mt-1 text-red-300">当前绑定类型与订阅类型不一致，保存前请重新绑定。</div>' : ''}
            `;
        }

        function setSubscriptionTmdbSearchBusy(loading) {
            subscriptionTmdbSearchBusy = !!loading;
            const btn = document.getElementById('subscription_tmdb_search_btn');
            if (!btn) return;
            btn.disabled = subscriptionTmdbSearchBusy;
            btn.classList.toggle('btn-disabled', subscriptionTmdbSearchBusy);
            btn.innerText = subscriptionTmdbSearchBusy ? '搜索中...' : '搜索';
        }

        function renderSubscriptionTmdbResults() {
            const listEl = document.getElementById('subscription_tmdb_result_list');
            if (!listEl) return;
            if (subscriptionTmdbSearchBusy) {
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">正在搜索 TMDB，请稍候...</div>';
                return;
            }
            if (!subscriptionTmdbResults.length) {
                listEl.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-slate-400 text-sm">暂无结果，请尝试更换关键词或年份。</div>';
                return;
            }
            listEl.innerHTML = subscriptionTmdbResults.map((item, index) => {
                const mediaLabel = normalizeTmdbMediaType(item.media_type, 'movie') === 'tv' ? '电视剧' : '电影';
                const poster = item.poster_url
                    ? `<img src="${escapeHtml(item.poster_url)}" alt="${escapeHtml(item.title || '--')}" class="w-14 h-20 rounded-lg object-cover border border-slate-700 bg-slate-900">`
                    : '<div class="w-14 h-20 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-500 flex items-center justify-center bg-slate-900">无封面</div>';
                const yearText = item.year ? ` / ${escapeHtml(item.year)}` : '';
                const voteText = Number(item.vote_average || 0) > 0 ? ` / 评分 ${escapeHtml(String(item.vote_average))}` : '';
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-3">
                        <div class="flex items-start gap-3">
                            ${poster}
                            <div class="min-w-0 flex-1 text-xs text-slate-400 leading-6">
                                <div class="text-sm font-bold text-white break-words">${escapeHtml(item.title || '--')}</div>
                                <div>${escapeHtml(mediaLabel)}${yearText}${voteText}</div>
                                <div>原名：${escapeHtml(item.original_title || '--')}</div>
                                <div class="line-clamp-2">${escapeHtml(item.overview || '暂无简介')}</div>
                            </div>
                            <button
                                type="button"
                                data-subscription-tmdb-action="select"
                                data-subscription-tmdb-index="${index}"
                                class="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shrink-0"
                            >绑定</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function searchSubscriptionTmdbBinding() {
            const searchInput = document.getElementById('subscription_tmdb_search_keyword');
            const hintEl = document.getElementById('subscription_tmdb_search_hint');
            const fallbackQuery = document.getElementById('subscription_title')?.value || '';
            const query = String(searchInput?.value || fallbackQuery || '').trim();
            if (!query) {
                alert('请先输入影视名称，再搜索 TMDB');
                return;
            }
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const year = normalizeTmdbYear(document.getElementById('subscription_year')?.value || '');
            const requestToken = ++subscriptionTmdbSearchToken;
            setSubscriptionTmdbSearchBusy(true);
            subscriptionTmdbResults = [];
            renderSubscriptionTmdbResults();
            if (hintEl) hintEl.innerText = `正在按 ${mediaType === 'tv' ? '电视剧' : '电影'} 搜索：${query}`;
            try {
                const qs = new URLSearchParams({ q: query, media_type: mediaType });
                if (year) qs.set('year', year);
                const res = await fetch(`/tmdb/search?${qs.toString()}`);
                const data = await res.json();
                if (requestToken !== subscriptionTmdbSearchToken) return;
                if (!res.ok || !data.ok) throw new Error(data.msg || 'TMDB 搜索失败');
                subscriptionTmdbResults = Array.isArray(data.items) ? data.items : [];
                renderSubscriptionTmdbResults();
                if (hintEl) {
                    hintEl.innerText = subscriptionTmdbResults.length
                        ? `已找到 ${subscriptionTmdbResults.length} 条结果，请选择要绑定的条目。`
                        : '未找到可绑定条目，请调整关键词后重试。';
                }
            } catch (e) {
                subscriptionTmdbResults = [];
                renderSubscriptionTmdbResults();
                if (hintEl) hintEl.innerText = `TMDB 搜索失败：${e.message || '未知错误'}`;
            } finally {
                if (requestToken === subscriptionTmdbSearchToken) {
                    setSubscriptionTmdbSearchBusy(false);
                    renderSubscriptionTmdbResults();
                }
            }
        }

        async function selectSubscriptionTmdbResult(index) {
            const target = subscriptionTmdbResults[Number(index)];
            if (!target) return;
            const hintEl = document.getElementById('subscription_tmdb_search_hint');
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            if (hintEl) hintEl.innerText = `正在读取 TMDB 详情：${target.title || '--'}`;
            try {
                const qs = new URLSearchParams({
                    tmdb_id: String(target.id || 0),
                    media_type: normalizeTmdbMediaType(target.media_type, mediaType) || mediaType
                });
                const res = await fetch(`/tmdb/detail?${qs.toString()}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取 TMDB 详情失败');
                const binding = data.task_binding || {};
                const bindingMediaType = normalizeTmdbMediaType(binding.tmdb_media_type, mediaType);
                if (bindingMediaType && bindingMediaType !== mediaType) {
                    throw new Error('TMDB 类型与当前订阅类型不一致，请切换类型后再绑定');
                }
                setSubscriptionTmdbBinding(binding);
                const titleInput = document.getElementById('subscription_title');
                if (titleInput && !String(titleInput.value || '').trim()) {
                    titleInput.value = String(binding.tmdb_title || target.title || '').trim();
                }
                const yearInput = document.getElementById('subscription_year');
                if (yearInput && !normalizeTmdbYear(yearInput.value || '') && normalizeTmdbYear(binding.tmdb_year || '')) {
                    yearInput.value = normalizeTmdbYear(binding.tmdb_year || '');
                }
                const aliasesInput = document.getElementById('subscription_aliases');
                if (aliasesInput && !String(aliasesInput.value || '').trim()) {
                    const defaultAliases = Array.isArray(binding.tmdb_aliases) ? binding.tmdb_aliases.slice(0, 4) : [];
                    aliasesInput.value = defaultAliases.join(', ');
                }
                if (mediaType === 'tv') {
                    // 绑定 TMDB 后应以 TMDB 详情刷新总集数，避免旧值残留。
                    suggestSubscriptionTotalEpisodesFromTmdb({ force: true });
                }
                closeSubscriptionTmdbSearchModal();
                showToast(`已绑定 TMDB：${binding.tmdb_title || target.title || '--'}`, { tone: 'success', duration: 2600, placement: 'top-center' });
            } catch (e) {
                if (hintEl) hintEl.innerText = `读取详情失败：${e.message || '未知错误'}`;
            }
        }

        function openSubscriptionTmdbSearchModal() {
            const keywordInput = document.getElementById('subscription_tmdb_search_keyword');
            const title = String(document.getElementById('subscription_title')?.value || '').trim();
            if (keywordInput) keywordInput.value = title || keywordInput.value || '';
            subscriptionTmdbResults = [];
            renderSubscriptionTmdbResults();
            showLockedModal('subscription-tmdb-modal');
            if (keywordInput && String(keywordInput.value || '').trim()) {
                searchSubscriptionTmdbBinding();
            }
        }

        function closeSubscriptionTmdbSearchModal() {
            hideLockedModal('subscription-tmdb-modal');
        }

        function suggestSubscriptionTotalEpisodesFromTmdb({ force = false } = {}) {
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            if (mediaType !== 'tv') return;
            const totalInput = document.getElementById('subscription_total_episodes');
            if (!totalInput) return;
            const currentTotal = parseInt(totalInput.value || '0', 10) || 0;
            if (!force && currentTotal > 0) return;
            const binding = getSubscriptionTmdbBindingFromForm();
            if ((parseInt(binding.tmdb_id || '0', 10) || 0) <= 0) return;
            const selectedSeason = Math.max(1, parseInt(document.getElementById('subscription_season')?.value || '1', 10) || 1);
            const seasonTotal = getTmdbSeasonEpisodeTotal(binding.tmdb_season_episode_map, selectedSeason);
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            const tmdbTotal = Math.max(0, parseInt(binding.tmdb_total_episodes || '0', 10) || 0);
            const suggestedTotal = multiSeasonMode
                ? (tmdbTotal > 0 ? tmdbTotal : seasonTotal)
                : (seasonTotal > 0 ? seasonTotal : 0);
            if (suggestedTotal > 0 && (force || currentTotal <= 0)) totalInput.value = String(suggestedTotal);
        }

        function syncSubscriptionProviderUI() {
            const provider = getCurrentSubscriptionProvider();
            const isQuark = provider === 'quark';
            const providerLabel = getSubscriptionProviderLabel(provider);
            const savepathProviderLabelEl = document.getElementById('subscription-savepath-provider-label');
            const fixedLinkBlockEl = document.getElementById('subscription-115-fixed-link-block');
            const quarkHintEl = document.getElementById('subscription-quark-provider-hint');
            const minScoreWrapEl = document.getElementById('subscription-min-score-wrap');
            const minScoreInputEl = document.getElementById('subscription_min_score');
            const strategyHintEl = document.getElementById('subscription-provider-strategy-hint');

            if (savepathProviderLabelEl) savepathProviderLabelEl.textContent = `${providerLabel} 保存目录`;
            if (fixedLinkBlockEl) fixedLinkBlockEl.classList.toggle('hidden', isQuark);
            if (quarkHintEl) quarkHintEl.classList.toggle('hidden', !isQuark);
            if (minScoreWrapEl) minScoreWrapEl.classList.toggle('hidden', isQuark);
            if (minScoreInputEl) minScoreInputEl.disabled = isQuark;
            if (strategyHintEl) {
                strategyHintEl.textContent = isQuark
                    ? '匹配策略：Quark 仅使用频道自动匹配，采用独立评分（强标题命中 + 集数命中）；仅集数命中会被拦截。'
                    : '匹配策略：若填写了固定 115 分享链接，默认只在该链接内扫描；可开启“固定链接后再补搜一次频道”作为兜底。未填写固定链接时，会在已启用频道按标题/别名主动搜索并评分命中。';
            }

            if (isQuark) {
                const shareLinkInput = document.getElementById('subscription_share_link_url');
                const shareReceiveInput = document.getElementById('subscription_share_receive_code');
                const fixedLinkSearchInput = document.getElementById('subscription_fixed_link_channel_search');
                if (shareLinkInput) shareLinkInput.value = '';
                if (shareReceiveInput) shareReceiveInput.value = '';
                if (fixedLinkSearchInput) fixedLinkSearchInput.checked = false;
                setSubscriptionShareSubdirSelection('', '');
                resetSubscriptionShareFolderBrowser();
            }
        }

        function syncSubscriptionTypeUI({ forceSuggestTotal = false } = {}) {
            const mediaType = normalizeSubscriptionMediaType(document.getElementById('subscription_media_type')?.value || 'movie');
            const tvFields = document.getElementById('subscription-tv-fields');
            if (tvFields) tvFields.classList.toggle('hidden', mediaType !== 'tv');
            const animeModeWrap = document.getElementById('subscription-anime-mode-wrap');
            if (animeModeWrap) animeModeWrap.classList.toggle('hidden', mediaType !== 'tv');
            const seasonInput = document.getElementById('subscription_season');
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode')?.checked;
            if (seasonInput) {
                const disableSeason = mediaType !== 'tv' || multiSeasonMode;
                seasonInput.disabled = disableSeason;
                if (disableSeason) seasonInput.setAttribute('title', '多季合一已开启时，季数不参与订阅过滤');
                else seasonInput.removeAttribute('title');
            }
            const hintEl = document.getElementById('subscription-savepath-hint');
            if (hintEl) {
                hintEl.innerText = mediaType === 'movie'
                    ? '电影会自动保存到“目标目录/影片名”子文件夹；电视剧保存到所选目录。'
                    : '电视剧会直接保存到所选目录；请把目录设在剧集父文件夹下。';
            }
            syncSubscriptionProviderUI();
            suggestSubscriptionTotalEpisodesFromTmdb({ force: !!forceSuggestTotal });
            renderSubscriptionTmdbBinding();
        }

        function setSubscriptionSavepath(folderId = '0', displayPath = '', { trail = null } = {}) {
            const normalizedFolderId = String(folderId || '0').trim() || '0';
            const normalizedPath = normalizeRelativePathInput(displayPath || '');
            const hiddenFolderEl = document.getElementById('subscription_folder_id');
            const hiddenSavepathEl = document.getElementById('subscription_savepath');
            const displayEl = document.getElementById('subscription_savepath_display');
            if (hiddenFolderEl) hiddenFolderEl.value = normalizedFolderId;
            if (hiddenSavepathEl) hiddenSavepathEl.value = normalizedPath;
            if (displayEl) displayEl.value = normalizedPath || '请选择保存目录';
            if (Array.isArray(trail) && trail.length) {
                subscriptionFolderTrail = trail;
            }
        }

        function currentSubscriptionFormData() {
            const title = document.getElementById('subscription_title').value.trim();
            const provider = getCurrentSubscriptionProvider();
            const tmdbBinding = getSubscriptionTmdbBindingFromForm();
            const multiSeasonMode = !!document.getElementById('subscription_anime_mode').checked;
            const scheduleWeekdays = getSubscriptionWeekdaysFromForm();
            const scheduleStartTime = normalizeSubscriptionScheduleTime(
                document.getElementById('subscription_schedule_start_time')?.value || '00:00',
                '00:00'
            );
            const scheduleEndTime = normalizeSubscriptionScheduleTime(
                document.getElementById('subscription_schedule_end_time')?.value || '23:59',
                '23:59'
            );
            const scheduleIntervalMinutes = Math.max(
                1,
                parseInt(
                    document.getElementById('subscription_schedule_interval_minutes')?.value || String(SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES),
                    10
                ) || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            const shareLinkRaw = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            const shareLinkType = detectResourceLinkTypeByUrl(shareLinkRaw);
            const normalizedShareLink = provider === '115' && shareLinkType === '115share' ? shareLinkRaw : '';
            const receiveCodeRaw = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            const normalizedReceiveCode = normalizeReceiveCodeInput(receiveCodeRaw);
            const shareSubdir = normalizeRelativePathInput(document.getElementById('subscription_share_subdir')?.value || '');
            const shareSubdirCid = shareSubdir
                ? normalizeShareCidInput(document.getElementById('subscription_share_subdir_cid')?.value || '')
                : '';
            const fixedLinkChannelSearch = provider === '115' && !!document.getElementById('subscription_fixed_link_channel_search')?.checked;
            return {
                name: title,
                provider,
                media_type: normalizeSubscriptionMediaType(document.getElementById('subscription_media_type').value),
                title,
                aliases: document.getElementById('subscription_aliases').value.trim(),
                year: document.getElementById('subscription_year').value.trim(),
                season: parseInt(document.getElementById('subscription_season').value || '1', 10) || 1,
                total_episodes: parseInt(document.getElementById('subscription_total_episodes').value || '0', 10) || 0,
                anime_mode: multiSeasonMode,
                multi_season_mode: multiSeasonMode,
                savepath: normalizeRelativePathInput(document.getElementById('subscription_savepath').value.trim()),
                share_link_url: normalizedShareLink,
                share_link_receive_code: normalizedReceiveCode,
                share_subdir: shareSubdir,
                share_subdir_cid: shareSubdirCid,
                fixed_link_channel_search: fixedLinkChannelSearch,
                schedule_weekdays: scheduleWeekdays,
                schedule_start_time: scheduleStartTime,
                schedule_end_time: scheduleEndTime,
                schedule_interval_minutes: scheduleIntervalMinutes,
                min_score: parseInt(document.getElementById('subscription_min_score').value || '55', 10) || 55,
                quality_priority: normalizeSubscriptionQualityPriority(document.getElementById('subscription_quality_priority').value || 'ultra'),
                enabled: document.getElementById('subscription_enabled').checked,
                tmdb_id: tmdbBinding.tmdb_id,
                tmdb_media_type: tmdbBinding.tmdb_media_type,
                tmdb_title: tmdbBinding.tmdb_title,
                tmdb_original_title: tmdbBinding.tmdb_original_title,
                tmdb_year: tmdbBinding.tmdb_year,
                tmdb_aliases: tmdbBinding.tmdb_aliases,
                tmdb_total_episodes: tmdbBinding.tmdb_total_episodes,
                tmdb_total_seasons: tmdbBinding.tmdb_total_seasons,
                tmdb_season_episode_map: tmdbBinding.tmdb_season_episode_map,
                tmdb_episode_mode: tmdbBinding.tmdb_episode_mode,
            };
        }

        function resetSubscriptionForm() {
            editingSubscriptionName = null;
            const titleEl = document.getElementById('subscription-modal-title');
            if (titleEl) titleEl.innerText = '新增订阅任务';
            document.getElementById('subscription_media_type').value = 'tv';
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = '115';
            document.getElementById('subscription_title').value = '';
            document.getElementById('subscription_aliases').value = '';
            document.getElementById('subscription_year').value = '';
            document.getElementById('subscription_season').value = 1;
            document.getElementById('subscription_total_episodes').value = 0;
            document.getElementById('subscription_anime_mode').checked = false;
            setSubscriptionSavepath('0', '');
            const shareLinkInput = document.getElementById('subscription_share_link_url');
            if (shareLinkInput) shareLinkInput.value = '';
            const shareReceiveInput = document.getElementById('subscription_share_receive_code');
            if (shareReceiveInput) shareReceiveInput.value = '';
            const fixedLinkChannelSearchInput = document.getElementById('subscription_fixed_link_channel_search');
            if (fixedLinkChannelSearchInput) fixedLinkChannelSearchInput.checked = false;
            setSubscriptionShareSubdirSelection('', '');
            resetSubscriptionShareFolderBrowser();
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            subscriptionFolderEntries = [];
            subscriptionFolderSummary = { folder_count: 0, file_count: 0 };
            subscriptionFolderLoading = false;
            subscriptionFolderCreateBusy = false;
            setSubscriptionWeekdaysToForm(SUBSCRIPTION_DEFAULT_WEEKDAYS);
            document.getElementById('subscription_schedule_start_time').value = '00:00';
            document.getElementById('subscription_schedule_end_time').value = '23:59';
            document.getElementById('subscription_schedule_interval_minutes').value = SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES;
            document.getElementById('subscription_min_score').value = 55;
            document.getElementById('subscription_quality_priority').value = 'ultra';
            document.getElementById('subscription_enabled').checked = true;
            clearSubscriptionTmdbBinding({ silent: true });
            subscriptionTmdbResults = [];
            subscriptionTmdbSearchToken += 1;
            setSubscriptionTmdbSearchBusy(false);
            const tmdbKeywordInput = document.getElementById('subscription_tmdb_search_keyword');
            if (tmdbKeywordInput) tmdbKeywordInput.value = '';
            const tmdbHintEl = document.getElementById('subscription_tmdb_search_hint');
            if (tmdbHintEl) tmdbHintEl.innerText = '按当前订阅类型（电影/电视剧）检索 TMDB，选择后会写入任务绑定信息。';
            renderSubscriptionTmdbResults();
            syncSubscriptionTypeUI();
        }

        function openNewSubscriptionTask(prefill = null) {
            resetSubscriptionForm();
            if (prefill && typeof prefill === 'object') applySubscriptionPrefill(prefill);
            showLockedModal('subscription-modal');
            switchTab('subscription');
        }

        function openSubscriptionFromResource(resourceOrId) {
            const directItem = resourceOrId && typeof resourceOrId === 'object' ? resourceOrId : null;
            const resourceId = Number(directItem ? directItem.id : resourceOrId || 0);
            let item = directItem;
            if (!item && resourceId) item = findResourceItem(resourceId);
            if (!item && selectedResourceItem && Number(selectedResourceItem?.id || 0) === resourceId) item = selectedResourceItem;
            if (!item) {
                showToast('未找到资源，无法转订阅', { tone: 'error', duration: 2600, placement: 'top-center' });
                return;
            }
            const resourceModal = document.getElementById('resource-import-modal');
            if (resourceModal && !resourceModal.classList.contains('hidden')) {
                closeResourceJobModal();
            }
            openNewSubscriptionTask(inferSubscriptionDraftFromResource(item));
            showToast('已预填订阅信息，请继续补充保存目录等配置后保存任务', {
                tone: 'success',
                duration: 3200,
                placement: 'top-center'
            });
        }

        function closeSubscriptionModal() {
            hideLockedModal('subscription-modal');
        }

        async function persistSubscriptionTasks(tasks) {
            const res = await fetch('/subscription/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tasks })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.msg || '保存订阅任务失败');
            applySubscriptionState({ ...subscriptionState, tasks: data.tasks || [] }, { forceRender: true });
        }

        function buildSubscriptionProviderTaskName(title, provider) {
            const normalizedTitle = String(title || '').trim();
            if (!normalizedTitle) return '';
            const suffix = getSubscriptionProviderBadgeLabel(provider);
            return `${normalizedTitle} (${suffix})`;
        }

        async function saveSubscriptionTask() {
            const task = currentSubscriptionFormData();
            task.provider = normalizeSubscriptionProvider(task.provider, '115');
            if (!task.title) return alert('订阅影视名称不能为空');
            if (!task.savepath) return alert('请先从网盘选择保存目录');
            const rawShareLink = String(document.getElementById('subscription_share_link_url')?.value || '').trim();
            if (task.provider === '115' && rawShareLink && !task.share_link_url) return alert('固定分享链接仅支持 115 分享链接格式');
            const rawReceiveCode = String(document.getElementById('subscription_share_receive_code')?.value || '').trim();
            if (task.provider === '115' && rawReceiveCode && !task.share_link_receive_code) return alert('提取码格式不正确，请输入 1-16 位字母或数字');
            if (task.provider !== '115' || !task.share_link_url) {
                task.share_link_url = '';
                task.share_link_receive_code = '';
                task.share_subdir = '';
                task.share_subdir_cid = '';
                task.fixed_link_channel_search = false;
            }
            if (!task.share_subdir) task.share_subdir_cid = '';
            if (task.year && !/^(19|20)\d{2}$/.test(task.year)) return alert('年份格式不正确，请输入四位年份');
            if (task.schedule_start_time === task.schedule_end_time) return alert('开始时间和结束时间不能相同');
            if (task.schedule_interval_minutes < 1) return alert('时段内查询间隔不能小于 1 分钟');
            if (task.enabled && (!Array.isArray(task.schedule_weekdays) || task.schedule_weekdays.length <= 0)) {
                return alert('请至少选择一个查询星期，或先关闭任务启用状态');
            }
            if (task.provider === '115' && (task.min_score < 30 || task.min_score > 100)) return alert('匹配阈值需在 30-100 之间');
            if (task.provider !== '115') task.min_score = 55;
            if (!['balanced', 'ultra', 'fhd', 'hd', 'sd'].includes(task.quality_priority)) return alert('清晰度优先级配置无效');
            if (task.tmdb_id > 0 && task.tmdb_media_type && task.tmdb_media_type !== task.media_type) {
                return alert('TMDB 绑定类型与订阅类型不一致，请重新绑定');
            }
            if (task.media_type !== 'tv') {
                task.season = 1;
                task.total_episodes = 0;
                task.anime_mode = false;
                task.multi_season_mode = false;
                task.tmdb_total_episodes = 0;
                task.tmdb_total_seasons = 0;
                task.tmdb_season_episode_map = {};
                task.tmdb_episode_mode = 'seasonal';
            } else {
                task.multi_season_mode = !!(task.multi_season_mode ?? task.anime_mode);
                task.anime_mode = !!task.multi_season_mode;
                task.tmdb_episode_mode = normalizeTmdbEpisodeMode(task.tmdb_episode_mode || 'seasonal');
                if (!task.multi_season_mode) {
                    const seasonTotal = getTmdbSeasonEpisodeTotal(task.tmdb_season_episode_map || {}, task.season);
                    const tmdbTotal = Math.max(0, parseInt(task.tmdb_total_episodes || '0', 10) || 0);
                    if (seasonTotal > 0 && (task.total_episodes <= 0 || (tmdbTotal > 0 && task.total_episodes === tmdbTotal && seasonTotal !== tmdbTotal))) {
                        task.total_episodes = seasonTotal;
                    }
                }
            }
            if (task.tmdb_id <= 0) {
                task.tmdb_media_type = '';
                task.tmdb_title = '';
                task.tmdb_original_title = '';
                task.tmdb_year = '';
                task.tmdb_aliases = [];
                task.tmdb_total_episodes = 0;
                task.tmdb_total_seasons = 0;
                task.tmdb_season_episode_map = {};
                task.tmdb_episode_mode = 'seasonal';
            }

            const tasks = [...(subscriptionState.tasks || [])].map(item => ({
                ...item,
                aliases: Array.isArray(item.aliases) ? item.aliases.join(', ') : (item.aliases || '')
            }));
            const normalizedTitle = String(task.title || '').trim();
            const editingTask = tasks.find((item) => String(item?.name || '').trim() === String(editingSubscriptionName || '').trim()) || null;
            const editingName = String(editingSubscriptionName || '').trim();
            const keepsProviderSuffix = /\s\((?:115|quark)\)$/i.test(editingName);
            if (editingTask && keepsProviderSuffix && String(task.name || '').trim() === normalizedTitle) {
                task.name = buildSubscriptionProviderTaskName(normalizedTitle, task.provider);
            }
            const hasSameTitleOtherProvider = tasks.some((item) => {
                if (String(item?.name || '').trim() === String(editingSubscriptionName || '').trim()) return false;
                const itemTitle = String(item?.title || '').trim();
                if (!itemTitle || itemTitle !== normalizedTitle) return false;
                const itemProvider = normalizeSubscriptionProvider(item?.provider || '115', '115');
                return itemProvider !== task.provider;
            });
            if (hasSameTitleOtherProvider && String(task.name || '').trim() === normalizedTitle) {
                task.name = buildSubscriptionProviderTaskName(normalizedTitle, task.provider);
            }
            const dup = tasks.find(item => item.name === task.name && item.name !== editingSubscriptionName);
            if (dup) return alert(`任务名称重复（${task.name}），请修改标题或网盘提供方后再保存`);
            const idx = tasks.findIndex(item => item.name === editingSubscriptionName);
            if (idx >= 0) tasks[idx] = task;
            else tasks.push(task);

            try {
                await persistSubscriptionTasks(tasks);
                closeSubscriptionModal();
                resetSubscriptionForm();
                alert('✅ 订阅任务已保存');
            } catch (e) {
                alert(`❌ ${e.message}`);
            }
        }

        function editSubscriptionTask(name) {
            const task = (subscriptionState.tasks || []).find(item => item.name === name);
            if (!task) return;
            editingSubscriptionName = task.name;
            const titleEl = document.getElementById('subscription-modal-title');
            if (titleEl) titleEl.innerText = `编辑订阅任务：${task.name}`;
            const providerInput = document.getElementById('subscription_provider');
            if (providerInput) providerInput.value = normalizeSubscriptionProvider(task.provider || '115', '115');
            document.getElementById('subscription_media_type').value = normalizeSubscriptionMediaType(task.media_type || 'movie');
            document.getElementById('subscription_title').value = task.title || '';
            document.getElementById('subscription_aliases').value = Array.isArray(task.aliases) ? task.aliases.join(', ') : (task.aliases || '');
            document.getElementById('subscription_year').value = task.year || '';
            document.getElementById('subscription_season').value = task.season || 1;
            document.getElementById('subscription_total_episodes').value = task.total_episodes || 0;
            document.getElementById('subscription_anime_mode').checked = resolveTaskMultiSeasonMode(task);
            subscriptionFolderTrail = [{ id: '0', name: '根目录' }];
            setSubscriptionSavepath('0', task.savepath || '');
            const shareLinkInput = document.getElementById('subscription_share_link_url');
            if (shareLinkInput) shareLinkInput.value = String(task.share_link_url || '').trim();
            const shareReceiveInput = document.getElementById('subscription_share_receive_code');
            if (shareReceiveInput) shareReceiveInput.value = normalizeReceiveCodeInput(task.share_link_receive_code || '');
            const fixedLinkChannelSearchInput = document.getElementById('subscription_fixed_link_channel_search');
            if (fixedLinkChannelSearchInput) fixedLinkChannelSearchInput.checked = !!task.fixed_link_channel_search;
            setSubscriptionShareSubdirSelection(task.share_subdir || '', task.share_subdir_cid || '');
            resetSubscriptionShareFolderBrowser();
            setSubscriptionWeekdaysToForm(task.schedule_weekdays || SUBSCRIPTION_DEFAULT_WEEKDAYS);
            document.getElementById('subscription_schedule_start_time').value = normalizeSubscriptionScheduleTime(task.schedule_start_time || '00:00', '00:00');
            document.getElementById('subscription_schedule_end_time').value = normalizeSubscriptionScheduleTime(task.schedule_end_time || '23:59', '23:59');
            document.getElementById('subscription_schedule_interval_minutes').value = Math.max(
                1,
                parseInt(
                    task.schedule_interval_minutes ?? task.cron_minutes ?? SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES,
                    10
                ) || SUBSCRIPTION_DEFAULT_SCHEDULE_INTERVAL_MINUTES
            );
            document.getElementById('subscription_min_score').value = task.min_score ?? 55;
            document.getElementById('subscription_quality_priority').value = normalizeSubscriptionQualityPriority(task.quality_priority || 'balanced');
            document.getElementById('subscription_enabled').checked = task.enabled !== false;
            setSubscriptionTmdbBinding({
                tmdb_id: task.tmdb_id || 0,
                tmdb_media_type: task.tmdb_media_type || '',
                tmdb_title: task.tmdb_title || '',
                tmdb_original_title: task.tmdb_original_title || '',
                tmdb_year: task.tmdb_year || '',
                tmdb_aliases: Array.isArray(task.tmdb_aliases) ? task.tmdb_aliases : [],
                tmdb_total_episodes: task.tmdb_total_episodes || 0,
                tmdb_total_seasons: task.tmdb_total_seasons || 0,
                tmdb_season_episode_map: task.tmdb_season_episode_map || {},
                tmdb_episode_mode: task.tmdb_episode_mode || 'seasonal',
            });
            syncSubscriptionTypeUI();
            showLockedModal('subscription-modal');
            switchTab('subscription');
        }

        async function deleteSubscriptionTask(name) {
            if (!confirm(`确定删除订阅任务“${name}”吗？`)) return;
            const res = await fetch('/subscription/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                return alert(`❌ ${data.msg || '删除失败'}`);
            }
            await refreshSubscriptionState();
            if (editingSubscriptionName === name) resetSubscriptionForm();
        }

        async function startSubscriptionTask(name) {
            const res = await fetch('/subscription/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                return alert(`❌ ${data.msg || '启动失败'}`);
            }
            if (data.status === 'queued') {
                const queued = Array.isArray(subscriptionState.queued) ? [...subscriptionState.queued] : [];
                if (!queued.includes(name)) queued.push(name);
                applySubscriptionState({ ...subscriptionState, queued }, { forceRender: true });
            } else {
                applySubscriptionState({
                    ...subscriptionState,
                    running: true,
                    current_task: name,
                    summary: { step: '准备执行', detail: `${name} (manual)` }
                }, { forceRender: true });
            }
            await refreshSubscriptionState();
        }

        async function stopSubscriptionTask(name) {
            const res = await fetch('/subscription/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!data.ok) {
                alert('当前没有这个订阅任务在运行');
                return;
            }
            applySubscriptionState({
                ...subscriptionState,
                summary: { step: '正在中断', detail: `${name} 已发送中断请求` }
            }, { forceRender: true });
            await refreshSubscriptionState();
        }

        async function rebuildSubscriptionTask(name, { refreshEpisodeModal = false } = {}) {
            const normalizedName = String(name || '').trim();
            if (!normalizedName) return;
            if (!confirm(`按当前保存目录重建“${normalizedName}”的追更进度和集数账本吗？`)) return;
            try {
                const res = await fetch('/subscription/rebuild', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: normalizedName })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '重建失败');
                const episodeView = data.episode_view && typeof data.episode_view === 'object' ? data.episode_view : null;
                if (episodeView) {
                    subscriptionEpisodeViewCache[normalizedName] = {
                        fetched_at: Date.now(),
                        data: episodeView,
                    };
                    if (subscriptionEpisodeViewTaskName === normalizedName) {
                        subscriptionEpisodeViewData = episodeView;
                        subscriptionEpisodeViewError = '';
                        subscriptionEpisodeViewLoading = false;
                        if (refreshEpisodeModal) renderSubscriptionEpisodeModal();
                    }
                } else {
                    delete subscriptionEpisodeViewCache[normalizedName];
                }
                delete subscriptionIntroEpisodeLookupFailedAt[normalizedName];
                showToast(data.msg || '已完成目录重建', { tone: 'success', duration: 3200, placement: 'top-center' });
                await refreshSubscriptionState();
                if (refreshEpisodeModal && subscriptionEpisodeViewTaskName === normalizedName) {
                    await refreshSubscriptionEpisodeView(true);
                }
            } catch (error) {
                showToast(`重建失败：${error?.message || '请稍后重试'}`, { tone: 'error', duration: 3600, placement: 'top-center' });
            }
        }

        async function rebuildCurrentSubscriptionEpisodeView() {
            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) return;
            await rebuildSubscriptionTask(taskName, { refreshEpisodeModal: true });
        }

        function renderSubscriptionTasks() {
            const container = document.getElementById('subscription-task-list');
            if (!container) return;
            const tasks = subscriptionState.tasks || [];
            if (!tasks.length) {
                container.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400 text-sm">还没有订阅任务，点击“新增订阅任务”即可创建。</div>';
                return;
            }
            container.innerHTML = tasks.map(task => {
                const taskName = String(task.name || '').trim();
                const displayTitle = String(task.title || taskName || '').trim() || taskName;
                const providerBadgeHtml = buildSubscriptionProviderBadge(task.provider || '115');
                const running = subscriptionState.running && subscriptionState.current_task === taskName;
                const queued = (subscriptionState.queued || []).includes(taskName);
                const status = running ? 'running' : (task.status || 'idle');
                const nextRun = (subscriptionState.next_runs || {})[taskName];
                const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
                const isTv = normalizeSubscriptionMediaType(task.media_type || 'movie') === 'tv';
                const multiSeasonMode = resolveTaskMultiSeasonMode(task);
                const introExpanded = isTaskIntroExpanded(subscriptionTaskIntroExpanded, taskName);
                if (isTv && introExpanded) ensureSubscriptionIntroEpisode(taskName);
                const episodeText = isTv
                    ? buildSubscriptionTaskEpisodeText(task, taskName, { introExpanded })
                    : '电影订阅：命中资源即执行';
                const progressBarHtml = status === 'running'
                    ? buildSubscriptionTaskProgressBar({
                        progress,
                        detail: String(task?.detail || '').trim(),
                    })
                    : '';
                const toggleRunLabel = running ? '中断' : (queued ? '排队中' : '运行');
                const toggleRunAction = running ? 'stop' : 'start';
                const toggleRunDisabled = queued || (subscriptionState.running && !running);
                const toggleRunClass = running
                    ? 'bg-amber-500/15 hover:bg-amber-500/25 text-amber-300'
                    : (queued
                        ? 'bg-slate-700/80 text-slate-300'
                        : 'bg-emerald-600 hover:bg-emerald-500 text-white');
                const rebuildDisabled = running;
                const actionGridClass = isTv
                    ? 'subscription-task-actions subscription-task-actions-tv grid grid-cols-3 sm:grid-cols-6 gap-2 shrink-0 w-full lg:w-auto'
                    : 'subscription-task-actions subscription-task-actions-movie grid grid-cols-2 sm:grid-cols-4 gap-2 shrink-0 w-full lg:w-auto';
                const rebuildButton = isTv
                    ? `<button type="button" data-subscription-action="rebuild" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 text-sky-200 text-sm font-bold ${rebuildDisabled ? 'btn-disabled' : ''}" ${rebuildDisabled ? 'disabled' : ''}>校准</button>`
                    : '';
                const episodeViewButton = isTv
                    ? `<button type="button" data-subscription-action="episodes" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">集数视图</button>`
                    : '';
                const introText = buildSubscriptionTaskIntro(task, { status, queued, nextRun, progress, isTv, episodeText, multiSeasonMode });
                return `
                    <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-3 sm:p-4">
                        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                            <div class="min-w-0 flex-1 flex items-center justify-between gap-3">
                                <button
                                    type="button"
                                    data-subscription-toggle-intro="${encodeURIComponent(taskName)}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="min-w-0 flex-1 text-left rounded-lg border border-transparent hover:border-slate-700/75 focus:outline-none focus:ring-2 focus:ring-sky-500/45 px-1 py-0.5"
                                >
                                    <div class="flex flex-wrap items-center gap-2">
                                        <span class="text-lg font-black text-white break-all leading-tight">${escapeHtml(displayTitle)}</span>
                                        ${providerBadgeHtml}
                                    </div>
                                </button>
                                <button
                                    type="button"
                                    data-subscription-toggle-intro="${encodeURIComponent(taskName)}"
                                    aria-expanded="${introExpanded ? 'true' : 'false'}"
                                    class="shrink-0 text-[11px] sm:text-xs font-bold text-sky-300 hover:text-sky-200 hover:underline underline-offset-2 rounded-lg px-1.5 py-1 focus:outline-none focus:ring-2 focus:ring-sky-500/45"
                                >${introExpanded ? '收起简介' : '展开简介'}</button>
                            </div>
                            <div class="${actionGridClass}">
                                <button type="button" data-subscription-action="toggle-run" data-subscription-run-action="${toggleRunAction}" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl text-sm font-bold ${toggleRunClass} ${toggleRunDisabled ? 'btn-disabled' : ''}" ${toggleRunDisabled ? 'disabled' : ''}>${toggleRunLabel}</button>
                                <button type="button" data-subscription-action="edit" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold">编辑</button>
                                <button type="button" data-subscription-action="delete" data-task-name="${encodeURIComponent(taskName)}" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 text-red-300 text-sm font-bold">删除</button>
                                ${rebuildButton}
                                ${episodeViewButton}
                            </div>
                        </div>
                        ${progressBarHtml}
                        ${introExpanded ? `<div class="mt-3 text-xs text-slate-300 leading-6 rounded-xl border border-slate-700/90 bg-slate-950/45 px-3 py-2">${escapeHtml(introText)}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        function getSubscriptionTaskByName(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return null;
            return (subscriptionState.tasks || []).find(item => String(item?.name || '').trim() === normalizedName) || null;
        }

        function normalizeEpisodeList(values) {
            const result = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach((item) => {
                const episodeNo = parseInt(item || '0', 10) || 0;
                if (episodeNo <= 0 || episodeNo > 5000 || seen.has(episodeNo)) return;
                seen.add(episodeNo);
                result.push(episodeNo);
            });
            result.sort((a, b) => a - b);
            return result;
        }

        function getCachedSubscriptionEpisodePayload(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return null;
            const cached = subscriptionEpisodeViewCache[normalizedName];
            if (!cached) return null;
            const fetchedAt = Number(cached.fetched_at || 0) || 0;
            if (fetchedAt <= 0) return null;
            if ((Date.now() - fetchedAt) >= SUBSCRIPTION_EPISODE_CACHE_TTL_MS) return null;
            return cached.data || null;
        }

        function resolveSubscriptionTaskSavedEpisode(taskName, task) {
            const cachedPayload = getCachedSubscriptionEpisodePayload(taskName);
            if (cachedPayload && typeof cachedPayload === 'object') {
                return {
                    episode: Math.max(0, parseInt(cachedPayload?.max_episode || '0', 10) || 0),
                    confirmed: true,
                };
            }
            const stats = task?.stats && typeof task.stats === 'object' ? task.stats : {};
            const statsMaxEpisode = Math.max(0, parseInt(stats?.existing_episode_max || '0', 10) || 0);
            return {
                episode: statsMaxEpisode,
                confirmed: statsMaxEpisode > 0,
            };
        }

        function buildSubscriptionTaskEpisodeText(task, taskName, { introExpanded = false } = {}) {
            const totalEpisodes = Math.max(0, parseInt(task?.total_episodes || '0', 10) || 0);
            const stateEpisode = Math.max(0, parseInt(task?.last_episode || '0', 10) || 0);
            const savedEpisode = resolveSubscriptionTaskSavedEpisode(taskName, task);
            const progressEpisode = savedEpisode.confirmed ? savedEpisode.episode : stateEpisode;
            let suffix = '';
            if (savedEpisode.confirmed) suffix = '（按保存文件确认）';
            else if (introExpanded && subscriptionIntroEpisodeLookupLoading[taskName]) suffix = '（正在按保存文件核对）';
            return `追更进度：E${progressEpisode}${totalEpisodes > 0 ? ` / E${totalEpisodes}` : ''}${suffix}`;
        }

        async function ensureSubscriptionIntroEpisode(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return;
            const task = getSubscriptionTaskByName(normalizedName);
            if (!task || normalizeSubscriptionMediaType(task.media_type || 'movie') !== 'tv') return;
            if (getCachedSubscriptionEpisodePayload(normalizedName)) return;
            if (subscriptionIntroEpisodeLookupLoading[normalizedName]) return;
            const failedAt = Number(subscriptionIntroEpisodeLookupFailedAt[normalizedName] || 0) || 0;
            if (failedAt > 0 && (Date.now() - failedAt) < SUBSCRIPTION_INTRO_EPISODE_RETRY_MS) return;

            subscriptionIntroEpisodeLookupLoading[normalizedName] = true;
            try {
                const res = await fetch(`/subscription/episodes?name=${encodeURIComponent(normalizedName)}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取集数失败');
                subscriptionEpisodeViewCache[normalizedName] = {
                    fetched_at: Date.now(),
                    data,
                };
                delete subscriptionIntroEpisodeLookupFailedAt[normalizedName];
            } catch (_) {
                subscriptionIntroEpisodeLookupFailedAt[normalizedName] = Date.now();
            } finally {
                delete subscriptionIntroEpisodeLookupLoading[normalizedName];
                if (isTaskIntroExpanded(subscriptionTaskIntroExpanded, normalizedName)) {
                    renderSubscriptionTasks();
                }
            }
        }

        function convertAbsoluteEpisodeToSeasonEpisode(seasonEpisodeMap, absoluteEpisode) {
            const target = Math.max(0, parseInt(absoluteEpisode || '0', 10) || 0);
            if (target <= 0) return { season: 0, episode: 0 };
            const normalizedMap = normalizeTmdbSeasonEpisodeMap(seasonEpisodeMap || {});
            const seasonList = Object.entries(normalizedMap)
                .map(([season, total]) => ({
                    season: Math.max(0, parseInt(season || '0', 10) || 0),
                    total: Math.max(0, parseInt(total || '0', 10) || 0),
                }))
                .filter((item) => item.season > 0 && item.total > 0)
                .sort((a, b) => a.season - b.season);
            if (!seasonList.length) return { season: 0, episode: target };

            let remaining = target;
            for (const item of seasonList) {
                if (remaining <= item.total) {
                    return { season: item.season, episode: remaining };
                }
                remaining -= item.total;
            }
            return { season: 0, episode: target };
        }

        function toggleSubscriptionEpisodeViewModeSwitch(task, payload) {
            const switchWrap = document.getElementById('subscription-episode-view-mode-switch');
            const absoluteBtn = document.getElementById('subscription-episode-mode-absolute');
            const seasonBtn = document.getElementById('subscription-episode-mode-season');
            if (!switchWrap || !absoluteBtn || !seasonBtn) return;

            const multiSeason = !!(task?.multi_season_mode ?? task?.anime_mode ?? payload?.multi_season_mode);
            if (multiSeason) {
                switchWrap.classList.remove('hidden');
                switchWrap.classList.add('inline-flex');
            } else {
                switchWrap.classList.add('hidden');
                switchWrap.classList.remove('inline-flex');
                subscriptionEpisodeViewMode = 'absolute';
            }

            const activeAbsolute = subscriptionEpisodeViewMode !== 'season';
            absoluteBtn.classList.toggle('is-active', activeAbsolute);
            seasonBtn.classList.toggle('is-active', !activeAbsolute);
            absoluteBtn.setAttribute('aria-pressed', activeAbsolute ? 'true' : 'false');
            seasonBtn.setAttribute('aria-pressed', !activeAbsolute ? 'true' : 'false');
        }

        function setSubscriptionEpisodeViewMode(mode) {
            const normalized = String(mode || '').trim().toLowerCase();
            subscriptionEpisodeViewMode = normalized === 'season' ? 'season' : 'absolute';
            renderSubscriptionEpisodeModal();
        }

        function renderSubscriptionEpisodeModal() {
            const titleEl = document.getElementById('subscription-episode-modal-title');
            const summaryEl = document.getElementById('subscription-episode-modal-summary');
            const noteEl = document.getElementById('subscription-episode-modal-note');
            const gridEl = document.getElementById('subscription-episode-grid');
            if (!titleEl || !summaryEl || !noteEl || !gridEl) return;

            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) {
                titleEl.innerText = '集数视图';
                summaryEl.className = 'text-xs text-slate-400 mt-2';
                summaryEl.innerText = '点击任务卡片里的“集数视图”查看。';
                noteEl.innerText = '-';
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂无任务数据</div>';
                return;
            }

            const task = getSubscriptionTaskByName(taskName);
            titleEl.innerText = `${taskName} · 集数视图`;
            if (subscriptionEpisodeViewLoading) {
                summaryEl.className = 'text-xs text-slate-400 mt-2';
                summaryEl.innerText = '正在读取目录集数，请稍候...';
                noteEl.innerText = `保存路径：${task?.savepath || '--'}`;
                gridEl.innerHTML = '<div class="subscription-episode-empty">正在扫描目录中的剧集文件...</div>';
                return;
            }

            if (subscriptionEpisodeViewError) {
                summaryEl.className = 'text-xs text-red-300 mt-2';
                summaryEl.innerText = `读取失败：${subscriptionEpisodeViewError}`;
                noteEl.innerText = `保存路径：${task?.savepath || '--'}`;
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂时无法加载集数视图，请点击“刷新”重试。</div>';
                return;
            }

            const payload = subscriptionEpisodeViewData || {};
            toggleSubscriptionEpisodeViewModeSwitch(task, payload);
            const existingEpisodes = normalizeEpisodeList(payload.existing_episodes);
            const existingSet = new Set(existingEpisodes);
            let displayTotal = parseInt(payload.display_total_episodes || '0', 10) || 0;
            if (displayTotal <= 0) {
                displayTotal = Math.max(
                    parseInt(payload.total_episodes || '0', 10) || 0,
                    parseInt(payload.last_episode || '0', 10) || 0,
                    parseInt(payload.max_episode || '0', 10) || 0,
                );
            }
            if (displayTotal <= 0) displayTotal = 60;
            displayTotal = Math.max(1, Math.min(1200, displayTotal));

            const presentInRange = existingEpisodes.filter((episodeNo) => episodeNo <= displayTotal).length;
            const missingCount = Math.max(0, displayTotal - presentInRange);
            const totalEpisodes = parseInt(payload.total_episodes || '0', 10) || 0;
            const scanStats = payload.scan_stats && typeof payload.scan_stats === 'object' ? payload.scan_stats : {};
            const scanDirs = parseInt(scanStats.scanned_dirs || '0', 10) || 0;
            const scanEntries = parseInt(scanStats.scanned_entries || '0', 10) || 0;
            const scanFailed = parseInt(scanStats.failed_dirs || '0', 10) || 0;
            const scanTruncated = !!scanStats.truncated;
            const seasonEpisodeMap = normalizeTmdbSeasonEpisodeMap(task?.tmdb_season_episode_map || {});
            const useSeasonView = subscriptionEpisodeViewMode === 'season' && !!(task?.multi_season_mode ?? task?.anime_mode);

            summaryEl.className = 'text-xs text-slate-300 mt-2';

            if (!useSeasonView) {
                summaryEl.innerText = `已存在 ${presentInRange} 集 / 展示 ${displayTotal} 集（缺失 ${missingCount} 集）`;
                noteEl.innerText = [
                    `视图：绝对集数`,
                    `保存路径：${payload.savepath || task?.savepath || '--'}`,
                    totalEpisodes > 0 ? `总集数：E${totalEpisodes}` : '总集数：未配置（按已识别范围展示）',
                    `扫描目录 ${scanDirs} 个 / 条目 ${scanEntries} 条${scanFailed > 0 ? ` / 失败 ${scanFailed}` : ''}${scanTruncated ? ' / 已截断' : ''}`,
                ].join('；');

                const cells = [];
                for (let episodeNo = 1; episodeNo <= displayTotal; episodeNo += 1) {
                    const present = existingSet.has(episodeNo);
                    cells.push(
                        `<div class="subscription-episode-cell ${present ? 'is-present' : 'is-missing'}" title="E${episodeNo}${present ? ' 已存在资源' : ' 缺失资源'}"><span class="subscription-episode-cell-no">${episodeNo}</span></div>`
                    );
                }
                gridEl.innerHTML = cells.length ? cells.join('') : '<div class="subscription-episode-empty">没有可展示的集数</div>';
                return;
            }

            const seasonBuckets = [];
            const sortedSeasons = Object.keys(seasonEpisodeMap)
                .map((seasonNo) => Math.max(0, parseInt(seasonNo || '0', 10) || 0))
                .filter((seasonNo) => seasonNo > 0)
                .sort((a, b) => a - b);

            if (sortedSeasons.length) {
                let absoluteStart = 1;
                sortedSeasons.forEach((seasonNo) => {
                    const seasonTotal = Math.max(0, parseInt(seasonEpisodeMap[String(seasonNo)] || '0', 10) || 0);
                    if (seasonTotal <= 0) return;
                    const absoluteEnd = absoluteStart + seasonTotal - 1;
                    seasonBuckets.push({ seasonNo, seasonTotal, absoluteStart, absoluteEnd, episodes: [] });
                    absoluteStart = absoluteEnd + 1;
                });
            }

            if (!seasonBuckets.length) {
                summaryEl.className = 'text-xs text-amber-300 mt-2';
                summaryEl.innerText = '当前任务缺少 TMDB 分季集数映射，暂时无法切换分季视图。';
                noteEl.innerText = [
                    `视图：分季视图`,
                    `保存路径：${payload.savepath || task?.savepath || '--'}`,
                    '提示：请先绑定 TMDB 并确保“季集映射”有效',
                ].join('；');
                gridEl.innerHTML = '<div class="subscription-episode-empty">暂无可用分季映射，请改用“绝对集数”查看。</div>';
                return;
            }

            existingEpisodes.forEach((absoluteEpisode) => {
                const mapped = convertAbsoluteEpisodeToSeasonEpisode(seasonEpisodeMap, absoluteEpisode);
                if (!mapped.season || !mapped.episode) return;
                const bucket = seasonBuckets.find((item) => item.seasonNo === mapped.season);
                if (!bucket) return;
                bucket.episodes.push(mapped.episode);
            });

            const seasonBlocks = seasonBuckets.map((bucket) => {
                const seasonSet = new Set(bucket.episodes);
                const presentCount = seasonSet.size;
                const missingSeasonCount = Math.max(0, bucket.seasonTotal - presentCount);
                const seasonCells = [];
                for (let ep = 1; ep <= bucket.seasonTotal; ep += 1) {
                    const present = seasonSet.has(ep);
                    seasonCells.push(`<div class="subscription-episode-cell ${present ? 'is-present' : 'is-missing'}" title="S${String(bucket.seasonNo).padStart(2, '0')}E${String(ep).padStart(2, '0')}${present ? ' 已存在资源' : ' 缺失资源'}"><span class="subscription-episode-cell-no">${ep}</span></div>`);
                }
                return `
                    <div class="subscription-episode-season-block">
                        <div class="subscription-episode-season-title">Season ${String(bucket.seasonNo).padStart(2, '0')} · 已存在 ${presentCount}/${bucket.seasonTotal}（缺失 ${missingSeasonCount}）</div>
                        <div class="subscription-episode-grid">${seasonCells.join('')}</div>
                    </div>
                `;
            });

            summaryEl.innerText = `多季合一 · 分季视图（总已存在 ${presentInRange} 集，绝对集数范围展示 ${displayTotal}）`;
            noteEl.innerText = [
                `视图：分季视图`,
                `保存路径：${payload.savepath || task?.savepath || '--'}`,
                `映射季数：${seasonBuckets.length} 季`,
                `扫描目录 ${scanDirs} 个 / 条目 ${scanEntries} 条${scanFailed > 0 ? ` / 失败 ${scanFailed}` : ''}${scanTruncated ? ' / 已截断' : ''}`,
            ].join('；');
            gridEl.innerHTML = seasonBlocks.join('');
        }

        async function refreshSubscriptionEpisodeView(force = false) {
            const taskName = String(subscriptionEpisodeViewTaskName || '').trim();
            if (!taskName) return;

            const cached = subscriptionEpisodeViewCache[taskName];
            const nowTs = Date.now();
            if (!force && cached && (nowTs - Number(cached.fetched_at || 0)) < SUBSCRIPTION_EPISODE_CACHE_TTL_MS) {
                subscriptionEpisodeViewData = cached.data || null;
                subscriptionEpisodeViewError = '';
                subscriptionEpisodeViewLoading = false;
                renderSubscriptionEpisodeModal();
                return;
            }

            subscriptionEpisodeViewLoading = true;
            subscriptionEpisodeViewError = '';
            renderSubscriptionEpisodeModal();

            const requestedTaskName = taskName;
            try {
                const res = await fetch(`/subscription/episodes?name=${encodeURIComponent(requestedTaskName)}`);
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.msg || '读取集数视图失败');
                if (subscriptionEpisodeViewTaskName !== requestedTaskName) return;
                subscriptionEpisodeViewData = data;
                subscriptionEpisodeViewCache[requestedTaskName] = {
                    fetched_at: Date.now(),
                    data,
                };
            } catch (error) {
                if (subscriptionEpisodeViewTaskName !== requestedTaskName) return;
                subscriptionEpisodeViewData = null;
                subscriptionEpisodeViewError = error?.message || '读取集数视图失败';
            } finally {
                if (subscriptionEpisodeViewTaskName === requestedTaskName) {
                    subscriptionEpisodeViewLoading = false;
                    renderSubscriptionEpisodeModal();
                }
            }
        }

        async function openSubscriptionEpisodeModal(taskName) {
            const normalizedName = String(taskName || '').trim();
            if (!normalizedName) return;
            const task = getSubscriptionTaskByName(normalizedName);
            if (!task) {
                alert('任务不存在或已被删除');
                return;
            }
            if (normalizeSubscriptionMediaType(task.media_type || 'movie') !== 'tv') {
                alert('仅电视剧任务支持集数视图');
                return;
            }

            subscriptionEpisodeViewTaskName = normalizedName;
            subscriptionEpisodeViewData = null;
            subscriptionEpisodeViewError = '';
            subscriptionEpisodeViewLoading = true;
            showLockedModal('subscription-episode-modal');
            renderSubscriptionEpisodeModal();
            await refreshSubscriptionEpisodeView(false);
        }

        function closeSubscriptionEpisodeModal() {
            hideLockedModal('subscription-episode-modal');
        }

        async function refreshSubscriptionState() {
            const subscriptionModule = await loadSubscriptionTabModule();
            if (subscriptionModule?.refreshSubscriptionState) {
                await subscriptionModule.refreshSubscriptionState({
                    applySubscriptionState,
                });
                return;
            }
            try {
                const res = await fetch('/subscription/status');
                if (!res.ok) return;
                applySubscriptionState(await res.json());
            } catch (e) {}
        }

        async function clearSubscriptionLogs() {
            const subscriptionModule = await loadSubscriptionTabModule();
            if (subscriptionModule?.clearSubscriptionLogs) {
                await subscriptionModule.clearSubscriptionLogs({
                    setLastSubscriptionLogSignature: (nextValue) => {
                        lastSubscriptionLogSignature = String(nextValue || '');
                    },
                    refreshSubscriptionState,
                });
                return;
            }
            const res = await fetch('/subscription/logs/clear', { method: 'POST' });
            if (res.ok) {
                lastSubscriptionLogSignature = '';
                await refreshSubscriptionState();
            }
        }
