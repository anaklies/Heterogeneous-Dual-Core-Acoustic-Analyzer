#include "binary_server.h"
#include "gateway.h"
#include "fc_capture.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --------------------------------------------------------- stream schemas */

static const char *const k_result_names[SMA_RESULT_WORD_COUNT] = {
    "protocol", "algorithmId", "frame", "configVersion",
    "session", "slot", "fftBase", "cycles",
    "sampleIndexLow", "sampleIndexHigh", "faults", "microphoneStatus",
    "missedWindows", "droppedSamples", "backgroundCompletions", "overwrittenResults",
    "failedFrames", "temperatureCenti", "humidityRaw", "pressurePa",
    "soundSpeedFloat32", "sensorValid", "rollPitch", "yaw",
    "qwQx", "qyQz", "envSequence", "poseSequence",
    "sensorErrors", "lostEvents", "handoffDrops", "sampleRateFloat32"
};
static const char *const k_result_units[SMA_RESULT_WORD_COUNT] = {
    "", "id", "frame", "configVersion", "", "slot", "byte", "cycles",
    "", "", "bits", "", "windows", "samples", "frames", "frames",
    "frames", "0.01 degC", "raw", "Pa",
    "m/s", "bits", "packed", "packed", "packed", "packed", "sequence", "sequence",
    "packed", "events", "drops", "Hz"
};
/* Sensor-related words are NOT hardware-verified; mark them unverified. */
static int result_word_unverified(unsigned idx)
{
    if (idx >= SM_R_TEMP_CENTI && idx <= SM_R_POSE_SEQUENCE) return 1;
    return 0;
}

static const char *const k_service_header_names[SMA_SERVICE_HEADER_WORDS] = {
    "magic", "commitSequence", "session", "config",
    "generation", "programVersion", "sourceFrame", "sampleIndexLow",
    "sampleIndexHigh", "slot", "length", "descriptor",
    "error", "pc", "done", "reserved"
};

static void set_source_common(gw *g, gw_json_writer *w, const char *type)
{
    gw_jw_key(w, "streamType"); gw_jw_str(w, type);
    gw_jw_key(w, "sourceKind"); gw_jw_str(w, gw_source_kind(g));
    gw_jw_key(w, "simulated"); gw_jw_bool(w, g->cfg.mock_fixture ? 1 : 0);
    gw_jw_key(w, "deviceId"); gw_jw_str(w, g->device_id);
    gw_jw_key(w, "connectionEpoch"); gw_jw_u64dec_str(w, g->epoch);
    gw_jw_key(w, "encoding"); gw_jw_str(w, "sma1");
    gw_jw_key(w, "createdMonotonicNs"); gw_jw_u64dec_str(w, gw_clock_ns());
}

int gw_stream_schema_build(gw *g, gw_stream_def *def, const char *type,
                           const gw_event_rec *ev, uint32_t chunk_bytes)
{
    char *buf = (char *)malloc(GW_LINE_BYTES);
    gw_json_writer w;
    unsigned i;
    if (!buf) return -1;
    if (!def || !type) { free(buf); return -1; }
    snprintf(def->type, sizeof def->type, "%s", type);
    gw_jw_init(&w, buf, GW_LINE_BYTES);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "streamId"); gw_jw_u32(&w, def->stream_id);
    set_source_common(g, &w, strcmp(type, "resultWords") == 0 ? "resultWords32" : type);
    if (strcmp(type, "resultWords") == 0) {
        gw_jw_key(&w,"wordCount");gw_jw_u32(&w,32);
        gw_jw_key(&w,"wordEncoding");gw_jw_str(&w,"uint32-le");
        gw_jw_key(&w,"resultSchema");gw_jw_str(&w,"protocol3-result-v1");
        gw_jw_key(&w, "units"); gw_jw_str(&w, "protocol-3 result snapshot words");
        gw_jw_key(&w, "wordMap");
        gw_jw_begin_arr(&w);
        for (i = 0; i < SMA_RESULT_WORD_COUNT; i++) {
            gw_jw_begin_obj(&w);
            gw_jw_key(&w, "index"); gw_jw_u32(&w, i);
            gw_jw_key(&w, "name"); gw_jw_str(&w, k_result_names[i]);
            gw_jw_key(&w, "unit"); gw_jw_str(&w, k_result_units[i]);
            gw_jw_key(&w, "encoding"); gw_jw_str(&w, "u32-le");
            gw_jw_key(&w, "validity");
            gw_jw_str(&w, result_word_unverified(i) ? "unverified" : "protocol3");
            gw_jw_end_obj(&w);
        }
        gw_jw_end_arr(&w);
    } else if (strcmp(type, "serviceSnapshot") == 0) {
        gw_jw_key(&w,"headerWords");gw_jw_u32(&w,16);
        gw_jw_key(&w,"services");gw_jw_begin_arr(&w);
        for(i=0;i<g->service_route_count;i++){
            uint32_t base=g->service_routes[i].descriptor;
            gw_jw_begin_obj(&w);
            gw_jw_key(&w,"serviceId");gw_jw_str(&w,g->service_routes[i].name);
            gw_jw_key(&w,"units");gw_jw_str(&w,g->service_routes[i].units);
            gw_jw_key(&w,"outputWords");gw_jw_u32(&w,g->service_routes[i].words);
            gw_jw_key(&w,"generation");gw_jw_u32(&w,g->service_routes[i].generation);
            gw_jw_key(&w,"programVersion");gw_jw_u32(&w,1);
            gw_jw_key(&w,"descriptorFamilies");gw_jw_begin_arr(&w);gw_jw_u32(&w,base);
            if(base>=524288u&&base<525312u)gw_jw_u32(&w,528384u+base-524288u);
            gw_jw_end_arr(&w);gw_jw_end_obj(&w);
        }
        gw_jw_end_arr(&w);
        gw_jw_key(&w, "payloadWordCount");
        gw_jw_str(&w, "header16 + header[10] service words");
        gw_jw_key(&w, "headerMap");
        gw_jw_begin_arr(&w);
        for (i = 0; i < SMA_SERVICE_HEADER_WORDS; i++) {
            gw_jw_begin_obj(&w);
            gw_jw_key(&w, "index"); gw_jw_u32(&w, i);
            gw_jw_key(&w, "name"); gw_jw_str(&w, k_service_header_names[i]);
            gw_jw_end_obj(&w);
        }
        gw_jw_end_arr(&w);
        gw_jw_key(&w, "readRule");
        gw_jw_str(&w, "copy 16-word header, data, header again; full compare; "
                      "require magic/done/error/session/config match");
    } else if (strcmp(type, "eventFile") == 0) {
        char num[21];
        if (!ev) { free(buf); return -1; }
        gw_jw_key(&w, "eventId"); gw_jw_str(&w, gw_u64_dec(ev->event_id, num));
        gw_jw_key(&w, "totalBytes"); gw_jw_u64dec_str(&w, ev->total_bytes);
        gw_jw_key(&w, "sha256"); gw_jw_str(&w, ev->sha256);
        gw_jw_key(&w, "chunkBytes"); gw_jw_u32(&w, chunk_bytes);
        /* stream-schema.schema.json types "container" as a string */
        gw_jw_key(&w, "container"); gw_jw_str(&w, "SMC1");
        gw_jw_key(&w, "containerVersion"); gw_jw_u32(&w, 1);
        gw_jw_key(&w, "containerHeaderBytes"); gw_jw_u32(&w, 64);
        gw_jw_key(&w, "containerRecordBytes"); gw_jw_u32(&w, 32);
        gw_jw_key(&w, "recordFormat");
        gw_jw_str(&w, "6x int24-sign-extended-le-int32 then uint64-le-low-word-first sampleIndex");
    } else if (strcmp(type, "events") == 0) {
        gw_jw_key(&w, "delivery"); gw_jw_str(&w, "control-channel");
        gw_jw_key(&w, "eventTypes");
        gw_jw_begin_arr(&w);
        gw_jw_str(&w, "eventAdded");
        gw_jw_end_arr(&w);
    } else if(strlen(type)==8&&!strncmp(type,"liveFft",7)){
        gw_jw_key(&w,"extension");gw_jw_str(&w,"echo-live-fft-1");
        gw_jw_key(&w,"channel");gw_jw_u32(&w,(unsigned)(type[7]-'0'));
        gw_jw_key(&w,"messageType");gw_jw_u32(&w,0x20);
        gw_jw_key(&w,"payloadWords");gw_jw_u32(&w,FC_LIVE_WORDS);
        gw_jw_key(&w,"layout");gw_jw_str(&w,"16 LE32 metadata,1025 [amplitude,PSD,binPower] triples,6x8 PL level scalars,6x2048 signed PCM24 LE32 samples");
        gw_jw_key(&w,"provenance");gw_jw_str(&w,"One complete PL FFT frame; header checked before/after copying. Explicit gaps; no hold, interpolation, CPU FFT or synthetic samples.");
    } else if (strcmp(type, "pcmRecord32") == 0) {
        gw_jw_key(&w, "units"); gw_jw_str(&w, "digital full scale PCM24 codes");
        gw_jw_key(&w, "pcm");
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "channels"); gw_jw_u32(&w, 6);
        gw_jw_key(&w, "channelOrder");
        gw_jw_begin_arr(&w);
        for (i = 0; i < 6; i++) {
            char nm[8];
            snprintf(nm, sizeof nm, "mic%u", i + 1u);
            gw_jw_str(&w, nm);
        }
        gw_jw_end_arr(&w);
        gw_jw_key(&w, "sampleFormat");
        gw_jw_str(&w, "int24-le-signextended-in-int32");
        gw_jw_key(&w, "recordBytes"); gw_jw_u32(&w, 32);
        gw_jw_key(&w, "sampleIndexOffset"); gw_jw_u32(&w, 24);
        gw_jw_key(&w, "sampleIndexEncoding");
        gw_jw_str(&w, "uint64-le-low-word-first");
        gw_jw_key(&w, "sampleRateHz");
        gw_jw_raw_value(&w, "48009.7734375", 13); /* float32 value of word31 */
        gw_jw_key(&w, "sampleRateExactHz");
        gw_jw_raw_value(&w, "48009.775390625", 15); /* design-rate double */
        gw_jw_key(&w, "sampleRateFloat32Bits");
        gw_jw_raw_value(&w, "1195088326", 10); /* 0x473b89c6 */
        gw_jw_key(&w, "sampleRateSource");
        gw_jw_str(&w, "pl-result-word31-float32");
        gw_jw_key(&w, "frameGroupRecords"); gw_jw_u32(&w, 150);
        gw_jw_key(&w, "gapPolicy");
        gw_jw_str(&w, "explicit STREAM_GAP; never silently splice");
        gw_jw_end_obj(&w);
        gw_jw_key(&w, "validity");
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "deviceTime"); gw_jw_str(&w, "optional");
        gw_jw_key(&w, "sampleIndex"); gw_jw_str(&w, "required");
        gw_jw_key(&w, "gapBefore"); gw_jw_str(&w, "flag");
        gw_jw_end_obj(&w);
    } else {
        free(buf);
        return -1;
    }
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w)) { free(buf); return -1; }
    def->schema_len = (uint32_t)w.len;
    def->schema_json = buf;
    {
        uint8_t digest[32];
        gw_sha256(buf, w.len, digest);
        gw_sha256_hex(digest, def->schema_sha);
    }
    return 0;
}

void gw_stream_def_free(gw_stream_def *def)
{
    if (!def) return;
    free(def->schema_json);
    def->schema_json = NULL;
    def->schema_len = 0;
    def->schema_sha[0] = 0;
}

int gw_stream_def_copy(gw_stream_def *dst, const gw_stream_def *src)
{
    memset(dst, 0, sizeof *dst);
    dst->stream_id = src->stream_id;
    snprintf(dst->type, sizeof dst->type, "%s", src->type);
    dst->schema_len = src->schema_len;
    snprintf(dst->schema_sha, sizeof dst->schema_sha, "%s", src->schema_sha);
    if (src->schema_json && src->schema_len) {
        dst->schema_json = (char *)malloc(src->schema_len);
        if (!dst->schema_json) return -1;
        memcpy(dst->schema_json, src->schema_json, src->schema_len);
    }
    return 0;
}

/* ---------------------------------------------------------------- frames */

static int bin_frame(gw *g, gw_bin_conn *c, uint16_t type, uint16_t flags,
                     uint32_t stream_id, uint32_t seq, uint64_t first_sample,
                     uint32_t frame_id, uint32_t config_version,
                     const void *payload, uint32_t payload_bytes)
{
    sma_header h;
    memset(&h, 0, sizeof h);
    h.protocol_version = (uint16_t)SMA_BINARY_PROTOCOL_VERSION;
    h.header_bytes = (uint16_t)SMA_BINARY_HEADER_BYTES;
    h.message_type = type;
    h.flags = flags;
    h.payload_bytes = payload_bytes;
    h.stream_id = stream_id;
    h.sequence = seq;
    h.connection_epoch = g->epoch;
    h.first_sample_index = first_sample;
    h.device_monotonic_ns = 0; /* no verified device-clock mapping */
    h.frame_id = frame_id;
    h.config_version = config_version;
    if (payload_bytes) {
        h.payload_crc32 = sma_crc32((const uint8_t *)payload, payload_bytes);
        h.flags |= SMA_FLAG_CRC32_VALID;
    }
    if (!gw_binary_append_frame(&c->out, &h, (const uint8_t *)payload)) return 0;
    c->last_tx_ms = g->now_ms;
    c->frames_out++;
    c->bytes_out += (uint64_t)SMA_BINARY_HEADER_BYTES + payload_bytes;
    g->stats.binary_frames_out++;
    return 1;
}

static void bin_free_conn(gw *g, gw_bin_conn *c)
{
    if (!c || !c->used) return;
    gw_net_close(c->fd);
    gw_fifo_free(&c->out);
    if (c->sess_idx >= 0 && c->sess_idx < (int)GW_MAX_BINARY_SESSIONS) {
        gw_bin_session *s = &g->bin_sessions[c->sess_idx];
        if (s->used && s->bound_conn == (int)(c - g->bin)) {
            unsigned i;
            for (i = 0; i < s->nstreams; ++i) gw_stream_def_free(&s->streams[i]);
            memset(s, 0, sizeof *s);
        }
    }
    memset(c, 0, sizeof *c);
}

static void bin_fatal(gw *g, gw_bin_conn *c, const char *code, const char *detail)
{
    char line[256];
    gw_json_writer w;
    if (!c->used) return;
    gw_jw_init(&w, line, sizeof line);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "code"); gw_jw_str(&w, code);
    gw_jw_key(&w, "messageKey");
    {
        char key[160];
        snprintf(key, sizeof key, "errors.%s", code);
        gw_jw_str(&w, key);
    }
    gw_jw_key(&w, "detail"); gw_jw_str(&w, detail ? detail : "");
    gw_jw_end_obj(&w);
    if (gw_jw_finish(&w)) {
        if (!bin_frame(g, c, SMA_MSG_ERROR, 0, 0, c->conn_seq++, 0, 0, 0,
                       line, (uint32_t)w.len)) {
            /* no room: still close, client sees connection loss */
        }
    }
    c->closing = 1;
    if (gw_fifo_avail(&c->out) == 0) bin_free_conn(g, c);
}

void bin_server_close_conn(gw *g, gw_bin_conn *c, const char *reason)
{
    if (!c || !c->used) return;
    if (!c->closing) {
        c->closing = 1;
        if (reason && c->hello_done) {
            char payload[256];
            gw_json_writer w;
            gw_jw_init(&w, payload, sizeof payload);
            gw_jw_begin_obj(&w);
            gw_jw_key(&w, "reason"); gw_jw_str(&w, reason);
            gw_jw_end_obj(&w);
            if (gw_jw_finish(&w))
                (void)bin_frame(g, c, SMA_MSG_BYE, 0, 0, c->conn_seq++, 0, 0, 0,
                                payload, (uint32_t)w.len);
        }
    }
    if (gw_fifo_avail(&c->out) == 0) bin_free_conn(g, c);
}

static int conn_stream_index(gw_bin_conn *c, const char *type)
{
    uint32_t i;
    for (i = 0; i < c->nstreams; i++) {
        if (strcmp(c->streams[i].is_result ? "resultWords32" :
                   c->streams[i].is_service ? "serviceSnapshot" :
                   c->streams[i].is_event_file ? "eventFile" : "", type) == 0)
            return (int)i;
    }
    return -1;
}

static void bin_send_schemas(gw *g, gw_bin_conn *c)
{
    int idx;
    uint32_t i;
    if (c->sess_idx < 0 || c->sess_idx >= (int)GW_MAX_BINARY_SESSIONS) return;
    {
        gw_bin_session *s = &g->bin_sessions[c->sess_idx];
        for (i = 0; i < c->nstreams && i < s->nstreams; i++) {
            if (c->streams[i].schema_sent) continue;
            idx = (int)i;
            if (!bin_frame(g, c, SMA_MSG_STREAM_SCHEMA, 0,
                           s->streams[idx].stream_id, c->streams[idx].seq++,
                           0, 0, 0, s->streams[idx].schema_json,
                           s->streams[idx].schema_len))
                return;
            c->streams[idx].schema_sent = 1;
            g->stats.binary_schema_sent++;
        }
    }
}

/* ------------------------------------------------------------- HELLO */

static int find_session_by_token(gw *g, const char *token)
{
    unsigned i;
    for (i = 0; i < GW_MAX_BINARY_SESSIONS; i++) {
        gw_bin_session *s = &g->bin_sessions[i];
        if (!s->used) continue;
        if (strcmp(s->token, token) != 0) continue;
        if (s->expires_ms != 0 && g->now_ms > s->expires_ms) return -1;
        if (s->bound_conn >= 0) return -2;
        return (int)i;
    }
    return -1;
}

static void bin_process_hello(gw *g, gw_bin_conn *c)
{
    gw_json_doc doc;
    char jerrbuf[96];
    const gw_json_node *root;
    char protocol[32];
    char token[65];
    uint64_t epoch = 0;
    uint32_t client_max = 0;
    int has_max = 0;
    int sess;
    gw_bin_session *s;
    char payload[512];
    gw_json_writer w;
    uint32_t i;
    if (c->hello_done) { bin_fatal(g, c, "bad_hello", "HELLO already completed"); return; }
    if (c->collect_len == 0 || c->collect_len > 4000) {
        bin_fatal(g, c, "bad_hello", "HELLO payload missing or too large");
        return;
    }
    if (gw_json_parse(&doc, (const char *)c->collect_buf, c->collect_len, 8, 512,
                      jerrbuf, sizeof jerrbuf) != 0) {
        bin_fatal(g, c, "bad_hello", "HELLO payload is not strict JSON");
        return;
    }
    root = gw_json_root(&doc);
    if (!root || root->type != GW_JSON_OBJECT) {
        gw_json_doc_free(&doc);
        bin_fatal(g, c, "bad_hello", "HELLO must be a JSON object");
        return;
    }
    if (gw_json_get_str(&doc, root, "protocol", protocol, sizeof protocol, NULL) != 0 ||
        strcmp(protocol, GW_PROTOCOL_NAME) != 0) {
        gw_json_doc_free(&doc);
        bin_fatal(g, c, "protocol_mismatch", "HELLO protocol is not sixmic-analysis");
        return;
    }
    if (gw_json_get_u64_dec(&doc, root, "connectionEpoch", &epoch) != 0 ||
        epoch != g->epoch) {
        gw_json_doc_free(&doc);
        bin_fatal(g, c, "epoch_mismatch", "HELLO connectionEpoch is stale");
        return;
    }
    if (gw_json_get_str(&doc, root, "token", token, sizeof token, NULL) != 0) {
        gw_json_doc_free(&doc);
        bin_fatal(g, c, "bad_token", "HELLO token missing");
        return;
    }
    if (gw_json_get_u32(&doc, root, "maxPayloadBytes", &client_max) == 0)
        has_max = 1;
    gw_json_doc_free(&doc);
    sess = find_session_by_token(g, token);
    if (sess < 0) {
        bin_fatal(g, c, "bad_token", sess == -2 ? "token already in use" :
                  "binary token unknown or expired");
        return;
    }
    s = &g->bin_sessions[sess];
    if (!has_max || client_max == 0) client_max = s->max_payload;
    c->max_payload = client_max;
    if (c->max_payload > s->max_payload) c->max_payload = s->max_payload;
    if (c->max_payload > g->cfg.max_binary_payload) c->max_payload = g->cfg.max_binary_payload;
    if (c->max_payload < SMA_MIN_MAX_BINARY_PAYLOAD) c->max_payload = SMA_MIN_MAX_BINARY_PAYLOAD;
    if (s->is_event_download && s->chunk_bytes > c->max_payload) {
        bin_fatal(g, c, "payload_cap_too_small",
                  "negotiated max payload is smaller than the event chunk size");
        return;
    }
    c->sess_idx = sess;
    s->bound_conn = (int)(c - g->bin);
    c->hello_done = 1;
    c->nstreams = s->nstreams;
    memset(c->streams, 0, sizeof c->streams);
    for (i = 0; i < s->nstreams && i < GW_MAX_SUB_STREAMS; i++) {
        c->streams[i].stream_id = s->streams[i].stream_id;
        c->streams[i].seq = 0;
        c->streams[i].schema_sent = 0;
        c->streams[i].is_result = strcmp(s->streams[i].type, "resultWords") == 0;
        c->streams[i].is_service = strcmp(s->streams[i].type, "serviceSnapshot") == 0;
        c->streams[i].is_event_file = strcmp(s->streams[i].type, "eventFile") == 0;
        c->streams[i].is_live = strlen(s->streams[i].type)==8&&!strncmp(s->streams[i].type,"liveFft",7);
        if(c->streams[i].is_live)c->streams[i].live_channel=(unsigned)(s->streams[i].type[7]-'0');
    }
    if (s->is_event_download) {
        c->event_download = 1;
        c->event_id = s->event_id;
        c->event_total = s->total_bytes;
        c->event_offset = s->event_offset_start;
        c->chunk_bytes = s->chunk_bytes;
        snprintf(c->event_sha, sizeof c->event_sha, "%.64s", s->sha);
        c->event_done = 0;
        c->event_first = 1;
    }
    gw_jw_init(&w, payload, sizeof payload);
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "accepted"); gw_jw_bool(&w, 1);
    gw_jw_key(&w, "maxPayloadBytes"); gw_jw_u32(&w, c->max_payload);
    gw_jw_key(&w, "connectionEpoch"); gw_jw_u64dec_str(&w, g->epoch);
    gw_jw_key(&w, "streams");
    gw_jw_begin_arr(&w);
    for (i = 0; i < s->nstreams && i < GW_MAX_SUB_STREAMS; i++) {
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "streamId"); gw_jw_u32(&w, s->streams[i].stream_id);
        gw_jw_key(&w, "streamType"); gw_jw_str(&w, s->streams[i].type);
        gw_jw_end_obj(&w);
    }
    gw_jw_end_arr(&w);
    gw_jw_end_obj(&w);
    if (!gw_jw_finish(&w) ||
        !bin_frame(g, c, SMA_MSG_HELLO_ACK, 0, 0, c->conn_seq++, 0, 0, 0,
                   payload, (uint32_t)w.len)) {
        bin_fatal(g, c, "internal", "HELLO_ACK could not be queued");
        return;
    }
    gw_logf(g, "binary: HELLO accepted maxPayload=%u sessions=%u",
            (unsigned)c->max_payload, (unsigned)c->nstreams);
    bin_send_schemas(g, c);
}

/* ---------------------------------------------------------- frame input */

/* The frozen wire header's sma_header_decode() rejects BYE payloads (-7) even
 * though PROTOCOL.md 5.3 gives BYE a JSON {reason} payload and the golden
 * sample carries one. Receive-side decoding therefore applies the immutable
 * field checks itself and only exempts BYE from the zero-payload rule until
 * interfaces/pc_backend_v1/c/sixmic_analysis_wire.h is corrected. */
static int bin_decode_header(const uint8_t in[SMA_BINARY_HEADER_BYTES],
                             sma_header *h, uint32_t max_payload)
{
    int rc = sma_header_decode(in, h, max_payload);
    if (rc == 0) return 0;
    if (rc != -7 || !h) return rc;
    if (h->message_type != SMA_MSG_BYE) return rc;
    if (h->payload_bytes > max_payload) return -6;
    return 0;
}

static void bin_finish_frame(gw *g, gw_bin_conn *c)
{
    sma_header *h = &c->cur;
    uint32_t crc;
    if (h->payload_bytes) {
        if (!(h->flags & SMA_FLAG_CRC32_VALID)) {
            g->stats.binary_bad_frames++;
            bin_fatal(g, c, "bad_crc", "payload CRC32 flag missing");
            return;
        }
        crc = c->payload_crc_acc ^ 0xFFFFFFFFu;
        if (crc != h->payload_crc32) {
            g->stats.binary_bad_frames++;
            bin_fatal(g, c, "bad_crc", "payload CRC32 mismatch");
            return;
        }
    }
    switch (h->message_type) {
    case SMA_MSG_HELLO:
        bin_process_hello(g, c);
        break;
    case SMA_MSG_HEARTBEAT:
        /* Keepalive is not an echo request. Echoing an echoing client creates
         * an unbounded heartbeat ping-pong. RX already refreshed last_rx_ms. */
        break;
    case SMA_MSG_BYE:
        bin_server_close_conn(g, c, "client_bye");
        break;
    default:
        g->stats.binary_unknown_frames++;
        c->unknown_frames++;
        break;
    }
}

void bin_server_on_readable(gw *g, gw_bin_conn *c)
{
    if (!c || !c->used) return;
    for (;;) {
        if (!c->have_header) {
            int n = gw_net_recv(c->fd, c->hdr + c->hdrlen,
                                SMA_BINARY_HEADER_BYTES - c->hdrlen);
            if (n == GW_RECV_AGAIN) return;
            if (n <= 0) { bin_free_conn(g, c); return; }
            c->last_rx_ms = g->now_ms;
            c->hdrlen += (size_t)n;
            if (c->hdrlen < SMA_BINARY_HEADER_BYTES) continue;
            {
                uint32_t cap = c->max_payload ? c->max_payload : g->cfg.max_binary_payload;
                int rc = bin_decode_header(c->hdr, &c->cur, cap);
                if (rc != 0) {
                    g->stats.binary_bad_frames++;
                    bin_fatal(g, c, "bad_frame", "SMA1 header failed validation");
                    return;
                }
            }
            c->have_header = 1;
            c->payload_left = c->cur.payload_bytes;
            c->collect_len = 0;
            c->payload_crc_acc = 0xFFFFFFFFu;
            c->collect = (c->cur.message_type == SMA_MSG_HELLO ||
                          c->cur.message_type == SMA_MSG_HEARTBEAT ||
                          c->cur.message_type == SMA_MSG_BYE);
            if (c->collect && c->payload_left > sizeof c->collect_buf) {
                g->stats.binary_bad_frames++;
                bin_fatal(g, c, "bad_frame", "HELLO/heartbeat payload too large");
                return;
            }
            if (c->payload_left == 0) {
                c->hdrlen = 0;
                bin_finish_frame(g, c);
                if (!c->used) return;
                c->have_header = 0;
                continue;
            }
            if (!c->collect && c->payload_left != 0) {
                /* bounded skip of unknown payloads: still CRC checked */
                c->payload_crc_acc = 0xFFFFFFFFu;
            }
            continue;
        }
        {
            uint32_t want = c->payload_left;
            size_t cap = sizeof c->scratch;
            int n;
            if (c->collect) {
                size_t room = sizeof c->collect_buf - c->collect_len;
                if ((size_t)want > room) want = (uint32_t)room;
            }
            if ((size_t)want > cap) want = (uint32_t)cap;
            n = gw_net_recv(c->fd, c->scratch, want);
            if (n == GW_RECV_AGAIN) return;
            if (n <= 0) { bin_free_conn(g, c); return; }
            c->last_rx_ms = g->now_ms;
            c->payload_crc_acc = sma_crc32_update(c->payload_crc_acc,
                                                  c->scratch, (size_t)n);
            if (c->collect) {
                memcpy(c->collect_buf + c->collect_len, c->scratch, (size_t)n);
                c->collect_len += (uint32_t)n;
            }
            c->payload_left -= (uint32_t)n;
            if (c->payload_left == 0) {
                c->hdrlen = 0;
                c->have_header = 0;
                bin_finish_frame(g, c);
                if (!c->used) return;
            }
        }
    }
}

/* ---------------------------------------------------------- server ticks */

void bin_server_flush(gw *g, gw_bin_conn *c)
{
    (void)g;
    if (!c || !c->used) return;
    while (gw_fifo_avail(&c->out) > 0) {
        size_t contig = 0;
        const uint8_t *p = gw_fifo_peek(&c->out, &contig);
        int n;
        if (!p || contig == 0) break;
        n = gw_net_send(c->fd, p, contig);
        if (n == GW_SEND_AGAIN) return;
        if (n <= 0) { bin_server_close_conn(g, c, NULL); return; }
        gw_fifo_consume(&c->out, (size_t)n);
    }
}

static void bin_drop_pending_result(gw *g, gw_bin_conn *c)
{
    if (!c->result_pending) return;
    c->result_pending = 0;
    c->result_gap = 1;
    c->result_dropped++;
    g->stats.result_frames_dropped++;
}

static void bin_flush_result(gw *g, gw_bin_conn *c)
{
    int idx;
    uint16_t flags = 0;
    if (!c->result_pending || !c->hello_done) return;
    idx = conn_stream_index(c, "resultWords32");
    if (idx < 0) { c->result_pending = 0; return; }
    if (gw_fifo_space(&c->out) < SMA_BINARY_HEADER_BYTES + SMA_RESULT_PAYLOAD_BYTES) {
        bin_drop_pending_result(g, c);
        return;
    }
    if (c->result_gap) flags |= SMA_FLAG_GAP_BEFORE;
    if (bin_frame(g, c, SMA_MSG_RESULT_WORDS32, flags,
                  c->streams[idx].stream_id, c->streams[idx].seq++,
                  0, gw_result_frame_id(c->result_words),
                  gw_result_config_version(c->result_words),
                  c->result_words, SMA_RESULT_PAYLOAD_BYTES)) {
        c->result_pending = 0;
        c->result_gap = 0;
    }
}

static void bin_flush_service(gw *g, gw_bin_conn *c)
{
    int idx;
    uint16_t flags = 0;
    if (!c->service_pending || !c->hello_done) return;
    idx = conn_stream_index(c, "serviceSnapshot");
    if (idx < 0) { c->service_pending = 0; return; }
    if (gw_fifo_space(&c->out) < SMA_BINARY_HEADER_BYTES + c->service_bytes) {
        c->service_pending = 0;
        c->service_gap = 1;
        return;
    }
    if (c->service_gap) flags |= SMA_FLAG_GAP_BEFORE;
    {
        uint32_t stream_id = c->streams[idx].stream_id;
        uint32_t seq = c->streams[idx].seq++;
        if (bin_frame(g, c, SMA_MSG_SERVICE_SNAPSHOT, flags, stream_id, seq,
                      0, 0, 0, c->service_payload, c->service_bytes)) {
            c->service_pending = 0;
            c->service_gap = 0;
        }
    }
}

static void bin_send_event_chunks(gw *g, gw_bin_conn *c)
{
    while (c->event_download && !c->event_done) {
        uint64_t remain = c->event_total - c->event_offset;
        uint32_t chunk = c->chunk_bytes;
        size_t need;
        const gw_event_rec *rec;
        uint16_t flags = 0;
        uint32_t idx = 0;
        char err[128];
        if (remain == 0) { c->event_done = 1; break; }
        if ((uint64_t)chunk > remain) chunk = (uint32_t)remain;
        need = SMA_BINARY_HEADER_BYTES + chunk;
        if (gw_fifo_space(&c->out) < need) break;
        rec = gw_spool_find(&g->spool, c->event_id);
        if(rec)g->spool.recs[rec-g->spool.recs].protected_until_ms=g->now_ms+60000;
        if (!rec) {
            char payload[256];
            gw_json_writer w;
            gw_jw_init(&w, payload, sizeof payload);
            gw_jw_begin_obj(&w);
            gw_jw_key(&w, "streamId"); gw_jw_u32(&w, c->streams[idx].stream_id);
            gw_jw_key(&w, "reason"); gw_jw_str(&w, "spool_lost");
            gw_jw_key(&w, "droppedRecords"); gw_jw_str(&w, "0");
            gw_jw_end_obj(&w);
            if (gw_jw_finish(&w))
                (void)bin_frame(g, c, SMA_MSG_STREAM_GAP, 0,
                                c->streams[idx].stream_id, c->streams[idx].seq++,
                                0, 0, 0, payload, (uint32_t)w.len);
            g->stats.binary_gaps_sent++;
            bin_server_close_conn(g, c, "event_released");
            return;
        }
        if (gw_spool_read(&g->spool, rec, c->event_offset, c->event_buf, chunk,
                          err, sizeof err) != 0) {
            bin_server_close_conn(g, c, "event_read_error");
            return;
        }
        if (c->event_first) { flags |= SMA_FLAG_FIRST_CHUNK; c->event_first = 0; }
        if (c->event_offset + chunk == c->event_total) flags |= SMA_FLAG_LAST_CHUNK;
        if (!bin_frame(g, c, SMA_MSG_EVENT_FILE_CHUNK, flags,
                       c->streams[idx].stream_id, c->streams[idx].seq++,
                       0, 0, 0, c->event_buf, chunk))
            return;
        c->event_offset += chunk;
        if (c->event_offset >= c->event_total) c->event_done = 1;
    }
}

void bin_server_tick(gw *g)
{
    unsigned i;
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        if (!c->used) continue;
        if (g->now_ms - c->last_rx_ms > GW_BINARY_IDLE_MS && !c->closing) {
            bin_server_close_conn(g, c, "idle_timeout");
        }
        if (!c->used || c->closing) continue;
        if (!c->hello_done) continue;
        bin_send_schemas(g, c);
        if (!c->used || c->closing) continue;
        for(uint32_t k=0;k<c->nstreams;k++)if(c->streams[k].is_live){
            uint32_t payload[FC_LIVE_WORDS];fc_provenance source;
            if(gw_fifo_avail(&c->out)>FC_LIVE_WORDS*4u)continue;
            if(c->max_payload<FC_LIVE_WORDS*4u){bin_fatal(g,c,"bad_args","live FFT needs >=61708 bytes negotiated payload");break;}
            if(!fc_live_frame(g,c->streams[k].live_channel,c->streams[k].last_live_frame,c->streams[k].last_live_config,payload,&source)){
                if(bin_frame(g,c,0x20,source.gap?SMA_FLAG_GAP_BEFORE:0,c->streams[k].stream_id,c->streams[k].seq++,source.first_sample,source.frame,source.config,payload,sizeof payload)){
                    c->streams[k].last_live_frame=source.frame;c->streams[k].last_live_config=source.config;
                }
            }
        }
        bin_flush_result(g, c);
        bin_flush_service(g, c);
        bin_send_event_chunks(g, c);
        if (!c->used || c->closing) continue;
        {
            size_t space = gw_fifo_space(&c->out);
            if (!c->event_download && space < 256u * 1024u && gw_fifo_avail(&c->out) > 0) {
                /* bounded queues: a stalled consumer is disconnected instead of
                 * buffering without limit (PROTOCOL.md 6). Event files already
                 * pause at FIFO capacity in bin_send_event_chunks; filling that
                 * bounded queue is normal, not proof of a stalled receiver. */
                g->stats.binary_backpressure_closes++;
                bin_server_close_conn(g, c, "backpressure");
                continue;
            }
        }
        if (g->now_ms - c->last_heartbeat_ms >= GW_BINARY_HEARTBEAT_MS) {
            if (bin_frame(g, c, SMA_MSG_HEARTBEAT, 0, 0, c->conn_seq++, 0, 0, 0,
                          NULL, 0)) c->last_heartbeat_ms = g->now_ms;
        }
    }
}

void bin_publish_result(gw *g, const uint32_t words[SMA_RESULT_WORD_COUNT])
{
    unsigned i;
    int global_gap = g->result_gap_pending;
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        int gap;
        if (!c->used || !c->hello_done) continue;
        if (!c->streams[0].is_result) {
            uint32_t k;
            int has = 0;
            for (k = 0; k < c->nstreams; k++)
                if (c->streams[k].is_result) has = 1;
            if (!has) continue;
        }
        gap = global_gap || c->result_pending;
        if (c->result_pending) {
            c->result_dropped++;
            g->stats.result_frames_dropped++;
        }
        memcpy(c->result_words, words, SMA_RESULT_PAYLOAD_BYTES);
        c->result_pending = 1;
        if (gap) c->result_gap = 1;
    }
    g->result_gap_pending = 0;
}

void bin_publish_service(gw *g, const uint8_t *payload, uint32_t bytes)
{
    unsigned i;
    if (bytes == 0 || bytes > sizeof g->bin[0].service_payload) return;
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++) {
        gw_bin_conn *c = &g->bin[i];
        uint32_t k;
        int has = 0;
        if (!c->used || !c->hello_done) continue;
        for (k = 0; k < c->nstreams; k++)
            if (c->streams[k].is_service) has = 1;
        if (!has) continue;
        if (c->service_pending) c->service_gap = 1;
        memcpy(c->service_payload, payload, bytes);
        c->service_bytes = bytes;
        c->service_pending = 1;
    }
}

/* --------------------------------------------------------------- init */

int bin_server_init(gw *g, char *err, size_t errcap)
{
    (void)g;
    (void)err;
    (void)errcap;
    return 0;
}

void bin_server_shutdown(gw *g)
{
    unsigned i;
    if (!g) return;
    for (i = 0; i < GW_MAX_BINARY_CONNS; i++)
        if (g->bin[i].used) bin_free_conn(g, &g->bin[i]);
}
