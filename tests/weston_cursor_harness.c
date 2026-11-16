/* Runs the actual cursor-update function with deterministic RDP/renderer stubs. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

typedef int BOOL;
typedef unsigned char BYTE;
#define TRUE 1
#define FALSE 0
#define SYSPTR_NULL 0
struct region { int dirty; };
struct weston_rdp_rail_window_pos { int32_t x,y; uint32_t width,height; };
struct weston_surface_rail_state {
    struct weston_rdp_rail_window_pos clientPos;
    struct region damage;
};
struct weston_pointer { int32_t hotspot_x,hotspot_y; };
struct weston_compositor { int unused; };
struct weston_output { int scale; };
struct weston_surface {
    void *committed_private,*backend_state;
    struct weston_compositor *compositor;
    struct weston_output *output;
    int width,height,buffer_width,buffer_height;
};
typedef struct { int type; } POINTER_SYSTEM_UPDATE;
typedef struct {
    int xorBpp,cacheIndex,hotSpotX,hotSpotY,width,height;
    int lengthAndMask,lengthXorMask;
    BYTE *xorMaskData,*andMaskData;
} POINTER_LARGE_UPDATE;
struct pointer_api {
    void (*PointerSystem)(void *, POINTER_SYSTEM_UPDATE *);
    void (*PointerLarge)(void *, POINTER_LARGE_UPDATE *);
};
typedef struct {
    struct pointer_api *pointer;
    void *context;
    void (*BeginPaint)(void *),(*EndPaint)(void *);
} rdpUpdate;
typedef struct {
    rdpUpdate *update;
    uint32_t cursor_hotspot_x,cursor_hotspot_y;
} RdpPeerContext;
struct peer { RdpPeerContext *context; };
struct rdp_backend { struct peer *rdp_peer; };
static struct rdp_backend backend;
static POINTER_LARGE_UPDATE sent;
static int updates,hidden,copy_failure,source_width,source_height;
static struct rdp_backend *to_rdp_backend(struct weston_compositor *c) { (void)c; return &backend; }
#define assert_compositor_thread(b) ((void)(b))
#define rdp_debug_verbose(...) ((void)0)
#define rdp_debug_error(...) ((void)0)
#define xmalloc malloc
static void weston_surface_get_content_size(struct weston_surface *s,int *w,int *h) { *w=s->buffer_width;*h=s->buffer_height; }
static void to_client_coordinate(RdpPeerContext *p,struct weston_output *o,int32_t *x,int32_t *y,uint32_t *w,uint32_t *h) {
    (void)p;(void)x;(void)y;*w*=o->scale;*h*=o->scale;
}
static int pixman_region32_not_empty(struct region *r) { return r->dirty; }
static void pixman_region32_clear(struct region *r) { r->dirty=0; }
static int weston_surface_copy_content(struct weston_surface *s,void *bits,size_t bytes,size_t stride,int w,int h,int x,int y,int sw,int sh,bool flip,bool argb) {
    (void)s;(void)bits;(void)stride;(void)x;(void)y;
    assert(bytes==(size_t)w*h*4);assert(flip&&argb);
    source_width=sw;source_height=sh;return copy_failure ? -1 : 0;
}
static void paint(void *p) { (void)p; }
static void system_pointer(void *p,POINTER_SYSTEM_UPDATE *u) { (void)p;(void)u;hidden++; }
static void large_pointer(void *p,POINTER_LARGE_UPDATE *u) { (void)p;sent=*u;updates++; }

#include "cursor-under-test.h"

int main(void) {
    struct pointer_api api={system_pointer,large_pointer};
    rdpUpdate update={&api,NULL,paint,paint};
    RdpPeerContext context={.update=&update};
    struct peer peer={&context};backend.rdp_peer=&peer;
    struct weston_compositor compositor={0};
    struct weston_surface_rail_state rail={0};
    struct weston_pointer pointer={8,8};
    struct weston_output output={2};
    struct weston_surface surface={&pointer,&rail,&compositor,&output,24,24,24,24};
    int cases=0;
    for(int scale=1;scale<=2;scale++)for(int buffer_scale=1;buffer_scale<=2;buffer_scale++) {
        memset(&rail,0,sizeof rail);rail.damage.dirty=1;output.scale=scale;
        surface.buffer_width=surface.buffer_height=24*buffer_scale;
        int before=updates;assert(rdp_rail_update_cursor(&surface)==0);
        assert(updates==before+1);assert(sent.width==24*scale&&sent.height==24*scale);
        assert(sent.hotSpotX==8*scale&&sent.hotSpotY==8*scale);
        assert(source_width==24*buffer_scale&&source_height==24*buffer_scale);
        before=updates;assert(rdp_rail_update_cursor(&surface)==0);assert(updates==before);
        pointer.hotspot_x=9;assert(rdp_rail_update_cursor(&surface)==0);
        assert(updates==before+1&&sent.hotSpotX==9*scale);
        pointer.hotspot_x=8;rail.damage.dirty=1;cases++;
    }
    /* Missing output is 1:1; endpoints must remain valid RDP bitmap indices. */
    surface.output=NULL;rail.damage.dirty=1;pointer.hotspot_x=-3;pointer.hotspot_y=30;
    assert(rdp_rail_update_cursor(&surface)==0);
    assert(sent.width==24&&sent.hotSpotX==0&&sent.hotSpotY==23);cases++;
    assert(rdp_rail_cursor_hotspot(1,3,5)==2);
    assert(rdp_rail_cursor_hotspot(INT32_MAX,24,48)==47);
    assert(rdp_rail_cursor_hotspot(8,0,0)==0);cases++;
    surface.width=surface.height=0;int before=updates;
    assert(rdp_rail_update_cursor(&surface)==0);assert(hidden==1&&updates==before);cases++;
    /* A failed readback must not falsely cache the unsent hotspot. */
    surface.width=surface.height=24;copy_failure=1;pointer.hotspot_x=4;
    uint32_t cached=context.cursor_hotspot_x;
    assert(rdp_rail_update_cursor(&surface)==-1);assert(context.cursor_hotspot_x==cached);cases++;
    printf("PASS: %d cursor geometry/update scenarios\n",cases);
    return 0;
}
