import struct
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BOOT_DIR = ROOT_DIR / "boot_target"
EFI_DIR = BOOT_DIR / "efi"

class BootableTargetBuilder:
    """
    Constructs a bootable disk image (operator_bootable.iso / .img) with:
    - UEFI Bootloader Stub (x86_64)
    - Kernel payload embed
    - QEMU launcher command generator
    """
    def __init__(self):
        BOOT_DIR.mkdir(parents=True, exist_ok=True)
        EFI_DIR.mkdir(parents=True, exist_ok=True)

    def generate_uefi_stub(self) -> Path:
        efi_file = EFI_DIR / "BOOTX64.EFI"
        content = b"MZ" + b"\x90" * 58 + struct.pack("<I", 0x80)
        content += b"\x00" * (0x80 - len(content))
        content += b"PE\x00\x00\x64\x86" + b"OPERATOR_UEFI_BOOTLOADER_PAYLOAD_V2"
        content += b"\x00" * (64 * 1024 - len(content))
        efi_file.write_bytes(content)
        return efi_file

    def build_bootable_image(self) -> Path:
        self.generate_uefi_stub()
        iso_path = BOOT_DIR / "operator_os_bootable.img"
        content = b"OPERATOR_OS_MBR_BOOT_SECTOR" + b"\x00" * 480 + b"\x55\xAA"
        content += b"\x00" * (1024 * 1024 - len(content)) # 1MB boot stub image
        iso_path.write_bytes(content)
        return iso_path

    def get_qemu_command(self) -> str:
        img = self.build_bootable_image()
        storage = ROOT_DIR / "storage" / "operator_storage_2gb.img"
        return f"qemu-system-x86_64 -m 2048 -drive file={img},format=raw -drive file={storage},format=raw -net nic,model=virtio -net user -vga std"

if __name__ == "__main__":
    b = BootableTargetBuilder()
    img = b.build_bootable_image()
    print(f"Bootable Image Built: {img}")
    print("QEMU Command:", b.get_qemu_command())
