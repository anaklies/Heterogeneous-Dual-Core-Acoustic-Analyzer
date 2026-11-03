#ifndef ECHO_FEATURE_RUNTIME_H
#define ECHO_FEATURE_RUNTIME_H
#include "gateway.h"
int echo_features_init(gw *, const char *, char *, size_t);
void echo_features_tick(gw *);
void echo_features_free(gw *);
int echo_features_dispatch(gw *, const char *, const gw_json_doc *,
                           const gw_json_node *, char *, size_t, const char **);
int echo_features_busy(gw *);
int echo_features_internal_config(gw *);
void echo_features_owner_closed(gw *,const char *);
#endif
