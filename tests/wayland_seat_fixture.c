/* SPDX-License-Identifier: MIT
 * Private-socket protocol fixture; it never connects to the desktop.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-server.h>

struct fixture {
    struct wl_display *display;
    struct wl_global *seat;
    struct wl_event_source *timer;
    uint32_t caps;
    int mode, phase;
    struct wl_list resources;
};
struct seat_resource { struct wl_list link; struct wl_resource *resource; };

static void release(struct wl_client *client, struct wl_resource *resource)
{ (void)client; wl_resource_destroy(resource); }

static void unexpected_device(struct wl_client *client, struct wl_resource *resource, uint32_t id)
{
    (void)resource; (void)id;
    wl_client_post_implementation_error(client, "guard must not request input devices");
}

static const struct wl_seat_interface seat_impl = {
    unexpected_device, unexpected_device, unexpected_device, release
};

static void destroy_resource(struct wl_resource *resource)
{
    struct seat_resource *seat = wl_resource_get_user_data(resource);
    wl_list_remove(&seat->link);
    free(seat);
}

static void bind_seat(struct wl_client *client, void *data, uint32_t version, uint32_t id)
{
    struct fixture *fixture = data;
    struct seat_resource *seat = calloc(1, sizeof(*seat));
    if (!seat) { wl_client_post_no_memory(client); return; }
    seat->resource = wl_resource_create(client, &wl_seat_interface, version, id);
    wl_resource_set_implementation(seat->resource, &seat_impl, seat, destroy_resource);
    wl_list_insert(&fixture->resources, &seat->link);
    wl_seat_send_capabilities(seat->resource, fixture->caps);
    if (version >= 2) wl_seat_send_name(seat->resource, "synthetic-seat");
}

static void add_seat(struct fixture *fixture, uint32_t caps)
{
    fixture->caps = caps;
    fixture->seat = wl_global_create(fixture->display, &wl_seat_interface, 5, fixture, bind_seat);
}

static int transition(void *data)
{
    struct fixture *fixture = data;
    if (fixture->mode == 1) add_seat(fixture, 3);
    else if (fixture->mode == 2) {
        fixture->caps = 3;
        struct seat_resource *seat;
        wl_list_for_each(seat, &fixture->resources, link)
            wl_seat_send_capabilities(seat->resource, fixture->caps);
    } else if (fixture->mode == 3) {
        if (fixture->phase++ == 0) {
            wl_global_destroy(fixture->seat);
            fixture->seat = NULL;
            wl_event_source_timer_update(fixture->timer, 200);
        } else add_seat(fixture, 3);
    } else if (fixture->mode == 4) wl_display_terminate(fixture->display);
    wl_display_flush_clients(fixture->display);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 3) return 64;
    struct fixture fixture = {0};
    fixture.mode = atoi(argv[2]);
    fixture.display = wl_display_create();
    wl_list_init(&fixture.resources);
    if (wl_display_add_socket(fixture.display, argv[1]) < 0) return 1;
    if (fixture.mode == 0) add_seat(&fixture, 3);
    if (fixture.mode == 2) add_seat(&fixture, 0);
    if (fixture.mode == 3 || fixture.mode == 5) add_seat(&fixture, 1);
    if (fixture.mode >= 1 && fixture.mode <= 4) {
        fixture.timer = wl_event_loop_add_timer(wl_display_get_event_loop(fixture.display), transition, &fixture);
        wl_event_source_timer_update(fixture.timer, 200);
    }
    puts("ready"); fflush(stdout);
    wl_display_run(fixture.display);
    wl_display_destroy_clients(fixture.display);
    if (fixture.timer) wl_event_source_remove(fixture.timer);
    if (fixture.seat) wl_global_destroy(fixture.seat);
    wl_display_destroy(fixture.display);
    return 0;
}
