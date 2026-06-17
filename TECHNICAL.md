# TECHNICAL.md - Design decisions

This document is the *decision log* for The Assortment. Not "how it works" (see
the README) and not "concepts explained" (that's a private doc) - this is the
record of choices made at every fork, with the alternatives considered and why
they were rejected. It's the document for anyone auditing the repo, and for me
in a year when I'm wondering "why did I do it that way?"

Organized by decision area, roughly in the order each came up.

---

## 1. No framework

**Decision:** vanilla HTML/CSS/JS. No React, no build step, no bundler.

**Alternatives considered:** React/Vite, Astro, eleventy, Next.js static export.

**Why:**
- The site is a static gallery with a click-wheel interface and one network-bound
  feature (Your Take). None of that benefits from a component framework.
- A build step adds operational weight - config files, a `node_modules` to keep
  current, a dev server, a chance for the build to break at deploy time. For a
  personal long-lived archive, that's a maintenance tax with no payoff.
- The interesting complexity here is architectural (the public/private split,
  the auth flow, the media pipeline), not UI. A framework would obscure that
  rather than help.
- "Vanilla because it fits" is also a clearer portfolio signal than "vanilla
  because I don't know React." The choice is defensive of the work, not
  a limitation imposed by skill.

**What I'd reconsider:** if the site ever grows interactive UI that genuinely
needs reactive state across many components (a multi-pane editor, a complex form),
the vanilla event-listener model gets unwieldy and React or similar would pay
for itself. Not the case here.

---

## 2. Two data files, with a publish pipeline

**Decision:** `data.private.js` (master, local-only, contains meanings) and
`data.public.js` (generated, no meanings, CDN URLs). A Python script
(`publish.py`) does the conversion, including a leak-check that fails if any
`meaning:` field survives into the public file.

**Alternatives considered:**
- *Single file, manually edited before push.* Rejected - relies on discipline.
  One forgetful commit and the meanings are in git history forever.
- *Single file, meanings encrypted.* Rejected - meanings are short prose, not
  secrets needing crypto; encryption is overkill and makes them unreadable to me
  when re-reading my own private file.
- *Meanings in a separate non-JS file (a YAML or txt sidecar).* Reasonable, but
  splits the moment's data across two files for no functional gain. The
  single-master + generated-output pattern is cleaner.

**Why this works:**
- The separation is enforced *by a mechanism* (the script), not by memory.
- The leak-check is a hard gate - the script refuses to write the public file
  if the regex finds a residual `meaning:`. So even a bug in the strip logic
  fails loudly rather than silently leaking.
- `data.public.js` is fully self-describing (just a JS array assigned to
  `ENTRIES`) so the site stays framework-free.

**Trade-off accepted:** the public data file is loaded as a `<script>` tag, not
fetched as JSON. That's fine at the current size (~34 entries, KB-scale); if it
ever grows large I'd switch to a `fetch('/data.public.json')` and lazy-load it.

---

## 3. Object storage + CDN, not a regular web host

**Decision:** Backblaze B2 stores media, Cloudflare CDNs it, served at
`media.samarthgoradia.com`.

**Alternatives considered:**
- *Host media directly with the site (in the repo, deployed to Vercel).*
  Rejected - Vercel has bandwidth caps on the free tier, and committing dozens
  of MB of media to git is the wrong tool for binary blobs.
- *AWS S3 + CloudFront.* Works, but B2 is ~5x cheaper for storage, and the
  Bandwidth Alliance with Cloudflare makes B2→CF traffic free, which AWS doesn't
  match on a free tier.
- *Cloudflare R2.* Considered. Comparable on price; B2 chosen because R2's egress
  to non-CF destinations isn't free, B2's is well-documented with CF specifically,
  and B2 has the longest track record.
- *Just embed media as base64 in `data.public.js`.* Rejected for obvious reasons
  at any non-trivial size.

**Why:** the architecture is genuinely free at this scale (B2 free up to 10GB,
CF→B2 transfer free via the alliance, CF caching free). The cost calculus only
breaks if storage exceeds 10GB *or* monthly egress from B2 exceeds the free
allowance - both very far away.

**The wiring detail worth noting:** Cloudflare sits in front of B2 with a
Transform Rule that rewrites incoming paths like `media.samarthgoradia.com/x.jpg`
to B2's expected `/file/<bucket>/x.jpg`. This keeps URLs clean without an
intermediate worker or compute step.

---

## 4. Supabase for "Your Take" (and the security model)

**Decision:** Supabase (Postgres + auth) with Row Level Security policies that
enforce per-user privacy at the database layer. Anon key shipped to the browser.

**Alternatives considered:**
- *Firebase.* Comparable, but its security rules language is less expressive
  than SQL + RLS, and Postgres is a more transferable skill than Firestore.
- *A custom backend (Node + a hosted DB).* Adds an entire server to maintain
  for a feature that's fundamentally CRUD-on-one-table. Not worth it.
- *Static comments via Giscus/Utterances (GitHub-issue-backed).* Rejected - would
  require users to have GitHub accounts and would make every take publicly visible,
  which is the opposite of the design (each person sees only their own).

**The security argument worth documenting:**

The anon key is in the client and visible in page source. This is correct, not
a leak. Security is enforced by:

1. **RLS denies by default** when enabled. The table is fully locked until
   policies explicitly permit something.
2. **Two policies, no more:** an authenticated user may INSERT a row only if
   `user_id = auth.uid()` (can't write rows pretending to be someone else),
   and may SELECT rows only where `user_id = auth.uid()` (can't read others').
3. **No UPDATE or DELETE policy.** Takes are append-only by construction -
   not by client-side discipline, but because the database physically refuses
   the operation. This matches the design intent ("reflections are permanent").

Therefore: someone with the anon key can do exactly what an honest user can do -
write their own takes, read their own takes. They cannot read others' takes or
modify/delete anything, because the database refuses, because no rule allows it.

**One gotcha I hit:** during project creation, I turned OFF "automatically expose
new tables." That means the table-level GRANT to the `authenticated` role wasn't
created - and RLS doesn't matter if the role can't *reach* the table at all.
First save returned a 403. Fix: `grant select, insert on table public.takes to
authenticated;`. The distinction: GRANT controls "can the role touch the table?";
RLS controls "which rows?". Both are needed. (Worth knowing because the Supabase
default would have set the GRANT silently and I'd never have learned the
distinction.)

---

## 5. Magic-link auth, no passwords

**Decision:** Supabase magic-link email auth. Email is identity. No password.

**Alternatives considered:**
- *Passwords.* Adds a password reset flow, password storage concerns, the user
  has to remember another credential. Worse experience and more attack surface
  for a feature this lightweight.
- *OAuth (Google/Apple sign-in).* Heavier; the user has to make a deliberate
  account-linking choice. Magic-link is friendlier for a low-stakes, art-context
  identity.
- *Anonymous identity (e.g. a random UUID stored in localStorage).* Considered
  seriously. Rejected because losing browser storage loses the takes; no way to
  recover. Email-as-identity means the takes follow the person across devices and
  across time.

**The append model:** every save is a new row, not an upsert. So reflections on
the same moment accumulate over time, with timestamps. This is partly an artistic
choice (reflections aren't supposed to overwrite - they layer) and partly a data
hygiene one (you never lose anything to an accidental save).

**The pending-take stash, explained:** when a logged-out user writes a take,
clicks save, and is asked for their email, the magic-link round-trip would
normally lose their words on page reload. So before sending the email, the
half-written take is stashed in localStorage under `assortment_pending_take`.
On return, `onAuthStateChange('SIGNED_IN')` fires, the stash is read, the take
is inserted, the stash is cleared, and a confirmation toast appears. localStorage
is per-origin (not per-path), so the redirect landing on a different path on the
same origin still finds the stash.

**The double-save bug, explained:** `onAuthStateChange` can fire `SIGNED_IN`
twice in some flows. Both calls read the stash before either clears it →
double insert. Fix: clear the localStorage key *immediately*, before the
async insert, so the second call finds nothing and exits. Order of operations
in async race conditions matters more than it looks.

---

## 6. Custom SMTP via Resend

**Decision:** Resend, sending from `noreply@samarthgoradia.com`, configured as
Supabase's custom SMTP.

**Alternatives considered:**
- *Supabase's built-in sender.* The default. Rationed to 2–3 emails/hour and
  often lands in spam. Not viable past the testing phase.
- *Mailgun, Postmark, SendGrid.* All comparable. Resend chosen because the
  developer experience is the cleanest (the dashboard, the docs), and the free
  tier (100/day, 3000/month) is generous for this use case.

**Why a custom domain (`noreply@samarthgoradia.com`) instead of Resend's
shared testing domain:** sender domain is a real signal to inbox providers'
spam classifiers. A custom verified domain with DKIM/SPF/DMARC records lands
in inboxes; a shared "@resend.dev" sender lands in spam. For a magic-link site,
if the email is in spam, the user can't log in. So the DNS work in Cloudflare
(MX, SPF TXT, DKIM TXT) is mandatory, not optional, for production.

**One trap worth documenting:** Supabase keeps its OWN rate limit on email
sending, separate from Resend's. Connecting custom SMTP does not lift it -
you have to manually raise it under Authentication → Rate Limits. Easy to
miss; symptom is "I connected Resend but I'm still getting 429s."

---

## 7. Two repos: private archive + public clean

**Decision:** maintain two GitHub repos. A *private* one with full history
(including old commits where the private data file existed under a different
name); a *public* one with a fresh single-commit history, provably free of any
meaning because there is no history to hide one in.

**Alternatives considered:**
- *Just go public with the existing history.* Rejected - old commits contained
  the master data file. Once public, those commits would be permanently
  visible. Gitignoring later doesn't retroactively erase history.
- *Public, with `git filter-repo` to scrub the offending file from history.*
  Works, but is fiddly (BFG or filter-repo, force-pushes, verifying nothing
  was missed). For a personal project, the certainty of "fresh repo, no
  history at all" is worth more than preserving commit history.
- *Public, but nuke history and lose the archive entirely.* Considered.
  Rejected because the history has personal value as a record of the project's
  evolution.

**The irreversible gate:** the only moment that genuinely couldn't be undone
was the first push of the public repo. Before that commit, a `git status`
read confirmed that the private data file, env file, and media folders were
ignored, and the staged list contained only the intended files. After that
push, public history began - and once public, that initial state is permanent.

---

## 8. Hosting on Vercel, DNS through Cloudflare

**Decision:** Vercel serves the site (auto-deploys from the public GitHub
repo). Cloudflare manages DNS for `samarthgoradia.com`.

**The two CNAME records have *opposite* proxy settings**, which trips people up:
- `media.samarthgoradia.com` → B2 - **proxied (orange cloud).** Because we *want*
  Cloudflare to cache and serve it.
- `theassortment.samarthgoradia.com` → Vercel - **DNS only (grey cloud).** Because
  Vercel runs its own CDN and SSL; proxying through Cloudflare would conflict.

**Site-files-in-a-subfolder gotcha:** the repo root contains both site files
(in `main/`) and project files (`README.md`, etc.). On Vercel, the project's
Root Directory must be set to `main` or it deploys the repo root and gets
nothing. Documented in DAY2_DEPLOY.md.

---

## 9. Audio performance: range fragments + prefetch, not pre-trimming

**Decision:** add `#t=start,end` time-range fragments to audio URLs, use
`preload="metadata"`, and prefetch the next entry's audio while the current
one plays. No re-encoding or pre-trimming of source files.

**Alternatives considered:**
- *Pre-trim every audio file to exactly the 30-second clip.* Most "obvious"
  fix, and it does work. Rejected because (a) clip lengths are deliberately
  non-uniform (some moments are 7 seconds, some are several minutes - the
  variance is part of the curation), (b) doing it once is a chore, doing it
  every time I add a new entry is a workflow tax, and (c) the technical fix
  below makes it unnecessary.
- *Re-encode to lower bitrate.* Held in reserve. Doesn't address the seek
  lag root cause (which is the byte-range, not file size), but does help
  cold-cache loads. Will do as a one-time batch pass with loudness
  normalization in the same ffmpeg command if it ever becomes necessary.

**Why range fragments work:** browsers honor `#t=` for media and, combined with
`preload="metadata"`, request only the byte range needed for the clip from the
CDN - not the whole file. Cloudflare honors HTTP Range requests transparently.
So instead of buffering an entire 4-minute file to play a 30-second middle
section, the browser fetches just that section.

**Why prefetch:** people browse sequentially with ▼. While the current clip
plays, quietly start fetching the next one (`new Audio(); preload='metadata';`).
By the time ▼ is hit, the next clip is warm. Same trick applied to images via
`new Image()`.

**Scale claim worth defending:** audio lag is *per-file*, not *per-count*.
Opening moment #3 of 300 is no slower than #3 of 34 because only one file is
loaded at a time. The playlist itself stays fast at any count because of
pagination (20 entries per "Load More" tap) plus `loading="lazy"` on
thumbnails (off-screen ones don't download).

---

## 10. The iPod metaphor (and its design discipline)

**Decision:** an iPod-style player as the entry viewer - a screen above, a
click-wheel below with five controls (prev, next, play/pause, credits, close).

**Why this metaphor, not a generic modal:**
- A modal with controls scattered across the chrome is the obvious choice and
  the wrong one. The iPod evokes *a personal mixtape of moments* - exactly the
  emotional register the project lives in. Form supporting feeling.
- Constraining all interaction to five wheel buttons forces discipline. You
  cannot keep adding buttons to a click-wheel; the constraint is real, and the
  constraint preserves the focus on the screen content.
- Color-as-identity (hex codes instead of titles) is reinforced by the iPod's
  song-display chrome - it reads like a track listing, not an art gallery
  caption.

**One discipline call worth documenting:** when the audio label overflowed on
the screen, the temptation was to enlarge the screen frame. Rejected - the
interface dimensions are deliberate. Instead, the label truncates with ellipsis
on the screen, and the full label appears as a "track" row in the credits panel.
The interface stays consistent; the information is still accessible one tap away.

**A second discipline call:** a friend suggested adding a corner ✕ outside the
iPod for first-time discoverability (the wheel's ✕ is there but isn't where
users instinctively look). Initially I resisted on metaphor purity grounds.
Accepted on the reasoning that discoverability with friends-sharing matters
more than purity, and a small, quiet ✕ in the viewport corner doesn't break
the metaphor - it just adds a third (universal-instinct) exit alongside the
wheel ✕ and the backdrop-click-to-close.

---

## 11. The mobile compromises (and the iOS volume restriction)

**Decisions and their reasoning:**

- **`dvh` instead of `vh` on mobile.** `vh` includes the area behind the
  browser's URL bar and toolbar, so a 90vh iPod gets cut off on mobile.
  `dvh` (dynamic viewport height) measures the actually-visible area.
  Standard fix for a known browser behavior.

- **`touch-action: none` on the wheel.** Without it, the browser claimed
  finger drags as page-scrolls instead of routing them to the volume gesture.
  This single CSS property is what allows custom touch handling on a draggable
  element.

- **Single-column playlist on mobile.** Trivially correct. The thing worth
  noting is that on mobile, this isn't a *smaller* version of the desktop
  experience - it's arguably the *main* one. Users encountering this kind of
  emotional/quiet site are more likely to be on their phone in the right mood
  than on a laptop. So mobile is treated as primary, not as the responsive
  afterthought.

- **iOS volume control is hidden, not "fixed".** The volume wheel gesture
  works visually on iOS (the indicator moves) but doesn't actually change
  audio output - because iOS blocks JavaScript from setting an audio
  element's volume. Hardware buttons only, by Apple's platform restriction.
  Rather than pretending to fix it, the volume indicator is hidden on
  touch devices (via `@media (pointer: coarse)`). The gesture is still
  detected (in case desktop touchscreens exist), and it remains fully
  functional on every device that doesn't block it. This is "honest
  degradation" - acknowledge the platform limit, don't fight it, don't
  pretend.

---

## 12. The disclaimer (and the legal posture)

**Decision:** a non-commercial / fair-use / good-faith / takedown-offered
disclaimer. Explicitly does NOT claim that 30 seconds is automatically safe.

**Why the revision (from the original "30s clips = fair use" wording):**
There's no bright-line "X seconds is fair use" rule - fair use is decided
case-by-case on four factors. Claiming a bright line that doesn't exist reads
as grading your own legal case, and overstates the protection. The revised
copy describes what the site actually does (brief excerpts, new context, no
distribution) without claiming legal conclusions, and adds the single most
practically protective element: a visible takedown offer with a direct email.

**The honest posture:** a disclaimer doesn't *create* fair use, and I'm not
a lawyer. What the disclaimer does is (a) state intent accurately, and (b)
make removal one click for a rights-holder who finds the site and prefers it
not exist. The vast majority of these situations resolve at "please remove
it" - not at lawsuits. The disclaimer's job is to ensure that's the
ceiling of escalation, not the floor.

**An authorship line is separate** from the disclaimer, in the footer:
`© 2026 Samarth Goradia. Featured media belongs to its respective owners.`
This claims rights on what I *did* make (the site, the curation, the writing)
while disclaiming rights to what I didn't. The single-blob original disclaimer
mixed these and was less clear about both.

---

## 13. Default sort: session-stable shuffle

**Decision:** the playlist defaults to **Shuffle**, and that shuffle is
*session-stable* - the order is fixed for the duration of a visit and only
re-randomizes on a brand-new session or an explicit re-shuffle. Chronological
and Recent remain as toggles.

**Why default to shuffle (changed from chronological):**
- The project is called *The Assortment* and describes itself as "a collection
  of moments... not named and not explained, just felt." That's an explicit
  anti-timeline stance. A chronological default implies a narrative sequence and
  quietly ranks entries (newest = most relevant), which contradicts the premise
  that every moment is equal and independent.
- Shuffle reinforces the concept: serendipity, a fresh path each visit, no
  privileged entry, and a reason to return.

**Why session-stable, not re-random on every load:**
- A naive shuffle that re-randomizes on every reload or interaction is
  disorienting - you lose your place mid-browse and can't point a friend to a
  specific entry.
- The order is derived from a single seed kept in `sessionStorage`. A
  deterministic PRNG (mulberry32) feeding a seeded Fisher-Yates reproduces the
  same order from that seed, so the arrangement survives reloads and
  chronological<->shuffle round-trips within one visit. A new tab/session gets a
  new seed; clicking Shuffle while already shuffled forces a new seed ("deal
  again").

**Why a seed, not the stored order array:** a seed is compact and robust to the
entry set changing between renders; persisting the literal id order would go
stale if an id disappeared. Seed + deterministic shuffle always regenerates a
valid order for whatever entries currently exist.

**Trade-off accepted:** within one tab session the order is preserved, so newly
added entries aren't surfaced by default for a returning visitor. That's what
the Recent toggle is for - verifying a new entry landed is a deliberate toggle,
not the default experience.

---

## 14. Favicon and link previews

**Decision:** an iPod-shaped SVG favicon, a generated 1200x630 PNG social card
for Open Graph / Twitter, plus standard description / author / theme-color /
canonical meta tags.

**Why the favicon is the iPod, not a logo or monogram:** the iPod player is the
site's visual hero (section 10). The favicon echoes it - cream body, black
screen with an accent-blue play glyph, click-wheel - so the browser tab reads as
a tiny version of the thing the site is about. An SVG mark stays crisp at every
size and is version-controllable as text, with no binary asset to manage.

**Why a separate PNG card and not the SVG for previews:** link-unfurlers
(WhatsApp, iMessage, most chat apps) don't render SVG `og:image`s - they need a
raster. So the favicon stays SVG, but the share image is a PNG: a dark,
landing-style card (title + the iPod illustration) at the 1.91:1 / 1200x630
proportion, referenced with `summary_large_image`. It's rasterized from an SVG
source locally rather than hand-painted, so it stays editable as text.

---

## 15. Things deliberately not built

Worth listing the choices made by *omission*:

- **No "log in to view without saving" flow.** A logged-out returning user
  could theoretically want to re-read their old takes without writing a new
  one. Not built because (a) sessions last 7 days, so this is a narrow edge
  case, and (b) adding a "log in to browse" entry point reframes the feature
  from *a place you leave a mark* into *an account you audit*, which is
  thematically heavier than the safe-space gesture intended.

- **No likes, comments, or social signals on takes.** Each person sees only
  their own. The point is private reflection, not performance.

- **No sign-out button.** Visitors aren't meant to think of themselves as
  having an account. Sign-out is available via the console
  (`await sb.auth.signOut()`) for testing.

- **No analytics.** For now. May add a privacy-respecting counter later;
  haven't yet because no decision needs them to inform it.

- **No moderation queue for "Your Take."** Takes are private to each writer.
  Nothing is ever publicly displayed, so there's no surface to moderate.

- **No admin UI for reading takes.** The Supabase dashboard's Table Editor
  is the admin UI. Building a custom one would duplicate something that
  already exists and works.

Each of these is a choice. Calling them out here makes the negative space
of the design visible.

---
<em>Author: Samarth Goradia</em>