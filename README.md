# The Assortment

A personal archive of audiovisual moments - each entry pairs an image or short video with a brief audio excerpt, presented through an old-school interface. Moments are identified by hexcodes, not titles. They're meant to be felt, not explained.

**Live:** [theassortment.samarthgoradia.com](https://theassortment.samarthgoradia.com)

It began as a series of Instagram Close Friends stories; this is the standalone web version.

---

## Why it exists

Some feelings resist language. The Assortment is an attempt to express them through the pairing of sound and image instead of words - a digital shelf for the things that made me pause. Visitors are invited to bring their own interpretation.

---

## How it's built

Plain HTML, CSS, and JavaScript - no framework, no build step. The interesting part isn't the stack, it's the architecture around keeping it free, fast, and private.

```
Browser
  │
  ├── Site (HTML/CSS/JS)        → Vercel
  ├── Media (images / audio)    → Backblaze B2, fronted by Cloudflare CDN
  └── "Your Take" reflections   → Supabase (Postgres + magic-link auth)
                                   email via Resend
```

**The whole thing runs on free tiers.** Media delivery is free because Backblaze B2 and Cloudflare are part of the Bandwidth Alliance - B2 is the origin, Cloudflare caches at the edge, and the transfer between them costs nothing.

### Public / private separation

The design problem at the centre of the project: every entry has a private *meaning* I want to keep to myself, but the site and its data are public.

The solution is a publish pipeline (`publish.py`). I maintain a private master data file locally with full paths and meanings. The script:

1. uploads any new media to B2 (skipping what's already there),
2. generates a public data file with local paths swapped for CDN URLs,
3. strips every `meaning` field, and
4. runs a leak-check confirming no meaning reached the public output.

The private master never leaves my machine. Only the stripped, CDN-pointed public file is committed and deployed.

### "Your Take"

Visitors can leave their own interpretation of a moment. It's append-only and private to each person:

- **Magic-link auth** (Supabase) - no passwords; your email is your identity.
- **Row Level Security** - Postgres policies enforce that you can only ever read or write your *own* takes. The public API key exposed in the client is safe precisely because security lives in the database, not in hiding the key.
- **Append model** - every save is a new permanent row; reflections accumulate rather than overwrite.

---

## Features

- Old-School click-wheel interface (prev / next / play-pause / credits / close)
- Three sort modes - shuffle (the default, session-stable), chronological, recent
- Pagination, lazy-loaded thumbnails, keyboard shortcuts
- Per-entry credits panel linking to original sources
- Audio excerpting via time-range fragments + next-entry prefetch for fast sequential playback

---

## Project structure

```
main/
├── index.html
├── style.css
├── script.js
├── config.js          # Supabase URL + anon key (public-safe)
├── data.public.js     # generated: CDN URLs, meanings stripped
├── publish.py         # the media + data pipeline
visuals/  audio/        # local media (lives in B2, not committed)
```

`data.private.js` (the master) and `.env` (B2 keys) are intentionally not in this repo.

---

## A note on the media

This is a non-commercial work. Each entry uses a brief excerpt of existing media, recontextualised to express a feeling, with every source credited. All rights to the original media remain with their owners. If you own something featured here and would like it removed, email **samarthgoradia@gmail.com** and it'll be taken down promptly.

---

*Built by [Samarth Goradia](https://samarthgoradia.com).*