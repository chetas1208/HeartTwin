"use client";

/*
 * CONTRACT: owns the 3D cardiac twin viewport. A premium real-time
 *   react-three-fiber scene: a procedural, anatomically-suggestive heart mesh
 *   that BEATS at the case's heart rate (driven by the electrophysiology
 *   rr_interval, falling back to summary heart_rate_bpm), with contraction
 *   amplitude scaled by ejection fraction. An electrical-activation wave sweeps
 *   the myocardium each cycle (crimson body, cyan leading edge), blood-flow
 *   particles stream through the field, and a damage / low-function zone is
 *   painted onto the wall when EF is depressed.
 * READS from store: visualization (summary.heart_rate_bpm, summary.ef_pct,
 *   electrophysiology.rr_interval_ms), state.tissue_state (scar_fraction,
 *   damage_zone_location), status.
 * All continuous values are driven by refs / motion values inside useFrame,
 *   never React state. Colors come from the OKLCH design tokens (resolved once
 *   from the live stylesheet). SSR-safe: the Canvas is loaded via next/dynamic
 *   with ssr:false. Respects prefers-reduced-motion (the beat slows to a calm,
 *   near-still diastole hold).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  useMotionValue,
  useReducedMotion,
  type MotionValue,
} from "motion/react";
import {
  AdditiveBlending,
  BackSide,
  BufferAttribute,
  BufferGeometry,
  Color,
  IcosahedronGeometry,
  MathUtils,
  Points,
  ShaderMaterial,
  Vector3,
  type Mesh,
} from "three";
import { Heart, Waveform } from "@phosphor-icons/react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/Panel";
import { useHeartTwinStore } from "@/lib/store";

/* ------------------------------------------------------------------ */
/*  Palette: resolve the OKLCH design tokens once, in the browser, so   */
/*  the GPU materials stay locked to the console's color language.      */
/* ------------------------------------------------------------------ */

interface ScenePalette {
  accent: Color; // systolic crimson
  accentDim: Color;
  signal: Color; // signal cyan (activation leading edge / agents)
  ecg: Color; // recovery green
  warn: Color; // amber, used only for the damage seam
  ink: Color;
  ground: Color; // near-black clinical ground
}

const FALLBACK_PALETTE: Record<keyof ScenePalette, string> = {
  accent: "oklch(0.62 0.2 18)",
  accentDim: "oklch(0.5 0.16 18)",
  signal: "oklch(0.78 0.13 195)",
  ecg: "oklch(0.79 0.16 150)",
  warn: "oklch(0.82 0.15 80)",
  ink: "oklch(0.97 0.005 250)",
  ground: "oklch(0.16 0.018 250)",
};

/** Read a CSS custom property, falling back to a known token value. */
function readToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

function resolvePalette(): ScenePalette {
  // Color (three r150+) parses oklch() / css color strings directly.
  const make = (token: string, fallback: string) =>
    new Color(readToken(token, fallback));
  return {
    accent: make("--ht-accent", FALLBACK_PALETTE.accent),
    accentDim: make("--ht-accent-dim", FALLBACK_PALETTE.accentDim),
    signal: make("--ht-signal", FALLBACK_PALETTE.signal),
    ecg: make("--ht-ecg", FALLBACK_PALETTE.ecg),
    warn: make("--ht-warn", FALLBACK_PALETTE.warn),
    ink: make("--ht-ink", FALLBACK_PALETTE.ink),
    ground: make("--ht-bg", FALLBACK_PALETTE.ground),
  };
}

/* ------------------------------------------------------------------ */
/*  Geometry: a procedural, anatomically-suggestive heart.             */
/*  A unit icosphere is warped by a heart radial profile: a top cleft   */
/*  (the two atria), bulged ventricles, a tapered apex, and a slight    */
/*  forward lean. Normals are recomputed so lighting reads cleanly.     */
/* ------------------------------------------------------------------ */

function buildHeartGeometry(): BufferGeometry {
  const base = new IcosahedronGeometry(1, 24);
  const pos = base.attributes.position as BufferAttribute;
  const v = new Vector3();
  const count = pos.count;

  for (let i = 0; i < count; i += 1) {
    v.fromBufferAttribute(pos, i).normalize();
    const { x, y, z } = v;

    // Spherical-ish parameters for the radial heart profile.
    const up = y; // -1 (apex) .. +1 (base/atria)

    // Lateral bulge: two ventricular lobes, widest just below the equator.
    const lobe = 1 + 0.16 * Math.cos(Math.atan2(x, z) * 2) * (1 - up * up);

    // Top cleft between the lobes (the dimple between the great vessels).
    const cleft = up > 0.45 ? -0.42 * Math.pow((up - 0.45) / 0.55, 1.4) : 0;
    const cleftLateral =
      up > 0.3 ? 1 - 0.34 * Math.exp(-Math.pow(x * 2.4, 2)) * (up - 0.3) : 1;

    // Apex: pinch the bottom to a soft point and pull it forward.
    const apex = up < -0.2 ? 1 + 0.34 * (up + 0.2) : 1; // shrinks toward base
    const apexForward = up < 0 ? -0.22 * up * up : 0;

    // Gentle anteroposterior flattening so it is not a billiard ball.
    const depth = 0.86;

    let r = lobe * cleftLateral * apex;
    r = Math.max(0.18, r);

    v.x = x * r;
    v.y = (y + cleft) * 1.04;
    v.z = z * r * depth + apexForward;

    pos.setXYZ(i, v.x, v.y, v.z);
  }

  pos.needsUpdate = true;
  base.computeVertexNormals();
  base.center();
  // Normalize overall scale to a stable footprint.
  base.scale(0.92, 0.92, 0.92);
  return base;
}

/* ------------------------------------------------------------------ */
/*  Heart material: physically-lit body + an electrical activation wave */
/*  that sweeps apex -> base each cardiac cycle, plus a damage seam that */
/*  appears where EF is low. Written as one shader so the wave, the      */
/*  fresnel rim, and the scar mask composite correctly.                 */
/* ------------------------------------------------------------------ */

const heartVertex = /* glsl */ `
  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying float vUp;       // -1 apex .. +1 base, in object space
  varying vec3 vObjPos;

  void main() {
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vViewDir = normalize(cameraPosition - worldPos.xyz);
    vUp = position.y;
    vObjPos = position;
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

const heartFragment = /* glsl */ `
  precision highp float;

  uniform vec3  uMuscle;     // base myocardium color
  uniform vec3  uMuscleDeep; // shaded creases
  uniform vec3  uWave;       // activation wave body (crimson)
  uniform vec3  uWaveEdge;   // activation leading edge (cyan)
  uniform vec3  uScar;       // damage seam tint (amber)
  uniform vec3  uRim;        // fresnel rim (ink/cyan mix)
  uniform float uWavePos;    // 0..1 sweep position apex->base
  uniform float uWaveGain;   // amplitude of the wave glow (contractility)
  uniform float uScarAmount; // 0..1 how much damage to paint
  uniform vec3  uScarDir;    // unit direction of the damage zone
  uniform float uBeat;       // 0..1 systolic intensity for emissive lift

  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying float vUp;
  varying vec3 vObjPos;

  void main() {
    vec3 N = normalize(vNormalW);
    vec3 V = normalize(vViewDir);

    // --- base lighting: two key fills baked as directional-ish terms ---
    vec3 key = normalize(vec3(0.55, 0.7, 0.8));
    vec3 fill = normalize(vec3(-0.7, -0.2, -0.4));
    float kd = max(dot(N, key), 0.0);
    float fd = max(dot(N, fill), 0.0) * 0.45;
    float ambient = 0.28;

    vec3 base = mix(uMuscleDeep, uMuscle, kd);
    base += uMuscle * (fd + ambient);

    // subtle specular sheen (wet myocardium)
    vec3 H = normalize(key + V);
    float spec = pow(max(dot(N, H), 0.0), 48.0) * 0.5;

    // --- fresnel rim, lifts the silhouette out of the dark ground ---
    float fres = pow(1.0 - max(dot(N, V), 0.0), 2.6);

    // --- electrical activation wave: a band that sweeps apex(0)->base(1) ---
    float t = (vUp + 1.0) * 0.5;              // 0 apex .. 1 base
    float d = t - uWavePos;
    float band = exp(-pow(d * 9.0, 2.0));     // crimson body of the wave
    float edge = exp(-pow((d - 0.045) * 26.0, 2.0)); // cyan leading edge
    float refractory = smoothstep(0.0, 0.35, uWavePos - t) * 0.18; // afterglow

    vec3 wave = uWave * band * 1.0 + uWaveEdge * edge * 0.9;
    wave += uWave * refractory;
    wave *= uWaveGain;

    // --- damage / low-function zone: a soft, dim, amber-seamed patch ---
    float facing = max(dot(normalize(vObjPos), normalize(uScarDir)), 0.0);
    float scarMask = smoothstep(0.45, 0.92, facing) * uScarAmount;
    // hypokinetic tissue reads darker and stiffer, with a faint amber seam.
    vec3 scarred = mix(base, base * 0.32, scarMask);
    float seam = smoothstep(0.55, 0.7, facing) * (1.0 - smoothstep(0.7, 0.86, facing));
    scarred += uScar * seam * uScarAmount * 0.9;
    // the wave is conducted poorly through scar (block / low amplitude).
    wave *= (1.0 - scarMask * 0.85);

    vec3 color = scarred;
    color += spec * vec3(0.7);
    color += uRim * fres * (0.4 + 0.35 * uBeat);
    color += wave;
    // systolic warmth: the whole muscle glows fractionally hotter at contraction
    color += uMuscle * uBeat * 0.1 * (1.0 - scarMask);

    // Reinhard tone map so additive highlights roll off instead of clipping to
    // white (this material bypasses three's tone-mapping chunks), then sRGB.
    color = color / (color + vec3(0.85));
    color = pow(color, vec3(1.0 / 2.2));

    gl_FragColor = vec4(color, 1.0);
  }
`;

interface HeartUniforms {
  uMuscle: { value: Color };
  uMuscleDeep: { value: Color };
  uWave: { value: Color };
  uWaveEdge: { value: Color };
  uScar: { value: Color };
  uRim: { value: Color };
  uWavePos: { value: number };
  uWaveGain: { value: number };
  uScarAmount: { value: number };
  uScarDir: { value: Vector3 };
  uBeat: { value: number };
}

/* ------------------------------------------------------------------ */
/*  Cardiac timing helpers.                                            */
/* ------------------------------------------------------------------ */

/** Period of one cardiac cycle in seconds, from rr_interval or bpm. */
function cyclePeriod(rrMs: number | null | undefined, bpm: number): number {
  if (rrMs && rrMs > 200 && rrMs < 3000) return rrMs / 1000;
  if (bpm > 20 && bpm < 260) return 60 / bpm;
  return 60 / 72; // resting default while idle
}

/**
 * A physiologic-ish contraction envelope over phase 0..1: a fast systolic
 * upstroke, a brief ejection plateau, then an eased diastolic relaxation.
 * Returns 0 (full diastole) .. 1 (peak systole).
 */
function contractionEnvelope(phase: number): number {
  const p = phase % 1;
  if (p < 0.12) {
    // isovolumic + rapid ejection: steep ease-out rise
    const x = p / 0.12;
    return 1 - Math.pow(1 - x, 3);
  }
  if (p < 0.32) {
    // reduced ejection: hold near peak with a slight decline
    const x = (p - 0.12) / 0.2;
    return 1 - 0.18 * x;
  }
  // diastole: smooth relaxation back to rest
  const x = (p - 0.32) / 0.68;
  return 0.82 * Math.pow(1 - x, 1.8);
}

/* ------------------------------------------------------------------ */
/*  The beating heart + activation wave + scar overlay.                */
/* ------------------------------------------------------------------ */

interface BeatInputs {
  /** beat-rate target in beats/sec; the loop eases its cadence toward this. */
  beatHzMv: MotionValue<number>;
  /** ejection fraction 0..1 (drives contraction amplitude). */
  ef: number;
  /** 0..1 damage amount (low EF / scar). */
  damage: number;
  /** unit direction of the damage zone in object space. */
  damageDir: Vector3;
  /** whether the case is live (vs idle). */
  live: boolean;
  /** whether to animate the beat. */
  animate: boolean;
}

/** Build the heart shader material + its strongly-typed uniforms together. */
function makeHeartMaterial(palette: ScenePalette): ShaderMaterial {
  const uniforms: HeartUniforms = {
    uMuscle: { value: palette.accent.clone() },
    uMuscleDeep: { value: palette.accentDim.clone().multiplyScalar(0.55) },
    uWave: { value: palette.accent.clone().multiplyScalar(1.6) },
    uWaveEdge: { value: palette.signal.clone().multiplyScalar(1.5) },
    uScar: { value: palette.warn.clone() },
    uRim: { value: palette.signal.clone().lerp(palette.ink, 0.4) },
    uWavePos: { value: 0 },
    uWaveGain: { value: 0.9 },
    uScarAmount: { value: 0 },
    uScarDir: { value: new Vector3(0.6, -0.4, 0.7).normalize() },
    uBeat: { value: 0 },
  };
  return new ShaderMaterial({
    vertexShader: heartVertex,
    fragmentShader: heartFragment,
    uniforms: uniforms as unknown as Record<string, { value: unknown }>,
  });
}

/** Additive fresnel glow shell, a headless-safe bloom substitute. */
function makeGlowMaterial(palette: ScenePalette): ShaderMaterial {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    side: BackSide,
    uniforms: {
      uColor: { value: palette.accent.clone() },
      uOpacity: { value: 0.0 },
    },
    vertexShader: /* glsl */ `
      varying vec3 vN;
      varying vec3 vV;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - wp.xyz);
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform float uOpacity;
      varying vec3 vN;
      varying vec3 vV;
      void main() {
        float fres = pow(1.0 - max(dot(normalize(vN), normalize(vV)), 0.0), 3.5);
        vec3 c = pow(uColor, vec3(1.0 / 2.2));
        gl_FragColor = vec4(c, fres * uOpacity);
      }
    `,
  });
}

function HeartBody({ inputs }: { inputs: BeatInputs }) {
  const mesh = useRef<Mesh>(null);
  const glow = useRef<Mesh>(null);

  // Construct GPU resources once. Reading these memoized values in JSX is fine;
  // per-frame mutation goes through the mesh refs (mesh.current.material) so the
  // React Compiler treats it as ref mutation, not memo mutation.
  const palette = useMemo(() => resolvePalette(), []);
  const geometry = useMemo(() => buildHeartGeometry(), []);
  const material = useMemo(() => makeHeartMaterial(palette), [palette]);
  const glowMaterial = useMemo(() => makeGlowMaterial(palette), [palette]);

  // Smoothed, frame-driven values (never React state).
  const phase = useRef(0);
  const beatHzSmoothed = useRef(1.2);
  const efSmoothed = useRef(0.6);
  const damageSmoothed = useRef(0);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
      glowMaterial.dispose();
    },
    [geometry, material, glowMaterial],
  );

  useFrame((_, rawDelta) => {
    const m = mesh.current;
    if (!m) return;
    const mat = m.material as ShaderMaterial;
    const delta = Math.min(rawDelta, 0.05); // clamp tab-switch jumps
    const u = mat.uniforms;

    // Ease the beat rate toward the store target so a heart-rate change ramps
    // (catecholamine-like) instead of snapping the cadence.
    beatHzSmoothed.current = MathUtils.damp(
      beatHzSmoothed.current,
      inputs.beatHzMv.get(),
      3,
      delta,
    );

    // Advance the cardiac phase by real time at the current beat rate.
    if (inputs.animate) {
      phase.current = (phase.current + delta * beatHzSmoothed.current) % 1;
    }

    // Smooth EF and damage so store changes ease in rather than snap.
    efSmoothed.current = MathUtils.damp(efSmoothed.current, inputs.ef, 4, delta);
    damageSmoothed.current = MathUtils.damp(
      damageSmoothed.current,
      inputs.damage,
      4,
      delta,
    );

    // Contraction amplitude scales with EF: a healthy heart (EF ~0.6+) moves
    // visibly; a depressed heart barely squeezes. Bounded so it always reads.
    const efAmp = MathUtils.clamp(efSmoothed.current, 0.08, 0.72);
    const env = inputs.animate
      ? contractionEnvelope(phase.current)
      : contractionEnvelope(0); // reduced-motion: rest at relaxed diastole

    // Systole shrinks the chamber: scale down + a slight long-axis shortening.
    const squeeze = env * (0.05 + efAmp * 0.16);
    m.scale.set(1 - squeeze * 1.05, 1 - squeeze * 0.78, 1 - squeeze * 1.05);

    // A slow, dignified rotation so the form reads as volumetric, not a logo.
    if (inputs.animate) m.rotation.y += delta * 0.16;

    // Drive the shader.
    u.uWavePos.value = phase.current; // wave runs apex->base each cycle
    u.uWaveGain.value = (0.45 + efAmp * 1.1) * (inputs.live ? 1 : 0.55);
    u.uScarAmount.value = damageSmoothed.current;
    (u.uScarDir.value as Vector3).copy(inputs.damageDir);
    u.uBeat.value = env;

    // Glow shell breathes with systole.
    const g = glow.current;
    if (g) {
      g.scale.copy(m.scale).multiplyScalar(1.08);
      g.rotation.copy(m.rotation);
      const gm = (g.material as ShaderMaterial).uniforms;
      gm.uOpacity.value = (0.08 + env * 0.2) * (inputs.live ? 1 : 0.55);
      // glow tints toward amber as damage rises (clinical alarm, restrained).
      (gm.uColor.value as Color)
        .copy(palette.accent)
        .lerp(palette.warn, damageSmoothed.current * 0.5);
    }
  });

  return (
    <group>
      <mesh ref={mesh} geometry={geometry} material={material} />
      <mesh ref={glow} geometry={geometry} material={glowMaterial} />
    </group>
  );
}

/* ------------------------------------------------------------------ */
/*  Blood-flow particles: a bounded field streaming around the heart,   */
/*  additive-blended so it reads as luminous plasma, not dots.          */
/* ------------------------------------------------------------------ */

const PARTICLE_COUNT = 520;

/** Random per-particle seeds: [radius, angle, height, speed] x N. */
function makeFlowSeeds(): Float32Array {
  const s = new Float32Array(PARTICLE_COUNT * 4);
  for (let i = 0; i < PARTICLE_COUNT; i += 1) {
    s[i * 4 + 0] = 1.15 + Math.random() * 0.95; // radius
    s[i * 4 + 1] = Math.random() * Math.PI * 2; // angle
    s[i * 4 + 2] = (Math.random() - 0.5) * 2.4; // height
    s[i * 4 + 3] = 0.18 + Math.random() * 0.5; // speed
  }
  return s;
}

function makeFlowMaterial(palette: ScenePalette): ShaderMaterial {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    uniforms: {
      uColorA: { value: palette.accent.clone() },
      uColorB: { value: palette.signal.clone() },
      uSize: { value: 14 },
      uOpacity: { value: 0.0 },
      uPulse: { value: 0 },
    },
    vertexShader: /* glsl */ `
      uniform float uSize;
      uniform float uPulse;
      varying float vMix;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        // brighter the closer to the chamber (inner stream = ejection)
        vMix = clamp((length(position.xz) - 1.1) / 1.0, 0.0, 1.0);
        float sizePulse = 1.0 + uPulse * 0.6 * (1.0 - vMix);
        gl_PointSize = uSize * sizePulse * (1.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColorA;
      uniform vec3 uColorB;
      uniform float uOpacity;
      varying float vMix;
      void main() {
        vec2 uv = gl_PointCoord - 0.5;
        float d = length(uv);
        if (d > 0.5) discard;
        float soft = smoothstep(0.5, 0.0, d);
        vec3 c = pow(mix(uColorB, uColorA, vMix), vec3(1.0 / 2.2));
        gl_FragColor = vec4(c, soft * uOpacity);
      }
    `,
  });
}

function BloodFlow({ inputs }: { inputs: BeatInputs }) {
  const points = useRef<Points>(null);
  const palette = useMemo(() => resolvePalette(), []);

  // Per-particle seeds (radius, angle, height, speed). Generated once via a
  // state initializer (random is impure, so it cannot live in useMemo) and
  // never changed; the geometry below is mutated through points.current.
  const [seeds] = useState(makeFlowSeeds);

  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i += 1) {
      const radius = seeds[i * 4 + 0];
      const angle = seeds[i * 4 + 1];
      positions[i * 3 + 0] = Math.cos(angle) * radius;
      positions[i * 3 + 1] = seeds[i * 4 + 2];
      positions[i * 3 + 2] = Math.sin(angle) * radius;
    }
    g.setAttribute("position", new BufferAttribute(positions, 3));
    return g;
  }, [seeds]);

  const material = useMemo(() => makeFlowMaterial(palette), [palette]);

  const elapsed = useRef(0);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );

  useFrame((_, rawDelta) => {
    const p = points.current;
    if (!p) return;
    const delta = Math.min(rawDelta, 0.05);
    if (inputs.animate) elapsed.current += delta;

    const attr = p.geometry.attributes.position as BufferAttribute;
    const arr = attr.array as Float32Array;
    // Ejection pulse: particles surge outward briefly on systole.
    const env = inputs.animate
      ? contractionEnvelope((elapsed.current * inputs.beatHzMv.get()) % 1)
      : 0;
    const surge = env * 0.5;

    for (let i = 0; i < PARTICLE_COUNT; i += 1) {
      const radius = seeds[i * 4 + 0];
      const baseAngle = seeds[i * 4 + 1];
      const height = seeds[i * 4 + 2];
      const speed = seeds[i * 4 + 3];
      const a = baseAngle + elapsed.current * speed;
      const r = radius + surge * (2.0 - radius);
      arr[i * 3 + 0] = Math.cos(a) * r;
      arr[i * 3 + 1] =
        height + Math.sin(elapsed.current * speed + baseAngle) * 0.12;
      arr[i * 3 + 2] = Math.sin(a) * r;
    }
    attr.needsUpdate = true;

    const u = (p.material as ShaderMaterial).uniforms;
    u.uOpacity.value = (inputs.live ? 0.5 : 0.22) + env * 0.25;
    u.uPulse.value = env;
  });

  return <points ref={points} geometry={geometry} material={material} />;
}

/* ------------------------------------------------------------------ */
/*  Lighting + camera framing.                                         */
/* ------------------------------------------------------------------ */

function Rig({ animate }: { animate: boolean }) {
  const { camera } = useThree();
  const target = useRef(new Vector3(0, 0, 4.1));
  // Mutate the camera through a ref so the per-frame writes are ref mutations.
  const cam = useRef(camera);

  useEffect(() => {
    cam.current = camera;
    cam.current.position.set(0.4, 0.25, 4.1);
    cam.current.lookAt(0, -0.05, 0);
  }, [camera]);

  useFrame(({ pointer }, rawDelta) => {
    if (!animate) return;
    const c = cam.current;
    const delta = Math.min(rawDelta, 0.05);
    // A restrained parallax: the camera leans toward the pointer, eased.
    target.current.x = MathUtils.damp(
      target.current.x,
      pointer.x * 0.55 + 0.3,
      3,
      delta,
    );
    target.current.y = MathUtils.damp(
      target.current.y,
      pointer.y * 0.4 + 0.2,
      3,
      delta,
    );
    c.position.x = target.current.x;
    c.position.y = target.current.y;
    c.lookAt(0, -0.05, 0);
  });

  return null;
}

/* ------------------------------------------------------------------ */
/*  Scene contents: subscribes to the store, marshals inputs into a ref */
/*  for the animation loop, then renders the heart + flow + lighting.   */
/* ------------------------------------------------------------------ */

const DAMAGE_ZONE_DIRECTION: Record<string, Vector3> = {
  anterior: new Vector3(0, 0.1, 1),
  inferior: new Vector3(0, -0.9, 0.2),
  lateral: new Vector3(1, 0, 0.1),
  septal: new Vector3(-0.6, 0, 0.5),
  apical: new Vector3(0, -1, 0.1),
  posterior: new Vector3(0, 0.1, -1),
};

function matchDamageDirection(location: string | null | undefined): Vector3 {
  if (location) {
    const key = location.toLowerCase();
    for (const name of Object.keys(DAMAGE_ZONE_DIRECTION)) {
      if (key.includes(name)) return DAMAGE_ZONE_DIRECTION[name].clone();
    }
  }
  // Default lesion sits on the anterolateral wall, facing the viewer.
  return new Vector3(0.7, -0.3, 0.7).normalize();
}

function SceneContents(inputs: BeatInputs) {
  const palette = useMemo(() => resolvePalette(), []);
  const background = useMemo(
    () => palette.ground.clone().multiplyScalar(0.4),
    [palette],
  );
  const invalidate = useThree((s) => s.invalidate);

  // In reduced-motion (frameloop="demand") the loop is idle, so a store change
  // (EF, damage, beat rate, live) must explicitly request one repaint to apply
  // the new uniforms. In "always" mode this is a harmless no-op.
  useEffect(() => {
    invalidate();
  }, [invalidate, inputs.ef, inputs.damage, inputs.live, inputs.damageDir]);

  // The heart/glow/flow materials self-light in their own shaders (a baked
  // two-key clinical lighting model), so the scene needs only the cleared
  // background. No three.js lights drive these custom materials.
  return (
    <>
      <color attach="background" args={[background]} />

      <Rig animate={inputs.animate} />
      <HeartBody inputs={inputs} />
      <BloodFlow inputs={inputs} />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  The client-only Canvas. Exported via next/dynamic(ssr:false).      */
/* ------------------------------------------------------------------ */

function HeartCanvas() {
  const reduce = useReducedMotion();

  // Store-derived values. Selectors keep re-renders to genuine changes.
  const status = useHeartTwinStore((s) => s.status);
  const rrInterval = useHeartTwinStore(
    (s) => s.visualization?.electrophysiology.rr_interval_ms ?? null,
  );
  const bpm = useHeartTwinStore(
    (s) => s.visualization?.summary.heart_rate_bpm ?? 0,
  );
  const efPct = useHeartTwinStore(
    (s) => s.visualization?.summary.ef_pct ?? null,
  );
  const scarFraction = useHeartTwinStore(
    (s) => s.state?.tissue_state.scar_fraction?.value ?? null,
  );
  const damageLocation = useHeartTwinStore(
    (s) => s.state?.tissue_state.damage_zone_location ?? null,
  );

  const live = status === "operated" || status === "complete";

  const period = cyclePeriod(rrInterval, bpm);
  const beatHz = 1 / period;

  // Beat rate as a motion value so the loop can ease the cadence across store
  // updates instead of snapping the phase frequency.
  const beatHzMv = useMotionValue(beatHz);
  useEffect(() => {
    beatHzMv.set(beatHz);
  }, [beatHz, beatHzMv]);

  // EF: prefer the simulation summary, else assume a healthy resting twin.
  const ef = efPct != null ? efPct / 100 : 0.6;

  // Damage: low EF and/or measured scar both raise the lesion overlay.
  const efDamage = MathUtils.clamp((0.5 - ef) / 0.35, 0, 1); // EF<50% ramps in
  const scarDamage = scarFraction != null ? MathUtils.clamp(scarFraction, 0, 1) : 0;
  const damage = live ? Math.max(efDamage, scarDamage) : 0;

  const damageDir = useMemo(
    () => matchDamageDirection(damageLocation),
    [damageLocation],
  );

  return (
    <Canvas
      camera={{ position: [0.4, 0.25, 4.1], fov: 40, near: 0.1, far: 30 }}
      dpr={[1, 2]}
      gl={{
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
        preserveDrawingBuffer: true, // lets the E2E screenshot read pixels
      }}
      frameloop={reduce ? "demand" : "always"}
    >
      <SceneContents
        beatHzMv={beatHzMv}
        ef={ef}
        damage={damage}
        damageDir={damageDir}
        live={live}
        animate={!reduce}
      />
    </Canvas>
  );
}

// SSR-safe: the WebGL canvas only renders in the browser.
const HeartCanvasClient = dynamic(() => Promise.resolve(HeartCanvas), {
  ssr: false,
  loading: () => <CanvasFallback />,
});

/** On-brand standby while the client-only canvas hydrates. */
function CanvasFallback() {
  return (
    <div className="absolute inset-0 grid place-items-center">
      <div className="flex flex-col items-center gap-3">
        <span className="ht-pulse text-accent-bright">
          <Heart weight="duotone" className="size-7" />
        </span>
        <div className="h-px w-28 ht-ecg-sweep" />
        <p className="ht-mono text-[0.62rem] text-muted">
          initializing viewport
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Public panel. Same named export AppShell already imports.          */
/* ------------------------------------------------------------------ */

export function HeartScene() {
  const status = useHeartTwinStore((s) => s.status);
  const bpm = useHeartTwinStore(
    (s) => s.visualization?.summary.heart_rate_bpm ?? 0,
  );
  const efPct = useHeartTwinStore(
    (s) => s.visualization?.summary.ef_pct ?? null,
  );
  const live = status === "operated" || status === "complete";
  const lowEf = efPct != null && efPct < 40;

  return (
    <Panel className="h-full overflow-hidden">
      <PanelHeader
        icon={Heart}
        accent="accent"
        eyebrow="Digital twin"
        title="Cardiac viewport"
        actions={
          <div className="flex items-center gap-2">
            {efPct != null ? (
              <span
                className="ht-chip"
                data-status={lowEf ? "warning" : "ok"}
                title="Ejection fraction"
              >
                <Waveform weight="bold" className="size-3" />
                {`EF ${Math.round(efPct)}%`}
              </span>
            ) : null}
            <span className="ht-chip" data-status={live ? "success" : "idle"}>
              <span
                className={`ht-chip-dot ${live ? "ht-pulse" : ""}`}
              />
              {bpm > 0 ? `${Math.round(bpm)} bpm` : "Idle"}
            </span>
          </div>
        }
      />
      <div className="ht-hairline" />
      <PanelBody className="pt-0">
        <div className="relative h-full min-h-[260px] overflow-hidden rounded-[var(--ht-r-md)] border border-[var(--ht-line)] bg-[radial-gradient(120%_120%_at_50%_-10%,var(--ht-accent-soft),transparent_60%)]">
          <HeartCanvasClient />

          {/* idle hint, fades out of the way once a case is running */}
          {!live ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-center pb-8">
              <p className="max-w-[34ch] text-center text-xs leading-relaxed text-muted">
                Run a case to drive the twin. The beat tracks heart rate;
                contraction depth tracks ejection fraction.
              </p>
            </div>
          ) : null}

          <p className="ht-mono pointer-events-none absolute bottom-2 left-3 text-[0.66rem] text-muted">
            cardiac_twin · viewport
          </p>
          {live ? (
            <p className="ht-mono pointer-events-none absolute bottom-2 right-3 text-[0.62rem] text-faint">
              activation · flow · perfusion
            </p>
          ) : null}
        </div>
      </PanelBody>
    </Panel>
  );
}
