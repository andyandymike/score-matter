---
hide:
  - navigation
  - toc
---

<section class="score-hero">
  <div class="score-hero__copy">
    <div class="score-eyebrow">M0 · Evidence kernel</div>
    <h1>Compose with <span>evidence.</span></h1>
    <p class="score-hero__lede">
      Auditable, local-first AI-assisted BGM authoring for games—built around
      typed requests, immutable artifacts, reproducible receipts, and explicit
      human approval boundaries.
    </p>
    <div class="score-actions">
      <a class="score-button score-button--primary" href="getting-started/">Run the M0 path →</a>
      <a class="score-button score-button--secondary" href="sa3-local-evaluation/">Inspect the SA3 evaluation lane</a>
      <a class="score-button score-button--secondary" href="https://github.com/andyandymike/score-matter">View source on GitHub</a>
    </div>
  </div>
  <div class="score-sheet" aria-hidden="true">
    <div class="score-sheet__label">AUTHORING TRACE / M0</div>
    <div class="score-staff">
      <span class="score-staff__line"></span>
      <span class="score-staff__line"></span>
      <span class="score-staff__line"></span>
      <span class="score-staff__line"></span>
      <span class="score-staff__line"></span>
      <i class="score-note score-note--one"></i>
      <i class="score-note score-note--two"></i>
      <i class="score-note score-note--three"></i>
      <i class="score-note score-note--four"></i>
      <i class="score-measure score-measure--one"></i>
      <i class="score-measure score-measure--two"></i>
    </div>
    <div class="score-ledger">
      <span>BRIEF</span><b>→</b><span>ARTIFACT</span><b>→</b><span>REPLAY</span>
    </div>
    <div class="score-receipt"><i></i> digest-bound receipt</div>
  </div>
</section>

<div class="score-metrics">
  <div class="score-metric">
    <strong>0 model calls</strong>
    <span>Inside the current M0 contract</span>
  </div>
  <div class="score-metric">
    <strong>RFC 8785</strong>
    <span>Canonical JSON evidence</span>
  </div>
  <div class="score-metric">
    <strong>3 providers</strong>
    <span>Mock, manual, and replay</span>
  </div>
</div>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">Why ScoreMatter</span>
      <h2>Creative tools need a proof boundary.</h2>
    </div>
    <p>
      ScoreMatter keeps replaceable music providers behind contracts that say
      exactly what was requested, what bytes were observed, and what still
      requires a human decision.
    </p>
  </div>
  <div class="score-card-grid">
    <article class="score-card">
      <div class="score-card__index">01 / CONTRACT</div>
      <h3>Typed before generated</h3>
      <p>Strict Brief, Plan, review, and resolved-request schemas reject stale bindings and unknown authority-bearing fields.</p>
    </article>
    <article class="score-card">
      <div class="score-card__index">02 / LINEAGE</div>
      <h3>Artifacts stay immutable</h3>
      <p>Content-addressed audio, manifests, and run receipts preserve exact byte identity without pretending to prove opaque provider internals.</p>
    </article>
    <article class="score-card">
      <div class="score-card__index">03 / AUTHORITY</div>
      <h3>Review stays human</h3>
      <p>Schema validity and replay integrity never become creative, listening, rights, or release approval.</p>
    </article>
  </div>
</section>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">Evidence path</span>
      <h2>Every handoff remains inspectable.</h2>
    </div>
    <p>
      M0 proves the authoring spine independently of any real music model.
      A shipped game consumes ordinary audio and manifests, never ScoreMatter itself.
    </p>
  </div>
  <div class="score-flow" role="list" aria-label="ScoreMatter evidence path">
    <div class="score-flow__step" role="listitem"><strong>Brief</strong><span>Intent and bounded requirements</span></div>
    <div class="score-flow__step" role="listitem"><strong>Plan</strong><span>Reviewed authoring decisions</span></div>
    <div class="score-flow__step" role="listitem"><strong>Request</strong><span>Provider-ready resolved input</span></div>
    <div class="score-flow__step" role="listitem"><strong>Provider</strong><span>Replaceable execution boundary</span></div>
    <div class="score-flow__step" role="listitem"><strong>Artifact</strong><span>Quarantined immutable bytes</span></div>
    <div class="score-flow__step" role="listitem"><strong>Receipt</strong><span>Observed lineage and facts</span></div>
    <div class="score-flow__step" role="listitem"><strong>Replay</strong><span>Integrity without regeneration</span></div>
  </div>
</section>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">Current boundary</span>
      <h2>Keep the kernel independent of the model.</h2>
    </div>
    <p>
      The public slice is deliberately narrow: deterministic fixture audio,
      bounded manual WAV ingestion, immutable storage, and replay verification.
    </p>
  </div>
  <div class="score-boundary">
    <div class="score-boundary__badge">EXPERIMENTAL M0</div>
    <p>
      ScoreMatter does not yet generate useful BGM, approve loops or mix quality,
      establish rights, publish releases, or integrate with a game runtime.
      A separate machine-local SA3 Medium installation and generic frozen-pilot
      orchestrator form an external evaluation lane, not a fourth built-in
      provider. Read the
      <a href="m0-contract/">M0 public contract</a> and
      <a href="sa3-local-evaluation/">SA3 evaluation boundary</a> before relying on either path.
    </p>
  </div>
  <div class="score-actions">
    <a class="score-button score-button--ink" href="getting-started/">Open the getting-started guide →</a>
    <a class="score-button score-button--ink" href="sa3-local-evaluation/">Open the SA3 evaluation guide →</a>
  </div>
</section>
