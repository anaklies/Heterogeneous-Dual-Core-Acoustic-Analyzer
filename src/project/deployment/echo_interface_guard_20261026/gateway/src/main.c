/* ps_analysis_gateway -- standalone sixmic-analysis v1 PS gateway candidate.
 *
 * Control channel: TCP UTF-8 JSON-lines (default 48120).
 * Binary channel: TCP SMA1 framed (default 48121).
 * Device access: /dev/uioN or /dev/mem through the read-only integration host
 * C API (sixmic_host.c / service_result.c compiled in, not forked), or the
 * deterministic --mock-fixture MMIO model for host tests and demonstrations.
 *
 * NOT board-validated: see docs/README.md and docs/INTERFACE_GAPS.md. */
#include "gateway.h"
#include "mock_mmio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <signal.h>
#include <unistd.h>
#endif

static gw *g_gateway;
static volatile int g_stop_flag;

static void usage(void)
{
    printf(
        "ps_analysis_gateway %s -- sixmic-analysis v1 PS gateway candidate\n"
        "\n"
        "Usage: ps_gateway [options]\n"
        "  --control-port N        control TCP port (default %u, 0 = ephemeral)\n"
        "  --binary-port N         binary TCP port (default %u, 0 = ephemeral)\n"
        "  --bind ADDR             IPv4 listen address (default 0.0.0.0); the PS\n"
        "                          interface/address must be confirmed on target\n"
        "  --uio PATH              real backend: map /dev/uioN resource0\n"
        "  --memdev PATH           real backend: map /dev/mem window\n"
        "  --mmio-base HEX         /dev/mem PL HOST window physical base\n"
        "  --mmio-bytes N          PL HOST window size (default 4096)\n"
        "  --ddr-memdev PATH       map reserved DDR through /dev/mem for clips and\n"
        "                          service snapshots (required for those features)\n"
        "  --ddr-base HEX          reserved DDR physical base\n"
        "  --ddr-bytes N           reserved DDR size\n"
        "  --mock-fixture          deterministic protocol-3 MMIO model (no hardware)\n"
        "  --spool-dir PATH        event spool directory (default ./spool)\n"
        "  --state-dir PATH        connectionEpoch/config cache dir (default spool/state)\n"
        "  --spool-limit BYTES     event spool limit (default 64 MiB)\n"
        "  --max-binary-payload N  SMA1 payload ceiling (default 1048576)\n"
        "  --poll-ms N             device poll interval in ms (default 10)\n"
        "  --feature-registry PATH  enable the 45-feature interface using\n"
        "                          registry/INTERFACE_REGISTRY.json\n"
        "  --service-snapshot-addr HEX  service output byte address (enables the\n"
        "                          serviceSnapshot stream; value comes from the\n"
        "                          deployed profile, never guessed)\n"
        "  --service-snapshot-words N   max service words requested (default 16)\n"
        "  --allow-config-commit   enable config.commit against real hardware\n"
        "                          (NOT hardware-validated; off by default)\n"
        "  --allow-event-capture   enable clip capture against real hardware (NOT\n"
        "                          hardware-validated; off by default)\n"
        "  --allow-live-results    advertise liveResults and allow resultWords on\n"
        "                          real hardware (NOT hardware-validated; off)\n"
        "  --job-fixture-polls N   fixture job poll ticks before completion\n"
        "  --version               print version and exit\n"
        "  --help                  this text\n",
        GW_VERSION, (unsigned)SMA_DEFAULT_CONTROL_PORT,
        (unsigned)SMA_DEFAULT_BINARY_PORT);
}

static int arg_u32(const char *s, uint32_t *out)
{
    if (gw_parse_u32_hex_or_dec(s, strlen(s), out) != 0) return -1;
    return 0;
}

static int parse_args(gw_config *cfg, int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "--help") == 0 || strcmp(a, "-h") == 0) { usage(); exit(0); }
        if (strcmp(a, "--version") == 0) { printf("%s\n", GW_VERSION); exit(0); }
        if (strcmp(a, "--mock-fixture") == 0) { cfg->mock_fixture = 1; continue; }
        if (strcmp(a, "--allow-config-commit") == 0) { cfg->allow_config_commit = 1; continue; }
        if (strcmp(a, "--allow-event-capture") == 0) { cfg->allow_event_capture = 1; continue; }
        if (strcmp(a, "--allow-live-results") == 0) { cfg->allow_live_results = 1; continue; }
        if (i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", a); return -1; }
        {
            const char *v = argv[++i];
            if (strcmp(a, "--control-port") == 0) {
                uint32_t x; if (arg_u32(v, &x) || x > 65535) return -1;
                cfg->control_port = (uint16_t)x;
            } else if (strcmp(a, "--binary-port") == 0) {
                uint32_t x; if (arg_u32(v, &x) || x > 65535) return -1;
                cfg->binary_port = (uint16_t)x;
            } else if (strcmp(a, "--bind") == 0) {
                snprintf(cfg->bind_addr, sizeof cfg->bind_addr, "%s", v);
            } else if (strcmp(a, "--uio") == 0) {
                snprintf(cfg->uio_path, sizeof cfg->uio_path, "%s", v);
            } else if (strcmp(a, "--memdev") == 0) {
                snprintf(cfg->memdev_path, sizeof cfg->memdev_path, "%s", v);
            } else if (strcmp(a, "--mmio-base") == 0) {
                if (arg_u32(v, &cfg->mmio_phys_base)) return -1;
            } else if (strcmp(a, "--mmio-bytes") == 0) {
                if (arg_u32(v, &cfg->mmio_bytes)) return -1;
            } else if (strcmp(a, "--ddr-memdev") == 0) {
                snprintf(cfg->ddr_memdev_path, sizeof cfg->ddr_memdev_path, "%s", v);
            } else if (strcmp(a, "--ddr-base") == 0) {
                if (arg_u32(v, &cfg->ddr_phys_base)) return -1;
            } else if (strcmp(a, "--ddr-bytes") == 0) {
                if (arg_u32(v, &cfg->ddr_bytes)) return -1;
            } else if (strcmp(a, "--spool-dir") == 0) {
                snprintf(cfg->spool_dir, sizeof cfg->spool_dir, "%s", v);
            } else if (strcmp(a, "--state-dir") == 0) {
                snprintf(cfg->state_dir, sizeof cfg->state_dir, "%s", v);
            } else if (strcmp(a, "--spool-limit") == 0) {
                uint64_t x;
                if (gw_parse_u64_dec(v, strlen(v), &x)) return -1;
                cfg->spool_limit_bytes = x;
            } else if (strcmp(a, "--max-binary-payload") == 0) {
                if (arg_u32(v, &cfg->max_binary_payload)) return -1;
            } else if (strcmp(a, "--poll-ms") == 0) {
                uint32_t x; if (arg_u32(v, &x)) return -1;
                cfg->poll_ms = (int)x;
            } else if (strcmp(a, "--service-snapshot-addr") == 0) {
                if (arg_u32(v, &cfg->service_snapshot_addr)) return -1;
            } else if (strcmp(a, "--service-snapshot-words") == 0) {
                if (arg_u32(v, &cfg->service_snapshot_words)) return -1;
            } else if (strcmp(a, "--service-catalog") == 0) {
                if (strlen(v)>=sizeof cfg->service_catalog_file) return -1;
                snprintf(cfg->service_catalog_file,sizeof cfg->service_catalog_file,"%s",v);
            } else if (strcmp(a, "--feature-registry") == 0) {
                if(strlen(v)>=sizeof cfg->feature_registry_file)return -1;
                snprintf(cfg->feature_registry_file,sizeof cfg->feature_registry_file,"%s",v);
            } else if (strcmp(a, "--job-fixture-polls") == 0) {
                if (arg_u32(v, &cfg->job_fixture_polls)) return -1;
            } else {
                fprintf(stderr, "unknown option %s\n", a);
                return -1;
            }
        }
    }
    return 0;
}

#if defined(_WIN32)
static BOOL WINAPI console_handler(DWORD type)
{
    (void)type;
    g_stop_flag = 1;
    if (g_gateway) gw_request_stop(g_gateway);
    return TRUE;
}
#else
static void sig_handler(int sig)
{
    (void)sig;
    g_stop_flag = 1;
    if (g_gateway) gw_request_stop(g_gateway);
}
#endif

int main(int argc, char **argv)
{
    gw_config cfg;
    static gw gateway;
    char err[512];
    int rc;
    gw_config_defaults(&cfg);
    if (parse_args(&cfg, argc, argv) != 0) {
        usage();
        return 2;
    }
    memset(&gateway, 0, sizeof gateway);
    g_gateway = &gateway;
    rc = gw_init(&gateway, &cfg, NULL, err, sizeof err);
    if (rc != 0) {
        fprintf(stderr, "GATEWAY_INIT_FAILED: %s\n", err);
        return 1;
    }
    printf("GW_LISTEN control=%u binary=%u bind=%s epoch=%s fixture=%d\n",
           (unsigned)gateway.ctl_bound_port, (unsigned)gateway.bin_bound_port,
           cfg.bind_addr, gw_u64_dec(gateway.epoch, err), cfg.mock_fixture);
    fflush(stdout);
#if defined(_WIN32)
    SetConsoleCtrlHandler(console_handler, TRUE);
#else
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);
#endif
    while (!g_stop_flag && !gateway.stop) {
        if (gw_pump(&gateway, cfg.poll_ms) != 0) {
            fprintf(stderr, "GATEWAY_PUMP_ERROR\n");
            break;
        }
    }
    printf("GW_STOP epoch=%s\n", gw_u64_dec(gateway.epoch, err));
    gw_shutdown(&gateway);
    return 0;
}
