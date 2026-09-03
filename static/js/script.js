document.addEventListener('DOMContentLoaded', () => {
    initCursor();
    initReveals();
    initCopyButtons();
    initCategoryFilter();
    initShuffle();
    initHeaderContrast();
    loadQuotes();
});

/* The header is fixed and transparent, so ink-coloured links vanish when a dark
   code block scrolls underneath. Rather than hardcoding which sections are dark,
   sample the real background colour behind the header and flip to light when it
   is. That way any future dark surface is handled without touching this code. */
function initHeaderContrast() {
    const header = document.querySelector('header');
    if (!header) return;

    const nav = header.querySelector('nav');
    const logo = header.querySelector('.logo');
    if (!nav && !logo) return;

    const DARK_THRESHOLD = 110; // 0-255 perceived luminance

    function luminanceBehind(element) {
        const rect = element.getBoundingClientRect();
        if (!rect.width) return 255;

        const y = rect.top + rect.height / 2;
        const samples = [rect.left + 2, (rect.left + rect.right) / 2, rect.right - 2];
        let darkest = 255;

        samples.forEach(x => {
            for (const node of document.elementsFromPoint(x, y)) {
                if (header.contains(node)) continue; // ignore the header itself
                const match = window.getComputedStyle(node).backgroundColor
                    .match(/^rgba?\(([^)]+)\)$/);
                if (!match) continue;

                const parts = match[1].split(',').map(parseFloat);
                const alpha = parts.length > 3 ? parts[3] : 1;
                if (alpha < 0.5) continue; // see through to whatever is below

                const luminance = 0.299 * parts[0] + 0.587 * parts[1] + 0.114 * parts[2];
                darkest = Math.min(darkest, luminance);
                break; // first opaque layer wins for this sample
            }
        });

        return darkest;
    }

    let queued = false;
    function update() {
        queued = false;
        if (nav) nav.classList.toggle('is-over-dark', luminanceBehind(nav) < DARK_THRESHOLD);
        if (logo) logo.classList.toggle('is-over-dark', luminanceBehind(logo) < DARK_THRESHOLD);
    }

    function schedule() {
        if (queued) return;
        queued = true;
        requestAnimationFrame(update);
    }

    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    update();
}

function initCopyButtons() {
    document.querySelectorAll('.code-block__copy').forEach(button => {
        button.addEventListener('click', async () => {
            const block = button.closest('.code-block');
            const code = block && block.querySelector('code');
            if (!code) return;

            try {
                await navigator.clipboard.writeText(code.textContent.trim());
                button.textContent = 'Copied';
                button.classList.add('copied');
                setTimeout(() => {
                    button.textContent = 'Copy';
                    button.classList.remove('copied');
                }, 1600);
            } catch (error) {
                console.error('Copy failed:', error);
                button.textContent = 'Failed';
                setTimeout(() => { button.textContent = 'Copy'; }, 1600);
            }
        });
    });
}

function initCursor() {
    const cursor = document.getElementById('cursor');
    if (!cursor) return;

    document.addEventListener('mousemove', e => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
    });

    document.querySelectorAll('a, .hover-invert').forEach(el => {
        el.addEventListener('mouseenter', () => cursor.classList.add('hover'));
        el.addEventListener('mouseleave', () => cursor.classList.remove('hover'));
    });
}

// Dropping .js-anim removes the CSS hidden state outright, so this is the
// escape hatch whenever the animation cannot or should not run.
function revealEverything() {
    document.documentElement.classList.remove('js-anim');
    document.querySelectorAll('.reveal, .reveal-group > *').forEach(el => {
        el.classList.add('visible');
        el.style.opacity = '';
        el.style.transform = '';
    });
}

function playReveal(el) {
    if (el.classList.contains('reveal-group')) {
        gsap.to(el.children, {
            opacity: 1,
            y: 0,
            duration: 0.8,
            ease: 'power3.out',
            stagger: 0.12
        });
        return;
    }

    el.classList.add('visible');
    gsap.to(el, { opacity: 1, y: 0, duration: 0.9, ease: 'expo.out' });
}

function initReveals() {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (prefersReduced || !window.gsap || !('IntersectionObserver' in window)) {
        revealEverything();
        return;
    }

    try {
        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                obs.unobserve(entry.target);
                playReveal(entry.target);
            });
        }, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });

        // Headings and copy wipe upward into view.
        document.querySelectorAll('.reveal').forEach(el => {
            gsap.set(el, { opacity: 0, y: 16 });
            observer.observe(el);
        });

        // Grids of cards rise in sequence rather than all at once.
        document.querySelectorAll('.reveal-group').forEach(group => {
            if (!group.children.length) return;
            gsap.set(group.children, { opacity: 0, y: 28 });
            observer.observe(group);
        });
    } catch (error) {
        console.error('Reveal setup failed:', error);
        revealEverything();
    }
}

function animateQuoteCards(cards) {
    if (!cards.length) return;

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced || !window.gsap) return;

    gsap.fromTo(cards,
        { opacity: 0, y: 28 },
        { opacity: 1, y: 0, duration: 0.7, ease: 'power3.out', stagger: 0.09 }
    );
}

const COPY_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="1"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>`;

const SHARE_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>`;

function quoteToText(quote) {
    return `“${quote.text}” — ${quote.author}`;
}

function closeAllShareMenus() {
    document.querySelectorAll('.share-menu.open').forEach(menu => {
        menu.classList.remove('open');
        const button = menu.previousElementSibling;
        if (button) button.setAttribute('aria-expanded', 'false');
    });
}

document.addEventListener('click', event => {
    if (!event.target.closest('.quote-actions')) closeAllShareMenus();
});

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeAllShareMenus();
});

function shareToPlatform(platform, quote) {
    const text = quoteToText(quote);
    const url = window.location.origin || 'https://quotia.io';
    const urls = {
        x: `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
        whatsapp: `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
        linkedin: `https://www.linkedin.com/feed/?shareActive=true&text=${encodeURIComponent(`${text} ${url}`)}`,
    };
    window.open(urls[platform], '_blank', 'noopener,noreferrer');
}

async function shareNative(quote) {
    try {
        await navigator.share({
            title: 'Quotia',
            text: quoteToText(quote),
            url: window.location.origin || 'https://quotia.io',
        });
    } catch (error) {
        if (error && error.name !== 'AbortError') console.error('Share failed:', error);
    }
}

// Renders the quote onto a square canvas in the site's palette, so the shared
// image is readable on its own without the surrounding page.
async function renderQuoteImage(quote) {
    const SIZE = 1080;
    const PAD = 110;
    const canvas = document.createElement('canvas');
    canvas.width = SIZE;
    canvas.height = SIZE;
    const ctx = canvas.getContext('2d');

    if (document.fonts && document.fonts.ready) {
        try { await document.fonts.ready; } catch (error) { /* fall back to system fonts */ }
    }

    ctx.fillStyle = '#F2F0EA';
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.strokeStyle = '#050505';
    ctx.lineWidth = 2;
    ctx.strokeRect(48, 48, SIZE - 96, SIZE - 96);

    // Fit the quote by stepping the type size down until it fits the text box.
    const maxWidth = SIZE - PAD * 2;
    const maxTextHeight = SIZE - PAD * 2 - 190;
    let fontSize = 62;
    let lines = [];

    for (; fontSize >= 26; fontSize -= 2) {
        ctx.font = `${fontSize}px "Playfair Display", Georgia, serif`;
        lines = [];
        let line = '';
        for (const word of `“${quote.text}”`.split(/\s+/)) {
            const candidate = line ? `${line} ${word}` : word;
            if (ctx.measureText(candidate).width > maxWidth && line) {
                lines.push(line);
                line = word;
            } else {
                line = candidate;
            }
        }
        if (line) lines.push(line);
        if (lines.length * (fontSize * 1.35) <= maxTextHeight) break;
    }

    const lineHeight = fontSize * 1.35;
    let y = PAD + 40 + lineHeight;
    ctx.fillStyle = '#050505';
    ctx.textBaseline = 'alphabetic';
    lines.forEach(l => {
        ctx.fillText(l, PAD, y);
        y += lineHeight;
    });

    ctx.fillStyle = '#FF3333';
    ctx.fillRect(PAD, y + 6, 90, 4);

    ctx.fillStyle = '#050505';
    ctx.font = `bold 40px "Playfair Display", Georgia, serif`;
    ctx.fillText(quote.author, PAD, y + 84);

    drawBrandmark(ctx, PAD, SIZE - PAD + 12);

    if (quote.source) {
        ctx.font = `22px "Space Mono", monospace`;
        ctx.fillStyle = 'rgba(5,5,5,0.45)';
        const attribution = `via ${quote.source}`;
        ctx.fillText(attribution, SIZE - PAD - ctx.measureText(attribution).width, SIZE - PAD + 20);
    }

    return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
}

// Redraws static/assets/logo.svg with canvas primitives rather than loading the
// file — an <img> from disk would taint the canvas and break toBlob().
function drawLogoMark(ctx, cx, cy, radius) {
    const scale = radius / 19.5; // logo.svg outer circle is r=19.5 in a 40x40 box

    ctx.save();
    ctx.strokeStyle = '#050505';
    ctx.lineWidth = Math.max(1, 1 * scale);

    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(cx, cy, 10 * scale, 0, Math.PI * 2);
    ctx.stroke();

    // The accent dot sits at (28,12) in a circle centred on (20,20).
    ctx.fillStyle = '#FF3333';
    ctx.beginPath();
    ctx.arc(cx + 8 * scale, cy - 8 * scale, 2 * scale, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
}

function drawBrandmark(ctx, x, baseline) {
    const radius = 15;
    ctx.save();
    ctx.globalAlpha = 0.6;
    drawLogoMark(ctx, x + radius, baseline - 8, radius);

    ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(5,5,5,0.7)';
    ctx.font = `bold 30px "Playfair Display", Georgia, serif`;
    ctx.fillText('Quotia', x + radius * 2 + 14, baseline);
    ctx.restore();
}

function quoteFileName(quote) {
    const slug = (quote.author || 'quote').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return `quotia-${slug || 'quote'}.png`;
}

async function shareQuoteImage(quote) {
    try {
        const blob = await renderQuoteImage(quote);
        if (!blob) throw new Error('Canvas produced no image');
        const file = new File([blob], quoteFileName(quote), { type: 'image/png' });

        if (navigator.canShare && navigator.canShare({ files: [file] })) {
            await navigator.share({ files: [file], text: quoteToText(quote) });
            return;
        }

        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = file.name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
        if (error && error.name !== 'AbortError') console.error('Image share failed:', error);
    }
}

function buildShareMenu(quote) {
    const menu = document.createElement('div');
    menu.className = 'share-menu';

    const items = [];
    if (navigator.share) items.push(['Share…', () => shareNative(quote)]);
    items.push(
        ['Post on X', () => shareToPlatform('x', quote)],
        ['WhatsApp', () => shareToPlatform('whatsapp', quote)],
        ['LinkedIn', () => shareToPlatform('linkedin', quote)],
        ['Save as image', () => shareQuoteImage(quote)],
    );

    items.forEach(([label, action]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.addEventListener('click', () => {
            closeAllShareMenus();
            action();
        });
        menu.appendChild(button);
    });

    return menu;
}

// Pages seen so far, so shuffling pulls genuinely different quotes rather than
// only reordering the six already on screen. Capped because deeper pages cost
// another upstream request per source.
const MAX_SHUFFLE_PAGE = 5;
let availablePages = 1;

function initCategoryFilter() {
    const select = document.getElementById('category-select');
    if (!select) return;
    select.addEventListener('change', () => {
        availablePages = 1; // page count is per-category
        loadQuotes(select.value);
    });
}

function initShuffle() {
    const button = document.getElementById('shuffle-button');
    if (!button) return;

    button.addEventListener('click', async () => {
        const select = document.getElementById('category-select');
        button.disabled = true;
        button.classList.add('is-loading');
        try {
            await loadQuotes(select ? select.value : '', { shuffle: true });
        } finally {
            button.disabled = false;
            button.classList.remove('is-loading');
        }
    });
}

function shuffled(items) {
    const copy = items.slice();
    for (let i = copy.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
}

// Quotes come from third-party sites, so they are inserted as text nodes rather
// than markup — never build these cards with innerHTML.
function buildQuoteCard(quote) {
    const card = document.createElement('div');
    card.className = 'card quote-card p-6 md:p-8 border border-ink border-opacity-10 hover-invert';

    const text = document.createElement('p');
    text.className = 'font-mono text-sm quote-card__text';
    text.textContent = `“${quote.text}”`;
    text.title = quote.text;

    // Author and actions share the bottom row, so the buttons sit clear of the
    // quote text and every card's controls line up regardless of quote length.
    const footer = document.createElement('div');
    footer.className = 'quote-card__footer';

    const actions = document.createElement('div');
    actions.className = 'quote-actions';

    const copyButton = document.createElement('button');
    copyButton.type = 'button';
    copyButton.className = 'quote-copy';
    copyButton.title = 'Copy quote';
    copyButton.setAttribute('aria-label', `Copy quote by ${quote.author}`);
    copyButton.innerHTML = COPY_ICON;
    copyButton.addEventListener('click', () => copyQuote(copyButton, quote));

    const shareButton = document.createElement('button');
    shareButton.type = 'button';
    shareButton.className = 'quote-share';
    shareButton.title = 'Share quote';
    shareButton.setAttribute('aria-label', `Share quote by ${quote.author}`);
    shareButton.setAttribute('aria-haspopup', 'true');
    shareButton.setAttribute('aria-expanded', 'false');
    shareButton.innerHTML = SHARE_ICON;

    const menu = buildShareMenu(quote);
    shareButton.addEventListener('click', () => {
        const isOpen = menu.classList.contains('open');
        closeAllShareMenus();
        if (!isOpen) {
            menu.classList.add('open');
            shareButton.setAttribute('aria-expanded', 'true');
        }
    });

    actions.appendChild(copyButton);
    actions.appendChild(shareButton);
    actions.appendChild(menu);

    const author = document.createElement('h3');
    author.className = 'text-lg font-serif font-bold quote-card__author';
    author.textContent = quote.author;

    footer.appendChild(author);
    footer.appendChild(actions);

    card.appendChild(text);
    card.appendChild(footer);
    return card;
}

async function copyQuote(button, quote) {
    try {
        await navigator.clipboard.writeText(`“${quote.text}” — ${quote.author}`);
        button.classList.add('copied');
        button.title = 'Copied';
        setTimeout(() => {
            button.classList.remove('copied');
            button.title = 'Copy quote';
        }, 1600);
    } catch (error) {
        console.error('Copy failed:', error);
    }
}

async function loadQuotes(category = '', { shuffle = false } = {}) {
    const quotesContainer = document.getElementById('quotes-container');
    if (!quotesContainer) return;

    const params = new URLSearchParams({ page_size: '6' });
    if (category) params.set('category', category);
    if (shuffle) {
        const depth = Math.max(1, Math.min(availablePages, MAX_SHUFFLE_PAGE));
        params.set('page', String(1 + Math.floor(Math.random() * depth)));
    }

    quotesContainer.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch(`/v1/quote?${params}`);
        const data = await response.json();
        availablePages = data.total_pages || 1;
        const quotes = shuffle ? shuffled(data.quotes || []) : (data.quotes || []);

        quotesContainer.innerHTML = ''; // Clear existing quotes

        if (!quotes.length) {
            const empty = document.createElement('p');
            empty.className = 'font-mono text-sm';
            empty.textContent = 'No quotes found for that category.';
            quotesContainer.appendChild(empty);
            return;
        }

        quotes.forEach(quote => quotesContainer.appendChild(buildQuoteCard(quote)));
        animateQuoteCards(Array.from(quotesContainer.children));
    } catch (error) {
        console.error('Error loading quotes:', error);
        quotesContainer.innerHTML = '';
        const failed = document.createElement('p');
        failed.className = 'font-mono text-sm';
        failed.textContent = 'Could not load quotes at this time.';
        quotesContainer.appendChild(failed);
    } finally {
        quotesContainer.removeAttribute('aria-busy');
    }
}
