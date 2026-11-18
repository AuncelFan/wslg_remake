/* SPDX-License-Identifier: MIT
 * One-shot GTK portal startup prerequisite. Observe seat capabilities only;
 * do not request keyboard/pointer objects or consume application input.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>

struct state;
struct seat {
    struct state *state;
    struct seat *next;
    struct wl_seat *proxy;
    uint32_t name, capabilities;
};
struct state { struct seat *seats; int failed; };

static int64_t now_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0) return -1;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void capabilities(void *data, struct wl_seat *proxy, uint32_t caps)
{
    (void)proxy;
    ((struct seat *)data)->capabilities = caps;
}

static void seat_name(void *data, struct wl_seat *proxy, const char *name)
{ (void)data; (void)proxy; (void)name; }

static const struct wl_seat_listener seat_listener = { capabilities, seat_name };

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version)
{
    struct state *state = data;
    if (strcmp(interface, "wl_seat")) return;
    struct seat *seat = calloc(1, sizeof(*seat));
    if (!seat) { state->failed = 1; return; }
    seat->state = state;
    seat->name = name;
    seat->proxy = wl_registry_bind(registry, name, &wl_seat_interface,
                                   version < 5 ? version : 5);
    if (!seat->proxy) { free(seat); state->failed = 1; return; }
    seat->next = state->seats;
    state->seats = seat;
    wl_seat_add_listener(seat->proxy, &seat_listener, seat);
}

static void global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    struct state *state = data;
    struct seat **link = &state->seats;
    (void)registry;
    while (*link) {
        struct seat *seat = *link;
        if (seat->name != name) { link = &seat->next; continue; }
        *link = seat->next;
        wl_seat_destroy(seat->proxy);
        free(seat);
        break;
    }
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

static int ready(const struct state *state)
{
    const uint32_t required = WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD;
    for (const struct seat *seat = state->seats; seat; seat = seat->next)
        if ((seat->capabilities & required) == required) return 1;
    return 0;
}

int main(int argc, char **argv)
{
    long timeout_ms = 30000;
    if (argc == 2 && !strncmp(argv[1], "--timeout-ms=", 13)) {
        char *end = NULL;
        errno = 0;
        timeout_ms = strtol(argv[1] + 13, &end, 10);
        if (errno || end == argv[1] + 13 || *end || timeout_ms < 1 || timeout_ms > 120000)
            return 64;
    } else if (argc != 1) return 64;

    struct state state = {0};
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) {
        fputs("WSLg portal seat guard: Wayland connection unavailable\n", stderr);
        return 69;
    }
    struct wl_registry *registry = wl_display_get_registry(display);
    if (!registry) { wl_display_disconnect(display); return 70; }
    wl_registry_add_listener(registry, &registry_listener, &state);
    int64_t start = now_ms();
    int result = 1;
    if (start < 0) goto out;
    for (;;) {
        if (wl_display_dispatch_pending(display) < 0 || state.failed) break;
        if (ready(&state)) { result = 0; break; }
        short events = POLLIN;
        if (wl_display_flush(display) < 0) {
            if (errno != EAGAIN) break;
            events |= POLLOUT;
        }
        int64_t now = now_ms();
        if (now < 0) break;
        int64_t remaining = start + timeout_ms - now;
        if (remaining <= 0) { result = 75; break; }
        struct pollfd fd = { wl_display_get_fd(display), events, 0 };
        int polled = poll(&fd, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (polled < 0 && errno == EINTR) continue;
        if (polled < 0) break;
        if (polled == 0) { result = 75; break; }
        if (fd.revents & (POLLERR | POLLHUP | POLLNVAL)) break;
        if ((fd.revents & POLLIN) && wl_display_dispatch(display) < 0) break;
    }
out:
    if (result == 0)
        fputs("WSLg portal seat guard: Wayland pointer and keyboard ready\n", stderr);
    else if (result == 75)
        fputs("WSLg portal seat guard: timed out; GTK portal was not started without input\n", stderr);
    else
        fputs("WSLg portal seat guard: Wayland initialization failed\n", stderr);
    while (state.seats) global_remove(&state, registry, state.seats->name);
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return result;
}
