//! Operator OS Rust Kernel Safety & Driver Layer
//! Manages memory page protection, hardware driver abstractions, and safe VFS journaling.

use std::collections::HashMap;
use std::env;
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
    pub page_limit: usize,
    pub allocated_pages: HashMap<usize, u32>, // page_id -> pid
}

impl MemorySupervisor {
    pub fn new(page_size: usize, page_limit: usize) -> Result<Self, &'static str> {
        if page_size == 0 || page_limit == 0 {
            return Err("Page size and memory limit must be non-zero");
        }
        Ok(Self {
            page_size,
            page_limit,
            allocated_pages: HashMap::new(),
        })
    }

    pub fn protect_alloc(&mut self, page_id: usize, pid: u32) -> Result<(), &'static str> {
        if pid == 0 {
            return Err("Invalid process ID");
        }
        if page_id >= self.page_limit {
            return Err("Page is outside the managed memory range");
        }
        if self.allocated_pages.contains_key(&page_id) {
            return Err("Page fault: Memory address access violation / double allocation");
        }
        self.allocated_pages.insert(page_id, pid);
        Ok(())
    }

    pub fn allocate_pages(&mut self, pid: u32, count: usize) -> Result<Vec<usize>, &'static str> {
        if pid == 0 || count == 0 {
            return Err("Process ID and page count must be non-zero");
        }

        let pages: Vec<usize> = (0..self.page_limit)
            .filter(|page_id| !self.allocated_pages.contains_key(page_id))
            .take(count)
            .collect();
        if pages.len() != count {
            return Err("Insufficient free pages");
        }

        for page_id in &pages {
            self.allocated_pages.insert(*page_id, pid);
        }
        Ok(pages)
    }

    pub fn release_pid(&mut self, pid: u32) -> usize {
        let before = self.allocated_pages.len();
        self.allocated_pages.retain(|_, owner| *owner != pid);
        before - self.allocated_pages.len()
    }

    pub fn allocated_bytes(&self, pid: u32) -> Option<usize> {
        self.allocated_pages
            .values()
            .filter(|owner| **owner == pid)
            .count()
            .checked_mul(self.page_size)
    }

    pub fn free_pages(&self) -> usize {
        self.page_limit.saturating_sub(self.allocated_pages.len())
    }
}

pub struct OperatorDriverBus {
    pub drivers: Vec<DeviceDriver>,
    next_id: u32,
}

impl OperatorDriverBus {
    pub fn new() -> Self {
        Self {
            drivers: Vec::new(),
            next_id: 1,
        }
    }

    pub fn register(&mut self, name: &str, kind: DeviceKind) -> Result<u32, &'static str> {
        let normalized_name = name.trim();
        if normalized_name.is_empty() {
            return Err("Driver name cannot be empty");
        }
        if self
            .drivers
            .iter()
            .any(|driver| driver.name.eq_ignore_ascii_case(normalized_name))
        {
            return Err("A driver with this name is already registered");
        }
        let id = self.next_id;
        self.next_id = self
            .next_id
            .checked_add(1)
            .ok_or("Driver ID space exhausted")?;
        self.drivers.push(DeviceDriver {
            id,
            name: normalized_name.to_string(),
            kind,
            is_active: true,
            io_ops_count: 0,
        });
        Ok(id)
    }

    pub fn set_active(&mut self, driver_id: u32, active: bool) -> Result<(), &'static str> {
        let driver = self
            .drivers
            .iter_mut()
            .find(|driver| driver.id == driver_id)
            .ok_or("Unknown driver ID")?;
        driver.is_active = active;
        Ok(())
    }

    pub fn trigger_io(&mut self, driver_id: u32) -> Result<(), &'static str> {
        let driver = self
            .drivers
            .iter_mut()
            .find(|driver| driver.id == driver_id)
            .ok_or("Unknown driver ID")?;
        if !driver.is_active {
            return Err("Driver is inactive");
        }
        driver.io_ops_count = driver
            .io_ops_count
            .checked_add(1)
            .ok_or("Driver I/O counter exhausted")?;
        Ok(())
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("syntax") {
        let source = args.iter().skip(2).cloned().collect::<Vec<_>>().join(" ");
        let tokens: Vec<&str> = source.split_whitespace().collect();
        if tokens.is_empty() {
            eprintln!("[POW:SYNTAX] empty command");
            std::process::exit(2);
        }
        println!("[POW:SYNTAX] {}", tokens.join(" | "));
        return;
    }
    let start_time = Instant::now();
    println!("[KERNEL:Rust] Initializing Safe Hardware Layer & Memory Supervisor...");

    let mut mem_sup = MemorySupervisor::new(4096, 256).expect("valid memory configuration");
    let mut bus = OperatorDriverBus::new();

    // Register hardware drivers
    let d_display = bus
        .register("vga_compositor_drv", DeviceKind::Display)
        .expect("register display");
    bus.register("ps2_keyboard_drv", DeviceKind::Keyboard)
        .expect("register keyboard");
    let d_net = bus
        .register("virtio_net_drv", DeviceKind::NetworkInterface)
        .expect("register network");
    let d_disk = bus
        .register("nvme_storage_drv", DeviceKind::BlockStorage)
        .expect("register storage");

    println!("[KERNEL:Rust] Registered 4 Hardware Driver Interfaces.");

    match mem_sup.allocate_pages(1, 4) {
        Ok(pages) => println!(
            "[KERNEL:Rust] Allocated {} guarded pages to PID 1 ({} bytes, {} free pages)",
            pages.len(),
            mem_sup.allocated_bytes(1).unwrap_or(0),
            mem_sup.free_pages()
        ),
        Err(e) => eprintln!("[KERNEL:Rust] Memory Error: {}", e),
    }

    match mem_sup.protect_alloc(0, 2) {
        Ok(_) => println!("[KERNEL:Rust] Allocated Page 0 to PID 2"),
        Err(e) => println!("[KERNEL:Rust] Handled Expected Trapped Fault: {}", e),
    }

    // Trigger driver IO
    bus.trigger_io(d_display).expect("display I/O");
    bus.trigger_io(d_net).expect("network I/O");
    bus.trigger_io(d_disk).expect("storage I/O");

    println!("[KERNEL:Rust] Driver Bus Status:");
    for drv in &bus.drivers {
        println!(
            "  - [{}] {} ({:?}): IO ops = {}",
            drv.id, drv.name, drv.kind, drv.io_ops_count
        );
    }

    println!(
        "[KERNEL:Rust] Kernel Guard Active in {:.2?}",
        start_time.elapsed()
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_allocations_are_bounded_and_released_by_owner() {
        let mut memory = MemorySupervisor::new(4096, 3).unwrap();
        let pages = memory.allocate_pages(7, 2).unwrap();
        assert_eq!(pages, vec![0, 1]);
        assert_eq!(memory.allocated_bytes(7), Some(8192));
        assert_eq!(memory.free_pages(), 1);
        assert_eq!(memory.allocate_pages(8, 2), Err("Insufficient free pages"));
        assert_eq!(memory.allocated_bytes(8), Some(0));
        assert_eq!(memory.release_pid(7), 2);
        assert_eq!(memory.free_pages(), 3);
    }

    #[test]
    fn memory_protection_rejects_invalid_and_duplicate_pages() {
        let mut memory = MemorySupervisor::new(4096, 2).unwrap();
        assert_eq!(memory.protect_alloc(0, 0), Err("Invalid process ID"));
        assert_eq!(
            memory.protect_alloc(2, 1),
            Err("Page is outside the managed memory range")
        );
        memory.protect_alloc(1, 1).unwrap();
        assert!(memory.protect_alloc(1, 2).is_err());
    }

    #[test]
    fn memory_supervisor_rejects_zero_sized_configuration() {
        assert!(MemorySupervisor::new(0, 2).is_err());
        assert!(MemorySupervisor::new(4096, 0).is_err());
    }

    #[test]
    fn driver_bus_validates_registration_and_counts_only_active_io() {
        let mut bus = OperatorDriverBus::new();
        let id = bus.register("display", DeviceKind::Display).unwrap();
        assert_eq!(
            bus.register(" DISPLAY ", DeviceKind::Display),
            Err("A driver with this name is already registered")
        );
        assert_eq!(
            bus.register(" ", DeviceKind::Display),
            Err("Driver name cannot be empty")
        );
        bus.trigger_io(id).unwrap();
        bus.set_active(id, false).unwrap();
        assert_eq!(bus.trigger_io(id), Err("Driver is inactive"));
        assert_eq!(bus.drivers[0].io_ops_count, 1);
        bus.set_active(id, true).unwrap();
        bus.trigger_io(id).unwrap();
        assert_eq!(bus.drivers[0].io_ops_count, 2);
        assert_eq!(bus.trigger_io(u32::MAX), Err("Unknown driver ID"));
    }
}
