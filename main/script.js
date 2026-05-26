/* ============================================================
   THE ASSORTMENT — Main Script
   Handles the playlist grid, iPod logic, audio playback,
   and dynamic UI toggles.
   ============================================================ */

// ── GLOBAL STATE ───────────────────────────────────────────
let displayOrder     = [];   // Array of entry IDs in current sorting order
let currentIndex     = 0;    // Which entry is currently active in the iPod
let currentDisplayed = 0;    // Tracks pagination load count
let audioPlayer      = null; // The active HTML5 Audio object
let isPlaying        = false;// Tracks if audio is currently playing
let progressTimer    = null; // Interval timer for the audio progress bar
let sortMode         = 'chrono'; // 'chrono', 'recent', 'shuffle'
let showCredits      = false;// Tracks which view the iPod screen is showing
let sb               = null; // Supabase client (set in initSupabase)
let activeTakeEntry  = null; // The entry the open "your take" modal refers to

const PENDING_KEY = 'assortment_pending_take'; // survives the magic-link redirect

// ── INITIALIZATION ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initSupabase();
  buildPlaylist();
  bindControls();
  setupToggles();
  setupWheelVolume();
});

// ── PLAYLIST GENERATION ────────────────────────────────────
function buildPlaylist() {
  const container = document.getElementById('playlist');
  const countEl   = document.getElementById('entry-count');

  // 1. Establish the order of items based on sorting preference
  if (sortMode === 'chrono') {
    // Oldest first
    const sortedEntries = [...ENTRIES].sort((a, b) => {
      const dateA = new Date(a.date).getTime();
      const dateB = new Date(b.date).getTime();
      if (dateA !== dateB) return dateA - dateB;
      return a.placeholderColor.localeCompare(b.placeholderColor);
    });
    displayOrder = sortedEntries.map(e => e.id);
  } else if (sortMode === 'recent') {
    // Newest first
    const sortedEntries = [...ENTRIES].sort((a, b) => {
      const dateA = new Date(a.date).getTime();
      const dateB = new Date(b.date).getTime();
      if (dateA !== dateB) return dateB - dateA;
      return b.placeholderColor.localeCompare(a.placeholderColor);
    });
    displayOrder = sortedEntries.map(e => e.id);
  } else {
    // Shuffle
    displayOrder = ENTRIES.map(e => e.id);
    shuffleArray(displayOrder);
  }

  // Clear existing items and reset counts
  container.innerHTML = '';
  currentDisplayed = 0;
  
  // Render the initial batch of 8
  loadMoreEntries(8);

  countEl.textContent = `${ENTRIES.length} entries`;
}

function loadMoreEntries(count) {
  const container = document.getElementById('playlist');
  const slice = displayOrder.slice(currentDisplayed, currentDisplayed + count);
  
  slice.forEach(id => {
    const entry = ENTRIES.find(e => e.id === id);
    if (!entry) return;

    let thumbHTML;
    if (entry.thumbnail) {
      thumbHTML = `<img src="${entry.thumbnail}" alt="thumbnail" loading="lazy">`;
    } else if (entry.media && entry.mediaType === 'image') {
      thumbHTML = `<img src="${entry.media}" alt="thumbnail" loading="lazy">`;
    } else {
      thumbHTML = `<div style="background:${entry.placeholderColor}; width:100%; height:100%;"></div>`;
    }

    const card = document.createElement('div');
    card.className = 'entry-card';
    card.dataset.id = entry.id;

    // Use audioLabel instead of audioSource for the card UI
    card.innerHTML = `
      <div class="entry-thumb">${thumbHTML}</div>
      <div class="entry-info">
        <div class="entry-id">${entry.placeholderColor}</div>
        <div class="entry-audio">${escapeHTML(entry.audioLabel || '—')}</div>
        <div class="entry-date">${formatDate(entry.date)}</div>
      </div>
    `;

    card.addEventListener('click', () => openEntry(id));
    container.appendChild(card);
  });

  currentDisplayed += slice.length;

  // Toggle "Load More" button visibility
  const btnLoadMore = document.getElementById('btn-load-more');
  if (currentDisplayed >= displayOrder.length) {
    btnLoadMore.classList.add('hidden');
  } else {
    btnLoadMore.classList.remove('hidden');
  }
}

// ── UI TOGGLES ─────────────────────────────────────────────
function setupToggles() {
  const togglePairs = [
    { btn: 'about-toggle',      sec: 'about-section' },
    { btn: 'origin-toggle',     sec: 'origin-section' },
    { btn: 'take-nav-toggle',   sec: 'take-nav-section' },
    { btn: 'disclaimer-toggle', sec: 'disclaimer-section' }
  ];

  togglePairs.forEach(pair => {
    const btnEl = document.getElementById(pair.btn);
    const secEl = document.getElementById(pair.sec);
    
    if (btnEl && secEl) {
      btnEl.addEventListener('click', () => {
        const isOpen = secEl.classList.contains('open');
        
        togglePairs.forEach(p => {
          document.getElementById(p.sec).classList.remove('open');
          const otherBtn = document.getElementById(p.btn);
          if (otherBtn) otherBtn.textContent = otherBtn.textContent.replace('↑', '↓');
        });
        
        if (!isOpen) {
          secEl.classList.add('open');
          btnEl.textContent = btnEl.textContent.replace('↓', '↑');
        }
      });
    }
  });
}

// ── iPOD LOGIC ─────────────────────────────────────────────

function openEntry(id) {
  currentIndex = displayOrder.indexOf(id);
  showCredits = false;
  document.getElementById('view-main').classList.remove('hidden');
  document.getElementById('view-credits').classList.add('hidden');
  
  loadEntry(id);
  
  document.getElementById('overlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function loadEntry(id) {
  const entry = ENTRIES.find(e => e.id === id);
  if (!entry) return;

  stopAudio();

  // Populate UI text fields using Hex Code as the primary identifier
  document.getElementById('screen-id').textContent    = entry.placeholderColor;
  document.getElementById('screen-audio').textContent = entry.audioLabel || '—';
  document.getElementById('screen-date').textContent  = formatDate(entry.date);
  document.getElementById('screen-pos').textContent   = `${currentIndex + 1} / ${displayOrder.length}`;
  
  // Render Credits Panel (Checking for URLs)
  document.getElementById('cred-media').innerHTML = formatCredit(entry.mediaSource);
  document.getElementById('cred-label').textContent = entry.audioLabel || '—';
  document.getElementById('cred-audio').innerHTML = formatCredit(entry.audioSource);

  // Load the visual media into the screen area
  const mediaEl = document.getElementById('screen-media');
  
  if (entry.mediaType === 'video' && entry.media) {
    mediaEl.innerHTML = `<video class="screen-media-fg" src="${entry.media}" autoplay muted loop playsinline></video>`;
  } else if (entry.mediaType === 'image' && entry.media) {
    mediaEl.innerHTML = `<img class="screen-media-fg" src="${entry.media}" alt="media" decoding="async">`;
  } else {
    mediaEl.innerHTML = `<div style="background:${entry.placeholderColor}; width:100%; height:100%; position:relative; z-index:1;"></div>`;
  }

  if (entry.audio) {
    // Fetch only the clip's time range when trim points exist, so the browser
    // requests a byte range from the CDN instead of buffering the whole file.
    const start   = entry.audioStart || 0;
    const trimEnd = entry.audioEnd || null;
    const frag    = trimEnd !== null ? `#t=${start},${trimEnd}`
                  : start > 0        ? `#t=${start}`
                  : '';

    audioPlayer = new Audio();
    audioPlayer.preload = 'metadata';
    audioPlayer.volume = 0.75; // leaves headroom so the wheel can go both up and down
    audioPlayer.src = entry.audio + frag;

    audioPlayer.addEventListener('ended', () => {
      isPlaying = false;
      document.getElementById('w-play').textContent = '▶\uFE0E';
      clearInterval(progressTimer);
    });

    playAudio();
  }

  // Quietly prefetch the NEXT entry's media so sequential ▼ navigation is instant.
  prefetchNextAudio();
  prefetchNextMedia();
}

// Warms the CDN/browser cache for the next entry's audio without playing it.
let prefetchEl = null;
function prefetchNextAudio() {
  const nextId = displayOrder[currentIndex + 1];
  if (nextId === undefined) return;
  const nextEntry = ENTRIES.find(e => e.id === nextId);
  if (!nextEntry || !nextEntry.audio) return;

  prefetchEl = new Audio();
  prefetchEl.preload = 'metadata';
  const s = nextEntry.audioStart || 0;
  prefetchEl.src = nextEntry.audio + (s > 0 ? `#t=${s}` : '');
}

// Warms the cache for the next entry's image (and the one after) so the
// visual appears instantly on ▼, the same way audio now does.
let prefetchImgs = [];
function prefetchNextMedia() {
  prefetchImgs = []; // drop references so old ones can be GC'd
  [1, 2].forEach(offset => {
    const nextId = displayOrder[currentIndex + offset];
    if (nextId === undefined) return;
    const nextEntry = ENTRIES.find(e => e.id === nextId);
    if (!nextEntry) return;
    // Only images prefetch cleanly via Image(); videos stream on demand.
    const url = nextEntry.mediaType === 'image' ? nextEntry.media : nextEntry.thumbnail;
    if (!url) return;
    const img = new Image();
    img.src = url;
    prefetchImgs.push(img);
  });
}

function closeEntry() {
  stopAudio();
  document.getElementById('overlay').classList.add('hidden');
  document.getElementById('take-modal').classList.add('hidden');
  document.body.style.overflow = ''; 
}

function toggleCredits() {
  showCredits = !showCredits;
  document.getElementById('view-main').classList.toggle('hidden', showCredits);
  document.getElementById('view-credits').classList.toggle('hidden', !showCredits);
}


// ── AUDIO CONTROLS ─────────────────────────────────────────

function playAudio() {
  if (!audioPlayer) return;
  
  const entry = ENTRIES.find(e => e.id === displayOrder[currentIndex]);
  const start = entry?.audioStart || 0;
  const trimEnd = entry?.audioEnd || null;
  
  if (audioPlayer.ended || (trimEnd !== null && audioPlayer.currentTime >= trimEnd)) {
    audioPlayer.currentTime = start;
  } else if (audioPlayer.currentTime < start - 0.2) {
    audioPlayer.currentTime = start;
  }

  audioPlayer.play().catch(err => console.log("Autoplay blocked by browser"));
  isPlaying = true;
  document.getElementById('w-play').textContent = '❚❚\uFE0E'; 
  startProgressTimer();
}

function stopAudio() {
  if (audioPlayer) {
    audioPlayer.pause();
    audioPlayer.src = ''; 
    audioPlayer = null;
  }
  isPlaying = false;
  clearInterval(progressTimer);
  document.getElementById('w-play').textContent = '▶\uFE0E';
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('progress-time').textContent = '0:00';
}

function startProgressTimer() {
  clearInterval(progressTimer);
  
  progressTimer = setInterval(() => {
    if (!audioPlayer || !audioPlayer.duration) return;

    const entry   = ENTRIES.find(e => e.id === displayOrder[currentIndex]);
    const start   = entry?.audioStart || 0;
    const trimEnd = entry?.audioEnd || null;
    
    const totalDuration = trimEnd !== null ? (trimEnd - start) : audioPlayer.duration;
    const elapsed = Math.max(0, audioPlayer.currentTime - start);
    
    let pct = (elapsed / totalDuration) * 100;
    if (pct > 100) pct = 100;

    document.getElementById('progress-fill').style.width = `${pct}%`;
    document.getElementById('progress-time').textContent = formatTime(elapsed);

    if (trimEnd !== null && audioPlayer.currentTime >= trimEnd) {
      audioPlayer.pause();
      isPlaying = false;
      document.getElementById('w-play').textContent = '▶\uFE0E';
      clearInterval(progressTimer);
    }
  }, 250); 
}

// ── WHEEL VOLUME CONTROL ───────────────────────────────────

function setupWheelVolume() {
  const wheel = document.querySelector('.wheel');
  let isDragging = false;
  let lastAngle = 0;
  let volTimeout = null;
  let vol = 0.75; // tracked separately so we don't lose precision to clamping

  function getAngle(e) {
    const rect = wheel.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return Math.atan2(clientY - centerY, clientX - centerX);
  }

  function onStart(e) {
    isDragging = true;
    lastAngle = getAngle(e);
    // sync our tracker to the player's current volume on grab
    if (audioPlayer) vol = audioPlayer.volume;
  }

  function onMove(e) {
    if (!isDragging || !audioPlayer) return;
    e.preventDefault(); 
    
    const currentAngle = getAngle(e);
    let diff = currentAngle - lastAngle;
    
    // Normalize angular wrapping (crossing the ±π axis on the left of the wheel)
    if (diff > Math.PI) diff -= 2 * Math.PI;
    if (diff < -Math.PI) diff += 2 * Math.PI;

    // Ignore the huge jump that happens right at the wrap boundary
    if (Math.abs(diff) > 1.5) { lastAngle = currentAngle; return; }
    
    if (Math.abs(diff) > 0.03) { // threshold prevents jitter
      // Clockwise (positive diff) = louder, anticlockwise = softer.
      vol = Math.max(0, Math.min(1, vol + diff * 0.4));
      audioPlayer.volume = vol;
      lastAngle = currentAngle;
      showVolumeIndicator(vol);
    }
  }

  function onEnd() {
    isDragging = false;
  }

  function showVolumeIndicator(vol) {
    const ind = document.getElementById('volume-indicator');
    ind.textContent = `VOL ${Math.round(vol * 100)}%`;
    ind.classList.remove('hidden', 'fade-out');
    
    clearTimeout(volTimeout);
    volTimeout = setTimeout(() => {
      ind.classList.add('fade-out');
      setTimeout(() => {
        if(ind.classList.contains('fade-out')) ind.classList.add('hidden');
      }, 400); 
    }, 1500);
  }

  // Mouse Listeners
  wheel.addEventListener('mousedown', onStart);
  document.addEventListener('mousemove', onMove, { passive: false });
  document.addEventListener('mouseup', onEnd);
  
  // Touch Listeners — bound to the WHEEL itself (not document) so the browser
  // routes the gesture here rather than treating it as a page scroll. The
  // wheel also has `touch-action: none` in CSS, which is what actually lets
  // preventDefault work and stops the page from scrolling under the finger.
  let touchStartX = 0, touchStartY = 0, touchMoved = false;

  wheel.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
    touchMoved = false;
    onStart(e);
  }, { passive: false });

  wheel.addEventListener('touchmove', (e) => {
    if (!isDragging) return;
    const t = e.touches[0];
    // Only engage the volume drag after a real movement, so a stationary
    // tap on a button isn't hijacked.
    if (!touchMoved) {
      const dx = Math.abs(t.clientX - touchStartX);
      const dy = Math.abs(t.clientY - touchStartY);
      if (dx < 6 && dy < 6) return;
      touchMoved = true;
    }
    onMove(e);
  }, { passive: false });

  wheel.addEventListener('touchend', onEnd);
  wheel.addEventListener('touchcancel', onEnd);
}

// ── EVENT BINDINGS (Buttons, Keystrokes, Scrubbing) ────────

function bindControls() {

  // Sorting
  document.getElementById('btn-chrono').addEventListener('click', () => setSortMode('chrono'));
  document.getElementById('btn-recent').addEventListener('click', () => setSortMode('recent'));
  document.getElementById('btn-shuffle').addEventListener('click', () => setSortMode('shuffle'));

  function setSortMode(mode) {
    sortMode = mode;
    document.getElementById('btn-chrono').classList.toggle('active', mode === 'chrono');
    document.getElementById('btn-recent').classList.toggle('active', mode === 'recent');
    document.getElementById('btn-shuffle').classList.toggle('active', mode === 'shuffle');
    buildPlaylist();
  }

  // Load More Button
  document.getElementById('btn-load-more').addEventListener('click', () => loadMoreEntries(16));

  // iPod Navigation (Click Wheel)
  document.getElementById('w-next').addEventListener('click', () => {
    currentIndex = (currentIndex + 1) % displayOrder.length;
    loadEntry(displayOrder[currentIndex]);
  });

  document.getElementById('w-prev').addEventListener('click', () => {
    currentIndex = (currentIndex - 1 + displayOrder.length) % displayOrder.length;
    loadEntry(displayOrder[currentIndex]);
  });

  document.getElementById('w-play').addEventListener('click', () => {
    if (isPlaying) {
      audioPlayer.pause();
      isPlaying = false;
      document.getElementById('w-play').textContent = '▶\uFE0E';
    } else {
      playAudio();
    }
  });

  document.getElementById('w-close').addEventListener('click', closeEntry);
  document.getElementById('w-credits').addEventListener('click', toggleCredits);

  // Click the dark backdrop (outside the iPod) to close — common expectation.
  document.getElementById('overlay').addEventListener('click', (e) => {
    if (e.target.id === 'overlay') closeEntry();
  });

  // Progress Bar Scrubbing 
  const progressTrack = document.querySelector('.progress-track');
  progressTrack.addEventListener('mousedown', (e) => {
    if (!audioPlayer || !audioPlayer.duration) return;

    const scrub = (event) => {
      const rect = progressTrack.getBoundingClientRect();
      let clickX = event.clientX - rect.left;
      clickX = Math.max(0, Math.min(clickX, rect.width));
      const pct = clickX / rect.width;

      const entry = ENTRIES.find(e => e.id === displayOrder[currentIndex]);
      const start = entry?.audioStart || 0;
      const end = entry?.audioEnd || audioPlayer.duration;
      const totalDuration = end - start;

      audioPlayer.currentTime = start + (pct * totalDuration);

      document.getElementById('progress-fill').style.width = `${pct * 100}%`;
      document.getElementById('progress-time').textContent = formatTime(pct * totalDuration);
    };

    scrub(e);

    const onMouseMove = (event) => scrub(event);
    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      if (!isPlaying) playAudio(); 
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });

  // "Your Take" — open the modal (no login needed just to write)
  document.getElementById('btn-take').addEventListener('click', () => {
    const entry = ENTRIES.find(e => e.id === displayOrder[currentIndex]);
    if (!entry) return;
    openTakeModal(entry);
  });

  // Save — logged in: write straight to Supabase. Logged out: ask for email.
  document.getElementById('take-save').addEventListener('click', async () => {
    const text = document.getElementById('take-text').value.trim();
    if (!text) { showTakeStatus('write something first.'); return; }
    if (!sb)   { showTakeStatus('saving isn\u2019t set up yet (check config.js).'); return; }

    showTakeStatus('checking\u2026');
    const { data: { session } } = await sb.auth.getSession();
    if (session) {
      await saveTake(session, text);
    } else {
      showEmailStep();
    }
  });

  // Send magic link (email step)
  document.getElementById('take-send-link').addEventListener('click', async () => {
    const email = document.getElementById('take-email').value.trim();
    const name  = document.getElementById('take-name').value.trim();
    const text  = document.getElementById('take-text').value.trim();

    if (!email || !email.includes('@')) { showTakeStatus('enter a valid email.'); return; }
    if (!text) { showTakeStatus('write something first.'); return; }
    if (!sb)   { showTakeStatus('saving isn\u2019t set up yet (check config.js).'); return; }

    // Stash the take so it survives the magic-link round-trip
    localStorage.setItem(PENDING_KEY, JSON.stringify({
      entry_id:     Number(activeTakeEntry.id),
      take_text:    text,
      display_name: name || null,
      color:        activeTakeEntry.placeholderColor
    }));

    showTakeStatus('sending\u2026');
    const { error } = await sb.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin + window.location.pathname }
    });

    if (error) {
      console.error(error);
      showTakeStatus('couldn\u2019t send the link \u2014 try again.');
    } else {
      showTakeStatus('check your inbox \uD83D\uDCEC click the link and your take saves itself.');
    }
  });

  // Back (email step → write step)
  document.getElementById('take-back').addEventListener('click', () => {
    resetTakeModalToWrite();
    hideTakeStatus();
  });

  // Cancel — close the modal
  document.getElementById('take-cancel').addEventListener('click', () => {
    document.getElementById('take-modal').classList.add('hidden');
  });

  // Click the take-modal backdrop (outside the box) to close it.
  document.getElementById('take-modal').addEventListener('click', (e) => {
    if (e.target.id === 'take-modal') {
      document.getElementById('take-modal').classList.add('hidden');
    }
  });

  // "see your previous takes" toggle
  document.getElementById('take-prev-toggle').addEventListener('click', togglePreviousTakes);

  // ── KEYBOARD SHORTCUTS ──
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
    if (document.getElementById('overlay').classList.contains('hidden')) return;

    switch (e.key) {
      case 'Escape':
        closeEntry();
        break;
      case 'ArrowDown':
        e.preventDefault();
        currentIndex = (currentIndex + 1) % displayOrder.length;
        loadEntry(displayOrder[currentIndex]);
        break;
      case 'ArrowUp':
        e.preventDefault();
        currentIndex = (currentIndex - 1 + displayOrder.length) % displayOrder.length;
        loadEntry(displayOrder[currentIndex]);
        break;
      case ' ':
        e.preventDefault(); 
        if (isPlaying) {
          audioPlayer.pause();
          isPlaying = false;
          document.getElementById('w-play').textContent = '▶\uFE0E';
        } else {
          playAudio();
        }
        break;
      case 'c':
      case 'C':
        e.preventDefault();
        toggleCredits();
        break;
    }
  });
}


// ── SUPABASE / YOUR TAKE ───────────────────────────────────

function initSupabase() {
  // Library present?
  if (typeof window.supabase === 'undefined') {
    console.warn('Supabase library not loaded — Your Take disabled.');
    return;
  }
  // Config filled in?
  if (typeof SUPABASE_URL === 'undefined' ||
      SUPABASE_URL.includes('YOUR_') ||
      SUPABASE_ANON_KEY.includes('YOUR_')) {
    console.warn('Supabase config.js not filled in — Your Take disabled.');
    return;
  }

  sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  // React to login state. SIGNED_IN fires after a magic-link redirect.
  sb.auth.onAuthStateChange((event, session) => {
    updateAuthNote(session);
    if (event === 'SIGNED_IN' && session) {
      completePendingTake(session);
    }
  });
}

// After a magic-link login, finish the take the user started before leaving.
async function completePendingTake(session) {
  const raw = localStorage.getItem(PENDING_KEY);
  if (!raw) return;

  // Remove immediately — before the async insert — so a second SIGNED_IN
  // event firing in the same page load finds nothing and exits cleanly.
  localStorage.removeItem(PENDING_KEY);

  let pending;
  try { pending = JSON.parse(raw); }
  catch { return; }

  const { error } = await sb.from('takes').insert({
    user_id:      session.user.id,
    entry_id:     pending.entry_id,
    take_text:    pending.take_text,
    display_name: pending.display_name || null
  });

  if (error) {
    console.error(error);
    showFloatingConfirm('you\u2019re signed in, but the take didn\u2019t save \u2014 open it again to retry.');
  } else {
    showFloatingConfirm(`your take on ${pending.color || 'that moment'} was saved \uD83E\uDEC2`);
  }
}

function openTakeModal(entry) {
  activeTakeEntry = entry;
  document.getElementById('take-id').textContent = entry.placeholderColor;
  document.getElementById('take-text').value = '';
  resetTakeModalToWrite();
  hideTakeStatus();

  // collapse the previous-takes list each open
  document.getElementById('take-prev-list').classList.add('hidden');
  document.getElementById('take-prev-list').innerHTML = '';
  document.getElementById('take-prev-toggle').textContent = 'see your previous takes \u2193';

  document.getElementById('take-modal').classList.remove('hidden');
}

async function saveTake(session, text) {
  showTakeStatus('saving\u2026');
  const { error } = await sb.from('takes').insert({
    user_id:   session.user.id,
    entry_id:  Number(activeTakeEntry.id),
    take_text: text
  });

  if (error) {
    console.error(error);
    showTakeStatus('something went wrong \u2014 try again.');
  } else {
    document.getElementById('take-text').value = '';
    showTakeStatus('saved \uD83E\uDEC2 it\u2019s yours, kept private.');
    // if the previous list is open, refresh it
    const list = document.getElementById('take-prev-list');
    if (!list.classList.contains('hidden')) loadPreviousTakes();
  }
}

async function togglePreviousTakes() {
  const list   = document.getElementById('take-prev-list');
  const toggle = document.getElementById('take-prev-toggle');
  const isOpen = !list.classList.contains('hidden');

  if (isOpen) {
    list.classList.add('hidden');
    toggle.textContent = 'see your previous takes \u2193';
    return;
  }

  toggle.textContent = 'see your previous takes \u2191';
  list.classList.remove('hidden');
  await loadPreviousTakes();
}

async function loadPreviousTakes() {
  const list = document.getElementById('take-prev-list');
  list.innerHTML = '<p class="take-prev-empty">loading\u2026</p>';

  if (!sb) {
    list.innerHTML = '<p class="take-prev-empty">not set up yet.</p>';
    return;
  }

  const { data: { session } } = await sb.auth.getSession();
  if (!session) {
    list.innerHTML = '<p class="take-prev-empty">your past takes appear here once you\u2019ve saved one.</p>';
    return;
  }

  // RLS guarantees this only ever returns the current user's own rows.
  const { data, error } = await sb
    .from('takes')
    .select('take_text, created_at')
    .eq('entry_id', Number(activeTakeEntry.id))
    .order('created_at', { ascending: true });

  if (error) {
    console.error(error);
    list.innerHTML = '<p class="take-prev-empty">couldn\u2019t load your takes.</p>';
    return;
  }
  if (!data || data.length === 0) {
    list.innerHTML = '<p class="take-prev-empty">nothing here yet \u2014 this would be your first.</p>';
    return;
  }

  list.innerHTML = data.map(t => `
    <div class="take-prev-item">
      <span class="take-prev-text">${escapeHTML(t.take_text)}</span>
      <span class="take-prev-date">${formatDate(t.created_at.split('T')[0])}</span>
    </div>
  `).join('');
}

// ── Modal view helpers ──
function showEmailStep() {
  document.getElementById('take-step-write').classList.add('hidden');
  document.getElementById('take-step-email').classList.remove('hidden');
  document.getElementById('take-heading').textContent = 'save your take';
  hideTakeStatus();
}

function resetTakeModalToWrite() {
  document.getElementById('take-step-write').classList.remove('hidden');
  document.getElementById('take-step-email').classList.add('hidden');
  document.getElementById('take-heading').textContent = 'what does this mean to you?';
  document.getElementById('take-email').value = '';
  document.getElementById('take-name').value  = '';
}

function showTakeStatus(msg) {
  const s = document.getElementById('take-status');
  s.textContent = msg;
  s.classList.remove('hidden');
}

function hideTakeStatus() {
  document.getElementById('take-status').classList.add('hidden');
}

function updateAuthNote(session) {
  const note = document.getElementById('take-note');
  if (!note) return;
  note.textContent = session
    ? `signed in as ${session.user.email} \u00b7 only you can read your takes`
    : 'no password needed \u00b7 only you can ever read your takes';
}

// Small confirmation that floats in after a magic-link save (overlay is closed by then)
function showFloatingConfirm(msg) {
  let toast = document.getElementById('take-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'take-toast';
    toast.className = 'take-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 6000);
}


// ── UTILITIES ──────────────────────────────────────────────

function formatDate(str) {
  if (!str) return '—';
  const [y, m, d] = str.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric'
  });
}

function formatTime(secs) {
  if (!secs || isNaN(secs) || secs < 0) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── FIXED CREDIT FORMATTING ──
function formatCredit(val) {
  if (!val) return 'not specified';
  if (val.startsWith('http')) {
    const cleanUrl = escapeHTML(val);
    // Shows the raw URL text, but makes it clickable with the ↗
    return `<a href="${cleanUrl}" target="_blank" rel="noopener">${cleanUrl} ↗\uFE0E</a>`;
  }
  // If not a link, just show the text naturally (no arrow)
  return escapeHTML(val);
}

function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
}

function escapeHTML(str) {
  if (!str) return '';
  return str
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}