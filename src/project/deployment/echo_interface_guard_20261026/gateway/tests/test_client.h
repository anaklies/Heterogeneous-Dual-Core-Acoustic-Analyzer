#ifndef GW_TEST_CLIENT_H
#define GW_TEST_CLIENT_H
/* Non-blocking test clients for the in-process gateway. The same thread
 * alternates gw_pump() with socket polling, so tests are deterministic and do
 * not depend on sleeps for correctness (a 1 ms sleep is used only to avoid
 * spinning). */
#include <stddef.h>
#include <stdint.h>

#include "fake_mmio.h"
#include "gateway.h"
#include "json.h"
#include "sixmic_analysis_wire.h"

#define CLI_RX_BYTES (64u * 1024u)
#define CLI_MAX_EVENTS 32

typedef struct {
    gw_sock fd;
    int binary;
    char rx[CLI_RX_BYTES];
    size_t rx_len;
    char events[CLI_MAX_EVENTS][1024];
    int nevents;
    char session_id[65];
    uint64_t epoch;
    unsigned req_seq;
} test_client;

int test_client_open(gw *g, test_client *c, int binary);
void test_client_close(gw *g, test_client *c);
/* Sends bytes (pumping the gateway when the socket is not writable). */
int test_client_send(gw *g, test_client *c, const void *data, size_t n);
/* Pumps the gateway and drains socket data. Returns bytes appended to rx. */
int test_client_pump(gw *g, test_client *c, int rounds);
/* Returns line length (>0, without the LF) or 0 when the peer closed,
 * -1 on timeout. */
int test_client_line(gw *g, test_client *c, char *out, size_t cap, int max_rounds);
/* Reads exactly n bytes (binary channel); 0 ok, -1 timeout/closed. */
int test_client_exact(gw *g, test_client *c, uint8_t *out, size_t n, int max_rounds);

/* Hello + envelope helpers. do_req returns 0 when a response with the matching
 * requestId arrived (raw JSON copied to resp); control events are buffered. */
int test_hello(gw *g, test_client *c, const char *client_name);
int test_req(gw *g, test_client *c, const char *op, const char *args_json,
             char *resp, size_t cap);
int test_req_id(gw *g, test_client *c, const char *request_id, const char *op,
                const char *args_json, char *resp, size_t cap);
const char *test_status(const char *resp_json); /* "ok"/"accepted"/"error"/NULL */
int test_error_code(const char *resp_json, char *out, size_t cap);
/* Extracts a string/number field path such as "result.jobId". */
int test_json_path_str(const char *json, const char *path, char *out, size_t cap);
int test_json_path_u32(const char *json, const char *path, uint32_t *out);
/* Waits for a control event by name and optional substring; stores raw event. */
int test_wait_event(gw *g, test_client *c, const char *event_name,
                    const char *needle, int max_rounds, char *out, size_t cap);
void test_clear_events(test_client *c);

/* Binary SMA1 helpers. */
typedef struct {
    sma_header h;
    uint8_t payload[65536];
} test_frame;
int test_bin_read_frame(gw *g, test_client *c, test_frame *f, int max_rounds);
int test_bin_send_frame(gw *g, test_client *c, uint16_t type, uint32_t stream_id,
                        uint32_t sequence, uint64_t epoch, uint32_t flags,
                        const void *payload, uint32_t payload_bytes,
                        int corrupt_crc);

#endif
