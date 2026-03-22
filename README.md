# jra-srb

JRA race information retrieval SDK and local HTTP API.

## Features

- Config-driven HTML extraction rules
- Short-lived in-memory cache by endpoint
- Fixture-friendly provider abstraction
- FastAPI endpoints for races, card, odds, and result

## Quick start

```bash
uv venv
uv pip install -e .[dev]
uv run uvicorn jra_srb.app:app --reload
```

## Tiny HITL demo app

Human in the Loop flow verification 用の極小 Web アプリも含めています。

```bash
uv run uvicorn hitl_tiny_counter.app:app --reload --port 8010
```

Open `http://127.0.0.1:8010` to use the counter UI.

## Endpoints

- `GET /health`
- `GET /races?date=YYYY-MM-DD&course=optional`
- `GET /meetings/{date}/{course}`
- `GET /meetings/{date}/{course}/races/{race_no}/card`
- `GET /meetings/{date}/{course}/races/{race_no}/odds?bet_type=trifecta&combination=1,2,3&refresh=true`
- `GET /meetings/{date}/{course}/races/{race_no}/result`
- `GET /races/{race_id}/card`
- `GET /races/{race_id}/odds?bet_type=trifecta&combination=1,2,3&refresh=true`
- `GET /races/{race_id}/odds?bet_types=win,trifecta`
- `GET /races/{race_id}/result`

## Notes

The default implementation ships with generic parser definitions and fixture-backed tests.
Live JRA selectors and URL templates can be refined by editing the JSON parser configs and
the URL builder in `jra_srb.provider`.
