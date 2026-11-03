/* Device-only orchestration. No CPU FFT/filter/correlation/acoustic estimates.
 */
#include "feature_runtime.h"
#include "fc_capture.h"
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FX_JOBS 8
#define FX_MAX_WORDS (6u * 1024u * 1024u)
#define FX_BASE 1048576u
#define FX_TABLE 525312u
#define FX_OUT (FX_BASE + 8192u)

typedef struct {
  int used, kind, step, cancel, exclusive, refs, role, staged, stage, stages,
      prep, observations, needed, capture_channels, restore_step,
      reference_held, excitation_detected;
  uint64_t id, began, deadline;
  uint32_t generation, channel, count, capacity, session, config, frame,
      last_sequence, last_observation, executed_instructions;
  uint32_t *data, *input, input_count, input_need, input_offset, output,
      output_count, program_version;
  uint32_t restore[32], wanted[32];
  char feature[64], state[24], error[160], plan_file[512], main_file[512],
      reference[64];
  char owner_session[65];
  const gw_json_node *definition;
  gw_json_doc plan, params;
  fc_provenance provenance;
  fc_raw_reader reader;
  uint64_t frame_samples[16];
} fx_job;

typedef struct {
  gw_json_doc registry;
  char directory[512];
  uint64_t counter;
  fx_job jobs[FX_JOBS];
  fx_job *active;
  int internal_config;
  uint64_t p1_requested_ms[16];
} fx_manager;

static const gw_json_node *member(const gw_json_doc *d, const gw_json_node *n,
                                  const char *k) {
  return gw_json_obj_get(d, n, k);
}
static uint32_t number(const gw_json_doc *d, const gw_json_node *n,
                       const char *k, uint32_t fallback) {
  uint32_t v;
  return gw_json_get_u32(d, n, k, &v) ? fallback : v;
}
static int boolean(const gw_json_doc *d, const gw_json_node *n, const char *k) {
  int v = 0;
  (void)gw_json_get_bool(d, n, k, &v);
  return v;
}
static const char *string(const gw_json_doc *d, const gw_json_node *n,
                          const char *k) {
  const gw_json_node *v = member(d, n, k);
  return v ? gw_json_str(d, v, NULL) : NULL;
}
static int nonblank(const char *text) {
  if (!text)
    return 0;
  for (; *text; ++text)
    if (!isspace((unsigned char)*text))
      return 1;
  return 0;
}
static int reference_matches(gw *g, fx_job *j, fx_job *reference) {
  if (!reference || !reference->role || strcmp(reference->state, "completed") ||
      reference->channel != j->channel ||
      reference->provenance.session != g->config_active_words[0] ||
      reference->provenance.sample_rate != sm_word_float(g->snap.word[31]))
    return 0;
  if (!strcmp(j->feature, "relative_insulation"))
    return !strcmp(reference->feature, "relative_insulation") &&
           reference->count == 9;
  return (!strcmp(reference->feature, "spectrum_freeze") ||
          !strcmp(reference->feature, "relative_limit")) &&
         reference->count == 1025;
}
static int private_capture_channel(fx_job *j, const char *key) {
  return !strcmp(key, "channel") && (!strcmp(j->feature, "spectrum_freeze") ||
                                     !strcmp(j->feature, "relative_limit"));
}
static void copy_text(char *out, size_t cap, const char *value) {
  size_t n;
  if (!cap)
    return;
  if (!value)
    value = "";
  n = strlen(value);
  if (n >= cap)
    n = cap - 1;
  memmove(out, value, n);
  out[n] = 0;
}
static void json_value(gw_json_writer *w, const gw_json_doc *d,
                       const gw_json_node *n) {
  const gw_json_node *c;
  char value[64];
  size_t len;
  if (!n) {
    gw_jw_null(w);
    return;
  }
  if (n->type == GW_JSON_OBJECT) {
    gw_jw_begin_obj(w);
    for (c = n->child; c; c = c->next) {
      const char *k = gw_json_key(d, c, &len);
      char key[256];
      if (!k || len >= sizeof key) {
        w->err = 1;
        return;
      }
      memcpy(key, k, len);
      key[len] = 0;
      gw_jw_key(w, key);
      json_value(w, d, c);
    }
    gw_jw_end_obj(w);
  } else if (n->type == GW_JSON_ARRAY) {
    gw_jw_begin_arr(w);
    for (c = n->child; c; c = c->next)
      json_value(w, d, c);
    gw_jw_end_arr(w);
  } else if (n->type == GW_JSON_STRING) {
    const char *s = gw_json_str(d, n, &len);
    gw_jw_strn(w, s, len);
  } else if (n->type == GW_JSON_BOOL)
    gw_jw_bool(w, n->boolean);
  else if (n->type == GW_JSON_NUMBER) {
    snprintf(value, sizeof value, "%.17g", n->number);
    gw_jw_raw_value(w, value, strlen(value));
  } else
    gw_jw_null(w);
}
static int load_json(const char *file, gw_json_doc *doc) {
  FILE *f = fopen(file, "rb");
  long n;
  char *data, error[160];
  int rc;
  if (!f)
    return -1;
  if (fseek(f, 0, SEEK_END) || (n = ftell(f)) < 1 || n > 16 * 1024 * 1024 ||
      fseek(f, 0, SEEK_SET)) {
    fclose(f);
    return -1;
  }
  data = malloc((size_t)n);
  if (!data) {
    fclose(f);
    return -1;
  }
  if (fread(data, 1, (size_t)n, f) != (size_t)n) {
    free(data);
    fclose(f);
    return -1;
  }
  fclose(f);
  gw_json_doc_init(doc);
  rc = gw_json_parse(doc, data, (size_t)n, 40, 250000, error, sizeof error);
  free(data);
  return rc;
}
static int path_for(fx_manager *m, const char *relative, char *out,
                    size_t size) {
  size_t i;
  if (!relative || strstr(relative, "..") || relative[0] == '/' ||
      strchr(relative, ':'))
    return -1;
  if (strlen(m->directory) + strlen(relative) + 2 >= size)
    return -1;
  i = strlen(m->directory);
  memcpy(out, m->directory, i);
  out[i++] = '/';
  memcpy(out + i, relative, strlen(relative) + 1);
  for (i = 0; out[i]; i++)
    if (out[i] == '\\')
      out[i] = '/';
  return 0;
}
static fx_job *find_job(fx_manager *m, const char *id) {
  unsigned i;
  uint64_t value = 0;
  if (!id || strncmp(id, "feature-", 8) ||
      gw_parse_u64_dec(id + 8, strlen(id + 8), &value))
    return NULL;
  for (i = 0; i < FX_JOBS; i++)
    if (m->jobs[i].used && m->jobs[i].id == value)
      return m->jobs + i;
  return NULL;
}
static void release_job(fx_job *j) {
  free(j->data);
  free(j->input);
  gw_json_doc_free(&j->plan);
  gw_json_doc_free(&j->params);
  memset(j, 0, sizeof *j);
}
static int terminal(const fx_job *j) {
  return !strcmp(j->state, "completed") || !strcmp(j->state, "failed") ||
         !strcmp(j->state, "canceled");
}
void echo_features_owner_closed(gw*g,const char*session){
 fx_manager*m=g->features;if(!m||!session||!session[0])return;
 for(unsigned i=0;i<FX_JOBS;i++)if(m->jobs[i].used&&!strcmp(m->jobs[i].owner_session,session)) {
   if(!terminal(&m->jobs[i]))m->jobs[i].cancel=1;
   m->jobs[i].owner_session[0]=0; /* orphaned references become recyclable */
 }
}
static fx_job *new_job(fx_manager *m) {
  unsigned i;
  fx_job *old = NULL;
  for (i = 0; i < FX_JOBS; i++) {
    fx_job *j = m->jobs + i;
    if (!j->used)
      return j;
    /* The panel reads levels every second. Prefer recycling those short reads
     * instead of evicting a completed P2 result before its pages are fetched. */
    if (terminal(j) && !j->refs && (strcmp(j->state,"completed") || !j->role || !j->owner_session[0]) &&
        (!old || (j->kind <= 2 && old->kind > 2) ||
         ((j->kind <= 2) == (old->kind <= 2) && j->began < old->began)))
      old = j;
  }
  if (old)
    release_job(old);
  return old;
}
static int allocate_result(fx_job *j, uint32_t words) {
  if (words > FX_MAX_WORDS)
    return -1;
  if (j->capacity < words) {
    uint32_t *p = realloc(j->data, 4ull * words);
    if (!p)
      return -1;
    j->data = p;
    j->capacity = words;
  }
  return 0;
}
static void fail(fx_job *j, const char *why) {
  copy_text(j->error, sizeof j->error, why);
  copy_text(j->state, sizeof j->state, "failed");
}
static void drop_reference(fx_manager *m, fx_job *j) {
  if (j->reference_held) {
    fx_job *reference = find_job(m, j->reference);
    if (reference && reference->refs > 0)
      reference->refs--;
    j->reference_held = 0;
  }
}
static void finish(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  drop_reference(m, j);
  copy_text(j->state, sizeof j->state, j->cancel ? "canceled" : "completed");
  /* Replace reference A only after a new A really completed. An invalid or
   * canceled request must not invalidate the previous usable reference. */
  if(j->role&&!j->cancel&&j->owner_session[0]) for(unsigned k=0;k<FX_JOBS;k++) {
    fx_job *old=m->jobs+k;
    if(old!=j&&old->used&&old->role&&!old->refs&&terminal(old)&&
       !strcmp(old->feature,j->feature)&&!strcmp(old->owner_session,j->owner_session))
      old->owner_session[0]=0;
  }
  if (m->active == j)
    m->active = NULL;
  if (j->exclusive) {
    gw_arb_pending_dec(&g->arb);
    j->exclusive = 0;
  }
}
static void abandon(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  drop_reference(m, j);
  if (m->active == j)
    m->active = NULL;
  if (j->exclusive) {
    gw_arb_pending_dec(&g->arb);
    j->exclusive = 0;
  }
}

int echo_features_init(gw *g, const char *file, char *error, size_t size) {
  fx_manager *m;
  const gw_json_node *features;
  char *slash;
  if (!file || !file[0])
    return 0;
  m = calloc(1, sizeof *m);
  if (!m)
    return -1;
  if (load_json(file, &m->registry)) {
    free(m);
    snprintf(error, size, "feature registry cannot be loaded");
    return -1;
  }
  features = member(&m->registry, gw_json_root(&m->registry), "features");
  if (gw_json_arr_count(features) != 51) {
    gw_json_doc_free(&m->registry);
    free(m);
    snprintf(error, size, "exactly51 nonDOA feature definitions required");
    return -1;
  }
  copy_text(m->directory, sizeof m->directory, file);
  slash = strrchr(m->directory, '/');
  if (!slash)
    slash = strrchr(m->directory, '\\');
  if (slash)
    *slash = 0;
  else
    strcpy(m->directory, ".");
  g->features = m;
  return 0;
}
void echo_features_free(gw *g) {
  fx_manager *m;
  if (!g)
    return;
  m = g->features;
  unsigned i;
  if (!m)
    return;
  for (i = 0; i < FX_JOBS; i++)
    if (m->jobs[i].used)
      release_job(m->jobs + i);
  gw_json_doc_free(&m->registry);
  free(m);
  g->features = NULL;
}
int echo_features_busy(gw *g) {
  fx_manager *m = g->features;
  return m && m->active;
}
int echo_features_internal_config(gw *g) {
  fx_manager *m = g->features;
  return m && m->internal_config;
}

static void describe_job(gw *g, fx_job *j, gw_json_writer *w) {
  char id[40], digits[21];
  snprintf(id, sizeof id, "feature-%s", gw_u64_dec(j->id, digits));
  gw_jw_key(w, "jobId");
  gw_jw_str(w, id);
  gw_jw_key(w, "featureId");
  gw_jw_str(w, j->feature);
  gw_jw_key(w, "state");
  gw_jw_str(w, j->state);
  gw_jw_key(w, "sourceKind");
  gw_jw_str(w, g->cfg.mock_fixture ? "test-fixture" : "pl-live");
  gw_jw_key(w, "configuration");
  gw_jw_begin_obj(w);
  gw_jw_key(w, "session");
  gw_jw_u32(w, j->session);
  gw_jw_key(w, "config");
  gw_jw_u32(w, j->config);
  gw_jw_key(w, "generation");
  gw_jw_u64dec_str(w, j->generation);
  gw_jw_key(w, "sourceFrame");
  gw_jw_u64dec_str(w, j->frame);
  gw_jw_end_obj(w);
  gw_jw_key(w, "progress");
  gw_jw_begin_obj(w);
  gw_jw_key(w, "completedStages");
  gw_jw_u32(w, !j->staged && j->needed > 1 ? (uint32_t)j->observations : (uint32_t)j->stage);
  gw_jw_key(w, "totalStages");
  gw_jw_u32(w, !j->staged && j->needed > 1 ? (uint32_t)j->needed : (uint32_t)j->stages);
  gw_jw_key(w, "capturedSamples");
  gw_jw_u32(w, j->input_count);
  gw_jw_key(w, "requiredSamples");
  gw_jw_u32(w, j->input_need);
  gw_jw_key(w, "executedInstructions");
  gw_jw_u32(w, j->executed_instructions);
  gw_jw_key(w, "excitationDetected");
  gw_jw_bool(w, j->excitation_detected);
  gw_jw_key(w, "phase");
  gw_jw_str(w, j->step == 13 ? "capturing" :
               j->step == 21 ? "computing" :
               j->step >= 30 && j->step <= 31 ? "restoring" :
               j->exclusive ? "preparing" : "reading");
  gw_jw_end_obj(w);
  if (j->error[0]) {
    gw_jw_key(w, "error");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "code");
    gw_jw_str(w, "io_error");
    gw_jw_key(w, "reason");
    gw_jw_str(w, j->error);
    gw_jw_end_obj(w);
  }
}
static int validate_token(gw *g, const gw_json_doc *d, const gw_json_node *a) {
  char token[65];
  return !gw_json_get_str(d, a, "controlToken", token, sizeof token, NULL) &&
         gw_arb_can_write(&g->arb, token);
}
static const gw_json_node *find_definition(fx_manager *m, const char *id) {
  const gw_json_node *f = member(&m->registry, gw_json_root(&m->registry),
                                 "features"),
                     *n;
  for (n = f->child; n; n = n->next) {
    const char *s = string(&m->registry, n, "featureId");
    if (s && !strcmp(s, id))
      return n;
  }
  return NULL;
}
static int same_value(const gw_json_doc *a, const gw_json_node *x,
                      const gw_json_doc *b, const gw_json_node *y) {
  char ca[4096], cb[4096];
  gw_json_writer wa, wb;
  gw_jw_init(&wa, ca, sizeof ca);
  gw_jw_init(&wb, cb, sizeof cb);
  json_value(&wa, a, x);
  json_value(&wb, b, y);
  return gw_jw_finish(&wa) && gw_jw_finish(&wb) && !strcmp(ca, cb);
}
static int control_parameter(const char *k) {
  return !strcmp(k, "frames") || !strcmp(k, "channels") ||
         !strcmp(k, "referenceJobId") || !strcmp(k, "stimulus") ||
         !strcmp(k, "confirmed") || !strcmp(k, "action") ||
         !strcmp(k, "testSignalConfirmed") || !strcmp(k, "referenceOffsetDb") ||
         !strcmp(k, "calibrationSource") || !strcmp(k, "referenceConfirmed") ||
         !strcmp(k, "timeResponse");
}
static int choose_plan(fx_manager *m, fx_job *j, const gw_json_doc *d,
                       const gw_json_node *params) {
  const gw_json_node *rules = member(&m->registry, j->definition, "params"), *v,
                     *variants =
                         member(&m->registry, j->definition, "variants"),
                     *selected = NULL;
  const char *mode = string(&m->registry, j->definition, "mode");
  char key[128];
  size_t n;
  int different = 0;
  if (params)
    for (v = params->child; v; v = v->next) {
      const char *k = gw_json_key(d, v, &n);
      const gw_json_node *r;
      if (!k || n >= sizeof key)
        return -1;
      memcpy(key, k, n);
      key[n] = 0;
      if(!strcmp(key,"framePolicy") && (!strcmp(j->feature,"fft")||!strcmp(j->feature,"levels_core")||!strcmp(j->feature,"levels_extended"))){
        const char *policy=gw_json_str(d,v,NULL);if(!policy||(strcmp(policy,"latest")&&strcmp(policy,"transient")))return -1;continue;
      }
      if(!strcmp(key,"component")&&!strcmp(j->feature,"fft")){
        const char *component=gw_json_str(d,v,NULL);if(!component||(strcmp(component,"amplitude")&&strcmp(component,"power")&&strcmp(component,"psd")))return -1;continue;
      }
      if (control_parameter(key) && !member(&m->registry, rules, key))
        return -1;
      if (control_parameter(key) || private_capture_channel(j, key) ||
          (!strcmp(j->feature, "io_pcm") && !strcmp(key, "samples")) ||
          (!strcmp(j->feature, "directed_das") &&
           (!strcmp(key, "azimuth_deg") || !strcmp(key, "elevation_deg"))))
        continue;
      if (!strcmp(key, "channel") && mode && !strcmp(mode, "p0"))
        continue;
      r = member(&m->registry, rules, key);
      if (!r)
        return -1;
      if (!same_value(d, v, &m->registry, member(&m->registry, r, "default")))
        different = 1;
    }
  if (different) {
    for (v = variants ? variants->child : NULL; v; v = v->next) {
      const gw_json_node *complete = member(&m->registry, v, "completeParams"),
                         *p;
      int match = 1;
      for (p = params ? params->child : NULL; p; p = p->next) {
        const char *k = gw_json_key(d, p, &n);
        if (!k || n >= sizeof key) {
          match = 0;
          break;
        }
        memcpy(key, k, n);
        key[n] = 0;
        if (control_parameter(key) || private_capture_channel(j, key) ||
            (!strcmp(j->feature, "io_pcm") && !strcmp(key, "samples")) ||
            (!strcmp(j->feature, "directed_das") &&
             (!strcmp(key, "azimuth_deg") || !strcmp(key, "elevation_deg"))))
          continue;
        if (!same_value(d, p, &m->registry,
                        member(&m->registry, complete, key))) {
          match = 0;
          break;
        }
      }
      if (match) {
        selected = v;
        break;
      }
    }
    if (!selected)
      return -1;
  }
  {
    const gw_json_node *plan =
        selected ? selected
                 : member(&m->registry, j->definition, "executionPlan");
    const char *file = string(&m->registry, plan, "file");
    if (path_for(m, file, j->plan_file, sizeof j->plan_file))
      return -1;
  }
  copy_text(j->main_file, sizeof j->main_file, j->plan_file);
  if (load_json(j->plan_file, &j->plan))
    return -1;
  return different;
}
static int internal_commit(gw *g, fx_job *j, uint32_t *words) {
  fx_manager *m = g->features;
  const char *reason = "";
  uint32_t bad;
  int rc;
  if (!g->cfg.mock_fixture && (!g->cfg.allow_config_commit ||
                               (words[14] && !g->cfg.allow_event_capture)))
    return -1;
  if (g->pending_config)
    return 1;
  if (g->active_config_version == 0xffffffffu)
    return -1;
  words[SM_C_VERSION] = g->active_config_version + 1;
  if (gw_config_validate(g, words, &bad, &reason))
    return -1;
  m->internal_config = 1;
  rc = echo_prepare_config(g, words, &reason);
  m->internal_config = 0;
  if (rc)
    return -1;
  if (sm_commit_config(&g->mmio->dev, words) != SM_OK)
    return -1;
  memcpy(g->pending_config_words, words, 128);
  g->pending_config = 1;
  g->pending_config_version = words[1];
  g->pending_config_job = 0;
  g->pending_config_deadline_ms = g->now_ms + 10000;
  memcpy(j->wanted, words, 128);
  return 0;
}
static int config_ready(gw *g, fx_job *j) {
  if (g->pending_config)
    return 0;
  return g->active_config_version == j->wanted[1] && g->config_active_known
             ? 1
             : -1;
}
static int private_write(gw *g, uint32_t offset, const uint32_t *words,
                         uint32_t count) {
  if (!g->mmio->write_feature || g->pending_config ||
      (g->config_active_words[8] & 3u))
    return -1;
  if (!((offset >= FX_BASE && (uint64_t)offset + count <= 4194304u) ||
        (offset >= FX_TABLE && (uint64_t)offset + count <= FX_TABLE + 64u)))
    return -1;
  return g->mmio->write_feature(g->mmio->mem.ctx, 0x10000000u + 4 * offset,
                                words, count);
}
static int clear_plan(gw *g, const gw_json_doc *d, const gw_json_node *root) {
  uint32_t zero[1024] = {0};
  const gw_json_node *r = member(d, root, "privateClearRanges"), *v;
  if (!r) {
    r = member(d, root, "initialClearRange");
    if (r) {
      uint32_t off = number(d, r, "wordOffset", 0),
               n = number(d, r, "wordCount", 0);
      while (n) {
        uint32_t k = n > 1024 ? 1024 : n;
        if (private_write(g, off, zero, k))
          return -1;
        off += k;
        n -= k;
      }
    }
    return 0;
  }
  for (v = r->child; v; v = v->next) {
    uint32_t off = number(d, v, "wordOffset", 0),
             n = number(d, v, "wordCount", 0);
    while (n) {
      uint32_t k = n > 1024 ? 1024 : n;
      if (private_write(g, off, zero, k))
        return -1;
      off += k;
      n -= k;
    }
  }
  return 0;
}
static int patch_plan(gw *g, fx_manager *m, const gw_json_doc *d,
                      const gw_json_node *root) {
  char path[1024], expected[65], actual[65];
  FILE *f;
  long size;
  unsigned char *blob;
  size_t at = 0;
  uint8_t digest[32];
  int ok = 0;
  if (path_for(m, string(d, root, "patchFile"), path, sizeof path) ||
      gw_json_get_str(d, root, "patchSHA256", expected, sizeof expected, NULL))
    return -1;
  f = fopen(path, "rb");
  if (!f)
    return -1;
  if (fseek(f, 0, SEEK_END) || (size = ftell(f)) < 8 ||
      size > 64 * 1024 * 1024 || fseek(f, 0, SEEK_SET)) {
    fclose(f);
    return -1;
  }
  blob = malloc((size_t)size);
  if (!blob) {
    fclose(f);
    return -1;
  }
  if (fread(blob, 1, (size_t)size, f) != (size_t)size) {
    free(blob);
    fclose(f);
    return -1;
  }
  fclose(f);
  gw_sha256(blob, (size_t)size, digest);
  gw_sha256_hex(digest, actual);
  if (strcmp(actual, expected)) {
    free(blob);
    return -1;
  }
  /* Validate complete immutable patch before the first DDR write. */
  while (at + 8 <= (size_t)size) {
    uint32_t off = sma_get_u32(blob + at), n = sma_get_u32(blob + at + 4);
    at += 8;
    if (!n) {
      ok = off == 0 && at == (size_t)size;
      break;
    }
    if (4ull * n > (size_t)size - at ||
        !((off >= FX_BASE && (uint64_t)off + n <= 4194304u) ||
          (off >= FX_TABLE && (uint64_t)off + n <= FX_TABLE + 64u)))
      break;
    at += 4ull * n;
  }
  if (!ok) {
    free(blob);
    return -1;
  }
  at = 0;
  for (;;) {
    uint32_t off = sma_get_u32(blob + at), n = sma_get_u32(blob + at + 4);
    at += 8;
    if (!n)
      break;
    while (n) {
      uint32_t words[1024], k = n > 1024 ? 1024 : n, i;
      for (i = 0; i < k; i++)
        words[i] = sma_get_u32(blob + at + 4 * i);
      if (private_write(g, off, words, k)) {
        free(blob);
        return -1;
      }
      at += 4ull * k;
      off += k;
      n -= k;
    }
  }
  free(blob);
  return 0;
}
static int read_memory(gw *g, uint32_t offset, uint32_t *data, uint32_t n) {
  sm_memory *m = &g->mmio->mem;
  uint64_t address = 0x10000000ull + 4ull * offset;
  if (address + 4ull * n > m->reserved_high || address < m->reserved_low)
    return -1;
  if (m->invalidate(m->ctx, (uint32_t)address, 4 * n))
    return -1;
  m->barrier(m->ctx);
  return m->read(m->ctx, (uint32_t)address, data, n);
}
static int rekey_p2(gw *g, fx_job *j, uint32_t config) {
  uint32_t d[64];
  unsigned slot;
  if (read_memory(g, FX_TABLE, d, 64))
    return -1;
  for (slot = 0; slot < 4; slot++) {
    if (d[slot * 16] != 0x414c5531u)
      return -1;
    d[slot * 16 + 9] = 512;
    d[slot * 16 + 11] = g->config_active_words[0];
    d[slot * 16 + 12] = config;
    d[slot * 16 + 14] = j->generation;
  }
  return private_write(g, FX_TABLE, d, 64);
}

static int replace_plan(fx_job *j, const char *file) {
  if (!file || strlen(file) >= sizeof j->plan_file)
    return -1;
  gw_json_doc_free(&j->plan);
  copy_text(j->plan_file, sizeof j->plan_file, file);
  return load_json(file, &j->plan);
}
static int read_p1(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  const gw_json_node *route =
      member(&m->registry, j->definition, "defaultP1Route");
  sm_service_result h;
  uint32_t out, n;
  int rc;
  if (j->role || !strcmp(j->feature, "relative_insulation")) {
    out = 706496;
    n = 10;
  } else {
    out = number(&m->registry, route, "output", 0);
    n = number(&m->registry, route, "output_words", 0);
  }
  if (!out || !n || allocate_result(j, n))
    return -1;
  for(unsigned i=0;i<g->service_route_count&&i<16;i++)
    if(g->service_routes[i].address==0x10000000u+4*out)m->p1_requested_ms[i]=g->now_ms;
  rc = sm_copy_service(&g->mmio->mem, 0x10000000u + 4 * out, n,
                       g->config_active_words[0], g->active_config_version,
                       j->data, &h, 2);
  if (rc)
    return rc == SM_IO ? -1 : 1;
  if (h.word[4] != 1 || h.word[5] != 1 || h.word[10] != n)
    return 1;
  j->count = j->role ? 9 : n;
  j->session = h.word[2];
  j->config = h.word[3];
  j->frame = h.word[6];
  j->generation = h.word[4];
  j->provenance.session = h.word[2];
  j->provenance.config = h.word[3];
  j->provenance.frame = h.word[6];
  j->provenance.first_sample = sm_join_u64(h.word[7], h.word[8]);
  j->provenance.sample_rate = sm_word_float(g->snap.word[31]);
  return 0;
}
static int capture_into_job(gw *g, fx_job *j) {
  static uint32_t records[4096 * 8];
  uint32_t count = 0, i, ch;
  fc_provenance p;
  int rc = fc_raw_poll(g, &j->reader, records, 4096, &count, &p);
  if (rc == -1)
    return -1;
  if (p.gap)
    return -1;
  if (rc || !count)
    return 1;
  if (j->input_count == 0)
    j->provenance = p;
  if (count > j->input_need - j->input_count)
    count = j->input_need - j->input_count;
  if (j->kind == 6) {
    for (ch = 0; ch < (unsigned)j->capture_channels; ch++)
      for (i = 0; i < count; i++)
        j->data[ch * j->input_need + j->input_count + i] =
            records[i * 8 + (j->capture_channels == 6 ? ch : j->channel)];
  } else
    for (i = 0; i < count; i++)
      j->input[j->input_count + i] = records[i * 8 + j->channel];
  j->input_count += count;
  j->provenance.last_sample = p.first_sample + count - 1;
  j->session = p.session;
  j->config = p.config;
  if (j->kind == 6)
    j->generation = j->reader.generation;
  return j->input_count == j->input_need ? 0 : 1;
}
static int input_write(gw *g, fx_job *j, uint32_t offset, const uint32_t *data,
                       uint32_t words) {
  (void)j;
  while (words) {
    uint32_t n = words > 1024 ? 1024 : words;
    if (private_write(g, offset, data, n))
      return -1;
    offset += n;
    data += n;
    words -= n;
  }
  return 0;
}
static int start_program(gw *g, fx_job *j) {
  uint32_t cfg[32];
  const gw_json_node *root = gw_json_root(&j->plan),
                     *service = member(&j->plan, root, "service");
  memcpy(cfg, g->config_active_words, 128);
  cfg[8] = (cfg[8] & ~7u) | SM_P2_ENABLE | SM_PAUSE_P1;
  cfg[7] = FX_TABLE;
  cfg[31] = j->needed > 1 ? 0 : 1;
  cfg[14] = 0;
  if (g->active_config_version == 0xffffffffu ||
      rekey_p2(g, j, g->active_config_version + 1))
    return -1;
  j->output = number(&j->plan, service, "output", FX_OUT);
  j->program_version = 1;
  {
    uint32_t d[16];
    if (read_memory(g, FX_TABLE, d, 16))
      return -1;
    j->program_version = d[13];
  }
  if (internal_commit(g, j, cfg))
    return -1;
  j->config = cfg[1];
  j->session = cfg[0];
  j->last_sequence = 0;
  j->last_observation = 0;
  j->observations = 0;
  copy_text(j->state, sizeof j->state, "running");
  j->step = 21;
  return 0;
}
static int load_stage_weight(gw *g, fx_manager *m, const gw_json_doc *d,
                             const gw_json_node *stage) {
  const gw_json_node *weight = member(d, stage, "weightPage");
  char relative[512], path[1024], expected[65], actual[65];
  unsigned char *data;
  uint8_t digest[32];
  FILE *f;
  uint32_t n, off, i;
  if (!weight || weight->type == GW_JSON_NULL)
    return 0;
  n = number(d, weight, "wordCount", 0);
  off = number(d, weight, "wordOffset", 0);
  if (!n || n > 1000000 || !boolean(d, weight, "materialized") ||
      !string(d, weight, "file"))
    return -1;
  snprintf(relative, sizeof relative, "plans/%s", string(d, weight, "file"));
  if (path_for(m, relative, path, sizeof path) ||
      gw_json_get_str(d, weight, "sha256", expected, sizeof expected, NULL))
    return -1;
  f = fopen(path, "rb");
  if (!f)
    return -1;
  data = malloc(4ull * n);
  if (!data) {
    fclose(f);
    return -1;
  }
  if (fread(data, 4, n, f) != n || fgetc(f) != EOF) {
    free(data);
    fclose(f);
    return -1;
  }
  fclose(f);
  gw_sha256(data, 4ull * n, digest);
  gw_sha256_hex(digest, actual);
  if (strcmp(actual, expected)) {
    free(data);
    return -1;
  }
  for (i = 0; i < n;) {
    uint32_t words[1024], k = n - i > 1024 ? 1024 : n - i, t;
    for (t = 0; t < k; t++)
      words[t] = sma_get_u32(data + 4 * (i + t));
    if (private_write(g, off + i, words, k)) {
      free(data);
      return -1;
    }
    i += k;
  }
  free(data);
  return 0;
}
static int load_stipa_stage(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  gw_json_doc graph;
  const gw_json_node *stage;
  char file[1024];
  int rc;
  if (load_json(j->main_file, &graph))
    return -1;
  stage = gw_json_arr_at(member(&graph, gw_json_root(&graph), "stages"),
                         (size_t)j->stage);
  if (!stage || path_for(m, string(&graph, stage, "plan"), file, sizeof file)) {
    gw_json_doc_free(&graph);
    return -1;
  }
  if (replace_plan(j, file)) {
    gw_json_doc_free(&graph);
    return -1;
  }
  rc = patch_plan(g, m, &j->plan, gw_json_root(&j->plan));
  if (!rc)
    rc = load_stage_weight(g, m, &graph, stage);
  gw_json_doc_free(&graph);
  return rc;
}
static void set_restore(gw *g, fx_job *j) {
  memcpy(j->wanted, g->config_active_words, 128);
  j->wanted[8] = j->restore[8] & ~SM_P2_ENABLE;
  j->wanted[14] = j->restore[14];
  j->wanted[31] = j->restore[31];
  j->step = 30;
  (void)g;
}
static int prepare_inputs(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  const gw_json_node *params = gw_json_root(&j->params),
                     *root = gw_json_root(&j->plan),
                     *meta = member(&j->plan, member(&j->plan, root, "service"),
                                    "metadata");
  fx_job *reference = j->reference[0] ? find_job(m, j->reference) : NULL;
  if (j->staged) {
    if (!reference || reference->count != j->input_need ||
        reference->capture_channels != 1 ||
        reference->provenance.sample_rate != sm_word_float(g->snap.word[31]))
      return -1;
    if (input_write(g, j, FX_OUT, reference->data, j->input_need) ||
        input_write(g, j, FX_OUT + j->input_need, j->input, j->input_need))
      return -1;
  } else if (j->input_need) {
    uint32_t off =
        j->input_offset
            ? j->input_offset
            : FX_OUT + number(&j->plan, meta, "input_offset",
                              number(&j->plan, meta, "ir_offset", 32));
    if (input_write(g, j, off, j->input, j->input_need))
      return -1;
  }
  if (!strcmp(j->feature, "relative_insulation")) {
    uint32_t refWords;
    if (!reference_matches(g, j, reference))
      return -1;
    if (!j->input || j->input_count != 9)
      return -1;
    refWords = 9;
    if (input_write(g, j, FX_OUT + 18, reference->data, refWords) ||
        input_write(g, j, FX_OUT + 27, j->input, refWords))
      return -1;
  }
  if (!strcmp(j->feature, "spectrum_freeze") ||
      !strcmp(j->feature, "relative_limit")) {
    uint32_t current[1025], n;
    fc_provenance p;
    if (!reference_matches(g, j, reference))
      return -1;
    if (fc_p0_read(g, "power", j->channel, current, 1025, &n, &p))
      return 1;
    if (input_write(g, j, FX_OUT + 4096, current, 1025) ||
        input_write(g, j, FX_OUT + 4096 + 1025, reference->data, 1025))
      return -1;
  }
  if (!strcmp(j->feature, "directed_das")) {
    const gw_json_node *az = member(&j->params, params, "azimuth_deg"),
                       *el = member(&j->params, params, "elevation_deg");
    float values[2] = {(float)(az ? az->number : 0),
                       (float)(el ? el->number : 0)};
    uint32_t bits[2];
    if ((az && az->type != GW_JSON_NUMBER) ||
        (el && el->type != GW_JSON_NUMBER) || !isfinite(values[0]) ||
        !isfinite(values[1]) || fabs(values[0]) > 360 || fabs(values[1]) > 90)
      return -1;
    memcpy(bits, values, 8);
    if (input_write(g, j, FX_OUT, bits, 2))
      return -1;
  }
  if (!strcmp(j->feature, "noise_rating")) {
    const gw_json_node *value = member(&j->params, params, "referenceOffsetDb");
    float f;
    uint32_t words[2];
    if (!value || value->type != GW_JSON_NUMBER || !isfinite(value->number) ||
        fabs(value->number) > 200)
      return -1;
    f = 1;
    memcpy(words, &f, 4);
    f = (float)value->number;
    memcpy(words + 1, &f, 4);
    if (input_write(g, j, FX_OUT + 30, words, 2))
      return -1;
  }
  return 0;
}
static void advance_exclusive(gw *g, fx_job *j) {
  fx_manager *m = g->features;
  int ready, rc;
  const gw_json_node *root = gw_json_root(&j->plan);
  uint32_t cfg[32];
  if (j->cancel && j->step < 20 && j->step != 11 && j->step != 30 &&
      j->step != 31)
    set_restore(g, j);
  if (j->step == 9) {
    sm_service_result h;
    uint32_t band[10];
    /* Measurement needs a fresh octave service even after the reference view
     * lease expired. The active exclusive job otherwise blocks idle promotion. */
    unsigned last = g->config_active_words[15];
    if (g->pending_config) return;
    for (unsigned i=0; i<g->service_route_count && i<16; i++)
      if (g->service_routes[i].address == 0x10000000u+4*706496u) {
        m->p1_requested_ms[i]=g->now_ms;
        if(i>last) last=i;
      }
    if(last != g->config_active_words[15]) {
      memcpy(cfg,g->config_active_words,128);cfg[15]=last;
      if(internal_commit(g,j,cfg)) {fail(j,"octave_preparation_rejected");set_restore(g,j);}
      return;
    }
    if (sm_copy_service(&g->mmio->mem, 0x10000000u + 4 * 706496u, 10,
                        g->snap.word[4], g->snap.word[3], band, &h, 2))
      return;
    memcpy(j->input, band, 36);
    j->input_count = 9;
    j->step = 10;
  }
  if (j->step == 10) {
    memcpy(cfg, g->config_active_words, 128);
    cfg[8] &= ~3u;
    // Capture jobs require the raw ring even when the idle profile disables it.
    if (j->input_need) cfg[8] |= SM_RECORD_ENABLE;
    cfg[14] = 0;
    if (internal_commit(g, j, cfg)) {
      fail(j, "quiesce_config_rejected");
      abandon(g, j);
      return;
    }
    j->step = 11;
    return;
  }
  if (j->step == 11) {
    ready = config_ready(g, j);
    if (!ready)
      return;
    if (ready < 0) {
      fail(j, "quiesce_not_confirmed");
      abandon(g, j);
      return;
    }
    if (j->cancel) {
      set_restore(g, j);
      return;
    }
    if (j->kind == 5) {
      memcpy(cfg, g->config_active_words, 128);
      cfg[8] = j->restore[8] | SM_RECORD_ENABLE;
      cfg[14] = 1;
      if (internal_commit(g, j, cfg)) {
        fail(j, "event_arm_rejected");
        return;
      }
      j->step = 41;
      return;
    }
    if (j->kind == 6) {
      j->step = 13;
      copy_text(j->state, sizeof j->state, "capturing");
      return;
    }
    if (clear_plan(g, &j->plan, root) ||
        (!j->staged && patch_plan(g, m, &j->plan, root))) {
      fail(j, "private_plan_validation_or_write_failed");
      set_restore(g, j);
      return;
    }
    if (j->input_need) {
      j->step = 13;
      copy_text(j->state, sizeof j->state, "capturing");
      return;
    }
    j->step = 14;
  }
  if (j->step == 13) {
    rc = capture_into_job(g, j);
    if (rc == 1)
      return;
    if (rc < 0) {
      fail(j, "capture_gap_or_IO_error");
      set_restore(g, j);
      return;
    }
    if (j->kind == 6) {
      j->count = j->input_need * j->capture_channels;
      set_restore(g, j);
      return;
    }
    j->step = 14;
  }
  if (j->step == 14) {
    rc = prepare_inputs(g, j);
    if (rc == 1)
      return;
    if (rc < 0) {
      fail(j, "required_input_or_reference_mismatch");
      set_restore(g, j);
      return;
    }
    if (j->staged) {
      if (load_stipa_stage(g, j)) {
        fail(j, "stipa_stage_or_weight_missing");
        set_restore(g, j);
        return;
      }
      j->step = 20;
    } else if (j->prep) {
      char file[1024];
      const gw_json_node *p =
          member(&m->registry, j->definition,
                 j->prep == 2 ? "experimentalImpulsePreparationPlan"
                              : "acquisitionPreparationPlan");
      if (path_for(m, string(&m->registry, p, "file"), file, sizeof file) ||
          replace_plan(j, file) ||
          patch_plan(g, m, &j->plan, gw_json_root(&j->plan))) {
        fail(j, "PL_input_preparation_missing");
        set_restore(g, j);
        return;
      }
      j->step = 20;
    } else
      j->step = 20;
  }
  if (j->step == 20) {
    if (j->staged && j->stage > 0 && load_stipa_stage(g, j)) {
      fail(j, "stipa_stage_patch_failed");
      set_restore(g, j);
      return;
    }
    if (start_program(g, j)) {
      fail(j, "program_activation_failed");
      set_restore(g, j);
    }
    return;
  }
  if (j->step == 21) {
    sm_service_result h;
    uint32_t hint[16], n, off;
    ready = config_ready(g, j);
    if (!ready)
      return;
    if (ready < 0) {
      fail(j, "program_config_not_applied");
      set_restore(g, j);
      return;
    }
    if (j->cancel) {
      set_restore(g, j);
      return;
    }
    if(j->staged) {
      uint32_t desc[64];
      if(!read_memory(g,FX_TABLE,desc,64)) for(unsigned slot=0;slot<4;slot++) {
        uint32_t ctx[16],after[16],*d=desc+slot*16;
        if(!read_memory(g,d[4],ctx,16)&&!read_memory(g,d[4],after,16)&&
           !memcmp(ctx,after,sizeof ctx)&&ctx[0]==0x43545831u&&
           ctx[2]==d[11]&&ctx[3]==d[12]&&ctx[4]==d[13]&&ctx[15]==d[14])
          j->executed_instructions=ctx[11];
      }
    }
    off = j->output ? j->output : FX_OUT;
    if (read_memory(g, off - 16, hint, 16))
      return;
    if (hint[0] != 0x52534c54u || hint[2] != j->session ||
        hint[3] != j->config || hint[4] != j->generation ||
        hint[5] != j->program_version || hint[14] != 1)
      return;
    if (hint[12]) {
      fail(j, "PL_program_error");
      set_restore(g, j);
      return;
    }
    if (hint[1] == j->last_sequence && hint[6] == j->last_observation)
      return;
    /* Multi-frame statistics count fresh physical source frames, not a
       repeated publication from the same pinned input. */
    if (j->needed > 1 && j->observations && hint[6] == j->last_observation)
      return;
    j->last_sequence = hint[1];
    j->last_observation = hint[6];
    j->observations++;
    j->frame = hint[6];
    if (j->observations < j->needed)
      return;
    if (j->staged && j->stage < j->stages - 1) {
      j->stage++;
      j->executed_instructions=0;
      memcpy(cfg, g->config_active_words, 128);
      cfg[8] &= ~3u;
      if (internal_commit(g, j, cfg)) {
        fail(j, "stage_disable_failed");
        set_restore(g, j);
        return;
      }
      j->step = 22;
      return;
    }
    if (j->prep) {
      if (j->prep == 2) {
        uint32_t summary[4];
        if (read_memory(g, off + 28, summary, 4) ||
            sm_word_float(summary[2]) != 1) {
          fail(j, "no_valid_impulse_detected");
          set_restore(g, j);
          return;
        }
        j->excitation_detected=1;
      }
      memcpy(cfg, g->config_active_words, 128);
      cfg[8] &= ~3u;
      if (internal_commit(g, j, cfg)) {
        fail(j, "preparation_disable_failed");
        set_restore(g, j);
        return;
      }
      j->step = 23;
      return;
    }
    n = j->staged
            ? 3
            : number(&j->plan, gw_json_root(&j->plan), "outputWordCount", 0);
    if (!n)
      n = number(&j->plan, member(&j->plan, gw_json_root(&j->plan), "service"),
                 "output_words", 0);
    if (allocate_result(j, n) ||
        sm_copy_service(&g->mmio->mem, 0x10000000u + 4 * off, n, j->session,
                        j->config, j->data, &h, 2))
      return;
    if (h.word[4] != j->generation || h.word[5] != j->program_version)
      return;
    j->count = n;
    j->frame = h.word[6];
    j->provenance.first_sample = sm_join_u64(h.word[7], h.word[8]);
    j->provenance.sample_rate = sm_word_float(g->snap.word[31]);
    set_restore(g, j);
    return;
  }
  if (j->step == 22 || j->step == 23) {
    ready = config_ready(g, j);
    if (!ready)
      return;
    if (ready < 0) {
      fail(j, "stage_quiesce_not_confirmed");
      set_restore(g, j);
      return;
    }
    if (j->step == 23) {
      j->prep = 0;
      if (replace_plan(j, j->main_file) ||
          patch_plan(g, m, &j->plan, gw_json_root(&j->plan))) {
        fail(j, "main_reload_failed");
        set_restore(g, j);
        return;
      }
    }
    j->step = 20;
    return;
  }
  if (j->step == 30) {
    if (g->pending_config)
      return;
    memcpy(cfg, g->config_active_words, 128);
    cfg[8] = j->restore[8] & ~SM_P2_ENABLE;
    cfg[14] = j->restore[14];
    cfg[31] = j->restore[31];
    if (internal_commit(g, j, cfg)) {
      fail(j, "restore_config_rejected");
      abandon(g, j);
      return;
    }
    j->step = 31;
    return;
  }
  if (j->step == 31) {
    ready = config_ready(g, j);
    if (!ready)
      return;
    if (ready < 0) {
      fail(j, "restore_config_not_confirmed");
      abandon(g, j);
      return;
    }
    if (!strcmp(j->state, "failed")) {
      abandon(g, j);
    } else
      finish(g, j);
    return;
  }
  if (j->step == 41) {
    ready = config_ready(g, j);
    if (!ready)
      return;
    if (ready < 0) {
      fail(j, "event_arm_not_confirmed");
      set_restore(g, j);
      return;
    }
    j->session = j->wanted[0];
    j->config = j->wanted[1];
    if (j->cancel) {
      if (allocate_result(j, 32) == 0) {
        memcpy(j->data, g->snap.word, 128);
        j->count = 32;
        j->session = g->snap.word[4];
        j->config = g->snap.word[3];
        j->frame = g->snap.word[2];
      }
      set_restore(g, j);
    }
    return;
  }
}

void echo_features_tick(gw *g) {
  fx_manager *m = g->features;
  unsigned i;
  if (!m)
    return;
  if(!g->cfg.mock_fixture && g->has_result && g->snap.word[SM_R_ALGORITHM]==0x82000002u &&
     g->config_active_known && !m->active && !g->pending_config &&
     (g->config_active_words[8]&3u)==SM_P1_ENABLE && g->service_route_count>=4){
    unsigned last=3;
    for(i=4;i<g->service_route_count&&i<16;i++)
      if(m->p1_requested_ms[i] && g->now_ms-m->p1_requested_ms[i]<1500)last=i;
    if(g->config_active_words[15]!=last){
      uint32_t cfg[32];fx_job scheduling={0};memcpy(cfg,g->config_active_words,128);cfg[15]=last;
      if(!internal_commit(g,&scheduling,cfg))gw_logf(g,"P1 view priority last_index=%u",last);
    }
  }
  for (i = 0; i < FX_JOBS; i++) {
    fx_job *j = m->jobs + i;
    int rc;
    uint32_t words;
    if (j->used && terminal(j) && !j->exclusive)
      drop_reference(m, j);
    if (!j->used || (terminal(j) && !j->exclusive))
      continue;
    if (!terminal(j) && g->now_ms > j->deadline) {
      j->cancel = 1;
      fail(j, "processing_deadline_exceeded");
      if (j->exclusive)
        set_restore(g, j);
      else
        continue;
    }
    if (j->exclusive) {
      advance_exclusive(g, j);
      continue;
    }
    if (j->cancel) {
      copy_text(j->state, sizeof j->state, "canceled");
      continue;
    }
    if (!g->has_result || !g->config_active_known)
      continue;
    if (j->kind == 2) {
      rc = read_p1(g, j);
      if (rc < 0)
        fail(j, "service_snapshot_IO_error");
      else if (!rc)
        finish(g, j);
      continue;
    }
    if (j->kind == 1) {
      const char *id = j->role ? "power" : j->feature;
      const char *component=string(&j->params,gw_json_root(&j->params),"component");
      const char *policy=string(&j->params,gw_json_root(&j->params),"framePolicy");
      if(!strcmp(j->feature,"fft")&&component){if(!strcmp(component,"power"))id="power";else if(!strcmp(component,"psd"))id="stft";}
      if (allocate_result(j, !strcmp(id, "io_pcm") ? 12288
                             : !strcmp(id, "stft") ? 16 * 1025
                                                   : 1025)) {
        fail(j, "result_capacity");
        continue;
      }
      if (!strcmp(id, "spatial_interface"))
        id = "signal_quality";
      int transient=policy&&!strcmp(policy,"transient");
      rc = (transient?fc_transient_read:fc_p0_read)(g, id, j->channel,
                      j->data + (j->needed > 1 ? j->observations * 1025 : 0),
                      j->capacity, &words, &j->provenance);
      if (rc == -1) {
        fail(j, "P0_snapshot_IO_error");
        continue;
      }
      if (rc)
        continue;
      if (j->needed > 1 && j->frame == j->provenance.frame)
        continue;
      if (j->observations && j->config != j->provenance.config) {
        fail(j, "source_config_changed_during_capture");
        continue;
      }
      if (j->observations < 16)
        j->frame_samples[j->observations] = j->provenance.first_sample;
      j->session = j->provenance.session;
      j->config = j->provenance.config;
      j->frame = j->provenance.frame;
      j->generation = 1;
      j->observations++;
      j->count = (j->needed > 1 ? (uint32_t)j->observations * 1025u : words);
      if (j->observations >= j->needed)
        finish(g, j);
    }
  }
}

static void result_schema(fx_manager *m, fx_job *j, gw_json_writer *w) {
  const char *component=string(&j->params,gw_json_root(&j->params),"component");
  if(!strcmp(j->feature,"fft")&&component&&strcmp(component,"amplitude")){
    gw_jw_begin_obj(w);gw_jw_key(w,"kind");gw_jw_str(w,"spectrum");
    gw_jw_key(w,"fields");gw_jw_begin_arr(w);gw_jw_str(w,!strcmp(component,"power")?"binPower":"PSD");gw_jw_end_arr(w);
    gw_jw_key(w,"axes");gw_jw_begin_obj(w);gw_jw_key(w,"bins");gw_jw_u32(w,1025);gw_jw_key(w,"fftSize");gw_jw_u32(w,2048);gw_jw_end_obj(w);
    gw_jw_key(w,"units");gw_jw_str(w,!strcmp(component,"power")?"FS squared per bin":"FS squared/Hz");
    gw_jw_key(w,"validity");gw_jw_str(w,"Original PL FFT values; optional retention selects one real frame, never a synthetic per-bin maximum");
    gw_jw_key(w,"retainedForMs");gw_jw_u32(w,j->provenance.frame_age_ms);gw_jw_end_obj(w);return;
  }
  if (!strcmp(j->feature, "stft")) {
    unsigned i;
    gw_jw_begin_obj(w);
    gw_jw_key(w, "kind");
    gw_jw_str(w, "timeFrequency");
    gw_jw_key(w, "fields");
    gw_jw_begin_arr(w);
    gw_jw_str(w, "PSD");
    gw_jw_end_arr(w);
    gw_jw_key(w, "axes");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "bins");
    gw_jw_u32(w, 1025);
    gw_jw_key(w, "fftSize");
    gw_jw_u32(w, 2048);
    gw_jw_key(w, "sampleRateHz");
    {
      char f[40];
      snprintf(f, sizeof f, "%.9g", j->provenance.sample_rate);
      gw_jw_raw_value(w, f, strlen(f));
    }
    gw_jw_key(w, "frameFirstSampleIndices");
    gw_jw_begin_arr(w);
    for (i = 0; i < (unsigned)j->observations && i < 16; i++)
      gw_jw_u64dec_str(w, j->frame_samples[i]);
    gw_jw_end_arr(w);
    gw_jw_end_obj(w);
    gw_jw_key(w, "units");
    gw_jw_str(w, "FS squared/Hz");
    gw_jw_key(w, "validity");
    gw_jw_str(w, "actual retained PL frames; explicit sample indices, not "
                 "guaranteed every input hop");
    gw_jw_end_obj(w);
    return;
  }
  if (j->kind == 6 || !strcmp(j->feature, "io_pcm") || j->role ||
      !strcmp(j->feature, "levels_core") ||
      !strcmp(j->feature, "levels_extended")) {
    gw_jw_begin_obj(w);
    gw_jw_key(w, "kind");
    gw_jw_str(w, j->role                                           ? "reference"
                 : (j->kind == 6 || !strcmp(j->feature, "io_pcm")) ? "waveform"
                                                                   : "scalars");
    gw_jw_key(w, "fields");
    gw_jw_begin_arr(w);
    if (j->kind == 6 || !strcmp(j->feature, "io_pcm") || j->role)
      gw_jw_str(w, j->role ? "PL_reference_values" : "signed_PCM24");
    else {
      const char *fields[] = {"rms_FS",    "peak_FS",     "peakToPeak_FS",
                              "mean_FS",   "rms_dBFS",    "crest",
                              "clipCount", "nonzeroValid"};
      unsigned i;
      for (i = 0; i < 8; i++)
        gw_jw_str(w, fields[i]);
    }
    gw_jw_end_arr(w);
    gw_jw_key(w, "axes");
    gw_jw_begin_obj(w);
    gw_jw_key(w, "channelStrideWords");
    gw_jw_u32(w, j->kind == 6                    ? j->input_need
                 : !strcmp(j->feature, "io_pcm") ? 2048
                 : j->role                       ? j->count
                                                 : 8);
    gw_jw_key(w, "channels");
    gw_jw_u32(w, j->kind == 6 ? j->capture_channels : j->role ? 1 : 6);
    gw_jw_end_obj(w);
    gw_jw_key(w, "units");
    gw_jw_str(w, (j->kind == 6 || !strcmp(j->feature, "io_pcm"))
                     ? "signed24 counts"
                 : j->role ? "PL reference values, original units"
                           : "FS, dBFS, ratio, count");
    gw_jw_key(w, "validity");
    gw_jw_str(
        w, "verified capture identity; silence nonzeroValid0 suppresses dBFS");
    gw_jw_end_obj(w);
  } else {
    const gw_json_node *schema = member(&m->registry, j->definition, "schema"),
                       *v;
    const gw_json_node *service =
        member(&j->plan, gw_json_root(&j->plan), "service");
    const gw_json_node *meta = member(&j->plan, service, "metadata");
    gw_jw_begin_obj(w);
    for (v = schema ? schema->child : NULL; v; v = v->next) {
      char key[128];
      size_t n;
      const char *s = gw_json_key(&m->registry, v, &n);
      if (!s || n >= sizeof key)
        continue;
      memcpy(key, s, n);
      key[n] = 0;
      gw_jw_key(w, key);
      json_value(w, &m->registry, v);
    }
    if (meta) {
      gw_jw_key(w, "actualProducerLayout");
      json_value(w, &j->plan, meta);
    }
    if (!strcmp(j->feature, "directed_das")) {
      gw_jw_key(w, "requestedParameters");
      json_value(w, &j->params, gw_json_root(&j->params));
    }
    gw_jw_end_obj(w);
  }
}

int echo_features_dispatch(gw *g, const char *op, const gw_json_doc *d,
                           const gw_json_node *a, char *out, size_t capacity,
                           const char **error) {
  fx_manager *m = g->features;
  const gw_json_node *root, *features, *def, *params;
  gw_json_writer w;
  char id[128];
  fx_job *j;
  int accepted = 0;
  *error = "bad_args";
  if (!m) {
    *error = "not_ready";
    return -1;
  }
  gw_jw_init(&w, out, capacity);
  root = gw_json_root(&m->registry);
  features = member(&m->registry, root, "features");
  if (!strcmp(op, "feature.list")) {
    uint32_t first = number(d, a, "cursor", 0),
             limit = number(d, a, "limit", 8), i = 0, end;
    if (limit < 1 || limit > 16 || first > 51)
      return -1;
    end = first + limit;
    if (end > 51)
      end = 51;
    gw_jw_begin_obj(&w);
    gw_jw_key(&w, "version");
    gw_jw_str(&w, "echo-features-1");
    gw_jw_key(&w, "total");
    gw_jw_u32(&w, 51);
    gw_jw_key(&w, "features");
    gw_jw_begin_arr(&w);
    for (def = features->child; def; def = def->next, i++)
      if (i >= first && i < end) {
        const char *keys[] = {"featureId",
                              "name",
                              "tier",
                              "mode",
                              "params",
                              "parameterConstraints",
                              "input",
                              "schema",
                              "parameterPolicy",
                              "supportedParameterSets"};
        unsigned k;
        gw_jw_begin_obj(&w);
        for (k = 0; k < sizeof keys / sizeof keys[0]; k++) {
          gw_jw_key(&w, keys[k]);
          json_value(&w, &m->registry, member(&m->registry, def, keys[k]));
        }
        gw_jw_key(&w, "hardwareAccepted");
        gw_jw_bool(&w, 0);
        gw_jw_key(&w, "implementation");
        gw_jw_str(&w, "PL program and PS orchestration");
        gw_jw_end_obj(&w);
      }
    gw_jw_end_arr(&w);
    gw_jw_key(&w, "nextCursor");
    if (end < 51)
      gw_jw_u32(&w, end);
    else
      gw_jw_null(&w);
    gw_jw_end_obj(&w);
  } else if (!strcmp(op, "feature.start")) {
    const char *fid, *mode, *action;
    int different;
    fx_job *protected_reference = NULL;
    const char *requested_reference;
    if (!g->pl_identified || !g->config_active_known) {
      *error = "not_ready";
      return -1;
    }
    fid = string(d, a, "featureId");
    if (!fid || (def = find_definition(m, fid)) == NULL) {
      *error = "unsupported_feature";
      return -1;
    }
    requested_reference = string(d, member(d, a, "params"), "referenceJobId");
    if (requested_reference) {
      protected_reference = find_job(m, requested_reference);
      if (!protected_reference ||
          strcmp(protected_reference->state, "completed")) {
        *error = "bad_state";
        return -1;
      }
      protected_reference->refs++;
    }
    j = new_job(m);
    if (!j) {
      if (protected_reference)
        protected_reference->refs--;
      *error = "busy";
      return -1;
    }
    memset(j, 0, sizeof *j);
    gw_json_doc_init(&j->plan);
    gw_json_doc_init(&j->params);
    j->used = 1;
    copy_text(j->owner_session,sizeof j->owner_session,string(d,gw_json_root(d),"sessionId"));
    if (protected_reference) {
      j->reference_held = 1;
      copy_text(j->reference, sizeof j->reference, requested_reference);
    }
    j->id = ++m->counter;
    j->generation = (uint32_t)(g->epoch * 65537u + j->id);
    if (!j->generation)
      j->generation = 1;
    j->definition = def;
    j->began = g->now_ms;
    j->deadline = g->now_ms + 120000;
    j->needed = 1;
    j->capture_channels = 1;
    copy_text(j->feature, sizeof j->feature, fid);
    copy_text(j->state, sizeof j->state, "running");
    params = member(d, a, "params");
    if (params && params->type != GW_JSON_OBJECT)
      goto bad_start;
    {
      char *serialized = malloc(65536);
      gw_json_writer pw;
      if (!serialized)
        goto bad_start;
      gw_jw_init(&pw, serialized, 65536);
      if (params)
        json_value(&pw, d, params);
      else {
        gw_jw_begin_obj(&pw);
        gw_jw_end_obj(&pw);
      }
      if (!gw_jw_finish(&pw) || gw_json_parse(&j->params, serialized, pw.len,
                                              32, 20000, id, sizeof id)) {
        free(serialized);
        goto bad_start;
      }
      free(serialized);
    }
    params = gw_json_root(&j->params);
    {
      const char *integer_controls[] = {"channel", "samples", "channels",
                                        "frames"};
      unsigned k;
      uint32_t value;
      for (k = 0; k < 4; k++)
        if (member(&j->params, params, integer_controls[k]) &&
            gw_json_get_u32(&j->params, params, integer_controls[k], &value))
          goto bad_start;
    }
    j->channel = number(&j->params, params, "channel", 0);
    if (j->channel > 5)
      goto bad_start;
    if ((different = choose_plan(m, j, &j->params, params)) < 0)
      goto bad_start;
    mode = string(&m->registry, def, "mode");
    action = string(&j->params, params, "action");
    copy_text(j->reference, sizeof j->reference,
              string(&j->params, params, "referenceJobId"));
    j->kind = mode && !strcmp(mode, "p0")                 ? 1
              : mode && !strcmp(mode, "p1") && !different ? 2
              : mode && !strcmp(mode, "events")           ? 5
                                                          : 3;
    if (j->kind == 5)
      j->deadline = UINT64_MAX;
    if (action && !strcmp(action, "reference") &&
        (!strcmp(fid, "spectrum_freeze") || !strcmp(fid, "relative_limit"))) {
      j->kind = 1;
      j->role = 1;
    }
    if (action && !strcmp(action, "reference") &&
        !strcmp(fid, "relative_insulation")) {
      j->kind = 2;
      j->role = 1;
    }
    if (!strcmp(fid, "stft")) {
      j->needed = (int)number(&j->params, params, "frames", 8);
      if (j->needed < 1 || j->needed > 16)
        goto bad_start;
    }
    if (!strcmp(fid, "io_pcm") &&
        number(&j->params, params, "samples", 2048) < 2048)
      goto bad_start;
    if (!strcmp(fid, "io_pcm") &&
        (number(&j->params, params, "samples", 2048) > 2048 ||
         number(&j->params, params, "channels", 6) == 1)) {
      j->kind = 6;
      j->input_need = number(&j->params, params, "samples", 2048);
      j->capture_channels = (int)number(&j->params, params, "channels", 6);
      if (j->input_need > 1000000 ||
          (j->capture_channels != 1 && j->capture_channels != 6) ||
          allocate_result(j, j->input_need * j->capture_channels))
        goto bad_start;
    }
    if (!strcmp(fid, "spatial_interface")) {
      j->count = 0;
      copy_text(j->state, sizeof j->state, "completed");
      j->kind = 0;
    }
    if (mode && !strcmp(mode, "staged")) {
      fx_job *reference = find_job(m, j->reference);
      const gw_json_node *graph = gw_json_root(&j->plan);
      j->staged = 1;
      j->stages = (int)gw_json_arr_count(member(&j->plan, graph, "stages"));
      j->input_need = number(&j->plan, graph, "samples", 720000);
      if (!boolean(&j->params, params, "confirmed") &&
          !boolean(&j->params, params, "testSignalConfirmed"))
        goto bad_start;
      if (!reference || !terminal(reference) ||
          strcmp(reference->state, "completed") || reference->kind != 6 ||
          reference->capture_channels != 1 || reference->count != j->input_need)
        goto bad_start;
      if (!j->stages || j->stages > 128)
        goto bad_start;
      j->deadline = g->now_ms + 4ull * 3600000;
    }
    if (!strcmp(fid, "room_decay") || !strcmp(fid, "room_clarity") ||
        !strcmp(fid, "spectral_decay")) {
      const char *stimulus = string(&j->params, params, "stimulus");
      const gw_json_node *p =
          member(&m->registry, def, "experimentalImpulsePreparationPlan");
      if (!stimulus ||
          (strcmp(stimulus, "clap") && strcmp(stimulus, "impulse")))
        goto bad_start;
      j->input_need = number(&m->registry, p, "captureSamples", 0);
      j->input_offset = number(&m->registry, p, "inputWordOffset", FX_OUT + 32);
      j->prep = 2;
      if (!j->input_need)
        goto bad_start;
    }
    if (!strcmp(fid, "zoom_fft")) {
      const gw_json_node *p =
          member(&m->registry, def, "acquisitionPreparationPlan");
      j->input_need = number(&m->registry, p, "inputWords", 0);
      j->input_offset = number(&m->registry, p, "inputWordOffset", 0);
      j->prep = 1;
      if (!j->input_need)
        goto bad_start;
    }
    if (!strcmp(fid, "frequency_time_weighting") &&
        boolean(&j->params, params, "timeResponse")) {
      char file[1024];
      const gw_json_node *p = member(&m->registry, def, "additionalPlan");
      if (path_for(m, string(&m->registry, p, "file"), file, sizeof file) ||
          replace_plan(j, file))
        goto bad_start;
      copy_text(j->main_file, sizeof j->main_file, file);
      j->input_need = 48000;
      j->input_offset = FX_OUT + 32;
    }
    if (!strcmp(fid, "noise_rating")) {
      const gw_json_node *v = member(&j->params, params, "referenceOffsetDb");
      if (!boolean(&j->params, params, "referenceConfirmed") ||
          !nonblank(string(&j->params, params, "calibrationSource")) || !v ||
          v->type != GW_JSON_NUMBER || !isfinite(v->number) ||
          fabs(v->number) > 200)
        goto bad_start;
    }
    if ((!strcmp(fid, "relative_insulation") && !j->role) ||
        (!strcmp(fid, "spectrum_freeze") && !j->role) ||
        (!strcmp(fid, "relative_limit") && !j->role)) {
      fx_job *reference = find_job(m, j->reference);
      if (!reference_matches(g, j, reference))
        goto bad_start;
      if (!strcmp(fid, "relative_insulation")) {
        char file[1024];
        const gw_json_node *p =
            member(&m->registry, def, "verifiedCapturePlan");
        if (!boolean(&j->params, params, "confirmed") ||
            !(g->config_active_words[8] & SM_P1_ENABLE) ||
            path_for(m, string(&m->registry, p, "file"), file, sizeof file) ||
            replace_plan(j, file))
          goto bad_start;
        copy_text(j->main_file, sizeof j->main_file, file);
        j->input = calloc(9, 4);
        if (!j->input)
          goto bad_start;
      }
    }
    if (j->input_need && j->kind != 6) {
      if (j->input_need > 1000000)
        goto bad_start;
      j->input = malloc(4ull * j->input_need);
      if (!j->input)
        goto bad_start;
    }
    if (j->kind == 3) {
      j->needed =
          !strcmp(fid, "level_statistics") ? 16
          : !strcmp(fid, "spectral_kurtosis") ? 8
          : (!strcmp(fid, "energy_change") || !strcmp(fid, "band_tracking"))
              ? 2
              : 1;
    }
    if (j->kind >= 3) {
      if (!g->cfg.mock_fixture &&
          (!g->cfg.allow_config_commit ||
           ((j->kind == 5 || g->config_active_words[14]) &&
            !g->cfg.allow_event_capture))) {
        drop_reference(m, j);
        release_job(j);
        *error = "not_ready";
        return -1;
      }
      /* Immutable P0/P1 reads can coexist with the PC control owner. Only
       * operations which change PL state require the exclusive lease. */
      if (!validate_token(g, d, a)) {
        drop_reference(m, j);
        release_job(j);
        *error = "bad_token";
        return -1;
      }
      if (m->active || g->pending_config) {
        *error = "busy";
        drop_reference(m, j);
        release_job(j);
        return -1;
      }
      memcpy(j->restore, g->config_active_words, 128);
      if (j->kind == 5)
        j->restore[14] = 0;
      j->step = !strcmp(fid, "relative_insulation") ? 9 : 10;
      j->exclusive = 1;
      m->active = j;
      gw_arb_pending_inc(&g->arb);
    }
    gw_jw_begin_obj(&w);
    describe_job(g, j, &w);
    gw_jw_end_obj(&w);
    accepted = 1;
    goto finish_response;
  bad_start:
    drop_reference(m, j);
    release_job(j);
    *error = "bad_args";
    return -1;
  } else {
    const char *job = string(d, a, "jobId");
    j = find_job(m, job);
    if (!j) {
      *error = "job_not_found";
      return -1;
    }
    if (!strcmp(op, "feature.stop")) {
      const char *caller=string(d,gw_json_root(d),"sessionId");
      int own_readonly=j->kind<=2&&caller&&j->owner_session[0]&&!strcmp(caller,j->owner_session);
      if (!own_readonly && !validate_token(g, d, a)) {
        *error = "bad_token";
        return -1;
      }
      j->cancel = 1;
      gw_jw_begin_obj(&w);
      gw_jw_key(&w, "jobId");
      gw_jw_str(&w, job);
      gw_jw_key(&w, "cancelRequested");
      gw_jw_bool(&w, !terminal(j));
      gw_jw_end_obj(&w);
    } else if (!strcmp(op, "feature.get")) {
      gw_jw_begin_obj(&w);
      describe_job(g, j, &w);
      gw_jw_end_obj(&w);
    } else if (!strcmp(op, "feature.result")) {
      uint32_t offset = number(d, a, "offsetWords", 0),
               n = number(d, a, "maxWords", 1024), i;
      if (strcmp(j->state, "completed") || offset > j->count || n < 1 ||
          n > 4096) {
        *error = "bad_state";
        return -1;
      }
      if (n > j->count - offset)
        n = j->count - offset;
      gw_jw_begin_obj(&w);
      describe_job(g, j, &w);
      gw_jw_key(&w, "schema");
      result_schema(m, j, &w);
      gw_jw_key(&w, "totalWords");
      gw_jw_u32(&w, j->count);
      gw_jw_key(&w, "offsetWords");
      gw_jw_u32(&w, offset);
      gw_jw_key(&w, "words");
      gw_jw_begin_arr(&w);
      for (i = 0; i < n && gw_jw_len(&w) < 60000; i++)
        gw_jw_u32(&w, j->data[offset + i]);
      n = i;
      gw_jw_end_arr(&w);
      gw_jw_key(&w, "more");
      gw_jw_bool(&w, offset + n < j->count);
      gw_jw_end_obj(&w);
    } else {
      *error = "unknown_op";
      return -1;
    }
  }
finish_response:
  if (!gw_jw_finish(&w)) {
    *error = "internal_error";
    return -1;
  }
  return accepted;
}
