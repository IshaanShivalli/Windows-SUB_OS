import socket
import urllib.request
import json
import time

class OperatorNetworkStack:
    """
    Subsystem Network Stack providing:
    - Network interface enumeration (loopback, eth0, virtio)
    - DNS resolution & host query
    - ICMP-like TCP Ping latency probe
    - Socket port scanning
    - HTTP/HTTPS client fetching
    - Virtual routing table
    """
    def __init__(self):
        self.interfaces = [
            {"name": "lo0", "ip": "127.0.0.1", "mask": "255.0.0.0", "mac": "00:00:00:00:00:00", "state": "UP"},
            {"name": "op_eth0", "ip": "192.168.100.15", "mask": "255.255.255.0", "mac": "52:54:00:12:34:56", "state": "UP"},
            {"name": "virtio_net", "ip": "10.0.2.15", "mask": "255.255.255.0", "mac": "52:54:00:ab:cd:ef", "state": "UP"},
        ]
        self.routes = [
            {"destination": "0.0.0.0/0", "gateway": "192.168.100.1", "iface": "op_eth0", "metric": 10},
            {"destination": "127.0.0.0/8", "gateway": "0.0.0.0", "iface": "lo0", "metric": 1},
            {"destination": "10.0.2.0/24", "gateway": "0.0.0.0", "iface": "virtio_net", "metric": 20},
        ]
        self.dns_servers = ["1.1.1.1", "8.8.8.8"]

    def ifconfig(self):
        return self.interfaces

    def route_table(self):
        return self.routes

    def dns_lookup(self, host: str):
        try:
            ip = socket.gethostbyname(host)
            return {"host": host, "resolved_ip": ip, "status": "SUCCESS"}
        except Exception as e:
            return {"host": host, "error": str(e), "status": "FAILED"}

    def ping(self, host: str, port: int = 80, timeout: float = 2.0):
        t0 = time.time()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            s.close()
            latency = (time.time() - t0) * 1000
            return {"host": host, "port": port, "latency_ms": round(latency, 2), "status": "ONLINE"}
        except Exception as e:
            return {"host": host, "port": port, "error": str(e), "status": "OFFLINE"}

    def http_fetch(self, url: str):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OperatorOS-NetStack/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                headers = dict(resp.getheaders())
                body = resp.read(2048).decode("utf-8", errors="ignore")
                return {"url": url, "status_code": status, "headers": headers, "preview": body}
        except Exception as e:
            return {"url": url, "error": str(e)}

if __name__ == "__main__":
    net = OperatorNetworkStack()
    print("Interfaces:", net.ifconfig())
    print("DNS Lookup google.com:", net.dns_lookup("google.com"))
    print("Ping google.com:80:", net.ping("google.com", 80))
