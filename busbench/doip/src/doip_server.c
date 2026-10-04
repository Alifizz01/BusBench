/* The socket half of the gateway. All it does is turn a TCP byte stream
 * into whole DoIP messages and back.
 *
 * The part worth reading is the reassembly loop. TCP is a stream, not a
 * message queue: one recv() can return half a message, or three of them
 * stuck together. Assuming one recv equals one message works on a fast
 * local link and then fails in the workshop. */

#include "doip_gateway.h"
#include <stdio.h>
#include <string.h>

#ifdef _WIN32
  #include <winsock2.h>
  #include <ws2tcpip.h>
  typedef SOCKET sock_t;
  #define CLOSE_SOCKET closesocket
  #define BAD_SOCKET   INVALID_SOCKET
#else
  #include <sys/socket.h>
  #include <netinet/in.h>
  #include <unistd.h>
  typedef int sock_t;
  #define CLOSE_SOCKET close
  #define BAD_SOCKET   (-1)
#endif

#define RX_BUF 8192

static sock_t active_client = BAD_SOCKET;

static bool net_startup(void)
{
#ifdef _WIN32
    WSADATA wsa;
    return WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
#else
    return true;
#endif
}

static void net_cleanup(void)
{
#ifdef _WIN32
    WSACleanup();
#endif
}

void DoipGateway_OnCanUdsResponse(const uint8_t *uds_resp, uint16_t len)
{
    if (active_client == BAD_SOCKET) return;

    uint8_t payload[4096 + 4];
    uint8_t frame[4096 + 16];
    if ((uint32_t)len + 4 > sizeof payload) return;

    payload[0] = (uint8_t)(DOIP_ENTITY_ADDRESS >> 8);
    payload[1] = (uint8_t)DOIP_ENTITY_ADDRESS;
    payload[2] = (uint8_t)(DOIP_TESTER_ADDRESS >> 8);
    payload[3] = (uint8_t)DOIP_TESTER_ADDRESS;
    memcpy(&payload[4], uds_resp, len);

    int n = Doip_Build(DOIP_DIAG_MESSAGE, payload, (uint32_t)(len + 4), frame, sizeof frame);
    if (n > 0) send(active_client, (const char *)frame, n, 0);
}

static void serve_client(sock_t client)
{
    uint8_t rx[RX_BUF];
    uint32_t have = 0;

    active_client = client;
    DoipGateway_ResetSession();

    for (;;) {
        int n = recv(client, (char *)&rx[have], (int)(sizeof rx - have), 0);
        if (n <= 0) break;                   /* tester disconnected */
        have += (uint32_t)n;

        /* Drain every complete message currently in the buffer, then keep
         * whatever partial message is left for the next recv. */
        uint32_t offset = 0;
        while (have - offset >= DOIP_HEADER_LEN) {
            uint16_t type;
            uint32_t plen;
            if (Doip_ParseHeader(&rx[offset], have - offset, &type, &plen) < 0) {
                /* Not DoIP. Say so once and drop the connection rather
                 * than hunting for a resync point in someone else's data. */
                uint8_t out[16];
                int r = DoipGateway_HandleMessage(&rx[offset], have - offset, out, sizeof out);
                if (r > 0) send(client, (const char *)out, r, 0);
                goto done;
            }
            uint32_t total = DOIP_HEADER_LEN + plen;
            if (total > sizeof rx) goto done;             /* would never fit */
            if (have - offset < total) break;             /* wait for the rest */

            uint8_t out[RX_BUF];
            int r = DoipGateway_HandleMessage(&rx[offset], total, out, sizeof out);
            if (r > 0) send(client, (const char *)out, r, 0);
            offset += total;
        }

        memmove(rx, &rx[offset], have - offset);
        have -= offset;
    }

done:
    active_client = BAD_SOCKET;
    CLOSE_SOCKET(client);
}

bool DoipGateway_Start(uint16_t tcp_port)
{
    if (!net_startup()) return false;

    sock_t listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener == BAD_SOCKET) { net_cleanup(); return false; }

    int yes = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof yes);

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);   /* loopback only, this is a demo */
    addr.sin_port = htons(tcp_port);

    if (bind(listener, (struct sockaddr *)&addr, sizeof addr) != 0 ||
        listen(listener, 1) != 0) {
        CLOSE_SOCKET(listener);
        net_cleanup();
        return false;
    }

    printf("DoIP gateway listening on 127.0.0.1:%u\n", tcp_port);
    fflush(stdout);

    sock_t client = accept(listener, NULL, NULL);
    if (client != BAD_SOCKET) serve_client(client);

    CLOSE_SOCKET(listener);
    net_cleanup();
    return true;
}
