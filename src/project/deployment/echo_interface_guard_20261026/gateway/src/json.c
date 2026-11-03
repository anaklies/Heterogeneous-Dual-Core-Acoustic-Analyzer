#include "json.h"
#include "utf8.h"

#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------- DOM parse */

enum {
    JERR_SYNTAX = -1,
    JERR_DEPTH = -2,
    JERR_NODES = -3,
    JERR_DUP_KEY = -4,
    JERR_NUMBER = -5,
    JERR_ESCAPE = -6,
    JERR_UTF8 = -7,
    JERR_MEMORY = -8
};

typedef struct {
    gw_json_doc *doc;
    const char *s;
    size_t len;
    size_t pos;
    uint32_t max_depth;
    char *err;
    size_t errcap;
} jparse;

static void jerr(jparse *p, const char *msg)
{
    if (p->err && p->errcap) {
        size_t n = strlen(msg);
        if (n >= p->errcap) n = p->errcap - 1;
        memcpy(p->err, msg, n);
        p->err[n] = 0;
    }
}

static gw_json_node *jnew(jparse *p)
{
    gw_json_node *n;
    if (p->doc->node_used >= p->doc->node_cap) {
        jerr(p, "node limit exceeded");
        return NULL;
    }
    n = &p->doc->nodes[p->doc->node_used++];
    memset(n, 0, sizeof *n);
    return n;
}

static void jskip_ws(jparse *p)
{
    while (p->pos < p->len) {
        char c = p->s[p->pos];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') p->pos++;
        else break;
    }
}

static int jhex4(jparse *p, uint32_t *out)
{
    uint32_t v = 0;
    int i;
    for (i = 0; i < 4; i++) {
        char c;
        if (p->pos >= p->len) return JERR_ESCAPE;
        c = p->s[p->pos++];
        v <<= 4;
        if (c >= '0' && c <= '9') v |= (uint32_t)(c - '0');
        else if (c >= 'a' && c <= 'f') v |= (uint32_t)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v |= (uint32_t)(c - 'A' + 10);
        else return JERR_ESCAPE;
    }
    *out = v;
    return 0;
}

/* Appends raw decoded bytes; no terminator per fragment. */
static int jstr_put(jparse *p, const uint8_t *bytes, size_t n)
{
    if (p->doc->str_used + n + 1 > p->doc->str_cap) return JERR_MEMORY;
    memcpy(p->doc->strs + p->doc->str_used, bytes, n);
    p->doc->str_used += n;
    return 0;
}

static int jparse_string(jparse *p, uint32_t *off_out, uint32_t *len_out)
{
    size_t start;
    if (p->pos >= p->len || p->s[p->pos] != '"') return JERR_SYNTAX;
    p->pos++;
    start = p->doc->str_used;
    while (p->pos < p->len) {
        uint8_t c = (uint8_t)p->s[p->pos];
        if (c == '"') {
            p->pos++;
            if (p->doc->str_used + 1 > p->doc->str_cap) return JERR_MEMORY;
            p->doc->strs[p->doc->str_used++] = 0;
            *off_out = (uint32_t)start;
            *len_out = (uint32_t)(p->doc->str_used - start - 1);
            return 0;
        }
        if (c == '\\') {
            uint8_t enc[4];
            size_t enc_n = 0;
            char e;
            p->pos++;
            if (p->pos >= p->len) return JERR_ESCAPE;
            e = p->s[p->pos++];
            if (e == '"' || e == '\\' || e == '/') { enc[0] = (uint8_t)e; enc_n = 1; }
            else if (e == 'b') { enc[0] = 0x08; enc_n = 1; }
            else if (e == 'f') { enc[0] = 0x0C; enc_n = 1; }
            else if (e == 'n') { enc[0] = 0x0A; enc_n = 1; }
            else if (e == 'r') { enc[0] = 0x0D; enc_n = 1; }
            else if (e == 't') { enc[0] = 0x09; enc_n = 1; }
            else if (e == 'u') {
                uint32_t cp;
                int rc = jhex4(p, &cp);
                if (rc) return rc;
                if (cp >= 0xD800 && cp <= 0xDBFF) {
                    uint32_t lo;
                    if (p->pos + 1 >= p->len || p->s[p->pos] != '\\' ||
                        p->s[p->pos + 1] != 'u') return JERR_ESCAPE;
                    p->pos += 2;
                    rc = jhex4(p, &lo);
                    if (rc) return rc;
                    if (lo < 0xDC00 || lo > 0xDFFF) return JERR_ESCAPE;
                    cp = 0x10000u + ((cp - 0xD800u) << 10) + (lo - 0xDC00u);
                } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                    return JERR_ESCAPE;
                }
                enc_n = gw_utf8_encode(cp, enc);
                if (enc_n == 0) return JERR_UTF8;
            } else return JERR_ESCAPE;
            if (jstr_put(p, enc, enc_n)) return JERR_MEMORY;
            continue;
        }
        if (c < 0x20) return JERR_SYNTAX;
        if (c < 0x80) {
            if (jstr_put(p, &c, 1)) return JERR_MEMORY;
            p->pos++;
            continue;
        }
        {
            uint32_t cp;
            size_t n = gw_utf8_decode((const uint8_t *)p->s + p->pos,
                                      p->len - p->pos, &cp);
            if (n == 0) return JERR_UTF8;
            if (jstr_put(p, (const uint8_t *)p->s + p->pos, n)) return JERR_MEMORY;
            p->pos += n;
        }
    }
    return JERR_SYNTAX;
}

static int jparse_value(jparse *p, gw_json_node *out, int depth);

static int jdup_check(jparse *p, const gw_json_node *obj)
{
    const gw_json_node *a;
    for (a = obj->child; a; a = a->next) {
        const gw_json_node *b;
        for (b = a->next; b; b = b->next) {
            if (a->key_len == b->key_len &&
                memcmp(p->doc->strs + a->key_off, p->doc->strs + b->key_off,
                       a->key_len) == 0) {
                jerr(p, "duplicate object key");
                return JERR_DUP_KEY;
            }
        }
    }
    return 0;
}

static int jparse_obj(jparse *p, gw_json_node *out, int depth)
{
    gw_json_node *last = NULL;
    p->pos++; /* '{' */
    out->type = GW_JSON_OBJECT;
    jskip_ws(p);
    if (p->pos < p->len && p->s[p->pos] == '}') { p->pos++; return 0; }
    for (;;) {
        gw_json_node *member;
        uint32_t koff = 0, klen = 0;
        int rc;
        jskip_ws(p);
        rc = jparse_string(p, &koff, &klen);
        if (rc) return rc;
        jskip_ws(p);
        if (p->pos >= p->len || p->s[p->pos] != ':') return JERR_SYNTAX;
        p->pos++;
        member = jnew(p);
        if (!member) return JERR_NODES;
        jskip_ws(p);
        rc = jparse_value(p, member, depth + 1);
        if (rc) return rc;
        member->has_key = 1;
        member->key_off = koff;
        member->key_len = klen;
        if (last) last->next = member; else out->child = member;
        last = member;
        jskip_ws(p);
        if (p->pos < p->len && p->s[p->pos] == ',') { p->pos++; continue; }
        if (p->pos < p->len && p->s[p->pos] == '}') {
            p->pos++;
            return jdup_check(p, out);
        }
        return JERR_SYNTAX;
    }
}

static int jparse_arr(jparse *p, gw_json_node *out, int depth)
{
    gw_json_node *last = NULL;
    p->pos++; /* '[' */
    out->type = GW_JSON_ARRAY;
    jskip_ws(p);
    if (p->pos < p->len && p->s[p->pos] == ']') { p->pos++; return 0; }
    for (;;) {
        gw_json_node *item = jnew(p);
        int rc;
        if (!item) return JERR_NODES;
        jskip_ws(p);
        rc = jparse_value(p, item, depth + 1);
        if (rc) return rc;
        if (last) last->next = item; else out->child = item;
        last = item;
        jskip_ws(p);
        if (p->pos < p->len && p->s[p->pos] == ',') { p->pos++; continue; }
        if (p->pos < p->len && p->s[p->pos] == ']') { p->pos++; return 0; }
        return JERR_SYNTAX;
    }
}

static int jparse_number(jparse *p, gw_json_node *out)
{
    size_t i = p->pos;
    int neg = 0;
    double v = 0.0;
    int digits = 0;
    if (i < p->len && p->s[i] == '-') { neg = 1; i++; }
    if (i >= p->len) return JERR_NUMBER;
    if (p->s[i] == '0') {
        i++; digits = 1;
        if (i < p->len && p->s[i] >= '0' && p->s[i] <= '9') return JERR_NUMBER;
    } else if (p->s[i] >= '1' && p->s[i] <= '9') {
        while (i < p->len && p->s[i] >= '0' && p->s[i] <= '9') {
            v = v * 10.0 + (double)(p->s[i] - '0');
            i++; digits++;
        }
    } else return JERR_NUMBER;
    if (i < p->len && p->s[i] == '.') {
        double scale = 0.1;
        i++;
        if (i >= p->len || p->s[i] < '0' || p->s[i] > '9') return JERR_NUMBER;
        while (i < p->len && p->s[i] >= '0' && p->s[i] <= '9') {
            v += (double)(p->s[i] - '0') * scale;
            scale *= 0.1;
            i++; digits++;
        }
    }
    if (i < p->len && (p->s[i] == 'e' || p->s[i] == 'E')) {
        int eneg = 0, edig = 0;
        long e = 0;
        i++;
        if (i < p->len && (p->s[i] == '+' || p->s[i] == '-')) {
            eneg = (p->s[i] == '-');
            i++;
        }
        while (i < p->len && p->s[i] >= '0' && p->s[i] <= '9') {
            if (e < 100000) e = e * 10 + (p->s[i] - '0');
            i++; edig++;
        }
        if (!edig) return JERR_NUMBER;
        while (e-- > 0) v = eneg ? v / 10.0 : v * 10.0;
    }
    if (!digits) return JERR_NUMBER;
    if (neg) v = -v;
    if (!(v == v) || v > 1.7976931348623157e308 || v < -1.7976931348623157e308)
        return JERR_NUMBER;
    out->type = GW_JSON_NUMBER;
    out->number = v;
    p->pos = i;
    return 0;
}

static int jparse_value(jparse *p, gw_json_node *out, int depth)
{
    char c;
    if (depth > (int)p->max_depth) {
        jerr(p, "depth limit exceeded");
        return JERR_DEPTH;
    }
    jskip_ws(p);
    if (p->pos >= p->len) return JERR_SYNTAX;
    c = p->s[p->pos];
    if (c == '{') return jparse_obj(p, out, depth);
    if (c == '[') return jparse_arr(p, out, depth);
    if (c == '"') {
        int rc;
        out->type = GW_JSON_STRING;
        rc = jparse_string(p, &out->str_off, &out->str_len);
        return rc;
    }
    if (p->len - p->pos >= 4 && memcmp(p->s + p->pos, "true", 4) == 0) {
        out->type = GW_JSON_BOOL; out->boolean = 1; p->pos += 4; return 0;
    }
    if (p->len - p->pos >= 5 && memcmp(p->s + p->pos, "false", 5) == 0) {
        out->type = GW_JSON_BOOL; out->boolean = 0; p->pos += 5; return 0;
    }
    if (p->len - p->pos >= 4 && memcmp(p->s + p->pos, "null", 4) == 0) {
        out->type = GW_JSON_NULL; p->pos += 4; return 0;
    }
    if (c == '-' || (c >= '0' && c <= '9')) return jparse_number(p, out);
    return JERR_SYNTAX;
}

void gw_json_doc_init(gw_json_doc *doc)
{
    memset(doc, 0, sizeof *doc);
}

void gw_json_doc_free(gw_json_doc *doc)
{
    if (!doc) return;
    free(doc->nodes);
    free(doc->strs);
    memset(doc, 0, sizeof *doc);
}

int gw_json_parse(gw_json_doc *doc, const char *text, size_t len,
                  uint32_t max_depth, uint32_t max_nodes,
                  char *err, size_t errcap)
{
    jparse p;
    uint32_t node_cap;
    size_t str_cap;
    int rc;
    gw_json_doc_init(doc);
    if (err && errcap) err[0] = 0;
    if (!text || max_depth == 0 || max_nodes == 0) return JERR_SYNTAX;
    node_cap = (uint32_t)(len / 2 + 4);
    if (node_cap > max_nodes) node_cap = max_nodes;
    if (node_cap < 4) node_cap = 4;
    str_cap = len * 2 + 8;
    doc->nodes = (gw_json_node *)calloc(node_cap, sizeof(gw_json_node));
    doc->strs = (char *)malloc(str_cap);
    if (!doc->nodes || !doc->strs) {
        gw_json_doc_free(doc);
        return JERR_MEMORY;
    }
    doc->node_cap = node_cap;
    doc->str_cap = str_cap;
    memset(&p, 0, sizeof p);
    p.doc = doc;
    p.s = text;
    p.len = len;
    p.max_depth = max_depth;
    p.err = err;
    p.errcap = errcap;
    jskip_ws(&p);
    rc = jparse_value(&p, &doc->root, 1);
    if (rc) { gw_json_doc_free(doc); return rc; }
    jskip_ws(&p);
    if (p.pos != p.len) {
        jerr(&p, "trailing bytes after JSON value");
        gw_json_doc_free(doc);
        return JERR_SYNTAX;
    }
    doc->root_set = 1;
    return 0;
}

const gw_json_node *gw_json_root(const gw_json_doc *doc)
{
    if (!doc || !doc->root_set) return NULL;
    return &doc->root;
}

static const char *nstr(const gw_json_doc *doc, uint32_t off, uint32_t len,
                        size_t *out_len)
{
    if (!doc) return NULL;
    if ((size_t)off + (size_t)len >= doc->str_cap) return NULL;
    if (out_len) *out_len = len;
    return doc->strs + off;
}

const char *gw_json_str(const gw_json_doc *doc, const gw_json_node *v, size_t *len)
{
    if (!v || v->type != GW_JSON_STRING) return NULL;
    return nstr(doc, v->str_off, v->str_len, len);
}

const char *gw_json_key(const gw_json_doc *doc, const gw_json_node *member, size_t *len)
{
    if (!member || !member->has_key) return NULL;
    return nstr(doc, member->key_off, member->key_len, len);
}

const gw_json_node *gw_json_obj_get(const gw_json_doc *doc,
                                    const gw_json_node *obj, const char *key)
{
    const gw_json_node *m;
    size_t klen;
    if (!doc || !obj || obj->type != GW_JSON_OBJECT || !key) return NULL;
    klen = strlen(key);
    for (m = obj->child; m; m = m->next) {
        if (m->has_key && (size_t)m->key_len == klen &&
            memcmp(doc->strs + m->key_off, key, klen) == 0) return m;
    }
    return NULL;
}

const gw_json_node *gw_json_arr_at(const gw_json_node *arr, size_t idx)
{
    const gw_json_node *n;
    if (!arr || arr->type != GW_JSON_ARRAY) return NULL;
    for (n = arr->child; n; n = n->next) {
        if (idx == 0) return n;
        idx--;
    }
    return NULL;
}

size_t gw_json_arr_count(const gw_json_node *arr)
{
    const gw_json_node *n;
    size_t c = 0;
    if (!arr || arr->type != GW_JSON_ARRAY) return 0;
    for (n = arr->child; n; n = n->next) c++;
    return c;
}

static int node_uint(const gw_json_node *v, double *out)
{
    if (!v || v->type != GW_JSON_NUMBER) return -1;
    if (!(v->number >= 0.0)) return -1;
    if (v->number > 4294967295.0) return -1;
    if ((double)(uint32_t)v->number != v->number) return -1;
    *out = v->number;
    return 0;
}

int gw_json_get_u32(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, uint32_t *out)
{
    double d;
    const gw_json_node *v = gw_json_obj_get(doc, obj, key);
    if (node_uint(v, &d)) return -1;
    *out = (uint32_t)d;
    return 0;
}

int gw_json_get_i32(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, int32_t *out)
{
    const gw_json_node *v = gw_json_obj_get(doc, obj, key);
    double d;
    if (!v || v->type != GW_JSON_NUMBER) return -1;
    d = v->number;
    if (d < -2147483648.0 || d > 2147483647.0) return -1;
    if ((double)(int32_t)d != d) return -1;
    *out = (int32_t)d;
    return 0;
}

int gw_json_get_bool(const gw_json_doc *doc, const gw_json_node *obj,
                     const char *key, int *out)
{
    const gw_json_node *v = gw_json_obj_get(doc, obj, key);
    if (!v || v->type != GW_JSON_BOOL) return -1;
    *out = v->boolean ? 1 : 0;
    return 0;
}

int gw_json_get_str(const gw_json_doc *doc, const gw_json_node *obj,
                    const char *key, char *out, size_t cap, size_t *out_len)
{
    const gw_json_node *v = gw_json_obj_get(doc, obj, key);
    size_t n = 0;
    const char *s;
    if (!v || v->type != GW_JSON_STRING) return -1;
    s = gw_json_str(doc, v, &n);
    if (!s) return -1;
    if (n + 1 > cap) return -1;
    memcpy(out, s, n);
    out[n] = 0;
    if (out_len) *out_len = n;
    return 0;
}

int gw_json_node_u32(const gw_json_node *v, uint32_t *out)
{
    double d;
    if (node_uint(v, &d)) return -1;
    *out = (uint32_t)d;
    return 0;
}

int gw_json_node_u64_dec(const gw_json_doc *doc, const gw_json_node *v,
                         uint64_t *out)
{
    size_t n = 0;
    const char *s;
    size_t i;
    uint64_t acc = 0;
    if (!v || v->type != GW_JSON_STRING) return -1;
    s = gw_json_str(doc, v, &n);
    if (!s || n == 0 || n > 20) return -1;
    for (i = 0; i < n; i++) {
        uint64_t d;
        if (s[i] < '0' || s[i] > '9') return -1;
        d = (uint64_t)(s[i] - '0');
        if (acc > (UINT64_MAX - d) / 10u) return -1;
        acc = acc * 10u + d;
    }
    *out = acc;
    return 0;
}

int gw_json_get_u64_dec(const gw_json_doc *doc, const gw_json_node *obj,
                        const char *key, uint64_t *out)
{
    const gw_json_node *v = gw_json_obj_get(doc, obj, key);
    return gw_json_node_u64_dec(doc, v, out);
}

/* ------------------------------------------------------------------ writer */

static void jw_fail(gw_json_writer *w) { w->err = 1; }

static void jw_ch(gw_json_writer *w, char c)
{
    if (w->err) return;
    if (w->len + 2 > w->cap) { jw_fail(w); return; }
    w->buf[w->len++] = c;
    w->buf[w->len] = 0;
}

static void jw_raw(gw_json_writer *w, const char *s, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) jw_ch(w, s[i]);
}

static void jw_esc(gw_json_writer *w, char e)
{
    jw_ch(w, '\\');
    jw_ch(w, e);
}

static void jw_prefix(gw_json_writer *w)
{
    int top;
    if (w->err) return;
    if (w->depth == 0) {
        if (w->root_written) { jw_fail(w); return; }
        w->root_written = 1;
        return;
    }
    top = w->depth - 1;
    if (w->st[top].is_obj) return; /* key() emitted the separator */
    if (!w->st[top].first) jw_ch(w, ',');
    w->st[top].first = 0;
}

void gw_jw_init(gw_json_writer *w, char *buf, size_t cap)
{
    memset(w, 0, sizeof *w);
    w->buf = buf;
    w->cap = cap;
    if (cap) buf[0] = 0;
}

int gw_jw_ok(const gw_json_writer *w) { return !w->err; }
size_t gw_jw_len(const gw_json_writer *w) { return w->len; }

static void jw_push(gw_json_writer *w, int is_obj)
{
    if (w->err) return;
    if (w->depth >= GW_JSON_MAX_WRITE_DEPTH) { jw_fail(w); return; }
    w->st[w->depth].is_obj = (uint8_t)(is_obj ? 1 : 0);
    w->st[w->depth].first = 1;
    w->depth++;
}

void gw_jw_begin_obj(gw_json_writer *w) { jw_prefix(w); jw_ch(w, '{'); jw_push(w, 1); }
void gw_jw_begin_arr(gw_json_writer *w) { jw_prefix(w); jw_ch(w, '['); jw_push(w, 0); }

void gw_jw_end_obj(gw_json_writer *w)
{
    if (w->err) return;
    if (w->depth <= 0 || !w->st[w->depth - 1].is_obj) { jw_fail(w); return; }
    w->depth--;
    jw_ch(w, '}');
}

void gw_jw_end_arr(gw_json_writer *w)
{
    if (w->err) return;
    if (w->depth <= 0 || w->st[w->depth - 1].is_obj) { jw_fail(w); return; }
    w->depth--;
    jw_ch(w, ']');
}

static void jw_str_body(gw_json_writer *w, const char *s, size_t n)
{
    static const char hx[] = "0123456789abcdef";
    size_t i;
    jw_ch(w, '"');
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
        case '"': jw_esc(w, '"'); break;
        case '\\': jw_esc(w, '\\'); break;
        case 0x08: jw_esc(w, 'b'); break;
        case 0x0C: jw_esc(w, 'f'); break;
        case 0x0A: jw_esc(w, 'n'); break;
        case 0x0D: jw_esc(w, 'r'); break;
        case 0x09: jw_esc(w, 't'); break;
        default:
            if (c < 0x20) {
                jw_ch(w, '\\');
                jw_ch(w, 'u');
                jw_ch(w, '0');
                jw_ch(w, '0');
                jw_ch(w, hx[c >> 4]);
                jw_ch(w, hx[c & 0x0F]);
            } else {
                jw_ch(w, (char)c);
            }
            break;
        }
    }
    jw_ch(w, '"');
}

void gw_jw_key(gw_json_writer *w, const char *key)
{
    if (w->err) return;
    if (w->depth <= 0 || !w->st[w->depth - 1].is_obj) { jw_fail(w); return; }
    if (!w->st[w->depth - 1].first) jw_ch(w, ',');
    w->st[w->depth - 1].first = 0;
    jw_str_body(w, key, strlen(key));
    jw_ch(w, ':');
}

void gw_jw_strn(gw_json_writer *w, const char *s, size_t n)
{
    jw_prefix(w);
    jw_str_body(w, s, n);
}

void gw_jw_str(gw_json_writer *w, const char *s) { gw_jw_strn(w, s, strlen(s)); }

static void jw_udec(gw_json_writer *w, uint64_t v)
{
    char tmp[24];
    int n = 0;
    if (v == 0) { jw_ch(w, '0'); return; }
    while (v > 0 && n < (int)sizeof tmp) {
        tmp[n++] = (char)('0' + (int)(v % 10u));
        v /= 10u;
    }
    while (n > 0) jw_ch(w, tmp[--n]);
}

void gw_jw_u32(gw_json_writer *w, uint32_t v)
{
    jw_prefix(w);
    jw_udec(w, (uint64_t)v);
}

void gw_jw_i64(gw_json_writer *w, int64_t v)
{
    jw_prefix(w);
    if (v < 0) {
        jw_ch(w, '-');
        jw_udec(w, (uint64_t)(-(v + 1)) + 1u);
    } else {
        jw_udec(w, (uint64_t)v);
    }
}

void gw_jw_u64dec_str(gw_json_writer *w, uint64_t v)
{
    jw_prefix(w);
    jw_ch(w, '"');
    jw_udec(w, v);
    jw_ch(w, '"');
}

void gw_jw_bool(gw_json_writer *w, int v)
{
    jw_prefix(w);
    if (v) jw_raw(w, "true", 4); else jw_raw(w, "false", 5);
}

void gw_jw_null(gw_json_writer *w) { jw_prefix(w); jw_raw(w, "null", 4); }

void gw_jw_raw_value(gw_json_writer *w, const char *json, size_t n)
{
    jw_prefix(w);
    jw_raw(w, json, n);
}

size_t gw_jw_finish(gw_json_writer *w)
{
    if (w->err || w->depth != 0 || !w->root_written) { w->err = 1; return 0; }
    if (w->len + 1 > w->cap) { w->err = 1; return 0; }
    w->buf[w->len] = 0;
    return w->len;
}