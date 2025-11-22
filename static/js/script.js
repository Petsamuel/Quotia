document.addEventListener('DOMContentLoaded', () => {
    // Custom cursor
    const cursor = document.getElementById('cursor');
    if (cursor) {
        document.addEventListener('mousemove', e => {
            cursor.style.left = e.clientX + 'px';
            cursor.style.top = e.clientY + 'px';
        });

        document.querySelectorAll('a, .hover-invert').forEach(el => {
            el.addEventListener('mouseenter', () => {
                cursor.classList.add('hover');
            });
            el.addEventListener('mouseleave', () => {
                cursor.classList.remove('hover');
            });
        });
    }

    // GSAP text reveals
    gsap.registerPlugin(ScrollTrigger);

    gsap.utils.toArray('.reveal').forEach(elem => {
        ScrollTrigger.create({
            trigger: elem,
            start: 'top 80%',
            onEnter: () => elem.classList.add('visible'),
            once: true
        });
    });

    loadQuotes();
});

async function loadQuotes() {
    const quotesContainer = document.getElementById('quotes-container');
    if (!quotesContainer) return;

    try {
        const response = await fetch('/v1/quote');
        const quotes = await response.json();

        quotesContainer.innerHTML = ''; // Clear existing quotes

        quotes.forEach(quote => {
            const quoteEl = document.createElement('div');
            quoteEl.className = 'card p-6 md:p-8 border border-ink border-opacity-10 hover-invert';
            quoteEl.innerHTML = `
                <p class="font-mono text-sm mb-4">"${quote.quote}"</p>
                <h3 class="text-lg font-serif font-bold">${quote.author}</h3>
            `;
            quotesContainer.appendChild(quoteEl);
        });
    } catch (error) {
        console.error('Error loading quotes:', error);
        quotesContainer.innerHTML = '<p>Could not load quotes at this time.</p>';
    }
}
