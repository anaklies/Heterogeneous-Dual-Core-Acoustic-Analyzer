#include "control_server.h"
#include "binary_server.h"
#include "gateway.h"
#include "feature_runtime.h"
#include "utf8.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ============================================================ error catalog
 * Stable machine codes for sixmic-analysis v1. ERROR_CATALOG.json was not yet
 * present under interfaces/pc_backend_v1/errors/ when this candidate was
 * built (see docs/INTERFACE_GAPS.md); this table is the built-in mirror and is
 * the single place to update once the catalog file lands. Message keys are
 * "errors.<code>". */
typedef struct {
    const char *code;
    int retryable;
} gw_err_def;

static const gw_err_def k_errors[] = {
    { "bad_json", 0 },
    { "bad_utf8", 0 },
    { "line_too_long", 0 },
    { "protocol_mismatch", 0 },
    { "unsupported_version", 0 },
    { "unknown_op", 0 },
    { "bad_args", 0 },
    { "bad_state", 0 },
    { "not_authenticated", 0 },
    { "unknown_session", 0 },
    { "epoch_mismatch", 0 },
    { "bad_token", 0 },
    { "control_conflict", 1 },
    { "control_not_held", 0 },
    { "rejected", 0 },
    { "not_ready", 0 },
    { "unsupported_feature", 0 },
    { "busy", 1 },
    { "timeout", 1 },
    { "io_error", 1 },
    { "storage_full", 0 },
    { "cursor_expired", 0 },
    { "unknown_event", 0 },
    { "event_hash_mismatch", 1 },
    { "job_not_found", 0 },
    { "rate_limited", 1 },
    { "cancelled", 0 },
    { "internal_error", 0 }
};

static const gw_err_def *err_lookup(const char *code)
{
    size_t i;
    for (i = 0; i < sizeof k_errors / sizeof k_errors[0]; i++)
        if (strcmp(k_errors[i].code, code) == 0) return &k_errors[i];
    return NULL;
}

static const gw_json_node k_empty_object = {
    GW_JSON_OBJECT, 0, 0, 0, 0, 0, 0, 0.0, NULL, NULL
};

/* ============================================================== responses */

static void ctl_push_line(gw *g, gw_ctl_conn *c, const char *line)
{
    size_t n;
    char *tmp;
    if (!c->used) return;
    if (gw_msgq_count(&c->out) >= GW_MSGQ_MAX - 1) {
        g->stats.notify_dropped++;
        c->closing = 1;
        return;
    }
    n = strlen(line);
    tmp = (char *)malloc(n + 2);
    if (!tmp) { c->closing = 1; return; }
    memcpy(tmp, line, n);
    tmp[n] = '\n'; /* one LF-terminated UTF-8 JSON line (PROTOCOL.md 2.1) */
    tmp[n + 1] = 0;
    (void)gw_msgq_push(&c->out, tmp);
    free(tmp);
}

static void dup_clear(gw_ctl_conn *c)
{
    unsigned i;
    for (i = 0; i < GW_MAX_DUP_ENTRIES; i++) {
        if (c->dup[i].response) {
            free(c->dup[i].response);
            c->dup[i].response = NULL;
        }
        c->dup[i].request_id[0] = 0;
        c->dup[i].at_ms = 0;
    }
    c->dup_head = 0;
    c->dup_count = 0;
}

static const char *dup_find(gw *g, gw_ctl_conn *c, const char *rid, uint64_t *age_ms)
{
    unsigned i;
    for (i = 0; i < GW_MAX_DUP_ENTRIES; i++) {
        gw_dup_entry *e = &c->dup[i];
        if (!e->response || strcmp(e->request_id, rid) != 0) continue;
        if (g->now_ms - e->at_ms > (uint64_t)SMA_DUPLICATE_CACHE_SECONDS * 1000u) {
            free(e->response);
            e->response = NULL;
            e->request_id[0] = 0;
            return NULL;
        }
        if (age_ms) *age_ms = g->now_ms - e->at_ms;
        return e->response;
    }
    return NULL;
}

static void dup_add(gw *g, gw_ctl_conn *c, const char *rid, const char *line)
{
    gw_dup_entry *e;
    (void)g;
    if (!rid || !*rid) return;
    if (c->dup_count == GW_MAX_DUP_ENTRIES) {
        e = &c->dup[c->dup_head];
        free(e->response);
        e->response = NULL;
        c->dup_head = (c->dup_head + 1u) % GW_MAX_DUP_ENTRIES;
        c->dup_count--;
    }
    e = &c->dup[(c->dup_head + c->dup_count) % GW_MAX_DUP_ENTRIES];
    e->response = gw_strdup(line);
    if (!e->response) return;
    snprintf(e->request_id, sizeof e->request_id, "%s", rid);
    e->at_ms = g->now_ms;
    c->dup_count++;
}

/* Builds and queues one response frame. result_json / detail_json are raw JSON
 * fragments (or NULL). Returns 0 on success. */
static int ctl_respond(gw *g, gw_ctl_conn *c, const char *rid, const char *status,
                       const char *result_json, const char *err_code,
                       const char *detail_json, int cache)
{
    gw_json_writer w;
    size_t len;
    gw_jw_init(&w, g->rbuf, GW_LINE_BYTES);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "type"); gw_jw_str(&w, "response");
    gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
    gw_jw_key(&w, "version"); gw_jw_u32(&w, GW_PROTOCOL_VERSION);
    gw_jw_key(&w, "requestId"); gw_jw_str(&w, rid ? rid : "");
    gw_jw_key(&w, "status"); gw_jw_str(&w, status);
    if (result_json) {
        gw_jw_key(&w, "result");
        gw_jw_raw_value(&w, result_json, strlen(result_json));
    }
    if (err_code) {
        const gw_err_def *d = err_lookup(err_code);
        char key[96];
        gw_jw_key(&w, "error");
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "code"); gw_jw_str(&w, err_code);
        snprintf(key, sizeof key, "errors.%s", err_code);
        gw_jw_key(&w, "messageKey"); gw_jw_str(&w, key);
        gw_jw_key(&w, "retryable"); gw_jw_bool(&w, d ? d->retryable : 0);
        if (detail_json) {
            gw_jw_key(&w, "detail");
            gw_jw_raw_value(&w, detail_json, strlen(detail_json));
        }
        gw_jw_end_obj(&w);
    }
    gw_jw_end_obj(&w);
    len = gw_jw_finish(&w);
    if (!len) {
        snprintf(g->rbuf, GW_LINE_BYTES,
                 "{\"type\":\"response\",\"protocol\":\"%s\",\"version\":1,"
                 "\"requestId\":\"%s\",\"status\":\"error\","
                 "\"error\":{\"code\":\"internal\",\"messageKey\":\"errors.internal\","
                 "\"retryable\":true}}",
                 GW_PROTOCOL_NAME, rid ? rid : "");
        cache = 0;
        len = strlen(g->rbuf);
    }
    if (!c->used) return -1;
    ctl_push_line(g, c, g->rbuf);
    if (cache && rid && *rid) dup_add(g, c, rid, g->rbuf);
    (void)len;
    return 0;
}

static void ctl_ok(gw *g, gw_ctl_conn *c, const char *rid, const char *result_json)
{
    ctl_respond(g, c, rid, "ok", result_json, NULL, NULL, 1);
}

static void ctl_accepted(gw *g, gw_ctl_conn *c, const char *rid, const char *result_json)
{
    ctl_respond(g, c, rid, "accepted", result_json, NULL, NULL, 1);
}

static void ctl_error(gw *g, gw_ctl_conn *c, const char *rid, const char *code,
                      const char *detail_json)
{
    ctl_respond(g, c, rid, "error", NULL, code, detail_json, 1);
}

static void ctl_error_field(gw *g, gw_ctl_conn *c, const char *rid, const char *code,
                            const char *field, const char *reason)
{
    char detail[256];
    if (reason)
        snprintf(detail, sizeof detail, "{\"field\":\"%s\",\"reason\":\"%s\"}",
                 field, reason);
    else
        snprintf(detail, sizeof detail, "{\"field\":\"%s\"}", field);
    ctl_error(g, c, rid, code, detail);
}

static void ctl_error_close(gw *g, gw_ctl_conn *c, const char *rid, const char *code,
                            const char *detail_json)
{
    ctl_error(g, c, rid, code, detail_json);
    c->closing = 1;
}

/* ============================================================== utilities */

static int ctl_rate_ok(gw *g, gw_ctl_conn *c)
{
    double add;
    uint64_t elapsed = g->now_ms - c->rate_last_ms;
    c->rate_last_ms = g->now_ms;
    add = (double)elapsed * GW_RATE_PER_SEC / 1000.0;
    c->rate_tokens += add;
    if (c->rate_tokens > GW_RATE_BURST) c->rate_tokens = GW_RATE_BURST;
    if (c->rate_tokens < 1.0) {
        g->stats.rate_limited++;
        return 0;
    }
    c->rate_tokens -= 1.0;
    return 1;
}

static int rid_valid(const char *s, size_t n)
{
    size_t i;
    if (n < 1 || n > SMA_MAX_REQUEST_ID_BYTES) return 0;
    for (i = 0; i < n; i++) {
        char ch = s[i];
        if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
            (ch >= '0' && ch <= '9') || ch == '.' || ch == '_' || ch == ':' ||
            ch == '-')
            continue;
        return 0;
    }
    return 1;
}

static int token_is_hex32(const char *s)
{
    size_t i;
    if (!s || strlen(s) != 32) return 0;
    for (i = 0; i < 32; i++) {
        char ch = s[i];
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') ||
              (ch >= 'A' && ch <= 'F')))
            return 0;
    }
    return 1;
}

static int get_args_token(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid, char out[65])
{
    if (!args || gw_json_get_str(doc, args, "controlToken", out, 65, NULL) != 0 ||
        !token_is_hex32(out)) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return -1;
    }
    if (!gw_arb_can_write(&g->arb, out)) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return -1;
    }
    return 0;
}

static int get_job_id(const gw_json_doc *doc, const gw_json_node *args,
                      const char *key, uint64_t *out)
{
    char buf[32];
    size_t n = 0;
    if (!args || gw_json_get_str(doc, args, key, buf, sizeof buf, &n) != 0)
        return -1;
    if (n > 4 && memcmp(buf, "job-", 4) == 0) {
        return gw_parse_u64_dec(buf + 4, n - 4, out);
    }
    return gw_parse_u64_dec(buf, n, out);
}

/* ===================================================== capabilities/status */

void gw_capabilities_json(gw *g, gw_json_writer *w)
{
    gw_jw_begin_obj(w);
    gw_jw_key(w, "device");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "livePcm"); gw_jw_bool(w, g->caps.live_pcm);
    gw_jw_key(w, "liveResults"); gw_jw_bool(w, g->caps.live_results);
    gw_jw_key(w, "resultSnapshot");
    gw_jw_str(w, g->cfg.mock_fixture ? "fixture" :
              (g->caps.live_results ? "available" : "not_ready"));
    gw_jw_key(w, "serviceSnapshots");
    gw_jw_begin_arr(w);
    if (g->service_snapshot_enabled) gw_jw_str(w, "serviceSnapshot");
    gw_jw_end_arr(w);
    gw_jw_key(w, "eventCapture"); gw_jw_bool(w, g->caps.event_capture);
    gw_jw_key(w, "eventDownload"); gw_jw_bool(w, g->caps.event_download);
    gw_jw_key(w, "rawRecording"); gw_jw_bool(w, g->caps.raw_recording);
    gw_jw_key(w, "profileUpload"); gw_jw_bool(w, g->caps.profile_upload);
    gw_jw_key(w, "profileActivate"); gw_jw_bool(w, g->caps.profile_activate);
    gw_jw_key(w, "taskControl"); gw_jw_bool(w, g->caps.task_control);
    gw_jw_key(w, "sensorSnapshot"); gw_jw_bool(w, g->caps.sensor_snapshot);
    gw_jw_key(w, "deviceLog"); gw_jw_bool(w, g->caps.device_log);
    gw_jw_key(w, "configCommit"); gw_jw_bool(w, g->caps.config_commit);
    gw_jw_key(w, "configVersion"); gw_jw_u32(w, g->caps.config_version);
    gw_jw_key(w, "protocol3"); gw_jw_bool(w, g->caps.protocol3);
    gw_jw_key(w, "missing");
    gw_jw_begin_arr(w);
    gw_jw_str(w, "PS gateway not integrated on a real board");
    gw_jw_str(w, "PL raw ring PS consumer/lease and full bandwidth NOT accepted");
    if (g->cfg.mock_fixture)
        gw_jw_str(w, "MMIO is a deterministic fixture model, not hardware");
    gw_jw_end_arr(w);
    gw_jw_end_obj(w);
    gw_jw_key(w, "gateway");
    gw_jw_begin_obj(w);
    gw_jw_key(w,"featureApi");gw_jw_begin_obj(w);
    gw_jw_key(w,"version");gw_jw_u32(w,1);gw_jw_key(w,"enabled");gw_jw_bool(w,g->features!=NULL);
    gw_jw_key(w,"featureCount");gw_jw_u32(w,g->features?GW_FEATURE_COUNT:0);
    gw_jw_key(w,"maxResultWordsPerPage");gw_jw_u32(w,4096);
    gw_jw_key(w,"p0TransientFrames");gw_jw_bool(w,1);
    gw_jw_key(w,"liveFftProtocol");gw_jw_str(w,"echo-live-fft-1");
    gw_jw_key(w,"catalogPageSize");gw_jw_u32(w,8);
    gw_jw_end_obj(w);
    gw_jw_key(w, "version"); gw_jw_str(w, GW_VERSION);
    gw_jw_key(w, "protocol"); gw_jw_str(w, GW_PROTOCOL_NAME);
    gw_jw_key(w, "protocolVersion"); gw_jw_u32(w, GW_PROTOCOL_VERSION);
    gw_jw_key(w, "connectionEpoch"); gw_jw_u64dec_str(w, g->epoch);
    gw_jw_key(w, "mockFixture"); gw_jw_bool(w, g->cfg.mock_fixture ? 1 : 0);
    gw_jw_key(w, "simulated"); gw_jw_bool(w, g->cfg.mock_fixture ? 1 : 0);
    gw_jw_key(w, "eventSpoolLimitBytes"); gw_jw_u64dec_str(w, g->cfg.spool_limit_bytes);
    gw_jw_key(w,"eventLoopRecording");gw_jw_bool(w,g->spool.circular);
    gw_jw_key(w,"eventLoopEvictions");gw_jw_u64dec_str(w,g->spool.evicted_events);
    gw_jw_key(w, "serviceSnapshotEnabled");
    gw_jw_bool(w, g->service_snapshot_enabled ? 1 : 0);
    gw_jw_key(w, "fixtureStreams");
    gw_jw_begin_arr(w);
    if (g->cfg.mock_fixture) {
        gw_jw_str(w, "resultWords");
        gw_jw_str(w, "serviceSnapshot");
        gw_jw_str(w, "events");
        gw_jw_str(w, "eventFile");
    }
    gw_jw_end_arr(w);
    gw_jw_key(w, "limits");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "maxLineBytes"); gw_jw_u32(w, SMA_MAX_LINE_BYTES);
    gw_jw_key(w, "maxBinaryPayloadBytes"); gw_jw_u32(w, g->cfg.max_binary_payload);
    gw_jw_key(w, "maxPendingJobs"); gw_jw_u32(w, SMA_DEFAULT_MAX_PENDING_JOBS);
    gw_jw_key(w, "duplicateCacheSeconds"); gw_jw_u32(w, SMA_DUPLICATE_CACHE_SECONDS);
    gw_jw_key(w, "maxControlLeaseSeconds"); gw_jw_u32(w, g->cfg.max_control_lease_seconds);
    gw_jw_end_obj(w);
    gw_jw_end_obj(w);
    gw_jw_end_obj(w);
}

static void gw_status_json(gw *g, gw_ctl_conn *c, gw_json_writer *w)
{
    int held = gw_arb_held(&g->arb);
    gw_jw_begin_obj(w);
    gw_jw_key(w, "connectionEpoch"); gw_jw_u64dec_str(w, g->epoch);
    gw_jw_key(w, "sessionId"); gw_jw_str(w, c->session_id);
    gw_jw_key(w, "deviceState");
    /* status.schema.json enum: ready|no_link|degraded|fault|reconnecting.
     * Fixture mode is reported as ready with an explicit reason string. */
    gw_jw_str(w, g->pl_identified ? "ready" : "no_link");
    gw_jw_key(w, "deviceStateReasons");
    gw_jw_begin_arr(w);
    if (g->cfg.mock_fixture)
        gw_jw_str(w, "deterministic fixture MMIO model; not physical hardware");
    if (!g->pl_identified) gw_jw_str(w, "PL HOST register window not responding");
    gw_jw_end_arr(w);
    gw_jw_key(w, "control");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "held"); gw_jw_bool(w, held ? 1 : 0);
    gw_jw_key(w, "expiresInMs");
    if (held && g->arb.state == GW_ARB_HELD) {
        uint64_t remain = g->arb.expires_ms > g->now_ms
            ? g->arb.expires_ms - g->now_ms : 0;
        gw_jw_u32(w, (uint32_t)remain);
    } else {
        gw_jw_null(w);
    }
    gw_jw_end_obj(w);
    gw_jw_key(w, "config");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "activeVersion"); gw_jw_u32(w, g->active_config_version);
    gw_jw_key(w, "shadowVersion");
    gw_jw_u32(w, (g->config_shadow_valid ? g->config_shadow[SM_C_VERSION] :
                  g->active_config_version));
    gw_jw_key(w, "pending"); gw_jw_bool(w, g->pending_config ? 1 : 0);
    gw_jw_key(w, "lastRejectedVersion");
    if (g->last_rejected_version) gw_jw_u32(w, g->last_rejected_version);
    else gw_jw_null(w);
    gw_jw_end_obj(w);
    gw_jw_key(w, "resultFreshness");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "frameId");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_FRAME] : 0u);
    gw_jw_key(w, "configVersion");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_CONFIG] : 0u);
    gw_jw_key(w, "sampleIndex");
    gw_jw_begin_arr(w);
    gw_jw_u64dec_str(w, g->has_result ? sm_join_u64(g->snap.word[SM_R_SAMPLE_LOW],
                                                    g->snap.word[SM_R_SAMPLE_HIGH]) : 0u);
    gw_jw_u64dec_str(w, g->has_result ? g->snap.word[SM_R_SAMPLE_HIGH] : 0u);
    gw_jw_end_arr(w);
    gw_jw_key(w, "deviceMonotonicNs"); gw_jw_null(w);
    gw_jw_key(w, "receivedMonotonicNs");
    gw_jw_u64dec_str(w, g->snap_rx_ms * 1000000ull);
    gw_jw_key(w, "stale");
    gw_jw_bool(w, (!g->has_result ||
                   g->now_ms - g->snap_rx_ms > 1000u) ? 1 : 0);
    gw_jw_end_obj(w);
    gw_jw_key(w, "sensors"); gw_jw_null(w);
    gw_jw_key(w, "faults");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "faultBits");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_FAULTS] : g->pl_faults);
    gw_jw_key(w, "sensorErrors");
    gw_jw_u32(w, g->has_result ? (g->snap.word[SM_R_SENSOR_ERRORS] & 0xFFFFu) : 0u);
    gw_jw_key(w, "microphoneStatus");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_MIC_STATUS] : 0u);
    gw_jw_key(w, "missedWindows");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_MISSED] : 0u);
    gw_jw_key(w, "droppedSamples");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_DROPPED] : 0u);
    gw_jw_key(w, "lostEvents");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_LOST_EVENTS] : 0u);
    gw_jw_key(w, "handoffDrops");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_HANDOFF_DROPS] : 0u);
    gw_jw_end_obj(w);
    gw_jw_key(w, "queues");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "pcmPendingBytes"); gw_jw_u64dec_str(w, 0);
    gw_jw_key(w, "pcmDroppedBytes"); gw_jw_u64dec_str(w, 0);
    gw_jw_key(w, "resultDroppedFrames");
    gw_jw_u64dec_str(w, g->stats.result_frames_dropped);
    gw_jw_key(w, "eventSpoolBytes"); gw_jw_u64dec_str(w, g->spool.used_bytes);
    gw_jw_key(w, "eventSpoolLimitBytes"); gw_jw_u64dec_str(w, g->cfg.spool_limit_bytes);
    gw_jw_key(w,"eventLoopRecording");gw_jw_bool(w,g->spool.circular);
    gw_jw_key(w,"eventLoopEvictions");gw_jw_u64dec_str(w,g->spool.evicted_events);
    gw_jw_end_obj(w);
    gw_jw_key(w, "recording");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "recordingId"); gw_jw_null(w);
    gw_jw_key(w, "state"); gw_jw_str(w, "idle");
    gw_jw_end_obj(w);
    gw_jw_key(w, "jobs");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "pending"); gw_jw_u32(w, gw_jobs_pending(g));
    gw_jw_end_obj(w);
    gw_jw_key(w, "pl");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "resultWordProtocol");
    gw_jw_u32(w, g->has_result ? g->snap.word[SM_R_PROTOCOL] : 0u);
    {
        char alg[16];
        snprintf(alg, sizeof alg, "0x%08x",
                 (unsigned)(g->has_result ? g->snap.word[SM_R_ALGORITHM] : 0u));
        gw_jw_key(w, "algorithmId"); gw_jw_str(w, alg);
    }
    {
        char cap[24];
        snprintf(cap, sizeof cap, "0x%08x%08x",
                 (unsigned)(g->pl_capabilities >> 32),
                 (unsigned)(g->pl_capabilities & 0xFFFFFFFFu));
        gw_jw_key(w, "capabilities"); gw_jw_str(w, cap);
    }
    gw_jw_end_obj(w);
    gw_jw_end_obj(w);
}

/* ============================================================ connection */

static int ctl_index(gw *g, gw_ctl_conn *c);
static void free_sub(gw_subscription *s);
static void free_bin_session(gw_bin_session *s);
void ctl_conn_close(gw *g, gw_ctl_conn *c)
{
    if (!c || !c->used) return;
    echo_features_owner_closed(g,c->session_id);
    if (g->holder_session[0] &&
        strcmp(g->holder_session, c->session_id) == 0 &&
        gw_arb_held(&g->arb)) {
        gw_arb_force_release(&g->arb, g->now_ms);
        gw_logf(g, "control: holder session %s disconnected; draining", c->session_id);
        g->holder_session[0] = 0;
    }
    /* A disconnected control owner must release its bounded subscriptions. */
    for (unsigned i = 0; i < GW_MAX_BINARY_SESSIONS; ++i) {
        gw_bin_session *s = &g->bin_sessions[i];
        if (!s->used || s->owner_conn != ctl_index(g, c)) continue;
        if (s->bound_conn >= 0 && s->bound_conn < (int)GW_MAX_BINARY_CONNS)
            bin_server_close_conn(g, &g->bin[s->bound_conn], "control_disconnected");
        free_bin_session(s);
    }
    for (unsigned i = 0; i < GW_MAX_SUBSCRIPTIONS; ++i) {
        if (g->subs[i].used && g->subs[i].owner_conn == ctl_index(g, c)) free_sub(&g->subs[i]);
    }
    gw_net_close(c->fd);
    gw_msgq_free(&c->out);
    dup_clear(c);
    memset(c, 0, sizeof *c);
}

void ctl_conn_mark_closing(gw *g, gw_ctl_conn *c)
{
    (void)g;
    if (c && c->used) c->closing = 1;
}

void ctl_server_flush(gw *g, gw_ctl_conn *c)
{
    if (!c || !c->used) return;
    while (gw_msgq_count(&c->out) > 0) {
        const char *line = gw_msgq_front(&c->out);
        size_t n, len;
        int sent;
        if (!line) { gw_msgq_pop(&c->out); continue; }
        len = strlen(line);
        if (c->out_off >= len) {
            c->out_off = 0;
            gw_msgq_pop(&c->out);
            continue;
        }
        n = len - c->out_off;
        sent = gw_net_send(c->fd, line + c->out_off, n);
        if (sent == GW_SEND_AGAIN) return;
        if (sent <= 0) { ctl_conn_close(g, c); return; }
        c->out_off += (size_t)sent;
        if (c->out_off < len) return;
        c->out_off = 0;
        gw_msgq_pop(&c->out);
    }
}

void ctl_notify_all(gw *g, const char *line)
{
    unsigned i;
    if (!g || !line) return;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        if (!c->used || !c->hello_done) continue;
        ctl_push_line(g, c, line);
    }
}

void ctl_notify_subscribers(gw *g, const char *line, int events_only)
{
    unsigned i;
    if (!g || !line) return;
    for (i = 0; i < GW_MAX_SUBSCRIPTIONS; i++) {
        gw_subscription *s = &g->subs[i];
        if (!s->used || !s->wants_events) continue;
        if (events_only && !s->wants_events) continue;
        if (s->owner_conn >= 0 && s->owner_conn < (int)GW_MAX_CONTROL_CONNS) {
            gw_ctl_conn *c = &g->ctl[s->owner_conn];
            if (c->used && c->hello_done) ctl_push_line(g, c, line);
        }
    }
}

/* ============================================================ dispatch */

typedef void (*ctl_op_fn)(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid);

typedef struct {
    const char *name;
    ctl_op_fn fn;
} ctl_op_entry;

static void op_hello(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                     const gw_json_node *args, const char *rid);
static void op_capabilities_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                                const gw_json_node *args, const char *rid);
static void op_status_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid);
static void op_diagnostics_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid);
static void op_heartbeat(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid);
static void op_control_claim(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid);
static void op_control_renew(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid);
static void op_control_release(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid);
static void op_subscribe(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid);
static void op_stream_open(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid);
static void op_stream_close(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid);
static void op_unsubscribe(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid);
static void op_config_read(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid);
static void op_config_write(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid);
static void op_config_commit(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid);
static void op_config_abort(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid);
static void op_task_start(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid);
static void op_task_cancel(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid);
static void op_job_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                       const gw_json_node *args, const char *rid);
static void op_job_list(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                        const gw_json_node *args, const char *rid);
static void op_recording_start(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid);
static void op_recording_stop(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                              const gw_json_node *args, const char *rid);
static void op_recording_status(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                                const gw_json_node *args, const char *rid);
static void op_event_list(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid);
static void op_event_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid);
static void op_event_download(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                              const gw_json_node *args, const char *rid);
static void op_event_ack(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid);
static void op_event_discard(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid);
static void op_profile(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                       const gw_json_node *args, const char *rid);

static void op_feature(gw *g,gw_ctl_conn*c,const gw_json_doc*doc,const gw_json_node*args,const char*rid){
    const char*error="internal_error";char op[40];char*result=malloc(GW_LINE_BYTES);int rc;
    if(!result){ctl_error(g,c,rid,"internal_error",NULL);return;}
    if(gw_json_get_str(doc,gw_json_root(doc),"op",op,sizeof op,NULL)){free(result);return;}
    rc=echo_features_dispatch(g,op,doc,args,result,GW_LINE_BYTES,&error);
    if(rc<0)ctl_error(g,c,rid,error,"{\"reason\":\"feature_input_state_or_parameter_requirements_not_met\"}");
    else if(rc)ctl_accepted(g,c,rid,result);else ctl_ok(g,c,rid,result);
    free(result);
}

static void op_time_sync(gw *g,gw_ctl_conn *c,const gw_json_doc *doc,const gw_json_node *args,const char *rid){
    uint64_t ms=0;char result[160];
    const gw_json_node *n=gw_json_obj_get(doc,args,"unixTimeMs");
    if(!n||gw_json_node_u64_dec(doc,n,&ms)||ms<1704067200000ull||ms>4102444800000ull){ctl_error(g,c,rid,"bad_args",NULL);return;}
#if !defined(_WIN32)
    if(!g->cfg.mock_fixture){struct timespec ts;ts.tv_sec=(time_t)(ms/1000);ts.tv_nsec=(long)(ms%1000)*1000000;
        if(clock_settime(CLOCK_REALTIME,&ts)){ctl_error(g,c,rid,"io_error",NULL);return;}}
#endif
    snprintf(result,sizeof result,"{\"synchronized\":%s,\"unixTimeMs\":\"%llu\",\"source\":\"pc\",\"sampleClockChanged\":false}",g->cfg.mock_fixture?"false":"true",(unsigned long long)ms);
    ctl_ok(g,c,rid,result);
}
static const ctl_op_entry k_ops[] = {
    {"time.sync",op_time_sync},
    {"feature.list",op_feature},{"feature.start",op_feature},{"feature.stop",op_feature},{"feature.get",op_feature},{"feature.result",op_feature},
    { "hello", op_hello },
    { "capabilities.get", op_capabilities_get },
    { "status.get", op_status_get },
    { "diagnostics.get", op_diagnostics_get },
    { "heartbeat", op_heartbeat },
    { "control.claim", op_control_claim },
    { "control.renew", op_control_renew },
    { "control.release", op_control_release },
    { "subscribe", op_subscribe },
    { "stream.open", op_stream_open },
    { "stream.close", op_stream_close },
    { "unsubscribe", op_unsubscribe },
    { "config.read", op_config_read },
    { "config.write", op_config_write },
    { "config.commit", op_config_commit },
    { "config.abort", op_config_abort },
    { "task.start", op_task_start },
    { "task.cancel", op_task_cancel },
    { "job.get", op_job_get },
    { "job.list", op_job_list },
    { "recording.start", op_recording_start },
    { "recording.stop", op_recording_stop },
    { "recording.status", op_recording_status },
    { "event.list", op_event_list },
    { "event.get", op_event_get },
    { "event.download", op_event_download },
    { "event.ack", op_event_ack },
    { "event.discard", op_event_discard },
    { "profile.upload", op_profile },
    { "profile.activate", op_profile },
    { "profile.deactivate", op_profile }
};

static ctl_op_fn find_op(const char *name)
{
    size_t i;
    for (i = 0; i < sizeof k_ops / sizeof k_ops[0]; i++)
        if (strcmp(k_ops[i].name, name) == 0) return k_ops[i].fn;
    return NULL;
}

/* ============================================================ line input */

static void ctl_process_line(gw *g, gw_ctl_conn *c)
{
    size_t len = c->in_line_len;
    char errbuf[96];
    gw_json_doc doc;
    const gw_json_node *root, *v, *args;
    char rid[65] = "";
    char op[40];
    char proto[40];
    uint32_t version = 0;
    size_t i;
    int found_op = 0;
    const char *cached;
    c->in_line[len] = 0;
    g->stats.control_requests++;
    c->requests++;
    if (len == 0) { c->empty_lines++; return; }
    if (!ctl_rate_ok(g, c)) {
        ctl_error(g, c, "0", "busy", NULL);
        return;
    }
    for (i = 0; i < len; i++) {
        if (c->in_line[i] == '\r') {
            g->stats.bad_json_frames++;
            c->bad_json_frames++;
            ctl_error(g, c, "0", "bad_json", "{\"reason\":\"CR is not a legal frame terminator\"}");
            return;
        }
    }
    {
        size_t bad = 0;
        if (!gw_utf8_valid((const uint8_t *)c->in_line, len, &bad)) {
            char detail[96];
            g->stats.bad_utf8_frames++;
            snprintf(detail, sizeof detail, "{\"offset\":%u}", (unsigned)bad);
            ctl_error_close(g, c, "0", "bad_utf8", detail);
            return;
        }
    }
    if (gw_json_parse(&doc, c->in_line, len, SMA_MAX_JSON_DEPTH, 20000,
                      errbuf, sizeof errbuf) != 0) {
        char detail[192];
        g->stats.bad_json_frames++;
        c->bad_json_frames++;
        snprintf(detail, sizeof detail, "{\"reason\":\"%s\"}", errbuf);
        ctl_error(g, c, "0", "bad_json", detail);
        return;
    }
    root = gw_json_root(&doc);
    if (!root || root->type != GW_JSON_OBJECT) {
        g->stats.bad_json_frames++;
        ctl_error(g, c, "0", "bad_json", "{\"reason\":\"frame must be a JSON object\"}");
        gw_json_doc_free(&doc);
        return;
    }
    if (gw_json_get_str(&doc, root, "protocol", proto, sizeof proto, NULL) != 0) {
        ctl_error(g, c, "0", "bad_json", "{\"reason\":\"protocol field missing\"}");
        gw_json_doc_free(&doc);
        return;
    }
    if (strcmp(proto, GW_PROTOCOL_NAME) != 0) {
        ctl_error_close(g, c, "0", "protocol_mismatch", NULL);
        gw_json_doc_free(&doc);
        return;
    }
    if (gw_json_get_u32(&doc, root, "version", &version) != 0 || version != 1u) {
        ctl_error(g, c, "0", "unsupported_version", "{\"supported\":1}");
        gw_json_doc_free(&doc);
        return;
    }
    {
        size_t rlen = 0;
        if (gw_json_get_str(&doc, root, "requestId", rid, sizeof rid, &rlen) != 0 ||
            !rid_valid(rid, rlen)) {
            ctl_error_field(g, c, "0", "bad_args", "requestId",
                            "1..64 chars of A-Za-z0-9._:-");
            gw_json_doc_free(&doc);
            return;
        }
    }
    cached = dup_find(g, c, rid, NULL);
    if (cached) {
        g->stats.duplicate_requests++;
        ctl_push_line(g, c, cached);
        gw_json_doc_free(&doc);
        return;
    }
    if (gw_json_get_str(&doc, root, "op", op, sizeof op, NULL) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "op", "missing");
        gw_json_doc_free(&doc);
        return;
    }
    v = gw_json_obj_get(&doc, root, "args");
    if (v && v->type != GW_JSON_OBJECT) {
        ctl_error_field(g, c, rid, "bad_args", "args", "must be an object");
        gw_json_doc_free(&doc);
        return;
    }
    args = v ? v : &k_empty_object;
    if (strcmp(op, "hello") != 0) {
        char session[65];
        if (!c->hello_done) {
            ctl_error(g, c, rid, "not_authenticated", NULL);
            gw_json_doc_free(&doc);
            return;
        }
        if (gw_json_get_str(&doc, root, "sessionId", session, sizeof session, NULL) != 0) {
            ctl_error_field(g, c, rid, "bad_args", "sessionId", "missing");
            gw_json_doc_free(&doc);
            return;
        }
        if (strcmp(session, c->session_id) != 0) {
            ctl_error(g, c, rid, "unknown_session", NULL);
            gw_json_doc_free(&doc);
            return;
        }
    }
    {
        ctl_op_fn fn = find_op(op);
        found_op = fn != NULL;
        if (fn) fn(g, c, &doc, args, rid);
    }
    if (!found_op) {
        g->stats.unknown_ops++;
        ctl_error(g, c, rid, "unknown_op", NULL);
    }
    gw_json_doc_free(&doc);
}

void ctl_server_on_readable(gw *g, gw_ctl_conn *c)
{
    if (!c || !c->used) return;
    for (;;) {
        int n;
        size_t i;
        if (c->closing) return;
        n = gw_net_recv(c->fd, c->inbuf, sizeof c->inbuf);
        if (n == GW_RECV_AGAIN) return;
        if (n <= 0) { ctl_conn_close(g, c); return; }
        c->last_rx_ms = g->now_ms;
        for (i = 0; i < (size_t)n; i++) {
            uint8_t ch = c->inbuf[i];
            if (c->dropping_line) {
                if (ch == '\n') {
                    g->stats.line_too_long_frames++;
                    ctl_error_close(g, c, "0", "line_too_long",
                                    "{\"maxLineBytes\":65536}");
                    return;
                }
                continue;
            }
            if (ch == '\n') {
                ctl_process_line(g, c);
                c->in_line_len = 0;
                if (c->closing) return;
                continue;
            }
            if (c->in_line_len + 1 >= GW_LINE_BYTES) {
                c->dropping_line = 1;
                c->in_line_len = 0;
                continue;
            }
            c->in_line[c->in_line_len++] = (char)ch;
        }
    }
}

void ctl_server_tick(gw *g)
{
    unsigned i;
    if (!g) return;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++) {
        gw_ctl_conn *c = &g->ctl[i];
        if (!c->used) continue;
        if (!c->hello_done && g->now_ms - c->connected_ms > 10000u) {
            gw_logf(g, "control: handshake timeout session=%s", c->session_id);
            ctl_conn_close(g, c);
            continue;
        }
        if (g->now_ms - c->last_rx_ms > GW_CONTROL_IDLE_MS) {
            gw_logf(g, "control: idle timeout session=%s", c->session_id);
            ctl_conn_close(g, c);
            continue;
        }
    }
}

int ctl_server_init(gw *g, char *err, size_t errcap)
{
    (void)g;
    (void)err;
    (void)errcap;
    return 0;
}

void ctl_server_shutdown(gw *g)
{
    unsigned i;
    if (!g) return;
    for (i = 0; i < GW_MAX_CONTROL_CONNS; i++)
        if (g->ctl[i].used) ctl_conn_close(g, &g->ctl[i]);
}
/* ============================================================ small JSON */

static int ctl_index(gw *g, gw_ctl_conn *c)
{
    return (int)(c - g->ctl);
}

static int sync_shadow(gw *g)
{
    unsigned i;
    if (g->config_shadow_valid) return 0;
    for (i = 0; i < 32; i++) {
        if (gw_device_read_reg(g, 0x40u + 4u * i, &g->config_shadow[i]) != 0)
            return -1;
    }
    g->config_shadow_valid = 1;
    return 0;
}

static void notify_control_changed(gw *g)
{
    char line[GW_NOTIFY_BYTES];
    gw_json_writer w;
    int held = gw_arb_held(&g->arb);
    gw_jw_init(&w, line, sizeof line);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "type"); gw_jw_str(&w, "event");
    gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
    gw_jw_key(&w, "version"); gw_jw_u32(&w, 1);
    gw_jw_key(&w, "event"); gw_jw_str(&w, "controlChanged");
    gw_jw_key(&w, "eventId"); gw_jw_u64dec_str(&w, g->next_event_id++);
    gw_jw_key(&w, "data");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "held"); gw_jw_bool(&w, held ? 1 : 0);
    gw_jw_key(&w, "state"); gw_jw_str(&w, gw_arb_state_name(&g->arb));
    if (held) {
        gw_jw_key(&w, "owner"); gw_jw_str(&w, g->arb.owner);
        gw_jw_key(&w, "expiresInMs");
        gw_jw_u32(&w, g->arb.expires_ms > g->now_ms
                  ? (uint32_t)(g->arb.expires_ms - g->now_ms) : 0u);
    }
    gw_jw_end_obj(&w);
    gw_jw_end_obj(&w);
    if (gw_jw_finish(&w)) ctl_notify_all(g, line);
}

static int sha_hex_valid(const char *s)
{
    size_t i;
    if (!s || strlen(s) != 64) return 0;
    for (i = 0; i < 64; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    return 1;
}

static gw_subscription *find_sub(gw *g, const char *id)
{
    unsigned i;
    for (i = 0; i < GW_MAX_SUBSCRIPTIONS; i++)
        if (g->subs[i].used && strcmp(g->subs[i].id, id) == 0) return &g->subs[i];
    return NULL;
}

static gw_subscription *alloc_sub(gw *g, gw_ctl_conn *c)
{
    unsigned i;
    for (i = 0; i < GW_MAX_SUBSCRIPTIONS; i++) {
        gw_subscription *s = &g->subs[i];
        if (s->used) continue;
        memset(s, 0, sizeof *s);
        s->used = 1;
        s->owner_conn = ctl_index(g, c);
        s->created_ms = g->now_ms;
        g->next_sub_seq++;
        snprintf(s->id, sizeof s->id, "sub-%04u", (unsigned)g->next_sub_seq);
        return s;
    }
    return NULL;
}

static void free_sub(gw_subscription *s)
{
    unsigned i;
    if (!s) return;
    for (i = 0; i < s->nstreams; i++) gw_stream_def_free(&s->streams[i]);
    memset(s, 0, sizeof *s);
}

static void free_bin_session(gw_bin_session *s)
{
    unsigned i;
    if (!s) return;
    for (i = 0; i < s->nstreams; i++) gw_stream_def_free(&s->streams[i]);
    memset(s, 0, sizeof *s);
}

static gw_bin_session *alloc_bin_session(gw *g)
{
    unsigned i;
    for (i = 0; i < GW_MAX_BINARY_SESSIONS; i++) {
        gw_bin_session *s = &g->bin_sessions[i];
        if (s->used && s->bound_conn < 0 && g->now_ms > s->expires_ms) free_bin_session(s);
        if (s->used) continue;
        memset(s, 0, sizeof *s);
        s->used = 1;
        s->bound_conn = -1;
        s->created_ms = g->now_ms;
        s->expires_ms = g->now_ms + 60000u;
        {
            uint8_t rnd[16];
            gw_random_bytes(rnd, sizeof rnd);
            gw_hex_encode(rnd, sizeof rnd, s->token, sizeof s->token);
        }
        return s;
    }
    return NULL;
}

static void add_stream_list_json(gw_json_writer *w, const gw_stream_def *defs,
                                 uint32_t n)
{
    uint32_t i;
    gw_jw_begin_arr(w);
    for (i = 0; i < n; i++) {
        gw_jw_begin_obj(w);
        gw_jw_key(w, "streamId"); gw_jw_u32(w, defs[i].stream_id);
        gw_jw_key(w, "type"); gw_jw_str(w, defs[i].type);
        gw_jw_key(w, "schemaSha256"); gw_jw_str(w, defs[i].schema_sha);
        gw_jw_end_obj(w);
    }
    gw_jw_end_arr(w);
}

/* =============================================================== handlers */

static void op_hello(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                     const gw_json_node *args, const char *rid)
{
    char name[65];
    char ver[33];
    uint32_t client_max = 0;
    char res[12288];
    char caps[8192];
    gw_json_writer w, cw;
    if (c->hello_done) {
        ctl_error(g, c, rid, "bad_state", "{\"reason\":\"hello already completed\"}");
        return;
    }
    if (gw_json_get_str(doc, args, "clientName", name, sizeof name, NULL) != 0 ||
        name[0] == 0) {
        ctl_error_field(g, c, rid, "bad_args", "clientName", "1..64 chars required");
        return;
    }
    if (gw_json_get_str(doc, args, "clientVersion", ver, sizeof ver, NULL) != 0)
        ver[0] = 0;
    if (gw_json_get_u32(doc, args, "maxBinaryPayloadBytes", &client_max) == 0) {
        if (client_max < SMA_MIN_MAX_BINARY_PAYLOAD)
            client_max = SMA_MIN_MAX_BINARY_PAYLOAD;
        if (client_max > SMA_MAX_MAX_BINARY_PAYLOAD)
            client_max = SMA_MAX_MAX_BINARY_PAYLOAD;
    } else {
        client_max = g->cfg.max_binary_payload;
    }
    snprintf(c->client_name, sizeof c->client_name, "%s", name);
    snprintf(c->client_version, sizeof c->client_version, "%s", ver);
    c->client_max_payload = client_max;
    c->hello_done = 1;
    gw_jw_init(&cw, caps, sizeof caps);
    gw_capabilities_json(g, &cw);
    if (!gw_jw_finish(&cw)) {
        ctl_error(g, c, rid, "internal_error", NULL);
        return;
    }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "protocol"); gw_jw_str(&w, GW_PROTOCOL_NAME);
    gw_jw_key(&w, "protocolVersion"); gw_jw_u32(&w, GW_PROTOCOL_VERSION);
    gw_jw_key(&w, "serverVersion"); gw_jw_str(&w, GW_VERSION);
    gw_jw_key(&w, "deviceId"); gw_jw_str(&w, g->device_id);
    gw_jw_key(&w, "connectionEpoch"); gw_jw_u64dec_str(&w, g->epoch);
    gw_jw_key(&w, "sessionId"); gw_jw_str(&w, c->session_id);
    gw_jw_key(&w, "limits");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "maxLineBytes"); gw_jw_u32(&w, SMA_MAX_LINE_BYTES);
    gw_jw_key(&w, "maxBinaryPayloadBytes"); gw_jw_u32(&w, g->cfg.max_binary_payload);
    gw_jw_key(&w, "maxPendingJobs"); gw_jw_u32(&w, SMA_DEFAULT_MAX_PENDING_JOBS);
    gw_jw_key(&w, "duplicateCacheSeconds"); gw_jw_u32(&w, SMA_DUPLICATE_CACHE_SECONDS);
    gw_jw_key(&w, "maxControlLeaseSeconds"); gw_jw_u32(&w, g->cfg.max_control_lease_seconds);
    gw_jw_end_obj(&w);
    gw_jw_key(&w, "capabilities");
    gw_jw_raw_value(&w, caps, strlen(caps));
    gw_jw_key(&w, "config");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "activeVersion"); gw_jw_u32(&w, g->active_config_version);
    gw_jw_key(&w, "pending"); gw_jw_bool(&w, g->pending_config ? 1 : 0);
    gw_jw_key(&w, "shadowDirty"); gw_jw_bool(&w, g->config_shadow_valid ? 1 : 0);
    gw_jw_end_obj(&w);
    gw_jw_key(&w, "control");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "held"); gw_jw_bool(&w, gw_arb_held(&g->arb) ? 1 : 0);
    gw_jw_end_obj(&w);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) {
        ctl_error(g, c, rid, "internal_error", NULL);
        return;
    }
    gw_logf(g, "control: hello from %s version %s session=%s", name, ver,
            c->session_id);
    ctl_ok(g, c, rid, res);
}

static void op_capabilities_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                                const gw_json_node *args, const char *rid)
{
    char res[8192];
    gw_json_writer w;
    (void)doc; (void)args;
    gw_jw_init(&w, res, sizeof res);
    gw_capabilities_json(g, &w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_status_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid)
{
    char res[8192];
    gw_json_writer w;
    (void)doc; (void)args;
    gw_jw_init(&w, res, sizeof res);
    gw_status_json(g, c, &w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_diagnostics_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid)
{
    char res[65536];
    gw_json_writer w;
    uint32_t tail = 50;
    unsigned total, start, i;
    if (gw_json_get_u32(doc, args, "tailLines", &tail) == 0) {
        if (tail < 1 || tail > 2000) {
            ctl_error_field(g, c, rid, "bad_args", "tailLines", "1..2000");
            return;
        }
    }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "deviceLog");
    gw_jw_begin_arr(&w);
    total = gw_log_count(&g->log);
    start = (total > tail) ? total - tail : 0;
    for (i = start; i < total; i++) gw_jw_str(&w, gw_log_at(&g->log, i));
    gw_jw_end_arr(&w);
    gw_jw_key(&w, "logDropped"); gw_jw_u64dec_str(&w, g->log.dropped);
    gw_jw_key(&w, "queues");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "pcmPendingBytes"); gw_jw_u64dec_str(&w, 0);
    gw_jw_key(&w, "pcmDroppedBytes"); gw_jw_u64dec_str(&w, 0);
    gw_jw_key(&w, "resultDroppedFrames"); gw_jw_u64dec_str(&w, g->stats.result_frames_dropped);
    gw_jw_key(&w, "eventSpoolBytes"); gw_jw_u64dec_str(&w, g->spool.used_bytes);
    gw_jw_key(&w, "eventSpoolLimitBytes"); gw_jw_u64dec_str(&w, g->cfg.spool_limit_bytes);
    gw_jw_key(&w, "snapshotRetries"); gw_jw_u64dec_str(&w, g->stats.snapshot_retries);
    gw_jw_key(&w, "snapshotErrors"); gw_jw_u64dec_str(&w, g->stats.snapshot_errors);
    gw_jw_key(&w, "serviceSnapshotRetries"); gw_jw_u64dec_str(&w, g->stats.service_snapshot_retries);
    gw_jw_key(&w, "eventSpoolDropped"); gw_jw_u64dec_str(&w, g->stats.event_spool_dropped);
    gw_jw_key(&w, "controlNotifyDropped"); gw_jw_u64dec_str(&w, g->stats.notify_dropped);
    gw_jw_key(&w, "binaryUnknownFrames"); gw_jw_u64dec_str(&w, g->stats.binary_unknown_frames);
    gw_jw_key(&w, "binaryBadFrames"); gw_jw_u64dec_str(&w, g->stats.binary_bad_frames);
    gw_jw_key(&w, "eventsCaptured"); gw_jw_u64dec_str(&w, g->stats.events_captured);
    gw_jw_end_obj(&w);
    gw_jw_key(&w, "uptimeSeconds");
    gw_jw_u32(&w, (uint32_t)((g->now_ms - g->start_ms) / 1000u));
    gw_jw_key(&w, "gatewayVersion"); gw_jw_str(&w, GW_VERSION);
    gw_jw_key(&w, "faults");
    gw_jw_u32(&w, g->has_result ? g->snap.word[SM_R_FAULTS] : g->pl_faults);
    gw_jw_key(&w, "mode");
    gw_jw_str(&w, g->cfg.mock_fixture ? "mock-fixture" : "device");
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_heartbeat(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid)
{
    char res[128];
    gw_json_writer w;
    (void)doc; (void)args;
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "serverMonotonicNs"); gw_jw_u64dec_str(&w, gw_clock_ns());
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_control_claim(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid)
{
    uint32_t lease = GW_DEFAULT_LEASE_SECONDS;
    char token[GW_ARB_TOKEN_HEX + 1];
    char holder[GW_ARB_OWNER_MAX];
    char res[1024];
    char detail[512];
    uint64_t expires = 0, since = 0;
    gw_json_writer w;
    int rc;
    if (gw_json_get_u32(doc, args, "leaseSeconds", &lease) == 0) {
        if (lease < 5 || lease > 300) {
            ctl_error_field(g, c, rid, "bad_args", "leaseSeconds", "5..300");
            return;
        }
    } else {
        lease = GW_DEFAULT_LEASE_SECONDS;
    }
    if (lease > g->cfg.max_control_lease_seconds)
        lease = g->cfg.max_control_lease_seconds;
    rc = gw_arb_claim(&g->arb, c->client_name[0] ? c->client_name : "client",
                      lease, g->now_ms, token, &expires, holder, &since);
    if (rc == 1) {
        gw_jw_init(&w, detail, sizeof detail);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "holder"); gw_jw_str(&w, holder);
        gw_jw_key(&w, "sinceMonotonicNs"); gw_jw_u64dec_str(&w, since * 1000000ull);
        gw_jw_end_obj(&w);
        (void)gw_jw_finish(&w);
        ctl_error(g, c, rid, "control_conflict", detail);
        return;
    }
    if (rc != 0) { ctl_error(g, c, rid, "bad_args", NULL); return; }
    snprintf(g->holder_session, sizeof g->holder_session, "%s", c->session_id);
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "controlToken"); gw_jw_str(&w, token);
    gw_jw_key(&w, "expiresInMs"); gw_jw_u64dec_str(&w, expires);
    gw_jw_key(&w, "owner");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "clientName"); gw_jw_str(&w, g->arb.owner);
    gw_jw_key(&w, "sinceMonotonicNs"); gw_jw_u64dec_str(&w, g->arb.since_ms * 1000000ull);
    gw_jw_end_obj(&w);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    gw_logf(g, "control: claimed by %s session=%s lease=%us",
            g->arb.owner, c->session_id, (unsigned)lease);
    ctl_ok(g, c, rid, res);
    notify_control_changed(g);
}

static void op_control_renew(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid)
{
    char token[65];
    uint64_t expires = 0;
    char res[128];
    gw_json_writer w;
    if (gw_json_get_str(doc, args, "controlToken", token, sizeof token, NULL) != 0 ||
        !token_is_hex32(token)) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return;
    }
    if (gw_arb_renew(&g->arb, token, g->now_ms, &expires) != 0) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return;
    }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "expiresInMs"); gw_jw_u64dec_str(&w, expires);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_control_release(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid)
{
    char token[65];
    char res[64];
    int rc;
    if (gw_json_get_str(doc, args, "controlToken", token, sizeof token, NULL) != 0 ||
        !token_is_hex32(token)) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return;
    }
    rc = gw_arb_release(&g->arb, token, g->now_ms);
    if (rc != 0) {
        ctl_error(g, c, rid, "bad_token", NULL);
        return;
    }
    g->holder_session[0] = 0;
    gw_logf(g, "control: released explicitly (state=%s)",
            gw_arb_state_name(&g->arb));
    snprintf(res, sizeof res, "{\"released\":true}");
    ctl_ok(g, c, rid, res);
    notify_control_changed(g);
}

/* ---------------------------------------------------------------- streams */

static int subscribe_type_allowed(gw *g, const char *type, const char **missing)
{
    *missing = NULL;
    if(strlen(type)==8&&!strncmp(type,"liveFft",7)&&type[7]>='0'&&type[7]<='5'){
        if(!g->cfg.mock_fixture&&g->caps.live_results)return 1;
        *missing="Real PL live FFT source not available";return 0;
    }
    if (strcmp(type, "resultWords") == 0) {
        if (g->cfg.mock_fixture || g->caps.live_results) return 1;
        *missing = "PL live results not accepted on hardware";
        return 0;
    }
    if (strcmp(type, "pcmRecord32") == 0) {
        *missing = "PL raw ring PS consumer/lease not accepted";
        return 0;
    }
    if (strcmp(type, "serviceSnapshot") == 0) {
        if (g->service_snapshot_enabled) return 1;
        *missing = "service snapshot address not configured/validated";
        return 0;
    }
    if (strcmp(type, "events") == 0) return 1;
    if (strcmp(type, "eventFile") == 0) {
        *missing = "event files are opened with stream.open{eventId} after event.download";
        return 0;
    }
    return -1;
}

static void op_subscribe(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid)
{
    const gw_json_node *streams;
    size_t count, i;
    gw_subscription *sub;
    char res[8192];
    gw_json_writer w;
    if (!args || (streams = gw_json_obj_get(doc, args, "streams")) == NULL ||
        streams->type != GW_JSON_ARRAY) {
        ctl_error_field(g, c, rid, "bad_args", "streams", "array required");
        return;
    }
    count = gw_json_arr_count(streams);
    if (count == 0 || count > GW_MAX_SUB_STREAMS) {
        ctl_error_field(g, c, rid, "bad_args", "streams", "1..8 entries");
        return;
    }
    sub = alloc_sub(g, c);
    if (!sub) { ctl_error(g, c, rid, "busy", "{\"reason\":\"subscription limit\"}"); return; }
    for (i = 0; i < count; i++) {
        const gw_json_node *entry = gw_json_arr_at(streams, i);
        char type[24];
        const char *missing = NULL;
        int allowed;
        gw_stream_def *def;
        if (!entry || entry->type != GW_JSON_OBJECT ||
            gw_json_get_str(doc, entry, "type", type, sizeof type, NULL) != 0) {
            ctl_error_field(g, c, rid, "bad_args", "streams", "entry needs string type");
            free_sub(sub);
            return;
        }
        allowed = subscribe_type_allowed(g, type, &missing);
        if (allowed == 0) {
            char detail[256];
            snprintf(detail, sizeof detail, "{\"missing\":\"%s\"}", missing);
            ctl_error(g, c, rid, "not_ready", detail);
            free_sub(sub);
            return;
        }
        if (allowed < 0) {
            ctl_error_field(g, c, rid, "bad_args", "streams", "unknown stream type");
            free_sub(sub);
            return;
        }
        if (strcmp(type, "events") == 0) {
            /* event notifications travel on the control channel; there is no
             * binary stream type for them (stream-schema enum). */
            sub->wants_events = 1;
            continue;
        }
        def = &sub->streams[sub->nstreams];
        def->stream_id = g->next_stream_id++;
        if (gw_stream_schema_build(g, def, type, NULL, 0) != 0) {
            ctl_error(g, c, rid, "internal_error", NULL);
            free_sub(sub);
            return;
        }
        sub->nstreams++;
    }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "subscriptionId"); gw_jw_str(&w, sub->id);
    gw_jw_key(&w, "streams");
    add_stream_list_json(&w, sub->streams, sub->nstreams);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static gw_download *find_download(gw *g, uint64_t event_id)
{
    unsigned i;
    for (i = 0; i < GW_MAX_DOWNLOADS; i++)
        if (g->downloads[i].used && g->downloads[i].event_id == event_id)
            return &g->downloads[i];
    return NULL;
}

static gw_download *alloc_download(gw *g)
{
    unsigned i;
    gw_download *oldest=NULL;
    for (i = 0; i < GW_MAX_DOWNLOADS; i++) {
        gw_download *d = &g->downloads[i];
        if (d->used) {
            int active=0;
            for(unsigned k=0;k<GW_MAX_BINARY_CONNS;k++)if(g->bin[k].used&&g->bin[k].event_download&&!g->bin[k].event_done&&g->bin[k].event_id==d->event_id)active=1;
            for(unsigned k=0;k<GW_MAX_BINARY_SESSIONS;k++)if(g->bin_sessions[k].used&&g->bin_sessions[k].is_event_download&&g->bin_sessions[k].bound_conn<0&&g->bin_sessions[k].expires_ms>g->now_ms&&g->bin_sessions[k].event_id==d->event_id)active=1;
            if(!active&&(!oldest||d->created_ms<oldest->created_ms))oldest=d;
            continue;
        }
        memset(d, 0, sizeof *d);
        d->used = 1;
        d->created_ms = g->now_ms;
        return d;
    }
    if(oldest){memset(oldest,0,sizeof *oldest);oldest->used=1;oldest->created_ms=g->now_ms;}
    return oldest;
}

static void op_stream_open(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid)
{
    char sub_id[40];
    const gw_json_node *evnode;
    char res[4096];
    gw_json_writer w;
    gw_bin_session *sess;
    if (gw_json_get_str(doc, args, "subscriptionId", sub_id, sizeof sub_id,
                        NULL) == 0) {
        gw_subscription *sub = find_sub(g, sub_id);
        uint32_t i;
        if (!sub || sub->owner_conn != ctl_index(g, c)) {
            ctl_error_field(g, c, rid, "bad_args", "subscriptionId",
                            "unknown subscription for this session");
            return;
        }
        sess = alloc_bin_session(g);
        if (!sess) { ctl_error(g, c, rid, "busy", NULL); return; }
        sess->owner_conn = ctl_index(g, c);
        sess->max_payload = g->cfg.max_binary_payload;
        if (c->client_max_payload && c->client_max_payload < sess->max_payload)
            sess->max_payload = c->client_max_payload;
        sess->nstreams = sub->nstreams;
        for (i = 0; i < sub->nstreams; i++) {
            if (gw_stream_def_copy(&sess->streams[i], &sub->streams[i]) != 0) {
                free_bin_session(sess);                ctl_error(g, c, rid, "internal_error", NULL);
                return;
            }
        }
        gw_jw_init(&w, res, sizeof res);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "binaryToken"); gw_jw_str(&w, sess->token);
        gw_jw_key(&w, "port"); gw_jw_u32(&w, g->bin_bound_port);
        gw_jw_key(&w, "maxPayloadBytes"); gw_jw_u32(&w, sess->max_payload);
        gw_jw_key(&w, "expiresInMs"); gw_jw_u64dec_str(&w, 60000);
        gw_jw_key(&w, "streams");
        add_stream_list_json(&w, sess->streams, sess->nstreams);
        gw_jw_end_obj(&w);
        if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
        ctl_ok(g, c, rid, res);
        return;
    }
    evnode = gw_json_obj_get(doc, args, "eventId");
    if (evnode) {
        uint64_t event_id = 0;
        const gw_event_rec *rec;
        gw_download *dl;
        gw_stream_def *def;
        if (gw_json_node_u64_dec(doc, evnode, &event_id) != 0) {
            ctl_error_field(g, c, rid, "bad_args", "eventId", "decimal string u64");
            return;
        }
        rec = gw_spool_find(&g->spool, event_id);
        if (!rec) { ctl_error(g, c, rid, "unknown_event", NULL); return; }
        g->spool.recs[rec-g->spool.recs].protected_until_ms=g->now_ms+60000;
        dl = find_download(g, event_id);
        if (!dl) {
            dl = alloc_download(g);
            if (!dl) { ctl_error(g, c, rid, "busy", NULL); return; }
            dl->event_id = event_id;
            dl->stream_id = g->next_stream_id++;
            dl->chunk_bytes = 65536;
            if (dl->chunk_bytes > g->cfg.max_binary_payload)
                dl->chunk_bytes = g->cfg.max_binary_payload;
            dl->total_bytes = rec->total_bytes;
            snprintf(dl->sha, sizeof dl->sha, "%.64s", rec->sha256);
        }
        sess = alloc_bin_session(g);
        if (!sess) { ctl_error(g, c, rid, "busy", NULL); return; }
        sess->max_payload = g->cfg.max_binary_payload;
        if (c->client_max_payload && c->client_max_payload < sess->max_payload)
            sess->max_payload = c->client_max_payload;
        sess->owner_conn = ctl_index(g, c);
        sess->is_event_download = 1;
        sess->event_id = event_id;
        sess->chunk_bytes = dl->chunk_bytes;
        sess->total_bytes = dl->total_bytes;
        sess->event_offset_start = dl->offset;
        snprintf(sess->sha, sizeof sess->sha, "%.64s", dl->sha);
        def = &sess->streams[0];
        def->stream_id = dl->stream_id;
        if (gw_stream_schema_build(g, def, "eventFile", rec, dl->chunk_bytes) != 0) {
            free_bin_session(sess);
            ctl_error(g, c, rid, "internal_error", NULL);
            return;
        }
        sess->nstreams = 1;
        gw_jw_init(&w, res, sizeof res);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "binaryToken"); gw_jw_str(&w, sess->token);
        gw_jw_key(&w, "port"); gw_jw_u32(&w, g->bin_bound_port);
        gw_jw_key(&w, "maxPayloadBytes"); gw_jw_u32(&w, sess->max_payload);
        gw_jw_key(&w, "expiresInMs"); gw_jw_u64dec_str(&w, 60000);
        gw_jw_key(&w, "streamId"); gw_jw_u32(&w, dl->stream_id);
        gw_jw_key(&w, "chunkBytes"); gw_jw_u32(&w, dl->chunk_bytes);
        gw_jw_key(&w, "totalBytes"); gw_jw_u64dec_str(&w, rec->total_bytes);
        gw_jw_key(&w, "sha256"); gw_jw_str(&w, rec->sha256);
        gw_jw_key(&w, "offset"); gw_jw_u64dec_str(&w, dl->offset);
        gw_jw_key(&w, "streams");
        add_stream_list_json(&w, sess->streams, sess->nstreams);
        gw_jw_end_obj(&w);
        if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
        ctl_ok(g, c, rid, res);
        return;
    }
    ctl_error_field(g, c, rid, "bad_args", "subscriptionId",
                    "subscriptionId or eventId required");
}

static void op_stream_close(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid)
{
    uint32_t stream_id = 0;
    unsigned i;
    if (gw_json_get_u32(doc, args, "streamId", &stream_id) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "streamId", "u32 required");
        return;
    }
    for (i = 0; i < GW_MAX_BINARY_SESSIONS; i++) {
        gw_bin_session *s = &g->bin_sessions[i];
        uint32_t k;
        int found = 0;
        if (!s->used) continue;
        for (k = 0; k < s->nstreams; k++)
            if (s->streams[k].stream_id == stream_id) found = 1;
        if (!found) continue;
        if (s->bound_conn >= 0 && s->bound_conn < (int)GW_MAX_BINARY_CONNS) {
            gw_bin_conn *bc = &g->bin[s->bound_conn];
            if (bc->used) bin_server_close_conn(g, bc, "stream_closed");
        }
        free_bin_session(s);
        ctl_ok(g, c, rid, "{\"closed\":true}");
        return;
    }
    ctl_error_field(g, c, rid, "bad_args", "streamId", "unknown stream");
}

static void op_unsubscribe(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid)
{
    char sub_id[40];
    gw_subscription *sub;
    if (gw_json_get_str(doc, args, "subscriptionId", sub_id, sizeof sub_id,
                        NULL) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "subscriptionId", "required");
        return;
    }
    sub = find_sub(g, sub_id);
    if (!sub || sub->owner_conn != ctl_index(g, c)) {
        ctl_error_field(g, c, rid, "bad_args", "subscriptionId",
                        "unknown subscription for this session");
        return;
    }
    free_sub(sub);
    ctl_ok(g, c, rid, "{\"unsubscribed\":true}");
}

/* ----------------------------------------------------------------- config */

static void op_config_read(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid)
{
    char res[4096];
    gw_json_writer w;
    unsigned i;
    (void)doc; (void)args;
    if (sync_shadow(g) != 0) { ctl_error(g, c, rid, "io_error", NULL); return; }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "shadow");
    gw_jw_begin_arr(&w);
    for (i = 0; i < 32; i++) gw_jw_u32(&w, g->config_shadow[i]);
    gw_jw_end_arr(&w);
    gw_jw_key(&w, "active");
    gw_jw_begin_arr(&w);
    for (i = 0; i < 32; i++)
        gw_jw_u32(&w, g->config_active_known ? g->config_active_words[i] : 0u);
    gw_jw_end_arr(&w);
    gw_jw_key(&w, "activeVersion"); gw_jw_u32(&w, g->active_config_version);
    gw_jw_key(&w, "activeWordsKnown"); gw_jw_bool(&w, g->config_active_known ? 1 : 0);
    gw_jw_key(&w, "pending"); gw_jw_bool(&w, g->pending_config ? 1 : 0);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_config_write(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid)
{
    const gw_json_node *words;
    size_t count, i;
    char token[65];
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    if (sync_shadow(g) != 0) { ctl_error(g, c, rid, "io_error", NULL); return; }
    words = gw_json_obj_get(doc, args, "words");
    if (!words || words->type != GW_JSON_ARRAY) {
        ctl_error_field(g, c, rid, "bad_args", "words", "array required");
        return;
    }
    count = gw_json_arr_count(words);
    if (count == 0 || count > 32) {
        ctl_error_field(g, c, rid, "bad_args", "words", "1..32 entries");
        return;
    }
    for (i = 0; i < count; i++) {
        const gw_json_node *e = gw_json_arr_at(words, i);
        uint32_t index = 0, value = 0;
        if (!e || e->type != GW_JSON_OBJECT ||
            gw_json_get_u32(doc, e, "index", &index) != 0 || index > 31 ||
            gw_json_get_u32(doc, e, "value", &value) != 0) {
            ctl_error_field(g, c, rid, "bad_args", "words",
                            "entries need index 0..31 and u32 value");
            return;
        }
        g->config_shadow[index] = value;
    }
    ctl_ok(g, c, rid, "{\"shadowDirty\":true}");
}

static void op_config_commit(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid)
{
    uint32_t version = 0;
    uint32_t words[32];
    const gw_json_node *warr;
    char token[65];
    const char *reason = "";
    uint64_t job_id = 0;
    char res[256];
    gw_json_writer w;
    size_t i;
    int rc;
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    if (gw_json_get_u32(doc, args, "version", &version) != 0 || version == 0) {
        ctl_error_field(g, c, rid, "bad_args", "version", "nonzero u32 required");
        return;
    }
    warr = gw_json_obj_get(doc, args, "words");
    if (warr) {
        size_t n;
        if (warr->type != GW_JSON_ARRAY || gw_json_arr_count(warr) != 32) {
            ctl_error_field(g, c, rid, "bad_args", "words", "32 numbers required");
            return;
        }
        n = gw_json_arr_count(warr);
        for (i = 0; i < n; i++) {
            uint32_t v = 0;
            if (gw_json_node_u32(gw_json_arr_at(warr, i), &v) != 0) {
                ctl_error_field(g, c, rid, "bad_args", "words",
                                "entries must be u32 numbers");
                return;
            }
            words[i] = v;
        }
    } else {
        if (sync_shadow(g) != 0) { ctl_error(g, c, rid, "io_error", NULL); return; }
        memcpy(words, g->config_shadow, sizeof words);
    }
    rc = gw_config_commit_start(g, version, words, &job_id, &reason);
    if (rc == -1) {
        char detail[256];
        snprintf(detail, sizeof detail, "{\"field\":\"version\",\"reason\":\"%s\"}",
                 reason);
        ctl_error(g, c, rid, "rejected", detail);
        return;
    }
    if (rc == -2) {
        char detail[256];
        snprintf(detail, sizeof detail,
                 "{\"feature\":\"configCommit\",\"reason\":\"%s\"}", reason);
        ctl_error(g, c, rid, "not_ready", detail);
        return;
    }
    if (rc == -3) { ctl_error(g, c, rid, "busy", "{\"reason\":\"config commit pending\"}"); return; }
    if (rc == -4) { ctl_error(g, c, rid, "busy", "{\"reason\":\"pending job limit\"}"); return; }
    if (rc == -5) { ctl_error(g, c, rid, "io_error", NULL); return; }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "jobId");
    {
        char id[24];
        gw_job_id_str(job_id, id);
        gw_jw_str(&w, id);
    }
    gw_jw_key(&w, "version"); gw_jw_u32(&w, version);
    gw_jw_key(&w, "note");
    gw_jw_str(&w, "accepted is not applied; wait for configApplied applied:true");
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_accepted(g, c, rid, res);
}

static void op_config_abort(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                            const gw_json_node *args, const char *rid)
{
    char token[65];
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    gw_config_abort(g);
    ctl_ok(g, c, rid, "{\"aborted\":true}");
}

/* ------------------------------------------------------------------- jobs */

static void op_task_start(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid)
{
    char kind[24];
    char key[65];
    char token[65];
    gw_job *job;
    char res[256];
    gw_json_writer w;
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    if (gw_json_get_str(doc, args, "kind", kind, sizeof kind, NULL) != 0 ||
        (strcmp(kind, "p1Carousel") != 0 && strcmp(kind, "p2OneShot") != 0)) {
        ctl_error_field(g, c, rid, "bad_args", "kind", "p1Carousel|p2OneShot");
        return;
    }
    key[0] = 0;
    (void)gw_json_get_str(doc, args, "clientTaskKey", key, sizeof key, NULL);
    if (key[0]) {
        gw_job *existing = gw_job_find_task_key(g, key);
        if (existing && g->now_ms - existing->created_ms <=
            (uint64_t)SMA_DUPLICATE_CACHE_SECONDS * 1000u) {
            char id[24];
            gw_job_id_str(existing->id, id);
            snprintf(res, sizeof res, "{\"jobId\":\"%s\",\"deduplicated\":true}", id);
            ctl_accepted(g, c, rid, res);
            return;
        }
    }
    if (!g->cfg.mock_fixture) {
        ctl_error(g, c, rid, "not_ready",
                  "{\"feature\":\"taskControl\","
                  "\"missing\":\"PL task start/cancel not accepted\"}");
        return;
    }
    job = gw_job_alloc(g, kind, c->client_name, 1);
    if (!job) { ctl_error(g, c, rid, "busy", "{\"reason\":\"pending job limit\"}"); return; }
    if (gw_arb_held(&g->arb)) {
        job->counted_pending = 1;
        gw_arb_pending_inc(&g->arb);
    }
    snprintf(job->client_task_key, sizeof job->client_task_key, "%s", key);
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "jobId");
    {
        char id[24];
        gw_job_id_str(job->id, id);
        gw_jw_str(&w, id);
    }
    gw_jw_key(&w, "note");
    gw_jw_str(&w, "fixture-mode simulated job; accepted is not completed");
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_accepted(g, c, rid, res);
}

static void op_task_cancel(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                           const gw_json_node *args, const char *rid)
{
    char token[65];
    uint64_t job_id = 0;
    gw_job *job;
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    if (get_job_id(doc, args, "jobId", &job_id) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "jobId", "job id required");
        return;
    }
    job = gw_job_find(g, job_id);
    if (!job) { ctl_error(g, c, rid, "job_not_found", NULL); return; }
    if (job->state != GW_JOB_COMPLETED && job->state != GW_JOB_FAILED &&
        job->state != GW_JOB_CANCELED) {
        if (job->state != GW_JOB_CANCEL_REQUESTED)
            gw_job_set_state(g, job, GW_JOB_CANCEL_REQUESTED,
                             "cancel requested; not yet stopped");
    }
    ctl_ok(g, c, rid, "{\"cancelRequested\":true}");
}

static void op_job_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                       const gw_json_node *args, const char *rid)
{
    uint64_t job_id = 0;
    gw_job *job;
    char res[1024];
    gw_json_writer w;
    if (get_job_id(doc, args, "jobId", &job_id) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "jobId", "job id required");
        return;
    }
    job = gw_job_find(g, job_id);
    if (!job) { ctl_error(g, c, rid, "job_not_found", NULL); return; }
    gw_jw_init(&w, res, sizeof res);
    gw_job_json(g, job, &w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static int job_sorter(const void *a, const void *b)
{
    const gw_job *ja = *(const gw_job *const *)a;
    const gw_job *jb = *(const gw_job *const *)b;
    if (ja->id < jb->id) return -1;
    if (ja->id > jb->id) return 1;
    return 0;
}

static void op_job_list(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                        const gw_json_node *args, const char *rid)
{
    char res[65536];
    gw_json_writer w;
    gw_job *sorted[GW_MAX_JOBS];
    unsigned n = 0, i;
    uint64_t cursor = 0;
    uint32_t limit = 50;
    unsigned emitted = 0;
    int more = 0;
    const gw_json_node *cnode;
    if (gw_json_get_u32(doc, args, "limit", &limit) == 0) {
        if (limit < 1 || limit > 100) {
            ctl_error_field(g, c, rid, "bad_args", "limit", "1..100");
            return;
        }
    }
    cnode = gw_json_obj_get(doc, args, "cursor");
    if (cnode && gw_json_node_u64_dec(doc, cnode, &cursor) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "cursor", "decimal string u64");
        return;
    }
    for (i = 0; i < GW_MAX_JOBS; i++)
        if (g->jobs[i].used) sorted[n++] = &g->jobs[i];
    qsort(sorted, n, sizeof sorted[0], job_sorter);
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "jobs");
    gw_jw_begin_arr(&w);
    for (i = 0; i < n; i++) {
        if (sorted[i]->id <= cursor) continue;
        if (emitted >= limit) { more = 1; break; }
        if (gw_jw_len(&w) > 56000) { more = 1; break; }
        gw_job_json(g, sorted[i], &w);
        cursor = sorted[i]->id;
        emitted++;
    }
    gw_jw_end_arr(&w);
    if (more) {
        gw_jw_key(&w, "nextCursor"); gw_jw_u64dec_str(&w, cursor);
    }
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

/* -------------------------------------------------------------- recording */

static void op_recording_start(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                               const gw_json_node *args, const char *rid)
{
    char token[65];
    const gw_json_node *streams;
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    streams = gw_json_obj_get(doc, args, "streams");
    if (!streams || streams->type != GW_JSON_ARRAY) {
        ctl_error_field(g, c, rid, "bad_args", "streams", "array required");
        return;
    }
    {
        size_t i, n = gw_json_arr_count(streams);
        if (n == 0 || n > 4) {
            ctl_error_field(g, c, rid, "bad_args", "streams", "1..4 entries");
            return;
        }
        for (i = 0; i < n; i++) {
            const gw_json_node *e = gw_json_arr_at(streams, i);
            size_t len = 0;
            const char *s = gw_json_str(doc, e, &len);
            if (!s || len != 10 || memcmp(s, "pcmRecord32", 10) != 0) {
                ctl_error_field(g, c, rid, "bad_args", "streams",
                                "only pcmRecord32 is defined for v1");
                return;
            }
        }
    }
    ctl_error(g, c, rid, "not_ready",
              "{\"feature\":\"rawRecording\","
              "\"missing\":\"PL raw ring PS consumer/lease not accepted\"}");
}

static void op_recording_stop(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                              const gw_json_node *args, const char *rid)
{
    char token[65];
    (void)args;
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    ctl_error(g, c, rid, "bad_state", "{\"reason\":\"no active recording\"}");
}

static void op_recording_status(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                                const gw_json_node *args, const char *rid)
{
    (void)doc; (void)args;
    ctl_ok(g, c, rid,
           "{\"recordingId\":null,\"state\":\"idle\",\"records\":\"0\","
           "\"bytes\":\"0\",\"gaps\":0,\"queueDrops\":\"0\"}");
}

/* ------------------------------------------------------------------ events */

static int parse_event_id(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid,
                          uint64_t *out)
{
    const gw_json_node *n = gw_json_obj_get(doc, args, "eventId");
    if (!n || gw_json_node_u64_dec(doc, n, out) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "eventId", "decimal string u64");
        return -1;
    }
    return 0;
}

static void op_event_list(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                          const gw_json_node *args, const char *rid)
{
    char res[65536];
    gw_json_writer w;
    uint64_t cursor = 0;
    uint32_t limit = 100;
    unsigned idx, emitted = 0;
    int more = 0;
    const gw_json_node *cnode;
    if (gw_json_get_u32(doc, args, "limit", &limit) == 0) {
        if (limit < 1 || limit > 200) {
            ctl_error_field(g, c, rid, "bad_args", "limit", "1..200");
            return;
        }
    }
    cnode = gw_json_obj_get(doc, args, "cursor");
    if (cnode && gw_json_node_u64_dec(doc, cnode, &cursor) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "cursor", "decimal string u64");
        return;
    }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "events");
    gw_jw_begin_arr(&w);
    for (idx = gw_spool_index_after(&g->spool, cursor);
         idx < gw_spool_count(&g->spool); idx++) {
        const gw_event_rec *rec = gw_spool_at(&g->spool, idx);
        if (emitted >= limit) { more = 1; break; }
        if (gw_jw_len(&w) > 56000) { more = 1; break; }
        gw_event_record_json(g, rec, &w);
        cursor = rec->event_id;
        emitted++;
    }
    gw_jw_end_arr(&w);
    if (more) {
        gw_jw_key(&w, "nextCursor"); gw_jw_u64dec_str(&w, cursor);
    }
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_event_get(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid)
{
    uint64_t event_id = 0;
    const gw_event_rec *rec;
    char res[4096];
    char data[1024];
    gw_json_writer w;
    if (parse_event_id(g, c, doc, args, rid, &event_id) != 0) return;
    rec = gw_spool_find(&g->spool, event_id);
    if (!rec) { ctl_error(g, c, rid, "unknown_event", NULL); return; }
    gw_jw_init(&w, data, sizeof data);
    gw_event_record_json(g, rec, &w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "event"); gw_jw_raw_value(&w, data, strlen(data));
    gw_jw_key(&w, "file");
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "totalBytes"); gw_jw_u64dec_str(&w, rec->total_bytes);
    gw_jw_key(&w, "sha256"); gw_jw_str(&w, rec->sha256);
    gw_jw_key(&w, "chunkBytes");
    gw_jw_u32(&w, g->cfg.max_binary_payload < 65536u
              ? g->cfg.max_binary_payload : 65536u);
    gw_jw_end_obj(&w);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_event_download(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                              const gw_json_node *args, const char *rid)
{
    uint64_t event_id = 0;
    const gw_event_rec *rec;
    gw_download *dl;
    uint64_t offset = 0;
    uint32_t max_bytes = 65536;
    const gw_json_node *onode;
    char res[1024];
    gw_json_writer w;
    if (parse_event_id(g, c, doc, args, rid, &event_id) != 0) return;
    rec = gw_spool_find(&g->spool, event_id);
    if (!rec) { ctl_error(g, c, rid, "unknown_event", NULL); return; }
    onode = gw_json_obj_get(doc, args, "offset");
    if (onode && gw_json_node_u64_dec(doc, onode, &offset) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "offset", "decimal string u64");
        return;
    }
    if (offset >= rec->total_bytes) {
        ctl_error_field(g, c, rid, "bad_args", "offset", "beyond event file");
        return;
    }
    if (gw_json_get_u32(doc, args, "maxBytes", &max_bytes) != 0)
        max_bytes = 65536;
    if (max_bytes < 32) max_bytes = 32;
    if (max_bytes > g->cfg.max_binary_payload) max_bytes = g->cfg.max_binary_payload;
    dl = find_download(g, event_id);
    if (!dl) {
        dl = alloc_download(g);
        if (!dl) { ctl_error(g, c, rid, "busy", NULL); return; }
        dl->event_id = event_id;
        dl->stream_id = g->next_stream_id++;
        dl->total_bytes = rec->total_bytes;
        snprintf(dl->sha, sizeof dl->sha, "%.64s", rec->sha256);
    }
    dl->chunk_bytes = max_bytes;
    dl->offset = offset;
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "streamId"); gw_jw_u32(&w, dl->stream_id);
    gw_jw_key(&w, "chunkBytes"); gw_jw_u32(&w, dl->chunk_bytes);
    gw_jw_key(&w, "totalBytes"); gw_jw_u64dec_str(&w, rec->total_bytes);
    gw_jw_key(&w, "sha256"); gw_jw_str(&w, rec->sha256);
    gw_jw_key(&w, "offset"); gw_jw_u64dec_str(&w, offset);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_event_ack(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                         const gw_json_node *args, const char *rid)
{
    uint64_t event_id = 0;
    char sha[80];
    int duplicate = 0;
    char err[192];
    char res[128];
    gw_json_writer w;
    int rc;
    if (parse_event_id(g, c, doc, args, rid, &event_id) != 0) return;
    if (gw_json_get_str(doc, args, "sha256", sha, sizeof sha, NULL) != 0 ||
        !sha_hex_valid(sha)) {
        ctl_error_field(g, c, rid, "bad_args", "sha256", "lowercase hex sha256");
        return;
    }
    rc = gw_spool_ack(&g->spool, event_id, sha, &duplicate, err, sizeof err);
    if (rc == -1) { ctl_error(g, c, rid, "unknown_event", NULL); return; }
    if (rc == -2) { ctl_error(g, c, rid, "event_hash_mismatch", NULL); return; }
    if (rc != 0) { ctl_error(g, c, rid, "io_error", NULL); return; }
    {gw_download*d=find_download(g,event_id);if(d)memset(d,0,sizeof *d);}
    gw_jw_init(&w, res, sizeof res);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "acked"); gw_jw_bool(&w, 1);
    gw_jw_key(&w, "duplicate"); gw_jw_bool(&w, duplicate ? 1 : 0);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { ctl_error(g, c, rid, "internal_error", NULL); return; }
    ctl_ok(g, c, rid, res);
}

static void op_event_discard(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                             const gw_json_node *args, const char *rid)
{
    char token[65];
    uint64_t event_id = 0;
    char reason[128];
    char err[192];
    if (get_args_token(g, c, doc, args, rid, token) != 0) return;
    if (parse_event_id(g, c, doc, args, rid, &event_id) != 0) return;
    if (gw_json_get_str(doc, args, "reason", reason, sizeof reason, NULL) != 0) {
        ctl_error_field(g, c, rid, "bad_args", "reason", "required");
        return;
    }
    for(unsigned k=0;k<GW_MAX_BINARY_CONNS;k++)if(g->bin[k].used&&g->bin[k].event_download&&!g->bin[k].event_done&&g->bin[k].event_id==event_id){ctl_error(g,c,rid,"busy","{\"reason\":\"event-download-active\"}");return;}
    if (gw_spool_discard(&g->spool, event_id, err, sizeof err) != 0) {
        ctl_error(g, c, rid, "unknown_event", NULL);
        return;
    }
    gw_logf(g, "event: discarded id=%s reason=%s",
            gw_u64_dec(event_id, (char[21]){0}), reason);
    ctl_ok(g, c, rid, "{\"discarded\":true}");
}

/* ---------------------------------------------------------------- profile */

static void op_profile(gw *g, gw_ctl_conn *c, const gw_json_doc *doc,
                       const gw_json_node *args, const char *rid)
{
    (void)doc; (void)args;
    ctl_error(g, c, rid, "not_ready",
              "{\"feature\":\"profileUpload\","
              "\"missing\":\"profile_upload.c two-pass read TOCTOU between "
              "validation passes not closed; arbitrary file writes intentionally "
              "not exposed\"}");
}
