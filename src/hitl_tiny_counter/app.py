from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="HITL Tiny Counter")

_counter_value = 0


def _page() -> str:
    return """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tiny Counter</title>
    <style>
      body { font-family: sans-serif; margin: 2rem; max-width: 32rem; }
      .card { border: 1px solid #ccc; border-radius: 12px; padding: 1rem; }
      .value { font-size: 3rem; margin: 1rem 0; }
      .actions { display: flex; gap: 0.75rem; }
      button { padding: 0.7rem 1rem; font-size: 1rem; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Tiny Counter</h1>
      <p>Human in the Loop flow demo</p>
      <div id="value" class="value">0</div>
      <div class="actions">
        <button id="increment" type="button">+1</button>
        <button id="reset" type="button">Reset</button>
      </div>
    </main>
    <script>
      async function refresh() {
        const response = await fetch('/api/value');
        const data = await response.json();
        document.getElementById('value').textContent = data.value;
      }
      async function post(path) {
        await fetch(path, { method: 'POST' });
        await refresh();
      }
      document.getElementById('increment').addEventListener('click', () => post('/api/increment'));
      document.getElementById('reset').addEventListener('click', () => post('/api/reset'));
      refresh();
    </script>
  </body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_page())


@app.get("/api/value")
async def get_value() -> dict[str, int]:
    return {"value": _counter_value}


@app.post("/api/increment")
async def increment() -> dict[str, int]:
    global _counter_value
    _counter_value += 1
    return {"value": _counter_value}


@app.post("/api/reset")
async def reset() -> dict[str, int]:
    global _counter_value
    _counter_value = 0
    return {"value": _counter_value}
