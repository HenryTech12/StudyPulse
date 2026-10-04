# Study Pulse (full stack)

Class-scoped study app: struggle posts (public or anonymous), "Me too" counts, Radar AI deadline posts, comments, private DMs with optional name reveal.

- **Backend:** Python, FastAPI, SQLAlchemy (SQLite by default, Postgres via `DATABASE_URL`), JWT auth
- **Frontend:** React 18 + Vite
- **Radar AI:** Groq (Llama 3.3 for text, Llama 4 Scout for photos, Whisper for voice notes) when `GROQ_API_KEY` is set, otherwise a built-in rule-based parser
- **Photos:** Cloudinary when `CLOUDINARY_URL` is set, otherwise local disk
- **Accounts:** username or phone number plus password (no email needed)

## Run it
```bash
# 1. Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY=change-me                 # required for real use
export GROQ_API_KEY=gsk_...                 # optional: AI Radar + voice notes
export CLOUDINARY_URL=cloudinary://KEY:SECRET@CLOUD   # optional: photo hosting
uvicorn app.main:app --reload --port 8000   # API docs: http://localhost:8000/docs

# 2. Frontend (terminal 2)
cd frontend
npm install
npm run dev                                 # http://localhost:5173 (proxies /api to :8000)
```
Open the app in two browser profiles, sign up two students, create a class with one and join with its code in the other.

## Tests
```bash
pip install -r backend/requirements-dev.txt
cd backend && pytest -q          # 96 API tests: every endpoint, anonymity, Cloudinary and Groq (mocked), moderation, recovery, live chat

# Real UI tests: the React app in jsdom against a real running backend (starts and stops the server for you)
cd frontend && npm install && cd .. && ./scripts/e2e.sh     # 5 tests: signup, anonymous post, Radar, DM + live reply/reveal, login, moderation
```

## Troubleshooting
- **"database was created by an older version"**: delete `backend/studypulse.db` and restart (no migrations yet).
- **Live chat not updating**: make sure `uvicorn[standard]` is installed (it is in `requirements.txt`); plain `uvicorn` has no websocket support.
- **Voice note says it needs GROQ_API_KEY**: set the key on the server; typing the deadline always works.

## One-container deploy (Docker)
```bash
cp .env.example .env   # fill in the keys
docker compose --env-file .env up --build   # http://localhost:8000
```
The image builds the React app and serves it from FastAPI. Data and uploads live in the `studypulse-data` volume. On Render/Railway, deploy the Dockerfile and attach a disk at `/data` (or set `DATABASE_URL` to Postgres).

## API summary (all under /api, Bearer token except register/login)
| Area | Endpoints |
|---|---|
| Auth | POST /auth/register (username and/or phone, returns a one-time recovery code), /auth/login, /auth/reset (recovery code), GET /me |
| Uploads | POST /uploads (base64 image, EXIF stripped, then sent to Cloudinary, max 4 MB) |
| Moderation (class owner) | GET /classes/{id}/reports, DELETE /classes/{id}/reports/{post_id}, DELETE /posts/{id} on any note |
| Live chat | WebSocket /ws/conversations/{id}?token=... (pushes new messages) |
| Classes | POST /classes, POST /classes/join, GET /classes, GET /classes/{id} |
| Posts | GET/POST /classes/{id}/posts, GET /classes/{id}/topics, GET/DELETE /posts/{id}, POST /posts/{id}/me-too, POST /posts/{id}/report |
| Comments | GET/POST /posts/{id}/comments |
| Radar | POST /radar/parse, POST /radar/transcribe (Groq Whisper), GET/POST /classes/{id}/deadlines, DELETE /deadlines/{id} |
| DMs | POST/GET /conversations, GET/POST /conversations/{id}/messages, POST /conversations/{id}/reveal |

## How anonymity works
- Posts and comments store only a copied `display_name` (real name or `Anon_NNN`).
- Author ids live in separate `post_authors` / `comment_authors` tables that no endpoint returns. Clients only get `is_mine`.
- Starting a DM looks up the hidden author on the server. The other student sees "Anonymous student" until that person calls `/reveal`, which affects that one chat only.
- Radar deadline posts are always public.
- Uploaded photos are re-encoded on our server before going to Cloudinary, which removes EXIF/GPS data that could identify an anonymous poster.
- Phone numbers and usernames are private: only `/me` returns your own, and no other endpoint ever includes them.
- The class owner sees reports with the display name only, never the real author, and can still remove the note.

## Accounts and recovery
Sign up with a username, a phone number (with country code) or both. Sign in with either. Phone numbers are not verified yet (no SMS), they are just a login handle. Because there is no email or SMS, signup shows a one-time **recovery code**; `/auth/reset` needs it to set a new password and issues a fresh code. Logins and resets are throttled to 5 failures per 15 minutes per identifier (in memory, per server process).

## Not included yet
Phone verification by SMS, email, shared rate limiting across multiple servers, image content moderation, push notifications, and automated frontend tests.
