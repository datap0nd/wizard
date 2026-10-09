// Drawn by scripts/wizard_art.py, which writes this file with the sprite sheet: do not edit by hand.
export const FRAME = 48;
export const COLUMNS = 8;
export const ROWS = 11;
export const ANIMATIONS = {
  idle: {row: 0, frames: 6, fps: 6, loop: true},
  wave: {row: 1, frames: 6, fps: 8, loop: true},
  think: {row: 2, frames: 6, fps: 6, loop: true},
  search: {row: 3, frames: 6, fps: 7, loop: true},
  read: {row: 4, frames: 6, fps: 6, loop: true},
  write: {row: 5, frames: 6, fps: 6, loop: true},
  cast: {row: 6, frames: 6, fps: 8, loop: true},
  chart: {row: 7, frames: 6, fps: 6, loop: true},
  check: {row: 8, frames: 6, fps: 6, loop: true},
  success: {row: 9, frames: 8, fps: 10, loop: false},
  fail: {row: 10, frames: 6, fps: 7, loop: false},
} as const;
export type WizardAnimation = keyof typeof ANIMATIONS;
