// Getting what isn't on the shelves yet (admins). Under a shelf's search, a
// quiet line offers to look further: Open Library for books, ComicVine or
// Metron for comics. The results are covers like the shelf's; what each is
// to you (in the library, asked for, following) is in its caption, and the
// cover is the action. Asked-for books and followed series then show up in
// Downloads. Nothing outside is searched until you ask.

(() => {
const BOOK_STATE = {have: 'In your library', downloaded: 'In your library', wanted: 'Asked for', snatched: 'Downloading'};

function setCaption(card, parts) {
    const line = parts.filter(Boolean).join(' · ');
    let el = card.querySelector('.book-caption__author');
    if (!el) card.querySelector('.book-caption').append(el = h('span', {class: 'book-caption__author'}));
    el.textContent = line;
}

function bookCard(book) {
    const owned = book.status === 'have' || book.status === 'downloaded';
    const asked = BOOK_STATE[book.status] && !owned;
    const card = coverCard({
        href: owned && book.href ? book.href : '#',
        label: owned ? `Read ${book.title}` : (asked ? `${book.title}, ${BOOK_STATE[book.status].toLowerCase()}` : `Ask for ${book.title}`),
        title: book.title,
        meta: [book.author, BOOK_STATE[book.status] || book.year],
        cover: book.cover_url,
        imgAttrs: {referrerpolicy: 'no-referrer'},
    });
    if (owned && book.href) return card;
    card.querySelector('.book > a').addEventListener('click', async (e) => {
        e.preventDefault();
        if (BOOK_STATE[book.status] || card.classList.contains('is-busy')) return;
        card.classList.add('is-busy');
        try {
            const data = await apiFetch('/api/get/books', {method: 'POST', body: book});
            book.status = data.status;
            book.request_id = data.id;
            setCaption(card, [book.author, BOOK_STATE[data.status] || 'Asked for']);
            showToast(`Asked for ${book.title}`, 'info', data.created ? {label: 'Undo', onClick: () => undoAsk(book, card)} : null);
        } catch (err) {
            showToast(err.message, 'error');
        }
        card.classList.remove('is-busy');
    });
    return card;
}

async function undoAsk(book, card) {
    try {
        await apiFetch(`/api/book-requests/${book.request_id}`, {method: 'DELETE'});
        book.status = null;
        setCaption(card, [book.author, book.year]);
    } catch (err) { showToast(err.message, 'error'); }
}

function comicCard(row) {
    const followed = Boolean(row.followed_id);
    const card = coverCard({
        href: followed ? appUrl(`/comics/series/${row.followed_id}`) : '#',
        label: followed ? `${row.name}, following` : `Follow ${row.name}`,
        title: row.name,
        meta: [row.start_year, row.publisher, followed ? 'Following' : (row.issue_count ? `${row.issue_count} issues` : null)],
        cover: row.cover_url,
        imgAttrs: {referrerpolicy: 'no-referrer'},
    });
    if (!followed) card.querySelector('.book > a').addEventListener('click', async (e) => {
        e.preventDefault();
        if (card.classList.contains('is-busy')) return;
        card.classList.add('is-busy');
        try {
            // New issues to start with; the series page's ⋯ changes it.
            const data = await apiFetch('/comics/api/series', {method: 'POST', body: {provider: row.provider, provider_id: row.provider_id, monitor: 'future'}});
            window.location = data.url;
        } catch (err) {
            showToast(err.message, 'error');
            card.classList.remove('is-busy');
        }
    });
    return card;
}

const KINDS = {
    books: {make: bookCard, source: 'Open Library', none: 'No books by that name on Open Library.'},
    comics: {make: comicCard, source: 'ComicVine', none: 'No comic series by that name.'},
};

/** Adds "Get …" under a shelf: `input` is its search box, `after` the
 * element to put it after, `kind` books or comics. */
function attachShelfGet({kind, input, after}) {
    const {make, source, none} = KINDS[kind];
    const ask = h('button', {type: 'button', class: 'shelf-get__ask arrow-after'});
    // Once there are results, a heading says they come from outside the library.
    const title = h('h2', {class: 'shelf-get__title meta-label', hidden: true}, `From ${source}`);
    const note = h('p', {class: 'shelf-get__note', 'aria-live': 'polite'});
    const results = h('div', {class: 'row library get-results'});
    const section = h('section', {class: 'shelf-get', hidden: true, 'aria-label': kind === 'books' ? 'Books to get' : 'Comic series to follow'}, ask, title, note, results);
    after.after(section);
    let generation = 0;
    let shownFor = '';

    function update() {
        const q = input.value.trim();
        section.hidden = !q;
        if (q === shownFor) return;
        // A new search: the old results go, and the offer is for this one.
        generation += 1;
        shownFor = '';
        results.replaceChildren();
        note.textContent = '';
        title.hidden = true;
        ask.hidden = false;
        ask.textContent = kind === 'books' ? `Get “${q}”` : `Find “${q}” to follow`;
    }

    async function look() {
        const q = input.value.trim();
        if (!q) return;
        const mine = ++generation;
        shownFor = q;
        ask.hidden = true;
        title.hidden = false;
        note.textContent = '';
        results.replaceChildren(...Array.from({length: 4}, () => h('div', {class: 'col-md-3 mb-3 book-skeleton-wrapper', 'aria-hidden': 'true'}, h('div', {class: 'book-skeleton'}))));
        let data;
        try {
            data = await apiFetch(`/api/get/search/${kind}?q=${encodeURIComponent(q)}`);
        } catch (e) {
            data = {results: [], error: e.message};
        }
        if (mine !== generation) return;  // a newer search has started
        results.replaceChildren(...data.results.map(make));
        note.textContent = data.error || (data.results.length ? (kind === 'books' ? 'Choose a cover to ask for it.' : 'Choose a series to follow it.') : none);
    }

    ask.addEventListener('click', look);
    input.addEventListener('input', update);
    // Enter in the box looks further too, once there's nothing on the shelf.
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !document.querySelector('#library > :not([hidden])')) look(); });
    update();
    return {look};
}

window.attachShelfGet = attachShelfGet;
})();
