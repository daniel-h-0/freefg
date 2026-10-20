/* SPDX-License-Identifier: MIT
 * Geometry only. Leave temporal phases, model IDs, UI flags, depth and engine
 * motion-vector units untouched. Pure helpers also exercised against SDK dumps.
 */
static unsigned mg_ceil(unsigned v,unsigned d){return (v+d-1)/d;}
static unsigned mg_align(unsigned v,unsigned d){return mg_ceil(v,d)*d;}
static void mg_float(unsigned*p,float v){memcpy(p,&v,4);}
static void mg_cap(unsigned w,unsigned h,unsigned*tw,unsigned*th){
 *tw=w;*th=h;if(w<=1920&&h<=1080)return;
 if((uint64_t)w*1080>=(uint64_t)h*1920){*tw=1920;*th=(unsigned)((uint64_t)h*1920/w);}
 else {*th=1080;*tw=(unsigned)((uint64_t)w*1080/h);}
 /* Even extents for the half-resolution reconstruction grid; never enlarge. */
 *tw=*tw>1?*tw&~1u:1;*th=*th>1?*th&~1u:1;
}
/* s uses the MFG graph's stage numbering; native 2x maps its flow/FEC stages.
 * Return the geometry words rewritten, for validation against original input.
 */
static uint64_t mg_geometry(unsigned w,unsigned h,unsigned s,unsigned multi,unsigned*c,unsigned*g){
 unsigned f[2]={mg_ceil(w,16)*4,mg_ceil(h,16)*4};
 unsigned a[2]={f[0]/4,f[1]/4},b[2]={mg_ceil(a[0],4)*2,mg_ceil(a[1],4)*2},d[2]={b[0]/2,b[1]/2};
 uint64_t mask=0;
#define MG(i,v) do{c[i]=(v);mask|=1ULL<<(i);}while(0)
#define MF(i,v) do{mg_float(c+(i),(v));mask|=1ULL<<(i);}while(0)
#define GROUP(x,y,z) do{g[0]=(x);g[1]=(y);g[2]=(z);}while(0)
 if(s==0){MG(2,w);MG(3,h);MG(6,w);MG(7,h);MG(8,(f[0]*4-w)/2);MG(9,(f[1]*4-h)/2);GROUP(mg_ceil(w,32),mg_ceil(h,32),1);}
 else if(s==1){MG(4,f[0]);MG(5,f[1]);GROUP(mg_ceil(f[0],8),mg_ceil(f[1],8),1);}
 else if(s==2){for(unsigned j=0;j<2;j++){MG(j,a[j]);MG(j+2,a[j]);MG(j+4,b[j]);MG(j+6,(b[j]*2-a[j])/2);}GROUP(mg_ceil(b[0],8),mg_ceil(b[1],8),16);}
 else if(s>=3&&s<=11){
  unsigned iw=s==3?b[0]:d[0],ih=s==3?b[1]:d[1];
  MG(0,mg_align(iw,s<=4?8:16));MG(1,ih+1);MG(2,iw);MG(3,ih);MG(4,d[0]);MG(5,d[1]);GROUP(mg_ceil(d[0],8),mg_ceil(d[1],8),28);
 }else if(s==12){MG(0,mg_align(d[0],16));MG(1,d[1]+1);MG(2,mg_align(b[0],16));MG(3,b[1]);MG(4,b[0]);MG(5,b[1]);GROUP(mg_ceil(d[0],8),mg_ceil(d[1],8),1);}
 else if(s==13){MG(0,mg_align(b[0],16));MG(1,b[1]);MG(2,b[0]);MG(3,b[1]);MG(4,mg_align(a[0],8));MG(5,a[1]);MG(6,a[0]);MG(7,a[1]);MF(8,(float)b[0]/a[0]);MF(9,(float)b[1]/a[1]);MF(10,(float)a[0]/b[0]);MF(11,(float)a[1]/b[1]);MG(12,mg_align(b[0],16));GROUP(mg_ceil(a[0],8),mg_ceil(a[1],8),1);}
 else if(s==14){MG(0,mg_align(a[0],8));MG(1,a[1]);MG(2,a[0]);MG(3,a[1]);MG(4,mg_align(f[0],8));MG(5,f[1]+1);MG(6,f[0]);MG(7,f[1]);GROUP(mg_ceil(f[0],8),mg_ceil(f[1],8),1);}
 else if(s==15){MG(0,f[0]);MG(1,f[1]);MG(2,mg_align(f[0],8));MG(3,f[1]+1);GROUP(mg_ceil(f[0],8),mg_ceil(f[1],8),1);}
 else if(s>=16&&s<=25){
  unsigned divisor=s==16?1:s==17?2:4,ow=s==16?f[0]/2:a[0],oh=s==16?f[1]/2:a[1];
  MG(0,mg_align(f[0]/divisor,s<=18?8:16));MG(1,f[1]/divisor+1);MG(2,f[0]/divisor);MG(3,f[1]/divisor);MG(4,ow);MG(5,oh);GROUP(mg_ceil(ow,8),mg_ceil(oh,8),s==16?2:4);
 }else if(s==26){MG(0,mg_align(a[0],16));MG(1,a[1]+1);MG(2,mg_align(f[0]/2,16));MG(3,f[1]/2);MG(4,f[0]/2);MG(5,f[1]/2);GROUP(mg_ceil(a[0],8),mg_ceil(a[1],8),1);}
 else if(s==27){MG(0,mg_align(f[0]/2,16));MG(1,f[1]/2);MG(2,f[0]/2);MG(3,f[1]/2);MG(4,mg_align(f[0],8));MG(5,f[1]);MG(6,f[0]);MG(7,f[1]);MG(12,mg_align(f[0],8));GROUP(mg_ceil(f[0],8),mg_ceil(f[1],8),1);}
 else {unsigned phase=(s-28)%16;
  if(phase==0){/* Scatter runs on the original engine input grid. */}
  else if(phase==1){MG(0,f[0]);MG(1,f[1]);MG(4,mg_align(f[0],8));GROUP(mg_ceil(f[0],8),mg_ceil(f[1],8),1);}
  else if(phase==2){
   MG(2,w);MG(3,h);MG(6,w);MG(7,h);MG(8,w);MG(9,h);MF(10,1.f/w);MF(11,1.f/h);
   MG(28,mg_ceil(w,2));MG(29,mg_ceil(h,2));MG(30,multi?mg_align(mg_ceil(w,2),256)+2:mg_ceil(w,2));MG(31,multi?mg_align(mg_ceil(h,2),32)+2:mg_ceil(h,2));MG(36,f[0]);MG(37,f[1]);MG(38,w);MG(39,h);
   for(unsigned j=40;j<46;j+=2){MF(j,1.f/w);MF(j+1,1.f/h);}MG(46,mg_align(f[0],8));GROUP(mg_ceil(w,16),mg_ceil(h,32),1);
  }else if(phase<=14){
   unsigned k=phase-3,cw,ch;
   static const unsigned divs[12]={2,4,8,16,32,16,16,8,8,4,4,2};
   static const unsigned gx[12]={32,8,8,16,16,8,16,32,8,16,8,16},gy[12]={32,32,16,8,16,16,8,8,8,32,8,32};
   if(multi&&k<5){cw=mg_align(mg_ceil(w,2),256)/(1u<<k);ch=mg_align(mg_ceil(h,2),32)/(1u<<k);}
   else {cw=mg_ceil(w,divs[k]);ch=mg_ceil(h,divs[k]);}
   MG(0,cw);MG(1,ch);GROUP(mg_ceil(cw,gx[k]),mg_ceil(ch,gy[k]),1);
  }else{MG(10,mg_ceil(w,2));MG(11,mg_ceil(h,2));MG(12,w);MG(13,h);MG(17,mg_ceil(w,2));GROUP(mg_ceil(w,8),mg_ceil(h,8),1);}
 }
#undef MG
#undef MF
#undef GROUP
 return mask;
}
static unsigned mg_native_stage(unsigned s){
 if(s==0)return 0;if(s<=8)return s+1;if(s<=20)return s+3;if(s<=22)return s+5;
 if(s==23)return 28;if(s==24)return 30;return s+6;
}
