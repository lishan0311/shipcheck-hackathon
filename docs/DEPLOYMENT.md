# Render + Supabase setup

The configured stack is React/TypeScript/Vite/Tailwind/React Router, FastAPI/Pydantic, scikit-learn, Supabase PostgreSQL + Storage, and Docker on Render. No Sites deployment is used: Render is the user-selected target.

## Deployment preflight

Before creating the Render service, run this from the repository root:

```powershell
.venv\Scripts\python.exe scripts\deployment_preflight.py
```

It makes read-only checks against Supabase and Gmail and reports whether demo mode is still enabled. It never prints a key, token or message content. For a production deployment, it must finish with `Ready for deployment.`

## 1. Supabase

1. Open your Supabase project SQL editor.
2. Run `supabase/migrations/001_shipcheck.sql` once. It creates email, attachment, job, report and review tables, lightweight/full latest-report views, an atomic report/review function, and the private `shipping-documents` bucket. Existing projects should run `002_inbox_summary.sql` and `003_review_outcome_summary.sql` in order.
3. Copy `.env.example` to `.env` if it does not exist. Fill `SUPABASE_URL` and the **backend-only service role key**. Set `ALLOW_DEMO_MODE=false` when using Supabase.
4. Restart the backend. The UI should show **Supabase configured**. Process one sample email to verify database inserts and storage uploads. Merely displaying the configured indicator does not prove a live connection.

The browser talks only to FastAPI. It never receives the service role key. RLS is enabled and the migration denies anonymous/authenticated table access; the server uses its service role. Attachments are uploaded to a private bucket with content-hash object paths. Raw files in the participant bundle remain unchanged.

The initial inbox is read from the bundled dataset and unprocessed records are handled automatically in the background. Each processed email and its original attachments are synchronized to Supabase. A configured Gmail connection polls the authorized Inbox and immediately processes newly imported messages.

## Gmail mailbox connection

1. In Google Cloud Console, create or select a project and enable **Gmail API**.
2. Configure the OAuth consent screen. Add the inbox account as a test user while the app is in testing.
3. Create an OAuth **Web application** client with `http://127.0.0.1:8765/callback` as an authorized redirect URI.
4. Put `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` in the local root `.env` and run `.venv/Scripts/python.exe scripts/gmail_oauth.py --write-env`.
5. Authorize the inbox account. Copy `MAIL_PROVIDER=gmail`, the three Gmail OAuth values, and `GMAIL_USER_ID` to Render.
6. Optionally set `MAIL_POLL_SECONDS` (minimum 10 seconds) and `MAIL_SYNC_LIMIT` (1–100 messages per poll).
7. Restart the service and check `/api/mailbox/status`. Send a real email to `GMAIL_USER_ID`; the UI should place it first and auto-process it.

The backend refreshes short-lived access tokens with the saved refresh token and requests `https://www.googleapis.com/auth/gmail.readonly` plus `https://www.googleapis.com/auth/gmail.send`. The browser never receives OAuth credentials. Keep the client secret and refresh token out of GitHub and `VITE_*` variables. Re-run the OAuth helper after upgrading from a read-only token.

An external OAuth app in **Testing** receives a refresh token that expires after seven days. Re-authorize before judging, or publish the OAuth consent screen after completing Google's production requirements. Internal Workspace apps follow organization policy.

## Optional Gemini fallback

Gemini is an optional fallback for low-confidence email routing. It has a short
timeout, a per-process request cap and a circuit breaker: quota, network or API
errors keep the email in human review and do not interrupt the inbox. Configure
`GEMINI_API_KEY` only as a backend environment variable; do not expose it in
`VITE_*`. See `docs/AI_FALLBACK.md` for the full safeguards and configuration.

## 2. GitHub

Commit the application, `frontend/package-lock.json`, migration, Dockerfile and Render blueprint to your own repository. Check dataset redistribution permissions before publishing the participant bundle in a public repository. Never commit `.env`, model secrets, `.venv`, `node_modules` or the organizer answer package.

The `.github/workflows/ci.yml` workflow runs pytest and the frontend production build on pushes and pull requests. Model binaries are ignored and recreated from the committed synthetic training data during the Docker build.

The organizer Docker distribution is not included in our Docker image. Do not add its answer key to a public repository.

## 3. Render

Create a Blueprint from your GitHub repository using `render.yaml`.

This blueprint uses **one Docker web service for both frontend and backend**. React is built with Vite during the image build; FastAPI serves the resulting assets and handles `/api`. This keeps the frontend and backend on one origin and still hosts both on Render. No second frontend framework or host is involved.

Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in Render. `APP_ACCESS_TOKEN` is generated for the demo workspace: retrieve it from the Render dashboard and enter it into the website when prompted. This is a shared demo gate, not individual user authentication. Reviewer names are self-reported. Do not describe them as verified identities.

`ALLOW_DEMO_MODE=false` makes missing Supabase configuration fail startup. Tesseract and its English language data are installed by the Dockerfile. The Render-provided `PORT` is respected. `/api/health` is a liveness/configuration check; validate actual persistence with a processing request after deployment.

If using a separate Render Static Site instead, build `frontend` with `npm ci && npm run build`, publish `frontend/dist`, rewrite all application paths to `/index.html`, set `VITE_API_BASE_URL` to the backend HTTPS origin, and set `FRONTEND_ORIGIN` on the backend to the frontend HTTPS origin. Never put the Supabase key in a `VITE_*` variable.

## 4. Verify before sharing with judges

- Open `/inbox`, `/emails/email_001` and `/review` directly; browser refresh should work.
- Run AI processing, reload, restart the service, and confirm the report remains in Supabase.
- Verify the private storage object and attachment hash for the processed email.
- Confirm an uncertain category or correct a field. Check that a new report and review audit exist, with the original report unchanged.
- Check a text PDF, DOCX, XLSX and scanned PDF. OCR uses page rendering and Tesseract but remains conservatively flagged for review.
- Verify access-token behavior and share the required demo access details with judges.
- Send a real Gmail message with two supported attachments and verify automatic import, Supabase persistence and comparison.

## Existing SQLite history

The previous `runtime/shipcheck.sqlite3` is preserved but is no longer used by the application. Inspect the migration count without changing anything:

```powershell
.venv/Scripts/python.exe scripts/import_legacy.py
```

After configuring Supabase, import once with `--apply`. Re-running imports creates duplicate historical reports. Source records are not deleted; imported records receive new IDs and import timestamps.

## Optional official self-evaluation

Once every email has a complete saved report and any uncertain categories are resolved:

```powershell
.venv/Scripts/python.exe scripts/export_submission.py --output runtime/submission.json
# Only when the organizer endpoint is available:
.venv/Scripts/python.exe scripts/export_submission.py --score-url http://localhost:8080
```

The exporter stops instead of inventing predictions for missing or unresolved emails. It does not read the reference answer key. The organizer scoreboard is separate from the synthetic classifier validation report and final judging.

## Validation status of this checkout

Run both applicable Supabase migrations before measuring inbox performance. The backend falls back to the original full-report view when migration 002 is absent, but the summary view avoids transferring every field-evidence block during inbox refresh.

The production frontend build, 69 backend tests (plus 31 generated comparison subtests), Docker image build, containerized API/UI flow and a real Tesseract scan-PDF smoke test pass locally. The organizer-format local scorer reports 1.0000 on the supplied dataset and on an independently generated seed-73 dataset. These results measure the synthetic generator and are not a claim of perfect accuracy on unrestricted Gmail traffic. See `docs/VALIDATION.md` for the reproducible commands, metric breakdown and limitations. Render deployment and GitHub CI still require your repository and Render project connection.

## Official implementation references

- [React Router declarative setup](https://reactrouter.com/start/declarative/installation)
- [Tailwind with Vite](https://tailwindcss.com/docs/installation/using-vite)
- [FastAPI response validation](https://fastapi.tiangolo.com/tutorial/response-model/)
- [Supabase Data API](https://supabase.com/docs/guides/api)
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
- [Render Blueprint reference](https://render.com/docs/blueprint-spec)
- [Gmail API: list messages](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
- [Gmail API: get attachments](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get)
- [Google OAuth for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [pdfplumber](https://github.com/jsvine/pdfplumber), [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html), [python-docx](https://python-docx.readthedocs.io/en/latest/api/document.html), [pytesseract](https://github.com/madmaze/pytesseract)
