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

#define MAX_PROCESSES 64
#define MAX_MEM_BLOCKS 256
#define BLOCK_SIZE 4096
#define MAX_VFS_FILES 128
#define MAX_IPC_MESSAGES 128
#define IPC_PAYLOAD_SIZE 256

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

void kernel_init(void) {
    memset(g_pcb_table, 0, sizeof(g_pcb_table));
    memset(g_memory_map, 0, sizeof(g_memory_map));
    memset(g_vfs_nodes, 0, sizeof(g_vfs_nodes));
    memset(g_ipc_queue, 0, sizeof(g_ipc_queue));

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
            strncpy(g_pcb_table[i].name, name, 31);
            g_pcb_table[i].state = PROC_READY;
            g_pcb_table[i].priority = priority;
            g_pcb_table[i].allocated_bytes = 0;
            g_pcb_table[i].cpu_ticks = 0;
            g_process_count++;
            printf("[KERNEL:C] Created process PID=%u ('%s') with Priority=%u\n", i, name, priority);
            return (int32_t)i;
        }
    }
    return -1;
}

bool sys_mem_allocate(uint32_t pid, uint32_t num_blocks) {
    uint32_t allocated = 0;
    for (int i = 0; i < MAX_MEM_BLOCKS && allocated < num_blocks; i++) {
        if (!g_memory_map[i].in_use) {
            g_memory_map[i].in_use = true;
            g_memory_map[i].pid_owner = pid;
            allocated++;
        }
    }
    if (allocated == num_blocks) {
        if (pid < MAX_PROCESSES) {
            g_pcb_table[pid].allocated_bytes += (num_blocks * BLOCK_SIZE);
        }
        return true;
    }
    return false;
}

void sys_scheduler_tick(void) {
    if (g_process_count == 0) return;

    // Find next ready process in round-robin fashion
    uint32_t scanned = 0;
    while (scanned < MAX_PROCESSES) {
        g_current_pid_index = (g_current_pid_index + 1) % MAX_PROCESSES;
        scanned++;
        if (g_pcb_table[g_current_pid_index].pid != 0 &&
            g_pcb_table[g_current_pid_index].state != PROC_TERMINATED) {
            
            g_pcb_table[g_current_pid_index].state = PROC_RUNNING;
            g_pcb_table[g_current_pid_index].cpu_ticks++;
            printf("[KERNEL:C][SCHEDULER] Context switch -> PID %u ('%s') [Ticks: %u, Mem: %u KB]\n",
                   g_pcb_table[g_current_pid_index].pid,
                   g_pcb_table[g_current_pid_index].name,
                   g_pcb_table[g_current_pid_index].cpu_ticks,
                   g_pcb_table[g_current_pid_index].allocated_bytes / 1024);
            g_pcb_table[g_current_pid_index].state = PROC_READY;
            break;
        }
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

int main(int argc, char **argv) {
    printf("Starting Operator OS Subsystem Kernel...\n");
    kernel_init();

    // Spawn fundamental system daemons
    int32_t pid_gui = sys_process_create("gui_compositor", 10);
    int32_t pid_shell = sys_process_create("opshell_daemon", 8);
    int32_t pid_db = sys_process_create("sqldb_service", 9);
    int32_t pid_ovm = sys_process_create("java_runtime", 5);

    // Allocate memory pages
    sys_mem_allocate(pid_gui, 16);
    sys_mem_allocate(pid_shell, 8);
    sys_mem_allocate(pid_db, 12);
    sys_mem_allocate(pid_ovm, 24);

    // Mount core VFS filesystems
    sys_vfs_mount("/dev/null", "");
    sys_vfs_mount("/dev/kmsg", "[klog] system booted successfully\n");
    sys_vfs_mount("/etc/operator.conf", "hostname=operator-os\nversion=1.0.0\nmode=subsystem\n");
    sys_vfs_mount("/proc/cpuinfo", "model name: Operator Virtual Core (x86_64)\ncores: 4\n");

    // IPC handshake
    sys_ipc_send(pid_shell, pid_gui, "WINDOW_CREATE: title='Operator Terminal' w=800 h=500");
    sys_ipc_send(pid_db, pid_shell, "DB_STATUS: ready uri='db/operator_system.db'");

    // Simulate scheduling passes
    for (int tick = 0; tick < 8; tick++) {
        sys_scheduler_tick();
    }

    kernel_dump_diagnostics();
    return 0;
}
