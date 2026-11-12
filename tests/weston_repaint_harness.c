/* SPDX-License-Identifier: MIT
 * Test boundary for extracted Weston functions, not a replacement backend.
 * Uses real pthreads, eventfd, Wayland lists, and Pixman regions. FreeRDP PDUs,
 * compositor scheduling, and the buffer transport are intentionally stubbed.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <pixman.h>

typedef unsigned UINT;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define CHANNEL_RC_OK 0
#define WL_EVENT_READABLE 1

struct weston_compositor;
struct weston_output {
	struct weston_compositor *compositor;
	uint32_t id;
	struct wl_list link;
	bool repaint_needed;
	unsigned schedule_calls;
};
struct weston_compositor {
	struct wl_list output_list;
	struct rdp_backend *backend;
	bool asleep;
};
struct weston_surface_rail_state {
	uint32_t window_id;
	BOOL isUpdatePending;
	bool isCursor;
	bool show_state_dirty;
	pixman_region32_t damage;
	unsigned presents;
};
struct weston_surface {
	struct weston_compositor *compositor;
	void *backend_state;
	uint32_t output_mask;
};
struct rdp_id_manager {
	pthread_mutex_t mutex;
	struct weston_surface *surfaces[8];
	size_t count;
};
struct rdp_peer_context;
typedef struct rdp_peer_context RdpPeerContext;
struct freerdp_peer {
	void *context;
	BOOL (*CheckFileDescriptor)(struct freerdp_peer *);
};
typedef struct freerdp_peer freerdp_peer;
typedef struct RdpgfxServerContext {
	void *custom;
	void (*EndFrame)(struct RdpgfxServerContext *, void *);
} RdpgfxServerContext;
typedef struct { void *custom; } GfxRedirServerContext;
typedef struct {
	uint32_t queueDepth, frameId, totalFramesDecoded;
} RDPGFX_FRAME_ACKNOWLEDGE_PDU;
typedef struct { uint32_t frameId; } RDPGFX_END_FRAME_PDU;
typedef struct { uint64_t windowId, presentId; } GFXREDIR_PRESENT_BUFFER_ACK_PDU;

struct rdp_backend {
	struct weston_compositor *compositor;
	freerdp_peer *rdp_peer;
	pthread_t compositor_thread;
	bool enable_display_power_by_screenupdate;
};
struct rdp_peer_context {
	struct rdp_backend *rdpBackend;
	struct rdp_id_manager windowId;
	uint32_t currentFrameId, acknowledgedFrameId;
	bool isAcknowledgedSuspended;
	bool is_window_zorder_dirty;
	RdpgfxServerContext *rail_grfx_server_context;
	void *vcm;
	int loop_task_event_source_fd;
	struct wl_event_source *loop_task_event_source;
	pthread_mutex_t loop_task_list_mutex;
	struct wl_list loop_task_list;
#if CANDIDATE
	bool rail_repaint_task_pending;
#endif
};
typedef void (*rdp_loop_task_func_t)(bool freeOnly, void *data);

/* SOURCE_TYPES: actual rdp_loop_task / rdp_output / iterator definitions. */

static struct rdp_backend *to_rdp_backend(struct weston_compositor *c)
{ return c->backend; }
static struct rdp_output *to_rdp_output(struct weston_output *o)
{ return wl_container_of(o, (struct rdp_output *)0, base); }
static void assert_compositor_thread(struct rdp_backend *b)
{ assert(pthread_equal(pthread_self(), b->compositor_thread)); }
static void assert_not_compositor_thread(struct rdp_backend *b)
{ assert(!pthread_equal(pthread_self(), b->compositor_thread)); }
/* Consume b so extracted baseline functions remain warning-clean. */
#define rdp_debug_verbose(b, ...) ((void)(b))
#define rdp_debug_error(b, ...) ((void)(b))
static unsigned allocations, frees_count;
static void *xmalloc(size_t size)
{
	void *p = malloc(size);
	assert(p);
	allocations++;
	return p;
}
static void counted_free(void *p) { if (p) frees_count++; free(p); }
static void rdp_id_manager_lock(struct rdp_id_manager *m)
{ assert(!pthread_mutex_lock(&m->mutex)); }
static void rdp_id_manager_unlock(struct rdp_id_manager *m)
{ assert(!pthread_mutex_unlock(&m->mutex)); }
static void *rdp_id_manager_lookup(struct rdp_id_manager *m, uint64_t id)
{
	for (size_t i = 0; i < m->count; i++) {
		struct weston_surface_rail_state *r = m->surfaces[i]->backend_state;
		if (r->window_id == id) return m->surfaces[i];
	}
	return NULL;
}
static void rdp_id_manager_for_each(struct rdp_id_manager *m,
				  void (*func)(void *, void *), void *data)
{ for (size_t i = 0; i < m->count; i++) func(m->surfaces[i], data); }
static void weston_output_schedule_repaint(struct weston_output *o)
{
	assert_compositor_thread(to_rdp_backend(o->compositor));
	if (!o->compositor->asleep) {
		o->repaint_needed = true;
		o->schedule_calls++;
	}
}
static void rdp_rail_sync_window_zorder(struct weston_compositor *c)
{ assert_compositor_thread(to_rdp_backend(c)); }
static void weston_compositor_wake(struct weston_compositor *c) { c->asleep = false; }
static void rdp_rail_update_cursor(struct weston_surface *s) { (void)s; }
static int rdp_rail_update_window(struct weston_surface *s,
				struct update_window_iter_data *iter)
{
	struct weston_surface_rail_state *r = s->backend_state;
	RdpPeerContext *p = to_rdp_backend(s->compositor)->rdp_peer->context;
	assert_compositor_thread(p->rdpBackend);
	assert(!r->isUpdatePending);
	r->show_state_dirty = false;
	if (pixman_region32_not_empty(&r->damage)) {
		r->presents++;
		r->isUpdatePending = TRUE;
		p->currentFrameId++;
		iter->isUpdatePending = TRUE;
		pixman_region32_clear(&r->damage);
	}
	return 0;
}
/* Event source initialization is outside the extracted boundary. Teardown
 * removes no source in this harness; it still drains actual queued tasks. */
static int wl_event_source_remove_stub(struct wl_event_source *s)
{ (void)s; assert(!"unexpected event source"); return 0; }

#define free counted_free
#define wl_event_source_remove wl_event_source_remove_stub
/* SOURCE_FUNCTIONS: actual queue, ACK, output and task teardown functions. */
#undef wl_event_source_remove
#undef free

static BOOL check_fd(freerdp_peer *p) { (void)p; return TRUE; }
static BOOL WTSVirtualChannelManagerCheckFileDescriptor(void *vcm)
{ (void)vcm; return TRUE; }
static int actual_destroy_wait(RdpPeerContext *peer_ctx,
			       struct weston_surface_rail_state *rail_state)
{
	freerdp_peer *client = peer_ctx->rail_grfx_server_context->custom;
	struct rdp_backend *b = peer_ctx->rdpBackend;
	/* SOURCE_DESTROY_WAIT: verbatim wait block from destroy-window. */
	return waitRetry;
}

struct fixture {
	struct weston_compositor compositor;
	struct rdp_backend backend;
	freerdp_peer client;
	RdpPeerContext peer;
	RdpgfxServerContext gfx;
	GfxRedirServerContext redir;
	struct rdp_output outputs[2];
	struct weston_surface surfaces[2];
	struct weston_surface_rail_state rails[2];
	bool linked[2];
};
static void init(struct fixture *f)
{
	memset(f, 0, sizeof *f);
	allocations = frees_count = 0;
	wl_list_init(&f->compositor.output_list);
	f->compositor.backend = &f->backend;
	f->backend.compositor = &f->compositor;
	f->backend.compositor_thread = pthread_self();
	f->backend.rdp_peer = &f->client;
	f->client.context = &f->peer;
	f->client.CheckFileDescriptor = check_fd;
	f->peer.rdpBackend = &f->backend;
	f->peer.rail_grfx_server_context = &f->gfx;
	f->gfx.custom = f->redir.custom = &f->client;
	assert(!pthread_mutex_init(&f->peer.windowId.mutex, NULL));
	assert(!pthread_mutex_init(&f->peer.loop_task_list_mutex, NULL));
	wl_list_init(&f->peer.loop_task_list);
	f->peer.loop_task_event_source_fd = eventfd(0, EFD_SEMAPHORE | EFD_NONBLOCK | EFD_CLOEXEC);
	assert(f->peer.loop_task_event_source_fd >= 0);
	for (unsigned i = 0; i < 2; i++) {
		f->outputs[i].base.compositor = &f->compositor;
		f->outputs[i].base.id = i;
		wl_list_insert(&f->compositor.output_list, &f->outputs[i].base.link);
		f->linked[i] = true;
		f->surfaces[i].compositor = &f->compositor;
		f->surfaces[i].backend_state = &f->rails[i];
		f->surfaces[i].output_mask = 1u << i;
		f->rails[i].window_id = i + 1;
		pixman_region32_init(&f->rails[i].damage);
		f->peer.windowId.surfaces[i] = &f->surfaces[i];
	}
	f->peer.windowId.count = 2;
}
static void finish(struct fixture *f)
{
	rdp_destroy_dispatch_task_event_source(&f->peer);
	assert(allocations == frees_count);
	assert(!pthread_mutex_destroy(&f->peer.windowId.mutex));
	for (unsigned i = 0; i < 2; i++) pixman_region32_fini(&f->rails[i].damage);
}
static unsigned tasks(struct fixture *f)
{ return wl_list_length(&f->peer.loop_task_list); }
static void dispatch(struct fixture *f)
{
	while (!wl_list_empty(&f->peer.loop_task_list))
		rdp_dispatch_task(f->peer.loop_task_event_source_fd, WL_EVENT_READABLE, &f->peer);
}
static void repaint(struct fixture *f, unsigned id)
{
	rdp_rail_output_repaint(&f->outputs[id].base, NULL);
	/* Core clears this after backend repaint, even when transport skipped. */
	f->outputs[id].base.repaint_needed = false;
}
static void damage(struct fixture *f, unsigned id)
{
	assert(pixman_region32_union_rect(&f->rails[id].damage,
		&f->rails[id].damage, 0, 0, 32, 32));
	f->rails[id].show_state_dirty = true;
}
struct ack_call {
	struct fixture *f;
	uint32_t id, depth;
	uint64_t window;
	bool gfxredir;
	unsigned repeat;
	unsigned delay_us;
};
static void *channel_thread(void *arg)
{
	struct ack_call *a = arg;
	if (a->delay_us) usleep(a->delay_us);
	for (unsigned i = 0; i < a->repeat; i++) {
		if (a->gfxredir) {
			GFXREDIR_PRESENT_BUFFER_ACK_PDU p = {a->window, a->id};
			assert(gfxredir_client_present_buffer_ack(&a->f->redir, &p) == CHANNEL_RC_OK);
		} else {
			RDPGFX_FRAME_ACKNOWLEDGE_PDU p = {a->depth, a->id, 0};
			assert(rail_grfx_client_frame_acknowledge(&a->f->gfx, &p) == CHANNEL_RC_OK);
		}
	}
	return NULL;
}
static void ack(struct fixture *f, uint32_t id, uint32_t depth,
		uint64_t window, bool gfxredir, unsigned repeat)
{
	struct ack_call a = {f, id, depth, window, gfxredir, repeat, 0};
	pthread_t t;
	assert(!pthread_create(&t, NULL, channel_thread, &a));
	assert(!pthread_join(t, NULL));
}
static void expect_resume(struct fixture *f, unsigned id)
{
	dispatch(f);
#if CANDIDATE
	assert(f->outputs[id].base.repaint_needed);
	repaint(f, id);
	assert(f->rails[id].presents == 1);
	assert(!pixman_region32_not_empty(&f->rails[id].damage));
	assert(!f->rails[id].show_state_dirty);
#else
	assert(!f->outputs[id].base.repaint_needed);
	assert(f->rails[id].presents == 0);
	assert(pixman_region32_not_empty(&f->rails[id].damage));
	assert(f->rails[id].show_state_dirty);
#endif
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *name = argv[1];
	struct fixture f;
	init(&f);
	if (!strcmp(name, "gfxredir-window-late-ack")) {
		f.peer.currentFrameId = 1;
		f.rails[0].isUpdatePending = TRUE;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 1, true, 1);
		assert(!f.rails[0].isUpdatePending);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "rdpgfx-global-late-ack") ||
		   !strcmp(name, "gfxredir-global-late-ack")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 2, name[0] == 'g', 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "still-throttled")) {
		f.peer.currentFrameId = 3;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 0, false, 1); dispatch(&f);
		assert(!f.outputs[0].base.schedule_calls);
		if (f.outputs[0].base.repaint_needed) repaint(&f, 0);
		assert(f.rails[0].presents == 0);
		ack(&f, 2, 0, 0, false, 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "ack-suspension")) {
		f.peer.currentFrameId = 30;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 0, UINT32_MAX, 0, false, 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "frame-id-wrap")) {
		f.peer.currentFrameId = UINT32_MAX;
		f.peer.acknowledgedFrameId = UINT32_MAX - 2;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, UINT32_MAX - 1, 0, 0, false, 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "ack-burst-coalesced")) {
		ack(&f, 1, 0, 0, false, 10000);
#if CANDIDATE
		assert(tasks(&f) == 1);
#else
		assert(tasks(&f) == 0);
#endif
		dispatch(&f);
		eventfd_t value;
		assert(eventfd_read(f.peer.loop_task_event_source_fd, &value) == -1 && errno == EAGAIN);
		assert(!f.outputs[0].base.schedule_calls && !f.outputs[1].base.schedule_calls);
	} else if (!strcmp(name, "ack-before-next-repaint")) {
		f.peer.currentFrameId = 1;
		ack(&f, 1, 0, 0, false, 1);
		damage(&f, 0); repaint(&f, 0); dispatch(&f);
		assert(f.rails[0].presents == 1);
		assert(!f.outputs[0].base.schedule_calls);
	} else if (!strcmp(name, "destroy-wait-progress")) {
		f.peer.currentFrameId = 5;
		f.peer.acknowledgedFrameId = 3;
		f.rails[0].isUpdatePending = TRUE;
		ack(&f, 5, 0, 1, true, 1);
		/* Evaluate the exact destroy-window wait condition without dispatching. */
		assert(!(f.rails[0].isUpdatePending ||
			(f.peer.currentFrameId != f.peer.acknowledgedFrameId &&
			 !f.peer.isAcknowledgedSuspended)));
		f.peer.acknowledgedFrameId = 3;
		ack(&f, 5, 0, 0, false, 1);
		assert(f.peer.currentFrameId == f.peer.acknowledgedFrameId);
	} else if (!strcmp(name, "actual-destroy-wait-rdpgfx") ||
		   !strcmp(name, "actual-destroy-wait-gfxredir")) {
		bool redir = !strcmp(name, "actual-destroy-wait-gfxredir");
		f.peer.currentFrameId = 5;
		f.peer.acknowledgedFrameId = 3;
		f.rails[0].isUpdatePending = redir;
		struct ack_call a = {&f, 5, 0, 1, redir, 1, 20000};
		pthread_t t;
		assert(!pthread_create(&t, NULL, channel_thread, &a));
		/* Do not dispatch display-loop tasks while actual Weston wait runs. */
		alarm(3);
		int retries = actual_destroy_wait(&f.peer, &f.rails[0]);
		alarm(0);
		assert(!pthread_join(t, NULL));
		assert(retries > 0 && retries < 100);
		assert(f.peer.acknowledgedFrameId == 5 && !f.rails[0].isUpdatePending);
	} else if (!strcmp(name, "multiple-windows-one-output")) {
		f.surfaces[1].output_mask = 1;
		f.peer.currentFrameId = 1;
		f.rails[0].isUpdatePending = TRUE;
		damage(&f, 0); damage(&f, 1); repaint(&f, 0);
		assert(f.rails[0].presents == 0 && f.rails[1].presents == 1);
		ack(&f, 1, 0, 1, true, 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "teardown-free-only")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 0, false, 1);
		/* finish drains actual tasks through freeOnly; no compositor call. */
		assert(!f.outputs[0].base.schedule_calls);
	} else if (!strcmp(name, "output-removed-before-dispatch")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 0, false, 1);
		wl_list_remove(&f.outputs[0].base.link); f.linked[0] = false;
		dispatch(&f);
		assert(!f.outputs[0].base.schedule_calls && !f.outputs[1].base.schedule_calls);
	} else if (!strcmp(name, "multi-output-retry")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); damage(&f, 1);
		repaint(&f, 0); repaint(&f, 1);
		ack(&f, 2, 0, 0, false, 1); dispatch(&f);
#if CANDIDATE
		assert(f.outputs[0].base.repaint_needed && f.outputs[1].base.repaint_needed);
		repaint(&f, 0); repaint(&f, 1);
		assert(f.rails[0].presents == 1 && f.rails[1].presents == 1);
#else
		assert(!f.outputs[0].base.repaint_needed && !f.outputs[1].base.repaint_needed);
#endif
	} else if (!strcmp(name, "unknown-window-ack")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 9999, true, 1);
		expect_resume(&f, 0);
	} else if (!strcmp(name, "no-repaint-feedback-loop")) {
		damage(&f, 0); repaint(&f, 0);
		ack(&f, 1, 0, 1, true, 1); dispatch(&f);
		assert(!f.outputs[0].base.repaint_needed);
		assert(!f.outputs[0].base.schedule_calls && f.rails[0].presents == 1);
	} else if (!strcmp(name, "sleep-retains-retry")) {
		f.peer.currentFrameId = 2;
		damage(&f, 0); repaint(&f, 0);
		f.compositor.asleep = true;
		ack(&f, 1, 0, 0, false, 1); dispatch(&f);
		assert(!f.outputs[0].base.repaint_needed);
		f.compositor.asleep = false;
		ack(&f, 1, 0, 0, false, 1);
		expect_resume(&f, 0);
	} else {
		fprintf(stderr, "Unknown case: %s\n", name); return 2;
	}
	finish(&f);
	assert(!f.outputs[1].base.schedule_calls || !strcmp(name, "multi-output-retry"));
	printf("%s: %s\n", name, CANDIDATE ? "candidate PASS" : "baseline observed");
	return 0;
}
