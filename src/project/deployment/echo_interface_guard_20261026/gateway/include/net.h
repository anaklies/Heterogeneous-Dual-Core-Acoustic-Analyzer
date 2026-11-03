#ifndef GW_NET_H
#define GW_NET_H
/* Thin non-blocking TCP socket layer: Winsock on Windows, POSIX elsewhere.
 * IPv4 only; the PS listen address/interface must be confirmed on target. */
#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
typedef intptr_t gw_sock;
#else
typedef int gw_sock;
#endif

#define GW_SOCK_INVALID ((gw_sock)-1)
#define GW_RECV_AGAIN (-1)
#define GW_RECV_ERROR (-2)
#define GW_SEND_AGAIN (-1)
#define GW_SEND_ERROR (-2)

int gw_net_startup(char *err, size_t errcap);
void gw_net_cleanup(void);

/* Listens on IPv4. bind_addr NULL or "0.0.0.0" means all interfaces. port 0
 * selects an ephemeral port, reported through actual_port. */
gw_sock gw_net_listen(const char *bind_addr, uint16_t port, uint16_t *actual_port,
                      char *err, size_t errcap);
gw_sock gw_net_accept(gw_sock listener, char *peer, size_t peercap);
gw_sock gw_net_connect(const char *host, uint16_t port, char *err, size_t errcap);
int gw_net_set_nonblocking(gw_sock s);
void gw_net_close(gw_sock s);
/* Returns bytes read (>0), 0 on orderly close, GW_RECV_AGAIN, GW_RECV_ERROR. */
int gw_net_recv(gw_sock s, void *buf, size_t cap);
/* Returns bytes sent (>=0), GW_SEND_AGAIN, GW_SEND_ERROR. */
int gw_net_send(gw_sock s, const void *buf, size_t len);

typedef struct {
    gw_sock fd;
    uint8_t want_read;
    uint8_t want_write;
    uint8_t ready_read;
    uint8_t ready_write;
} gw_pollfd;

/* Waits up to timeout_ms (0 = poll once). Returns ready count, -1 on error. */
int gw_net_poll(gw_pollfd *fds, size_t nfds, int timeout_ms);

#endif
