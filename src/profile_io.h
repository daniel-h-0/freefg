/* SPDX-License-Identifier: MIT
 * The shader profile's files by their UTF-8 path (patchdir and a file name), opened through the wide-character API: a
 * game folder whose name the ANSI code page cannot spell still loads its profile. noinline keeps each caller's frame
 * below one page (the add-on has no stack probe without the CRT).
 */
static __attribute__((noinline)) FILE*profile_fopen(const char*path,const char*mode){
 wchar_t wide[1400],wide_mode[8];
 if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,1400)||!MultiByteToWideChar(CP_UTF8,0,mode,-1,wide_mode,8))return NULL;
 return _wfopen(wide,wide_mode);
}
static __attribute__((noinline)) HANDLE profile_open(const char*path){
 wchar_t wide[1400];if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,1400))return INVALID_HANDLE_VALUE;
 return CreateFileW(wide,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
}
