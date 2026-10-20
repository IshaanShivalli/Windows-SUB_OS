/* Native Operator shell launcher. Keeps startup and process handoff in C. */
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    char command[4096];
    snprintf(command, sizeof(command),
        "java -cp runtime_java\\bin operator.pow.PowShell");
    STARTUPINFOA si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    if (!CreateProcessA(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) {
        fprintf(stderr, "Operator shell launch failed: %lu\n", GetLastError());
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
