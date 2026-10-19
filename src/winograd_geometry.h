/* SPDX-License-Identifier: MIT
 * Bound the existing dynamic F(4,3) helpers by their actual indexing and D3D12
 * dispatch/buffer limits, rather than a historical display-resolution trial.
 */
#include <stdint.h>
struct bc250_winograd_geometry {
 uint32_t tiles,matrix_columns,stride;
 uint64_t bytes;
};
static int bc250_winograd_geometry(uint32_t w,uint32_t h,uint32_t channels,uint32_t columns,uint32_t pad,struct bc250_winograd_geometry*out) {
 if(!out||!w||!h||w>16384||h>16384||(channels!=64&&channels!=224)||
    (columns!=32&&columns!=48)||(pad!=0&&pad!=16)||pad>=columns)return 0;
 uint64_t tiles=(((uint64_t)w+3)/4)*(((uint64_t)h+3)/4);
 uint64_t matrix=((tiles+columns-1)/columns)*columns,stride=matrix+pad;
 uint64_t elements=36*channels*stride;
 /* One finish group per tile; preparation uses eight columns per group.
  * Root UAVs are uint/int structured buffers. Keeping <=2^27 elements also
  * keeps all existing shader element/byte indexes representable in uint32. */
 if(tiles>65535||stride%8||stride/8>65535||matrix/columns>65535||elements>(1ULL<<27))return 0;
 out->tiles=(uint32_t)tiles;out->matrix_columns=(uint32_t)matrix;
 out->stride=(uint32_t)stride;out->bytes=elements*4;return 1;
}
