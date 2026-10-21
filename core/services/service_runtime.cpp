#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using JobCallback = void (*)(const char*, const char*, const char*, char*, size_t);

static std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (unsigned char ch : value) {
        switch (ch) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (ch < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                    << static_cast<int>(ch) << std::dec;
            } else {
                out << static_cast<char>(ch);
            }
        }
    }
    return out.str();
}

static std::string json_quote(const std::string& value) {
    return "\"" + json_escape(value) + "\"";
}

static bool valid_name(const std::string& name) {
    return !name.empty() && name.size() <= 96 &&
        std::all_of(name.begin(), name.end(), [](unsigned char ch) {
            return std::isalnum(ch) || ch == '_' || ch == '-' || ch == '.';
        });
}

static std::wstring widen(const std::string& value) {
    if (value.empty()) return {};
    int count = MultiByteToWideChar(CP_UTF8, 0, value.c_str(), -1, nullptr, 0);
    std::wstring result(static_cast<size_t>(count), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.c_str(), -1, result.data(), count);
    result.pop_back();
    return result;
}

struct Service {
    std::string name;
    std::string description;
    std::string command;
    std::string policy;
    std::string health_check;
    std::string state = "inactive";
    std::string health = "stopped";
    std::string last_error;
    DWORD pid = 0;
    unsigned restart_count = 0;
    bool desired_running = false;
    HANDLE process = nullptr;
    HANDLE process_job = nullptr;
    std::thread monitor;
    std::mutex mutex;
    std::condition_variable changed;
};

struct ScheduledJob {
    std::string name;
    std::string owner;
    uint64_t interval_seconds = 0;
    std::string command;
    std::chrono::system_clock::time_point next_run;
    bool running = false;
};

class Runtime {
public:
    Runtime(const std::string& root, JobCallback callback)
        : state_dir_(widen(root)), callback_(callback) {
        WSADATA data{};
        int socket_status = WSAStartup(MAKEWORD(2, 2), &data);
        if (socket_status != 0) {
            throw std::runtime_error("WSAStartup failed with code " + std::to_string(socket_status));
        }
        std::filesystem::create_directories(state_dir_);
        std::filesystem::create_directories(state_dir_ / L"logs");
        load_services();
        load_jobs();
        start_persisted_services();
        scheduler_ = std::thread(&Runtime::scheduler_loop, this);
    }

    ~Runtime() {
        try {
            {
                std::lock_guard<std::mutex> guard(mutex_);
                stopping_ = true;
            }
            changed_.notify_all();
            if (scheduler_.joinable()) scheduler_.join();

            std::vector<std::string> names;
            {
                std::lock_guard<std::mutex> guard(mutex_);
                for (const auto& entry : services_) names.push_back(entry.first);
            }
            for (const auto& name : names) stop_service(name);
            for (auto& entry : services_) {
                if (entry.second->monitor.joinable()) entry.second->monitor.join();
            }
        } catch (...) {
            OutputDebugStringA("Atlas service runtime shutdown failed.\n");
        }
        WSACleanup();
    }

    std::string register_service(
        const std::string& name, const std::string& description, const std::string& command,
        const std::string& policy, const std::string& health_check) {
        if (!valid_name(name)) return "[SRV ERROR] Invalid service name.";
        if (command.empty()) return "[SRV ERROR] Service command cannot be empty.";
        if (policy != "no" && policy != "on-failure" && policy != "always") {
            return "[SRV ERROR] Restart policy must be no, on-failure, or always.";
        }
        if (!validate_health_check(health_check)) {
            return "[SRV ERROR] Health check must be 'process' or 'tcp:<host>:<port>'.";
        }
        std::lock_guard<std::mutex> guard(mutex_);
        auto existing = services_.find(name);
        if (existing != services_.end()) {
            std::lock_guard<std::mutex> service_guard(existing->second->mutex);
            if (existing->second->desired_running) {
                return "[SRV ERROR] Stop service before changing its definition.";
            }
        }
        auto service = std::make_shared<Service>();
        service->name = name;
        service->description = description.empty() ? name : description;
        service->command = command;
        service->policy = policy;
        service->health_check = health_check;
        services_[name] = service;
        persist_services_locked();
        log("service", name, "Registered command: " + command);
        return "[SRV REGISTERED] " + name + " (" + policy + ")";
    }

    std::string start_service(const std::string& name) {
        std::shared_ptr<Service> service = find_service(name);
        if (!service) return "[SRV ERROR] Unknown service.";
        {
            std::lock_guard<std::mutex> guard(service->mutex);
            if (service->desired_running) return "[SRV ACTIVE] " + name + " is already supervised.";
        }
        if (service->monitor.joinable()) service->monitor.join();
        {
            std::lock_guard<std::mutex> guard(service->mutex);
            service->desired_running = true;
            service->state = "starting";
            service->health = "starting";
            service->restart_count = 0;
            service->last_error.clear();
            service->monitor = std::thread(&Runtime::monitor_service, this, service);
        }
        return "[SRV STARTING] Supervisor started for " + name + ".";
    }

    std::string stop_service(const std::string& name) {
        std::shared_ptr<Service> service = find_service(name);
        if (!service) return "[SRV ERROR] Unknown service.";
        bool stop_failed = false;
        {
            std::lock_guard<std::mutex> guard(service->mutex);
            service->desired_running = false;
            if (service->process && WaitForSingleObject(service->process, 0) == WAIT_TIMEOUT) {
                BOOL terminated = FALSE;
                if (service->process_job) {
                    terminated = TerminateJobObject(service->process_job, 1);
                } else {
                    terminated = TerminateProcess(service->process, 1);
                }
                if (!terminated) {
                    TerminateProcess(service->process, 1);
                }
                if (WaitForSingleObject(service->process, 5000) != WAIT_OBJECT_0) {
                    TerminateProcess(service->process, 1);
                    stop_failed = WaitForSingleObject(service->process, 5000) != WAIT_OBJECT_0;
                }
            }
        }
        service->changed.notify_all();
        if (service->monitor.joinable() &&
            service->monitor.get_id() != std::this_thread::get_id()) {
            service->monitor.join();
        }
        {
            std::lock_guard<std::mutex> guard(service->mutex);
            close_process_handles(*service);
            service->pid = 0;
            service->state = "inactive";
            service->health = "stopped";
        }
        log("service", name, "Stopped by operator");
        if (stop_failed) return "[SRV ERROR] Process did not exit after termination: " + name;
        return "[SRV STOPPED] Stopped " + name + ".";
    }

    std::string remove_service(const std::string& name) {
        auto result = stop_service(name);
        if (result.rfind("[SRV ERROR]", 0) == 0) return result;
        std::lock_guard<std::mutex> guard(mutex_);
        services_.erase(name);
        persist_services_locked();
        return "[SRV REMOVED] " + name;
    }

    std::string list_services() {
        std::ostringstream out;
        out << "[";
        bool first = true;
        std::lock_guard<std::mutex> guard(mutex_);
        for (const auto& entry : services_) {
            auto& service = *entry.second;
            std::lock_guard<std::mutex> service_guard(service.mutex);
            if (!first) out << ",";
            first = false;
            out << "{\"unit\":" << json_quote(service.name)
                << ",\"description\":" << json_quote(service.description)
                << ",\"active\":" << json_quote(service.state)
                << ",\"sub\":" << json_quote(service.health)
                << ",\"pid\":" << service.pid
                << ",\"restart\":" << json_quote(service.policy)
                << ",\"restart_count\":" << service.restart_count
                << ",\"error\":" << json_quote(service.last_error) << "}";
        }
        out << "]";
        return out.str();
    }

    std::string service_logs(const std::string& name, size_t limit) {
        if (!valid_name(name)) return "[]";
        return read_log("service", name, limit);
    }

    std::string add_job(
        const std::string& name, const std::string& owner,
        const std::string& interval, const std::string& command) {
        if (!valid_name(name)) return "[CRON ERROR] Invalid job name.";
        if (!valid_name(owner)) return "[CRON ERROR] Invalid Atlas username.";
        if (command.empty()) return "[CRON ERROR] Job command cannot be empty.";
        uint64_t seconds = 0;
        try {
            size_t consumed = 0;
            seconds = std::stoull(interval, &consumed);
            if (consumed != interval.size() || seconds < 10 || seconds > 31536000) {
                return "[CRON ERROR] Interval must be 10 seconds to 365 days.";
            }
        } catch (...) {
            return "[CRON ERROR] Interval must be an integer number of seconds.";
        }
        std::lock_guard<std::mutex> guard(mutex_);
        ScheduledJob job;
        job.name = name;
        job.owner = owner;
        job.interval_seconds = seconds;
        job.command = command;
        job.next_run = std::chrono::system_clock::now() + std::chrono::seconds(seconds);
        jobs_[name] = job;
        persist_jobs_locked();
        log("job", name, "Scheduled every " + std::to_string(seconds) + " seconds: " + command);
        changed_.notify_all();
        return "[CRON ADDED] " + name + " will run every " + std::to_string(seconds) + " seconds.";
    }

    std::string remove_job(const std::string& name) {
        std::lock_guard<std::mutex> guard(mutex_);
        if (jobs_.erase(name) == 0) return "[CRON ERROR] Unknown job.";
        persist_jobs_locked();
        log("job", name, "Removed");
        return "[CRON REMOVED] " + name;
    }

    std::string list_jobs() {
        std::ostringstream out;
        out << "[";
        bool first = true;
        std::lock_guard<std::mutex> guard(mutex_);
        for (const auto& entry : jobs_) {
            const auto& job = entry.second;
            if (!first) out << ",";
            first = false;
            auto next = std::chrono::system_clock::to_time_t(job.next_run);
            std::tm local_time{};
            localtime_s(&local_time, &next);
            char buffer[32]{};
            std::strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &local_time);
            out << "{\"name\":" << json_quote(job.name)
                << ",\"owner\":" << json_quote(job.owner)
                << ",\"interval_seconds\":" << job.interval_seconds
                << ",\"command\":" << json_quote(job.command)
                << ",\"next_run\":" << json_quote(buffer)
                << ",\"running\":" << (job.running ? "true" : "false") << "}";
        }
        out << "]";
        return out.str();
    }

    std::string job_logs(const std::string& name, size_t limit) {
        if (!valid_name(name)) return "[]";
        return read_log("job", name, limit);
    }

private:
    std::filesystem::path state_dir_;
    JobCallback callback_ = nullptr;
    std::mutex mutex_;
    std::mutex log_mutex_;
    std::condition_variable changed_;
    bool stopping_ = false;
    std::map<std::string, std::shared_ptr<Service>> services_;
    std::map<std::string, ScheduledJob> jobs_;
    std::thread scheduler_;

    std::shared_ptr<Service> find_service(const std::string& name) {
        std::lock_guard<std::mutex> guard(mutex_);
        auto it = services_.find(name);
        return it == services_.end() ? nullptr : it->second;
    }

    static bool validate_health_check(const std::string& health) {
        if (health.empty() || health == "process") return true;
        if (health.rfind("tcp:", 0) != 0) return false;
        auto sep = health.rfind(':');
        if (sep <= 4) return false;
        try {
            int port = std::stoi(health.substr(sep + 1));
            return port >= 1 && port <= 65535;
        } catch (...) {
            return false;
        }
    }

    std::filesystem::path config_path(const wchar_t* file) {
        return state_dir_ / file;
    }

    void load_services() {
        std::ifstream in(config_path(L"services.cfg"));
        std::string name, description, command, policy, health;
        while (in >> std::quoted(name) >> std::quoted(description) >> std::quoted(command)
                  >> std::quoted(policy) >> std::quoted(health)) {
            if (!valid_name(name) || command.empty()) continue;
            auto service = std::make_shared<Service>();
            service->name = name;
            service->description = description;
            service->command = command;
            service->policy = policy;
            service->health_check = health;
            services_[name] = service;
        }
    }

    void start_persisted_services() {
        std::vector<std::string> names;
        names.reserve(services_.size());
        for (const auto& entry : services_) names.push_back(entry.first);
        for (const auto& name : names) {
            const std::string result = start_service(name);
            if (result.rfind("[SRV ERROR]", 0) == 0) {
                log("service", name, "Automatic startup failed: " + result);
            }
        }
    }

    void persist_services_locked() {
        std::ofstream out(config_path(L"services.cfg"), std::ios::trunc);
        if (!out) throw std::runtime_error("Could not persist service definitions.");
        for (const auto& entry : services_) {
            const auto& s = *entry.second;
            out << std::quoted(s.name) << ' ' << std::quoted(s.description) << ' '
                << std::quoted(s.command) << ' ' << std::quoted(s.policy) << ' '
                << std::quoted(s.health_check) << '\n';
        }
        if (!out) throw std::runtime_error("Failed writing service definitions.");
    }

    void load_jobs() {
        std::ifstream in(config_path(L"jobs.cfg"));
        std::string name, owner, command;
        uint64_t interval = 0;
        int64_t next_epoch = 0;
        while (in >> std::quoted(name) >> std::quoted(owner) >> interval >> next_epoch >> std::quoted(command)) {
            if (!valid_name(name) || !valid_name(owner) || interval < 10 || command.empty()) continue;
            ScheduledJob job;
            job.name = name;
            job.owner = owner;
            job.interval_seconds = interval;
            job.command = command;
            job.next_run = std::chrono::system_clock::from_time_t(next_epoch);
            jobs_[name] = job;
        }
    }

    void persist_jobs_locked() {
        std::ofstream out(config_path(L"jobs.cfg"), std::ios::trunc);
        if (!out) throw std::runtime_error("Could not persist scheduled jobs.");
        for (const auto& entry : jobs_) {
            const auto& job = entry.second;
            auto next_epoch = std::chrono::system_clock::to_time_t(job.next_run);
            out << std::quoted(job.name) << ' ' << std::quoted(job.owner) << ' ' << job.interval_seconds << ' '
                << next_epoch << ' ' << std::quoted(job.command) << '\n';
        }
        if (!out) throw std::runtime_error("Failed writing scheduled jobs.");
    }

    void log(const std::string& group, const std::string& name, const std::string& message) {
        if (!valid_name(name)) return;
        std::lock_guard<std::mutex> guard(log_mutex_);
        std::filesystem::path file = state_dir_ / L"logs" / widen(group) / (widen(name) + L".log");
        std::filesystem::create_directories(file.parent_path());
        rotate_log(file);
        std::ofstream out(file, std::ios::app);
        if (!out) throw std::runtime_error("Could not open persistent runtime log.");
        auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        std::tm local_time{};
        localtime_s(&local_time, &now);
        char buffer[32]{};
        std::strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &local_time);
        out << "[" << buffer << "] " << message << '\n';
    }

    static void rotate_log(const std::filesystem::path& file) {
        constexpr uintmax_t max_bytes = 5 * 1024 * 1024;
        std::error_code error;
        if (!std::filesystem::exists(file, error) ||
            std::filesystem::file_size(file, error) < max_bytes || error) return;
        auto first_backup = file;
        first_backup += L".1";
        auto second_backup = file;
        second_backup += L".2";
        std::filesystem::remove(second_backup, error);
        error.clear();
        if (std::filesystem::exists(first_backup, error) && !error) {
            std::filesystem::rename(first_backup, second_backup, error);
            error.clear();
        }
        std::filesystem::rename(file, first_backup, error);
        if (error) throw std::runtime_error("Could not rotate log file.");
    }

    std::string read_log(const std::string& group, const std::string& name, size_t limit) {
        std::filesystem::path file = state_dir_ / L"logs" / widen(group) / (widen(name) + L".log");
        std::lock_guard<std::mutex> guard(log_mutex_);
        std::ifstream in(file);
        std::vector<std::string> lines;
        std::string line;
        while (std::getline(in, line)) lines.push_back(line);
        if (limit == 0 || limit > 1000) limit = 100;
        if (lines.size() > limit) lines.erase(lines.begin(), lines.end() - static_cast<std::ptrdiff_t>(limit));
        std::ostringstream out;
        out << "[";
        for (size_t i = 0; i < lines.size(); ++i) {
            if (i) out << ",";
            out << json_quote(lines[i]);
        }
        out << "]";
        return out.str();
    }

    bool spawn_service(Service& service) {
        std::wstring command_line = widen(service.command);
        if (command_line.empty()) return false;
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        std::filesystem::path log_file = state_dir_ / L"logs" / L"service" / (widen(service.name) + L".log");
        std::filesystem::create_directories(log_file.parent_path());
        rotate_log(log_file);
        SECURITY_ATTRIBUTES security{};
        security.nLength = sizeof(security);
        security.bInheritHandle = TRUE;
        HANDLE output = CreateFileW(
            log_file.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (output == INVALID_HANDLE_VALUE) {
            service.last_error = "Could not open service log file";
            return false;
        }
        startup.hStdOutput = output;
        startup.hStdError = output;
        startup.hStdInput = CreateFileW(
            L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (startup.hStdInput == INVALID_HANDLE_VALUE) {
            startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        }
        PROCESS_INFORMATION info{};
        std::wstring cwd = state_dir_.parent_path().parent_path().parent_path().wstring();
        BOOL created = CreateProcessW(
            nullptr, command_line.data(), nullptr, nullptr, TRUE,
            CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, nullptr, cwd.c_str(), &startup, &info);
        CloseHandle(output);
        if (startup.hStdInput && startup.hStdInput != INVALID_HANDLE_VALUE &&
            startup.hStdInput != GetStdHandle(STD_INPUT_HANDLE)) {
            CloseHandle(startup.hStdInput);
        }
        if (!created) {
            service.last_error = "CreateProcess failed with Windows error " + std::to_string(GetLastError());
            return false;
        }
        HANDLE job = CreateJobObjectW(nullptr, nullptr);
        if (job) {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
            AssignProcessToJobObject(job, info.hProcess);
        }
        CloseHandle(info.hThread);
        service.process = info.hProcess;
        service.process_job = job;
        service.pid = info.dwProcessId;
        service.state = "active";
        service.health = service.health_check.empty() || service.health_check == "process"
            ? "healthy" : "starting";
        service.last_error.clear();
        log("service", service.name, "Started PID " + std::to_string(service.pid));
        return true;
    }

    static void close_process_handles(Service& service) {
        if (service.process) {
            CloseHandle(service.process);
            service.process = nullptr;
        }
        if (service.process_job) {
            CloseHandle(service.process_job);
            service.process_job = nullptr;
        }
    }

    bool check_health(const Service& service) {
        if (service.health_check.empty() || service.health_check == "process") return true;
        auto sep = service.health_check.rfind(':');
        std::string host = service.health_check.substr(4, sep - 4);
        std::string port = service.health_check.substr(sep + 1);
        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        addrinfo* results = nullptr;
        if (getaddrinfo(host.c_str(), port.c_str(), &hints, &results) != 0) return false;
        bool healthy = false;
        for (addrinfo* item = results; item && !healthy; item = item->ai_next) {
            SOCKET connection = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
            if (connection == INVALID_SOCKET) continue;
            u_long nonblocking = 1;
            if (ioctlsocket(connection, FIONBIO, &nonblocking) == 0) {
                int status = connect(connection, item->ai_addr, static_cast<int>(item->ai_addrlen));
                if (status == 0) {
                    healthy = true;
                } else if (WSAGetLastError() == WSAEWOULDBLOCK ||
                           WSAGetLastError() == WSAEINPROGRESS ||
                           WSAGetLastError() == WSAEINVAL) {
                    fd_set writable;
                    FD_ZERO(&writable);
                    FD_SET(connection, &writable);
                    timeval timeout{1, 0};
                    if (select(0, nullptr, &writable, nullptr, &timeout) > 0) {
                        int socket_error = 0;
                        int error_size = sizeof(socket_error);
                        if (getsockopt(
                                connection, SOL_SOCKET, SO_ERROR,
                                reinterpret_cast<char*>(&socket_error), &error_size) == 0 &&
                            socket_error == 0) {
                            healthy = true;
                        }
                    }
                }
            }
            closesocket(connection);
        }
        freeaddrinfo(results);
        return healthy;
    }

    void monitor_service(const std::shared_ptr<Service>& service) {
        try {
            monitor_service_impl(service);
        } catch (const std::exception& error) {
            std::lock_guard<std::mutex> guard(service->mutex);
            service->last_error = std::string("Supervisor error: ") + error.what();
            service->desired_running = false;
            service->state = "failed";
            service->health = "failed";
            if (service->process && WaitForSingleObject(service->process, 0) == WAIT_TIMEOUT) {
                if (service->process_job) TerminateJobObject(service->process_job, 1);
                else TerminateProcess(service->process, 1);
                WaitForSingleObject(service->process, 5000);
            }
            close_process_handles(*service);
            service->pid = 0;
            OutputDebugStringA(service->last_error.c_str());
        } catch (...) {
            OutputDebugStringA("Atlas service supervisor failed unexpectedly.\n");
        }
    }

    void monitor_service_impl(const std::shared_ptr<Service>& service) {
        unsigned backoff = 1;
        auto unhealthy_since = std::chrono::steady_clock::time_point{};
        for (;;) {
            {
                std::lock_guard<std::mutex> guard(service->mutex);
                if (!service->desired_running) break;
                if (!spawn_service(*service)) {
                    service->state = "failed";
                    service->health = "failed";
                }
            }
            if (!service->process) {
                if (service->policy == "no") break;
                std::unique_lock<std::mutex> guard(service->mutex);
                if (service->changed.wait_for(guard, std::chrono::seconds(backoff), [&] {
                    return !service->desired_running;
                })) break;
                ++service->restart_count;
                backoff = std::min(backoff * 2, 30u);
                continue;
            }

            bool restart = false;
            while (true) {
                {
                    std::unique_lock<std::mutex> guard(service->mutex);
                    if (service->changed.wait_for(guard, std::chrono::seconds(1), [&] {
                        return !service->desired_running;
                    })) break;
                    if (!service->process ||
                        WaitForSingleObject(service->process, 0) != WAIT_TIMEOUT) {
                        DWORD code = 0;
                        if (service->process) GetExitCodeProcess(service->process, &code);
                        service->state = code == 0 ? "inactive" : "failed";
                        service->health = code == 0 ? "stopped" : "failed";
                        service->pid = 0;
                        log("service", service->name, "Process exited with code " + std::to_string(code));
                        restart = service->policy == "always" ||
                            (service->policy == "on-failure" && code != 0);
                        close_process_handles(*service);
                        break;
                    }
                }
                bool healthy = check_health(*service);
                auto now = std::chrono::steady_clock::now();
                std::lock_guard<std::mutex> guard(service->mutex);
                if (healthy) {
                    service->health = "healthy";
                    unhealthy_since = {};
                    backoff = 1;
                } else {
                    service->health = "unhealthy";
                    if (unhealthy_since.time_since_epoch().count() == 0) unhealthy_since = now;
                    if (now - unhealthy_since >= std::chrono::seconds(15)) {
                        service->last_error = "Health check failed for 15 seconds";
                        log("service", service->name, service->last_error);
                        if (service->process_job) TerminateJobObject(service->process_job, 1);
                        else if (service->process) TerminateProcess(service->process, 1);
                        if (service->process) WaitForSingleObject(service->process, 5000);
                        close_process_handles(*service);
                        service->pid = 0;
                        restart = service->policy != "no";
                        break;
                    }
                }
            }

            {
                std::unique_lock<std::mutex> guard(service->mutex);
                if (!service->desired_running) {
                    close_process_handles(*service);
                    service->pid = 0;
                    service->state = "inactive";
                    service->health = "stopped";
                    break;
                }
                if (!restart) break;
                ++service->restart_count;
                log("service", service->name, "Restarting in " + std::to_string(backoff) + " seconds");
                if (service->changed.wait_for(guard, std::chrono::seconds(backoff), [&] {
                    return !service->desired_running;
                })) break;
                backoff = std::min(backoff * 2, 30u);
            }
        }
        std::lock_guard<std::mutex> guard(service->mutex);
        if (!service->desired_running) {
            close_process_handles(*service);
            service->pid = 0;
            service->state = "inactive";
            service->health = "stopped";
        } else {
            service->desired_running = false;
        }
    }

    void scheduler_loop() {
        try {
            scheduler_loop_impl();
        } catch (const std::exception& error) {
            OutputDebugStringA(error.what());
            OutputDebugStringA("\n");
        } catch (...) {
            OutputDebugStringA("Atlas scheduler failed unexpectedly.\n");
        }
    }

    void scheduler_loop_impl() {
        while (true) {
            struct DueJob { std::string name; std::string owner; std::string command; };
            std::vector<DueJob> due;
            {
                std::unique_lock<std::mutex> guard(mutex_);
                if (changed_.wait_for(guard, std::chrono::seconds(1), [&] { return stopping_; })) break;
                auto now = std::chrono::system_clock::now();
                for (auto& entry : jobs_) {
                    auto& job = entry.second;
                    if (!job.running && job.next_run <= now) {
                        job.running = true;
                        due.push_back({job.name, job.owner, job.command});
                        job.next_run = now + std::chrono::seconds(job.interval_seconds);
                    }
                }
                if (!due.empty()) persist_jobs_locked();
            }
            for (const auto& item : due) {
                char output[4096]{};
                if (callback_) {
                    callback_(item.name.c_str(), item.owner.c_str(), item.command.c_str(), output, sizeof(output));
                } else {
                    strcpy_s(output, "No scheduled-job handler is configured.");
                }
                log("job", item.name, output);
                std::lock_guard<std::mutex> guard(mutex_);
                auto it = jobs_.find(item.name);
                if (it != jobs_.end()) it->second.running = false;
            }
        }
    }
};

static std::string from_utf8(const char* text) {
    return text ? std::string(text) : std::string();
}

static size_t parse_limit(const char* text) {
    if (!text) return 100;
    try {
        auto value = std::stoul(text);
        return std::clamp<size_t>(value, 1, 1000);
    } catch (...) {
        return 100;
    }
}

static thread_local std::string result_buffer;

extern "C" {
__declspec(dllexport) void* atlas_runtime_create(const char* state_dir, JobCallback callback) {
    try {
        return new Runtime(from_utf8(state_dir), callback);
    } catch (...) {
        return nullptr;
    }
}

__declspec(dllexport) void atlas_runtime_destroy(void* handle) {
    delete static_cast<Runtime*>(handle);
}

#define ATLAS_CALL(handle, expression) \
    try { result_buffer = static_cast<Runtime*>(handle)->expression; } \
    catch (const std::exception& error) { result_buffer = std::string("[ERROR] ") + error.what(); } \
    catch (...) { result_buffer = "[ERROR] Unexpected native runtime failure."; } \
    return result_buffer.c_str()

__declspec(dllexport) const char* atlas_service_register(
    void* handle, const char* name, const char* description, const char* command,
    const char* policy, const char* health) {
    ATLAS_CALL(handle, register_service(from_utf8(name), from_utf8(description), from_utf8(command), from_utf8(policy), from_utf8(health)));
}
__declspec(dllexport) const char* atlas_service_start(void* handle, const char* name) {
    ATLAS_CALL(handle, start_service(from_utf8(name)));
}
__declspec(dllexport) const char* atlas_service_stop(void* handle, const char* name) {
    ATLAS_CALL(handle, stop_service(from_utf8(name)));
}
__declspec(dllexport) const char* atlas_service_remove(void* handle, const char* name) {
    ATLAS_CALL(handle, remove_service(from_utf8(name)));
}
__declspec(dllexport) const char* atlas_service_list(void* handle) {
    ATLAS_CALL(handle, list_services());
}
__declspec(dllexport) const char* atlas_service_logs(void* handle, const char* name, const char* limit) {
    ATLAS_CALL(handle, service_logs(from_utf8(name), parse_limit(limit)));
}
__declspec(dllexport) const char* atlas_job_add(void* handle, const char* name, const char* owner, const char* interval, const char* command) {
    ATLAS_CALL(handle, add_job(from_utf8(name), from_utf8(owner), from_utf8(interval), from_utf8(command)));
}
__declspec(dllexport) const char* atlas_job_remove(void* handle, const char* name) {
    ATLAS_CALL(handle, remove_job(from_utf8(name)));
}
__declspec(dllexport) const char* atlas_job_list(void* handle) {
    ATLAS_CALL(handle, list_jobs());
}
__declspec(dllexport) const char* atlas_job_logs(void* handle, const char* name, const char* limit) {
    ATLAS_CALL(handle, job_logs(from_utf8(name), parse_limit(limit)));
}
}
