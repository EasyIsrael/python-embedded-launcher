#include <windows.h>
#include <stdio.h>
#include <shellapi.h>
#include <stdbool.h>
#include <string.h>
#include <wchar.h>
#include "launcher3.h"

#define Py_LIMITED_API
#include <Python.h>

#define FIND_FUNCTION(name) \
    FARPROC name = GetProcAddress(python_dll, #name); \
    if (name == NULL) { \
        printf(#name " not found"); \
        show_message_from_resource(IDS_PYDLL_ERROR); \
        return 1; \
    }


wchar_t pythonhome_relative[PATH_MAX];
wchar_t pythonhome_absolute[PATH_MAX];


// show a message dialog with text from the built-in resource
void show_message_from_resource(int id) {
    wchar_t name[80];
    wchar_t message[1024];
    LoadString(NULL, IDS_NAME, name, sizeof(name));
    LoadString(NULL, id, message, sizeof(message));
    MessageBox(NULL, message, name, MB_OK | MB_ICONSTOP);
}


// test if a file has a zip appended to it
bool test_zip_file(const wchar_t *path) {
    HANDLE hFile = CreateFile(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile != INVALID_HANDLE_VALUE) {
        char zipid[22];
        DWORD len;
        SetFilePointer(hFile, -sizeof(zipid), NULL, FILE_END);
        ReadFile(hFile, zipid, sizeof(zipid), &len, NULL);
        CloseHandle(hFile);
        return 0 == memcmp(zipid, "PK\005\006", 4);
    } else {
        return false;
    }
}


// given a path, write a null byte where the filename starts
// does not seem that Windows has this as a function in its core, just in
// extra DLLs.
void cut_away_filename(wchar_t * path) {
    unsigned slash = 0;
    // search the entire string and remember position of last path separator
    for (unsigned pos=0; path[pos]; pos++) {
        if (path[pos] == L'\\' || path[pos] == L'/') {
            slash = pos;
        }
    }
    path[slash] = '\0';
}

// append a filename to a path
// does not seem that Windows has this as a function in its core, just in
// extra DLLs.
void append_filename(wchar_t *path_out, size_t outsize, const wchar_t *path_in,
                     const wchar_t *filename, const wchar_t *extension) {
    while (outsize && *path_in) {
        *path_out++ = *path_in++;
        outsize--;
    }
    if (outsize) {
        *path_out++ = '\\';
        outsize--;
    }
    while (outsize && *filename) {
        *path_out++ = *filename++;
        outsize--;
    }
    while (outsize && *extension) {
        *path_out++ = *extension++;
        outsize--;
    }
    if (outsize) *path_out = '\0';
}


bool check_if_directory_exists(wchar_t * path) {
    DWORD dwAttrib = GetFileAttributes(path);
    return (dwAttrib != INVALID_FILE_ATTRIBUTES && 
           (dwAttrib & FILE_ATTRIBUTE_DIRECTORY));
}


// set an environment variable "SELF" pointing to the location of the executable
void set_self_env(void) {
    static wchar_t env_self[PATH_MAX];
    GetModuleFileName(NULL, env_self, sizeof(env_self));
    cut_away_filename(env_self);
    SetEnvironmentVariable(L"SELF", env_self);
}


// where to find our python?
void get_pythonhome(void) {
    wchar_t pythonhome_in[PATH_MAX];
    LoadString(NULL, IDS_PYTHONHOME, pythonhome_in, sizeof(pythonhome_in));
    ExpandEnvironmentStrings(pythonhome_in, pythonhome_relative, sizeof(pythonhome_relative));
    GetFullPathName(pythonhome_relative, sizeof(pythonhome_absolute), pythonhome_absolute, NULL);
    //~ wprintf(L"env: %s\n", pythonhome_absolute);
}


// prefix PATH environment variable with the location of our Python installation
void patch_path_env(void) {
    static wchar_t env_path[32760];
    unsigned pos = snwprintf(env_path, sizeof(env_path), L"%s;", pythonhome_absolute);
    GetEnvironmentVariable(L"PATH", &env_path[pos], sizeof(env_path) - pos);
    SetEnvironmentVariable(L"PATH", env_path);
}


int main() {
    set_self_env();
    get_pythonhome();
    if (!check_if_directory_exists(pythonhome_absolute)) {
        wprintf(L"ERROR python minimal distribution not found!\n"
                 "Directory not found: %s\n", pythonhome_absolute);
        show_message_from_resource(IDS_PY_NOT_FOUND);
        return 3;
    }
    // patch PATH so that DLLs can be found
    patch_path_env();

    wchar_t pydll_path[PATH_MAX];
    wchar_t python_version[20];
    LoadString(NULL, IDS_PY_VERSION, python_version, sizeof(python_version));
    append_filename(pydll_path, sizeof(pydll_path), pythonhome_absolute, python_version,  L".dll");
    HMODULE python_dll = LoadLibrary(pydll_path);
    if (python_dll == NULL) {
        wprintf(L"Python is expected in: %s\n\n"
                 "ERROR Python DLL not found!\n"
                 "File not found: %s\n" , pythonhome_absolute, pydll_path);
        show_message_from_resource(IDS_PYDLL_NOT_FOUND);
        return 1;
    }

    // get a few pointers to symbols in Python DLL
    FIND_FUNCTION(Py_Main)
    FIND_FUNCTION(Py_SetProgramName)
    FIND_FUNCTION(Py_SetPythonHome)
    FIND_FUNCTION(Py_SetPath)

    // Set the name and isolate Python from the environment
    wchar_t argv_0[PATH_MAX];
    GetModuleFileName(NULL, argv_0, sizeof(argv_0));
    Py_SetProgramName(argv_0);
    Py_SetPythonHome(pythonhome_absolute);
    // must ensure that python finds its "landmark file" Lib/os.py (it is in python35.zip)
    wchar_t pythonpath[32768];
    snwprintf(pythonpath, sizeof(pythonpath), L"%s;%s\\%s.zip", 
              pythonhome_absolute, pythonhome_absolute, python_version);
    Py_SetPath(pythonpath);

    // the application is appended as zip to the exe. so load ourselfes
    // to get a nice user feedback, test first if the zip is really appended
    if (!test_zip_file(argv_0)) {
        wprintf(L"ERROR application not found!\n"
                 "No zip data appended to file: %s\n", argv_0);
        show_message_from_resource(IDS_ZIP_NOT_FOUND);
        return 1;
    }

    // use the high level entry to start our boot code, pass along the location of our python installation
    int retcode = Py_Main(4, (wchar_t *[]){L"", L"-I", argv_0, pythonhome_absolute});
    //~ printf("exitcode %d\n", retcode);
    return retcode;
}

