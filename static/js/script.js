document.addEventListener('DOMContentLoaded', () => {
    initCursor();
    initReveals();
    initCopyButtons();
    initCategoryFilter();
    loadQuotes();
});

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

function initCategoryFilter() {
    const select = document.getElementById('category-select');
    if (!select) return;
    select.addEventListener('change', () => loadQuotes(select.value));
}

// Quotes come from third-party sites, so they are inserted as text nodes rather
// than markup — never build these cards with innerHTML.
function buildQuoteCard(quote) {
    const card = document.createElement('div');
    card.className = 'card quote-card p-6 md:p-8 border border-ink border-opacity-10 hover-invert';

    const head = document.createElement('div');
    head.className = 'flex justify-between items-start gap-4 mb-4';

    const text = document.createElement('p');
    text.className = 'font-mono text-sm quote-card__text';
    text.textContent = `“${quote.text}”`;
    text.title = quote.text;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'quote-copy';
    button.title = 'Copy quote';
    button.setAttribute('aria-label', `Copy quote by ${quote.author}`);
    button.innerHTML = COPY_ICON;
    button.addEventListener('click', () => copyQuote(button, quote));

    head.appendChild(text);
    head.appendChild(button);

    const author = document.createElement('h3');
    author.className = 'text-lg font-serif font-bold quote-card__author';
    author.textContent = quote.author;

    card.appendChild(head);
    card.appendChild(author);
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

async function loadQuotes(category = '') {
    const quotesContainer = document.getElementById('quotes-container');
    if (!quotesContainer) return;

    const params = new URLSearchParams({ page_size: '6' });
    if (category) params.set('category', category);

    quotesContainer.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch(`/v1/quote?${params}`);
        const data = await response.json();
        const quotes = data.quotes || [];

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
