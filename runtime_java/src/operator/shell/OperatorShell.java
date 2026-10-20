package operator.shell;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Persistent Java command shell for the Operator subsystem. */
public final class OperatorShell {
    private final BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
    private final Map<String, String> variables = new HashMap<>();
    private Path cwd = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();

    public static void main(String[] args) throws Exception { new OperatorShell().run(); }

    private void run() throws Exception {
        variables.put("SYS.OS", "Operator OS");
        variables.put("SYS.LANG", "Java/C");
        String line;
        while (true) {
            System.out.print("op-subsystem:operator[" + cwd.getFileName() + "] » ");
            System.out.flush();
            line = input.readLine();
            if (line == null || line.trim().equalsIgnoreCase("exit")) return;
            try { String result = execute(line.trim()); if (!result.isEmpty()) System.out.println(result); }
            catch (Exception e) { System.out.println("[shell error] " + e.getMessage()); }
        }
    }

    private String execute(String line) throws Exception {
        if (line.isEmpty()) return "";
        String[] p = line.split("\\s+", 2);
        String command = p[0].toLowerCase(Locale.ROOT);
        String arg = p.length > 1 ? p[1].trim() : "";
        switch (command) {
            case "help": return "Java/C Operator shell\n  help, pwd, ls [path], cd <path>, cat <file>, echo <text>, var.get <name>, var.set <name>=<value>, proc.list, gpu.probe, exit";
            case "pwd": return cwd.toString();
            case "echo": return expand(arg);
            case "cd": cwd = cwd.resolve(arg).normalize(); if (!Files.isDirectory(cwd)) throw new IOException("directory not found"); return "";
            case "ls": return list(arg.isEmpty() ? cwd : cwd.resolve(arg).normalize());
            case "cat": return Files.readString(cwd.resolve(arg).normalize());
            case "var.get": return variables.getOrDefault(arg, "");
            case "var.set":
                int eq = arg.indexOf('='); if (eq < 1) throw new IllegalArgumentException("use var.set NAME=value");
                variables.put(arg.substring(0, eq), arg.substring(eq + 1)); return "OK";
            case "gpu.probe": return gpuProbe();
            case "proc.list": return processList();
            default: return runHost(command, arg);
        }
    }

    private String list(Path path) throws IOException {
        StringBuilder out = new StringBuilder();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(path)) {
            for (Path entry : entries) out.append(Files.isDirectory(entry) ? "[DIR] " : "      ").append(entry.getFileName()).append('\n');
        }
        return out.toString().trim();
    }

    private String processList() throws IOException {
        Process p = new ProcessBuilder("powershell", "-NoProfile", "-Command", "Get-Process | Select-Object -First 20 Name,Id").redirectErrorStream(true).start();
        return new String(p.getInputStream().readAllBytes());
    }

    private String gpuProbe() throws IOException {
        try { Process p = new ProcessBuilder("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader").redirectErrorStream(true).start(); return "NVIDIA/CUDA\n" + new String(p.getInputStream().readAllBytes()); }
        catch (IOException ignored) { return "GPU runtime: host driver detected; CUDA/ROCm compute tool not installed"; }
    }

    private String runHost(String command, String arg) throws IOException {
        Process p = new ProcessBuilder("cmd.exe", "/d", "/s", "/c", command + (arg.isEmpty() ? "" : " " + arg)).directory(cwd.toFile()).redirectErrorStream(true).start();
        return new String(p.getInputStream().readAllBytes());
    }

    private String expand(String value) { for (Map.Entry<String,String> e : variables.entrySet()) value = value.replace("${" + e.getKey() + "}", e.getValue()); return value; }
}
