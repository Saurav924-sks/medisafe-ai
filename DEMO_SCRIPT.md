# Local synthetic workflow walkthrough

MediSafe AI is a production-oriented clinical decision support prototype. Keep
the clinical-use disclaimer visible; this walkthrough uses only synthetic local
data and is not clinical evidence.

## Start the local stack

At the repository root, configure `.env` with a local API key and SQLite:

```dotenv
DATABASE_URL=sqlite:///./medisafe-local.db
API_KEY=<local-development-key>
```

Terminal 1 — prepare the seeded synthetic clinicians and start the backend:

```powershell
Set-Location "C:\CHANDAN\medisafe-ai_ML\frontend\backend"
..\..\.venv\Scripts\Activate.ps1
python .\scripts\seed_dev.py
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — start the frontend:

```powershell
Set-Location "C:\CHANDAN\medisafe-ai_ML"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open `http://localhost:5173`. Sign in using the local `.env` API key and one of
the seeded clinician IDs:

| Clinician ID | Local synthetic role |
|---|---|
| `1` | Admin/prescriber (`ADMIN`, `DOCTOR`) |
| `2` | Read-only (`READ_ONLY`) |

The seed output is authoritative if the database already contained users and
the IDs differ. The API key is shared and is a prototype boundary, not
production authentication. Do not put it in source control, screenshots,
command output, or logs.

## Walkthrough

1. Sign in with clinician ID `1` and the local API key. Verify the clinician
   name and roles appear in the header.
2. Register a clearly synthetic patient, for example `Synthetic E2E Patient`,
   then add synthetic penicillin allergy, chronic kidney disease, and warfarin
   current-medication context from the profile tabs.
3. Review Medication History, Observations, Encounters, and Prescriptions.
   Each connected tab loads its API records and states empty or failed data
   explicitly. Audit remains unavailable because there is no patient audit
   read endpoint.
4. Create a prescription draft and review any normalized medication concept
   with the clinician before confirming it. Then run analysis and inspect the
   returned analysis status, evaluated and not-evaluated safety domains,
   alerts, and provenance. Never interpret no alerts as safety.
5. Acknowledge an alert or perform an override only with a structured reason
   where required. Review actions are appended; the original alert is
   preserved.
6. Sign out. Optionally sign in with ID `2` and confirm write controls remain
   unavailable; backend authorization remains authoritative.

The local knowledge base v1 is prototype data pending clinical review, and its
rule coverage is partial. SMART token state is in memory, no live FHIR service
is configured, and this walkthrough uses only synthetic local records.
