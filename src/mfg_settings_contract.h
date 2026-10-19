/* SPDX-License-Identifier: MIT
 * Shared by the private addon, its OptiScaler UI and host-side geometry tests.
 * Saved settings apply at process startup. ABI fields are fixed-width integers.
 */
#ifndef BC250_MFG_SETTINGS_CONTRACT_H
#define BC250_MFG_SETTINGS_CONTRACT_H
#include <stdint.h>

enum bc250_fg_resolution { BC250_FG_OUTPUT=0, BC250_FG_SCALE=1, BC250_FG_LIMIT=2 };
enum bc250_fg_filter {
 BC250_FG_BILINEAR=0, BC250_FG_AREA=1, BC250_FG_BICUBIC=2,
 BC250_FG_LANCZOS2=3, BC250_FG_FSR1=4
};
struct bc250_fg_settings {
 uint32_t resolution, percent, height_limit, downscale, upscale;
};
struct bc250_fg_status {
 uint32_t size, version;
 struct bc250_fg_settings applied;
 uint32_t output_width, output_height, generated_width, generated_height;
 uint32_t ready, launch_override;
 uint32_t downscale_mask, upscale_mask;
};
#define BC250_FG_SETTINGS_VERSION 1u

static struct bc250_fg_settings bc250_fg_defaults(void) {
 struct bc250_fg_settings s={BC250_FG_OUTPUT,75,1080,BC250_FG_BILINEAR,BC250_FG_BILINEAR};
 return s;
}
static int bc250_fg_settings_valid(const struct bc250_fg_settings*s) {
 return s&&s->resolution<=BC250_FG_LIMIT&&s->percent>=50&&s->percent<=100&&
  (s->height_limit==720||s->height_limit==1080||s->height_limit==1440||s->height_limit==2160)&&
  s->downscale<=BC250_FG_LANCZOS2&&
  (s->upscale==BC250_FG_BILINEAR||s->upscale==BC250_FG_BICUBIC||
   s->upscale==BC250_FG_LANCZOS2||s->upscale==BC250_FG_FSR1);
}
/* Native output, including odd dimensions, must remain untouched. Scaled
 * reconstruction uses even extents, bounded by the actual output dimensions.
 * Limits fit a16:9 box, preserving the delivered1920x1080 cap behavior. */
static int bc250_fg_dimensions(const struct bc250_fg_settings*s,uint32_t w,uint32_t h,
                              uint32_t*tw,uint32_t*th) {
 if(!tw||!th||!w||!h||!bc250_fg_settings_valid(s))return 0;
 *tw=w;*th=h;
 if(s->resolution==BC250_FG_OUTPUT)return 1;
 if(s->resolution==BC250_FG_SCALE) {
  if(s->percent==100)return 1;
  *tw=(uint32_t)((uint64_t)w*s->percent/100);
  *th=(uint32_t)((uint64_t)h*s->percent/100);
 }else {
  uint32_t bh=s->height_limit,bw=bh*16/9;
  if(w<=bw&&h<=bh)return 1;
  if((uint64_t)w*bh>=(uint64_t)h*bw){*tw=bw;*th=(uint32_t)((uint64_t)h*bw/w);}
  else{*th=bh;*tw=(uint32_t)((uint64_t)w*bh/h);}
 }
 *tw=*tw>1?*tw&~1u:1;
 *th=*th>1?*th&~1u:1;
 return *tw<=w&&*th<=h;
}
#endif
