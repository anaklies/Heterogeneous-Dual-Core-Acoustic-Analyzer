#if defined(_WIN32)
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#endif

#include "net.h"
#include "gw_util.h"

#include <stdio.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#endif

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

#if defined(_WIN32)
#define GW_SOCK_ARG(x) ((SOCKET)(x))
#else
#define GW_SOCK_ARG(x) (x)
#endif

int gw_net_startup(char *err, size_t errcap)
{
#if defined(_WIN32)
    WSADATA wsa;
    int rc = WSAStartup(MAKEWORD(2, 2), &wsa);
    if (rc != 0) {
        if (err && errcap) snprintf(err, errcap, "WSAStartup failed: %d", rc);
        return -1;
    }
#else
    (void)err;
    (void)errcap;
#endif
    return 0;
}

void gw_net_cleanup(void)
{
#if defined(_WIN32)
    WSACleanup();
#endif
}

static void set_err(char *err, size_t errcap, const char *what)
{
    if (err && errcap) snprintf(err, errcap, "%s", what);
}

gw_sock gw_net_listen(const char *bind_addr, uint16_t port, uint16_t *actual_port,
                      char *err, size_t errcap)
{
    gw_sock s = GW_SOCK_INVALID;
    struct sockaddr_in addr;
    int one = 1;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (!bind_addr || strcmp(bind_addr, "0.0.0.0") == 0) {
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
    } else if (inet_pton(AF_INET, bind_addr, &addr.sin_addr) != 1) {
        set_err(err, errcap, "invalid IPv4 bind address");
        return GW_SOCK_INVALID;
    }
    s = (gw_sock)socket(AF_INET, SOCK_STREAM, 0);
    if (s == GW_SOCK_INVALID) { set_err(err, errcap, "socket() failed"); return GW_SOCK_INVALID; }
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, (int)sizeof one);
#if defined(TCP_NODELAY)
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, (const char *)&one, (int)sizeof one);
#endif
    if (bind(s, (struct sockaddr *)&addr, (int)sizeof addr) != 0) {
        set_err(err, errcap, "bind() failed (port in use or not permitted)");
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    if (listen(s, 8) != 0) {
        set_err(err, errcap, "listen() failed");
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    if (actual_port) {
        struct sockaddr_in got;
#if defined(_WIN32)
        int glen = (int)sizeof got;
#else
        socklen_t glen = sizeof got;
#endif
        memset(&got, 0, sizeof got);
        if (getsockname(s, (struct sockaddr *)&got, &glen) == 0)
            *actual_port = ntohs(got.sin_port);
        else
            *actual_port = port;
    }
    if (gw_net_set_nonblocking(s) != 0) {
        set_err(err, errcap, "non-blocking setup failed");
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    return s;
}

gw_sock gw_net_accept(gw_sock listener, char *peer, size_t peercap)
{
    struct sockaddr_in addr;
#if defined(_WIN32)
    int alen = (int)sizeof addr;
#else
    socklen_t alen = sizeof addr;
#endif
    gw_sock s;
    memset(&addr, 0, sizeof addr);
    s = (gw_sock)accept(GW_SOCK_ARG(listener), (struct sockaddr *)&addr, &alen);
    if (s == GW_SOCK_INVALID) return GW_SOCK_INVALID;
    if (peer && peercap) {
        char ip[64];
        if (inet_ntop(AF_INET, &addr.sin_addr, ip, (int)sizeof ip))
            snprintf(peer, peercap, "%s:%u", ip, (unsigned)ntohs(addr.sin_port));
        else
            snprintf(peer, peercap, "?");
    }
    if (gw_net_set_nonblocking(s) != 0) {
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    return s;
}

gw_sock gw_net_connect(const char *host, uint16_t port, char *err, size_t errcap)
{
    struct sockaddr_in addr;
    gw_sock s;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        set_err(err, errcap, "invalid IPv4 host");
        return GW_SOCK_INVALID;
    }
    s = (gw_sock)socket(AF_INET, SOCK_STREAM, 0);
    if (s == GW_SOCK_INVALID) { set_err(err, errcap, "socket() failed"); return GW_SOCK_INVALID; }
    if (connect(GW_SOCK_ARG(s), (struct sockaddr *)&addr, (int)sizeof addr) != 0) {
        set_err(err, errcap, "connect() failed");
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    if (gw_net_set_nonblocking(s) != 0) {
        set_err(err, errcap, "non-blocking setup failed");
        gw_net_close(s);
        return GW_SOCK_INVALID;
    }
    return s;
}

int gw_net_set_nonblocking(gw_sock s)
{
#if defined(_WIN32)
    u_long mode = 1;
    return ioctlsocket((SOCKET)s, FIONBIO, &mode) == 0 ? 0 : -1;
#else
    int flags = fcntl(s, F_GETFL, 0);
    if (flags < 0) return -1;
    return fcntl(s, F_SETFL, flags | O_NONBLOCK) == 0 ? 0 : -1;
#endif
}

void gw_net_close(gw_sock s)
{
#if defined(_WIN32)
    closesocket((SOCKET)s);
#else
    close(s);
#endif
}

int gw_net_recv(gw_sock s, void *buf, size_t cap)
{
#if defined(_WIN32)
    int n = recv((SOCKET)s, (char *)buf, (int)cap, 0);
    if (n > 0) return n;
    if (n == 0) return 0;
    if (WSAGetLastError() == WSAEWOULDBLOCK) return GW_RECV_AGAIN;
    return GW_RECV_ERROR;
#else
    ssize_t n = recv(s, buf, cap, 0);
    if (n > 0) return (int)n;
    if (n == 0) return 0;
    if (errno == EAGAIN || errno == EWOULDBLOCK) return GW_RECV_AGAIN;
    return GW_RECV_ERROR;
#endif
}

int gw_net_send(gw_sock s, const void *buf, size_t len)
{
#if defined(_WIN32)
    int n = send((SOCKET)s, (const char *)buf, (int)len, 0);
    if (n >= 0) return n;
    if (WSAGetLastError() == WSAEWOULDBLOCK) return GW_SEND_AGAIN;
    return GW_SEND_ERROR;
#else
    ssize_t n = send(s, buf, len, MSG_NOSIGNAL);
    if (n >= 0) return (int)n;
    if (errno == EAGAIN || errno == EWOULDBLOCK) return GW_SEND_AGAIN;
    return GW_SEND_ERROR;
#endif
}

int gw_net_poll(gw_pollfd *fds, size_t nfds, int timeout_ms)
{
    fd_set rd, wr;
    struct timeval tv;
    size_t i;
    int ready;
#if defined(_WIN32)
    FD_ZERO(&rd);
    FD_ZERO(&wr);
    for (i = 0; i < nfds; i++) {
        fds[i].ready_read = 0;
        fds[i].ready_write = 0;
        if (fds[i].want_read) FD_SET((SOCKET)fds[i].fd, &rd);
        if (fds[i].want_write) FD_SET((SOCKET)fds[i].fd, &wr);
    }
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    ready = select(0, &rd, &wr, NULL, timeout_ms >= 0 ? &tv : NULL);
    if (ready == SOCKET_ERROR) return -1;
    for (i = 0; i < nfds; i++) {
        if (fds[i].want_read && FD_ISSET((SOCKET)fds[i].fd, &rd)) fds[i].ready_read = 1;
        if (fds[i].want_write && FD_ISSET((SOCKET)fds[i].fd, &wr)) fds[i].ready_write = 1;
    }
#else
    int maxfd = -1;
    FD_ZERO(&rd);
    FD_ZERO(&wr);
    for (i = 0; i < nfds; i++) {
        fds[i].ready_read = 0;
        fds[i].ready_write = 0;
        if (fds[i].want_read) FD_SET(fds[i].fd, &rd);
        if (fds[i].want_write) FD_SET(fds[i].fd, &wr);
        if (fds[i].fd > maxfd) maxfd = fds[i].fd;
    }
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    if (maxfd < 0) {
        if (timeout_ms > 0) gw_sleep_ms((unsigned)timeout_ms);
        return 0;
    }
    ready = select(maxfd + 1, &rd, &wr, NULL, timeout_ms >= 0 ? &tv : NULL);
    if (ready < 0) {
        if (errno == EINTR) return 0;
        return -1;
    }
    for (i = 0; i < nfds; i++) {
        if (fds[i].want_read && FD_ISSET(fds[i].fd, &rd)) fds[i].ready_read = 1;
        if (fds[i].want_write && FD_ISSET(fds[i].fd, &wr)) fds[i].ready_write = 1;
    }
#endif
    return ready;
}