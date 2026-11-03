/* In-process host integration tests for the sixmic-analysis v1 PS gateway.
 * Real TCP loopback sockets, real SMA1 framing, real JSON-lines framing and a
 * deterministic protocol-3 fake-MMIO device model. NOT a physical board test. */
#include "fake_mmio.h"
#include "gateway.h"
#include "gw_util.h"
#include "sha256.h"
#include "json.h"
#include "sixmic_analysis_wire.h"
#include "test_client.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_fail;
static int g_checks;
static fake_env ENV;
static gw *G;
static test_client g_primary;
static char g_primary_token[33];

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

static uint64_t now_ms(void) { return gw_clock_ms(); }

static void pump_ms(uint64_t ms)
{
    uint64_t target = now_ms() + ms;
    while (now_ms() < target) {
        gw_test_clock_set(now_ms() + 1);
        gw_pump(G, 0);
    }
}

static void pump_n(int n)
{
    int i;
    for (i = 0; i < n; i++) { gw_test_clock_set(now_ms() + 1); gw_pump(G, 0); }
}

static int resp_ok(const char *resp)
{
    const char *st = test_status(resp);
    return st && strcmp(st, "ok") == 0;
}

static int resp_accepted(const char *resp)
{
    const char *st = test_status(resp);
    return st && strcmp(st, "accepted") == 0;
}

static int resp_error(const char *resp, const char *code)
{
    char got[48];
    if (test_error_code(resp, got, sizeof got) != 0) return 0;
    return strcmp(got, code) == 0;
}

static int build_words_args(char *out, size_t cap, const uint32_t words[32],
                            const char *token)
{
    int n = 0;
    unsigned i;
    n += snprintf(out + n, cap - (size_t)n, "{\"words\":[");
    for (i = 0; i < 32; i++)
        n += snprintf(out + n, cap - (size_t)n, "%s%u",
                      i ? "," : "", (unsigned)words[i]);
    n += snprintf(out + n, cap - (size_t)n, "]");
    if (token)
        n += snprintf(out + n, cap - (size_t)n,
                      ",\"controlToken\":\"%s\"", token);
    n += snprintf(out + n, cap - (size_t)n, "}");
    return n;
}

static int build_shadow_write_args(char *out, size_t cap,
                                   const uint32_t words[32], const char *token)
{
    int n = 0;
    unsigned i;
    n += snprintf(out + n, cap - (size_t)n, "{\"words\":[");
    for (i = 0; i < 32; i++)
        n += snprintf(out + n, cap - (size_t)n,
                      "%s{\"index\":%u,\"value\":%u}",
                      i ? "," : "", i, (unsigned)words[i]);
    n += snprintf(out + n, cap - (size_t)n, "]");
    if (token)
        n += snprintf(out + n, cap - (size_t)n,
                      ",\"controlToken\":\"%s\"", token);
    n += snprintf(out + n, cap - (size_t)n, "}");
    return n;
}

/* ==================================================== handshake and framing */

static void test_handshake(void)
{
    test_client c;
    char resp[GW_LINE_BYTES];
    char session[65], epoch[32];
    section("handshake");
    CHECK(test_client_open(G, &c, 0) == 0);
    /* partial frame: first half must not produce a response */
    {
        const char *part1 =
            "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
            "\"requestId\":\"hello-part\",\"op\":\"hello\",\"args\":"
            "{\"clientName\":\"partial-tester\"";
        const char *part2 = ",\"maxBinaryPayloadBytes\":1048576}}\n";
        char early[64];
        CHECK(test_client_send(G, &c, part1, strlen(part1)) == 0);
        pump_n(3);
        CHECK(test_client_line(G, &c, early, sizeof early, 3) == -1);
        CHECK(test_client_send(G, &c, part2, strlen(part2)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(resp_ok(resp));
    }
    CHECK(test_json_path_str(resp, "result.sessionId", session, sizeof session) == 0);
    CHECK(test_json_path_str(resp, "result.connectionEpoch", epoch, sizeof epoch) == 0);
    snprintf(c.session_id, sizeof c.session_id, "%s", session);
    c.epoch = strtoull(epoch, NULL, 10);
    {
        char buf[64];
        CHECK(test_json_path_str(resp, "result.capabilities.device.livePcm",
                                 buf, sizeof buf) == 0 && strcmp(buf, "false") == 0);
        CHECK(test_json_path_str(resp, "result.capabilities.device.liveResults",
                                 buf, sizeof buf) == 0 && strcmp(buf, "false") == 0);
        CHECK(test_json_path_str(resp, "result.capabilities.device.configCommit",
                                 buf, sizeof buf) == 0 && strcmp(buf, "true") == 0);
        CHECK(test_json_path_str(resp, "result.capabilities.device.protocol3",
                                 buf, sizeof buf) == 0 && strcmp(buf, "true") == 0);
        CHECK(test_json_path_str(resp, "result.capabilities.device.resultSnapshot",
                                 buf, sizeof buf) == 0 && strcmp(buf, "fixture") == 0);
        CHECK(test_json_path_str(resp, "result.capabilities.gateway.mockFixture",
                                 buf, sizeof buf) == 0 && strcmp(buf, "true") == 0);
        CHECK(test_json_path_u32(resp, "result.limits.maxLineBytes",
                                 &(uint32_t){0}) == 0);
    }
    /* capabilities.get + status.get */
    CHECK(test_req(G, &c, "capabilities.get", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_u32(resp, "result.device.configVersion",
                             &(uint32_t){0}) == 0);
    CHECK(test_req(G, &c, "status.get", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char st[32], sid[65];
        CHECK(test_json_path_str(resp, "result.deviceState", st, sizeof st) == 0);
        CHECK(strcmp(st, "ready") == 0);
        CHECK(test_json_path_str(resp, "result.sessionId", sid, sizeof sid) == 0);
        CHECK(strcmp(sid, session) == 0);
        CHECK(test_json_path_u32(resp, "result.queues.eventSpoolLimitBytes",
                                 &(uint32_t){0}) == 0);
    }
    /* sticky frames: two requests in one write */
    {
        char two[1024];
        char rid[64];
        snprintf(two, sizeof two,
                 "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                 "\"requestId\":\"sticky-1\",\"sessionId\":\"%s\","
                 "\"op\":\"heartbeat\",\"args\":{}}\n"
                 "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                 "\"requestId\":\"sticky-2\",\"sessionId\":\"%s\","
                 "\"op\":\"no.such.op\",\"args\":{}}\n",
                 session, session);
        CHECK(test_client_send(G, &c, two, strlen(two)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(test_json_path_str(resp, "requestId", rid, sizeof rid) == 0);
        CHECK(strcmp(rid, "sticky-1") == 0);
        CHECK(resp_ok(resp));
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(test_json_path_str(resp, "requestId", rid, sizeof rid) == 0);
        CHECK(strcmp(rid, "sticky-2") == 0);
        CHECK(resp_error(resp, "unknown_op"));
    }
    /* empty lines are ignored (counted, not an error) */
    CHECK(test_client_send(G, &c, "\n\n", 2) == 0);
    CHECK(test_req(G, &c, "heartbeat", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    /* CR is not a legal terminator: bad_json but connection survives */
    {
        char bad[256];
        snprintf(bad, sizeof bad,
                 "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                 "\"requestId\":\"cr-1\",\"sessionId\":\"%s\","
                 "\"op\":\"heartbeat\",\"args\":{}}\r\n", session);
        CHECK(test_client_send(G, &c, bad, strlen(bad)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(resp_error(resp, "bad_json"));
        CHECK(test_req(G, &c, "heartbeat", "{}", resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
    }
    /* plain bad JSON keeps the connection */
    CHECK(test_client_send(G, &c, "not-json\n", 9) == 0);
    CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
    CHECK(resp_error(resp, "bad_json"));
    /* duplicate keys rejected */
    {
        const char *dup =
            "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
            "\"requestId\":\"dk\",\"requestId\":\"dk2\",\"sessionId\":\"x\","
            "\"op\":\"heartbeat\",\"args\":{}}\n";
        CHECK(test_client_send(G, &c, dup, strlen(dup)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(resp_error(resp, "bad_json"));
    }
    /* unknown session */
    {
        char badsid[512];
        snprintf(badsid, sizeof badsid,
                 "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                 "\"requestId\":\"bad-sess\",\"sessionId\":\"sess-wrong\","
                 "\"op\":\"heartbeat\",\"args\":{}}\n");
        CHECK(test_client_send(G, &c, badsid, strlen(badsid)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 100) > 0);
        CHECK(resp_error(resp, "unknown_session"));
    }
    /* duplicate requestId returns the first response verbatim */
    {
        char first[GW_LINE_BYTES], second[GW_LINE_BYTES];
        CHECK(test_req_id(G, &c, "dup-1", "heartbeat", "{}", first, sizeof first) == 0);
        CHECK(resp_ok(first));
        CHECK(test_req_id(G, &c, "dup-1", "heartbeat", "{}", second, sizeof second) == 0);
        CHECK(strcmp(first, second) == 0);
        CHECK(G->stats.duplicate_requests >= 1u);
    }
    test_client_close(G, &c);

    /* unauthenticated request on a fresh connection */
    {
        test_client c2;
        CHECK(test_client_open(G, &c2, 0) == 0);
        CHECK(test_client_send(G, &c2,
              "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
              "\"requestId\":\"prehello\",\"op\":\"status.get\",\"args\":{}}\n",
              110) == 0);
        CHECK(test_client_line(G, &c2, resp, sizeof resp, 100) > 0);
        CHECK(resp_error(resp, "not_authenticated"));
        test_client_close(G, &c2);
    }
}

/* ===================================================== fatal framing errors */

static void test_fatal_frames(void)
{
    char resp[GW_LINE_BYTES];
    section("fatal_framing");
    /* oversize line -> line_too_long then close */
    {
        test_client c;
        char *big = (char *)malloc(70000);
        CHECK(big != NULL);
        if (big) {
            memset(big, 'a', 70000);
            big[69999] = '\n';
            CHECK(test_client_open(G, &c, 0) == 0);
            CHECK(test_client_send(G, &c, big, 70000) == 0);
            CHECK(test_client_line(G, &c, resp, sizeof resp, 200) > 0);
            CHECK(resp_error(resp, "line_too_long"));
            CHECK(test_client_line(G, &c, resp, sizeof resp, 200) == 0);
            test_client_close(G, &c);
            free(big);
        }
    }
    /* invalid UTF-8 -> bad_utf8 then close */
    {
        test_client c;
        char frame[256];
        int n;
        CHECK(test_client_open(G, &c, 0) == 0);
        n = snprintf(frame, sizeof frame,
                     "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                     "\"requestId\":\"u8\",\"op\":\"hello\",\"args\":"
                     "{\"clientName\":\"");
        frame[n++] = (char)0xC0;
        frame[n++] = (char)0xAF;
        frame[n++] = '"';
        frame[n++] = '}';
        frame[n++] = '}';
        frame[n++] = '\n';
        CHECK(test_client_send(G, &c, frame, (size_t)n) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) > 0);
        CHECK(resp_error(resp, "bad_utf8"));
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) == 0);
        test_client_close(G, &c);
    }
    /* protocol mismatch -> close */
    {
        const char *bad =
            "{\"protocol\":\"other-protocol\",\"version\":1,"
            "\"requestId\":\"pm\",\"op\":\"hello\",\"args\":{}}\n";
        test_client c;
        CHECK(test_client_open(G, &c, 0) == 0);
        CHECK(test_client_send(G, &c, bad, strlen(bad)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) > 0);
        CHECK(resp_error(resp, "protocol_mismatch"));
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) == 0);
        test_client_close(G, &c);
    }
    /* unsupported version keeps the connection */
    {
        test_client c;
        char frame[512];
        CHECK(test_client_open(G, &c, 0) == 0);
        CHECK(test_hello(G, &c, "version-tester") == 0);
        snprintf(frame, sizeof frame,
                 "{\"protocol\":\"sixmic-analysis\",\"version\":2,"
                 "\"requestId\":\"v2\",\"sessionId\":\"%s\","
                 "\"op\":\"heartbeat\",\"args\":{}}\n", c.session_id);
        CHECK(test_client_send(G, &c, frame, strlen(frame)) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) > 0);
        CHECK(resp_error(resp, "unsupported_version"));
        CHECK(test_req(G, &c, "heartbeat", "{}", resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
        test_client_close(G, &c);
    }
    /* deep JSON -> bad_json on an authenticated connection */
    {
        test_client c;
        char frame[2048];
        int n = 0, i;
        CHECK(test_client_open(G, &c, 0) == 0);
        CHECK(test_hello(G, &c, "depth-tester") == 0);
        n += snprintf(frame + n, sizeof frame - (size_t)n,
                      "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                      "\"requestId\":\"deep\",\"sessionId\":\"%s\","
                      "\"op\":\"heartbeat\",\"args\":{\"x\":",
                      c.session_id);
        for (i = 0; i < 40; i++) frame[n++] = '[';
        for (i = 0; i < 40; i++) frame[n++] = ']';
        n += snprintf(frame + n, sizeof frame - (size_t)n, "}}\n");
        CHECK(test_client_send(G, &c, frame, (size_t)n) == 0);
        CHECK(test_client_line(G, &c, resp, sizeof resp, 200) > 0);
        CHECK(resp_error(resp, "bad_json"));
        CHECK(test_req(G, &c, "heartbeat", "{}", resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
        test_client_close(G, &c);
    }
}

/* ======================================================== control lease */

static void test_control_lease(void)
{
    test_client pc, sc, dc;
    char resp[GW_LINE_BYTES];
    char token[33] = {0};
    section("control_lease");
    CHECK(test_client_open(G, &pc, 0) == 0);
    CHECK(test_hello(G, &pc, "primary-tester") == 0);
    pc.req_seq = 100;
    /* first claim */
    CHECK(test_req(G, &pc, "control.claim", "{\"leaseSeconds\":10}",
                   resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_str(resp, "result.controlToken", token, sizeof token) == 0);
    CHECK(strlen(token) == 32);
    CHECK(test_json_path_u32(resp, "result.expiresInMs", &(uint32_t){0}) == 0);
    /* duplicate requestId returns the first response verbatim (here: a
     * control_conflict because we already hold the lease) */
    {
        char again[GW_LINE_BYTES];
        CHECK(test_req_id(G, &pc, "claim-once", "control.claim",
                          "{\"leaseSeconds\":10}", resp, sizeof resp) == 0);
        CHECK(resp_error(resp, "control_conflict"));
        CHECK(test_req_id(G, &pc, "claim-once", "control.claim",
                          "{\"leaseSeconds\":10}", again, sizeof again) == 0);
        CHECK(strcmp(resp, again) == 0);
    }
    /* second controller gets control_conflict with holder info */
    CHECK(test_client_open(G, &sc, 0) == 0);
    CHECK(test_hello(G, &sc, "second-tester") == 0);
    CHECK(test_req(G, &sc, "control.claim", "{\"leaseSeconds\":10}",
                   resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "control_conflict"));
    CHECK(strstr(resp, "primary-tester") != NULL);
    CHECK(strstr(resp, token) == NULL); /* never leak the token */
    /* write without a token is refused */
    {
        char args[4096];
        uint32_t words[32];
        fake_fill_config(words, 1, 1);
        build_shadow_write_args(args, sizeof args, words,
                                "00000000000000000000000000000000");
        CHECK(test_req(G, &pc, "config.write", args, resp, sizeof resp) == 0);
        CHECK(resp_error(resp, "bad_token"));
    }
    /* renew semantics */
    CHECK(test_req(G, &pc, "control.renew",
                   "{\"controlToken\":\"00000000000000000000000000000000\"}",
                   resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "bad_token"));
    {
        char args[128];
        snprintf(args, sizeof args, "{\"controlToken\":\"%s\"}", token);
        CHECK(test_req(G, &pc, "control.renew", args, resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
    }
    /* lease expiry releases the controller; accepted work would drain first */
    gw_test_clock_set(now_ms() + 10000);
    pump_n(4);
    CHECK(test_req(G, &sc, "control.claim", "{\"leaseSeconds\":30}",
                   resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char t2[33];
        CHECK(test_json_path_str(resp, "result.controlToken", t2, sizeof t2) == 0);
        {
            char args[128];
            snprintf(args, sizeof args, "{\"controlToken\":\"%s\"}", t2);
            CHECK(test_req(G, &sc, "control.release", args, resp, sizeof resp) == 0);
            CHECK(resp_ok(resp));
        }
    }
    /* primary re-claims, then a disconnect releases control */
    CHECK(test_req_id(G, &pc, "claim-2", "control.claim", "{\"leaseSeconds\":300}",
                      resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_str(resp, "result.controlToken", token, sizeof token) == 0);
    CHECK(test_client_open(G, &dc, 0) == 0);
    CHECK(test_hello(G, &dc, "disconnect-tester") == 0);
    CHECK(test_req(G, &dc, "control.claim", "{\"leaseSeconds\":300}",
                   resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "control_conflict"));
    test_client_close(G, &pc);
    pump_n(5);
    CHECK(test_req(G, &dc, "control.claim", "{\"leaseSeconds\":300}",
                   resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_str(resp, "result.controlToken", token, sizeof token) == 0);
    test_client_close(G, &sc);
    /* keep a fresh primary for the remaining sections */
    CHECK(test_client_open(G, &pc, 0) == 0);
    CHECK(test_hello(G, &pc, "primary-tester") == 0);
    pc.req_seq = 200;
    {
        char args[128];
        snprintf(args, sizeof args, "{\"controlToken\":\"%s\"}", token);
        CHECK(test_req(G, &pc, "control.release", args, resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
    }
    CHECK(test_req_id(G, &pc, "claim-3", "control.claim", "{\"leaseSeconds\":300}",
                      resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_str(resp, "result.controlToken", token, sizeof token) == 0);
    /* expose the primary/token through globals used by later sections */
    g_primary = pc;
    snprintf(g_primary_token, sizeof g_primary_token, "%s", token);
    test_client_close(G, &dc);
}

/* ==================================================================== config */

static uint64_t g_epoch;

static int primary_req(const char *op, const char *args, char *resp, size_t cap)
{
    return test_req(G, &g_primary, op, args, resp, cap);
}

static int primary_req_id(const char *rid, const char *op, const char *args,
                          char *resp, size_t cap)
{
    return test_req_id(G, &g_primary, rid, op, args, resp, cap);
}

static void test_config(void)
{
    char resp[GW_LINE_BYTES];
    char args[8192];
    char job_id[32];
    uint32_t words[32];
    uint32_t v = 0;
    section("config_shadow_commit");
    CHECK(primary_req("config.read", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(test_json_path_u32(resp, "result.activeVersion", &v) == 0 && v == 0);
    fake_fill_config(words, 1, 1);
    build_shadow_write_args(args, sizeof args, words, g_primary_token);
    CHECK(primary_req("config.write", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char dirty[16];
        CHECK(test_json_path_str(resp, "result.shadowDirty", dirty, sizeof dirty) == 0);
        CHECK(strcmp(dirty, "true") == 0);
    }
    /* commit version 1 from the staged shadow */
    snprintf(args, sizeof args, "{\"version\":1,\"controlToken\":\"%s\"}",
             g_primary_token);
    CHECK(primary_req_id("commit-1", "config.commit", args, resp, sizeof resp) == 0);
    CHECK(resp_accepted(resp));
    CHECK(test_json_path_str(resp, "result.jobId", job_id, sizeof job_id) == 0);
    pump_ms(20);
    {
        char ev[GW_LINE_BYTES];
        CHECK(test_wait_event(G, &g_primary, "configApplied",
                              "\"version\":1", 300, ev, sizeof ev) == 0);
        {
            char applied[16];
            CHECK(test_json_path_str(ev, "data.applied", applied, sizeof applied) == 0);
            CHECK(strcmp(applied, "true") == 0);
        }
    }
    {
        char jargs[128];
        char state[24];
        snprintf(jargs, sizeof jargs, "{\"jobId\":\"%s\"}", job_id);
        CHECK(primary_req("job.get", jargs, resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
        CHECK(test_json_path_str(resp, "result.state", state, sizeof state) == 0);
        CHECK(strcmp(state, "completed") == 0);
    }
    CHECK(primary_req("config.read", "{}", resp, sizeof resp) == 0);
    CHECK(test_json_path_u32(resp, "result.activeVersion", &v) == 0 && v == 1);
    {
        char known[16];
        uint32_t b0 = 0;
        CHECK(test_json_path_str(resp, "result.activeWordsKnown", known, sizeof known) == 0);
        CHECK(strcmp(known, "true") == 0);
        CHECK(test_json_path_u32(resp, "result.active.9", &b0) == 0);
        CHECK(b0 == 0x12000000u);
    }
    /* duplicate active version rejected */
    CHECK(primary_req_id("commit-dup", "config.commit",
                         "{\"version\":1,\"controlToken\":\"x\"}",
                         resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "bad_token"));
    snprintf(args, sizeof args, "{\"version\":1,\"controlToken\":\"%s\"}",
             g_primary_token);
    CHECK(primary_req_id("commit-dup2", "config.commit", args, resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "rejected"));
    CHECK(strstr(resp, "version") != NULL);
    /* version 0 is bad_args */
    CHECK(primary_req_id("commit-zero", "config.commit",
                         "{\"version\":0,\"controlToken\":\"x\"}",
                         resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "bad_token"));
    snprintf(args, sizeof args, "{\"version\":0,\"controlToken\":\"%s\"}",
             g_primary_token);
    CHECK(primary_req_id("commit-zero2", "config.commit", args, resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "bad_args"));
    /* PL rejection is surfaced as configApplied rejected + failed job */
    mock_mmio_set_reject_next_commit(ENV.mmio, 1);
    fake_fill_config(words, 1, 2);
    build_words_args(args, sizeof args, words, g_primary_token);
    {
        char withver[9000];
        snprintf(withver, sizeof withver, "{\"version\":2,%s", args + 1);
        CHECK(primary_req_id("commit-2", "config.commit", withver,
                             resp, sizeof resp) == 0);
    }
    CHECK(resp_accepted(resp));
    pump_ms(20);
    {
        char ev[GW_LINE_BYTES];
        CHECK(test_wait_event(G, &g_primary, "configApplied",
                              "\"version\":2", 300, ev, sizeof ev) == 0);
        {
            char rejected[16];
            CHECK(test_json_path_str(ev, "data.rejected", rejected,
                                     sizeof rejected) == 0);
            CHECK(strcmp(rejected, "true") == 0);
        }
    }
    CHECK(primary_req("config.read", "{}", resp, sizeof resp) == 0);
    CHECK(test_json_path_u32(resp, "result.activeVersion", &v) == 0 && v == 1);
    /* a fresh unique version still applies after a rejection */
    fake_fill_config(words, 1, 3);
    build_words_args(args, sizeof args, words, g_primary_token);
    {
        char withver[9000];
        snprintf(withver, sizeof withver, "{\"version\":3,%s", args + 1);
        CHECK(primary_req_id("commit-3", "config.commit", withver,
                             resp, sizeof resp) == 0);
    }
    CHECK(resp_accepted(resp));
    pump_ms(20);
    {
        char ev[GW_LINE_BYTES];
        CHECK(test_wait_event(G, &g_primary, "configApplied",
                              "\"version\":3", 300, ev, sizeof ev) == 0);
    }
    CHECK(primary_req("config.read", "{}", resp, sizeof resp) == 0);
    CHECK(test_json_path_u32(resp, "result.activeVersion", &v) == 0 && v == 3);
    snprintf(args, sizeof args, "{\"controlToken\":\"%s\"}", g_primary_token);
    CHECK(primary_req("config.abort", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
}

/* ========================================================= binary streams */

static int bin_hello(gw *g, test_client *bc, const char *token, uint64_t epoch,
                     uint32_t max_payload, test_frame *ack)
{
    char payload[512];
    char ep[24];
    int n;
    gw_u64_dec(epoch, ep);
    snprintf(payload, sizeof payload,
             "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
             "\"connectionEpoch\":\"%s\",\"token\":\"%s\","
             "\"maxPayloadBytes\":%u}",
             ep, token, (unsigned)max_payload);
    n = (int)strlen(payload);
    if (test_bin_send_frame(g, bc, SMA_MSG_HELLO, 0, 0, epoch, 0,
                            payload, (uint32_t)n, 0) != 0) return -1;
    if (test_bin_read_frame(g, bc, ack, 300) != 0) return -1;
    if (ack->h.message_type != SMA_MSG_HELLO_ACK) {
        fprintf(stderr, "BIN_HELLO_UNEXPECTED type=0x%04x\n",
                (unsigned)ack->h.message_type);
        return -1;
    }
    return 0;
}

static int bin_read_type(gw *g, test_client *bc, uint16_t type, test_frame *f,
                         int max_rounds)
{
    int r;
    for (r = 0; r < max_rounds; r++) {
        int rc = test_bin_read_frame(g, bc, f, 20);
        if (rc != 0) { gw_pump(g, 0); gw_sleep_ms(1); continue; }
        if (f->h.message_type == type) return 0;
        if (f->h.message_type == SMA_MSG_ERROR || f->h.message_type == SMA_MSG_BYE)
            return -2;
        if (f->h.message_type == SMA_MSG_HEARTBEAT) continue;
        f->h.message_type = f->h.message_type; /* keep scanning */
    }
    return -1;
}

static int open_stream_for(gw *g, const char *subscribe_args, char *token,
                           uint32_t *port, char *schema_sha, size_t shacap,
                           uint32_t *stream_id)
{
    char resp[GW_LINE_BYTES];
    char args[512];
    char sub[40];
    if (test_req(g, &g_primary, "subscribe", subscribe_args, resp, sizeof resp) != 0)
        return -1;
    if (!resp_ok(resp)) { fprintf(stderr, "SUBSCRIBE_FAILED %s\n", resp); return -1; }
    if (test_json_path_str(resp, "result.subscriptionId", sub, sizeof sub) != 0)
        return -1;
    if (test_json_path_str(resp, "result.streams.0.schemaSha256", schema_sha,
                           shacap) != 0)
        return -1;
    if (test_json_path_u32(resp, "result.streams.0.streamId", stream_id) != 0)
        return -1;
    snprintf(args, sizeof args, "{\"subscriptionId\":\"%s\"}", sub);
    if (test_req(g, &g_primary, "stream.open", args, resp, sizeof resp) != 0)
        return -1;
    if (!resp_ok(resp)) { fprintf(stderr, "STREAM_OPEN_FAILED %s\n", resp); return -1; }
    if (test_json_path_str(resp, "result.binaryToken", token, 33) != 0)
        return -1;
    return test_json_path_u32(resp, "result.port", port);
}

static void test_result_words_stream(void)
{
    char token[33], schema_sha[80];
    uint32_t stream_id = 0, port = 0;
    uint32_t words[32];
    test_client bc;
    test_frame f;
    section("binary_result_words32");
    fake_fill_result_words(words, 100, 3, 1, 5000);
    mock_mmio_set_result_words(ENV.mmio, words);
    pump_ms(10);
    CHECK(open_stream_for(G, "{\"streams\":[{\"type\":\"resultWords\"}]}",
                          token, &port, schema_sha, sizeof schema_sha,
                          &stream_id) == 0);
    CHECK(port == G->bin_bound_port);
    CHECK(test_client_open(G, &bc, 1) == 0);
    CHECK(bin_hello(G, &bc, token, g_epoch, 1048576, &f) == 0);
    {
        char accepted[16], buf[128];
        CHECK(test_json_path_str((const char *)f.payload, "accepted",
                                 accepted, sizeof accepted) == 0);
        CHECK(strcmp(accepted, "true") == 0);
        CHECK(test_json_path_str((const char *)f.payload, "connectionEpoch",
                                 buf, sizeof buf) == 0);
        CHECK(strtoull(buf, NULL, 10) == g_epoch);
        {
            uint32_t negotiated = 0;
            CHECK(test_json_path_u32((const char *)f.payload,
                                     "maxPayloadBytes", &negotiated) == 0);
            CHECK(negotiated == 1048576u);
        }
    }
    /* schema must arrive before any data and match the subscribe hash */
    {
        uint8_t digest[32];
        char hex[65];
        CHECK(bin_read_type(G, &bc, SMA_MSG_STREAM_SCHEMA, &f, 100) == 0);
        CHECK(f.h.stream_id == stream_id);
        CHECK(f.h.sequence == 0);
        CHECK(strstr((const char *)f.payload, "\"streamType\":\"resultWords32\"") != NULL);
        CHECK(strstr((const char *)f.payload, "\"sourceKind\":\"test-fixture\"") != NULL);
        CHECK(strstr((const char *)f.payload, "\"simulated\":true") != NULL);
        CHECK(strstr((const char *)f.payload, "\"wordMap\"") != NULL);
        gw_sha256(f.payload, f.h.payload_bytes, digest);
        gw_sha256_hex(digest, hex);
        CHECK(strcmp(hex, schema_sha) == 0);
    }
    /* publish a fresh snapshot and verify framing */
    fake_fill_result_words(words, 101, 3, 1, 5050);
    mock_mmio_set_result_words(ENV.mmio, words);
    pump_ms(10);
    CHECK(bin_read_type(G, &bc, SMA_MSG_RESULT_WORDS32, &f, 200) == 0);
    CHECK(f.h.payload_bytes == SMA_RESULT_PAYLOAD_BYTES);
    CHECK(f.h.stream_id == stream_id);
    CHECK(f.h.connection_epoch == g_epoch);
    CHECK((f.h.flags & SMA_FLAG_CRC32_VALID) != 0);
    CHECK(sma_crc32(f.payload, 128) == f.h.payload_crc32);
    CHECK(f.h.frame_id == 101);
    CHECK(f.h.config_version == 3);
    CHECK(f.h.sequence == 1);
    {
        unsigned i;
        int match = 1;
        for (i = 0; i < 32; i++)
            if (sma_get_u32(f.payload + i * 4u) != words[i]) match = 0;
        CHECK(match == 1);
    }
    CHECK(gw_result_header_matches(f.h.frame_id, f.h.config_version,
                                   (const uint32_t *)0) == -1);
    test_client_close(G, &bc);

    /* unknown binary message type is skipped in bounded fashion, connection lives */
    {
        test_client bc2;
        char token2[33], sha2[80];
        uint32_t sid2 = 0, port2 = 0;
        uint8_t junk[16];
        memset(junk, 0xAB, sizeof junk);
        CHECK(open_stream_for(G, "{\"streams\":[{\"type\":\"resultWords\"}]}",
                              token2, &port2, sha2, sizeof sha2, &sid2) == 0);
        CHECK(test_client_open(G, &bc2, 1) == 0);
        CHECK(test_bin_send_frame(G, &bc2, 0x7777u, 0, 0, g_epoch, 0,
                                  junk, sizeof junk, 0) == 0);
        CHECK(bin_hello(G, &bc2, token2, g_epoch, 1048576, &f) == 0);
        pump_n(3);
        CHECK(G->stats.binary_unknown_frames >= 1u);
        test_client_close(G, &bc2);
    }
    /* bad payload CRC terminates the connection */
    {
        test_client bc3;
        char token3[33], sha3[80];
        uint32_t sid3 = 0, port3 = 0;
        char hello_payload[256];
        CHECK(open_stream_for(G, "{\"streams\":[{\"type\":\"resultWords\"}]}",
                              token3, &port3, sha3, sizeof sha3, &sid3) == 0);
        CHECK(test_client_open(G, &bc3, 1) == 0);
        {
            char ep[24];
            gw_u64_dec(g_epoch, ep);
            snprintf(hello_payload, sizeof hello_payload,
                     "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                     "\"connectionEpoch\":\"%s\",\"token\":\"%s\","
                     "\"maxPayloadBytes\":1048576}", ep, token3);
        }
        CHECK(test_bin_send_frame(G, &bc3, SMA_MSG_HELLO, 0, 0, g_epoch, 0,
                                  hello_payload, (uint32_t)strlen(hello_payload),
                                  1) == 0);
        CHECK(bin_read_type(G, &bc3, SMA_MSG_ERROR, &f, 300) == 0);
        {
            char code[32];
            CHECK(test_json_path_str((const char *)f.payload, "code",
                                     code, sizeof code) == 0);
            CHECK(strcmp(code, "bad_crc") == 0);
        }
        pump_n(10);
        CHECK(test_bin_read_frame(G, &bc3, &f, 5) == -1);
        test_client_close(G, &bc3);
    }
}

/* ======================================================== service snapshot */

static void test_service_snapshot(void)
{
    char token[33], schema_sha[80];
    uint32_t stream_id = 0, port = 0;
    uint32_t words[32], hdr[16], data[8];
    test_client bc;
    test_frame f;
    unsigned i;
    section("binary_service_snapshot");
    fake_fill_service_header(hdr, 1, 3, 8, 1);
    for (i = 0; i < 8; i++) data[i] = 200u + i;
    mock_mmio_set_service(ENV.mmio, G->cfg.service_snapshot_addr, hdr, data, 8);
    fake_fill_result_words(words, 102, 3, 1, 5100);
    mock_mmio_set_result_words(ENV.mmio, words);
    pump_ms(10);
    CHECK(open_stream_for(G, "{\"streams\":[{\"type\":\"serviceSnapshot\"}]}",
                          token, &port, schema_sha, sizeof schema_sha,
                          &stream_id) == 0);
    CHECK(test_client_open(G, &bc, 1) == 0);
    CHECK(bin_hello(G, &bc, token, g_epoch, 1048576, &f) == 0);
    CHECK(bin_read_type(G, &bc, SMA_MSG_STREAM_SCHEMA, &f, 100) == 0);
    CHECK(strstr((const char *)f.payload, "\"streamType\":\"serviceSnapshot\"") != NULL);
    CHECK(strstr((const char *)f.payload, "\"headerMap\"") != NULL);
    {
        uint8_t digest[32];
        char hex[65];
        gw_sha256(f.payload, f.h.payload_bytes, digest);
        gw_sha256_hex(digest, hex);
        CHECK(strcmp(hex, schema_sha) == 0);
    }
    pump_ms(10);
    CHECK(bin_read_type(G, &bc, SMA_MSG_SERVICE_SNAPSHOT, &f, 300) == 0);
    CHECK(f.h.payload_bytes == 64u + 8u * 4u);
    CHECK(f.h.stream_id == stream_id);
    CHECK(sma_get_u32(f.payload) == 0x52534C54u);
    CHECK(sma_get_u32(f.payload + 4) == 7u);       /* commitSequence */
    CHECK(sma_get_u32(f.payload + 8) == 1u);       /* session */
    CHECK(sma_get_u32(f.payload + 12) == 3u);      /* config */
    CHECK(sma_get_u32(f.payload + 40) == 8u);      /* length */
    CHECK(sma_get_u32(f.payload + 56) == 1u);      /* done */
    CHECK(sma_get_u32(f.payload + 64) == 200u);
    CHECK(sma_get_u32(f.payload + 64 + 28) == 207u);
    {
        uint64_t retries_before, ok_before;
        /* drain periodically published snapshots before testing rejection */
        {
            int drain;
            for (drain = 0; drain < 100; drain++) {
                if (test_bin_read_frame(G, &bc, &f, 20) != 0) {
                    gw_pump(G, 0);
                    if (drain > 5) break;
                    continue;
                }
            }
        }
        retries_before = G->stats.service_snapshot_retries;
        ok_before = G->stats.service_snapshots_ok;
        /* header that changes between the before/after copies must be rejected:
         * no new snapshot may be accepted/published while the header flips. */
        mock_mmio_set_service_flip(ENV.mmio, 2);
        pump_ms(30);
        CHECK(G->stats.service_snapshot_retries > retries_before);
        CHECK(G->stats.service_snapshots_ok == ok_before);
        mock_mmio_set_service_flip(ENV.mmio, 0);
        {
            int got = 0;
            int attempt;
            for (attempt = 0; attempt < 200 && !got; attempt++) {
                if (test_bin_read_frame(G, &bc, &f, 20) == 0) {
                    if (f.h.message_type == SMA_MSG_SERVICE_SNAPSHOT) got = 1;
                    continue;
                }
                pump_ms(2);
            }
            CHECK(got == 1);
        }
        CHECK(G->stats.service_snapshots_ok > ok_before);
    }
    test_client_close(G, &bc);
}

/* ================================================================== events */

static void test_events(void)
{
    char resp[GW_LINE_BYTES];
    char args[1024];
    char ev[GW_LINE_BYTES];
    char sha[80];
    uint32_t words[32], clip[16], stream_id = 0;
    uint8_t records[4 * 32];
    test_client bc;
    test_frame f;
    section("events_spool_download");
    fake_fill_result_words(words, 103, 3, 1, 5200);
    mock_mmio_set_result_words(ENV.mmio, words);
    pump_ms(10);
    CHECK(primary_req("subscribe", "{\"streams\":[{\"type\":\"events\"}]}",
                      resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    fake_fill_clip_words(clip, 5001, 0x12000000u, 4, 1000, 1, 3);
    fake_make_records(records, 4, 1000);
    CHECK(mock_mmio_inject_clip(ENV.mmio, 0, clip, records, sizeof records) == 0);
    pump_ms(20);
    CHECK(mock_mmio_clip_mask(ENV.mmio) == 0);
    CHECK(mock_mmio_clip_released_count(ENV.mmio) == 1);
    CHECK(G->stats.events_captured >= 1u);
    CHECK(test_wait_event(G, &g_primary, "eventAdded", "\"eventId\":\"5001\"",
                          300, ev, sizeof ev) == 0);
    CHECK(strstr(ev, "test-fixture") != NULL);
    CHECK(primary_req("event.list", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char eid[16];
        CHECK(test_json_path_str(resp, "result.events.0.eventId", eid, sizeof eid) == 0);
        CHECK(strcmp(eid, "5001") == 0);
    }
    CHECK(test_json_path_str(resp, "result.events.0.sha256", sha, sizeof sha) == 0);
    {
        char total[32];
        CHECK(test_json_path_str(resp, "result.events.0.totalBytes",
                                 total, sizeof total) == 0);
        CHECK(strcmp(total, "192") == 0);
    }
    snprintf(args, sizeof args, "{\"eventId\":\"5001\"}");
    CHECK(primary_req("event.get", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char got[80];
        CHECK(test_json_path_str(resp, "result.file.sha256", got, sizeof got) == 0);
        CHECK(strcmp(got, sha) == 0);
    }
    snprintf(args, sizeof args, "{\"eventId\":\"5001\",\"maxBytes\":64}");
    CHECK(primary_req("event.download", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        uint32_t chunk = 0;
        char total[32], off[16], tkn[33], ssha[80];
        char oargs[512];
        test_frame ack;
        uint8_t assembled[512];
        size_t assembled_len = 0;
        int chunks = 0, got_first = 0, got_last = 0;
        CHECK(test_json_path_u32(resp, "result.streamId", &stream_id) == 0);
        CHECK(test_json_path_u32(resp, "result.chunkBytes", &chunk) == 0);
        CHECK(chunk == 64u);
        CHECK(test_json_path_str(resp, "result.totalBytes", total, sizeof total) == 0);
        CHECK(strcmp(total, "192") == 0);
        CHECK(test_json_path_str(resp, "result.offset", off, sizeof off) == 0);
        CHECK(strcmp(off, "0") == 0);
        snprintf(oargs, sizeof oargs, "{\"eventId\":\"5001\"}");
        CHECK(test_req(G, &g_primary, "stream.open", oargs, resp, sizeof resp) == 0);
        CHECK(resp_ok(resp));
        CHECK(test_json_path_str(resp, "result.binaryToken", tkn, sizeof tkn) == 0);
        CHECK(test_json_path_str(resp, "result.streams.0.schemaSha256",
                                 ssha, sizeof ssha) == 0);
        CHECK(test_json_path_u32(resp, "result.streamId", &stream_id) == 0);
        CHECK(test_client_open(G, &bc, 1) == 0);
        CHECK(bin_hello(G, &bc, tkn, g_epoch, 1048576, &ack) == 0);
        CHECK(bin_read_type(G, &bc, SMA_MSG_STREAM_SCHEMA, &f, 100) == 0);
        CHECK(strstr((const char *)f.payload, "\"streamType\":\"eventFile\"") != NULL);
        CHECK(strstr((const char *)f.payload, "\"eventId\":\"5001\"") != NULL);
        CHECK(strstr((const char *)f.payload, "\"totalBytes\":\"192\"") != NULL);
        {
            uint8_t digest[32];
            char hex[65];
            gw_sha256(f.payload, f.h.payload_bytes, digest);
            gw_sha256_hex(digest, hex);
            CHECK(strcmp(hex, ssha) == 0);
        }
        pump_ms(20);
        {
            int r;
            for (r = 0; r < 20; r++) {
                if (test_bin_read_frame(G, &bc, &f, 5) != 0) { gw_pump(G, 0); continue; }
                if (f.h.message_type != SMA_MSG_EVENT_FILE_CHUNK) continue;
                if (chunks == 0) {
                    CHECK((f.h.flags & SMA_FLAG_FIRST_CHUNK) != 0);
                    got_first = 1;
                }
                CHECK(f.h.stream_id == stream_id);
                CHECK(f.h.sequence == (uint32_t)chunks + 1u); /* schema used sequence 0 */
                CHECK(f.h.payload_bytes == 64u);
                memcpy(assembled + assembled_len, f.payload, f.h.payload_bytes);
                assembled_len += f.h.payload_bytes;
                if (f.h.flags & SMA_FLAG_LAST_CHUNK) got_last = 1;
                chunks++;
                if (got_last) break;
            }
        }
        CHECK(chunks == 3);
        CHECK(got_first == 1 && got_last == 1);
        CHECK(assembled_len == 192u);
        {
            uint8_t digest[32];
            char hex[65];
            gw_sha256(assembled, assembled_len, digest);
            gw_sha256_hex(digest, hex);
            CHECK(strcmp(hex, sha) == 0);
        }
        {
            gw_smc1 smc;
            CHECK(gw_smc1_decode(assembled, &smc) == 0);
            CHECK(smc.event_id == 5001u);
            CHECK(smc.record_count == 4u);
            CHECK(smc.first_sample == 1000u);
            CHECK(smc.last_sample == 1003u);
            CHECK(smc.record_count * 32u + 64u == 192u);
        }
        test_client_close(G, &bc);
    }
    snprintf(args, sizeof args, "{\"eventId\":\"5001\",\"sha256\":\"%s\"}", sha);
    CHECK(primary_req_id("ack-1", "event.ack", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char dup[16]; char acked[16];
        CHECK(test_json_path_str(resp, "result.acked", acked, sizeof acked) == 0);
        CHECK(strcmp(acked, "true") == 0);
        CHECK(test_json_path_str(resp, "result.duplicate", dup, sizeof dup) == 0);
        CHECK(strcmp(dup, "false") == 0);
    }
    CHECK(primary_req_id("ack-1b", "event.ack", args, resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    {
        char dup[16];
        CHECK(test_json_path_str(resp, "result.duplicate", dup, sizeof dup) == 0);
        CHECK(strcmp(dup, "true") == 0);
    }
    /* wrong sha is rejected, unknown event is not found */
    CHECK(primary_req("event.ack",
          "{\"eventId\":\"5001\",\"sha256\":"
          "\"0000000000000000000000000000000000000000000000000000000000000000\"}",
          resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "event_hash_mismatch"));
    CHECK(primary_req("event.ack",
          "{\"eventId\":\"9999\",\"sha256\":"
          "\"0000000000000000000000000000000000000000000000000000000000000000\"}",
          resp, sizeof resp) == 0);
    CHECK(resp_error(resp, "unknown_event"));
    CHECK(primary_req("event.list", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    CHECK(strstr(resp, "\"events\":[]") != NULL);
}

/* ============================================================ epoch restart */

static char g_spool_dir[256];

static void test_epoch_restart(void)
{
    test_client c;
    char resp[GW_LINE_BYTES];
    uint64_t old_epoch;
    section("connection_epoch_persistence");
    old_epoch = G->epoch;
    test_client_close(G, &g_primary);
    /* let the server see the disconnects before shutdown */
    pump_n(3);
    fake_env_stop(&ENV);
    CHECK(fake_env_start(&ENV, g_spool_dir) == 0);
    G = ENV.gateway;
    CHECK(G->epoch == old_epoch + 1u);
    CHECK(test_client_open(G, &c, 0) == 0);
    CHECK(test_hello(G, &c, "epoch-tester") == 0);
    CHECK(c.epoch == old_epoch + 1u);
    CHECK(test_req(G, &c, "status.get", "{}", resp, sizeof resp) == 0);
    CHECK(resp_ok(resp));
    test_client_close(G, &c);
}

/* ==================================================================== main */

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("GATEWAY_TEST_START pid=%d\n", gw_pid());
    gw_test_clock_set(1000000);
    snprintf(g_spool_dir, sizeof g_spool_dir, "build/gwtest_%d", gw_pid());
    if (fake_env_start(&ENV, g_spool_dir) != 0) {
        printf("GATEWAY_TESTS_FAIL env_start\n");
        return 1;
    }
    G = ENV.gateway;
    g_epoch = G->epoch;
    printf("PHASE handshake\n"); fflush(stdout);
    test_handshake();
    printf("PHASE fatal\n"); fflush(stdout);
    test_fatal_frames();
    printf("PHASE lease\n"); fflush(stdout);
    test_control_lease();
    printf("PHASE config\n"); fflush(stdout);
    test_config();
    g_epoch = G->epoch;
    printf("PHASE result\n"); fflush(stdout);
    test_result_words_stream();
    printf("PHASE service\n"); fflush(stdout);
    test_service_snapshot();
    printf("PHASE events\n"); fflush(stdout);
    test_events();
    printf("PHASE epoch\n"); fflush(stdout);
    test_epoch_restart();
    if (ENV.gateway) fake_env_stop(&ENV);
    gw_test_clock_reset();
    if (g_fail) {
        printf("GATEWAY_TESTS_FAIL failures=%d checks=%d\n", g_fail, g_checks);
        return 1;
    }
    printf("GATEWAY_TESTS_PASS checks=%d\n", g_checks);
    return 0;
}
