"""Voice Action Gate -- Cloudflare Python Worker.

Three responsibilities, and nothing else:

  GET  /api/token   mint a SHORT-LIVED AssemblyAI streaming token, behind a
                    strongly-consistent daily issuance counter. The main API key
                    lives in a Worker secret and never leaves this process.
  POST /api/gate    run the gate over a client-supplied transcript + proposal
                    and return the verdict.
  everything else   static assets (the browser UI).

Audio never touches this Worker: the browser streams straight to AssemblyAI
with the temporary token. That is why we cannot store anyone's voice -- not a
promise, a shape.

🔴 The gate eats a transcript the CLIENT sent. That is the documented
out-of-scope boundary (docs/ARCHITECTURE.md section 1), not an oversight.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(__file__)
for _p in (os.path.join(_HERE, "vendor"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json

from workers import DurableObject, Response, WorkerEntrypoint, fetch

import policy
from gate.errors import GateError
from gate.proposal import parse_proposal
from gate.reasons import Outcome
from gate.transcript import parse_transcript

TOKEN_URL = "https://streaming.assemblyai.com/v3/token"
WS_BASE = "wss://streaming.assemblyai.com/v3/ws"

# AssemblyAI's documented bounds for max_session_duration_seconds.
CAP_MIN = 60
CAP_MAX = 10800

DEMO_CAP_SECONDS = 120
"""What we actually ask for. A demo turn is seconds long; 120 is the smallest
useful value above CAP_MIN. Worst-case billed length is `cap + ~60s`, because
the server's close lags expiry by an observed ~60s (docs/ARCHITECTURE.md
section 6.2) -- observed, n=2, NOT a documented promise."""

TOKEN_TTL_SECONDS = 60
"""How long the minted token may be used to OPEN a connection. Short on
purpose: a leaked token is worth one connection for one minute."""

DAILY_TOKEN_LIMIT = 200
"""Issuance ceiling per UTC day for the whole deployment. This bounds spend:
worst case = DAILY_TOKEN_LIMIT * (DEMO_CAP_SECONDS + ~60s) of streaming."""

_JSON = {"content-type": "application/json; charset=utf-8"}


def _json(payload: object, status: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False), status=status, headers=_JSON)


# ---------------------------------------------------------------------------
# Durable Object: the daily issuance counter.
# ---------------------------------------------------------------------------
class DailyQuota(DurableObject):
    """🔴 A Durable Object, not KV, and the difference is the whole point.

    KV is eventually consistent: two concurrent read-modify-writes both read the
    old count and both write old+1, so the ceiling leaks under exactly the load
    it exists to survive. A DO instance is single-threaded and its storage is
    strongly consistent, so `read; +1; write` is atomic without a lock.

    A quota that says "fail closed" and is not actually consistent is worse than
    no quota: it reports a bound it does not hold.
    """

    async def fetch(self, request):
        body = await request.json()
        day = str(body["day"])
        limit = int(body["limit"])

        key = f"issued:{day}"
        issued = await self.ctx.storage.get(key)
        issued = 0 if issued is None else int(issued)

        if issued >= limit:
            return _json(
                {"granted": False, "issued": issued, "limit": limit, "day": day}, 200
            )

        issued += 1
        await self.ctx.storage.put(key, issued)
        return _json(
            {"granted": True, "issued": issued, "limit": limit, "day": day}, 200
        )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class Default(WorkerEntrypoint):
    async def fetch(self, request):
        from urllib.parse import urlparse

        path = urlparse(request.url).path

        if path == "/api/token":
            return await self._mint_token(request)
        if path == "/api/gate":
            return await self._run_gate(request)
        if path == "/api/health":
            return _json({"ok": True, "python": sys.version.split()[0]})

        return await self.env.ASSETS.fetch(request)

    # -- token ------------------------------------------------------------
    async def _mint_token(self, request):
        key = getattr(self.env, "ASSEMBLYAI_API_KEY", None)
        if not key:
            # Fail closed and say so plainly. Never fall back to "no quota".
            return _json({"error": "server is not configured with an API key"}, 503)

        day = _utc_day()
        grant = await self._claim_quota(day)
        if grant is None:
            return _json(
                {"error": "quota service unavailable; refusing to mint", "day": day},
                503,
            )
        if not grant.get("granted"):
            return _json(
                {
                    "error": "daily token limit reached",
                    "issued": grant.get("issued"),
                    "limit": grant.get("limit"),
                    "day": day,
                },
                429,
            )

        url = (
            f"{TOKEN_URL}?expires_in_seconds={TOKEN_TTL_SECONDS}"
            f"&max_session_duration_seconds={DEMO_CAP_SECONDS}"
        )
        upstream = await fetch(url, headers={"Authorization": key})
        if upstream.status != 200:
            text = await upstream.text()
            return _json(
                {"error": "upstream token mint failed", "status": upstream.status,
                 "detail": text[:200]},
                502,
            )
        data = await upstream.json()
        token = data.get("token") if hasattr(data, "get") else None
        if not token:
            return _json({"error": "upstream returned no token"}, 502)

        return _json(
            {
                "token": token,
                "ws_base": WS_BASE,
                "expires_in_seconds": TOKEN_TTL_SECONDS,
                "max_session_duration_seconds": DEMO_CAP_SECONDS,
                "quota": {"issued": grant.get("issued"), "limit": grant.get("limit"),
                          "day": day},
            }
        )

    async def _claim_quota(self, day: str):
        """Returns the grant dict, or None if the counter could not be consulted.

        None means "we do not know", and the caller treats not-knowing as a
        refusal. That is the only reading that makes the word `fail-closed`
        true.
        """
        try:
            ns = self.env.QUOTA
            stub = ns.get(ns.idFromName("global"))
            resp = await stub.fetch(
                "https://quota.internal/claim",
                method="POST",
                body=json.dumps({"day": day, "limit": DAILY_TOKEN_LIMIT}),
                headers={"content-type": "application/json"},
            )
            return await resp.json()
        except Exception:
            return None

    # -- gate -------------------------------------------------------------
    async def _run_gate(self, request):
        if request.method != "POST":
            return _json({"error": "POST only"}, 405)
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "body is not JSON"}, 400)

        words = body.get("words")
        raw_proposal = body.get("proposal")
        # 🔴 Must be declared by whoever opened the connection. Absent -> None ->
        # REQUIRE_KNOWN_PROVENANCE turns every verdict into BLOCK. We refuse to
        # infer it from `turn_is_formatted`; gate/transcript.py records why.
        formatting = body.get("format_turns", None)
        if formatting is not None:
            formatting = bool(formatting)

        if not isinstance(words, list) or not isinstance(raw_proposal, dict):
            return _json({"error": "expected {words: [...], proposal: {...}}"}, 400)

        try:
            transcript = parse_transcript(words)
            proposal = parse_proposal(raw_proposal)
            gate = policy.build_gate(formatting_enabled=formatting)
            verdict = gate.evaluate(proposal, transcript)
        except GateError as exc:
            # A malformed input is not an ALLOW. Report it as its own shape so a
            # reader can never mistake it for a decision the gate made.
            return _json({"error": type(exc).__name__, "detail": str(exc)}, 400)

        return _json(_verdict_json(verdict))


def _utc_day() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _verdict_json(verdict) -> dict:
    ev = verdict.evidence
    out = {
        "outcome": verdict.outcome.value,
        "reasons": [r.value for r in verdict.reasons],
        "evidence": {
            "provenance": {
                "field_name": ev.provenance.field_name,
                "formatting_enabled": ev.provenance.formatting_enabled,
                "extractor_id": ev.provenance.extractor_id,
            },
            "confidence_floor": ev.confidence_floor,
            "max_span_words": ev.max_span_words,
            "role_window": ev.role_window,
            "max_transcript_words": ev.max_transcript_words,
            "witness_count": ev.witness_count,
            "rejected_count": ev.rejected_count,
            "matched": {
                param: {
                    "value": _scalar(w.value),
                    "role": w.role.value,
                    "span": [w.span.start_index, w.span.end_index],
                    "span_text": w.span.text,
                    "min_confidence": w.min_confidence,
                    "decoder_id": w.decoder_id,
                }
                for param, w in ev.matched.items()
            },
            "records": [
                {
                    "param": r.param,
                    "check": r.check.value,
                    "status": None if r.status is None else r.status.value,
                    "outcome": r.outcome,
                    "reason": None if r.reason is None else r.reason.value,
                    "detail": r.detail,
                }
                for r in ev.records
            ],
        },
    }
    if verdict.outcome is Outcome.ALLOW and verdict.capability is not None:
        # The capability object itself never crosses the wire -- it is a
        # process-local credential. What crosses is a description of it.
        out["capability"] = {
            "action": verdict.capability.action,
            "arguments": {k: _scalar(v) for k, v in verdict.capability.arguments.items()},
        }
    return out


def _scalar(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
