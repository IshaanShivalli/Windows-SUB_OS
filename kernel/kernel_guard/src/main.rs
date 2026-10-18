//! Operator OS Rust Kernel Safety & Driver Layer
//! Manages memory page protection, hardware driver abstractions, and safe VFS journaling.

use std::collections::HashMap;
use std::time::Instant;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeviceKind {
    Display,
    Keyboard,
    NetworkInterface,
    BlockStorage,
}

#[derive(Debug, Clone)]
pub struct DeviceDriver {
    pub id: u32,
    pub name: String,
    pub kind: DeviceKind,
    pub is_active: bool,
    pub io_ops_count: u64,
}

pub struct MemorySupervisor {
    pub page_size: usize,
    pub allocated_pages: HashMap<usize, u32>, // page_id -> pid
}

impl MemorySupervisor {
    pub fn new(page_size: usize) -> Self {
        Self {
            page_size,
            allocated_pages: HashMap::new(),
        }
    }

    pub fn protect_alloc(&mut self, page_id: usize, pid: u32) -> Result<(), &'static str> {
        if self.allocated_pages.contains_key(&page_id) {
            return Err("Page fault: Memory address access violation / double allocation");
        }
        self.allocated_pages.insert(page_id, pid);
        Ok(())
    }

    pub fn release_pid(&mut self, pid: u32) -> usize {
        let before = self.allocated_pages.len();
        self.allocated_pages.retain(|_, owner| *owner != pid);
        before - self.allocated_pages.len()
    }
}

pub struct OperatorDriverBus {
    pub drivers: Vec<DeviceDriver>,
}

impl OperatorDriverBus {
    pub fn new() -> Self {
        Self { drivers: Vec::new() }
    }

    pub fn register(&mut self, name: &str, kind: DeviceKind) -> u32 {
        let id = (self.drivers.len() + 1) as u32;
        self.drivers.push(DeviceDriver {
            id,
            name: name.to_string(),
            kind,
            is_active: true,
            io_ops_count: 0,
        });
        id
    }

    pub fn trigger_io(&mut self, driver_id: u32) {
        if let Some(drv) = self.drivers.iter_mut().find(|d| d.id == driver_id) {
            drv.io_ops_count += 1;
        }
    }
}

fn main() {
    let start_time = Instant::now();
    println!("[KERNEL:Rust] Initializing Safe Hardware Layer & Memory Supervisor...");

    let mut mem_sup = MemorySupervisor::new(4096);
    let mut bus = OperatorDriverBus::new();

    // Register hardware drivers
    let d_display = bus.register("vga_compositor_drv", DeviceKind::Display);
    bus.register("ps2_keyboard_drv", DeviceKind::Keyboard);
    let d_net = bus.register("virtio_net_drv", DeviceKind::NetworkInterface);
    let d_disk = bus.register("nvme_storage_drv", DeviceKind::BlockStorage);

    println!("[KERNEL:Rust] Registered 4 Hardware Driver Interfaces.");

    // Guarded memory checks
    match mem_sup.protect_alloc(0x1000, 1) {
        Ok(_) => println!("[KERNEL:Rust] Allocated Page 0x1000 to PID 1 (Guarded)"),
        Err(e) => eprintln!("[KERNEL:Rust] Memory Error: {}", e),
    }

    match mem_sup.protect_alloc(0x1000, 2) {
        Ok(_) => println!("[KERNEL:Rust] Allocated Page 0x1000 to PID 2"),
        Err(e) => println!("[KERNEL:Rust] Handled Expected Trapped Fault: {}", e),
    }

    // Trigger driver IO
    bus.trigger_io(d_display);
    bus.trigger_io(d_net);
    bus.trigger_io(d_disk);

    println!("[KERNEL:Rust] Driver Bus Status:");
    for drv in &bus.drivers {
        println!("  - [{}] {} ({:?}): IO ops = {}", drv.id, drv.name, drv.kind, drv.io_ops_count);
    }

    println!("[KERNEL:Rust] Kernel Guard Active in {:.2?}", start_time.elapsed());
}
