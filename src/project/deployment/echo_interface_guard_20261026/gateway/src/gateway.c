#include "gateway.h"
#include "feature_runtime.h"
#include "control_server.h"
#include "binary_server.h"
#include "mock_mmio.h"
#include "fc_capture.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* =============================================================== config */

void gw_config_defaults(gw_config *c)
{
    memset(c, 0, sizeof *c);
    snprintf(c->bind_addr, sizeof c->bind_addr, "%s", "0.0.0.0");
    c->control_port = SMA_DEFAULT_CONTROL_PORT;
    c->binary_port = SMA_DEFAULT_BINARY_PORT;
    snprintf(c->spool_dir, sizeof c->spool_dir, "%s", "spool");
    snprintf(c->state_dir, sizeof c->state_dir, "%s", "spool/state");
    c->spool_limit_bytes = 64ull * 1024ull * 1024ull;
    c->max_binary_payload = SMA_DEFAULT_MAX_BINARY_PAYLOAD;
    c->poll_ms = GW_SETTLE_MS;
    c->service_snapshot_words = 16;
    c->max_control_lease_seconds = GW_MAX_LEASE_SECONDS;
    c->config_confirm_timeout_ms = (uint32_t)GW_CONFIG_CONFIRM_TIMEOUT_MS;
    c->job_fixture_polls = 3;
}

void gw_logf(gw *g, const char *fmt, ...)
{
    char line[GW_LOG_LINE_BYTES];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    gw_log_add(&g->log, "%s", line);
}

static void state_path(const gw *g, const char *name, char *out, size_t cap)
{
    (void)gw_path_join(g->cfg.state_dir, name, out, cap);
}

static int load_epoch(gw *g)
{
    char path[GW_EVENT_PATH_MAX * 2];
    FILE *f;
    char token[32];
    uint64_t old = 0;
    state_path(g, "connection_epoch", path, sizeof path);
    f = fopen(path, "rb");
    if (f) {
        if (fscanf(f, "%31s", token) == 1)
            (void)gw_parse_u64_dec(token, strlen(token), &old);
        fclose(f);
    }
    if (old == GW_U64_MAX) old = 0;
    g->epoch = old + 1u;
    g->next_event_id = 0;
    return 0;
}

static int save_epoch(gw *g)
{
    char path[GW_EVENT_PATH_MAX * 4];
    char tmp[GW_EVENT_PATH_MAX * 4 + 8];
    char num[21];
    FILE *f;
    state_path(g, "connection_epoch", path, sizeof path);
    (void)gw_str_concat(path, ".tmp", tmp, sizeof tmp);
    f = fopen(tmp, "wb");
    if (!f) return -1;
    fprintf(f, "%s\n", gw_u64_dec(g->epoch, num));
    fclose(f);
    remove(path);
    if (rename(tmp, path) != 0) return -1;
    return 0;
}

static void config_cache_save(gw *g)
{
    char path[GW_EVENT_PATH_MAX * 2];
    char tmp[GW_EVENT_PATH_MAX * 2 + 8];
    FILE *f;
    unsigned i;
    if (!g->config_active_known) return;
    state_path(g, "config_active.txt", path, sizeof path);
    (void)gw_str_concat(path, ".tmp", tmp, sizeof tmp);
    f = fopen(tmp, "wb");
    if (!f) return;
    fprintf(f, "%u\n", (unsigned)g->active_config_version);
    for (i = 0; i < 32; i++) fprintf(f, "%08x\n", (unsigned)g->config_active_words[i]);
    fclose(f);
    remove(path);
    (void)rename(tmp, path);
}

static void config_cache_load(gw *g)
{
    char path[GW_EVENT_PATH_MAX * 2];
    FILE *f;
    unsigned version = 0;
    unsigned i;
    uint32_t words[32];
    state_path(g, "config_active.txt", path, sizeof path);
    f = fopen(path, "rb");
    if (!f) return;
    if (fscanf(f, "%u", &version) != 1) { fclose(f); return; }
    for (i = 0; i < 32; i++) {
        unsigned v = 0;
        if (fscanf(f, "%x", &v) != 1) { fclose(f); return; }
        words[i] = (uint32_t)v;
    }
    fclose(f);
    memcpy(g->config_active_words, words, sizeof words);
    g->config_active_known = 1;
    /* Only trusted when the PL still reports the same active version; checked
     * in gw_device_poll (PL exposes active version but not active words). */
}

/* =============================================================== identify */

static void gw_refresh_caps(gw *g)
{
    gw_device_caps *c = &g->caps;
    c->protocol3 = g->pl_identified && g->pl_protocol == 3u;
    c->config_version = g->active_config_version;
    c->live_pcm = 0;
    c->live_results = (g->pl_identified && g->cfg.allow_live_results && g->stats.result_frames_published>=2 && g->has_result) ? 1 : 0;
    c->config_commit = (g->cfg.mock_fixture || g->cfg.allow_config_commit) ? 1 : 0;
    c->event_capture = (g->cfg.mock_fixture || g->cfg.allow_event_capture) ? 1 : 0;
    c->event_download = c->event_capture;
    c->task_control = 0;
    c->device_log = 1;
    c->raw_recording = 0;
    c->profile_upload = 0;
    c->profile_activate = 0;
    c->sensor_snapshot = c->live_results;
}

static void gw_identify(gw *g)
{
    sm_identity id;
    if (!g->mmio) return;
    if (sm_identify(&g->mmio->dev, &id) == SM_OK) {
        char suffix[8];
        g->pl_identified = 1;
        g->pl_protocol = id.protocol;
        g->pl_firmware = id.firmware;
        g->pl_capabilities = id.capabilities;
        snprintf(suffix, sizeof suffix, "%04x", (unsigned)(id.firmware & 0xFFFFu));
        snprintf(g->device_id, sizeof g->device_id, "sixmic-dev-%s", suffix);
        gw_refresh_caps(g);
        gw_logf(g, "PL identified protocol=%u firmware=0x%08x",
                (unsigned)id.protocol, (unsigned)id.firmware);
    } else {
        if (g->pl_identified) gw_logf(g, "PL identify failed (link lost?)");
        g->pl_identified = 0;
        g->pl_protocol = 0;
        gw_refresh_caps(g);
    }
    g->last_identify_ms = g->now_ms;
}

/* ================================================================ init */

static gw_mmio *gw_open_backend(gw *g, gw_mmio *provided, char *err, size_t errcap)
{
    if (provided) { g->mock_owned = NULL; return provided; }
    if (g->cfg.mock_fixture) {
        mock_mmio *m = mock_mmio_create();
        if (!m) {
            snprintf(err, errcap, "cannot allocate mock MMIO fixture (64 MiB DDR)");
            return NULL;
        }
        g->mock_owned = m;
        return mock_mmio_gw(m);
    }
    if (g->cfg.uio_path[0]) {
        gw_mmio *m = NULL;
        if (gw_mmio_open_uio(g->cfg.uio_path, g->cfg.mmio_bytes ? g->cfg.mmio_bytes : 0x1000u,
                             &m, err, errcap) != 0) return NULL;
        g->owns_mmio = 1;
        if (g->cfg.ddr_memdev_path[0]) {
            if (gw_mmio_map_ddr(m, g->cfg.ddr_memdev_path,
                                g->cfg.ddr_phys_base, g->cfg.ddr_bytes,
                                err, errcap) != 0) {
                gw_mmio_close(m);
                return NULL;
            }
        }
        return m;
    }
    if (g->cfg.memdev_path[0]) {
        gw_mmio *m = NULL;
        if (gw_mmio_open_memdev(g->cfg.memdev_path,
                                g->cfg.mmio_phys_base,
                                g->cfg.mmio_bytes ? g->cfg.mmio_bytes : 0x1000u,
                                &m, err, errcap) != 0) return NULL;
        g->owns_mmio = 1;
        if (g->cfg.ddr_memdev_path[0]) {
            if (gw_mmio_map_ddr(m, g->cfg.ddr_memdev_path,
                                g->cfg.ddr_phys_base, g->cfg.ddr_bytes,
                                err, errcap) != 0) {
                gw_mmio_close(m);
                return NULL;
            }
        }
        return m;
    }
    snprintf(err, errcap, "no device backend: pass --uio, --memdev or --mock-fixture");
    return NULL;
}

int gw_init(gw *g, const gw_config *cfg, gw_mmio *provided_mmio,
            char *err, size_t errcap)
{
    char e[256];
    memset(g, 0, sizeof *g);
    if (err && errcap) err[0] = 0;
    g->cfg = *cfg;
    if (g->cfg.poll_ms < 1) g->cfg.poll_ms = 1;
    if (g->cfg.poll_ms > 1000) g->cfg.poll_ms = 1000;
    if (g->cfg.max_binary_payload < SMA_MIN_MAX_BINARY_PAYLOAD)
        g->cfg.max_binary_payload = SMA_MIN_MAX_BINARY_PAYLOAD;
    if (g->cfg.max_binary_payload > SMA_MAX_MAX_BINARY_PAYLOAD)
        g->cfg.max_binary_payload = SMA_MAX_MAX_BINARY_PAYLOAD;
    if (g->cfg.spool_limit_bytes < 1024u * 1024u)
        g->cfg.spool_limit_bytes = 1024u * 1024u;
    if (g->cfg.state_dir[0] == 0) {
        (void)gw_path_join(g->cfg.spool_dir, "state", g->cfg.state_dir,
                           sizeof g->cfg.state_dir);
    }
    if (g->cfg.service_snapshot_words == 0) g->cfg.service_snapshot_words = 16;
    if (g->cfg.service_snapshot_words > GW_SERVICE_MAX_WORDS)
        g->cfg.service_snapshot_words = GW_SERVICE_MAX_WORDS;
    if (g->cfg.max_control_lease_seconds == 0 ||
        g->cfg.max_control_lease_seconds > GW_MAX_LEASE_SECONDS)
        g->cfg.max_control_lease_seconds = GW_MAX_LEASE_SECONDS;
    if (g->cfg.config_confirm_timeout_ms == 0)
        g->cfg.config_confirm_timeout_ms = (uint32_t)GW_CONFIG_CONFIRM_TIMEOUT_MS;
    if (g->cfg.job_fixture_polls == 0) g->cfg.job_fixture_polls = 3;
    g->ctl_listener = GW_SOCK_INVALID;
    g->bin_listener = GW_SOCK_INVALID;
    if (gw_net_startup(e, sizeof e) != 0) {
        snprintf(err, errcap, "%s", e);
        return -1;
    }
    g->now_ms = gw_clock_ms();
    g->start_ms = g->now_ms;
    g->last_poll_ms = g->now_ms;
    gw_arb_init(&g->arb);
    gw_log_init(&g->log);
    if (gw_mkdir_p(g->cfg.spool_dir) != 0 || gw_mkdir_p(g->cfg.state_dir) != 0) {
        snprintf(err, errcap, "cannot create spool/state directories");
        goto fail;
    }
    if (gw_spool_init(&g->spool, g->cfg.spool_dir, g->cfg.spool_limit_bytes,
                      e, sizeof e) != 0) {
        snprintf(err, errcap, "%s", e);
        goto fail;
    }
    load_epoch(g);
    if (save_epoch(g) != 0) {
        snprintf(err, errcap, "cannot persist connectionEpoch in %s",
                 g->cfg.state_dir);
        goto fail;
    }
    g->mmio = gw_open_backend(g, provided_mmio, e, sizeof e);
    if (!g->mmio) {
        snprintf(err, errcap, "%s", e);
        goto fail;
    }
    gw_identify(g);
    if (!g->pl_identified && !g->cfg.mock_fixture)
        gw_logf(g, "device not identified at startup; will retry");
    config_cache_load(g);
    if (gw_device_read_reg(g, 0x1C, &g->active_config_version) != 0)
        g->active_config_version = 0;
    /* The PL exposes the active version (0x1c) but not the active words, so a
     * cached word image is only trusted when its version matches the register. */
    if (g->config_active_known &&
        g->config_active_words[SM_C_VERSION] != g->active_config_version)
        g->config_active_known = 0;
    gw_refresh_caps(g);
    {
        uint16_t port = 0;
        g->ctl_listener = gw_net_listen(g->cfg.bind_addr, g->cfg.control_port,
                                        &port, e, sizeof e);
        if (g->ctl_listener == GW_SOCK_INVALID) {
            snprintf(err, errcap, "control listener: %s", e);
            goto fail;
        }
        g->ctl_bound_port = port;
        g->bin_listener = gw_net_listen(g->cfg.bind_addr, g->cfg.binary_port,
                                        &port, e, sizeof e);
        if (g->bin_listener == GW_SOCK_INVALID) {
            snprintf(err, errcap, "binary listener: %s", e);
            goto fail;
        }
        g->bin_bound_port = port;
    }
    if (ctl_server_init(g, e, sizeof e) != 0 || bin_server_init(g, e, sizeof e) != 0) {
        snprintf(err, errcap, "%s", e);
        goto fail;
    }
    if (echo_routes_load(g,g->cfg.service_catalog_file,e,sizeof e)) { snprintf(err,errcap,"%s",e); goto fail; }
    g->service_snapshot_enabled = g->cfg.service_snapshot_addr != 0 || g->service_route_count != 0;
    if(echo_features_init(g,g->cfg.feature_registry_file,e,sizeof e)){snprintf(err,errcap,"%s",e);goto fail;}
    gw_logf(g, "gateway up version=%s epoch=%s control=%u binary=%u fixture=%d",
            GW_VERSION, gw_u64_dec(g->epoch, e), (unsigned)g->ctl_bound_port,
            (unsigned)g->bin_bound_port, g->cfg.mock_fixture);
    return 0;
fail:
    gw_shutdown(g);
    return -1;
}

void gw_shutdown(gw *g)
{
    echo_features_free(g);
    unsigned i;
    if (!g) return;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        if (g->ctl[i].used) {
            gw_msgq_free(&g->ctl[i].out);
            g->ctl[i].used = 0;
        }
    }
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        if (g->bin[i].used) {
            gw_net_close(g->bin[i].fd);
            gw_fifo_free(&g->bin[i].out);
            g->bin[i].used = 0;
        }
    }
    for (i = 0; i < GW_MAX_SUBSCRIPTIONS; i++) {
        unsigned k;
        if (!g->subs[i].used) continue;
        for (k = 0; k < g->subs[i].nstreams; k++)
            gw_stream_def_free(&g->subs[i].streams[k]);
        g->subs[i].used = 0;
    }
    for (i = 0; i < GW_MAX_BINARY_SESSIONS; i++) {
        unsigned k;
        if (!g->bin_sessions[i].used) continue;
        for (k = 0; k < g->bin_sessions[i].nstreams; k++)
            gw_stream_def_free(&g->bin_sessions[i].streams[k]);
        g->bin_sessions[i].used = 0;
    }
    if (g->ctl_listener != GW_SOCK_INVALID) {
        gw_net_close(g->ctl_listener);
        g->ctl_listener = GW_SOCK_INVALID;
    }
    if (g->bin_listener != GW_SOCK_INVALID) {
        gw_net_close(g->bin_listener);
        g->bin_listener = GW_SOCK_INVALID;
    }
    if (g->mock_owned) {
        mock_mmio_destroy((mock_mmio *)g->mock_owned);
        g->mock_owned = NULL;
    } else if (g->owns_mmio && g->mmio) {
        gw_mmio_close(g->mmio);
    }
    g->mmio = NULL;
    gw_spool_close(&g->spool);
    gw_net_cleanup();
}

/* ============================================================== pumping */

static void gw_accept_control(gw *g)
{
    gw_sock s;
    char peer[64];
    unsigned i;
    s = gw_net_accept(g->ctl_listener, peer, sizeof peer);
    if (s == GW_SOCK_INVALID) return;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        char num[21];
        if (c->used) continue;
        memset(c, 0, sizeof *c);
        c->used = 1;
        c->fd = s;
        c->connected_ms = g->now_ms;
        c->last_rx_ms = g->now_ms;
        c->rate_tokens = GW_RATE_BURST;
        c->rate_last_ms = g->now_ms;
        gw_msgq_init(&c->out);
        snprintf(c->session_id, sizeof c->session_id, "sess-%s-%02llu",
                 gw_u64_dec(g->epoch, num), (unsigned long long)g->stats.control_connections + 1u);
        g->stats.control_connections++;
        gw_logf(g, "control: accepted %s session=%s", peer, c->session_id);
        return;
    }
    gw_net_close(s);
    gw_logf(g, "control: connection table full, rejected %s", peer);
}

static void gw_accept_binary(gw *g)
{
    gw_sock s;
    char peer[64];
    unsigned i;
    s = gw_net_accept(g->bin_listener, peer, sizeof peer);
    if (s == GW_SOCK_INVALID) return;
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        if (c->used) continue;
        memset(c, 0, sizeof *c);
        c->used = 1;
        c->fd = s;
        c->connected_ms = g->now_ms;
        c->last_rx_ms = g->now_ms;
        c->last_tx_ms = g->now_ms;
        c->max_payload = SMA_DEFAULT_MAX_BINARY_PAYLOAD;
        if (gw_fifo_init(&c->out, GW_BINARY_OUT_CAP) != 0) {
            gw_net_close(s);
            c->used = 0;
            return;
        }
        g->stats.binary_connections++;
        gw_logf(g, "binary: accepted %s", peer);
        return;
    }
    gw_net_close(s);
    gw_logf(g, "binary: connection table full, rejected %s", peer);
}

int gw_pump(gw *g, int timeout_ms)
{
    gw_pollfd fds[2 + GW_MAX_CONTROL_CONNS + GW_MAX_BINARY_CONNS];
    gw_ctl_conn *cmap[GW_MAX_CONTROL_CONNS];
    gw_bin_conn *bmap[GW_MAX_BINARY_CONNS];
    size_t nfds = 0, ncmap = 0, nbmap = 0, i;
    int ready;
    if (!g) return -1;
    g->now_ms = gw_clock_ms();
    if (g->stop) return 0;
    if (gw_arb_tick(&g->arb, g->now_ms)) {
        char line[GW_NOTIFY_BYTES];
        snprintf(line, sizeof line,
                 "{\"type\":\"event\",\"protocol\":\"%s\",\"version\":1,"
                 "\"event\":\"controlChanged\",\"eventId\":\"%s\","
                 "\"data\":{\"held\":false}}",
                 GW_PROTOCOL_NAME, gw_u64_dec(g->next_event_id++, (char[21]){0}));
        ctl_notify_all(g, line);
        gw_logf(g, "control: released (expiry/drain complete)");
    }
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        if (!c->used) continue;
        if (c->closing && gw_msgq_count(&c->out) == 0) { ctl_conn_close(g, c); continue; }
    }
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        if (!c->used) continue;
        if (c->closing && gw_fifo_avail(&c->out) == 0) { bin_server_close_conn(g, c, NULL); continue; }
    }
    memset(fds, 0, sizeof fds);
    fds[nfds].fd = g->ctl_listener;
    fds[nfds].want_read = 1;
    nfds++;
    fds[nfds].fd = g->bin_listener;
    fds[nfds].want_read = 1;
    nfds++;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        if (!c->used) continue;
        fds[nfds].fd = c->fd;
        fds[nfds].want_read = c->closing ? 0 : 1;
        fds[nfds].want_write = gw_msgq_count(&c->out) ? 1 : 0;
        cmap[ncmap++] = c;
        nfds++;
    }
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        if (!c->used) continue;
        fds[nfds].fd = c->fd;
        fds[nfds].want_read = c->closing ? 0 : 1;
        fds[nfds].want_write = gw_fifo_avail(&c->out) ? 1 : 0;
        bmap[nbmap++] = c;
        nfds++;
    }
    if (timeout_ms < 0) timeout_ms = g->cfg.poll_ms;
    ready = gw_net_poll(fds, nfds, timeout_ms);
    if (ready < 0) return -1;
    if (fds[0].ready_read) gw_accept_control(g);
    if (fds[1].ready_read) gw_accept_binary(g);
    for (i = 0; i < ncmap; i++) {
        size_t idx = 2 + i;
        gw_ctl_conn *c = cmap[i];
        if (!c->used) continue;
        if (fds[idx].ready_read) ctl_server_on_readable(g, c);
        if (c->used && fds[idx].ready_write) ctl_server_flush(g, c);
    }
    for (i = 0; i < nbmap; i++) {
        size_t idx = 2 + ncmap + i;
        gw_bin_conn *c = bmap[i];
        if (!c->used) continue;
        if (fds[idx].ready_read) bin_server_on_readable(g, c);
        if (c->used && fds[idx].ready_write) bin_server_flush(g, c);
    }
    g->now_ms = gw_clock_ms();
    if (g->now_ms - g->last_poll_ms >= (uint64_t)g->cfg.poll_ms) {
        g->last_poll_ms = g->now_ms;
        gw_device_poll(g);
        gw_event_tick(g);
    }
    echo_features_tick(g);
    gw_jobs_tick(g);
    ctl_server_tick(g);
    bin_server_tick(g);
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        if (!c->used) continue;
        if (gw_msgq_count(&c->out)) ctl_server_flush(g, c);
        if (c->used && c->closing && gw_msgq_count(&c->out) == 0) ctl_conn_close(g, c);
    }
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        if (!c->used) continue;
        if (gw_fifo_avail(&c->out)) bin_server_flush(g, c);
        if (c->used && c->closing && gw_fifo_avail(&c->out) == 0)
            bin_server_close_conn(g, c, NULL);
    }
    return 0;
}

int gw_run(gw *g)
{
    while (g && !g->stop) {
        if (gw_pump(g, g->cfg.poll_ms) != 0) return -1;
    }
    return 0;
}

void gw_request_stop(gw *g)
{
    if (g) g->stop = 1;
}

uint64_t gw_epoch(const gw *g) { return g ? g->epoch : 0; }

const char *gw_device_id(const gw *g) { return g ? g->device_id : ""; }

const char *gw_source_kind(const gw *g)
{
    return (g && g->cfg.mock_fixture) ? "test-fixture" : "pl-live";
}

/* ========================================================= device/config */
/* --------------------------------------------------------- device poll */

int gw_device_read_reg(gw *g, uint32_t offset, uint32_t *value)
{
    if (!g || !g->mmio) return -1;
    return gw_mmio_read_reg(g->mmio, offset, value);
}

static void gw_release_clip(gw *g, const sm_clip *clip)
{
    int rc = sm_release_clip(&g->mmio->dev, clip);
    if (rc != SM_OK) {
        g->stats.event_release_errors++;
        gw_logf(g, "clip release failed rc=%d bank=%u", rc, clip->bank);
    }
}

static void gw_snapshot_poll(gw *g)
{
    sm_snapshot s;
    int rc;
    if (!g->pl_identified) return;
    rc = sm_read_snapshot(&g->mmio->dev, &s, 3);
    if (rc == SM_OK) {
        g->stats.snapshot_ok++;
        if (s.epoch != (uint32_t)g->last_result_epoch_seen) {
            uint32_t frame = s.word[SM_R_FRAME];
            uint32_t cfg = s.word[SM_R_CONFIG];
            g->last_result_epoch_seen = s.epoch;
            /* Analysis firmware publishes every TWO input windows. Its frame
             * stride of two is intentional decimation, not a lost PCM frame. */
            uint32_t stride=s.word[SM_R_ALGORITHM]==0x82000002u?2u:1u;
            g->result_gap_pending = (g->has_result && frame != g->last_result_frame + stride) ? 1 : 0;
            g->last_result_frame = frame;
            g->snap = s;
            g->has_result = 1;
            g->snap_rx_ms = g->now_ms;
            fc_transient_poll(g);
            (void)cfg;
            g->stats.result_frames_published++;
            gw_refresh_caps(g);
            bin_publish_result(g, s.word);
        }
    } else if (rc == SM_NO_DATA) {
        g->stats.snapshot_no_data++;
    } else if (rc == SM_RETRY) {
        g->stats.snapshot_retries++;
    } else {
        g->stats.snapshot_errors++;
    }
}

static void gw_config_commit_finish(gw *g, int applied, const char *reason)
{
    uint32_t version = g->pending_config_version;
    uint64_t job_id = g->pending_config_job;
    gw_job *job = gw_job_find(g, job_id);
    char data[512];
    char line[GW_NOTIFY_BYTES];
    gw_json_writer w;
    g->pending_config = 0;
    g->pending_config_job = 0;
    if (applied) {
        memcpy(g->config_active_words, g->pending_config_words, sizeof g->config_active_words);
        g->config_active_known = 1;
        g->active_config_version = version;
        g->stats.config_applied++;
        config_cache_save(g);
        gw_refresh_caps(g);
        gw_logf(g, "config: version %u applied by PL", (unsigned)version);
        if (job) gw_job_set_state(g, job, GW_JOB_COMPLETED, "PL confirmed config applied");
    } else {
        g->last_rejected_version = version;
        g->stats.config_rejected++;
        gw_logf(g, "config: version %u rejected (%s)", (unsigned)version, reason ? reason : "");
        if (job) gw_job_set_state(g, job, GW_JOB_FAILED, reason ? reason : "PL rejected config");
        {
            char buf[256];
            snprintf(buf, sizeof buf,
                     "{\"type\":\"event\",\"protocol\":\"%s\",\"version\":1,"
                     "\"event\":\"diagnosticAdded\",\"eventId\":\"%s\","
                     "\"data\":{\"level\":\"warning\",\"code\":\"config_rejected\","
                     "\"messageKey\":\"errors.config_rejected\",\"detail\":\"%s\","
                     "\"monotonicNs\":\"%s\"}}",
                     GW_PROTOCOL_NAME, gw_u64_dec(g->next_event_id++, (char[21]){0}),
                     reason ? reason : "pl_rejected",
                     gw_u64_dec(gw_clock_ns(), (char[21]){0}));
            ctl_notify_all(g, buf);
        }
    }
    gw_jw_init(&w, data, sizeof data);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "version");
    gw_jw_u32(&w, version);
    gw_jw_key(&w, "applied");
    gw_jw_bool(&w, applied ? 1 : 0);
    gw_jw_key(&w, "rejected");
    gw_jw_bool(&w, applied ? 0 : 1);
    if (!applied) {
        gw_jw_key(&w, "rejectedReason");
        gw_jw_str(&w, reason ? reason : "pl_rejected");
    }
    gw_jw_end_obj(&w);
    if (gw_jw_finish(&w)) {
        gw_jw_init(&w, line, sizeof line);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "type"); gw_jw_str(&w, "event");
        gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
        gw_jw_key(&w, "version"); gw_jw_u32(&w, 1);
        gw_jw_key(&w, "event"); gw_jw_str(&w, "configApplied");
        gw_jw_key(&w, "eventId"); gw_jw_u64dec_str(&w, g->next_event_id++);
        gw_jw_key(&w, "data"); gw_jw_raw_value(&w, data, strlen(data));
        gw_jw_end_obj(&w);
        if (gw_jw_finish(&w)) ctl_notify_all(g, line);
    }
}

static void gw_config_status_poll(gw *g)
{
    int rc;
    if (!g->pending_config || !g->pl_identified) return;
    rc = sm_config_status(&g->mmio->dev, g->pending_config_version);
    if (rc == SM_OK) {
        gw_config_commit_finish(g, 1, NULL);
    } else if (rc == SM_REJECTED) {
        gw_config_commit_finish(g, 0, "pl_rejected");
    } else if (rc == SM_IO) {
        g->stats.config_io_errors++;
        if (g->now_ms >= g->pending_config_deadline_ms)
            gw_config_commit_finish(g, 0, "status_io_timeout");
    } else if (g->now_ms >= g->pending_config_deadline_ms) {
        g->stats.config_timeouts++;
        gw_config_commit_finish(g, 0, "confirm_timeout");
    }
}

static void gw_service_poll(gw *g)
{
    uint8_t payload[SMA_SERVICE_HEADER_BYTES + GW_SERVICE_MAX_WORDS * 4u];
    uint32_t bytes = 0;
    if (!g->service_snapshot_enabled || !g->pl_identified) return;
    if (echo_service_read(g, payload, &bytes) == 0) bin_publish_service(g, payload, bytes);
}

void gw_device_poll(gw *g)
{
    uint32_t reg = 0;
    if (!g || !g->mmio) return;
    if (!g->pl_identified && g->now_ms - g->last_identify_ms >= 1000u)
        gw_identify(g);
    if (g->pl_identified) {
        if (gw_device_read_reg(g, 0x14, &reg) == 0) g->pl_faults = reg;
        if (gw_device_read_reg(g, 0x1C, &reg) == 0 &&
            reg != g->active_config_version && !g->pending_config) {
            gw_logf(g, "config: PL active version changed %u -> %u",
                    (unsigned)g->active_config_version, (unsigned)reg);
            g->active_config_version = reg;
            if (g->config_active_known &&
                g->config_active_words[SM_C_VERSION] != reg)
                g->config_active_known = 0;
            gw_refresh_caps(g);
        }
    }
    gw_snapshot_poll(g);
    gw_config_status_poll(g);
    gw_service_poll(g);
}

/* ------------------------------------------------------------- clip data */

static int gw_copy_ddr_to_writer(gw *g, uint64_t byte_addr, uint64_t bytes,
                                 gw_spool_writer *w)
{
    uint8_t buf[16384];
    static uint32_t words_buf[16384 / 4];
    while (bytes > 0) {
        uint32_t chunk = (bytes > sizeof buf) ? (uint32_t)sizeof buf : (uint32_t)bytes;
        uint32_t words = chunk / 4u;
        if (g->mmio->mem.read(g->mmio->mem.ctx, (uint32_t)byte_addr, words_buf, words) != 0)
            return -1;
        memcpy(buf, words_buf, (size_t)words * 4u);
        if (gw_spool_writer_write(w, buf, (size_t)words * 4u) != 0) return -1;
        byte_addr += (uint64_t)words * 4u;
        bytes -= (uint64_t)words * 4u;
    }
    return 0;
}

int gw_event_capture_bank(gw *g, unsigned bank, const sm_clip *clip)
{
    uint64_t event_id;
    if (!clip || bank > 1) return -1;
    if (!g->cfg.mock_fixture && g->epoch > 0xffffffffull) return -1;
    event_id = (g->cfg.mock_fixture ? 0ull : g->epoch << 32) | clip->word[SM_E_ID];
    uint32_t frames = clip->word[SM_E_FRAMES];
    uint32_t base = clip->word[SM_E_BASE];
    uint32_t offset = clip->word[SM_E_OFFSET];
    uint32_t bank_bytes = g->config_active_known
        ? g->config_active_words[SM_C_BANK_BYTES] : 0u;
    uint64_t total;
    uint64_t first_seg;
    gw_smc1 hdr;
    gw_spool_writer writer;
    gw_event_rec rec;
    char err[256];
    int rc;
    if (!clip || bank > 1) return -1;
    if (gw_spool_find(&g->spool, event_id)) {
        g->stats.events_duplicate++;
        gw_release_clip(g, clip);
        return 0;
    }
    if (frames == 0 || bank_bytes == 0 || offset >= bank_bytes || frames > bank_bytes / 32u) {
        g->stats.event_capture_errors++;
        gw_logf(g, "event: bad clip geometry id=%s frames=%u", 
                gw_u64_dec(event_id, (char[21]){0}), (unsigned)frames);
        gw_release_clip(g, clip);
        return -1;
    }
    total = (uint64_t)frames * GW_SMC1_RECORD_BYTES;
    first_seg = (uint64_t)bank_bytes - offset;
    if (first_seg > total) first_seg = total;
    gw_smc1_init(&hdr);
    hdr.event_id = event_id;
    hdr.record_count = frames;
    hdr.first_sample = sm_join_u64(clip->word[SM_E_FIRST_LOW], clip->word[SM_E_FIRST_HIGH]);
    hdr.last_sample = sm_join_u64(clip->word[SM_E_LAST_LOW], clip->word[SM_E_LAST_HIGH]);
    hdr.clip_reason = clip->word[SM_E_REASON] & 0xFFFFu;
    if (g->has_result) hdr.sample_rate_word = g->snap.word[SM_R_SAMPLE_RATE_FLOAT];
    if (clip->word[SM_E_INCOMPLETE] != 0) hdr.flags |= GW_SMC1_FLAG_INCOMPLETE;
    if (!g->has_result || g->snap.word[SM_R_LOST_EVENTS] != 0)
        hdr.flags |= GW_SMC1_FLAG_LOST_EVENTS;
    if (!g->has_result || (clip->word[SM_E_AGE_VALID] & 1u) == 0)
        hdr.flags |= GW_SMC1_FLAG_SUMMARY_STALE;
    if (!g->has_result) {
        hdr.flags |= GW_SMC1_FLAG_ENV_INVALID | GW_SMC1_FLAG_POSE_INVALID;
    } else {
        uint32_t v = g->snap.word[SM_R_SENSOR_VALID];
        if ((v & 0x3u) != 0x3u) hdr.flags |= GW_SMC1_FLAG_ENV_INVALID;
        if ((v & 0x4u) == 0u) hdr.flags |= GW_SMC1_FLAG_POSE_INVALID;
    }
    rc = gw_spool_writer_begin(&g->spool, &hdr, &writer, err, sizeof err);
    if (rc != 0) {
        g->stats.event_spool_dropped++;
        gw_logf(g, "event: spool refused id=%s: %s",
                gw_u64_dec(event_id, (char[21]){0}), err);
        gw_notify_diag(g, "warning", "event_spool_full", err);
        g->event_retry_after[bank]=g->now_ms+1000u; /* Keep lease until durable storage succeeds. */
        return -1;
    }
    if (first_seg > 0 &&
        gw_copy_ddr_to_writer(g, (uint64_t)base + offset, first_seg, &writer) != 0)
        goto io_error;
    if (total > first_seg &&
        gw_copy_ddr_to_writer(g, base, total - first_seg, &writer) != 0)
        goto io_error;
    if (gw_spool_writer_finish(&g->spool, &writer, &rec, err, sizeof err) != 0)
        goto io_error;
    g->stats.events_captured++;
    {
        char data[1400];
        char line[GW_NOTIFY_BYTES];
        gw_json_writer w;
        gw_jw_init(&w, data, sizeof data);
        gw_event_record_json(g, &rec, &w);
        if (gw_jw_finish(&w)) {
            gw_jw_init(&w, line, sizeof line);
            gw_jw_begin_obj(&w);
            gw_jw_key(&w, "type"); gw_jw_str(&w, "event");
            gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
            gw_jw_key(&w, "version"); gw_jw_u32(&w, 1);
            gw_jw_key(&w, "event"); gw_jw_str(&w, "eventAdded");
            gw_jw_key(&w, "eventId"); gw_jw_u64dec_str(&w, g->next_event_id++);
            gw_jw_key(&w, "data"); gw_jw_raw_value(&w, data, strlen(data));
            gw_jw_end_obj(&w);
            if (gw_jw_finish(&w)) ctl_notify_subscribers(g, line, 1);
        }
    }
    gw_logf(g, "event: captured id=%s records=%u bank=%u",
            gw_u64_dec(event_id, (char[21]){0}), (unsigned)frames, bank);
    gw_release_clip(g, clip);
    return 0;
io_error:
    gw_spool_writer_abort(&writer);
    g->stats.event_capture_errors++;
    gw_logf(g, "event: capture IO failure id=%s",
            gw_u64_dec(event_id, (char[21]){0}));
    g->event_retry_after[bank]=g->now_ms+1000u; /* Retry, never acknowledge an uncopied clip. */
    return -1;
}

void gw_event_tick(gw *g)
{
    unsigned bank;
    uint32_t flags;
    if (!g) return;
    if (!g->cfg.mock_fixture && !g->cfg.allow_event_capture) return;
    if (!g->pl_identified || !g->has_result) return;
    if (!g->config_active_known) return;
    flags = g->config_active_words[SM_C_FLAGS];
    (void)bank;
    {
        for (bank = 0; bank < 2; bank++) {
            sm_clip clip;
            if(g->now_ms < g->event_retry_after[bank])continue;
            int rc;
            if ((flags & SM_RECORD_ENABLE) == 0u) break;
            rc = sm_read_clip(&g->mmio->dev, bank, &clip);
            if (rc == SM_NO_DATA) continue;
            if (rc == SM_OK) {
                gw_event_capture_bank(g, bank, &clip);
            } else if (rc != SM_RETRY) {
                g->stats.event_capture_errors++;
            }
        }
    }
}

/* ---------------------------------------------------------------- config */

int gw_config_validate(gw *g, const uint32_t words[32], uint32_t *bad_index,
                       const char **reason)
{
    uint32_t rl, rh;
    uint64_t req0_end, req1_end, analysis_end;
    uint32_t bank_bytes;
    if (!g || !words) return -1;
    if (words[SM_C_SESSION] == 0) { *bad_index = SM_C_SESSION; *reason = "session must be nonzero"; return -1; }
    if (words[SM_C_VERSION] == 0) { *bad_index = SM_C_VERSION; *reason = "version must be nonzero"; return -1; }
    if (words[SM_C_VERSION] == g->active_config_version) {
        *bad_index = SM_C_VERSION; *reason = "version equals active version"; return -1;
    }
    if (words[SM_C_VERSION] < g->active_config_version) {
        *bad_index = SM_C_VERSION; *reason = "version must increase"; return -1;
    }
    if (g->last_rejected_version && words[SM_C_VERSION] == g->last_rejected_version) {
        *bad_index = SM_C_VERSION; *reason = "version was already rejected"; return -1;
    }
    if (words[SM_C_ARENA_BASE] & 3u) { *bad_index = SM_C_ARENA_BASE; *reason = "arena base must be 4-byte aligned"; return -1; }
    if (words[SM_C_ARENA_WORDS] == 0 || words[SM_C_ARENA_WORDS] > 0x40000000u) {
        *bad_index = SM_C_ARENA_WORDS; *reason = "arena_words out of range"; return -1;
    }
    rl = words[SM_C_RESERVED_LOW];
    rh = words[SM_C_RESERVED_HIGH];
    if (rl >= rh) { *bad_index = SM_C_RESERVED_LOW; *reason = "reserved_low must be below reserved_high"; return -1; }
    if (words[SM_C_FLAGS] & ~(SM_P1_ENABLE | SM_P2_ENABLE | SM_PAUSE_P1 | SM_RECORD_ENABLE)) {
        *bad_index = SM_C_FLAGS; *reason = "unsupported config flag bits"; return -1;
    }
    /* descriptor word indices must live inside the arena and fit a 64-word
     * descriptor table (16 words * 4 slots). */
    if (words[SM_C_P1_DESCRIPTOR] != 0 &&
        (uint64_t)words[SM_C_P1_DESCRIPTOR] + 64u > words[SM_C_ARENA_WORDS]) {
        *bad_index = SM_C_P1_DESCRIPTOR; *reason = "p1 descriptor outside arena"; return -1;
    }
    if (words[SM_C_P2_DESCRIPTOR] != 0 &&
        (uint64_t)words[SM_C_P2_DESCRIPTOR] + 64u > words[SM_C_ARENA_WORDS]) {
        *bad_index = SM_C_P2_DESCRIPTOR; *reason = "p2 descriptor outside arena"; return -1;
    }
    if (words[SM_C_P1_STRIDE_WORDS] != 0 &&
        (words[SM_C_P1_STRIDE_WORDS] < 64u || (words[SM_C_P1_STRIDE_WORDS] & 15u) != 0u)) {
        *bad_index = SM_C_P1_STRIDE_WORDS; *reason = "p1 stride must be 0 or >=64 and 16-word aligned"; return -1;
    }
    if (words[SM_C_P2_ONESHOT] > 1u) {
        *bad_index = SM_C_P2_ONESHOT; *reason = "p2 oneshot must be 0 or 1"; return -1;
    }
    bank_bytes = words[SM_C_BANK_BYTES];
    if (words[SM_C_FLAGS] & SM_RECORD_ENABLE) {
        /* Mirror raw_legal in integration/instrument_top.sv: two 32-byte-record
         * rings, power-of-two >= 16 MiB, 4 KiB aligned, inside the raw window
         * (cfg words 11/12), disjoint from each other and from the arena. */
        uint32_t b0 = words[SM_C_BANK0];
        uint32_t b1 = words[SM_C_BANK1];
        uint32_t raw_low = words[SM_C_RAW_LOW];
        uint32_t raw_high = words[SM_C_RAW_HIGH];
        if (bank_bytes < (16u * 1024u * 1024u) || (bank_bytes & (bank_bytes - 1u)) != 0u) {
            *bad_index = SM_C_BANK_BYTES;
            *reason = "bank_bytes must be a power of two >= 16 MiB when recording";
            return -1;
        }
        if ((b0 & 0xFFFu) != 0u) { *bad_index = SM_C_BANK0; *reason = "bank0 must be 4 KiB aligned"; return -1; }
        if ((b1 & 0xFFFu) != 0u) { *bad_index = SM_C_BANK1; *reason = "bank1 must be 4 KiB aligned"; return -1; }
        if (raw_low >= raw_high) { *bad_index = SM_C_RAW_LOW; *reason = "raw window low must be below high"; return -1; }
        if (b0 < raw_low) { *bad_index = SM_C_BANK0; *reason = "bank0 below raw window low"; return -1; }
        if (b1 < raw_low) { *bad_index = SM_C_BANK1; *reason = "bank1 below raw window low"; return -1; }
        req0_end = (uint64_t)b0 + bank_bytes;
        req1_end = (uint64_t)b1 + bank_bytes;
        if (req0_end > raw_high) { *bad_index = SM_C_BANK0; *reason = "bank0 extends past raw window high"; return -1; }
        if (req1_end > raw_high) { *bad_index = SM_C_BANK1; *reason = "bank1 extends past raw window high"; return -1; }
        if (!(req0_end <= b1 || req1_end <= b0)) {
            *bad_index = SM_C_BANK0; *reason = "raw rings overlap"; return -1;
        }
        analysis_end = (uint64_t)words[SM_C_ARENA_BASE] + (uint64_t)words[SM_C_ARENA_WORDS] * 4u;
        if (!(req0_end <= words[SM_C_ARENA_BASE] || analysis_end <= b0)) {
            *bad_index = SM_C_BANK0; *reason = "ring0 overlaps analysis arena"; return -1;
        }
        if (!(req1_end <= words[SM_C_ARENA_BASE] || analysis_end <= b1)) {
            *bad_index = SM_C_BANK1; *reason = "ring1 overlaps analysis arena"; return -1;
        }
    }
    return 0;
}

int gw_config_commit_start(gw *g, uint32_t version, const uint32_t words[32],
                           uint64_t *job_id, const char **err_reason)
{
    uint32_t bad_index = 0,effective[32];
    memcpy(effective,words,sizeof effective);
    const char *reason = "";
    gw_job *job;
    int rc;
    if (!g->pl_identified) { *err_reason = "device_not_identified"; return -2; }
    if (!g->cfg.mock_fixture && !g->cfg.allow_config_commit) {
        *err_reason = "config_commit_capability_not_accepted";
        return -2;
    }
    if (g->pending_config||echo_features_busy(g)) { *err_reason = "config_commit_pending_or_feature_running"; return -3; }
    if (gw_config_validate(g, words, &bad_index, &reason) != 0) {
        *err_reason = reason;
        g->last_rejected_version = version;
        return -1;
    }
    if(echo_prepare_config(g,effective,&reason)){*err_reason=reason;return -1;}
    job = gw_job_alloc(g, "configCommit", "gateway", 0);
    if (!job) { *err_reason = "pending_job_limit"; return -4; }
    rc = sm_commit_config(&g->mmio->dev, effective);
    if (rc != SM_OK) {
        gw_job_set_state(g, job, GW_JOB_FAILED, "sm_commit_config failed");
        *err_reason = (rc == SM_BUSY) ? "pl_commit_pending" : "pl_commit_io_error";
        g->stats.config_io_errors++;
        return -5;
    }
    g->pending_config = 1;
    g->pending_config_version = version;
    memcpy(g->pending_config_words, effective, sizeof g->pending_config_words);
    g->pending_config_job = job->id;
    g->pending_config_deadline_ms = g->now_ms + g->cfg.config_confirm_timeout_ms;
    job->is_config_commit = 1;
    job->config_version = version;
    gw_job_set_state(g, job, GW_JOB_RUNNING, "waiting for PL config confirmation");
    if (gw_arb_held(&g->arb)) {
        job->counted_pending = 1;
        gw_arb_pending_inc(&g->arb);
    }
    *job_id = job->id;
    gw_logf(g, "config: commit version %u accepted job=%s", (unsigned)version,
            gw_u64_dec(job->id, (char[21]){0}));
    return 0;
}

void gw_config_abort(gw *g)
{
    if (!g) return;
    /* Only the uncommitted gateway-side shadow staging is discarded; a commit
     * already handed to the PL is an accepted transaction and still drains. */
    g->config_shadow_valid = 0;
}

/* ------------------------------------------------------------------ jobs */

void gw_job_id_str(uint64_t id, char out[24])
{
    char num[21];
    size_t n, k = 0, i;
    gw_u64_dec(id, num);
    n = strlen(num);
    memcpy(out, "job-", 4);
    k = 4;
    for (i = n; i < 10; i++) out[k++] = '0';
    memcpy(out + k, num, n + 1);
}

const char *gw_job_state_str(gw_job_state st)
{
    switch (st) {
    case GW_JOB_QUEUED: return "queued";
    case GW_JOB_RUNNING: return "running";
    case GW_JOB_COMPLETED: return "completed";
    case GW_JOB_FAILED: return "failed";
    case GW_JOB_CANCEL_REQUESTED: return "cancel_requested";
    case GW_JOB_CANCELED: return "canceled";
    default: return "unknown";
    }
}

gw_job *gw_job_alloc(gw *g, const char *kind, const char *client, int simulated)
{
    unsigned i;
    for (i = 0; i < GW_MAX_JOBS; i++) {
        gw_job *job = &g->jobs[i];
        if (job->used) continue;
        memset(job, 0, sizeof *job);
        job->used = 1;
        job->id = ++g->next_job_id;
        snprintf(job->kind, sizeof job->kind, "%s", kind ? kind : "unknown");
        if (client) snprintf(job->client_name, sizeof job->client_name, "%s", client);
        job->state = GW_JOB_QUEUED;
        job->simulated = simulated;
        job->created_ms = g->now_ms;
        job->updated_ms = g->now_ms;
        if (simulated) job->fixture_polls_left = g->cfg.job_fixture_polls;
        g->stats.jobs_started++;
        return job;
    }
    return NULL;
}

gw_job *gw_job_find(gw *g, uint64_t id)
{
    unsigned i;
    if (!g || id == 0) return NULL;
    for (i = 0; i < GW_MAX_JOBS; i++)
        if (g->jobs[i].used && g->jobs[i].id == id) return &g->jobs[i];
    return NULL;
}

gw_job *gw_job_find_task_key(gw *g, const char *key)
{
    unsigned i;
    if (!g || !key || !*key) return NULL;
    for (i = 0; i < GW_MAX_JOBS; i++)
        if (g->jobs[i].used && strcmp(g->jobs[i].client_task_key, key) == 0)
            return &g->jobs[i];
    return NULL;
}

void gw_job_json(gw *g, const gw_job *job, gw_json_writer *w)
{
    char id[24];
    (void)g;
    gw_job_id_str(job->id, id);
    gw_jw_begin_obj(w);
    gw_jw_key(w, "jobId"); gw_jw_str(w, id);
    gw_jw_key(w, "kind"); gw_jw_str(w, job->kind);
    gw_jw_key(w, "state"); gw_jw_str(w, gw_job_state_str(job->state));
    gw_jw_key(w, "simulated"); gw_jw_bool(w, job->simulated ? 1 : 0);
    if (job->client_task_key[0]) {
        gw_jw_key(w, "clientTaskKey"); gw_jw_str(w, job->client_task_key);
    }
    gw_jw_key(w, "createdMonotonicNs"); gw_jw_u64dec_str(w, job->created_ms * 1000000ull);
    gw_jw_key(w, "updatedMonotonicNs"); gw_jw_u64dec_str(w, job->updated_ms * 1000000ull);
    if (job->detail[0]) {
        gw_jw_key(w, "detail"); gw_jw_str(w, job->detail);
    }
    if (job->is_config_commit) {
        gw_jw_key(w, "configVersion"); gw_jw_u32(w, job->config_version);
    }
    gw_jw_end_obj(w);
}

static void gw_job_notify(gw *g, const gw_job *job)
{
    char data[1024];
    char line[GW_NOTIFY_BYTES];
    gw_json_writer w;
    gw_jw_init(&w, data, sizeof data);
    gw_job_json(g, job, &w);
    if (!gw_jw_finish(&w)) return;
    gw_jw_init(&w, line, sizeof line);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "type"); gw_jw_str(&w, "event");
    gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
    gw_jw_key(&w, "version"); gw_jw_u32(&w, 1);
    gw_jw_key(&w, "event"); gw_jw_str(&w, "jobUpdated");
    gw_jw_key(&w, "eventId"); gw_jw_u64dec_str(&w, g->next_event_id++);
    gw_jw_key(&w, "data"); gw_jw_raw_value(&w, data, strlen(data));
    gw_jw_end_obj(&w);
    if (gw_jw_finish(&w)) ctl_notify_all(g, line);
}

void gw_job_set_state(gw *g, gw_job *job, gw_job_state state, const char *detail)
{
    int terminal;
    if (!g || !job) return;
    terminal = (state == GW_JOB_COMPLETED || state == GW_JOB_FAILED ||
                state == GW_JOB_CANCELED);
    if (terminal && job->counted_pending) {
        job->counted_pending = 0;
        gw_arb_pending_dec(&g->arb);
    }
    job->state = state;
    job->updated_ms = g->now_ms;
    if (detail) snprintf(job->detail, sizeof job->detail, "%s", detail);
    if (state == GW_JOB_COMPLETED) g->stats.jobs_completed++;
    else if (state == GW_JOB_FAILED) g->stats.jobs_failed++;
    else if (state == GW_JOB_CANCELED) g->stats.jobs_canceled++;
    gw_job_notify(g, job);
}

uint32_t gw_jobs_pending(const gw *g)
{
    uint32_t n = 0;
    unsigned i;
    if (!g) return 0;
    for (i = 0; i < GW_MAX_JOBS; i++) {
        gw_job_state st = g->jobs[i].state;
        if (!g->jobs[i].used) continue;
        if (st == GW_JOB_QUEUED || st == GW_JOB_RUNNING ||
            st == GW_JOB_CANCEL_REQUESTED) n++;
    }
    return n;
}

void gw_jobs_tick(gw *g)
{
    unsigned i;
    if (!g) return;
    for (i = 0; i < GW_MAX_JOBS; i++) {
        gw_job *job = &g->jobs[i];
        if (!job->used || job->is_config_commit || !job->simulated) continue;
        if (job->state == GW_JOB_QUEUED) {
            gw_job_set_state(g, job, GW_JOB_RUNNING,
                             "fixture-mode job; simulated, no PL execution");
            continue;
        }
        if (job->state == GW_JOB_COMPLETED || job->state == GW_JOB_FAILED ||
            job->state == GW_JOB_CANCELED) continue;
        if (job->fixture_polls_left > 0) { job->fixture_polls_left--; continue; }
        if (job->state == GW_JOB_CANCEL_REQUESTED)
            gw_job_set_state(g, job, GW_JOB_CANCELED,
                             "cancel completed at fixture poll boundary");
        else
            gw_job_set_state(g, job, GW_JOB_COMPLETED,
                             "fixture-mode simulated completion; no PL task execution");
    }
}

/* ---------------------------------------------------------- notifications */

void gw_notify_diag(gw *g, const char *level, const char *code, const char *msg)
{
    char line[GW_NOTIFY_BYTES];
    gw_json_writer w;
    if (!g) return;
    gw_logf(g, "diag %s %s %s", level, code, msg ? msg : "");
    gw_jw_init(&w, line, sizeof line);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "type"); gw_jw_str(&w, "event");
    gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
    gw_jw_key(&w, "version"); gw_jw_u32(&w, 1);
    gw_jw_key(&w, "event"); gw_jw_str(&w, "diagnosticAdded");
    gw_jw_key(&w, "eventId"); gw_jw_u64dec_str(&w, g->next_event_id++);
    gw_jw_key(&w, "data");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "level"); gw_jw_str(&w, level);
    gw_jw_key(&w, "code"); gw_jw_str(&w, code);
    gw_jw_key(&w, "messageKey"); 
    {
        char key[128];
        snprintf(key, sizeof key, "errors.%s", code);
        gw_jw_str(&w, key);
    }
    gw_jw_key(&w, "detail"); gw_jw_str(&w, msg ? msg : "");
    gw_jw_key(&w, "monotonicNs"); gw_jw_u64dec_str(&w, gw_clock_ns());
    gw_jw_end_obj(&w);
    gw_jw_end_obj(&w);
    if (gw_jw_finish(&w)) ctl_notify_all(g, line);
}

void gw_notify_event(gw *g, const char *line)
{
    if (g && line) ctl_notify_all(g, line);
}

void gw_event_record_json(gw *g, const gw_event_rec *rec, gw_json_writer *w)
{
    char num[21];
    gw_jw_begin_obj(w);
    gw_jw_key(w, "eventId");
    gw_jw_str(w, gw_u64_dec(rec->event_id, num));
    gw_jw_key(w, "sourceKind");
    gw_jw_str(w, gw_source_kind(g));
    gw_jw_key(w, "simulated");
    gw_jw_bool(w, g->cfg.mock_fixture ? 1 : 0);
    gw_jw_key(w, "totalBytes");
    gw_jw_u64dec_str(w, rec->total_bytes);
    gw_jw_key(w, "recordCount");
    gw_jw_u64dec_str(w, rec->record_count);
    gw_jw_key(w, "firstSampleIndex");
    gw_jw_u64dec_str(w, rec->first_sample);
    gw_jw_key(w, "lastSampleIndex");
    gw_jw_u64dec_str(w, rec->last_sample);
    gw_jw_key(w, "sha256");
    gw_jw_str(w, rec->sha256);
    gw_jw_key(w, "flags");
    gw_jw_u32(w, rec->flags);
    gw_jw_key(w, "clipReason");
    gw_jw_u32(w, rec->clip_reason);
    gw_jw_key(w, "sampleRateFloat32Bits");
    gw_jw_u32(w, rec->sample_rate_word);
    gw_jw_key(w, "createdMonotonicNs");
    gw_jw_u64dec_str(w, rec->created_ms * 1000000ull);
    if(rec->created_unix_ms){gw_jw_key(w,"createdUnixMs");gw_jw_u64dec_str(w,rec->created_unix_ms);}
    else if((rec->event_id>>32)==g->epoch && rec->created_ms<=g->now_ms && time(NULL)>=1704067200){
        uint64_t wall=(uint64_t)time(NULL)*1000ull;
        uint64_t age=g->now_ms-rec->created_ms;
        if(age<wall){gw_jw_key(w,"createdUnixMs");gw_jw_u64dec_str(w,wall-age);}
    }
    gw_jw_key(w, "acked");
    gw_jw_bool(w, rec->acked ? 1 : 0);
    gw_jw_end_obj(w);
}
