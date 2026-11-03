#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static long long milliseconds(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static int wait_socket(int fd, short events, long long deadline) {
  struct pollfd p = {fd, events, 0};
  long long left = deadline - milliseconds();
  if (left <= 0)
    return -1;
  return poll(&p, 1, (int)left) > 0 && (p.revents & events) ? 0 : -1;
}
int main(void) {
  const char request[] =
      "{\"protocol\":\"sixmic-analysis\",\"version\":1,\"requestId\":"
      "\"health\",\"op\":\"hello\",\"args\":{\"clientName\":\"echo-health\","
      "\"clientVersion\":\"1\"}}\n";
  struct sockaddr_in address = {0};
  char buffer[16384];
  size_t sent = 0, used = 0;
  int error = 0, fd, result = 1;
  socklen_t length = sizeof error;
  long long deadline = milliseconds() + 2000;
  fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0)
    return 1;
  if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0)
    goto done;
  address.sin_family = AF_INET;
  address.sin_port = htons(48120);
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (connect(fd, (struct sockaddr *)&address, sizeof address) < 0 &&
      errno != EINPROGRESS)
    goto done;
  if (wait_socket(fd, POLLOUT, deadline) ||
      getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) || error)
    goto done;
  while (sent < sizeof request - 1) {
    ssize_t n;
    if (wait_socket(fd, POLLOUT, deadline))
      goto done;
    n = send(fd, request + sent, sizeof request - 1 - sent, MSG_NOSIGNAL);
    if (n < 0 && (errno == EINTR || errno == EAGAIN))
      continue;
    if (n <= 0)
      goto done;
    sent += (size_t)n;
  }
  while (used < sizeof buffer - 1) {
    ssize_t n;
    if (wait_socket(fd, POLLIN, deadline))
      goto done;
    n = recv(fd, buffer + used, sizeof buffer - 1 - used, 0);
    if (n < 0 && (errno == EINTR || errno == EAGAIN))
      continue;
    if (n <= 0)
      goto done;
    used += (size_t)n;
    buffer[used] = 0;
    if (strchr(buffer, '\n')) {
      result = !(strstr(buffer, "\"serverVersion\"") &&
                 strstr(buffer, "\"status\":\"ok\"") &&
                 strstr(buffer, "\"protocol\":\"sixmic-analysis\""));
      break;
    }
  }
done:
  close(fd);
  return result;
}
