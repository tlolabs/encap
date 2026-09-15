#pragma once
static inline double encap_shuttle_rate(double current, int direction, int slow) {
  double magnitude = current < 0 ? -current : current;
  if (slow) return direction * 0.5;
  if (current * direction <= 0) return direction;
  magnitude *= 2;
  return direction * (magnitude < 1 ? 1 : magnitude > 32 ? 32 : magnitude);
}
