# Fragrance Survey Dashboard

Live fieldwork dashboard for **PRIVE_SEPTEMBER CAMPAIGN BLS**. It reads the 12 Kobo Fragrance Survey forms (brands A–F, control vs experimental) and shows age and gender counts.

## Local

```
py -3.13 run_dashboard.py
```

Open http://127.0.0.1:8050

Put your Kobo token in `.env` (never commit that file):

```
KOBO_TOKEN=
KOBO_KF_URL=https://kf.kobotoolbox.org
```

## Vercel

1. Import this GitHub repo in [Vercel](https://vercel.com). Framework: Python / Flask (`app.py`).
2. Add environment variables:
   - `KOBO_TOKEN` — same Kobo API token
   - `KOBO_KF_URL` — `https://kf.kobotoolbox.org`
3. Deploy. Share the Vercel URL with the client.

The token stays on the server. It is not sent to the browser.
