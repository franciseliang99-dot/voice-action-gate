<!-- ════════════════════════════════════════════════════════════════════
     Editing rules for this file. Each one exists because of a specific way
     this kind of document goes wrong:

     1. NO UNMEASURED NUMBERS. Thresholds, confidences, latencies, accuracy --
        if the experiment has not been run, leave a MEASURE marker in an HTML
        comment. Never write a plausible-looking figure "to calibrate later":
        a number in a README gets quoted back as a conclusion.
     2. NO "IMPOSSIBLE" WITHOUT LOAD-BEARING EVIDENCE. This project's pitch is
        a structural claim. Until the evidence is in (see the evidence table in
        docs/ARCHITECTURE.md), the wording is "the design intent is", not
        "it cannot".
     3. CLEAN ROOM: not one line of pre-existing code was carried in. Methods
        are reusable; implementations were written from scratch for this entry.
        Everything here was committed inside the hackathon window.
     ════════════════════════════════════════════════════════════════════ -->

# Voice Action Gate

**A voice agent that cannot execute an irreversible action without provable confirmation.**

Not "an agent that tries hard not to mis-hear." One where *"I couldn't tell"* has no
path to *"go ahead"* — because the code that executes an action can only be reached
through a credential that the gate refuses to mint when the evidence isn't there.

---

## The problem this exists for

Streaming ASR is good, not perfect. `"transfer five hundred"` and `"transfer five thousand"`
differ by one token that is acoustically close and semantically 10×.

That single fact is why voice agents in banking, healthcare and insurance are still
mostly **read-only**: ask about your balance, never move the money. The industry's
answer has been to raise accuracy. Accuracy is an asymptote — it never reaches a place
where "execute an irreversible action on a guess" becomes acceptable.

<!-- MEASURE: a citable WER figure with a source (the organiser's own benchmark
     page first). Until there is a source, the prose says "imperfect" and states
     no percentage. Writing a plausible-looking number now would get quoted back
     as a finding. -->

**So this project changes what the failure does, not how often it happens.**

| Failure direction | What it costs |
|---|---|
| Gate wrongly **blocks** | The user repeats themselves. Annoying. |
| Gate wrongly **passes** | Money moved. Irreversible. |

The two are not symmetric, so the system is not built symmetric.

---

## How it works

AssemblyAI's Voice Agent API uses **client-side function tools**: the agent emits a
`tool.call`, *your code runs the logic*, and you send back a `tool.result`.

That seam is not a hack we found — it is the documented architecture. The gate sits
exactly there:

```
  speech ──▶ Universal-Streaming v3 ──▶ agent ──▶ tool.call  ─┐
                                                              │
                                                     ┌────────▼────────┐
                                                     │  ACTION  GATE   │
                                                     │  mints, or not, │
                                                     │  an Execute cap │
                                                     └────────┬────────┘
                                                              │
  audio ◀── agent ◀── tool.result ◀── executor ◀───────────────┘
                                       (needs the capability
                                        to even be callable)
```

The gate's inputs are all things the API actually gives us — verified, not assumed:

- **word-level `confidence`** and `word_is_final`, per word, on every `Turn`
- word **timings** (`start` / `end`, milliseconds)
- `end_of_turn_confidence`
- the proposed `tool.call` arguments

Plus one thing the API cannot give us and the design commits to: **an explicit
read-back confirmation**, grounded against the transcript rather than against the
model's own summary of it — **specified this round, not implemented**; see the limits
below.

---

## The one idea worth stealing

**Grounding.** Before an action's parameters are trusted, each one must be shown to
have been *spoken* — located in the word-level transcript — not merely *produced* by
the language model. A value the model invented is a value nobody said.

The hard part isn't the lookup. It's that normalization (`"five hundred"` → `500`)
is a machine for manufacturing witnesses: normalize aggressively enough and every
value finds "evidence" for itself. So the normalizer is a **partial function** —
it is allowed to say *undecodable*, and undecodable is not a pass.

Full write-up: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). It was drafted in
Chinese as a working document; **§0 is a self-contained English summary** of the
design, the evidence behind each claim, and what is deliberately *not* claimed.

---

## Running it

```sh
# The gate is pure Python with no dependencies. Run its test suite from the repo root:
python3 -m unittest discover -s tests -t . -q          # 152 tests

# The Worker (Cloudflare Python Workers). Build vendors the gate + runtime into app/worker/:
cd app && ./build.sh

# Local end-to-end against a dev server, printing one line per gate decision:
cd app && ./run_local.sh                                # needs .dev.vars, see .dev.vars.example
```

The tests cite specification IDs (`TS-01` … `TS-49`, `A0` … `A24.6`, `DN-1`) from the
design document the implementation was built against. **That document is the
development record and is not part of this submission** — it lives outside this
repository. The tests are written to be self-describing: each one states what it
pins in its own docstring, so the IDs are provenance labels, not required reading.

## Honest limits

<!-- 🔴 DO NOT DELETE THIS SECTION. A system that claims "it cannot mis-approve"
     devalues that claim by being vague about its own edges. "Our threat model
     excludes this" and "we didn't think of it" look identical in a demo; only
     one of them is written down in advance. -->

**Outside the threat model — stated, not implied:**

- **A malicious client.** The gate consumes a transcript the client supplies, so a
  client can forge one. But the adversary here is the *language model*, and the person
  at the microphone is the party being protected. Forging your own transcript is lying
  to yourself.
- **A wrong transcript that is internally consistent.** If the recognizer confidently
  mishears and the model proposes exactly what was misheard, every argument *is*
  grounded and the action passes. **The gate proves provenance, not truth.**

**Not yet measured:**

- The full path — browser → live WebSocket → real transcript → gate → execution — has
  **not been run end to end**. What has been verified — locally and now on the deployed
  Worker — is that a real key held by the Worker mints a usable token with both duration
  caps applied (`docs/ARCHITECTURE.md` §5.7).
- The daily-issuance counter's strong consistency is measured **on Cloudflare** (2026-09-03):
  12 concurrent `/api/token` calls, **66 of 66 in-flight interval pairs overlapping**,
  `issued` 16…27 distinct and contiguous, zero duplicates (0.77 s wall vs a 2.26 s serial
  lower bound). That is one concurrency level on one day — not a proof that the property
  holds at arbitrary concurrency, or across DO eviction and migration.

- The registry lint is **weaker than an earlier draft of this README claimed.** It rejects
  `NOT_IMPLEMENTED` checks on irreversible actions, but not `NOT_REQUIRED` ones — and the
  deployed registry is *derived from* the checker table the lint then compares it against,
  so deleting a checker leaves it green (measured, 3/3, 2026-09-03). The registry that does
  refuse is `gate/reference.py`, whose requirements are declared independently. The lint
  also runs per request inside `build_gate()`, not once at startup. Grounding itself is
  enforced in `gate/witness.py`: delete one checker and a tampered amount is still blocked;
  delete two and it is allowed.
- `READ_BACK_CONFIRMED` is an **interface slot with no implementation**, shipped as
  `NOT_REQUIRED` (i.e. skipped). It is a design commitment, not something you can demo.

---

## Demo

- **Live:** <https://voice-action-gate.franciseliang99.workers.dev> — no microphone
  needed: **Use a sample instead** → **Ask the gate** runs a full decision against the
  deployed Worker, and the three ghost buttons reproduce the three refusals — a tampered
  amount, a misheard name, and a bare "dollars" that never says whose dollars.
  `GET /api/health` returns `{"ok": true, "python": "3.13.2"}`.
- **Video:** <https://youtu.be/wE1RtY_qOr0> (unlisted) — 4:16, 1920×1080. The same
  file is in this repo as [`media/demo.mp4`](media/demo.mp4), with
  [`media/demo.srt`](media/demo.srt) as captions. The SRT is not a transcript made
  after the fact: it is the text that was rendered into the narration track, so what
  the video *says* is readable here as plain text. What it *shows* is not.
- **Slides:** [`media/slides.pdf`](media/slides.pdf) · cover image: [`media/cover.png`](media/cover.png)

<!-- 🔴 The first two are written as visible text, not HTML comments. A comment
     renders as nothing, which would make this section look complete while being
     empty -- the exact failure this file's own discipline note warns about. -->

Built for the **AssemblyAI Voice Agent Hackathon** (lablab.ai, Sep 1–30, 2026) with
Universal-Streaming v3 and the Voice Agent API.

## Who built this

I build software with adversarial review loops and deterministic safety gates —
the same discipline this project is *about*, applied to shipping code:
**[Security Gate Pass →](https://franciseliang99-dot.github.io/adversarial-delivery/)**

If the idea of "an irreversible action that cannot run without provable
confirmation" is a problem you have, that page has a way to get in touch.

## License

MIT — full text in [`LICENSE`](LICENSE).
