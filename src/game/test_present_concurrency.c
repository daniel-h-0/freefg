/* SPDX-License-Identifier: MIT
 * queue_present through a fake driver: two threads presenting on two queues of one paced device (every present must
 * reach the driver and every ring semaphore must be waited once), deferred present errors kept per swapchain, and the
 * BC250_XEFG_PACE switch values. */
#include "wave_layer.c"
#include <assert.h>
#include <unistd.h>
static int presents,submits,signals[PACE_SLOTS];static VkResult present_result=VK_SUCCESS;
static VkResult VKAPI_CALL f_create_fence(VkDevice d,const VkFenceCreateInfo*i,const VkAllocationCallbacks*a,VkFence*o){static uintptr_t n=0x100;(void)d;(void)i;(void)a;*o=(VkFence)__atomic_add_fetch(&n,1,__ATOMIC_SEQ_CST);return VK_SUCCESS;}
static VkResult VKAPI_CALL f_create_sem(VkDevice d,const VkSemaphoreCreateInfo*i,const VkAllocationCallbacks*a,VkSemaphore*o){static uintptr_t n=0;(void)d;(void)i;(void)a;*o=(VkSemaphore)__atomic_add_fetch(&n,1,__ATOMIC_SEQ_CST);return VK_SUCCESS;}
static void VKAPI_CALL f_destroy_fence(VkDevice d,VkFence f,const VkAllocationCallbacks*a){(void)d;(void)f;(void)a;}
static void VKAPI_CALL f_destroy_sem(VkDevice d,VkSemaphore s,const VkAllocationCallbacks*a){(void)d;(void)s;(void)a;}
static VkResult VKAPI_CALL f_wait(VkDevice d,uint32_t n,const VkFence*f,VkBool32 all,uint64_t t){(void)d;(void)n;(void)f;(void)all;(void)t;return VK_SUCCESS;}
static VkResult VKAPI_CALL f_reset(VkDevice d,uint32_t n,const VkFence*f){(void)d;(void)n;(void)f;return VK_SUCCESS;}
static VkResult VKAPI_CALL f_submit(VkQueue q,uint32_t n,const VkSubmitInfo*s,VkFence f){(void)q;(void)n;(void)f;
 for(uint32_t i=0;i<s->signalSemaphoreCount;i++)__atomic_add_fetch(&signals[((uintptr_t)s->pSignalSemaphores[i]-1)%PACE_SLOTS],1,__ATOMIC_SEQ_CST);
 __atomic_add_fetch(&submits,1,__ATOMIC_SEQ_CST);usleep(20);return VK_SUCCESS;}
static VkResult VKAPI_CALL f_present(VkQueue q,const VkPresentInfoKHR*p){(void)q;
 for(uint32_t i=0;i<p->waitSemaphoreCount;i++)__atomic_sub_fetch(&signals[((uintptr_t)p->pWaitSemaphores[i]-1)%PACE_SLOTS],1,__ATOMIC_SEQ_CST);
 __atomic_add_fetch(&presents,1,__ATOMIC_SEQ_CST);return present_result;}
static uint32_t created_images,surface_maximum;static VkResult caps_result=VK_SUCCESS;
static VkResult VKAPI_CALL f_caps(VkPhysicalDevice d,VkSurfaceKHR surface,VkSurfaceCapabilitiesKHR*caps){(void)d;(void)surface;memset(caps,0,sizeof(*caps));caps->maxImageCount=surface_maximum;return caps_result;}
static VkResult VKAPI_CALL f_create_chain(VkDevice d,const VkSwapchainCreateInfoKHR*i,const VkAllocationCallbacks*a,VkSwapchainKHR*o){(void)d;(void)a;created_images=i->minImageCount;*o=(VkSwapchainKHR)9;return VK_SUCCESS;}
static void VKAPI_CALL f_destroy_chain(VkDevice d,VkSwapchainKHR c,const VkAllocationCallbacks*a){(void)d;(void)c;(void)a;}
static void*key=(void*)0x77;static void*queue_a=(void*)0x77,*queue_b=(void*)0x77;
static void*presenter(void*q){
 VkSwapchainKHR chain=(VkSwapchainKHR)(uintptr_t)(q==&queue_a?1:2);uint32_t index=0;
 VkPresentInfoKHR info={VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,NULL,0,NULL,1,&chain,&index,NULL};
 for(int i=0;i<1500;i++)assert(queue_present((VkQueue)q,&info)==VK_SUCCESS);
 return NULL;
}
static VkResult present_on(VkSwapchainKHR chain){uint32_t index=0;VkPresentInfoKHR info={VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,NULL,0,NULL,1,&chain,&index,NULL};return queue_present((VkQueue)&queue_a,&info);}
int main(void){
 /* Switch values. */
 setenv("BC250_XEFG_PACE","off",1);assert(pace_switch("BC250_XEFG_PACE")==0);
 setenv("BC250_XEFG_PACE","FALSE",1);assert(pace_switch("BC250_XEFG_PACE")==0);
 setenv("BC250_XEFG_PACE","yes",1);assert(pace_switch("BC250_XEFG_PACE")==1);
 setenv("BC250_XEFG_PACE","auto",1);assert(pace_switch("BC250_XEFG_PACE")==-1);
 setenv("BC250_XEFG_PACE","maybe",1);assert(pace_switch("BC250_XEFG_PACE")==-1);
 setenv("BC250_XEFG_PACE","1",1);setenv("BC250_XEFG_PACE_NUDGE","0",1);
 struct device_state*s=calloc(1,sizeof(*s));
 *s=(struct device_state){.device=(VkDevice)4,.key=key,.pace_shared=1,.present=f_present,.submit=f_submit,.create_fence=f_create_fence,.destroy_fence=f_destroy_fence,
  .create_sem=f_create_sem,.destroy_sem=f_destroy_sem,.wait_fences=f_wait,.reset_fences=f_reset,.create_swapchain=f_create_chain,.destroy_swapchain=f_destroy_chain};devices=s;
 /* Two presenting threads: nothing lost, no ring semaphore signalled twice. */
 pthread_t a,b;pthread_create(&a,NULL,presenter,&queue_a);pthread_create(&b,NULL,presenter,&queue_b);pthread_join(a,NULL);pthread_join(b,NULL);
 pace_drain();
 for(int i=0;i<PACE_SLOTS;i++)assert(signals[i]==0);
 assert(presents==3000&&submits==3000);
 /* A deferred SUBOPTIMAL is returned to the next present on its swapchain... */
 present_result=VK_SUBOPTIMAL_KHR;assert(present_on((VkSwapchainKHR)1)==VK_SUCCESS);pace_drain();present_result=VK_SUCCESS;
 assert(present_on((VkSwapchainKHR)1)==VK_SUBOPTIMAL_KHR);pace_drain();
 /* ...a real error (here on another swapchain, before the app presents again) replaces a stored SUBOPTIMAL... */
 present_result=VK_SUBOPTIMAL_KHR;assert(present_on((VkSwapchainKHR)1)==VK_SUCCESS);pace_drain();
 present_result=VK_ERROR_SURFACE_LOST_KHR;assert(present_on((VkSwapchainKHR)2)==VK_SUCCESS);pace_drain();present_result=VK_SUCCESS;
 assert(pq.error==VK_ERROR_SURFACE_LOST_KHR&&pq.error_chain==(VkSwapchainKHR)2);
 pq.error_chain=(VkSwapchainKHR)1; /* as if it had come from swapchain 1, for the recreate case below */
 /* ...and a stored error goes with its swapchain (recreated with oldSwapchain, or destroyed). */
 VkSwapchainCreateInfoKHR ci={.sType=VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,.minImageCount=3,.oldSwapchain=(VkSwapchainKHR)1};VkSwapchainKHR fresh;
 assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS);assert(pq.error==VK_SUCCESS);
 assert(created_images==4); // no capabilities function: original one-image allowance
 s->surface_caps=f_caps;surface_maximum=0;
 assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS&&created_images==6);
 surface_maximum=4;assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS&&created_images==4);
 surface_maximum=3;assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS&&created_images==3);
 caps_result=VK_ERROR_SURFACE_LOST_KHR;
 assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS&&created_images==4);
 s->pace_shared=0;assert(create_swapchain((VkDevice)&queue_a,&ci,NULL,&fresh)==VK_SUCCESS&&created_images==3);s->pace_shared=1;
 present_result=VK_SUBOPTIMAL_KHR;assert(present_on((VkSwapchainKHR)2)==VK_SUCCESS);pace_drain();present_result=VK_SUCCESS;
 destroy_swapchain((VkDevice)&queue_a,(VkSwapchainKHR)2,NULL);assert(pq.error==VK_SUCCESS);
 assert(present_on((VkSwapchainKHR)2)==VK_SUCCESS);pace_drain();
 printf("PASS concurrent presents on two queues, deferred errors per swapchain, pace switch values\n");
 return 0;
}
