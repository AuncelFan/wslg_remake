/* SPDX-License-Identifier: MIT
 * No GUI and no app injection. Records native preedit/commit from a test-only
 * Weston socket. This is not GPU or original ChatGPT desktop acceptance.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include "text-input-v1-client-protocol.h"

struct probe {
    struct wl_compositor *compositor;
    struct wl_seat *seat;
    struct zwp_text_input_manager_v1 *manager;
    bool committed;
};

static void emit_text(const char *event, const char *text)
{
    printf("{\"event\":\"%s\",\"text\":\"", event);
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\')
            putchar('\\');
        if (*p < 0x20)
            printf("\\u%04x", *p);
        else
            putchar(*p);
    }
    puts("\"}");
    fflush(stdout);
}

static void registry_global(void *data, struct wl_registry *registry,
                            uint32_t name, const char *interface, uint32_t version)
{
    struct probe *p = data;
    (void)version;
    if (!strcmp(interface, "wl_compositor"))
        p->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 1);
    else if (!strcmp(interface, "wl_seat"))
        p->seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
    else if (!strcmp(interface, "zwp_text_input_manager_v1"))
        p->manager = wl_registry_bind(registry, name, &zwp_text_input_manager_v1_interface, 1);
}

static void global_remove(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener registry_listener = {registry_global, global_remove};

static void enter(void *d, struct zwp_text_input_v1 *t, struct wl_surface *s)
{ emit_text("enter", ""); }
static void leave(void *d, struct zwp_text_input_v1 *t) {}
static void modifiers(void *d, struct zwp_text_input_v1 *t, struct wl_array *a) {}
static void panel(void *d, struct zwp_text_input_v1 *t, uint32_t state) {}
static void preedit(void *d, struct zwp_text_input_v1 *t, uint32_t serial,
                     const char *text, const char *commit)
{ emit_text("preedit", text); }
static void styling(void *d, struct zwp_text_input_v1 *t, uint32_t i, uint32_t n, uint32_t s) {}
static void preedit_cursor(void *d, struct zwp_text_input_v1 *t, int32_t i) {}
static void commit(void *data, struct zwp_text_input_v1 *t, uint32_t serial, const char *text)
{
    struct probe *p = data;
    emit_text("commit", text);
    if (text[0])
        p->committed = true;
}
static void cursor(void *d, struct zwp_text_input_v1 *t, int32_t i, int32_t a) {}
static void delete_text(void *d, struct zwp_text_input_v1 *t, int32_t i, uint32_t n) {}
static void keysym(void *d, struct zwp_text_input_v1 *t, uint32_t serial,
                   uint32_t time, uint32_t key, uint32_t state, uint32_t mods) {}
static void language(void *d, struct zwp_text_input_v1 *t, uint32_t s, const char *l) {}
static void direction(void *d, struct zwp_text_input_v1 *t, uint32_t s, uint32_t dir) {}

static const struct zwp_text_input_v1_listener text_listener = {
    enter, leave, modifiers, panel, preedit, styling, preedit_cursor, commit,
    cursor, delete_text, keysym, language, direction
};

int main(void)
{
    struct probe probe = {0};
    struct wl_display *display = wl_display_connect(NULL);
    if (!display)
        return 2;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, &probe);
    if (wl_display_roundtrip(display) < 0 ||
        !probe.compositor || !probe.manager || !probe.seat)
        return 3;
    struct wl_surface *surface = wl_compositor_create_surface(probe.compositor);
    struct zwp_text_input_v1 *text = zwp_text_input_manager_v1_create_text_input(probe.manager);
    zwp_text_input_v1_add_listener(text, &text_listener, &probe);
    zwp_text_input_v1_activate(text, probe.seat, surface);
    zwp_text_input_v1_set_surrounding_text(text, "", 0, 0);
    zwp_text_input_v1_set_content_type(text, 0, ZWP_TEXT_INPUT_V1_CONTENT_PURPOSE_NORMAL);
    zwp_text_input_v1_set_cursor_rectangle(text, 100, 100, 1, 24);
    zwp_text_input_v1_show_input_panel(text);
    zwp_text_input_v1_commit_state(text, 1);
    while (!probe.committed && wl_display_dispatch(display) >= 0) {}
    zwp_text_input_v1_deactivate(text, probe.seat);
    wl_display_roundtrip(display);
    wl_display_disconnect(display);
    return probe.committed ? 0 : 4;
}
