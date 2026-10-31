/* SPDX-License-Identifier: MIT
 * Game-facing subgroup selection. Each Vulkan instance/device owns its dispatch
 * chain; shader module handles are qualified by device. No driver replacement.
 * The wave profile applies to the BC-250 (1002:13fe); BC250_XEFG_ANY_GPU=1 applies it to any device, choice by choice
 * where the device supports that subgroup size for compute shaders.
 */
#define _GNU_SOURCE /* dladdr: the layer pins itself (pace_pin_self) */
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct instance_state {VkInstance instance;PFN_vkGetInstanceProcAddr next;struct instance_state*link;};
struct physical_state {VkPhysicalDevice physical;VkInstance instance;struct physical_state*link;};
struct device_state {VkDevice device;PFN_vkGetDeviceProcAddr next;int enabled;struct device_state*link;void*key;VkQueue pace_queue;
 VkPhysicalDevice physical;PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR surface_caps;
 PFN_vkQueuePresentKHR present;PFN_vkQueueSubmit submit;PFN_vkCreateFence create_fence;PFN_vkDestroyFence destroy_fence;PFN_vkCreateSemaphore create_sem;
 PFN_vkDestroySemaphore destroy_sem;PFN_vkWaitForFences wait_fences;PFN_vkResetFences reset_fences;PFN_vkAcquireNextImageKHR acquire;PFN_vkAcquireNextImage2KHR acquire2;
 PFN_vkCreateSwapchainKHR create_swapchain;PFN_vkDestroySwapchainKHR destroy_swapchain;PFN_vkQueueWaitIdle queue_wait_idle;PFN_vkDeviceWaitIdle device_wait_idle;
 int pace_shared;PFN_vkQueueSubmit2 submit2,submit2_khr;PFN_vkQueueBindSparse bind_sparse;
 PFN_vkQueueBeginDebugUtilsLabelEXT label_begin;PFN_vkQueueEndDebugUtilsLabelEXT label_end;PFN_vkQueueInsertDebugUtilsLabelEXT label_insert;
 unsigned wave_min,wave_max;}; /* subgroup sizes compute shaders may require (wave_range) */
struct module_state {VkDevice device;VkShaderModule module;char name[17];struct module_state*link;};
static struct instance_state*instances;
static struct physical_state*physicals;
static struct device_state*devices;
static struct module_state*modules;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t config_once=PTHREAD_ONCE_INIT;
static struct {char name[17];unsigned wave;} choices[512];
static unsigned choice_count;
static PFN_vkVoidFunction VKAPI_CALL gipa(VkInstance,const char*);
static PFN_vkVoidFunction VKAPI_CALL gdpa(VkDevice,const char*);

/* One table line: 16 lower-case hex digits, blanks, the wave, optional trailing blanks. Read by hand: with _GNU_SOURCE,
 * glibc 2.38 and later turn sscanf into __isoc23_sscanf, which would make the layer need glibc 2.38 instead of 2.34. */
static int wave_line(const char*s,char hash[17],unsigned*wave){
 size_t n=0;while(n<16&&((s[n]>='0'&&s[n]<='9')||(s[n]>='a'&&s[n]<='f')))n++;
 if(n!=16||(s[n]!=' '&&s[n]!='\t'))return 0;
 memcpy(hash,s,16);hash[16]=0;s+=16;while(*s==' '||*s=='\t')s++;
 unsigned v=0,digits=0;while(*s>='0'&&*s<='9'&&digits<3){v=v*10+(unsigned)(*s++-'0');digits++;}
 while(*s==' '||*s=='\t'||*s=='\r'||*s=='\n')s++;
 if(!digits||*s)return 0;*wave=v;return 1;
}
static void configuration(void){
 const char*path=getenv("XEFG_WAVE_CONFIG");if(!path)return;
 FILE*f=fopen(path,"r");if(!f)return;
 char line[128];unsigned count=0;int ok=1;
 while(fgets(line,sizeof(line),f)){
  if(strspn(line," \t\r\n")==strlen(line))continue;
  char hash[17];unsigned wave;
  if(count==512||!wave_line(line,hash,&wave)||(wave!=32&&wave!=64)){ok=0;break;}
  for(unsigned i=0;i<count;i++)if(!strcmp(choices[i].name,hash))ok=0;
  if(!ok)break;
  strcpy(choices[count].name,hash);choices[count++].wave=wave;
 }
 if(ferror(f))ok=0;fclose(f);choice_count=ok?count:0;
}
static PFN_vkGetInstanceProcAddr instance_next(VkInstance instance){
 PFN_vkGetInstanceProcAddr next=NULL;pthread_mutex_lock(&mutex);
 for(struct instance_state*p=instances;p;p=p->link)if(p->instance==instance){next=p->next;break;}
 pthread_mutex_unlock(&mutex);return next;
}
static PFN_vkGetDeviceProcAddr device_next(VkDevice device,int*enabled){
 PFN_vkGetDeviceProcAddr next=NULL;if(enabled)*enabled=0;pthread_mutex_lock(&mutex);
 for(struct device_state*p=devices;p;p=p->link)if(p->device==device){next=p->next;if(enabled)*enabled=p->enabled;break;}
 pthread_mutex_unlock(&mutex);return next;
}
/* Subgroup sizes the device can require of compute shaders ({0,0}: none). */
static void wave_range(VkInstance instance,PFN_vkGetInstanceProcAddr next_i,VkPhysicalDevice physical,unsigned*low,unsigned*high){
 *low=*high=0;PFN_vkGetPhysicalDeviceProperties2 get=(void*)next_i(instance,"vkGetPhysicalDeviceProperties2");
 if(!get)get=(void*)next_i(instance,"vkGetPhysicalDeviceProperties2KHR");if(!get)return;
 VkPhysicalDeviceSubgroupSizeControlProperties size={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_PROPERTIES};
 VkPhysicalDeviceProperties2 properties={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,.pNext=&size};get(physical,&properties);
 if(size.requiredSubgroupSizeStages&VK_SHADER_STAGE_COMPUTE_BIT){*low=size.minSubgroupSize;*high=size.maxSubgroupSize;}
}
static void remember_physical(VkInstance instance,VkPhysicalDevice physical){
 pthread_mutex_lock(&mutex);
 for(struct physical_state*p=physicals;p;p=p->link)if(p->physical==physical){pthread_mutex_unlock(&mutex);return;}
 struct physical_state*p=malloc(sizeof(*p));if(p){*p=(struct physical_state){physical,instance,physicals};physicals=p;}
 pthread_mutex_unlock(&mutex);
}
#include "present_pacer.h"
static VkResult VKAPI_CALL create_instance(const VkInstanceCreateInfo*info,const VkAllocationCallbacks*a,VkInstance*out){
 VkLayerInstanceCreateInfo*link=(void*)info->pNext;
 while(link&&(link->sType!=VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO||link->function!=VK_LAYER_LINK_INFO))link=(void*)link->pNext;
 if(!link)return VK_ERROR_INITIALIZATION_FAILED;
 PFN_vkGetInstanceProcAddr next=link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
 PFN_vkCreateInstance create=(void*)next(VK_NULL_HANDLE,"vkCreateInstance");
 struct instance_state*state=malloc(sizeof(*state));if(!state)return VK_ERROR_OUT_OF_HOST_MEMORY;
 link->u.pLayerInfo=link->u.pLayerInfo->pNext;VkResult result=create(info,a,out);
 if(result){free(state);return result;}
 *state=(struct instance_state){*out,next,NULL};pthread_mutex_lock(&mutex);state->link=instances;instances=state;pthread_mutex_unlock(&mutex);return result;
}
static void VKAPI_CALL destroy_instance(VkInstance instance,const VkAllocationCallbacks*a){
 PFN_vkGetInstanceProcAddr next=instance_next(instance);if(!next)return;
 ((PFN_vkDestroyInstance)next(instance,"vkDestroyInstance"))(instance,a);
 pthread_mutex_lock(&mutex);
 struct physical_state**physical=&physicals;
 while(*physical){struct physical_state*p=*physical;if(p->instance==instance){*physical=p->link;free(p);}else physical=&p->link;}
 struct instance_state**link=&instances;while(*link){struct instance_state*p=*link;if(p->instance==instance){*link=p->link;free(p);break;}link=&p->link;}
 pthread_mutex_unlock(&mutex);
}
static VkResult VKAPI_CALL enumerate_physical(VkInstance instance,uint32_t*count,VkPhysicalDevice*out){
 PFN_vkGetInstanceProcAddr next=instance_next(instance);if(!next)return VK_ERROR_INITIALIZATION_FAILED;
 VkResult result=((PFN_vkEnumeratePhysicalDevices)next(instance,"vkEnumeratePhysicalDevices"))(instance,count,out);
 if(out&&(result==VK_SUCCESS||result==VK_INCOMPLETE))for(uint32_t i=0;i<*count;i++)remember_physical(instance,out[i]);return result;
}
static VkResult enumerate_groups(VkInstance instance,uint32_t*count,VkPhysicalDeviceGroupProperties*out,const char*name){
 PFN_vkGetInstanceProcAddr next=instance_next(instance);if(!next)return VK_ERROR_INITIALIZATION_FAILED;
 PFN_vkEnumeratePhysicalDeviceGroups fn=(void*)next(instance,name);if(!fn)return VK_ERROR_EXTENSION_NOT_PRESENT;
 VkResult result=fn(instance,count,out);
 if(out&&(result==VK_SUCCESS||result==VK_INCOMPLETE))for(uint32_t i=0;i<*count;i++)for(uint32_t j=0;j<out[i].physicalDeviceCount;j++)remember_physical(instance,out[i].physicalDevices[j]);return result;
}
static VkResult VKAPI_CALL groups(VkInstance i,uint32_t*n,VkPhysicalDeviceGroupProperties*p){return enumerate_groups(i,n,p,"vkEnumeratePhysicalDeviceGroups");}
static VkResult VKAPI_CALL groups_khr(VkInstance i,uint32_t*n,VkPhysicalDeviceGroupProperties*p){return enumerate_groups(i,n,p,"vkEnumeratePhysicalDeviceGroupsKHR");}
static VkResult VKAPI_CALL create_device(VkPhysicalDevice physical,const VkDeviceCreateInfo*info,const VkAllocationCallbacks*a,VkDevice*out){
 VkLayerDeviceCreateInfo*link=(void*)info->pNext;
 while(link&&(link->sType!=VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO||link->function!=VK_LAYER_LINK_INFO))link=(void*)link->pNext;
 if(!link)return VK_ERROR_INITIALIZATION_FAILED;
 VkInstance instance=VK_NULL_HANDLE;pthread_mutex_lock(&mutex);
 for(struct physical_state*p=physicals;p;p=p->link)if(p->physical==physical){instance=p->instance;break;}
 pthread_mutex_unlock(&mutex);if(!instance)return VK_ERROR_INITIALIZATION_FAILED;
 PFN_vkGetInstanceProcAddr next_i=link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
 PFN_vkGetDeviceProcAddr next_d=link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
 PFN_vkCreateDevice create=(void*)next_i(instance,"vkCreateDevice");
 struct device_state*state=malloc(sizeof(*state));if(!state)return VK_ERROR_OUT_OF_HOST_MEMORY;
 PFN_vkSetDeviceLoaderData set_loader_data=NULL;
 for(const VkLayerDeviceCreateInfo*c=info->pNext;c;c=(const void*)c->pNext)if(c->sType==VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO&&c->function==VK_LOADER_DATA_CALLBACK)set_loader_data=c->u.pfnSetDeviceLoaderData;
 VkDeviceCreateInfo paced;VkDeviceQueueCreateInfo queues[17];float priorities[64];uint32_t pace_index=0;
 int pace_family=set_loader_data?pace_queue_request(instance,physical,next_i,info,&paced,queues,priorities,&pace_index):-1;
 link->u.pLayerInfo=link->u.pLayerInfo->pNext;VkResult result=create(physical,pace_family>=0?&paced:info,a,out);
 if(result){free(state);return result;}
 VkPhysicalDeviceProperties properties;((PFN_vkGetPhysicalDeviceProperties)next_i(instance,"vkGetPhysicalDeviceProperties"))(physical,&properties);
 int enabled=0;
 for(const VkBaseInStructure*p=info->pNext;p;p=p->pNext){
  if(p->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES)enabled=((const VkPhysicalDeviceVulkan13Features*)p)->subgroupSizeControl;
  if(p->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_FEATURES)enabled=((const VkPhysicalDeviceSubgroupSizeControlFeatures*)p)->subgroupSizeControl;
 }
 int any_gpu=pace_switch("BC250_XEFG_ANY_GPU")==1,bc250=properties.vendorID==0x1002&&properties.deviceID==0x13fe;
 enabled&=bc250||any_gpu;
 pthread_once(&config_once,configuration);enabled&=choice_count!=0;
 unsigned wave_min=0,wave_max=0;if(enabled)wave_range(instance,next_i,physical,&wave_min,&wave_max);enabled&=wave_max!=0;
 *state=(struct device_state){.device=*out,.next=next_d,.enabled=enabled,.wave_min=wave_min,.wave_max=wave_max,.key=*(void**)*out};
 state->physical=physical;state->surface_caps=(PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR)next_i(instance,"vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
#define NEXT(field,type,name) state->field=(type)next_d(*out,name)
 NEXT(present,PFN_vkQueuePresentKHR,"vkQueuePresentKHR");NEXT(submit,PFN_vkQueueSubmit,"vkQueueSubmit");NEXT(create_fence,PFN_vkCreateFence,"vkCreateFence");
 NEXT(destroy_fence,PFN_vkDestroyFence,"vkDestroyFence");NEXT(create_sem,PFN_vkCreateSemaphore,"vkCreateSemaphore");NEXT(destroy_sem,PFN_vkDestroySemaphore,"vkDestroySemaphore");
 NEXT(wait_fences,PFN_vkWaitForFences,"vkWaitForFences");NEXT(reset_fences,PFN_vkResetFences,"vkResetFences");NEXT(acquire,PFN_vkAcquireNextImageKHR,"vkAcquireNextImageKHR");
 NEXT(acquire2,PFN_vkAcquireNextImage2KHR,"vkAcquireNextImage2KHR");NEXT(create_swapchain,PFN_vkCreateSwapchainKHR,"vkCreateSwapchainKHR");
 NEXT(destroy_swapchain,PFN_vkDestroySwapchainKHR,"vkDestroySwapchainKHR");NEXT(queue_wait_idle,PFN_vkQueueWaitIdle,"vkQueueWaitIdle");NEXT(device_wait_idle,PFN_vkDeviceWaitIdle,"vkDeviceWaitIdle");
 NEXT(submit2,PFN_vkQueueSubmit2,"vkQueueSubmit2");NEXT(submit2_khr,PFN_vkQueueSubmit2,"vkQueueSubmit2KHR");NEXT(bind_sparse,PFN_vkQueueBindSparse,"vkQueueBindSparse");
 NEXT(label_begin,PFN_vkQueueBeginDebugUtilsLabelEXT,"vkQueueBeginDebugUtilsLabelEXT");NEXT(label_end,PFN_vkQueueEndDebugUtilsLabelEXT,"vkQueueEndDebugUtilsLabelEXT");
 NEXT(label_insert,PFN_vkQueueInsertDebugUtilsLabelEXT,"vkQueueInsertDebugUtilsLabelEXT");
#undef NEXT
 if(pace_family>=0){PFN_vkGetDeviceQueue get=(PFN_vkGetDeviceQueue)next_d(*out,"vkGetDeviceQueue");VkQueue q=VK_NULL_HANDLE;if(get)get(*out,(uint32_t)pace_family,pace_index,&q);
  if(q&&set_loader_data(*out,q)==VK_SUCCESS&&state->present&&state->submit&&state->create_fence&&state->destroy_fence&&state->create_sem&&state->destroy_sem&&state->wait_fences&&state->reset_fences)state->pace_queue=q;}
 /* No dedicated compute queue to reserve: present from the application's queue (present_pacer.h, shared_queue_lock). */
 if(!state->pace_queue&&pace_wanted()&&state->present&&state->submit&&state->create_fence&&state->destroy_fence&&state->create_sem&&state->destroy_sem&&state->wait_fences&&state->reset_fences
    &&state->queue_wait_idle&&state->device_wait_idle)state->pace_shared=1;
 pthread_mutex_lock(&mutex);state->link=devices;devices=state;pthread_mutex_unlock(&mutex);
 if(state->pace_shared)fprintf(stderr,"BC250_PACE on (application queue%s)\n",pace_app_queue()?", BC250_XEFG_PACE_QUEUE=app":": no dedicated compute queue");
 else fprintf(stderr,"BC250_PACE %s (compute family %d queue %u)\n",state->pace_queue?"on":"off",pace_family,pace_index);
 fprintf(stderr,"XEFG_GAME_LAYER device=%04x:%04x enabled=%d choices=%u%s\n",properties.vendorID,properties.deviceID,enabled,choice_count,
         !bc250&&any_gpu?" (BC250_XEFG_ANY_GPU=1: untested outside the BC-250)":"");return result;
}
static void VKAPI_CALL destroy_device(VkDevice device,const VkAllocationCallbacks*a){
 PFN_vkGetDeviceProcAddr next=device_next(device,NULL);if(!next)return;
 struct device_state*d=NULL;pthread_mutex_lock(&mutex);for(struct device_state*p=devices;p;p=p->link)if(p->device==device)d=p;pthread_mutex_unlock(&mutex);if(d)pace_forget_device(d);
 ((PFN_vkDestroyDevice)next(device,"vkDestroyDevice"))(device,a);
 pthread_mutex_lock(&mutex);struct module_state**module=&modules;
 while(*module){struct module_state*p=*module;if(p->device==device){*module=p->link;free(p);}else module=&p->link;}
 struct device_state**link=&devices;while(*link){struct device_state*p=*link;if(p->device==device){*link=p->link;free(p);break;}link=&p->link;}
 pthread_mutex_unlock(&mutex);
}
static void module_name(const VkShaderModuleCreateInfo*info,char name[17]){
 name[0]=0;size_t words=info->codeSize/4;
 for(size_t i=5;i<words;){uint32_t count=info->pCode[i]>>16,op=info->pCode[i]&65535;if(!count||i+count>words)break;
  if(op==7&&count>=8){const char*s=(const char*)&info->pCode[i+2];size_t bytes=(count-2)*4;
   if(strnlen(s,bytes)==21&&!strcmp(s+16,".dxil")){memcpy(name,s,16);name[16]=0;return;}}
  i+=count;
 }
}
static VkResult VKAPI_CALL create_module(VkDevice device,const VkShaderModuleCreateInfo*info,const VkAllocationCallbacks*a,VkShaderModule*out){
 int enabled;PFN_vkGetDeviceProcAddr next=device_next(device,&enabled);if(!next)return VK_ERROR_INITIALIZATION_FAILED;
 char name[17];module_name(info,name);struct module_state*state=enabled&&name[0]?malloc(sizeof(*state)):NULL;
 if(enabled&&name[0]&&!state)return VK_ERROR_OUT_OF_HOST_MEMORY;
 VkResult result=((PFN_vkCreateShaderModule)next(device,"vkCreateShaderModule"))(device,info,a,out);
 if(result){free(state);return result;}
 if(state){*state=(struct module_state){.device=device,.module=*out};strcpy(state->name,name);pthread_mutex_lock(&mutex);state->link=modules;modules=state;pthread_mutex_unlock(&mutex);}return result;
}
static void VKAPI_CALL destroy_module(VkDevice device,VkShaderModule module,const VkAllocationCallbacks*a){
 PFN_vkGetDeviceProcAddr next=device_next(device,NULL);if(!next)return;
 pthread_mutex_lock(&mutex);struct module_state**link=&modules;
 while(*link){struct module_state*p=*link;if(p->device==device&&p->module==module){*link=p->link;free(p);break;}link=&p->link;}
 pthread_mutex_unlock(&mutex);((PFN_vkDestroyShaderModule)next(device,"vkDestroyShaderModule"))(device,module,a);
}
static VkResult VKAPI_CALL create_pipelines(VkDevice device,VkPipelineCache cache,uint32_t count,const VkComputePipelineCreateInfo*infos,const VkAllocationCallbacks*a,VkPipeline*out){
 int enabled;PFN_vkGetDeviceProcAddr next=device_next(device,&enabled);if(!next)return VK_ERROR_INITIALIZATION_FAILED;
 unsigned wave_min=0,wave_max=0;
 if(enabled){pthread_mutex_lock(&mutex);for(struct device_state*p=devices;p;p=p->link)if(p->device==device){wave_min=p->wave_min;wave_max=p->wave_max;break;}pthread_mutex_unlock(&mutex);}
 PFN_vkCreateComputePipelines fn=(void*)next(device,"vkCreateComputePipelines");if(!enabled||!count)return fn(device,cache,count,infos,a,out);
 VkComputePipelineCreateInfo*copy=malloc(count*sizeof(*copy));VkPipelineShaderStageRequiredSubgroupSizeCreateInfo*requirements=calloc(count,sizeof(*requirements));
 if(!copy||!requirements){free(copy);free(requirements);return VK_ERROR_OUT_OF_HOST_MEMORY;}memcpy(copy,infos,count*sizeof(*copy));
 for(uint32_t i=0;i<count;i++){
  char name[17]={0};unsigned wave=0;int explicit_size=0;
  pthread_mutex_lock(&mutex);for(struct module_state*p=modules;p;p=p->link)if(p->device==device&&p->module==infos[i].stage.module){strcpy(name,p->name);break;}pthread_mutex_unlock(&mutex);
  for(const VkBaseInStructure*p=infos[i].stage.pNext;p;p=p->pNext){
   if(p->sType==VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO)explicit_size=1;
   if(p->sType==VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO)module_name((const void*)p,name);
  }
  if(explicit_size)continue;
  for(unsigned j=0;j<choice_count;j++)if(!strcmp(choices[j].name,name)){wave=choices[j].wave;break;}
  if(wave&&(wave<wave_min||wave>wave_max)){fprintf(stderr,"XEFG_WAVE %s %u skipped: device supports %u-%u\n",name,wave,wave_min,wave_max);wave=0;}
  if(wave){
   requirements[i]=(VkPipelineShaderStageRequiredSubgroupSizeCreateInfo){.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO,.pNext=infos[i].stage.pNext,.requiredSubgroupSize=wave};
   copy[i].stage.pNext=&requirements[i];copy[i].stage.flags&=~VK_PIPELINE_SHADER_STAGE_CREATE_ALLOW_VARYING_SUBGROUP_SIZE_BIT;
   fprintf(stderr,"XEFG_WAVE %s %u\n",name,wave);
  }
 }
 VkResult result=fn(device,cache,count,copy,a,out);free(copy);free(requirements);return result;
}
static PFN_vkVoidFunction intercept_device(const char*name){
 if(!strcmp(name,"vkGetDeviceProcAddr"))return (void*)gdpa;
 if(!strcmp(name,"vkDestroyDevice"))return (void*)destroy_device;
 if(!strcmp(name,"vkCreateShaderModule"))return (void*)create_module;
 if(!strcmp(name,"vkDestroyShaderModule"))return (void*)destroy_module;
 if(!strcmp(name,"vkCreateComputePipelines"))return (void*)create_pipelines;
 if(!strcmp(name,"vkQueuePresentKHR"))return (void*)queue_present;
 if(!strcmp(name,"vkAcquireNextImageKHR"))return (void*)acquire_image;
 if(!strcmp(name,"vkAcquireNextImage2KHR"))return (void*)acquire_image2;
 if(!strcmp(name,"vkCreateSwapchainKHR"))return (void*)create_swapchain;
 if(!strcmp(name,"vkDestroySwapchainKHR"))return (void*)destroy_swapchain;
 if(!strcmp(name,"vkQueueWaitIdle"))return (void*)queue_wait_idle;
 if(!strcmp(name,"vkDeviceWaitIdle"))return (void*)device_wait_idle;
 return NULL;
}
static PFN_vkVoidFunction shared_queue_hook(VkDevice device,const char*name,PFN_vkVoidFunction next){
 if(!next)return NULL;
 int shared=0;pthread_mutex_lock(&mutex);for(struct device_state*p=devices;p;p=p->link)if(p->device==device){shared=p->pace_shared;break;}pthread_mutex_unlock(&mutex);
 if(!shared)return next;
 if(!strcmp(name,"vkQueueSubmit"))return (void*)shared_submit;
 if(!strcmp(name,"vkQueueSubmit2"))return (void*)shared_submit2;
 if(!strcmp(name,"vkQueueSubmit2KHR"))return (void*)shared_submit2_khr;
 if(!strcmp(name,"vkQueueBindSparse"))return (void*)shared_bind_sparse;
 if(!strcmp(name,"vkQueueBeginDebugUtilsLabelEXT"))return (void*)shared_label_begin;
 if(!strcmp(name,"vkQueueEndDebugUtilsLabelEXT"))return (void*)shared_label_end;
 if(!strcmp(name,"vkQueueInsertDebugUtilsLabelEXT"))return (void*)shared_label_insert;
 return next;
}
static PFN_vkVoidFunction VKAPI_CALL gdpa(VkDevice device,const char*name){
 PFN_vkVoidFunction hook=intercept_device(name);if(hook)return hook;
 PFN_vkGetDeviceProcAddr next=device_next(device,NULL);PFN_vkVoidFunction fn=next?next(device,name):NULL;
 if(!strncmp(name,"vkQueue",7))return shared_queue_hook(device,name,fn);
 return fn;
}
static PFN_vkVoidFunction VKAPI_CALL gipa(VkInstance instance,const char*name){
 if(!strcmp(name,"vkGetInstanceProcAddr"))return (void*)gipa;
 if(!strcmp(name,"vkCreateInstance"))return (void*)create_instance;
 if(!strcmp(name,"vkDestroyInstance"))return (void*)destroy_instance;
 if(!strcmp(name,"vkEnumeratePhysicalDevices"))return (void*)enumerate_physical;
 if(!strcmp(name,"vkEnumeratePhysicalDeviceGroups"))return (void*)groups;
 if(!strcmp(name,"vkEnumeratePhysicalDeviceGroupsKHR"))return (void*)groups_khr;
 if(!strcmp(name,"vkCreateDevice"))return (void*)create_device;
 if(!strcmp(name,"vkGetPhysicalDeviceQueueFamilyProperties"))return (void*)queue_families;
 if(!strcmp(name,"vkGetPhysicalDeviceQueueFamilyProperties2"))return (void*)queue_families2_core;
 if(!strcmp(name,"vkGetPhysicalDeviceQueueFamilyProperties2KHR"))return (void*)queue_families2_khr;
 if(!strcmp(name,"vkGetPhysicalDeviceFeatures2"))return (void*)features2_core;
 if(!strcmp(name,"vkGetPhysicalDeviceFeatures2KHR"))return (void*)features2_khr;
 PFN_vkVoidFunction hook=intercept_device(name);if(hook)return hook;
 PFN_vkGetInstanceProcAddr next=instance_next(instance);return next?next(instance,name):NULL;
}
/* The pacer's threads (watcher, releaser, X nudge) run for the life of the process, but the Vulkan loader unloads a
 * layer library when the last instance is destroyed: a thread returning into unmapped code would crash the game. The
 * library therefore keeps itself loaded. */
static void pace_pin_self(void){
 static int pinned;Dl_info self;if(pinned||!dladdr((void*)pace_pin_self,&self)||!self.dli_fname)return;
 pinned=dlopen(self.dli_fname,RTLD_NOW|RTLD_NOLOAD|RTLD_NODELETE)!=NULL;
}
/* No vk_layerGetPhysicalDeviceProcAddr: the layer intercepts no physical-device function the loader does not know, and
 * gipa is not one (the loader would take any name it answers for a physical-device entry point). */
VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface*p){
 if(p->loaderLayerInterfaceVersion<2)return VK_ERROR_INITIALIZATION_FAILED;
 pace_pin_self();
 p->loaderLayerInterfaceVersion=2;p->pfnGetInstanceProcAddr=gipa;p->pfnGetDeviceProcAddr=gdpa;p->pfnGetPhysicalDeviceProcAddr=NULL;return VK_SUCCESS;
}
