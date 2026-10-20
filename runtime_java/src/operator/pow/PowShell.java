package operator.pow;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Java command runtime for POW. Rust validates syntax; C launches the runtime. */
public final class PowShell {
    private final BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
    private final Map<String, String> variables = new HashMap<>();
    private Path cwd = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();

    public static void main(String[] args) throws Exception { new PowShell().run(); }

    private void run() throws Exception {
        variables.put("POW.RUNTIME", "Java/C/Rust");
        variables.put("POW.CWD", cwd.toString());
        while (true) {
            System.out.print("pow:operator[" + cwd.getFileName() + "] » ");
            System.out.flush();
            String line = input.readLine();
            if (line == null || line.trim().equalsIgnoreCase("exit")) return;
            try { String result = execute(line.trim()); if (!result.isBlank()) System.out.println(result); }
            catch (Exception e) { System.out.println("[pow error] " + e.getMessage()); }
        }
    }

    private String execute(String line) throws Exception {
        if (line.isBlank()) return "";
        String[] parts = line.split("\\s+", 2);
        String command = parts[0].toLowerCase(Locale.ROOT);
        String arg = parts.length > 1 ? parts[1] : "";
        if (command.equals("import")) return importCli(arg);
        if (command.equals("pipe")) return pipeline(arg);
        if (command.equals("net") || command.startsWith("net.") || command.startsWith("drive.")) return bridgeToOpshell(line);
        return local(command, arg);
    }

    private String local(String command, String arg) throws Exception {
        switch (command) {
            case "help": return "POW Java/C/Rust shell\n  import <cli> <command> | pipe <cli: command> | <cli: command>\n  pwd, ls, cd, cat, touch, grep, echo, var.get, var.set, proc.list, gpu.probe\n  Network and Drive commands bridge to opshell.";
            case "pwd": return cwd.toString();
            case "echo": return expand(arg);
            case "cd": cwd = cwd.resolve(arg).normalize(); if (!Files.isDirectory(cwd)) throw new IOException("directory not found"); variables.put("POW.CWD", cwd.toString()); return "";
            case "ls": return list(arg.isBlank() ? cwd : cwd.resolve(arg).normalize());
            case "cat": return Files.readString(cwd.resolve(arg).normalize());
            case "touch": Files.createDirectories(cwd.resolve(arg).normalize().getParent()); Files.writeString(cwd.resolve(arg).normalize(), "", StandardOpenOption.CREATE, StandardOpenOption.APPEND); return "";
            case "grep": return grep(arg);
            case "var.get": return variables.getOrDefault(arg, "");
            case "var.set": int i = arg.indexOf('='); if (i < 1) throw new IllegalArgumentException("use var.set NAME=value"); variables.put(arg.substring(0, i), arg.substring(i + 1)); return "OK";
            case "proc.list": return host("powershell", "-NoProfile", "-Command", "Get-Process | Select-Object -First 30 Name,Id");
            case "gpu.probe": return gpu();
            case "clear": case "cls": return "\u001b[2J\u001b[H";
            default: return host("cmd.exe", "/d", "/s", "/c", command + (arg.isBlank() ? "" : " " + arg));
        }
    }

    private String importCli(String arg) throws Exception {
        String[] p = arg.split("\\s+", 2); if (p.length < 2) throw new IllegalArgumentException("use import <cli> <command>");
        return runCli(p[0], p[1], "");
    }
    private String pipeline(String arg) throws Exception {
        String data = ""; for (String stage : arg.split("\\|")) { String[] p = stage.trim().split(":", 2); if (p.length != 2) throw new IllegalArgumentException("use pipe cli: command | cli: command"); data = runCli(p[0].trim(), p[1].trim(), data); } return data;
    }
    private String runCli(String cli, String command, String stdin) throws Exception {
        String c = cli.toLowerCase(Locale.ROOT);
        if (c.equals("powershell") || c.equals("pwsh")) return process(stdin, "powershell", "-NoProfile", "-NonInteractive", "-Command", command);
        if (c.equals("cmd")) return process(stdin, "cmd.exe", "/d", "/s", "/c", command);
        if (c.equals("bash")) return process(stdin, "bash", "-lc", command);
        if (c.equals("wsl")) return process(stdin, "wsl", "--", "bash", "-lc", command);
        if (c.equals("java")) return process(stdin, "java", command);
        if (c.equals("c")) return process(stdin, command);
        return process(stdin, cli, command);
    }
    private String bridgeToOpshell(String command) throws Exception { return process("", "python", "shell/opshell.py", "--bridge", command); }
    private String host(String... args) throws Exception { return process("", args); }
    private String process(String stdin, String... args) throws Exception { Process p = new ProcessBuilder(args).directory(cwd.toFile()).redirectErrorStream(true).start(); try (OutputStream out = p.getOutputStream()) { out.write(stdin.getBytes()); } return new String(p.getInputStream().readAllBytes()); }
    private String list(Path p) throws IOException { StringBuilder b = new StringBuilder(); try (DirectoryStream<Path> d = Files.newDirectoryStream(p)) { for (Path x : d) b.append(Files.isDirectory(x) ? "[DIR] " : "      ").append(x.getFileName()).append('\n'); } return b.toString(); }
    private String grep(String a) throws IOException { String[] p = a.split("\\s+", 2); if (p.length < 2) throw new IllegalArgumentException("use grep <text> <file>"); return Files.readAllLines(cwd.resolve(p[1])).stream().filter(x -> x.contains(p[0])).reduce("", (x, y) -> x + y + "\n"); }
    private String gpu() throws Exception { try { return "NVIDIA/CUDA\n" + host("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"); } catch (IOException e) { return "GPU compute runtime not available; install CUDA, ROCm, or DirectML support on the host."; } }
    private String expand(String value) { for (Map.Entry<String,String> e : variables.entrySet()) value = value.replace("${" + e.getKey() + "}", e.getValue()); return value; }
}
