---
hide:
  - navigation
  - toc
---

<section class="score-hero">
  <div class="score-hero__copy">
    <div class="score-eyebrow">LOCAL BGM GENERATION AGENT</div>
    <h1>Describe the scene. <span>Hear the score.</span></h1>
    <p class="score-hero__lede">
      Turn game context into one focused Stable Audio 3 candidate, listen
      immediately, and shape the next attempt with ordinary language.
    </p>
    <div class="score-actions">
      <a class="score-button score-button--primary" href="getting-started/">Generate a BGM draft →</a>
      <a class="score-button score-button--secondary" href="sa3-local-evaluation/">Set up the local runtime</a>
      <a class="score-button score-button--secondary" href="https://github.com/andyandymike/score-matter">View source on GitHub</a>
    </div>
  </div>
  <div class="score-sheet" aria-hidden="true">
    <div class="score-sheet__label">SCENE DIRECTION / CANDIDATE 01</div>
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
      <span>CONTEXT</span><b>→</b><span>ONE WAV</span><b>→</b><span>LISTEN</span>
    </div>
    <div class="score-receipt"><i></i> local · offline · revisable</div>
  </div>
</section>

<div class="score-metrics">
  <div class="score-metric">
    <strong>1 candidate</strong>
    <span>Per authoring request</span>
  </div>
  <div class="score-metric">
    <strong>0 hidden retries</strong>
    <span>The attempt stays visible</span>
  </div>
  <div class="score-metric">
    <strong>Local WAV</strong>
    <span>Ready for immediate listening</span>
  </div>
</div>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">How ScoreMatter helps</span>
      <h2>Music direction without the ceremony.</h2>
    </div>
    <p>
      The Agent reasons about the scene once, calls the installed generator
      once, and hands the result back to your ears. No evaluation campaign is
      required before the first audible idea.
    </p>
  </div>
  <div class="score-card-grid">
    <article class="score-card">
      <div class="score-card__index">01 / CONTEXT</div>
      <h3>Project-aware direction</h3>
      <p>Scene purpose, pacing, dialogue, UI, world tone, and playback limits become a focused music prompt.</p>
    </article>
    <article class="score-card">
      <div class="score-card__index">02 / ATTEMPT</div>
      <h3>One focused candidate</h3>
      <p>A local SA3 Medium process produces one 44.1 kHz stereo WAV with no hidden retry or candidate pool.</p>
    </article>
    <article class="score-card">
      <div class="score-card__index">03 / LISTEN</div>
      <h3>Revise by hearing</h3>
      <p>Say what is too loud, too sharp, too busy, or emotionally wrong; the next request becomes the next attempt.</p>
    </article>
  </div>
</section>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">Default authoring path</span>
      <h2>Shortest path to useful feedback.</h2>
    </div>
    <p>
      The shipped game later consumes an ordinary audio file. It never needs
      ScoreMatter, Python, the model, or a network connection.
    </p>
  </div>
  <div class="score-flow" role="list" aria-label="ScoreMatter authoring path">
    <div class="score-flow__step" role="listitem"><strong>Scene</strong><span>Gameplay and emotional purpose</span></div>
    <div class="score-flow__step" role="listitem"><strong>Agent</strong><span>One music-direction judgment</span></div>
    <div class="score-flow__step" role="listitem"><strong>Prompt</strong><span>Focused SA3 instructions</span></div>
    <div class="score-flow__step" role="listitem"><strong>Generate</strong><span>One offline local process</span></div>
    <div class="score-flow__step" role="listitem"><strong>WAV</strong><span>Immediate listening candidate</span></div>
    <div class="score-flow__step" role="listitem"><strong>Feedback</strong><span>Your next natural-language change</span></div>
  </div>
</section>

<section class="score-section">
  <div class="score-section__head">
    <div>
      <span class="score-kicker">Honest boundary</span>
      <h2>Generation is not approval.</h2>
    </div>
    <p>
      Human listening outranks technical success. A valid WAV can still be
      quiet, harsh, generic, vocally strange, hard to loop, or wrong for the
      game mix.
    </p>
  </div>
  <div class="score-boundary">
    <div class="score-boundary__badge">EXPERIMENTAL · LOCAL FIRST</div>
    <p>
      ScoreMatter does not automatically approve music, establish rights,
      normalize loudness, build loops, publish releases, or import assets into
      a game. Earlier evidence-kernel, blind-listening, semantic-atlas, and
      Director Phase A work remains available only as optional research. Read
      the <a href="getting-started/">generation guide</a> first; consult the
      <a href="sa3-local-evaluation/">runtime and research boundary</a> only
      when needed.
    </p>
  </div>
  <div class="score-actions">
    <a class="score-button score-button--ink" href="getting-started/">Generate the first draft →</a>
    <a class="score-button score-button--ink" href="m0-contract/">Inspect optional evidence tooling</a>
  </div>
</section>
