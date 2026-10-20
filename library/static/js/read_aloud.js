/* Read aloud: the book read by this device's own voices, a sentence at a
 * time, with the sentence (and the word, where the voice reports it)
 * highlighted, and the pages turning or scrolling to keep up.
 *
 * Works with reader.js's globals: currentBook, currentChapterNum,
 * allChapters, isPaginated(), pageOfRect(), visiblePageRect(), currentPageIndex,
 * applyPageTransform(), nextChapter(), saveBookmark(), updateProgressBar(),
 * updateChapterNumberLabel(), CHROME_SELECTOR.
 *
 * Languages: each sentence takes the language of the element it's in (the
 * book's own lang tags, then the chapter's, then the book's). Chinese text
 * is read as Mandarin or Cantonese by the book's tags, or by the per-book
 * "Chinese as" setting, since the script can't tell them apart.
 */
(() => {
    const synth = window.speechSynthesis;
    const supported = Boolean(synth && window.SpeechSynthesisUtterance && window.Intl?.Segmenter);
    const highlights = window.CSS?.highlights && window.Highlight ? CSS.highlights : null;

    const RATES = [0.8, 1, 1.2, 1.4, 1.7, 2];
    const LONG_SENTENCE = 260;           // longer than this is split at clauses (long utterances can fail)
    const LANGS = {                      // what the voice settings offer, by key
        en: 'English',
        'zh-CN': 'Mandarin',
        'zh-TW': 'Mandarin (Taiwan)',
        'zh-HK': 'Cantonese',
    };
    const HAN = /[\u3400-\u9fff\uf900-\ufaff]/;   // Chinese characters (CJK unified and compatibility)
    // A device without a voice for one kind of Chinese reads with the nearest it has.
    const FALLBACK = {'zh-HK': ['zh-CN', 'zh-TW'], 'zh-TW': ['zh-CN'], 'zh-CN': ['zh-TW']};
    // Elements that start a new run of text (see textRuns), and what isn't read.
    const BLOCKS = 'p, li, blockquote, h1, h2, h3, h4, h5, h6, figcaption, dt, dd, td, th, pre, div';
    const SKIP = 'nav.chapter-end, script, style, [aria-hidden="true"], aside[epub\\:type~="footnote"], ' +
        'aside[epub\\:type~="endnote"], [epub\\:type~="footnotes"], [epub\\:type~="endnotes"], ' +
        '[epub\\:type~="noteref"], a.noteref, sup a, a > sup, .read-aloud';

    let sentences = [];                  // [{text, range, lang, key, pieces, start}]
    let builtChapter = -1;
    let index = 0;
    let playing = false;
    let open = false;                    // the player bar is showing
    let following = true;                // the page keeps up with the voice
    let token = 0;                       // ignores events from cancelled utterances
    let rate = Number(localStorage.getItem('readAloudRate')) || 1;
    let voices = [];

    const $ = (id) => document.getElementById(id);
    const bookKey = () => `readAloudChinese:${window.location.pathname}`;
    const chineseAs = () => localStorage.getItem(bookKey()) || 'auto';

    // ---------- languages and voices ----------

    /** A language tag as one of our keys: en, zh-CN, zh-TW, zh-HK (or the tag itself). */
    function keyOf(tag) {
        const t = String(tag || '').toLowerCase().replace(/_/g, '-');
        if (!t) return '';
        if (t.startsWith('yue') || /^zh-(hant-)?(hk|mo)\b/.test(t)) return 'zh-HK';
        if (/^zh-(hant|tw)\b/.test(t) || t === 'zh-hant-tw') return 'zh-TW';
        if (t.startsWith('zh') || t.startsWith('cmn')) return 'zh-CN';
        if (t.startsWith('en')) return 'en';
        return t.split('-')[0];
    }

    /** Which voice language a sentence needs. */
    function sentenceKey(text, tag) {
        const declared = keyOf(tag);
        if (HAN.test(text)) {
            const as = chineseAs();
            if (as !== 'auto') return as;
            return declared.startsWith('zh') ? declared : 'zh-CN';
        }
        // Latin text in a Chinese book (a name, an English passage) is English.
        return declared && !declared.startsWith('zh') ? declared : 'en';
    }

    function loadVoices() {
        voices = synth.getVoices();
        fillVoiceSettings();
    }

    function voicesFor(key) {
        return voices.filter((v) => keyOf(v.lang) === key);
    }

    /** The voice chosen for a language, or the best one this device has. */
    function voiceFor(key) {
        const options = voicesFor(key);
        const saved = localStorage.getItem(`readAloudVoice:${key}`);
        const chosen = options.find((v) => v.voiceURI === saved);
        if (chosen) return chosen;
        const score = (v) => (/premium|enhanced|natural|neural/i.test(v.name) ? 4 : 0)
            + (v.localService ? 2 : 0)
            + (key === 'en' && v.lang === navigator.language ? 1 : 0)
            + (v.default ? 1 : 0);
        return options.sort((a, b) => score(b) - score(a))[0] || null;
    }

    // ---------- sentences ----------

    /** The chapter's text in runs read as a unit, each with where its characters live
     * in the page. A run is the text of one block, ended by a <br> or the start of
     * another block, so a chapter of loose lines in one <div> (as Haodoo's are)
     * reads line by line, not just its heading. */
    function textRuns(root) {
        const runs = [];
        let run = null;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
            acceptNode: (n) => (n.nodeType === 1 && n.matches(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
        });
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            if (n.nodeType === 1) {
                if (n.tagName === 'BR') run = null;
                continue;
            }
            const block = n.parentElement.closest(BLOCKS) || root;
            if (!run || run.block !== block) {
                run = {block, text: '', pieces: []};
                runs.push(run);
            }
            run.pieces.push({node: n, start: run.text.length});
            run.text += n.data;
        }
        return runs.filter((r) => r.text.trim());
    }

    function pointAt(pieces, i) {
        let lo = 0, hi = pieces.length - 1;
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (pieces[mid].start <= i) lo = mid; else hi = mid - 1;
        }
        const p = pieces[lo];
        return [p.node, Math.min(i - p.start, p.node.data.length)];
    }

    /** Split an over-long sentence at its clause marks. */
    function clauses(text, start) {
        if (text.length <= LONG_SENTENCE) return [[text, start]];
        const out = [];
        let from = 0;
        for (const m of text.matchAll(/[,;:，；：、—]\s*/g)) {
            const end = m.index + m[0].length;
            if (end - from >= LONG_SENTENCE / 2) { out.push([text.slice(from, end), start + from]); from = end; }
        }
        if (from < text.length) out.push([text.slice(from), start + from]);
        return out;
    }

    function buildSentences() {
        const root = $('chapter-content');
        sentences = [];
        builtChapter = currentChapterNum;
        if (!root) return;
        for (const {block, text, pieces} of textRuns(root)) {
            const tag = block.closest('[lang], [xml\\:lang]');
            const lang = tag ? (tag.getAttribute('lang') || tag.getAttribute('xml:lang')) : '';
            const segmenter = new Intl.Segmenter(keyOf(lang) || undefined, {granularity: 'sentence'});
            for (const seg of segmenter.segment(text)) {
                for (const [part, at] of clauses(seg.segment, seg.index)) {
                    const lead = part.length - part.trimStart().length;
                    const body = part.trim();
                    if (!body || !/[\p{L}\p{N}]/u.test(body)) continue;
                    const range = document.createRange();
                    range.setStart(...pointAt(pieces, at + lead));
                    range.setEnd(...pointAt(pieces, at + lead + body.length));
                    sentences.push({text: body, range, lang, key: sentenceKey(body, lang), pieces, start: at + lead});
                }
            }
        }
    }

    /** The first sentence showing on screen. */
    function firstVisible() {
        const box = visiblePageRect();
        const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
        const i = sentences.findIndex((s) => {
            const r = s.range.getClientRects()[0];
            if (!r) return false;
            return isPaginated()
                ? r.right > box.left + 1 && r.left < box.right - 1
                : r.bottom > topBar + 4;
        });
        return Math.max(0, i);
    }

    // ---------- highlighting and following ----------

    function mark(sentence, word = null) {
        if (!highlights) return;
        highlights.set('read-aloud-sentence', new Highlight(sentence.range));
        if (word) highlights.set('read-aloud-word', new Highlight(word));
        else highlights.delete('read-aloud-word');
    }

    function unmark() {
        highlights?.delete('read-aloud-sentence');
        highlights?.delete('read-aloud-word');
    }

    /** Keep the sentence on screen: turn to its page, or scroll it into the upper third. */
    function follow(sentence) {
        if (!following) return;
        const r = sentence.range.getClientRects()[0];
        if (!r) return;
        if (isPaginated()) {
            const page = pageOfRect(r);
            if (page !== currentPageIndex) {
                currentPageIndex = page;
                applyPageTransform(true);
                applyChrome(false);
                updateProgressBar();
                updateChapterNumberLabel();
                saveBookmark();
            }
        } else {
            const topBar = document.querySelector('.top-controls.visible')?.offsetHeight || 0;
            if (r.top < topBar + 8 || r.bottom > window.innerHeight * 0.75) {
                window.scrollTo({top: window.scrollY + r.top - window.innerHeight * 0.3, behavior: 'smooth'});
                applyChrome(false);
            }
        }
    }

    /** You moved the page yourself (wheel, touch and keys are always you; the
     * reader's own scrolling doesn't fire them): stop following, and offer the way back. */
    function detach() {
        if (!playing || !following) return;
        following = false;
        $('read-aloud-back').hidden = false;
    }

    function reattach() {
        following = true;
        $('read-aloud-back').hidden = true;
        if (stale()) return startAt(null);
        if (sentences[index]) follow(sentences[index]);
    }

    // ---------- speaking ----------

    /** The list no longer matches the page: another chapter, or the text re-rendered. */
    function stale() {
        return builtChapter !== currentChapterNum || !sentences[0]?.range.startContainer.isConnected;
    }

    const STALL_MS = 1000;   // a sentence that hasn't started by then was dropped: say it again, once

    function speak(i, retried = false) {
        if (stale()) {
            // You went somewhere else while it was reading: carry on from what's on screen.
            buildSentences();
            i = firstVisible();
        }
        if (i >= sentences.length) return chapterDone();
        index = Math.max(0, i);
        const s = sentences[index];
        const mine = ++token;
        const u = new SpeechSynthesisUtterance(s.text);
        const voice = voiceFor(s.key) || (FALLBACK[s.key] || []).map(voiceFor).find(Boolean) || null;
        u.lang = voice?.lang || s.key;
        if (voice) u.voice = voice;
        u.rate = rate;
        showMissing(s.key, voice);
        let started = false;
        u.onstart = () => {
            if (mine !== token) return;
            started = true;
            mark(s);
            follow(s);
        };
        u.onboundary = (e) => {
            if (mine !== token || e.name === 'sentence') return;
            const word = wordRange(s, e.charIndex, e.charLength);
            if (word) mark(s, word);
        };
        u.onend = () => {
            if (mine !== token || !playing) return;
            speak(index + 1);
        };
        u.onerror = (e) => {
            if (mine !== token || e.error === 'interrupted' || e.error === 'canceled') return;
            if (e.error === 'not-allowed') return stop();        // needs a tap first (iOS)
            if (playing) speak(index + 1);                       // a sentence it can't say: move on
        };
        synth.speak(u);
        if (!retried) {
            setTimeout(() => {
                if (started || mine !== token || !playing) return;
                cancelSpeech();
                const again = token;
                setTimeout(() => { if (again === token && playing) speak(index, true); }, RESTART_MS);
            }, STALL_MS);
        }
    }

    /** The word at charIndex in a sentence, as a range in the page. Some voices
     * don't say how long the word is; then the word is found by segmenting. */
    function wordRange(s, at, length) {
        if (!length) {
            const seg = new Intl.Segmenter(s.key, {granularity: 'word'});
            const word = [...seg.segment(s.text)].find((w) => w.index <= at && at < w.index + w.segment.length);
            if (!word) return null;
            at = word.index;
            length = word.segment.length;
        }
        if (at + length > s.text.length) return null;
        if (!/[\p{L}\p{N}]/u.test(s.text.slice(at, at + length))) return null;   // punctuation isn't a word
        const r = document.createRange();
        r.setStart(...pointAt(s.pieces, s.start + at));
        r.setEnd(...pointAt(s.pieces, s.start + at + length));
        return r;
    }

    function chapterDone() {
        if (currentBook && currentChapterNum < currentBook.spine_length - 1 && allChapters[currentChapterNum + 1]) {
            nextChapter();
            // Let the new chapter lay out before measuring it.
            requestAnimationFrame(() => requestAnimationFrame(() => { buildSentences(); speak(0); }));
        } else {
            stop();
        }
    }

    // Chrome on desktop drops an utterance spoken straight after cancel(), so
    // starting over while it's talking waits this long for the cancel to settle.
    const RESTART_MS = 120;

    function startAt(i) {
        const busy = synth.speaking || synth.pending;
        cancelSpeech();
        if (stale()) buildSentences();
        playing = true;
        following = true;
        $('read-aloud-back').hidden = true;
        setPlayButton();
        const at = i === null ? firstVisible() : i;
        if (!busy) return speak(at);
        // Show where it's going at once; the voice follows a moment later.
        index = at;
        if (sentences[at]) { mark(sentences[at]); follow(sentences[at]); }
        const mine = token;
        setTimeout(() => { if (mine === token && playing) speak(at); }, RESTART_MS);
    }

    function pause() {
        playing = false;
        cancelSpeech();
        setPlayButton();
    }

    function stop() {
        pause();
        unmark();
    }

    function cancelSpeech() {
        token++;
        synth.cancel();
    }

    function step(delta) {
        startAt(Math.min(Math.max(0, index + delta), Math.max(0, sentences.length - 1)));
    }

    // ---------- the player bar ----------

    const ICONS = {
        listen: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 14v-2a8 8 0 0 1 16 0v2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><rect x="3" y="13" width="4.5" height="7" rx="1.5" fill="currentColor"/><rect x="16.5" y="13" width="4.5" height="7" rx="1.5" fill="currentColor"/></svg>',
        play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>',
        pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="5.5" width="4" height="13" rx="1" fill="currentColor"/><rect x="13.5" y="5.5" width="4" height="13" rx="1" fill="currentColor"/></svg>',
        back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6v12M18 6.5v11L9 12z" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        next: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6v12M6 6.5v11L15 12z" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
    };

    function buildBar() {
        const bar = document.createElement('div');
        bar.className = 'read-aloud';
        bar.id = 'read-aloud';
        bar.setAttribute('role', 'region');
        bar.setAttribute('aria-label', 'Read aloud');
        bar.hidden = true;
        bar.innerHTML = `
            <button type="button" class="read-aloud__btn" data-act="back" aria-label="Previous sentence" title="Previous sentence">${ICONS.back}</button>
            <button type="button" class="read-aloud__btn read-aloud__play" data-act="play" aria-label="Play">${ICONS.play}</button>
            <button type="button" class="read-aloud__btn" data-act="next" aria-label="Next sentence" title="Next sentence">${ICONS.next}</button>
            <button type="button" class="read-aloud__rate" data-act="rate" title="Speed"></button>
            <span class="read-aloud__note" id="read-aloud-note" hidden></span>
            <button type="button" class="read-aloud__close" data-act="close" aria-label="Stop reading aloud" title="Stop">×</button>`;
        bar.addEventListener('click', (e) => {
            const act = e.target.closest('[data-act]')?.dataset.act;
            if (act === 'play') return playing ? pause() : startAt(stale() ? null : index);
            if (act === 'back') return step(-1);
            if (act === 'next') return step(1);
            if (act === 'rate') return cycleRate();
            if (act === 'close') return closeBar();
        });
        const back = document.createElement('div');
        back.className = 'back-pill';
        back.id = 'read-aloud-back';
        back.hidden = true;
        back.innerHTML = '<button type="button" class="back-pill__go">Back to where it’s reading</button>';
        back.addEventListener('click', reattach);
        document.body.append(bar, back);
        setRateLabel();
    }

    function setPlayButton() {
        const b = document.querySelector('.read-aloud__play');
        if (!b) return;
        b.innerHTML = playing ? ICONS.pause : ICONS.play;
        b.setAttribute('aria-label', playing ? 'Pause' : 'Play');
        $('read-aloud-toggle')?.classList.toggle('active', open);
    }

    function setRateLabel() {
        const b = document.querySelector('.read-aloud__rate');
        if (b) b.textContent = `${rate}×`;
    }

    function cycleRate() {
        rate = RATES[(RATES.indexOf(rate) + 1) % RATES.length] || 1;
        localStorage.setItem('readAloudRate', String(rate));
        setRateLabel();
        if (playing) startAt(index);           // the new speed from this sentence
    }

    /** Say when this device has no voice for a language the book needs. */
    function showMissing(key, voice) {
        const note = $('read-aloud-note');
        if (!note) return;
        let text = '';
        if (!voice) text = `No ${LANGS[key] || key} voice on this device`;
        else if (keyOf(voice.lang) !== key) text = `No ${LANGS[key]} voice here: reading in ${LANGS[keyOf(voice.lang)] || voice.lang}`;
        note.textContent = text;
        note.hidden = !text;
    }

    function openBar() {
        open = true;
        $('read-aloud').hidden = false;
        document.body.classList.add('reading-aloud');
        applyChrome(false);            // listening: the text gets the whole screen
        startAt(null);
    }

    function closeBar() {
        stop();
        open = false;
        $('read-aloud').hidden = true;
        $('read-aloud-back').hidden = true;
        document.body.classList.remove('reading-aloud');
        setPlayButton();
    }

    // ---------- settings (in the Aa panel) ----------

    /** The voice languages this book needs: what's in the chapter open, else the book's language. */
    function languagesHere() {
        if (stale()) buildSentences();
        const keys = new Set(sentences.map((s) => s.key));
        if (!keys.size && currentBook?.language) {
            const declared = keyOf(currentBook.language);
            keys.add(declared.startsWith('zh') && chineseAs() !== 'auto' ? chineseAs() : declared);
        }
        return keys;
    }

    /** Only the settings that matter for this book: no Chinese options for an English one. */
    function showRelevant(section) {
        const keys = languagesHere();
        const chinese = [...keys].some((k) => k.startsWith('zh'));
        const row = (el) => el.closest('.rs-row');
        row(section.querySelector('[data-setting="chinese"]')).hidden = !chinese;
        for (const select of section.querySelectorAll('select[data-voice]')) {
            const key = select.dataset.voice;
            row(select).hidden = !keys.has(key);
        }
    }

    function fillVoiceSettings() {
        const section = $('rs-read-aloud');
        if (!section) return;
        if (currentBook) showRelevant(section);
        const seg = section.querySelector('[data-setting="chinese"]');
        seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.value === chineseAs())));
        for (const select of section.querySelectorAll('select[data-voice]')) {
            const key = select.dataset.voice;
            const options = voicesFor(key);
            const current = voiceFor(key);
            select.innerHTML = '';
            if (!options.length) {
                select.append(new Option('None on this device', ''));
                select.disabled = true;
            } else {
                select.disabled = false;
                for (const v of options) select.append(new Option(`${v.name}${v.localService ? '' : ' (online)'}`, v.voiceURI, false, v === current));
            }
        }
    }

    function wireSettings() {
        const section = $('rs-read-aloud');
        if (!section) return;
        section.hidden = false;
        // Fill it in each time it opens: the voices may have loaded since, and the chapter may differ.
        $('settings-toggle')?.addEventListener('click', () => setTimeout(fillVoiceSettings));
        section.querySelector('[data-setting="chinese"]').addEventListener('click', (e) => {
            const b = e.target.closest('button[data-value]');
            if (!b) return;
            localStorage.setItem(bookKey(), b.dataset.value);
            for (const s of sentences) s.key = sentenceKey(s.text, s.lang);
            fillVoiceSettings();
            if (playing) startAt(index);
        });
        section.addEventListener('change', (e) => {
            const select = e.target.closest('select[data-voice]');
            if (!select) return;
            localStorage.setItem(`readAloudVoice:${select.dataset.voice}`, select.value);
            if (playing) startAt(index);
        });
    }

    // ---------- wiring ----------

    function init() {
        const toggle = $('read-aloud-toggle');
        if (!supported) { toggle?.remove(); return; }
        toggle.hidden = false;
        buildBar();
        wireSettings();
        loadVoices();
        synth.addEventListener?.('voiceschanged', loadVoices);
        toggle.addEventListener('click', () => (open ? closeBar() : openBar()));

        // You moved the page: stop following until you ask.
        ['wheel', 'touchmove'].forEach((ev) => window.addEventListener(ev, detach, {passive: true}));
        document.addEventListener('keydown', (e) => {
            if (['ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', ' '].includes(e.key) && !e.target.closest('input, textarea, select')) detach();
            if (e.key.toLowerCase() === 'l' && !e.metaKey && !e.ctrlKey && !e.altKey
                && !e.target.closest('input, textarea, select') && !window.getSelection().toString().trim()) {
                e.preventDefault();
                if (!open) openBar(); else if (playing) pause(); else startAt(index);
            }
        });

        // While reading aloud, a tap (or click) on a sentence reads from it. A tap
        // that lands on empty space (margins, gaps between paragraphs) does what
        // it always does: shows or hides the bars, or turns the page.
        const seek = (x, y) => {
            let node, offset;
            if (document.caretPositionFromPoint) {
                const p = document.caretPositionFromPoint(x, y);
                if (!p) return false;
                [node, offset] = [p.offsetNode, p.offset];
            } else {
                const r = document.caretRangeFromPoint?.(x, y);
                if (!r) return false;
                [node, offset] = [r.startContainer, r.startOffset];
            }
            if (stale()) buildSentences();
            const i = sentences.findIndex((s) => s.range.isPointInRange(node, offset));
            if (i < 0) return false;
            // The caret snaps to the nearest text; only a tap on the sentence itself counts.
            const hit = [...sentences[i].range.getClientRects()].some((r) =>
                x >= r.left - 4 && x <= r.right + 4 && y >= r.top - 4 && y <= r.bottom + 4);
            if (!hit) return false;
            startAt(i);
            return true;
        };
        const onText = (e) => open && !e.target.closest(CHROME_SELECTOR) && e.target.closest('#chapter-content')
            && !window.getSelection().toString().trim();
        window.addEventListener('click', (e) => {
            if (onText(e) && seek(e.clientX, e.clientY)) { e.stopPropagation(); e.preventDefault(); }
        }, true);
        let tap = null;
        window.addEventListener('touchstart', (e) => {
            tap = e.touches.length === 1 ? {x: e.touches[0].clientX, y: e.touches[0].clientY, t: e.timeStamp} : null;
        }, {capture: true, passive: true});
        window.addEventListener('touchend', (e) => {
            const t = e.changedTouches[0];
            if (!tap || !onText(e) || Math.hypot(t.clientX - tap.x, t.clientY - tap.y) > 10 || e.timeStamp - tap.t > 350) return;
            if (seek(t.clientX, t.clientY)) {
                e.stopPropagation();   // not also the bars or a page turn
                e.preventDefault();    // nor the click the browser would send after it
            }
        }, true);

        // Leaving the page stops the voice (it would carry on otherwise on some browsers).
        window.addEventListener('pagehide', () => synth.cancel());
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
