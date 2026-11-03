#include "spool.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#include <direct.h>
#include <io.h>
#include <sys/stat.h>
#else
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/statvfs.h>
#endif

static int flush_file(FILE *f){
    if(fflush(f))return -1;
#ifdef _WIN32
    return _commit(_fileno(f));
#else
    return fsync(fileno(f));
#endif
}
static int flush_directory(const char *path){
#ifdef _WIN32
    (void)path;return 0;
#else
    int fd=open(path,O_RDONLY|O_DIRECTORY),rc;if(fd<0)return -1;rc=fsync(fd);close(fd);return rc;
#endif
}
static int close_persist(FILE *file){int a=flush_file(file),b=fclose(file);return a||b;}

static void set_err(char *err, size_t errcap, const char *msg)
{
    if (err && errcap) snprintf(err, errcap, "%s", msg);
}

static int mkdir_one(const char *path)
{
#if defined(_WIN32)
    if (_mkdir(path) == 0) return 0;
#else
    if (mkdir(path, 0755) == 0) return 0;
#endif
    return (errno == EEXIST) ? 0 : -1;
}

static int path_exists(const char *path)
{
#if defined(_WIN32)
    return _access(path, 0) == 0;
#else
    return access(path, F_OK) == 0;
#endif
}

static uint64_t file_size(const char *path)
{
#if defined(_WIN32)
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return 0;
    return (uint64_t)st.st_size;
#else
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return (uint64_t)st.st_size;
#endif
}

static void make_path(const gw_spool *s, const char *name, char *out, size_t cap)
{
    (void)gw_path_join(s->events_dir, name, out, cap);
}

static void event_path(const gw_spool *s, uint64_t id, char *out, size_t cap)
{
    char num[21];
    char name[64];
    snprintf(name, sizeof name, "ev-%s.smc", gw_u64_dec(id, num));
    (void)gw_path_join(s->events_dir, name, out, cap);
}

static int tomb_find(const gw_spool *s, uint64_t id, unsigned *slot)
{
    unsigned i;
    for (i = 0; i < s->tomb_count; i++) {
        unsigned idx = (s->tomb_head + i) % GW_SPOOL_MAX_ACK_TOMBS;
        if (s->tombs[idx].event_id == id) {
            if (slot) *slot = idx;
            return 1;
        }
    }
    return 0;
}

static void tomb_add(gw_spool *s, uint64_t id, const char *sha)
{
    unsigned idx;
    if (s->tomb_count < GW_SPOOL_MAX_ACK_TOMBS) {
        idx = (s->tomb_head + s->tomb_count) % GW_SPOOL_MAX_ACK_TOMBS;
        s->tomb_count++;
    } else {
        idx = s->tomb_head;
        s->tomb_head = (s->tomb_head + 1u) % GW_SPOOL_MAX_ACK_TOMBS;
    }
    s->tombs[idx].event_id = id;
    snprintf(s->tombs[idx].sha256, sizeof s->tombs[idx].sha256, "%.64s", sha);
}

static int load_tombs(gw_spool *s)
{
    char path[GW_SPOOL_PATH_BYTES * 2];
    char idbuf[32], sha[80];
    FILE *f;
    (void)gw_path_join(s->root, "acked.txt", path, sizeof path);
    f = fopen(path, "rb");
    if (!f) return 0;
    for (;;) {
        uint64_t id = 0;
        if (fscanf(f, "%31s %64s", idbuf, sha) != 2) break;
        if (gw_parse_u64_dec(idbuf, strlen(idbuf), &id) != 0) continue;
        tomb_add(s, id, sha);
    }
    fclose(f);
    return 0;
}

static int append_tomb(gw_spool *s, uint64_t id, const char *sha)
{
    char path[GW_SPOOL_PATH_BYTES * 2];
    char num[21];
    FILE *f;
    (void)gw_path_join(s->root, "acked.txt", path, sizeof path);
    f = fopen(path, "ab");
    if (!f) return -1;
    fprintf(f, "%s %s\n", gw_u64_dec(id, num), sha);
    fclose(f);
    return 0;
}

static void save_times(gw_spool *s){
    char path[GW_SPOOL_PATH_BYTES*2],tmp[GW_SPOOL_PATH_BYTES*2];FILE*f;
    gw_path_join(s->root,"timestamps.txt",path,sizeof path);gw_path_join(s->root,"timestamps.tmp",tmp,sizeof tmp);
    f=fopen(tmp,"wb");if(!f)return;
    for(unsigned i=0;i<s->count;i++){char a[21],b[21];fprintf(f,"%s %s\n",gw_u64_dec(s->recs[i].event_id,a),gw_u64_dec(s->recs[i].created_unix_ms,b));}
    if(close_persist(f))return;
#if defined(_WIN32)
    _unlink(path);
#endif
    if(!rename(tmp,path))flush_directory(s->root);
}
static int save_index(gw_spool *s)
{
    char tmp[GW_SPOOL_PATH_BYTES * 2], final[GW_SPOOL_PATH_BYTES * 2];
    FILE *f;
    unsigned i;
    (void)gw_path_join(s->root, "index.tmp", tmp, sizeof tmp);
    (void)gw_path_join(s->root, "index.txt", final, sizeof final);
    f = fopen(tmp, "wb");
    if (!f) { s->spool_io_errors++; return -1; }
    for (i = 0; i < s->count; i++) {
        const gw_event_rec *r = &s->recs[i];
        char idb[21], tb[21], rb[21], fb[21], lb[21], cb[21];
        fprintf(f, "%s %s %s %s %s %s %u %u %u %s\n",
                gw_u64_dec(r->event_id, idb), r->sha256,
                gw_u64_dec(r->total_bytes, tb), gw_u64_dec(r->record_count, rb),
                gw_u64_dec(r->first_sample, fb), gw_u64_dec(r->last_sample, lb),
                r->flags, r->clip_reason, r->sample_rate_word,
                gw_u64_dec(r->created_ms, cb));
    }
    if (close_persist(f)) { s->spool_io_errors++; return -1; }
#if defined(_WIN32)
    _unlink(final);
#endif
    if (rename(tmp, final) != 0 || flush_directory(s->root)) { s->spool_io_errors++; return -1; }
    save_times(s);return 0;
}

static void sort_recs(gw_spool *s)
{
    unsigned i, j;
    for (i = 1; i < s->count; i++) {
        gw_event_rec tmp = s->recs[i];
        j = i;
        while (j > 0 && s->recs[j - 1].event_id > tmp.event_id) {
            s->recs[j] = s->recs[j - 1];
            j--;
        }
        s->recs[j] = tmp;
    }
}

static int load_index(gw_spool *s)
{
    char path[GW_SPOOL_PATH_BYTES * 2];
    FILE *f;
    (void)gw_path_join(s->root, "index.txt", path, sizeof path);
    f = fopen(path, "rb");
    if (!f) return 0;
    for (;;) {
        char idbuf[32], sha[80], totalb[32], recsb[32], firstb[32], lastb[32];
        char createdb[32];
        uint64_t id = 0, total = 0, recs = 0, first = 0, last = 0, created = 0;
        unsigned flags = 0, reason = 0, rate = 0;
        gw_event_rec *r;
        char evpath[GW_SPOOL_PATH_BYTES * 2];
        if (s->count >= GW_SPOOL_MAX_EVENTS) break;
        if (fscanf(f, "%31s %64s %31s %31s %31s %31s %u %u %u %31s",
                   idbuf, sha, totalb, recsb, firstb, lastb, &flags, &reason,
                   &rate, createdb) != 10) break;
        if (gw_parse_u64_dec(idbuf, strlen(idbuf), &id) != 0) break;
        if (gw_parse_u64_dec(totalb, strlen(totalb), &total) != 0) break;
        if (gw_parse_u64_dec(recsb, strlen(recsb), &recs) != 0) break;
        if (gw_parse_u64_dec(firstb, strlen(firstb), &first) != 0) break;
        if (gw_parse_u64_dec(lastb, strlen(lastb), &last) != 0) break;
        if (gw_parse_u64_dec(createdb, strlen(createdb), &created) != 0) break;
        event_path(s, id, evpath, sizeof evpath);
        if (!path_exists(evpath)) continue;
        if (!s->circular && tomb_find(s, id, NULL)) {
#if defined(_WIN32)
            _unlink(evpath);
#else
            unlink(evpath);
#endif
            continue;
        }
        r = &s->recs[s->count];
        memset(r, 0, sizeof *r);
        r->event_id = id;
        snprintf(r->sha256, sizeof r->sha256, "%.64s", sha);
        r->total_bytes = file_size(evpath);
        if (r->total_bytes == 0) r->total_bytes = total;
        r->record_count = recs;
        r->first_sample = first;
        r->last_sample = last;
        r->flags = flags;
        r->clip_reason = reason;
        r->sample_rate_word = rate;
        r->created_ms = created;
        s->used_bytes += r->total_bytes;
        s->count++;
    }
    fclose(f);
    sort_recs(s);
    return 0;
}

int gw_spool_init(gw_spool *s, const char *root, uint64_t limit_bytes,
                  char *err, size_t errcap)
{
    memset(s, 0, sizeof *s);
    if (!root || !*root) { set_err(err, errcap, "spool root required"); return -1; }
    snprintf(s->root, sizeof s->root, "%s", root);
    (void)gw_path_join(s->root, "events", s->events_dir, sizeof s->events_dir);
    s->limit_bytes = limit_bytes;
    s->circular = getenv("ECHO_EVENT_LOOP") && !strcmp(getenv("ECHO_EVENT_LOOP"),"1");
    if (mkdir_one(s->root) != 0 || mkdir_one(s->events_dir) != 0) {
        set_err(err, errcap, "cannot create spool directories");
        return -1;
    }
    load_tombs(s);
    load_index(s);
    {char path[GW_SPOOL_PATH_BYTES*2],a[32],b[32];FILE*f;gw_path_join(s->root,"timestamps.txt",path,sizeof path);f=fopen(path,"rb");
     if(f){while(fscanf(f,"%31s %31s",a,b)==2){uint64_t id=0,ms=0;if(!gw_parse_u64_dec(a,strlen(a),&id)&&!gw_parse_u64_dec(b,strlen(b),&ms))for(unsigned i=0;i<s->count;i++)if(s->recs[i].event_id==id)s->recs[i].created_unix_ms=ms;}fclose(f);}}
    for(unsigned i=0;i<s->count;i++){unsigned slot;if(tomb_find(s,s->recs[i].event_id,&slot))s->recs[i].acked=1;}
    return 0;
}

void gw_spool_close(gw_spool *s)
{
    (void)s;
}

const gw_event_rec *gw_spool_find(const gw_spool *s, uint64_t event_id)
{
    unsigned i;
    for (i = 0; i < s->count; i++)
        if (s->recs[i].event_id == event_id) return &s->recs[i];
    return NULL;
}

const gw_event_rec *gw_spool_at(const gw_spool *s, unsigned idx)
{
    return idx < s->count ? &s->recs[idx] : NULL;
}

unsigned gw_spool_count(const gw_spool *s) { return s->count; }

unsigned gw_spool_index_after(const gw_spool *s, uint64_t cursor)
{
    unsigned i;
    for (i = 0; i < s->count; i++)
        if (s->recs[i].event_id > cursor) return i;
    return s->count;
}

int gw_spool_is_acked(const gw_spool *s, uint64_t event_id, const char *sha256,
                      int *duplicate)
{
    unsigned slot = 0;
    if (duplicate) *duplicate = 0;
    if (!s || !sha256) return -1;
    if (tomb_find(s, event_id, &slot)) {
        if (strcmp(s->tombs[slot].sha256, sha256) != 0) return -2;
        if (duplicate) *duplicate = 1;
        return 0;
    }
    return -1;
}

static int remove_rec(gw_spool *s, unsigned idx);
static int disk_room(const gw_spool *s,uint64_t need){
#if !defined(_WIN32)
    struct statvfs st;if(statvfs(s->root,&st))return 0;
    return (uint64_t)st.f_bavail*st.f_frsize>=need+67108864ull;
#else
    (void)s;(void)need;return 1;
#endif
}
int gw_spool_writer_begin(gw_spool *s, const gw_smc1 *hdr, gw_spool_writer *w,
                          char *err, size_t errcap)
{
    uint64_t need;
    char name[GW_SPOOL_PATH_BYTES];
    memset(w, 0, sizeof *w);
    if (!s || !hdr) return -1;
    need = GW_SMC1_HEADER_BYTES + hdr->record_count * GW_SMC1_RECORD_BYTES;
    if (hdr->record_count == 0 || need > s->limit_bytes) {
        s->dropped_events++;
        s->dropped_bytes += need;
        set_err(err, errcap, "event larger than spool limit");
        return -3;
    }
    if (s->circular && (s->used_bytes + need > s->limit_bytes*9/10 || s->count >= GW_SPOOL_MAX_EVENTS || !disk_room(s,need))) {
        uint64_t target=s->limit_bytes*8/10;
        while(s->count && (s->used_bytes+need>target || s->count>=GW_SPOOL_MAX_EVENTS || !disk_room(s,need))) {
            unsigned oldest=0;
            while(oldest<s->count && s->recs[oldest].protected_until_ms>gw_clock_ms())oldest++;
            if(oldest==s->count)break;
            {uint64_t released=s->recs[oldest].total_bytes;
             if(remove_rec(s,oldest))break;
             s->used_bytes-=released;s->evicted_events++;save_index(s);}
        }
    }
    if (s->used_bytes + need > s->limit_bytes || s->count >= GW_SPOOL_MAX_EVENTS || (s->circular&&!disk_room(s,need))) {
        s->dropped_events++;
        s->dropped_bytes += need;
        set_err(err, errcap, "event spool full");
        return -3;
    }
    if (gw_spool_find(s, hdr->event_id)) {
        set_err(err, errcap, "duplicate event id");
        return -2;
    }
    w->spool = s;
    w->hdr = *hdr;
    w->need_bytes = need;
    {
        char num[21];
        snprintf(name, sizeof name, "ev-%s.smc", gw_u64_dec(hdr->event_id, num));
        make_path(s, name, w->final_path, sizeof w->final_path);
        {
            char tname[64];
            snprintf(tname, sizeof tname, ".tmp-%s.smc",
                     gw_u64_dec(hdr->event_id, num));
            (void)gw_path_join(s->events_dir, tname, w->tmp_path,
                               sizeof w->tmp_path);
        }
    }
    w->f = fopen(w->tmp_path, "wb");
    if (!w->f) { set_err(err, errcap, "cannot create spool file"); return -1; }
    gw_sha256_init(&w->hash);
    {
        uint8_t hbuf[GW_SMC1_HEADER_BYTES];
        gw_smc1_encode(hdr, hbuf);
        if (fwrite(hbuf, 1, sizeof hbuf, w->f) != sizeof hbuf) {
            w->failed = 1;
            set_err(err, errcap, "spool write failed");
            return -1;
        }
        gw_sha256_update(&w->hash, hbuf, sizeof hbuf);
        w->bytes = sizeof hbuf;
    }
    return 0;
}

int gw_spool_writer_write(gw_spool_writer *w, const void *data, size_t n)
{
    if (!w || !w->f || w->failed) return -1;
    if (w->bytes + n > w->need_bytes) { w->failed = 1; return -1; }
    if (fwrite(data, 1, n, w->f) != n) { w->failed = 1; return -1; }
    gw_sha256_update(&w->hash, data, n);
    w->bytes += n;
    return 0;
}

int gw_spool_writer_finish(gw_spool *s, gw_spool_writer *w, gw_event_rec *out,
                           char *err, size_t errcap)
{
    uint8_t digest[32];
    gw_event_rec *r;
    if (!s || !w || !w->f || w->failed) {
        if (w && w->f) { fclose(w->f); w->f = NULL; }
        if (w) {
#if defined(_WIN32)
            _unlink(w->tmp_path);
#else
            unlink(w->tmp_path);
#endif
        }
        set_err(err, errcap, "spool writer failed");
        return -1;
    }
    if (w->bytes != w->need_bytes) {
        fclose(w->f);
        w->f = NULL;
#if defined(_WIN32)
        _unlink(w->tmp_path);
#else
        unlink(w->tmp_path);
#endif
        set_err(err, errcap, "spool size mismatch");
        s->spool_io_errors++;
        return -1;
    }
    if (close_persist(w->f)) {
        w->f = NULL;
        s->spool_io_errors++;
        set_err(err, errcap, "spool close failed");
        return -1;
    }
    w->f = NULL;
#if defined(_WIN32)
    _unlink(w->final_path);
#endif
    if (rename(w->tmp_path, w->final_path) != 0 || flush_directory(s->events_dir)) {
        s->spool_io_errors++;
        set_err(err, errcap, "spool rename failed");
        return -1;
    }
    gw_sha256_final(&w->hash, digest);
    r = &s->recs[s->count++];
    memset(r, 0, sizeof *r);
    r->event_id = w->hdr.event_id;
    r->total_bytes = w->bytes;
    r->record_count = w->hdr.record_count;
    r->first_sample = w->hdr.first_sample;
    r->last_sample = w->hdr.last_sample;
    r->flags = w->hdr.flags;
    r->clip_reason = w->hdr.clip_reason;
    r->sample_rate_word = w->hdr.sample_rate_word;
    gw_sha256_hex(digest, r->sha256);
    r->created_ms = gw_clock_ms();
    if(time(NULL)>=1704067200)r->created_unix_ms=(uint64_t)time(NULL)*1000ull;
    s->used_bytes += r->total_bytes;
    sort_recs(s);
    if(save_index(s)) {
        unsigned at;
        for(at=0;at<s->count;at++)if(s->recs[at].event_id==w->hdr.event_id) {
            memmove(s->recs+at,s->recs+at+1,(s->count-at-1)*sizeof *s->recs);s->count--;s->used_bytes-=w->bytes;break;
        }
        set_err(err,errcap,"spool index persistence failed");return -1;
    }
    if(out){const gw_event_rec *saved=gw_spool_find(s,w->hdr.event_id);if(!saved)return -1;*out=*saved;}
    return 0;
}

void gw_spool_writer_abort(gw_spool_writer *w)
{
    if (!w) return;
    if (w->f) fclose(w->f);
    w->f = NULL;
    if (w->tmp_path[0]) {
#if defined(_WIN32)
        _unlink(w->tmp_path);
#else
        unlink(w->tmp_path);
#endif
    }
}

int gw_spool_read(const gw_spool *s, const gw_event_rec *rec, uint64_t offset,
                  void *dst, size_t n, char *err, size_t errcap)
{
    char path[GW_SPOOL_PATH_BYTES * 2];
    FILE *f;
    event_path(s, rec->event_id, path, sizeof path);
    if (offset > rec->total_bytes || n > rec->total_bytes - offset) {
        set_err(err, errcap, "read outside event file");
        return -1;
    }
#if defined(_WIN32)
    f = fopen(path, "rb");
#else
    f = fopen(path, "rb");
#endif
    if (!f) { set_err(err, errcap, "event file missing"); return -1; }
#if defined(_WIN32)
    if (_fseeki64(f, (__int64)offset, SEEK_SET) != 0) {
#else
    if (fseeko(f, (off_t)offset, SEEK_SET) != 0) {
#endif
        fclose(f);
        set_err(err, errcap, "seek failed");
        return -1;
    }
    if (fread(dst, 1, n, f) != n) {
        fclose(f);
        set_err(err, errcap, "short read");
        return -1;
    }
    fclose(f);
    return 0;
}

static int remove_rec(gw_spool *s, unsigned idx)
{
    char path[GW_SPOOL_PATH_BYTES * 2];
    event_path(s, s->recs[idx].event_id, path, sizeof path);
#if defined(_WIN32)
    if (_unlink(path) != 0) {s->spool_io_errors++;return -1;}
#else
    if (unlink(path) != 0) {s->spool_io_errors++;return -1;}
#endif
    memmove(&s->recs[idx], &s->recs[idx + 1],
            (s->count - idx - 1) * sizeof s->recs[0]);
    s->count--;
    return 0;
}

int gw_spool_ack(gw_spool *s, uint64_t event_id, const char *sha256,
                 int *duplicate, char *err, size_t errcap)
{
    const gw_event_rec *found;
    unsigned idx, slot = 0;
    if (duplicate) *duplicate = 0;
    if (tomb_find(s, event_id, &slot)) {
        if (strcmp(s->tombs[slot].sha256, sha256) != 0) {
            set_err(err, errcap, "ack sha256 mismatch for acked event");
            return -2;
        }
        if (duplicate) *duplicate = 1;
        return 0;
    }
    found = gw_spool_find(s, event_id);
    if (!found) { set_err(err, errcap, "unknown event"); return -1; }
    if (strcmp(found->sha256, sha256) != 0) {
        set_err(err, errcap, "ack sha256 mismatch");
        return -2;
    }
    if(s->circular){
        idx=(unsigned)(found-s->recs);
        if(duplicate)*duplicate=found->acked;
        if(!found->acked){tomb_add(s,event_id,sha256);append_tomb(s,event_id,sha256);}
        s->recs[idx].acked=1;
        save_index(s);return 0;
    }
    idx = (unsigned)(found - s->recs);
    {uint64_t released=found->total_bytes;if(remove_rec(s,idx))return -1;s->used_bytes-=released;}
    tomb_add(s, event_id, sha256);
    append_tomb(s, event_id, sha256);
    save_index(s);
    return 0;
}

int gw_spool_discard(gw_spool *s, uint64_t event_id, char *err, size_t errcap)
{
    const gw_event_rec *found = gw_spool_find(s, event_id);
    unsigned idx;
    if (!found) { set_err(err, errcap, "unknown event"); return -1; }
    idx = (unsigned)(found - s->recs);
    {uint64_t released=found->total_bytes;if(remove_rec(s,idx))return -1;s->used_bytes-=released;s->dropped_bytes+=released;}
    s->dropped_events++;
    /* File removal succeeded before counters and index are committed. */
    save_index(s);
    return 0;
}
