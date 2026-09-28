# LumiLamp Motion System Design Decisions

Date: 2026-08-31

## Purpose

This document records the current motion-development decisions for LumiLamp.
It is a design boundary document, not an implementation plan.

The fixed desktop lamp version is designed for natural, human-readable motion
expression, but not for jumping, balancing, grabbing, or other complex robot
body control.

## Current Decisions

- The current fixed desktop lamp version does not use MuJoCo to train motion.
- Reinforcement learning is not part of the current motion stack.
- Jumping, balance control, and complex contact control are out of scope.
- Motion naturalness must come from staged keyframes, motion layering, smooth
  interpolation, speed limits, acceleration limits, jerk limits, delayed
  follow-through, slight overshoot, rebound, and settling.
- No angular teleportation is allowed.
- No meaningless continuous jitter is allowed.
- No uncalibrated large high-speed motion is allowed.
- The real mechanical mount must be calibrated before meaningful motion work
  can continue.
- Each joint must have a mechanical zero, a software zero, mechanical limits,
  software limits, a maximum speed, a maximum acceleration, a maximum jerk,
  and load verification.
- New motion must first be validated in simulation or another low-risk mode,
  then in low-speed, small-angle bench tests.

## Role of MuJoCo

MuJoCo is not a prerequisite for current motion development.

It may be used later as an optional tool for:

- collision checking,
- center-of-gravity analysis,
- trajectory prevalidation,
- advanced dynamics study.

It must not become a blocker for motion quality work. If MuJoCo is not used,
the motion design still needs the same quality bar, and that quality bar must
be verified on the real bench with calibration and feedback data.

## Motion Authoring Model

LumiLamp uses a hybrid motion authoring workflow:

1. A human demonstrates key poses.
2. The system records only the key poses, timing, joint positions, and motion
   metadata.
3. The program generates the smooth trajectory between those poses.

This keeps the motion library compact while leaving interpolation and timing
consistency to software.

## Teaching Rules

Manual pose teaching must respect servo safety:

- Do not force a servo that is currently holding torque.
- Prefer turning torque off and reading the current position.
- If the joint must be moved manually into a pose, use small-step control and
  record the position only after the pose is reached safely.

## Division of Responsibility

### Raspberry Pi

- Owns the motion library.
- Selects and composes motions.
- Chooses which motion sequence to run for a behavior.

### ESP32-S3

- Checks limits before execution.
- Enforces speed, acceleration, and jerk constraints.
- Executes interpolation.
- Reports feedback.
- Handles emergency stop behavior.

## Data Model Boundary

The motion data model should remain minimal and explicit.

It should store only:

- key poses,
- time values,
- joint positions,
- motion metadata.

It should not store full physical simulation state as a required part of the
motion format.

## Current Scope

The current phase only defines:

- the keyframe data model,
- the trajectory protocol,
- the module interfaces between motion selection and motion execution.

This phase does not define:

- real servo output code,
- hardware configuration,
- MuJoCo training pipelines,
- reinforcement learning,
- high-speed motion generation.

## Verification Rule

Motion design must be verified in the following order:

1. simulation or other low-risk mode,
2. low-speed, small-angle real bench test,
3. calibration-based refinement on real hardware.

That sequence is mandatory. A simulation pass does not replace real-bench
validation.
