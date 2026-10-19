/* SPDX-License-Identifier: MIT */
#include "wave_layer.c"
#include <assert.h>
#include <unistd.h>
static unsigned expected_wave,calls_a,calls_b;
static VkResult VKAPI_CALL fake_module(VkDevice d,const VkShaderModuleCreateInfo*i,const VkAllocationCallbacks*a,VkShaderModule*out){(void)d;(void)i;(void)a;*out=(VkShaderModule)55;return VK_SUCCESS;}
static void VKAPI_CALL fake_destroy_module(VkDevice d,VkShaderModule m,const VkAllocationCallbacks*a){(void)d;(void)m;(void)a;}
static void VKAPI_CALL fake_destroy_device(VkDevice d,const VkAllocationCallbacks*a){(void)d;(void)a;}
static VkResult check_pipeline(const VkComputePipelineCreateInfo*info){
 const VkPipelineShaderStageRequiredSubgroupSizeCreateInfo*r=info->stage.pNext;
 if(expected_wave){assert(r&&r->sType==VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO);assert(r->requiredSubgroupSize==expected_wave);assert(!(info->stage.flags&VK_PIPELINE_SHADER_STAGE_CREATE_ALLOW_VARYING_SUBGROUP_SIZE_BIT));}
 else assert(!r);
 return VK_SUCCESS;
}
static VkResult VKAPI_CALL pipeline_a(VkDevice d,VkPipelineCache c,uint32_t n,const VkComputePipelineCreateInfo*i,const VkAllocationCallbacks*a,VkPipeline*out){(void)d;(void)c;(void)a;(void)out;assert(n==1);calls_a++;return check_pipeline(i);}
static VkResult VKAPI_CALL pipeline_b(VkDevice d,VkPipelineCache c,uint32_t n,const VkComputePipelineCreateInfo*i,const VkAllocationCallbacks*a,VkPipeline*out){(void)d;(void)c;(void)a;(void)out;assert(n==1);calls_b++;return check_pipeline(i);}
static PFN_vkVoidFunction common(const char*n){if(!strcmp(n,"vkCreateShaderModule"))return(void*)fake_module;if(!strcmp(n,"vkDestroyShaderModule"))return(void*)fake_destroy_module;if(!strcmp(n,"vkDestroyDevice"))return(void*)fake_destroy_device;return NULL;}
/* A device that presents from the application's queue: its queue calls go through the layer's lock. */
static int in_submit,overlap,submits;
static VkResult VKAPI_CALL fake_submit(VkQueue q,uint32_t n,const VkSubmitInfo*s,VkFence f){
 (void)q;(void)n;(void)s;(void)f;if(__atomic_fetch_add(&in_submit,1,__ATOMIC_SEQ_CST))overlap=1;usleep(20);__atomic_fetch_sub(&in_submit,1,__ATOMIC_SEQ_CST);submits++;return VK_SUCCESS;}
static PFN_vkVoidFunction VKAPI_CALL next_shared(VkDevice d,const char*n){(void)d;return !strcmp(n,"vkQueueSubmit")?(void*)fake_submit:common(n);}
static void*submitter(void*q){for(int i=0;i<300;i++)assert(shared_submit((VkQueue)q,0,NULL,VK_NULL_HANDLE)==VK_SUCCESS);return NULL;}
static PFN_vkVoidFunction VKAPI_CALL next_a(VkDevice d,const char*n){(void)d;return !strcmp(n,"vkCreateComputePipelines")?(void*)pipeline_a:common(n);}
static PFN_vkVoidFunction VKAPI_CALL next_b(VkDevice d,const char*n){(void)d;return !strcmp(n,"vkCreateComputePipelines")?(void*)pipeline_b:common(n);}
static VkShaderStageFlags fake_stages;
static void VKAPI_CALL fake_properties2(VkPhysicalDevice p,VkPhysicalDeviceProperties2*out){
 (void)p;VkPhysicalDeviceSubgroupSizeControlProperties*s=out->pNext;assert(s&&s->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_PROPERTIES);
 s->minSubgroupSize=32;s->maxSubgroupSize=64;s->requiredSubgroupSizeStages=fake_stages;}
static PFN_vkVoidFunction VKAPI_CALL fake_gipa(VkInstance i,const char*n){(void)i;return !strcmp(n,"vkGetPhysicalDeviceProperties2")?(void*)fake_properties2:NULL;}
static PFN_vkVoidFunction VKAPI_CALL no_gipa(VkInstance i,const char*n){(void)i;(void)n;return NULL;}
static VkShaderModule named(VkDevice device,const char*hash){
 uint32_t words[13]={0x07230203,0x10000,0,2,0,(8u<<16)|7,1};char name[22];snprintf(name,sizeof(name),"%s.dxil",hash);memcpy(&words[7],name,22);
 VkShaderModuleCreateInfo info={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.pCode=words,.codeSize=sizeof(words)};VkShaderModule module;
 assert(create_module(device,&info,NULL,&module)==VK_SUCCESS);return module;
}
int main(void){
 struct device_state*a=calloc(1,sizeof(*a)),*b=calloc(1,sizeof(*b)),*disabled=calloc(1,sizeof(*disabled));
 *a=(struct device_state){.device=(VkDevice)1,.next=next_a,.enabled=1,.link=b,.wave_min=32,.wave_max=64};
 *b=(struct device_state){.device=(VkDevice)2,.next=next_b,.enabled=1,.link=disabled,.wave_min=32,.wave_max=64};
 *disabled=(struct device_state){.device=(VkDevice)3,.next=next_a,.enabled=0};devices=a;
 strcpy(choices[0].name,"aaaaaaaaaaaaaaaa");choices[0].wave=32;strcpy(choices[1].name,"bbbbbbbbbbbbbbbb");choices[1].wave=64;choice_count=2;
 VkShaderModule one=named((VkDevice)1,choices[0].name),two=named((VkDevice)2,choices[1].name);assert(one==two);
 VkComputePipelineCreateInfo info={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.flags=VK_PIPELINE_SHADER_STAGE_CREATE_ALLOW_VARYING_SUBGROUP_SIZE_BIT,.module=one}};VkPipeline out;
 expected_wave=32;assert(create_pipelines((VkDevice)1,0,1,&info,NULL,&out)==0);assert(calls_a==1&&calls_b==0);
 expected_wave=64;assert(create_pipelines((VkDevice)2,0,1,&info,NULL,&out)==0);assert(calls_b==1);
 assert(!info.stage.pNext); // Input structure is never mutated.
 expected_wave=0;assert(create_pipelines((VkDevice)3,0,1,&info,NULL,&out)==0);
 VkPipelineShaderStageRequiredSubgroupSizeCreateInfo explicit_size={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO,.requiredSubgroupSize=64};info.stage.pNext=&explicit_size;info.stage.flags=0;
 expected_wave=64;assert(create_pipelines((VkDevice)1,0,1,&info,NULL,&out)==0);assert(explicit_size.requiredSubgroupSize==64);
 info.stage.pNext=NULL;destroy_module((VkDevice)1,one,NULL);
 expected_wave=64;assert(create_pipelines((VkDevice)2,0,1,&info,NULL,&out)==0); // Other device's same-valued handle survives.
 expected_wave=0;assert(create_pipelines((VkDevice)1,0,1,&info,NULL,&out)==0);
 /* A device limited to 32-wide subgroups (another vendor, BC250_XEFG_ANY_GPU=1): its 32 choices apply, 64 ones are skipped. */
 struct device_state*narrow=calloc(1,sizeof(*narrow));*narrow=(struct device_state){.device=(VkDevice)5,.next=next_a,.enabled=1,.link=devices,.wave_min=32,.wave_max=32};devices=narrow;
 VkShaderModule five_a=named((VkDevice)5,choices[0].name);info.stage.module=five_a;info.stage.flags=VK_PIPELINE_SHADER_STAGE_CREATE_ALLOW_VARYING_SUBGROUP_SIZE_BIT;
 expected_wave=32;assert(create_pipelines((VkDevice)5,0,1,&info,NULL,&out)==0);destroy_module((VkDevice)5,five_a,NULL);
 VkShaderModule five_b=named((VkDevice)5,choices[1].name);info.stage.module=five_b;
 expected_wave=0;assert(create_pipelines((VkDevice)5,0,1,&info,NULL,&out)==0);destroy_module((VkDevice)5,five_b,NULL);destroy_device((VkDevice)5,NULL);
 /* wave_range: compute-stage sizes from VkPhysicalDeviceSubgroupSizeControlProperties, none without compute or the query. */
 unsigned low,high;fake_stages=VK_SHADER_STAGE_COMPUTE_BIT;wave_range((VkInstance)9,fake_gipa,(VkPhysicalDevice)9,&low,&high);assert(low==32&&high==64);
 fake_stages=VK_SHADER_STAGE_FRAGMENT_BIT;wave_range((VkInstance)9,fake_gipa,(VkPhysicalDevice)9,&low,&high);assert(!low&&!high);
 wave_range((VkInstance)9,no_gipa,(VkPhysicalDevice)9,&low,&high);assert(!low&&!high);
 static void*key=(void*)0x77;void*dispatch=key;VkQueue queue=(VkQueue)&dispatch;
 struct device_state*shared=calloc(1,sizeof(*shared));*shared=(struct device_state){.device=(VkDevice)4,.next=next_shared,.key=key,.pace_shared=1,.submit=fake_submit,.link=devices};devices=shared;
 assert(gdpa((VkDevice)4,"vkQueueSubmit")==(PFN_vkVoidFunction)shared_submit);
 assert(!gdpa((VkDevice)4,"vkQueueSubmit2")); // unsupported below stays unsupported
 assert(gdpa((VkDevice)1,"vkQueueSubmit")==common("vkQueueSubmit")); // devices with their own present queue: no wrapper
 pthread_t t1,t2;pthread_create(&t1,NULL,submitter,queue);pthread_create(&t2,NULL,submitter,queue);pthread_join(t1,NULL);pthread_join(t2,NULL);
 assert(!overlap&&submits==600);destroy_device((VkDevice)4,NULL);
 destroy_device((VkDevice)1,NULL);destroy_device((VkDevice)2,NULL);destroy_device((VkDevice)3,NULL);
 assert(!devices&&!modules);puts("PASS per-device dispatch, same-valued handles, explicit contracts, disable and destruction, subgroup-size range, shared-queue lock");return 0;
}
