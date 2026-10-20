#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <io.h>

#define STATUS_CAPACITY 512
#define MAX_COMMAND_LENGTH 32768

static HANDLE g_process = NULL;
static DWORD g_process_id = 0;
static wchar_t g_window_title[128];
static int g_volume = 50;
static int g_hwaccel_checked = 0;
static int g_hwaccel_supported = 0;

static void set_status(char *status, size_t capacity, const char *message) {
    if (status && capacity > 0) {
        snprintf(status, capacity, "%s", message ? message : "");
    }
}

static void set_windows_error(char *status, size_t capacity, const char *operation) {
    char detail[256] = "unknown Windows error";
    DWORD code = GetLastError();
    FormatMessageA(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL,
        code,
        0,
        detail,
        (DWORD)sizeof(detail),
        NULL
    );
    snprintf(status, capacity, "%s failed: %s (error %lu)", operation, detail, (unsigned long)code);
}

static int append_text(wchar_t *buffer, size_t capacity, size_t *length, const wchar_t *text) {
    size_t text_length = wcslen(text);
    if (*length + text_length >= capacity) {
        return 0;
    }
    memcpy(buffer + *length, text, text_length * sizeof(wchar_t));
    *length += text_length;
    buffer[*length] = L'\0';
    return 1;
}

static int append_quoted(wchar_t *buffer, size_t capacity, size_t *length, const wchar_t *argument) {
    if (!append_text(buffer, capacity, length, L"\"")) return 0;

    size_t slashes = 0;
    for (const wchar_t *cursor = argument; ; ++cursor) {
        if (*cursor == L'\\') {
            slashes++;
            continue;
        }
        if (*cursor == L'"') {
            for (size_t i = 0; i < slashes * 2 + 1; ++i) {
                if (!append_text(buffer, capacity, length, L"\\")) return 0;
            }
            if (!append_text(buffer, capacity, length, L"\"")) return 0;
            slashes = 0;
            continue;
        }
        if (*cursor == L'\0') {
            for (size_t i = 0; i < slashes * 2; ++i) {
                if (!append_text(buffer, capacity, length, L"\\")) return 0;
            }
            break;
        }
        for (size_t i = 0; i < slashes; ++i) {
            if (!append_text(buffer, capacity, length, L"\\")) return 0;
        }
        slashes = 0;
        wchar_t character[2] = {*cursor, L'\0'};
        if (!append_text(buffer, capacity, length, character)) return 0;
    }

    return append_text(buffer, capacity, length, L"\"");
}

static int resolve_ffplay(wchar_t *executable, size_t capacity) {
    DWORD configured_length = GetEnvironmentVariableW(L"OPERATOR_FFPLAY", executable, (DWORD)capacity);
    if (configured_length > 0 && configured_length < capacity && _waccess(executable, 0) == 0) {
        return 1;
    }
    DWORD found_length = SearchPathW(NULL, L"ffplay.exe", NULL, (DWORD)capacity, executable, NULL);
    return found_length > 0 && found_length < capacity;
}

static int launch_probe(const wchar_t *executable) {
    wchar_t command[MAX_COMMAND_LENGTH] = L"";
    size_t length = 0;
    if (!append_quoted(command, MAX_COMMAND_LENGTH, &length, executable) ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, L" -hide_banner -hwaccel auto -version")) {
        return 0;
    }

    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(
        executable, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
        NULL, NULL, &startup, &process
    )) {
        return 0;
    }

    DWORD wait_result = WaitForSingleObject(process.hProcess, 5000);
    DWORD exit_code = 1;
    if (wait_result == WAIT_OBJECT_0) {
        GetExitCodeProcess(process.hProcess, &exit_code);
    } else {
        TerminateProcess(process.hProcess, 1);
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return wait_result == WAIT_OBJECT_0 && exit_code == 0;
}

static HWND find_process_window(void) {
    if (!g_process_id) return NULL;

    for (int attempt = 0; attempt < 60; ++attempt) {
        HWND window = GetTopWindow(NULL);
        while (window) {
            DWORD owner = 0;
            GetWindowThreadProcessId(window, &owner);
            if (owner == g_process_id && IsWindowVisible(window)) {
                return window;
            }
            window = GetNextWindow(window, GW_HWNDNEXT);
        }
        if (!g_process || WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0) {
            return NULL;
        }
        Sleep(50);
    }
    return NULL;
}

static int post_key(WORD key, char *status, size_t capacity) {
    if (!g_process || WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0) {
        set_status(status, capacity, "No powcurl playback is active");
        return 0;
    }
    HWND window = find_process_window();
    if (!window) {
        set_status(status, capacity, "The playback window is not available");
        return 0;
    }
    if (!PostMessageW(window, WM_KEYDOWN, key, 0) ||
        !PostMessageW(window, WM_KEYUP, key, 0)) {
        set_windows_error(status, capacity, "Sending playback control");
        return 0;
    }
    return 1;
}

static int is_audio_path(const wchar_t *path) {
    const wchar_t *extension = wcsrchr(path, L'.');
    if (!extension) return 0;
    return _wcsicmp(extension, L".mp3") == 0 ||
        _wcsicmp(extension, L".wav") == 0;
}

static void close_process_handles(void) {
    if (g_process) {
        CloseHandle(g_process);
        g_process = NULL;
    }
    g_process_id = 0;
}

int operator_media_start(const wchar_t *media_path, int volume, char *status, size_t capacity) {
    if (!media_path || !*media_path || _waccess(media_path, 4) != 0) {
        set_status(status, capacity, "Media file does not exist or cannot be read");
        return 0;
    }
    if (volume < 0 || volume > 100) {
        set_status(status, capacity, "Volume must be between 0 and 100");
        return 0;
    }
    if (g_process && WaitForSingleObject(g_process, 0) == WAIT_TIMEOUT) {
        set_status(status, capacity, "A powcurl playback window is already active");
        return 0;
    }
    close_process_handles();

    wchar_t executable[MAX_PATH];
    if (!resolve_ffplay(executable, MAX_PATH)) {
        set_status(status, capacity, "ffplay.exe was not found; install FFmpeg or set OPERATOR_FFPLAY");
        return 0;
    }

    if (!g_hwaccel_checked) {
        g_hwaccel_supported = launch_probe(executable);
        g_hwaccel_checked = 1;
    }

    swprintf(g_window_title, sizeof(g_window_title) / sizeof(g_window_title[0]),
        L"Operator powcurl %lu", (unsigned long)GetTickCount());

    wchar_t command[MAX_COMMAND_LENGTH] = L"";
    size_t length = 0;
    wchar_t volume_text[8];
    const wchar_t *show_mode = is_audio_path(media_path) ? L" -showmode 1" : L" -showmode 0";
    swprintf(volume_text, sizeof(volume_text) / sizeof(volume_text[0]), L"%d", volume);

    if (!append_quoted(command, MAX_COMMAND_LENGTH, &length, executable) ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, L" -hide_banner -loglevel error -autoexit") ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, show_mode) ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, L" -volume ") ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, volume_text) ||
        !append_text(command, MAX_COMMAND_LENGTH, &length, L" -window_title ") ||
        !append_quoted(command, MAX_COMMAND_LENGTH, &length, g_window_title)) {
        set_status(status, capacity, "The playback command is too long");
        return 0;
    }
    if (g_hwaccel_supported &&
        !append_text(command, MAX_COMMAND_LENGTH, &length, L" -hwaccel auto")) {
        set_status(status, capacity, "The playback command is too long");
        return 0;
    }
    if (!append_text(command, MAX_COMMAND_LENGTH, &length, L" ") ||
        !append_quoted(command, MAX_COMMAND_LENGTH, &length, media_path)) {
        set_status(status, capacity, "The playback command is too long");
        return 0;
    }

    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(
        executable, command, NULL, NULL, FALSE,
        CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        NULL, NULL, &startup, &process
    )) {
        set_windows_error(status, capacity, "Starting FFplay");
        return 0;
    }

    g_process = process.hProcess;
    g_process_id = process.dwProcessId;
    g_volume = volume;
    CloseHandle(process.hThread);
    Sleep(200);
    if (WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0) {
        DWORD exit_code = 1;
        GetExitCodeProcess(g_process, &exit_code);
        char message[STATUS_CAPACITY];
        snprintf(message, sizeof(message), "FFplay exited immediately (code %lu); check its codec support and media file",
            (unsigned long)exit_code);
        set_status(status, capacity, message);
        close_process_handles();
        return 0;
    }

    if (!g_hwaccel_supported) {
        set_status(status, capacity, "This FFplay build lacks automatic hardware decoding; playback is using CPU decoding");
    }
    return 1;
}

int operator_media_toggle_pause(char *status, size_t capacity) {
    return post_key(VK_SPACE, status, capacity);
}

int operator_media_seek(int seconds, char *status, size_t capacity) {
    if (seconds < -3600 || seconds > 3600 || seconds % 10 != 0) {
        set_status(status, capacity, "Seek offset must be a 10-second step between -3600 and 3600");
        return 0;
    }
    WORD key = seconds < 0 ? VK_LEFT : VK_RIGHT;
    unsigned int presses = (unsigned int)(abs(seconds) / 10);
    if (seconds != 0 && presses == 0) presses = 1;
    for (unsigned int i = 0; i < presses; ++i) {
        if (!post_key(key, status, capacity)) return 0;
        Sleep(20);
    }
    return 1;
}

int operator_media_set_volume(int volume, char *status, size_t capacity) {
    if (volume < 0 || volume > 100) {
        set_status(status, capacity, "Volume must be between 0 and 100");
        return 0;
    }
    if (!g_process || WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0) {
        g_volume = volume;
        return 1;
    }
    int difference = volume - g_volume;
    WORD key = difference < 0 ? VK_DOWN : VK_UP;
    unsigned int presses = (unsigned int)abs(difference);
    for (unsigned int i = 0; i < presses; ++i) {
        if (!post_key(key, status, capacity)) return 0;
        Sleep(20);
    }
    g_volume = volume;
    return 1;
}

int operator_media_wait(char *status, size_t capacity) {
    if (!g_process) {
        set_status(status, capacity, "No powcurl playback is active");
        return 0;
    }
    DWORD wait_result = WaitForSingleObject(g_process, INFINITE);
    DWORD exit_code = 1;
    if (wait_result != WAIT_OBJECT_0 || !GetExitCodeProcess(g_process, &exit_code)) {
        set_windows_error(status, capacity, "Waiting for playback");
        close_process_handles();
        return 0;
    }
    close_process_handles();
    if (exit_code != 0) {
        char message[STATUS_CAPACITY];
        snprintf(message, sizeof(message), "FFplay exited with code %lu", (unsigned long)exit_code);
        set_status(status, capacity, message);
        return 0;
    }
    return 1;
}

int operator_media_stop(char *status, size_t capacity) {
    if (!g_process) return 1;
    if (WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0) {
        close_process_handles();
        return 1;
    }

    HWND window = find_process_window();
    if (window) {
        PostMessageW(window, WM_KEYDOWN, 'Q', 0);
        PostMessageW(window, WM_KEYUP, 'Q', 0);
    }
    if (WaitForSingleObject(g_process, 2000) != WAIT_OBJECT_0) {
        if (!TerminateProcess(g_process, 0)) {
            set_windows_error(status, capacity, "Stopping playback");
            return 0;
        }
        WaitForSingleObject(g_process, 2000);
    }
    close_process_handles();
    return 1;
}
