#include <math.h>
#include <stdint.h>

#include "q16_exact.h"
#include "track_acos.h"
struct Track {
  int id, hits, age, miss;
  bool alive, range, haspos;
  float p[3], v[3], u[3], observed[3], du[3];
};
static float norm_core(float x, float y, float z) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
  return sqrtf(x * x + y * y + z * z);
}
static float norm3(const float a[3]) { return norm_core(a[0], a[1], a[2]); }
static void unit3(float a[3]) {
  float n = fmaxf(norm3(a), 1e-12f);
  for (int c = 0; c < 3; c++)
    a[c] /= n;
}
static int32_t q16(float x) { return q16_exact(x); }
// Same association, five-centimetre static hold, velocity limit and
// missed-frame rules as update_multisource_tracks.m. Output slots preserve the
// localization layout; words +11/+12/+13/+14 are held/confirmed/age/missed
// flags.
void track_sources(const int32_t input[52], float dt, bool reset,
                   int32_t output[52]) {
#pragma HLS INTERFACE ap_memory port = input
#pragma HLS INTERFACE ap_memory port = output
#pragma HLS INTERFACE ap_ctrl_hs port = return
#pragma HLS ALLOCATION function instances = norm_core limit = 1
#pragma HLS ALLOCATION function instances = q16_exact limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
  static Track tracks[3] = {};
  static int nextid = 1;
  if (reset) {
    nextid = 1;
    for (int i = 0; i < 3; i++)
      tracks[i].alive = false;
  }
  dt = isfinite(dt) && dt >= .001f && dt <= 5 ? dt : .25f;
  int count = input[0] < 0 ? 0 : (input[0] > 3 ? 3 : input[0]);
  float pos[3][3], dir[3][3], pred[3][3], predU[3][3];
  bool range[3], used[3] = {}, matched[3] = {};
  for (int d = 0; d < 3; d++) {
    int base = 7 + 15 * d;
    range[d] = input[base + 1] != 0;
    for (int c = 0; c < 3; c++) {
      pos[d][c] = input[base + 5 + c] / 65536.f;
      dir[d][c] = input[base + 2 + c] / 65536.f;
    }
    unit3(dir[d]);
  }
  for (int i = 0; i < 3; i++)
    for (int c = 0; c < 3; c++) {
      pred[i][c] = tracks[i].p[c] + tracks[i].v[c] * dt;
      predU[i][c] = tracks[i].observed[c] + tracks[i].du[c] * dt;
    }
  for (int i = 0; i < 3; i++)
    unit3(predU[i]);
  // Evaluate each gate once; choose a global one-to-one assignment.
  // Maximize matched tracks first, then minimize total cost (64 bounded
  // choices).
  float costs[3][3];
  for (int i = 0; i < 3; i++)
    for (int d = 0; d < 3; d++) {
      costs[i][d] = 1e20f;
      if (tracks[i].alive && d < count) {
        float dot = 0;
        for (int c = 0; c < 3; c++)
          dot += predU[i][c] * dir[d][c];
        float angle = track_acos(fminf(1, fmaxf(-1, dot))) * 57.295779513f;
        if (angle <= 32) {
          float cost = angle / 22 + (range[d] ? 0 : .5f);
          bool eligible = true;
          if (range[d] && tracks[i].haspos) {
            float residual[3];
            for (int c = 0; c < 3; c++)
              residual[c] = pred[i][c] - pos[d][c];
            float separation = norm3(residual),
                  gate = fmaxf(.18f, .55f * dt + .08f * tracks[i].miss);
            float hard = fmaxf(gate, 2.0f * dt);
            if (separation > hard)
              eligible = false;
            cost += separation / gate;
          }
          if (eligible)
            costs[i][d] = cost;
        }
      }
    }
  int assignment[3] = {3, 3, 3}, best_matches = -1;
  float best_cost = 1e20f;
  for (int code = 0; code < 64; code++) {
    int choices[3] = {code & 3, (code >> 2) & 3, (code >> 4) & 3}, matches = 0;
    float total = 0;
    bool legal = true;
    for (int i = 0; i < 3; i++)
      if (choices[i] < 3) {
        if (costs[i][choices[i]] >= 1e19f)
          legal = false;
        for (int j = 0; j < i; j++)
          if (choices[i] == choices[j])
            legal = false;
        matches++;
        total += costs[i][choices[i]];
      }
    if (legal && (matches > best_matches ||
                  (matches == best_matches && total < best_cost))) {
      best_matches = matches;
      best_cost = total;
      for (int i = 0; i < 3; i++)
        assignment[i] = choices[i];
    }
  }
  for (int ti = 0; ti < 3; ti++) {
    int di = assignment[ti];
    if (di < 3) {
      Track &t = tracks[ti];
      float rate[3];
      for (int c = 0; c < 3; c++)
        rate[c] = (dir[di][c] - t.observed[c]) / dt;
      float n = norm3(rate);
      if (n > 1)
        for (int c = 0; c < 3; c++)
          rate[c] /= n;
      for (int c = 0; c < 3; c++) {
        t.du[c] = .65f * rate[c] + .35f * t.du[c];
        t.observed[c] = dir[di][c];
        t.u[c] = .65f * dir[di][c] + .35f * t.u[c];
      }
      unit3(t.u);
      if (range[di]) {
        if (!t.range) {
          float delta[3];
          for (int c = 0; c < 3; c++)
            delta[c] = pos[di][c] - t.p[c];
          if (!t.haspos || norm3(delta) > .05f) {
            for (int c = 0; c < 3; c++) {
              t.p[c] = pos[di][c];
              t.v[c] = 0;
            }
          } else {
            for (int c = 0; c < 3; c++)
              t.v[c] *= .35f;
          }
        } else {
          float residual[3];
          for (int c = 0; c < 3; c++)
            residual[c] = pos[di][c] - t.p[c];
          if (norm3(residual) > .05f) {
            for (int c = 0; c < 3; c++) {
              float correction = pos[di][c] - pred[ti][c];
              t.p[c] = pred[ti][c] + .72f * correction;
              t.v[c] = .55f * t.v[c] + .28f * correction / dt;
            }
            float speed = norm3(t.v);
            if (speed > 1.2f)
              for (int c = 0; c < 3; c++)
                t.v[c] *= 1.2f / speed;
          } else
            for (int c = 0; c < 3; c++)
              t.v[c] *= .35f;
        }
        t.haspos = true;
      }
      if (!range[di] && t.haspos) {
        // The internal prediction must advance across successive range gaps.
        // No predicted XYZ is emitted while the current range is invalid.
        for (int c = 0; c < 3; c++) {
          t.p[c] = pred[ti][c];
          t.v[c] *= .8f;
        }
        // Only established motion may reorient the hidden prediction.
        // Do not emit a valid XYZ while range is unavailable.
        if (norm3(t.v) > .1f) {
          float predicted_range = norm3(t.p);
          for (int c = 0; c < 3; c++)
            t.p[c] = predicted_range * dir[di][c];
        }
      }
      t.range = range[di];
      if (t.hits < 2)
        t.hits++;
      if (t.age < 2147483647)
        t.age++;
      t.miss = 0;
      used[di] = true;
      matched[ti] = true;
    }
  }
  for (int i = 0; i < 3; i++)
    if (tracks[i].alive && !matched[i]) {
      Track &t = tracks[i];
      if (t.hits < 2)
        t.hits = 0;
      t.miss++;
      for (int c = 0; c < 3; c++) {
        t.v[c] *= .5f;
        t.du[c] *= .5f;
      }
      if (t.miss > 3)
        t.alive = false;
    }
  for (int d = 0; d < 3; d++)
    if (d < count && !used[d]) {
      int slot = -1;
      for (int i = 0; i < 3; i++)
        if (slot < 0 && !tracks[i].alive)
          slot = i;
      if (slot >= 0) {
        Track &t = tracks[slot];
        t.id = nextid;
        nextid = nextid == 2147483647 ? 1 : nextid + 1;
        t.hits = 1;
        t.age = 1;
        t.miss = 0;
        t.alive = true;
        t.range = range[d];
        t.haspos = range[d];
        for (int c = 0; c < 3; c++) {
          t.p[c] = range[d] ? pos[d][c] : 0;
          t.v[c] = 0;
          t.du[c] = 0;
          t.u[c] = dir[d][c];
          t.observed[c] = dir[d][c];
        }
      }
    }
  for (int w = 0; w < 52; w++)
    output[w] = 0;
  for (int w = 1; w < 7; w++)
    output[w] = input[w];
  int out = 0;
  for (int i = 0; i < 3; i++)
    if (tracks[i].alive) {
      Track &t = tracks[i];
      int b = 7 + 15 * out++;
      output[b] = t.id;
      output[b + 1] = t.range;
      for (int c = 0; c < 3; c++) {
        output[b + 2 + c] = q16(t.u[c]);
        output[b + 5 + c] = t.range ? q16(t.p[c]) : 0;
      }
      output[b + 8] = t.range ? q16(norm3(t.p)) : 0;
      output[b + 11] = t.miss > 0;
      output[b + 12] = t.hits >= 2;
      output[b + 13] = t.age;
      output[b + 14] = t.miss;
    }
  output[0] = out;
}






