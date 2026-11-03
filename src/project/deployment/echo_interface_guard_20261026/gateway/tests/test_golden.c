/* Golden cross-check for the frozen sixmic-analysis v1 wire format.
 *
 * Reads interfaces/pc_backend_v1/golden/ (read-only; never modified) and
 * verifies:
 *  - GOLDEN_MANIFEST.json sha256 of every sample still matches
 *  - each SMA1 header decodes and re-encodes byte-for-byte (explicit LE layout)
 *  - payload CRC32 and payload length
 *  - PCM records decode/re-encode byte-for-byte (24-bit sign extension + u64
 *    low-word-first sample index)
 *  - RESULT_WORDS32 / SERVICE_SNAPSHOT payload words match the header fields
 *  - SMC1 event container header CRC and record count
 *  - stream schema / event / error JSON payloads are strict JSON with the
 *    documented fields
 * Mismatches are reported; golden files are never edited. */
#include "gw_wire.h"
#include "json.h"
#include "sha256.h"
#include "gw_util.h"
#include "sixmic_analysis_wire.h"
#include "sixmic_host.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_fail;
static int g_checks;
static char g_golden[512];

#define CHECK(cond) do { \
    g_checks++; \
    if (!(cond)) { \
        printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        g_fail++; \
    } \
} while (0)

static void section(const char *name)
{
    printf("SECTION %s\n", name);
    fflush(stdout);
}

static int file_exists(const char *p)
{
    FILE *f = fopen(p, "rb");
    if (!f) return 0;
    fclose(f);
    return 1;
}

static int locate_golden(void)
{
    static const char *cands[] = {
        "interfaces/pc_backend_v1/golden",
        "../interfaces/pc_backend_v1/golden",
        "../../interfaces/pc_backend_v1/golden",
        "C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/golden"
    };
    size_t i;
    for (i = 0; i < sizeof cands / sizeof cands[0]; i++) {
        char probe[600];
        snprintf(probe, sizeof probe, "%s/GOLDEN_MANIFEST.json", cands[i]);
        if (file_exists(probe)) {
            snprintf(g_golden, sizeof g_golden, "%s", cands[i]);
            return 0;
        }
    }
    return -1;
}

static unsigned char *read_file(const char *rel, size_t *len_out)
{
    char path[900];
    FILE *f;
    long sz;
    unsigned char *buf;
    snprintf(path, sizeof path, "%s/%s", g_golden, rel);
    f = fopen(path, "rb");
    if (!f) { printf("MISSING_GOLDEN %s\n", rel); g_fail++; return NULL; }
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    sz = ftell(f);
    if (sz < 0) { fclose(f); return NULL; }
    rewind(f);
    buf = (unsigned char *)malloc((size_t)sz + 1);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    buf[sz] = 0;
    *len_out = (size_t)sz;
    return buf;
}

/* --------------------------------------------------------- header checks */

/* sixmic_analysis_wire.h sma_header_decode() rejects ANY payload on BYE
 * (-7), but PROTOCOL.md 5.3 defines BYE payload as UTF-8 JSON {reason} and
 * golden/binary/bye_backpressure.bin carries exactly that payload. This is a
 * frozen-interface gap (reported in docs/INTERFACE_GAPS.md); the test documents
 * it and decodes BYE fields manually instead of hiding the mismatch. */

static int manual_header(const unsigned char *raw, size_t len, sma_header *h)
{
    if (len < SMA_BINARY_HEADER_BYTES) return -1;
    if (memcmp(raw, "SMA1", 4) != 0) return -1;
    h->protocol_version = sma_get_u16(raw + SMA_HDR_OFF_PROTOCOL_VERSION);
    h->header_bytes = sma_get_u16(raw + SMA_HDR_OFF_HEADER_BYTES);
    h->message_type = sma_get_u16(raw + SMA_HDR_OFF_MESSAGE_TYPE);
    h->flags = sma_get_u16(raw + SMA_HDR_OFF_FLAGS);
    h->payload_bytes = sma_get_u32(raw + SMA_HDR_OFF_PAYLOAD_BYTES);
    h->stream_id = sma_get_u32(raw + SMA_HDR_OFF_STREAM_ID);
    h->sequence = sma_get_u32(raw + SMA_HDR_OFF_SEQUENCE);
    h->connection_epoch = sma_get_u64(raw + SMA_HDR_OFF_CONNECTION_EPOCH);
    h->first_sample_index = sma_get_u64(raw + SMA_HDR_OFF_FIRST_SAMPLE_INDEX);
    h->device_monotonic_ns = sma_get_u64(raw + SMA_HDR_OFF_DEVICE_TIME_NS);
    h->frame_id = sma_get_u32(raw + SMA_HDR_OFF_FRAME_ID);
    h->config_version = sma_get_u32(raw + SMA_HDR_OFF_CONFIG_VERSION);
    h->payload_crc32 = sma_get_u32(raw + SMA_HDR_OFF_PAYLOAD_CRC32);
    if (h->protocol_version != SMA_BINARY_PROTOCOL_VERSION) return -1;
    if (h->header_bytes != SMA_BINARY_HEADER_BYTES) return -1;
    if (sma_get_u32(raw + SMA_HDR_OFF_RESERVED) != 0) return -1;
    if ((size_t)h->payload_bytes != len - SMA_BINARY_HEADER_BYTES) return -1;
    return 0;
}

static void check_frame_header(const char *rel, int expect_type, int expect_flags,
                               int expect_flags_only)
{
    size_t len = 0;
    unsigned char *raw = read_file(rel, &len);
    sma_header h;
    uint8_t hdr[SMA_BINARY_HEADER_BYTES];
    int rc;
    if (!raw) return;
    CHECK(len >= SMA_BINARY_HEADER_BYTES);
    if (len < SMA_BINARY_HEADER_BYTES) { free(raw); return; }
    rc = sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD);
    if (rc == -7 && sma_get_u16(raw + SMA_HDR_OFF_MESSAGE_TYPE) == SMA_MSG_BYE) {
        /* documented gap: shared header decoder rejects BYE payload */
        CHECK(rc == -7);
        rc = manual_header(raw, len, &h);
    }
    if (rc != 0) printf("GOLDEN_DECODE_FAIL %s rc=%d\n", rel, rc);
    CHECK(rc == 0);
    if (rc != 0) { free(raw); return; }
    CHECK(h.header_bytes == SMA_BINARY_HEADER_BYTES);
    CHECK(h.protocol_version == SMA_BINARY_PROTOCOL_VERSION);
    CHECK(sma_get_u32(raw + SMA_HDR_OFF_RESERVED) == 0u);
    CHECK(h.payload_bytes == len - SMA_BINARY_HEADER_BYTES);
    if (expect_type >= 0) CHECK(h.message_type == (uint16_t)expect_type);
    if (expect_flags_only) CHECK(h.flags == (uint16_t)expect_flags);
    else CHECK((h.flags & (uint16_t)expect_flags) == (uint16_t)expect_flags);
    if (h.payload_bytes) {
        CHECK((h.flags & SMA_FLAG_CRC32_VALID) != 0);
        CHECK(sma_crc32(raw + SMA_BINARY_HEADER_BYTES, h.payload_bytes) ==
              h.payload_crc32);
    }
    /* header re-encode must be byte identical (explicit little-endian) */
    sma_header_encode(hdr, &h);
    CHECK(memcmp(hdr, raw, SMA_BINARY_HEADER_BYTES) == 0);
    free(raw);
}

static void check_result_words(void)
{
    size_t len = 0;
    unsigned char *raw = read_file("binary/result_words32.bin", &len);
    sma_header h;
    uint32_t words[SMA_RESULT_WORD_COUNT];
    uint8_t reenc[SMA_RESULT_PAYLOAD_BYTES];
    unsigned i;
    section("golden_result_words32");
    if (!raw) return;
    CHECK(len == SMA_BINARY_HEADER_BYTES + SMA_RESULT_PAYLOAD_BYTES);
    CHECK(sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD) == 0);
    CHECK(h.message_type == SMA_MSG_RESULT_WORDS32);
    for (i = 0; i < SMA_RESULT_WORD_COUNT; i++)
        words[i] = sma_get_u32(raw + SMA_BINARY_HEADER_BYTES + i * 4u);
    CHECK(gw_result_words_check(words) == 0);
    CHECK(h.frame_id == words[SM_R_FRAME]);
    CHECK(h.config_version == words[SM_R_CONFIG]);
    CHECK(gw_result_header_matches(h.frame_id, h.config_version, words) == 0);
    CHECK(words[SM_R_SAMPLE_RATE_FLOAT] == 0x473B89C6u);
    for (i = 0; i < SMA_RESULT_WORD_COUNT; i++)
        sma_put_u32(reenc + i * 4u, words[i]);
    CHECK(memcmp(reenc, raw + SMA_BINARY_HEADER_BYTES, SMA_RESULT_PAYLOAD_BYTES) == 0);
    free(raw);
}

static void check_pcm_records(void)
{
    size_t len = 0;
    unsigned char *raw = read_file("binary/pcm_record32_corner.bin", &len);
    sma_header h;
    size_t off;
    section("golden_pcm_record32");
    if (!raw) return;
    CHECK(sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD) == 0);
    CHECK(h.message_type == SMA_MSG_PCM_RECORD32);
    CHECK(h.payload_bytes % SMA_PCM_RECORD_BYTES == 0);
    CHECK(h.payload_bytes >= SMA_PCM_RECORD_BYTES);
    CHECK((h.flags & SMA_FLAG_SAMPLE_INDEX_VALID) != 0);
    for (off = 0; off + SMA_PCM_RECORD_BYTES <= h.payload_bytes;
         off += SMA_PCM_RECORD_BYTES) {
        const uint8_t *r = raw + SMA_BINARY_HEADER_BYTES + off;
        int32_t samples[SMA_PCM_CHANNELS];
        uint8_t reenc[SMA_PCM_RECORD_BYTES];
        uint64_t idx = 0;
        unsigned c;
        CHECK(gw_pcm_decode_record(r, samples, &idx) == 0);
        gw_pcm_encode_record(samples, idx, reenc);
        CHECK(memcmp(reenc, r, SMA_PCM_RECORD_BYTES) == 0);
        for (c = 0; c < SMA_PCM_CHANNELS; c++) {
            uint32_t v = sma_get_u32(r + SMA_PCM_CHANNEL_OFFSET(c));
            uint8_t sign = (uint8_t)((v >> 24) & 0xFFu);
            CHECK(sign == 0x00 || sign == 0xFF);
            if (v & 0x00800000u) CHECK(sign == 0xFF);
            else CHECK(sign == 0x00);
            CHECK((v & 0x00FFFFFFu) == (uint32_t)samples[c] ||
                  (int32_t)(v & 0x00FFFFFFu) - 0x01000000 == samples[c]);
        }
    }
    free(raw);
}

static void check_service_snapshot(void)
{
    size_t len = 0;
    unsigned char *raw = read_file("binary/service_snapshot.bin", &len);
    sma_header h;
    section("golden_service_snapshot");
    if (!raw) return;
    CHECK(sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD) == 0);
    CHECK(h.message_type == SMA_MSG_SERVICE_SNAPSHOT);
    CHECK(h.payload_bytes >= SMA_SERVICE_HEADER_BYTES);
    CHECK(sma_get_u32(raw + SMA_BINARY_HEADER_BYTES) == 0x52534C54u);
    {
        uint32_t n = sma_get_u32(raw + SMA_BINARY_HEADER_BYTES + 10u * 4u);
        CHECK(h.payload_bytes == SMA_SERVICE_HEADER_BYTES + n * 4u);
    }
    free(raw);
}

static void check_event_container(void)
{
    size_t len = 0;
    unsigned char *raw = read_file("event/event_file_sample.smc", &len);
    gw_smc1 h;
    uint8_t reenc[GW_SMC1_HEADER_BYTES];
    section("golden_event_container");
    if (!raw) return;
    CHECK(len >= GW_SMC1_HEADER_BYTES);
    CHECK(gw_smc1_decode(raw, &h) == 0);
    gw_smc1_encode(&h, reenc);
    CHECK(memcmp(reenc, raw, GW_SMC1_HEADER_BYTES) == 0);
    CHECK(len == GW_SMC1_HEADER_BYTES + h.record_count * GW_SMC1_RECORD_BYTES);
    CHECK(h.record_count > 0);
    free(raw);
}

/* ------------------------------------------------------ payload JSON checks */

static int payload_json(const unsigned char *raw, const sma_header *h,
                         gw_json_doc *doc)
{
    char err[128];
    if (!raw || !h || !doc) return -1;
    return gw_json_parse(doc, (const char *)(raw + SMA_BINARY_HEADER_BYTES),
                         h->payload_bytes, 32, 20000, err, sizeof err);
}

static void check_json_payloads(void)
{
    static const struct { const char *file; const char *must; } cases[] = {
        { "binary/hello_frame.bin", "\"protocol\":\"sixmic-analysis\"" },
        { "binary/hello_ack_frame.bin", "\"accepted\":true" },
        { "binary/stream_gap.bin", "\"reason\":" },
        { "binary/error_fatal.bin", "\"messageKey\":" },
        { "binary/bye_backpressure.bin", "\"reason\":\"backpressure\"" }
    };
    size_t i;
    section("golden_json_payloads");
    for (i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        size_t len = 0;
        unsigned char *raw = read_file(cases[i].file, &len);
        sma_header h;
        gw_json_doc doc;
        memset(&h, 0, sizeof h);
        if (!raw) continue;
        /* BYE carries optional JSON {"reason":...} (PROTOCOL 5.3). The earlier
         * shared-decoder erratum rejected it; interface erratum 2026-10-24 fixes
         * the shared header, so BYE must now decode like any other payload. */
        CHECK(sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD) == 0);
        CHECK(manual_header(raw, len, &h) == 0);
        CHECK(payload_json(raw, &h, &doc) == 0);
        CHECK(gw_json_root(&doc) != NULL);
        CHECK(strstr((const char *)(raw + SMA_BINARY_HEADER_BYTES),
                     cases[i].must) != NULL);
        gw_json_doc_free(&doc);
        free(raw);
    }
    {
        size_t len = 0;
        unsigned char *raw = read_file("binary/stream_schema_pcm.bin", &len);
        sma_header h;
        gw_json_doc doc;
        const gw_json_node *root, *pcm;
        memset(&h, 0, sizeof h);
        if (raw) {
            int drc = sma_header_decode(raw, &h, SMA_MAX_MAX_BINARY_PAYLOAD);
            if (drc != 0) printf("GOLDEN_DECODE_FAIL stream_schema_pcm rc=%d\n", drc);
            CHECK(drc == 0);
        }
        if (raw && h.message_type == SMA_MSG_STREAM_SCHEMA &&
            payload_json(raw, &h, &doc) == 0) {
            root = gw_json_root(&doc);
            pcm = gw_json_obj_get(&doc, root, "pcm");
            CHECK(pcm != NULL && pcm->type == GW_JSON_OBJECT);
            CHECK(gw_json_arr_count(gw_json_obj_get(&doc, pcm, "channelOrder")) == 6);
            {
                const gw_json_node *exact = gw_json_obj_get(&doc, pcm,
                                                            "sampleRateExactHz");
                const gw_json_node *hz = gw_json_obj_get(&doc, pcm, "sampleRateHz");
                CHECK(exact && exact->type == GW_JSON_NUMBER);
                CHECK(hz && hz->type == GW_JSON_NUMBER);
                if (exact) CHECK(exact->number > 48009.7 && exact->number < 48009.8);
                if (hz) CHECK(hz->number > 48009.7 && hz->number < 48009.8);
            }
            gw_json_doc_free(&doc);
        } else {
            CHECK(0);
        }
        free(raw);
    }
}

/* -------------------------------------------------------------- manifest */

static void check_manifest(void)
{
    size_t len = 0;
    unsigned char *raw = read_file("GOLDEN_MANIFEST.json", &len);
    gw_json_doc doc;
    char err[128];
    const gw_json_node *root, *meta;
    section("golden_manifest");
    if (!raw) return;
    CHECK(gw_json_parse(&doc, (const char *)raw, len, 32, 20000, err, sizeof err) == 0);
    root = gw_json_root(&doc);
    meta = gw_json_obj_get(&doc, root, "_meta");
    CHECK(meta != NULL);
    if (meta) {
        char bits[24] = "";
        uint32_t parsed = 0;
        CHECK(gw_json_get_str(&doc, meta, "sampleRateFloat32Bits",
                              bits, sizeof bits, NULL) == 0);
        CHECK(gw_parse_hex_u32(bits, strlen(bits), &parsed) == 0);
        CHECK(parsed == 0x473B89C6u);
    }
    {
        const gw_json_node *m;
        unsigned files = 0;
        for (m = root->child; m; m = m->next) {
            char name[128];
            size_t nlen = 0;
            const char *s = gw_json_key(&doc, m, &nlen);
            size_t flen = 0;
            unsigned char *data;
            uint8_t digest[32];
            char hex[65];
            char expect[80];
            if (!s || nlen >= sizeof name || m->type != GW_JSON_OBJECT) continue;
            memcpy(name, s, nlen);
            name[nlen] = 0;
            if (name[0] == '_') continue;
            data = read_file(name, &flen);
            if (!data) continue;
            gw_sha256(data, flen, digest);
            gw_sha256_hex(digest, hex);
            if (gw_json_get_str(&doc, m, "sha256", expect, sizeof expect, NULL) == 0)
                CHECK(strcmp(hex, expect) == 0);
            free(data);
            files++;
        }
        CHECK(files >= 19);
    }
    gw_json_doc_free(&doc);
    free(raw);
}

/* ------------------------------------------------------------ control lines */

static void check_control_lines(void)
{
    static const char *files[] = {
        "control/hello_request.jsonl",
        "control/hello_response.jsonl",
        "control/status_get_request.jsonl",
        "control/config_read_response.jsonl",
        "control/error_not_ready.jsonl",
        "control/job_accepted_response.jsonl",
        "control/job_updated_event.jsonl"
    };
    size_t i;
    section("golden_control_lines");
    for (i = 0; i < sizeof files / sizeof files[0]; i++) {
        size_t len = 0;
        unsigned char *raw = read_file(files[i], &len);
        size_t pos = 0;
        if (!raw) continue;
        while (pos < len) {
            size_t eol = pos;
            char line[70000];
            gw_json_doc doc;
            const gw_json_node *root;
            char type[24] = "";
            char err[128];
            while (eol < len && raw[eol] != '\n') eol++;
            CHECK(eol - pos < sizeof line);
            if (eol - pos >= sizeof line) break;
            memcpy(line, raw + pos, eol - pos);
            line[eol - pos] = 0;
            pos = eol + 1;
            if (line[0] == 0) continue;
            CHECK(gw_json_parse(&doc, line, strlen(line), 32, 20000,
                                err, sizeof err) == 0);
            root = gw_json_root(&doc);
            CHECK(root && root->type == GW_JSON_OBJECT);
            if (gw_json_get_str(&doc, root, "type", type, sizeof type, NULL) != 0)
                snprintf(type, sizeof type, "request"); /* request envelopes have no type */
            if (strcmp(type, "request") == 0) {
                char proto[32];
                CHECK(gw_json_get_str(&doc, root, "protocol", proto, sizeof proto, NULL) == 0);
                CHECK(strcmp(proto, "sixmic-analysis") == 0);
                CHECK(gw_json_obj_get(&doc, root, "op") != NULL);
                CHECK(gw_json_obj_get(&doc, root, "args") != NULL);
            } else if (strcmp(type, "response") == 0) {
                char status[16];
                CHECK(gw_json_get_str(&doc, root, "status", status, sizeof status, NULL) == 0);
                CHECK(strcmp(status, "ok") == 0 || strcmp(status, "accepted") == 0 ||
                      strcmp(status, "error") == 0);
            } else if (strcmp(type, "event") == 0) {
                uint64_t event_id = 0;
                CHECK(gw_json_get_u64_dec(&doc, root, "eventId", &event_id) == 0);
                CHECK(gw_json_obj_get(&doc, root, "event") != NULL);
                CHECK(gw_json_obj_get(&doc, root, "data") != NULL);
            }
            gw_json_doc_free(&doc);
        }
        free(raw);
    }
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("GOLDEN_TEST_START pid=%d\n", gw_pid());
    section("locate");
    if (locate_golden() != 0) {
        printf("GOLDEN_TESTS_FAIL missing golden directory\n");
        return 1;
    }
    printf("GOLDEN_ROOT %s\n", g_golden);
    check_manifest();
    check_frame_header("binary/hello_frame.bin", SMA_MSG_HELLO, 0, 0);
    check_frame_header("binary/hello_ack_frame.bin", SMA_MSG_HELLO_ACK, 0, 0);
    check_frame_header("binary/heartbeat.bin", SMA_MSG_HEARTBEAT, 0, 1);
    check_frame_header("binary/stream_schema_pcm.bin", SMA_MSG_STREAM_SCHEMA, 0, 0);
    check_frame_header("binary/result_words32.bin", SMA_MSG_RESULT_WORDS32, 0, 0);
    check_frame_header("binary/service_snapshot.bin", SMA_MSG_SERVICE_SNAPSHOT, 0, 0);
    check_frame_header("binary/pcm_record32_corner.bin", SMA_MSG_PCM_RECORD32, 0, 0);
    check_frame_header("binary/event_chunk_first.bin", SMA_MSG_EVENT_FILE_CHUNK,
                       SMA_FLAG_FIRST_CHUNK, 0);
    check_frame_header("binary/event_chunk_last.bin", SMA_MSG_EVENT_FILE_CHUNK,
                       SMA_FLAG_LAST_CHUNK, 0);
    check_frame_header("binary/stream_gap.bin", SMA_MSG_STREAM_GAP, 0, 0);
    check_frame_header("binary/error_fatal.bin", SMA_MSG_ERROR, 0, 0);
    check_frame_header("binary/bye_backpressure.bin", SMA_MSG_BYE, 0, 0);
    check_result_words();
    check_pcm_records();
    check_service_snapshot();
    check_event_container();
    check_json_payloads();
    check_control_lines();
    if (g_fail) {
        printf("GOLDEN_TESTS_FAIL failures=%d checks=%d\n", g_fail, g_checks);
        return 1;
    }
    printf("GOLDEN_TESTS_PASS checks=%d\n", g_checks);
    return 0;
}
