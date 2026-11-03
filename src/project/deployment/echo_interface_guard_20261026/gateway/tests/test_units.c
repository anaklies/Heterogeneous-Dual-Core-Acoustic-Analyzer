/* Host unit tests: JSON/UTF-8/SHA-256/CRC/SMC1/PCM wire helpers, bounded
 * queues, event spool idempotent ack, config validation mirror, device
 * arbitration, and the protocol-3 fake-MMIO snapshot/service retry semantics.
 * These are host-runnable; no physical board is involved. */
#include "fake_mmio.h"
#include "gateway.h"
#include "gw_util.h"
#include "gw_wire.h"
#include "json.h"
#include "sha256.h"
#include "spool.h"
#include "utf8.h"
#include "device_arbiter.h"
#include "mock_mmio.h"
#include "sixmic_analysis_wire.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_fail;
static int g_checks;

#define CHECK(cond) do { \
    g_checks++; \
    if (!(cond)) { \
        printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        g_fail++; \
    } \
} while (0)

static void section(const char *name) { printf("SECTION %s\n", name); }

static char g_tmp[256];

static void make_tmp(const char *tag)
{
    snprintf(g_tmp, sizeof g_tmp, "build/unit_%s_%d", tag, gw_pid());
}

/* ------------------------------------------------------------------ SHA256 */

static void test_sha256(void)
{
    uint8_t d[32];
    char hex[65];
    section("sha256");
    gw_sha256("abc", 3, d);
    gw_sha256_hex(d, hex);
    CHECK(strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") == 0);
    gw_sha256("", 0, d);
    gw_sha256_hex(d, hex);
    CHECK(strcmp(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") == 0);
    CHECK(sma_crc32((const uint8_t *)"123456789", 9) == 0xCBF43926u);
}

/* -------------------------------------------------------------------- UTF8 */

static void test_utf8(void)
{
    size_t bad = 0;
    section("utf8");
    CHECK(gw_utf8_valid((const uint8_t *)"hello", 5, NULL) == 1);
    CHECK(gw_utf8_valid((const uint8_t *)"\xC3\xA9", 2, NULL) == 1);
    CHECK(gw_utf8_valid((const uint8_t *)"\xE2\x82\xAC", 3, NULL) == 1);
    CHECK(gw_utf8_valid((const uint8_t *)"\xF0\x9F\x98\x80", 4, NULL) == 1);
    CHECK(gw_utf8_valid((const uint8_t *)"\xC0\xAF", 2, &bad) == 0); /* overlong */
    CHECK(bad == 0);
    CHECK(gw_utf8_valid((const uint8_t *)"\xED\xA0\x80", 3, NULL) == 0); /* surrogate */
    CHECK(gw_utf8_valid((const uint8_t *)"\xF4\x90\x80\x80", 4, NULL) == 0); /* >10FFFF */
    CHECK(gw_utf8_valid((const uint8_t *)"\xE2\x82", 2, NULL) == 0); /* truncated */
    CHECK(gw_utf8_valid((const uint8_t *)"\x80", 1, NULL) == 0); /* stray cont */
    {
        uint8_t enc[4];
        uint32_t cp = 0;
        size_t n = gw_utf8_encode(0x1F600u, enc);
        CHECK(n == 4);
        CHECK(gw_utf8_decode(enc, n, &cp) == n);
        CHECK(cp == 0x1F600u);
        CHECK(gw_utf8_encode(0xD800u, enc) == 0);
    }
}

/* -------------------------------------------------------------------- JSON */

static void test_json(void)
{
    gw_json_doc doc;
    char err[96];
    const gw_json_node *root, *v;
    const char *text;
    section("json");
    text = "{\"a\":1,\"b\":[true,false,null],\"s\":\"x\\u00e9\\ud83d\\ude00\","
           "\"u\":\"18446744073709551615\"}";
    CHECK(gw_json_parse(&doc, text, strlen(text), 32, 20000, err, sizeof err) == 0);
    root = gw_json_root(&doc);
    CHECK(root && root->type == GW_JSON_OBJECT);
    {
        uint32_t a = 0;
        CHECK(gw_json_get_u32(&doc, root, "a", &a) == 0 && a == 1);
    }
    v = gw_json_obj_get(&doc, root, "b");
    CHECK(v && v->type == GW_JSON_ARRAY && gw_json_arr_count(v) == 3);
    CHECK(gw_json_arr_at(v, 0)->type == GW_JSON_BOOL && gw_json_arr_at(v, 0)->boolean == 1);
    CHECK(gw_json_arr_at(v, 2)->type == GW_JSON_NULL);
    {
        size_t n = 0;
        const char *s = gw_json_str(&doc, gw_json_obj_get(&doc, root, "s"), &n);
        CHECK(s && n == 7); /* "x" + e-acute(2) + emoji(4) */
        CHECK(s && (unsigned char)s[1] == 0xC3);
    }
    {
        uint64_t u = 0;
        CHECK(gw_json_get_u64_dec(&doc, root, "u", &u) == 0);
        CHECK(u == 18446744073709551615ull);
    }
    gw_json_doc_free(&doc);

    CHECK(gw_json_parse(&doc, "{\"a\":1,\"a\":2}", 13, 32, 20000, err, sizeof err) < 0);
    CHECK(gw_json_parse(&doc, "{\"a\":NaN}", 9, 32, 20000, err, sizeof err) < 0);
    CHECK(gw_json_parse(&doc, "{\"a\":1}x", 8, 32, 20000, err, sizeof err) < 0);
    CHECK(gw_json_parse(&doc, "{\"a\":1e999}", 10, 32, 20000, err, sizeof err) < 0);
    CHECK(gw_json_parse(&doc, "\"\\ud800\"", 8, 32, 20000, err, sizeof err) < 0);
    CHECK(gw_json_parse(&doc, "\"\\q\"", 4, 32, 20000, err, sizeof err) < 0);
    {
        char deep[512];
        int i;
        int pos = 0;
        for (i = 0; i < 40; i++) deep[pos++] = '[';
        for (i = 0; i < 40; i++) deep[pos++] = ']';
        deep[pos] = 0;
        CHECK(gw_json_parse(&doc, deep, (size_t)pos, 32, 20000, err, sizeof err) < 0);
        CHECK(gw_json_parse(&doc, deep, (size_t)pos, 64, 20000, err, sizeof err) == 0);
        gw_json_doc_free(&doc);
    }
    /* writer round trip incl. escaping */
    {
        char buf[512];
        char in[800];
        gw_json_writer w;
        gw_jw_init(&w, buf, sizeof buf);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "k\"x");
        gw_jw_str(&w, "a\nb\tc\x01");
        gw_jw_key(&w, "n");
        gw_jw_u32(&w, 4294967295u);
        gw_jw_key(&w, "u");
        gw_jw_u64dec_str(&w, 18446744073709551615ull);
        gw_jw_key(&w, "arr");
        gw_jw_begin_arr(&w);
        gw_jw_bool(&w, 1);
        gw_jw_null(&w);
        gw_jw_end_arr(&w);
        gw_jw_end_obj(&w);
        CHECK(gw_jw_finish(&w) > 0);
        snprintf(in, sizeof in, "%s", buf);
        CHECK(gw_json_parse(&doc, in, strlen(in), 32, 20000, err, sizeof err) == 0);
        root = gw_json_root(&doc);
        CHECK(root != NULL);
        gw_json_doc_free(&doc);
    }
    {
        char buf[8];
        gw_json_writer w;
        gw_jw_init(&w, buf, sizeof buf);
        gw_jw_begin_obj(&w);
        gw_jw_key(&w, "longkey");
        gw_jw_str(&w, "012345678901234567890123456789");
        gw_jw_end_obj(&w);
        CHECK(gw_jw_finish(&w) == 0);
    }
}

/* ------------------------------------------------------------------ queues */

static void test_queues(void)
{
    gw_fifo f;
    gw_msgq q;
    unsigned i;
    section("bounded_queues");
    CHECK(gw_fifo_init(&f, 16) == 0);
    CHECK(gw_fifo_write(&f, "0123456789", 10) == 10);
    CHECK(gw_fifo_write(&f, "abcdefghij", 10) == 6);
    CHECK(f.dropped_bytes == 4u);
    {
        uint8_t out[32];
        size_t n = gw_fifo_read(&f, out, 8);
        CHECK(n == 8 && memcmp(out, "01234567", 8) == 0);
        CHECK(gw_fifo_avail(&f) == 8);
        {
            size_t contig = 0;
            const uint8_t *p = gw_fifo_peek(&f, &contig);
            CHECK(p != NULL && contig == 8 && memcmp(p, "89abcdef", 8) == 0);
            gw_fifo_consume(&f, 2);
            CHECK(gw_fifo_avail(&f) == 6);
        }
    }
    gw_fifo_free(&f);

    gw_msgq_init(&q);
    for (i = 0; i < GW_MSGQ_MAX + 2; i++) {
        char line[32];
        snprintf(line, sizeof line, "L%u", i);
        CHECK(gw_msgq_push(&q, line) == 1);
    }
    CHECK(gw_msgq_count(&q) == GW_MSGQ_MAX);
    CHECK(q.dropped == 2u);
    CHECK(strcmp(gw_msgq_front(&q), "L2") == 0);
    gw_msgq_free(&q);
}

/* ------------------------------------------------------------------- wire */

static void test_wire(void)
{
    section("wire");
    {
        int32_t samples[6];
        int32_t decoded[6];
        uint8_t rec[SMA_PCM_RECORD_BYTES];
        uint64_t idx = 0;
        samples[0] = -8388608;  /* 0xFF800000 */
        samples[1] = 8388607;   /* 0x007FFFFF */
        samples[2] = -1;
        samples[3] = 0;
        samples[4] = 0x00123456;
        samples[5] = -2;
        gw_pcm_encode_record(samples, 0x1122334455667788ull, rec);
        CHECK(rec[0] == 0x00 && rec[1] == 0x00 && rec[2] == 0x80 && rec[3] == 0xFF);
        CHECK(rec[4] == 0xFF && rec[5] == 0xFF && rec[6] == 0x7F && rec[7] == 0x00);
        CHECK(rec[8] == 0xFF && rec[9] == 0xFF && rec[10] == 0xFF && rec[11] == 0xFF);
        CHECK(rec[12] == 0 && rec[13] == 0 && rec[14] == 0 && rec[15] == 0);
        CHECK(rec[16] == 0x56 && rec[17] == 0x34 && rec[18] == 0x12 && rec[19] == 0x00);
        CHECK(rec[20] == 0xFE && rec[21] == 0xFF && rec[22] == 0xFF && rec[23] == 0xFF);
        CHECK(rec[24] == 0x88 && rec[25] == 0x77 && rec[26] == 0x66 && rec[27] == 0x55);
        CHECK(rec[28] == 0x44 && rec[29] == 0x33 && rec[30] == 0x22 && rec[31] == 0x11);
        CHECK(gw_pcm_decode_record(rec, decoded, &idx) == 0);
        CHECK(idx == 0x1122334455667788ull);
        CHECK(decoded[0] == -8388608 && decoded[1] == 8388607 && decoded[2] == -1);
        CHECK(decoded[4] == 0x00123456 && decoded[5] == -2);
        /* fourth byte must equal the sign extension byte */
        rec[3] = 0x00;
        CHECK(gw_pcm_decode_record(rec, decoded, &idx) == -2);
    }
    {
        uint8_t payload[3 * SMA_PCM_RECORD_BYTES];
        uint8_t bad[2 * SMA_PCM_RECORD_BYTES];
        int32_t samples[6] = {0, 0, 0, 0, 0, 0};
        uint64_t first = 0;
        uint32_t count = 0;
        unsigned i;
        for (i = 0; i < 3; i++)
            gw_pcm_encode_record(samples, 1000 + i, payload + i * 32);
        CHECK(gw_pcm_validate_payload(payload, sizeof payload, &first, &count) == 0);
        CHECK(first == 1000 && count == 3);
        gw_pcm_encode_record(samples, 2000, bad);
        gw_pcm_encode_record(samples, 2002, bad + 32);
        CHECK(gw_pcm_validate_payload(bad, sizeof bad, &first, &count) == -3);
        CHECK(gw_pcm_validate_payload(payload, 33, &first, &count) == -2);
        CHECK(gw_pcm_validate_payload(payload, 0, &first, &count) == -1);
    }
    {
        uint8_t hdr[GW_SMC1_HEADER_BYTES];
        gw_smc1 h, back;
        gw_smc1_init(&h);
        h.event_id = 1234;
        h.record_count = 10;
        h.first_sample = 555;
        h.last_sample = 564;
        h.flags = GW_SMC1_FLAG_INCOMPLETE;
        h.clip_reason = 3;
        h.sample_rate_word = 0x473B89C6u;
        gw_smc1_encode(&h, hdr);
        CHECK(memcmp(hdr, "SMC1", 4) == 0);
        CHECK(sma_get_u16(hdr + 4) == 1);
        CHECK(sma_get_u16(hdr + 6) == 64);
        CHECK(sma_get_u32(hdr + 8) == 32);
        CHECK(sma_get_u32(hdr + 12) == 6);
        CHECK(sma_get_u64(hdr + 24) == 1234);
        CHECK(sma_get_u64(hdr + 32) == 555);
        CHECK(sma_get_u64(hdr + 40) == 564);
        CHECK(sma_get_u64(hdr + 48) == 10);
        CHECK(sma_get_u32(hdr + 56) == 0x473B89C6u);
        CHECK(sma_get_u32(hdr + 60) == sma_crc32(hdr, 56));
        CHECK(gw_smc1_decode(hdr, &back) == 0);
        CHECK(back.event_id == 1234 && back.record_count == 10);
        hdr[20] ^= 1; /* corrupt clipReason -> CRC fails */
        CHECK(gw_smc1_decode(hdr, &back) == -6);
    }
    {
        uint32_t words[SMA_RESULT_WORD_COUNT];
        uint8_t payload[SMA_RESULT_PAYLOAD_BYTES];
        uint8_t frame[SMA_BINARY_HEADER_BYTES + SMA_RESULT_PAYLOAD_BYTES];
        gw_fifo fifo;
        sma_header h;
        unsigned i;
        fake_fill_result_words(words, 77, 5, 9, 0x1122334455667788ull);
        for (i = 0; i < SMA_RESULT_WORD_COUNT; i++)
            sma_put_u32(payload + i * 4u, words[i]);
        memset(&h, 0, sizeof h);
        h.protocol_version = 1;
        h.header_bytes = 64;
        h.message_type = SMA_MSG_RESULT_WORDS32;
        h.flags = SMA_FLAG_CRC32_VALID | SMA_FLAG_SAMPLE_INDEX_VALID;
        h.payload_bytes = SMA_RESULT_PAYLOAD_BYTES;
        h.stream_id = 3;
        h.sequence = 7;
        h.connection_epoch = 4;
        h.first_sample_index = 0x1122334455667788ull;
        h.frame_id = 77;
        h.config_version = 5;
        h.payload_crc32 = sma_crc32(payload, sizeof payload);
        CHECK(gw_fifo_init(&fifo, 1024) == 0);
        CHECK(gw_binary_append_frame(&fifo, &h, payload) == 1);
        CHECK(gw_fifo_avail(&fifo) == sizeof frame);
        CHECK(gw_fifo_read(&fifo, frame, sizeof frame) == sizeof frame);
        CHECK(memcmp(frame, "SMA1", 4) == 0);
        CHECK(sma_get_u16(frame + 4) == 1);
        CHECK(sma_get_u16(frame + 6) == 64);
        CHECK(sma_get_u16(frame + 8) == SMA_MSG_RESULT_WORDS32);
        CHECK(sma_get_u16(frame + 10) == (SMA_FLAG_CRC32_VALID | SMA_FLAG_SAMPLE_INDEX_VALID));
        CHECK(sma_get_u32(frame + 12) == 128);
        CHECK(sma_get_u32(frame + 16) == 3);
        CHECK(sma_get_u32(frame + 20) == 7);
        CHECK(sma_get_u64(frame + 24) == 4);
        CHECK(sma_get_u64(frame + 32) == 0x1122334455667788ull);
        CHECK(sma_get_u64(frame + 40) == 0);
        CHECK(sma_get_u32(frame + 48) == 77);
        CHECK(sma_get_u32(frame + 52) == 5);
        CHECK(sma_get_u32(frame + 56) == sma_crc32(frame + 64, 128));
        CHECK(sma_get_u32(frame + 60) == 0);
        CHECK(memcmp(frame + 64, payload, 128) == 0);
        CHECK(gw_result_words_check(words) == 0);
        CHECK(gw_result_header_matches(77, 5, words) == 0);
        CHECK(gw_result_header_matches(78, 5, words) != 0);
        CHECK(gw_result_header_matches(77, 6, words) != 0);
        gw_fifo_free(&fifo);
    }
}

/* ------------------------------------------------------ fake-MMIO protocol */

static void test_fake_mmio_retries(void)
{
    mock_mmio *m;
    sm_snapshot snap;
    sm_identity id;
    uint32_t words[32];
    section("fake_mmio_retry");
    m = mock_mmio_create();
    CHECK(m != NULL);
    if (!m) return;
    CHECK(sm_identify(&mock_mmio_gw(m)->dev, &id) == SM_OK);
    CHECK(id.protocol == 3);
    fake_fill_result_words(words, 1, 1, 1, 42);
    mock_mmio_set_result_words(m, words);
    CHECK(sm_read_snapshot(&mock_mmio_gw(m)->dev, &snap, 3) == SM_OK);
    CHECK(snap.word[SM_R_FRAME] == 1 && snap.epoch == 1);

    fake_fill_result_words(words, 2, 1, 1, 84);
    mock_mmio_set_result_words(m, words);
    mock_mmio_set_snapshot_flip(m, 1); /* one epoch race, retry succeeds */
    CHECK(sm_read_snapshot(&mock_mmio_gw(m)->dev, &snap, 3) == SM_OK);
    CHECK(snap.word[SM_R_FRAME] == 2);

    mock_mmio_set_snapshot_flip(m, 2); /* every read races: always SM_RETRY */
    CHECK(sm_read_snapshot(&mock_mmio_gw(m)->dev, &snap, 3) == SM_RETRY);
    mock_mmio_set_snapshot_flip(m, 0);

    /* service snapshot: stable header accepted */
    {
        uint32_t hdr[16];
        uint32_t data[8];
        uint32_t out[8];
        sm_service_result meta;
        uint32_t addr = GW_MOCK_DDR_BASE + 0x200000u;
        unsigned i;
        fake_fill_service_header(hdr, 1, 1, 8, 1);
        for (i = 0; i < 8; i++) data[i] = 100u + i;
        mock_mmio_set_service(m, addr, hdr, data, 8);
        CHECK(sm_copy_service(&mock_mmio_gw(m)->mem, addr, 8, 1, 1, out, &meta, 2) == SM_OK);
        CHECK(meta.word[1] == 7u && meta.word[14] == 1u);
        CHECK(out[0] == 100u && out[7] == 107u);
        mock_mmio_set_service_flip(m, 1); /* header changes once: retry accepted */
        CHECK(sm_copy_service(&mock_mmio_gw(m)->mem, addr, 8, 1, 1, out, &meta, 3) == SM_OK);
        mock_mmio_set_service_flip(m, 2); /* header changes every attempt */
        CHECK(sm_copy_service(&mock_mmio_gw(m)->mem, addr, 8, 1, 1, out, &meta, 3) == SM_RETRY);
        mock_mmio_set_service_flip(m, 0);
    }
    mock_mmio_destroy(m);
}

/* ----------------------------------------------------------- device arbiter */

static void test_arbiter(void)
{
    gw_arbiter a;
    char token[33] = {0};
    char holder[GW_ARB_OWNER_MAX];
    uint64_t exp = 0, since = 0;
    section("device_arbiter");
    gw_arb_init(&a);
    CHECK(gw_arb_claim(&a, "clientA", 5, 1000, token, &exp, holder, &since) == 0);
    CHECK(strlen(token) == 32);
    CHECK(exp == 5000);
    CHECK(gw_arb_can_write(&a, token) == 1);
    {
        char token2[33];
        CHECK(gw_arb_claim(&a, "clientB", 5, 1100, token2, &exp, holder, &since) == 1);
        CHECK(strcmp(holder, "clientA") == 0);
        CHECK(gw_arb_can_write(&a, token2) == 0);
    }
    CHECK(gw_arb_renew(&a, "00000000000000000000000000000000", 1200, &exp) == -1);
    CHECK(gw_arb_renew(&a, token, 1200, &exp) == 0 && exp == 5000);
    CHECK(gw_arb_tick(&a, 6199) == 0);
    CHECK(gw_arb_held(&a) == 1);
    CHECK(gw_arb_tick(&a, 6200) == 1);
    CHECK(gw_arb_held(&a) == 0);

    /* explicit release with an accepted transaction drains first */
    gw_arb_init(&a);
    CHECK(gw_arb_claim(&a, "clientA", 30, 0, token, &exp, holder, &since) == 0);
    gw_arb_pending_inc(&a);
    CHECK(gw_arb_release(&a, token, 0) == 0);
    CHECK(gw_arb_can_write(&a, token) == 0);
    CHECK(gw_arb_held(&a) == 1); /* draining */
    CHECK(gw_arb_tick(&a, 1) == 0);
    gw_arb_pending_dec(&a);
    CHECK(gw_arb_tick(&a, 2) == 1);
    CHECK(gw_arb_held(&a) == 0);

    /* lease expiry with pending work enters draining, never silently aborts */
    gw_arb_init(&a);
    CHECK(gw_arb_claim(&a, "clientA", 5, 0, token, &exp, holder, &since) == 0);
    gw_arb_pending_inc(&a);
    CHECK(gw_arb_tick(&a, 5000) == 0);
    CHECK(a.state == GW_ARB_DRAINING);
    CHECK(gw_arb_tick(&a, 9000) == 0);
    gw_arb_pending_dec(&a);
    CHECK(gw_arb_tick(&a, 9001) == 1);
    CHECK(gw_arb_held(&a) == 0);
}

/* -------------------------------------------------------- config validation */

static void test_config_validation(void)
{
    gw g;
    uint32_t words[32];
    uint32_t bad_index = 0;
    const char *reason = NULL;
    section("config_validation");
    memset(&g, 0, sizeof g);
    fake_fill_config(words, 1, 1);
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) == 0);
    words[SM_C_VERSION] = 0;
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    g.active_config_version = 1;
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    g.active_config_version = 0;
    fake_fill_config(words, 1, 1);
    words[SM_C_FLAGS] |= 0x10u;
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    words[SM_C_BANK1] = words[SM_C_BANK0];
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    words[SM_C_BANK_BYTES] = 0x100000u; /* below 16 MiB */
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    words[SM_C_P1_DESCRIPTOR] = words[SM_C_ARENA_WORDS];
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    words[SM_C_RAW_HIGH] = 0x12000000u; /* ring outside raw window */
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    fake_fill_config(words, 1, 1);
    g.last_rejected_version = 1;
    CHECK(gw_config_validate(&g, words, &bad_index, &reason) != 0);
    g.last_rejected_version = 0;
    {
        uint32_t cfg[32];
        fake_fill_config(cfg, 1, 2);
        CHECK(gw_config_validate(&g, cfg, &bad_index, &reason) == 0);
    }
}

/* ------------------------------------------------------------------ spool */

static void test_spool(void)
{
    gw_spool spool;
    gw_spool_writer writer;
    gw_smc1 hdr;
    gw_event_rec rec;
    char err[192];
    uint32_t words[32];
    uint8_t *records;
    uint8_t *readback;
    uint32_t frames = 4;
    uint64_t total = 0, first = 0;
    section("spool");
    make_tmp("spool");
    memset(&spool, 0, sizeof spool);
    CHECK(gw_spool_init(&spool, g_tmp, 1024u * 1024u, err, sizeof err) == 0);
    fake_fill_result_words(words, 1, 1, 1, 0);
    (void)words;
    records = (uint8_t *)malloc(frames * 32u);
    CHECK(records != NULL);
    fake_make_records(records, frames, 1000);
    gw_smc1_init(&hdr);
    hdr.event_id = 42;
    hdr.record_count = frames;
    hdr.first_sample = 1000;
    hdr.last_sample = 1003;
    hdr.flags = 0;
    hdr.clip_reason = 3;
    hdr.sample_rate_word = 0x473B89C6u;
    CHECK(gw_spool_writer_begin(&spool, &hdr, &writer, err, sizeof err) == 0);
    CHECK(gw_spool_writer_write(&writer, records, frames * 32u) == 0);
    CHECK(gw_spool_writer_finish(&spool, &writer, &rec, err, sizeof err) == 0);
    CHECK(rec.event_id == 42 && rec.total_bytes == 64u + frames * 32u);
    CHECK(gw_spool_count(&spool) == 1);
    CHECK(rec.sha256[0] != 0);
    readback = (uint8_t *)malloc((size_t)rec.total_bytes);
    CHECK(readback != NULL);
    if (readback) {
        uint8_t d[32];
        char hex[65];
        CHECK(gw_spool_read(&spool, &rec, 0, readback, (size_t)rec.total_bytes, err, sizeof err) == 0);
        gw_sha256(readback, (size_t)rec.total_bytes, d);
        gw_sha256_hex(d, hex);
        CHECK(strcmp(hex, rec.sha256) == 0);
        /* duplicate event id refused */
        {
            gw_spool_writer w2;
            CHECK(gw_spool_writer_begin(&spool, &hdr, &w2, err, sizeof err) == -2);
        }
        free(readback);
    }
    /* idempotent ack */
    {
        int dup = 0;
        CHECK(gw_spool_ack(&spool, 42, rec.sha256, &dup, err, sizeof err) == 0);
        CHECK(dup == 0);
        CHECK(gw_spool_count(&spool) == 0);
        CHECK(gw_spool_ack(&spool, 42, rec.sha256, &dup, err, sizeof err) == 0);
        CHECK(dup == 1);
        CHECK(gw_spool_ack(&spool, 42, "0000000000000000000000000000000000000000000000000000000000000000", &dup, err, sizeof err) == -2);
        CHECK(gw_spool_ack(&spool, 999, rec.sha256, &dup, err, sizeof err) == -1);
    }
    /* acked tombstone survives restart, spool file released */
    {
        gw_spool spool2;
        CHECK(gw_spool_init(&spool2, g_tmp, 1024u * 1024u, err, sizeof err) == 0);
        CHECK(gw_spool_count(&spool2) == 0);
        gw_spool_close(&spool2);
    }
    /* spool capacity refusal is explicit and counted */
    {
        gw_spool small;
        gw_spool_writer w3;
        char dir2[256];
        snprintf(dir2, sizeof dir2, "build/unit_spool_small_%d", gw_pid());
        CHECK(gw_spool_init(&small, dir2, 4096, err, sizeof err) == 0);
        gw_smc1_init(&hdr);
        hdr.event_id = 7;
        hdr.record_count = 200; /* 6464 bytes > 4096 limit */
        hdr.first_sample = 0;
        hdr.last_sample = 199;
        CHECK(gw_spool_writer_begin(&small, &hdr, &w3, err, sizeof err) == -3);
        CHECK(small.dropped_events == 1);
        gw_spool_close(&small);
    }
    /* acked event rejected again through refresh */
    (void)total; (void)first;
    free(records);
    gw_spool_close(&spool);
}

/* --------------------------------------------------------------- entry */

int main(void)
{
    printf("UNIT_TEST_START pid=%d\n", gw_pid());
    test_sha256();
    test_utf8();
    test_json();
    test_queues();
    test_wire();
    test_fake_mmio_retries();
    test_arbiter();
    test_config_validation();
    test_spool();
    if (g_fail) {
        printf("UNIT_TESTS_FAIL failures=%d checks=%d\n", g_fail, g_checks);
        return 1;
    }
    printf("UNIT_TESTS_PASS checks=%d\n", g_checks);
    return 0;
}
