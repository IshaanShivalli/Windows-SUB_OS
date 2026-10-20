/**
 * Operator OS Core Kernel (C Implementation)
 * Features:
 * - Process Control Block (PCB) table
 * - Round-Robin Scheduler with tick emulation
 * - Slab/Pool Memory Allocator simulation
 * - Virtual File System (VFS) nodes
 * - IPC Pipe messaging system
 * - Syscall dispatcher
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "operator_syscall.h"

#define MAX_PROCESSES 64
#define MAX_MEM_BLOCKS 256
#define BLOCK_SIZE 4096
#define MAX_VFS_FILES 128
#define MAX_IPC_MESSAGES 128
#define IPC_PAYLOAD_SIZE 256
#define PRIORITY_AGING_TICKS 4

typedef enum {
    PROC_READY,
    PROC_RUNNING,
    PROC_WAITING,
    PROC_TERMINATED
} ProcessState;

typedef struct {
    uint32_t pid;
    char name[32];
    ProcessState state;
    uint32_t priority;
    uint32_t allocated_bytes;
    uint32_t cpu_ticks;
    uint32_t waiting_ticks;
} ProcessControlBlock;

typedef struct {
    uint32_t block_index;
    uint32_t pid_owner;
    bool in_use;
} MemoryBlock;

typedef struct {
    char path[128];
    uint32_t size;
    uint32_t permissions; // e.g. 0755
    char content[512];
} VFSNode;

typedef struct {
    uint32_t from_pid;
    uint32_t to_pid;
    char payload[IPC_PAYLOAD_SIZE];
} IPCMessage;

/* Global Kernel State */
static ProcessControlBlock g_pcb_table[MAX_PROCESSES];
static MemoryBlock g_memory_map[MAX_MEM_BLOCKS];
static VFSNode g_vfs_nodes[MAX_VFS_FILES];
static IPCMessage g_ipc_queue[MAX_IPC_MESSAGES];
static uint32_t g_process_count = 0;
static uint32_t g_vfs_count = 0;
static uint32_t g_ipc_count = 0;
static uint32_t g_current_pid_index = 0;

void kernel_dump_diagnostics(void);

void kernel_init(void) {
    memset(g_pcb_table, 0, sizeof(g_pcb_table));
    memset(g_memory_map, 0, sizeof(g_memory_map));
    memset(g_vfs_nodes, 0, sizeof(g_vfs_nodes));
    memset(g_ipc_queue, 0, sizeof(g_ipc_queue));
    g_process_count = 0;
    g_vfs_count = 0;
    g_ipc_count = 0;
    g_current_pid_index = 0;

    for (int i = 0; i < MAX_MEM_BLOCKS; i++) {
        g_memory_map[i].block_index = i;
        g_memory_map[i].in_use = false;
        g_memory_map[i].pid_owner = 0;
    }

    printf("[KERNEL:C] Operator Kernel v1.0 initialized.\n");
    printf("[KERNEL:C] Initialized %d Memory Pages (Total: %d KB)\n", MAX_MEM_BLOCKS, (MAX_MEM_BLOCKS * BLOCK_SIZE) / 1024);
}

int32_t sys_process_create(const char *name, uint32_t priority) {
    for (uint32_t i = 1; i < MAX_PROCESSES; i++) {
        if (g_pcb_table[i].pid == 0 || g_pcb_table[i].state == PROC_TERMINATED) {
            g_pcb_table[i].pid = i;
            strncpy(g_pcb_table[i].name, name, sizeof(g_pcb_table[i].name) - 1);
            g_pcb_table[i].name[sizeof(g_pcb_table[i].name) - 1] = '\0';
            g_pcb_table[i].state = PROC_READY;
            g_pcb_table[i].priority = priority;
            g_pcb_table[i].allocated_bytes = 0;
            g_pcb_table[i].cpu_ticks = 0;
            g_pcb_table[i].waiting_ticks = 0;
            g_process_count++;
            printf("[KERNEL:C] Created process PID=%u ('%s') with Priority=%u\n", i, name, priority);
            return (int32_t)i;
        }
    }
    return -1;
}

bool sys_mem_allocate(uint32_t pid, uint32_t num_blocks) {
    if (pid == 0 || pid >= MAX_PROCESSES || g_pcb_table[pid].pid != pid ||
        g_pcb_table[pid].state == PROC_TERMINATED || num_blocks == 0) {
        return false;
    }

    uint32_t available = 0;
    for (uint32_t i = 0; i < MAX_MEM_BLOCKS; i++) {
        if (!g_memory_map[i].in_use) available++;
    }
    if (available < num_blocks ||
        num_blocks > (UINT32_MAX - g_pcb_table[pid].allocated_bytes) / BLOCK_SIZE) {
        return false;
    }

    uint32_t allocated = 0;
    for (uint32_t i = 0; i < MAX_MEM_BLOCKS && allocated < num_blocks; i++) {
        if (!g_memory_map[i].in_use) {
            g_memory_map[i].in_use = true;
            g_memory_map[i].pid_owner = pid;
            allocated++;
        }
    }
    g_pcb_table[pid].allocated_bytes += num_blocks * BLOCK_SIZE;
    return true;
}

static void sys_mem_release(uint32_t pid) {
    for (uint32_t i = 0; i < MAX_MEM_BLOCKS; i++) {
        if (g_memory_map[i].in_use && g_memory_map[i].pid_owner == pid) {
            g_memory_map[i].in_use = false;
            g_memory_map[i].pid_owner = 0;
        }
    }
    if (pid < MAX_PROCESSES) {
        g_pcb_table[pid].allocated_bytes = 0;
    }
}

static bool sys_process_terminate(uint32_t pid) {
    if (pid == 0 || pid >= MAX_PROCESSES || g_pcb_table[pid].pid != pid ||
        g_pcb_table[pid].state == PROC_TERMINATED) {
        return false;
    }
    g_pcb_table[pid].state = PROC_TERMINATED;
    sys_mem_release(pid);
    if (g_process_count > 0) g_process_count--;
    return true;
}

int32_t sys_scheduler_tick(void) {
    if (g_process_count == 0) return 0;

    uint32_t selected = MAX_PROCESSES;
    uint64_t selected_priority = 0;
    for (uint32_t offset = 1; offset <= MAX_PROCESSES; offset++) {
        uint32_t index = (g_current_pid_index + offset) % MAX_PROCESSES;
        ProcessControlBlock *process = &g_pcb_table[index];
        if (process->pid != 0 && process->state == PROC_RUNNING) {
            process->state = PROC_READY;
        }
        if (process->pid != 0 && process->state == PROC_READY) {
            if (process->waiting_ticks < UINT32_MAX) process->waiting_ticks++;
            uint64_t effective_priority = (uint64_t)process->priority +
                process->waiting_ticks / PRIORITY_AGING_TICKS;
            if (selected == MAX_PROCESSES || effective_priority > selected_priority) {
                selected = index;
                selected_priority = effective_priority;
            }
        }
    }
    if (selected == MAX_PROCESSES) return 0;

    g_current_pid_index = selected;
    g_pcb_table[selected].state = PROC_RUNNING;
    g_pcb_table[selected].waiting_ticks = 0;
    g_pcb_table[selected].cpu_ticks++;
    printf("[KERNEL:C][SCHEDULER] Context switch -> PID %u ('%s') [Priority: %u, Ticks: %u, Mem: %u KB]\n",
           g_pcb_table[selected].pid,
           g_pcb_table[selected].name,
           g_pcb_table[selected].priority,
           g_pcb_table[selected].cpu_ticks,
           g_pcb_table[selected].allocated_bytes / 1024);
    return (int32_t)g_pcb_table[selected].pid;
}

int64_t operator_kernel_syscall(const OperatorSyscall *call) {
    if (call == NULL) return -1;

    switch (call->number) {
        case OP_SYS_PROCESS_CREATE:
            if (call->args.process_create.name == NULL ||
                call->args.process_create.name[0] == '\0') return -1;
            return sys_process_create(
                call->args.process_create.name,
                call->args.process_create.priority
            );
        case OP_SYS_MEMORY_ALLOCATE:
            return sys_mem_allocate(
                call->args.memory_allocate.pid,
                call->args.memory_allocate.num_blocks
            ) ? 0 : -1;
        case OP_SYS_SCHEDULER_TICK:
            return sys_scheduler_tick();
        case OP_SYS_PROCESS_TERMINATE:
            return sys_process_terminate(call->args.process_terminate.pid) ? 0 : -1;
        case OP_SYS_DIAGNOSTICS:
            kernel_dump_diagnostics();
            return 0;
        default:
            return -1;
    }
}

bool sys_vfs_mount(const char *path, const char *initial_data) {
    if (g_vfs_count >= MAX_VFS_FILES) return false;
    strncpy(g_vfs_nodes[g_vfs_count].path, path, 127);
    strncpy(g_vfs_nodes[g_vfs_count].content, initial_data, 511);
    g_vfs_nodes[g_vfs_count].size = (uint32_t)strlen(initial_data);
    g_vfs_nodes[g_vfs_count].permissions = 0755;
    g_vfs_count++;
    printf("[KERNEL:C][VFS] Mounted virtual node '%s' (bytes: %u)\n", path, (uint32_t)strlen(initial_data));
    return true;
}

bool sys_ipc_send(uint32_t from_pid, uint32_t to_pid, const char *payload) {
    if (g_ipc_count >= MAX_IPC_MESSAGES) return false;
    g_ipc_queue[g_ipc_count].from_pid = from_pid;
    g_ipc_queue[g_ipc_count].to_pid = to_pid;
    strncpy(g_ipc_queue[g_ipc_count].payload, payload, IPC_PAYLOAD_SIZE - 1);
    g_ipc_count++;
    printf("[KERNEL:C][IPC] Message from PID %u -> PID %u: \"%s\"\n", from_pid, to_pid, payload);
    return true;
}

void kernel_dump_diagnostics(void) {
    printf("\n=== OPERATOR KERNEL STATUS REPORT ===\n");
    printf("Active Processes: %u\n", g_process_count);
    for (uint32_t i = 1; i < MAX_PROCESSES; i++) {
        if (g_pcb_table[i].pid != 0) {
            printf("  - PID %u: %s (State: %d, Mem: %u KB, Ticks: %u)\n",
                   g_pcb_table[i].pid,
                   g_pcb_table[i].name,
                   g_pcb_table[i].state,
                   g_pcb_table[i].allocated_bytes / 1024,
                   g_pcb_table[i].cpu_ticks);
        }
    }
    printf("Virtual Filesystem Mounts: %u\n", g_vfs_count);
    for (uint32_t i = 0; i < g_vfs_count; i++) {
        printf("  - %s (%u bytes)\n", g_vfs_nodes[i].path, g_vfs_nodes[i].size);
    }
    printf("Pending IPC Packets: %u\n", g_ipc_count);
    printf("======================================\n\n");
}

static int kernel_self_test(void) {
    kernel_init();
    OperatorSyscall call = {0};
    call.number = OP_SYS_PROCESS_CREATE;
    call.args.process_create.name = "low_priority";
    call.args.process_create.priority = 1;
    int64_t low_pid = operator_kernel_syscall(&call);
    call.args.process_create.name = "high_priority";
    call.args.process_create.priority = 10;
    int64_t high_pid = operator_kernel_syscall(&call);
    if (low_pid <= 0 || high_pid <= 0) return 1;

    call.number = OP_SYS_MEMORY_ALLOCATE;
    call.args.memory_allocate.pid = (uint32_t)high_pid;
    call.args.memory_allocate.num_blocks = 2;
    if (operator_kernel_syscall(&call) != 0) return 1;
    call.args.memory_allocate.num_blocks = MAX_MEM_BLOCKS;
    if (operator_kernel_syscall(&call) == 0 ||
        g_pcb_table[high_pid].allocated_bytes != 2 * BLOCK_SIZE) return 1;
    call.args.memory_allocate.num_blocks = MAX_MEM_BLOCKS - 2;
    if (operator_kernel_syscall(&call) != 0 ||
        g_pcb_table[high_pid].allocated_bytes != MAX_MEM_BLOCKS * BLOCK_SIZE) return 1;

    call.number = OP_SYS_SCHEDULER_TICK;
    if (operator_kernel_syscall(&call) != high_pid) return 1;
    if (operator_kernel_syscall(&call) != high_pid) return 1;

    call.number = OP_SYS_PROCESS_TERMINATE;
    call.args.process_terminate.pid = (uint32_t)high_pid;
    if (operator_kernel_syscall(&call) != 0) return 1;
    call.number = OP_SYS_SCHEDULER_TICK;
    if (operator_kernel_syscall(&call) != low_pid) return 1;

    kernel_init();
    call.number = OP_SYS_PROCESS_CREATE;
    call.args.process_create.name = "aging_low";
    call.args.process_create.priority = 1;
    low_pid = operator_kernel_syscall(&call);
    call.args.process_create.name = "aging_high";
    call.args.process_create.priority = 5;
    high_pid = operator_kernel_syscall(&call);
    call.number = OP_SYS_SCHEDULER_TICK;
    for (uint32_t tick = 0; tick < 20; tick++) {
        operator_kernel_syscall(&call);
    }
    if (low_pid <= 0 || high_pid <= 0 || g_pcb_table[low_pid].cpu_ticks == 0) return 1;

    puts("[KERNEL:C][TEST] Syscalls, priority aging, and atomic process memory passed.");
    return 0;
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--self-test") == 0) {
        return kernel_self_test();
    }

    printf("Starting Operator OS Subsystem Kernel...\n");
    kernel_init();

    // Spawn fundamental system daemons
    OperatorSyscall call = {0};
    call.number = OP_SYS_PROCESS_CREATE;
    call.args.process_create.name = "opshell_daemon";
    call.args.process_create.priority = 8;
    int32_t pid_shell = (int32_t)operator_kernel_syscall(&call);
    call.args.process_create.name = "sqldb_service";
    call.args.process_create.priority = 9;
    int32_t pid_db = (int32_t)operator_kernel_syscall(&call);
    call.args.process_create.name = "java_runtime";
    call.args.process_create.priority = 5;
    int32_t pid_ovm = (int32_t)operator_kernel_syscall(&call);

    // Allocate memory pages
    call.number = OP_SYS_MEMORY_ALLOCATE;
    call.args.memory_allocate.pid = (uint32_t)pid_shell;
    call.args.memory_allocate.num_blocks = 8;
    operator_kernel_syscall(&call);
    call.args.memory_allocate.pid = (uint32_t)pid_db;
    call.args.memory_allocate.num_blocks = 12;
    operator_kernel_syscall(&call);
    call.args.memory_allocate.pid = (uint32_t)pid_ovm;
    call.args.memory_allocate.num_blocks = 24;
    operator_kernel_syscall(&call);

    // Mount core VFS filesystems
    sys_vfs_mount("/dev/null", "");
    sys_vfs_mount("/dev/kmsg", "[klog] system booted successfully\n");
    sys_vfs_mount("/etc/operator.conf", "hostname=operator-os\nversion=1.0.0\nmode=subsystem\n");
    sys_vfs_mount("/proc/cpuinfo", "model name: Operator Virtual Core (x86_64)\ncores: 4\n");

    // IPC handshake
    sys_ipc_send(pid_db, pid_shell, "DB_STATUS: ready uri='db/operator_system.db'");

    // Simulate scheduling passes
    call.number = OP_SYS_SCHEDULER_TICK;
    for (int tick = 0; tick < 8; tick++) {
        operator_kernel_syscall(&call);
    }

    call.number = OP_SYS_DIAGNOSTICS;
    operator_kernel_syscall(&call);
    return 0;
}
