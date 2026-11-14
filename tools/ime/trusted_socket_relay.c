/* SPDX-License-Identifier: MIT
 * Experimental WSLg system-distro helper. Weston must launch this process.
 * Never creates an ordinary Wayland connection or weakens IME authorization.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;

static void stop(int signum)
{
    (void)signum;
    stopping = 1;
}

static int fail(const char *message)
{
    fprintf(stderr, "wslg-ime-relay: %s\n", message);
    return EXIT_FAILURE;
}

int main(void)
{
    const char *name = getenv("WSLG_IME_BRIDGE_SOCKET");
    const char *inherited = getenv("WAYLAND_SOCKET");
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    struct stat st;
    struct ucred peer;
    socklen_t peer_len = sizeof(peer);
    char parent[sizeof(address.sun_path)], *slash, *end;
    int relay = -1, type;
    socklen_t type_len = sizeof(type);
    long wayland;
    struct sigaction action = {.sa_handler = stop};

    if (!name || name[0] != '/' || strlen(name) >= sizeof(address.sun_path))
        return fail("WSLG_IME_BRIDGE_SOCKET must be a short absolute Unix path");
    if (!inherited || !inherited[0])
        return fail("WAYLAND_SOCKET must be inherited from the compositor");
    errno = 0;
    wayland = strtol(inherited, &end, 10);
    if (errno || *end || wayland < 0 || wayland > INT_MAX ||
        getsockopt((int)wayland, SOL_SOCKET, SO_TYPE, &type, &type_len) ||
        type != SOCK_STREAM)
        return fail("WAYLAND_SOCKET is not an open stream socket");

    strcpy(address.sun_path, name);
    strcpy(parent, name);
    slash = strrchr(parent, '/');
    if (!slash || slash == parent)
        return fail("a private socket directory is required");
    *slash = '\0';
    if (mkdir(parent, 0700) && errno != EEXIST)
        return fail("cannot create private broker directory");
    if (lstat(parent, &st) || !S_ISDIR(st.st_mode) ||
        st.st_uid != getuid() || (st.st_mode & 0777) != 0700)
        return fail("socket directory must be owned by this uid with mode 0700");

    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    signal(SIGPIPE, SIG_IGN);
    /* The system compositor can start before the Ubuntu user manager. */
    for (int attempt = 0; attempt < 6000 && !stopping; ++attempt) {
        struct timespec delay = {.tv_nsec = 100000000};
        if (!lstat(name, &st)) {
            if (!S_ISSOCK(st.st_mode) || st.st_uid != getuid() ||
                (st.st_mode & 0777) != 0600)
                return fail("broker socket must be owned by this uid with mode 0600");
            relay = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
            if (relay < 0)
                return fail("cannot create broker connection");
            if (!connect(relay, (struct sockaddr *)&address, sizeof(address)))
                break;
            close(relay);
            relay = -1;
        }
        nanosleep(&delay, NULL);
    }
    if (relay < 0)
        return fail("broker unavailable after bounded startup wait");
    if (getsockopt(relay, SOL_SOCKET, SO_PEERCRED, &peer, &peer_len) ||
        peer.uid != getuid()) {
        close(relay);
        return fail("broker uid does not match compositor client uid");
    }

    char magic[] = "WSLGIME1";
    union {
        struct cmsghdr align;
        char bytes[CMSG_SPACE(sizeof(int))];
    } control = {0};
    struct iovec data = {.iov_base = magic, .iov_len = 8};
    struct msghdr message = {
        .msg_iov = &data, .msg_iovlen = 1,
        .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)
    };
    struct cmsghdr *ancillary = CMSG_FIRSTHDR(&message);
    ancillary->cmsg_level = SOL_SOCKET;
    ancillary->cmsg_type = SCM_RIGHTS;
    ancillary->cmsg_len = CMSG_LEN(sizeof(int));
    int fd = (int)wayland;
    memcpy(CMSG_DATA(ancillary), &fd, sizeof(fd));
    if (sendmsg(relay, &message, MSG_NOSIGNAL) != 8) {
        close(relay);
        return fail("descriptor transfer failed");
    }
    struct pollfd ready = {.fd = relay, .events = POLLIN};
    char reply;
    if (poll(&ready, 1, 10000) <= 0 || recv(relay, &reply, 1, 0) != 1 || reply != 'O') {
        close(relay);
        return fail("broker did not confirm the Fcitx handoff");
    }
    close(fd);
    unsetenv("WAYLAND_SOCKET");
    fprintf(stderr, "wslg-ime-relay: trusted descriptor handed off\n");
    while (!stopping) {
        ssize_t received = recv(relay, &reply, 1, 0);
        if (received < 0 && errno == EINTR)
            continue;
        break;
    }
    close(relay);
    return EXIT_SUCCESS;
}
