/* Live native-Wayland/D3D12 pointer calibration. Logs only this window's input.
 * The optional cursor has a known surface-local hotspot for host-side checks. */
#define _GNU_SOURCE
#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <sys/mman.h>
#include <poll.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include "xdg-shell-client-protocol.h"

struct output { struct wl_output *object; int scale; };
struct state {
 struct wl_display *display; struct wl_compositor *compositor; struct wl_shm *shm;
 struct wl_seat *seat; struct wl_pointer *pointer; struct xdg_wm_base *wm;
 struct wl_surface *surface, *cursor_surface; struct wl_buffer *cursor_buffer;
 struct xdg_surface *xdg; struct xdg_toplevel *top; struct wl_egl_window *window;
 struct output outputs[8]; unsigned output_count;
 EGLDisplay ed; EGLContext ec; EGLSurface es;
 int width,height,scale,configured,done,cursor_scale; double px,py;
};
static void rect(struct state *s,int x,int y,int w,int h,float r,float g,float b) {
 glScissor(x*s->scale,(s->height-y-h)*s->scale,w*s->scale,h*s->scale);
 glClearColor(r,g,b,1);glClear(GL_COLOR_BUFFER_BIT);
}
static void draw(struct state *s) {
 if(!s->window)return;
 wl_surface_set_buffer_scale(s->surface,s->scale);
 wl_egl_window_resize(s->window,s->width*s->scale,s->height*s->scale,0,0);
 glViewport(0,0,s->width*s->scale,s->height*s->scale);
 glDisable(GL_SCISSOR_TEST);glClearColor(.08,.10,.15,1);glClear(GL_COLOR_BUFFER_BIT);
 glEnable(GL_SCISSOR_TEST);
 rect(s,0,0,s->width,24,1,.5,0);rect(s,0,0,3,s->height,1,.5,0);
 rect(s,s->width-3,0,3,s->height,1,.5,0);rect(s,0,s->height-3,s->width,3,1,.5,0);
 int xs[]={64,s->width/2,s->width-64},ys[]={64,s->height/2,s->height-64};
 for(int y=0;y<3;y++)for(int x=0;x<3;x++)rect(s,xs[x]-9,ys[y]-9,18,18,0,1,1);
 if(s->px>=0){rect(s,(int)s->px-12,(int)s->py,25,1,1,0,1);rect(s,(int)s->px,(int)s->py-12,1,25,1,0,1);}
 glDisable(GL_SCISSOR_TEST);eglSwapBuffers(s->ed,s->es);
}
static void enter(void*d,struct wl_pointer*p,uint32_t serial,struct wl_surface*f,wl_fixed_t x,wl_fixed_t y){
 struct state*s=d;(void)f;s->px=wl_fixed_to_double(x);s->py=wl_fixed_to_double(y);
 if(s->cursor_surface)wl_pointer_set_cursor(p,serial,s->cursor_surface,8,8);
 printf("{\"event\":\"enter\",\"x\":%.4f,\"y\":%.4f}\n",s->px,s->py);draw(s);
}
static void leave(void*d,struct wl_pointer*p,uint32_t n,struct wl_surface*f){(void)d;(void)p;(void)n;(void)f;puts("{\"event\":\"leave\"}");}
static void motion(void*d,struct wl_pointer*p,uint32_t t,wl_fixed_t x,wl_fixed_t y){
 struct state*s=d;(void)p;(void)t;s->px=wl_fixed_to_double(x);s->py=wl_fixed_to_double(y);
 printf("{\"event\":\"motion\",\"x\":%.4f,\"y\":%.4f}\n",s->px,s->py);draw(s);
}
static void button(void*d,struct wl_pointer*p,uint32_t n,uint32_t t,uint32_t b,uint32_t pressed){
 struct state*s=d;(void)p;(void)n;(void)t;
 printf("{\"event\":\"button\",\"button\":%u,\"pressed\":%u,\"x\":%.4f,\"y\":%.4f}\n",b,pressed,s->px,s->py);
 if(pressed&&b==272&&s->py<24)xdg_toplevel_move(s->top,s->seat,n);
}
static void axis(void*d,struct wl_pointer*p,uint32_t t,uint32_t a,wl_fixed_t v){(void)d;(void)p;(void)t;(void)a;(void)v;}
static const struct wl_pointer_listener pl={.enter=enter,.leave=leave,.motion=motion,.button=button,.axis=axis};
static void capabilities(void*d,struct wl_seat*seat,uint32_t caps){struct state*s=d;if((caps&WL_SEAT_CAPABILITY_POINTER)&&!s->pointer){s->pointer=wl_seat_get_pointer(seat);wl_pointer_add_listener(s->pointer,&pl,s);}}
static void seat_name(void*d,struct wl_seat*s,const char*n){(void)d;(void)s;(void)n;}
static const struct wl_seat_listener sl={capabilities,seat_name};
static void geom(void*d,struct wl_output*o,int32_t x,int32_t y,int32_t pw,int32_t ph,int32_t sub,const char*make,const char*model,int32_t transform){(void)d;(void)o;(void)x;(void)y;(void)pw;(void)ph;(void)sub;(void)make;(void)model;(void)transform;}
static void mode(void*d,struct wl_output*o,uint32_t flags,int32_t w,int32_t h,int32_t rate){(void)d;(void)o;(void)flags;(void)w;(void)h;(void)rate;}
static void output_done(void*d,struct wl_output*o){(void)d;(void)o;}
static void output_scale(void*d,struct wl_output*o,int32_t scale){(void)o;((struct output*)d)->scale=scale;}
static const struct wl_output_listener ol={geom,mode,output_done,output_scale};
static void surface_enter(void*d,struct wl_surface*f,struct wl_output*o){
 struct state*s=d;(void)f;for(unsigned i=0;i<s->output_count;i++)if(s->outputs[i].object==o){
  s->scale=s->outputs[i].scale;printf("{\"event\":\"output-enter\",\"index\":%u,\"scale\":%d}\n",i,s->scale);draw(s);break;
 }
}
static void surface_leave(void*d,struct wl_surface*f,struct wl_output*o){(void)d;(void)f;(void)o;}
static const struct wl_surface_listener sfl={surface_enter,surface_leave};
static void ping(void*d,struct xdg_wm_base*w,uint32_t n){(void)d;xdg_wm_base_pong(w,n);}
static const struct xdg_wm_base_listener wml={ping};
static void global(void*d,struct wl_registry*r,uint32_t n,const char*i,uint32_t v){
 struct state*s=d;
 if(!strcmp(i,"wl_compositor"))s->compositor=wl_registry_bind(r,n,&wl_compositor_interface,v<4?v:4);
 else if(!strcmp(i,"wl_shm"))s->shm=wl_registry_bind(r,n,&wl_shm_interface,1);
 else if(!strcmp(i,"wl_seat")){s->seat=wl_registry_bind(r,n,&wl_seat_interface,4);wl_seat_add_listener(s->seat,&sl,s);}
 else if(!strcmp(i,"xdg_wm_base")){s->wm=wl_registry_bind(r,n,&xdg_wm_base_interface,1);xdg_wm_base_add_listener(s->wm,&wml,s);}
 else if(!strcmp(i,"wl_output")&&s->output_count<8){struct output*o=&s->outputs[s->output_count++];o->scale=1;o->object=wl_registry_bind(r,n,&wl_output_interface,2);wl_output_add_listener(o->object,&ol,o);}
}
static void removed(void*d,struct wl_registry*r,uint32_t n){(void)d;(void)r;(void)n;}
static const struct wl_registry_listener rl={global,removed};
static void configure(void*d,struct xdg_surface*x,uint32_t n){struct state*s=d;xdg_surface_ack_configure(x,n);s->configured=1;printf("{\"event\":\"configure\",\"width\":%d,\"height\":%d,\"scale\":%d}\n",s->width,s->height,s->scale);draw(s);}
static const struct xdg_surface_listener xl={configure};
static void top_config(void*d,struct xdg_toplevel*t,int32_t w,int32_t h,struct wl_array*a){struct state*s=d;(void)t;(void)a;if(w>0&&h>0){s->width=w;s->height=h;}}
static void top_close(void*d,struct xdg_toplevel*t){(void)t;((struct state*)d)->done=1;}
static const struct xdg_toplevel_listener tl={top_config,top_close};
static void cursor_create(struct state*s){
 int scale=s->cursor_scale,size=24*scale,stride=size*4;size_t bytes=size*stride;
 int fd=memfd_create("wslg-known-cursor",MFD_CLOEXEC);if(fd<0||ftruncate(fd,bytes))exit(10);
 uint32_t*p=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(p==MAP_FAILED)exit(11);
 for(int y=0;y<size;y++)for(int x=0;x<size;x++){
  int lx=x/scale,ly=y/scale;p[y*size+x]=((lx>=7&&lx<=9&&ly<=16)||(ly>=7&&ly<=9&&lx<=16))?0xffffffff:0;
  if(lx==8&&ly==8)p[y*size+x]=0xffff00ff;
 }
 struct wl_shm_pool*pool=wl_shm_create_pool(s->shm,fd,bytes);s->cursor_buffer=wl_shm_pool_create_buffer(pool,0,size,size,stride,WL_SHM_FORMAT_ARGB8888);wl_shm_pool_destroy(pool);close(fd);munmap(p,bytes);
 s->cursor_surface=wl_compositor_create_surface(s->compositor);wl_surface_set_buffer_scale(s->cursor_surface,scale);wl_surface_attach(s->cursor_surface,s->cursor_buffer,0,0);wl_surface_damage(s->cursor_surface,0,0,24,24);wl_surface_commit(s->cursor_surface);
 printf("{\"event\":\"known-cursor\",\"logical_width\":24,\"buffer_scale\":%d,\"hotspot_x\":8,\"hotspot_y\":8}\n",scale);
}
int main(int argc,char**argv){
 struct state s={.width=480,.height=320,.scale=2,.px=-1,.py=-1,.ed=EGL_NO_DISPLAY,.ec=EGL_NO_CONTEXT,.es=EGL_NO_SURFACE};setbuf(stdout,NULL);
 if(argc==3&&!strcmp(argv[1],"--cursor-scale")){s.cursor_scale=atoi(argv[2]);if(s.cursor_scale<1||s.cursor_scale>2)return 12;}
 s.display=wl_display_connect(NULL);if(!s.display)return 2;
 struct wl_registry*r=wl_display_get_registry(s.display);wl_registry_add_listener(r,&rl,&s);wl_display_roundtrip(s.display);wl_display_roundtrip(s.display);
 if(!s.compositor||!s.shm||!s.wm||!s.seat)return 3;
 s.surface=wl_compositor_create_surface(s.compositor);wl_surface_add_listener(s.surface,&sfl,&s);
 if(s.cursor_scale)cursor_create(&s);
 s.xdg=xdg_wm_base_get_xdg_surface(s.wm,s.surface);xdg_surface_add_listener(s.xdg,&xl,&s);
 s.top=xdg_surface_get_toplevel(s.xdg);xdg_toplevel_add_listener(s.top,&tl,&s);xdg_toplevel_set_title(s.top,"WSLg D3D12 pointer calibration");xdg_toplevel_set_app_id(s.top,"wslg-pointer-probe");wl_surface_commit(s.surface);
 while(!s.configured)if(wl_display_dispatch(s.display)<0)return 4;
 s.ed=eglGetDisplay((EGLNativeDisplayType)s.display);EGLint major,minor;if(!eglInitialize(s.ed,&major,&minor))return 5;
 EGLint attrs[]={EGL_SURFACE_TYPE,EGL_WINDOW_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,0,EGL_NONE};EGLConfig cfg;EGLint count;if(!eglChooseConfig(s.ed,attrs,&cfg,1,&count)||count<1)return 6;
 eglBindAPI(EGL_OPENGL_ES_API);EGLint ca[]={EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE};s.ec=eglCreateContext(s.ed,cfg,EGL_NO_CONTEXT,ca);s.window=wl_egl_window_create(s.surface,s.width*s.scale,s.height*s.scale);s.es=eglCreateWindowSurface(s.ed,cfg,(EGLNativeWindowType)s.window,NULL);
 if(!eglMakeCurrent(s.ed,s.es,s.es,s.ec))return 7;
 const char*renderer=(const char*)glGetString(GL_RENDERER);printf("{\"event\":\"renderer\",\"renderer\":\"%s\"}\n",renderer?renderer:"");
 if(!renderer||!strstr(renderer,"D3D12"))return 8;
 draw(&s);time_t end=time(NULL)+1200;
 while(!s.done&&time(NULL)<end){
  while(wl_display_prepare_read(s.display)!=0)if(wl_display_dispatch_pending(s.display)<0)goto finish;
  wl_display_flush(s.display);struct pollfd f={wl_display_get_fd(s.display),POLLIN,0};
  if(poll(&f,1,250)>0){if(wl_display_read_events(s.display)<0)break;wl_display_dispatch_pending(s.display);}else wl_display_cancel_read(s.display);
 }
finish:
 eglMakeCurrent(s.ed,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroySurface(s.ed,s.es);eglDestroyContext(s.ed,s.ec);wl_egl_window_destroy(s.window);eglTerminate(s.ed);wl_display_disconnect(s.display);return 0;
}
