/* SPDX-License-Identifier: MIT
 * Test-only shell for an isolated Weston instance, never the live desktop.
 * Runs the installed, unmodified text backend with an isolated keyboard seat.
 */
#include "config.h"
#include <stdbool.h>
#include <time.h>
#include <stdlib.h>
#include <string.h>
#include <libweston/libweston.h>
#include "libweston/libweston-internal.h"
#include "libweston/backend.h"
#include "compositor/weston.h"
#ifdef WSLG_IME_PANEL_FIXTURE
#include <assert.h>
#include <libweston/backend-rdp.h>
#include "rdprail-shell/shell.h"
#endif

struct ime_fixture {
#ifdef WSLG_IME_PANEL_FIXTURE
    struct desktop_shell shell;
    bool panel_checks_scheduled;
#endif
    struct weston_seat seat;
    struct text_backend *text;
    struct wl_listener destroy;
    struct wl_listener show;
    struct wl_event_source *timer;
    size_t key_index;
    bool started;
};

#ifdef WSLG_IME_PANEL_FIXTURE
static struct ime_fixture *panel_fixture;

struct weston_view *get_default_view(struct weston_surface *surface)
{
    struct weston_view *view;
    if (wl_list_empty(&surface->views))
        return NULL;
    view = wl_container_of(surface->views.next, view, surface_link);
    return view;
}

static void check_panel_lifecycle(void *data)
{
    struct weston_surface *panel = data;
    struct desktop_shell *shell = &panel_fixture->shell;
    struct weston_surface *parent = shell->text_input.surface;
    struct weston_view *view = get_default_view(panel);
    struct weston_view *parent_view = get_default_view(parent);
    pixman_box32_t original = shell->text_input.cursor_rectangle;
    float old_x = parent_view->geometry.x, old_y = parent_view->geometry.y;
    assert(panel->is_mapped && view->is_mapped);
    weston_view_set_position(parent_view, 200, 150);
    weston_view_update_transform(parent_view);
    assert(view->geometry.x == 300 && view->geometry.y == 274);
    weston_log("IME_PANEL_CHECK parent-move passed\n");
    pixman_box32_t edge = {1000, 700, 1001, 724};
    wl_signal_emit(&shell->compositor->update_input_panel_signal, &edge);
    assert(view->geometry.x + panel->width <= parent->output->x + parent->output->width);
    assert(view->geometry.y + panel->height <= parent->output->y + parent->output->height);
    weston_log("IME_PANEL_CHECK output-clamp passed\n");
    wl_signal_emit(&shell->compositor->hide_input_panel_signal, NULL);
    assert(!panel->is_mapped && !view->is_mapped && !panel->output);
    wl_signal_emit(&shell->compositor->show_input_panel_signal, parent);
    assert(panel->is_mapped && view->is_mapped);
    input_panel_hide_for_surface(shell, parent);
    assert(!panel->is_mapped && !view->is_mapped);
    wl_signal_emit(&shell->compositor->show_input_panel_signal, parent);
    assert(panel->is_mapped);
    weston_log("IME_PANEL_CHECK hide-show-and-minimize-hook passed\n");
    struct weston_surface *other = weston_surface_create(shell->compositor);
    struct weston_view *other_view = weston_view_create(other);
    other->width = 400;
    other->height = 200;
    other->is_mapped = other_view->is_mapped = true;
    weston_layer_entry_insert(&shell->input_panel.layer.view_list, &other_view->layer_link);
    weston_view_set_position(other_view, 30, 30);
    weston_view_update_transform(other_view);
    wl_signal_emit(&shell->compositor->show_input_panel_signal, other);
    assert(panel->is_mapped && shell->text_input.surface == other);
    weston_surface_destroy(other);
    assert(!panel->is_mapped && !shell->text_input.surface);
    wl_signal_emit(&shell->compositor->show_input_panel_signal, parent);
    assert(panel->is_mapped && shell->text_input.surface == parent);
    weston_view_set_position(parent_view, old_x, old_y);
    weston_view_update_transform(parent_view);
    wl_signal_emit(&shell->compositor->update_input_panel_signal, &original);
    weston_log("IME_PANEL_CHECK owner-destroy-and-reuse passed\n");
}

static void record_panel(struct weston_surface *surface,
                         struct weston_surface *parent, bool visible)
{
    struct weston_view *view = get_default_view(surface);
    assert(surface->role_name && !strcmp(surface->role_name, WESTON_RDPRAIL_INPUT_PANEL_ROLE));
    if (visible) {
        assert(parent && parent != surface && view && view->is_mapped);
        assert(surface->output && view->geometry.x >= surface->output->x);
        assert(view->geometry.y >= surface->output->y);
        if (surface->width > 100 && !panel_fixture->panel_checks_scheduled) {
            panel_fixture->panel_checks_scheduled = true;
            wl_event_loop_add_idle(wl_display_get_event_loop(surface->compositor->wl_display),
                                   check_panel_lifecycle, surface);
        }
    }
    weston_log("IME_PANEL visible=%d mapped=%d owner=%d x=%.0f y=%.0f w=%d h=%d\n",
               visible, view ? view->is_mapped : 0, parent != NULL,
               view ? view->geometry.x : 0, view ? view->geometry.y : 0,
               surface->width, surface->height);
}
static const struct weston_rdprail_input_panel_api mock_rail_api = {record_panel};
#endif

/* Deliberately synthetic n-i-h-a-o-space, only in this isolated test seat. */
static int send_probe_key(void *data)
{
    struct ime_fixture *fixture = data;
    static const uint32_t keys[] = {49, 23, 35, 30, 24, 57};
    struct timespec time;
    size_t pair = fixture->key_index / 2;
    bool released = (fixture->key_index % 2) != 0;
    clock_gettime(CLOCK_MONOTONIC, &time);
    notify_key(&fixture->seat, &time, keys[pair],
               released ? WL_KEYBOARD_KEY_STATE_RELEASED : WL_KEYBOARD_KEY_STATE_PRESSED,
               STATE_UPDATE_AUTOMATIC);
    fixture->key_index++;
    if (fixture->key_index < sizeof(keys) / sizeof(keys[0]) * 2)
        wl_event_source_timer_update(fixture->timer, released ? 180 : 40);
    return 0;
}

static void input_activated(struct wl_listener *listener, void *data)
{
    struct ime_fixture *fixture = wl_container_of(listener, fixture, show);
    const char *enabled = getenv("WSLG_IME_PROBE_KEYS");
    if (!enabled || enabled[0] != '1' || fixture->started || !data)
        return;
    fixture->started = true;
#ifdef WSLG_IME_PANEL_FIXTURE
    /* This client has no UI buffer: construct ONLY its fixture parent view.
     * Candidate buffers still come from the real isolated Fcitx classic UI. */
    struct weston_surface *surface = data;
    struct weston_view *view = weston_view_create(surface);
    surface->width = 640;
    surface->height = 360;
    surface->is_mapped = view->is_mapped = true;
    weston_layer_entry_insert(&fixture->shell.input_panel.layer.view_list,
                              &view->layer_link);
    weston_view_set_position(view, 16, 20);
    weston_view_update_transform(view);
#endif
    weston_keyboard_set_focus(weston_seat_get_keyboard(&fixture->seat), data);
    fixture->timer = wl_event_loop_add_timer(
        wl_display_get_event_loop(fixture->seat.compositor->wl_display),
        send_probe_key, fixture);
    wl_event_source_timer_update(fixture->timer, 1200);
    weston_log("IME protocol fixture: scheduling synthetic pinyin probe keys\n");
}

static void destroy_fixture(struct wl_listener *listener, void *data)
{
    struct ime_fixture *fixture =
        wl_container_of(listener, fixture, destroy);
    (void)data;
    wl_list_remove(&fixture->destroy.link);
    wl_list_remove(&fixture->show.link);
    if (fixture->timer)
        wl_event_source_remove(fixture->timer);
#ifdef WSLG_IME_PANEL_FIXTURE
    fixture->shell.input_panel.shutting_down = true;
#endif
    text_backend_destroy(fixture->text);
#ifdef WSLG_IME_PANEL_FIXTURE
    input_panel_destroy(&fixture->shell);
#endif
    weston_seat_release(&fixture->seat);
    free(fixture);
}

WL_EXPORT int wet_shell_init(struct weston_compositor *compositor,
                             int *argc, char *argv[])
{
    struct ime_fixture *fixture = calloc(1, sizeof(*fixture));
    (void)argc;
    (void)argv;
    if (!fixture)
        return -1;
    weston_seat_init(&fixture->seat, compositor, "ime-protocol-fixture");
    if (weston_seat_init_keyboard(&fixture->seat, NULL) < 0) {
        weston_seat_release(&fixture->seat);
        free(fixture);
        return -1;
    }
#ifdef WSLG_IME_PANEL_FIXTURE
    panel_fixture = fixture;
    fixture->shell.compositor = compositor;
    wl_list_init(&fixture->shell.output_list);
    if (weston_plugin_api_register(compositor, WESTON_RDPRAIL_INPUT_PANEL_API_NAME,
                                  &mock_rail_api, sizeof mock_rail_api) < 0 ||
        input_panel_setup(&fixture->shell) < 0)
        return -1;
#endif
    fixture->text = text_backend_init(compositor);
    if (!fixture->text) {
        weston_seat_release(&fixture->seat);
        free(fixture);
        return -1;
    }
    fixture->show.notify = input_activated;
    wl_signal_add(&compositor->show_input_panel_signal, &fixture->show);
    fixture->destroy.notify = destroy_fixture;
    wl_signal_add(&compositor->destroy_signal, &fixture->destroy);
    weston_log("IME protocol fixture: isolated seat and stock text backend ready\n");
    return 0;
}
