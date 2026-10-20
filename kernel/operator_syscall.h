#ifndef OPERATOR_SYSCALL_H
#define OPERATOR_SYSCALL_H

#include <stdint.h>

typedef enum {
    OP_SYS_PROCESS_CREATE = 1,
    OP_SYS_MEMORY_ALLOCATE,
    OP_SYS_SCHEDULER_TICK,
    OP_SYS_PROCESS_TERMINATE,
    OP_SYS_DIAGNOSTICS
} OperatorSyscallNumber;

typedef struct {
    OperatorSyscallNumber number;
    union {
        struct {
            const char *name;
            uint32_t priority;
        } process_create;
        struct {
            uint32_t pid;
            uint32_t num_blocks;
        } memory_allocate;
        struct {
            uint32_t pid;
        } process_terminate;
    } args;
} OperatorSyscall;

int64_t operator_kernel_syscall(const OperatorSyscall *call);

#endif
