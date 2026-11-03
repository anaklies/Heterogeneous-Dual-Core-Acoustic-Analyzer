#include "test_client.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int test_client_open(gw *g, test_client *c, int binary)
{
    char err[128];
    memset(c, 0, sizeof *c);
    c->binary = binary;
    c->fd = gw_net_connect("127.0.0.1", binary ? g->bin_bound_port
                                                : g->ctl_bound_port,
                           err, sizeof err);
    if (c->fd == GW_SOCK_INVALID) {
        fprintf(stderr, "CLIENT_CONNECT_FAILED: %s\n", err);
        return -1;
    }
    return 0;
}

void test_client_close(gw *g, test_client *c)
{
    if (c->fd != GW_SOCK_INVALID) {
        gw_net_close(c->fd);
        c->fd = GW_SOCK_INVALID;
    }
    (void)g;
}

int test_client_send(gw *g, test_client *c, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    size_t sent = 0;
    while (sent < n) {
        int r = gw_net_send(c->fd, p + sent, n - sent);
        if (r > 0) { sent += (size_t)r; continue; }
        if (r == GW_SEND_ERROR) return -1;
        gw_pump(g, 0);
        gw_sleep_ms(1);
    }
    return 0;
}

static int drain(gw *g, test_client *c, int rounds)
{
    int total = 0;
    int r;
    for (r = 0; r < rounds; r++) {
        gw_pump(g, 0);
        for (;;) {
            int n;
            if (c->rx_len >= sizeof c->rx) break;
            n = gw_net_recv(c->fd, c->rx + c->rx_len, sizeof c->rx - c->rx_len);
            if (n > 0) { c->rx_len += (size_t)n; total += n; continue; }
            if (n == 0) return total; /* peer closed */
            if (n == GW_RECV_ERROR) return -total - 1;
            break;
        }
        if (total > 0 && r > 2) break;
        if (r > 2) gw_sleep_ms(1);
    }
    return total;
}

int test_client_pump(gw *g, test_client *c, int rounds)
{
    int r;
    for (r = 0; r < rounds; r++) gw_pump(g, 0);
    return drain(g, c, 1);
}

int test_client_line(gw *g, test_client *c, char *out, size_t cap, int max_rounds)
{
    int r;
    for (r = 0; r < max_rounds; r++) {
        size_t i;
        for (i = 0; i < c->rx_len; i++) {
            if (c->rx[i] == '\n') {
                size_t len = i;
                if (len + 1 > cap) len = cap - 1;
                memcpy(out, c->rx, len);
                out[len] = 0;
                memmove(c->rx, c->rx + i + 1, c->rx_len - i - 1);
                c->rx_len -= i + 1;
                return (int)len;
            }
        }
        {
            int n;
            gw_pump(g, 0);
            if (c->rx_len < sizeof c->rx) {
                n = gw_net_recv(c->fd, c->rx + c->rx_len,
                                sizeof c->rx - c->rx_len);
                if (n == 0) return 0;
                if (n == GW_RECV_ERROR) return -2;
                if (n > 0) c->rx_len += (size_t)n;
            }
        }
        gw_sleep_ms(1);
    }
    return -1;
}

int test_client_exact(gw *g, test_client *c, uint8_t *out, size_t n, int max_rounds)
{
    size_t got = 0;
    int r;
    for (r = 0; r < max_rounds && got < n; r++) {
        size_t take = n - got;
        if (take > c->rx_len) take = c->rx_len;
        if (take > 0) {
            memcpy(out + got, c->rx, take);
            got += take;
            memmove(c->rx, c->rx + take, c->rx_len - take);
            c->rx_len -= take;
            continue;
        }
        {
            int nr;
            gw_pump(g, 0);
            if (c->rx_len < sizeof c->rx) {
                nr = gw_net_recv(c->fd, c->rx + c->rx_len,
                                 sizeof c->rx - c->rx_len);
                if (nr == 0) return -1;
                if (nr == GW_RECV_ERROR) return -1;
                if (nr > 0) c->rx_len += (size_t)nr;
            }
        }
        gw_sleep_ms(1);
    }
    return got == n ? 0 : -1;
}

/* ------------------------------------------------------------------ JSON */

static int parse_doc(gw_json_doc *doc, const char *json)
{
    char err[128];
    return gw_json_parse(doc, json, strlen(json), 64, 20000, err, sizeof err);
}

const char *test_status(const char *resp_json)
{
    gw_json_doc doc;
    const gw_json_node *root;
    static char status[16];
    if (parse_doc(&doc, resp_json) != 0) return NULL;
    root = gw_json_root(&doc);
    if (gw_json_get_str(&doc, root, "status", status, sizeof status, NULL) != 0)
        status[0] = 0;
    gw_json_doc_free(&doc);
    return status[0] ? status : NULL;
}

int test_error_code(const char *resp_json, char *out, size_t cap)
{
    gw_json_doc doc;
    const gw_json_node *root, *err;
    int rc = -1;
    if (parse_doc(&doc, resp_json) != 0) return -1;
    root = gw_json_root(&doc);
    err = gw_json_obj_get(&doc, root, "error");
    if (err && gw_json_get_str(&doc, err, "code", out, cap, NULL) == 0) rc = 0;
    gw_json_doc_free(&doc);
    return rc;
}

static const gw_json_node *path_walk(const gw_json_doc *doc,
                                     const gw_json_node *node, const char *path)
{
    char key[64];
    const char *p = path;
    const gw_json_node *cur = node;
    while (cur && *p) {
        size_t n = 0;
        while (p[n] && p[n] != '.') n++;
        if (n >= sizeof key) return NULL;
        memcpy(key, p, n);
        key[n] = 0;
        if (cur->type == GW_JSON_ARRAY) {
            uint32_t idx = 0;
            if (gw_parse_u32_dec(key, n, &idx) != 0) return NULL;
            cur = gw_json_arr_at(cur, idx);
        } else {
            cur = gw_json_obj_get(doc, cur, key);
        }
        p += n;
        if (*p == '.') p++;
    }
    return cur;
}

int test_json_path_str(const char *json, const char *path, char *out, size_t cap)
{
    gw_json_doc doc;
    const gw_json_node *root, *v;
    int rc = -1;
    if (parse_doc(&doc, json) != 0) return -1;
    root = gw_json_root(&doc);
    v = path_walk(&doc, root, path);
    if (v && v->type == GW_JSON_STRING) {
        size_t n = 0;
        const char *s = gw_json_str(&doc, v, &n);
        if (s && n + 1 <= cap) { memcpy(out, s, n); out[n] = 0; rc = 0; }
    } else if (v && (v->type == GW_JSON_NUMBER || v->type == GW_JSON_BOOL)) {
        const char *s = NULL;
        if (v->type == GW_JSON_BOOL) s = v->boolean ? "true" : "false";
        if (s) snprintf(out, cap, "%s", s);
        else if (v->number >= 0 && v->number <= 4294967295.0)
            snprintf(out, cap, "%.0f", v->number);
        rc = 0;
    }
    gw_json_doc_free(&doc);
    return rc;
}

int test_json_path_u32(const char *json, const char *path, uint32_t *out)
{
    gw_json_doc doc;
    const gw_json_node *root, *v;
    int rc = -1;
    if (parse_doc(&doc, json) != 0) return -1;
    root = gw_json_root(&doc);
    v = path_walk(&doc, root, path);
    if (v && v->type == GW_JSON_NUMBER) {
        if (gw_json_node_u32(v, out) == 0) rc = 0;
    } else if (v && v->type == GW_JSON_STRING) {
        size_t n = 0;
        const char *s = gw_json_str(&doc, v, &n);
        if (s && gw_parse_u32_dec(s, n, out) == 0) rc = 0;
    }
    gw_json_doc_free(&doc);
    return rc;
}

static int wait_response(gw *g, test_client *c, const char *request_id,
                         char *resp, size_t cap, int max_rounds)
{
    int r;
    for (r = 0; r < max_rounds; r++) {
        char line[GW_LINE_BYTES];
        int len = test_client_line(g, c, line, sizeof line, 1);
        if (len < 0) { gw_sleep_ms(1); continue; }
        if (len == 0) return -1;
        {
            gw_json_doc doc;
            const gw_json_node *root;
            char type[24] = "";
            char rid[80] = "";
            if (parse_doc(&doc, line) != 0) continue;
            root = gw_json_root(&doc);
            (void)gw_json_get_str(&doc, root, "type", type, sizeof type, NULL);
            (void)gw_json_get_str(&doc, root, "requestId", rid, sizeof rid, NULL);
            if (strcmp(type, "event") == 0) {
                if (c->nevents < CLI_MAX_EVENTS)
                    snprintf(c->events[c->nevents++], 1024, "%s", line);
                gw_json_doc_free(&doc);
                continue;
            }
            if (strcmp(type, "response") == 0 &&
                (request_id == NULL || strcmp(rid, request_id) == 0)) {
                snprintf(resp, cap, "%s", line);
                gw_json_doc_free(&doc);
                return 0;
            }
            gw_json_doc_free(&doc);
        }
    }
    return -1;
}

int test_hello(gw *g, test_client *c, const char *client_name)
{
    char args[256];
    char resp[GW_LINE_BYTES];
    char sid[65];
    snprintf(args, sizeof args,
             "{\"clientName\":\"%s\",\"clientVersion\":\"host-test-1\","
             "\"maxBinaryPayloadBytes\":1048576}", client_name);
    if (test_req_id(g, c, "hello-0", "hello", args, resp, sizeof resp) != 0)
        return -1;
    if (strcmp(test_status(resp), "ok") != 0) {
        fprintf(stderr, "HELLO_FAILED: %s\n", resp);
        return -1;
    }
    if (test_json_path_str(resp, "result.sessionId", sid, sizeof sid) != 0)
        return -1;
    snprintf(c->session_id, sizeof c->session_id, "%s", sid);
    {
        char ep[32];
        if (test_json_path_str(resp, "result.connectionEpoch", ep, sizeof ep) == 0)
            c->epoch = strtoull(ep, NULL, 10);
    }
    return 0;
}

static int send_req(gw *g, test_client *c, const char *request_id,
                    const char *op, const char *args_json)
{
    char req[GW_LINE_BYTES];
    int n;
    if (c->session_id[0]) {
        n = snprintf(req, sizeof req,
                     "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                     "\"requestId\":\"%s\",\"sessionId\":\"%s\",\"op\":\"%s\","
                     "\"args\":%s}\n",
                     request_id, c->session_id, op, args_json);
    } else {
        n = snprintf(req, sizeof req,
                     "{\"protocol\":\"sixmic-analysis\",\"version\":1,"
                     "\"requestId\":\"%s\",\"op\":\"%s\",\"args\":%s}\n",
                     request_id, op, args_json);
    }
    if (n < 0 || (size_t)n >= sizeof req) return -1;
    return test_client_send(g, c, req, (size_t)n);
}

int test_req_id(gw *g, test_client *c, const char *request_id, const char *op,
                const char *args_json, char *resp, size_t cap)
{
    if (send_req(g, c, request_id, op, args_json) != 0) return -1;
    return wait_response(g, c, request_id, resp, cap, 400);
}

int test_req(gw *g, test_client *c, const char *op, const char *args_json,
             char *resp, size_t cap)
{
    char rid[32];
    snprintf(rid, sizeof rid, "r-%u", ++c->req_seq);
    return test_req_id(g, c, rid, op, args_json, resp, cap);
}

int test_wait_event(gw *g, test_client *c, const char *event_name,
                    const char *needle, int max_rounds, char *out, size_t cap)
{
    int r;
    for (r = 0; r < max_rounds; r++) {
        char line[GW_LINE_BYTES];
        int len = test_client_line(g, c, line, sizeof line, 1);
        if (len > 0) {
            gw_json_doc doc;
            const gw_json_node *root;
            char type[24] = "";
            char name[32] = "";
            if (parse_doc(&doc, line) == 0) {
                root = gw_json_root(&doc);
                (void)gw_json_get_str(&doc, root, "type", type, sizeof type, NULL);
                (void)gw_json_get_str(&doc, root, "event", name, sizeof name, NULL);
                if (strcmp(type, "event") == 0) {
                    if (strcmp(name, event_name) == 0 &&
                        (!needle || strstr(line, needle))) {
                        if (out) snprintf(out, cap, "%s", line);
                        gw_json_doc_free(&doc);
                        return 0;
                    }
                    if (c->nevents < CLI_MAX_EVENTS)
                        snprintf(c->events[c->nevents++], 1024, "%s", line);
                }
                gw_json_doc_free(&doc);
            }
            continue;
        }
        gw_pump(g, 0);
        gw_sleep_ms(1);
    }
    return -1;
}

void test_clear_events(test_client *c) { c->nevents = 0; }

/* ---------------------------------------------------------------- binary */

int test_bin_read_frame(gw *g, test_client *c, test_frame *f, int max_rounds)
{
    uint8_t hdr[SMA_BINARY_HEADER_BYTES];
    int rc;
    if (!c) return -1;
    rc = test_client_exact(g, c, hdr, sizeof hdr, max_rounds);
    if (rc != 0) return -1;
    rc = sma_header_decode(hdr, &f->h, 16u * 1024u * 1024u);
    if (rc != 0) return -2;
    if (f->h.payload_bytes > sizeof f->payload) return -2;
    if (f->h.payload_bytes) {
        if (test_client_exact(g, c, f->payload, f->h.payload_bytes,
                              max_rounds) != 0) return -1;
        if (f->h.payload_bytes < sizeof f->payload)
            f->payload[f->h.payload_bytes] = 0; /* test-side JSON convenience */
        if ((f->h.flags & SMA_FLAG_CRC32_VALID) &&
            sma_crc32(f->payload, f->h.payload_bytes) != f->h.payload_crc32)
            return -3;
    }
    return 0;
}

int test_bin_send_frame(gw *g, test_client *c, uint16_t type, uint32_t stream_id,
                        uint32_t sequence, uint64_t epoch, uint32_t flags,
                        const void *payload, uint32_t payload_bytes,
                        int corrupt_crc)
{
    uint8_t hdr[SMA_BINARY_HEADER_BYTES];
    sma_header h;
    memset(&h, 0, sizeof h);
    h.protocol_version = (uint16_t)SMA_BINARY_PROTOCOL_VERSION;
    h.header_bytes = (uint16_t)SMA_BINARY_HEADER_BYTES;
    h.message_type = type;
    h.flags = (uint16_t)flags;
    h.payload_bytes = payload_bytes;
    h.stream_id = stream_id;
    h.sequence = sequence;
    h.connection_epoch = epoch;
    if (payload_bytes) {
        h.flags |= SMA_FLAG_CRC32_VALID;
        h.payload_crc32 = sma_crc32((const uint8_t *)payload, payload_bytes);
        if (corrupt_crc) h.payload_crc32 ^= 0x1u;
    }
    sma_header_encode(hdr, &h);
    if (test_client_send(g, c, hdr, sizeof hdr) != 0) return -1;
    if (payload_bytes && test_client_send(g, c, payload, payload_bytes) != 0)
        return -1;
    return 0;
}
