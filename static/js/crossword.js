/* Playable crossword. Consumes GET /v1/crossword and renders a solvable grid. */

const BLOCK = '#';

const STORAGE_KEY = 'quotia.crossword.v1';

const state = {
    puzzle: null,
    size: 0,
    inputs: new Map(),        // "r,c" -> <input>
    acrossAt: new Map(),      // "r,c" -> across entry containing this cell
    downAt: new Map(),        // "r,c" -> down entry containing this cell
    direction: 'across',
    cursor: null,             // "r,c"
    revealed: false,
};

const key = (r, c) => `${r},${c}`;
const el = id => document.getElementById(id);

/* ---- Progress persistence -------------------------------------------------
   Saving letters alone would be pointless: without the puzzle identity a
   refresh generates a different grid and the letters would land on the wrong
   squares. So the identity is stored alongside them and letters are only
   restored when it matches exactly. localStorage is wrapped throughout because
   it throws in private mode and when the quota is full. */

function puzzleId(p) {
    if (!p) return '';
    const scope = p.date ? `daily:${p.date}` : `seed:${p.seed}`;
    return `${scope}|${p.size}|${p.category || 'mixed'}`;
}

function readSaved() {
    try {
        return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    } catch (error) {
        return null;
    }
}

function saveProgress() {
    if (!state.puzzle) return;
    const letters = {};
    state.inputs.forEach((input, k) => {
        if (input.value) letters[k] = input.value;
    });
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
            id: puzzleId(state.puzzle),
            seed: state.puzzle.seed,
            size: state.puzzle.size,
            category: state.puzzle.category || '',
            daily: Boolean(state.puzzle.date),
            revealed: state.revealed,
            letters,
        }));
    } catch (error) {
        /* Storage unavailable or full — solving still works, it just won't persist. */
    }
}

function restoreProgress() {
    const saved = readSaved();
    if (!saved || saved.id !== puzzleId(state.puzzle)) return 0;

    let restored = 0;
    Object.entries(saved.letters || {}).forEach(([k, letter]) => {
        const input = state.inputs.get(k);
        if (!input) return;
        input.value = letter;
        if (saved.revealed) input.parentElement.classList.add('is-revealed');
        restored += 1;
    });
    state.revealed = Boolean(saved.revealed);
    return restored;
}

function entryCells(entry) {
    const cells = [];
    for (let i = 0; i < entry.length; i += 1) {
        cells.push(entry.direction === 'across'
            ? key(entry.row, entry.col + i)
            : key(entry.row + i, entry.col));
    }
    return cells;
}

function currentEntry() {
    if (!state.cursor) return null;
    const map = state.direction === 'across' ? state.acrossAt : state.downAt;
    return map.get(state.cursor) || null;
}

function buildGrid() {
    const { puzzle } = state;
    const grid = el('cw-grid');
    grid.innerHTML = '';
    grid.style.setProperty('--cw-size', state.size);
    state.inputs.clear();
    state.acrossAt.clear();
    state.downAt.clear();

    // Tag every cell with the entries that run through it, and note clue numbers.
    const numbers = new Map();
    puzzle.across.forEach(e => {
        const entry = { ...e, direction: 'across' };
        entryCells(entry).forEach(k => state.acrossAt.set(k, entry));
        numbers.set(key(e.row, e.col), e.number);
    });
    puzzle.down.forEach(e => {
        const entry = { ...e, direction: 'down' };
        entryCells(entry).forEach(k => state.downAt.set(k, entry));
        numbers.set(key(e.row, e.col), e.number);
    });

    for (let r = 0; r < state.size; r += 1) {
        for (let c = 0; c < state.size; c += 1) {
            const cell = document.createElement('div');
            const k = key(r, c);

            if (puzzle.puzzle[r][c] === BLOCK) {
                cell.className = 'cw-cell cw-cell--block';
                grid.appendChild(cell);
                continue;
            }

            cell.className = 'cw-cell';
            if (numbers.has(k)) {
                const num = document.createElement('span');
                num.className = 'cw-cell__number';
                num.textContent = numbers.get(k);
                cell.appendChild(num);
            }

            const input = document.createElement('input');
            input.className = 'cw-cell__input';
            input.type = 'text';
            input.maxLength = 1;
            input.autocomplete = 'off';
            input.autocapitalize = 'characters';
            input.dataset.row = r;
            input.dataset.col = c;
            input.setAttribute('aria-label', `Row ${r + 1}, column ${c + 1}`);

            input.addEventListener('focus', () => setCursor(k, false));
            input.addEventListener('click', () => {
                // Clicking the cell you're already on flips direction, matching
                // how every crossword app behaves.
                if (state.cursor === k) toggleDirection();
                else setCursor(k, false);
            });
            input.addEventListener('input', onInput);
            input.addEventListener('keydown', onKeyDown);

            cell.appendChild(input);
            state.inputs.set(k, input);
            grid.appendChild(cell);
        }
    }
}

function buildClueLists() {
    [['cw-across', state.puzzle.across, 'across'], ['cw-down', state.puzzle.down, 'down']]
        .forEach(([listId, entries, direction]) => {
            const list = el(listId);
            list.innerHTML = '';
            entries.forEach(e => {
                const item = document.createElement('li');
                item.className = 'cw-clue';
                item.dataset.number = e.number;
                item.dataset.direction = direction;
                item.innerHTML = `<span class="cw-clue__num">${e.number}</span><span>${e.clue}</span>`;
                item.addEventListener('click', () => {
                    state.direction = direction;
                    setCursor(key(e.row, e.col), true);
                });
                list.appendChild(item);
            });
        });
}

function setCursor(k, focus = true) {
    if (!state.inputs.has(k)) return;
    state.cursor = k;

    // Keep the direction only if a word actually runs that way through the cell.
    const map = state.direction === 'across' ? state.acrossAt : state.downAt;
    if (!map.has(k)) state.direction = state.direction === 'across' ? 'down' : 'across';

    if (focus) state.inputs.get(k).focus();
    render();
}

function toggleDirection() {
    const other = state.direction === 'across' ? 'down' : 'across';
    const map = other === 'across' ? state.acrossAt : state.downAt;
    if (map.has(state.cursor)) {
        state.direction = other;
        render();
    }
}

function render() {
    const entry = currentEntry();
    const active = new Set(entry ? entryCells(entry) : []);

    state.inputs.forEach((input, k) => {
        input.parentElement.classList.toggle('is-active-word', active.has(k));
        input.parentElement.classList.toggle('is-cursor', k === state.cursor);
    });

    const bar = el('cw-current-clue');
    if (entry) {
        bar.textContent = `${entry.number} ${state.direction === 'across' ? 'Across' : 'Down'} — ${entry.clue}`;
    } else {
        bar.textContent = 'Pick a square to start.';
    }

    document.querySelectorAll('.cw-clue').forEach(item => {
        const isCurrent = entry
            && Number(item.dataset.number) === entry.number
            && item.dataset.direction === state.direction;
        item.classList.toggle('is-current', Boolean(isCurrent));
    });
}

function step(delta) {
    const entry = currentEntry();
    if (!entry) return;
    const cells = entryCells(entry);
    const index = cells.indexOf(state.cursor);
    const next = cells[index + delta];
    if (next) setCursor(next, true);
}

function onInput(event) {
    const input = event.target;
    const value = input.value.replace(/[^a-zA-Z]/g, '').toUpperCase();
    input.value = value.slice(-1);
    input.parentElement.classList.remove('is-wrong');
    saveProgress();
    if (input.value) {
        step(1);
        checkComplete();
    }
}

function onKeyDown(event) {
    const r = Number(event.target.dataset.row);
    const c = Number(event.target.dataset.col);

    const moves = {
        ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
    };

    if (moves[event.key]) {
        event.preventDefault();
        const [dr, dc] = moves[event.key];
        const wanted = dr ? 'down' : 'across';
        if (state.direction !== wanted) {
            const map = wanted === 'across' ? state.acrossAt : state.downAt;
            if (map.has(key(r, c))) {
                state.direction = wanted;
                render();
                return;
            }
        }
        for (let i = 1; i < state.size; i += 1) {
            const k = key(r + dr * i, c + dc * i);
            if (state.inputs.has(k)) { setCursor(k, true); return; }
        }
        return;
    }

    if (event.key === ' ' || event.key === 'Tab') {
        event.preventDefault();
        toggleDirection();
        return;
    }

    if (event.key === 'Backspace') {
        event.preventDefault();
        const input = event.target;
        input.parentElement.classList.remove('is-wrong');
        if (input.value) input.value = '';
        else step(-1);
        saveProgress();
    }
}

function checkAnswers() {
    let wrong = 0;
    let blank = 0;
    state.inputs.forEach((input, k) => {
        const [r, c] = k.split(',').map(Number);
        const expected = state.puzzle.solution[r][c];
        input.parentElement.classList.remove('is-wrong');
        if (!input.value) { blank += 1; return; }
        if (input.value !== expected) {
            input.parentElement.classList.add('is-wrong');
            wrong += 1;
        }
    });
    setStatus(wrong === 0 && blank === 0
        ? 'Solved. Every square is correct.'
        : `${wrong} wrong, ${blank} still empty.`);
}

function revealAll() {
    state.inputs.forEach((input, k) => {
        const [r, c] = k.split(',').map(Number);
        input.value = state.puzzle.solution[r][c];
        input.parentElement.classList.remove('is-wrong');
        input.parentElement.classList.add('is-revealed');
    });
    state.revealed = true;
    saveProgress();
    setStatus('Solution revealed.');
}

function clearGrid() {
    state.inputs.forEach(input => {
        input.value = '';
        input.parentElement.classList.remove('is-wrong', 'is-revealed');
    });
    state.revealed = false;
    saveProgress();
    setStatus('');
}

function checkComplete() {
    let complete = true;
    state.inputs.forEach((input, k) => {
        const [r, c] = k.split(',').map(Number);
        if (input.value !== state.puzzle.solution[r][c]) complete = false;
    });
    if (complete) setStatus('Solved. Nice one.');
}

function setStatus(message) {
    el('cw-status').textContent = message;
}

async function loadPuzzle({ category, size, seed, daily = false } = {}) {
    const grid = el('cw-grid');
    const button = el(daily ? 'cw-daily' : 'cw-new');
    button.disabled = true;
    button.classList.add('is-loading');
    setStatus('');

    const params = new URLSearchParams();
    if (size) params.set('size', size);
    if (!daily) {
        if (category) params.set('category', category);
        if (seed) params.set('seed', seed);
    }

    try {
        const path = daily ? '/v1/crossword/daily' : '/v1/crossword';
        const response = await fetch(`${path}?${params}`);
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        const data = await response.json();

        state.puzzle = data;
        state.size = data.size;
        state.direction = 'across';
        state.cursor = null;
        state.revealed = false;

        buildGrid();
        buildClueLists();

        const restored = restoreProgress();
        if (restored) {
            setStatus(`Picked up where you left off — ${restored} letter${restored === 1 ? '' : 's'} restored.`);
        } else {
            // Record the new puzzle's identity so the next refresh returns it.
            saveProgress();
        }

        const first = data.across[0] || data.down[0];
        if (first) {
            state.direction = data.across[0] ? 'across' : 'down';
            setCursor(key(first.row, first.col), false);
        }
        render();

        el('cw-seed').textContent = data.date ? `daily · ${data.date}` : `seed ${data.seed}`;
        el('cw-meta').textContent = `${data.word_count} words · ${data.size}×${data.size}`
            + (data.category ? ` · ${data.category}` : '');
        if (data.category && el('cw-category').value !== data.category) {
            // The daily puzzle picks its own theme; reflect it in the control.
            el('cw-category').value = data.category;
        }
    } catch (error) {
        console.error('Crossword load failed:', error);
        grid.innerHTML = '';
        setStatus('Could not load a puzzle. Try again.');
    } finally {
        button.disabled = false;
        button.classList.remove('is-loading');
    }
}

function currentOptions() {
    return {
        category: el('cw-category').value,
        size: el('cw-size').value,
    };
}

document.addEventListener('DOMContentLoaded', () => {
    if (!el('cw-grid')) return;

    el('cw-new').addEventListener('click', () => loadPuzzle(currentOptions()));
    el('cw-daily').addEventListener('click', () => loadPuzzle({ ...currentOptions(), daily: true }));
    el('cw-category').addEventListener('change', () => loadPuzzle(currentOptions()));
    el('cw-size').addEventListener('change', () => loadPuzzle(currentOptions()));
    el('cw-check').addEventListener('click', checkAnswers);
    el('cw-reveal').addEventListener('click', revealAll);
    el('cw-clear').addEventListener('click', clearGrid);

    el('cw-prev').addEventListener('click', () => moveEntry(-1));
    el('cw-next').addEventListener('click', () => moveEntry(1));

    // Precedence: an explicit URL seed (a shared puzzle) beats saved progress,
    // which beats a fresh random puzzle.
    const url = new URLSearchParams(window.location.search);
    const urlSeed = url.get('seed');
    const urlCategory = url.get('category');

    if (urlSeed) {
        if (urlCategory) el('cw-category').value = urlCategory;
        loadPuzzle({ ...currentOptions(), seed: urlSeed });
        return;
    }

    const saved = readSaved();
    if (saved && saved.size) {
        // Reload the exact puzzle they were solving, not a new random one.
        el('cw-size').value = String(saved.size);
        el('cw-category').value = saved.category || '';
        loadPuzzle(saved.daily
            ? { size: saved.size, daily: true }
            : { category: saved.category || '', size: saved.size, seed: saved.seed });
        return;
    }

    loadPuzzle(currentOptions());
});

function moveEntry(delta) {
    const entry = currentEntry();
    if (!entry) return;
    const list = state.direction === 'across' ? state.puzzle.across : state.puzzle.down;
    const index = list.findIndex(e => e.number === entry.number);
    const next = list[(index + delta + list.length) % list.length];
    if (next) setCursor(key(next.row, next.col), true);
}
