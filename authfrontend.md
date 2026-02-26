# Frontend Auth Integration — Change Log

**Date:** February 20, 2026  
**Scope:** Connected the vanilla-JS Tailwind dashboard to the secured FastAPI JWT backend. All frontend files consolidated into a single `frontend/` folder.

---

## Summary of Problem

The original frontend (`templates/index.html`) made raw `fetch()` calls to the API with no authentication headers. After adding JWT auth to the backend, every protected endpoint (`/api/bulk-screen`, `/jobs/`, etc.) started returning `401 Unauthorized` because no token was being sent. There was also no login page, no registration flow, and no way to establish a session.

---

## Files Created

### `frontend/static/js/auth.js` _(new)_

The core auth layer — a self-contained vanilla JS module that mirrors the logic previously written in `src/context/AuthContext.jsx` and `src/lib/api.js`, but with **zero build tooling**. It is included via a plain `<script>` tag.

**What it does:**

| Function | Description |
|---|---|
| `Auth.checkAuth()` | Call at DOMContentLoaded on any protected page. Reads the JWT from `localStorage`, checks its `exp` claim. If expired or missing, immediately redirects to `/login`. |
| `Auth.authFetch(url, opts)` | Drop-in replacement for `fetch()`. Automatically reads `access_token` from `localStorage` and injects `Authorization: Bearer <token>` into every request. If the server returns `401`, it clears storage and redirects to `/login` — preventing the user from silently operating with a dead token. |
| `Auth.login(email, password)` | Posts to `POST /auth/login` using `application/x-www-form-urlencoded` with `username` + `password` fields. This is required because FastAPI's `OAuth2PasswordRequestForm` expects form encoding, not JSON. On success, stores `access_token` and a decoded user profile (`{ id, company_id, email }`) in `localStorage`. |
| `Auth.register(email, password, company_name)` | Posts JSON to `POST /auth/register`, then immediately calls `Auth.login()` to obtain a token. Returns the user profile. |
| `Auth.logout()` | Clears both `access_token` and `ats_user` from `localStorage`, then redirects to `/login`. |
| `Auth.getUser()` | Returns the stored user profile object from `localStorage`, or `null`. |
| `Auth.getToken()` | Returns the raw JWT string if it exists and has not expired, otherwise `null`. |

**JWT expiry check:** Before returning a stored token, `getToken()` decodes the payload (base64url → JSON) and compares the `exp` claim (seconds since epoch) against `Date.now()`. Expired tokens are cleared immediately so they never reach the server.

---

### `frontend/login.html` _(new)_

A standalone login and registration page. Design matches the existing Tailwind dashboard (slate-900 brand, amber-400 accent, Inter font, Lucide icons).

**Features:**
- **Split-panel layout** — dark branding panel on the left (hidden on mobile), form card on the right.
- **Tabbed Sign In / Register** — single page, no navigation between routes. Switching tabs shows/hides the Company Name field and updates all button labels and footer text.
- **Password visibility toggle** — Eye/EyeOff icon button next to the password input.
- **Error and success banners** — Inline, animated, parse FastAPI's `{ detail: string | array }` error shape.
- **Loading state** — Submit button disables and label changes to "Signing in…" / "Creating workspace…" while the request is in flight.
- **Already-logged-in guard** — At the very top of the `<body>`, before any content renders, a script checks `Auth.getToken()`. If a valid token exists, the user is redirected straight to `/` without seeing the login page.
- **Register flow** — Calls `Auth.register()`, which hits `POST /auth/register` (creates Company + User) then auto-calls `Auth.login()`, so the user gets a token in a single step.

---

### `frontend/index.html` _(updated from `templates/index.html`)_

The existing recruiter dashboard, moved into `frontend/` and updated to be auth-aware.

**Changes from the original:**

1. **Auth script included**
   ```html
   <script src="/static/js/auth.js"></script>
   ```
   Added before any other scripts so `Auth.*` is available everywhere.

2. **Page guard on DOMContentLoaded**
   ```js
   Auth.checkAuth(); // redirects to /login if no valid token
   ```
   Prevents unauthenticated users from ever seeing the dashboard HTML.

3. **User email displayed in nav bar**
   ```js
   const user = Auth.getUser();
   if (user?.email) document.getElementById("nav-user-email").textContent = user.email;
   ```
   Shows the logged-in user's email next to the status pill.

4. **Sign Out button added to nav**
   ```html
   <button onclick="Auth.logout()">Sign out</button>
   ```
   Replaces the static nav — one click clears the token and returns to `/login`.

5. **All `fetch()` calls replaced with `Auth.authFetch()`**

   | Before | After |
   |---|---|
   | `fetch("/api/bulk-screen", { method: "POST", body: formData })` | `Auth.authFetch("/api/bulk-screen", { method: "POST", body: formData })` |
   | `fetch(\`/api/job/${jobId}\`)` | `Auth.authFetch(\`/api/job/${jobId}\`)` |

   `Auth.authFetch` automatically injects `Authorization: Bearer <token>` on every call and handles 401 globally, so no individual route handler needs to think about auth headers.

---

## Files Changed

### `main.py`

Two targeted changes:

**1. Static files and templates now served from `frontend/` instead of separate `static/` and `templates/` folders:**

```python
# Before
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# After — single consolidated source of truth
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend")
```

**2. New `/login` route added:**

```python
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
```

Without this route, navigating to `/login` (or being redirected there by `Auth.checkAuth()`) would return a 404. FastAPI now serves `frontend/login.html` at that path.

---

## Full Auth Flow (End to End)

```
1. User visits  GET /
   └─ FastAPI returns frontend/index.html
        └─ auth.js loads
             └─ Auth.checkAuth() runs
                  ├─ No token or expired → redirect to /login
                  └─ Valid token → render dashboard, show email in nav

2. User visits  GET /login
   └─ FastAPI returns frontend/login.html
        └─ Auth.getToken() check at top of body
             ├─ Already logged in → redirect to /  (skip login form)
             └─ Not logged in → show form

3. User submits Login form
   └─ Auth.login(email, password)
        └─ POST /auth/login  (application/x-www-form-urlencoded)
             └─ FastAPI OAuth2PasswordRequestForm validates credentials
                  └─ Returns { access_token, token_type: "bearer" }
                       └─ Token + profile saved to localStorage
                            └─ Browser redirects to /

4. User submits Bulk Screen form
   └─ Auth.authFetch("/api/bulk-screen", { method: "POST", body: formData })
        └─ Header injected: Authorization: Bearer eyJ...
             └─ FastAPI Depends(get_current_user) decodes token
                  └─ company_id extracted from JWT → job scoped to tenant

5. Polling  GET /api/job/:id
   └─ Auth.authFetch injects Bearer header on every poll tick
        └─ 401 at any point → Auth clears storage + redirects to /login

6. User clicks Sign Out
   └─ Auth.logout()
        └─ localStorage cleared
             └─ redirect to /login
```

---

## Folder Structure (Before vs After)

```
Before                          After
──────────────────────────────  ──────────────────────────────
templates/                      frontend/
  index.html                      index.html     ← auth-guarded
static/                           login.html     ← new
  styles.css                      static/
src/                                js/
  lib/api.js                          auth.js    ← new (shared)
  context/AuthContext.jsx         (styles.css still in static/ for
  pages/Login.jsx                  legacy reference if needed)
```

The `src/` React files remain untouched as a reference implementation for a future Vite/React build. The `templates/` and `static/` directories are superseded but not deleted.

---

## Security Notes

- `company_id` is **never** read from the client in any API call. It is always extracted server-side from the decoded JWT by `get_current_user`. A user cannot spoof another tenant's ID.
- The client-side JWT decode in `auth.js` is for display purposes only (reading `exp`, `user_id`, `company_id`). Signature verification happens exclusively on the server.
- Tokens are stored in `localStorage`. For higher-security requirements, consider `httpOnly` cookies with CSRF protection — this is a known trade-off for SPAs using `localStorage`.
- The `SECRET_KEY` in `services/auth.py` must be set via environment variable before deploying (`openssl rand -hex 32`).
