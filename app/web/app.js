'use strict';

// The gate needs to know how the connection was opened. We open it with
// format_turns=false and declare exactly that. We never infer it from
// turn_is_formatted -- the meaning of that field is in dispute, and a
// safety-relevant field must not be built out of a disputed one.
const FORMAT_TURNS = false;
const SAMPLE_RATE = 16000;

const $ = (id) => document.getElementById(id);
const els = {
  mic: $('btn-mic'), sample: $('btn-sample'), gate: $('btn-gate'),
  tamper: $('btn-tamper'), status: $('status'), transcript: $('transcript'),
  tmeta: $('tmeta'), verdict: $('verdict'), evidence: $('evidence'),
  action: $('f-action'), amount: $('f-amount'), currency: $('f-currency'), to: $('f-to'),
};

let words = [];        // accumulated AssemblyAI word objects
let ws = null, audio = null, streamRef = null, running = false;

function setStatus(t, cls) {
  els.status.textContent = t;
  els.status.className = 'status ' + (cls || '');
}

// ---------------------------------------------------------------------------
// Transcript rendering. Confidence is shown because it is load-bearing: a word
// under the floor stops being usable evidence.
// ---------------------------------------------------------------------------
function renderTranscript() {
  els.transcript.innerHTML = '';
  for (const w of words) {
    const s = document.createElement('span');
    s.className = 'w' + (w.confidence < 0.9 ? ' low' : '') + (w.word_is_final ? '' : ' partial');
    s.textContent = w.text;
    s.title = `confidence ${w.confidence.toFixed(2)}${w.word_is_final ? '' : ' · not final'}`;
    els.transcript.appendChild(s);
    els.transcript.appendChild(document.createTextNode(' '));
  }
  els.tmeta.textContent = words.length
    ? `${words.length} words · ${words.filter(w => w.confidence < 0.9).length} below 0.90 · format_turns=${FORMAT_TURNS}`
    : '';
}


// A tiny English number-word reader, only good enough for a demo agent.
const NUMWORDS = {
  zero:0, one:1, two:2, three:3, four:4, five:5, six:6, seven:7, eight:8, nine:9,
  ten:10, eleven:11, twelve:12, thirteen:13, fourteen:14, fifteen:15, sixteen:16,
  seventeen:17, eighteen:18, nineteen:19, twenty:20, thirty:30, forty:40,
  fifty:50, sixty:60, seventy:70, eighty:80, ninety:90,
};
function wordNumber(text) {
  let total = 0, current = 0, seen = false;
  for (const raw of text.toLowerCase().split(/[^a-z]+/)) {
    if (raw in NUMWORDS) { current += NUMWORDS[raw]; seen = true; }
    else if (raw === 'hundred') { current = (current || 1) * 100; seen = true; }
    else if (raw === 'thousand') { total += (current || 1) * 1000; current = 0; seen = true; }
  }
  return seen ? [null, String(total + current)] : null;
}

// A deliberately naive extractor standing in for "the agent". It is allowed to
// be wrong -- that is the point. The gate is what makes being wrong safe.
function guessProposal() {
  const text = words.map(w => w.text).join(' ');
  const num = text.match(/\b(\d[\d,]*)\b/) || wordNumber(text);
  // The stand-in agent guesses USD from a bare "dollars". It is allowed to be
  // wrong -- the gate is what makes being wrong safe.
  const cur = /dollar|usd|\$/i.test(text) ? 'USD' : (/euro|eur/i.test(text) ? 'EUR' : '');
  const to = text.match(/\bto\s+([A-Za-z][A-Za-z'-]*)/i);
  if (num) els.amount.value = num[1].replace(/,/g, '');
  if (cur) els.currency.value = cur;
  if (to) els.to.value = to[1];
}

// ---------------------------------------------------------------------------
// Microphone -> PCM16 -> AssemblyAI
// ---------------------------------------------------------------------------
async function startMic() {
  if (running) return stopMic();
  setStatus('requesting token…');
  let cfg;
  try {
    const r = await fetch('/api/token');
    cfg = await r.json();
    if (!r.ok) throw new Error(cfg.error || `HTTP ${r.status}`);
  } catch (e) {
    setStatus('token: ' + e.message, 'bad');
    return;
  }

  try {
    streamRef = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (e) {
    setStatus('microphone denied — use the sample', 'bad');
    return;
  }

  const q = new URLSearchParams({
    token: cfg.token,
    sample_rate: String(SAMPLE_RATE),
    format_turns: String(FORMAT_TURNS),
  });
  ws = new WebSocket(`${cfg.ws_base}?${q}`);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    setStatus(`listening · session capped at ${cfg.max_session_duration_seconds}s`, 'good');
    running = true;
    els.mic.textContent = 'Stop';
  };
  ws.onerror = () => setStatus('websocket error', 'bad');
  ws.onclose = (ev) => {
    running = false;
    els.mic.textContent = 'Start microphone';
    setStatus(ev.reason ? `closed: ${ev.reason}` : 'closed');
    teardownAudio();
  };
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'Turn' && Array.isArray(m.words)) {
      words = m.words.map(w => ({
        text: w.text, start: w.start, end: w.end,
        confidence: w.confidence, word_is_final: w.word_is_final,
      }));
      renderTranscript();
      guessProposal();
    } else if (m.type === 'Error') {
      setStatus(`error ${m.error_code}: ${m.error}`, 'bad');
    }
  };

  audio = new AudioContext({ sampleRate: SAMPLE_RATE });
  const src = audio.createMediaStreamSource(streamRef);
  const node = audio.createScriptProcessor(4096, 1, 1);
  node.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const f32 = e.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(pcm.buffer);
  };
  src.connect(node);
  node.connect(audio.destination);
  audio._nodes = [src, node];
}

function teardownAudio() {
  if (audio) {
    (audio._nodes || []).forEach(n => { try { n.disconnect(); } catch {} });
    try { audio.close(); } catch {}
    audio = null;
  }
  if (streamRef) {
    streamRef.getTracks().forEach(t => t.stop());
    streamRef = null;
  }
}

function stopMic() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify({ type: 'Terminate' })); } catch {}
    ws.close();
  }
  teardownAudio();
  running = false;
  els.mic.textContent = 'Start microphone';
}

// ---------------------------------------------------------------------------
// Sample path -- so a judge with no microphone still sees the whole thing.
// The confidences are the fixture's own; nothing here claims to be a
// measurement of real speech.
// ---------------------------------------------------------------------------
function makeSample(conf) {
  return 'send five hundred US dollars to Alice'.split(' ').map((t, i) => ({
    text: t, start: i * 100, end: i * 100 + 90,
    confidence: conf[t] === undefined ? 0.99 : conf[t], word_is_final: true,
  }));
}

function useSample() {
  words = makeSample({});
  renderTranscript();
  guessProposal();
  setStatus('sample loaded — ask the gate', 'good');
}

// The same sentence with "US" dropped. Nothing else changes -- guessProposal
// still reads "dollars" and guesses USD, which is exactly the point: the word
// "dollars" does not say whose dollars, so the guess has no witness behind it.
// This exists so the act can be shown without a live microphone.
function useSampleBare() {
  words = makeSample({}).filter(w => w.text !== 'US');
  renderTranscript();
  guessProposal();
  setStatus('sample loaded — nobody said WHICH dollars', 'good');
}

// Not a tampered proposal: a tampered RECOGNITION. The recognizer was unsure of
// the name. The floor is what turns "unsure" into "not evidence".
function misheard() {
  words = makeSample({ Alice: 0.71 });
  renderTranscript();
  setStatus('the recognizer is only 0.71 sure of "Alice" — below the 0.90 floor', 'bad');
}

// ---------------------------------------------------------------------------
// Ask the gate
// ---------------------------------------------------------------------------
async function askGate() {
  const proposal = {
    action: els.action.value,
    arguments: {
      amount: els.amount.value,
      currency: els.currency.value,
      to: els.to.value,
    },
  };
  els.verdict.className = 'verdict empty';
  els.verdict.textContent = 'asking…';
  els.evidence.innerHTML = '';

  let r, data;
  try {
    r = await fetch('/api/gate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ words, proposal, format_turns: FORMAT_TURNS }),
    });
    data = await r.json();
  } catch (e) {
    els.verdict.className = 'verdict bad';
    els.verdict.textContent = 'request failed: ' + e.message;
    return;
  }

  if (!r.ok) {
    els.verdict.className = 'verdict bad';
    els.verdict.textContent = `${data.error || 'error'} — not an allow`;
    if (data.detail) els.evidence.textContent = data.detail;
    return;
  }
  renderVerdict(data);
}

function renderVerdict(d) {
  const allow = d.outcome === 'ALLOW';
  els.verdict.className = 'verdict ' + (allow ? 'allow' : 'block');
  els.verdict.textContent = allow
    ? 'ALLOW — every argument was spoken'
    : 'BLOCK';

  const ev = d.evidence || {};
  const parts = [];

  if (!allow && d.reasons && d.reasons.length) {
    parts.push(section('Why it blocked', list(d.reasons)));
  }
  if (allow && d.capability) {
    parts.push(section('Capability minted', pre(JSON.stringify(d.capability.arguments, null, 2))));
  }

  const matched = ev.matched || {};
  const keys = Object.keys(matched);
  if (keys.length) {
    const rows = keys.map(k => {
      const m = matched[k];
      return `${k} = ${m.value} · from words [${m.span[0]}‥${m.span[1]}) “${m.span_text}” · min conf ${m.min_confidence.toFixed(2)} · ${m.decoder_id}`;
    });
    parts.push(section('Grounded in', list(rows)));
  }

  parts.push(section('Policy this decision was made under', list([
    `confidence floor ${ev.confidence_floor}`,
    `max span ${ev.max_span_words} words`,
    `role window ${ev.role_window}`,
    `witnesses ${ev.witness_count} · rejected ${ev.rejected_count}`,
    `provenance: ${ev.provenance.field_name} / formatting_enabled=${ev.provenance.formatting_enabled} / ${ev.provenance.extractor_id}`,
  ])));

  els.evidence.innerHTML = '';
  parts.forEach(p => els.evidence.appendChild(p));
}

function section(title, body) {
  const d = document.createElement('div');
  d.className = 'ev';
  const h = document.createElement('h3');
  h.textContent = title;
  d.appendChild(h);
  d.appendChild(body);
  return d;
}
function list(items) {
  const ul = document.createElement('ul');
  for (const i of items) {
    const li = document.createElement('li');
    li.textContent = i;
    ul.appendChild(li);
  }
  return ul;
}
function pre(text) {
  const p = document.createElement('pre');
  p.textContent = text;
  return p;
}

els.mic.addEventListener('click', startMic);
els.sample.addEventListener('click', useSample);
els.gate.addEventListener('click', askGate);
els.tamper.addEventListener('click', () => {
  const n = parseInt(els.amount.value || '0', 10);
  els.amount.value = String((isNaN(n) ? 50 : n) * 10);
  els.verdict.className = 'verdict empty';
  els.verdict.textContent = 'amount changed — ask the gate again';
});

els.sampleBare = $('btn-sample-bare');
if (els.sampleBare) els.sampleBare.addEventListener('click', useSampleBare);

els.misheard = $('btn-misheard');
if (els.misheard) els.misheard.addEventListener('click', misheard);
