#ifndef GW_DEVICE_ARBITER_H
#define GW_DEVICE_ARBITER_H
/* Single-controller arbitration for the PL device (PROTOCOL.md 3).
 * Only one control holder may issue write operations. On disconnect, heartbeat
 * timeout or lease expiry the holder enters DRAINING: no new write work is
 * accepted, already-accepted transactions finish, then control is released.
 * The PL is never reset and captured data is never erased by this path. */
#include <stdint.h>

#define GW_ARB_TOKEN_HEX 32
#define GW_ARB_OWNER_MAX 64

typedef enum {
    GW_ARB_FREE = 0,
    GW_ARB_HELD = 1,
    GW_ARB_DRAINING = 2
} gw_arb_state;

typedef struct {
    gw_arb_state state;
    char token[GW_ARB_TOKEN_HEX + 1];
    char owner[GW_ARB_OWNER_MAX];
    uint32_t lease_seconds;
    uint64_t since_ms;
    uint64_t expires_ms;
    uint64_t pending_jobs;
    uint32_t lease_expiries;
    uint32_t drain_completions;
} gw_arbiter;

void gw_arb_init(gw_arbiter *a);

/* 0 = claimed; 1 = a live holder exists (holder_out is filled); -1 bad args. */
int gw_arb_claim(gw_arbiter *a, const char *owner, uint32_t lease_seconds,
                 uint64_t now_ms, char token_out[GW_ARB_TOKEN_HEX + 1],
                 uint64_t *expires_in_ms, char holder_out[GW_ARB_OWNER_MAX],
                 uint64_t *holder_since_ms);
int gw_arb_renew(gw_arbiter *a, const char *token, uint64_t now_ms,
                 uint64_t *expires_in_ms);
/* Begin drain (explicit release). Token invalid afterwards. 0 = ok, -1 bad token. */
int gw_arb_release(gw_arbiter *a, const char *token, uint64_t now_ms);
/* Disconnect/heartbeat/lease-loss path: begin drain without token check. */
void gw_arb_force_release(gw_arbiter *a, uint64_t now_ms);
/* 1 when this token is the live, non-draining holder (writes allowed). */
int gw_arb_can_write(const gw_arbiter *a, const char *token);
int gw_arb_held(const gw_arbiter *a);
void gw_arb_pending_inc(gw_arbiter *a);
void gw_arb_pending_dec(gw_arbiter *a);
/* Expiry + drain completion. Returns 1 when the holder was fully released. */
int gw_arb_tick(gw_arbiter *a, uint64_t now_ms);
const char *gw_arb_state_name(const gw_arbiter *a);

#endif
