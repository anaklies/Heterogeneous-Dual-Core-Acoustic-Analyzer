#ifndef GW_JSON_H
#define GW_JSON_H
/* Minimal strict JSON DOM parser + writer. C99, no locale, no external deps.
 *
 * Strictness notes (sixmic-analysis v1, PROTOCOL.md 2.1):
 *  - duplicate object keys are rejected
 *  - NaN/Infinity are not JSON numbers and are rejected
 *  - depth and node-count limits are enforced
 *  - strings may contain JSON escapes including \uXXXX with surrogate pairs
 * The caller validates UTF-8 before parsing; the parser still rejects malformed
 * multi-byte sequences inside strings rather than emitting invalid UTF-8.
 */
#include <stddef.h>
#include <stdint.h>

#define GW_JSON_MAX_WRITE_DEPTH 40

typedef enum {
    GW_JSON_NULL = 0,
    GW_JSON_BOOL = 1,
    GW_JSON_NUMBER = 2,
    GW_JSON_STRING = 3,
    GW_JSON_ARRAY = 4,
    GW_JSON_OBJECT = 5
} gw_json_type;

typedef struct gw_json_node {
    uint8_t type;
    uint8_t has_key;
    uint32_t key_off;
    uint32_t key_len;
    uint32_t str_off;
    uint32_t str_len;
    int boolean;
    double number;
    struct gw_json_node *child;
    struct gw_json_node *next;
} gw_json_node;

typedef struct {
    gw_json_node *nodes;
    uint32_t node_cap;
    uint32_t node_used;
    char *strs;
    size_t str_cap;
    size_t str_used;
    gw_json_node root;
    int root_set;
} gw_json_doc;

void gw_json_doc_init(gw_json_doc *doc);
void gw_json_doc_free(gw_json_doc *doc);

/* Parse exactly one JSON value (trailing whitespace allowed). Returns 0 on
 * success, negative parse error code on failure, and writes a short ASCII
 * reason to err when err != NULL. The document is unusable after failure. */
int gw_json_parse(gw_json_doc *doc, const char *text, size_t len,
                  uint32_t max_depth, uint32_t max_nodes,
                  char *err, size_t errcap);
const gw_json_node *gw_json_root(const gw_json_doc *doc);

const gw_json_node *gw_json_obj_get(const gw_json_doc *doc,
                                    const gw_json_node *obj, const char *key);
const gw_json_node *gw_json_arr_at(const gw_json_node *arr, size_t idx);
size_t gw_json_arr_count(const gw_json_node *arr);
const char *gw_json_str(const gw_json_doc *doc, const gw_json_node *v,
                        size_t *len);
const char *gw_json_key(const gw_json_doc *doc, const gw_json_node *member,
                        size_t *len);

/* Strict getters: 0 = present and correct type, -1 = missing/wrong type. */
int gw_json_get_u32(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, uint32_t *out);
int gw_json_get_i32(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, int32_t *out);
int gw_json_get_bool(const gw_json_doc *doc, const gw_json_node *obj,
                     const char *key, int *out);
/* Copies a string value; returns 0 on success. Rejects strings that do not
 * fit (including NUL) and non-string values. */
int gw_json_get_str(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, char *out, size_t cap, size_t *out_len);
/* Protocol v1: 64-bit integers travel as decimal strings. Strict decimal,
 * no sign, no leading '+', max uint64. */
int gw_json_get_u64_dec(const gw_json_doc *doc, const gw_json_node *obj,
                        const char *key, uint64_t *out);
int gw_json_node_u64_dec(const gw_json_doc *doc, const gw_json_node *v,
                         uint64_t *out);
int gw_json_node_u32(const gw_json_node *v, uint32_t *out);

/* -------- writer -------- */
typedef struct {
    char *buf;
    size_t cap;
    size_t len;
    int err;
    int root_written;
    int depth;
    struct { uint8_t is_obj; uint8_t first; } st[GW_JSON_MAX_WRITE_DEPTH];
} gw_json_writer;

void gw_jw_init(gw_json_writer *w, char *buf, size_t cap);
int gw_jw_ok(const gw_json_writer *w);
size_t gw_jw_len(const gw_json_writer *w);
/* Finalize: NUL-terminate and verify structure. Returns total byte length
 * (excluding NUL) or 0 on error. */
size_t gw_jw_finish(gw_json_writer *w);

void gw_jw_begin_obj(gw_json_writer *w);
void gw_jw_end_obj(gw_json_writer *w);
void gw_jw_begin_arr(gw_json_writer *w);
void gw_jw_end_arr(gw_json_writer *w);
void gw_jw_key(gw_json_writer *w, const char *key);
void gw_jw_str(gw_json_writer *w, const char *s);
void gw_jw_strn(gw_json_writer *w, const char *s, size_t n);
void gw_jw_u32(gw_json_writer *w, uint32_t v);
void gw_jw_i64(gw_json_writer *w, int64_t v);
void gw_jw_u64dec_str(gw_json_writer *w, uint64_t v);
void gw_jw_bool(gw_json_writer *w, int v);
void gw_jw_null(gw_json_writer *w);
/* Appends an already-serialized JSON value (e.g. a prebuilt subtree or a
 * literal number that must not go through double formatting). */
void gw_jw_raw_value(gw_json_writer *w, const char *json, size_t n);

#endif