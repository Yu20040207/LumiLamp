# Motion language

Natural motion must come from staged keyframes, smooth interpolation, speed
limits, acceleration limits, jerk limits, delayed follow-through, slight
overshoot, rebound, and a visible settling tail.

Current motion development decisions:

- The fixed desktop lamp version does not use MuJoCo for motion training.
- Reinforcement learning, jumping, balance control, and complex contact
  control are out of scope for the current phase.
- Motion quality must be validated on the real bench through calibration data,
  not reduced because MuJoCo is not used.
- MuJoCo is reserved for later optional work such as collision checks, center
  of gravity analysis, trajectory prevalidation, and advanced dynamics study.
- No angular teleportation, meaningless continuous jitter, or uncalibrated
  large high-speed movements are allowed.
- The motion stack must first define joint zero position, direction, mechanical
  limits, software limits, maximum speed, maximum acceleration, and load
  verification.
- New motion should be validated in simulation or other low-risk modes before
  any low-speed, small-angle real bench test.

Motion authoring uses a hybrid model:

- Manual demonstration captures key poses and timing.
- The program generates the smooth trajectory from those key poses.
- Hand-guided teaching must never force a servo that is holding torque.
- When teaching poses, first turn torque off and read the current position, or
  use small-step control to move the joint into position and record it.

Data storage is intentionally minimal:

- Key poses.
- Time values.
- Joint positions.
- Motion metadata.

The Raspberry Pi owns motion libraries, motion selection, and motion
composition. The ESP32-S3 owns limit checking, speed and acceleration
constraints, interpolation execution, feedback, and emergency stop handling.

The current phase only defines the keyframe data model, trajectory protocol,
and module interfaces. It does not define real servo output code or hardware
configuration.
