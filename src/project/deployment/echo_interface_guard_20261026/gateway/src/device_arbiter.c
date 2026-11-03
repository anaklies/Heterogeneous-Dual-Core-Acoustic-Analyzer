#include "device_arbiter.h"
#include "gw_util.h"

#include <stdio.h>
#include <string.h>

void gw_arb_init(gw_arbiter *a)
{
    memset(a, 0, sizeof *a);
    a->state = GW_ARB_FREE;
}

static void new_token(char out[GW_ARB_TOKEN_HEX + 1])
{
    uint8_t bytes[GW_ARB_TOKEN_HEX / 2];
    gw_random_bytes(bytes, sizeof bytes);
    gw_hex_encode(bytes, sizeof bytes, out, GW_ARB_TOKEN_HEX + 1);
}

static void clear_holder(gw_arbiter *a)
{
    memset(a->token, 0, sizeof a->token);
    memset(a->owner, 0, sizeof a->owner);
    a->lease_seconds = 0;
    a->since_ms = 0;
    a->expires_ms = 0;
    a->pending_jobs = 0;
    a->state = GW_ARB_FREE;
}

int gw_arb_claim(gw_arbiter *a, const char *owner, uint32_t lease_seconds,
                 uint64_t now_ms, char token_out[GW_ARB_TOKEN_HEX + 1],
                 uint64_t *expires_in_ms, char holder_out[GW_ARB_OWNER_MAX],
                 uint64_t *holder_since_ms)
{
    if (!a || !owner || !*owner || lease_seconds == 0) return -1;
    if (a->state != GW_ARB_FREE) {
        if (holder_out) {
            snprintf(holder_out, GW_ARB_OWNER_MAX, "%s", a->owner);
        }
        if (holder_since_ms) *holder_since_ms = a->since_ms;
        return 1;
    }
    a->state = GW_ARB_HELD;
    snprintf(a->owner, GW_ARB_OWNER_MAX, "%s", owner);
    a->lease_seconds = lease_seconds;
    a->since_ms = now_ms;
    a->expires_ms = now_ms + (uint64_t)lease_seconds * 1000u;
    new_token(a->token);
    if (token_out) {
        memcpy(token_out, a->token, GW_ARB_TOKEN_HEX + 1);
    }
    if (expires_in_ms) *expires_in_ms = (uint64_t)lease_seconds * 1000u;
    return 0;
}

int gw_arb_renew(gw_arbiter *a, const char *token, uint64_t now_ms,
                 uint64_t *expires_in_ms)
{
    if (!a || !token) return -1;
    if (a->state != GW_ARB_HELD) return -1;
    if (strncmp(a->token, token, GW_ARB_TOKEN_HEX) != 0) return -1;
    a->expires_ms = now_ms + (uint64_t)a->lease_seconds * 1000u;
    if (expires_in_ms) *expires_in_ms = (uint64_t)a->lease_seconds * 1000u;
    return 0;
}

int gw_arb_release(gw_arbiter *a, const char *token, uint64_t now_ms)
{
    (void)now_ms;
    if (!a || !token) return -1;
    if (a->state != GW_ARB_HELD) return -1;
    if (strncmp(a->token, token, GW_ARB_TOKEN_HEX) != 0) return -1;
    a->state = GW_ARB_DRAINING;
    if (a->pending_jobs == 0) clear_holder(a);
    return 0;
}

void gw_arb_force_release(gw_arbiter *a, uint64_t now_ms)
{
    (void)now_ms;
    if (!a) return;
    if (a->state == GW_ARB_FREE) return;
    a->state = GW_ARB_DRAINING;
    if (a->pending_jobs == 0) clear_holder(a);
}

int gw_arb_can_write(const gw_arbiter *a, const char *token)
{
    if (!a || !token || a->state != GW_ARB_HELD) return 0;
    return strncmp(a->token, token, GW_ARB_TOKEN_HEX) == 0;
}

int gw_arb_held(const gw_arbiter *a)
{
    return a && a->state != GW_ARB_FREE;
}

void gw_arb_pending_inc(gw_arbiter *a)
{
    if (a) a->pending_jobs++;
}

void gw_arb_pending_dec(gw_arbiter *a)
{
    if (!a) return;
    if (a->pending_jobs > 0) a->pending_jobs--;
}

int gw_arb_tick(gw_arbiter *a, uint64_t now_ms)
{
    if (!a) return 0;
    if (a->state == GW_ARB_HELD && now_ms >= a->expires_ms) {
        a->lease_expiries++;
        a->state = GW_ARB_DRAINING;
        if (a->pending_jobs == 0) { clear_holder(a); return 1; }
        return 0;
    }
    if (a->state == GW_ARB_DRAINING && a->pending_jobs == 0) {
        a->drain_completions++;
        clear_holder(a);
        return 1;
    }
    return 0;
}

const char *gw_arb_state_name(const gw_arbiter *a)
{
    if (!a) return "free";
    switch (a->state) {
    case GW_ARB_HELD: return "held";
    case GW_ARB_DRAINING: return "draining";
    default: return "free";
    }
}