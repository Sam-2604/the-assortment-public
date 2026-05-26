# The Assortment

A personal static site — plain HTML, CSS, and JS, no frameworks, no backend. A curated archive of audiovisual moments where each entry pairs an image or video with a short audio clip. Currently runs locally. Deployment target: a subdomain of `samarthgoradia.com` via Vercel.

---

## Table of Contents

- [Project Structure](#project-structure)
- [Running Locally](#running-locally)
- [Adding an Entry](#adding-an-entry)
- [The ID System](#the-id-system)
- [Audio Trimming](#audio-trimming)
- [iPod Controls](#ipod-controls)
- [Private Meaning Field](#private-meaning-field)
- [Your Take Feature](#your-take-feature)
- [Known Bugs](#known-bugs)
- [Roadmap](#roadmap)
- [Deployment](#deployment)

---

## Project Structure

```
assortment/
├── index.html       Page structure and layout
├── style.css        All visual design, iPod interface, responsive rules
├── script.js        All logic: audio playback, iPod navigation, sorting, toggles
├── data.js          Entry database — the only file edited regularly
├── visual/          All local image and video files
└── audio/           All local audio files
```

`data.js` is loaded as a plain `<script>` tag before `script.js`. It sets a global `const ENTRIES` array. No imports or module syntax — keep it that way.

---

## Running Locally

Do not open `index.html` by double-clicking it. Browsers block media APIs on `file://` URLs, which means audio will silently fail to load.

**Correct method:** Open the project folder in VS Code and use the [Live Server](https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer) extension. Click **Go Live** in the bottom-right status bar. The site opens at `http://127.0.0.1:5500`.

---

## Adding an Entry

**Step 1 — Save your files**

Drop them into the appropriate folders:
- `visual/` → image (`sparks.jpg`) or video (`clip.mp4`)
- `audio/` → audio file (`sparks.mp3`) — can be the full uncut file, see [Audio Trimming](#audio-trimming)

**Step 2 — Add the entry to `data.js`**

Copy the template at the bottom of `data.js` and append it to the `ENTRIES` array. Always add a comma after the previous entry's closing `}`.

```js
{
  id:               7,                        // next number — permanent, never change or reuse
  date:             "2025-05-10",             // YYYY-MM-DD

  thumbnail:        null,                     // "visual/07-thumb.jpg" or null
  media:            "../visual/07.jpg",       // "../visual/07.jpg" or "../visual/07.mp4" or null
  mediaType:        "image",                  // "image" or "video"

  audio:            "../audio/07.mp3",        // can be the full uncut file
  audioStart:       0,                        // seconds to start from (0 = beginning)
  audioEnd:         null,                     // seconds to stop at (null = play to end)

  audioSource:      "Artist — Song Name",     // shown in the credits panel
  mediaSource:      "https://source-url.com", // shown in the credits panel, or null

  placeholderColor: "#1e2a3a",                // see ID System below — choose deliberately
  meaning:          "PRIVATE: ..."            // never rendered anywhere
}
```

**Step 3 — Save and refresh.** Done.

---

## The ID System

Entries have no names or titles. Each entry's identity is its `placeholderColor` hex code, displayed on the card and on the iPod screen.

The hex is chosen manually to match the emotional tone of the visual — it is not auto-generated and is not arbitrary. Once set, treat it as permanent. Do not change it.

In the rare case two entries share the same hex, the date and audio credit disambiguate them. The probability of a genuine collision across a large archive is negligible given the size of the hex space.

---

## Audio Trimming

If your audio file is a full song and you only want a specific window to play, use `audioStart` and `audioEnd` in `data.js`. Both values are in seconds.

| Goal | Config |
|---|---|
| Play from the beginning to 0:30 | `audioStart: 0, audioEnd: 30` |
| Play from 1:20 to 1:50 | `audioStart: 80, audioEnd: 110` |
| Play from 2:00 to end of file | `audioStart: 120, audioEnd: null` |

The progress bar reflects the trimmed duration, not the full file duration.

---

## iPod Controls

| Action | How |
|---|---|
| Play / Pause | Center wheel button |
| Next entry | ▼ on the wheel |
| Previous entry | ▲ on the wheel |
| Toggle credits panel | © on the left of the wheel |
| Close | ✕ on the right of the wheel, or click outside the iPod |
| Your Take | "your take ↗" button below the wheel |

> **Note:** Keyboard shortcuts (Space, arrow keys, Escape) are pending re-addition to `script.js`.

---

## Private Meaning Field

The `meaning` field in each `data.js` entry is never rendered anywhere — not in the HTML, not in any panel. It exists only in the file on your machine.

Before any public deployment, either delete these fields from `data.js` or ensure the file itself is not pushed to a public GitHub repository. If using GitHub, add `data.js` to `.gitignore` and manually upload it to Vercel instead, or strip the `meaning` fields before committing.

---

## Your Take Feature

"Your Take" currently saves viewer responses to the browser's `localStorage` only. The data lives on that device and browser. It is not transmitted anywhere. Clearing browser cache or site data will permanently delete it.

This is intentional for the local phase. A proper submission and storage system (with optional anonymity) is planned for the public launch — see [Roadmap](#roadmap).

---

## Roadmap

Planned work for the weeks ahead, in rough priority order:

1. **Log entries** — populate `data.js` with the real archive from the Instagram Close Friends stories.
2. **Mobile optimisation** — the iPod overlay and playlist grid need proper responsive handling for small screens.
3. **Your Take — persistent storage** — replace `localStorage` with a real submission system. Viewer responses should persist across sessions and devices. Include an option for the viewer to attach an identity or remain anonymous.
4. **Update disclaimer** — the current footer disclaimer is a placeholder. Revise with more precise language before going public.
5. **Personal website first** — build `samarthgoradia.com`, then deploy this as a subdomain (e.g. `assortment.samarthgoradia.com`) via Vercel.
6. **Your Assortment** - option for others to build their own assortment somehow.

---

## Deployment

When ready, use [Vercel](https://vercel.com) free tier. Two options:

- **Drag and drop** — upload the project folder directly in the Vercel dashboard.
- **GitHub connect** — push to a repo, connect it to Vercel, and it auto-deploys on every push.

No build step required. This is a plain static site — Vercel serves it as-is.

Before deploying, decide what to do with `data.js` given the `meaning` fields (see [Private Meaning Field](#private-meaning-field)).