const CLIP_HIDDEN = 'polygon(0 100%, 100% 100%, 100% 100%, 0 100%)';
const CLIP_SHOWN = 'polygon(0 0, 100% 0, 100% 100%, 0 100%)';

document.addEventListener('DOMContentLoaded', () => {
    initCursor();
    initReveals();
    initCopyButtons();
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
    document.querySelectorAll('.reveal').forEach(el => el.classList.add('visible'));
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

    gsap.to(el, {
        clipPath: CLIP_SHOWN,
        y: 0,
        duration: 1,
        ease: 'expo.out',
        onComplete: () => el.classList.add('visible')
    });
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
            gsap.set(el, { clipPath: CLIP_HIDDEN, y: 12 });
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

async function loadQuotes() {
    const quotesContainer = document.getElementById('quotes-container');
    if (!quotesContainer) return;

    try {
        const response = await fetch('/v1/quote?page_size=6');
        const data = await response.json();
        const quotes = data.quotes || [];

        quotesContainer.innerHTML = ''; // Clear existing quotes

        quotes.forEach(quote => {
            const quoteEl = document.createElement('div');
            quoteEl.className = 'card p-6 md:p-8 border border-ink border-opacity-10 hover-invert';
            quoteEl.innerHTML = `
                <p class="font-mono text-sm mb-4">"${quote.text}"</p>
                <h3 class="text-lg font-serif font-bold">${quote.author}</h3>
            `;
            quotesContainer.appendChild(quoteEl);
        });

        animateQuoteCards(Array.from(quotesContainer.children));
    } catch (error) {
        console.error('Error loading quotes:', error);
        quotesContainer.innerHTML = '<p>Could not load quotes at this time.</p>';
    }
}
