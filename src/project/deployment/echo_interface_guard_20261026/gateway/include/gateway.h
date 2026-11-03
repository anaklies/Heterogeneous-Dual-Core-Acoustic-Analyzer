#ifndef GW_GATEWAY_H
#define GW_GATEWAY_H
/* Gateway runtime state shared by the control server, binary server, device
 * poller and fixture tests. Single-threaded: one gw_pump() iteration owns all
 * sockets and all device accesses (single controller). */
#include <stdint.h>
#include <stddef.h>

#include "gw_util.h"
#include "json.h"
#include "net.h"
#include "spool.h"
#include "sha256.h"
#include "mmio.h"
#include "device_arbiter.h"
#include "sixmic_analysis_wire.h"

#define GW_VERSION "echo-ps-1.0.0"
#define GW_PROTOCOL_NAME SMA_PROTOCOL_NAME
#define GW_PROTOCOL_VERSION SMA_PROTOCOL_VERSION
#define GW_FEATURE_COUNT 45 /* spatial interfaces removed 2026-10-31; must match registry */

#define GW_MAX_CONTROL_CONNS 8
#define GW_MAX_BINARY_CONNS 8
#define GW_MAX_JOBS SMA_DEFAULT_MAX_PENDING_JOBS
#define GW_MAX_SUBSCRIPTIONS 16
#define GW_MAX_SUB_STREAMS 8
#define GW_MAX_BINARY_SESSIONS 8
#define GW_MAX_DOWNLOADS 8
#define GW_MAX_DUP_ENTRIES SMA_DUPLICATE_CACHE_ENTRIES
#define GW_LINE_BYTES (SMA_MAX_LINE_BYTES + 2u)
#define GW_NOTIFY_BYTES 2048u
#define GW_INBUF_BYTES 4096u
#define GW_BINARY_OUT_CAP (2u * 1024u * 1024u)
#define GW_SERVICE_MAX_WORDS 16384u
#define GW_SERVICE_ROUTES 16u
#define GW_RATE_PER_SEC 64.0
#define GW_RATE_BURST 128.0
#define GW_SETTLE_MS 10u
#define GW_DEFAULT_LEASE_SECONDS 30u
#define GW_MAX_LEASE_SECONDS 300u
#define GW_CONTROL_IDLE_MS 120000ull
#define GW_BINARY_IDLE_MS 120000ull
#define GW_BINARY_HEARTBEAT_MS 5000ull
#define GW_CONFIG_CONFIRM_TIMEOUT_MS 10000ull
#define GW_PENDING_CONFIG_WORDS 32u
#define GW_DEVICE_ID_MAX 32
#define GW_EVENT_PATH_MAX 384

/* Candidate-level device capabilities. Every value defaults to the honest
 * "not integrated" state; fixture mode never claims pl-live. */
typedef struct {
    int live_pcm;          /* false: no PL raw-ring PS consumer accepted */
    int live_results;      /* true only with --allow-live-results (unvalidated) */
    int config_commit;     /* true in fixture mode or with --allow-config-commit */
    int event_capture;
    int event_download;
    int task_control;      /* false: no PL task start/cancel acceptance */
    int device_log;
    int raw_recording;
    int profile_upload;
    int profile_activate;
    int sensor_snapshot;
    int protocol3;
    uint32_t config_version;
} gw_device_caps;

typedef struct {
    char bind_addr[64];
    uint16_t control_port;
    uint16_t binary_port;
    int mock_fixture;
    char uio_path[128];
    char memdev_path[128];
    uint32_t mmio_phys_base;
    uint32_t mmio_bytes;
    char ddr_memdev_path[128];
    uint32_t ddr_phys_base;
    uint32_t ddr_bytes;
    char spool_dir[GW_EVENT_PATH_MAX];
    char state_dir[GW_EVENT_PATH_MAX * 2];
    uint64_t spool_limit_bytes;
    uint32_t max_binary_payload;
    int poll_ms;
    int allow_config_commit;
    int allow_event_capture;
    int allow_live_results;
    uint32_t service_snapshot_addr;
    uint32_t service_snapshot_words;
    char service_catalog_file[384];
    char feature_registry_file[512];
    uint32_t max_control_lease_seconds;
    uint32_t config_confirm_timeout_ms;
    uint32_t job_fixture_polls;
} gw_config;

void gw_config_defaults(gw_config *c);

typedef enum {
    GW_JOB_QUEUED = 0,
    GW_JOB_RUNNING,
    GW_JOB_COMPLETED,
    GW_JOB_FAILED,
    GW_JOB_CANCEL_REQUESTED,
    GW_JOB_CANCELED
} gw_job_state;

typedef struct {
    int used;
    uint64_t id;
    char kind[24];
    gw_job_state state;
    int simulated;
    char client_task_key[65];
    char client_name[65];
    uint64_t created_ms;
    uint64_t updated_ms;
    char detail[128];
    int is_config_commit;
    int counted_pending;
    uint32_t config_version;
    uint32_t fixture_polls_left;
} gw_job;

typedef struct {
    char request_id[65];
    char *response;
    uint64_t at_ms;
} gw_dup_entry;

struct gw_bin_conn;

typedef struct {
    int used;
    gw_sock fd;
    char session_id[65];
    int hello_done;
    int closing;
    uint64_t connected_ms;
    uint64_t last_rx_ms;
    uint8_t inbuf[GW_INBUF_BYTES];
    size_t inlen;
    char in_line[GW_LINE_BYTES];
    size_t in_line_len;
    int dropping_line;
    gw_msgq out;
    size_t out_off;
    double rate_tokens;
    uint64_t rate_last_ms;
    gw_dup_entry dup[GW_MAX_DUP_ENTRIES];
    unsigned dup_head;
    unsigned dup_count;
    uint64_t empty_lines;
    uint64_t bad_json_frames;
    uint64_t requests;
    char client_name[65];
    char client_version[33];
    uint32_t client_max_payload;
} gw_ctl_conn;

typedef struct {
    uint32_t stream_id;
    uint32_t seq;
    int schema_sent;
    int is_result;
    int is_service;
    int is_event_file;
    int is_live;
    unsigned live_channel;
    uint32_t last_live_frame,last_live_config;
} gw_bin_stream_state;

typedef struct {
    int used;
    gw_sock fd;
    int closing;
    uint64_t connected_ms;
    uint64_t last_rx_ms;
    uint64_t last_tx_ms;
    uint64_t last_heartbeat_ms;
    uint8_t hdr[SMA_BINARY_HEADER_BYTES];
    size_t hdrlen;
    int hello_done;
    uint32_t max_payload;
    gw_fifo out;
    uint32_t nstreams;
    gw_bin_stream_state streams[GW_MAX_SUB_STREAMS];
    int result_pending;
    uint32_t result_words[SMA_RESULT_WORD_COUNT];
    uint64_t result_dropped;
    int result_gap;
    int service_pending;
    uint32_t service_bytes;
    uint8_t service_payload[SMA_SERVICE_HEADER_BYTES + GW_SERVICE_MAX_WORDS * 4u];
    int service_gap;
    int event_download;
    uint64_t event_id;
    uint64_t event_offset;
    uint64_t event_total;
    uint32_t chunk_bytes;
    char event_sha[65];
    int event_done;
    int event_first;
    char token[33];
    uint64_t bytes_out;
    uint64_t frames_out;
    uint32_t unknown_frames;
    int sess_idx;
    uint32_t conn_seq;
    sma_header cur;
    int have_header;
    uint32_t payload_left;
    uint32_t payload_crc_acc;
    int collect;
    uint8_t collect_buf[4096];
    uint32_t collect_len;
    uint8_t scratch[8192];
    uint8_t event_buf[65536];
} gw_bin_conn;

typedef struct {
    uint32_t stream_id;
    char type[24];
    char *schema_json;
    uint32_t schema_len;
    char schema_sha[65];
} gw_stream_def;

typedef struct {
    int used;
    char id[32];
    gw_stream_def streams[GW_MAX_SUB_STREAMS];
    uint32_t nstreams;
    int owner_conn;
    int wants_events;
    uint64_t created_ms;
} gw_subscription;

typedef struct {
    int used;
    char token[33];
    uint64_t expires_ms;
    uint64_t created_ms;
    uint32_t max_payload;
    uint32_t nstreams;
    gw_stream_def streams[GW_MAX_SUB_STREAMS];
    int is_event_download;
    uint64_t event_id;
    uint32_t chunk_bytes;
    uint64_t total_bytes;
    char sha[65];
    int bound_conn;
    int owner_conn;
    uint64_t event_offset_start;
} gw_bin_session;

typedef struct {
    int used;
    uint64_t event_id;
    uint32_t stream_id;
    uint32_t chunk_bytes;
    uint64_t total_bytes;
    uint64_t offset;
    char sha[65];
    uint64_t created_ms;
} gw_download;

typedef struct {
    uint64_t control_connections;
    uint64_t binary_connections;
    uint64_t control_requests;
    uint64_t bad_json_frames;
    uint64_t bad_utf8_frames;
    uint64_t line_too_long_frames;
    uint64_t rate_limited;
    uint64_t unknown_ops;
    uint64_t duplicate_requests;
    uint64_t notify_dropped;
    uint64_t snapshot_ok;
    uint64_t snapshot_retries;
    uint64_t snapshot_no_data;
    uint64_t snapshot_errors;
    uint64_t result_frames_published;
    uint64_t result_frames_dropped;
    uint64_t service_snapshots_ok;
    uint64_t service_snapshot_retries;
    uint64_t service_snapshot_errors;
    uint64_t events_captured;
    uint64_t events_duplicate;
    uint64_t event_capture_errors;
    uint64_t event_release_errors;
    uint64_t event_spool_dropped;
    uint64_t config_applied;
    uint64_t config_rejected;
    uint64_t config_io_errors;
    uint64_t config_timeouts;
    uint64_t binary_frames_out;
    uint64_t binary_unknown_frames;
    uint64_t binary_bad_frames;
    uint64_t binary_backpressure_closes;
    uint64_t binary_schema_sent;
    uint64_t binary_gaps_sent;
    uint64_t jobs_started;
    uint64_t jobs_completed;
    uint64_t jobs_failed;
    uint64_t jobs_canceled;
} gw_stats;

typedef struct {
    gw_config cfg;
    gw_mmio *mmio;
    int owns_mmio;
    void *mock_owned;
    gw_sock ctl_listener;
    gw_sock bin_listener;
    uint16_t ctl_bound_port;
    uint16_t bin_bound_port;
    uint64_t epoch;
    uint64_t start_ms;
    uint64_t now_ms;
    int stop;
    char device_id[GW_DEVICE_ID_MAX];
    uint32_t pl_firmware;
    uint32_t pl_protocol;
    int pl_identified;
    uint64_t pl_capabilities;
    gw_device_caps caps;
    /* last result snapshot */
    int has_result;
    sm_snapshot snap;
    uint64_t snap_rx_ms;
    uint32_t active_config_version;
    uint32_t config_shadow[32];
    uint32_t config_active_words[32];
    int config_active_known;
    int config_shadow_valid;
    uint32_t last_rejected_version;
    int pending_config;
    uint32_t pending_config_version;
    uint32_t pending_config_words[32];
    uint64_t pending_config_job;
    uint64_t pending_config_deadline_ms;
    /* runtime state */
    gw_arbiter arb;
    gw_job jobs[GW_MAX_JOBS];
    uint64_t next_job_id;
    uint32_t next_stream_id;
    uint64_t next_sub_seq;
    uint32_t next_bin_token;
    gw_subscription subs[GW_MAX_SUBSCRIPTIONS];
    gw_bin_session bin_sessions[GW_MAX_BINARY_SESSIONS];
    gw_download downloads[GW_MAX_DOWNLOADS];
    gw_ctl_conn ctl[GW_MAX_CONTROL_CONNS];
    gw_bin_conn bin[GW_MAX_BINARY_CONNS];
    gw_spool spool;
    gw_log log;
    gw_stats stats;
    uint64_t last_poll_ms;
    uint64_t last_identify_ms;
    uint64_t last_result_epoch_seen;
    uint32_t last_result_frame;
    int result_gap_pending;
    uint32_t pl_faults;
    uint64_t next_event_id;
    int service_snapshot_enabled;
    struct { uint32_t address, words, descriptor, generation, sequence; int seen; char name[48],units[96]; } service_routes[GW_SERVICE_ROUTES];
    unsigned service_route_count,service_route_next;
    void *features;
    uint32_t route_session,route_config;
    uint64_t event_retry_after[2];
    uint64_t service_frames;
    char holder_session[65];
    uint64_t last_heartbeat_notify_ms;
    char nbuf[GW_NOTIFY_BYTES];
    char rbuf[GW_LINE_BYTES];
} gw;

/* ------------------------------------------------------------ gateway.c */
void gw_config_defaults(gw_config *c);
int gw_init(gw *g, const gw_config *cfg, gw_mmio *mmio_or_null,
            char *err, size_t errcap);
void gw_shutdown(gw *g);
int gw_pump(gw *g, int timeout_ms);
int echo_routes_load(gw *g,const char *path,char *error,size_t capacity);
int echo_service_read(gw *g,uint8_t *payload,uint32_t *bytes);
int echo_prepare_config(gw *g,uint32_t words[32],const char **reason);
int gw_run(gw *g);
void gw_request_stop(gw *g);
uint64_t gw_epoch(const gw *g);
const char *gw_device_id(const gw *g);
void gw_device_poll(gw *g);
int gw_device_read_reg(gw *g, uint32_t offset, uint32_t *value);
int gw_config_validate(gw *g, const uint32_t words[32], uint32_t *bad_index,
                       const char **reason);
int gw_config_commit_start(gw *g, uint32_t version, const uint32_t words[32],
                           uint64_t *job_id, const char **err_reason);
void gw_config_abort(gw *g);
void gw_event_tick(gw *g);
int gw_event_capture_bank(gw *g, unsigned bank, const sm_clip *clip);
/* jobs */
gw_job *gw_job_alloc(gw *g, const char *kind, const char *client, int simulated);
gw_job *gw_job_find(gw *g, uint64_t id);
gw_job *gw_job_find_task_key(gw *g, const char *key);
void gw_job_set_state(gw *g, gw_job *job, gw_job_state state, const char *detail);
uint32_t gw_jobs_pending(const gw *g);
void gw_jobs_tick(gw *g);
const char *gw_job_state_str(gw_job_state st);
/* notifications */
void gw_notify_event(gw *g, const char *line);
void gw_notify_diag(gw *g, const char *level, const char *code, const char *msg);
/* Shared JSON fragments (also used by control_server.c). */
void gw_job_json(gw *g, const gw_job *job, gw_json_writer *w);
void gw_event_record_json(gw *g, const gw_event_rec *rec, gw_json_writer *w);
void gw_job_id_str(uint64_t id, char out[24]);
const char *gw_source_kind(const gw *g);

/* ------------------------------------------------------ control_server.c */
int ctl_server_init(gw *g, char *err, size_t errcap);
void ctl_server_shutdown(gw *g);
void ctl_server_on_readable(gw *g, gw_ctl_conn *c);
void ctl_server_flush(gw *g, gw_ctl_conn *c);
void ctl_server_tick(gw *g);
void ctl_notify_all(gw *g, const char *line);
void ctl_notify_subscribers(gw *g, const char *line, int events_only);
void ctl_conn_close(gw *g, gw_ctl_conn *c);
void ctl_conn_mark_closing(gw *g, gw_ctl_conn *c);
void gw_capabilities_json(gw *g, gw_json_writer *w);

/* ------------------------------------------------------- binary_server.c */
int bin_server_init(gw *g, char *err, size_t errcap);
void bin_server_shutdown(gw *g);
void bin_server_on_readable(gw *g, gw_bin_conn *c);
void bin_server_flush(gw *g, gw_bin_conn *c);
void bin_server_tick(gw *g);
void bin_publish_result(gw *g, const uint32_t words[SMA_RESULT_WORD_COUNT]);
void bin_publish_service(gw *g, const uint8_t *payload, uint32_t bytes);
void bin_server_close_conn(gw *g, gw_bin_conn *c, const char *reason);
int gw_stream_schema_build(gw *g, gw_stream_def *def, const char *type,
                           const gw_event_rec *ev, uint32_t chunk_bytes);
void gw_stream_def_free(gw_stream_def *def);
int gw_stream_def_copy(gw_stream_def *dst, const gw_stream_def *src);
void gw_logf(gw *g, const char *fmt, ...);

#endif
