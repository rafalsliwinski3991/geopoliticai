---
name: react-frontend
description: "INVOKE THIS SKILL when writing or changing a React + Vite frontend — components, state, data fetching, streaming responses, auth tokens in the browser, rendering untrusted Markdown or HTML, the Vite build and static serving, or frontend tests. Use it before adding any component or frontend dependency."
---

Keep React narrow: it earns its place on interactive surfaces. Server-rendered pages
(landing, marketing, docs, blog, login and signup flows) stay server-rendered — they
are simpler, and they are what search engines read.

## Dependency budget

Start with React, Vite, and nothing else. Then, in order:

- **State:** `useState` → lifting it up → `useReducer` → context for the one or two
  values that are genuinely global. A state-management library needs a problem those
  four failed at.
- **Routing:** none until there is a second route.
- **Data:** `fetch` in an effect or an action is fine for a handful of calls. A
  data-fetching library pays off at many endpoints with caching and invalidation, not
  before.
- **UI:** plain CSS and native elements first — `<dialog>`, `<details>`,
  `<input type="date">`, form validation attributes. A component library is a large
  bet on someone else's design system.

Every dependency here ships to the user over the network. That is the cost.

## Components and state

- Derive during render instead of mirroring one state value into another; the second
  copy is the bug.
- `useEffect` is for synchronizing with something outside React (a socket, a
  subscription, the document title) — not for computing values or reacting to props.
  Always return the cleanup function.
- Keys are identity: use stable ids, never the array index for a list that reorders.
- Abort in-flight requests on unmount or on a superseding request
  (`AbortController`), or a slow response will overwrite a fresh one.

## Auth tokens in the browser

- Keep an access token **in a JS variable in memory — not `localStorage`, not
  `sessionStorage`.** Anything an XSS can read, an XSS will exfiltrate.
- Fetch it from a session-cookie-authenticated endpoint with
  `credentials: "include"`; on 401 there, redirect to the login page with a `next`
  parameter rather than rendering a broken app.
- Send it as `Authorization: Bearer …` on every API call, and re-fetch once on a 401
  before giving up.
- The server decides ownership. A client-held id is a hint, never a permission.

## Streaming responses

`EventSource` cannot send an `Authorization` header — for an authenticated stream use
`fetch` plus a `ReadableStream` reader, and parse the SSE frames yourself. Wire an
`AbortController` for both the user's cancel and a hard timeout. Render partial output
as it arrives; handle a stream that ends mid-message as a visible state, not silence.
Cover the statuses the API can return before the stream opens — 401, 403, 429 and the
server's own error codes — with distinct UI, not one generic failure.

## Rendering untrusted content

Sanitize Markdown and HTML before it reaches the DOM. `dangerouslySetInnerHTML` takes
sanitized input only. This is a trust boundary, not polish — never simplify it away.

## Build and serving

- Vite builds static assets; a plain static server (nginx) serves them. No Node
  process in production unless something actually renders on the server.
- Multi-stage Dockerfile: a `node` stage runs `vite build`, a small nginx image serves
  `dist`. One container.
- Served under a path prefix? Set Vite's `base`, and have the server fall back to
  `index.html` for client routes under that prefix only.
- Keep images out of the bundle's way — an unoptimized logo is often larger than all
  the JavaScript.

## Tests

The repository's frontend suite is `.mjs` files in `frontend/tests/` run by Node's
built-in runner — `npm test` from `frontend/`. Extend that runner; do not introduce
Vitest, jsdom, or a different test framework unless the frontend adopts one first.
Test the behaviour most likely to break: the streaming reader, auth redirects, and
any pause/resume or multi-step flow.

Check context7 for current React and Vite APIs before quoting config; this
toolchain moves fast.
