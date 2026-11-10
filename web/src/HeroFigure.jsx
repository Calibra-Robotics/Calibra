import { useEffect, useMemo, useState } from 'react'

// Hero figure: every line is one episode of lerobot/pusht. The counts
// (206 episodes, 175 kept, 31 dropped) come from `calibra analyze
// lerobot/pusht`. The trajectories themselves are schematic: a fixed seeded
// layout so the render is stable, with dropped episodes chosen as the
// tightest members of the densest bundles (near-duplicates).

const TOTAL = 206
const KEPT = 175
const DROPPED = TOTAL - KEPT

const W = 640
const H = 500
const PAD = { l: 46, r: 14, t: 14, b: 36 }
const PW = W - PAD.l - PAD.r
const PH = H - PAD.t - PAD.b

function rng(seed) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Control points in unit space. Three common strategies plus rare detours.
const MODES = [
  { n: 82, pts: [[0.08, 0.55], [0.3, 0.22], [0.62, 0.26], [0.9, 0.48]] },
  { n: 70, pts: [[0.08, 0.55], [0.32, 0.78], [0.64, 0.7], [0.9, 0.48]] },
  { n: 46, pts: [[0.08, 0.55], [0.42, 0.5], [0.6, 0.9], [0.9, 0.48]] },
]
const RARE = [
  [[0.08, 0.55], [0.18, 0.08], [0.78, 0.06], [0.9, 0.48]],
  [[0.08, 0.55], [0.5, 0.12], [0.98, 0.2], [0.9, 0.48]],
  [[0.08, 0.55], [0.12, 0.95], [0.86, 0.94], [0.9, 0.48]],
  [[0.08, 0.55], [0.55, 0.38], [0.72, 0.6], [0.9, 0.48]],
  [[0.08, 0.55], [0.02, 0.2], [0.4, 0.04], [0.9, 0.48]],
  [[0.08, 0.55], [0.7, 0.98], [0.98, 0.78], [0.9, 0.48]],
  [[0.08, 0.55], [0.24, 0.5], [0.46, 0.06], [0.9, 0.48]],
  [[0.08, 0.55], [0.36, 0.96], [0.5, 0.62], [0.9, 0.48]],
]

const toX = (u) => PAD.l + u * PW
const toY = (v) => PAD.t + v * PH

function bezier(p, t) {
  const m = 1 - t
  return [
    m * m * m * p[0][0] + 3 * m * m * t * p[1][0] + 3 * m * t * t * p[2][0] + t * t * t * p[3][0],
    m * m * m * p[0][1] + 3 * m * m * t * p[1][1] + 3 * m * t * t * p[2][1] + t * t * t * p[3][1],
  ]
}

function buildEpisodes() {
  const r = rng(206)
  const gauss = () => (r() + r() + r() - 1.5) / 1.5
  const eps = []

  MODES.forEach((mode, m) => {
    for (let k = 0; k < mode.n; k += 1) {
      const spread = 0.008 + r() * 0.05
      const pts = mode.pts.map(([x, y], i) =>
        i === 0 || i === 3 ? [x + gauss() * 0.02, y + gauss() * 0.04] : [x + gauss() * spread * 2, y + gauss() * spread * 3]
      )
      eps.push({ mode: m, pts, spread })
    }
  })
  RARE.forEach((pts) => eps.push({ mode: -1, pts, spread: 1 }))

  // Deterministic shuffle so episode ids are not grouped by mode.
  for (let i = eps.length - 1; i > 0; i -= 1) {
    const j = Math.floor(r() * (i + 1))
    ;[eps[i], eps[j]] = [eps[j], eps[i]]
  }

  // Near-duplicates: the tightest members of the two densest bundles.
  const dropped = new Set(
    eps
      .map((e, i) => ({ i, e }))
      .filter(({ e }) => e.mode === 0 || e.mode === 1)
      .sort((a, b) => a.e.spread - b.e.spread)
      .slice(0, DROPPED)
      .map(({ i }) => i)
  )

  // One kept episode from the third bundle carries a jerk spike.
  const jerkIdx = eps.findIndex((e, i) => e.mode === 2 && !dropped.has(i) && e.spread > 0.03)

  return eps.map((e, i) => {
    const steps = 44
    const pts = []
    const wob = r() * 6.28
    for (let s = 0; s <= steps; s += 1) {
      const t = s / steps
      let [x, y] = bezier(e.pts, t)
      y += Math.sin(t * 9 + wob) * 0.004
      if (i === jerkIdx && s > 26 && s < 31) y += (s % 2 ? -1 : 1) * 0.035
      pts.push([toX(x), toY(y)])
    }
    const d = pts.map(([x, y], s) => `${s ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join('')
    const kind = dropped.has(i) ? 'drop' : e.mode === -1 ? 'rare' : i === jerkIdx ? 'jerk' : 'keep'
    return { id: i, d, kind, pts, mode: e.mode }
  })
}

const pad3 = (n) => String(n).padStart(3, '0')

function useCountdown(active, from, to, ms) {
  const [value, setValue] = useState(from)
  useEffect(() => {
    if (!active) return undefined
    let raf
    const start = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - start) / ms)
      setValue(Math.round(from - (from - to) * (1 - (1 - p) ** 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, from, to, ms])
  return value
}

export default function HeroFigure() {
  const episodes = useMemo(buildEpisodes, [])
  const [curated, setCurated] = useState(false)

  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setCurated(true)
      return undefined
    }
    const t = setTimeout(() => setCurated(true), 2300)
    return () => clearTimeout(t)
  }, [])

  const kept = useCountdown(curated, TOTAL, KEPT, 1100)

  const callouts = useMemo(() => {
    // Labels sit on: a dropped episode in the lower bundle, the flagged
    // episode, and the top-most rare detour, so they never overlap.
    const drop = episodes.find((e) => e.kind === 'drop' && e.mode === 1 && e.id > 40)
    const twin = episodes.find((e) => e.kind === 'keep' && e.mode === 1 && e.id > 100)
    const jerk = episodes.find((e) => e.kind === 'jerk')
    const rare = episodes
      .filter((e) => e.kind === 'rare')
      .reduce((a, b) => (b.pts[22][1] < a.pts[22][1] ? b : a))
    return [
      { ep: drop, at: 14, dx: -8, dy: 40, verdict: 'DROP', note: `near-duplicate of ep ${pad3(twin.id)}` },
      { ep: jerk, at: 28, dx: 20, dy: -44, verdict: 'KEEP', note: 'jerk spike, within baseline' },
      { ep: rare, at: 22, dx: 14, dy: -20, verdict: 'KEEP', note: 'rare strategy' },
    ]
  }, [episodes])

  const xTicks = [0, 128, 256, 384, 512]

  return (
    <figure className={`hf${curated ? ' is-curated' : ''}`}>
      <div className="hf-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${TOTAL} episode trajectories from lerobot/pusht; ${DROPPED} near-duplicates dropped, ${KEPT} kept`}>
          <g className="hf-axes" aria-hidden="true">
            {xTicks.map((v) => {
              const x = PAD.l + (v / 512) * PW
              const y = PAD.t + (1 - v / 512) * PH
              return (
                <g key={v}>
                  <line x1={x} x2={x} y1={PAD.t} y2={PAD.t + PH} className="hf-gridline" />
                  <line x1={PAD.l} x2={PAD.l + PW} y1={y} y2={y} className="hf-gridline" />
                  <text x={x} y={H - 14} textAnchor="middle">{v}</text>
                  <text x={PAD.l - 10} y={y + 3} textAnchor="end">{v}</text>
                </g>
              )
            })}
          </g>

          <g className="hf-lines" aria-hidden="true">
            {episodes.map((e) => (
              <path
                key={e.id}
                d={e.d}
                pathLength="1"
                className={`hf-ep ${e.kind}`}
                style={{ '--i': e.id }}
              />
            ))}
          </g>

          <rect className="hf-scan" x={PAD.l} y={PAD.t} width="2" height={PH} aria-hidden="true" />

          <g className="hf-callouts" aria-hidden="true">
            {callouts.map((c, n) => {
              const [px, py] = c.ep.pts[c.at]
              const tx = px + c.dx
              const ty = py + c.dy
              const left = tx > W * 0.62
              return (
                <g key={c.ep.id} className={`hf-callout hf-callout-${n}`}>
                  <circle cx={px} cy={py} r="4.5" />
                  <line x1={px} y1={py} x2={tx} y2={ty} />
                  <text x={tx + (left ? -6 : 6)} y={ty - 4} textAnchor={left ? 'end' : 'start'} className="hf-callout-id">
                    ep {pad3(c.ep.id)} <tspan className={c.verdict === 'DROP' ? 'v-drop' : 'v-keep'}>{c.verdict}</tspan>
                  </text>
                  <text x={tx + (left ? -6 : 6)} y={ty + 11} textAnchor={left ? 'end' : 'start'} className="hf-callout-note">
                    {c.note}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
      </div>

      <div className="hf-readout" aria-live="off">
        <div>
          <span>dataset</span>
          <strong>lerobot/pusht</strong>
        </div>
        <div>
          <span>episodes</span>
          <strong>{TOTAL}</strong>
        </div>
        <div className="hf-readout-kept">
          <span>train on</span>
          <strong>{kept}</strong>
        </div>
        <div>
          <span>dropped</span>
          <strong>{TOTAL - kept}</strong>
        </div>
      </div>

      <figcaption>
        <b>Fig. 1</b> Each line is one demonstration. Calibra drops near-duplicates, keeps rare
        strategies, and gives a reason for every call. Counts from <code>calibra analyze lerobot/pusht</code>;
        trajectories schematic.
      </figcaption>
    </figure>
  )
}
