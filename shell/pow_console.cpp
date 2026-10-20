// Native POW console editor: persistent history and command/path completion.
#include <conio.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <algorithm>

namespace fs = std::filesystem;

static const std::vector<std::string> kCommands = {
    "help", "pwd", "ls", "cd", "cat", "touch", "grep", "echo", "df", "free", "uname", "uptime", "wc",
    "sys.probe", "storage.inspect", "proc.list", "proc.top", "proc.start", "proc.stop", "proc.kill", "proc.info",
    "auth.login", "auth.whoami", "sec.firewall", "pkg.list", "pkg.avail", "pkg.install", "pkg.uninstall", "pkg.rollback",
    "fs.mount", "fs.list", "fs.copy", "fs.move", "fs.delete", "app.list", "app.launch", "app.close",
    "service.list", "service.start", "service.stop", "settings.list", "settings.set", "log.show", "log.clear",
    "system.health", "srv.list", "srv.start", "srv.stop", "srv.logs", "rel.restore", "rel.health", "dev.test", "dev.trace", "dev.build",
    "gpu.probe", "gpu.ai", "import", "pipe", "clear", "exit"
};

static fs::path historyPath() {
    return fs::current_path() / "storage" / "operator_os_root" / "var" / "lib" / "pow_history";
}

static std::vector<std::string> loadHistory() {
    std::vector<std::string> out; std::ifstream in(historyPath()); std::string line;
    while (std::getline(in, line)) if (!line.empty()) out.push_back(line);
    return out;
}

static void appendHistory(const std::string& line) {
    if (line.empty()) return;
    fs::create_directories(historyPath().parent_path());
    std::ofstream out(historyPath(), std::ios::app); out << line << '\n';
}

static std::string complete(const std::string& text) {
    std::vector<std::string> matches;
    for (const auto& command : kCommands)
        if (command.rfind(text, 0) == 0) matches.push_back(command);
    if (matches.size() == 1) return matches.front();
    if (matches.size() > 1) {
        std::cout << "\n"; for (const auto& m : matches) std::cout << m << "  "; std::cout << "\n";
    }
    return text;
}

static std::string readLine(std::vector<std::string>& history) {
    std::string line; size_t index = history.size();
    std::cout << "pow:operator » " << std::flush;
    for (;;) {
        int key = _getch();
        if (key == '\r') { std::cout << "\n"; return line; }
        if (key == '\t') {
            if (line.find(' ') == std::string::npos) {
                std::string replacement = complete(line);
                if (replacement != line) { std::cout << "\r\33[2Kpow:operator » " << replacement << std::flush; line = replacement; }
            }
            continue;
        }
        if (key == 0 || key == 224) {
            int arrow = _getch();
            if (arrow == 72 && index > 0) { index--; line = history[index]; }
            if (arrow == 80 && index < history.size()) { index++; line = index == history.size() ? "" : history[index]; }
            std::cout << "\r\33[2Kpow:operator » " << line << std::flush;
            continue;
        }
        if (key == '\b') { if (!line.empty()) { line.pop_back(); std::cout << "\b \b" << std::flush; } continue; }
        if (key >= 32 && key < 127) { line += static_cast<char>(key); std::cout << static_cast<char>(key) << std::flush; }
    }
}

int main() {
    auto history = loadHistory();
    std::cout << "POW native C++ console: Up/Down history, Tab completion, exit to quit.\n";
    for (;;) {
        std::string command = readLine(history);
        if (command.empty()) continue;
        appendHistory(command); history.push_back(command);
        if (command == "exit" || command == "quit") break;
        // The Java POW runtime remains the command executor. cmd.exe safely
        // hands this one command to the existing Java runtime process.
        std::string escaped = command;
        std::replace(escaped.begin(), escaped.end(), '"', '\'');
        // Parentheses are required: without them cmd.exe pipes only `exit`
        // and prints the requested POW command in the parent shell.
        std::string invoke = "(echo " + escaped + " & echo exit) | java -cp runtime_java\\bin operator.pow.PowShell";
        std::system(invoke.c_str());
    }
    return 0;
}
